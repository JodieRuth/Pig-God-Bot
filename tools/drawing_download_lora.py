from __future__ import annotations

from typing import Any

from _drawing_gateway import (
    failure_result,
    format_download_accepted,
    integer_value,
    request_json,
    require_admin,
    success_result,
)


def definition(ctx: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "drawing_download_lora",
            "description": "仅供 ADMIN_USERS 使用。让 Drawing Gateway 按 drawing_search_civitai 返回的 Civitai version/file id 创建异步 LoRA 下载批次，会写入服务器磁盘；普通用户不得调用。创建后必须调用 drawing_download_status 等待成功，再重新调用 drawing_search_loras 获取精确 managed identifier，不能直接拿 Civitai id 生成。下载前或容量错误时可先调用 drawing_storage_status。",
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 20,
                        "description": "从 drawing_search_civitai 结果中选择的下载项目。",
                        "items": {
                            "type": "object",
                            "properties": {
                                "model_version_id": {
                                    "type": "integer",
                                    "minimum": 1,
                                    "description": "Civitai model version id。",
                                },
                                "file_id": {
                                    "type": "integer",
                                    "minimum": 1,
                                    "description": "可选 Civitai safetensors file id；省略时由网关选择 primary 文件。",
                                },
                            },
                            "required": ["model_version_id"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["items"],
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
        require_admin(runtime, ctx)
        raw_items = args.get("items")
        if not isinstance(raw_items, list):
            raise ValueError("items 必须是数组。")
        if not 1 <= len(raw_items) <= 20:
            raise ValueError("items 必须包含 1 到 20 项。")
        items = []
        for index, item in enumerate(raw_items):
            if not isinstance(item, dict):
                raise ValueError(f"items[{index}] 必须是对象。")
            request_item = {
                "model_version_id": integer_value(
                    item.get("model_version_id"),
                    f"items[{index}].model_version_id",
                    minimum=1,
                )
            }
            if item.get("file_id") is not None:
                request_item["file_id"] = integer_value(
                    item.get("file_id"),
                    f"items[{index}].file_id",
                    minimum=1,
                )
            items.append(request_item)
        payload = await request_json(
            "POST",
            "/v1/civitai/downloads",
            body={"items": items},
        )
        return success_result(format_download_accepted(payload))
    except Exception as exc:
        return failure_result("创建 Drawing Gateway LoRA 下载", exc, ctx)
