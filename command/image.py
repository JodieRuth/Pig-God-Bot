from __future__ import annotations

import uuid
from typing import Any


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    prompt = arg.strip()
    if not prompt:
        await ctx["reply"](event, "用法：/image <生图提示词>，可在同一条消息里附带参考图片。")
        return

    images = list(event.get("current_images") or [])[: int(ctx.get("max_context_images") or 8)]
    job_id = uuid.uuid4().hex[:8]
    try:
        queue_result = await ctx["enqueue_image_job"](event, job_id, prompt, [], images)
    except Exception as exc:
        await ctx["reply"](event, f"生图任务启动失败：{ctx['exception_detail'](exc)}")
        return

    if not queue_result.get("ok"):
        await ctx["reply"](event, str(queue_result.get("content") or "生图任务启动失败。"))
        return

    image_note = f"，已附带 {len(images)} 张参考图" if images else ""
    if queue_result.get("queued"):
        position = int(queue_result.get("position") or 0)
        await ctx["reply"](event, f"收到，图像任务已开始{image_note}。\n任务 ID：{job_id}\n当前同时最多生成 2 张，你的任务已进入队列，当前排第 {position} 位。")
    else:
        await ctx["reply"](event, f"收到，图像任务已开始{image_note}。\n任务 ID：{job_id}\n当前正在生成。")


COMMAND = {
    "name": "/image",
    "usage": "/image <生图提示词>",
    "description": "直接启动图片生成任务：后续文本作为提示词，本条消息图片作为参考图，不经过 LLM。",
    "handler": handler,
}
