"""Create and execute an isolated example workflow using the local configured services."""
import json
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    def node(id, type, x, y, **data):
        return {"id": id, "type": type, "position": {"x": x, "y": y}, "data": {"label": id, **data}}
    graph = {"nodes": [
        node("start", "start", 0, 150, label="创作主题", fields="topic"),
        node("speech", "speech", 280, 20, label="合成语音", model="speech-2.8-hd", prompt="{{start.topic}}", voice_id="male-qn-qingse", speed="1"),
        node("asr", "asr", 560, 20, label="识别语音", model="asr-1.0", audio_url="{{speech.url}}"),
        node("template", "template", 840, 20, label="整理识别结果", template="识别结果：{{asr.output}}"),
        node("image", "image", 280, 270, label="生成配图", model="image-01", prompt="A cup of coffee in soft morning light, cinematic photography", size="1024x1024"),
        node("video", "video", 560, 270, label="配图变视频", model="MiniMax-H3-Highspeed", prompt="Steam gently rises from the coffee. Static camera.", image_url="{{image.url}}", duration="5", resolution="768P", ratio="16:9", timeout="300"),
        node("end", "end", 1140, 150, label="多模态输出"),
    ], "edges": [{"id": f"{a}-{b}", "source": a, "target": b} for a, b in [
        ("start", "speech"), ("speech", "asr"), ("asr", "template"), ("template", "end"),
        ("start", "image"), ("image", "video"), ("video", "end"),
    ]]}
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=30) as client:
        def post(path, payload):
            response = client.post(path, json=payload)
            response.raise_for_status()
            return response.json()
        workflow = post("/api/workflows", {"name": "多模态节点验证：语音识别与图生视频", "graph": graph})
        run = post("/api/workflows/runs", {"id": workflow["id"], "inputs": {"topic": "清晨的一杯咖啡，唤醒一天的灵感。"}})
        print("Workflow: " + workflow["id"], flush=True)
        print("Run: " + run["id"], flush=True)
        last = ""
        while run["status"] == "running":
            time.sleep(3)
            run = post("/api/runs/get", {"id": run["id"]})
            if run["status"] != last:
                print("Status: " + run["status"], flush=True)
                last = run["status"]
        (ROOT / "docs" / "media-workflow-check.json").write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Result: " + str(ROOT / "docs" / "media-workflow-check.json"), flush=True)
        if run["status"] != "succeeded":
            raise SystemExit(run.get("error") or "工作流未成功")


if __name__ == "__main__":
    main()
