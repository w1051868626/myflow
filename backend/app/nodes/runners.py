import json

from app.engine.graph import input_fields, render
from app.providers.client import Provider


class StartNode:
    async def run(self, node, inputs, context, parents, emit):
        values = {key: inputs[key] for key in input_fields(node)}
        return {**values, "output": json.dumps(values, ensure_ascii=False)}, values


class LLMNode:
    async def run(self, node, inputs, context, parents, emit):
        prompt = render(node.data.get("prompt", ""), context)
        system = render(node.data.get("system", ""), context)
        provider = Provider(node.data.get("model", "demo-text"), "text")
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
        provider = Provider(node.data.get("model", "demo-image"), "image")
        image = await provider.text2img(prompt, node.data.get("size", "1024x1024"))
        return {"output": image}, {"prompt": prompt, "model": provider.model}


class TemplateNode:
    async def run(self, node, inputs, context, parents, emit):
        template = node.data.get("template", "")
        return {"output": render(template, context)}, {"template": template}


class EndNode:
    async def run(self, node, inputs, context, parents, emit):
        values = {key: context[key]["output"] for key in sorted(parents)}
        return {"output": values}, values


RUNNERS = {"start": StartNode(), "llm": LLMNode(), "image": ImageNode(), "template": TemplateNode(), "end": EndNode()}
