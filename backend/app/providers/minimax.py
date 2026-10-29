"""MiniMax model playground. Endpoint selection is server-owned, all inputs use JSON."""
import base64
import copy
from pathlib import Path
from uuid import uuid4

import httpx
from pydantic import JsonValue

from app.models import DATA_DIR
from app.providers.client import catalog, connection
from app.providers.types import GeneratedMedia, Media, ModelPreset, RequestOptions, TrialResult
from app.providers.validation import validate_trial


DOCS = "https://platform.minimax.cn/docs/api-reference/"


def check_report() -> dict[str, JsonValue]:
    path = Path(__file__).resolve().parents[3] / "docs" / "minimax-model-check.json"
    if not path.exists():
        return {"models": [], "pending": []}
    try:
        import json
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {"models": [], "pending": []}


def presets() -> list[ModelPreset]:
    entries = []
    for model in catalog():
        if model["provider"] not in ("minimax", "minimax_text"):
            continue
        item = dict(model)
        kind = model["kind"]
        if kind == "text":
            payload = {
                "messages": [{"role": "user", "content": "用一句话描述清晨的咖啡。"}],
                "max_completion_tokens": 512, "stream": False, "reasoning_split": True,
            }
            doc = "text-chat-openai"
        elif kind == "image":
            payload = {
                "prompt": "A cup of coffee in soft morning light", "aspect_ratio": "1:1",
                "n": 1, "response_format": "base64",
            }
            doc = "image-generation-t2i"
        elif kind == "speech":
            payload = {"text": "你好，欢迎来到 MyFlow。", "stream": False, "output_format": "hex",
                       "voice_setting": {"voice_id": "male-qn-qingse", "speed": 1, "vol": 1, "pitch": 0},
                       "audio_setting": {"sample_rate": 32000, "bitrate": 128000, "format": "mp3"}}
            doc = "speech-t2a-http"
        elif kind == "music":
            payload = {"prompt": "轻快的钢琴与吉他，温暖宁静的清晨咖啡馆", "stream": False, "output_format": "hex",
                       "audio_setting": {"sample_rate": 44100, "bitrate": 128000, "format": "mp3"}}
            if model.get("reference") == "audio":
                payload["audio_url"] = ""
            else:
                payload["is_instrumental"] = True
            doc = "music-generation"
        elif kind == "video":
            payload, doc = video_preset(model)
        elif kind == "asr":
            payload = {"response_format": "json", "stream": False}
            doc = "speech-to-text"
        else:
            continue
        item.update(payload={"model": model["id"], **payload}, docs=DOCS + doc)
        entries.append(item)
    return entries


def video_preset(model: ModelPreset) -> tuple[dict[str, JsonValue], str]:
    if model.get("api_version") == "v2":
        payload = {
            "content": [{"type": "text", "text": "A cup of steaming coffee in morning sunlight, static camera"}],
            "resolution": "768P", "duration": 5, "ratio": "16:9",
        }
        doc = "video-generation-v2-create"
    else:
        payload = {
            "prompt": "A cup of steaming coffee in morning sunlight, static camera",
            "duration": 6, "resolution": "768P",
        }
        if model["id"] in ("T2V-01", "T2V-01-Director", "S2V-01") or model["id"].startswith("I2V-"):
            payload["resolution"] = "720P"
        if model.get("reference") == "image":
            payload["first_frame_image"] = ""
        if model.get("reference") == "subject":
            payload["subject_reference"] = [{"type": "character", "image": [""]}]
        video_docs = {"subject": "video-generation-s2v", "image": "video-generation-i2v"}
        doc = video_docs.get(model.get("reference"), "video-generation-t2v")
    return payload, doc


def api_url(base: str, version: str, path: str) -> str:
    # Keep proxy prefixes, replacing only a trailing API version.
    root = base.rstrip("/")
    if root.endswith(("/v1", "/v2")):
        root = root.rsplit("/", 1)[0]
    return f"{root}/{version}/{path}"


async def request_json(
    provider: str, version: str, path: str, options: RequestOptions | None = None,
) -> dict[str, JsonValue]:
    """Send exactly one request using either JSON or multipart options."""
    options = options or RequestOptions()
    base, key = connection(provider)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=15)) as client:
            kwargs = (
                {"data": options.payload, "files": options.files}
                if options.files else {"json": options.payload}
            )
            response = await client.request(
                options.method, api_url(base, version, path), headers={"Authorization": f"Bearer {key}"},
                params=options.params, **kwargs,
            )
            return response_json(response, key)
    except httpx.TimeoutException:
        raise ValueError("MiniMax 请求超时；上游可能仍在生成，请勿自动重复提交") from None
    except httpx.HTTPError:
        raise ValueError("无法连接 MiniMax，请检查服务地址和网络") from None


def response_json(response: httpx.Response, key: str) -> dict[str, JsonValue]:
    try:
        result = response.json()
    except ValueError:
        raise ValueError(f"MiniMax 返回非 JSON 响应（HTTP {response.status_code}）") from None
    if response.is_error or result.get("error") or result.get("base_resp", {}).get("status_code", 0) != 0:
        error = result.get("error") or result.get("base_resp") or {}
        detail = error.get("message") or error.get("status_msg") if isinstance(error, dict) else str(error)
        message = str(detail or '请检查模型权限、余额和参数').replace(key, '[已隐藏]')[:500]
        raise ValueError(f"MiniMax 请求失败（HTTP {response.status_code}）：{message}")
    return result


def save_media(content: bytes, ext: str, kind: str) -> Media:
    """Persist generated bytes under a random artifact name and return its public URL."""
    name = f"{uuid4().hex}.{ext}"
    (DATA_DIR / "artifacts" / name).write_bytes(content)
    return {"kind": kind, "url": f"/artifacts/{name}"}


def normalize(result: dict[str, JsonValue], kind: str, payload: dict[str, JsonValue]) -> GeneratedMedia:
    """Copy the response and persist embedded media without mutating the caller's data."""
    result = copy.deepcopy(result)
    media = []
    data = result.get("data")
    if isinstance(data, dict):
        media.extend(image_resources(data))
        data.pop("image_base64", None)
        if kind in ("speech", "music"):
            audio = audio_resource(data, payload)
            if audio is not None:
                media.append(audio)
                data["audio"] = audio["url"]
    task = result.get("task") or {}
    url = (task.get("content") or {}).get("url")
    if isinstance(url, str) and url.startswith(("https://", "http://")):
        media.append({"kind": "video", "url": url, "temporary": True})
    if kind in ("image", "speech", "music") and not media:
        raise ValueError("MiniMax 未返回可用的生成资源，请检查响应及内容审核结果")
    return {"result": result, "media": media}


def image_resources(data: dict[str, JsonValue]) -> list[Media]:
    media: list[Media] = []
    for encoded in data.get("image_base64", []) or []:
        content = base64.b64decode(encoded, validate=True)
        ext = image_extension(content)
        if ext is None:
            raise ValueError("MiniMax 返回了不支持的图片格式")
        media.append(save_media(content, ext, "image"))
    for url in data.get("image_urls", []) or []:
        if isinstance(url, str) and url.startswith(("https://", "http://")):
            media.append({"kind": "image", "url": url, "temporary": True})
    return media


async def trial(
    model: str, payload: dict[str, JsonValue], file_base64: str | None = None, file_name: str = "audio.mp3",
) -> TrialResult:
    config = next((m for m in presets() if m["id"] == model), None)
    if config is None:
        raise ValueError("模型不在 MiniMax 试验目录中")
    validate_trial(config, payload)
    body = copy.deepcopy(payload)
    body["model"] = model
    if body.get("stream"):
        raise ValueError("试验台请使用 stream: false；工作流文本节点支持流式输出")
    if config["kind"] in ("text", "speech", "music", "asr"):
        body["stream"] = False
    kind = config["kind"]
    version = config.get("api_version", "v1")
    endpoint = {
        "text": "chat/completions", "image": "image_generation", "speech": "t2a_v2",
        "music": "music_generation", "video": "video_generation", "asr": "speech_to_text",
    }[kind]
    if kind == "text" and model not in ("MiniMax-M3", "MiniMax-M3.1-Flash"):
        endpoint = "text/chatcompletion_v2"
    options = trial_options(kind, body, file_base64, file_name)
    result = await request_json(config["provider"], version, endpoint, options)
    return {"model": model, "kind": kind, "api_version": version, **normalize(result, kind, payload)}


def trial_options(
    kind: str, body: dict[str, JsonValue], file_base64: str | None, file_name: str,
) -> RequestOptions:
    files = None
    if kind == "asr":
        if not file_base64:
            raise ValueError("语音识别需要上传音频文件")
        content = base64.b64decode(file_base64, validate=True)
        if not content or len(content) > 20 * 1024 * 1024:
            raise ValueError("试验台音频文件不能为空且不能超过 20 MB")
        files = {"file": (Path(file_name).name, content, "application/octet-stream")}
        body = {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in body.items()}
    return RequestOptions(payload=body, files=files)


async def query_video(task_id: str, version: str) -> GeneratedMedia:
    path = f"query/video_generation/{task_id}" if version == "v2" else "query/video_generation"
    result = await request_json(
        "minimax", version, path,
        RequestOptions(method="GET", params={"task_id": task_id} if version == "v1" else None),
    )
    if version == "v1" and result.get("status") == "Success" and result.get("file_id"):
        file = await request_json(
            "minimax", "v1", "files/retrieve", RequestOptions(method="GET", params={"file_id": result["file_id"]}),
        )
        url = file.get("file", {}).get("download_url", "")
        if url.startswith(("https://", "http://")):
            return {"result": result, "media": [{"kind": "video", "url": url, "temporary": True}]}
    return normalize(result, "video", {})


def image_extension(content: bytes) -> str | None:
    if content.startswith(b"\x89PNG"):
        return "png"
    if content.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "webp"
    return None


def audio_resource(data: dict[str, JsonValue], payload: dict[str, JsonValue]) -> Media | None:
    """Persist hex audio or return its remote URL; leave the response mapping untouched."""
    audio = data.get("audio")
    if not audio:
        return None
    if payload.get("output_format", "hex") == "hex":
        ext = payload.get("audio_setting", {}).get("format", "mp3")
        if ext not in ("mp3", "wav", "flac", "pcm"):
            raise ValueError("不支持的音频格式")
        return save_media(bytes.fromhex(audio), ext, "audio")
    if audio.startswith(("https://", "http://")):
        return {"kind": "audio", "url": audio, "temporary": True}
    return None
