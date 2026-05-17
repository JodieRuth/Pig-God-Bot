from __future__ import annotations

from pathlib import Path
from typing import Any

from _pixiv_common import (
    MAX_COLLAGES,
    add_image_to_runtime,
    create_collages,
    format_candidates,
    limited_int,
    pixiv_search_tag,
    store_search,
)


TOOL_DESCRIPTION = "搜索 Pixiv 全年龄插画候选并生成带编号的缩略图拼图给 LLM 查看。自动屏蔽 R18、R18G 和 AI 生成内容。注意：拼图里的编号是 Pixiv 候选编号，不是 bot 当前图片编号；如果需要某张候选背后的原图/大图，必须继续调用 pixiv_select_result，并传 search_id 与候选编号。"


def definition(ctx: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "pixiv_search_tag",
            "description": TOOL_DESCRIPTION,
            "parameters": {
                "type": "object",
                "properties": {
                    "tag": {
                        "type": "string",
                        "description": "Pixiv 搜索 tag 或关键词。只能用于全年龄内容搜索。",
                    },
                    "pages": {
                        "type": "integer",
                        "description": "搜索页数，1 到 4。每页最多拼 25 个候选。默认 1。",
                    },
                    "sort": {
                        "type": "string",
                        "description": "本地排序方式：safe_relevance、date_desc、bookmark_desc、popular_safe、tag_match。默认 safe_relevance。",
                    },
                },
                "required": ["tag"],
            },
        },
    }


def info(ctx: dict[str, Any]) -> dict[str, str]:
    item = definition(ctx).get("function", {})
    return {
        "name": str(item.get("name") or "pixiv_search_tag"),
        "description": str(item.get("description") or ""),
    }


async def execute(args: dict[str, Any], runtime: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    tag = str(args.get("tag") or "").strip()
    if not tag:
        return {"ok": False, "content": "Pixiv 搜索失败：缺少 tag。"}
    pages = limited_int(args.get("pages"), 1, 1, MAX_COLLAGES)
    sort = str(args.get("sort") or "safe_relevance").strip() or "safe_relevance"
    try:
        candidates = await pixiv_search_tag(tag, pages, sort)
    except Exception as exc:
        return {"ok": False, "content": f"Pixiv 搜索失败：{ctx['exception_detail'](exc)}"}
    if not candidates:
        return {"ok": True, "content": f"Pixiv 搜索完成，但没有找到通过安全过滤的候选。tag: {tag}"}
    search_id = store_search(candidates, tag)
    output_dir = Path(ctx.get("output_dir") or ".")
    try:
        collages = await create_collages(candidates, output_dir, search_id)
    except Exception as exc:
        return {"ok": False, "content": f"Pixiv 候选拼图生成失败：{ctx['exception_detail'](exc)}"}
    image_indexes: list[Any] = []
    for index, path in enumerate(collages, start=1):
        image_index = add_image_to_runtime(path, f"Pixiv 搜索 {tag} 的候选拼图 {index}/{len(collages)}，search_id={search_id}。拼图编号不是 bot 图片编号。", runtime, ctx)
        image_indexes.append(image_index)
    lines = [
        "Pixiv 搜索成功，已生成候选缩略图拼图并加入当前 LLM 图片上下文。",
        f"search_id: {search_id}",
        f"tag: {tag}",
        f"通过安全过滤的候选数: {len(candidates)}",
        f"拼图张数: {len(collages)}",
        f"拼图在 bot 图片上下文中的编号: {', '.join(str(item) for item in image_indexes)}",
        "重要：拼图里的 01、02 等编号是 Pixiv 候选编号，不是 bot 图片编号。需要某个缩略图背后的原图/大图时，继续调用 pixiv_select_result(search_id, candidate_numbers)。",
        "候选摘要：",
    ]
    lines.extend(format_candidates(candidates, 30))
    return {"ok": True, "content": "\n".join(lines), "search_id": search_id, "candidate_count": len(candidates), "collage_image_indexes": image_indexes}
