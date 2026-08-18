from __future__ import annotations

from typing import Any

from _drawing_gateway import (
    failure_result,
    generation_status,
    success_result,
)
from _drawing_generation_runtime import (
    gateway_generation_id,
    normalize_public_generation_id,
)


def definition(ctx: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "drawing_generation_status",
            "description": "按 drawing_generate_image 返回的机器人八位任务号查询当前进程仍在等待的本地图片任务。禁止传入或向用户索要 Drawing Gateway job id，禁止为同一请求重新提交生成任务。结果只返回八位任务号、状态和图片 URL，不返回排队位置、密码、到期时间、seed、生成参数或内部等待方式；机器人重启或管理员使用 /status <任务号> 停止等待后无法再查询。",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "minLength": 8,
                        "maxLength": 8,
                        "pattern": "^[0-9a-fA-F]{8}$",
                        "description": "drawing_generate_image 返回的机器人八位任务号。",
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
        public_id = normalize_public_generation_id(args.get("job_id"))
        if not public_id:
            return {
                "ok": False,
                "content": "查询本地生图状态失败：任务 ID 必须是八位十六进制字符。",
            }
        internal_id = gateway_generation_id(public_id)
        if not internal_id:
            return {
                "ok": False,
                "content": "没有找到这个任务，任务可能已完成、已取消或来自机器人重启前。",
            }
        result = await generation_status(internal_id)
        if not gateway_generation_id(public_id):
            return {
                "ok": False,
                "content": "这个任务已取消，后续结果不会发送。",
            }
        status = str(result.get("status") or "unknown")
        payload: dict[str, Any] = {
            "job_id": public_id,
            "status": status,
        }
        if status == "succeeded":
            images = []
            for image in result.get("images") or []:
                if not isinstance(image, dict):
                    continue
                url = str(image.get("url") or "").strip()
                if url:
                    images.append({"url": url})
            payload["images"] = images
        elif status == "failed" and isinstance(result.get("error"), dict):
            error = result["error"]
            payload["error"] = {
                "code": str(error.get("code") or ""),
                "description": str(error.get("description") or "任务失败"),
            }
        return success_result(payload)
    except Exception as exc:
        return failure_result("查询本地生图状态", exc, ctx)
