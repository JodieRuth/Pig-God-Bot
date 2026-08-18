from __future__ import annotations

from typing import Any

from _drawing_gateway import (
    failure_result,
    format_storage,
    request_json,
    success_result,
)


def definition(ctx: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "drawing_storage_status",
            "description": "查询 Drawing Gateway 受管 LoRA 的已安装文件数、已用容量和上限；不会统计或修改服务器原有 LoRA。准备下载较大 LoRA 前或下载因容量限制失败时使用，本工具本身不会下载或删除文件。",
            "parameters": {
                "type": "object",
                "properties": {},
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
        payload = await request_json("GET", "/v1/catalog/storage")
        return success_result(format_storage(payload))
    except Exception as exc:
        return failure_result("查询 Drawing Gateway LoRA 容量", exc, ctx)
