from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DATA_FILE = Path(__file__).with_name("sb.json")


def load_items() -> list[str]:
    if not DATA_FILE.exists():
        return []
    try:
        with DATA_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    if isinstance(data, list):
        return [str(item) for item in data if str(item).strip()]
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return [str(item) for item in data["items"] if str(item).strip()]
    return []


def save_items(items: list[str]) -> None:
    with DATA_FILE.open("w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    if not ctx["is_admin_event"](event):
        await ctx["reply"](event, "你没有权限使用 /sb_r。")
        return
    text = arg.strip()
    if not text:
        await ctx["reply"](event, "用法：/sb_r <要移除的完整内容>")
        return
    items = load_items()
    try:
        items.remove(text)
    except ValueError:
        await ctx["reply"](event, "没有找到这条内容。")
        return
    save_items(items)
    await ctx["reply"](event, f"已移除，当前剩余 {len(items)} 条。")


COMMAND = {
    "name": "/sb_r",
    "usage": "/sb_r <内容>",
    "description": "仅管理员可用：从 /sb 内容池中移除一条完整匹配的内容。",
    "handler": handler,
}
