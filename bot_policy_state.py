from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

POLICY_STATE_FILE = Path(__file__).with_name("bot_policy_state.json")
HOURLY_USAGE_LIMIT = 12
DAILY_USAGE_LIMIT = 60
PolicyScope = Literal["groups", "private_users"]
UsageClaimReason = Literal["allowed", "duplicate", "hourly_limit", "daily_limit"]


@dataclass(frozen=True)
class UsageClaimResult:
    allowed: bool
    reason: UsageClaimReason
    hourly_used: int
    daily_used: int


def current_date_text(timestamp: float | None = None) -> str:
    value = time.time() if timestamp is None else timestamp
    return datetime.fromtimestamp(value).date().isoformat()


def default_policy_state(timestamp: float | None = None) -> dict[str, Any]:
    return {
        "operators": [],
        "disabled_commands": {},
        "usage": {
            "date": current_date_text(timestamp),
            "user_timestamps": {},
            "sent_content": [],
        },
    }


def normalized_integer_list(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    result: set[int] = set()
    for item in value:
        try:
            parsed = int(item)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            result.add(parsed)
    return sorted(result)


def normalized_disabled_commands(value: Any) -> dict[str, dict[str, list[int]]]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, dict[str, list[int]]] = {}
    for raw_name, raw_scopes in value.items():
        name = str(raw_name).strip().lower()
        if not name or not isinstance(raw_scopes, dict):
            continue
        scopes = {
            "groups": normalized_integer_list(raw_scopes.get("groups")),
            "private_users": normalized_integer_list(raw_scopes.get("private_users")),
        }
        if scopes["groups"] or scopes["private_users"]:
            result[name] = scopes
    return result


def normalized_user_timestamps(value: Any) -> dict[str, list[float]]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, list[float]] = {}
    for raw_user_id, raw_timestamps in value.items():
        user_id = str(raw_user_id).strip()
        if not user_id.isdigit() or not isinstance(raw_timestamps, list):
            continue
        timestamps: list[float] = []
        for raw_timestamp in raw_timestamps:
            try:
                timestamp = float(raw_timestamp)
            except (TypeError, ValueError):
                continue
            if timestamp > 0:
                timestamps.append(timestamp)
        result[user_id] = sorted(timestamps)
    return result


def normalized_policy_state(value: Any) -> dict[str, Any]:
    data = value if isinstance(value, dict) else {}
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    date_text = str(usage.get("date") or "").strip()
    sent_content = usage.get("sent_content") if isinstance(usage.get("sent_content"), list) else []
    return {
        "operators": normalized_integer_list(data.get("operators")),
        "disabled_commands": normalized_disabled_commands(data.get("disabled_commands")),
        "usage": {
            "date": date_text or current_date_text(),
            "user_timestamps": normalized_user_timestamps(usage.get("user_timestamps")),
            "sent_content": sorted({str(item).strip() for item in sent_content if str(item).strip()}),
        },
    }


def load_policy_state() -> dict[str, Any]:
    if not POLICY_STATE_FILE.exists():
        return default_policy_state()
    try:
        with POLICY_STATE_FILE.open("r", encoding="utf-8") as file:
            return normalized_policy_state(json.load(file))
    except (OSError, json.JSONDecodeError):
        return default_policy_state()


policy_state = load_policy_state()


def save_policy_state() -> None:
    normalized = normalized_policy_state(policy_state)
    policy_state.clear()
    policy_state.update(normalized)
    temporary_file = POLICY_STATE_FILE.with_suffix(".json.tmp")
    with temporary_file.open("w", encoding="utf-8") as file:
        json.dump(policy_state, file, ensure_ascii=False, indent=2)
    temporary_file.replace(POLICY_STATE_FILE)


def reset_daily_usage(timestamp: float | None = None) -> bool:
    date_text = current_date_text(timestamp)
    usage = policy_state.setdefault("usage", {})
    if usage.get("date") == date_text:
        return False
    policy_state["usage"] = {
        "date": date_text,
        "user_timestamps": {},
        "sent_content": [],
    }
    return True


def operator_user_ids() -> set[int]:
    return set(normalized_integer_list(policy_state.get("operators")))


def is_operator_user(user_id: int) -> bool:
    return int(user_id) in operator_user_ids()


def set_operator_user(user_id: int, enabled: bool) -> bool:
    target_user_id = int(user_id)
    operators = operator_user_ids()
    before = target_user_id in operators
    if enabled:
        operators.add(target_user_id)
    else:
        operators.discard(target_user_id)
    policy_state["operators"] = sorted(operators)
    if before == enabled:
        return False
    save_policy_state()
    return True


def command_is_enabled(command_name: str, scope: PolicyScope, scope_id: int) -> bool:
    disabled_commands = policy_state.get("disabled_commands", {})
    command_scopes = disabled_commands.get(command_name.lower(), {}) if isinstance(disabled_commands, dict) else {}
    disabled_values = command_scopes.get(scope, []) if isinstance(command_scopes, dict) else []
    return int(scope_id) not in normalized_integer_list(disabled_values)


def set_command_enabled(command_name: str, scope: PolicyScope, scope_id: int, enabled: bool) -> bool:
    name = command_name.strip().lower()
    disabled_commands = policy_state.setdefault("disabled_commands", {})
    command_scopes = disabled_commands.setdefault(name, {"groups": [], "private_users": []})
    disabled_values = set(normalized_integer_list(command_scopes.get(scope)))
    target_id = int(scope_id)
    before = target_id not in disabled_values
    if enabled:
        disabled_values.discard(target_id)
    else:
        disabled_values.add(target_id)
    command_scopes[scope] = sorted(disabled_values)
    command_scopes.setdefault("groups", [])
    command_scopes.setdefault("private_users", [])
    if not command_scopes["groups"] and not command_scopes["private_users"]:
        disabled_commands.pop(name, None)
    if before == enabled:
        return False
    save_policy_state()
    return True


def sent_content_fingerprints(timestamp: float | None = None) -> set[str]:
    if reset_daily_usage(timestamp):
        save_policy_state()
    usage = policy_state.get("usage", {})
    sent_content = usage.get("sent_content", []) if isinstance(usage, dict) else []
    return {str(item) for item in sent_content if str(item)}


def claim_content_usage(
    user_id: int,
    fingerprint: str,
    timestamp: float | None = None,
    allow_duplicate: bool = False,
) -> UsageClaimResult:
    current_timestamp = time.time() if timestamp is None else timestamp
    reset_daily_usage(current_timestamp)
    usage = policy_state.setdefault("usage", {})
    sent_content = {str(item) for item in usage.get("sent_content", []) if str(item)}
    user_timestamps = usage.setdefault("user_timestamps", {})
    user_key = str(int(user_id))
    timestamps = [
        float(value)
        for value in user_timestamps.get(user_key, [])
        if isinstance(value, (int, float)) and float(value) > 0
    ]
    hourly_used = sum(1 for value in timestamps if value > current_timestamp - 3600)
    daily_used = len(timestamps)
    if fingerprint in sent_content and not allow_duplicate:
        return UsageClaimResult(False, "duplicate", hourly_used, daily_used)
    if hourly_used >= HOURLY_USAGE_LIMIT:
        return UsageClaimResult(False, "hourly_limit", hourly_used, daily_used)
    if daily_used >= DAILY_USAGE_LIMIT:
        return UsageClaimResult(False, "daily_limit", hourly_used, daily_used)
    timestamps.append(current_timestamp)
    user_timestamps[user_key] = sorted(timestamps)
    sent_content.add(fingerprint)
    usage["sent_content"] = sorted(sent_content)
    save_policy_state()
    return UsageClaimResult(True, "allowed", hourly_used + 1, daily_used + 1)


def text_content_fingerprint(text: str) -> str:
    normalized = text.strip().encode("utf-8")
    return f"sb:{hashlib.sha256(normalized).hexdigest()}"


def image_content_fingerprint(md5_value: str) -> str:
    normalized = md5_value.strip().lower()
    return f"sbt:{normalized}" if normalized else ""
