import asyncio
import base64
import json

import httpx
import pytest

from app.artifacts import read_artifact
from app.engine.graph import validate_graph
from app.nodes.media import VideoNode
from app.schemas import Graph, Node
from fastapi.testclient import TestClient
from collections.abc import Callable

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a5S8AAAAASUVORK5CYII=")


def graph(*nodes):
    items = [{"id": "start", "type": "start", "data": {"fields": "topic"}}, *nodes, {"id": "end", "type": "end", "data": {}}]
    return {"nodes": items, "edges": [{"id": str(i), "source": a["id"], "target": b["id"]} for i, (a, b) in enumerate(zip(items, items[1:]))]}


def run_workflow(client, graph):
    workflow = client.post("/api/workflows", json={"name": "多模态测试", "graph": graph}).json()
    response = client.post("/api/workflows/runs", json={"id": workflow["id"], "inputs": {"topic": "你好"}})
    assert response.status_code == 201, response.text
    id = response.json()["id"]
    stream = client.post("/api/runs/events", json={"id": id})
    events = [json.loads(line[6:]) for line in stream.text.splitlines() if line.startswith("data: ")]
    return client.post("/api/runs/get", json={"id": id}).json(), events


@pytest.fixture
def upstream(client, monkeypatch):
    client.post("/api/provider/save", json={"provider": "minimax", "base_url": "https://example.com/v1", "api_key": "media-test-key"})
    real = httpx.AsyncClient

    def install(handler):
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return install


def test_speech_to_asr_to_template_runs_in_order(client, upstream):
    called = []

    def handler(request):
        called.append(request.url.path)
        if request.url.path.endswith("t2a_v2"):
            assert json.loads(request.content)["text"] == "你好"
            return httpx.Response(200, json={"data": {"audio": b"ID3-speech".hex()}, "base_resp": {"status_code": 0}})
        assert request.url.path.endswith("speech_to_text")
        assert b"ID3-speech" in request.content
        return httpx.Response(200, json={"text": "识别后的你好", "duration": 2})
    upstream(handler)
    run, events = run_workflow(client, graph(
        {"id": "speech", "type": "speech", "data": {"prompt": "{{start.topic}}"}},
        {"id": "asr", "type": "asr", "data": {"audio_url": "{{speech.url}}"}},
        {"id": "summary", "type": "template", "data": {"template": "识别结果：{{asr.output}}"}},
    ))
    assert run["status"] == "succeeded", run["error"]
    assert run["outputs"]["summary"] == "识别结果：识别后的你好"
    assert called == ["/v1/t2a_v2", "/v1/speech_to_text"]
    assert [e["data"]["node_id"] for e in events if e["type"] == "node_finished"] == ["start", "speech", "asr", "summary", "end"]


def test_connected_voice_and_speed_variables_remain_usable(
    client: TestClient, upstream: Callable,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body['voice_setting']['voice_id'] == 'voice-from-upstream'
        assert body['voice_setting']['speed'] == 1.25
        return httpx.Response(200, json={'data': {'audio': b'ID3speech'.hex()}})

    upstream(handler)
    run, events = run_workflow(client, graph(
        {'id': 'voice', 'type': 'template', 'data': {'template': 'voice-from-upstream'}},
        {'id': 'speed', 'type': 'template', 'data': {'template': '1.25'}},
        {'id': 'speech', 'type': 'speech', 'data': {
            'prompt': '{{start.topic}}', 'voice_id': '{{voice.output}}', 'speed': '{{speed.output}}',
        }},
    ))
    assert run['status'] == 'succeeded', run['error']
    assert client.get(run['outputs']['speech']['url']).content == b'ID3speech'
    assert sum(event['type'] == 'run_finished' for event in events) == 1


def test_image_to_h3_video_waits_and_passes_image_as_data_url(client, upstream, monkeypatch):
    monkeypatch.setattr(VideoNode, "poll_interval", 0)
    calls = []
    queried = 0

    def handler(request):
        nonlocal queried
        calls.append(request.url.path)
        if request.url.path.endswith("image_generation"):
            return httpx.Response(200, json={"data": {"image_base64": [base64.b64encode(PNG).decode()]}})
        if request.method == "POST":
            assert request.url.path == "/v2/video_generation"
            body = json.loads(request.content)
            assert body["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
            assert body["content"][1]["role"] == "first_frame"
            return httpx.Response(200, json={"task_id": "task-123"})
        queried += 1
        return httpx.Response(200, json={"task": {"status": "running" if queried == 1 else "succeeded", "content": {} if queried == 1 else {"url": "https://example.com/result.mp4"}}})
    upstream(handler)
    run, events = run_workflow(client, graph(
        {"id": "image", "type": "image", "data": {"prompt": "{{start.topic}}", "model": "image-01"}},
        {"id": "video", "type": "video", "data": {"prompt": "让画面动起来", "image_url": "{{image.url}}"}},
    ))
    assert run["status"] == "succeeded", run["error"]
    assert run["outputs"]["video"] == {"kind": "video", "url": "https://example.com/result.mp4", "temporary": True, "task_id": "task-123", "api_version": "v2"}
    assert calls.count("/v2/video_generation") == 1
    assert queried == 2
    assert any(e["type"] == "node_progress" and e["data"]["task_id"] == "task-123" for e in events)


def test_music_can_feed_asr_and_cover_uses_local_audio(client, upstream):
    def handler(request):
        if request.url.path.endswith("speech_to_text"):
            return httpx.Response(200, json={"text": "歌词", "duration": 10})
        body = json.loads(request.content)
        if body["model"] == "music-cover":
            assert base64.b64decode(body["audio_base64"]) == b"ID3-music"
        else:
            assert body["is_instrumental"] is True
        return httpx.Response(200, json={"data": {"audio": b"ID3-music".hex()}})
    upstream(handler)
    run, _ = run_workflow(client, graph(
        {"id": "music", "type": "music", "data": {}},
        {"id": "cover", "type": "music", "data": {"model": "music-cover", "audio_url": "{{music.url}}"}},
        {"id": "asr", "type": "asr", "data": {"audio_url": "{{cover.url}}"}},
    ))
    assert run["status"] == "succeeded", run["error"]
    assert run["outputs"]["asr"] == "歌词"


def test_uploaded_audio_is_persistent_input_to_asr(client, upstream):
    response = client.post("/api/artifacts/upload", json={"file_name": "录音.mp3", "file_base64": base64.b64encode(b"ID3-upload").decode()})
    assert response.status_code == 201
    url = response.json()["url"]
    assert client.get(url).content == b"ID3-upload"
    upstream(lambda request: httpx.Response(200, json={"text": "录音内容"}))
    run, _ = run_workflow(client, graph({"id": "asr", "type": "asr", "data": {"audio_url": url}}))
    assert run["outputs"]["asr"] == "录音内容"
    assert client.post("/api/artifacts/upload", json={"file_name": "bad.html", "file_base64": "aGVsbG8="}).status_code == 422
    assert client.post("/api/artifacts/upload", json={"file_name": "audio.mp3", "file_base64": "invalid"}).status_code == 422
    with pytest.raises(ValueError):
        read_artifact("/artifacts/../../outside.mp3", "audio")


@pytest.mark.parametrize("source,field,target", [("speech", "output", "asr"), ("image", "output", "video"), ("speech", "url", "llm"), ("video", "url", "asr")])
def test_invalid_media_types_and_references_are_rejected(source, field, target):
    data = {"audio_url" if target == "asr" else "image_url" if target == "video" else "prompt": f"{{{{source.{field}}}}}"}
    with pytest.raises(ValueError):
        validate_graph(Graph.model_validate(graph({"id": "source", "type": source, "data": {}}, {"id": "consumer", "type": target, "data": data})))


def test_video_poll_failure_preserves_task_id_without_resubmitting(client, monkeypatch):
    import app.nodes.media as media

    calls = []
    async def trial(*args):
        calls.append("create")
        return {"result": {"task_id": "task-error"}}
    async def query(*args):
        calls.append("query")
        raise ValueError("system error")
    monkeypatch.setattr(media, "trial", trial)
    monkeypatch.setattr(media, "query_video", query)
    monkeypatch.setattr(VideoNode, "poll_interval", 0)
    run, events = run_workflow(client, graph({"id": "video", "type": "video", "data": {}}))
    assert run["status"] == "failed"
    assert "task-error" in run["error"]
    assert calls == ["create", "query", "query", "query"]
    assert any(e["type"] == "node_progress" and e["data"]["task_id"] == "task-error" for e in events)


def test_video_timeout_bounds_a_hanging_query_and_cancellation_stops_polling(monkeypatch):
    import app.nodes.media as media

    async def trial(*args):
        return {"result": {"task_id": "task-slow"}}
    async def query(*args):
        await asyncio.sleep(100)
    monkeypatch.setattr(media, "trial", trial)
    monkeypatch.setattr(media, "query_video", query)
    node = Node(id="video", type="video", data={"prompt": "咖啡", "timeout": "1"})

    async def check():
        with pytest.raises(ValueError, match="task-slow.*等待超时"):
            await VideoNode().run(node, {}, {}, set(), lambda *args: None)
        started = asyncio.Event()
        events = []
        def emit(type, data):
            events.append(type)
            if type == "node_progress":
                started.set()
        task = asyncio.create_task(VideoNode().run(node, {}, {}, set(), emit))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(check())


@pytest.mark.parametrize('case', [
    ('MiniMax-H3-Max', 4, '768P', False),
    ('MiniMax-H3-Max', 5, '768P', True),
    ('MiniMax-H3-Highspeed', 5, '2K', False),
    ('MiniMax-H3-Lite', 4, '480P', True),
    ('T2V-01', 6, '720P', True),
    ('T2V-01', 10, '720P', False),
    ('MiniMax-Hailuo-02', 10, '768P', True),
    ('MiniMax-Hailuo-02', 10, '1080P', False),
])
def test_video_limits_match_between_workflow_and_lab(
    client: TestClient, upstream: Callable[[Callable[[httpx.Request], httpx.Response]], None],
    monkeypatch: pytest.MonkeyPatch,
    case: tuple[str, int, str, bool],
) -> None:
    model, duration, resolution, valid = case
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == 'POST':
            return httpx.Response(200, json={'task_id': 'same-video-task'})
        return httpx.Response(200, json={
            'status': 'Success',
            'task': {'status': 'succeeded', 'content': {'url': 'https://example.com/video.mp4'}},
        })

    upstream(handler)
    monkeypatch.setattr(VideoNode, 'poll_interval', 0)
    payload = {'duration': duration, 'resolution': resolution, 'prompt': 'coffee'}
    if model.startswith('MiniMax-H3'):
        payload['content'] = [{'type': 'text', 'text': 'coffee'}]
    response = client.post('/api/minimax/trial', json={'model': model, 'payload': payload})
    assert response.status_code == (200 if valid else 422), response.text
    assert len(calls) == int(valid)
    calls.clear()
    run, events = run_workflow(client, graph({'id': 'video', 'type': 'video', 'data': {
        'model': model, 'prompt': 'coffee', 'duration': str(duration), 'resolution': resolution,
    }}))
    assert run['status'] == ('succeeded' if valid else 'failed'), run['error']
    assert sum(request.method == 'POST' for request in calls) == int(valid)
    assert sum(event['type'] == 'run_finished' for event in events) == 1
    if valid:
        assert run['outputs']['video']['task_id'] == 'same-video-task'
    else:
        assert calls == []
