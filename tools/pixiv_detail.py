from __future__ import annotations

from pathlib import Path
from typing import Any

from _pixiv_common import add_image_to_runtime, download_full_image, metadata_text, pixiv_detail


TOOL_DESCRIPTION = "按 Pixiv PID 获取全年龄作品详情，并下载该作品的大图/原图加入当前 LLM 图片上下文。自动屏蔽 R18、R18G 和 AI 生成内容。工具返回标题、全部标签、简介、作者名、PID、链接等元数据；这些元数据也会和图片一起追加进上下文，供后续生图、发送、分析等工具使用。"


def definition(ctx: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "pixiv_detail",
            "description": TOOL_DESCRIPTION,
            "parameters": {
                "type": "object",
                "properties": {
                    "pid": {
                        "type": "string",
                        "description": "Pixiv 作品 PID。必须是全年龄、非 R18/R18G、非 AI 生成作品。",
                    }
                },
                "required": ["pid"],
            },
        },
    }


def info(ctx: dict[str, Any]) -> dict[str, str]:
    item = definition(ctx).get("function", {})
    return {
        "name": str(item.get("name") or "pixiv_detail"),
        "description": str(item.get("description") or ""),
    }


async def execute(args: dict[str, Any], runtime: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    pid = str(args.get("pid") or "").strip()
    if not pid:
        return {"ok": False, "content": "Pixiv 详情获取失败：缺少 pid。"}
    try:
        item = await pixiv_detail(pid)
        path = await download_full_image(item, Path(ctx.get("output_dir") or ".") / "pixiv_images")
    except Exception as exc:
        return {"ok": False, "content": f"Pixiv 详情获取失败：{ctx['exception_detail'](exc)}"}
    content = metadata_text(item)
    image_index = add_image_to_runtime(path, content, runtime, ctx)
    return {
        "ok": True,
        "content": f"{content}\n\n图片已下载并加入当前 LLM 图片上下文：图{image_index}。后续如需发送、分析或用于生图，请使用这个 bot 图片编号。",
        "pid": item.get("pid"),
        "image_index": image_index,
        "path": str(path),
        "raw_result": item,
    }
