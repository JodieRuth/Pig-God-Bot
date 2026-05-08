from __future__ import annotations

import uuid
from typing import Any


TOOL_DESCRIPTION = "启动一个后台图像生成或图像编辑任务。仅用于合规的图片生成、参考图改图、替换主体、改变风格、图文生图、图像合成等请求。调用本工具时，必须由 LLM 在 prompt 参数中写入最终、完整、可直接发送给图像模型的中文提示词；程序不会再把聊天上下文、系统提示或用户原话追加进绘图接口。需要参考图片时，必须用 image_indexes 明确指定要传入的图片编号；未指定的图片不会传给绘图接口。若请求或上下文涉及政治敏感、中国大陆政治不正确、违法违规、暴力恐怖、色情低俗、赌博诈骗、侵犯隐私、规避平台审核、攻击骚扰、仇恨歧视、自伤自杀诱导、未成年人不当内容、伪造证件票据、冒充真实个人或任何 QQ 平台和中国大陆法规不允许的内容，禁止调用此工具，必须直接拒绝。"


def definition(ctx: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": TOOL_DESCRIPTION,
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "最终、完整、可直接发送给图像生成模型的中文提示词。必须由 LLM 根据用户当前请求、必要聊天上下文和所选图片编号自行整合完成；程序不会再额外拼接上下文。若需要编辑或引用图片，必须在提示词中明确说明图1、图2等编号各自的用途、编辑目标、保留内容和输出要求。不得包含政治敏感、中国大陆政治不正确、违法违规、色情低俗、隐私侵犯、攻击骚扰等不允许内容。",
                    },
                    "image_indexes": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "实际传给生图接口的图片编号列表，例如 [1,2]。编号来自 LLM 输入图片顺序：图1 是第一张输入图片，图2 是第二张。只有这里列出的图片会被传入绘图 API；纯文生图必须省略或传空数组。",
                    },
                    "notice": {
                        "type": "string",
                        "description": "使用本工具时本轮对话需要发给 QQ 用户的完整回复消息。工具启动成功后程序会立即发送该消息并附加任务 ID，使用自然语言回复即可，就像平时回复那样，但需要告知用户任务已开始需要等待。",
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
    prompt = str(args.get("prompt") or "").strip()
    if not prompt:
        return {"ok": False, "content": "生图任务启动失败：缺少工具参数 prompt。"}
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
    return {
        "ok": True,
        "answered": True,
        "job_id": job_id,
        "notice": notice,
    }
