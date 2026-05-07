from __future__ import annotations

import importlib.util
import random
from pathlib import Path
from typing import Any

COMMON_MODULE = Path(__file__).with_name("zhubi_ext_common.py")
spec = importlib.util.spec_from_file_location("local_onebot_zhubi_ext_common_fakuang", COMMON_MODULE)
if spec is None or spec.loader is None:
    raise RuntimeError("无法加载猪币扩展模块")
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)
zhubi = common.zhubi


def parse_amount(arg: str) -> int | None:
    amount = common.parse_positive_amount(arg)
    if amount is None:
        return None
    whole = int(amount)
    return whole if whole > 0 else None


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
    return (user_id, amount) if amount > 0 else None


async def handle_add(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> bool:
    if not arg.strip().lower().startswith("add"):
        return False
    if not ctx["is_admin_event"](event):
        await ctx["reply"](event, "你没有权限使用发狂配额管理指令。")
        return True
    parsed = parse_add_args(arg)
    if parsed is None:
        await ctx["reply"](event, "用法：/zhubi_fakuang add <QQ号> <今日额外次数>")
        return True
    target_id, amount = parsed
    data = zhubi.load_data()
    target = zhubi.user_data(data, target_id)
    target["daily_fakuang_extra"] = int(target.get("daily_fakuang_extra", 0)) + amount
    zhubi.save_data(data)
    available = 1 + int(target.get("daily_fakuang_extra", 0)) - int(target.get("daily_fakuang_used", 0))
    await ctx["reply"](event, f"已为 QQ {target_id} 增加今日发狂次数 {amount} 次，今日剩余：{max(0, available)} 次。")
    return True


def mining_return(amount: int, data: dict[str, Any]) -> int:
    state = zhubi.normalize_mine_state(data)
    pressure = float(state.get("pressure", 1.0))
    recent_rate = float(state.get("recent_rate", 1.0))
    base = random.uniform(0.72, 1.16)
    sweet_chance = min(0.28, max(0.08, 0.18 + (0.96 - recent_rate) * 0.45 - (pressure - 1.0) * 0.06))
    if random.random() < sweet_chance:
        base += random.uniform(0.18, 0.55)
    pity = min(0.22, int(state.get("loss_streak", 0)) * 0.045)
    heat = min(0.18, int(state.get("win_streak", 0)) * 0.04)
    target = min(1.05, max(0.86, 0.96 - (pressure - 1.0) * 0.10 + pity - heat))
    rate = max(0.25, base * target)
    return max(1, int(amount * rate))


def apply_pool(amount: int, returned: int, data: dict[str, Any]) -> tuple[int, int, int]:
    state = zhubi.normalize_mine_state(data)
    pool_before = int(state.get("pool", 0))
    if returned <= amount:
        added = int((amount - returned) * 0.85)
        state["pool"] = pool_before + added
        return returned, added, 0
    max_bonus = amount // 2
    if max_bonus <= 0 or pool_before <= 0:
        return returned, 0, 0
    pressure = float(state.get("pressure", 1.0))
    draw_ratio = random.uniform(0.08, 0.28) / max(0.75, pressure)
    bonus = min(pool_before, max_bonus, max(1, int(amount * draw_ratio)))
    state["pool"] = pool_before - bonus
    return returned + bonus, 0, bonus


def update_mine_state(data: dict[str, Any], amount: int, returned: int) -> None:
    state = zhubi.normalize_mine_state(data)
    state["recent_spent"] = int(int(state.get("recent_spent", 0)) * 0.85 + amount)
    state["recent_returned"] = int(int(state.get("recent_returned", 0)) * 0.85 + returned)
    if state["recent_spent"] > 0:
        state["recent_rate"] = round(state["recent_returned"] / state["recent_spent"], 4)
    if returned > amount:
        state["win_streak"] = int(state.get("win_streak", 0)) + 1
        state["loss_streak"] = 0
    else:
        state["loss_streak"] = int(state.get("loss_streak", 0)) + 1
        state["win_streak"] = 0
    pressure = float(state.get("pressure", 1.0))
    if float(state.get("recent_rate", 1.0)) > 1.02:
        pressure += 0.04
    elif float(state.get("recent_rate", 1.0)) < 0.88:
        pressure -= 0.05
    else:
        pressure += (1.0 - pressure) * 0.03
    pressure += int(state.get("win_streak", 0)) * 0.01
    pressure -= min(0.04, int(state.get("loss_streak", 0)) * 0.008)
    state["pressure"] = round(min(1.8, max(0.75, pressure)), 4)


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    if await handle_add(event, arg, ctx):
        return
    amount = parse_amount(arg)
    if amount is None:
        await ctx["reply"](event, "用法：/zhubi_fakuang <猪币数量>")
        return
    data = zhubi.load_data()
    user_id = str(event.get("user_id", 0))
    user = zhubi.user_data(data, user_id)
    is_bot_admin = user_id in {str(value) for value in ctx.get("admin_users", set())}
    used = int(user.get("daily_fakuang_used", 0))
    limit = 1 + int(user.get("daily_fakuang_extra", 0))
    if not is_bot_admin and used >= limit:
        await ctx["reply"](event, f"你今天已经发狂过了，今日已用：{used} 次，今日上限：{limit} 次。")
        return
    if common.total_holding(user) < amount:
        await ctx["reply"](event, f"猪币不足。你当前持有：{common.format_amount(common.total_holding(user))}。")
        return
    returned = mining_return(amount, data)
    returned, pool_added, pool_bonus = apply_pool(amount, returned, data)
    update_mine_state(data, amount, returned)
    spent = common.spend_amount(user, float(amount))
    if spent is None:
        await ctx["reply"](event, f"猪币不足。你当前持有：{common.format_amount(common.total_holding(user))}。")
        return
    main_spent, idle_spent = spent
    user["balance"] = common.truncate_decimal(common.balance_of(user) + float(returned))
    user["total_mined_spent"] = int(user.get("total_mined_spent", 0)) + amount
    user["total_mined_returned"] = int(user.get("total_mined_returned", 0)) + returned
    user["mine_count"] = int(user.get("mine_count", 0)) + 1
    if not is_bot_admin:
        user["daily_fakuang_used"] = used + 1
    data["global"]["total_mined_spent"] = int(data["global"].get("total_mined_spent", 0)) + amount
    data["global"]["total_mined_returned"] = int(data["global"].get("total_mined_returned", 0)) + returned
    data["global"]["mine_count"] = int(data["global"].get("mine_count", 0)) + 1
    zhubi.save_data(data)
    diff = returned - amount
    sign = "+" if diff >= 0 else "-"
    pool_text = f"，猪池补贴：+{common.format_amount(pool_bonus)}" if pool_bonus > 0 else f"，进入猪池：{common.format_amount(pool_added)}" if pool_added > 0 else ""
    idle_text = f"，从 idle 抵扣了 {common.format_amount(idle_spent)}" if idle_spent > 0 else ""
    await ctx["reply"](event, f"你投入了 {common.format_amount(amount)} 发狂，得到了 {common.format_amount(returned)}，本次收益：{sign}{common.format_amount(abs(diff))}{pool_text}{idle_text}。当前持有：{common.format_amount(user['balance'])}。")


COMMAND = {
    "name": "/zhubi_fakuang",
    "usage": "/zhubi_fakuang <猪币数量或nMAX+数字> 仅所有者： /zhubi_fakuang add <QQ号> <今日额外次数>",
    "description": "每天一次，投入指定数量猪币发狂，数量支持 40MAX+12000000；add 仅所有者可用。",
    "handler": handler,
}
