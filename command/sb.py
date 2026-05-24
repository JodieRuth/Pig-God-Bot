from __future__ import annotations

import json
import random
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


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    items = load_items()
    if not items:
        await ctx["reply"](event, "还没有保存任何内容，使用 /sb_s <内容> 添加。")
        return
    await ctx["reply"](event, random.choice(items))


COMMAND = {
    "name": "/sb",
    "usage": "/sb",
    "description": "从 /sb_s 保存的内容中随机抽取一条发送。",
    "handler": handler,
}
