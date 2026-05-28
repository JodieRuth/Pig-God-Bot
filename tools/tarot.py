from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Callable


def definition(ctx: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "tarot",
            "description": "进行一次本地塔罗牌占卜。只需要传入用户想占卜的问题，工具会返回完整的四张牌阵、正逆位、位置解读和综合建议。适用于用户明确要求塔罗、占卜、抽牌、运势、牌阵解读时。工具结果可直接作为回复正文使用，不需要再次改写为另一套占卜。",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "用户想占卜的问题。若用户没有具体问题，可传空字符串或概括为近期整体运势。",
                    },
                },
                "required": ["question"],
            },
        },
    }


def info(ctx: dict[str, Any]) -> dict[str, str]:
    item = definition(ctx).get("function", {})
    return {
        "name": str(item.get("name") or "tarot"),
        "description": str(item.get("description") or ""),
    }


def load_tarot_reading() -> Callable[[str], str]:
    tarot_path = Path(__file__).resolve().parents[1] / "command" / "tarot.py"
    spec = importlib.util.spec_from_file_location("local_onebot_command_tarot_for_tool", tarot_path)
    if not spec or not spec.loader:
        raise RuntimeError("无法加载 /tarot 命令模块。")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tarot_reading = getattr(module, "tarot_reading", None)
    if not callable(tarot_reading):
        raise RuntimeError("/tarot 命令模块缺少 tarot_reading 函数。")
    return tarot_reading


async def execute(args: dict[str, Any], runtime: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    question = str(args.get("question") or "").strip()
    try:
        tarot_reading = load_tarot_reading()
        content = tarot_reading(question)
    except Exception as exc:
        return {"ok": False, "content": f"塔罗占卜失败：{ctx['exception_detail'](exc)}"}
    return {"ok": True, "content": content}
