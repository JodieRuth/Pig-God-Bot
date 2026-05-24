from __future__ import annotations

import json
import random
import re
from pathlib import Path
from typing import Any

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
                    await ctx["reply"](event, f"#{item['id']} {item['text']}")
                    return
            await ctx["reply"](event, f"不存在编号 #{target_id}。")
            return
        lowered_query = query.lower()
        matched = [item for item in items if lowered_query in str(item.get("text", "")).lower()]
        if not matched:
            await ctx["reply"](event, f"没有找到包含“{query}”的内容。")
            return
        item = random.choice(matched)
        await ctx["reply"](event, f"#{item['id']} {item['text']}")
        return
    item = random.choice(items)
    await ctx["reply"](event, f"#{item['id']} {item['text']}")


COMMAND = {
    "name": "/sb",
    "usage": "/sb [#编号|关键词]",
    "description": "从 /sb_s 保存的内容中随机抽取一条；可指定编号，或按关键词匹配后随机抽取。",
    "handler": handler,
}
