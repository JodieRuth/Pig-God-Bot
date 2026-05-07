from __future__ import annotations

import importlib.util
import math
import time
from pathlib import Path
from typing import Any

ZHUBI_MODULE = Path(__file__).with_name("zhubi.py")
spec = importlib.util.spec_from_file_location("local_onebot_zhubi_shared_ext", ZHUBI_MODULE)
if spec is None or spec.loader is None:
    raise RuntimeError("无法加载猪币数据模块")
zhubi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(zhubi)

MAX_UNIT = 2147483647
IDLE_BASE_RATE = 0.0001
DECIMAL_PRECISION = 5
DECIMAL_FACTOR = 10 ** DECIMAL_PRECISION
LEVEL_NAMES = ["ULV", "LV", "MV", "HV", "EV", "IV", "LuV", "ZPM", "UV", "UHV", "UEV", "UIV", "UMV", "UXV", "MAX"]
UPGRADE_BASE_COSTS = {
    "quality": 100000.0,
    "efficiency": 1000000.0,
    "speed": float(MAX_UNIT),
}
UPGRADE_COST_GROWTH = {
    "quality": 1.35,
    "efficiency": 1.45,
    "speed": 1.6,
}
MILESTONES = [
    (25565.0, "ULV"),
    (262144.0, "LV"),
    (2097152.0, "MV"),
    (16777216.0, "MV"),
    (134217728.0, "HV"),
    (1073741824.0, "EV"),
    (2.0 * MAX_UNIT, "IV"),
    (16.0 * MAX_UNIT, "LuV"),
    (128.0 * MAX_UNIT, "ZPM"),
    (1024.0 * MAX_UNIT, "UV"),
    (8192.0 * MAX_UNIT, "UHV"),
    (65536.0 * MAX_UNIT, "UEV"),
    (524288.0 * MAX_UNIT, "UIV"),
    (4194304.0 * MAX_UNIT, "UMV"),
    (33554432.0 * MAX_UNIT, "UXV"),
    (2147483647.0 * MAX_UNIT, "MAX"),
]
SESSION_STARTED = time.time()


def truncate_decimal(value: float) -> float:
    return math.floor(max(0.0, float(value)) * DECIMAL_FACTOR) / DECIMAL_FACTOR


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


def parse_positive_amount(value: str) -> float | None:
    amount = parse_amount_value(value)
    if amount is None or amount <= 0:
        return None
    return amount


def parse_positive_int(value: str) -> int | None:
    amount = parse_positive_amount(value)
    if amount is None:
        return None
    whole = int(amount)
    return whole if whole > 0 else None


def balance_of(user: dict[str, Any]) -> float:
    return truncate_decimal(float(user.get("balance", 0.0)))


def change_balance(user: dict[str, Any], delta: int | float) -> None:
    user["balance"] = truncate_decimal(max(0.0, float(user.get("balance", 0.0)) + float(delta)))


def idle_state(user: dict[str, Any]) -> dict[str, Any]:
    state = user.setdefault("idle", {})
    if not isinstance(state, dict):
        state = {}
        user["idle"] = state
    state.setdefault("coins", 0.0)
    state.setdefault("max", 0.0)
    state.setdefault("last_tick", SESSION_STARTED)
    state.setdefault("quality", 0)
    state.setdefault("efficiency", 0)
    state.setdefault("speed", 0)
    state.setdefault("remakes", 0)
    state.setdefault("cleared", False)
    state.setdefault("last_milestone", -1)
    state.setdefault("group_id", 0)
    state["coins"] = truncate_decimal(float(state.get("coins", 0.0)))
    state["max"] = float(state.get("max", 0.0))
    state["last_tick"] = float(state.get("last_tick", SESSION_STARTED))
    state["quality"] = max(0, int(state.get("quality", 0)))
    state["efficiency"] = max(0, int(state.get("efficiency", 0)))
    state["speed"] = max(0, int(state.get("speed", 0)))
    state["remakes"] = max(0, int(state.get("remakes", 0)))
    state["cleared"] = bool(state.get("cleared", False))
    state["last_milestone"] = int(state.get("last_milestone", -1))
    state["group_id"] = int(state.get("group_id", 0) or 0)
    normalize_idle_units(state)
    return state


def idle_total_coins(state: dict[str, Any]) -> float:
    return float(state.get("max", 0.0)) * MAX_UNIT + float(state.get("coins", 0.0))


def whole_idle_total_coins(state: dict[str, Any]) -> int:
    return int(float(state.get("max", 0.0))) * MAX_UNIT + int(float(state.get("coins", 0.0)))


def normalize_idle_units(state: dict[str, Any]) -> None:
    coins = truncate_decimal(float(state.get("coins", 0.0)))
    max_count = float(state.get("max", 0.0))
    if coins >= MAX_UNIT:
        gained = math.floor(coins / MAX_UNIT)
        max_count += gained
        coins -= gained * MAX_UNIT
    state["coins"] = truncate_decimal(coins)
    state["max"] = max_count


def format_amount(value: int | float) -> str:
    amount = max(0.0, float(value))
    max_count = int(amount // MAX_UNIT)
    remainder = truncate_decimal(amount - max_count * MAX_UNIT)
    remainder_text = f"{remainder:.{DECIMAL_PRECISION}f}".rstrip("0").rstrip(".")
    if not remainder_text:
        remainder_text = "0"
    if max_count <= 0:
        return remainder_text
    return f"{max_count}MAX+{remainder_text}"


def remake_multiplier(state: dict[str, Any]) -> float:
    return 1.0 + 0.15 * int(state.get("remakes", 0))


def idle_multiplier(state: dict[str, Any]) -> float:
    quality = 1.1 ** int(state.get("quality", 0))
    speed = 1.025 ** int(state.get("speed", 0))
    return quality * speed * remake_multiplier(state)


def idle_unit_rate(state: dict[str, Any]) -> float:
    return IDLE_BASE_RATE + int(state.get("efficiency", 0)) * 0.0001


def upgrade_cost(kind: str, level: int) -> int:
    return int(round(UPGRADE_BASE_COSTS[kind] * (UPGRADE_COST_GROWTH[kind] ** level)))


def level_label(level: int) -> str:
    cycle, index = divmod(max(0, level), len(LEVEL_NAMES))
    prefix = f"{cycle}MAX-" if cycle > 0 else ""
    return prefix + LEVEL_NAMES[index]


def milestone_index(total: float) -> int:
    result = -1
    for index, (threshold, _) in enumerate(MILESTONES):
        if total >= threshold:
            result = index
        else:
            break
    return result


def apply_idle_income_to_user(user: dict[str, Any], now: float | None = None) -> tuple[bool, int, str, float]:
    state = idle_state(user)
    current = time.time() if now is None else now
    last_tick = float(state.get("last_tick", current))
    elapsed = max(0, int(current - last_tick))
    state["last_tick"] = last_tick + elapsed
    if elapsed <= 0 or state.get("cleared"):
        return False, -1, "", 0.0
    total_before = whole_idle_total_coins(state)
    if total_before <= 0:
        return False, -1, "", 0.0
    gain = total_before * idle_unit_rate(state) * idle_multiplier(state) * elapsed
    state["coins"] = truncate_decimal(float(state.get("coins", 0.0)) + gain)
    normalize_idle_units(state)
    total_after = idle_total_coins(state)
    reached = milestone_index(total_after)
    previous = int(state.get("last_milestone", -1))
    if reached > previous:
        state["last_milestone"] = reached
        label = MILESTONES[reached][1]
        if reached == len(MILESTONES) - 1:
            state["cleared"] = True
        return True, reached, label, total_after
    return True, -1, "", total_after


def flush_idle_data() -> None:
    data = zhubi.load_data()
    apply_idle_income(data)
    zhubi.save_data(data)


def apply_idle_income(data: dict[str, Any], now: float | None = None) -> list[tuple[str, int, str, float]]:
    notifications: list[tuple[str, int, str, float]] = []
    users = data.setdefault("users", {})
    current = time.time() if now is None else now
    for user_id, user in users.items():
        if not isinstance(user, dict):
            continue
        changed, reached, label, total = apply_idle_income_to_user(user, current)
        if changed and reached >= 0:
            group_id = int(idle_state(user).get("group_id", 0) or 0)
            if group_id:
                notifications.append((str(user_id), group_id, label, total))
    return notifications
