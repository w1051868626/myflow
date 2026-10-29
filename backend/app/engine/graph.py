import re

from app.schemas import Graph

REFERENCE = re.compile(r"{{\s*([a-zA-Z][a-zA-Z0-9_]*)\.([a-zA-Z][a-zA-Z0-9_]*)\s*}}")
FIELD_NAME = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")


def input_fields(node):
    raw = node.data.get("fields", "topic")
    if not isinstance(raw, str):
        raise ValueError("开始节点的 fields 必须是文本")
    fields = [s.strip() for s in raw.split(",") if s.strip()]
    if not fields or len(fields) != len(set(fields)) or any(not FIELD_NAME.fullmatch(s) or s == "output" for s in fields):
        raise ValueError("开始节点输入字段必须唯一，使用英文字母、数字或下划线，且不能为 output")
    return fields


def validate_graph(graph: Graph):
    nodes = {node.id: node for node in graph.nodes}
    if len(nodes) != len(graph.nodes):
        raise ValueError("节点 ID 不能重复")
    starts = [n for n in graph.nodes if n.type == "start"]
    ends = [n for n in graph.nodes if n.type == "end"]
    if len(starts) != 1 or len(ends) != 1:
        raise ValueError("工作流需要且只能有一个开始节点和一个输出节点")
    fields = input_fields(starts[0])
    parents = {key: set() for key in nodes}
    children = {key: set() for key in nodes}
    seen = set()
    for edge in graph.edges:
        if edge.source not in nodes or edge.target not in nodes:
            raise ValueError("连线引用了不存在的节点")
        pair = (edge.source, edge.target)
        if pair in seen:
            raise ValueError("不能重复连线")
        seen.add(pair)
        src, dst = nodes[edge.source], nodes[edge.target]
        if src.type == "end" or dst.type == "start" or src.id == dst.id:
            raise ValueError("开始节点只能输出，结束节点只能接收，节点不能连接自身")
        if src.type == "image" and dst.type != "end":
            raise ValueError("MVP 的图像输出只能接到输出节点")
        parents[dst.id].add(src.id)
        children[src.id].add(dst.id)
    remaining = {key: len(value) for key, value in parents.items()}
    ready = [key for key, count in remaining.items() if count == 0]
    order, ancestors = [], {key: set() for key in nodes}
    while ready:
        key = ready.pop(0)
        order.append(key)
        for child in sorted(children[key]):
            ancestors[child].update(ancestors[key] | {key})
            remaining[child] -= 1
            if not remaining[child]:
                ready.append(child)
    if len(order) != len(nodes):
        raise ValueError("工作流不能包含循环")
    for node in graph.nodes:
        if node.id != starts[0].id and starts[0].id not in ancestors[node.id]:
            raise ValueError(f"节点 {node.id} 无法从开始节点到达")
        if node.id != ends[0].id and node.id not in ancestors[ends[0].id]:
            raise ValueError(f"节点 {node.id} 未连接到输出节点")
        for key in ("fields", "system", "prompt", "template", "model", "size"):
            if key in node.data and not isinstance(node.data[key], str):
                raise ValueError(f"节点 {node.id} 的 {key} 必须是文本")
        for key in ("system", "prompt", "template"):
            value = node.data.get(key, "")
            if "{{" in REFERENCE.sub("", value) or "}}" in REFERENCE.sub("", value):
                raise ValueError(f"节点 {node.id} 的变量格式应为 {{{{node.output}}}}")
            for source, field in REFERENCE.findall(value):
                if source not in ancestors[node.id]:
                    raise ValueError(f"{node.id} 只能引用已连接的上游节点：{source}")
                allowed = fields + ["output"] if nodes[source].type == "start" else ["output"]
                if field not in allowed or nodes[source].type == "image":
                    raise ValueError(f"不支持的文本变量：{source}.{field}")
    return nodes, parents, children


def render(template, context):
    def replace(match):
        source, field = match.groups()
        if source not in context or field not in context[source]:
            raise ValueError(f"变量不存在：{source}.{field}")
        return str(context[source][field])
    return REFERENCE.sub(replace, template)
