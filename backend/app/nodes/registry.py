from typing import Any


def field(title, default="", **extra):
    return {"type": "string", "title": title, "default": default, **extra}


NODE_REGISTRY: dict[str, dict[str, Any]] = {
    "start": {"title": "开始", "description": "定义这次创作的输入", "output_type": "text", "properties": {
        "fields": field("输入字段（逗号分隔）", "topic"),
    }},
    "llm": {"title": "文本生成", "description": "让灵感变成文字", "output_type": "text", "properties": {
        "model": field("模型", "demo-text", format="text-model"),
        "system": field("系统提示词", "你是一位简洁、有创意的中文内容创作者。", format="textarea"),
        "prompt": field("提示词", "为 {{start.topic}} 写一段简短的创意文案。", format="textarea"),
    }},
    "image": {"title": "图像生成", "description": "把想象变成画面", "output_type": "image", "properties": {
        "model": field("模型", "demo-image", format="image-model"),
        "prompt": field("画面描述", "为这段文案生成配图：{{llm.output}}", format="textarea"),
        "size": field("尺寸", "1024x1024", enum=["1024x1024", "1536x1024", "1024x1536"]),
    }},
    "template": {"title": "模板拼接", "description": "组合上游文本", "output_type": "text", "properties": {
        "template": field("文本模板", "创意文案\n\n{{llm.output}}", format="textarea"),
    }},
    "end": {"title": "输出", "description": "收集文字与图像", "output_type": "any", "properties": {}},
}
