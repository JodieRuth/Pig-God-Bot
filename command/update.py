import asyncio
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any

import aiohttp

UPDATE_REPO = "https://github.com/JodieRuth/Pig-God-Bot"
UPDATE_ZIP = f"{UPDATE_REPO}/archive/refs/heads/main.zip"
PRESERVE_FILES = {".env", "runtime_state.json"}
ALLOWED_JSON_FILES = {
    "command_nickname.json",
    "prompts.json",
    "command/haochi/drinks.json",
    "command/haochi/foods.json",
}
C_SHARP_ROOT = "tools/browser_automation_host"
C_SHARP_ALLOWED_SUFFIXES = {".cs", ".csproj"}
ROOT_ALLOWED_FILES = {"requirements.txt"}


async def _download(url: str, target: Path) -> str:
    try:
        timeout = aiohttp.ClientTimeout(total=120)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status >= 400:
                    return f"HTTP {resp.status}"
                data = await resp.read()
                target.write_bytes(data)
                return ""
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"


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


def _install_requirements(root: Path) -> None:
    req = root / "requirements.txt"
    if not req.exists():
        return
    try:
        import subprocess
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(req)],
            capture_output=True,
            timeout=120,
        )
    except Exception:
        pass


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    if not ctx["is_admin_event"](event):
        await ctx["reply"](event, "你没有权限使用更新指令。")
        return

    await ctx["reply"](event, "正在从 GitHub 下载更新，完成后将自动重启。")

    bot_root = Path(__file__).resolve().parent.parent
    zip_path = bot_root / "_update.zip"
    tmp_dir = bot_root / "_update_tmp"

    error = await _download(UPDATE_ZIP, zip_path)
    if error:
        zip_path.unlink(missing_ok=True)
        await ctx["reply"](event, f"下载失败：{error}")
        return

    error = _extract(zip_path, tmp_dir)
    zip_path.unlink(missing_ok=True)
    if error:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        await ctx["reply"](event, f"解压失败：{error}")
        return

    src = _find_source_root(tmp_dir)
    if src is None:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        await ctx["reply"](event, "更新文件结构异常，未找到源码目录。")
        return

    copy_errors: list[str] = []
    _copy_files(src, bot_root, copy_errors)

    _clean_pycache(bot_root)

    shutil.rmtree(tmp_dir, ignore_errors=True)

    _install_requirements(bot_root)

    if copy_errors:
        detail = "；".join(copy_errors[:3])
        suffix = f"，但有 {len(copy_errors)} 个文件覆盖失败：{detail}" if len(copy_errors) <= 3 else f"，但 {len(copy_errors)} 个文件覆盖失败（部分：{detail}）"
    else:
        suffix = ""

    ctx["bot_state"]["stopped"] = False
    await ctx["reply"](event, f"更新完成{suffix}，正在重启 bot 进程。")
    await asyncio.sleep(0.5)
    ctx["reboot_process"]()


COMMAND = {
    "name": "/update",
    "usage": "/update",
    "description": "仅所有者可用：从 GitHub 拉取最新源码更新并重启。",
    "handler": handler,
}
