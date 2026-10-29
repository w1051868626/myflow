"""Run one small real request per configured MiniMax model, saving no credentials.

Run from the repository root with the backend's Python environment.
"""
import argparse
import asyncio
import base64
import copy
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("MYFLOW_DATA_DIR", str(ROOT / "backend" / "data"))

from app.providers.minimax import presets, query_video, request_json, trial
from app.providers.types import RequestOptions


async def main(args: argparse.Namespace) -> None:
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "models": [], "pending": []}
    output = ROOT / "docs" / "minimax-model-check.json"
    if args.resume and output.exists():
        report = json.loads(output.read_text(encoding="utf-8"))

    def save():
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        discovery = await request_json("minimax_text", "v1", "models", RequestOptions(method="GET"))
        report["account_models"] = [item["id"] for item in discovery.get("data", [])]
        print("Account model discovery succeeded", flush=True)
    except ValueError as exc:
        report["discovery_error"] = str(exc)
        print("Account model discovery: " + str(exc), flush=True)
    save()
    if args.discover_only:
        return

    audio = None
    for config in presets():
        if args.kind and config["kind"] != args.kind:
            continue
        previous = next((row for row in report["models"] if row["model"] == config["id"]), None)
        if args.resume and previous and not (previous["status"] == "failed" and "rate limit" in previous.get("detail", "").lower()):
            continue
        body = copy.deepcopy(config["payload"])
        row = {"model": config["id"], "kind": config["kind"]}
        started = time.monotonic()
        reference = config.get("reference")
        if reference in ("audio", "file") and not audio:
            row.update(status="needs_input", detail="需要参考音频或可用的语音生成结果")
        else:
            if config["kind"] == "text":
                body["messages"] = [{"role": "user", "content": "只回复：你好。"}]
                body["max_completion_tokens"] = 256
                if config["id"] == "MiniMax-M3.1-Flash":
                    body["reasoning_effort"] = "low"
            if config["kind"] == "speech":
                body["text"] = "你好，欢迎来到我的创作空间。今天我们一起体验不同模型，看看文字、图片和声音如何让一个小小的灵感变得丰富而生动。"
            if reference == "image":
                body["first_frame_image"] = "https://cdn.hailuoai.com/prod/2024-09-18-16/user/multi_chat_file/9c0b5c14-ee88-4a5b-b503-4f626f018639.jpeg"
            if reference == "subject":
                body["subject_reference"] = [{"type": "character", "image": ["https://cdn.hailuoai.com/prod/2025-08-12-17/video_cover/1754990600020238321-411603868533342214-cover.jpg"]}]
                body["prompt"] = "A person smiles gently at the camera."
            if reference == "audio" and audio:
                body.pop("audio_url", None)
                body["audio_base64"] = audio
            try:
                result = await trial(config["id"], body, audio if reference == "file" else None)
                raw = result["result"]
                row.update(status="submitted" if raw.get("task_id") else "succeeded", media=result["media"])
                if raw.get("task_id"):
                    row["task_id"] = str(raw["task_id"])
                    row["api_version"] = result["api_version"]
                    report["pending"].append(row["model"])
                if raw.get("choices"):
                    row["text"] = str(raw["choices"][0].get("message", {}).get("content", ""))[:300]
                    row["finish_reason"] = raw["choices"][0].get("finish_reason")
                    if not row["text"].strip():
                        row["status"] = "empty_output"
                if raw.get("usage"):
                    row["usage"] = raw["usage"]
                if config["kind"] == "speech" and not audio:
                    local = next((m["url"] for m in result["media"] if m["url"].startswith("/artifacts/")), None)
                    if local:
                        from app.models import DATA_DIR
                        audio = base64.b64encode((DATA_DIR / "artifacts" / local.split("/")[-1]).read_bytes()).decode()
            except (ValueError, KeyError, TypeError) as exc:
                row.update(status="failed", detail=str(exc))
        row["elapsed_seconds"] = round(time.monotonic() - started, 2)
        if previous:
            report["models"].remove(previous)
            row["previous_attempt"] = {"status": previous["status"], "detail": previous.get("detail")}
        report["models"].append(row)
        save()
        print(f"{row['model']}: {row['status']}" + (" - " + row["detail"] if row.get("detail") else ""), flush=True)

    # Poll submitted tasks; never resubmit a generation request.
    deadline = time.monotonic() + args.poll_seconds
    while report["pending"] and time.monotonic() < deadline:
        for row in report["models"]:
            if row["model"] not in report["pending"]:
                continue
            try:
                response = await query_video(row["task_id"], row["api_version"])
                raw = response["result"]
                status = (raw.get("task") or raw).get("status")
                row["remote_status"] = status
                if status in ("succeeded", "Success", "failed", "Fail", "cancelled"):
                    row["status"] = "succeeded" if status in ("succeeded", "Success") else "failed"
                    row["media"] = response["media"]
                    report["pending"].remove(row["model"])
                    print(f"{row['model']}: {row['status']}", flush=True)
            except ValueError as exc:
                row["query_error"] = str(exc)
            save()
        if report["pending"]:
            await asyncio.sleep(10)
    print("Report: " + str(output), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--discover-only", action="store_true")
    parser.add_argument("--resume", action="store_true", help="Only retry RPM-limited calls and poll unfinished video tasks")
    parser.add_argument("--kind", choices=["text", "image", "speech", "music", "video", "asr"])
    parser.add_argument("--poll-seconds", type=int, default=300)
    asyncio.run(main(parser.parse_args()))
