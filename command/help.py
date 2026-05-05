from typing import Any


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    if arg.strip().lower() == "plugins":
        await ctx["reply_forward"](event, ctx["plugin_help_text"](event).split("\n"))
        return
    await ctx["reply_forward"](event, ctx["command_help_text"]().split("\n"))


COMMAND = {
    "name": "/help",
    "usage": "/help [plugins]",
    "description": "查看可用指令。",
    "handler": handler,
}
