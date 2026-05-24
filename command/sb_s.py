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
    text = arg.strip()
    if not text:
        await ctx["reply"](event, "用法：/sb_s <要保存的内容>")
        return
    items = load_items()
    items.append(text)
    save_items(items)
    await ctx["reply"](event, f"已保存，当前共有 {len(items)} 条。")


COMMAND = {
    "name": "/sb_s",
    "usage": "/sb_s <内容>",
    "description": "保存一条内容，供 /sb 随机抽取。",
    "handler": handler,
}
