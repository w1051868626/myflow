import base64
import mimetypes
from pathlib import Path

from app.models import DATA_DIR
from app.providers.minimax import save_media

MAX_UPLOAD = 20 * 1024 * 1024
AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac", ".opus"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def upload(file_name, encoded):
    ext = Path(file_name).suffix.lower()
    if ext not in AUDIO_EXTENSIONS | IMAGE_EXTENSIONS:
        raise ValueError("支持 MP3、WAV、FLAC、M4A、OGG、AAC、OPUS 音频和 JPG、PNG、WebP 图片")
    content = base64.b64decode(encoded, validate=True)
    if not content or len(content) > MAX_UPLOAD:
        raise ValueError("文件不能为空且不能超过 20 MB")
    return save_media(content, ext.lstrip("."), "audio" if ext in AUDIO_EXTENSIONS else "image")


def read_artifact(url, kind):
    if not isinstance(url, str) or not url.startswith("/artifacts/"):
        raise ValueError("请选择上传的本地资源，或引用上游节点的本地资源 URL")
    filename = url[len("/artifacts/"):]
    root = (DATA_DIR / "artifacts").resolve()
    target = (root / filename).resolve()
    allowed = AUDIO_EXTENSIONS if kind == "audio" else IMAGE_EXTENSIONS
    if not filename or target.parent != root or "/" in filename or "\\" in filename or target.suffix.lower() not in allowed:
        raise ValueError("无效的本地资源地址或文件类型")
    if not target.is_file():
        raise ValueError("资源文件不存在，请重新上传或运行上游节点")
    if target.stat().st_size > MAX_UPLOAD:
        raise ValueError("资源文件不能超过 20 MB")
    return target.name, target.read_bytes()


def media_input(url, kind):
    if url.startswith("/artifacts/"):
        name, content = read_artifact(url, kind)
        mime = mimetypes.guess_type(name)[0] or ("audio/mpeg" if kind == "audio" else "image/png")
        return f"data:{mime};base64,{base64.b64encode(content).decode()}"
    if not url.startswith(("https://", "http://", f"data:{kind}/")):
        raise ValueError("参考资源必须是 HTTP(S) 地址、已上传资源或对应类型的 Data URL")
    return url
