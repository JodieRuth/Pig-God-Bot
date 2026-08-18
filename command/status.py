from typing import Any

from _drawing_generation_runtime import (
    active_public_generation_ids,
    normalize_public_generation_id,
    stop_generation_wait,
)


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    if not ctx["is_admin_event"](event):
        await ctx["reply"](event, "你没有权限使用控制指令。")
        return
    target = arg.strip()
    if target:
        public_id = normalize_public_generation_id(target)
        if not public_id:
            await ctx["reply"](event, "用法：/status <八位本地模型任务ID>")
            return
        if not stop_generation_wait(public_id):
            await ctx["reply"](event, "没有找到这个任务。")
            return
        await ctx["reply"](
            event,
            f"任务 {public_id} 已取消，后续结果不会发送。",
        )
        return
    active_jobs = ctx.get("active_image_jobs", {})
    queued_jobs = ctx.get("image_queue", [])
    other_jobs = [job_id for job_id in ctx["jobs"].keys() if job_id not in active_jobs]
    local_jobs = active_public_generation_ids()
    lines = [
        f"正在生成的图片任务：{', '.join(active_jobs.keys()) if active_jobs else '无'}",
        f"排队中的图片任务：{', '.join(str(item.get('job_id')) for item in queued_jobs) if queued_jobs else '无'}",
        f"本地模型图片任务：{', '.join(local_jobs) if local_jobs else '无'}",
    ]
    if other_jobs:
        lines.append(f"其他运行中任务：{', '.join(other_jobs)}")
    await ctx["reply"](event, "\n".join(lines))


COMMAND = {
    "name": "/status",
    "usage": "/status [八位本地模型任务ID]",
    "description": "仅所有者可用：查看图片任务，或停止等待指定本地模型任务且不再发送其结果。",
    "handler": handler,
}
