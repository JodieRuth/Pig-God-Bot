from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

TOOL_PATH = Path(__file__).resolve().parent.parent / "tools" / "animetrace.py"
_spec = importlib.util.spec_from_file_location("local_onebot_animetrace_tool_for_command", TOOL_PATH)
if not _spec or not _spec.loader:
    raise RuntimeError("无法加载 animetrace 工具")
_tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_tool)


def select_command_images(event: dict[str, Any], ctx: dict[str, Any]) -> list[dict[str, Any]]:
    key = ctx["scope_key"](event)
    user_id = int(event.get("user_id", 0))
    current_images = list(event.get("current_images") or [])
    replied_images = list(event.get("replied_images") or [])
    if current_images:
        ctx["log"](f"AnimeTrace selected current message image: {current_images[-1].get('path')}")
        return current_images[-1:]
    if replied_images:
        ctx["log"](f"AnimeTrace selected replied image: {replied_images[-1].get('path')}")
        return replied_images[-1:]
    images = ctx["visible_images_for_sender"](key, user_id)
    if images:
        ctx["log"](f"AnimeTrace selected sender previous image: {images[-1].get('path')}")
        return images[-1:]
    _, recent_images = ctx["recent_context"](key)
    if recent_images:
        ctx["log"](f"AnimeTrace selected recent context image: {recent_images[-1].get('path')}")
    return recent_images[-1:]


async def avatar_image_record(event: dict[str, Any], qq: str, ctx: dict[str, Any]) -> dict[str, Any] | None:
    path = await ctx["download_qq_avatar"](qq)
    if not path:
        return None
    sender = event.get("sender") if isinstance(event.get("sender"), dict) else {}
    sender_name = str(sender.get("card") or sender.get("nickname") or event.get("user_id") or qq)
    return {
        "path": str(path),
        "sender_id": int(qq),
        "sender_name": f"QQ头像 {qq}",
        "message_id": event.get("message_id"),
        "source_sender_name": sender_name,
    }


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    target_qq = arg.strip()
    if target_qq:
        if not target_qq.isdigit():
            await ctx["reply"](event, "用法：/animetrace [QQ号]")
            return
        image = await avatar_image_record(event, target_qq, ctx)
        if not image:
            await ctx["reply"](event, f"获取 QQ {target_qq} 的头像失败。")
            return
        images = [image]
        message_id = event.get("message_id")
        target_event = event
        await ctx["reply_to_message"](target_event, message_id, f"正在使用 AnimeTrace 识别 QQ {target_qq} 的头像，请稍等。")
    else:
        images = select_command_images(event, ctx)
        if not images:
            await ctx["reply"](event, "没有找到可用于 AnimeTrace 识别的图片。请回复一条带图片的消息使用 /animetrace，或先发送图片再使用。")
            return
        message_id = images[0].get("message_id")
        target_event = event if message_id is None else {**event, "message_id": message_id}
        await ctx["reply_to_message"](target_event, message_id, "正在使用 AnimeTrace 识别图片，请稍等。")
    result = await _tool.execute({"image_indexes": [1]}, {"images": images}, ctx)
    await ctx["reply_to_message"](target_event, message_id, str(result.get("content") or "AnimeTrace 没有返回结果。"))


COMMAND = {
    "name": "/animetrace",
    "usage": "/animetrace [QQ号]",
    "description": "识别最近或回复消息中的图片角色来源；带 QQ 号时识别该 QQ 的高清头像。",
    "handler": handler,
}
