from __future__ import annotations

import importlib.util
import random
import time
from pathlib import Path
from typing import Any

COMMON_MODULE = Path(__file__).with_name("zhubi_ext_common.py")
spec = importlib.util.spec_from_file_location("local_onebot_zhubi_ext_common_pvp", COMMON_MODULE)
if spec is None or spec.loader is None:
    raise RuntimeError("无法加载猪币扩展模块")
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)
zhubi = common.zhubi

PENDING_TTL = 15 * 60
DAILY_PVP_LIMIT = 3
PVP_NORMAL_MAX_RATIO = 10000
PVP_MAX_UNIT_MAX_RATIO = 100


async def group_member(ctx: dict[str, Any], group_id: int, user_id: int) -> dict[str, Any] | None:
    try:
        data = await ctx["onebot_post"]("get_group_member_info", {"group_id": group_id, "user_id": user_id, "no_cache": False})
    except Exception:
        return None
    if isinstance(data, dict):
        if data.get("status") == "failed" or data.get("retcode") not in (None, 0):
            return None
        member = data.get("data") if isinstance(data.get("data"), dict) else data
        if str(member.get("user_id", "")) == str(user_id) or member.get("nickname") or member.get("card"):
            return member
    return None


def member_name(member: dict[str, Any] | None, fallback: str) -> str:
    if not member:
        return fallback
    return str(member.get("card") or member.get("nickname") or fallback)


def pending_store(data: dict[str, Any]) -> dict[str, Any]:
    store = data.setdefault("pvp_pending", {})
    if isinstance(store, dict):
        return store
    data["pvp_pending"] = {}
    return data["pvp_pending"]


def clean_pending(data: dict[str, Any]) -> None:
    now = time.time()
    store = pending_store(data)
    expired = [key for key, value in store.items() if not isinstance(value, dict) or now - float(value.get("time", 0)) > PENDING_TTL]
    for key in expired:
        delete_pending(data, store, key)


def delete_pending(data: dict[str, Any], store: dict[str, Any], key: str) -> None:
    store.pop(key, None)
    deleted = data.setdefault("_pvp_pending_deleted", [])
    if isinstance(deleted, list):
        deleted.append(key)
    else:
        data["_pvp_pending_deleted"] = [key]


def user_has_pending(store: dict[str, Any], user_id: str) -> bool:
    for value in store.values():
        if not isinstance(value, dict):
            continue
        if str(value.get("from")) == user_id or str(value.get("to")) == user_id:
            return True
    return False


def target_is_busy(store: dict[str, Any], user_id: str) -> bool:
    for value in store.values():
        if not isinstance(value, dict):
            continue
        if str(value.get("to")) == user_id:
            return True
    return False


def challenge_key(group_id: int, user_a: str, user_b: str) -> str:
    first, second = sorted([user_a, user_b])
    return f"{group_id}:{first}:{second}"


def win_probability(amount_a: int, amount_b: int) -> float:
    total = amount_a + amount_b
    if total <= 0:
        return 0.5
    return min(0.75, max(0.25, amount_a / total))


def pvp_amount_gap_too_large(amount_a: int, amount_b: int) -> bool:
    smaller = max(1, min(amount_a, amount_b))
    larger = max(amount_a, amount_b)
    max_ratio = PVP_MAX_UNIT_MAX_RATIO if larger > common.MAX_UNIT else PVP_NORMAL_MAX_RATIO
    return larger / smaller >= max_ratio


def parse_add_args(arg: str) -> tuple[str, int] | None:
    parts = arg.split()
    if len(parts) != 3 or parts[0].lower() != "add":
        return None
    user_id = parts[1].strip()
    if not user_id.isdigit():
        return None
    try:
        amount = int(parts[2])
    except ValueError:
        return None
    if amount <= 0:
        return None
    return user_id, amount


def pvp_available(user: dict[str, Any]) -> int:
    return DAILY_PVP_LIMIT + int(user.get("daily_pvp_extra", 0)) - int(user.get("daily_pvp_used", 0))


async def handle_add(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> bool:
    if not arg.strip().lower().startswith("add"):
        return False
    if not ctx["is_admin_event"](event):
        await ctx["reply"](event, "你没有权限使用 PVP 次数管理指令。")
        return True
    parsed = parse_add_args(arg)
    if parsed is None:
        await ctx["reply"](event, "用法：/zhubi_pvp add <QQ号> <今日额外次数>")
        return True
    target_id, amount = parsed
    data = zhubi.load_data()
    target = zhubi.user_data(data, target_id)
    target["daily_pvp_extra"] = int(target.get("daily_pvp_extra", 0)) + amount
    zhubi.save_data(data)
    await ctx["reply"](event, f"已为 QQ {target_id} 增加今日 PVP 次数 {amount} 次，今日剩余：{max(0, pvp_available(target))} 次。")
    return True


def extract_at_target(message: list[dict[str, Any]]) -> int | None:
    for seg in message:
        if seg.get("type") == "at":
            qq = str(seg.get("data", {}).get("qq") or "")
            if qq.isdigit():
                return int(qq)
    return None


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    if await handle_add(event, arg, ctx):
        return
    if event.get("message_type") != "group":
        await ctx["reply"](event, "/zhubi_pvp 只能在群聊中使用。")
        return
    group_id = int(event.get("group_id", 0))
    challenger_id = str(event.get("user_id", 0))
    message = event.get("message", [])
    at_target = extract_at_target(message)
    parts = arg.split()
    if len(parts) >= 2 and any(part.isdigit() for part in parts[:-1]):
        target_id = next(part for part in parts[:-1] if part.isdigit())
        amount = common.parse_positive_int(parts[-1])
    elif at_target is not None:
        target_id = str(at_target)
        amount = common.parse_positive_int(parts[-1]) if parts else None
    else:
        if len(parts) != 2 or not parts[0].isdigit():
            await ctx["reply"](event, "用法：/zhubi_pvp <QQ号或@某人> <猪币数量或nMAX+数字>；仅所有者：/zhubi_pvp add <QQ号> <今日额外次数>")
            return
        target_id = parts[0]
        amount = common.parse_positive_int(parts[1])
    if amount is None:
        await ctx["reply"](event, "PVP 投入数量必须是正数，支持 40MAX+12000000 格式；不足 1 的部分不会用于 PVP。")
        return
    if target_id == challenger_id:
        await ctx["reply"](event, "不能和自己打 PVP。")
        return
    challenger_member = await group_member(ctx, group_id, int(challenger_id))
    target_member = await group_member(ctx, group_id, int(target_id))
    if not target_member:
        await ctx["reply"](event, "目标 QQ 必须是当前群成员。")
        return
    challenger_name = member_name(challenger_member, challenger_id)
    target_name = member_name(target_member, target_id)
    data = zhubi.load_data()
    common.apply_idle_income(data)
    clean_pending(data)
    challenger = zhubi.user_data(data, challenger_id)
    is_admin = ctx["is_admin_event"](event)
    if common.total_holding(challenger) < amount:
        await ctx["reply"](event, f"猪币不足。你当前持有：{common.format_amount(common.total_holding(challenger))}。")
        zhubi.save_data(data)
        return
    key = challenge_key(group_id, challenger_id, target_id)
    store = pending_store(data)
    pending = store.get(key)
    if pending and str(pending.get("from")) == target_id and str(pending.get("to")) == challenger_id:
        pending_amount = int(pending.get("amount", 0))
        target = zhubi.user_data(data, target_id)
        if common.total_holding(target) < pending_amount:
            delete_pending(data, store, key)
            zhubi.save_data(data)
            await ctx["reply"](event, f"{target_name} 猪币不足，PVP 已取消。")
            return
        if pvp_amount_gap_too_large(amount, pending_amount):
            delete_pending(data, store, key)
            zhubi.save_data(data)
            await ctx["reply"](event, "双方投入差距过大，这场比赛并不公平，已被取消")
            return
        challenger_probability = win_probability(amount, pending_amount)
        challenger_wins = random.random() < challenger_probability
        winner_id, loser_id = (challenger_id, target_id) if challenger_wins else (target_id, challenger_id)
        winner_name, loser_name = (challenger_name, target_name) if challenger_wins else (target_name, challenger_name)
        winner = zhubi.user_data(data, winner_id)
        loser = zhubi.user_data(data, loser_id)
        loser_amount = pending_amount if challenger_wins else amount
        reward = int(round(loser_amount * 0.75))
        pool_amount = max(0, loser_amount - reward)
        common.spend_amount(loser, float(loser_amount))
        common.change_balance(winner, reward)
        mine_state = zhubi.normalize_mine_state(data)
        mine_state["pool"] = int(mine_state.get("pool", 0)) + pool_amount
        delete_pending(data, store, key)
        zhubi.save_data(data)
        await ctx["reply"](event, f"PVP 开始！{challenger_name} 投入 {common.format_amount(amount)}，{target_name} 投入 {common.format_amount(pending_amount)}。{challenger_name} 胜率 {challenger_probability:.1%}，{target_name} 胜率 {1 - challenger_probability:.1%}。胜者：{winner_name}，获得败者投入的 75%：{common.format_amount(reward)}；败者：{loser_name}，损失 {common.format_amount(loser_amount)}；进入猪池：{common.format_amount(pool_amount)}。")
        return
    if not is_admin and user_has_pending(store, challenger_id):
        zhubi.save_data(data)
        await ctx["reply"](event, "你当前已经在一个 PVP 挑战中，需等待应战、结算或 15 分钟超时后才能再次发起。")
        return
    if not is_admin and target_is_busy(store, target_id):
        zhubi.save_data(data)
        await ctx["reply"](event, f"{target_name} 当前已经在一个 PVP 挑战中，暂时不能被挑战。")
        return
    if not is_admin and pvp_available(challenger) <= 0:
        zhubi.save_data(data)
        await ctx["reply"](event, "你今天的 PVP 发起次数已经用完。")
        return
    if not is_admin:
        challenger["daily_pvp_used"] = int(challenger.get("daily_pvp_used", 0)) + 1
    store[key] = {"from": challenger_id, "to": target_id, "amount": amount, "group_id": group_id, "time": time.time()}
    zhubi.save_data(data)
    await ctx["reply"](event, f"{challenger_name} 向 {target_name} 发起猪币 PVP，投入 {common.format_amount(amount)}。{target_name} 15 分钟内输入 /zhubi_pvp {challenger_id} <投入数量> 即可应战，应战不消耗次数；双方投入可不同，胜率按投入比例计算并限制在 25% 到 75%。今日剩余发起次数：{'不限' if is_admin else str(max(0, pvp_available(challenger)))}。")


COMMAND = {
    "name": "/zhubi_pvp",
    "usage": "/zhubi_pvp <QQ号或@某人> <猪币数量或nMAX+数字>；仅所有者：/zhubi_pvp add <QQ号> <今日额外次数>",
    "description": "发起猪币 PVP，支持@对象，每人每天3次发起机会，败者25%损失入猪池。",
    "handler": handler,
}
