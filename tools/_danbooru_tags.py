from __future__ import annotations

import asyncio
import copy
import math
import os
import socket
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import aiohttp


CATEGORY_NAMES = ("general", "artist", "copyright", "character", "meta")
CATEGORY_BY_ID = {
    0: "general",
    1: "artist",
    3: "copyright",
    4: "character",
    5: "meta",
}
RETRYABLE_STATUSES = {408, 425, 429, 500, 502, 503, 504}
TAG_CACHE: dict[tuple[Any, ...], tuple[float, Any]] = {}


@dataclass(frozen=True)
class DanbooruTagConfig:
    base_url: str
    timeout_seconds: float
    cache_ttl_seconds: float
    retry_attempts: int
    force_ipv4: bool
    login: str
    api_key: str


class DanbooruTagError(RuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.public_message = message


def _configured_number(
    name: str,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise DanbooruTagError(f"{name} 必须是数字。") from exc
    if not math.isfinite(value) or value < minimum or value > maximum:
        raise DanbooruTagError(
            f"{name} 必须在 {minimum:g} 到 {maximum:g} 之间。"
        )
    return value


def load_config() -> DanbooruTagConfig:
    base_url = (
        os.getenv("DANBOORU_BASE_URL", "https://danbooru.donmai.us")
        .strip()
        .rstrip("/")
    )
    try:
        parsed = urlsplit(base_url)
        _ = parsed.port
    except ValueError as exc:
        raise DanbooruTagError(
            "DANBOORU_BASE_URL 不是有效的 HTTP/HTTPS 地址。"
        ) from exc
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise DanbooruTagError(
            "DANBOORU_BASE_URL 必须是不含凭据、查询参数和片段的 HTTP/HTTPS 地址。"
        )
    login = os.getenv("DANBOORU_LOGIN", "").strip()
    api_key = os.getenv("DANBOORU_API_KEY", "").strip()
    if bool(login) != bool(api_key):
        raise DanbooruTagError(
            "DANBOORU_LOGIN 和 DANBOORU_API_KEY 必须同时配置。"
        )
    retry_attempts = int(
        _configured_number(
            "DANBOORU_RETRY_ATTEMPTS",
            2,
            1,
            4,
        )
    )
    return DanbooruTagConfig(
        base_url=base_url,
        timeout_seconds=_configured_number(
            "DANBOORU_REQUEST_TIMEOUT_SECONDS",
            20,
            1,
            120,
        ),
        cache_ttl_seconds=_configured_number(
            "DANBOORU_CACHE_TTL_SECONDS",
            600,
            0,
            86400,
        ),
        retry_attempts=retry_attempts,
        force_ipv4=os.getenv("DANBOORU_FORCE_IPV4", "0").strip() == "1",
        login=login,
        api_key=api_key,
    )


def clear_tag_cache() -> None:
    TAG_CACHE.clear()


def _cache_key(
    config: DanbooruTagConfig,
    path: str,
    params: dict[str, Any],
) -> tuple[Any, ...]:
    return (
        config.base_url,
        path,
        tuple(sorted((str(key), str(value)) for key, value in params.items())),
    )


def _cached_value(
    key: tuple[Any, ...],
    ttl_seconds: float,
) -> Any | None:
    if ttl_seconds <= 0:
        return None
    cached = TAG_CACHE.get(key)
    if cached is None:
        return None
    created_at, value = cached
    if time.monotonic() - created_at > ttl_seconds:
        TAG_CACHE.pop(key, None)
        return None
    return copy.deepcopy(value)


def _store_cached_value(
    key: tuple[Any, ...],
    value: Any,
    ttl_seconds: float,
) -> None:
    if ttl_seconds <= 0:
        return
    TAG_CACHE[key] = (time.monotonic(), copy.deepcopy(value))


def _clean_text(value: Any, maximum: int = 256) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.replace("\x00", "").split())[:maximum]


def _safe_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _safe_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return round(number, 6) if math.isfinite(number) else None


def _category_name(value: Any) -> str:
    category_id = _safe_int(value)
    return CATEGORY_BY_ID.get(category_id, "unknown")


class DanbooruTagClient:
    def __init__(self, config: DanbooruTagConfig) -> None:
        self.config = config
        self.session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> "DanbooruTagClient":
        family = socket.AF_INET if self.config.force_ipv4 else socket.AF_UNSPEC
        connector = aiohttp.TCPConnector(
            family=family,
            ttl_dns_cache=300,
            enable_cleanup_closed=True,
        )
        auth = (
            aiohttp.BasicAuth(self.config.login, self.config.api_key)
            if self.config.login
            else None
        )
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.config.timeout_seconds),
            headers={
                "Accept": "application/json",
                "User-Agent": "local-onebot-bot/1.0",
            },
            auth=auth,
            trust_env=True,
            connector=connector,
        )
        return self

    async def __aexit__(
        self,
        exc_type: Any,
        exc: Any,
        traceback: Any,
    ) -> None:
        if self.session is not None:
            await self.session.close()

    async def get_json(
        self,
        path: str,
        params: dict[str, Any],
        *,
        allow_not_found: bool = False,
    ) -> Any:
        key = _cache_key(self.config, path, params)
        cached = _cached_value(key, self.config.cache_ttl_seconds)
        if cached is not None:
            return cached
        if self.session is None:
            raise RuntimeError("Danbooru client is not open")
        url = f"{self.config.base_url}/{path.lstrip('/')}"
        for attempt in range(1, self.config.retry_attempts + 1):
            try:
                async with self.session.get(url, params=params) as response:
                    if response.status == 404 and allow_not_found:
                        return None
                    if response.status >= 400:
                        await response.read()
                        if (
                            response.status in RETRYABLE_STATUSES
                            and attempt < self.config.retry_attempts
                        ):
                            await asyncio.sleep(min(2 ** (attempt - 1), 4))
                            continue
                        if response.status in {401, 403}:
                            raise DanbooruTagError(
                                "Danbooru 鉴权失败，请检查登录名和 API Key。"
                            )
                        if response.status == 429:
                            raise DanbooruTagError(
                                "Danbooru 请求过于频繁，请稍后重试。"
                            )
                        raise DanbooruTagError(
                            f"Danbooru 请求失败（HTTP {response.status}）。"
                        )
                    try:
                        payload = await response.json(content_type=None)
                    except (ValueError, TypeError) as exc:
                        raise DanbooruTagError(
                            "Danbooru 返回了无法解析的 JSON。"
                        ) from exc
                    _store_cached_value(
                        key,
                        payload,
                        self.config.cache_ttl_seconds,
                    )
                    return payload
            except DanbooruTagError:
                raise
            except (
                aiohttp.ClientConnectionError,
                aiohttp.ServerTimeoutError,
                asyncio.TimeoutError,
                OSError,
            ) as exc:
                if attempt < self.config.retry_attempts:
                    await asyncio.sleep(min(2 ** (attempt - 1), 4))
                    continue
                raise DanbooruTagError(
                    "无法连接 Danbooru，请检查系统代理、DANBOORU_BASE_URL 或网络连接。"
                ) from exc
            except aiohttp.ClientError as exc:
                raise DanbooruTagError(
                    f"Danbooru HTTP 请求失败（{type(exc).__name__}）。"
                ) from exc
        raise DanbooruTagError("Danbooru 查询未能完成。")

    async def search(
        self,
        query: str,
        limit: int,
        categories: set[str],
    ) -> dict[str, Any]:
        request_limit = min(20, max(limit, limit * 3 if categories else limit))
        payload = await self.get_json(
            "/autocomplete.json",
            {
                "search[query]": query,
                "search[type]": "tag_query",
                "limit": request_limit,
            },
        )
        raw_items = payload if isinstance(payload, list) else []
        matches = []
        seen: set[str] = set()
        normalized_query = query.casefold().replace(" ", "_")
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            raw_tag = item.get("tag")
            tag = raw_tag if isinstance(raw_tag, dict) else {}
            name = _clean_text(item.get("value") or tag.get("name"), 256)
            if not name or name in seen:
                continue
            category = _category_name(item.get("category", tag.get("category")))
            if categories and category not in categories:
                continue
            antecedent = _clean_text(item.get("antecedent"), 256)
            if name.casefold() == normalized_query:
                matched_by = "exact"
            elif antecedent:
                matched_by = "alias"
            else:
                matched_by = "autocomplete"
            matches.append(
                {
                    "tag": name,
                    "label": _clean_text(item.get("label"), 256) or name,
                    "category": category,
                    "post_count": _safe_int(
                        item.get("post_count", tag.get("post_count"))
                    )
                    or 0,
                    "deprecated": bool(tag.get("is_deprecated", False)),
                    "matched_by": matched_by,
                    "alias": antecedent or None,
                }
            )
            seen.add(name)
            if len(matches) >= limit:
                break
        return {
            "query": query,
            "normalized_query": normalized_query,
            "matches": matches,
        }

    async def related(
        self,
        tag_name: str,
        limit: int,
        category: str,
    ) -> dict[str, Any]:
        payload = await self.get_json(
            "/related_tag.json",
            {
                "query": tag_name,
                "category": category,
                "limit": min(20, limit + 1),
            },
            allow_not_found=True,
        )
        if not isinstance(payload, dict):
            return {"tag": tag_name, "category": category, "matches": []}
        raw_items = payload.get("related_tags")
        items = raw_items if isinstance(raw_items, list) else []
        matches = []
        seen = {tag_name.casefold()}
        for item in items:
            if not isinstance(item, dict):
                continue
            raw_tag = item.get("tag")
            tag = raw_tag if isinstance(raw_tag, dict) else {}
            name = _clean_text(tag.get("name"), 256)
            if not name or name.casefold() in seen:
                continue
            matches.append(
                {
                    "tag": name,
                    "category": _category_name(tag.get("category")),
                    "post_count": _safe_int(tag.get("post_count")) or 0,
                    "frequency": _safe_float(item.get("frequency")),
                    "cosine_similarity": _safe_float(
                        item.get("cosine_similarity")
                    ),
                    "jaccard_similarity": _safe_float(
                        item.get("jaccard_similarity")
                    ),
                }
            )
            seen.add(name.casefold())
            if len(matches) >= limit:
                break
        return {
            "tag": _clean_text(payload.get("query"), 256) or tag_name,
            "category": category,
            "matches": matches,
        }


async def query_danbooru_tags(
    queries: list[str],
    related_tags: list[str],
    limit_per_query: int,
    related_limit: int,
    categories: set[str],
    related_category: str,
) -> dict[str, Any]:
    config = load_config()
    searches = []
    related = []
    async with DanbooruTagClient(config) as client:
        for query in queries:
            searches.append(
                await client.search(
                    query,
                    limit_per_query,
                    categories,
                )
            )
        for tag_name in related_tags:
            related.append(
                await client.related(
                    tag_name,
                    related_limit,
                    related_category,
                )
            )
    return {
        "source": "danbooru",
        "searches": searches,
        "related": related,
        "unmatched_queries": [
            item["query"] for item in searches if not item["matches"]
        ],
    }
