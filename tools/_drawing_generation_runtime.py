from __future__ import annotations

import asyncio
import re
import secrets
from collections.abc import Iterable
from typing import Any


PUBLIC_GENERATION_ID_PATTERN = re.compile(r"^[0-9a-f]{8}$")
BACKGROUND_GENERATION_TASKS: dict[str, asyncio.Task[Any]] = {}
GATEWAY_GENERATION_IDS: dict[str, str] = {}
STOPPED_GENERATION_IDS: set[str] = set()


def normalize_public_generation_id(value: Any) -> str:
    public_id = str(value or "").strip().lower()
    if not PUBLIC_GENERATION_ID_PATTERN.fullmatch(public_id):
        return ""
    return public_id


def create_public_generation_id(
    gateway_job_id: str,
    reserved_ids: Iterable[str] = (),
) -> str:
    internal_id = str(gateway_job_id or "").strip()
    if not internal_id:
        raise ValueError("Drawing Gateway did not return a job id")
    unavailable = {
        str(value or "").strip().lower()
        for value in reserved_ids
        if str(value or "").strip()
    }
    unavailable.update(GATEWAY_GENERATION_IDS)
    for _ in range(128):
        public_id = secrets.token_hex(4)
        if public_id in unavailable:
            continue
        GATEWAY_GENERATION_IDS[public_id] = internal_id
        STOPPED_GENERATION_IDS.discard(public_id)
        return public_id
    raise RuntimeError("Unable to allocate a public generation task id")


def attach_background_generation_task(
    public_id: str,
    task: asyncio.Task[Any],
) -> None:
    normalized = normalize_public_generation_id(public_id)
    if not normalized or normalized not in GATEWAY_GENERATION_IDS:
        raise ValueError("Unknown public generation task id")
    BACKGROUND_GENERATION_TASKS[normalized] = task


def gateway_generation_id(public_id: Any) -> str:
    normalized = normalize_public_generation_id(public_id)
    if not normalized or normalized in STOPPED_GENERATION_IDS:
        return ""
    return GATEWAY_GENERATION_IDS.get(normalized, "")


def generation_reply_allowed(public_id: Any) -> bool:
    normalized = normalize_public_generation_id(public_id)
    return bool(
        normalized
        and normalized in GATEWAY_GENERATION_IDS
        and normalized not in STOPPED_GENERATION_IDS
    )


def active_public_generation_ids() -> list[str]:
    return [
        public_id
        for public_id in GATEWAY_GENERATION_IDS
        if public_id not in STOPPED_GENERATION_IDS
    ]


def stop_generation_wait(public_id: Any) -> bool:
    normalized = normalize_public_generation_id(public_id)
    if not normalized or normalized not in GATEWAY_GENERATION_IDS:
        return False
    STOPPED_GENERATION_IDS.add(normalized)
    task = BACKGROUND_GENERATION_TASKS.get(normalized)
    if task is not None and not task.done():
        task.cancel()
    return True


def release_public_generation(
    public_id: Any,
    task: asyncio.Task[Any] | None = None,
) -> None:
    normalized = normalize_public_generation_id(public_id)
    if not normalized:
        return
    current_task = BACKGROUND_GENERATION_TASKS.get(normalized)
    if task is not None and current_task is not None and current_task is not task:
        return
    BACKGROUND_GENERATION_TASKS.pop(normalized, None)
    GATEWAY_GENERATION_IDS.pop(normalized, None)
    STOPPED_GENERATION_IDS.discard(normalized)


def clear_generation_runtime() -> None:
    BACKGROUND_GENERATION_TASKS.clear()
    GATEWAY_GENERATION_IDS.clear()
    STOPPED_GENERATION_IDS.clear()
