import asyncio
import copy
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.engine.executor import execute
from app.engine.graph import render, validate_graph
from app.examples import example_graph
from app.models import Event, Run, Session, Setting
from app.nodes.runners import RUNNERS
from app.providers.client import Provider
from app.schemas import Graph


def test_restart_marks_unfinished_run_interrupted(client):
    from fastapi.testclient import TestClient
    from app.main import app

    with Session.begin() as db:
        db.add(Run(id="interrupted-test", status="running", graph=example_graph(demo=True), inputs={}))
    with TestClient(app) as restarted:
        assert restarted.post("/api/runs/get", json={"id": "interrupted-test"}).json()["status"] == "interrupted"
        replay = events(restarted, "interrupted-test")
        assert replay[-1]["type"] == "run_finished"
        assert replay[-1]["data"]["status"] == "interrupted"


def workflow(client, graph=None):
    response = client.post("/api/workflows", json={"name": "测试创作", "graph": graph or example_graph(demo=True)})
    assert response.status_code == 201
    return response.json()


def test_post_api_contract_and_get_documentation(client):
    schema = client.get("/openapi.json").json()
    for path, operations in schema["paths"].items():
        if path.startswith("/api/"):
            assert set(operations) == {"post"}, path
            assert "{" not in path, path
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200
    assert client.get("/api/health").status_code == 405
    assert client.post("/api/health").json() == {"status": "ok"}
    assert client.post("/api/nodes").json()
    assert client.post("/api/models").json()


def test_workflow_list_and_delete_payload(client):
    w = workflow(client)
    assert any(item["id"] == w["id"] for item in client.post("/api/workflows/list").json())
    response = client.post("/api/workflows/delete", json={"id": w["id"]})
    assert response.status_code == 204
    assert response.content == b""
    assert client.post("/api/workflows/get", json={"id": w["id"]}).status_code == 404


@pytest.mark.parametrize("payload", [{}, {"id": ""}, {"id": "missing", "after": -1}, {"id": "missing", "after": "bad"}])
def test_event_payload_validation(client, payload):
    assert client.post("/api/runs/events", json=payload).status_code == 422


def test_event_run_not_found(client):
    assert client.post("/api/runs/events", json={"id": "missing"}).status_code == 404


def events(client, id, after=0):
    response = client.post("/api/runs/events", json={"id": id, "after": after})
    assert response.status_code == 200
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def test_demo_end_to_end_history_and_reconnect(client):
    w = workflow(client)
    response = client.post("/api/workflows/runs", json={"id": w["id"], "inputs": {"topic": "慢生活"}})
    assert response.status_code == 201
    id = response.json()["id"]
    replay = events(client, id)
    assert replay[0]["type"] == "run_started"
    assert any(event["type"] == "llm_token" for event in replay)
    assert replay[-1]["data"]["status"] == "succeeded"
    detail = client.post("/api/runs/get", json={"id": id}).json()
    assert "慢生活" in detail["outputs"]["template"]
    assert client.get(detail["outputs"]["image"]["url"]).status_code == 200
    assert len([e for e in replay if e["type"] == "node_finished"]) == 5
    assert client.post("/api/workflows/runs/list", json={"id": w["id"]}).json()[0]["graph"] == w["graph"]
    with Session() as db:
        cursor = db.scalar(select(Event.id).where(Event.run_id == id).order_by(Event.id).limit(1))
    resumed = events(client, id, cursor)
    assert resumed[0]["type"] != "run_started"
    assert resumed[-1] == replay[-1]


def test_optimistic_save_and_snapshot(client):
    w = workflow(client)
    payload = {"id": w["id"], "name": "更新", "graph": w["graph"], "version": w["version"]}
    saved = client.post("/api/workflows/save", json=payload)
    assert saved.json()["version"] == 2
    assert client.post("/api/workflows/save", json=payload).status_code == 409
    assert client.post("/api/workflows/get", json={"id": w["id"]}).json()["name"] == "更新"


@pytest.mark.parametrize("mutation", [
    lambda g: g["edges"].append({"id": "cycle", "source": "template", "target": "llm"}),
    lambda g: g["nodes"][1]["data"].update(prompt="{{image.output}}"),
    lambda g: g["nodes"][1]["data"].update(prompt="{{start.unknown}}"),
    lambda g: g["nodes"].append(copy.deepcopy(g["nodes"][0])),
    lambda g: g["edges"].append({"id": "bad-type", "source": "image", "target": "template"}),
    lambda g: g["nodes"][0]["data"].update(fields=["topic"]),
    lambda g: g["nodes"][1]["data"].update(prompt="{{start.topic"),
])
def test_rejects_invalid_graphs(client, mutation):
    graph = example_graph(demo=True)
    mutation(graph)
    with pytest.raises(ValueError):
        validate_graph(Graph.model_validate(graph))


def test_terminal_branch_does_not_require_end_connection(client: TestClient) -> None:
    graph = example_graph(demo=True)
    graph['edges'].pop()  # A former invalid branch is now an automatic terminal output.
    w = workflow(client, graph)
    response = client.post('/api/workflows/runs', json={'id': w['id'], 'inputs': {'topic': '独立末端'}})
    assert response.status_code == 201, response.text
    events(client, response.json()['id'])
    run = client.post('/api/runs/get', json={'id': response.json()['id']}).json()
    assert run['status'] == 'succeeded', run['error']
    assert set(run['outputs']) == {'image', 'template'}
    assert '独立末端' in run['outputs']['template']


def test_required_inputs_and_provider_key(client):
    w = workflow(client)
    assert client.post("/api/workflows/runs", json={"id": w["id"], "inputs": {}}).status_code == 422
    response = client.post("/api/provider/save", json={"base_url": "https://example.com/v1", "api_key": "private-test-key"})
    assert response.status_code == 200
    assert "private-test-key" not in response.text
    assert client.post("/api/provider/get").json()["configured"]
    with Session() as db:
        assert "private-test-key" not in db.get(Setting, "deepseek").encrypted_key
    assert client.post("/api/provider/save", json={"base_url": "file:///etc", "api_key": ""}).status_code == 422


def test_cancel_running_task(client):
    w = workflow(client)
    run = client.post("/api/workflows/runs", json={"id": w["id"], "inputs": {"topic": "取消"}}).json()
    assert client.post("/api/runs/cancel", json={"id": run["id"]}).status_code == 200
    assert events(client, run["id"])[-1]["data"]["status"] == "cancelled"


def test_failing_model_ends_run(client):
    graph = example_graph(demo=True)
    graph["nodes"][1]["data"]["model"] = "nonexistent"
    w = workflow(client, graph)
    run = client.post("/api/workflows/runs", json={"id": w["id"], "inputs": {"topic": "错误"}}).json()
    replay = events(client, run["id"])
    assert any(e["type"] == "node_failed" for e in replay)
    assert replay[-1]["data"]["status"] == "failed"


def test_ready_queue_does_not_wait_for_unrelated_branch(client, monkeypatch):
    async def check():
        branch_released = asyncio.Event()

        class Template:
            async def run(self, node, *args):
                if node.id == "slow":
                    # A level-by-level gather scheduler would deadlock here.
                    await asyncio.wait_for(branch_released.wait(), timeout=2)
                if node.id == "child":
                    branch_released.set()
                return {"output": node.id}, {}

        monkeypatch.setitem(RUNNERS, "template", Template())
        graph = Graph.model_validate({"nodes": [
            {"id": key, "type": kind, "data": {"fields": "topic"} if kind == "start" else {}}
            for key, kind in [("start", "start"), ("fast", "template"), ("slow", "template"), ("child", "template"), ("end", "end")]
        ], "edges": [{"id": str(i), "source": a, "target": b} for i, (a, b) in enumerate([
            ("start", "fast"), ("start", "slow"), ("fast", "child"), ("slow", "end"), ("child", "end")
        ])]})
        with Session.begin() as db:
            db.add(Run(id="parallel-test", graph=graph.model_dump(), inputs={"topic": "x"}))
        await execute("parallel-test", graph, {"topic": "x"})
        with Session() as db:
            assert db.get(Run, "parallel-test").status == "succeeded"

    asyncio.run(check())


def test_deepseek_stream_adapter(client, monkeypatch):
    client.post("/api/provider/save", json={"base_url": "https://example.com/v1", "api_key": "test-key"})
    real_client = httpx.AsyncClient

    def handler(request):
        assert request.headers["authorization"] == "Bearer test-key"
        assert request.url.path == "/v1/chat/completions"
        payload = json.loads(request.content)
        assert payload["model"] == "deepseek-flash"
        assert payload["thinking"] == {"type": "disabled"}
        assert payload["stream"] is True
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"hello"}}]}\n\ndata: {"choices":[],"usage":{"total_tokens":3}}\n\ndata: [DONE]\n\n')

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))

    async def check():
        chunks = [chunk async for chunk in Provider("deepseek-flash", "text").chat("system", "prompt")]
        assert "".join(c["text"] for c in chunks) == "hello"
        assert chunks[-1]["usage"]["total_tokens"] == 3
    asyncio.run(check())


def test_provider_connections_are_independent_and_keys_stay_private(client):
    for provider, url in [("deepseek", "https://api.deepseek.com"), ("minimax", "https://api.minimax.cn/v1")]:
        response = client.post("/api/provider/save", json={"provider": provider, "base_url": url, "api_key": f"private-{provider}"})
        assert response.status_code == 200
        assert f"private-{provider}" not in response.text
        response = client.post("/api/provider/get", json={"provider": provider})
        assert response.json() == {"provider": provider, "base_url": url, "configured": True}
        assert f"private-{provider}" not in response.text
        client.post("/api/provider/save", json={"provider": provider, "base_url": url, "api_key": ""})
    assert Provider("deepseek-flash", "text").key == "private-deepseek"
    assert Provider("image-01", "image").key == "private-minimax"
    assert client.post("/api/provider/save", json={"provider": "unknown", "base_url": "https://example.com"}).status_code == 422


@pytest.mark.parametrize("size,dimensions", [("1024x1024", (1024, 1024)), ("1536x1024", (1536, 1024)), ("1024x1536", (1024, 1536))])
def test_minimax_adapter_persists_generated_image(client, monkeypatch, size, dimensions):
    import base64
    from app.models import DATA_DIR

    client.post("/api/provider/save", json={"provider": "minimax", "base_url": "https://api.minimax.cn/v1", "api_key": "image-key"})
    real_client = httpx.AsyncClient
    content = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a5S8AAAAASUVORK5CYII=")

    def handler(request):
        assert request.method == "POST"
        assert str(request.url) == "https://api.minimax.cn/v1/image_generation"
        assert request.headers["authorization"] == "Bearer image-key"
        payload = json.loads(request.content)
        assert payload == {"model": "image-01", "prompt": "一杯咖啡", "width": dimensions[0], "height": dimensions[1], "response_format": "base64", "n": 1}
        return httpx.Response(200, json={"base_resp": {"status_code": 0}, "data": {"image_base64": [base64.b64encode(content).decode()]}})

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    image = asyncio.run(Provider("image-01", "image").text2img("一杯咖啡", size))
    assert image["url"].startswith("/artifacts/")
    assert (DATA_DIR / "artifacts" / image["url"].split("/")[-1]).read_bytes() == content
    assert client.get(image["url"]).status_code == 200


@pytest.mark.parametrize("result,expected", [
    ({"base_resp": {"status_code": 1008}, "data": {}}, "错误码 1008"),
    ({"base_resp": {"status_code": 0}, "data": {}}, "未返回有效图片"),
])
def test_minimax_business_errors_do_not_look_like_success(client, monkeypatch, result, expected):
    client.post("/api/provider/save", json={"provider": "minimax", "base_url": "https://api.minimax.cn/v1", "api_key": "image-key"})
    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=result)), **kw))
    with pytest.raises(ValueError, match=expected):
        asyncio.run(Provider("image-01", "image").text2img("咖啡", "1024x1024"))


def test_new_workflows_and_node_defaults_use_requested_models(client):
    graph = example_graph()
    assert graph["nodes"][1]["data"]["model"] == "deepseek-flash"
    assert graph["nodes"][2]["data"]["model"] == "image-01"
    registry = client.post("/api/nodes").json()
    assert registry["llm"]["properties"]["model"]["default"] == "deepseek-flash"
    assert registry["image"]["properties"]["model"]["default"] == "image-01"


def test_template_missing_variable_is_error():
    with pytest.raises(ValueError):
        render("{{missing.output}}", {})


def test_failure_cancels_sibling_and_skips_end(client, monkeypatch):
    async def check():
        started, cancelled = asyncio.Event(), asyncio.Event()

        class Branch:
            async def run(self, node, *args):
                if node.id == "bad":
                    await started.wait()
                    raise ValueError("intentional failure")
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()

        monkeypatch.setitem(RUNNERS, "template", Branch())
        graph = Graph.model_validate({"nodes": [
            {"id": key, "type": kind, "data": {"fields": "topic"} if kind == "start" else {}}
            for key, kind in [("start", "start"), ("bad", "template"), ("slow", "template"), ("end", "end")]
        ], "edges": [{"id": str(i), "source": a, "target": b} for i, (a, b) in enumerate([
            ("start", "bad"), ("start", "slow"), ("bad", "end"), ("slow", "end")
        ])]})
        with Session.begin() as db:
            db.add(Run(id="failure-test", graph=graph.model_dump(), inputs={"topic": "x"}))
        await asyncio.wait_for(execute("failure-test", graph, {"topic": "x"}), timeout=3)
        assert cancelled.is_set()
        with Session() as db:
            assert db.get(Run, "failure-test").status == "failed"
            rows = list(db.scalars(select(Event).where(Event.run_id == "failure-test")))
            assert any(e.type == "node_cancelled" and e.data["node_id"] == "slow" for e in rows)
            assert not any(e.type == "node_started" and e.data["node_id"] == "end" for e in rows)
    asyncio.run(check())
