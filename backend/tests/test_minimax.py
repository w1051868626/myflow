import base64
from collections.abc import Callable
import copy
import json

import httpx
import pytest

from app.models import Session, Setting
from app.providers.client import Provider, cipher
from app.providers.minimax import presets
from app.providers.types import RequestOptions
from app.models import DATA_DIR
from fastapi.testclient import TestClient


@pytest.fixture
def minimax(client, monkeypatch):
    client.post("/api/provider/save", json={"provider": "minimax", "base_url": "https://example.com/gateway/v1", "api_key": "private-multimodal"})
    client.post("/api/provider/save", json={"provider": "minimax_text", "base_url": "https://example.com/text/v1", "api_key": "private-text"})
    real_client = httpx.AsyncClient

    def install(handler):
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    return install


@pytest.mark.parametrize("preset", presets(), ids=lambda item: item["id"])
def test_every_catalog_model_is_routed_to_its_api(client, minimax, preset):
    body = copy.deepcopy(preset["payload"])
    kind = preset["kind"]
    if preset.get("reference") == "audio":
        body["audio_url"] = "https://example.com/reference.mp3"
    elif preset.get("reference") == "image":
        body["first_frame_image"] = "https://example.com/reference.png"
    elif preset.get("reference") == "subject":
        body["subject_reference"] = [{"type": "character", "image": ["https://example.com/person.png"]}]
    expected_paths = {"text": "chat/completions", "image": "image_generation", "speech": "t2a_v2", "music": "music_generation", "video": "video_generation", "asr": "speech_to_text"}
    endpoint = expected_paths[kind]
    if kind == "text" and preset["id"] not in ("MiniMax-M3", "MiniMax-M3.1-Flash"):
        endpoint = "text/chatcompletion_v2"

    def handler(request):
        assert request.method == "POST"
        prefix = "/text" if kind == "text" else "/gateway"
        assert request.url.path == f"{prefix}/{preset.get('api_version', 'v1')}/{endpoint}"
        assert request.headers["authorization"] == ("Bearer private-text" if kind == "text" else "Bearer private-multimodal")
        if kind == "asr":
            assert request.headers["content-type"].startswith("multipart/form-data")
            assert b"sample-audio" in request.content
        else:
            assert json.loads(request.content)["model"] == preset["id"]
        data = {"image_urls": ["https://example.com/image.png"]} if kind == "image" else {"audio": b"ID3audio".hex()} if kind in ("speech", "music") else {}
        return httpx.Response(200, json={"base_resp": {"status_code": 0}, "choices": [], "data": data})
    minimax(handler)
    response = client.post("/api/minimax/trial", json={"model": preset["id"], "payload": body,
                           "file_base64": base64.b64encode(b"sample-audio").decode() if kind == "asr" else None})
    assert response.status_code == 200, response.text
    assert response.json()["model"] == preset["id"]
    assert "private-text" not in response.text and "private-multimodal" not in response.text


def test_v2_task_query_uses_saved_key_and_returns_video(client, minimax):
    def handler(request):
        assert request.method == "GET"
        assert request.url.path == "/gateway/v2/query/video_generation/12345"
        return httpx.Response(200, json={"task": {"status": "succeeded", "content": {"url": "https://example.com/video.mp4"}}})
    minimax(handler)
    response = client.post("/api/minimax/video/query", json={"task_id": "12345", "api_version": "v2"})
    assert response.json()["media"][0]["kind"] == "video"
    assert client.post("/api/minimax/video/query", json={"task_id": "../escape"}).status_code == 422


def test_discovery_keeps_post_api_and_get_provider_request(
    client: TestClient, minimax: Callable[[Callable[[httpx.Request], httpx.Response]], None],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == 'GET'
        assert request.url.path == '/text/v1/models'
        assert request.headers['authorization'] == 'Bearer private-text'
        return httpx.Response(200, json={'data': [{'id': 'available-model'}]})

    minimax(handler)
    response = client.post('/api/minimax/discover', json={})
    assert response.status_code == 200
    assert response.json() == {'data': [{'id': 'available-model'}]}


def test_legacy_task_query_retrieves_download_link(client, minimax):
    def handler(request):
        if request.url.path.endswith("query/video_generation"):
            assert request.url.params["task_id"] == "12345"
            return httpx.Response(200, json={"status": "Success", "file_id": "file-1"})
        assert request.url.path.endswith("files/retrieve")
        assert request.url.params["file_id"] == "file-1"
        return httpx.Response(200, json={"file": {"download_url": "https://example.com/video.mp4"}})
    minimax(handler)
    response = client.post("/api/minimax/video/query", json={"task_id": "12345", "api_version": "v1"})
    assert response.json()["media"][0]["url"] == "https://example.com/video.mp4"


def test_audio_hex_is_saved_as_downloadable_resource(client, minimax):
    minimax(lambda request: httpx.Response(200, json={"data": {"audio": b"ID3audio".hex()}, "base_resp": {"status_code": 0}}))
    response = client.post("/api/minimax/trial", json={"model": "speech-2.8-hd", "payload": {"text": "你好", "output_format": "hex"}})
    url = response.json()["media"][0]["url"]
    assert url.endswith(".mp3")
    assert client.get(url).content == b"ID3audio"
    assert response.json()["result"]["data"]["audio"] == url


@pytest.mark.parametrize("model,payload", [("unknown", {}), ("speech-2.8-hd", {"stream": True}), ("music-cover", {}), ("asr-1.0", {}), ("I2V-01", {}), ("S2V-01", {})])
def test_invalid_trials_do_not_call_upstream(client, minimax, model, payload):
    minimax(lambda request: pytest.fail("invalid request called upstream"))
    assert client.post("/api/minimax/trial", json={"model": model, "payload": payload}).status_code == 422


@pytest.mark.parametrize('model,payload', [
    ('speech-2.8-hd', {'text': ''}),
    ('speech-2.8-hd', {'text': '   '}),
    ('speech-2.8-hd', {'text': 123}),
    ('speech-2.8-hd', {'text': ' ' * 10000 + 'x'}),
    ('speech-2.8-hd', {'text': 'x', 'voice_setting': []}),
    ('speech-2.8-hd', {'text': 'x', 'voice_setting': {'speed': 99}}),
    ('speech-2.8-hd', {'text': 'x', 'voice_setting': {'speed': True}}),
    ('speech-2.8-hd', {'text': 'x', 'voice_setting': {'voice_id': ' '}}),
    ('MiniMax-M3', {'messages': []}),
    ('MiniMax-M3', {'messages': 'hello'}),
    ('image-01', {'prompt': ' '}),
    ('image-01', {'prompt': 'x', 'n': -1}),
    ('music-3.0', {'prompt': 'x', 'is_instrumental': False}),
    ('music-cover', {'audio_url': ' '}),
    ('MiniMax-H3-Highspeed', {'content': [], 'duration': -1, 'resolution': 'bogus'}),
    ('MiniMax-H3-Highspeed', {'content': [{'type': 'text', 'text': 'x'}], 'duration': -1}),
    ('MiniMax-H3-Highspeed', {'content': [{'type': 'text', 'text': 'x'}], 'resolution': 'bogus'}),
    ('MiniMax-H3-Highspeed', {'content': [{'type': 'text', 'text': 'x'}], 'duration': True}),
    ('MiniMax-H3-Highspeed', {'content': [{'type': 'text', 'text': ' '}]}),
    ('T2V-01', {'prompt': '', 'duration': 6}),
    ('S2V-01', {'prompt': 'x', 'subject_reference': [123]}),
])
def test_lab_001_invalid_parameters_have_no_side_effects(
    client: TestClient, model: str, payload: dict[str, object], monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []

    async def unexpected(*args: object, **kwargs: object) -> dict[str, object]:
        calls.append((args, kwargs))
        return {'data': {'audio': b'ID3mock'.hex(), 'image_urls': ['https://example.com/mock.png']}}

    monkeypatch.setattr('app.providers.minimax.request_json', unexpected)
    before = set((DATA_DIR / 'artifacts').iterdir())
    response = client.post('/api/minimax/trial', json={'model': model, 'payload': payload})
    assert response.status_code == 422, response.text
    assert calls == []
    assert set((DATA_DIR / 'artifacts').iterdir()) == before


def test_lab_001_validation_preserves_optional_defaults_and_extensions(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    async def upstream(
        provider: str, version: str, path: str, options: RequestOptions,
    ) -> dict[str, object]:
        calls.append(options.payload)
        return {'data': {'audio': b'ID3validated'.hex()}}

    monkeypatch.setattr('app.providers.minimax.request_json', upstream)
    payload = {'text': 'hello', 'provider_extension': {'enabled': True}}
    response = client.post('/api/minimax/trial', json={'model': 'speech-2.8-hd', 'payload': payload})
    assert response.status_code == 200, response.text
    assert calls == [{**payload, 'model': 'speech-2.8-hd', 'stream': False}]
    assert client.get(response.json()['media'][0]['url']).content == b'ID3validated'


@pytest.mark.parametrize('encoded', ['====', '%%%invalid'])
def test_lab_001_invalid_asr_bytes_never_call_upstream(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, encoded: str,
) -> None:
    calls: list[object] = []

    async def upstream(*args: object, **kwargs: object) -> dict[str, object]:
        calls.append(args)
        return {'text': 'unexpected'}

    monkeypatch.setattr('app.providers.minimax.request_json', upstream)
    response = client.post('/api/minimax/trial', json={
        'model': 'asr-1.0', 'payload': {}, 'file_base64': encoded,
    })
    assert response.status_code == 422, response.text
    assert calls == []


def test_upstream_business_error_redacts_secret(client, minimax):
    minimax(lambda request: httpx.Response(200, json={"base_resp": {"status_code": 1004, "status_msg": "invalid private-multimodal"}}))
    response = client.post("/api/minimax/trial", json={"model": "image-01", "payload": {"prompt": "coffee"}})
    assert response.status_code == 422
    assert "private-multimodal" not in response.text
    assert "invalid" in response.json()["detail"]


def test_minimax_text_can_fall_back_to_multimodal_key(client, minimax):
    with Session.begin() as db:
        db.delete(db.get(Setting, "minimax_text"))
        setting = db.get(Setting, "minimax")
        setting.encrypted_key = cipher().encrypt(b"fallback-key").decode()
    assert Provider("MiniMax-M3", "text").key == "fallback-key"


@pytest.mark.parametrize("size,ratio", [("1024x1024", "1:1"), ("1536x1024", "3:2"), ("1024x1536", "2:3")])
def test_image_live_workflow_adapter_uses_aspect_ratio(client, minimax, size, ratio):
    import asyncio

    def handler(request):
        body = json.loads(request.content)
        assert body["model"] == "image-01-live"
        assert body["aspect_ratio"] == ratio
        assert "width" not in body and "height" not in body
        return httpx.Response(200, json={"data": {"image_urls": ["https://example.com/live.jpg"]}, "base_resp": {"status_code": 0}})
    minimax(handler)
    assert asyncio.run(Provider("image-01-live", "image").text2img("咖啡", size))["url"] == "https://example.com/live.jpg"
