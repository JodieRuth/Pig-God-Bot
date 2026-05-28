from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

COMMON_MODULE = Path(__file__).with_name("sbt_common.py")
spec = importlib.util.spec_from_file_location("local_onebot_sbt_common_r", COMMON_MODULE)
if spec is None or spec.loader is None:
    raise RuntimeError("无法加载 sbt 数据模块")
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    if not ctx["is_admin_event"](event):
        await ctx["reply"](event, "你没有权限使用 /sbt_r。")
        return
    target_id = common.parse_id(arg.strip())
    if target_id is None:
        await ctx["reply"](event, "用法：/sbt_r <#编号>")
        return
    items, next_id = common.load_items()
    removed: dict[str, Any] | None = None
    for index, item in enumerate(items):
        if int(item.get("id", 0)) == target_id:
            removed = items.pop(index)
            break
    if removed is None:
        await ctx["reply"](event, f"不存在编号 #{target_id}。")
        return
    path = common.image_record_path(removed)
    common.save_items(items, next_id)
    if path.exists():
        await ctx["reply"](event, [{"type": "text", "data": {"text": f"已移除图片 #{target_id}，当前剩余 {len(items)} 张。\n"}}, common.image_segment(path)])
        path.unlink(missing_ok=True)
    else:
        await ctx["reply"](event, f"已移除图片 #{target_id}，但对应图片文件不存在。当前剩余 {len(items)} 张。")


COMMAND = {
    "name": "/sbt_r",
    "usage": "/sbt_r <#编号>",
    "description": "仅管理员可用：按编号移除收藏图片。",
    "handler": handler,
}
