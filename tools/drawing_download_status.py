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
            "description": "仅供 ADMIN_USERS 使用。按 batch id 或单个 download id 查询 Drawing Gateway 的 LoRA 下载状态，不读取或返回文件内容。批次查询只传 {\"batch_id\":\"原样复制 drawing_download_lora 返回的 batch_id\"}；单项查询只传 {\"download_id\":\"从 download_ids 数组中取出的一个字符串元素\"}。禁止传 download_ids 数组、禁止同时传两个字段、禁止拼接或改写 ID。未完成时继续查询同一个 ID；成功后必须重新调用 drawing_search_loras，并用其返回的精确 managed identifier 进行 prompt 查询和生成。",
            "parameters": {
                "type": "object",
                "properties": {
                    "batch_id": {
                        "type": "string",
                        "description": "drawing_download_lora 返回的 batch id。",
                        "minLength": 1,
                        "maxLength": 64,
                    },
                    "download_id": {
                        "type": "string",
                        "description": "drawing_download_lora 返回的 download_ids 数组中的一个字符串元素。",
                        "minLength": 1,
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
                "oneOf": [
                    {"required": ["batch_id"]},
                    {"required": ["download_id"]},
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


async def execute(
    args: dict[str, Any],
    runtime: dict[str, Any],
    ctx: dict[str, Any],
) -> dict[str, Any]:
    try:
        require_admin(runtime, ctx)
        raw_batch_id = args.get("batch_id")
        raw_download_id = args.get("download_id")
        if isinstance(raw_batch_id, str) and not raw_batch_id.strip():
            raw_batch_id = None
        if isinstance(raw_download_id, str) and not raw_download_id.strip():
            raw_download_id = None
        if (raw_batch_id is None) == (raw_download_id is None):
            raise ValueError(
                "只能提供 batch_id 或 download_id 其中一个；不要传 download_ids 数组，也不要同时传两个字段。"
            )
        if raw_download_id is not None:
            download_id = resource_id(raw_download_id, "download_id")
            payload = await request_json(
                "GET",
                f"/v1/civitai/downloads/{download_id}",
            )
        else:
            batch_id = resource_id(raw_batch_id, "batch_id")
            if len(batch_id) > 64:
                raise ValueError("batch_id 不能超过 64 个字符。")
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
