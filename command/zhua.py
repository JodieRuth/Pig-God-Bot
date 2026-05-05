from typing import Any


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    await ctx["reply"](event, "zhua")


COMMAND = {
    "name": "/zhua",
    "usage": "/zhua",
    "description": "有猪a",
    "handler": handler,
}
