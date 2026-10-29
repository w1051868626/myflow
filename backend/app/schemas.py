from typing import Any, Literal

from pydantic import BaseModel, Field


class Node(BaseModel):
    id: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_]*$", max_length=64)
    type: Literal["text", "start", "llm", "image", "speech", "music", "video", "asr", "template", "end"]
    position: dict[str, float] = Field(default_factory=lambda: {"x": 0, "y": 0})
    data: dict[str, Any] = Field(default_factory=dict)


class Edge(BaseModel):
    id: str
    source: str
    target: str


class Graph(BaseModel):
    nodes: list[Node] = Field(max_length=100)
    edges: list[Edge] = Field(max_length=500)


class WorkflowWrite(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    graph: Graph
    version: int | None = None


class RunRequest(BaseModel):
    inputs: dict[str, str] = Field(default_factory=dict)


class ProviderWrite(BaseModel):
    provider: Literal["deepseek", "minimax", "minimax_text", "openai"] = "deepseek"
    base_url: str
    api_key: str = ""


class ProviderRead(BaseModel):
    provider: Literal["deepseek", "minimax", "minimax_text", "openai"] = "deepseek"


class ModelTrial(BaseModel):
    model: str = Field(min_length=1, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)
    file_base64: str | None = Field(default=None, max_length=28_000_000)
    file_name: str = "audio.mp3"


class VideoQuery(BaseModel):
    task_id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$", max_length=128)
    api_version: Literal["v1", "v2"] = "v2"


class IdRequest(BaseModel):
    id: str = Field(min_length=1, max_length=128)


class WorkflowSave(WorkflowWrite, IdRequest):
    pass


class WorkflowRun(RunRequest, IdRequest):
    pass


class EventsRequest(IdRequest):
    after: int = Field(default=0, ge=0)


class ArtifactUpload(BaseModel):
    file_name: str = Field(min_length=1, max_length=255)
    file_base64: str = Field(min_length=1, max_length=28_000_000)
