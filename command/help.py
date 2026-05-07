from typing import Any


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    if arg.strip().lower() == "plugins":
        await ctx["reply_forward"](event, ctx["plugin_help_text"](event).split("\n"))
        return
    await ctx["reply_forward"](event, ctx["command_help_text"]().split("\n"))


async def handler_show(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    if arg.strip().lower() == "plugins":
        await ctx["reply"](event, ctx["plugin_help_text"](event))
        return
    await ctx["reply"](event, ctx["command_help_text"]())


COMMANDS = [
    {
        "name": "/help",
        "usage": "/help [plugins]",
        "description": "查看可用指令，以转发聊天集合发送。",
        "handler": handler,
    },
    {
        "name": "/help_show",
        "usage": "/help_show [plugins]",
        "description": "查看可用指令，直接回复消息。",
        "handler": handler_show,
    },
]
