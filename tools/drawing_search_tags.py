from __future__ import annotations

import json
from typing import Any

from _danbooru_tags import (
    CATEGORY_NAMES,
    DanbooruTagError,
    query_danbooru_tags,
)


TOOL_DESCRIPTION = "为 Drawing Gateway 的本地二次元纯文生图查询 Danbooru 规范 tag。调用前先把用户自然语言拆成外观、服装、动作、场景、构图和光照等短英文或日文概念，再把这些概念批量放入 queries；不要把整段中文原话直接当作一个查询。结果返回规范 tag、类别、作品量、别名命中和未匹配概念。需要扩展候选时，只能把本工具已返回的规范 tag 放入 related_tags 查询关联 tag；关联结果只是统计候选，必须按用户原意筛选，禁止因为高频而擅自加入矛盾、人体或无关标签。完成 tag 校正后，再调用 drawing_search_loras、drawing_prompt_suggestions 和 drawing_generate_image。"


def definition(ctx: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "drawing_search_tags",
            "description": TOOL_DESCRIPTION,
            "parameters": {
                "type": "object",
                "properties": {
                    "queries": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 8,
                        "uniqueItems": True,
                        "items": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 128,
                        },
                        "description": "从用户自然语言拆出的短英文或日文概念，例如 white hair、twintails、sitting、train station、rain、backlighting。一个元素只表达一个概念。",
                    },
                    "related_tags": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 3,
                        "uniqueItems": True,
                        "items": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 128,
                            "pattern": "^[^\\s,]+$",
                        },
                        "description": "需要查询关联候选的 Danbooru 规范 tag。只能使用本工具当前或最近一次查询返回的 tag，不得猜测。",
                    },
                    "categories": {
                        "type": "array",
                        "maxItems": 5,
                        "uniqueItems": True,
                        "items": {
                            "type": "string",
                            "enum": list(CATEGORY_NAMES),
                        },
                        "description": "可选的 autocomplete 类别过滤。省略时返回全部类别。",
                    },
                    "related_category": {
                        "type": "string",
                        "enum": list(CATEGORY_NAMES),
                        "default": "general",
                        "description": "关联 tag 的类别，绘图描述通常使用 general；角色名使用 character，作品名使用 copyright。",
                    },
                    "limit_per_query": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 8,
                        "default": 5,
                    },
                    "related_limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 12,
                        "default": 8,
                    },
                },
                "anyOf": [
                    {"required": ["queries"]},
                    {"required": ["related_tags"]},
                ],
                "additionalProperties": False,
            },
        },
    }


def info(ctx: dict[str, Any]) -> dict[str, str]:
    function = definition(ctx)["function"]
    return {
        "name": str(function["name"]),
        "description": str(function["description"]),
    }


def _text_list(
    value: Any,
    name: str,
    *,
    maximum_items: int,
    normalize_tag: bool = False,
) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{name} 必须是数组。")
    if not value:
        raise ValueError(f"{name} 不能为空数组。")
    if len(value) > maximum_items:
        raise ValueError(f"{name} 最多包含 {maximum_items} 项。")
    result = []
    seen = set()
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise ValueError(f"{name}[{index}] 必须是字符串。")
        cleaned = " ".join(item.replace("\x00", "").split())
        if normalize_tag:
            cleaned = cleaned.casefold().replace(" ", "_")
        if not cleaned:
            raise ValueError(f"{name}[{index}] 不能为空。")
        if len(cleaned) > 128:
            raise ValueError(f"{name}[{index}] 最长为 128 个字符。")
        if normalize_tag and any(
            character in cleaned for character in ",\r\n\t"
        ):
            raise ValueError(f"{name}[{index}] 不是有效的规范 tag。")
        key = cleaned.casefold()
        if key not in seen:
            result.append(cleaned)
            seen.add(key)
    return result


def _integer(
    value: Any,
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} 必须是整数。")
    if value < minimum or value > maximum:
        raise ValueError(f"{name} 必须在 {minimum} 到 {maximum} 之间。")
    return value


def _categories(value: Any) -> set[str]:
    if value is None:
        return set()
    raw = _text_list(value, "categories", maximum_items=5)
    categories = set(raw)
    invalid = categories - set(CATEGORY_NAMES)
    if invalid:
        raise ValueError(
            "categories 包含不支持的类别："
            + ", ".join(sorted(invalid))
            + "。"
        )
    return categories


async def execute(
    args: dict[str, Any],
    runtime: dict[str, Any],
    ctx: dict[str, Any],
) -> dict[str, Any]:
    try:
        queries = _text_list(
            args.get("queries"),
            "queries",
            maximum_items=8,
        )
        related_tags = _text_list(
            args.get("related_tags"),
            "related_tags",
            maximum_items=3,
            normalize_tag=True,
        )
        if not queries and not related_tags:
            raise ValueError(
                "queries 和 related_tags 至少需要提供一个。"
            )
        related_category = str(
            args.get("related_category") or "general"
        ).strip().casefold()
        if related_category not in CATEGORY_NAMES:
            raise ValueError(
                "related_category 只允许："
                + ", ".join(CATEGORY_NAMES)
                + "。"
            )
        result = await query_danbooru_tags(
            queries=queries,
            related_tags=related_tags,
            limit_per_query=_integer(
                args.get("limit_per_query"),
                "limit_per_query",
                default=5,
                minimum=1,
                maximum=8,
            ),
            related_limit=_integer(
                args.get("related_limit"),
                "related_limit",
                default=8,
                minimum=1,
                maximum=12,
            ),
            categories=_categories(args.get("categories")),
            related_category=related_category,
        )
        return {
            "ok": True,
            "content": json.dumps(
                result,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        }
    except Exception as exc:
        if isinstance(exc, DanbooruTagError):
            detail = exc.public_message
        elif isinstance(exc, ValueError):
            detail = str(exc)
        else:
            detail = f"内部错误（{type(exc).__name__}）"
        logger = ctx.get("log") if isinstance(ctx, dict) else None
        if callable(logger):
            logger(f"Danbooru tag query failed: {type(exc).__name__}")
        return {
            "ok": False,
            "content": f"查询 Danbooru tag 失败：{detail}",
        }
