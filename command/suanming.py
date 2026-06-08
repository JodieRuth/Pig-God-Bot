from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Callable

CORE_PATH = Path(__file__).resolve().parent.parent / "tools" / "_suanming_core.py"
_spec = importlib.util.spec_from_file_location("local_onebot_suanming_core_for_command", CORE_PATH)
if not _spec or not _spec.loader:
    raise RuntimeError("无法加载六爻算命核心模块")
_core = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_core)

suanming_reading: Callable[[str], str] = _core.suanming_reading


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    try:
        await ctx["reply"](event, suanming_reading(arg.strip()))
    except Exception as exc:
        await ctx["reply"](event, f"六爻算命失败：{ctx['exception_detail'](exc)}")


COMMAND = {
    "name": "/suanming",
    "usage": "/suanming [想占卜的问题]",
    "description": "按当前北京时间进行一次时间起卦六爻占卜，回复本卦、动爻、变卦、旬空、六神和综合判断。",
    "handler": handler,
}
