from typing import Any


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    if not ctx["is_admin_event"](event):
        await ctx["reply"](event, "你没有权限使用控制指令。")
        return
    ctx["bot_state"]["stopped"] = False
    await ctx["reply"](event, "已恢复响应。")


COMMAND = {
    "name": "/restart",
    "usage": "/restart",
    "description": "仅所有者可用：恢复 bot 响应。",
    "handler": handler,
}
