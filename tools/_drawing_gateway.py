from __future__ import annotations

import asyncio
import json
import math
import os
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit

import aiohttp


ACTIVE_GENERATION_STATUSES = {"queued", "running", "cancel_requested"}
FINAL_GENERATION_STATUSES = {"cancelled", "succeeded", "failed"}
RESOURCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
ERROR_CODE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
ERROR_DESCRIPTIONS = {
    "api_key_required": "缺少 API Key",
    "api_key_invalid": "API Key 无效",
    "job_not_found": "生成任务不存在",
    "job_result_unavailable": "生成结果尚不可用",
    "gateway_restarted": "网关在任务执行期间重启",
    "duplicate_lora": "同一个 LoRA 被重复选择",
    "prompt_too_long": "prompt 超过网关限制",
    "negative_prompt_too_long": "negative prompt 超过网关限制",
    "too_many_loras": "选择的 LoRA 数量超过网关限制",
    "too_many_prompts": "prompt 预设数量超过网关限制",
    "image_too_large": "图片尺寸超过网关限制",
    "too_many_steps": "采样步数超过网关限制",
    "too_many_images": "单任务图片数量超过网关限制",
    "lora_not_found": "LoRA 不存在",
    "lora_not_ready": "受管 LoRA 尚未安装完成",
    "lora_file_missing": "LoRA 文件缺失",
    "download_not_found": "LoRA 下载任务不存在",
    "civitai_file_not_found": "Civitai 版本中没有指定文件",
    "incompatible_base_model": "LoRA 底模不在网关允许列表",
    "not_a_lora": "所选 Civitai 模型不是 LoRA",
    "unsupported_lora_file": "网关只支持 safetensors LoRA",
    "lora_file_too_large": "LoRA 文件超过单文件容量限制",
    "lora_hash_mismatch": "LoRA 文件哈希校验失败",
    "managed_lora_capacity_exhausted": "受管 LoRA 容量不足且无法安全清理",
    "internal_error": "网关内部错误",
}


@dataclass(frozen=True)
class DrawingGatewayConfig:
    base_url: str
    api_key: str
    request_timeout_seconds: float
    poll_interval_seconds: float


class DrawingGatewayToolError(RuntimeError):
    def __init__(self, message: str, code: str = "") -> None:
        super().__init__(message)
        self.public_message = message
        self.code = code


def _configured_number(
    name: str,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise DrawingGatewayToolError(
            f"{name} 必须是数字。",
            "configuration_invalid",
        ) from exc
    if not math.isfinite(value) or value < minimum or value > maximum:
        raise DrawingGatewayToolError(
            f"{name} 必须在 {minimum:g} 到 {maximum:g} 之间。",
            "configuration_invalid",
        )
    return value


def load_config() -> DrawingGatewayConfig:
    base_url = os.getenv("DRAWING_GATEWAY_BASE_URL", "").strip().rstrip("/")
    api_key = os.getenv("DRAWING_GATEWAY_API_KEY", "").strip()
    missing = []
    if not base_url:
        missing.append("DRAWING_GATEWAY_BASE_URL")
    if not api_key:
        missing.append("DRAWING_GATEWAY_API_KEY")
    if missing:
        raise DrawingGatewayToolError(
            f"Drawing Gateway 未配置：缺少 {', '.join(missing)}。",
            "not_configured",
        )
    try:
        parsed = urlsplit(base_url)
        _ = parsed.port
    except ValueError as exc:
        raise DrawingGatewayToolError(
            "DRAWING_GATEWAY_BASE_URL 不是有效的 HTTP/HTTPS 地址。",
            "configuration_invalid",
        ) from exc
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise DrawingGatewayToolError(
            "DRAWING_GATEWAY_BASE_URL 必须是不含凭据、查询参数和片段的 HTTP/HTTPS 地址。",
            "configuration_invalid",
        )
    return DrawingGatewayConfig(
        base_url=base_url,
        api_key=api_key,
        request_timeout_seconds=_configured_number(
            "DRAWING_GATEWAY_REQUEST_TIMEOUT_SECONDS",
            30.0,
            0.1,
            600.0,
        ),
        poll_interval_seconds=_configured_number(
            "DRAWING_GATEWAY_POLL_INTERVAL_SECONDS",
            2.0,
            0.1,
            60.0,
        ),
    )


def clean_text(value: Any, limit: int = 512, collapse: bool = True) -> str:
    text = str(value or "").replace("\x00", "")
    if collapse:
        text = " ".join(text.split())
    else:
        text = text.strip()
    if len(text) > limit:
        return text[: max(0, limit - 3)] + "..."
    return text


def _safe_code(value: Any) -> str:
    code = clean_text(value, 80)
    return code if ERROR_CODE_PATTERN.fullmatch(code) else ""


def _error_code(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    code = _safe_code(payload.get("code"))
    if code:
        return code
    detail = payload.get("detail")
    if isinstance(detail, dict):
        return _safe_code(detail.get("code"))
    return ""


def _validation_errors(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    detail = payload.get("detail")
    if not isinstance(detail, list):
        return []
    errors: list[str] = []
    for item in detail[:8]:
        if not isinstance(item, dict):
            continue
        raw_location = item.get("loc")
        location = ""
        if isinstance(raw_location, list):
            location = ".".join(
                clean_text(part, 64)
                for part in raw_location
                if clean_text(part, 64) not in {"body", "query", "path"}
            )
        message = clean_text(item.get("msg"), 180)
        if location and message:
            errors.append(f"{location}: {message}")
        elif message:
            errors.append(message)
    return errors


def _code_suffix(code: str) -> str:
    if not code:
        return ""
    description = ERROR_DESCRIPTIONS.get(code)
    return f"（{code}：{description}）" if description else f"（{code}）"


def _http_error(status: int, payload: Any) -> DrawingGatewayToolError:
    code = _error_code(payload)
    suffix = _code_suffix(code)
    if status == 401:
        return DrawingGatewayToolError(
            f"Drawing Gateway 鉴权失败：未提供有效 API Key{suffix}。",
            code,
        )
    if status == 403:
        return DrawingGatewayToolError(
            f"Drawing Gateway 鉴权失败：API Key 被拒绝{suffix}。",
            code,
        )
    if status == 404:
        return DrawingGatewayToolError(
            f"Drawing Gateway 未找到请求的资源{suffix}。",
            code,
        )
    if status == 409:
        return DrawingGatewayToolError(
            f"Drawing Gateway 拒绝了当前状态下的请求{suffix}。",
            code,
        )
    if status == 422:
        validation = _validation_errors(payload)
        detail = f"：{'；'.join(validation)}" if validation else suffix
        return DrawingGatewayToolError(
            f"Drawing Gateway 参数校验失败{detail}。",
            code,
        )
    if status == 429:
        return DrawingGatewayToolError(
            f"Drawing Gateway 请求过于频繁，请稍后重试{suffix}。",
            code,
        )
    if status >= 500:
        return DrawingGatewayToolError(
            f"Drawing Gateway 服务暂不可用（HTTP {status}）{suffix}。",
            code,
        )
    return DrawingGatewayToolError(
        f"Drawing Gateway 请求失败（HTTP {status}）{suffix}。",
        code,
    )


async def request_json(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
) -> Any:
    config = load_config()
    url = f"{config.base_url}/{path.lstrip('/')}"
    timeout = aiohttp.ClientTimeout(total=config.request_timeout_seconds)
    request_params = None
    if params:
        request_params = {}
        for key, value in params.items():
            if value is None:
                continue
            request_params[key] = (
                "true" if value else "false"
            ) if isinstance(value, bool) else value
    try:
        async with aiohttp.ClientSession(
            headers={"X-API-Key": config.api_key},
            timeout=timeout,
        ) as session:
            async with session.request(
                method,
                url,
                params=request_params,
                json=body,
            ) as response:
                try:
                    payload = await response.json(content_type=None)
                except (json.JSONDecodeError, ValueError, TypeError):
                    payload = None
                if response.status >= 400:
                    raise _http_error(response.status, payload)
                if payload is None:
                    raise DrawingGatewayToolError(
                        "Drawing Gateway 返回了无法解析的 JSON 响应。"
                    )
                return payload
    except DrawingGatewayToolError:
        raise
    except asyncio.TimeoutError as exc:
        raise DrawingGatewayToolError(
            f"Drawing Gateway 请求超过 {config.request_timeout_seconds:g} 秒。"
        ) from exc
    except (aiohttp.ClientConnectionError, OSError) as exc:
        raise DrawingGatewayToolError(
            "无法连接 Drawing Gateway，请检查机器人侧回环 SSH 本地转发和网关服务。"
        ) from exc
    except aiohttp.ClientError as exc:
        raise DrawingGatewayToolError(
            f"Drawing Gateway HTTP 请求失败（{type(exc).__name__}）。"
        ) from exc


def success_result(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    }


def failure_result(
    action: str,
    exc: Exception,
    ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if isinstance(exc, DrawingGatewayToolError):
        message = exc.public_message
    elif isinstance(exc, ValueError):
        message = clean_text(exc, 400)
    else:
        message = f"内部错误（{type(exc).__name__}）"
    logger = ctx.get("log") if isinstance(ctx, dict) else None
    if callable(logger):
        logger(f"Drawing Gateway {action} failed: {type(exc).__name__}")
    return {"ok": False, "content": f"{action}失败：{message}"}


def is_admin_request(runtime: dict[str, Any], ctx: dict[str, Any]) -> bool:
    checker = ctx.get("is_admin_event")
    event = runtime.get("event")
    if not callable(checker) or not isinstance(event, dict):
        return False
    try:
        return bool(checker(event))
    except Exception:
        return False


def require_admin(runtime: dict[str, Any], ctx: dict[str, Any]) -> None:
    if not is_admin_request(runtime, ctx):
        raise DrawingGatewayToolError(
            "此工具会读取或写入服务器上的 LoRA 下载状态，仅允许 ADMIN_USERS 使用。"
        )


def string_value(
    value: Any,
    name: str,
    *,
    default: str = "",
    required: bool = False,
    maximum: int | None = None,
) -> str:
    if value is None:
        value = default
    if not isinstance(value, str):
        raise ValueError(f"{name} 必须是字符串。")
    result = value.strip()
    if required and not result:
        raise ValueError(f"{name} 不能为空。")
    if maximum is not None and len(result) > maximum:
        raise ValueError(f"{name} 最长为 {maximum} 个字符。")
    return result


def integer_value(
    value: Any,
    name: str,
    *,
    default: int | None = None,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if value is None:
        if default is None:
            raise ValueError(f"{name} 不能为空。")
        result = default
    elif isinstance(value, bool):
        raise ValueError(f"{name} 必须是整数。")
    elif isinstance(value, int):
        result = value
    elif isinstance(value, str) and re.fullmatch(r"-?\d+", value.strip()):
        result = int(value.strip())
    else:
        raise ValueError(f"{name} 必须是整数。")
    if minimum is not None and result < minimum:
        raise ValueError(f"{name} 不能小于 {minimum}。")
    if maximum is not None and result > maximum:
        raise ValueError(f"{name} 不能大于 {maximum}。")
    return result


def number_value(
    value: Any,
    name: str,
    *,
    default: float,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if value is None:
        result = default
    elif isinstance(value, bool):
        raise ValueError(f"{name} 必须是数字。")
    elif isinstance(value, (int, float)):
        result = float(value)
    elif isinstance(value, str):
        try:
            result = float(value.strip())
        except ValueError as exc:
            raise ValueError(f"{name} 必须是数字。") from exc
    else:
        raise ValueError(f"{name} 必须是数字。")
    if not math.isfinite(result):
        raise ValueError(f"{name} 必须是有限数字。")
    if minimum is not None and result < minimum:
        raise ValueError(f"{name} 不能小于 {minimum:g}。")
    if maximum is not None and result > maximum:
        raise ValueError(f"{name} 不能大于 {maximum:g}。")
    return result


def boolean_value(value: Any, name: str, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    raise ValueError(f"{name} 必须是布尔值。")


def resource_id(value: Any, name: str) -> str:
    result = string_value(value, name, required=True, maximum=128)
    if not RESOURCE_ID_PATTERN.fullmatch(result):
        raise ValueError(f"{name} 格式无效。")
    return result


def choice_value(
    value: Any,
    name: str,
    choices: set[str],
    *,
    default: str,
) -> str:
    result = string_value(value, name, default=default).casefold()
    if result not in choices:
        raise ValueError(f"{name} 只允许：{', '.join(sorted(choices))}。")
    return result


def string_list(
    value: Any,
    name: str,
    *,
    maximum_items: int | None = None,
    maximum_length: int | None = None,
) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{name} 必须是数组。")
    if maximum_items is not None and len(value) > maximum_items:
        raise ValueError(f"{name} 最多包含 {maximum_items} 项。")
    result = []
    for item in value:
        text = string_value(
            item,
            name,
            required=True,
            maximum=maximum_length,
        )
        result.append(text)
    return result


def _safe_string_list(value: Any, limit: int, item_limit: int = 160) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        clean_text(item, item_limit)
        for item in value[:limit]
        if clean_text(item, item_limit)
    ]


def _safe_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _safe_number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(float(value)) else None


def format_lora_catalog(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise DrawingGatewayToolError("Drawing Gateway 返回了无效的 LoRA 目录。")
    raw_existing = payload.get("existing")
    raw_managed = payload.get("managed")
    existing = raw_existing if isinstance(raw_existing, list) else []
    managed = raw_managed if isinstance(raw_managed, list) else []
    existing_items = []
    for item in existing[:30]:
        if not isinstance(item, dict):
            continue
        identifier = clean_text(item.get("identifier"), 1024)
        if not identifier:
            continue
        existing_items.append(
            {
                "source": "existing",
                "identifier": identifier,
                "name": clean_text(item.get("name"), 256),
                "alias": clean_text(item.get("alias"), 256) or None,
                "suggested_tags": _safe_string_list(
                    item.get("suggested_tags"), 20
                ),
            }
        )
    managed_items = []
    for item in managed[:30]:
        if not isinstance(item, dict):
            continue
        identifier = clean_text(item.get("identifier"), 128)
        if not identifier:
            continue
        managed_items.append(
            {
                "source": "managed",
                "identifier": identifier,
                "status": clean_text(item.get("status"), 32),
                "name": clean_text(item.get("name"), 256),
                "version_name": clean_text(item.get("version_name"), 256),
                "base_model": clean_text(item.get("base_model"), 128) or None,
                "a1111_name": clean_text(item.get("a1111_name"), 512),
                "file_name": clean_text(item.get("file_name"), 512),
                "size_bytes": _safe_int(item.get("size_bytes")),
                "sha256": clean_text(item.get("sha256"), 128) or None,
                "trained_words": _safe_string_list(
                    item.get("trained_words"), 20
                ),
            }
        )
    return {
        "existing": existing_items,
        "managed": managed_items,
        "counts": {
            "existing_total": len(existing),
            "existing_returned": len(existing_items),
            "managed_total": len(managed),
            "managed_returned": len(managed_items),
        },
        "usage": "后续生成必须使用这里返回的精确 source 和 identifier。",
    }


def _safe_example_prompt(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    prompt = clean_text(value.get("prompt"), 1400)
    if not prompt:
        return None
    result: dict[str, Any] = {
        "prompt": prompt,
        "negative_prompt": clean_text(value.get("negative_prompt"), 900),
    }
    sampler = clean_text(value.get("sampler"), 128)
    if sampler:
        result["sampler"] = sampler
    steps = _safe_int(value.get("steps"))
    if steps is not None:
        result["steps"] = steps
    cfg_scale = _safe_number(value.get("cfg_scale"))
    if cfg_scale is not None:
        result["cfg_scale"] = cfg_scale
    return result


def format_prompt_suggestions(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise DrawingGatewayToolError("Drawing Gateway 返回了无效的 prompt 建议。")
    examples = []
    raw_examples = payload.get("example_prompts")
    if isinstance(raw_examples, list):
        for item in raw_examples[:10]:
            cleaned = _safe_example_prompt(item)
            if cleaned:
                examples.append(cleaned)
    result: dict[str, Any] = {
        "trained_words": _safe_string_list(payload.get("trained_words"), 40),
        "suggested_tags": _safe_string_list(payload.get("suggested_tags"), 40),
        "example_prompts": examples,
    }
    presets = payload.get("presets")
    if isinstance(presets, list):
        preset_items = []
        for item in presets[:15]:
            if not isinstance(item, dict):
                continue
            preset_id = clean_text(item.get("id"), 128)
            if not preset_id:
                continue
            preset_items.append(
                {
                    "id": preset_id,
                    "name": clean_text(item.get("name"), 256),
                    "prompt": clean_text(item.get("prompt"), 1600),
                    "negative_prompt": clean_text(
                        item.get("negative_prompt"), 1000
                    ),
                    "tags": _safe_string_list(item.get("tags"), 30),
                    "enabled": bool(item.get("enabled")),
                }
            )
        result["presets"] = preset_items
        result["preset_total"] = len(presets)
    version_id = _safe_int(payload.get("model_version_id"))
    if version_id is not None:
        result["model_version_id"] = version_id
        result["base_model"] = clean_text(payload.get("base_model"), 256) or None
    return result


def format_civitai_search(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise DrawingGatewayToolError("Drawing Gateway 返回了无效的 Civitai 搜索结果。")
    raw_items = payload.get("items")
    items = raw_items if isinstance(raw_items, list) else []
    result_items = []
    for item in items[:30]:
        if not isinstance(item, dict):
            continue
        model_id = _safe_int(item.get("id"))
        if model_id is None:
            continue
        raw_versions = item.get("versions")
        versions = raw_versions if isinstance(raw_versions, list) else []
        version_items = []
        for version in versions[:8]:
            if not isinstance(version, dict):
                continue
            version_id = _safe_int(version.get("id"))
            if version_id is None:
                continue
            raw_files = version.get("files")
            files = raw_files if isinstance(raw_files, list) else []
            file_items = []
            for file_item in files[:8]:
                if not isinstance(file_item, dict):
                    continue
                file_id = _safe_int(file_item.get("id"))
                if file_id is None:
                    continue
                file_items.append(
                    {
                        "id": file_id,
                        "name": clean_text(file_item.get("name"), 512),
                        "size_bytes": _safe_int(file_item.get("size_bytes")),
                        "primary": bool(file_item.get("primary")),
                        "sha256": clean_text(file_item.get("sha256"), 128)
                        or None,
                    }
                )
            version_items.append(
                {
                    "id": version_id,
                    "name": clean_text(version.get("name"), 256),
                    "base_model": clean_text(
                        version.get("base_model"), 256
                    )
                    or None,
                    "trained_words": _safe_string_list(
                        version.get("trained_words"), 30
                    ),
                    "files": file_items,
                    "files_total": len(files),
                }
            )
        result_items.append(
            {
                "id": model_id,
                "name": clean_text(item.get("name"), 256),
                "creator": clean_text(item.get("creator"), 256) or None,
                "nsfw": bool(item.get("nsfw")),
                "tags": _safe_string_list(item.get("tags"), 30),
                "versions": version_items,
                "versions_total": len(versions),
            }
        )
    return {
        "items": result_items,
        "total_received": len(items),
        "returned": len(result_items),
        "next_cursor": clean_text(payload.get("next_cursor"), 512) or None,
    }


def format_download_accepted(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise DrawingGatewayToolError("Drawing Gateway 返回了无效的下载批次。")
    batch_id = clean_text(payload.get("batch_id"), 128)
    raw_ids = payload.get("download_ids")
    download_ids = _safe_string_list(raw_ids, 20, 128)
    if not batch_id or not download_ids:
        raise DrawingGatewayToolError("Drawing Gateway 下载批次缺少任务 ID。")
    return {
        "batch_id": batch_id,
        "download_ids": download_ids,
        "status": "queued",
    }


def _safe_task_error(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    code = _safe_code(value.get("code"))
    if not code:
        return None
    return {
        "code": code,
        "description": ERROR_DESCRIPTIONS.get(code, "网关任务失败"),
    }


def _safe_download_item(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    download_id = clean_text(value.get("id"), 128)
    if not download_id:
        return None
    result_value = value.get("result")
    safe_result = None
    if isinstance(result_value, dict):
        safe_result = {
            "managed_lora_id": clean_text(
                result_value.get("managed_lora_id"), 128
            )
            or None,
            "already_installed": bool(result_value.get("already_installed")),
            "a1111_name": clean_text(result_value.get("a1111_name"), 512)
            or None,
            "size_bytes": _safe_int(result_value.get("size_bytes")),
            "sha256": clean_text(result_value.get("sha256"), 128) or None,
            "warning": bool(result_value.get("warning")),
        }
    return {
        "id": download_id,
        "batch_id": clean_text(value.get("batch_id"), 128),
        "status": clean_text(value.get("status"), 32),
        "model_version_id": _safe_int(value.get("model_version_id")),
        "file_id": _safe_int(value.get("file_id")),
        "managed_lora_id": clean_text(value.get("managed_lora_id"), 128)
        or None,
        "result": safe_result,
        "error": _safe_task_error(value.get("error")),
        "created_at": clean_text(value.get("created_at"), 64),
        "started_at": clean_text(value.get("started_at"), 64) or None,
        "completed_at": clean_text(value.get("completed_at"), 64) or None,
    }


def format_download_status(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        raw_items = payload["items"]
        items = []
        for item in raw_items[:100]:
            cleaned = _safe_download_item(item)
            if cleaned:
                items.append(cleaned)
        return {
            "items": items,
            "total_received": len(raw_items),
            "returned": len(items),
        }
    item = _safe_download_item(payload)
    if item is None:
        raise DrawingGatewayToolError("Drawing Gateway 返回了无效的下载状态。")
    return item


def format_storage(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise DrawingGatewayToolError("Drawing Gateway 返回了无效的容量状态。")
    ready_files = _safe_int(payload.get("ready_files"))
    used_bytes = _safe_int(payload.get("used_bytes"))
    maximum_files = _safe_int(payload.get("maximum_files"))
    maximum_bytes = _safe_int(payload.get("maximum_bytes"))
    if None in {ready_files, used_bytes, maximum_files, maximum_bytes}:
        raise DrawingGatewayToolError("Drawing Gateway 容量状态缺少必要字段。")
    file_usage_percent = (
        round(ready_files / maximum_files * 100, 2) if maximum_files else None
    )
    byte_usage_percent = (
        round(used_bytes / maximum_bytes * 100, 2) if maximum_bytes else None
    )
    return {
        "ready_files": ready_files,
        "used_bytes": used_bytes,
        "maximum_files": maximum_files,
        "maximum_bytes": maximum_bytes,
        "file_usage_percent": file_usage_percent,
        "byte_usage_percent": byte_usage_percent,
    }


def generation_payload(args: dict[str, Any]) -> dict[str, Any]:
    prompt = string_value(args.get("prompt"), "prompt")
    negative_prompt = string_value(
        args.get("negative_prompt"), "negative_prompt"
    )
    preset_ids = string_list(
        args.get("prompt_preset_ids"),
        "prompt_preset_ids",
    )
    if not prompt and not preset_ids:
        raise ValueError("prompt 和 prompt_preset_ids 至少需要提供一个。")
    width = integer_value(
        args.get("width"), "width", default=1024, minimum=64
    )
    height = integer_value(
        args.get("height"), "height", default=1024, minimum=64
    )
    if width % 8 or height % 8:
        raise ValueError("width 和 height 必须是 8 的倍数。")
    raw_loras = args.get("loras")
    if raw_loras is None:
        raw_loras = []
    if not isinstance(raw_loras, list):
        raise ValueError("loras 必须是数组。")
    loras = []
    for index, item in enumerate(raw_loras):
        if not isinstance(item, dict):
            raise ValueError(f"loras[{index}] 必须是对象。")
        if item.get("source") is None:
            raise ValueError(f"loras[{index}].source 不能为空。")
        source = choice_value(
            item.get("source"),
            f"loras[{index}].source",
            {"existing", "managed"},
            default="existing",
        )
        identifier = string_value(
            item.get("identifier"),
            f"loras[{index}].identifier",
            required=True,
            maximum=1024,
        )
        if any(character in identifier for character in "<>:\r\n"):
            raise ValueError(
                f"loras[{index}].identifier 不能包含尖括号、冒号或换行。"
            )
        loras.append(
            {
                "source": source,
                "identifier": identifier,
                "weight": number_value(
                    item.get("weight"),
                    f"loras[{index}].weight",
                    default=0.8,
                    minimum=-2.0,
                    maximum=2.0,
                ),
                "add_trained_words": boolean_value(
                    item.get("add_trained_words"),
                    f"loras[{index}].add_trained_words",
                    default=False,
                ),
            }
        )
    return {
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "prompt_preset_ids": preset_ids,
        "loras": loras,
        "width": width,
        "height": height,
        "steps": integer_value(
            args.get("steps"), "steps", default=28, minimum=1
        ),
        "cfg_scale": number_value(
            args.get("cfg_scale"),
            "cfg_scale",
            default=5.0,
            minimum=1.0,
            maximum=30.0,
        ),
        "sampler_name": string_value(
            args.get("sampler_name"),
            "sampler_name",
            default="Euler a",
            required=True,
            maximum=128,
        ),
        "seed": integer_value(
            args.get("seed"),
            "seed",
            default=-1,
            minimum=-1,
            maximum=4_294_967_295,
        ),
        "batch_size": integer_value(
            args.get("batch_size"),
            "batch_size",
            default=1,
            minimum=1,
            maximum=8,
        ),
        "n_iter": integer_value(
            args.get("n_iter"),
            "n_iter",
            default=1,
            minimum=1,
            maximum=8,
        ),
    }


def _safe_generation_parameters(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for key in (
        "width",
        "height",
        "steps",
        "cfg_scale",
        "sampler_name",
        "seed",
        "batch_size",
        "n_iter",
    ):
        item = value.get(key)
        if isinstance(item, str):
            result[key] = clean_text(item, 128)
        elif isinstance(item, (int, float)) and not isinstance(item, bool):
            result[key] = item
    raw_loras = value.get("loras")
    if isinstance(raw_loras, list):
        loras = []
        for item in raw_loras[:20]:
            if not isinstance(item, dict):
                continue
            lora: dict[str, Any] = {}
            source = clean_text(item.get("source"), 32)
            identifier = clean_text(item.get("identifier"), 1024)
            a1111_name = clean_text(item.get("a1111_name"), 512)
            weight = _safe_number(item.get("weight"))
            if source:
                lora["source"] = source
            if identifier:
                lora["identifier"] = identifier
            if a1111_name:
                lora["a1111_name"] = a1111_name
            if weight is not None:
                lora["weight"] = weight
            if isinstance(item.get("add_trained_words"), bool):
                lora["add_trained_words"] = item["add_trained_words"]
            if lora:
                loras.append(lora)
        result["loras"] = loras
    return result


def _merged_generation_parameters(
    request_value: Any,
    result_value: Any,
) -> dict[str, Any]:
    request_parameters = _safe_generation_parameters(request_value)
    result_parameters = _safe_generation_parameters(result_value)
    request_loras = request_parameters.pop("loras", [])
    result_loras = result_parameters.pop("loras", [])
    request_parameters.update(result_parameters)
    if isinstance(request_loras, list) or isinstance(result_loras, list):
        merged_loras = []
        maximum = max(
            len(request_loras) if isinstance(request_loras, list) else 0,
            len(result_loras) if isinstance(result_loras, list) else 0,
        )
        for index in range(maximum):
            item = {}
            if isinstance(request_loras, list) and index < len(request_loras):
                item.update(request_loras[index])
            if isinstance(result_loras, list) and index < len(result_loras):
                item.update(result_loras[index])
            merged_loras.append(item)
        request_parameters["loras"] = merged_loras
    return request_parameters


def format_generation_result(
    job_id: str,
    payload: Any,
    request_value: Any = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise DrawingGatewayToolError("Drawing Gateway 返回了无效的生成结果。")
    raw_images = payload.get("images")
    images = raw_images if isinstance(raw_images, list) else []
    image_items = []
    for item in images[:64]:
        if not isinstance(item, dict):
            continue
        url = clean_text(item.get("url"), 4096, collapse=False)
        password = clean_text(item.get("password"), 512, collapse=False)
        expires_at = clean_text(item.get("expires_at"), 128)
        if not url or not password or not expires_at:
            continue
        try:
            parsed_url = urlsplit(url)
        except ValueError:
            continue
        if parsed_url.scheme.casefold() not in {"http", "https"} or not parsed_url.netloc:
            continue
        image_items.append(
            {
                "url": url,
                "password": password,
                "expires_at": expires_at,
            }
        )
    raw_seeds = payload.get("seeds")
    seeds = (
        [
            item
            for item in raw_seeds
            if isinstance(item, int) and not isinstance(item, bool)
        ]
        if isinstance(raw_seeds, list)
        else []
    )
    return {
        "job_id": job_id,
        "status": "succeeded",
        "images": image_items,
        "seeds": seeds,
        "parameters": _merged_generation_parameters(
            request_value,
            payload.get("parameters"),
        ),
    }


def _format_generation_job(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise DrawingGatewayToolError("Drawing Gateway 返回了无效的生成任务状态。")
    job_id = clean_text(payload.get("id") or payload.get("job_id"), 128)
    status = clean_text(payload.get("status"), 32)
    if not job_id or status not in ACTIVE_GENERATION_STATUSES | FINAL_GENERATION_STATUSES:
        raise DrawingGatewayToolError("Drawing Gateway 生成任务状态缺少必要字段。")
    return {
        "job_id": job_id,
        "status": status,
        "position": _safe_int(payload.get("position")),
        "cancel_requested": bool(payload.get("cancel_requested")),
        "error": _safe_task_error(payload.get("error")),
        "created_at": clean_text(payload.get("created_at"), 64) or None,
        "started_at": clean_text(payload.get("started_at"), 64) or None,
        "completed_at": clean_text(payload.get("completed_at"), 64) or None,
    }


async def generation_status(job_id: str) -> dict[str, Any]:
    escaped_id = quote(resource_id(job_id, "job_id"), safe="")
    job_payload = await request_json("GET", f"/v1/jobs/{escaped_id}")
    job = _format_generation_job(job_payload)
    if job["status"] == "succeeded":
        result_payload = await request_json(
            "GET", f"/v1/jobs/{escaped_id}/result"
        )
        request_value = (
            job_payload.get("request")
            if isinstance(job_payload, dict)
            else None
        )
        return format_generation_result(
            job["job_id"],
            result_payload,
            request_value,
        )
    return job


async def submit_generation(args: dict[str, Any]) -> dict[str, Any]:
    body = generation_payload(args)
    accepted_payload = await request_json("POST", "/v1/jobs", body=body)
    try:
        return _format_generation_job(accepted_payload)
    except DrawingGatewayToolError as exc:
        raise DrawingGatewayToolError(
            "Drawing Gateway 返回了无效的任务接收响应。",
            exc.code,
        ) from exc


async def health_ready_report() -> tuple[str, str]:
    started = time.perf_counter()
    try:
        load_config()
    except DrawingGatewayToolError as exc:
        status = "SKIP" if exc.code == "not_configured" else "FAIL"
        return status, exc.public_message
    try:
        payload = await request_json("GET", "/health/ready")
    except DrawingGatewayToolError as exc:
        elapsed = int((time.perf_counter() - started) * 1000)
        return "FAIL", f"{exc.public_message} {elapsed}ms"
    elapsed = int((time.perf_counter() - started) * 1000)
    if not isinstance(payload, dict):
        return "FAIL", f"ready 响应格式无效 {elapsed}ms"
    status = clean_text(payload.get("status"), 32) or "unknown"
    raw_checks = payload.get("checks")
    checks = raw_checks if isinstance(raw_checks, dict) else {}
    check_text = " ".join(
        f"{clean_text(key, 64)}={clean_text(value, 64)}"
        for key, value in sorted(checks.items())
    )
    detail = f"status={status}"
    if check_text:
        detail += f" {check_text}"
    detail += f" {elapsed}ms"
    return ("OK" if status == "ok" else "FAIL"), detail
