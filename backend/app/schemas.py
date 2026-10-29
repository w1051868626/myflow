from typing import Any, Literal

from pydantic import BaseModel, Field


class Node(BaseModel):
    id: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_]*$", max_length=64)
    type: Literal["start", "llm", "image", "template", "end"]
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
    base_url: str
    api_key: str = ""
