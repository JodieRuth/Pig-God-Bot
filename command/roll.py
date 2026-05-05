from __future__ import annotations

import random
from typing import Any

MAX_COUNT = 100


def parse_args(arg: str) -> tuple[int, int, int] | None:
    parts = arg.split()
    if len(parts) != 3:
        return None
    try:
        start, end, count = (int(part) for part in parts)
    except ValueError:
        return None
    if count <= 0 or count > MAX_COUNT:
        return None
    if start > end:
        start, end = end, start
    return start, end, count


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    parsed = parse_args(arg)
    if parsed is None:
        await ctx["reply"](event, f"用法：/roll <最小值> <最大值> <数量>，数量范围 1-{MAX_COUNT}。例如：/roll 1 100 20")
        return
    start, end, count = parsed
    values = [str(random.randint(start, end)) for _ in range(count)]
    await ctx["reply"](event, f"{start}-{end} 随机整数 {count} 个：\n" + " ".join(values))


COMMAND = {
    "name": "/roll",
    "usage": "/roll <最小值> <最大值> <数量>",
    "description": "输出指定范围内的多个随机整数，例如 /roll 1 100 20。",
    "handler": handler,
}
