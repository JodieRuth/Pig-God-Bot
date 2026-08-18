from __future__ import annotations

from typing import Any

from _drawing_gateway import (
    failure_result,
    generation_status,
    resource_id,
    success_result,
)


def definition(ctx: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "drawing_generation_status",
            "description": "按原 job id 主动查询 Drawing Gateway 本地图片后台任务的状态。drawing_generate_image 已会在后台监控并在完成后主动通知，本工具用于用户主动追问、机器人重启后恢复查询或排查异常；禁止为同一请求重新提交生成任务。任务成功时只返回临时图片 URL、密码、到期时间、seed 和安全参数，不下载或读取图片。",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 128,
                        "description": "drawing_generate_image 返回的 job id。",
                    }
                },
                "required": ["job_id"],
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
        job_id = resource_id(args.get("job_id"), "job_id")
        return success_result(await generation_status(job_id))
    except Exception as exc:
        return failure_result("查询 Drawing Gateway 生图状态", exc, ctx)
