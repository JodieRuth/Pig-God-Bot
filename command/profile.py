from __future__ import annotations

import re
from typing import Any


def member_list_data(response: Any) -> list[dict[str, Any]]:
    if isinstance(response, dict) and isinstance(response.get("data"), list):
        return [item for item in response["data"] if isinstance(item, dict)]
    if isinstance(response, list):
        return [item for item in response if isinstance(item, dict)]
    return []


def member_display_name(member: dict[str, Any]) -> str:
    return str(member.get("card") or member.get("nickname") or member.get("user_id") or "").strip()


def member_line(index: int, member: dict[str, Any]) -> str:
    user_id = str(member.get("user_id") or "").strip()
    card = str(member.get("card") or "").strip() or "无"
    nickname = str(member.get("nickname") or "").strip() or "无"
    return f"{index}. QQ号：{user_id} | 群名片：{card} | QQ昵称：{nickname} | 显示名：{member_display_name(member)}"


async def handle_getlist(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    if not ctx["is_admin_event"](event):
        await ctx["reply"](event, "你没有权限使用这个指令。")
        return
    if event.get("message_type") != "group":
        await ctx["reply"](event, "/getlist 只能在群聊中使用。")
        return
    group_id = int(event.get("group_id", 0))
    if not group_id:
        await ctx["reply"](event, "无法识别当前群号。")
        return
    try:
        response = await ctx["onebot_post"]("get_group_member_list", {"group_id": group_id})
    except Exception as exc:
        await ctx["reply"](event, f"获取群成员列表失败：{ctx['exception_detail'](exc)}")
        return
    members = member_list_data(response)
    if not members:
        await ctx["reply"](event, "获取群成员列表失败或当前群成员列表为空。")
        return
    members.sort(key=lambda item: int(item.get("user_id") or 0) if str(item.get("user_id") or "").isdigit() else 0)
    lines = [f"群 {group_id} 成员映射，共 {len(members)} 人："]
    lines.extend(member_line(index, member) for index, member in enumerate(members, 1))
    await ctx["reply_forward"](event, lines)


async def handle_getprofile(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    target = arg.strip()
    if not re.fullmatch(r"\d{5,20}", target):
        await ctx["reply"](event, "用法：/getprofile <QQ号>")
        return
    avatar_url = ctx["qq_avatar_url"](target)
    await ctx["reply"](event, [
        {"type": "text", "data": {"text": f"QQ {target} 的头像：\n"}},
        {"type": "image", "data": {"file": avatar_url}},
    ])


COMMANDS = [
    {
        "name": "/getlist",
        "usage": "/getlist",
        "description": "仅所有者可用：导出当前群成员的 QQ号、群名片与 QQ昵称映射。",
        "handler": handle_getlist,
    },
    {
        "name": "/getprofile",
        "usage": "/getprofile <QQ号>",
        "description": "发送指定 QQ号的头像。",
        "handler": handle_getprofile,
    },
]
