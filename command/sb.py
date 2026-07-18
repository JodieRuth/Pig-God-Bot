from __future__ import annotations

import json
import random
import re
from pathlib import Path
from typing import Any

import bot_policy_state

DATA_FILE = Path(__file__).with_name("sb.json")


def normalize_data(data: Any) -> tuple[list[dict[str, Any]], int, bool]:
    changed = False
    items: list[dict[str, Any]] = []
    next_id = 1
    raw_items = data.get("items") if isinstance(data, dict) else data
    if isinstance(data, dict):
        try:
            next_id = max(1, int(data.get("next_id", 1)))
        except (TypeError, ValueError):
            changed = True
            next_id = 1
    if not isinstance(raw_items, list):
        return [], next_id, True
    used_ids: set[int] = set()
    for raw in raw_items:
        if isinstance(raw, dict):
            text = str(raw.get("text") or "").strip()
            try:
                item_id = int(raw.get("id", 0))
            except (TypeError, ValueError):
                item_id = 0
            if not text:
                changed = True
                continue
            if item_id <= 0 or item_id in used_ids:
                item_id = next_id
                next_id += 1
                changed = True
            used_ids.add(item_id)
            items.append({"id": item_id, "text": text})
            next_id = max(next_id, item_id + 1)
            continue
        text = str(raw).strip()
        if not text:
            changed = True
            continue
        item_id = next_id
        next_id += 1
        used_ids.add(item_id)
        items.append({"id": item_id, "text": text})
        changed = True
    return items, next_id, changed


def save_items(items: list[dict[str, Any]], next_id: int) -> None:
    with DATA_FILE.open("w", encoding="utf-8") as f:
        json.dump({"next_id": next_id, "items": items}, f, ensure_ascii=False, indent=2)


def load_items() -> tuple[list[dict[str, Any]], int]:
    if not DATA_FILE.exists():
        return [], 1
    try:
        with DATA_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return [], 1
    items, next_id, changed = normalize_data(data)
    if changed:
        save_items(items, next_id)
    return items, next_id


def parse_id(text: str) -> int | None:
    match = re.fullmatch(r"#?(\d+)", text.strip())
    return int(match.group(1)) if match else None


def item_fingerprint(item: dict[str, Any]) -> str:
    return bot_policy_state.text_content_fingerprint(str(item.get("text") or ""))


async def send_item(
    event: dict[str, Any],
    item: dict[str, Any],
    ctx: dict[str, Any],
    allow_duplicate: bool = False,
) -> None:
    result = bot_policy_state.claim_content_usage(
        int(event.get("user_id", 0)),
        item_fingerprint(item),
        allow_duplicate=allow_duplicate,
    )
    if result.reason == "duplicate":
        await ctx["reply"](event, f"#{item['id']} 今天已经发送过，明天重置后可以再次发送。")
        return
    if result.reason == "hourly_limit":
        await ctx["reply"](event, "你在最近一小时内已使用 /sb、/sbt、/rp 和 /rpp 共 12 次，请稍后再试。")
        return
    if result.reason == "daily_limit":
        await ctx["reply"](event, "你今天已使用 /sb、/sbt、/rp 和 /rpp 共 60 次，明天重置后可以继续使用。")
        return
    await ctx["reply"](event, f"#{item['id']} {item['text']}")


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    items, _ = load_items()
    if not items:
        await ctx["reply"](event, "还没有保存任何内容，使用 /sb_s <内容> 添加。")
        return
    query = arg.strip()
    if query:
        target_id = parse_id(query)
        if target_id is not None:
            for item in items:
                if int(item.get("id", 0)) == target_id:
                    await send_item(event, item, ctx, allow_duplicate=True)
                    return
            await ctx["reply"](event, f"不存在编号 #{target_id}。")
            return
        lowered_query = query.lower()
        matched = [item for item in items if lowered_query in str(item.get("text", "")).lower()]
        if not matched:
            await ctx["reply"](event, f"没有找到包含“{query}”的内容。")
            return
        await send_item(event, random.choice(matched), ctx, allow_duplicate=True)
        return
    sent_content = bot_policy_state.sent_content_fingerprints()
    available = [item for item in items if item_fingerprint(item) not in sent_content]
    if not available:
        await ctx["reply"](event, "今天所有 /sb 内容都已经发送过，明天重置后可以再次发送。")
        return
    await send_item(event, random.choice(available), ctx)


COMMAND = {
    "name": "/sb",
    "usage": "/sb [#编号|关键词]",
    "description": "随机抽取今日未发送的内容，指定编号或关键词可重复；与 /sbt、/rp、/rpp 共用个人限额。",
    "handler": handler,
}
