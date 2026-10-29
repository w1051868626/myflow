def example_graph(*, demo=False):
    def node(id, type, x, y, data):
        return {"id": id, "type": type, "position": {"x": x, "y": y}, "data": data}
    return {
        "nodes": [
            node("start", "start", 0, 120, {"label": "创作主题", "fields": "topic"}),
            node("llm", "llm", 300, 120, {"label": "写一段文案", "model": "demo-text" if demo else "deepseek-flash", "system": "你是一位简洁、有创意的中文内容创作者。", "prompt": "为 {{start.topic}} 写一段简短的创意文案。"}),
            node("image", "image", 620, 20, {"label": "生成配图", "model": "demo-image" if demo else "image-01", "prompt": "为这段文案生成配图：{{llm.output}}", "size": "1024x1024"}),
            node("template", "template", 620, 240, {"label": "整理文案", "template": "# {{start.topic}}\n\n{{llm.output}}"}),
            node("end", "end", 940, 120, {"label": "创作完成"}),
        ],
        "edges": [{"id": f"{a}-{b}", "source": a, "target": b} for a, b in [
            ("start", "llm"), ("llm", "image"), ("llm", "template"), ("image", "end"), ("template", "end")
        ]],
    }
