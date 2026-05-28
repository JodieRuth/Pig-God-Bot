from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

DATA_FILE = Path(__file__).with_name("sbt.json")
IMAGE_DIR = Path(__file__).with_name("sbt_images")


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
            used_ids.add(item_id)
            items.append({"id": item_id, "path": path, "text": text, "sender_id": sender_id, "sender_name": sender_name})
            next_id = max(next_id, item_id + 1)
            continue
        path = str(raw).strip()
        if not path:
            changed = True
            continue
        item_id = next_id
        next_id += 1
        used_ids.add(item_id)
        items.append({"id": item_id, "path": path, "text": "", "sender_id": None, "sender_name": ""})
        changed = True
    return items, next_id, changed


def save_items(items: list[dict[str, Any]], next_id: int) -> None:
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    with DATA_FILE.open("w", encoding="utf-8") as f:
        json.dump({"next_id": next_id, "items": items}, f, ensure_ascii=False, indent=2)


def load_items() -> tuple[list[dict[str, Any]], int]:
    if not DATA_FILE.exists():
        return [], 1
    try:
        with DATA_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return [], 1
    items, next_id, changed = normalize_data(data)
    if changed:
        save_items(items, next_id)
    return items, next_id


def parse_id(text: str) -> int | None:
    match = re.fullmatch(r"#?(\d+)", text.strip())
    return int(match.group(1)) if match else None


def image_record_path(item: dict[str, Any]) -> Path:
    return Path(str(item.get("path") or ""))


def image_segment(path: Path) -> dict[str, Any]:
    return {"type": "image", "data": {"file": path.as_uri()}}


def copy_image(source: Path, item_id: int) -> Path:
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    suffix = source.suffix or ".png"
    target = IMAGE_DIR / f"{item_id}{suffix}"
    shutil.copy2(source, target)
    return target


def message_images(message: list[dict[str, Any]]) -> list[Path]:
    images: list[Path] = []
    for seg in message:
        if not isinstance(seg, dict) or seg.get("type") != "image":
            continue
        data = seg.get("data", {}) if isinstance(seg.get("data"), dict) else {}
        value = data.get("file") or data.get("url")
        if not value:
            continue
        if str(value).startswith("file://"):
            try:
                images.append(Path(str(value)[7:]))
            except Exception:
                continue
        else:
            images.append(Path(str(value)))
    return images


def extract_event_images(event: dict[str, Any]) -> list[Path]:
    images: list[Path] = []
    for key in ("current_images", "replied_images"):
        for record in event.get(key) or []:
            if isinstance(record, dict):
                path = record.get("path")
                if path:
                    images.append(Path(str(path)))
    return images


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
        for path in message_images(replied_segments):
            if path.exists():
                return path
    latest = latest_sender_image(event, ctx)
    if latest and latest.exists():
        return latest
    return None
