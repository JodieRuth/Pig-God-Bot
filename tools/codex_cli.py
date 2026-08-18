from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit, urlunsplit

BOT_ROOT = Path(__file__).resolve().parent.parent
PROVIDER_ID = "local_onebot_active"
API_KEY_ENV = "LOCAL_ONEBOT_CODEX_API_KEY"
CODEX_LOCK = asyncio.Lock()


def definition(ctx: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "codex_cli_investigate",
            "description": "需要联网搜索或是复杂代码调查时使用。启动机器上的 Codex CLI，使用机器人当前启用的相同端点和模型、最高思考强度执行问题，只将 Codex 的最终回答回传。",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "要交给 Codex CLI 完整调查并回答的问题。",
                    }
                },
                "required": ["question"],
            },
        },
    }


def info(ctx: dict[str, Any]) -> dict[str, str]:
    item = definition(ctx)["function"]
    return {"name": str(item["name"]), "description": str(item["description"])}


def runtime_dir() -> Path:
    configured = os.getenv("CODEX_CLI_RUNTIME_DIR", "").strip()
    if not configured:
        return BOT_ROOT / ".codex-cli-runtime"
    path = Path(os.path.expandvars(configured)).expanduser()
    return path if path.is_absolute() else BOT_ROOT / path


def normalize_endpoint(url: str) -> tuple[str, list[tuple[str, str]]]:
    parsed = urlsplit(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("当前 LLM_API_URL 不是有效的 HTTP/HTTPS 地址")
    path = parsed.path.rstrip("/")
    lower_path = path.lower()
    for suffix in ("/chat/completions", "/responses"):
        if lower_path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    base_url = urlunsplit((parsed.scheme, parsed.netloc, path.rstrip("/"), "", ""))
    return base_url, parse_qsl(parsed.query, keep_blank_values=True)


def provider_label(base_url: str) -> str:
    parsed = urlsplit(base_url)
    if not parsed.hostname:
        return ""
    return f"{parsed.hostname}:{parsed.port}" if parsed.port else parsed.hostname


def toml_string(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def codex_config(model: str, base_url: str, query_params: list[tuple[str, str]], has_key: bool) -> str:
    lines = [
        f"model = {toml_string(model)}",
        f"model_provider = {toml_string(PROVIDER_ID)}",
        'model_reasoning_effort = "xhigh"',
        'model_reasoning_summary = "none"',
        'web_search = "live"',
        "hide_agent_reasoning = true",
        "check_for_update_on_startup = false",
        "windows_wsl_setup_acknowledged = true",
        'history.persistence = "none"',
        "",
        f"[model_providers.{PROVIDER_ID}]",
        'name = "Current local OneBot LLM"',
        f"base_url = {toml_string(base_url)}",
        'wire_api = "responses"',
        "requires_openai_auth = false",
    ]
    if has_key:
        lines.append(f"env_key = {toml_string(API_KEY_ENV)}")
    if query_params:
        lines.extend(["", f"[model_providers.{PROVIDER_ID}.query_params]"])
        for key, value in query_params:
            lines.append(f"{toml_string(key)} = {toml_string(value)}")
    return "\n".join(lines) + "\n"


def resolve_executable(value: str) -> Path | None:
    expanded = Path(os.path.expandvars(value.strip().strip('"'))).expanduser()
    if expanded.is_file():
        return expanded.resolve()
    located = shutil.which(value.strip().strip('"'))
    return Path(located).resolve() if located else None


def resolve_codex_launcher() -> Path | None:
    explicit = os.getenv("CODEX_CLI_PATH", "").strip()
    if explicit:
        return resolve_executable(explicit)
    global_cli = resolve_executable("codex")
    if global_cli:
        return global_cli
    local_script = runtime_dir() / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
    return local_script.resolve() if local_script.is_file() else None


def launcher_command(launcher: Path, args: list[str]) -> list[str]:
    suffix = launcher.suffix.lower()
    if suffix == ".py":
        return [sys.executable, str(launcher), *args]
    if suffix in {".js", ".cjs", ".mjs"}:
        node = shutil.which(os.getenv("CODEX_NODE_BIN", "node").strip() or "node")
        if not node:
            raise RuntimeError("找到本地 Codex CLI 脚本，但找不到 Node.js")
        return [node, str(launcher), *args]
    return [str(launcher), *args]


def configured_timeout() -> int:
    try:
        return max(30, int(os.getenv("CODEX_CLI_TIMEOUT_SECONDS", "1800")))
    except ValueError:
        return 1800


def configured_install_timeout() -> int:
    try:
        return max(60, int(os.getenv("CODEX_CLI_INSTALL_TIMEOUT_SECONDS", "900")))
    except ValueError:
        return 900


def clean_process_text(value: bytes, secrets: list[str], limit: int = 2400) -> str:
    text = value.decode("utf-8", errors="replace").replace("\x00", "").strip()
    for secret in secrets:
        if secret:
            text = text.replace(secret, "<redacted>")
    if len(text) > limit:
        text = text[-limit:]
    return text


async def install_local_codex(ctx: dict[str, Any]) -> tuple[Path | None, str]:
    if os.getenv("CODEX_CLI_AUTO_INSTALL", "1") == "0":
        return None, "服务器未找到 Codex CLI，且 CODEX_CLI_AUTO_INSTALL=0。"
    npm = resolve_executable(os.getenv("CODEX_NPM_BIN", "npm"))
    if npm is None:
        return None, "服务器未找到 npm，无法安装 Codex CLI。"
    target = runtime_dir()
    package = os.getenv("CODEX_CLI_NPM_PACKAGE", "@openai/codex@latest").strip() or "@openai/codex@latest"
    target.mkdir(parents=True, exist_ok=True)
    args = ["install", "--prefix", str(target), "--no-audit", "--no-fund", package]
    command = launcher_command(npm, args)
    timeout = configured_install_timeout()
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    ctx["log"](f"Codex CLI local runtime install start: package={package} timeout={timeout}s")
    try:
        proc = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(BOT_ROOT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=os.environ.copy(),
            creationflags=creationflags,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return None, f"安装 Codex CLI 超过 {timeout} 秒。"
    except Exception as exc:
        return None, f"安装 Codex CLI 失败：{ctx['exception_detail'](exc)}"
    if proc.returncode != 0:
        detail = clean_process_text(stderr or stdout, [])
        return None, f"npm 安装 Codex CLI 失败：{detail or f'exit code {proc.returncode}'}"
    local_script = target / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
    if not local_script.is_file():
        return None, "npm 安装完成但没有找到 Codex CLI 入口。"
    ctx["log"](f"Codex CLI local runtime installed: {local_script}")
    return local_script.resolve(), ""


async def execute(args: dict[str, Any], runtime: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    question = str(args.get("question") or "").strip()
    if not question:
        return {"ok": False, "content": "Codex CLI 调查失败：缺少 question。"}
    active_api_config = ctx.get("active_api_config")
    active_model = ctx.get("active_model")
    if not callable(active_api_config) or not callable(active_model):
        return {"ok": False, "content": "Codex CLI 调查失败：机器人没有提供当前 LLM 配置。"}
    llm_config = active_api_config("llm")
    endpoint = str(llm_config.get("url") or "").strip()
    api_key = str(llm_config.get("key") or "")
    model = str(active_model("llm") or "").strip()
    if not endpoint or not model:
        return {"ok": False, "content": "Codex CLI 调查失败：当前 LLM 端点或模型为空。"}
    try:
        base_url, query_params = normalize_endpoint(endpoint)
    except ValueError as exc:
        return {"ok": False, "content": f"Codex CLI 调查失败：{exc}"}
    timeout = configured_timeout()
    async with CODEX_LOCK:
        launcher = resolve_codex_launcher()
        if launcher is None:
            if os.getenv("CODEX_CLI_PATH", "").strip():
                return {"ok": False, "content": "Codex CLI 调查失败：CODEX_CLI_PATH 指向的文件不存在。"}
            launcher, install_error = await install_local_codex(ctx)
            if launcher is None:
                return {"ok": False, "content": f"Codex CLI 调查失败：{install_error}"}
        with tempfile.TemporaryDirectory(prefix="local_onebot_codex_") as temp_dir_value:
            temp_dir = Path(temp_dir_value)
            output_path = temp_dir / "final.txt"
            config_path = temp_dir / "config.toml"
            config_path.write_text(codex_config(model, base_url, query_params, bool(api_key)), encoding="utf-8")
            cli_args = [
                "exec",
                "--ephemeral",
                "--skip-git-repo-check",
                "--dangerously-bypass-approvals-and-sandbox",
                "--color",
                "never",
                "--output-last-message",
                str(output_path),
                "--model",
                model,
                "-",
            ]
            try:
                command = launcher_command(launcher, cli_args)
            except RuntimeError as exc:
                return {"ok": False, "content": f"Codex CLI 调查失败：{exc}"}
            env = os.environ.copy()
            env["CODEX_HOME"] = str(temp_dir)
            env["NO_COLOR"] = "1"
            env["PYTHONUTF8"] = "1"
            if api_key:
                env[API_KEY_ENV] = api_key
            provider = provider_label(base_url)
            ctx["log"](f"Codex CLI tool start: model={model} provider={provider} timeout={timeout}s")
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            try:
                proc = await asyncio.create_subprocess_exec(
                    *command,
                    cwd=str(BOT_ROOT),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                    creationflags=creationflags,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(question.encode("utf-8")), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                return {"ok": False, "content": f"Codex CLI 调查失败：超过 {timeout} 秒未完成。"}
            except Exception as exc:
                return {"ok": False, "content": f"Codex CLI 调查失败：{ctx['exception_detail'](exc)}"}
            if proc.returncode != 0:
                detail = clean_process_text(stderr or stdout, [api_key, endpoint, *[value for _, value in query_params]])
                if not detail:
                    detail = f"exit code {proc.returncode}"
                return {
                    "ok": False,
                    "content": f"Codex CLI 调查失败：{detail}\n当前活动端点必须兼容 OpenAI Responses API。",
                }
            if not output_path.is_file():
                return {"ok": False, "content": "Codex CLI 调查失败：进程完成但没有生成最终回答文件。"}
            answer = output_path.read_text(encoding="utf-8", errors="replace").replace("\x00", "").strip()
            if not answer:
                return {"ok": False, "content": "Codex CLI 调查失败：Codex 最终回答为空。"}
            ctx["log"](f"Codex CLI tool completed: model={model} answer_chars={len(answer)}")
            return {
                "ok": True,
                "content": answer,
                "model": model,
                "provider": provider,
            }
