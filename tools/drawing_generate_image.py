from __future__ import annotations

import asyncio
import json
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


BACKGROUND_GENERATION_TASKS: dict[str, asyncio.Task[Any]] = {}
PERMANENT_MONITOR_ERROR_CODES = {
    "api_key_required",
    "api_key_invalid",
    "configuration_invalid",
    "job_not_found",
    "not_configured",
}
TOOL_DESCRIPTION = "使用 Drawing Gateway 管理的本地图片模型（本地 A1111）提交合规的纯文生图后台任务，不直接调用 A1111。推荐用于没有参考图的二次元、动漫或游戏角色文生图；本工具不接受参考图，不用于已有图片的二次修改、修图、改风格、替换主体或合成，这些请求必须使用通用远程工具 generate_image。对同一请求不得同时调用两套生图工具。正确流程：先用 drawing_search_loras 查询已安装 LoRA，再用 drawing_prompt_suggestions 获取训练词、预设和示例；已安装目录没有所需 LoRA 时才用 drawing_search_civitai，只有 ADMIN_USERS 可以调用 drawing_download_lora，随后用 drawing_download_status 等待成功，并重新调用 drawing_search_loras 获取精确 managed identifier；最后再调用本工具。网关接受任务后，本工具会立即向 QQ 回复 job id、状态和排队位置，并结束当前 LLM 回复；机器人随后在后台监控同一个网关任务，成功后主动向原 QQ 会话发送每张图的临时 URL、密码、过期时间、seed 和安全参数，失败或取消也会主动通知。不得因为没有即时图片而重复提交；用户主动询问已有任务时使用 drawing_generation_status。LoRA 必须通过 loras 参数传入精确 source/identifier，不得把 A1111 LoRA 语法直接塞进 prompt。不下载图片、不返回 base64、不调用全局中断。若请求涉及政治敏感、中国大陆政治不正确、违法违规、暴力恐怖、色情低俗、赌博诈骗、侵犯隐私、规避平台审核、攻击骚扰、仇恨歧视、自伤诱导、未成年人不当内容、伪造证件票据、冒充真实个人或 QQ 平台及中国大陆法规不允许的内容，禁止调用。"


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
                        "description": "任务被网关接受后立即发送给 QQ 用户的自然语言回执开头。程序会自动追加 job id、状态、排队位置和完成后主动通知的说明。",
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
    submission: dict[str, Any],
) -> str:
    job_id = str(submission.get("job_id") or "")
    status = str(submission.get("status") or "queued")
    position = submission.get("position")
    if status == "queued" and isinstance(position, int) and position > 0:
        state = f"当前在网关全局队列中排第 {position} 位。"
    elif status == "queued":
        state = "当前已进入网关全局队列。"
    elif status == "running":
        state = "当前正在由本地模型生成。"
    else:
        state = f"网关当前状态：{status}，正在确认最终结果。"
    return (
        f"{notice}\n"
        f"本地模型任务 ID：{job_id}\n"
        f"{state}\n"
        "机器人会在后台监控该任务，完成、失败或取消后主动通知。"
    )


def completion_messages(
    result: dict[str, Any],
    elapsed: str,
) -> list[str]:
    job_id = str(result.get("job_id") or "")
    raw_images = result.get("images")
    images = raw_images if isinstance(raw_images, list) else []
    raw_seeds = result.get("seeds")
    seeds = raw_seeds if isinstance(raw_seeds, list) else []
    parameters = result.get("parameters")
    header_lines = [
        f"本地模型任务 {job_id} 完成，用时 {elapsed}。",
        f"共返回 {len(images)} 张图片。临时链接和密码会在标注时间后失效。",
    ]
    if isinstance(parameters, dict) and parameters:
        header_lines.append(
            "生成参数："
            + json.dumps(
                parameters,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
    if not images:
        header_lines.append("网关没有返回可用的临时图片链接。")
        return ["\n".join(header_lines)]
    blocks = []
    for index, image in enumerate(images):
        if not isinstance(image, dict):
            continue
        seed = seeds[index] if index < len(seeds) else None
        lines = [
            f"图片 {index + 1}",
            f"临时 URL：{image.get('url') or ''}",
            f"密码：{image.get('password') or ''}",
            f"过期时间：{image.get('expires_at') or ''}",
        ]
        if isinstance(seed, int) and not isinstance(seed, bool):
            lines.append(f"Seed：{seed}")
        blocks.append("\n".join(lines))
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
    elapsed: str,
) -> str:
    job_id = str(result.get("job_id") or "")
    status = str(result.get("status") or "unknown")
    if status == "cancelled":
        return f"本地模型任务 {job_id} 已取消，已用时 {elapsed}。"
    error = result.get("error")
    if isinstance(error, dict):
        code = str(error.get("code") or "")
        description = str(error.get("description") or "网关任务失败")
        detail = f"{description}（{code}）" if code else description
    else:
        detail = "网关没有返回具体失败原因"
    return f"本地模型任务 {job_id} 失败，用时 {elapsed}：{detail}。"


async def reply_with_retry(
    event: dict[str, Any],
    message: str,
    ctx: dict[str, Any],
) -> bool:
    for attempt in range(5):
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
    job_id: str,
    poll_interval: float,
    ctx: dict[str, Any],
) -> None:
    started = time.monotonic()
    failures = 0
    interruption_reported = False
    while True:
        try:
            result = await generation_status(job_id)
            failures = 0
        except asyncio.CancelledError:
            ctx["log"](
                f"Drawing Gateway background monitor cancelled: job_id={job_id}"
            )
            raise
        except DrawingGatewayToolError as exc:
            ctx["log"](
                "Drawing Gateway background status failed: "
                f"job_id={job_id} code={exc.code or 'unknown'}"
            )
            if permanent_monitor_error(exc):
                await reply_with_retry(
                    event,
                    (
                        f"本地模型任务 {job_id} 的后台监控已停止："
                        f"{exc.public_message}\n"
                        "任务可能仍保留在网关中，可稍后按原任务 ID 查询。"
                    ),
                    ctx,
                )
                return
            failures += 1
            if failures >= 3 and not interruption_reported:
                interruption_reported = True
                await reply_with_retry(
                    event,
                    (
                        f"本地模型任务 {job_id} 暂时无法查询状态，"
                        "机器人会继续在后台重试，不会重新提交任务。"
                    ),
                    ctx,
                )
            await asyncio.sleep(poll_interval)
            continue
        except Exception as exc:
            failures += 1
            ctx["log"](
                "Drawing Gateway background status internal failure: "
                f"job_id={job_id} error={ctx['exception_detail'](exc)}"
            )
            if failures >= 3 and not interruption_reported:
                interruption_reported = True
                await reply_with_retry(
                    event,
                    (
                        f"本地模型任务 {job_id} 暂时无法查询状态，"
                        "机器人会继续在后台重试，不会重新提交任务。"
                    ),
                    ctx,
                )
            await asyncio.sleep(poll_interval)
            continue
        status = str(result.get("status") or "")
        ctx["log"](
            f"Drawing Gateway background status: job_id={job_id} status={status}"
        )
        if status in ACTIVE_GENERATION_STATUSES:
            await asyncio.sleep(poll_interval)
            continue
        elapsed = elapsed_text(ctx, started)
        if status == "succeeded":
            for message in completion_messages(result, elapsed):
                await reply_with_retry(event, message, ctx)
            return
        await reply_with_retry(
            event,
            terminal_status_message(result, elapsed),
            ctx,
        )
        return


def track_background_task(
    job_id: str,
    task: asyncio.Task[Any],
    ctx: dict[str, Any],
) -> None:
    BACKGROUND_GENERATION_TASKS[job_id] = task

    def completed(completed_task: asyncio.Task[Any]) -> None:
        if BACKGROUND_GENERATION_TASKS.get(job_id) is completed_task:
            BACKGROUND_GENERATION_TASKS.pop(job_id, None)
        if completed_task.cancelled():
            return
        try:
            error = completed_task.exception()
        except asyncio.CancelledError:
            return
        if error is not None:
            ctx["log"](
                "Drawing Gateway background task failed: "
                f"job_id={job_id} error={ctx['exception_detail'](error)}"
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
    job_id = str(submission.get("job_id") or "")
    create_task = ctx.get("create_task")
    task = (
        create_task(
            monitor_generation(
                runtime["event"],
                job_id,
                poll_interval,
                ctx,
            )
        )
        if callable(create_task)
        else asyncio.create_task(
            monitor_generation(
                runtime["event"],
                job_id,
                poll_interval,
                ctx,
            )
        )
    )
    track_background_task(job_id, task, ctx)
    notice = (
        str(args.get("notice") or "本地模型任务已提交。").strip()
        or "本地模型任务已提交。"
    )
    reply_text = submission_reply(notice, submission)
    try:
        await ctx["reply"](runtime["event"], reply_text)
    except Exception as exc:
        ctx["log"](
            "Drawing Gateway submission QQ reply failed: "
            f"job_id={job_id} error={ctx['exception_detail'](exc)}"
        )
    return {
        "ok": True,
        "answered": True,
        "content": reply_text,
        "job_id": job_id,
        "status": submission.get("status"),
        "position": submission.get("position"),
    }
