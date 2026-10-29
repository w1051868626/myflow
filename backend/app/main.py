import asyncio
import json
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import JsonValue
from sqlalchemy import select, update

from app.artifacts import upload

from app.engine.executor import TASKS, launch
from app.engine.graph import input_fields, validate_graph
from app.examples import example_graph
from app.models import Base, DATA_DIR, Event, Run, Session, Workflow, emit, engine, now, run_dict
from app.nodes.registry import NODE_REGISTRY
from app.providers.client import catalog, cipher, provider_setting, save_provider
from app.providers.minimax import check_report, presets, query_video, request_json, trial
from app.providers.types import RequestOptions
from app.schemas import ArtifactUpload, EventsRequest, Graph, IdRequest, ModelTrial, ProviderRead, ProviderWrite, VideoQuery, WorkflowRun, WorkflowSave, WorkflowWrite


@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    cipher()
    with Session.begin() as db:
        for run in db.scalars(select(Run).where(Run.status == "running")):
            run.status, run.error, run.finished_at = "interrupted", "服务重启导致运行中断，请重新运行", now()
            db.add(Event(run_id=run.id, type="run_finished", data={"status": run.status, "error": run.error, "outputs": {}}))
        if not db.scalar(select(Workflow.id).limit(1)):
            db.add(Workflow(id=uuid4().hex, name="从灵感到图文", graph=example_graph()))
    yield
    tasks = list(TASKS.values())
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="MyFlow", lifespan=lifespan)
app.mount("/artifacts", StaticFiles(directory=DATA_DIR / "artifacts"), name="artifacts")


@app.exception_handler(ValueError)
async def invalid_value(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=422, content={"detail": str(exc)})


def get_workflow(db, id):
    workflow = db.get(Workflow, id)
    if workflow is None:
        raise HTTPException(404, "工作流不存在")
    return workflow


def workflow_dict(workflow):
    return {key: getattr(workflow, key) for key in ("id", "name", "graph", "version", "updated_at")}


def get_run(db, id):
    run = db.get(Run, id)
    if run is None:
        raise HTTPException(404, "运行记录不存在")
    return run


@app.post("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/nodes")
def node_types():
    return NODE_REGISTRY


@app.post("/api/artifacts/upload", status_code=201)
def upload_artifact(body: ArtifactUpload):
    return upload(body.file_name, body.file_base64)


@app.post("/api/models")
def models():
    return catalog()


@app.post("/api/minimax/catalog")
def minimax_catalog():
    return presets()


@app.post("/api/minimax/checks")
def minimax_checks():
    return check_report()


@app.post("/api/minimax/discover")
async def minimax_discover() -> dict[str, JsonValue]:
    return await request_json("minimax_text", "v1", "models", RequestOptions(method="GET"))


@app.post("/api/minimax/trial")
async def minimax_trial(body: ModelTrial):
    return await trial(body.model, body.payload, body.file_base64, body.file_name)


@app.post("/api/minimax/video/query")
async def minimax_video_query(body: VideoQuery):
    return await query_video(body.task_id, body.api_version)


@app.post("/api/provider/get")
def provider(body: ProviderRead = Body(default=ProviderRead())):
    return provider_setting(body.provider)


@app.post("/api/provider/save")
def configure(body: ProviderWrite):
    save_provider(body.base_url, body.api_key, body.provider)
    return provider_setting(body.provider)


@app.post("/api/workflows/list")
def workflows():
    with Session() as db:
        return [workflow_dict(w) for w in db.scalars(select(Workflow).order_by(Workflow.updated_at.desc()))]


@app.post("/api/workflows", status_code=201)
def create(body: WorkflowWrite):
    # Drafts may be incomplete; execution performs full DAG validation.
    with Session.begin() as db:
        workflow = Workflow(id=uuid4().hex, name=body.name, graph=body.graph.model_dump())
        db.add(workflow)
        db.flush()
        return workflow_dict(workflow)


@app.post("/api/workflows/get")
def read(body: IdRequest):
    with Session() as db:
        return workflow_dict(get_workflow(db, body.id))


@app.post("/api/workflows/save")
def save(body: WorkflowSave):
    id = body.id
    with Session.begin() as db:
        get_workflow(db, id)
        result = db.execute(update(Workflow).where(Workflow.id == id, Workflow.version == body.version).values(
            name=body.name, graph=body.graph.model_dump(), version=Workflow.version + 1, updated_at=now()))
        if not result.rowcount:
            raise HTTPException(409, "工作流已被更新，请刷新后重试")
        db.expire_all()
        return workflow_dict(get_workflow(db, id))


@app.post("/api/workflows/delete", status_code=204)
def delete(body: IdRequest):
    with Session.begin() as db:
        db.delete(get_workflow(db, body.id))


@app.post("/api/workflows/runs", status_code=201)
async def start(body: WorkflowRun):
    id = body.id
    with Session.begin() as db:
        workflow = get_workflow(db, id)
        graph = Graph.model_validate(workflow.graph)
        validate_graph(graph)
        fields = input_fields(next(n for n in graph.nodes if n.type == "start"))
        if set(fields) != set(body.inputs) or any(not body.inputs[key].strip() for key in fields):
            raise ValueError(f"请填写所有输入字段：{', '.join(fields)}")
        run = Run(id=uuid4().hex, workflow_id=id, workflow_version=workflow.version, graph=workflow.graph, inputs=body.inputs)
        db.add(run)
        db.flush()
        result = run_dict(run)
    launch(run.id, graph, body.inputs)
    await asyncio.sleep(0)
    return result


@app.post("/api/workflows/runs/list")
def history(body: IdRequest):
    with Session() as db:
        return [run_dict(run) for run in db.scalars(select(Run).where(Run.workflow_id == body.id).order_by(Run.created_at.desc()).limit(50))]


@app.post("/api/runs/get")
def detail(body: IdRequest):
    with Session() as db:
        return run_dict(get_run(db, body.id))


@app.post("/api/runs/cancel")
async def cancel(body: IdRequest):
    id = body.id
    with Session() as db:
        run = get_run(db, id)
        status = run.status
    task = TASKS.get(id)
    if task and not task.done():
        task.cancel()
    return {"status": status, "cancellation_requested": bool(task)}


@app.post("/api/runs/events")
async def events(body: EventsRequest, request: Request):
    id = body.id
    with Session() as db:
        get_run(db, id)
    cursor = body.after

    async def stream():
        nonlocal cursor
        ticks = 0
        while not await request.is_disconnected():
            with Session() as db:
                rows = list(db.scalars(select(Event).where(Event.run_id == id, Event.id > cursor).order_by(Event.id).limit(200)))
                status = get_run(db, id).status
            for event in rows:
                cursor = event.id
                yield f"id: {event.id}\ndata: {json.dumps({'type': event.type, 'data': event.data, 'created_at': event.created_at}, ensure_ascii=False)}\n\n"
                if event.type == "run_finished":
                    return
            if status != "running" and not rows:
                yield f"data: {json.dumps({'type': 'stream_closed', 'data': {'status': status}})}\n\n"
                return
            ticks += 1
            if ticks % 50 == 0:
                yield ": heartbeat\n\n"
            await asyncio.sleep(0.2)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
