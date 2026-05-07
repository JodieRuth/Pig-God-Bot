from __future__ import annotations

import importlib.util
import math
from pathlib import Path
from typing import Any

COMMON_MODULE = Path(__file__).with_name("zhubi_ext_common.py")
spec = importlib.util.spec_from_file_location("local_onebot_zhubi_ext_common_idle", COMMON_MODULE)
if spec is None or spec.loader is None:
    raise RuntimeError("无法加载猪币扩展模块")
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)
zhubi = common.zhubi


def idle_summary(state: dict[str, Any], balance: float) -> str:
    total = common.idle_total_coins(state)
    int_base = int(float(state.get("max", 0.0))) * common.MAX_UNIT + int(float(state.get("coins", 0.0)))
    growth_per_sec = int_base * common.idle_unit_rate(state) * common.idle_multiplier(state)
    lines = [
        f"钱包猪币：{common.format_amount(balance)}",
        f"idle 猪币：{common.format_amount(total)}",
        f"MAX 储量：{int(float(state.get('max', 0.0)))}MAX",
        f"当前效率倍率：{common.idle_multiplier(state):.4f}x",
        f"每单位基础获取率：{common.idle_unit_rate(state):.6f}/秒",
        f"idle 每秒增长速度：{common.format_amount(growth_per_sec)}",
        f"转生倍率：{1 + 0.15 * int(state.get('remakes', 0)):.2f}x",
        f"quality 等级：{common.level_label(int(state.get('quality', 0)))}，下级价格：{common.format_amount(common.upgrade_cost('quality', int(state.get('quality', 0))))}",
        f"efficiency 等级：{common.level_label(int(state.get('efficiency', 0)))}，下级价格：{common.format_amount(common.upgrade_cost('efficiency', int(state.get('efficiency', 0))))}",
        f"speed 等级：{common.level_label(int(state.get('speed', 0)))}，下级价格：{common.format_amount(common.upgrade_cost('speed', int(state.get('speed', 0))))}",
        f"转生次数：{int(state.get('remakes', 0))}",
    ]
    if state.get("cleared"):
        lines.append("当前状态：已通关，可使用 /zhubi_idle remake 转生。")
    return "\n".join(lines)


async def notify_milestones(event: dict[str, Any], ctx: dict[str, Any], notifications: list[tuple[str, int, str, float]]) -> None:
    if event.get("message_type") != "group":
        return
    group_id = int(event.get("group_id", 0))
    for user_id, notify_group_id, label, total in notifications:
        if notify_group_id != group_id:
            continue
        await ctx["reply"](event, f"[CQ:at,qq={user_id}] 您已持有{common.format_amount(total)}，恭喜达到{label}")


def parse_amount(parts: list[str]) -> float | None:
    if len(parts) != 2:
        return None
    return common.parse_positive_amount(parts[1])


async def handle_move(event: dict[str, Any], parts: list[str], ctx: dict[str, Any]) -> None:
    direction = parts[0].lower()
    amount = parse_amount(parts)
    if amount is None:
        await ctx["reply"](event, "用法：/zhubi_idle in <数量> 或 /zhubi_idle out <数量>")
        return
    data = zhubi.load_data()
    notifications = common.apply_idle_income(data)
    user_id = str(event.get("user_id", 0))
    user = zhubi.user_data(data, user_id)
    state = common.idle_state(user)
    if event.get("message_type") == "group":
        state["group_id"] = int(event.get("group_id", 0))
    if direction == "in":
        balance = common.balance_of(user)
        if balance < amount:
            zhubi.save_data(data)
            await ctx["reply"](event, f"猪币不足。你当前持有：{common.format_amount(balance)}。")
            return
        common.change_balance(user, -amount)
        state["coins"] = common.truncate_decimal(float(state.get("coins", 0.0)) + float(amount))
        common.normalize_idle_units(state)
        zhubi.save_data(data)
        await notify_milestones(event, ctx, notifications)
        await ctx["reply"](event, f"已投入 {common.format_amount(amount)} 到 idle。\n{idle_summary(state, common.balance_of(user))}")
        return
    if direction == "out":
        total = common.idle_total_coins(state)
        if total < amount:
            zhubi.save_data(data)
            await ctx["reply"](event, f"idle 猪币不足。当前 idle 中有：{common.format_amount(total)}。")
            return
        max_part = float(state.get("max", 0.0))
        coin_part = float(state.get("coins", 0.0))
        remaining = float(amount)
        if coin_part >= remaining:
            state["coins"] = coin_part - remaining
        else:
            remaining -= coin_part
            used_max = math.ceil(remaining / common.MAX_UNIT)
            state["max"] = max(0.0, max_part - used_max)
            state["coins"] = common.truncate_decimal(used_max * common.MAX_UNIT - remaining)
        common.change_balance(user, amount)
        common.normalize_idle_units(state)
        zhubi.save_data(data)
        await notify_milestones(event, ctx, notifications)
        await ctx["reply"](event, f"已从 idle 取出 {common.format_amount(amount)}。\n{idle_summary(state, common.balance_of(user))}")
        return
    await ctx["reply"](event, "用法：/zhubi_idle in/out <数量>")


async def handle_buy(event: dict[str, Any], parts: list[str], ctx: dict[str, Any]) -> None:
    if len(parts) != 3 or parts[1].lower() != "update" or parts[2].lower() not in common.UPGRADE_BASE_COSTS:
        await ctx["reply"](event, "用法：/zhubi_idle buy update quality|efficiency|speed")
        return
    kind = parts[2].lower()
    data = zhubi.load_data()
    notifications = common.apply_idle_income(data)
    user_id = str(event.get("user_id", 0))
    user = zhubi.user_data(data, user_id)
    state = common.idle_state(user)
    level = int(state.get(kind, 0))
    cost = common.upgrade_cost(kind, level)
    balance = common.balance_of(user)
    if balance < cost:
        zhubi.save_data(data)
        await ctx["reply"](event, f"猪币不足。升级 {kind} 需要 {common.format_amount(cost)}，你当前持有 {common.format_amount(balance)}。")
        return
    common.change_balance(user, -cost)
    state[kind] = level + 1
    if event.get("message_type") == "group":
        state["group_id"] = int(event.get("group_id", 0))
    zhubi.save_data(data)
    await notify_milestones(event, ctx, notifications)
    await ctx["reply"](event, f"已购买 {kind} 升级，消耗 {common.format_amount(cost)}。当前等级：{common.level_label(int(state[kind]))}。")


async def handle_remake(event: dict[str, Any], ctx: dict[str, Any]) -> None:
    data = zhubi.load_data()
    common.apply_idle_income(data)
    user_id = str(event.get("user_id", 0))
    user = zhubi.user_data(data, user_id)
    state = common.idle_state(user)
    if not state.get("cleared"):
        zhubi.save_data(data)
        await ctx["reply"](event, "你还没有通关 idle，不能转生。")
        return
    remakes = int(state.get("remakes", 0)) + 1
    user["balance"] = 0.0
    user["idle"] = {
        "coins": 0.0,
        "max": 0.0,
        "last_tick": common.SESSION_STARTED,
        "quality": 0,
        "efficiency": 0,
        "speed": 0,
        "remakes": remakes,
        "cleared": False,
        "last_milestone": -1,
        "group_id": int(event.get("group_id", 0)) if event.get("message_type") == "group" else 0,
    }
    zhubi.save_data(data)
    await ctx["reply"](event, f"转生完成。已清空所有钱包与 idle 猪币，当前转生次数：{remakes}，基础数值倍率：{1 + 0.15 * remakes:.2f}x。")


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    parts = arg.split()
    if not parts:
        data = zhubi.load_data()
        notifications = common.apply_idle_income(data)
        user = zhubi.user_data(data, str(event.get("user_id", 0)))
        state = common.idle_state(user)
        if event.get("message_type") == "group":
            state["group_id"] = int(event.get("group_id", 0))
        zhubi.save_data(data)
        await notify_milestones(event, ctx, notifications)
        await ctx["reply"](event, idle_summary(state, common.balance_of(user)))
        return
    action = parts[0].lower()
    if action in {"in", "out"}:
        await handle_move(event, parts, ctx)
        return
    if action == "buy":
        await handle_buy(event, parts, ctx)
        return
    if action == "remake" and len(parts) == 1:
        await handle_remake(event, ctx)
        return
    await ctx["reply"](event, "用法：/zhubi_idle [in/out 数量 | buy update quality|efficiency|speed | remake]")


COMMAND = {
    "name": "/zhubi_idle",
    "usage": "/zhubi_idle [in/out <数量或nMAX+数字> | buy update quality|efficiency|speed | remake]",
    "description": "猪币放置游戏：投入猪币每秒增长0.0001/单位，可买quality(×1.1)/efficiency(+0.0001)/speed(×1.025)升级，2147483647MAX通关后转生(×1.15)。",
    "handler": handler,
}
