from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

COMMON_MODULE = Path(__file__).with_name("sbt_common.py")
spec = importlib.util.spec_from_file_location("local_onebot_sbt_common_s", COMMON_MODULE)
if spec is None or spec.loader is None:
    raise RuntimeError("无法加载 sbt 数据模块")
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    items, next_id = common.load_items()
    target = await common.save_source_image(event, ctx, next_id)
    if target is None or not target.exists():
        await ctx["reply"](event, "没有找到可收藏的图片：请在本条消息附图、回复一条带图消息，或先发送一张图片。")
        return
    item = {
        "id": next_id,
        "path": str(target),
        "text": target.name,
        "sender_id": event.get("user_id"),
        "sender_name": str(event.get("sender", {}).get("card") or event.get("sender", {}).get("nickname") or event.get("user_id", "")),
    }
    items.append(item)
    common.save_items(items, next_id + 1)
    await ctx["reply"](event, [{"type": "text", "data": {"text": f"已收藏为 #{next_id}\n"}}, common.image_segment(target)])


COMMAND = {
    "name": "/sbt_s",
    "usage": "/sbt_s",
    "description": "收藏本条消息、被回复消息或发送者上一张图片，并复读原图。",
    "handler": handler,
}
