from __future__ import annotations

from typing import Any

from _drawing_gateway import (
    choice_value,
    failure_result,
    format_prompt_suggestions,
    integer_value,
    request_json,
    string_value,
    success_result,
)


def definition(ctx: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "drawing_prompt_suggestions",
            "description": "为本地二次元纯文生图查询 Drawing Gateway 的 prompt 预设、LoRA 训练词、建议标签和示例 prompt。选定已安装 LoRA 后，应使用 drawing_search_loras 返回的精确 source/identifier 调用本工具，并把结果整理进最终标签式 prompt；指定 civitai_version_id 时只用于了解尚未下载版本的训练词和示例，不能据此直接生成。",
            "parameters": {
                "type": "object",
                "properties": {
                    "q": {
                        "type": "string",
                        "description": "筛选预设、训练词、标签或示例 prompt 的查询词。",
                        "maxLength": 256,
                    },
                    "lora_source": {
                        "type": "string",
                        "enum": ["existing", "managed"],
                        "description": "已安装 LoRA 的来源；与 lora_identifier 同时提供。",
                    },
                    "lora_identifier": {
                        "type": "string",
                        "description": "drawing_search_loras 返回的精确 identifier；与 lora_source 同时提供。",
                        "maxLength": 1024,
                    },
                    "civitai_version_id": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Civitai version id。提供后改用版本 prompt 接口并忽略其他 LoRA 参数。",
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
        raw_version_id = args.get("civitai_version_id")
        if raw_version_id is not None:
            version_id = integer_value(
                raw_version_id,
                "civitai_version_id",
                minimum=1,
            )
            payload = await request_json(
                "GET",
                f"/v1/civitai/versions/{version_id}/prompts",
            )
            return success_result(format_prompt_suggestions(payload))
        query = string_value(args.get("q"), "q", maximum=256)
        raw_source = args.get("lora_source")
        raw_identifier = args.get("lora_identifier")
        if (raw_source is None) != (raw_identifier is None):
            raise ValueError(
                "lora_source 和 lora_identifier 必须同时提供。"
            )
        params: dict[str, Any] = {"q": query or None}
        if raw_source is not None:
            params["lora_source"] = choice_value(
                raw_source,
                "lora_source",
                {"existing", "managed"},
                default="existing",
            )
            params["lora_identifier"] = string_value(
                raw_identifier,
                "lora_identifier",
                required=True,
                maximum=1024,
            )
        payload = await request_json(
            "GET",
            "/v1/catalog/prompts",
            params=params,
        )
        return success_result(format_prompt_suggestions(payload))
    except Exception as exc:
        return failure_result("查询 Drawing Gateway prompt 建议", exc, ctx)
