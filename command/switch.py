from __future__ import annotations

from typing import Any

import aiohttp


def parse_args(arg: str) -> tuple[str, str] | None:
    parts = arg.split(maxsplit=1)
    if len(parts) != 2:
        return None
    kind = parts[0].lower()
    value = parts[1].strip()
    if kind not in {"llm", "image", "prompt", "photo"} or not value:
        return None
    return kind, value


def api_base(url: str) -> str:
    value = url.rstrip("/")
    for suffix in ("/v1/chat/completions", "/v1/responses", "/v1/images/edits", "/v1/images/generations"):
        if value.endswith(suffix):
            return value.removesuffix(suffix)
    return value


async def fetch_models(config: dict[str, str]) -> tuple[list[str], str]:
    url = config.get("url", "")
    if not url:
        return [], "未配置 URL"
    headers = {"Authorization": f"Bearer {config.get('key', '')}"} if config.get("key") else {}
    models_url = api_base(url) + "/v1/models"
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            async with session.get(models_url) as resp:
                body = await resp.text()
                if resp.status >= 400:
                    return [], f"{models_url} 返回 HTTP {resp.status}: {body[:500]}"
                try:
                    data = await resp.json(content_type=None)
                except Exception as exc:
                    return [], f"{models_url} 返回非 JSON 响应: {type(exc).__name__}: {exc}; body={body[:500]}"
    except Exception as exc:
        return [], f"请求 {models_url} 失败: {type(exc).__name__}: {exc}"
    names: list[str] = []
    if isinstance(data, dict):
        items = data.get("data")
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    name = item.get("id") or item.get("name")
                    if name:
                        names.append(str(name))
        for key in ("models", "result"):
            value = data.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        name = item.get("id") or item.get("name")
                        if name:
                            names.append(str(name))
                    elif isinstance(item, str):
                        names.append(item)
    names = sorted(set(names))
    if names:
        return names, ""
    return [], f"{models_url} 未解析到模型列表，响应：{str(data)[:500]}"


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    ctx["reload_runtime_files"]()
    if not ctx["is_admin_event"](event):
        await ctx["reply"](event, "你没有权限使用切换指令。")
        return
    parsed = parse_args(arg)
    if parsed is None:
        await ctx["reply"](event, "用法：/switch llm <modelname>、/switch image <modelname>、/switch prompt <编号> 或 /switch photo true|false")
        return
    kind, value = parsed
    if kind == "photo":
        normalized = value.lower()
        if normalized not in {"true", "false", "1", "0", "on", "off", "yes", "no"}:
            await ctx["reply"](event, "用法：/switch photo true|false")
            return
        enabled = normalized in {"true", "1", "on", "yes"}
        ctx["set_photo_enabled"](enabled)
        ctx["clear_contexts"]()
        await ctx["reply"](event, f"已{'开启' if enabled else '关闭'}图片输入。已清空暂存上下文。")
        return
    if kind == "prompt":
        prompt_configs = ctx["get_prompt_configs"]()
        if value not in prompt_configs:
            available = sorted(str(key) for key in prompt_configs.keys())
            suffix = f"可用编号：{', '.join(available)}" if available else "当前没有可用 prompt 配置。"
            await ctx["reply"](event, f"没有找到 prompt #{value}。{suffix}")
            return
        ctx["set_active_prompt"](value)
        name = prompt_configs.get(value, {}).get("name") or value
        await ctx["reply"](event, f"已切换 prompt：#{value} {name}。")
        return

    model = value
    configs = ctx["api_configs"].get(kind, [])
    if not configs:
        await ctx["reply"](event, f"没有配置 {kind} API。")
        return

    all_models: dict[str, list[str]] = {}
    errors: dict[str, str] = {}
    for config in configs:
        models, error = await fetch_models(config)
        all_models[config["index"]] = models
        if error:
            errors[config["index"]] = error
        if model in models:
            ctx["set_active_runtime"](kind, config["index"], model)
            await ctx["reply"](event, f"已切换 {kind}：API #{config['index']}，模型 {model}。已清空暂存上下文。")
            ctx["clear_contexts"]()
            return

    available = sorted({name for names in all_models.values() for name in names})
    if available:
        detail = "；".join(f"API #{index}: {error}" for index, error in errors.items())
        suffix = f"\n获取模型时的错误：{detail}" if detail else ""
        await ctx["reply"](event, f"没有找到模型 {model}。当前可用模型：{', '.join(available)}{suffix}")
        return
    detail = "；".join(f"API #{index}: {error}" for index, error in errors.items())
    suffix = f"错误详情：{detail}" if detail else "没有返回具体错误。"
    await ctx["reply"](event, f"没有从任何 {kind} API 获取到可用模型，无法切换到 {model}。{suffix}")


COMMAND = {
    "name": "/switch",
    "usage": "/switch llm/image <modelname>、/switch prompt <编号> 或 /switch photo true|false",
    "description": "仅所有者可用：切换当前使用的 LLM、图片 API、prompt 或图片输入开关。",
    "handler": handler,
}
