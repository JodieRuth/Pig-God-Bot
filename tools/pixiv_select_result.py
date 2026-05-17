from __future__ import annotations

from pathlib import Path
from typing import Any

from _pixiv_common import add_image_to_runtime, candidate_by_number, download_full_image, metadata_text


TOOL_DESCRIPTION = "根据 pixiv_search_tag 返回的 search_id 和拼图里的候选编号，下载该缩略图背后真正的 Pixiv 大图/原图，并把图片与标题、全部标签、简介、作者名、PID 等元数据一起追加到当前 LLM 上下文。注意 candidate_numbers 是拼图里的编号，不是 bot 图片编号。"


def definition(ctx: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "pixiv_select_result",
            "description": TOOL_DESCRIPTION,
            "parameters": {
                "type": "object",
                "properties": {
                    "search_id": {
                        "type": "string",
                        "description": "pixiv_search_tag 返回的 search_id。",
                    },
                    "candidate_numbers": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "拼图中要选择的 Pixiv 候选编号，例如 [3] 或 [1, 12]。这是缩略图编号，不是 bot 图片编号。",
                    },
                },
                "required": ["search_id", "candidate_numbers"],
            },
        },
    }


def info(ctx: dict[str, Any]) -> dict[str, str]:
    item = definition(ctx).get("function", {})
    return {
        "name": str(item.get("name") or "pixiv_select_result"),
        "description": str(item.get("description") or ""),
    }


def unique_numbers(values: Any) -> list[int]:
    if not isinstance(values, list):
        values = [values]
    result: list[int] = []
    for value in values:
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number > 0 and number not in result:
            result.append(number)
    return result[:5]


async def execute(args: dict[str, Any], runtime: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    search_id = str(args.get("search_id") or "").strip()
    numbers = unique_numbers(args.get("candidate_numbers"))
    if not search_id:
        return {"ok": False, "content": "Pixiv 候选选择失败：缺少 search_id。"}
    if not numbers:
        return {"ok": False, "content": "Pixiv 候选选择失败：缺少 candidate_numbers。"}
    output_dir = Path(ctx.get("output_dir") or ".") / "pixiv_images"
    selected: list[dict[str, Any]] = []
    lines = ["Pixiv 候选选择成功，已下载真实大图/原图并追加到当前 LLM 图片上下文。"]
    for number in numbers:
        item = candidate_by_number(search_id, number)
        if item is None:
            lines.append(f"候选 {number:02d}: 未找到，可能 search_id 已过期或编号不存在。")
            continue
        try:
            path = await download_full_image(item, output_dir)
        except Exception as exc:
            lines.append(f"候选 {number:02d}: 下载失败：{ctx['exception_detail'](exc)}")
            continue
        content = metadata_text(item)
        image_index = add_image_to_runtime(path, content, runtime, ctx)
        selected.append({"candidate_number": number, "image_index": image_index, "pid": item.get("pid"), "path": str(path), "item": item})
        lines.extend([
            "",
            f"候选 {number:02d} -> bot 图片图{image_index}",
            content,
        ])
    if not selected:
        return {"ok": False, "content": "\n".join(lines)}
    lines.append("")
    lines.append("后续如需发送、分析或用于生图，请使用这里返回的 bot 图片编号；不要再使用拼图里的候选编号当作 image_index。")
    return {"ok": True, "content": "\n".join(lines), "selected": selected}
