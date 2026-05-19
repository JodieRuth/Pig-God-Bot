from __future__ import annotations

from pathlib import Path
from typing import Any

from _pixiv_common import (
    MAX_COLLAGES,
    add_images_to_runtime,
    create_collages,
    format_candidates,
    limited_int,
    list_arg,
    normalize_sort,
    pixiv_search_title,
    store_search,
)


TOOL_DESCRIPTION = "按标题/说明文字搜索 Pixiv 全年龄插画候选，并生成带编号的缩略图拼图仅供 LLM 内部查看和挑选。适用于 pixiv_search_tag 按 tag 搜不到、tag 形态不确定、角色/作品名不是 Pixiv 正式 tag、或需要从标题/说明里反查实际 tag 名时使用。搜索成功后应观察候选摘要里的 tags，提取真实 Pixiv tag 形态；普通搜图请求仍必须继续调用 pixiv_select_result 选择最符合的一张或多张真实原图，不能直接把候选拼图发送给用户。"


def definition(ctx: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "pixiv_search_title",
            "description": TOOL_DESCRIPTION,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "用于 Pixiv 标题/说明文字搜索的关键词，例如角色名、作品名、别名、中文名、日文名或英文名。tag 搜索无结果时应尝试更宽泛的标题关键词。",
                    },
                    "required_terms": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "二次过滤必需匹配词，例如作品名、角色名、社团名。用于减少标题搜索误命中。",
                    },
                    "pages": {
                        "type": "integer",
                        "description": "搜索页数，1 到 4。每页最多拼 25 个候选。默认 1。",
                    },
                    "sort": {
                        "type": "string",
                        "enum": ["safe_relevance", "popular_safe", "date_desc", "bookmark_desc", "tag_match"],
                        "description": "筛选/排序偏好。safe_relevance=默认综合相关性；popular_safe=热门/人气优先；date_desc=最新/新图优先；bookmark_desc=收藏数优先；tag_match=标题/标签匹配优先。",
                    },
                    "min_bookmarks": {
                        "type": "integer",
                        "description": "可选的最低收藏数过滤。用户要求高质量/热门时可设置；无要求时省略或设 0。",
                    },
                },
                "required": ["query"],
            },
        },
    }


def info(ctx: dict[str, Any]) -> dict[str, str]:
    item = definition(ctx).get("function", {})
    return {
        "name": str(item.get("name") or "pixiv_search_title"),
        "description": str(item.get("description") or ""),
    }


def frequent_tags(candidates: list[dict[str, Any]], limit: int = 20) -> list[str]:
    counts: dict[str, int] = {}
    for item in candidates:
        for tag in item.get("tags", []):
            text = str(tag or "").strip()
            if text:
                counts[text] = counts.get(text, 0) + 1
    return [tag for tag, _ in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))[:limit]]


async def execute(args: dict[str, Any], runtime: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or args.get("title") or args.get("keyword") or "").strip()
    if not query:
        return {"ok": False, "content": "Pixiv 标题搜索失败：缺少 query。"}
    pages = limited_int(args.get("pages"), 1, 1, MAX_COLLAGES)
    sort = normalize_sort(args.get("sort"))
    min_bookmarks = limited_int(args.get("min_bookmarks"), 0, 0, 1_000_000)
    required_terms = list_arg(args.get("required_terms"))
    try:
        candidates = await pixiv_search_title(query, pages, sort, min_bookmarks, required_terms)
    except Exception as exc:
        return {"ok": False, "content": f"Pixiv 标题搜索失败：{ctx['exception_detail'](exc)}"}
    if not candidates:
        return {"ok": True, "content": f"Pixiv 标题搜索完成，但没有找到通过安全过滤的候选。query: {query}"}
    search_id = store_search(candidates, query, runtime=runtime)
    output_dir = Path(ctx.get("output_dir") or ".")
    try:
        collages = await create_collages(candidates, output_dir, search_id)
    except Exception as exc:
        return {"ok": False, "content": f"Pixiv 标题搜索候选拼图生成失败：{ctx['exception_detail'](exc)}"}
    image_items = [
        (path, f"Pixiv 标题搜索 {query} 的候选拼图 {index}/{len(collages)}，search_id={search_id}。仅供 LLM 内部挑选候选和反查实际 tag，禁止直接发送给用户；拼图编号不是 bot 图片编号。")
        for index, path in enumerate(collages, start=1)
    ]
    image_indexes = add_images_to_runtime(image_items, runtime, ctx)
    tags = frequent_tags(candidates)
    lines = [
        "Pixiv 标题搜索成功，已生成候选缩略图拼图并加入当前 LLM 图片上下文，仅供内部视觉挑选候选使用。",
        "使用建议：请观察候选摘要中的 tags，找出实际 Pixiv tag 名；如果标题搜索只是为了反查 tag，后续可用 pixiv_search_tag 重新按真实 tag 搜索。",
        "强制规则：除非用户明确要求查看候选/拼图/列表，否则不要把候选拼图发给用户，也不要让用户从候选编号中选择。",
        "普通搜图请求必须由 LLM 自行根据拼图和摘要选择候选，并继续调用 pixiv_select_result 下载真实原图/大图；选好真实图后再回答或发送真实图。",
        f"search_id: {search_id}",
        f"query: {query}",
        f"required_terms: {', '.join(required_terms) if required_terms else '无'}",
        f"排序/筛选模式: {sort}",
        f"最低收藏数过滤: {min_bookmarks}",
        f"通过安全过滤的候选数: {len(candidates)}",
        f"拼图张数: {len(collages)}",
        f"拼图在 bot 图片上下文中的编号: {', '.join(str(item) for item in image_indexes)}",
        f"候选中常见 tags: {', '.join(tags) if tags else '无'}",
        "重要：拼图里的 01、02 等编号是 Pixiv 候选编号，不是 bot 图片编号。需要某个缩略图背后的原图/大图时，继续调用 pixiv_select_result(search_id, candidate_numbers)。",
        "候选摘要：",
    ]
    if any(bool(item.get("min_bookmarks_fallback")) for item in candidates):
        lines.insert(9, "提示：没有候选达到请求的最低收藏数，因此已自动退回为热门/相关排序结果，避免误报无结果。")
    if any(bool(item.get("required_terms_fallback")) for item in candidates):
        lines.insert(9, "提示：没有候选完全命中 required_terms，因此已自动退回为标题搜索结果；请结合 tags 与拼图判断。")
    lines.extend(format_candidates(candidates, 30))
    return {"ok": True, "content": "\n".join(lines), "search_id": search_id, "candidate_count": len(candidates), "collage_image_indexes": image_indexes, "frequent_tags": tags}
