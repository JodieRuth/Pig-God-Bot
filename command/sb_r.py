from __future__ import annotations

import json
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
    if not ctx["is_admin_event"](event):
        await ctx["reply"](event, "你没有权限使用 /sb_r。")
        return
    items, next_id = load_items()
    if not items:
        await ctx["reply"](event, "当前没有可移除的内容。")
        return
    text = arg.strip()
    removed: dict[str, Any] | None = None
    if not text:
        removed = items.pop()
    else:
        target_id = parse_id(text)
        if target_id is None:
            await ctx["reply"](event, "用法：/sb_r [#编号]；不传参数时移除最新添加的一条。")
            return
        for index, item in enumerate(items):
            if int(item.get("id", 0)) == target_id:
                removed = items.pop(index)
                break
    if removed is None:
        await ctx["reply"](event, "没有找到这个编号。")
        return
    save_items(items, next_id)
    await ctx["reply"](event, f"已移除 #{removed['id']}：{removed['text']}。当前剩余 {len(items)} 条。")


COMMAND = {
    "name": "/sb_r",
    "usage": "/sb_r [#编号]",
    "description": "仅管理员可用：按编号移除 /sb 内容池中的内容；不传参数时移除最新添加的一条。",
    "handler": handler,
}
