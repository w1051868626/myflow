import asyncio
from time import perf_counter
from typing import cast

import httpx

from app.engine.graph import validate_graph
from app.models import Run, Session, emit, now
from app.nodes.runners import RUNNERS
from app.schemas import Graph, Node


def terminal_outputs(
    nodes: dict[str, Node], children: dict[str, set[str]], context: dict[str, dict[str, object]],
) -> dict[str, object]:
    outputs: dict[str, object] = {}
    for key in sorted(nodes):
        if children[key]:
            continue
        result = context[key]["output"]
        if nodes[key].type == "end":
            outputs.update(cast(dict[str, object], result))
        else:
            outputs[key] = result
    return outputs

# One ASGI worker owns all in-process execution tasks.
TASKS: dict[str, asyncio.Task] = {}


async def execute(run_id: str, graph: Graph, inputs: dict[str, str]) -> None:
    nodes, parents, children = validate_graph(graph)
    context, completed = {}, set()
    pending = set(nodes)
    active: dict[asyncio.Task, str] = {}
    semaphore = asyncio.Semaphore(4)

    def publish(kind: str, data: dict[str, object]) -> None:
        emit(run_id, kind, data)

    async def run_node(key: str) -> dict[str, object]:
        node = nodes[key]
        async with semaphore:
            started = perf_counter()
            publish("node_started", {"node_id": key})
            try:
                result, resolved_inputs = await RUNNERS[node.type].run(node, inputs, context, parents[key], publish)
                publish("node_finished", {
                    "node_id": key, "result": result, "inputs": resolved_inputs,
                    "elapsed_ms": round((perf_counter() - started) * 1000),
                })
                return result
            except asyncio.CancelledError:
                publish("node_cancelled", {"node_id": key, "elapsed_ms": round((perf_counter() - started) * 1000)})
                raise
            except Exception as exc:
                message = (
                    str(exc) if isinstance(exc, ValueError)
                    else "模型网络请求失败，请检查连接" if isinstance(exc, httpx.HTTPError)
                    else "节点执行异常，请检查参数及模型响应格式"
                )
                publish("node_failed", {
                    "node_id": key, "error": message,
                    "elapsed_ms": round((perf_counter() - started) * 1000),
                })
                raise ValueError(message) from exc

    status, error, outputs = "succeeded", None, {}
    publish("run_started", {"run_id": run_id})
    try:
        while pending or active:
            for key in sorted(pending.copy()):
                if parents[key] <= completed:
                    task = asyncio.create_task(run_node(key))
                    active[task] = key
                    pending.remove(key)
            done, _ = await asyncio.wait(active, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                key = active[task]
                context[key] = task.result()
                completed.add(key)
                del active[task]
        outputs = terminal_outputs(nodes, children, context)
    except asyncio.CancelledError:
        status, error = "cancelled", "运行已取消"
    except Exception as exc:
        status, error = "failed", str(exc)
    finally:
        for task in active:
            task.cancel()
        if active:
            await asyncio.gather(*active, return_exceptions=True)
        for key in sorted(set(nodes) - completed):
            publish("node_skipped", {"node_id": key})
        with Session.begin() as db:
            run = db.get(Run, run_id)
            run.status, run.error, run.outputs, run.finished_at = status, error, outputs, now()
        publish("run_finished", {"status": status, "error": error, "outputs": outputs})


def launch(run_id, graph, inputs):
    task = asyncio.create_task(execute(run_id, graph, inputs))
    TASKS[run_id] = task
    task.add_done_callback(lambda _: TASKS.pop(run_id, None))
