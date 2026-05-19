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
    pixiv_search_tag,
    store_search,
)


TOOL_DESCRIPTION = "搜索 Pixiv 全年龄插画候选并生成带编号的缩略图拼图仅供 LLM 内部查看和挑选。默认优先使用系统代理，自动屏蔽 R18、R18G 和 AI 生成内容。LLM 应根据用户偏好设置 sort，例如用户要热门/人气图时用 popular_safe，要最新/新图时用 date_desc，要精确 tag 匹配时用 tag_match。Pixiv 的相关 tag/联想 tag 有时并不可靠；遇到角色有多种 tag 形态、翻译名、旧译名、别名，或 xxx(作品名) 这种同名角色但作品不同的指定方式时，应主动把可能的 tag 形态放入 alternate_tags，并把作品名、角色限定词放入 required_terms 以二次过滤。强制规则：候选拼图只是工具中间产物，绝不能把候选拼图发送给用户，也不能让用户从候选拼图中挑编号，除非用户明确说要看候选/拼图/列表。普通搜图请求必须继续调用 pixiv_select_result 选择最符合的一张或多张真实原图；拼图里的编号是 Pixiv 候选编号，不是 bot 当前图片编号。"


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
                        "description": "Pixiv 搜索主 tag 或关键词。只能用于全年龄内容搜索。遇到 xxx(作品名) 时可以直接填原文，程序会自动扩展搜索 xxx 和作品名。",
                    },
                    "alternate_tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "同一角色/主题可能的其他 Pixiv tag 形态、日文名、英文名、中文名、旧译名、别名。Pixiv 相关 tag 并不总可靠，LLM 应主动提供合理别名以合并搜索。",
                    },
                    "required_terms": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "二次过滤必需匹配词，例如作品名、角色名、社团名。用于区分 xxx(作品名) 这类同名角色但作品不同的情况；会在标题、标签、作者、简介中匹配。",
                    },
                    "pages": {
                        "type": "integer",
                        "description": "搜索页数，1 到 4。每页最多拼 25 个候选。默认 1。",
                    },
                    "sort": {
                        "type": "string",
                        "enum": ["safe_relevance", "popular_safe", "date_desc", "bookmark_desc", "tag_match"],
                        "description": "筛选/排序偏好。safe_relevance=默认综合相关性；popular_safe=热门/人气优先；date_desc=最新/新图优先；bookmark_desc=收藏数优先；tag_match=标签标题匹配优先。应根据用户要求选择，例如用户说热门就用 popular_safe，说新图就用 date_desc。",
                    },
                    "min_bookmarks": {
                        "type": "integer",
                        "description": "可选的最低收藏数过滤。用户要求高质量/热门时可设置，例如 100、500、1000；无要求时省略或设 0。",
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
    sort = normalize_sort(args.get("sort"))
    min_bookmarks = limited_int(args.get("min_bookmarks"), 0, 0, 1_000_000)
    alternate_tags = list_arg(args.get("alternate_tags"))
    required_terms = list_arg(args.get("required_terms"))
    try:
        candidates = await pixiv_search_tag(tag, pages, sort, min_bookmarks, alternate_tags, required_terms)
    except Exception as exc:
        return {"ok": False, "content": f"Pixiv 搜索失败：{ctx['exception_detail'](exc)}"}
    if not candidates:
        return {"ok": True, "content": f"Pixiv 搜索完成，但没有找到通过安全过滤的候选。tag: {tag}"}
    search_id = store_search(candidates, tag, runtime=runtime)
    output_dir = Path(ctx.get("output_dir") or ".")
    try:
        collages = await create_collages(candidates, output_dir, search_id)
    except Exception as exc:
        return {"ok": False, "content": f"Pixiv 候选拼图生成失败：{ctx['exception_detail'](exc)}"}
    image_items = [
        (path, f"Pixiv 搜索 {tag} 的候选拼图 {index}/{len(collages)}，search_id={search_id}。仅供 LLM 内部挑选候选，禁止直接发送给用户；拼图编号不是 bot 图片编号。")
        for index, path in enumerate(collages, start=1)
    ]
    image_indexes = add_images_to_runtime(image_items, runtime, ctx)
    lines = [
        "Pixiv 搜索成功，已生成候选缩略图拼图并加入当前 LLM 图片上下文，仅供内部视觉挑选候选使用。",
        "强制规则：除非用户明确要求查看候选/拼图/列表，否则不要把候选拼图发给用户，也不要让用户从候选编号中选择。",
        "普通搜图请求必须由 LLM 自行根据拼图和摘要选择候选，并继续调用 pixiv_select_result 下载真实原图/大图；选好真实图后再回答或发送真实图。",
        "警告：搜索结果已自动过滤 R18、R18G 和 AI 生成内容，但仍需人工确认内容是否符合用户需求与安全规范。",
        f"search_id: {search_id}",
        f"tag: {tag}",
        f"alternate_tags: {', '.join(alternate_tags) if alternate_tags else '无'}",
        f"required_terms: {', '.join(required_terms) if required_terms else '无'}",
        f"排序/筛选模式: {sort}",
        f"最低收藏数过滤: {min_bookmarks}",
        f"通过安全过滤的候选数: {len(candidates)}",
        f"拼图张数: {len(collages)}",
        f"拼图在 bot 图片上下文中的编号: {', '.join(str(item) for item in image_indexes)}",
        "重要：拼图里的 01、02 等编号是 Pixiv 候选编号，不是 bot 图片编号。需要某个缩略图背后的原图/大图时，继续调用 pixiv_select_result(search_id, candidate_numbers)。",
        "候选摘要：",
    ]
    if any(bool(item.get("min_bookmarks_fallback")) for item in candidates):
        lines.insert(8, "提示：没有候选达到请求的最低收藏数，因此已自动退回为热门/相关排序结果，避免误报无结果。")
    if any(bool(item.get("required_terms_fallback")) for item in candidates):
        lines.insert(8, "提示：没有候选完全命中 required_terms，因此已自动退回为合并搜索结果；Pixiv tag/相关 tag 有时不可靠，请结合拼图与候选摘要判断。")
    lines.extend(format_candidates(candidates, 30))
    return {"ok": True, "content": "\n".join(lines), "search_id": search_id, "candidate_count": len(candidates), "collage_image_indexes": image_indexes}
