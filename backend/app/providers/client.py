import asyncio
import base64
import json
import os
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import httpx
import yaml
from cryptography.fernet import Fernet

from app.models import DATA_DIR, Session, Setting


def cipher():
    supplied = os.environ.get("MYFLOW_ENCRYPTION_KEY")
    key_path = DATA_DIR / "encryption.key"
    if supplied:
        return Fernet(supplied.encode())
    try:
        with key_path.open("xb") as file:
            file.write(Fernet.generate_key())
        key_path.chmod(0o600)
    except FileExistsError:
        pass
    return Fernet(key_path.read_bytes())


def catalog():
    path = Path(os.environ.get("MYFLOW_MODELS_FILE", Path(__file__).resolve().parents[2] / "models.yaml"))
    return yaml.safe_load(path.read_text(encoding="utf-8"))["models"]


def provider_setting():
    with Session() as db:
        setting = db.get(Setting, "openai")
        return {"base_url": setting.base_url if setting else "https://api.openai.com/v1",
                "configured": bool(setting and setting.encrypted_key)}


def save_provider(base_url, api_key):
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Base URL 必须是有效的 HTTP(S) 地址，不包含账号、参数或片段")
    with Session.begin() as db:
        setting = db.get(Setting, "openai")
        if setting is None:
            setting = Setting(id="openai", encrypted_key="")
            db.add(setting)
        setting.base_url = base_url.rstrip("/")
        if api_key:
            setting.encrypted_key = cipher().encrypt(api_key.encode()).decode()


class Provider:
    def __init__(self, model, kind):
        config = next((m for m in catalog() if m["id"] == model and m["kind"] == kind), None)
        if config is None:
            raise ValueError(f"未配置的模型：{model}，请检查 models.yaml")
        self.model = model
        self.demo = config["provider"] == "demo"
        self.base_url = ""
        self.key = ""
        if not self.demo:
            with Session() as db:
                setting = db.get(Setting, "openai")
                if not setting or not setting.encrypted_key:
                    raise ValueError("请先在模型设置中填写 API Key，或选择演示模型")
                self.base_url = setting.base_url
                self.key = cipher().decrypt(setting.encrypted_key.encode()).decode()

    async def chat(self, system, prompt):
        if self.demo:
            text = f"【演示输出】\n\n{prompt}\n\n让每一次灵感，都有自己的表达。\n从一个小小的想法出发，创造属于你的精彩。"
            for i in range(0, len(text), 3):
                await asyncio.sleep(0.025)
                yield {"text": text[i:i + 3]}
            return
        async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=15)) as client:
            async with client.stream("POST", f"{self.base_url}/chat/completions", headers={"Authorization": f"Bearer {self.key}"}, json={
                "model": self.model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                "stream": True, "stream_options": {"include_usage": True},
            }) as response:
                if response.is_error:
                    raise ValueError(f"模型请求失败（HTTP {response.status_code}），请检查地址、密钥和模型")
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    chunk = json.loads(payload)
                    if chunk.get("error"):
                        raise ValueError("模型返回流式错误，请检查服务端配置")
                    choices = chunk.get("choices") or []
                    yield {"text": choices[0].get("delta", {}).get("content") or "" if choices else "", "usage": chunk.get("usage")}

    async def text2img(self, prompt, size):
        if self.demo:
            await asyncio.sleep(0.6)
            # A local SVG demo artifact, deliberately distinct from a real model output.
            name = f"{uuid4().hex}.svg"
            (DATA_DIR / "artifacts" / name).write_text('''<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024"><defs><linearGradient id="g" x2="1" y2="1"><stop stop-color="#d8f3cc"/><stop offset="1" stop-color="#eff5e7"/></linearGradient></defs><rect width="1024" height="1024" fill="url(#g)"/><circle cx="650" cy="360" r="200" fill="#f6c878"/><path d="M0 850L340 370 670 850Z" fill="#497459"/><path d="M320 1024L720 480 1100 1024Z" fill="#294f43"/><text x="64" y="100" font-family="sans-serif" font-size="32" fill="#294f43">MYFLOW / DEMO ARTWORK</text><text x="64" y="960" font-family="sans-serif" font-size="20" fill="#d8f3cc">A little idea. A world of possibilities.</text></svg>''', encoding="utf-8")
            return {"url": f"/artifacts/{name}", "demo": True}
        async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=15)) as client:
            response = await client.post(f"{self.base_url}/images/generations", headers={"Authorization": f"Bearer {self.key}"}, json={
                "model": self.model, "prompt": prompt, "size": size, "n": 1,
            })
            if response.is_error:
                raise ValueError(f"生图请求失败（HTTP {response.status_code}），请检查模型及接口兼容性")
            item = response.json()["data"][0]
            if item.get("b64_json"):
                content = base64.b64decode(item["b64_json"], validate=True)
                if content.startswith(b"\x89PNG\r\n\x1a\n"):
                    ext = "png"
                elif content.startswith(b"\xff\xd8\xff"):
                    ext = "jpg"
                elif content.startswith(b"RIFF") and content[8:12] == b"WEBP":
                    ext = "webp"
                else:
                    raise ValueError("图像接口返回了不支持的文件格式")
                name = f"{uuid4().hex}.{ext}"
                (DATA_DIR / "artifacts" / name).write_bytes(content)
                return {"url": f"/artifacts/{name}"}
            url = item.get("url", "")
            if urlparse(url).scheme not in ("http", "https"):
                raise ValueError("图像接口未返回有效图片")
            return {"url": url, "temporary": True}
