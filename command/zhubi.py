from __future__ import annotations

import json
import math
import random
from datetime import date
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).with_name("zhubi")
DATA_FILE = DATA_DIR / "data.json"
DAILY_LIMIT = 1
MAX_UNIT = 2147483647
DECIMAL_PRECISION = 5
DECIMAL_FACTOR = 10 ** DECIMAL_PRECISION


def today_key() -> str:
    return date.today().isoformat()


def truncate_decimal(value: float) -> float:
    return math.floor(max(0.0, float(value)) * DECIMAL_FACTOR) / DECIMAL_FACTOR


def balance_of_value(value: float) -> float:
    return truncate_decimal(float(value))


def format_balance(value: int | float) -> str:
    amount = max(0.0, float(value))
    max_count = int(amount // MAX_UNIT)
    remainder = truncate_decimal(amount - max_count * MAX_UNIT)
    remainder_text = f"{remainder:.{DECIMAL_PRECISION}f}".rstrip("0").rstrip(".")
    if not remainder_text:
        remainder_text = "0"
    if max_count <= 0:
        return remainder_text
    return f"{max_count}MAX+{remainder_text}"


def parse_amount_value(value: str) -> float | None:
    text = value.strip().upper()
    if not text:
        return None
    if "MAX" in text:
        left, sep, right = text.partition("MAX")
        if not sep or not left:
            return None
        if right.startswith("+"):
            right = right[1:]
        elif right:
            return None
        try:
            max_count = float(left)
            coins = float(right) if right else 0.0
        except ValueError:
            return None
        if max_count < 0 or coins < 0:
            return None
        return truncate_decimal(max_count * MAX_UNIT + coins)
    try:
        amount = float(text)
    except ValueError:
        return None
    if amount < 0:
        return None
    return truncate_decimal(amount)


def default_mine_state() -> dict[str, Any]:
    return {
        "pressure": 1.0,
        "pool": 0,
        "recent_spent": 0,
        "recent_returned": 0,
        "recent_rate": 1.0,
        "loss_streak": 0,
        "win_streak": 0,
    }


def normalize_mine_state(data: dict[str, Any]) -> dict[str, Any]:
    state = data.setdefault("mine_state", default_mine_state())
    defaults = default_mine_state()
    for key, value in defaults.items():
        state.setdefault(key, value)
    state["pressure"] = min(1.8, max(0.75, float(state.get("pressure", 1.0))))
    state["pool"] = max(0, int(state.get("pool", 0)))
    state["recent_spent"] = max(0, int(state.get("recent_spent", 0)))
    state["recent_returned"] = max(0, int(state.get("recent_returned", 0)))
    state["recent_rate"] = float(state.get("recent_rate", 1.0))
    state["loss_streak"] = max(0, int(state.get("loss_streak", 0)))
    state["win_streak"] = max(0, int(state.get("win_streak", 0)))
    return state


def normalize_user_data(user: dict[str, Any]) -> dict[str, Any]:
    user["balance"] = balance_of_value(float(user.get("balance", 0.0)))
    user.setdefault("daily_claims", 0)
    user.setdefault("daily_claimed", 0)
    user.setdefault("daily_fakuang_used", 0)
    user.setdefault("daily_fakuang_extra", 0)
    user.setdefault("daily_pvp_used", 0)
    user.setdefault("daily_pvp_extra", 0)
    user.setdefault("total_claimed", 0)
    user.setdefault("total_mined_spent", 0)
    user.setdefault("total_mined_returned", 0)
    user.setdefault("mine_count", 0)
    idle = user.get("idle")
    if isinstance(idle, dict):
        idle["coins"] = truncate_decimal(float(idle.get("coins", 0.0)))
        idle["max"] = float(idle.get("max", 0.0))
        idle["last_tick"] = float(idle.get("last_tick", 0.0) or 0.0)
    return user


def default_data() -> dict[str, Any]:
    return {
        "date": today_key(),
        "users": {},
        "global": {
            "total_claimed": 0,
            "total_mined_spent": 0,
            "total_mined_returned": 0,
            "mine_count": 0,
        },
        "mine_state": default_mine_state(),
    }


def load_data() -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not DATA_FILE.exists():
        data = default_data()
        save_data(data)
        return data
    try:
        with DATA_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        data = default_data()
    if not isinstance(data, dict):
        data = default_data()
    data.setdefault("users", {})
    data.setdefault("global", {})
    data["global"].setdefault("total_claimed", 0)
    data["global"].setdefault("total_mined_spent", 0)
    data["global"].setdefault("total_mined_returned", 0)
    data["global"].setdefault("mine_count", 0)
    for user in data["users"].values():
        if isinstance(user, dict):
            normalize_user_data(user)
    normalize_mine_state(data)
    if data.get("date") != today_key():
        data["date"] = today_key()
        for user in data["users"].values():
            if isinstance(user, dict):
                user["daily_claims"] = 0
                user["daily_claimed"] = 0
                user["daily_fakuang_used"] = 0
                user["daily_fakuang_extra"] = 0
                user["daily_pvp_used"] = 0
                user["daily_pvp_extra"] = 0
    return data


def save_data(data: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = DATA_FILE.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(DATA_FILE)


def user_data(data: dict[str, Any], user_id: str) -> dict[str, Any]:
    users = data.setdefault("users", {})
    user = users.setdefault(user_id, {})
    return normalize_user_data(user)


def parse_add_args(arg: str) -> tuple[str, float] | None:
    parts = arg.split()
    if len(parts) != 3 or parts[0].lower() != "add":
        return None
    user_id = parts[1].strip()
    if not user_id.isdigit():
        return None
    amount = parse_amount_value(parts[2])
    if amount is None or amount == 0:
        return None
    return user_id, amount


async def handle_add(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> bool:
    if not arg.strip().lower().startswith("add"):
        return False
    if not ctx["is_admin_event"](event):
        await ctx["reply"](event, "你没有权限使用猪币管理指令。")
        return True
    parsed = parse_add_args(arg)
    if parsed is None:
        await ctx["reply"](event, "用法：/zhubi add <QQ号> <猪币数量或nMAX+数字>")
        return True
    target_id, amount = parsed
    data = load_data()
    target = user_data(data, target_id)
    target["balance"] = balance_of_value(float(target.get("balance", 0.0)) + float(amount))
    save_data(data)
    await ctx["reply"](event, f"已为 QQ {target_id} 增加 {format_balance(amount)}，当前余额：{format_balance(target['balance'])}。")
    return True


def idle_summary(user: dict[str, Any]) -> str:
    state = user.setdefault("idle", {})
    if not isinstance(state, dict):
        state = {}
        user["idle"] = state
    coins = truncate_decimal(float(state.get("coins", 0.0)))
    max_count = float(state.get("max", 0.0))
    total = max_count * MAX_UNIT + coins
    quality = max(0, int(state.get("quality", 0)))
    efficiency = max(0, int(state.get("efficiency", 0)))
    speed = max(0, int(state.get("speed", 0)))
    remakes = max(0, int(state.get("remakes", 0)))
    quality_multiplier = 1.1 ** quality
    speed_multiplier = 1.025 ** speed
    remake_multiplier = 1 + 0.15 * remakes
    unit_rate = 0.0001 + efficiency * 0.0001
    total_multiplier = quality_multiplier * speed_multiplier * remake_multiplier
    return "\n".join([
        f"当前持有：{format_balance(user['balance'])}",
        f"idle 运作中：{format_balance(total)}",
        f"idle 整数增长基数：{format_balance(int(max_count) * MAX_UNIT + int(coins))}",
        f"quality 等级：{quality}，倍率：{quality_multiplier:.4f}x",
        f"efficiency 等级：{efficiency}，每单位基础获取率：{unit_rate:.6f}/秒",
        f"speed 等级：{speed}，倍率：{speed_multiplier:.4f}x",
        f"转生次数：{remakes}，转生倍率：{remake_multiplier:.2f}x",
        f"总效率倍率：{total_multiplier:.4f}x",
        f"当前状态：{'已通关' if bool(state.get('cleared', False)) else '运行中'}",
    ])


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    if await handle_add(event, arg, ctx):
        return
    data = load_data()
    user_id = str(event.get("user_id", 0))
    user = user_data(data, user_id)
    if arg.strip().lower() == "show":
        save_data(data)
        await ctx["reply"](event, idle_summary(user))
        return
    is_admin = ctx["is_admin_event"](event)
    if not is_admin and float(user.get("daily_claims", 0)) >= DAILY_LIMIT:
        await ctx["reply"](event, f"你今天已经领过 {DAILY_LIMIT} 次猪币了，当前余额：{format_balance(user['balance'])}。")
        return
    amount = random.randint(1, 3000)
    user["balance"] = balance_of_value(float(user.get("balance", 0.0)) + float(amount))
    user["daily_claims"] = int(user.get("daily_claims", 0)) + 1
    user["daily_claimed"] = int(user.get("daily_claimed", 0)) + amount
    user["total_claimed"] = int(user.get("total_claimed", 0)) + amount
    data["global"]["total_claimed"] = int(data["global"].get("total_claimed", 0)) + amount
    save_data(data)
    if is_admin:
        await ctx["reply"](event, f"你获得了 {format_balance(amount)}。当前持有：{format_balance(user['balance'])}。")
        return
    remaining = DAILY_LIMIT - int(user.get("daily_claims", 0))
    await ctx["reply"](event, f"你获得了 {format_balance(amount)}，当前持有：{format_balance(user['balance'])}。今日剩余领取次数：{remaining}。")


COMMAND = {
    "name": "/zhubi",
    "usage": "/zhubi [show | add <QQ号> <猪币数量或nMAX+数字>]",
    "description": "领取猪币；show 查看钱包和 idle 参数；add 仅所有者可用，数量支持 40MAX+12000000。",
    "handler": handler,
}
