import asyncio
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

import aiohttp

COMMON_MODULE = Path(__file__).with_name("zhubi_ext_common.py")
spec = importlib.util.spec_from_file_location("local_onebot_zhubi_ext_common_update", COMMON_MODULE)
if spec is None or spec.loader is None:
    raise RuntimeError("无法加载猪币扩展模块")
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)

UPDATE_REPO = "https://github.com/JodieRuth/Pig-God-Bot"
UPDATE_ZIP = f"{UPDATE_REPO}/archive/refs/heads/main.zip"
UPDATE_MIRROR_PREFIXES = [
    "https://gh.llkk.cc/",
    "https://ghproxy.net/",
    "https://gh-proxy.com/",
]
PRESERVE_FILES = {".env", "runtime_state.json", ".pending_update.json"}
ALLOWED_JSON_FILES = {
    "command_nickname.json",
    "command/haochi/drinks.json",
    "command/haochi/foods.json",
}
C_SHARP_ROOT = "tools/browser_automation_host"
C_SHARP_ALLOWED_SUFFIXES = {".cs", ".csproj"}
ROOT_ALLOWED_FILES = {"requirements.txt", "tools/server.mjs"}
ROLLBACK_DIR_NAME = "rollback"
PENDING_UPDATE_FILE = ".pending_update.json"
STARTUP_MAX_WAIT = 45
PLAYWRIGHT_CHROMIUM_DIR_PREFIX = "chromium-"

ROLLBACK_SKIP_ITEMS = {".env", "runtime_state.json", ROLLBACK_DIR_NAME, PENDING_UPDATE_FILE,
                       "cache", "outputs", "logs", "__pycache__", ".git"}


def _short_error(error: str, limit: int = 300) -> str:
    text = " ".join(str(error).split())
    return text[:limit] + ("..." if len(text) > limit else "")


def _download_plan() -> list[tuple[str, str, bool]]:
    plan = [("GitHub 直连", UPDATE_ZIP, False), ("GitHub 系统代理", UPDATE_ZIP, True)]
    for prefix in UPDATE_MIRROR_PREFIXES:
        plan.append((f"镜像 {prefix.rstrip('/')}", prefix + UPDATE_ZIP, False))
        plan.append((f"镜像 {prefix.rstrip('/')} 系统代理", prefix + UPDATE_ZIP, True))
    return plan


async def _download(url: str, target: Path, trust_env: bool = False) -> str:
    try:
        timeout = aiohttp.ClientTimeout(total=120, connect=30, sock_connect=30, sock_read=90)
        async with aiohttp.ClientSession(timeout=timeout, trust_env=trust_env) as session:
            async with session.get(url, allow_redirects=True) as resp:
                if resp.status >= 400:
                    return f"HTTP {resp.status}"
                data = await resp.read()
                if not data:
                    return "下载内容为空"
                target.write_bytes(data)
                return ""
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"


async def _download_with_fallback(target: Path) -> tuple[str, list[str]]:
    failures: list[str] = []
    for name, url, trust_env in _download_plan():
        target.unlink(missing_ok=True)
        error = await _download(url, target, trust_env=trust_env)
        if not error and target.exists() and target.stat().st_size > 0:
            return name, failures
        failures.append(f"{name}: {_short_error(error or '下载文件不存在或为空')}")
    target.unlink(missing_ok=True)
    return "", failures


def _format_download_failures(failures: list[str]) -> str:
    lines = ["下载失败，所有下载方式均不可用："]
    for index, failure in enumerate(failures, start=1):
        lines.append(f"{index}. {failure}")
    return "\n".join(lines)


def _extract(zip_path: Path, dest: Path) -> str:
    try:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(dest)
        return ""
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"


def _find_source_root(extract_dir: Path) -> Path | None:
    for entry in extract_dir.iterdir():
        if entry.is_dir() and entry.name.startswith("Pig-God-Bot"):
            return entry
    for entry in extract_dir.iterdir():
        if entry.is_dir():
            return entry
    return None


def _is_allowed_update_file(rel: Path) -> bool:
    rel_posix = rel.as_posix()
    if rel.suffix.lower() == ".py":
        return True
    if rel.suffix.lower() == ".json" and rel_posix in ALLOWED_JSON_FILES:
        return True
    if rel_posix.startswith(C_SHARP_ROOT + "/") and rel.suffix.lower() in C_SHARP_ALLOWED_SUFFIXES:
        return True
    if rel_posix in ROOT_ALLOWED_FILES:
        return True
    return False


def _copy_files(src: Path, dest: Path, errors: list[str]) -> None:
    for item in src.rglob("*"):
        rel = item.relative_to(src)
        if any(part.startswith(".") and part not in (".env", ".env.example", ".gitignore") for part in rel.parts):
            continue
        name = rel.name
        if item.is_file() and not _is_allowed_update_file(rel):
            continue
        if name in PRESERVE_FILES:
            continue
        target = dest / rel
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
        except Exception as exc:
            errors.append(f"{rel}: {exc}")


def _clean_pycache(root: Path) -> None:
    for d in root.rglob("__pycache__"):
        try:
            shutil.rmtree(d)
        except OSError:
            pass


def _install_requirements(root: Path) -> str:
    req = root / "requirements.txt"
    if not req.exists():
        return ""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(req)],
            capture_output=False,
            timeout=300,
            cwd=str(root),
        )
        if result.returncode != 0:
            return f"pip install 返回 exit code {result.returncode}"
        return ""
    except subprocess.TimeoutExpired:
        return "pip install 超时"
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"


def _module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _playwright_chromium_installed() -> bool:
    cache_root = Path(os.getenv("PLAYWRIGHT_BROWSERS_PATH", "")).expanduser() if os.getenv("PLAYWRIGHT_BROWSERS_PATH") else Path.home() / "AppData" / "Local" / "ms-playwright"
    if os.getenv("PLAYWRIGHT_BROWSERS_PATH") == "0":
        try:
            import playwright
            cache_root = Path(playwright.__file__).resolve().parent / "driver" / "package" / ".local-browsers"
        except Exception:
            return False
    if not cache_root.exists():
        return False
    return any(path.is_dir() and path.name.startswith(PLAYWRIGHT_CHROMIUM_DIR_PREFIX) for path in cache_root.iterdir())


def _install_crawl4ai_runtime(root: Path) -> str:
    errors: list[str] = []
    if not _module_available("crawl4ai"):
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "crawl4ai>=0.7.0"],
                capture_output=False,
                timeout=600,
                cwd=str(root),
            )
            if result.returncode != 0:
                errors.append(f"pip install crawl4ai 返回 exit code {result.returncode}")
        except subprocess.TimeoutExpired:
            errors.append("pip install crawl4ai 超时")
        except Exception as exc:
            errors.append(f"pip install crawl4ai 失败：{type(exc).__name__}: {exc}")
    if not _module_available("playwright"):
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "playwright>=1.40.0"],
                capture_output=False,
                timeout=300,
                cwd=str(root),
            )
            if result.returncode != 0:
                errors.append(f"pip install playwright 返回 exit code {result.returncode}")
        except subprocess.TimeoutExpired:
            errors.append("pip install playwright 超时")
        except Exception as exc:
            errors.append(f"pip install playwright 失败：{type(exc).__name__}: {exc}")
    if _module_available("playwright") and not _playwright_chromium_installed():
        try:
            result = subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                capture_output=False,
                timeout=900,
                cwd=str(root),
            )
            if result.returncode != 0:
                errors.append(f"playwright install chromium 返回 exit code {result.returncode}")
        except subprocess.TimeoutExpired:
            errors.append("playwright install chromium 超时")
        except Exception as exc:
            errors.append(f"playwright install chromium 失败：{type(exc).__name__}: {exc}")
    return "；".join(errors)


def _update_vndb_data(root: Path) -> str:
    script = root / "tools" / "server.mjs"
    if not script.exists():
        return "tools/server.mjs 不存在"
    try:
        result = subprocess.run(
            [os.getenv("VNDB_NODE_BIN", "node"), str(script), "--update"],
            capture_output=True,
            text=True,
            timeout=600,
            cwd=str(root / "tools"),
            encoding="utf-8",
            errors="replace",
        )
        output = " ".join((result.stdout + "\n" + result.stderr).split())
        if result.returncode != 0:
            return f"node server.mjs --update 返回 exit code {result.returncode}: {_short_error(output)}"
        return ""
    except subprocess.TimeoutExpired:
        return "node server.mjs --update 超时"
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"


def _backup_to_rollback(bot_root: Path) -> str:
    rollback_root = bot_root / ROLLBACK_DIR_NAME
    rollback_root.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
    target = rollback_root / timestamp
    target.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    for item in bot_root.iterdir():
        if item.name in ROLLBACK_SKIP_ITEMS:
            continue
        if item.name.startswith("_update"):
            continue
        try:
            if item.is_dir():
                shutil.copytree(item, target / item.name,
                                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                                dirs_exist_ok=True)
            else:
                target_item = target / item.name
                target_item.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target_item)
        except Exception as exc:
            errors.append(f"{item.name}: {exc}")

    if errors:
        return f"ERR:{'; '.join(errors[:3])}"
    return timestamp


def _restore_from_rollback(bot_root: Path, timestamp: str) -> str:
    source = bot_root / ROLLBACK_DIR_NAME / timestamp
    if not source.exists():
        return f"回滚点 {timestamp} 不存在"

    errors: list[str] = []
    for item in source.iterdir():
        if item.name in ROLLBACK_SKIP_ITEMS or item.name.startswith("_update"):
            continue
        target = bot_root / item.name
        try:
            if item.is_dir():
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(item, target)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
        except Exception as exc:
            errors.append(f"{item.name}: {exc}")

    _clean_pycache(bot_root)

    if errors:
        return f"回滚部分失败: {'; '.join(errors[:3])}"
    return ""


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    if not ctx["is_admin_event"](event):
        await ctx["reply"](event, "你没有权限使用更新指令。")
        return

    common.flush_idle_data()
    await ctx["reply"](event, "正在从 GitHub 下载更新，完成后将自动重启。")

    bot_root = Path(__file__).resolve().parent.parent

    await ctx["reply"](event, "正在备份当前 bot 全部代码到 rollback 文件夹...")
    backup_result = _backup_to_rollback(bot_root)
    if backup_result.startswith("ERR:"):
        await ctx["reply"](event, f"备份失败：{backup_result[4:]}")
        return
    rollback_timestamp = backup_result

    zip_path = bot_root / "_update.zip"
    tmp_dir = bot_root / "_update_tmp"

    source_name, download_failures = await _download_with_fallback(zip_path)
    if not source_name:
        zip_path.unlink(missing_ok=True)
        await ctx["reply_forward"](event, [
            _format_download_failures(download_failures),
            f"已备份到 rollback/{rollback_timestamp}",
        ])
        return
    await ctx["reply"](event, f"下载成功，来源：{source_name}，正在解压更新包。")

    error = _extract(zip_path, tmp_dir)
    zip_path.unlink(missing_ok=True)
    if error:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        await ctx["reply"](event, f"解压失败：{error}，已备份到 rollback/{rollback_timestamp}")
        return

    src = _find_source_root(tmp_dir)
    if src is None:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        await ctx["reply"](event, f"更新文件结构异常，未找到源码目录。已备份到 rollback/{rollback_timestamp}")
        return

    copy_errors: list[str] = []
    _copy_files(src, bot_root, copy_errors)

    _clean_pycache(bot_root)

    shutil.rmtree(tmp_dir, ignore_errors=True)

    pip_error = _install_requirements(bot_root)

    await ctx["reply"](event, "正在检查 Crawl4AI 与 Playwright Chromium 运行环境...")
    crawl4ai_error = _install_crawl4ai_runtime(bot_root)
    if crawl4ai_error:
        await ctx["reply"](event, f"Crawl4AI 运行环境准备失败，将继续重启 bot：{crawl4ai_error}")
    else:
        await ctx["reply"](event, "Crawl4AI 运行环境已就绪。")

    await ctx["reply"](event, "正在使用 tools/server.mjs 更新并解压 VNDB 数据...")
    vndb_error = _update_vndb_data(bot_root)
    if vndb_error:
        await ctx["reply"](event, f"VNDB 数据更新失败，将继续重启 bot：{vndb_error}")
    else:
        await ctx["reply"](event, "VNDB 数据已更新到 tools/data。")

    pending = {
        "rollback_timestamp": rollback_timestamp,
        "event": {
            "message_type": event.get("message_type"),
            "group_id": event.get("group_id"),
            "user_id": event.get("user_id"),
            "message_id": event.get("message_id"),
        },
    }
    pending_file = bot_root / PENDING_UPDATE_FILE
    pending_file.write_text(json.dumps(pending, ensure_ascii=False), encoding="utf-8")

    ctx["bot_state"]["stopped"] = True
    stop_vndb_json_server = ctx.get("stop_vndb_json_server")
    if callable(stop_vndb_json_server):
        await stop_vndb_json_server()
    stop_searxng_server = ctx.get("stop_searxng_server")
    if callable(stop_searxng_server):
        await stop_searxng_server()
    await ctx["reply"](event, "更新文件已就绪，正在启动新版本 bot...")
    await asyncio.sleep(0.5)

    proc = await asyncio.create_subprocess_exec(
        sys.executable, str(bot_root / "bot.py"),
    )

    startup_ok = False
    for _ in range(STARTUP_MAX_WAIT):
        if not pending_file.exists():
            startup_ok = True
            break
        if proc.returncode is not None:
            break
        await asyncio.sleep(1)

    if startup_ok:
        if copy_errors:
            detail = "；".join(copy_errors[:3])
            ctx["log"](f"Update finished with copy warnings: {detail}")
        if pip_error:
            ctx["log"](f"Update finished with pip warning: {pip_error}")
        if crawl4ai_error:
            ctx["log"](f"Update finished with Crawl4AI warning: {crawl4ai_error}")
        if vndb_error:
            ctx["log"](f"Update finished with VNDB warning: {vndb_error}")
        os._exit(0)

    if proc.returncode is not None:
        try:
            proc.kill()
        except Exception:
            pass

    restore_error = _restore_from_rollback(bot_root, rollback_timestamp)
    pending_file.unlink(missing_ok=True)

    fail_msg = "更新失败，bot 启动崩溃。"
    if proc.returncode is not None:
        fail_msg += f"\n进程退出码: {proc.returncode}"
    if restore_error:
        fail_msg += f"\n回滚时出现问题：{restore_error}"
    else:
        fail_msg += "\n已自动回滚到更新前的版本，正在重启旧版 bot..."

    await ctx["reply"](event, fail_msg)
    await asyncio.sleep(0.5)
    await ctx["reboot_process"]()


COMMAND = {
    "name": "/update",
    "usage": "/update",
    "description": "仅所有者可用：从 GitHub 拉取最新源码更新并重启。更新前自动备份到 rollback，启动失败自动回滚。",
    "handler": handler,
}
