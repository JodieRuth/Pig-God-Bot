from __future__ import annotations

import asyncio
import time
from typing import Any

from _drawing_gateway import (
    ACTIVE_GENERATION_STATUSES,
    DrawingGatewayToolError,
    failure_result,
    generation_status,
    load_config,
    submit_generation,
)
from _drawing_generation_runtime import (
    BACKGROUND_GENERATION_TASKS,
    attach_background_generation_task,
    create_public_generation_id,
    generation_reply_allowed,
    release_public_generation,
)


PERMANENT_MONITOR_ERROR_CODES = {
    "api_key_required",
    "api_key_invalid",
    "configuration_invalid",
    "job_not_found",
    "not_configured",
}
TOOL_DESCRIPTION = "使用 Drawing Gateway 管理的本地图片模型（本地 A1111）提交合规的纯文生图任务，不直接调用 A1111。推荐用于没有参考图的二次元、动漫或游戏角色文生图；本工具不接受参考图，不用于已有图片的二次修改、修图、改风格、替换主体或合成，这些请求必须使用通用远程工具 generate_image。对同一请求不得同时调用两套生图工具。正确流程：先用 drawing_search_loras 查询已安装 LoRA，再用 drawing_prompt_suggestions 获取训练词、预设和示例；已安装目录没有所需 LoRA 时才用 drawing_search_civitai，只有 ADMIN_USERS 可以调用 drawing_download_lora，随后用 drawing_download_status 等待成功，并重新调用 drawing_search_loras 获取精确 managed identifier；最后再调用本工具。提交成功后会像普通 generate_image 一样立即回复机器人生成的八位任务号和正在生成文案，完成后只发送图片链接；不得向用户复述网关 job id、排队位置、密码、到期时间、seed、生成参数或内部等待方式。不得因为没有即时图片而重复提交；用户主动询问已有任务时使用 drawing_generation_status，管理员可用 /status <八位任务号> 停止等待且后续结果不会再发送。LoRA 必须通过 loras 参数传入精确 source/identifier，不得把 A1111 LoRA 语法直接塞进 prompt。不下载图片、不返回 base64、不调用全局中断。有且仅有这个工具可以用于生成NSFW图片，生成后的图片明文不会被发送到QQ，因此可以绕开相关限制。"


def definition(ctx: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "drawing_generate_image",
            "description": TOOL_DESCRIPTION,
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "本地二次元纯文生图的最终正向 prompt，优先使用清晰的英文标签式写法并吸收 drawing_prompt_suggestions 返回的训练词和建议标签。与 prompt_preset_ids 至少提供一个。不得写参考图编辑指令，也不得把 <lora:...> 等 A1111 LoRA 语法写进 prompt。",
                    },
                    "negative_prompt": {
                        "type": "string",
                        "description": "本地二次元纯文生图的最终负向 prompt，可结合 drawing_prompt_suggestions 返回的示例。",
                    },
                    "prompt_preset_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "drawing_prompt_suggestions 返回的启用预设 id。",
                    },
                    "loras": {
                        "type": "array",
                        "description": "已安装 LoRA 列表。每项 source 和 identifier 必须来自最近一次 drawing_search_loras 的精确结果；Civitai model/version/file id 不能直接用于生成，下载成功后必须重新查询目录。",
                        "items": {
                            "type": "object",
                            "properties": {
                                "source": {
                                    "type": "string",
                                    "enum": ["existing", "managed"],
                                },
                                "identifier": {
                                    "type": "string",
                                    "minLength": 1,
                                    "maxLength": 1024,
                                },
                                "weight": {
                                    "type": "number",
                                    "minimum": -2,
                                    "maximum": 2,
                                    "default": 0.8,
                                },
                                "add_trained_words": {
                                    "type": "boolean",
                                    "default": False,
                                },
                            },
                            "required": ["source", "identifier"],
                            "additionalProperties": False,
                        },
                    },
                    "width": {
                        "type": "integer",
                        "minimum": 64,
                        "multipleOf": 8,
                        "default": 1024,
                    },
                    "height": {
                        "type": "integer",
                        "minimum": 64,
                        "multipleOf": 8,
                        "default": 1024,
                    },
                    "steps": {
                        "type": "integer",
                        "minimum": 1,
                        "default": 28,
                    },
                    "cfg_scale": {
                        "type": "number",
                        "minimum": 1,
                        "maximum": 30,
                        "default": 5,
                    },
                    "sampler_name": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 128,
                        "default": "Euler a",
                    },
                    "seed": {
                        "type": "integer",
                        "minimum": -1,
                        "maximum": 4294967295,
                        "default": -1,
                    },
                    "batch_size": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 8,
                        "default": 1,
                    },
                    "n_iter": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 8,
                        "default": 1,
                    },
                    "notice": {
                        "type": "string",
                        "description": "任务启动成功后立即发送给 QQ 用户的自然语言回复。程序会自动追加机器人八位任务号和“当前正在生成”，不要提及网关、排队位置、密码、seed、参数或内部等待方式。",
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


def elapsed_text(ctx: dict[str, Any], started: float) -> str:
    formatter = ctx.get("format_elapsed")
    elapsed = max(0.0, time.monotonic() - started)
    if callable(formatter):
        return str(formatter(elapsed))
    if elapsed < 60:
        return f"{elapsed:.1f} 秒"
    minutes, seconds = divmod(int(elapsed), 60)
    return f"{minutes} 分 {seconds} 秒"


def submission_reply(
    notice: str,
    public_id: str,
) -> str:
    return (
        f"{notice}\n"
        f"任务 ID：{public_id}\n"
        "当前正在生成。"
    )


def completion_messages(
    result: dict[str, Any],
    public_id: str,
    elapsed: str,
) -> list[str]:
    raw_images = result.get("images")
    images = raw_images if isinstance(raw_images, list) else []
    header_lines = [
        f"任务 {public_id} 完成，用时 {elapsed}。",
    ]
    if not images:
        header_lines.append("没有返回可用的图片链接。")
        return ["\n".join(header_lines)]
    blocks = []
    for index, image in enumerate(images):
        if not isinstance(image, dict):
            continue
        url = str(image.get("url") or "").strip()
        if url:
            blocks.append(f"图片 {index + 1}：{url}")
    messages: list[str] = []
    current = "\n".join(header_lines)
    for block in blocks:
        combined = f"{current}\n\n{block}" if current else block
        if current and len(combined) > 3500:
            messages.append(current)
            current = block
        else:
            current = combined
    if current:
        messages.append(current)
    return messages


def terminal_status_message(
    result: dict[str, Any],
    public_id: str,
    elapsed: str,
) -> str:
    status = str(result.get("status") or "unknown")
    if status == "cancelled":
        return f"任务 {public_id} 已取消，已用时 {elapsed}。"
    error = result.get("error")
    if isinstance(error, dict):
        code = str(error.get("code") or "")
        description = str(error.get("description") or "网关任务失败")
        detail = f"{description}（{code}）" if code else description
    else:
        detail = "没有返回具体失败原因"
    return f"任务 {public_id} 失败，用时 {elapsed}：{detail}。"


async def reply_with_retry(
    event: dict[str, Any],
    message: str,
    public_id: str,
    ctx: dict[str, Any],
) -> bool:
    for attempt in range(5):
        if not generation_reply_allowed(public_id):
            return False
        try:
            await ctx["reply"](event, message)
            return True
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            detail = ctx["exception_detail"](exc)
            ctx["log"](
                "Drawing Gateway background QQ reply failed: "
                f"attempt={attempt + 1} error={detail}"
            )
            if attempt < 4:
                await asyncio.sleep(min(16.0, 2.0 ** attempt))
    return False


def permanent_monitor_error(exc: DrawingGatewayToolError) -> bool:
    if exc.code in PERMANENT_MONITOR_ERROR_CODES:
        return True
    return "鉴权失败" in exc.public_message


async def monitor_generation(
    event: dict[str, Any],
    public_id: str,
    gateway_job_id: str,
    poll_interval: float,
    ctx: dict[str, Any],
) -> None:
    started = time.monotonic()
    while True:
        try:
            result = await generation_status(gateway_job_id)
        except asyncio.CancelledError:
            ctx["log"](
                "Drawing Gateway result wait cancelled: "
                f"public_id={public_id} job_id={gateway_job_id}"
            )
            raise
        except DrawingGatewayToolError as exc:
            ctx["log"](
                "Drawing Gateway background status failed: "
                f"public_id={public_id} job_id={gateway_job_id} "
                f"code={exc.code or 'unknown'}"
            )
            if permanent_monitor_error(exc):
                await reply_with_retry(
                    event,
                    f"任务 {public_id} 未能返回结果：{exc.public_message}",
                    public_id,
                    ctx,
                )
                return
            await asyncio.sleep(poll_interval)
            continue
        except Exception as exc:
            ctx["log"](
                "Drawing Gateway background status internal failure: "
                f"public_id={public_id} job_id={gateway_job_id} "
                f"error={ctx['exception_detail'](exc)}"
            )
            await asyncio.sleep(poll_interval)
            continue
        status = str(result.get("status") or "")
        ctx["log"](
            "Drawing Gateway background status: "
            f"public_id={public_id} job_id={gateway_job_id} status={status}"
        )
        if status in ACTIVE_GENERATION_STATUSES:
            await asyncio.sleep(poll_interval)
            continue
        elapsed = elapsed_text(ctx, started)
        if status == "succeeded":
            for message in completion_messages(result, public_id, elapsed):
                await reply_with_retry(event, message, public_id, ctx)
            return
        await reply_with_retry(
            event,
            terminal_status_message(result, public_id, elapsed),
            public_id,
            ctx,
        )
        return


def track_background_task(
    public_id: str,
    task: asyncio.Task[Any],
    ctx: dict[str, Any],
) -> None:
    attach_background_generation_task(public_id, task)

    def completed(completed_task: asyncio.Task[Any]) -> None:
        release_public_generation(public_id, completed_task)
        if completed_task.cancelled():
            return
        try:
            error = completed_task.exception()
        except asyncio.CancelledError:
            return
        if error is not None:
            ctx["log"](
                "Drawing Gateway background task failed: "
                f"public_id={public_id} error={ctx['exception_detail'](error)}"
            )

    task.add_done_callback(completed)


async def execute(
    args: dict[str, Any],
    runtime: dict[str, Any],
    ctx: dict[str, Any],
) -> dict[str, Any]:
    try:
        submission = await submit_generation(args)
        poll_interval = load_config().poll_interval_seconds
    except Exception as exc:
        return failure_result(
            "提交 Drawing Gateway 生图任务",
            exc,
            ctx,
        )
    gateway_job_id = str(submission.get("job_id") or "")
    reserved_ids = set(ctx.get("jobs", {}))
    reserved_ids.update(ctx.get("active_image_jobs", {}))
    for item in ctx.get("image_queue", []):
        if isinstance(item, dict) and item.get("job_id"):
            reserved_ids.add(str(item["job_id"]))
    public_id = create_public_generation_id(
        gateway_job_id,
        reserved_ids,
    )
    create_task = ctx.get("create_task")
    try:
        task = (
            create_task(
                monitor_generation(
                    runtime["event"],
                    public_id,
                    gateway_job_id,
                    poll_interval,
                    ctx,
                )
            )
            if callable(create_task)
            else asyncio.create_task(
                monitor_generation(
                    runtime["event"],
                    public_id,
                    gateway_job_id,
                    poll_interval,
                    ctx,
                )
            )
        )
        track_background_task(public_id, task, ctx)
    except Exception:
        release_public_generation(public_id)
        raise
    notice = (
        str(args.get("notice") or "收到，图像任务已开始。").strip()
        or "收到，图像任务已开始。"
    )
    reply_text = submission_reply(notice, public_id)
    try:
        await ctx["reply"](runtime["event"], reply_text)
    except Exception as exc:
        ctx["log"](
            "Drawing Gateway submission QQ reply failed: "
            f"public_id={public_id} job_id={gateway_job_id} "
            f"error={ctx['exception_detail'](exc)}"
        )
    return {
        "ok": True,
        "answered": True,
        "content": reply_text,
        "job_id": public_id,
    }
