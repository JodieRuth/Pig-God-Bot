from __future__ import annotations

from typing import Any

from _vndb_common import execute_action, info_from_definition, meta_search_definition


def definition(ctx: dict[str, Any]) -> dict[str, Any]:
    return meta_search_definition()


def info(ctx: dict[str, Any]) -> dict[str, str]:
    return info_from_definition(definition(ctx))


async def execute(args: dict[str, Any], runtime: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    return await execute_action("metaSearch", args, runtime, ctx)
