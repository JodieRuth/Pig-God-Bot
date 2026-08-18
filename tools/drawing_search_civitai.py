from __future__ import annotations

from typing import Any

from _drawing_gateway import (
    boolean_value,
    failure_result,
    format_civitai_search,
    integer_value,
    request_json,
    string_value,
    success_result,
)


def definition(ctx: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "drawing_search_civitai",
            "description": "仅当 drawing_search_loras 的已安装目录没有所需 LoRA 时，通过 Drawing Gateway 搜索 Civitai，返回 model/version/file id、底模、训练词、文件大小、SHA-256 和分页游标。搜索结果不能直接传给 drawing_generate_image；需要由 ADMIN_USERS 下载，等待下载成功并重新查询目录取得精确 managed identifier 后才能生成。",
            "parameters": {
                "type": "object",
                "properties": {
                    "q": {
                        "type": "string",
                        "description": "Civitai LoRA 搜索词。",
                        "maxLength": 256,
                    },
                    "base_model": {
                        "type": "string",
                        "description": "目标底模，默认 Illustrious。",
                        "default": "Illustrious",
                        "maxLength": 256,
                    },
                    "nsfw": {
                        "type": "boolean",
                        "description": "是否让 Civitai 搜索包含标记为 NSFW 的模型。",
                        "default": True,
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100,
                        "default": 20,
                        "description": "本页请求数量。",
                    },
                    "cursor": {
                        "type": "string",
                        "maxLength": 512,
                        "description": "上一页返回的 next_cursor。",
                    },
                },
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


async def execute(
    args: dict[str, Any],
    runtime: dict[str, Any],
    ctx: dict[str, Any],
) -> dict[str, Any]:
    try:
        payload = await request_json(
            "GET",
            "/v1/civitai/search",
            params={
                "q": string_value(args.get("q"), "q", maximum=256) or None,
                "base_model": string_value(
                    args.get("base_model"),
                    "base_model",
                    default="Illustrious",
                    maximum=256,
                )
                or "Illustrious",
                "nsfw": boolean_value(
                    args.get("nsfw"), "nsfw", default=True
                ),
                "limit": integer_value(
                    args.get("limit"),
                    "limit",
                    default=20,
                    minimum=1,
                    maximum=100,
                ),
                "cursor": string_value(
                    args.get("cursor"), "cursor", maximum=512
                )
                or None,
            },
        )
        return success_result(format_civitai_search(payload))
    except Exception as exc:
        return failure_result("搜索 Civitai LoRA", exc, ctx)
