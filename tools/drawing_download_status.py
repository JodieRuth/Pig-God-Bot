from __future__ import annotations

from typing import Any

from _drawing_gateway import (
    failure_result,
    format_download_status,
    integer_value,
    request_json,
    require_admin,
    resource_id,
    success_result,
)


def definition(ctx: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "drawing_download_status",
            "description": "仅供 ADMIN_USERS 使用。按 batch id 或 download id 查询 Drawing Gateway 的 LoRA 下载状态，不读取或返回文件内容。未完成时继续查询同一批次或下载项；成功后必须重新调用 drawing_search_loras，并用其返回的精确 managed identifier 进行 prompt 查询和生成。",
            "parameters": {
                "type": "object",
                "properties": {
                    "batch_id": {
                        "type": "string",
                        "description": "drawing_download_lora 返回的 batch id。",
                        "maxLength": 128,
                    },
                    "download_id": {
                        "type": "string",
                        "description": "drawing_download_lora 返回的单项 download id。",
                        "maxLength": 128,
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 500,
                        "default": 100,
                        "description": "按 batch id 查询时的最大返回数量。",
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
        require_admin(runtime, ctx)
        raw_batch_id = args.get("batch_id")
        raw_download_id = args.get("download_id")
        if (raw_batch_id is None) == (raw_download_id is None):
            raise ValueError(
                "batch_id 和 download_id 必须且只能提供一个。"
            )
        if raw_download_id is not None:
            download_id = resource_id(raw_download_id, "download_id")
            payload = await request_json(
                "GET",
                f"/v1/civitai/downloads/{download_id}",
            )
        else:
            batch_id = resource_id(raw_batch_id, "batch_id")
            payload = await request_json(
                "GET",
                "/v1/civitai/downloads",
                params={
                    "batch_id": batch_id,
                    "limit": integer_value(
                        args.get("limit"),
                        "limit",
                        default=100,
                        minimum=1,
                        maximum=500,
                    ),
                },
            )
        return success_result(format_download_status(payload))
    except Exception as exc:
        return failure_result("查询 Drawing Gateway LoRA 下载状态", exc, ctx)
