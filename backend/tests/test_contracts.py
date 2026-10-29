"""Acceptance contracts from SPEC.md; use public APIs where possible."""

import asyncio
import base64
import copy
import json
from uuid import uuid4

import pytest
import httpx
from sqlalchemy import select

from app.engine.executor import execute
from app.examples import example_graph
from app.models import Event, Run, Session
from app.nodes.runners import RUNNERS
from app.schemas import Graph
from fastapi.testclient import TestClient


def create(client, graph=None):
    response = client.post('/api/workflows', json={
        'name': '验收工作流', 'graph': graph if graph is not None else example_graph(demo=True),
    })
    assert response.status_code == 201, response.text
    return response.json()


def finish(client, run_id):
    response = client.post('/api/runs/events', json={'id': run_id})
    assert response.status_code == 200
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]


@pytest.mark.parametrize('field', ['model', 'voice_id', 'speed'])
@pytest.mark.parametrize('reference', ['{{other.output}}', '{{start.unknown}}', '{{start.topic'])
def test_ref_001_media_properties_reject_invalid_references(
    client: TestClient, field: str, reference: str,
) -> None:
    graph = {
        'nodes': [
            {'id': 'start', 'type': 'start'},
            {'id': 'other', 'type': 'template', 'data': {'template': 'voice'}},
            {'id': 'speech', 'type': 'speech', 'data': {field: reference}},
            {'id': 'end', 'type': 'end'},
        ],
        'edges': [{'id': str(i), 'source': a, 'target': b} for i, (a, b) in enumerate([
            ('start', 'other'), ('other', 'end'), ('start', 'speech'), ('speech', 'end'),
        ])],
    }
    workflow = create(client, graph)
    response = client.post('/api/workflows/runs', json={'id': workflow['id'], 'inputs': {'topic': 'x'}})
    assert response.status_code == 422, response.text
    assert client.post('/api/workflows/runs/list', json={'id': workflow['id']}).json() == []


@pytest.mark.parametrize('value', [123, None, [], {}])
def test_graph_001_non_string_legacy_property_is_rejected(client: TestClient, value: object) -> None:
    graph = example_graph(demo=True)
    graph['nodes'][0]['data']['prompt'] = value
    workflow = create(client, graph)
    response = client.post('/api/workflows/runs', json={'id': workflow['id'], 'inputs': {'topic': 'x'}})
    assert response.status_code == 422, response.text
    assert client.post('/api/workflows/runs/list', json={'id': workflow['id']}).json() == []


@pytest.mark.parametrize('inputs', [{}, {'topic': ''}, {'topic': '  '}, {'topic': 'x', 'extra': 'y'}])
def test_input_001_rejected_inputs_create_no_run(client, inputs):
    workflow = create(client)
    response = client.post('/api/workflows/runs', json={'id': workflow['id'], 'inputs': inputs})
    assert response.status_code == 422
    assert client.post('/api/workflows/runs/list', json={'id': workflow['id']}).json() == []


def test_graph_001_incomplete_draft_is_saved_but_cannot_run(client):
    workflow = create(client, {'nodes': [], 'edges': []})
    assert client.post('/api/workflows/get', json={'id': workflow['id']}).json()['graph'] == workflow['graph']
    assert client.post('/api/workflows/runs', json={'id': workflow['id']}).status_code == 422
    assert client.post('/api/workflows/runs/list', json={'id': workflow['id']}).json() == []


@pytest.mark.parametrize('defect', [
    'duplicate_edge', 'self_edge', 'missing_source', 'missing_target', 'incoming_start',
    'outgoing_end', 'missing_start', 'invalid_fields',
])
def test_graph_001_invalid_draft_never_creates_a_run(client, defect):
    graph = example_graph(demo=True)
    if defect == 'duplicate_edge':
        graph['edges'].append({**graph['edges'][0], 'id': 'duplicate'})
    elif defect in ('self_edge', 'missing_source', 'missing_target', 'incoming_start', 'outgoing_end'):
        source, target = {
            'self_edge': ('llm', 'llm'), 'missing_source': ('absent', 'end'),
            'missing_target': ('start', 'absent'), 'incoming_start': ('llm', 'start'),
            'outgoing_end': ('end', 'llm'),
        }[defect]
        graph['edges'].append({'id': 'invalid', 'source': source, 'target': target})
    elif defect == 'missing_start':
        graph['nodes'] = [node for node in graph['nodes'] if node['type'] != 'start']
    else:
        graph['nodes'][0]['data']['fields'] = 'topic,topic'
    workflow = create(client, graph)
    response = client.post('/api/workflows/runs', json={'id': workflow['id'], 'inputs': {'topic': 'x'}})
    assert response.status_code == 422
    assert client.post('/api/workflows/runs/list', json={'id': workflow['id']}).json() == []


@pytest.mark.parametrize('extra_type', ['end', 'template'])
def test_graph_001_additional_terminals_are_valid(client: TestClient, extra_type: str) -> None:
    graph = example_graph(demo=True)
    graph['nodes'].append({'id': 'extra', 'type': extra_type, 'data': {}})
    workflow = create(client, graph)
    response = client.post('/api/workflows/runs', json={'id': workflow['id'], 'inputs': {'topic': 'x'}})
    assert response.status_code == 201, response.text
    finish(client, response.json()['id'])
    run = client.post('/api/runs/get', json={'id': response.json()['id']}).json()
    assert run['status'] == 'succeeded', run['error']
    expected = {'image', 'template', 'extra'} if extra_type == 'template' else {'image', 'template'}
    assert set(run['outputs']) == expected


@pytest.mark.parametrize('resource,count', [('nodes', 101), ('edges', 501)])
def test_graph_002_graph_size_limits(client, resource, count):
    graph = {'nodes': [], 'edges': []}
    graph[resource] = ([{'id': f'n{i}', 'type': 'template'} for i in range(count)]
                       if resource == 'nodes' else [{'id': str(i), 'source': 'a', 'target': 'b'} for i in range(count)])
    assert client.post('/api/workflows', json={'name': '超出上限', 'graph': graph}).status_code == 422


def test_save_001_stale_write_cannot_overwrite_saved_graph(client):
    workflow = create(client)
    original = {'id': workflow['id'], 'name': workflow['name'], 'graph': workflow['graph'], 'version': workflow['version']}
    changed = copy.deepcopy(original)
    changed['name'] = '新名称'
    changed['graph']['nodes'][0]['position'] = {'x': 321, 'y': 123}
    response = client.post('/api/workflows/save', json=changed)
    assert response.status_code == 200
    assert response.json()['version'] == workflow['version'] + 1
    assert client.post('/api/workflows/save', json=original).status_code == 409
    saved = client.post('/api/workflows/get', json={'id': workflow['id']}).json()
    assert saved['graph'] == changed['graph']
    assert saved['name'] == changed['name']


def test_history_001_graph_version_inputs_and_outputs_survive_later_edits(client):
    workflow = create(client)
    response = client.post('/api/workflows/runs', json={'id': workflow['id'], 'inputs': {'topic': '历史主题'}})
    assert response.status_code == 201
    run_id = response.json()['id']
    replay = finish(client, run_id)
    before = client.post('/api/runs/get', json={'id': run_id}).json()
    changed = copy.deepcopy(workflow['graph'])
    changed['nodes'][1]['data']['prompt'] = '全新的提示词'
    assert client.post('/api/workflows/save', json={
        'id': workflow['id'], 'name': '编辑后的工作流', 'graph': changed, 'version': workflow['version'],
    }).status_code == 200
    after = client.post('/api/runs/get', json={'id': run_id}).json()
    assert after == before
    assert after['graph'] == workflow['graph']
    assert after['workflow_version'] == workflow['version']
    assert after['inputs'] == {'topic': '历史主题'}
    assert after['status'] == 'succeeded'
    assert finish(client, run_id) == replay


def test_history_002_only_latest_fifty_runs_are_returned(client):
    workflow = create(client)
    ids = [uuid4().hex for _ in range(52)]
    with Session.begin() as db:
        for index, run_id in enumerate(ids):
            db.add(Run(id=run_id, workflow_id=workflow['id'], status='succeeded', graph=workflow['graph'],
                       inputs={}, created_at=f'2026-01-01T00:00:{index:02d}+00:00'))
    response = client.post('/api/workflows/runs/list', json={'id': workflow['id']})
    assert response.status_code == 200
    assert [run['id'] for run in response.json()] == list(reversed(ids[2:]))


def test_sse_001_cursor_is_exclusive_and_terminal_cursor_closes_stream(client):
    workflow = create(client)
    response = client.post('/api/workflows/runs', json={'id': workflow['id'], 'inputs': {'topic': '事件游标'}})
    assert response.status_code == 201
    run_id = response.json()['id']
    response = client.post('/api/runs/events', json={'id': run_id})
    assert response.headers['content-type'].startswith('text/event-stream')
    ids = [int(line[4:]) for line in response.text.splitlines() if line.startswith('id: ')]
    assert len(ids) > 2
    assert ids == sorted(set(ids))
    cursor = ids[len(ids) // 2]
    resumed = client.post('/api/runs/events', json={'id': run_id, 'after': cursor})
    resumed_ids = [int(line[4:]) for line in resumed.text.splitlines() if line.startswith('id: ')]
    assert resumed_ids == [event_id for event_id in ids if event_id > cursor]
    closed = client.post('/api/runs/events', json={'id': run_id, 'after': ids[-1]})
    data = [json.loads(line[6:]) for line in closed.text.splitlines() if line.startswith('data: ')]
    assert data == [{'type': 'stream_closed', 'data': {'status': 'succeeded'}}]


def test_run_001_independent_nodes_run_concurrently_with_limit_four(client, monkeypatch):
    async def check():
        active = peak = started = 0
        release = asyncio.Event()

        class Branch:
            async def run(self, node, *args):
                nonlocal active, peak, started
                active += 1
                started += 1
                peak = max(peak, active)
                if started == 4:
                    release.set()
                try:
                    await asyncio.wait_for(release.wait(), timeout=2)
                    # Yield so all improperly scheduled extra branches would overlap.
                    await asyncio.sleep(0.01)
                    return {'output': node.id}, {}
                finally:
                    active -= 1

        monkeypatch.setitem(RUNNERS, 'template', Branch())
        branches = [f'branch{i}' for i in range(9)]
        graph = Graph.model_validate({
            'nodes': [{'id': 'start', 'type': 'start'}, *[{'id': key, 'type': 'template'} for key in branches],
                      {'id': 'end', 'type': 'end'}],
            'edges': [{'id': f'{a}-{b}', 'source': a, 'target': b}
                      for key in branches for a, b in [('start', key), (key, 'end')]],
        })
        run_id = uuid4().hex
        with Session.begin() as db:
            db.add(Run(id=run_id, graph=graph.model_dump(), inputs={'topic': 'x'}))
        await asyncio.wait_for(execute(run_id, graph, {'topic': 'x'}), timeout=5)
        assert started == len(branches)
        assert peak == 4
        assert active == 0
        with Session() as db:
            assert db.get(Run, run_id).status == 'succeeded'
            terminal = list(db.scalars(select(Event).where(Event.run_id == run_id, Event.type == 'run_finished')))
            assert len(terminal) == 1
    asyncio.run(check())


@pytest.mark.parametrize('payload', [
    {'file_name': 'x.html', 'file_base64': 'aGk='},
    {'file_name': 'x.mp3', 'file_base64': '%%%invalid'},
    {'file_name': 'x.mp3', 'file_base64': ''},
])
def test_media_001_invalid_upload_creates_no_artifact(client, payload):
    from app.models import DATA_DIR
    root = DATA_DIR / 'artifacts'
    before = set(root.iterdir())
    assert client.post('/api/artifacts/upload', json=payload).status_code == 422
    assert set(root.iterdir()) == before


def test_media_001_upload_limit_is_on_decoded_bytes(client):
    # Exercise both sides of the actual 20 MiB boundary, rather than a patched limit.
    content = b'a' * (20 * 1024 * 1024)
    response = client.post('/api/artifacts/upload', json={
        'file_name': 'limit.mp3', 'file_base64': base64.b64encode(content).decode(),
    })
    assert response.status_code == 201
    assert client.get(response.json()['url']).content == content
    response = client.post('/api/artifacts/upload', json={
        'file_name': 'oversize.mp3', 'file_base64': base64.b64encode(content + b'a').decode(),
    })
    assert response.status_code == 422


@pytest.mark.parametrize('url', ['https://example.com/private.mp3', 'file:///private.mp3',
                                '/artifacts/../private.mp3', '/artifacts/sub/file.mp3',
                                '/artifacts/sub\\file.mp3', '/artifacts/missing.mp3'])
def test_media_002_asr_local_resource_boundary(url):
    from app.artifacts import read_artifact
    with pytest.raises(ValueError):
        read_artifact(url, 'audio')


@pytest.mark.parametrize('business_code,expected_status', [(0, 200), (1008, 422)])
def test_lab_001_one_trial_never_retries_generation(client, monkeypatch, business_code, expected_status):
    client.post('/api/provider/save', json={
        'provider': 'minimax', 'base_url': 'https://example.com/v1', 'api_key': 'contract-test-key',
    })
    calls = []
    real_client = httpx.AsyncClient

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={
            'base_resp': {'status_code': business_code},
            'data': {'image_urls': ['https://example.com/image.png']},
        })

    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    response = client.post('/api/minimax/trial', json={'model': 'image-01', 'payload': {'prompt': '咖啡'}})
    assert response.status_code == expected_status, response.text
    assert len(calls) == 1
    assert calls[0].method == 'POST'
    assert calls[0].url.path == '/v1/image_generation'
    if expected_status == 200:
        assert response.json()['media'][0]['url'] == 'https://example.com/image.png'


def test_acceptance_default_http_transport_is_blocked():
    with httpx.Client() as upstream:
        with pytest.raises(AssertionError, match='Real HTTP is disabled'):
            upstream.get('https://example.invalid')

    async def check():
        async with httpx.AsyncClient() as upstream:
            with pytest.raises(AssertionError, match='Real HTTP is disabled'):
                await upstream.get('https://example.invalid')
    asyncio.run(check())
