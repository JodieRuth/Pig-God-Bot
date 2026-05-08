from typing import Any


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    if not ctx["is_admin_event"](event):
        await ctx["reply"](event, "你没有权限使用控制指令。")
        return
    active_jobs = ctx.get("active_image_jobs", {})
    queued_jobs = ctx.get("image_queue", [])
    other_jobs = [job_id for job_id in ctx["jobs"].keys() if job_id not in active_jobs]
    lines = [
        f"正在生成的图片任务：{', '.join(active_jobs.keys()) if active_jobs else '无'}",
        f"排队中的图片任务：{', '.join(str(item.get('job_id')) for item in queued_jobs) if queued_jobs else '无'}",
    ]
    if other_jobs:
        lines.append(f"其他运行中任务：{', '.join(other_jobs)}")
    await ctx["reply"](event, "\n".join(lines))


COMMAND = {
    "name": "/status",
    "usage": "/status",
    "description": "仅所有者可用：查看当前运行中的图片任务。",
    "handler": handler,
}
