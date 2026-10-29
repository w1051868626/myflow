"""Local checks for known playground inputs; unknown provider options pass through."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StringConstraints

from app.providers.types import ModelPreset

NonBlank = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]
PositiveInt = Annotated[StrictInt, Field(gt=0)]


class Options(BaseModel):
    model_config = ConfigDict(extra="allow")
    stream: Literal[False] = False


class Voice(Options):
    voice_id: NonBlank | None = None
    speed: Annotated[float, Field(strict=True, ge=0.5, le=2, allow_inf_nan=False)] = 1


class Speech(Options):
    text: Annotated[NonBlank, Field(max_length=9999)]
    voice_setting: Voice = Field(default_factory=Voice)
    output_format: Literal["hex", "url"] = "hex"


class Message(Options):
    role: NonBlank
    content: NonBlank | list[dict[str, object]] | None = None


class Text(Options):
    messages: Annotated[list[Message], Field(min_length=1)]
    max_completion_tokens: PositiveInt | None = None
    max_tokens: PositiveInt | None = None


class Image(Options):
    prompt: Annotated[NonBlank, Field(max_length=1500)]
    n: PositiveInt = 1
    width: PositiveInt | None = None
    height: PositiveInt | None = None


class Music(Options):
    prompt: NonBlank | None = None
    lyrics: NonBlank | None = None
    is_instrumental: StrictBool = True
    audio_url: NonBlank | None = None
    audio_base64: NonBlank | None = None
    cover_feature_id: NonBlank | None = None


class VideoContent(Options):
    type: NonBlank
    text: NonBlank | None = None
    image_url: dict[str, object] | None = None


class Subject(Options):
    image: Annotated[list[NonBlank], Field(min_length=1)]


class Video(Options):
    prompt: NonBlank | None = None
    content: Annotated[list[VideoContent], Field(min_length=1)] | None = None
    duration: StrictInt | None = None
    resolution: NonBlank | None = None
    first_frame_image: NonBlank | None = None
    subject_reference: Annotated[list[Subject], Field(min_length=1)] | None = None


H3_RESOLUTIONS = {
    "MiniMax-H3": {"768P", "2K"},
    "MiniMax-H3-Highspeed": {"768P"},
    "MiniMax-H3-Lite": {"480P", "768P"},
    "MiniMax-H3-Max": {"480P", "768P"},
}


def validate_video(model: str, version: str, body: Video) -> None:
    if version == "v2":
        validate_h3(model, body)
        return
    validate_legacy_video(model, body)


def validate_h3(model: str, body: Video) -> None:
    if not body.content:
        raise ValueError("视频 content 不能为空")
    duration = body.duration if body.duration is not None else 5
    resolution = body.resolution if body.resolution is not None else "768P"
    validate_video_dimensions(model, "v2", duration, resolution)


def validate_legacy_video(model: str, body: Video) -> None:
    if not body.prompt:
        raise ValueError("视频 prompt 不能为空")
    hailuo = model.startswith("MiniMax-Hailuo-")
    duration = body.duration if body.duration is not None else 6
    resolution = body.resolution if body.resolution is not None else "768P" if hailuo else "720P"
    validate_video_dimensions(model, "v1", duration, resolution)


def validate_video_dimensions(model: str, version: str, duration: int, resolution: str) -> None:
    if version == "v2":
        minimum = 5 if model == "MiniMax-H3-Max" else 4
        if resolution not in H3_RESOLUTIONS[model] or not minimum <= duration <= 15:
            raise ValueError("当前 H3 模型不支持所选分辨率或时长，请调整参数")
        return
    hailuo = model.startswith("MiniMax-Hailuo-")
    resolutions = {"768P", "1080P"} if hailuo else {"720P", "1080P"}
    durations = {6, 10} if hailuo and resolution == "768P" else {6}
    if resolution not in resolutions or duration not in durations:
        raise ValueError("当前旧版视频模型不支持所选分辨率或时长，通常需 6 秒及 720P/768P")


def validate_music(body: Music, reference: str | None) -> None:
    if reference == "audio":
        if not (body.audio_url or body.audio_base64 or body.cover_feature_id):
            raise ValueError("翻唱模型需要参考音频")
        return
    if not body.prompt:
        raise ValueError("音乐 prompt 不能为空")
    if not body.is_instrumental and not body.lyrics:
        raise ValueError("歌曲生成需要歌词，或选择纯音乐")


def validate_trial(config: ModelPreset, payload: dict[str, object]) -> None:
    kind = config["kind"]
    validators = {"text": Text, "image": Image, "speech": Speech, "music": Music, "video": Video}
    validator = validators.get(kind)
    if validator is None:
        Options.model_validate(payload)
        return
    body = validator.model_validate(payload)
    if isinstance(body, Music):
        validate_music(body, config.get("reference"))
    if isinstance(body, Video):
        validate_video(config["id"], config.get("api_version", "v1"), body)
        reference = config.get("reference")
        if reference == "image" and not body.first_frame_image:
            raise ValueError("此模型需要 first_frame_image 参考图片")
        if reference == "subject" and not body.subject_reference:
            raise ValueError("此模型需要 subject_reference 人物参考图片")
