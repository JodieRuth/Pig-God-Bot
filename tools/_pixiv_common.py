from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

import aiohttp
from PIL import Image, ImageDraw, ImageFont, ImageOps


PIXIV_BASE = "https://www.pixiv.net"
PIXIV_AJAX = f"{PIXIV_BASE}/ajax"
PIXIV_REFERER = PIXIV_BASE + "/"
MAX_CANDIDATES_PER_COLLAGE = 25
MAX_COLLAGES = 4
MAX_SEARCH_CANDIDATES = MAX_CANDIDATES_PER_COLLAGE * MAX_COLLAGES
PIXIV_TIMEOUT = aiohttp.ClientTimeout(total=int(os.getenv("PIXIV_TIMEOUT_SECONDS", "45")))
PIXIV_USE_SYSTEM_PROXY = os.getenv("PIXIV_USE_SYSTEM_PROXY", "1") != "0"
PIXIV_COOKIE = os.getenv("PIXIV_COOKIE", "").strip()
PIXIV_ACCEPT_LANGUAGE = os.getenv("PIXIV_ACCEPT_LANGUAGE", "zh-CN,zh;q=0.9,en;q=0.8,ja;q=0.7")
SEARCH_CACHE_TTL_SECONDS = int(os.getenv("PIXIV_SEARCH_CACHE_TTL_SECONDS", "1800"))
PIXIV_DETAIL_ENRICH_LIMIT = int(os.getenv("PIXIV_DETAIL_ENRICH_LIMIT", "120"))
PIXIV_DETAIL_ENRICH_CONCURRENCY = int(os.getenv("PIXIV_DETAIL_ENRICH_CONCURRENCY", "6"))
SEARCH_CACHE: dict[str, dict[str, Any]] = {}


BLOCKED_TAGS = {
    "r-18",
    "r18",
    "r-18g",
    "r18g",
    "r-18guro",
    "r18guro",
    "ai生成",
    "ai生成作品",
    "ai-generated",
    "aigenerated",
    "ai generated",
    "aiイラスト",
    "aiart",
    "ai art",
}


SORT_ALIASES = {
    "safe_relevance": "safe_relevance",
    "relevance": "safe_relevance",
    "相关": "safe_relevance",
    "相关优先": "safe_relevance",
    "date_desc": "date_desc",
    "date": "date_desc",
    "new": "date_desc",
    "newest": "date_desc",
    "latest": "date_desc",
    "最新": "date_desc",
    "新图": "date_desc",
    "优先新图": "date_desc",
    "bookmark_desc": "bookmark_desc",
    "bookmarks": "bookmark_desc",
    "bookmark": "bookmark_desc",
    "收藏": "bookmark_desc",
    "收藏优先": "bookmark_desc",
    "popular_safe": "popular_safe",
    "popular": "popular_safe",
    "popularity": "popular_safe",
    "hot": "popular_safe",
    "热门": "popular_safe",
    "人气": "popular_safe",
    "人气优先": "popular_safe",
    "tag_match": "tag_match",
    "tag": "tag_match",
    "标签匹配": "tag_match",
}


REQUEST_HEADERS = {
    "User-Agent": os.getenv("PIXIV_USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": PIXIV_ACCEPT_LANGUAGE,
    "Referer": PIXIV_REFERER,
}
if PIXIV_COOKIE:
    REQUEST_HEADERS["Cookie"] = PIXIV_COOKIE


IMAGE_HEADERS = {
    "User-Agent": REQUEST_HEADERS["User-Agent"],
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "Accept-Language": PIXIV_ACCEPT_LANGUAGE,
    "Referer": PIXIV_REFERER,
}
if PIXIV_COOKIE:
    IMAGE_HEADERS["Cookie"] = PIXIV_COOKIE


def limited_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def clean_text(value: Any, limit: int = 120) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def tag_names(value: Any) -> list[str]:
    result: list[str] = []
    if isinstance(value, dict):
        tags = value.get("tags")
        if isinstance(tags, list):
            for item in tags:
                if isinstance(item, dict):
                    name = str(item.get("tag") or item.get("name") or "").strip()
                    translation = item.get("translation")
                    if name:
                        result.append(name)
                    if isinstance(translation, dict):
                        translated = str(translation.get("en") or "").strip()
                        if translated:
                            result.append(translated)
                elif item:
                    result.append(str(item).strip())
        for key in ("tag", "tags", "illustTags"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                result.extend(part.strip() for part in re.split(r"[,\s]+", item) if part.strip())
    elif isinstance(value, list):
        for item in value:
            result.extend(tag_names(item))
    return [item for item in result if item]


def contains_blocked_text(*values: Any) -> bool:
    combined = " ".join(str(value or "") for value in values).lower().replace("_", " ")
    compact = combined.replace(" ", "").replace("-", "")
    for tag in BLOCKED_TAGS:
        lowered = tag.lower()
        if lowered in combined or lowered.replace(" ", "").replace("-", "") in compact:
            return True
    return False


def is_safe_item(item: dict[str, Any]) -> bool:
    x_restrict = item.get("xRestrict", item.get("x_restrict", item.get("xRestrictLabel")))
    try:
        if int(x_restrict or 0) != 0:
            return False
    except (TypeError, ValueError):
        if str(x_restrict or "").strip().lower() not in {"", "0", "safe", "全年齢"}:
            return False
    ai_type = item.get("aiType", item.get("ai_type"))
    try:
        if int(ai_type or 0) == 2:
            return False
    except (TypeError, ValueError):
        if str(ai_type or "").strip().lower() in {"ai", "generated", "ai-generated"}:
            return False
    tags = tag_names(item.get("tags")) or tag_names(item)
    return not contains_blocked_text(item.get("title"), item.get("description"), item.get("alt"), " ".join(tags))


def pick_url(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    return ""


def full_url_from_thumb(url: str) -> str:
    result = url
    replacements = [
        ("/c/250x250_80_a2/custom-thumb/", "/img-master/"),
        ("/c/250x250_80_a2/img-master/", "/img-master/"),
        ("/c/540x540_70/", "/"),
    ]
    for old, new in replacements:
        result = result.replace(old, new)
    result = result.replace("_square1200.jpg", "_master1200.jpg")
    result = result.replace("_custom1200.jpg", "_master1200.jpg")
    return result


def normalize_search_item(item: dict[str, Any]) -> dict[str, Any] | None:
    pid = str(item.get("id") or item.get("illustId") or item.get("illust_id") or "").strip()
    if not pid:
        return None
    title = clean_text(item.get("title") or item.get("illustTitle") or item.get("alt"))
    user_id = str(item.get("userId") or item.get("user_id") or "").strip()
    user_name = clean_text(item.get("userName") or item.get("user_name") or item.get("profileImageUrl"), 80)
    thumbnail = pick_url(item.get("url"), item.get("thumb"), item.get("thumbnail"), item.get("thumbnail_src"), item.get("cover"))
    full = pick_url(item.get("original"), item.get("regular"), item.get("img_src"), item.get("full")) or full_url_from_thumb(thumbnail)
    tags = tag_names(item.get("tags")) or tag_names(item)
    bookmarks = item.get("bookmarkCount", item.get("total_bookmarks", item.get("bookmark_count", 0)))
    views = item.get("viewCount", item.get("total_view", item.get("view_count", 0)))
    date = str(item.get("createDate") or item.get("create_date") or item.get("updateDate") or item.get("date") or "")
    record = {
        "pid": pid,
        "title": title,
        "user_id": user_id,
        "user_name": user_name,
        "thumbnail_url": thumbnail,
        "full_url": full,
        "url": f"https://www.pixiv.net/artworks/{pid}",
        "tags": tags,
        "bookmark_count": numeric_score(bookmarks),
        "view_count": numeric_score(views),
        "date": date,
        "raw": item,
    }
    return record if is_safe_item({**item, "tags": tags}) and thumbnail else None


def numeric_score(value: Any) -> int:
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return 0


def normalize_sort(value: Any) -> str:
    key = str(value or "safe_relevance").strip().lower()
    return SORT_ALIASES.get(key, "safe_relevance")


def list_arg(value: Any) -> list[str]:
    if value is None:
        return []
    raw_values = value if isinstance(value, list) else [value]
    result: list[str] = []
    for raw in raw_values:
        text = str(raw or "").strip()
        if not text:
            continue
        parts = [part.strip() for part in re.split(r"[,，\n]+", text) if part.strip()]
        for part in parts:
            if part not in result:
                result.append(part)
    return result


def split_parenthesized_term(value: str) -> tuple[str, str]:
    text = str(value or "").strip()
    match = re.match(r"^(.+?)[（(]([^（）()]+)[）)]$", text)
    if not match:
        return text, ""
    return match.group(1).strip(), match.group(2).strip()


def expanded_search_tags(tags: list[str]) -> list[str]:
    result: list[str] = []
    for tag in tags:
        main, qualifier = split_parenthesized_term(tag)
        for value in (tag, main, qualifier):
            if value and value not in result:
                result.append(value)
    return result


def item_match_text(item: dict[str, Any]) -> str:
    values = [item.get("title"), item.get("description"), item.get("user_name"), item.get("user_id"), " ".join(str(tag) for tag in item.get("tags", []))]
    return " ".join(str(value or "") for value in values).lower()


def matches_required_terms(item: dict[str, Any], terms: list[str]) -> bool:
    if not terms:
        return True
    text = item_match_text(item)
    compact = re.sub(r"[\s_\-・·:：/\\]+", "", text)
    for term in terms:
        lowered = term.lower().strip()
        term_compact = re.sub(r"[\s_\-・·:：/\\]+", "", lowered)
        if lowered not in text and term_compact not in compact:
            return False
    return True


def search_score(item: dict[str, Any], query: str, sort: str) -> tuple[Any, ...]:
    title = str(item.get("title") or "").lower()
    tags = " ".join(str(tag) for tag in item.get("tags", [])).lower()
    q = query.lower()
    tag_match = int(q in tags) * 4 + int(q in title) * 2
    bookmarks = int(item.get("bookmark_count") or 0)
    views = int(item.get("view_count") or 0)
    date = str(item.get("date") or "")
    if sort == "date_desc":
        return (date, bookmarks, tag_match, views)
    if sort == "bookmark_desc":
        return (bookmarks, views, tag_match, date)
    if sort == "popular_safe":
        return (bookmarks * 3 + views, bookmarks, tag_match, date)
    if sort == "tag_match":
        return (tag_match, bookmarks, views, date)
    return (tag_match, bookmarks * 2 + views, date)


async def fetch_json(url: str, params: dict[str, Any] | None = None) -> Any:
    async with aiohttp.ClientSession(timeout=PIXIV_TIMEOUT, headers=REQUEST_HEADERS, trust_env=PIXIV_USE_SYSTEM_PROXY) as session:
        async with session.get(url, params=params) as resp:
            text = await resp.text()
            if resp.status >= 400:
                raise RuntimeError(f"Pixiv HTTP {resp.status}: {text[:300]}")
            return json.loads(text)


async def enrich_candidate_details(candidates: list[dict[str, Any]], limit: int = PIXIV_DETAIL_ENRICH_LIMIT) -> None:
    semaphore = asyncio.Semaphore(max(1, PIXIV_DETAIL_ENRICH_CONCURRENCY))

    async def enrich(item: dict[str, Any]) -> None:
        async with semaphore:
            try:
                detail = await pixiv_detail(str(item.get("pid") or ""))
            except Exception:
                return
            item.update({key: value for key, value in detail.items() if value not in (None, "", [])})

    await asyncio.gather(*(enrich(item) for item in candidates[:max(0, limit)]))


def should_enrich_for_sort(sort: str, min_bookmarks: int) -> bool:
    return min_bookmarks > 0 or sort in {"popular_safe", "bookmark_desc"}


async def fetch_pixiv_search_page(tag: str, page: int) -> list[Any]:
    params = {
        "word": tag,
        "order": "date_d",
        "mode": "safe",
        "p": page,
        "s_mode": "s_tag_full",
        "type": "illust_and_ugoira",
        "lang": "zh",
        "ai_type": 1,
    }
    data = await fetch_json(f"{PIXIV_AJAX}/search/illustrations/{quote(tag)}", params)
    return extract_search_items(data)


async def pixiv_search_tag(tag: str, pages: int, sort: str, min_bookmarks: int = 0, alternate_tags: list[str] | None = None, required_terms: list[str] | None = None) -> list[dict[str, Any]]:
    sort = normalize_sort(sort)
    pages = limited_int(pages, 1, 1, MAX_COLLAGES)
    min_bookmarks = limited_int(min_bookmarks, 0, 0, 1_000_000)
    base_tags = list_arg([tag] + (alternate_tags or []))
    search_tags = expanded_search_tags(base_tags) or [tag]
    required = list_arg(required_terms)
    collected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for search_tag in search_tags:
        for page in range(1, pages + 1):
            items = await fetch_pixiv_search_page(search_tag, page)
            for raw in items:
                if not isinstance(raw, dict):
                    continue
                item = normalize_search_item(raw)
                if not item or item["pid"] in seen:
                    continue
                item.setdefault("matched_search_tag", search_tag)
                seen.add(item["pid"])
                collected.append(item)
    if required or should_enrich_for_sort(sort, min_bookmarks):
        await enrich_candidate_details(collected)
    if required:
        filtered_by_terms = [item for item in collected if matches_required_terms(item, required)]
        if filtered_by_terms:
            collected = filtered_by_terms
        else:
            for item in collected:
                item["required_terms_fallback"] = True
    if min_bookmarks > 0:
        filtered = [item for item in collected if int(item.get("bookmark_count") or 0) >= min_bookmarks]
        if filtered:
            collected = filtered
        else:
            for item in collected:
                item["min_bookmarks_fallback"] = True
    score_query = " ".join(base_tags + required)
    collected.sort(key=lambda item: search_score(item, score_query, sort), reverse=True)
    return collected[:pages * MAX_CANDIDATES_PER_COLLAGE]


def extract_search_items(data: Any) -> list[Any]:
    if not isinstance(data, dict):
        return []
    body = data.get("body")
    if not isinstance(body, dict):
        return []
    for path in (("illust", "data"), ("illustManga", "data"), ("data",), ("works",)):
        current: Any = body
        for key in path:
            current = current.get(key) if isinstance(current, dict) else None
        if isinstance(current, list):
            return current
    return []


async def pixiv_detail(pid: str) -> dict[str, Any]:
    data = await fetch_json(f"{PIXIV_AJAX}/illust/{quote(str(pid))}")
    body = data.get("body") if isinstance(data, dict) else None
    if not isinstance(body, dict):
        raise RuntimeError("Pixiv 详情响应结构异常")
    item = normalize_detail_item(body)
    if not item or not is_safe_item(body):
        raise RuntimeError("该 PID 对应作品被安全过滤规则拦截或不可用")
    return item


def normalize_detail_item(body: dict[str, Any]) -> dict[str, Any] | None:
    pid = str(body.get("illustId") or body.get("id") or "").strip()
    if not pid:
        return None
    urls = body.get("urls") if isinstance(body.get("urls"), dict) else {}
    tags = tag_names(body.get("tags")) or tag_names(body)
    user_id = str(body.get("userId") or "").strip()
    item = {
        "pid": pid,
        "title": clean_text(body.get("illustTitle") or body.get("title")),
        "description": clean_text(body.get("description") or body.get("caption"), 1200),
        "user_id": user_id,
        "user_name": clean_text(body.get("userName") or body.get("userAccount"), 80),
        "thumbnail_url": pick_url(urls.get("thumb_mini"), urls.get("small"), urls.get("regular"), body.get("url")),
        "full_url": pick_url(urls.get("original"), urls.get("regular"), urls.get("small")),
        "url": f"https://www.pixiv.net/artworks/{pid}",
        "tags": tags,
        "bookmark_count": numeric_score(body.get("bookmarkCount")),
        "view_count": numeric_score(body.get("viewCount")),
        "date": str(body.get("createDate") or body.get("uploadDate") or ""),
        "raw": body,
    }
    if not item["thumbnail_url"]:
        item["thumbnail_url"] = item["full_url"]
    return item if item["full_url"] else None


def purge_search_cache() -> None:
    now = time.time()
    for key in list(SEARCH_CACHE.keys()):
        if now - float(SEARCH_CACHE[key].get("time", 0)) > SEARCH_CACHE_TTL_SECONDS:
            SEARCH_CACHE.pop(key, None)


def store_search(candidates: list[dict[str, Any]], query: str) -> str:
    purge_search_cache()
    search_id = uuid.uuid4().hex[:8]
    for index, item in enumerate(candidates, start=1):
        item["candidate_number"] = index
    SEARCH_CACHE[search_id] = {"time": time.time(), "query": query, "candidates": candidates}
    return search_id


def cached_candidates(search_id: str) -> list[dict[str, Any]]:
    purge_search_cache()
    item = SEARCH_CACHE.get(str(search_id).strip())
    if not item:
        return []
    candidates = item.get("candidates")
    return candidates if isinstance(candidates, list) else []


def candidate_by_number(search_id: str, number: Any) -> dict[str, Any] | None:
    try:
        candidate_number = int(number)
    except (TypeError, ValueError):
        return None
    for item in cached_candidates(search_id):
        if int(item.get("candidate_number") or 0) == candidate_number:
            return item
    return None


async def download_url(url: str, target_dir: Path, prefix: str) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(url.split("?", 1)[0]).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        suffix = ".jpg"
    target = target_dir / f"{prefix}_{uuid.uuid4().hex}{suffix}"
    async with aiohttp.ClientSession(timeout=PIXIV_TIMEOUT, headers=IMAGE_HEADERS, trust_env=PIXIV_USE_SYSTEM_PROXY) as session:
        async with session.get(url) as resp:
            if resp.status >= 400:
                text = await resp.text()
                raise RuntimeError(f"图片下载失败 HTTP {resp.status}: {text[:200]}")
            target.write_bytes(await resp.read())
    return normalize_image_file(target)


def normalize_image_file(path: Path) -> Path:
    try:
        with Image.open(path) as img:
            if getattr(img, "is_animated", False):
                img.seek(0)
            converted = img.convert("RGBA") if img.mode in {"P", "LA"} else img.convert("RGB")
            target = path.with_suffix(".jpg")
            save_target = target if target != path else path.with_suffix(".normalized.jpg")
            converted.save(save_target, "JPEG", quality=92)
        if target == path:
            save_target.replace(path)
        else:
            path.unlink(missing_ok=True)
        return target
    except Exception:
        return path


async def download_thumbnail(item: dict[str, Any], target_dir: Path) -> Path | None:
    url = str(item.get("thumbnail_url") or "")
    if not url:
        return None
    try:
        return await download_url(url, target_dir, f"pixiv_thumb_{item.get('pid')}")
    except Exception:
        return None


async def download_full_image(item: dict[str, Any], target_dir: Path) -> Path:
    detail = await pixiv_detail(str(item.get("pid") or ""))
    item.update({key: value for key, value in detail.items() if value not in (None, "", [])})
    url = str(item.get("full_url") or "")
    if not url:
        raise RuntimeError("候选没有可下载图片 URL")
    return await download_url(url, target_dir, f"pixiv_{item.get('pid')}")


def metadata_text(item: dict[str, Any]) -> str:
    tags = [str(tag) for tag in item.get("tags", []) if str(tag).strip()]
    lines = [
        "Pixiv 图片详情已加入上下文：",
        f"PID: {item.get('pid') or '未知'}",
        f"标题: {item.get('title') or '无标题'}",
        f"作者: {item.get('user_name') or '未知'} (ID: {item.get('user_id') or '未知'})",
        f"链接: {item.get('url') or ''}",
        f"收藏数: {item.get('bookmark_count', 0)}",
        f"浏览数: {item.get('view_count', 0)}",
        f"发布时间: {item.get('date') or '未知'}",
        f"标签: {'、'.join(tags) if tags else '无'}",
        f"简介: {item.get('description') or '无'}",
    ]
    return "\n".join(lines)


def font(size: int) -> ImageFont.ImageFont:
    candidates = [
        os.getenv("PIXIV_COLLAGE_FONT", "").strip(),
        "C:/Windows/Fonts/YuGothR.ttc",
        "C:/Windows/Fonts/YuGothM.ttc",
        "C:/Windows/Fonts/YuGothB.ttc",
        "C:/Windows/Fonts/meiryo.ttc",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/msyhbd.ttc",
        "C:/Windows/Fonts/simsun.ttc",
        "C:/Windows/Fonts/msgothic.ttc",
        "C:/Windows/Fonts/NotoSansCJK-Regular.ttc",
        "arial.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for name in candidates:
        if not name:
            continue
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def fit_image(path: Path, size: int) -> Image.Image:
    with Image.open(path) as img:
        img = img.convert("RGB")
        return ImageOps.fit(img, (size, size), method=Image.Resampling.LANCZOS)


async def create_collages(candidates: list[dict[str, Any]], output_dir: Path, search_id: str) -> list[Path]:
    thumb_dir = output_dir / "pixiv_thumbs"
    collage_dir = output_dir / "pixiv_collages"
    collage_dir.mkdir(parents=True, exist_ok=True)
    thumb_paths = await asyncio.gather(*(download_thumbnail(item, thumb_dir) for item in candidates))
    usable: list[dict[str, Any]] = []
    for item, path in zip(candidates, thumb_paths):
        if path:
            item["thumbnail_path"] = str(path)
            usable.append(item)
    candidates[:] = usable
    result: list[Path] = []
    for page_index in range(MAX_COLLAGES):
        chunk = candidates[page_index * MAX_CANDIDATES_PER_COLLAGE:(page_index + 1) * MAX_CANDIDATES_PER_COLLAGE]
        if not chunk:
            break
        result.append(draw_collage(chunk, collage_dir / f"pixiv_{search_id}_{page_index + 1}.jpg", page_index + 1))
    return result


def draw_collage(items: list[dict[str, Any]], target: Path, page_number: int) -> Path:
    cell = 220
    label_h = 42
    cols = 5
    rows = 5
    margin = 14
    header_h = 46
    width = cols * cell + (cols + 1) * margin
    height = header_h + rows * (cell + label_h) + (rows + 1) * margin
    canvas = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(canvas)
    title_font = font(24)
    label_font = font(26)
    small_font = font(15)
    draw.text((margin, 10), f"Pixiv candidates page {page_number} - use candidate_number, not bot image index", fill=(20, 20, 20), font=title_font)
    for offset, item in enumerate(items):
        row, col = divmod(offset, cols)
        x = margin + col * (cell + margin)
        y = header_h + margin + row * (cell + label_h + margin)
        try:
            image = fit_image(Path(str(item["thumbnail_path"])), cell)
        except Exception:
            image = Image.new("RGB", (cell, cell), (230, 230, 230))
        canvas.paste(image, (x, y))
        number = int(item.get("candidate_number") or 0)
        badge = f"{number:02d}"
        draw.rectangle((x, y, x + 58, y + 36), fill=(0, 0, 0))
        draw.text((x + 7, y + 2), badge, fill=(255, 255, 255), font=label_font)
        label = clean_text(f"{item.get('title') or '无标题'} / {item.get('user_name') or item.get('user_id') or '未知作者'}", 26)
        draw.text((x, y + cell + 5), label, fill=(20, 20, 20), font=small_font)
    canvas.save(target, "JPEG", quality=92)
    return target


def add_images_to_runtime(items: list[tuple[Path, str]], runtime: dict[str, Any], ctx: dict[str, Any]) -> list[int | str]:
    add_image_context = ctx.get("add_tool_image_context")
    if not callable(add_image_context):
        return ["?" for _ in items]
    records = [add_image_context(runtime["event"], path, text) for path, text in items]
    images = runtime.setdefault("images", [])
    if not isinstance(images, list):
        return ["?" for _ in items]
    max_images = int(ctx.get("max_context_images", 10) or 10)
    for record in records:
        if record in images:
            images.remove(record)
    overflow = max(0, len(images) + len(records) - max_images)
    if overflow:
        del images[:overflow]
    images.extend(records)
    return [images.index(record) + 1 if record in images else "?" for record in records]


def add_image_to_runtime(path: Path, text: str, runtime: dict[str, Any], ctx: dict[str, Any]) -> int | str:
    indexes = add_images_to_runtime([(path, text)], runtime, ctx)
    return indexes[0] if indexes else "?"


def format_candidates(candidates: list[dict[str, Any]], limit: int = 25) -> list[str]:
    lines: list[str] = []
    for item in candidates[:limit]:
        number = int(item.get("candidate_number") or 0)
        tags = " / ".join(str(tag) for tag in item.get("tags", [])[:5])
        lines.append(f"{number:02d}. PID {item.get('pid')} | {item.get('title') or '无标题'} | {item.get('user_name') or item.get('user_id') or '未知作者'} | bookmarks={item.get('bookmark_count', 0)} | {tags}")
    return lines
