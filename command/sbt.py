from __future__ import annotations

import importlib.util
import random
from pathlib import Path
from typing import Any

import bot_policy_state

COMMON_MODULE = Path(__file__).with_name("sbt_common.py")
spec = importlib.util.spec_from_file_location("local_onebot_sbt_common", COMMON_MODULE)
if spec is None or spec.loader is None:
    raise RuntimeError("无法加载 sbt 数据模块")
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)


def item_fingerprint(item: dict[str, Any]) -> str:
    return bot_policy_state.image_content_fingerprint(common.item_md5(item))


async def send_item(
    event: dict[str, Any],
    item: dict[str, Any],
    ctx: dict[str, Any],
    allow_duplicate: bool = False,
) -> None:
    path = common.image_record_path(item)
    if not path.exists():
        await ctx["reply"](event, f"#{item['id']} 的图片文件不存在。")
        return
    fingerprint = item_fingerprint(item)
    if not fingerprint:
        await ctx["reply"](event, f"无法读取 #{item['id']} 的图片内容。")
        return
    result = bot_policy_state.claim_content_usage(
        int(event.get("user_id", 0)),
        fingerprint,
        allow_duplicate=allow_duplicate,
    )
    if result.reason == "duplicate":
        await ctx["reply"](event, f"#{item['id']} 今天已经发送过，明天重置后可以再次发送。")
        return
    if result.reason == "hourly_limit":
        await ctx["reply"](event, "你在最近一小时内已使用 /sb 和 /sbt 共 12 次，请稍后再试。")
        return
    if result.reason == "daily_limit":
        await ctx["reply"](event, "你今天已使用 /sb 和 /sbt 共 60 次，明天重置后可以继续使用。")
        return
    await ctx["reply"](event, [{"type": "text", "data": {"text": f"#{item['id']}\n"}}, common.image_segment(path)])


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
        sent_content = bot_policy_state.sent_content_fingerprints()
        available: list[dict[str, Any]] = []
        for value in items:
            if not common.image_record_path(value).exists():
                continue
            fingerprint = item_fingerprint(value)
            if fingerprint and fingerprint not in sent_content:
                available.append(value)
        if not available:
            await ctx["reply"](event, "今天所有可用的 /sbt 图片都已经发送过，明天重置后可以再次发送。")
            return
        item = random.choice(available)
    await send_item(event, item, ctx, allow_duplicate=bool(text))


COMMAND = {
    "name": "/sbt",
    "usage": "/sbt [#编号]",
    "description": "随机发送今日未发送的图片，指定编号可重复；/sb 与 /sbt 每个 QQ 每小时共 12 次、每天共 60 次。",
    "handler": handler,
}
