from __future__ import annotations

import re
from typing import Any


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    target = arg.strip()
    if not re.fullmatch(r"\d{5,20}", target):
        await ctx["reply"](event, "用法：/getprofile <QQ号>")
        return
    avatar_url = ctx["qq_avatar_url"](target)
    await ctx["reply"](event, [
        {"type": "text", "data": {"text": f"QQ {target} 的头像：\n"}},
        {"type": "image", "data": {"file": avatar_url}},
    ])


COMMAND = {
    "name": "/getprofile",
    "usage": "/getprofile <QQ号>",
    "description": "发送指定 QQ号的头像。",
    "handler": handler,
}
