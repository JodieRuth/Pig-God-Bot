from __future__ import annotations

import ipaddress
import socket
from typing import Any
from urllib.parse import quote, urlparse

import aiohttp


MAX_URL_LENGTH = 2000
MAX_CONTENT_CHARS = 30000
TOOL_DESCRIPTION = "读取用户明确提供的公开网页 URL，并返回清洗后的 Markdown 正文。适用于网页总结、网页问答、资料整理、文档阅读、提取网页中的具体信息。当用户提供 URL，或 web_search 返回结果中需要深入阅读某个 URL 时调用。不能用于搜索互联网，不能访问需要登录、验证码、私有权限或复杂交互的网站。"


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


def jina_reader_url(url: str) -> str:
    return "https://r.jina.ai/http://" + quote(url, safe="")


async def fetch_with_jina(url: str) -> str:
    timeout = aiohttp.ClientTimeout(total=45)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(jina_reader_url(url), headers={"User-Agent": "Mozilla/5.0"}) as resp:
            text = await resp.text(errors="replace")
            if resp.status >= 400:
                raise RuntimeError(f"Jina Reader HTTP {resp.status}: {text[:300]}")
            text = text.strip()
            if not text:
                raise RuntimeError("Jina Reader 返回内容为空")
            return text


async def execute(args: dict[str, Any], runtime: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    raw_url = str(args.get("url") or "").strip()
    reason = str(args.get("reason") or "").strip()
    if not raw_url:
        return {"ok": False, "content": "网页读取失败：缺少 url。"}

    try:
        url = validate_url(raw_url)
        content = await fetch_with_jina(url)
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
        "来源: Jina Reader",
        f"内容长度: {original_length} 字符",
    ]
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
