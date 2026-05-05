from __future__ import annotations

from typing import Any


def definition(ctx: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "reply_to_context_message",
            "description": "直接回复当前会话上下文中的某一条消息。可用于需要针对某人某条消息作答、纠正、补充、吐槽、解释、引用回答时。调用后机器人会把 answer 作为回复段发到指定 message_id 下方；如果此工具调用成功，就代表已经完成对用户的回答，不需要再输出普通文本。",
            "parameters": {
                "type": "object",
                "properties": {
                    "message_id": {
                        "type": "string",
                        "description": "要回复的上下文消息 ID。必须来自当前请求提供的上下文消息列表。",
                    },
                    "answer": {
                        "type": "string",
                        "description": "要发送给 QQ 用户的完整回复文本。",
                    },
                },
                "required": ["message_id", "answer"],
            },
        },
    }


def info(ctx: dict[str, Any]) -> dict[str, str]:
    item = definition(ctx).get("function", {})
    return {
        "name": str(item.get("name") or "reply_to_context_message"),
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


async def execute(args: dict[str, Any], runtime: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    message_id = str(args.get("message_id") or "").strip()
    answer = str(args.get("answer") or "").strip()
    if not message_id:
        return {"ok": False, "content": "回复失败：缺少 message_id。"}
    if not answer:
        return {"ok": False, "content": "回复失败：缺少 answer。"}
    allowed_ids = valid_message_ids(runtime)
    if allowed_ids and message_id not in allowed_ids:
        return {"ok": False, "content": f"回复失败：message_id {message_id} 不在当前上下文消息列表中。"}
    try:
        await ctx["reply_to_message"](runtime["event"], message_id, answer)
    except Exception as exc:
        return {"ok": False, "content": f"回复失败：{ctx['exception_detail'](exc)}"}
    return {"ok": True, "content": "已回复指定上下文消息。", "message_id": message_id}
