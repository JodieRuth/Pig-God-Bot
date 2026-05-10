from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any

SCRIPT_PATH = Path(__file__).with_name("animetrace_headless.py")
HOST_DIR = Path(__file__).with_name("browser_automation_host")
HOST_PROJECT = HOST_DIR / "browser_automation_host.csproj"
HOST_DLL = HOST_DIR / "bin" / "Release" / "net9.0-windows" / "browser_automation_host.dll"
DEFAULT_URL = os.getenv("ANIMETRACE_URL", "https://ai.animedb.cn/en/")
DEFAULT_WAIT_MS = int(os.getenv("ANIMETRACE_WAIT_MS", "20000"))
DEFAULT_CAPTURE_JSON = os.getenv("ANIMETRACE_CAPTURE_JSON", "0") == "1"
DEFAULT_BROWSER_PATH = os.getenv("ANIMETRACE_BROWSER_PATH", "").strip() or None
DEFAULT_BACKEND = os.getenv("ANIMETRACE_BACKEND", "webview2").strip().lower()


def definition(ctx: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "animetrace_character",
            "description": "识别输入图片里的动漫、游戏或插画人物来源与角色。可以使用 image_indexes 指定图1、图2等图片编号。强制规则：只要当前有可用图片，且用户问题涉及图中人物是谁、角色是谁、出自哪里、人物身份、角色来源、像谁、叫什么，必须先调用本工具获取识别结果，不得仅根据上下文、文件名、画风、模型视觉能力或聊天历史猜测后直接回答。",
            "parameters": {
                "type": "object",
                "properties": {
                    "image_indexes": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "要识别的人物图片编号列表，例如 [1]。编号来自输入图片顺序：图1 是第一张输入图片，图2 是第二张。通常只传最相关的一张。",
                    }
                },
            },
        },
    }


def info(ctx: dict[str, Any]) -> dict[str, str]:
    item = definition(ctx).get("function", {})
    return {
        "name": str(item.get("name") or "animetrace_character"),
        "description": str(item.get("description") or ""),
    }


def select_images(images: list[dict[str, Any]], image_indexes: list[Any]) -> list[dict[str, Any]]:
    if not image_indexes:
        return images[:1]
    selected: list[dict[str, Any]] = []
    for value in image_indexes:
        try:
            index = int(value)
        except (TypeError, ValueError):
            continue
        if 1 <= index <= len(images):
            record = images[index - 1]
            if record not in selected:
                selected.append(record)
    return selected[:1]


async def ensure_host_built(ctx: dict[str, Any]) -> None:
    if HOST_DLL.exists():
        return
    if not HOST_PROJECT.exists():
        raise RuntimeError("WebView2 宿主项目不存在")
    ctx["log"]("AnimeTrace WebView2 host build start")
    proc = await asyncio.create_subprocess_exec(
        "dotnet",
        "build",
        str(HOST_PROJECT),
        "-c",
        "Release",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    stdout_text = stdout.decode("utf-8", errors="replace").strip()
    stderr_text = stderr.decode("utf-8", errors="replace").strip()
    if stdout_text:
        ctx["log"](f"AnimeTrace WebView2 host build stdout:\n{stdout_text[:6000]}")
    if stderr_text:
        ctx["log"](f"AnimeTrace WebView2 host build stderr:\n{stderr_text[:6000]}")
    if proc.returncode != 0 or not HOST_DLL.exists():
        detail = sanitize_child_error(stderr_text or stdout_text or f"exit code {proc.returncode}")
        raise RuntimeError(f"WebView2 宿主编译失败：{detail}")


async def run_animetrace_webview2(image: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    await ensure_host_built(ctx)
    output_dir = Path(ctx.get("output_dir") or SCRIPT_PATH.parent.parent / "outputs")
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / f"animetrace_{uuid.uuid4().hex}.json"
    command = [
        "dotnet",
        str(HOST_DLL),
        "--task",
        "animetrace",
        "--image",
        str(image),
        "--url",
        DEFAULT_URL,
        "--wait-ms",
        str(DEFAULT_WAIT_MS),
        "--output-json",
        str(result_path),
    ]
    if DEFAULT_CAPTURE_JSON:
        command.append("--capture-json")
    env = os.environ.copy()
    env["DOTNET_CLI_UI_LANGUAGE"] = "zh-CN"
    ctx["log"](f"AnimeTrace WebView2 host start: {' '.join(command)}")
    proc = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    timeout = max(DEFAULT_WAIT_MS / 1000 + 45, 75)
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise TimeoutError(f"AnimeTrace WebView2 宿主超过 {int(timeout)} 秒未完成")
    stdout_text = stdout.decode("utf-8", errors="replace").strip()
    stderr_text = stderr.decode("utf-8", errors="replace").strip()
    if stdout_text:
        ctx["log"](f"AnimeTrace WebView2 host stdout:\n{stdout_text[:6000]}")
    if stderr_text:
        ctx["log"](f"AnimeTrace WebView2 host stderr:\n{stderr_text[:6000]}")
    if proc.returncode != 0:
        detail = sanitize_child_error(stderr_text or stdout_text or f"exit code {proc.returncode}")
        raise RuntimeError(f"AnimeTrace WebView2 宿主失败：{detail}")
    if not result_path.exists():
        raise RuntimeError("AnimeTrace WebView2 宿主没有生成结果文件")
    try:
        with result_path.open("r", encoding="utf-8") as f:
            result = json.load(f)
        if isinstance(result, dict) and result.get("error"):
            raise RuntimeError(str(result.get("message") or result.get("error") or "WebView2 宿主返回错误"))
        return result
    finally:
        result_path.unlink(missing_ok=True)


async def run_animetrace_playwright(image: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    output_dir = Path(ctx.get("output_dir") or SCRIPT_PATH.parent.parent / "outputs")
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / f"animetrace_{uuid.uuid4().hex}.json"
    command = [
        sys.executable,
        str(SCRIPT_PATH),
        str(image),
        "--url",
        DEFAULT_URL,
        "--wait-ms",
        str(DEFAULT_WAIT_MS),
        "--output-json",
        str(result_path),
    ]
    if DEFAULT_BROWSER_PATH:
        command.extend(["--browser-path", DEFAULT_BROWSER_PATH])
    if DEFAULT_CAPTURE_JSON:
        command.append("--capture-json")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    ctx["log"](f"AnimeTrace Playwright subprocess start: {' '.join(command)}")
    proc = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    timeout = max(DEFAULT_WAIT_MS / 1000 + 30, 60)
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise TimeoutError(f"AnimeTrace 子进程超过 {int(timeout)} 秒未完成")
    stdout_text = stdout.decode("utf-8", errors="replace").strip()
    stderr_text = stderr.decode("utf-8", errors="replace").strip()
    if stdout_text:
        ctx["log"](f"AnimeTrace Playwright subprocess stdout:\n{stdout_text[:6000]}")
    if stderr_text:
        ctx["log"](f"AnimeTrace Playwright subprocess stderr:\n{stderr_text[:6000]}")
    if proc.returncode != 0:
        detail = sanitize_child_error(stderr_text or stdout_text or f"exit code {proc.returncode}")
        raise RuntimeError(f"AnimeTrace 子进程失败：{detail}")
    if not result_path.exists():
        raise RuntimeError("AnimeTrace 子进程没有生成结果文件")
    try:
        with result_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    finally:
        result_path.unlink(missing_ok=True)


async def run_animetrace(image: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    if DEFAULT_BACKEND == "playwright":
        return await run_animetrace_playwright(image, ctx)
    return await run_animetrace_webview2(image, ctx)



def short_line(value: Any, limit: int = 80) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def format_candidate(item: dict[str, Any]) -> str | None:
    work = item.get("work") or item.get("anime") or item.get("title") or item.get("name")
    character = item.get("character") or item.get("person") or item.get("role") or item.get("nickname")
    similarity = item.get("similarity") or item.get("score") or item.get("prob") or item.get("confidence")
    if isinstance(work, (list, dict)) or isinstance(character, (list, dict)):
        return None
    if not work and not character:
        return None
    parts = [f"作品：{short_line(work, 40) if work else '未知'}", f"角色：{short_line(character, 40) if character else '未知'}"]
    if similarity is not None:
        parts.append(f"相似度 {short_line(similarity, 24)}")
    return " ".join(parts)


def collect_candidates(value: Any, limit: int = 5) -> list[str]:
    candidates: list[str] = []

    def walk(item: Any) -> None:
        if len(candidates) >= limit:
            return
        if isinstance(item, dict):
            line = format_candidate(item)
            if line and line not in candidates:
                candidates.append(line)
            for key in ("data", "result", "results", "docs", "list", "items", "character", "characters"):
                if key in item:
                    walk(item[key])
        elif isinstance(item, list):
            for child in item:
                walk(child)
                if len(candidates) >= limit:
                    break

    walk(value)
    return candidates


def collect_page_candidates(body_text: str, limit: int = 5) -> list[str]:
    lines = []
    for raw in str(body_text or "").splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if line and line not in lines:
            lines.append(line)
    try:
        start = lines.index("Search result") + 1
    except ValueError:
        return []
    stop_markers = {"Error Feedback", "📢 New Notice!", "New Notice!", "Notice Board", "Got it", "@2024 AnimeTrace"}
    noise = {"Click the character name to view related images", "Results will appear here after uploading an image"}
    useful = []
    for line in lines[start:]:
        if line in stop_markers:
            break
        if line in noise:
            continue
        if line.lower().startswith("error feedback"):
            break
        useful.append(line)
    candidates = []
    for index in range(0, len(useful) - 1, 2):
        character = useful[index]
        work = useful[index + 1]
        if character and work:
            item = f"作品：{short_line(work, 40)} 角色：{short_line(character, 40)}"
            if item not in candidates:
                candidates.append(item)
        if len(candidates) >= limit:
            break
    return candidates


def parse_search_json(text: str) -> Any | None:
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def summarize_body(body_text: str, limit: int = 1800) -> str:
    lines = []
    banned_prefixes = ("GET ", "POST ", "OPTIONS ", "HEAD ", "RESP ", "http://", "https://")
    for raw in body_text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            continue
        lower = line.lower()
        if line.startswith(banned_prefixes) or "animedb.cn" in lower or "animetrace" in lower or lower.startswith("data:image"):
            continue
        if line in lines:
            continue
        lines.append(line)
        if len("\n".join(lines)) >= limit:
            break
    return "\n".join(lines)[:limit]


def sanitize_child_error(text: str, limit: int = 300) -> str:
    text = str(text).replace("\r", " ").replace("\n", " ").strip()
    if not text:
        return "未知错误"
    text = re.sub(r"Traceback \(most recent call last\):.*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"File \"[^\"]+\"", 'File "<path redacted>"', text)
    text = re.sub(r"[A-Za-z]:\\(?:[^\\\s]+\\)*[^\\\s]+", "<path redacted>", text)
    text = re.sub(r"\\\\[^\\\s]+\\(?:[^\\\s]+\\)*[^\\\s]+", "<path redacted>", text)
    text = re.sub(r"\s+", " ", text).strip()
    if "Traceback" in text:
        text = text.split("Traceback", 1)[0].strip()
    return text[:limit] + ("..." if len(text) > limit else "")


def result_preview(result: dict[str, Any]) -> str:
    search_response = result.get("search_response") if isinstance(result.get("search_response"), dict) else {}
    search_text = str(search_response.get("text") or "") if isinstance(search_response, dict) else ""
    parsed = parse_search_json(search_text)
    candidates = collect_candidates(parsed) if parsed is not None else []
    if not candidates:
        candidates = collect_page_candidates(str(result.get("body_text") or ""))
    if candidates:
        lines = ["可能结果："]
        for index, item in enumerate(candidates, start=1):
            lines.append(f"{index}. {item}")
        return "\n".join(lines)
    if parsed is not None:
        return "没有找到任何可能符合的角色。"
    body_summary = summarize_body(str(result.get("body_text") or ""))
    if body_summary:
        return body_summary
    if search_text:
        return search_text[:1800]
    return "AnimeTrace 没有返回可读识别结果。"


async def execute(args: dict[str, Any], runtime: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    images = select_images(runtime.get("images", []), args.get("image_indexes") or [])
    if not images:
        return {"ok": False, "content": "AnimeTrace 识别失败：当前没有可用图片。"}
    image = ctx["image_path"](images[0])
    if not image.exists():
        return {"ok": False, "content": "AnimeTrace 识别失败：图片文件不存在或已过期。"}
    try:
        result = await run_animetrace(image, ctx)
    except Exception as exc:
        return {"ok": False, "content": f"AnimeTrace 识别失败：{ctx['exception_detail'](exc)}"}
    content = f"AnimeTrace 识别完成，图片：{image.name}\n{result_preview(result)}"
    return {"ok": True, "content": content, "raw_result": result, "image_path": str(image)}
