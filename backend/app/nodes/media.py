import asyncio
import base64
from collections.abc import Callable
import copy
from dataclasses import dataclass
import math
import re
from time import monotonic
from typing import NotRequired, TypedDict

from pydantic import JsonValue

from app.artifacts import media_input, read_artifact
from app.engine.graph import render
from app.nodes.registry import NODE_REGISTRY
from app.providers.minimax import presets, query_video, trial
from app.providers.types import GeneratedMedia, ModelPreset
from app.providers.validation import validate_video_dimensions
from app.schemas import Node


class NodeOutput(TypedDict):
    output: object
    url: NotRequired[str]
    usage: NotRequired[object]


Context = dict[str, NodeOutput]
ResolvedInputs = dict[str, object]
NodeExecution = tuple[NodeOutput, ResolvedInputs]
Emit = Callable[[str, dict[str, object]], None]


@dataclass(frozen=True)
class VideoTask:
    node_id: str
    task_id: str
    api_version: str
    deadline: float  # Monotonic seconds; limits local polling only.


def value(node: Node, key: str, context: Context) -> str:
    default = NODE_REGISTRY[node.type]["properties"][key]["default"]
    return render(node.data.get(key, default), context)


def model_config(node: Node, kind: str, context: Context) -> tuple[ModelPreset, dict[str, JsonValue]]:
    model = value(node, "model", context)
    config = next((item for item in presets() if item["id"] == model and item["kind"] == kind), None)
    if config is None:
        raise ValueError(f"未配置的{NODE_REGISTRY[node.type]['title']}模型：{model}")
    return config, copy.deepcopy(config["payload"])


def media_result(response: GeneratedMedia) -> NodeOutput:
    media = response["media"][0]
    return {
        "output": media,
        "url": media["url"],
        "usage": response["result"].get("usage") or response["result"].get("extra_info"),
    }


def video_output(result: GeneratedMedia, task_id: str, version: str) -> NodeOutput | None:
    raw = result["result"]
    task = raw.get("task") or raw
    status = task.get("status", "unknown")
    if status in ("failed", "Fail", "Failed", "cancelled"):
        raise ValueError(f"视频任务 {task_id} 已{status}，请检查供应商结果")
    if status not in ("succeeded", "Success"):
        return None
    if not result["media"]:
        raise ValueError(f"视频任务 {task_id} 已完成但未返回资源链接")
    media = result["media"][0].copy()
    media.update(task_id=task_id, api_version=version)
    output = media_result(result)
    output["output"] = media
    return output


def legacy_video_reference(config: ModelPreset, image: str) -> dict[str, JsonValue]:
    if config.get("reference") == "subject":
        if not image:
            raise ValueError("S2V 模型需要人物参考图片")
        return {"subject_reference": [{"type": "character", "image": [media_input(image, "image")]}]}
    if not image:
        return {}
    if config["id"].startswith("T2V-"):
        raise ValueError("T2V 模型不支持参考图，请选择 H3、Hailuo 或 I2V 模型")
    return {"first_frame_image": media_input(image, "image")}


class SpeechNode:
    async def run(
        self, node: Node, inputs: dict[str, str], context: Context, parents: set[str], emit: Emit,
    ) -> NodeExecution:
        config, body = model_config(node, "speech", context)
        text, voice = value(node, "prompt", context), value(node, "voice_id", context)
        if not text.strip() or len(text) >= 10000 or not voice.strip():
            raise ValueError("朗读文本和音色不能为空，朗读文本必须少于 10000 字符")
        try:
            speed = float(value(node, "speed", context))
        except ValueError:
            raise ValueError("语速必须是 0.5–2 之间的数字") from None
        if not math.isfinite(speed) or not 0.5 <= speed <= 2:
            raise ValueError("语速必须是 0.5–2 之间的数字")
        body.update(text=text, voice_setting={"voice_id": voice, "speed": speed, "vol": 1, "pitch": 0})
        response = await trial(config["id"], body)
        return media_result(response), {"model": config["id"], "text": text, "voice_id": voice, "speed": speed}


class MusicNode:
    async def run(
        self, node: Node, inputs: dict[str, str], context: Context, parents: set[str], emit: Emit,
    ) -> NodeExecution:
        config, body = model_config(node, "music", context)
        prompt, lyrics = value(node, "prompt", context), value(node, "lyrics", context)
        audio = value(node, "audio_url", context).strip()
        instrumental = value(node, "instrumental", context)
        if instrumental not in ("true", "false"):
            raise ValueError("纯音乐选项必须为 true 或 false")
        body.update(prompt=prompt)
        if config.get("reference") == "audio":
            if audio.startswith("/artifacts/"):
                _, content = read_artifact(audio, "audio")
                body.pop("audio_url", None)
                body["audio_base64"] = base64.b64encode(content).decode()
            elif audio.startswith(("https://", "http://")):
                body["audio_url"] = audio
            else:
                raise ValueError("翻唱模型需要上传参考音频或填写其 HTTP(S) 地址")
        else:
            if audio:
                raise ValueError("当前模型不支持参考音频，请选择 Music Cover 模型")
            body["is_instrumental"] = instrumental == "true"
            if instrumental == "false" and not lyrics.strip():
                raise ValueError("歌曲生成需要填写歌词，或选择纯音乐")
        if lyrics:
            body["lyrics"] = lyrics
        response = await trial(config["id"], body)
        return media_result(response), {
            "model": config["id"], "prompt": prompt, "lyrics": lyrics,
            "audio_url": audio, "instrumental": instrumental,
        }


class ASRNode:
    async def run(
        self, node: Node, inputs: dict[str, str], context: Context, parents: set[str], emit: Emit,
    ) -> NodeExecution:
        config, body = model_config(node, "asr", context)
        audio = value(node, "audio_url", context).strip()
        name, content = read_artifact(audio, "audio")
        response = await trial(config["id"], body, base64.b64encode(content).decode(), name)
        text = response["result"].get("text")
        if not isinstance(text, str):
            raise ValueError("语音识别接口未返回文本")
        return {"output": text, "usage": {"duration": response["result"].get("duration")}}, {
            "model": config["id"], "audio_url": audio,
        }


class VideoNode:
    poll_interval = 5

    async def run(
        self, node: Node, inputs: dict[str, str], context: Context, parents: set[str], emit: Emit,
    ) -> NodeExecution:
        config, body = model_config(node, "video", context)
        prompt, image = value(node, "prompt", context), value(node, "image_url", context).strip()
        try:
            duration, timeout = int(value(node, "duration", context)), int(value(node, "timeout", context))
        except ValueError:
            raise ValueError("时长和等待时间必须为整数") from None
        if not 1 <= timeout <= 1200:
            raise ValueError("最长等待时间必须在 1–1200 秒之间")
        resolution = value(node, "resolution", context)
        version = config.get("api_version", "v1")
        if not prompt.strip():
            raise ValueError("视频画面描述不能为空")
        body.update(duration=duration, resolution=resolution)
        validate_video_dimensions(config["id"], version, duration, resolution)
        if version == "v2":
            body["content"] = [{"type": "text", "text": prompt}]
            if image:
                body["content"].append({
                    "type": "image_url", "image_url": {"url": media_input(image, "image")}, "role": "first_frame",
                })
                body.pop("ratio", None)
            else:
                body["ratio"] = value(node, "ratio", context)
        else:
            body["prompt"] = prompt
            body.update(legacy_video_reference(config, image))
        response = await trial(config["id"], body)
        task_id = str(response["result"].get("task_id", ""))
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", task_id):
            raise ValueError("视频接口未返回有效任务 ID")
        resolved = {
            "model": config["id"], "prompt": prompt, "image_url": image, "duration": duration,
            "resolution": resolution, "task_id": task_id, "api_version": version,
        }
        task = VideoTask(node.id, task_id, version, monotonic() + timeout)
        return await self.wait_for_video(task, emit), resolved

    async def wait_for_video(self, task: VideoTask, emit: Emit) -> NodeOutput:
        task_id, version, deadline = task.task_id, task.api_version, task.deadline
        failures, last_status = 0, None
        emit("node_progress", {
            "node_id": task.node_id, "status": "已提交，等待视频生成",
            "task_id": task_id, "api_version": version,
        })
        while monotonic() < deadline:
            try:
                async with asyncio.timeout(max(0.001, deadline - monotonic())):
                    result = await query_video(task_id, version)
                failures = 0
            except TimeoutError:
                break
            except ValueError as exc:
                failures += 1
                if failures >= 3:
                    raise ValueError(f"视频任务 {task_id} 查询失败：{exc}；可在试验台继续查询，请勿重复提交") from None
                await asyncio.sleep(min(self.poll_interval, max(0, deadline - monotonic())))
                continue
            raw = result["result"]
            status = (raw.get("task") or raw).get("status", "unknown")
            output = video_output(result, task_id, version)
            if output is not None:
                return output
            if status != last_status:
                emit("node_progress", {
                    "node_id": task.node_id, "status": f"视频任务：{status}",
                    "task_id": task_id, "api_version": version,
                })
                last_status = status
            await asyncio.sleep(min(self.poll_interval, max(0, deadline - monotonic())))
        raise ValueError(
            f"视频任务 {task_id} 等待超时，上游任务可能仍在运行；可在试验台继续查询，请勿重复提交"
        )
