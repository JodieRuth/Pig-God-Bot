from __future__ import annotations

import base64
import shutil
import uuid
from pathlib import Path
from typing import Any

from PIL import Image

MAX_READ_CHARS = 50000
MAX_WRITE_CHARS = 200000


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


def display_path(ctx: dict[str, Any], path: Path) -> str:
    root = temp_root(ctx)
    try:
        value = path.resolve().relative_to(root).as_posix()
    except ValueError:
        value = path.name
    return value or "."


def clipped(text: str, limit: int = MAX_READ_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...内容过长，已截断到 {limit} 字符。"


TOOL_DESCRIPTION = "在受限沙箱 tools/temp 内执行文件操作。支持 list/read/write/append/delete/mkdir/move/copy/replace/stat/clear。所有路径都被限制在 tools/temp 内，不能访问沙箱外文件；LLM 不得试图用相对路径、绝对路径、符号链接或命令组合操作 tools/temp 以外任何位置，除非管理员明确要求且程序仍会拦截越界。写入/修改 bat/cmd/ps1/py/js/vbs/sh 等脚本后，执行前必须先 read 审查内容，确认不会越界或危害系统。read 目标是图片时，工具会把图片转换为 PNG 并追加到当前 LLM 图片上下文，而不是把二进制当文本返回。适合和 execute_command 配合创建临时脚本、读写临时数据、清理工作区。"


def definition(ctx: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "temp_file_operation",
            "description": TOOL_DESCRIPTION,
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["list", "read", "write", "append", "delete", "mkdir", "move", "copy", "replace", "stat", "clear"],
                        "description": "文件操作类型。",
                    },
                    "path": {
                        "type": "string",
                        "description": "tools/temp 内的相对路径。禁止绝对路径、../ 越界或任何沙箱外路径。list/read/write/delete/mkdir/stat 等操作使用。clear 可省略。",
                    },
                    "target_path": {
                        "type": "string",
                        "description": "move/copy 的目标相对路径。",
                    },
                    "content": {
                        "type": "string",
                        "description": "write/append 写入内容，或 replace 的替换内容。",
                    },
                    "old_content": {
                        "type": "string",
                        "description": "replace 要查找的旧内容。",
                    },
                    "encoding": {
                        "type": "string",
                        "description": "文本编码，默认 utf-8。",
                    },
                    "base64": {
                        "type": "boolean",
                        "description": "write/read 是否按 base64 处理二进制内容。",
                    },
                    "recursive": {
                        "type": "boolean",
                        "description": "delete 删除目录时是否递归，默认 true。",
                    },
                },
                "required": ["operation"],
            },
        },
    }


def info(ctx: dict[str, Any]) -> dict[str, str]:
    item = definition(ctx).get("function", {})
    return {"name": str(item.get("name") or "temp_file_operation"), "description": str(item.get("description") or "")}


def bool_arg(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "是"}
    return bool(value)


def list_dir(ctx: dict[str, Any], path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"ok": False, "content": f"列表失败：路径不存在 {display_path(ctx, path)}"}
    if not path.is_dir():
        return {"ok": False, "content": f"列表失败：不是目录 {display_path(ctx, path)}"}
    items = []
    for item in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        stat = item.stat()
        items.append({"name": item.name, "path": display_path(ctx, item), "type": "dir" if item.is_dir() else "file", "size": stat.st_size})
    lines = [f"目录 {display_path(ctx, path)}:"]
    lines.extend(f"- {entry['type']} {entry['path']} ({entry['size']} bytes)" for entry in items)
    return {"ok": True, "content": "\n".join(lines), "items": items}


def is_image_file(path: Path) -> bool:
    if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff"}:
        return False
    try:
        with Image.open(path) as img:
            img.verify()
        return True
    except Exception:
        return False


def convert_image_to_png(path: Path, ctx: dict[str, Any]) -> Path:
    target_dir = temp_root(ctx) / "_image_context"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{path.stem}_{uuid.uuid4().hex}.png"
    with Image.open(path) as img:
        if getattr(img, "is_animated", False):
            img.seek(0)
        converted = img.convert("RGBA") if img.mode in {"P", "LA", "RGBA"} else img.convert("RGB")
        converted.save(target, "PNG")
    return target


def add_png_to_runtime(path: Path, runtime: dict[str, Any], ctx: dict[str, Any]) -> int | str:
    add_image_context = ctx.get("add_tool_image_context")
    if not callable(add_image_context):
        return "?"
    record = add_image_context(runtime["event"], path, f"tools/temp 图片已读取并转换为 PNG：{path.name}")
    images = runtime.setdefault("images", [])
    if not isinstance(images, list):
        return "?"
    if record in images:
        images.remove(record)
    max_images = int(ctx.get("max_context_images", 10) or 10)
    while len(images) >= max_images and images:
        images.pop(0)
    images.append(record)
    return images.index(record) + 1 if record in images else "?"


async def execute(args: dict[str, Any], runtime: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    operation = str(args.get("operation") or "").strip().lower()
    encoding = str(args.get("encoding") or "utf-8").strip() or "utf-8"
    try:
        root = temp_root(ctx)
        path = sandbox_path(ctx, args.get("path"))
        if operation == "clear":
            clear = ctx.get("clear_tools_temp_dir")
            if callable(clear):
                clear()
            else:
                shutil.rmtree(root, ignore_errors=True)
                root.mkdir(parents=True, exist_ok=True)
            return {"ok": True, "content": "已清空 tools/temp。"}
        if operation == "list":
            return list_dir(ctx, path)
        if operation == "mkdir":
            path.mkdir(parents=True, exist_ok=True)
            return {"ok": True, "content": f"已创建目录：{display_path(ctx, path)}"}
        if operation == "stat":
            if not path.exists():
                return {"ok": False, "content": f"stat 失败：路径不存在 {display_path(ctx, path)}"}
            stat = path.stat()
            return {"ok": True, "content": f"{display_path(ctx, path)} type={'dir' if path.is_dir() else 'file'} size={stat.st_size} mtime={stat.st_mtime}", "stat": {"size": stat.st_size, "mtime": stat.st_mtime, "is_dir": path.is_dir()}}
        if operation == "read":
            if not path.exists() or not path.is_file():
                return {"ok": False, "content": f"读取失败：文件不存在 {display_path(ctx, path)}"}
            if is_image_file(path):
                png_path = convert_image_to_png(path, ctx)
                image_index = add_png_to_runtime(png_path, runtime, ctx)
                return {"ok": True, "content": f"读取到图片文件，已转换为 PNG 并追加到当前 LLM 图片上下文：图{image_index}。PNG 路径：{display_path(ctx, png_path)}", "image_index": image_index, "path": display_path(ctx, png_path)}
            if bool_arg(args.get("base64")):
                data = base64.b64encode(path.read_bytes()).decode("ascii")
                return {"ok": True, "content": clipped(data), "base64": data}
            text = path.read_text(encoding=encoding, errors="replace")
            return {"ok": True, "content": clipped(text), "text": text}
        if operation in {"write", "append"}:
            content = str(args.get("content") or "")
            if len(content) > MAX_WRITE_CHARS and not bool_arg(args.get("base64")):
                return {"ok": False, "content": f"写入失败：内容超过 {MAX_WRITE_CHARS} 字符。"}
            path.parent.mkdir(parents=True, exist_ok=True)
            if bool_arg(args.get("base64")):
                data = base64.b64decode(content.encode("ascii"))
                mode = "ab" if operation == "append" else "wb"
                with path.open(mode) as f:
                    f.write(data)
            else:
                mode = "a" if operation == "append" else "w"
                with path.open(mode, encoding=encoding, errors="replace") as f:
                    f.write(content)
            return {"ok": True, "content": f"已{('追加' if operation == 'append' else '写入')}文件：{display_path(ctx, path)} ({path.stat().st_size} bytes)"}
        if operation == "replace":
            old = str(args.get("old_content") or "")
            new = str(args.get("content") or "")
            if not old:
                return {"ok": False, "content": "替换失败：缺少 old_content。"}
            if not path.exists() or not path.is_file():
                return {"ok": False, "content": f"替换失败：文件不存在 {display_path(ctx, path)}"}
            text = path.read_text(encoding=encoding, errors="replace")
            if old not in text:
                return {"ok": False, "content": "替换失败：old_content 未找到。"}
            path.write_text(text.replace(old, new, 1), encoding=encoding, errors="replace")
            return {"ok": True, "content": f"已替换文件内容：{display_path(ctx, path)}"}
        if operation == "delete":
            if not path.exists():
                return {"ok": True, "content": f"路径已不存在：{display_path(ctx, path)}"}
            if path.is_dir():
                if bool_arg(args.get("recursive"), True):
                    shutil.rmtree(path)
                else:
                    path.rmdir()
            else:
                path.unlink()
            return {"ok": True, "content": f"已删除：{display_path(ctx, path)}"}
        if operation in {"move", "copy"}:
            target = sandbox_path(ctx, args.get("target_path"))
            if not path.exists():
                return {"ok": False, "content": f"{operation} 失败：源路径不存在 {display_path(ctx, path)}"}
            target.parent.mkdir(parents=True, exist_ok=True)
            if operation == "move":
                shutil.move(str(path), str(target))
                return {"ok": True, "content": f"已移动：{display_path(ctx, path)} -> {display_path(ctx, target)}"}
            if path.is_dir():
                shutil.copytree(path, target, dirs_exist_ok=True)
            else:
                shutil.copy2(path, target)
            return {"ok": True, "content": f"已复制：{display_path(ctx, path)} -> {display_path(ctx, target)}"}
        return {"ok": False, "content": f"未知文件操作：{operation}"}
    except Exception as exc:
        return {"ok": False, "content": f"文件操作失败：{ctx['exception_detail'](exc)}"}
