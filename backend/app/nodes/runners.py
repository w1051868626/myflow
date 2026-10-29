import json

from app.engine.graph import input_fields, render
from app.providers.client import Provider
from app.nodes.media import ASRNode, MusicNode, SpeechNode, VideoNode
from app.nodes.media import Context, Emit, NodeExecution
from app.schemas import Node


class TextNode:
    async def run(
        self, node: Node, inputs: dict[str, str], context: Context, parents: set[str], emit: Emit,
    ) -> NodeExecution:
        text = node.data["text"]
        return {"output": text}, {"text": text}


class StartNode:
    async def run(self, node, inputs, context, parents, emit):
        values = {key: inputs[key] for key in input_fields(node)}
        return {**values, "output": json.dumps(values, ensure_ascii=False)}, values


class LLMNode:
    async def run(self, node, inputs, context, parents, emit):
        prompt = render(node.data.get("prompt", ""), context)
        system = render(node.data.get("system", ""), context)
        provider = Provider(node.data.get("model", "deepseek-flash"), "text")
        output, usage = "", None
        async for chunk in provider.chat(system, prompt):
            if chunk.get("usage"):
                usage = chunk["usage"]
            if chunk["text"]:
                output += chunk["text"]
                emit("llm_token", {"node_id": node.id, "text": chunk["text"]})
        return {"output": output, "usage": usage}, {"prompt": prompt, "system": system, "model": provider.model}


class ImageNode:
    async def run(self, node, inputs, context, parents, emit):
        prompt = render(node.data.get("prompt", ""), context)
        provider = Provider(node.data.get("model", "image-01"), "image")
        image = await provider.text2img(prompt, node.data.get("size", "1024x1024"))
        image["kind"] = "image"
        return {"output": image, "url": image["url"]}, {"prompt": prompt, "model": provider.model}


class TemplateNode:
    async def run(self, node, inputs, context, parents, emit):
        template = node.data.get("template", "")
        return {"output": render(template, context)}, {"template": template}


class EndNode:
    async def run(self, node, inputs, context, parents, emit):
        values = {key: context[key]["output"] for key in sorted(parents)}
        return {"output": values}, values


RUNNERS = {
    "text": TextNode(), "start": StartNode(), "llm": LLMNode(), "image": ImageNode(),
    "speech": SpeechNode(), "music": MusicNode(), "video": VideoNode(), "asr": ASRNode(),
    "template": TemplateNode(), "end": EndNode(),
}
