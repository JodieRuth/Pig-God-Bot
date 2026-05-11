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


def models_url_for_request(url: str) -> str:
    value = url.rstrip("/")
    for suffix in ("/chat/completions", "/responses", "/images/edits", "/images/generations"):
        if value.endswith(suffix):
            return value.removesuffix(suffix) + "/models"
    return value + "/models"


async def fetch_models(config: dict[str, str]) -> tuple[list[str], str]:
    url = config.get("url", "")
    if not url:
        return [], "未配置 URL"
    headers = {"Authorization": f"Bearer {config.get('key', '')}"} if config.get("key") else {}
    models_url = models_url_for_request(url)
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
        await ctx["reply"](event, "用法：/switch llm <modelname[#N]>、/switch image <modelname[#N]>、/switch prompt <编号> 或 /switch photo true|false")
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
        ctx["set_active_prompt"](value, ctx["scope_key"](event))
        name = prompt_configs.get(value, {}).get("name") or value
        await ctx["reply"](event, f"已切换 prompt：#{value} {name}。")
        return

    model = value
    configs = ctx["api_configs"].get(kind, [])
    if not configs:
        await ctx["reply"](event, f"没有配置 {kind} API。")
        return

    target_pos: int | None = None
    base_model = model
    disabled = ctx["disabled_llm_models"] if kind == "llm" else ctx["disabled_image_models"]
    if "#" in model:
        base_model, _, num_part = model.rpartition("#")
        if num_part.isdigit():
            target_pos = int(num_part)
            if target_pos < 0 or target_pos >= len(configs):
                await ctx["reply"](event, f"配置位置 #{target_pos} 不存在，当前 {kind} 配置共 {len(configs)} 个（位置 0 到 {len(configs) - 1}）。")
                return
        else:
            await ctx["reply"](event, f"模型名 {model} 格式无效，# 后应为数字。")
            return

    if target_pos is not None:
        config = configs[target_pos]
        models, error = await fetch_models(config)
        models = [m for m in models if m.lower() not in disabled]
        if error:
            await ctx["reply"](event, f"获取 #{target_pos} 模型列表失败：{error}")
            return
        if base_model not in models:
            available = sorted(models)
            await ctx["reply"](event, f"#{target_pos} 中没有模型 {base_model}。可用：{', '.join(available) if available else '无'}")
            return
        ctx["set_active_runtime"](kind, config["index"], base_model)
        await ctx["reply"](event, f"已切换 {kind}：API #{config['index']}，模型 {base_model}。已清空暂存上下文。")
        ctx["clear_contexts"]()
        return

    all_models: dict[str, list[str]] = {}
    errors: dict[str, str] = {}
    for config in configs:
        models, error = await fetch_models(config)
        models = [m for m in models if m.lower() not in disabled]
        all_models[config["index"]] = models
        if error:
            errors[config["index"]] = error
        if base_model in models:
            ctx["set_active_runtime"](kind, config["index"], base_model)
            await ctx["reply"](event, f"已切换 {kind}：API #{config['index']}，模型 {base_model}。已清空暂存上下文。")
            ctx["clear_contexts"]()
            return

    model_positions: dict[str, list[int]] = {}
    for i, config in enumerate(configs):
        for m in all_models.get(config["index"], []):
            model_positions.setdefault(m, []).append(i)
    available: list[str] = []
    for m in sorted(model_positions.keys()):
        positions = model_positions[m]
        if len(positions) > 1:
            for p in positions:
                available.append(f"{m}#{p}")
        else:
            available.append(m)
    if available:
        detail = "；".join(f"API #{index}: {error}" for index, error in errors.items())
        suffix = f"\n获取模型时的错误：{detail}" if detail else ""
        await ctx["reply"](event, f"没有找到模型 {base_model}。当前可用模型：{', '.join(available)}{suffix}")
        return
    detail = "；".join(f"API #{index}: {error}" for index, error in errors.items())
    suffix = f"错误详情：{detail}" if detail else "没有返回具体错误。"
    await ctx["reply"](event, f"没有从任何 {kind} API 获取到可用模型，无法切换到 {base_model}。{suffix}")


COMMAND = {
    "name": "/switch",
    "usage": "/switch llm/image <modelname[#N]>、/switch prompt <编号> 或 /switch photo true|false",
    "description": "仅所有者可用：切换当前使用的 LLM、图片 API、prompt 或图片输入开关。",
    "handler": handler,
}
