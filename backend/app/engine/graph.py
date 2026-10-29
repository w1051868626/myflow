from collections.abc import Mapping
import re

from app.schemas import Edge, Graph, Node
from app.nodes.registry import NODE_REGISTRY

REFERENCE = re.compile(r"{{\s*([a-zA-Z][a-zA-Z0-9_]*)\.([a-zA-Z][a-zA-Z0-9_]*)\s*}}")
FIELD_NAME = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
MEDIA_TARGETS = {
    "image": {"video", "end"},
    "speech": {"asr", "music", "end"},
    "music": {"asr", "music", "end"},
    "video": {"end"},
}
LEGACY_TEMPLATES = {"system", "prompt", "template", "lyrics", "audio_url", "image_url"}
MEDIA_NODES = {"speech", "music", "video", "asr"}


def input_fields(node: Node) -> list[str]:
    raw = node.data.get("fields", "topic")
    if not isinstance(raw, str):
        raise ValueError("开始节点的 fields 必须是文本")
    fields = [s.strip() for s in raw.split(",") if s.strip()]
    invalid_names = any(not FIELD_NAME.fullmatch(s) or s == "output" for s in fields)
    if not fields or len(fields) != len(set(fields)) or invalid_names:
        raise ValueError("开始节点输入字段必须唯一，使用英文字母、数字或下划线，且不能为 output")
    return fields


def validate_references(
    node: Node, nodes: dict[str, Node], ancestors: set[str],
) -> None:
    properties = NODE_REGISTRY[node.type]["properties"]
    keys = LEGACY_TEMPLATES | set(properties) | {"label"}
    for key in keys:
        if key in node.data and not isinstance(node.data[key], str):
            raise ValueError(f"节点 {node.id} 的 {key} 必须是文本")
    rendered = LEGACY_TEMPLATES | (set(properties) if node.type in MEDIA_NODES else set())
    for key in rendered:
        value = node.data.get(key, "")
        for source, field in parse_references(value, node.id):
            if source not in ancestors:
                raise ValueError(f"{node.id} 只能引用已连接的上游节点：{source}")
            allowed = reference_fields(nodes[source])
            if field not in allowed:
                raise ValueError(f"不支持的变量：{source}.{field}，媒体资源请引用 .url")


def parse_references(value: str, node_id: str) -> list[tuple[str, str]]:
    remainder = REFERENCE.sub("", value)
    if "{{" in remainder or "}}" in remainder:
        raise ValueError(f"节点 {node_id} 的变量格式应为 {{{{node.output}}}}")
    return REFERENCE.findall(value)


def reference_fields(node: Node) -> list[str]:
    if node.type == "start":
        return input_fields(node) + ["output"]
    return ["url"] if node.type in MEDIA_TARGETS else ["output"]


def validate_graph(graph: Graph) -> tuple[dict[str, Node], dict[str, set[str]], dict[str, set[str]]]:
    nodes = {node.id: node for node in graph.nodes}
    if len(nodes) != len(graph.nodes):
        raise ValueError("节点 ID 不能重复")
    if not nodes:
        raise ValueError("工作流至少需要一个节点")
    parents, children = graph_links(graph.edges, nodes)
    ancestors = graph_ancestors(parents, children)
    for node in graph.nodes:
        validate_references(node, nodes, ancestors[node.id])
        if node.type == "start":
            input_fields(node)
        if node.type == "text" and not node.data.get("text", "").strip():
            raise ValueError(f"请填写文本节点 {node.id} 的文本内容")
    return nodes, parents, children


def validate_edge(edge: Edge, nodes: dict[str, Node], seen: set[tuple[str, str]]) -> None:
    if edge.source not in nodes or edge.target not in nodes:
        raise ValueError("连线引用了不存在的节点")
    if (edge.source, edge.target) in seen:
        raise ValueError("不能重复连线")
    src, dst = nodes[edge.source], nodes[edge.target]
    if src.type == "end" or dst.type in ("start", "text") or src.id == dst.id:
        raise ValueError("文本输入/开始节点只能输出，输出节点只能接收，节点不能连接自身")
    if src.type in MEDIA_TARGETS and dst.type not in MEDIA_TARGETS[src.type]:
        raise ValueError(f"{NODE_REGISTRY[src.type]['title']}不能连接到{NODE_REGISTRY[dst.type]['title']}")


def graph_links(
    edges: list[Edge], nodes: dict[str, Node],
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    parents = {key: set() for key in nodes}
    children = {key: set() for key in nodes}
    seen = set()
    for edge in edges:
        validate_edge(edge, nodes, seen)
        seen.add((edge.source, edge.target))
        parents[edge.target].add(edge.source)
        children[edge.source].add(edge.target)
    return parents, children


def graph_ancestors(parents: dict[str, set[str]], children: dict[str, set[str]]) -> dict[str, set[str]]:
    remaining = {key: len(value) for key, value in parents.items()}
    ready = [key for key, count in remaining.items() if count == 0]
    order, ancestors = [], {key: set() for key in parents}
    while ready:
        key = ready.pop(0)
        order.append(key)
        for child in sorted(children[key]):
            ancestors[child].update(ancestors[key] | {key})
            remaining[child] -= 1
            if not remaining[child]:
                ready.append(child)
    if len(order) != len(parents):
        raise ValueError("工作流不能包含循环")
    return ancestors


def run_input_snapshot(graph: Graph, inputs: dict[str, str]) -> dict[str, str]:
    fields = {field for node in graph.nodes if node.type == "start" for field in input_fields(node)}
    if set(inputs) != fields or any(not value.strip() for value in inputs.values()):
        raise ValueError(f"请精确填写输入字段：{', '.join(sorted(fields))}")
    text_inputs = {f"{node.id}.output": node.data["text"] for node in graph.nodes if node.type == "text"}
    return {**inputs, **text_inputs}


def render(template: str, context: Mapping[str, Mapping[str, object]]) -> str:
    def replace(match: re.Match[str]) -> str:
        source, field = match.groups()
        if source not in context or field not in context[source]:
            raise ValueError(f"变量不存在：{source}.{field}")
        return str(context[source][field])
    return REFERENCE.sub(replace, template)
