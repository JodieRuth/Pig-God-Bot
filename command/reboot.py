import asyncio
from typing import Any


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    if not ctx["is_admin_event"](event):
        await ctx["reply"](event, "你没有权限使用重启指令。")
        return
    ctx["bot_state"]["stopped"] = False
    await ctx["reply"](event, "正在重启 bot 进程。")
    await asyncio.sleep(0.5)
    ctx["reboot_process"]()


COMMAND = {
    "name": "/reboot",
    "usage": "/reboot",
    "description": "仅所有者可用：重启 bot 进程。",
    "handler": handler,
}
