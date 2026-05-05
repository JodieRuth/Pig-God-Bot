from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).with_name("haochi")
FOODS_FILE = DATA_DIR / "foods.json"
DRINKS_FILE = DATA_DIR / "drinks.json"


def load_items(file: Path, fallback: str) -> list[str]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not file.exists():
        return [fallback]
    try:
        with file.open("r", encoding="utf-8") as f:
            items = json.load(f)
    except (json.JSONDecodeError, OSError):
        return [fallback]
    if not isinstance(items, list):
        return [fallback]
    result = [str(item).strip() for item in items if str(item).strip()]
    return result or [fallback]


def load_foods() -> list[str]:
    return load_items(FOODS_FILE, "麦乐鸡")


def load_drinks() -> list[str]:
    return load_items(DRINKS_FILE, "珍珠奶茶")


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    if random.random() < 0.5:
        food = random.choice(load_foods())
        await ctx["reply"](event, f"大猪今天吃{food}")
        return
    drink = random.choice(load_drinks())
    await ctx["reply"](event, f"大猪今天喝{drink}")


COMMAND = {
    "name": "/haochi",
    "usage": "/haochi",
    "description": "大猪今天吃什么？",
    "handler": handler,
}
