from typing import Any


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    count = ctx["clear_current_context"](event)
    await ctx["reply"](event, f"已清空当前会话上下文，共移除 {count} 条缓存。")


COMMAND = {
    "name": "/clear",
    "usage": "/clear",
    "description": "清空当前群聊或私聊的上下文缓存。",
    "handler": handler,
}
