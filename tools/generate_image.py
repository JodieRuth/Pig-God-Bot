from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any


def definition(ctx: dict[str, Any]) -> dict[str, Any]:
    description = ctx["prompt_value"]("tool_description") or "当用户明确要求生成、编辑、重绘、修图、扩图或进行其他允许的图片生成任务时调用。"
    return {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "给图像生成模型的完整中文提示词。必须保留用户对图1、图2等图片编号的引用和编辑目标。提示词不得包含政治敏感、中国大陆政治不正确、违法违规、色情低俗、隐私侵犯、攻击骚扰等不允许内容。在传入时，尽可能根据图片实际内容与用户目的对提示词进行优化。",
                    },
                    "image_indexes": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "要传给生图工具的图片编号列表，例如 [1,2]。编号来自输入图片顺序：图1 是第一张输入图片，图2 是第二张。若本次是纯文生图，就不要填写任何图片编号。",
                    },
                    "notice": {
                        "type": "string",
                        "description": "发给 QQ 用户的简短开始提示，例如：已开始处理这张图，完成后会带用时回复。",
                    },
                },
                "required": ["prompt"],
            },
        },
    }


def info(ctx: dict[str, Any]) -> dict[str, str]:
    item = definition(ctx).get("function", {})
    return {
        "name": str(item.get("name") or "generate_image"),
        "description": str(item.get("description") or ""),
    }


def build_image_order_note(images: list[dict[str, Any]], ctx: dict[str, Any]) -> str:
    if not images:
        return ""
    lines = ["输入图片按时间顺序编号如下，图1 最早，编号越大越新："]
    max_images = int(ctx["max_context_images"])
    for index, record in enumerate(images[:max_images], start=1):
        image = ctx["image_path"](record)
        lines.append(f"图{index} = 第 {index} 张输入图片，文件名 {image.name}，发送者 {ctx['image_sender_label'](record)}")
    lines.append("用户提到图1、图2、第一张、第二张时，必须按这个编号理解；不要自行交换图片顺序。")
    lines.append("如果本次传入了多张参考图，而用户没有明确指定编号，请结合最近聊天上下文、用户当前请求、图片时间顺序和发送者信息，甄别真正应该用于生图的参考图片，通常优先使用与当前请求最相关、时间上最接近、由触发者本人发送或被明确点名的两张图片。")
    lines.append("不要把无关的旧图强行混入画面；如果用户要求替换、合成或把图A内容应用到图B，要明确区分哪张是待编辑底图，哪张是参考主体/风格图。")
    return "\n".join(lines)


def image_api_url_for_request(has_images: bool, ctx: dict[str, Any]) -> str:
    ctx["reload_runtime_files"]()
    image_url = ctx["active_api_config"]("image")["url"]
    if has_images:
        return image_url
    if image_url.endswith("/images/edits"):
        return image_url.removesuffix("/images/edits") + "/images/generations"
    return image_url


async def call_image_api(prompt: str, context_texts: list[str], images: list[dict[str, Any]], ctx: dict[str, Any]) -> Path:
    ctx["reload_runtime_files"]()
    image_config = ctx["active_api_config"]("image")
    image_url = image_config["url"]
    image_key = image_config["key"]
    image_model = ctx["active_model"]("image")
    if not image_url:
        raise RuntimeError("未配置生图接口地址")

    max_messages = int(ctx["max_context_messages"])
    max_images = int(ctx["max_context_images"])
    context = "\n".join(context_texts[-max_messages:])
    image_order_note = build_image_order_note(images, ctx)
    prompt_parts = []
    if context:
        prompt_parts.append(f"最近聊天上下文，仅用于理解用户意图、图片指代、发送者和时间顺序，不要当作必须出现在图片里的内容：\n{context}")
    if image_order_note:
        prompt_parts.append(image_order_note)
    prompt_parts.append(f"当前生图请求：\n{prompt}")
    full_prompt = "\n\n".join(prompt_parts)
    headers = {"Authorization": f"Bearer {image_key}"} if image_key else {}

    image_paths = [ctx["image_path"](record) for record in images[:max_images]]
    request_url = image_api_url_for_request(bool(image_paths), ctx)
    if image_paths:
        form = aiohttp.FormData()
        form.add_field("model", image_model)
        form.add_field("prompt", full_prompt)
        for image in image_paths:
            form.add_field("image", image.open("rb"), filename=image.name, content_type="image/png" if image.suffix.lower() == ".png" else "image/jpeg")
        payload: Any = form
    else:
        payload = {"model": image_model, "prompt": full_prompt}

    ctx["log_json"]("Image request", {"url": request_url, "prompt": full_prompt, "images": [str(p) for p in image_paths], "headers": headers})
    async with aiohttp.ClientSession(headers=headers) as session:
        if image_paths:
            request = session.post(request_url, data=payload, timeout=60 * 30)
        else:
            request = session.post(request_url, json=payload, timeout=60 * 30)
        async with request as resp:
            body = await resp.read()
            body_text = body[:1000].decode("utf-8", errors="replace")
            ctx["log"](f"Image response status={resp.status} content_type={resp.headers.get('content-type', '')} body_preview={body[:300]!r}")
            if resp.status >= 400:
                raise RuntimeError(f"HTTP {resp.status}: {ctx['sanitize_error_detail'](body_text)}")
            content_type = resp.headers.get("content-type", "")
            if content_type.startswith("image/"):
                suffix = ".png" if "png" in content_type else ".jpg"
                target = ctx["output_dir"] / f"{uuid.uuid4().hex}{suffix}"
                target.write_bytes(body)
                ctx["log"](f"Image saved: {target}")
                return target

            data = json.loads(body.decode("utf-8"))
            first = data.get("data", [{}])[0]
            image_b64 = first.get("b64_json") or data.get("image_base64")
            if image_b64:
                target = ctx["output_dir"] / f"{uuid.uuid4().hex}.png"
                target.write_bytes(base64.b64decode(image_b64))
                ctx["log"](f"Image decoded from base64: {target}")
                return target
            image_url = first.get("url") or data.get("image_url")
            if image_url:
                ctx["log"](f"Image URL received: {image_url}")
                path = await ctx["download_image"](session, image_url)
                if path:
                    return path
            raise RuntimeError(f"生图接口没有返回可用图片字段，响应：{ctx['sanitize_error_detail'](data)}")


def select_images(images: list[dict[str, Any]], image_indexes: list[Any]) -> list[dict[str, Any]]:
    if not image_indexes:
        return []
    selected: list[dict[str, Any]] = []
    for value in image_indexes:
        try:
            index = int(value)
        except (TypeError, ValueError):
            continue
        if 1 <= index <= len(images):
            record = images[index - 1]
            if record not in selected:
                selected.append(record)
    return selected


async def execute(args: dict[str, Any], runtime: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    prompt = str(args.get("prompt") or runtime.get("prompt") or "").strip()
    if not prompt:
        return {"ok": False, "content": "生图任务启动失败：缺少 prompt 参数。"}
    images = select_images(runtime.get("images", []), args.get("image_indexes") or [])
    job_id = uuid.uuid4().hex[:8]
    notice = str(args.get("notice") or "收到，图像任务已开始。").strip() or "收到，图像任务已开始。"
    try:
        await ctx["reply"](runtime["event"], f"{notice}\n任务 ID：{job_id}")
        task = ctx["create_task"](ctx["image_job"](runtime["event"], job_id, prompt, runtime.get("context_texts", []), images))
        ctx["jobs"][job_id] = task
        task.add_done_callback(lambda t, jid=job_id: ctx["log"](f"Background task done: {jid} cancelled={t.cancelled()} exception={t.exception() if not t.cancelled() else None}"))
    except Exception as exc:
        return {"ok": False, "content": f"生图任务启动失败：{ctx['exception_detail'](exc)}"}
    image_names = [ctx["image_path"](record).name for record in images]
    detail = f"，参考图片：{', '.join(image_names)}" if image_names else "，无参考图片"
    return {
        "ok": True,
        "content": f"生图后台任务已启动，任务 ID：{job_id}{detail}。工具只负责启动任务，不等待完整图片生成；图片完成或失败后会由 bot 在群聊中另行回复。",
        "job_id": job_id,
        "notice": notice,
    }
