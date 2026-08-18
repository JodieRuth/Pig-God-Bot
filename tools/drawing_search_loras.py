from __future__ import annotations

from typing import Any

from _drawing_gateway import (
    choice_value,
    failure_result,
    format_lora_catalog,
    request_json,
    string_value,
    success_result,
)


def definition(ctx: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "drawing_search_loras",
            "description": "本地图片模型工具链的第一步：在 Drawing Gateway 中查询服务器已有 LoRA 和网关受管 LoRA。为二次元、动漫或游戏角色纯文生图选择 LoRA 时必须先调用本工具，后续 prompt 查询和生成必须使用返回的精确 source 与 identifier，不能猜测名称。目录没有所需 LoRA 时才继续调用 drawing_search_civitai。",
            "parameters": {
                "type": "object",
                "properties": {
                    "q": {
                        "type": "string",
                        "description": "按名称、别名、训练词或标签搜索；省略时列出目录中的前若干项。",
                        "maxLength": 256,
                    },
                    "source": {
                        "type": "string",
                        "enum": ["all", "existing", "managed"],
                        "description": "all 查询全部，existing 查询服务器原有 LoRA，managed 查询网关下载并管理的 LoRA。",
                        "default": "all",
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
        query = string_value(args.get("q"), "q", maximum=256)
        source = choice_value(
            args.get("source"),
            "source",
            {"all", "existing", "managed"},
            default="all",
        )
        payload = await request_json(
            "GET",
            "/v1/catalog/loras",
            params={"q": query or None, "source": source},
        )
        return success_result(format_lora_catalog(payload))
    except Exception as exc:
        return failure_result("查询 Drawing Gateway LoRA", exc, ctx)
