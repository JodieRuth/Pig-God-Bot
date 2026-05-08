from typing import Any


HELP_SECTION_SIZE = 10


def chunked_forward_lines(lines: list[str], chunk_size: int = HELP_SECTION_SIZE) -> list[str]:
    if not lines:
        return []
    result: list[str] = []
    current: list[str] = []
    for line in lines:
        if not line:
            if current:
                result.extend(current)
                result.append("")
                current = []
            continue
        current.append(line)
        if len(current) >= chunk_size:
            result.extend(current)
            result.append("")
            current = []
    if current:
        result.extend(current)
    while result and not result[-1]:
        result.pop()
    return result


def command_help_forward_lines(ctx: dict[str, Any]) -> list[str]:
    lines = ["可用指令："]
    command_items = ctx.get("command_help_items", {})
    for usage, description in sorted(command_items.items()):
        lines.append(f"{usage} - {description}")
    lines.append("/plugins - 查看和管理群插件。")
    lines = chunked_forward_lines(lines)
    lines.append("")
    lines.append("群聊中所有指令和对话都必须先 @ 我，再接命令或触发词。")
    lines.append("支持 @QQ号、@当前群名片或 @Pig god 等机器人识别到的艾特形式。")
    return lines


def plugin_help_forward_lines(event: dict[str, Any], ctx: dict[str, Any]) -> list[str]:
    return chunked_forward_lines(ctx["plugin_help_text"](event).split("\n"))


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    if arg.strip().lower() == "plugins":
        await ctx["reply_forward"](event, plugin_help_forward_lines(event, ctx))
        return
    await ctx["reply_forward"](event, command_help_forward_lines(ctx))


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
