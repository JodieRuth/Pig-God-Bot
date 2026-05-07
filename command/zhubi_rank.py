from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

COMMON_MODULE = Path(__file__).with_name("zhubi_ext_common.py")
spec = importlib.util.spec_from_file_location("local_onebot_zhubi_ext_common_rank", COMMON_MODULE)
if spec is None or spec.loader is None:
    raise RuntimeError("无法加载猪币扩展模块")
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)
zhubi = common.zhubi


async def group_members(ctx: dict[str, Any], group_id: int) -> list[dict[str, Any]]:
    data = await ctx["onebot_post"]("get_group_member_list", {"group_id": group_id})
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        return data["data"]
    if isinstance(data, list):
        return data
    return []


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    if event.get("message_type") != "group":
        await ctx["reply"](event, "/zhubi_rank 只能在群聊中使用。")
        return
    group_id = int(event.get("group_id", 0))
    sender_id = str(event.get("user_id", 0))
    members = await group_members(ctx, group_id)
    if not members:
        await ctx["reply"](event, "获取群成员列表失败，无法生成猪币排行。")
        return
    member_ids = {str(item.get("user_id")) for item in members if str(item.get("user_id", "")).isdigit()}
    names = {
        str(item.get("user_id")): str(item.get("card") or item.get("nickname") or item.get("user_id"))
        for item in members
        if str(item.get("user_id", "")).isdigit()
    }
    data = zhubi.load_data()
    common.apply_idle_income(data)
    rows: list[tuple[float, str, str]] = []
    for user_id in member_ids:
        user = zhubi.user_data(data, user_id)
        balance = common.balance_of(user)
        if balance > 0:
            rows.append((balance, user_id, names.get(user_id, user_id)))
    zhubi.save_data(data)
    if not rows:
        await ctx["reply"](event, "本群暂时没有人持有猪币。")
        return
    rows.sort(key=lambda item: item[0], reverse=True)
    rank_by_user = {user_id: index for index, (_, user_id, _) in enumerate(rows, start=1)}
    lines = ["本群猪币排行前 10："]
    for index, (balance, user_id, name) in enumerate(rows[:10], start=1):
        lines.append(f"{index}. {name}：{common.format_amount(balance)}")
    sender_rank = rank_by_user.get(sender_id)
    if sender_rank is None:
        lines.append(f"你的当前名次：未上榜，当前持有 {common.format_amount(0)}。")
    elif sender_rank > 10:
        sender_balance = next(balance for balance, user_id, _ in rows if user_id == sender_id)
        lines.append(f"你的当前名次：第 {sender_rank} 名，持有 {common.format_amount(sender_balance)}。")
    else:
        lines.append(f"你的当前名次：第 {sender_rank} 名。")
    await ctx["reply"](event, "\n".join(lines))


COMMAND = {
    "name": "/zhubi_rank",
    "usage": "/zhubi_rank",
    "description": "列出本群成员猪币排行前 10，并显示命令发送者当前名次。",
    "handler": handler,
}
