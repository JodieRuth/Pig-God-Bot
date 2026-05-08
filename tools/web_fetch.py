from __future__ import annotations

import ipaddress
import socket
from typing import Any
from urllib.parse import urlparse

from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig


MAX_URL_LENGTH = 2000
MAX_CONTENT_CHARS = 30000
TOOL_DESCRIPTION = "读取用户明确提供的公开网页 URL，并使用 Crawl4AI 返回清洗后的 Markdown 正文。适用于网页总结、网页问答、资料整理、文档阅读、提取网页中的具体信息。当用户提供 URL，或 web_search 返回结果中需要深入阅读某个 URL 时调用。不能用于搜索互联网，不能访问需要登录、验证码、私有权限或复杂交互的网站。"
CRAWL4AI_PAGE_TIMEOUT_MS = 30000
CRAWL4AI_WORD_COUNT_THRESHOLD = 10


def definition(ctx: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": TOOL_DESCRIPTION,
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "需要读取的公开网页 URL，必须以 http:// 或 https:// 开头。",
                    },
                    "reason": {
                        "type": "string",
                        "description": "为什么要读取该网页，例如总结、回答问题、提取配置、核对事实。可省略。",
                    },
                },
                "required": ["url"],
            },
        },
    }


def info(ctx: dict[str, Any]) -> dict[str, str]:
    item = definition(ctx).get("function", {})
    return {
        "name": str(item.get("name") or "web_fetch"),
        "description": str(item.get("description") or ""),
    }


def is_blocked_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified


def is_blocked_hostname(hostname: str) -> bool:
    lowered = hostname.lower().strip(".")
    if not lowered or lowered == "localhost":
        return True
    if is_blocked_ip(lowered):
        return True
    try:
        infos = socket.getaddrinfo(lowered, None)
    except socket.gaierror:
        return False
    for info in infos:
        address = info[4][0]
        if is_blocked_ip(address):
            return True
    return False


def validate_url(raw_url: str) -> str:
    url = raw_url.strip()
    if len(url) > MAX_URL_LENGTH:
        raise ValueError("URL 过长")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("URL 必须以 http:// 或 https:// 开头")
    if not parsed.hostname:
        raise ValueError("URL 缺少主机名")
    if parsed.username or parsed.password:
        raise ValueError("URL 不允许包含用户名或密码")
    if is_blocked_hostname(parsed.hostname):
        raise ValueError("不允许访问本地、内网或保留地址")
    return url


async def fetch_with_crawl4ai(url: str) -> tuple[str, int | None, str]:
    browser_config = BrowserConfig(headless=True, verbose=False)
    run_config = CrawlerRunConfig(
        page_timeout=CRAWL4AI_PAGE_TIMEOUT_MS,
        word_count_threshold=CRAWL4AI_WORD_COUNT_THRESHOLD,
    )
    async with AsyncWebCrawler(config=browser_config) as crawler:
        result = await crawler.arun(url=url, config=run_config)

    success = bool(getattr(result, "success", False))
    status_code = getattr(result, "status_code", None)
    error_message = str(getattr(result, "error_message", "") or "").strip()
    markdown = str(getattr(result, "markdown", "") or "").strip()

    if not success:
        raise RuntimeError(error_message or "Crawl4AI 抓取失败")
    if isinstance(status_code, int) and status_code in {401, 403}:
        raise RuntimeError(f"目标站拒绝访问：HTTP {status_code}")
    if isinstance(status_code, int) and status_code >= 400:
        raise RuntimeError(f"目标站返回 HTTP {status_code}")
    if not markdown:
        raise RuntimeError("Crawl4AI 返回 Markdown 为空")
    return markdown, status_code if isinstance(status_code, int) else None, error_message


async def execute(args: dict[str, Any], runtime: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    raw_url = str(args.get("url") or "").strip()
    reason = str(args.get("reason") or "").strip()
    if not raw_url:
        return {"ok": False, "content": "网页读取失败：缺少 url。"}

    try:
        url = validate_url(raw_url)
        content, status_code, crawl_error = await fetch_with_crawl4ai(url)
    except Exception as exc:
        return {"ok": False, "content": f"网页读取失败：{ctx['exception_detail'](exc)}"}

    original_length = len(content)
    truncated = False
    if len(content) > MAX_CONTENT_CHARS:
        content = content[:MAX_CONTENT_CHARS]
        truncated = True

    lines = [
        "网页读取成功",
        f"URL: {url}",
        "来源: Crawl4AI",
        f"HTTP 状态: {status_code if status_code is not None else '未知'}",
        f"内容长度: {original_length} 字符",
    ]
    if crawl_error:
        lines.append(f"Crawl4AI 提示: {crawl_error}")
    if reason:
        lines.append(f"读取目的: {reason}")
    if truncated:
        lines.append("内容因过长已截断，回答时请说明可能只基于部分网页内容。")
    lines.extend([
        "",
        "以下是网页 Markdown 正文：",
        "---",
        content,
    ])
    return {"ok": True, "content": "\n".join(lines)}
