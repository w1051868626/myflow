"""Named data contracts shared by the playground and media node adapters."""

from dataclasses import dataclass
from typing import Literal, NotRequired, TypedDict

from pydantic import JsonValue


@dataclass(frozen=True)
class RequestOptions:
    method: Literal["GET", "POST"] = "POST"
    payload: dict[str, JsonValue] | None = None
    params: dict[str, str | int] | None = None
    files: dict[str, tuple[str, bytes, str]] | None = None


class Media(TypedDict):
    kind: str
    url: str
    temporary: NotRequired[bool]
    task_id: NotRequired[str]
    api_version: NotRequired[str]


class GeneratedMedia(TypedDict):
    result: dict[str, JsonValue]
    media: list[Media]


class TrialResult(GeneratedMedia):
    model: str
    kind: str
    api_version: str


class ModelPreset(TypedDict):
    id: str
    kind: str
    provider: str
    payload: dict[str, JsonValue]
    api_version: NotRequired[str]
    reference: NotRequired[str]
