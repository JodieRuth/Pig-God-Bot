from __future__ import annotations

import importlib.util
import math
import random
from pathlib import Path
from typing import Any

COMMON_MODULE = Path(__file__).with_name("zhubi_ext_common.py")
spec = importlib.util.spec_from_file_location("local_onebot_zhubi_ext_common_zhuazhu", COMMON_MODULE)
if spec is None or spec.loader is None:
    raise RuntimeError("无法加载猪币扩展模块")
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)
zhubi = common.zhubi

DAILY_ZHUA_LIMIT = 3
IDLE_MIN_THRESHOLD = 1000.0


def extract_at_target(message: list[dict[str, Any]]) -> int | None:
    for seg in message:
        if seg.get("type") == "at":
            qq = str(seg.get("data", {}).get("qq") or "")
            if qq.isdigit():
                return int(qq)
    return None


def zhuazhu_available(user: dict[str, Any]) -> int:
    return DAILY_ZHUA_LIMIT + int(user.get("daily_zhuazhu_extra", 0)) - int(user.get("daily_zhuazhu_used", 0))


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


async def handle_add(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> bool:
    if not arg.strip().lower().startswith("add"):
        return False
    if not ctx["is_admin_event"](event):
        await ctx["reply"](event, "你没有权限使用抓抓次数管理指令。")
        return True
    parsed = parse_add_args(arg)
    if parsed is None:
        await ctx["reply"](event, "用法：/zhuazhu add <QQ号> <今日额外次数>")
        return True
    target_id, amount = parsed
    data = zhubi.load_data()
    target = zhubi.user_data(data, target_id)
    target["daily_zhuazhu_extra"] = int(target.get("daily_zhuazhu_extra", 0)) + amount
    zhubi.save_data(data)
    await ctx["reply"](event, f"已为 QQ {target_id} 增加今日抓抓次数 {amount} 次，今日剩余：{max(0, zhuazhu_available(target))} 次。")
    return True


def idle_transfer_out(idle: dict[str, Any], amount: float) -> None:
    max_part = float(idle.get("max", 0.0))
    coin_part = float(idle.get("coins", 0.0))
    remaining = amount
    if coin_part >= remaining:
        idle["coins"] = common.truncate_decimal(coin_part - remaining)
    else:
        remaining -= coin_part
        used_max = int(math.ceil(remaining / common.MAX_UNIT))
        idle["max"] = max(0.0, max_part - used_max)
        idle["coins"] = common.truncate_decimal(used_max * common.MAX_UNIT - remaining)


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    if await handle_add(event, arg, ctx):
        return
    if event.get("message_type") != "group":
        await ctx["reply"](event, "/zhuazhu 只能在群聊中使用。")
        return
    thief_id = str(event.get("user_id", 0))
    is_admin = ctx["is_admin_event"](event)
    message = event.get("message", [])
    at_target = extract_at_target(message)
    if at_target is not None:
        target_id = str(at_target)
    else:
        parts = arg.split()
        if len(parts) != 1 or not parts[0].isdigit():
            await ctx["reply"](event, "用法：/zhuazhu <QQ号或@某人>；仅所有者：/zhuazhu add <QQ号> <今日额外次数>")
            return
        target_id = parts[0]
    if target_id == thief_id:
        await ctx["reply"](event, "不能抓自己。")
        return
    data = zhubi.load_data()
    common.apply_idle_income(data)
    thief = zhubi.user_data(data, thief_id)
    target = zhubi.user_data(data, target_id)
    if not is_admin and zhuazhu_available(thief) <= 0:
        zhubi.save_data(data)
        await ctx["reply"](event, "你今天的抓抓次数已经用完。")
        return
    if not is_admin:
        thief["daily_zhuazhu_used"] = int(thief.get("daily_zhuazhu_used", 0)) + 1

    thief_idle = common.idle_state(thief)
    target_idle = common.idle_state(target)
    target_idle_total = common.idle_total_coins(target_idle)

    use_main = target_idle_total < IDLE_MIN_THRESHOLD

    if use_main:
        target_balance = common.balance_of(target)
        if target_balance <= 0:
            zhubi.save_data(data)
            await ctx["reply"](event, "对方主钱包猪币不足，无法抓取。")
            return
        ratio = random.uniform(0.01, 0.20)
        steal_amount = common.truncate_decimal(target_balance * ratio)
        if steal_amount <= 0:
            zhubi.save_data(data)
            await ctx["reply"](event, "对方主钱包猪币太少，无法抓取。")
            return
        reversed_result = random.random() < 0.5
        source_name = "主钱包"
    else:
        ratio = random.uniform(0.01, 0.20)
        steal_amount = common.truncate_decimal(target_idle_total * ratio)
        if steal_amount <= 0:
            zhubi.save_data(data)
            await ctx["reply"](event, "对方 idle 猪币太少，无法抓取。")
            return
        reversed_result = random.random() < 0.5
        source_name = "idle 钱包"

    if reversed_result:
        if use_main:
            if common.total_holding(thief) <= 0:
                zhubi.save_data(data)
                await ctx["reply"](event, f"偷鸡不成蚀把米！但你的{source_name}不足，无事发生。")
                return
            ratio = random.uniform(0.01, 0.20)
            steal_amount = common.truncate_decimal(common.total_holding(thief) * ratio)
            common.spend_amount(thief, float(steal_amount))
            common.change_balance(target, steal_amount)
            zhubi.save_data(data)
            remaining = "不限" if is_admin else str(max(0, zhuazhu_available(thief)))
            await ctx["reply"](event, f"偷鸡不成蚀把米！{common.format_amount(steal_amount)} 从你的{source_name}被反抓到了对方{source_name}。今日剩余抓抓次数：{remaining}。")
            return
        else:
            thief_idle_total = common.idle_total_coins(thief_idle)
            if thief_idle_total <= 0:
                zhubi.save_data(data)
                await ctx["reply"](event, f"偷鸡不成蚀把米！但你的{source_name}不足，无事发生。")
                return
            ratio = random.uniform(0.01, 0.20)
            steal_amount = common.truncate_decimal(thief_idle_total * ratio)
            idle_transfer_out(thief_idle, float(steal_amount))
            target_idle["coins"] = common.truncate_decimal(float(target_idle.get("coins", 0.0)) + float(steal_amount))
            common.normalize_idle_units(thief_idle)
            common.normalize_idle_units(target_idle)
            zhubi.save_data(data)
            remaining = "不限" if is_admin else str(max(0, zhuazhu_available(thief)))
            await ctx["reply"](event, f"偷鸡不成蚀把米！{common.format_amount(steal_amount)} 从你的{source_name}被反抓到了对方{source_name}。今日剩余抓抓次数：{remaining}。")
            return

    if use_main:
        common.spend_amount(target, float(steal_amount))
        common.change_balance(thief, steal_amount)
        zhubi.save_data(data)
        remaining = "不限" if is_admin else str(max(0, zhuazhu_available(thief)))
        await ctx["reply"](event, f"抓取成功！{common.format_amount(steal_amount)} 猪币已从对方{source_name}转入你的{source_name}。今日剩余抓抓次数：{remaining}。")
        return

    idle_transfer_out(target_idle, float(steal_amount))
    thief_idle["coins"] = common.truncate_decimal(float(thief_idle.get("coins", 0.0)) + float(steal_amount))
    common.normalize_idle_units(target_idle)
    common.normalize_idle_units(thief_idle)
    zhubi.save_data(data)
    remaining = "不限" if is_admin else str(max(0, zhuazhu_available(thief)))
    await ctx["reply"](event, f"抓取成功！{common.format_amount(steal_amount)} 猪币已从对方{source_name}转入你的{source_name}。今日剩余抓抓次数：{remaining}。")


COMMAND = {
    "name": "/zhuazhu",
    "usage": "/zhuazhu <QQ号或@某人>；仅所有者：/zhuazhu add <QQ号> <今日额外次数>",
    "description": "偷取某个人的猪币，每日3次。",
    "handler": handler,
}
