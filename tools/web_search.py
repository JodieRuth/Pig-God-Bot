from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import urlencode

import aiohttp


DEFAULT_SEARXNG_INSTANCES = [
    "https://search.inetol.net",
    "https://searx.tiekoetter.com",
    "https://search.sapti.me",
]
MAX_RESULTS = 8
TOOL_DESCRIPTION = "根据用户问题搜索互联网，返回候选网页列表。适用于用户没有提供明确 URL、需要查询资料、查找官网、查找文档、查询近期信息、对开放性问题寻找来源时。此工具只返回搜索结果摘要，不读取完整网页正文；如果需要基于网页内容回答，应继续调用 web_fetch 读取具体 URL。公共 SearXNG 实例稳定性不保证，若搜索失败应向用户说明。"


def definition(ctx: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": TOOL_DESCRIPTION,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词。应由 LLM 根据用户问题改写成适合搜索引擎的简洁查询词。",
                    },
                    "count": {
                        "type": "integer",
                        "description": "返回结果数量，默认 5，最多 8。",
                    },
                    "language": {
                        "type": "string",
                        "description": "搜索语言，默认 zh-CN；英文资料可用 en。",
                    },
                },
                "required": ["query"],
            },
        },
    }


def info(ctx: dict[str, Any]) -> dict[str, str]:
    item = definition(ctx).get("function", {})
    return {
        "name": str(item.get("name") or "web_search"),
        "description": str(item.get("description") or ""),
    }


def configured_instances() -> list[str]:
    raw = os.getenv("SEARXNG_URLS") or os.getenv("SEARXNG_URL") or ""
    values = [item.strip().rstrip("/") for item in raw.split(",") if item.strip()]
    if values:
        return values
    return DEFAULT_SEARXNG_INSTANCES[:]


def parse_count(value: Any) -> int:
    try:
        count = int(value or 5)
    except (TypeError, ValueError):
        count = 5
    return max(1, min(count, MAX_RESULTS))


def format_result_item(index: int, item: dict[str, Any]) -> list[str]:
    title = str(item.get("title") or "").strip() or "无标题"
    url = str(item.get("url") or "").strip()
    content = str(item.get("content") or "").strip() or "无摘要"
    engines = item.get("engines") or item.get("engine") or "SearXNG"
    if isinstance(engines, list):
        engine_text = ", ".join(str(engine) for engine in engines if str(engine).strip()) or "SearXNG"
    else:
        engine_text = str(engines).strip() or "SearXNG"
    return [
        f"{index}. {title}",
        f"URL: {url}",
        f"摘要: {content}",
        f"来源: {engine_text}",
        "",
    ]


async def search_instance(instance: str, query: str, language: str) -> dict[str, Any]:
    params = urlencode({
        "q": query,
        "format": "json",
        "language": language or "zh-CN",
        "safesearch": 1,
    })
    url = f"{instance.rstrip('/')}/search?{params}"
    timeout = aiohttp.ClientTimeout(total=25)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}) as resp:
            text = await resp.text(errors="replace")
            if resp.status >= 400:
                raise RuntimeError(f"HTTP {resp.status}: {text[:300]}")
            try:
                return json.loads(text)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"返回内容不是 JSON: {text[:300]}") from exc


async def execute(args: dict[str, Any], runtime: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not query:
        return {"ok": False, "content": "搜索失败：缺少 query。"}

    count = parse_count(args.get("count"))
    language = str(args.get("language") or "zh-CN").strip() or "zh-CN"
    errors: list[str] = []
    data: dict[str, Any] | None = None
    used_instance = ""

    for instance in configured_instances():
        try:
            data = await search_instance(instance, query, language)
            used_instance = instance
            break
        except Exception as exc:
            errors.append(f"{instance}: {ctx['exception_detail'](exc)}")

    if data is None:
        detail = "；".join(errors[-3:])
        return {"ok": False, "content": f"搜索失败：公共 SearXNG 实例暂不可用。{detail}"}

    raw_results = data.get("results") if isinstance(data, dict) else []
    if not isinstance(raw_results, list) or not raw_results:
        return {"ok": True, "content": f"搜索完成，但没有找到结果。\n查询: {query}\n使用实例: {used_instance}"}

    lines = [
        "搜索成功",
        f"查询: {query}",
        f"使用实例: {used_instance}",
        "",
    ]
    seen_urls: set[str] = set()
    used = 0

    for item in raw_results:
        if used >= count:
            break
        if not isinstance(item, dict):
            continue
        result_url = str(item.get("url") or "").strip()
        if not result_url or result_url in seen_urls:
            continue
        seen_urls.add(result_url)
        used += 1
        lines.extend(format_result_item(used, item))

    if used == 0:
        return {"ok": True, "content": f"搜索完成，但没有可用结果。\n查询: {query}\n使用实例: {used_instance}"}

    lines.insert(3, f"结果数量: {used}")
    lines.append("如需基于某个网页正文回答，应继续调用 web_fetch 读取对应 URL。")
    return {"ok": True, "content": "\n".join(lines)}
