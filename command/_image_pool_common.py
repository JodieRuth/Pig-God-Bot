from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import aiohttp

POOL_ROOT = Path(__file__).resolve().parent


def pool_data_file(pool_name: str) -> Path:
    return POOL_ROOT / f"{pool_name}.json"


def pool_image_dir(pool_name: str) -> Path:
    return POOL_ROOT / f"{pool_name}_images"


def normalize_data(data: Any) -> tuple[list[dict[str, Any]], int, bool]:
    changed = False
    items: list[dict[str, Any]] = []
    next_id = 1
    raw_items = data.get("items") if isinstance(data, dict) else data
    if isinstance(data, dict):
        try:
            next_id = max(1, int(data.get("next_id", 1)))
        except (TypeError, ValueError):
            changed = True
            next_id = 1
    if not isinstance(raw_items, list):
        return [], next_id, True
    used_ids: set[int] = set()
    for raw in raw_items:
        if isinstance(raw, dict):
            path = str(raw.get("path") or "").strip()
            text = str(raw.get("text") or "").strip()
            sender_id = raw.get("sender_id")
            sender_name = str(raw.get("sender_name") or "").strip()
            try:
                item_id = int(raw.get("id", 0))
            except (TypeError, ValueError):
                item_id = 0
            if not path or not Path(path).exists():
                changed = True
                continue
            if item_id <= 0 or item_id in used_ids:
                item_id = next_id
                next_id += 1
                changed = True
            md5_value = str(raw.get("md5") or "").strip().lower()
            if not md5_value:
                try:
                    md5_value = image_md5(Path(path))
                    changed = True
                except OSError:
                    md5_value = ""
            used_ids.add(item_id)
            items.append({"id": item_id, "path": path, "text": text, "sender_id": sender_id, "sender_name": sender_name, "md5": md5_value})
            next_id = max(next_id, item_id + 1)
            continue
        path = str(raw).strip()
        if not path:
            changed = True
            continue
        item_id = next_id
        next_id += 1
        used_ids.add(item_id)
        md5_value = ""
        try:
            md5_value = image_md5(Path(path))
        except OSError:
            pass
        items.append({"id": item_id, "path": path, "text": "", "sender_id": None, "sender_name": "", "md5": md5_value})
        changed = True
    return items, next_id, changed


def save_items(items: list[dict[str, Any]], next_id: int, pool_name: str = "sbt") -> None:
    pool_image_dir(pool_name).mkdir(parents=True, exist_ok=True)
    with pool_data_file(pool_name).open("w", encoding="utf-8") as f:
        json.dump({"next_id": next_id, "items": items}, f, ensure_ascii=False, indent=2)


def load_items(pool_name: str = "sbt") -> tuple[list[dict[str, Any]], int]:
    data_file = pool_data_file(pool_name)
    if not data_file.exists():
        return [], 1
    try:
        with data_file.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return [], 1
    items, next_id, changed = normalize_data(data)
    if changed:
        save_items(items, next_id, pool_name)
    return items, next_id


def parse_id(text: str) -> int | None:
    match = re.fullmatch(r"#?(\d+)", text.strip())
    return int(match.group(1)) if match else None


def image_record_path(item: dict[str, Any]) -> Path:
    return Path(str(item.get("path") or ""))


def image_md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def item_md5(item: dict[str, Any]) -> str:
    value = str(item.get("md5") or "").strip().lower()
    if value:
        return value
    path = image_record_path(item)
    try:
        return image_md5(path) if path.exists() else ""
    except OSError:
        return ""


def find_duplicate_by_md5(items: list[dict[str, Any]], md5_value: str) -> dict[str, Any] | None:
    lowered = md5_value.strip().lower()
    if not lowered:
        return None
    for item in items:
        if item_md5(item) == lowered:
            return item
    return None


def image_segment(path: Path) -> dict[str, Any]:
    return {"type": "image", "data": {"file": path.as_uri()}}


def stored_image_stem(item_id: int, sender_id: Any, saved_at: datetime | None = None) -> str:
    timestamp = (saved_at or datetime.now()).strftime("%Y%m%d%H%M%S")
    sender_text = str(sender_id or "unknown").strip() or "unknown"
    return f"{item_id}_{sender_text}_{timestamp}"


def suffix_from_bytes(data: bytes, content_type: str = "", fallback: str = "") -> str:
    lowered = content_type.lower()
    if data.startswith((b"GIF87a", b"GIF89a")) or "gif" in lowered:
        return ".gif"
    if data.startswith(b"\x89PNG\r\n\x1a\n") or "png" in lowered:
        return ".png"
    if data.startswith(b"\xff\xd8\xff") or "jpeg" in lowered or "jpg" in lowered:
        return ".jpg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP" or "webp" in lowered:
        return ".webp"
    suffix = Path(fallback).suffix.lower()
    return suffix if suffix else ".png"


def copy_image(source: Path, item_id: int, sender_id: Any = None, saved_at: datetime | None = None, pool_name: str = "sbt") -> Path:
    image_dir = pool_image_dir(pool_name)
    image_dir.mkdir(parents=True, exist_ok=True)
    data = source.read_bytes()
    suffix = suffix_from_bytes(data, fallback=source.name)
    target = image_dir / f"{stored_image_stem(item_id, sender_id, saved_at)}{suffix}"
    target.write_bytes(data)
    return target


async def save_image_ref(value: str, item_id: int, sender_id: Any = None, saved_at: datetime | None = None, pool_name: str = "sbt") -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.startswith("file://"):
        path = Path(text.removeprefix("file:///").removeprefix("file://"))
        return copy_image(path, item_id, sender_id, saved_at, pool_name) if path.exists() else None
    path = Path(text)
    if path.exists():
        return copy_image(path, item_id, sender_id, saved_at, pool_name)
    if not text.startswith(("http://", "https://")):
        return None
    async with aiohttp.ClientSession() as session:
        async with session.get(text, timeout=60) as resp:
            resp.raise_for_status()
            data = await resp.read()
            suffix = suffix_from_bytes(data, resp.headers.get("content-type", ""), text)
    image_dir = pool_image_dir(pool_name)
    image_dir.mkdir(parents=True, exist_ok=True)
    target = image_dir / f"{stored_image_stem(item_id, sender_id, saved_at)}{suffix}"
    target.write_bytes(data)
    return target


def onebot_response_data(response: Any) -> Any:
    if isinstance(response, dict) and "data" in response and ("status" in response or "retcode" in response):
        return response.get("data")
    return response


def is_image_like_segment(seg: dict[str, Any]) -> bool:
    return seg.get("type") in {"image", "mface"}


def message_image_refs(message: list[dict[str, Any]]) -> list[str]:
    refs: list[str] = []
    for seg in message:
        if not isinstance(seg, dict) or not is_image_like_segment(seg):
            continue
        data = seg.get("data", {}) if isinstance(seg.get("data"), dict) else {}
        for key in ("file", "path", "url"):
            value = data.get(key)
            if value:
                refs.append(str(value))
    return refs


async def save_image_segment(seg: dict[str, Any], item_id: int, ctx: dict[str, Any], sender_id: Any = None, saved_at: datetime | None = None, pool_name: str = "sbt") -> Path | None:
    data = seg.get("data", {}) if isinstance(seg.get("data"), dict) else {}
    file_value = data.get("file")
    if file_value and callable(ctx.get("onebot_post")):
        try:
            response = onebot_response_data(await ctx["onebot_post"]("get_image", {"file": str(file_value)}))
        except Exception:
            response = None
        if isinstance(response, dict):
            for key in ("file", "path", "url"):
                value = response.get(key)
                if not value:
                    continue
                try:
                    saved = await save_image_ref(str(value), item_id, sender_id, saved_at, pool_name)
                except Exception:
                    saved = None
                if saved is not None:
                    return saved
    for key in ("file", "path", "url"):
        value = data.get(key)
        if not value:
            continue
        try:
            saved = await save_image_ref(str(value), item_id, sender_id, saved_at, pool_name)
        except Exception:
            saved = None
        if saved is not None:
            return saved
    return None


async def save_first_image_from_message(message: list[dict[str, Any]], item_id: int, ctx: dict[str, Any], sender_id: Any = None, saved_at: datetime | None = None, pool_name: str = "sbt") -> Path | None:
    for seg in message:
        if isinstance(seg, dict) and is_image_like_segment(seg):
            saved = await save_image_segment(seg, item_id, ctx, sender_id, saved_at, pool_name)
            if saved is not None:
                return saved
    return None


def extract_event_images(event: dict[str, Any]) -> list[Path]:
    images: list[Path] = []
    for key in ("current_images", "replied_images"):
        for record in event.get(key) or []:
            if isinstance(record, dict):
                path = record.get("path")
                if path:
                    images.append(Path(str(path)))
    return images


def cached_image_from_event(event: dict[str, Any], key: str) -> Path | None:
    for record in event.get(key) or []:
        if isinstance(record, dict) and record.get("path"):
            path = Path(str(record.get("path")))
            if path.exists():
                return path
    return None


def latest_sender_image(event: dict[str, Any], ctx: dict[str, Any]) -> Path | None:
    sender_id = int(event.get("user_id", 0))
    scope = ctx.get("scope_key")
    visible = ctx.get("visible_images_for_sender")
    if callable(scope) and callable(visible):
        try:
            records = visible(scope(event), sender_id)
            for record in reversed(records):
                if isinstance(record, dict) and record.get("path"):
                    path = Path(str(record.get("path")))
                    if path.exists():
                        return path
        except Exception:
            pass
    return None


def choose_source_image(event: dict[str, Any], ctx: dict[str, Any]) -> Path | None:
    images = extract_event_images(event)
    if images:
        return images[0]
    replied = event.get("reply")
    if isinstance(replied, dict):
        replied_segments = replied.get("message") if isinstance(replied.get("message"), list) else []
        for ref in message_image_refs(replied_segments):
            path = Path(ref.removeprefix("file:///").removeprefix("file://")) if ref.startswith("file://") else Path(ref)
            if path.exists():
                return path
    latest = latest_sender_image(event, ctx)
    if latest and latest.exists():
        return latest
    return None


def has_reply_segment(message: list[dict[str, Any]]) -> bool:
    return any(isinstance(seg, dict) and seg.get("type") == "reply" for seg in message)


async def save_source_image(event: dict[str, Any], ctx: dict[str, Any], item_id: int, pool_name: str = "sbt") -> Path | None:
    sender_id = event.get("user_id")
    saved_at = datetime.now()
    message = event.get("message") if isinstance(event.get("message"), list) else []
    replied = event.get("reply")
    is_reply_command = has_reply_segment(message) or isinstance(replied, dict)
    if not is_reply_command:
        saved = await save_first_image_from_message(message, item_id, ctx, sender_id, saved_at, pool_name)
        if saved is not None:
            return saved
        current = cached_image_from_event(event, "current_images")
        if current is not None:
            return copy_image(current, item_id, sender_id, saved_at, pool_name)
    if isinstance(replied, dict):
        replied_segments = replied.get("message") if isinstance(replied.get("message"), list) else []
        saved = await save_first_image_from_message(replied_segments, item_id, ctx, sender_id, saved_at, pool_name)
        if saved is not None:
            return saved
    replied_cached = cached_image_from_event(event, "replied_images")
    if replied_cached is not None:
        return copy_image(replied_cached, item_id, sender_id, saved_at, pool_name)
    if is_reply_command:
        saved = await save_first_image_from_message(message, item_id, ctx, sender_id, saved_at, pool_name)
        if saved is not None:
            return saved
        return None
    latest = latest_sender_image(event, ctx)
    if latest and latest.exists():
        return copy_image(latest, item_id, sender_id, saved_at, pool_name)
    return None
