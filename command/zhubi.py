from __future__ import annotations

import json
import random
from datetime import date
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).with_name("zhubi")
DATA_FILE = DATA_DIR / "data.json"
DAILY_LIMIT = 1


def today_key() -> str:
    return date.today().isoformat()


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
        return default_data()
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
    normalize_mine_state(data)
    if data.get("date") != today_key():
        data["date"] = today_key()
        for user in data["users"].values():
            if isinstance(user, dict):
                user["daily_claims"] = 0
                user["daily_claimed"] = 0
                user["daily_fakuang_used"] = 0
                user["daily_fakuang_extra"] = 0
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
    user.setdefault("balance", 0)
    user.setdefault("daily_claims", 0)
    user.setdefault("daily_claimed", 0)
    user.setdefault("daily_fakuang_used", 0)
    user.setdefault("daily_fakuang_extra", 0)
    user.setdefault("total_claimed", 0)
    user.setdefault("total_mined_spent", 0)
    user.setdefault("total_mined_returned", 0)
    user.setdefault("mine_count", 0)
    return user


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
    if amount == 0:
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
        await ctx["reply"](event, "用法：/zhubi add <QQ号> <猪币数量>")
        return True
    target_id, amount = parsed
    data = load_data()
    target = user_data(data, target_id)
    target["balance"] = int(target.get("balance", 0)) + amount
    save_data(data)
    await ctx["reply"](event, f"已为 QQ {target_id} 增加 {amount} 猪币，当前余额：{int(target['balance'])} 猪币。")
    return True


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    if await handle_add(event, arg, ctx):
        return
    data = load_data()
    user_id = str(event.get("user_id", 0))
    user = user_data(data, user_id)
    is_admin = ctx["is_admin_event"](event)
    if not is_admin and int(user.get("daily_claims", 0)) >= DAILY_LIMIT:
        await ctx["reply"](event, f"你今天已经领过 {DAILY_LIMIT} 次猪币了，当前余额：{int(user['balance'])} 猪币。")
        return
    amount = random.randint(1, 3000)
    user["balance"] = int(user.get("balance", 0)) + amount
    user["daily_claims"] = int(user.get("daily_claims", 0)) + 1
    user["daily_claimed"] = int(user.get("daily_claimed", 0)) + amount
    user["total_claimed"] = int(user.get("total_claimed", 0)) + amount
    data["global"]["total_claimed"] = int(data["global"].get("total_claimed", 0)) + amount
    save_data(data)
    if is_admin:
        await ctx["reply"](event, f"你获得了 {amount} 猪币。当前持有：{int(user['balance'])} 猪币。")
        return
    remaining = DAILY_LIMIT - int(user.get("daily_claims", 0))
    await ctx["reply"](event, f"你获得了 {amount} 猪币，当前持有：{int(user['balance'])} 猪币。今日剩余领取次数：{remaining}。")


COMMAND = {
    "name": "/zhubi",
    "usage": "/zhubi [add <QQ号> <猪币数量>]",
    "description": "领取猪币，每个 QQ 每天 1 次；add 仅所有者可用。",
    "handler": handler,
}
