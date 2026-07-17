from __future__ import annotations

import re
from typing import Any


def parse_qq_id(value: str) -> int | None:
    text = value.strip()
    for pattern in (r"(\d+)", r"@(\d+)", r"@.*\[(\d+)\]"):
        match = re.fullmatch(pattern, text)
        if match:
            user_id = int(match.group(1))
            return user_id if user_id > 0 else None
    return None


async def update_operator(event: dict[str, Any], arg: str, ctx: dict[str, Any], enabled: bool) -> None:
    if not ctx["is_admin_event"](event):
        await ctx["reply"](event, "你没有权限管理 OP。")
        return
    user_id = parse_qq_id(arg)
    if user_id is None:
        command = "/op" if enabled else "/deop"
        await ctx["reply"](event, f"用法：{command} <QQ号>")
        return
    changed = ctx["set_operator_user"](user_id, enabled)
    if changed:
        message = f"已{'授予' if enabled else '移除'} QQ {user_id} 的 OP 权限。"
    else:
        message = f"QQ {user_id} {'已经是 OP' if enabled else '当前不是 OP'}。"
    await ctx["reply"](event, message)


async def handle_op(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    await update_operator(event, arg, ctx, True)


async def handle_deop(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    await update_operator(event, arg, ctx, False)


COMMANDS = [
    {
        "name": "/op",
        "usage": "/op <QQ号>",
        "description": "仅管理员可用：授予用户 OP 权限。",
        "handler": handle_op,
    },
    {
        "name": "/deop",
        "usage": "/deop <QQ号>",
        "description": "仅管理员可用：移除用户的 OP 权限。",
        "handler": handle_deop,
    },
]
