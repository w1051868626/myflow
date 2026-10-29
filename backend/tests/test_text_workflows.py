import copy
import json

import pytest
from fastapi.testclient import TestClient

from app.examples import example_graph, text_example_graph
from app.nodes.runners import RUNNERS
from app.schemas import Node


def text_node(id: str, value: str = 'hello') -> dict[str, object]:
    return {'id': id, 'type': 'text', 'data': {'text': value}, 'position': {'x': 0, 'y': 0}}


def create(client: TestClient, nodes: list[dict], edges: list[dict] | None = None) -> dict:
    response = client.post('/api/workflows', json={'name': '文本输入工作流', 'graph': {
        'nodes': nodes, 'edges': edges or [],
    }})
    assert response.status_code == 201, response.text
    return response.json()


def finish(client: TestClient, run_id: str) -> dict:
    response = client.post('/api/runs/events', json={'id': run_id})
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
    assert sum(event['type'] == 'run_finished' for event in events) == 1
    result = client.post('/api/runs/get', json={'id': run_id}).json()
    assert result['status'] == 'succeeded', result['error']
    return result


def test_text_source_and_multiple_terminals_without_start_or_end(client: TestClient) -> None:
    workflow = create(client, [text_node('one', '咖啡'), text_node('two', '清晨'),
        {'id': 'joined', 'type': 'template', 'data': {'template': '{{one.output}} / {{two.output}}'}},
        {'id': 'other', 'type': 'template', 'data': {'template': '独立末端'}},
    ], [{'id': 'a', 'source': 'one', 'target': 'joined'}, {'id': 'b', 'source': 'two', 'target': 'joined'}])
    response = client.post('/api/workflows/runs', json={'id': workflow['id']})
    assert response.status_code == 201, response.text
    result = finish(client, response.json()['id'])
    assert result['outputs'] == {'joined': '咖啡 / 清晨', 'other': '独立末端'}
    assert result['inputs'] == {'one.output': '咖啡', 'two.output': '清晨'}


def test_single_text_preserves_literal_braces_and_history(client: TestClient) -> None:
    workflow = create(client, [text_node('text', '  {{unknown.output}} 原文  ')])
    response = client.post('/api/workflows/runs', json={'id': workflow['id']})
    assert response.status_code == 201, response.text
    before = finish(client, response.json()['id'])
    assert before['outputs'] == {'text': '  {{unknown.output}} 原文  '}
    changed = copy.deepcopy(workflow['graph'])
    changed['nodes'][0]['data']['text'] = '编辑后'
    assert client.post('/api/workflows/save', json={
        'id': workflow['id'], 'name': workflow['name'], 'version': workflow['version'], 'graph': changed,
    }).status_code == 200
    assert client.post('/api/runs/get', json={'id': before['id']}).json() == before


@pytest.mark.parametrize('value', ['', '  ', 123, None])
def test_invalid_text_never_creates_a_run(client: TestClient, value: object) -> None:
    workflow = create(client, [{'id': 'text', 'type': 'text', 'data': {'text': value}}])
    assert client.post('/api/workflows/runs', json={'id': workflow['id']}).status_code == 422
    assert client.post('/api/workflows/runs/list', json={'id': workflow['id']}).json() == []


def test_leaf_audio_and_video_are_both_collected(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    class Media:
        async def run(self, node: Node, *args: object) -> tuple[dict, dict]:
            kind = 'audio' if node.type == 'speech' else 'video'
            media = {'kind': kind, 'url': f'/artifacts/mock.{kind}'}
            return {'output': media, 'url': media['url']}, {}

    monkeypatch.setitem(RUNNERS, 'speech', Media())
    monkeypatch.setitem(RUNNERS, 'video', Media())
    workflow = create(client, [text_node('text'), {'id': 'speech', 'type': 'speech'},
        {'id': 'video', 'type': 'video'}], [
        {'id': 'a', 'source': 'text', 'target': 'speech'}, {'id': 'b', 'source': 'text', 'target': 'video'},
    ])
    response = client.post('/api/workflows/runs', json={'id': workflow['id']})
    assert response.status_code == 201, response.text
    outputs = finish(client, response.json()['id'])['outputs']
    assert outputs == {'speech': {'kind': 'audio', 'url': '/artifacts/mock.audio'},
                       'video': {'kind': 'video', 'url': '/artifacts/mock.video'}}


def test_legacy_end_and_independent_text_terminal_coexist(client: TestClient) -> None:
    graph = example_graph(demo=True)
    graph['nodes'].append(text_node('extra', '独立文本'))
    workflow = create(client, graph['nodes'], graph['edges'])
    response = client.post('/api/workflows/runs', json={'id': workflow['id'], 'inputs': {'topic': '咖啡'}})
    assert response.status_code == 201, response.text
    outputs = finish(client, response.json()['id'])['outputs']
    assert set(outputs) == {'image', 'template', 'extra'}
    assert outputs['extra'] == '独立文本'


@pytest.mark.parametrize('defect', ['cycle', 'incoming_text', 'unknown_field', 'unconnected_reference', 'extra_input'])
def test_text_graph_validation_still_rejects_invalid_requests(client: TestClient, defect: str) -> None:
    nodes = [text_node('text'), {'id': 'joined', 'type': 'template', 'data': {'template': '{{text.output}}'}}]
    edges = [{'id': 'a', 'source': 'text', 'target': 'joined'}]
    inputs = {}
    if defect in ('cycle', 'incoming_text'):
        edges.append({'id': 'b', 'source': 'joined', 'target': 'text'})
    elif defect == 'unknown_field':
        nodes[1]['data']['template'] = '{{text.url}}'
    elif defect == 'unconnected_reference':
        edges = []
    else:
        inputs = {'topic': 'unexpected'}
    workflow = create(client, nodes, edges)
    assert client.post('/api/workflows/runs', json={'id': workflow['id'], 'inputs': inputs}).status_code == 422
    assert client.post('/api/workflows/runs/list', json={'id': workflow['id']}).json() == []


@pytest.mark.parametrize('reference,expected_status', [('{{a.one}} / {{b.two}}', 201), ('{{a.two}}', 422)])
def test_multiple_legacy_sources_keep_their_own_fields(
    client: TestClient, reference: str, expected_status: int,
) -> None:
    workflow = create(client, [
        {'id': 'a', 'type': 'start', 'data': {'fields': 'one'}},
        {'id': 'b', 'type': 'start', 'data': {'fields': 'two'}},
        {'id': 'joined', 'type': 'template', 'data': {'template': reference}},
    ], [{'id': 'a-joined', 'source': 'a', 'target': 'joined'},
        {'id': 'b-joined', 'source': 'b', 'target': 'joined'}])
    response = client.post('/api/workflows/runs', json={'id': workflow['id'], 'inputs': {'one': 'A', 'two': 'B'}})
    assert response.status_code == expected_status, response.text
    if expected_status == 201:
        assert finish(client, response.json()['id'])['outputs'] == {'joined': 'A / B'}
    else:
        assert client.post('/api/workflows/runs/list', json={'id': workflow['id']}).json() == []


def test_new_example_runs_without_start_end_or_external_inputs(client: TestClient) -> None:
    graph = text_example_graph(demo=True)
    assert all(node['type'] not in ('start', 'end') for node in graph['nodes'])
    workflow = create(client, graph['nodes'], graph['edges'])
    response = client.post('/api/workflows/runs', json={'id': workflow['id']})
    assert response.status_code == 201, response.text
    result = finish(client, response.json()['id'])
    assert set(result['outputs']) == {'image', 'template'}
    assert result['inputs'] == {'text.output': '一杯咖啡里的慢生活'}
