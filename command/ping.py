from typing import Any


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    await ctx["reply"](event, "pong")


COMMAND = {
    "name": "/ping",
    "usage": "/ping",
    "description": "检查 bot 是否在线。",
    "handler": handler,
}
