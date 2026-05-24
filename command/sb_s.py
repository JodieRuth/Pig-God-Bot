from __future__ import annotations

import json
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


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    text = arg.strip()
    if not text:
        await ctx["reply"](event, "用法：/sb_s <要保存的内容>")
        return
    items, next_id = load_items()
    item = {"id": next_id, "text": text}
    items.append(item)
    save_items(items, next_id + 1)
    await ctx["reply"](event, f"已保存为 #{item['id']}，当前共有 {len(items)} 条。")


COMMAND = {
    "name": "/sb_s",
    "usage": "/sb_s <内容>",
    "description": "保存一条带编号的内容，供 /sb 随机抽取。",
    "handler": handler,
}
