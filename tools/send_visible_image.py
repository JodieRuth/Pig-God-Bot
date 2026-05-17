from __future__ import annotations

from typing import Any


TOOL_DESCRIPTION = "直接把 LLM 当前可见的一张或多张输入图片原样发到当前会话，可选择是否作为对指定上下文消息的回复发送，并可附带一段文字。适用于用户要求把上文某张/多张图直接发出来、转发出来、贴出来，或判断不需要生图/改图、只需要发送它能看到的输入图片时。image_index/image_indexes 必须来自当前输入图片编号：图1 是第一张输入图片，图2 是第二张。调用成功后机器人已经完成本轮回答，不需要再输出普通文本。"


def definition(ctx: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "send_visible_image",
            "description": TOOL_DESCRIPTION,
            "parameters": {
                "type": "object",
                "properties": {
                    "reply": {
                        "type": "boolean",
                        "description": "是否把这条消息作为 message_id 指定消息的回复发送。需要回复某条上下文消息时填 true，否则填 false。",
                    },
                    "message_id": {
                        "type": "string",
                        "description": "当 reply 为 true 时要回复的上下文消息 ID，必须来自最近可直接回复的上下文消息 ID 列表。reply 为 false 时省略或留空。",
                    },
                    "text": {
                        "type": "string",
                        "description": "随图片一起发送给 QQ 用户的文字。可以为空字符串；如果需要解释图片来源或简短回应，就写完整自然语言文本。",
                    },
                    "image_index": {
                        "type": "integer",
                        "description": "要发送的单张图片编号，来自当前输入图片顺序：图1 是第一张输入图片，图2 是第二张，以此类推。发送多张时优先使用 image_indexes。",
                    },
                    "image_indexes": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "要一次性发送的多张图片编号列表，例如 [1,2,3]。编号来自当前输入图片顺序。纯单张也可以只填 image_index。",
                    },
                },
                "required": ["reply", "text"],
            },
        },
    }


def info(ctx: dict[str, Any]) -> dict[str, str]:
    item = definition(ctx).get("function", {})
    return {
        "name": str(item.get("name") or "send_visible_image"),
        "description": str(item.get("description") or ""),
    }


def valid_message_ids(runtime: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    for item in runtime.get("context_messages", []):
        message_id = item.get("message_id") if isinstance(item, dict) else None
        if message_id is not None:
            values.add(str(message_id))
    event_message_id = runtime.get("event", {}).get("message_id")
    if event_message_id is not None:
        values.add(str(event_message_id))
    for image in runtime.get("images", []):
        if isinstance(image, dict) and image.get("message_id") is not None:
            values.add(str(image.get("message_id")))
    return values


def selected_image(runtime: dict[str, Any], image_index: Any) -> dict[str, Any] | None:
    try:
        index = int(image_index)
    except (TypeError, ValueError):
        return None
    images = runtime.get("images", [])
    if not isinstance(images, list) or index < 1 or index > len(images):
        return None
    image = images[index - 1]
    return image if isinstance(image, dict) else None


def image_index_values(args: dict[str, Any]) -> list[Any]:
    values = args.get("image_indexes")
    if isinstance(values, list):
        return values
    if values is not None:
        return [values]
    return [args.get("image_index")]


def selected_images(runtime: dict[str, Any], args: dict[str, Any]) -> tuple[list[dict[str, Any]], list[int]]:
    selected: list[dict[str, Any]] = []
    indexes: list[int] = []
    for value in image_index_values(args):
        try:
            index = int(value)
        except (TypeError, ValueError):
            continue
        image = selected_image(runtime, index)
        if image is not None and image not in selected:
            selected.append(image)
            indexes.append(index)
    return selected, indexes


def bool_arg(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "是", "回复"}
    return bool(value)


def image_segment(image: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    path = ctx["image_path"](image)
    return {"type": "image", "data": {"file": path.as_uri()}}


def message_segments(text: str, images: list[dict[str, Any]], ctx: dict[str, Any]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    if text:
        segments.append({"type": "text", "data": {"text": f"{text}\n"}})
    for image in images:
        segments.append(image_segment(image, ctx))
    return segments


async def execute(args: dict[str, Any], runtime: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    images, indexes = selected_images(runtime, args)
    if not images:
        return {"ok": False, "content": "发送图片失败：image_index/image_indexes 不在当前可用图片编号中。"}
    text = str(args.get("text") or "").strip()
    should_reply = bool_arg(args.get("reply"))
    message_id = str(args.get("message_id") or args.get("reply_message_id") or "").strip()
    if should_reply:
        if not message_id:
            return {"ok": False, "content": "发送图片失败：reply 为 true 时缺少 message_id。"}
        allowed_ids = valid_message_ids(runtime)
        if allowed_ids and message_id not in allowed_ids:
            return {"ok": False, "content": f"发送图片失败：message_id {message_id} 不在当前上下文消息列表中。"}
    try:
        segments = message_segments(text, images, ctx)
        if should_reply:
            await ctx["reply_to_message"](runtime["event"], message_id, segments)
        else:
            await ctx["reply"](runtime["event"], segments)
    except Exception as exc:
        return {"ok": False, "content": f"发送图片失败：{ctx['exception_detail'](exc)}"}
    return {
        "ok": True,
        "answered": True,
        "content": f"已发送指定输入图片 {len(images)} 张。",
        "reply": should_reply,
        "message_id": message_id if should_reply else "",
        "image_indexes": indexes,
    }
