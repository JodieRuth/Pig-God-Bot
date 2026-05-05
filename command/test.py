from __future__ import annotations

import json
import os
import time
from typing import Any

import aiohttp
import websockets


def api_base(url: str) -> str:
    value = url.rstrip("/")
    for suffix in ("/v1/chat/completions", "/api/paas/v4/chat/completions", "/v1/responses", "/v1/images/edits", "/v1/images/generations"):
        if value.endswith(suffix):
            return value.removesuffix(suffix)
    return value


def models_url_for_request(url: str) -> str:
    value = url.rstrip("/")
    for suffix in ("/chat/completions", "/responses", "/images/edits", "/images/generations"):
        if value.endswith(suffix):
            return value.removesuffix(suffix) + "/models"
    return value + "/models"


async def check_http(url: str, headers: dict[str, str]) -> tuple[str, str]:
    if not url:
        return "SKIP", "未配置"
    started = time.perf_counter()
    try:
        timeout = aiohttp.ClientTimeout(total=12)
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            async with session.get(url) as resp:
                cost = int((time.perf_counter() - started) * 1000)
                return "OK", f"HTTP {resp.status} {cost}ms"
    except Exception as exc:
        cost = int((time.perf_counter() - started) * 1000)
        return "FAIL", f"{type(exc).__name__}: {cost}ms"


async def check_ws(url: str, headers: dict[str, str]) -> tuple[str, str]:
    if not url:
        return "SKIP", "未配置"
    started = time.perf_counter()
    try:
        try:
            ws = await websockets.connect(url, additional_headers=headers)
        except TypeError:
            ws = await websockets.connect(url, extra_headers=headers)
        await ws.close()
        cost = int((time.perf_counter() - started) * 1000)
        return "OK", f"connected {cost}ms"
    except Exception as exc:
        cost = int((time.perf_counter() - started) * 1000)
        return "FAIL", f"{type(exc).__name__}: {cost}ms"


async def fetch_models(config: dict[str, str]) -> tuple[list[str], str]:
    url = config.get("url", "")
    if not url:
        return [], "未配置"
    headers = {"Authorization": f"Bearer {config.get('key', '')}"} if config.get("key") else {}
    models_url = models_url_for_request(url)
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            async with session.get(models_url) as resp:
                body = await resp.text()
                if resp.status >= 400:
                    return [], f"HTTP {resp.status}"
    except Exception as exc:
        return [], f"{type(exc).__name__}"
    names: list[str] = []
    try:
        body_obj = json.loads(body)
    except Exception:
        return [], "非 JSON 响应"
    if isinstance(body_obj, dict):
        data = body_obj.get("data")
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    name = item.get("id") or item.get("name")
                    if name:
                        names.append(str(name))
        for key in ("models", "result"):
            value = body_obj.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        name = item.get("id") or item.get("name")
                        if name:
                            names.append(str(name))
                    elif isinstance(item, str):
                        names.append(item)
    if names:
        return sorted(set(names)), ""
    return [], "未解析到模型列表"


async def check_chat(config: dict[str, str], model: str) -> tuple[str, str]:
    url = config.get("url", "")
    if not url:
        return "SKIP", "未配置"
    headers = {"Authorization": f"Bearer {config.get('key', '')}"} if config.get("key") else {}
    started = time.perf_counter()
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "你好"}],
        "temperature": 0,
        "max_tokens": 16,
    }
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            async with session.post(url, json=payload) as resp:
                body = await resp.json(content_type=None)
                cost = int((time.perf_counter() - started) * 1000)
                if resp.status >= 400:
                    return "FAIL", f"HTTP {resp.status} {cost}ms"
                choices = body.get("choices") if isinstance(body, dict) else None
                if isinstance(choices, list) and choices:
                    message = choices[0].get("message") if isinstance(choices[0], dict) else None
                    if isinstance(message, dict) and str(message.get("content") or "").strip():
                        return "OK", f"reply {cost}ms"
                return "FAIL", f"empty reply {cost}ms"
    except Exception as exc:
        cost = int((time.perf_counter() - started) * 1000)
        return "FAIL", f"{type(exc).__name__}: {cost}ms"


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    ctx["reload_runtime_files"]()
    if not ctx["is_admin_event"](event):
        await ctx["reply"](event, "你没有权限使用测试指令。")
        return

    onebot_http = os.getenv("ONEBOT_HTTP", "http://127.0.0.1:3000").rstrip("/")
    onebot_ws = os.getenv("ONEBOT_WS", "ws://127.0.0.1:3001")
    onebot_token = os.getenv("ONEBOT_TOKEN", "")
    bot_qq = os.getenv("BOT_QQ", "")
    bot_name = os.getenv("BOT_NAME", "")
    admin_users = os.getenv("ADMIN_USERS", "")
    openai_model = ctx["active_model"]("llm")
    image_model = ctx["active_model"]("image")

    headers_onebot = {"Authorization": f"Bearer {onebot_token}"} if onebot_token else {}
    llm_configs = ctx["api_configs"].get("llm", [])
    image_configs = ctx["api_configs"].get("image", [])
    llm_active = ctx["active_api_config"]("llm").get("index", "")
    image_active = ctx["active_api_config"]("image").get("index", "")
    prompt_configs = ctx["get_prompt_configs"]()
    prompt_active = ctx["active_prompt_id"]()

    tool_infos = ctx.get("tool_infos", [])
    plugins = ctx.get("plugins", {})

    console_log = ctx.get("console_log") or ctx.get("log")
    results = []

    def report(line: str = "") -> None:
        results.append(line)
        if callable(console_log):
            console_log(f"/test {line}" if line else "/test")

    report("运行参数：")
    report(f"BOT_QQ: {bot_qq or '未配置'}")
    report(f"BOT_NAME: {bot_name or '未配置'}")
    report(f"ADMIN_USERS: {admin_users or '未配置'}")
    report(f"OPENAI_MODEL: {openai_model or '未配置'}")
    report(f"IMAGE_MODEL: {image_model or '未配置'}")
    report(f"ONEBOT_TOKEN: {'已配置' if onebot_token else '未配置'}")
    report(f"ACTIVE_LLM_API_INDEX: #{llm_active or '无'}")
    report(f"ACTIVE_IMAGE_API_INDEX: #{image_active or '无'}")
    report(f"ACTIVE_PROMPT_ID: #{prompt_active or '无'}")
    report(f"LLM_API_COUNT: {len(llm_configs)} 当前 #{llm_active or '无'}")
    report(f"IMAGE_API_COUNT: {len(image_configs)} 当前 #{image_active or '无'}")
    report(f"PROMPT_CURRENT: #{prompt_active or '无'}")
    if prompt_configs:
        prompt_items = []
        for key in sorted(str(item) for item in prompt_configs.keys()):
            config = prompt_configs.get(key, {})
            name = config.get("name") if isinstance(config, dict) else ""
            marker = " 当前" if key == prompt_active else ""
            prompt_items.append(f"#{key}{marker}{f' {name}' if name else ''}")
        report(f"PROMPTS: {', '.join(prompt_items)}")
    else:
        report("PROMPTS: 未配置")
    report()
    report("连接检查：")
    onebot_http_status, onebot_http_detail = await check_http(onebot_http, headers_onebot)
    report(f"OneBot HTTP: {onebot_http_status} - {onebot_http_detail}")
    onebot_ws_status, onebot_ws_detail = await check_ws(onebot_ws, headers_onebot)
    report(f"OneBot WS: {onebot_ws_status} - {onebot_ws_detail}")

    if tool_infos:
        report()
        report("当前可用工具：")
        for item in tool_infos:
            name = str(item.get("name") or "").strip()
            if name:
                report(name)
    else:
        report()
        report("当前可用工具：无")

    if plugins:
        report()
        report("当前存在插件：")
        for name in sorted(str(item) for item in plugins.keys()):
            report(name)
    else:
        report()
        report("当前存在插件：无")
    report()

    all_models: set[str] = set()
    for config in llm_configs:
        models, models_error = await fetch_models(config)
        all_models.update(models)
        active = " 当前" if config.get("index") == llm_active else ""
        if not models:
            reason = f"models: {models_error}" if models_error else "models: 未获取到模型"
            report(f"LLM #{config.get('index')}{active}: FAIL - {reason}，跳过聊天测试，模型数 0")
            continue
        test_model = openai_model if openai_model in models else models[0]
        status, detail = await check_chat(config, test_model)
        report(f"LLM #{config.get('index')}{active}: {status} - {detail}，测试模型 {test_model}，模型数 {len(models)}")
    for config in image_configs:
        models, models_error = await fetch_models(config)
        all_models.update(models)
        active = " 当前" if config.get("index") == image_active else ""
        if not models:
            detail = models_error or "未获取到模型"
            report(f"Image #{config.get('index')}{active}: FAIL - {detail}")
            continue
        status = "OK"
        detail = f"models {len(models)}"
        report(f"Image #{config.get('index')}{active}: {status} - {detail}")

    if all_models:
        report()
        report("所有可用模型：")
        report(", ".join(sorted(all_models)))

    await ctx["reply"](event, "\n".join(results))


COMMAND = {
    "name": "/test",
    "usage": "/test",
    "description": "仅所有者可用：轮询所有远端接口、显示可用模型、当前工具列表和脱敏运行参数。",
    "handler": handler,
}
