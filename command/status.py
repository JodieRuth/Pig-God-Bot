from typing import Any


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    if not ctx["is_admin_event"](event):
        await ctx["reply"](event, "你没有权限使用控制指令。")
        return
    jobs = ctx["jobs"]
    await ctx["reply"](event, f"运行中任务：{', '.join(jobs.keys()) if jobs else '无'}")


COMMAND = {
    "name": "/status",
    "usage": "/status",
    "description": "仅所有者可用：查看当前运行中的图片任务。",
    "handler": handler,
}
