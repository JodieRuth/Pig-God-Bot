from __future__ import annotations

import importlib.util
import random
from pathlib import Path
from typing import Any

COMMON_MODULE = Path(__file__).with_name("sbt_common.py")
spec = importlib.util.spec_from_file_location("local_onebot_sbt_common", COMMON_MODULE)
if spec is None or spec.loader is None:
    raise RuntimeError("无法加载 sbt 数据模块")
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    items, _ = common.load_items()
    if not items:
        await ctx["reply"](event, "还没有收藏任何图片，使用 /sbt_s 收藏。")
        return
    text = arg.strip()
    if text:
        target_id = common.parse_id(text)
        if target_id is None:
            await ctx["reply"](event, "用法：/sbt [#编号]")
            return
        item = next((value for value in items if int(value.get("id", 0)) == target_id), None)
        if item is None:
            await ctx["reply"](event, f"不存在编号 #{target_id}。")
            return
    else:
        item = random.choice(items)
    path = common.image_record_path(item)
    if not path.exists():
        await ctx["reply"](event, f"#{item['id']} 的图片文件不存在。")
        return
    await ctx["reply"](event, [{"type": "text", "data": {"text": f"#{item['id']}\n"}}, common.image_segment(path)])


COMMAND = {
    "name": "/sbt",
    "usage": "/sbt [#编号]",
    "description": "从收藏图片中随机发送一张；可指定编号发送对应图片。",
    "handler": handler,
}
