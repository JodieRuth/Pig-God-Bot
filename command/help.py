from typing import Any


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    if arg.strip().lower() == "plugins":
        await ctx["reply"](event, ctx["plugin_help_text"](event))
        return
    await ctx["reply"](event, ctx["command_help_text"]())


COMMAND = {
    "name": "/help",
    "usage": "/help [plugins]",
    "description": "查看可用指令。",
    "handler": handler,
}
