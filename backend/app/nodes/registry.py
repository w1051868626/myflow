from typing import Any


def field(title, default="", **extra):
    return {"type": "string", "title": title, "default": default, **extra}


NODE_REGISTRY: dict[str, dict[str, Any]] = {
    "text": {"title": "文本输入", "description": "直接填写原文，连接到下游后引用 .output，无需调用模型",
             "output_type": "text", "properties": {
        "text": field("文本内容", "一杯咖啡里的慢生活", format="plain-text"),
    }},
    "start": {"title": "开始", "description": "定义这次创作的输入", "output_type": "text", "properties": {
        "fields": field("输入字段（逗号分隔）", "topic"),
    }},
    "llm": {"title": "文本生成", "description": "让灵感变成文字", "output_type": "text", "properties": {
        "model": field("模型", "deepseek-flash", format="text-model"),
        "system": field("系统提示词", "你是一位简洁、有创意的中文内容创作者。", format="textarea"),
        "prompt": field("提示词", "为 {{start.topic}} 写一段简短的创意文案。", format="textarea"),
    }},
    "image": {"title": "图像生成", "description": "把想象变成画面", "output_type": "image", "properties": {
        "model": field("模型", "image-01", format="image-model"),
        "prompt": field("画面描述", "为这段文案生成配图：{{llm.output}}", format="textarea"),
        "size": field("尺寸", "1024x1024", enum=["1024x1024", "1536x1024", "1024x1536"]),
    }},
    "template": {"title": "模板拼接", "description": "组合上游文本", "output_type": "text", "properties": {
        "template": field("文本模板", "创意文案\n\n{{llm.output}}", format="textarea"),
    }},
    "speech": {"title": "语音合成", "description": "将文案变成可播放的语音", "output_type": "audio", "properties": {
        "model": field("模型", "speech-2.8-hd", format="speech-model"),
        "prompt": field("朗读文本", "{{start.topic}}", format="textarea"),
        "voice_id": field("音色 ID", "male-qn-qingse"),
        "speed": field("语速（0.5–2）", "1"),
    }},
    "music": {"title": "音乐生成", "description": "生成配乐或使用参考音频翻唱；模型权限以供应商账户为准", "output_type": "audio", "properties": {
        "model": field("模型", "music-3.0", format="music-model"),
        "prompt": field("音乐风格", "温暖轻快的钢琴配乐，适合清晨咖啡馆", format="textarea"),
        "lyrics": field("歌词（纯音乐可留空）", "", format="textarea"),
        "instrumental": field("纯音乐", "true", enum=["true", "false"]),
        "audio_url": field("翻唱参考音频（可选）", "", format="audio-file"),
    }},
    "video": {"title": "视频生成", "description": "提交视频任务并等待完成；取消运行会停止本地等待，上游任务可能继续", "output_type": "video", "properties": {
        "model": field("模型", "MiniMax-H3-Highspeed", format="video-model"),
        "prompt": field("画面描述", "{{start.topic}}", format="textarea"),
        "image_url": field("首帧 / 人物参考图片（可选）", "", format="image-file"),
        "duration": field("时长（秒）", "5", enum=["4", "5", "6", "10", "15"]),
        "resolution": field("分辨率", "768P", enum=["480P", "720P", "768P", "1080P", "2K"]),
        "ratio": field("宽高比（H3 文生视频）", "16:9", enum=["16:9", "9:16", "1:1", "4:3", "3:4", "21:9"]),
        "timeout": field("最长等待（秒）", "600", enum=["60", "300", "600", "1200"]),
    }},
    "asr": {"title": "语音识别", "description": "上传音频或引用上游语音 / 音乐，识别结果可继续交给文本模型", "output_type": "text", "properties": {
        "model": field("模型", "asr-1.0", format="asr-model"),
        "audio_url": field("待识别音频", "", format="audio-file"),
    }},
    "end": {"title": "输出", "description": "收集文字、图片、音频和视频", "output_type": "any", "properties": {}},
}
