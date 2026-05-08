from typing import Any


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    if not ctx["is_admin_event"](event):
        await ctx["reply"](event, "你没有权限使用控制指令。")
        return
    job_id = arg.strip()
    if not job_id:
        await ctx["reply"](event, "用法：/cancel <任务ID>")
        return
    if not await ctx["cancel_image_job"](job_id):
        await ctx["reply"](event, "没有找到这个任务。")
        return
    await ctx["reply"](event, f"已请求取消任务 {job_id}。")


COMMAND = {
    "name": "/cancel",
    "usage": "/cancel <任务ID>",
    "description": "仅所有者可用：取消指定图片任务。",
    "handler": handler,
}
