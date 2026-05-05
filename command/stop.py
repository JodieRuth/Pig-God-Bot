import asyncio
from typing import Any


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    if not ctx["is_admin_event"](event):
        await ctx["reply"](event, "你没有权限使用控制指令。")
        return
    command = arg.strip().lower()
    if command == "/reboot":
        ctx["bot_state"]["stopped"] = False
        await ctx["reply"](event, "正在重启 bot 进程。")
        await asyncio.sleep(0.5)
        ctx["reboot_process"]()
        return
    ctx["bot_state"]["stopped"] = True
    await ctx["reply"](event, "已停止响应。使用 /restart 恢复。")


COMMAND = {
    "name": "/stop",
    "usage": "/stop",
    "description": "仅所有者可用：停止 bot 响应。",
    "handler": handler,
}
