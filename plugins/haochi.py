from __future__ import annotations

import importlib.util
import random
import re
from pathlib import Path
from typing import Any, Callable

COMMAND_PATH = Path(__file__).resolve().parent.parent / "command" / "haochi.py"
TRAILING_PUNCTUATION = " \t\r\n?？!！。~～…"


def load_haochi_command() -> Any:
    spec = importlib.util.spec_from_file_location("local_onebot_command_haochi_for_plugin", COMMAND_PATH)
    if not spec or not spec.loader:
        raise RuntimeError("无法加载 /haochi 命令模块")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pick_item(loader_name: str, fallback: str) -> str:
    try:
        module = load_haochi_command()
        loader: Callable[[], list[str]] | None = getattr(module, loader_name, None)
        items = loader() if callable(loader) else [fallback]
    except Exception:
        items = [fallback]
    choices = [str(item).strip() for item in items if str(item).strip()]
    return random.choice(choices or [fallback])


def normalized_text(text: str) -> str:
    return re.sub(r"\s+", "", text).rstrip(TRAILING_PUNCTUATION)


def match_kind(text: str) -> str:
    normalized = normalized_text(text)
    if normalized.endswith("吃什么"):
        return "food"
    if normalized.endswith("喝什么"):
        return "drink"
    return ""


async def handler(event: dict[str, Any], text: str, ctx: dict[str, Any]) -> bool:
    if str(event.get("user_id")) == str(ctx.get("bot_qq")):
        return False
    if event.get("message_type") != "group":
        return False

    kind = match_kind(text)
    if kind == "food":
        food = pick_item("load_foods", "麦乐鸡")
        await ctx["reply"](event, f"大猪今天吃{food}")
        return True
    if kind == "drink":
        drink = pick_item("load_drinks", "珍珠奶茶")
        await ctx["reply"](event, f"大猪今天喝{drink}")
        return True
    return False


PLUGIN = {
    "name": "haochi",
    "description": "订阅群内有人以吃什么/喝什么结尾时，随机回复今天吃或喝什么。",
    "handler": handler,
}
