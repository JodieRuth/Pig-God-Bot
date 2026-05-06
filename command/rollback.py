import asyncio
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROLLBACK_DIR_NAME = "rollback"

ROLLBACK_SKIP_ITEMS = {".env", "runtime_state.json", ROLLBACK_DIR_NAME, ".pending_update.json",
                       "cache", "outputs", "logs", "__pycache__", ".git"}


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
        import subprocess

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


def _list_rollback_timestamps(bot_root: Path) -> list[str]:
    rollback_root = bot_root / ROLLBACK_DIR_NAME
    if not rollback_root.exists():
        return []
    timestamps = []
    for entry in sorted(rollback_root.iterdir(), reverse=True):
        if entry.is_dir():
            timestamps.append(entry.name)
    return timestamps


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    if not ctx["is_admin_event"](event):
        await ctx["reply"](event, "你没有权限使用回滚指令。")
        return

    bot_root = Path(__file__).resolve().parent.parent
    arg = arg.strip()

    if not arg:
        timestamps = _list_rollback_timestamps(bot_root)
        if not timestamps:
            await ctx["reply"](event, "当前没有可用的回滚点。")
            return
        lines = ["可用的回滚时间点："]
        for ts in timestamps:
            lines.append(f"  {ts}")
        await ctx["reply_forward"](event, lines)
        return

    timestamp = arg.replace(":", "-")
    source = bot_root / ROLLBACK_DIR_NAME / timestamp
    if not source.exists():
        timestamps = _list_rollback_timestamps(bot_root)
        hint = ""
        if timestamps:
            recent = timestamps[:3]
            hint = f"\n可用的回滚点：{', '.join(recent)}"
        await ctx["reply"](event, f"回滚点 {timestamp} 不存在。{hint}")
        return

    await ctx["reply"](event, f"正在回滚到 {timestamp} ...")

    current_backup = _backup_to_rollback(bot_root)
    if current_backup.startswith("ERR:"):
        await ctx["reply"](event, f"回滚前备份当前状态失败：{current_backup[4:]}")
        return

    restore_error = _restore_from_rollback(bot_root, timestamp)
    if restore_error:
        await ctx["reply"](event, f"回滚失败：{restore_error}")
        return

    _clean_pycache(bot_root)
    _install_requirements(bot_root)

    ctx["bot_state"]["stopped"] = False
    await ctx["reply"](event, f"已回滚到 {timestamp}，正在重启 bot 进程。")
    await asyncio.sleep(0.5)
    ctx["reboot_process"]()


COMMAND = {
    "name": "/rollback",
    "usage": "/rollback [时间戳]",
    "description": "仅所有者可用：裸打列出所有回滚时间点，带时间戳参数则回滚到指定版本。",
    "handler": handler,
}
