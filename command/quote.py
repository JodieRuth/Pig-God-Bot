from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).with_name("quote")
DATA_FILE = DATA_DIR / "data.json"
IMG_DIR = DATA_DIR / "img"
PAGE_SIZE = 10
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024


def load_data() -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not DATA_FILE.exists():
        return {"groups": {}}
    try:
        with DATA_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"groups": {}}
    if not isinstance(data, dict):
        return {"groups": {}}
    groups = data.setdefault("groups", {})
    if not isinstance(groups, dict):
        data["groups"] = {}
    return data


def save_data(data: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = DATA_FILE.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(DATA_FILE)


def group_quotes(data: dict[str, Any], group_id: str) -> list[dict[str, Any]]:
    groups = data.setdefault("groups", {})
    quotes = groups.setdefault(group_id, [])
    if not isinstance(quotes, list):
        groups[group_id] = []
        return groups[group_id]
    return quotes


def message_segments(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        message = value.get("message")
        if isinstance(message, list):
            return [item for item in message if isinstance(item, dict)]
    return []


def reply_message_id(message: list[dict[str, Any]]) -> str:
    for seg in message:
        if seg.get("type") == "reply":
            value = seg.get("data", {}).get("id")
            if value:
                return str(value)
    return ""


def message_text(message: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for seg in message:
        typ = seg.get("type")
        data = seg.get("data", {})
        if typ == "text":
            parts.append(str(data.get("text") or ""))
        elif typ == "at":
            qq = str(data.get("qq") or "")
            if qq:
                parts.append(f"@{qq}")
        elif typ == "face":
            parts.append("[表情]")
    return "".join(parts).strip()


def image_sources(message: list[dict[str, Any]]) -> list[str]:
    sources: list[str] = []
    for seg in message:
        if seg.get("type") != "image":
            continue
        data = seg.get("data", {})
        value = data.get("url") or data.get("file")
        if value:
            sources.append(str(value))
    return sources


def image_suffix(source: str) -> str:
    lower = source.lower().split("?", 1)[0]
    for suffix in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"):
        if lower.endswith(suffix):
            return suffix
    return ".jpg"


async def save_quote_image(source: str) -> str | None:
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    target = IMG_DIR / f"{int(time.time())}_{uuid.uuid4().hex}{image_suffix(source)}"
    if source.startswith("file://"):
        path = Path(source.removeprefix("file:///").removeprefix("file://"))
        if not path.exists():
            return None
        shutil.copyfile(path, target)
        return str(target.relative_to(DATA_DIR))
    if source.startswith(("http://", "https://")):
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(source, timeout=60) as resp:
                resp.raise_for_status()
                size = 0
                with target.open("wb") as f:
                    async for chunk in resp.content.iter_chunked(64 * 1024):
                        size += len(chunk)
                        if size > MAX_DOWNLOAD_BYTES:
                            target.unlink(missing_ok=True)
                            raise RuntimeError("图片超过大小限制")
                        f.write(chunk)
        return str(target.relative_to(DATA_DIR))
    return None


async def save_quote_images(message: list[dict[str, Any]]) -> list[str]:
    paths: list[str] = []
    for source in image_sources(message):
        path = await save_quote_image(source)
        if path:
            paths.append(path)
    return paths


def sender_id(data: dict[str, Any]) -> str:
    sender = data.get("sender") if isinstance(data.get("sender"), dict) else {}
    return str(data.get("user_id") or sender.get("user_id") or "0")


def sender_name(data: dict[str, Any]) -> str:
    sender = data.get("sender") if isinstance(data.get("sender"), dict) else {}
    user_id = sender_id(data)
    return str(sender.get("card") or sender.get("nickname") or user_id).strip()


def clean_text(text: str) -> str:
    return " ".join(str(text).replace("[图片]", "").split()).strip()


def truncate_text(text: str, limit: int = 20) -> str:
    value = clean_text(text)
    if len(value) <= limit:
        return value
    return f"{value[:limit]}..."


def format_time(timestamp: Any) -> str:
    try:
        value = int(timestamp)
    except (TypeError, ValueError):
        value = int(time.time())
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(value))


def quote_display_text(item: dict[str, Any]) -> str:
    text = clean_text(str(item.get("text") or ""))
    images = item.get("images") if isinstance(item.get("images"), list) else []
    if text and images:
        return f"{truncate_text(text)}[图片]"
    if text:
        return truncate_text(text)
    if images:
        name = str(item.get("name") or item.get("qq") or "某人")
        return f"{name}在{format_time(item.get('time'))}发的一张图片"
    return "空收藏"


def current_group_id(event: dict[str, Any]) -> str:
    return str(event.get("group_id") or "private")


def current_sender_name(event: dict[str, Any]) -> str:
    sender = event.get("sender") if isinstance(event.get("sender"), dict) else {}
    user_id = str(event.get("user_id") or "0")
    return str(sender.get("card") or sender.get("nickname") or user_id).strip()


async def handle_add(event: dict[str, Any], key: str, ctx: dict[str, Any]) -> None:
    message = event.get("message", [])
    if not key:
        await ctx["reply"](event, "用法：回复要收藏的消息并发送 /quote add <编号>")
        return
    if not reply_message_id(message):
        await ctx["reply"](event, "请直接回复要收藏的消息并发送 /quote add <编号>。")
        return
    replied = event.get("reply")
    if not isinstance(replied, dict):
        await ctx["reply"](event, "没有读取到被回复的消息。")
        return
    segments = message_segments(replied)
    text = clean_text(message_text(segments))
    images = await save_quote_images(segments)
    if not text and not images:
        await ctx["reply"](event, "这条消息没有可收藏的文本或图片内容。")
        return
    data = load_data()
    group_id = current_group_id(event)
    quotes = group_quotes(data, group_id)
    for item in quotes:
        if str(item.get("key") or "") == key:
            await ctx["reply"](event, "这个编号已经存在。")
            return
    item = {
        "key": key,
        "qq": sender_id(replied),
        "name": sender_name(replied),
        "time": int(replied.get("time") or time.time()),
        "text": text,
        "images": images,
    }
    quotes.append(item)
    save_data(data)
    await ctx["reply"](event, f"已收藏 {key}：{item['name']}：{quote_display_text(item)}")


async def handle_remove(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    if not ctx["is_controller"](event):
        await ctx["reply"](event, "你没有权限移除收藏。")
        return
    parts = arg.split(maxsplit=1)
    if len(parts) != 2 or not parts[1].strip():
        await ctx["reply"](event, "用法：/quote remove <编号>")
        return
    key = parts[1].strip()
    data = load_data()
    quotes = group_quotes(data, current_group_id(event))
    for index, item in enumerate(quotes):
        if str(item.get("key") or index + 1) == key:
            removed = quotes.pop(index)
            save_data(data)
            await ctx["reply"](event, f"已移除 {key}：{removed.get('name', '未知')}：{quote_display_text(removed)}")
            return
    await ctx["reply"](event, "没有这个编号的收藏。")


async def handle_list(event: dict[str, Any], page: int, ctx: dict[str, Any]) -> None:
    data = load_data()
    quotes = group_quotes(data, current_group_id(event))
    current_user_id = str(event.get("user_id") or "0")
    current_name = current_sender_name(event)
    changed = False
    for item in quotes:
        if str(item.get("qq") or "") == current_user_id and item.get("name") != current_name:
            item["name"] = current_name
            changed = True
    if changed:
        save_data(data)
    if not quotes:
        await ctx["reply"](event, "当前群还没有收藏。回复消息并发送 /quote add <编号> 可以收藏。")
        return
    total_pages = max(1, (len(quotes) + PAGE_SIZE - 1) // PAGE_SIZE)
    if page < 1 or page > total_pages:
        await ctx["reply"](event, f"没有这一页。当前共 {total_pages} 页。")
        return
    start = (page - 1) * PAGE_SIZE
    page_quotes = quotes[start:start + PAGE_SIZE]
    lines = [f"当前群收藏列表（第 {page}/{total_pages} 页）："]
    for index, item in enumerate(page_quotes, start + 1):
        key = str(item.get("key") or index)
        name = str(item.get("name") or item.get("qq") or "未知")
        text = quote_display_text(item)
        lines.append(f"{key}. {name}：{text}")
    if page < total_pages:
        lines.append(f"发送 /quote {page + 1} 查看下一页。")
    await ctx["reply"](event, "\n".join(lines))


async def handle_say(event: dict[str, Any], key: str, ctx: dict[str, Any]) -> None:
    data = load_data()
    quotes = group_quotes(data, current_group_id(event))
    for index, item in enumerate(quotes, 1):
        if str(item.get("key") or index) == key:
            text = clean_text(str(item.get("text") or ""))
            images = item.get("images") if isinstance(item.get("images"), list) else []
            if images:
                message: list[dict[str, Any]] = []
                if text:
                    message.append({"type": "text", "data": {"text": text + "\n"}})
                for image in images:
                    path = DATA_DIR / str(image)
                    if path.exists():
                        message.append({"type": "image", "data": {"file": path.as_uri()}})
                if message:
                    await ctx["reply"](event, message)
                    return
            await ctx["reply"](event, text or "这条收藏是空的。")
            return
    await ctx["reply"](event, "没有这个编号的收藏。")


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    value = arg.strip()
    lower_value = value.lower()
    if lower_value == "add" or lower_value.startswith("add "):
        parts = value.split(maxsplit=1)
        key = parts[1].strip() if len(parts) == 2 else ""
        await handle_add(event, key, ctx)
        return
    if lower_value.startswith("remove"):
        await handle_remove(event, value, ctx)
        return
    if lower_value == "replay" or lower_value.startswith("replay "):
        parts = value.split(maxsplit=1)
        key = parts[1].strip() if len(parts) == 2 else ""
        if not key:
            await ctx["reply"](event, "用法：/quote replay <编号>")
            return
        await handle_say(event, key, ctx)
        return
    if value:
        if value.isdigit():
            await handle_list(event, int(value), ctx)
            return
        await ctx["reply"](event, "用法：/quote、/quote <页码>、/quote add <编号>、/quote replay <编号>、/quote remove <编号>")
        return
    await handle_list(event, 1, ctx)


COMMAND = {
    "name": "/quote",
    "usage": "/quote [页码 | add <编号> | replay <编号> | remove <编号>]",
    "description": "回复消息后用 add 编号收藏群友语录；默认分页列出本群收藏；用 replay 复读；remove 仅管理员可用。",
    "handler": handler,
}
