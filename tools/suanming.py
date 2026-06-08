from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Callable

CORE_PATH = Path(__file__).resolve().parent / "_suanming_core.py"
_spec = importlib.util.spec_from_file_location("local_onebot_suanming_core_for_tool", CORE_PATH)
if not _spec or not _spec.loader:
    raise RuntimeError("无法加载六爻算命核心模块")
_core = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_core)

suanming_reading: Callable[[str], str] = _core.suanming_reading


def definition(ctx: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "suanming",
            "description": "按当前北京时间进行一次本地六爻时间起卦。只需要传入用户想占卜的问题，工具会把当前年月日时转换为农历、干支、节令、旬空、本卦、动爻和变卦，并返回可读的六爻结果。适用于用户明确要求算命、算卦、六爻、起卦、卜一卦、测一件事时。",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "用户想占卜的问题。格式类似 /suanming [问题]；如果没有具体问题，可传空字符串。",
                    },
                },
                "required": ["question"],
            },
        },
    }


def info(ctx: dict[str, Any]) -> dict[str, str]:
    item = definition(ctx).get("function", {})
    return {
        "name": str(item.get("name") or "suanming"),
        "description": str(item.get("description") or ""),
    }


async def execute(args: dict[str, Any], runtime: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    question = str(args.get("question") or "").strip()
    try:
        content = suanming_reading(question)
    except Exception as exc:
        return {"ok": False, "content": f"六爻算命失败：{ctx['exception_detail'](exc)}"}
    return {"ok": True, "content": content}
