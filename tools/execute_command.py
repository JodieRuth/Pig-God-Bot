from __future__ import annotations

import asyncio
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

MAX_OUTPUT_CHARS = 20000
DEFAULT_TIMEOUT_SECONDS = 30
MAX_TIMEOUT_SECONDS = 120
SYSTEM_PROXY_ENV_KEYS = ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy")
SCRIPT_SUFFIXES = {".bat", ".cmd", ".ps1", ".psm1", ".vbs", ".js", ".jse", ".wsf", ".py", ".sh"}
DANGEROUS_PATTERNS = [
    r"\bformat\b",
    r"\bdiskpart\b",
    r"\bbcdedit\b",
    r"\breg\s+(?:add|delete|import|save|restore)\b",
    r"\bshutdown\b",
    r"\brestart-computer\b",
    r"\bstop-computer\b",
    r"\btaskkill\b",
    r"\bsc\s+(?:delete|stop|config)\b",
    r"\bnet\s+user\b",
    r"\bnet\s+localgroup\b",
    r"\bset-executionpolicy\b",
    r"\binvoke-expression\b",
    r"\biex\b",
    r"\binvoke-webrequest\b.*\|",
    r"\biwr\b.*\|",
    r"\bcurl\b.*\|",
    r"\brm\s+-rf\s+(?:/|[a-z]:)",
    r"\bremove-item\b[^\n]*(?:[a-z]:\\|/|\$env:|\$home)",
    r"\bremove-item\b[^\n]*(?:-recurse|-r)",
    r"\bdel\b[^\n]*(?:[a-z]:\\|\\windows\\|\\users\\)",
    r"\brmdir\b[^\n]*(?:[a-z]:\\|\\windows\\|\\users\\)",
]
SANDBOX_ESCAPE_PATTERNS = [
    r"\.\.",
    r"\bcd\s+(?:/d\s+)?(?:[a-z]:\\|\\\\|/)",
    r"\bpushd\s+(?:[a-z]:\\|\\\\|/)",
    r"\bcopy\b[^\n]*(?:[a-z]:\\|\\\\)",
    r"\bxcopy\b[^\n]*(?:[a-z]:\\|\\\\)",
    r"\brobocopy\b",
    r"\bmove\b[^\n]*(?:[a-z]:\\|\\\\)",
    r"\bnew-item\b[^\n]*(?:[a-z]:\\|\\\\)",
    r"\bset-content\b[^\n]*(?:[a-z]:\\|\\\\)",
    r"\badd-content\b[^\n]*(?:[a-z]:\\|\\\\)",
    r"\bpython\b[^\n]*(?:\.\.|[a-z]:\\|\\\\)",
]


def temp_root(ctx: dict[str, Any]) -> Path:
    root = Path(ctx.get("tools_temp_dir") or Path(__file__).resolve().parent / "temp").resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def safe_relative_path(value: Any) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if not text or text in {".", "./"}:
        return ""
    return text.lstrip("/")


def sandbox_path(ctx: dict[str, Any], value: Any) -> Path:
    root = temp_root(ctx)
    relative = safe_relative_path(value)
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("路径越界：只能访问 tools/temp 内的文件") from exc
    return path


def clipped(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...输出过长，已截断到 {limit} 字符。"


def timeout_value(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = DEFAULT_TIMEOUT_SECONDS
    return max(1, min(number, MAX_TIMEOUT_SECONDS))


def normalize_proxy_url(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = "http://" + text
    return text


def windows_system_proxy() -> str:
    if not sys.platform.startswith("win"):
        return ""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
            enabled = int(winreg.QueryValueEx(key, "ProxyEnable")[0] or 0)
            if not enabled:
                return ""
            server = str(winreg.QueryValueEx(key, "ProxyServer")[0] or "").strip()
    except Exception:
        return ""
    if not server:
        return ""
    entries: dict[str, str] = {}
    for part in server.split(";"):
        if "=" in part:
            name, value = part.split("=", 1)
            entries[name.strip().lower()] = value.strip()
    return normalize_proxy_url(entries.get("https") or entries.get("http") or server.split(";", 1)[0])


def environment_proxy(env: dict[str, str]) -> str:
    for key in SYSTEM_PROXY_ENV_KEYS:
        value = normalize_proxy_url(env.get(key, ""))
        if value:
            return value
    return ""


def apply_system_proxy_env(env: dict[str, str]) -> str:
    proxy = environment_proxy(env) or windows_system_proxy()
    if not proxy:
        return ""
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env[key] = proxy
    git_config = [f"http.proxy={proxy}", f"https.proxy={proxy}"]
    existing = env.get("GIT_CONFIG_PARAMETERS", "").strip()
    injected = " ".join(f"'{item}'" for item in git_config)
    env["GIT_CONFIG_PARAMETERS"] = f"{existing} {injected}".strip()
    env.setdefault("GIT_SSL_NO_VERIFY", "false")
    return proxy


TOOL_DESCRIPTION = "在受限沙箱 tools/temp 内执行 cmd 或 PowerShell 命令，并返回 stdout/stderr/退出码。命令工作目录默认是 tools/temp，也可以通过 cwd 指定 tools/temp 内的子目录；不得访问、修改或依赖沙箱外路径。默认会为子进程注入系统代理环境变量；在 Windows 上会读取系统 Internet Settings 代理并转换为 HTTP_PROXY/HTTPS_PROXY，同时给 git 注入临时 http.proxy/https.proxy 配置，以便 git clone/fetch 默认走代理。LLM 必须拒绝任何可能操作 tools/temp 以外路径、修改系统设置、删除系统文件、停止进程/服务、提权、持久化、下载并管道执行远程代码、窃取信息或危害系统的命令，除非管理员明确要求且命令仍会被程序安全检查。执行任何 bat/cmd/ps1/py/js/vbs/sh 等脚本前，必须先用 temp_file_operation 读取并审查脚本内容，确认不会越界或危害系统；未审查脚本不得执行。适合临时计算、运行已审查脚本、处理由文件工具写入的临时文件，或进入 git clone 产生的子目录执行命令。命令可能有副作用，但只能影响 tools/temp。"


def definition(ctx: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "execute_command",
            "description": TOOL_DESCRIPTION,
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "要执行的命令文本。工作目录默认为 tools/temp，可用 cwd 指定 tools/temp 内子目录。",
                    },
                    "cwd": {
                        "type": "string",
                        "description": "可选工作目录，必须是 tools/temp 内的相对目录，例如 repo、repo/src。目录不存在会返回错误，不会自动越界。",
                    },
                    "shell": {
                        "type": "string",
                        "enum": ["powershell", "cmd"],
                        "description": "使用的 shell。默认 powershell。",
                    },
                    "timeout_seconds": {
                        "type": "integer",
                        "description": "超时时间，1-120 秒，默认 30。",
                    },
                    "script_reviewed": {
                        "type": "boolean",
                        "description": "仅当命令会执行 bat/cmd/ps1/py/js/vbs/sh 等脚本时使用。必须先用 temp_file_operation 读取并人工/模型审查脚本内容确认安全，再设为 true；否则程序会拒绝执行脚本。",
                    },
                },
                "required": ["command"],
            },
        },
    }


def info(ctx: dict[str, Any]) -> dict[str, str]:
    item = definition(ctx).get("function", {})
    return {"name": str(item.get("name") or "execute_command"), "description": str(item.get("description") or "")}


def shell_args(shell: str, command: str) -> list[str]:
    if shell == "cmd":
        return ["cmd.exe", "/d", "/s", "/c", command]
    return ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", command]


def admin_allowed(runtime: dict[str, Any], ctx: dict[str, Any]) -> bool:
    checker = ctx.get("is_admin_event")
    event = runtime.get("event") if isinstance(runtime.get("event"), dict) else {}
    return bool(checker(event)) if callable(checker) else False


def command_matches(patterns: list[str], command: str) -> str:
    for pattern in patterns:
        if re.search(pattern, command, flags=re.IGNORECASE):
            return pattern
    return ""


def referenced_script_paths(ctx: dict[str, Any], command: str) -> list[Path]:
    result: list[Path] = []
    for raw in re.findall(r"(?i)(?:^|\s|[&;])(?:\.\\|\.\/)?([^\s'\"]+\.(?:bat|cmd|ps1|psm1|vbs|js|jse|wsf|py|sh))", command):
        try:
            path = sandbox_path(ctx, raw)
        except Exception:
            continue
        if path.exists() and path.is_file() and path.suffix.lower() in SCRIPT_SUFFIXES and path not in result:
            result.append(path)
    for raw in re.findall(r"['\"]([^'\"]+\.(?:bat|cmd|ps1|psm1|vbs|js|jse|wsf|py|sh))['\"]", command, flags=re.IGNORECASE):
        try:
            path = sandbox_path(ctx, raw)
        except Exception:
            continue
        if path.exists() and path.is_file() and path.suffix.lower() in SCRIPT_SUFFIXES and path not in result:
            result.append(path)
    return result


def script_review_requested(args: dict[str, Any]) -> bool:
    value = args.get("script_reviewed") or args.get("reviewed") or args.get("script_checked")
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "是", "已检查", "checked"}
    return bool(value)


def validate_command_safety(args: dict[str, Any], runtime: dict[str, Any], ctx: dict[str, Any]) -> str:
    command = str(args.get("command") or "")
    admin = admin_allowed(runtime, ctx)
    sandbox_pattern = command_matches(SANDBOX_ESCAPE_PATTERNS, command)
    if sandbox_pattern:
        return f"命令被拒绝：疑似访问 tools/temp 以外路径或越界操作，匹配规则 {sandbox_pattern}。"
    dangerous_pattern = command_matches(DANGEROUS_PATTERNS, command)
    if dangerous_pattern and not admin:
        return f"命令被拒绝：疑似危害系统或高风险操作，匹配规则 {dangerous_pattern}。只有管理员明确要求时才允许继续。"
    scripts = referenced_script_paths(ctx, command)
    if scripts and not script_review_requested(args):
        names = ", ".join(path.name for path in scripts)
        return f"命令被拒绝：将执行脚本 {names}。执行任何脚本前必须先用 temp_file_operation 读取并审查内容，确认安全后再传 script_reviewed=true。"
    for script in scripts:
        try:
            text = script.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"命令被拒绝：无法读取脚本 {script.name} 进行安全检查：{exc}"
        pattern = command_matches(SANDBOX_ESCAPE_PATTERNS + ([] if admin else DANGEROUS_PATTERNS), text)
        if pattern:
            return f"命令被拒绝：脚本 {script.name} 内容疑似越界或高风险，匹配规则 {pattern}。"
    return ""


async def execute(args: dict[str, Any], runtime: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    command = str(args.get("command") or "").strip()
    if not command:
        return {"ok": False, "content": "命令执行失败：缺少 command。"}
    safety_error = validate_command_safety(args, runtime, ctx)
    if safety_error:
        return {"ok": False, "content": safety_error}
    shell = str(args.get("shell") or "powershell").strip().lower()
    if shell not in {"powershell", "cmd"}:
        shell = "powershell"
    root = temp_root(ctx)
    try:
        cwd = sandbox_path(ctx, args.get("cwd")) if str(args.get("cwd") or "").strip() else root
    except Exception as exc:
        return {"ok": False, "content": f"命令执行失败：cwd 非法：{ctx['exception_detail'](exc)}"}
    if not cwd.exists() or not cwd.is_dir():
        return {"ok": False, "content": f"命令执行失败：cwd 不存在或不是目录：{cwd}"}
    timeout = timeout_value(args.get("timeout_seconds"))
    env = os.environ.copy()
    env["LOCAL_ONEBOT_TOOLS_TEMP"] = str(root)
    proxy = apply_system_proxy_env(env)
    try:
        proc = await asyncio.create_subprocess_exec(
            *shell_args(shell, command),
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {"ok": False, "content": f"命令执行超时，已终止。timeout={timeout}s", "timeout": True}
    except Exception as exc:
        return {"ok": False, "content": f"命令启动失败：{ctx['exception_detail'](exc)}"}
    stdout_text = stdout.decode("utf-8", errors="replace")
    stderr_text = stderr.decode("utf-8", errors="replace")
    content = "\n".join([
        f"命令执行完成。shell={shell} cwd={cwd}",
        f"system_proxy={'已注入' if proxy else '未检测到'}",
        f"exit_code={proc.returncode}",
        "stdout:",
        clipped(stdout_text or "(空)"),
        "stderr:",
        clipped(stderr_text or "(空)"),
    ])
    return {"ok": proc.returncode == 0, "content": content, "exit_code": proc.returncode, "stdout": stdout_text, "stderr": stderr_text}
