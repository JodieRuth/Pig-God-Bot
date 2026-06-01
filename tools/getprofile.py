from __future__ import annotations

from typing import Any


TOOL_DESCRIPTION = "获取指定 QQ 号的头像，并把头像图片追加到当前 LLM 图片上下文。适用于用户要求查看、分析、使用某个 QQ 头像，或提到自己的头像/某人的头像时。调用成功后会返回头像 URL、本地缓存路径和新的 bot 图片编号；后续如需发送该头像，使用 send_visible_image 并传入返回的 image_index。"


def definition(ctx: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "getprofile",
            "description": TOOL_DESCRIPTION,
            "parameters": {
                "type": "object",
                "properties": {
                    "qq": {
                        "type": "string",
                        "description": "要获取头像的 QQ 号。若用户说“我”“我的头像”，使用触发者 QQ。",
                    },
                    "size": {
                        "type": "integer",
                        "description": "头像尺寸，默认 640。通常不需要指定。",
                    },
                },
            },
        },
    }


def info(ctx: dict[str, Any]) -> dict[str, str]:
    item = definition(ctx).get("function", {})
    return {
        "name": str(item.get("name") or "getprofile"),
        "description": str(item.get("description") or ""),
    }


def add_image_to_runtime(path: Any, text: str, runtime: dict[str, Any], ctx: dict[str, Any]) -> int | str:
    add_image_context = ctx.get("add_tool_image_context")
    if not callable(add_image_context):
        return "?"
    record = add_image_context(runtime["event"], path, text)
    images = runtime.setdefault("images", [])
    if not isinstance(images, list):
        return "?"
    if record in images:
        images.remove(record)
    limit_getter = ctx.get("max_tool_context_images")
    max_images = int(limit_getter() if callable(limit_getter) else ctx.get("max_context_images", 10) or 10)
    while len(images) >= max_images and images:
        images.pop(0)
    images.append(record)
    return images.index(record) + 1 if record in images else "?"


async def execute(args: dict[str, Any], runtime: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    qq = str(args.get("qq") or runtime.get("trigger_sender_id") or "").strip()
    if not qq.isdigit() or not 5 <= len(qq) <= 20:
        return {"ok": False, "content": "获取 QQ 头像失败：缺少有效 QQ 号。"}
    try:
        size = int(args.get("size") or 640)
    except (TypeError, ValueError):
        size = 640
    size = max(40, min(size, 640))
    avatar_url = ctx["qq_avatar_url"](qq, size)
    try:
        path = await ctx["download_qq_avatar"](qq, size)
    except Exception as exc:
        return {"ok": False, "content": f"获取 QQ {qq} 的头像失败：{ctx['exception_detail'](exc)}", "qq": qq, "avatar_url": avatar_url}
    if path is None:
        return {"ok": False, "content": f"获取 QQ {qq} 的头像失败：无法下载头像。", "qq": qq, "avatar_url": avatar_url}
    text = f"QQ {qq} 的头像已加入上下文：{path.name}"
    image_index = add_image_to_runtime(path, text, runtime, ctx)
    content = "\n".join([
        f"已获取 QQ {qq} 的头像并追加到当前 LLM 图片上下文。",
        f"头像 URL：{avatar_url}",
        f"本地缓存：{path}",
        f"bot 图片编号：图{image_index}",
        "后续如需发送、分析或用于生图，请使用这里返回的 bot 图片编号。",
    ])
    return {"ok": True, "content": content, "qq": qq, "avatar_url": avatar_url, "path": str(path), "image_index": image_index}
