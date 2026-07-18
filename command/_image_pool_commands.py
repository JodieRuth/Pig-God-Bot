from __future__ import annotations

import importlib.util
import random
from pathlib import Path
from typing import Any, Literal

import bot_policy_state

COMMON_MODULE = Path(__file__).with_name("_image_pool_common.py")
spec = importlib.util.spec_from_file_location("local_onebot_image_pool_common", COMMON_MODULE)
if spec is None or spec.loader is None:
    raise RuntimeError("无法加载图片池数据模块")
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)

ManagementPermission = Literal["everyone", "admin", "privileged"]


def pool_item_fingerprint(item: dict[str, Any], pool_name: str) -> str:
    return bot_policy_state.image_content_fingerprint(common.item_md5(item), pool_name)


def can_manage_pool(event: dict[str, Any], ctx: dict[str, Any], permission: ManagementPermission) -> bool:
    if permission == "everyone":
        return True
    if ctx["is_admin_event"](event):
        return True
    return permission == "privileged" and ctx["is_operator_event"](event)


async def send_pool_item(
    event: dict[str, Any],
    item: dict[str, Any],
    ctx: dict[str, Any],
    pool_name: str,
    allow_duplicate: bool = False,
) -> None:
    path = common.image_record_path(item)
    if not path.exists():
        await ctx["reply"](event, f"#{item['id']} 的图片文件不存在。")
        return
    fingerprint = pool_item_fingerprint(item, pool_name)
    if not fingerprint:
        await ctx["reply"](event, f"无法读取 #{item['id']} 的图片内容。")
        return
    result = bot_policy_state.claim_content_usage(
        int(event.get("user_id", 0)),
        fingerprint,
        allow_duplicate=allow_duplicate,
    )
    if result.reason == "duplicate":
        await ctx["reply"](event, f"#{item['id']} 今天已经发送过，明天重置后可以再次发送。")
        return
    if result.reason == "hourly_limit":
        await ctx["reply"](event, "你在最近一小时内已使用 /sb、/sbt、/rp 和 /rpp 共 12 次，请稍后再试。")
        return
    if result.reason == "daily_limit":
        await ctx["reply"](event, "你今天已使用 /sb、/sbt、/rp 和 /rpp 共 60 次，明天重置后可以继续使用。")
        return
    await ctx["reply"](event, [{"type": "text", "data": {"text": f"#{item['id']}\n"}}, common.image_segment(path)])


def create_pool_read_command(pool_name: str, command_name: str) -> dict[str, Any]:
    async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
        items, _ = common.load_items(pool_name)
        if not items:
            await ctx["reply"](event, f"{command_name} 图池还没有收藏任何图片，使用 {command_name}_s 收藏。")
            return
        text = arg.strip()
        if text:
            target_id = common.parse_id(text)
            if target_id is None:
                await ctx["reply"](event, f"用法：{command_name} [#编号]")
                return
            item = next((value for value in items if int(value.get("id", 0)) == target_id), None)
            if item is None:
                await ctx["reply"](event, f"不存在编号 #{target_id}。")
                return
        else:
            sent_content = bot_policy_state.sent_content_fingerprints()
            available: list[dict[str, Any]] = []
            for value in items:
                if not common.image_record_path(value).exists():
                    continue
                fingerprint = pool_item_fingerprint(value, pool_name)
                if fingerprint and fingerprint not in sent_content:
                    available.append(value)
            if not available:
                await ctx["reply"](event, f"今天所有可用的 {command_name} 图片都已经发送过，明天重置后可以再次发送。")
                return
            item = random.choice(available)
        await send_pool_item(event, item, ctx, pool_name, allow_duplicate=bool(text))

    return {
        "name": command_name,
        "usage": f"{command_name} [#编号]",
        "description": "随机发送本图池今日未发送的图片，指定编号可重复；与 /sb、/sbt、/rp、/rpp 共用个人限额。",
        "handler": handler,
    }


def create_pool_save_command(
    pool_name: str,
    command_name: str,
    permission: ManagementPermission,
) -> dict[str, Any]:
    async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
        if not can_manage_pool(event, ctx, permission):
            await ctx["reply"](event, f"你没有权限使用 {command_name}。")
            return
        items, next_id = common.load_items(pool_name)
        target = await common.save_source_image(event, ctx, next_id, pool_name)
        if target is None or not target.exists():
            await ctx["reply"](event, "没有找到可收藏的图片：请在本条消息附图、回复一条带图消息，或先发送一张图片。")
            return
        md5_value = common.image_md5(target)
        duplicate = common.find_duplicate_by_md5(items, md5_value)
        if duplicate is not None:
            try:
                target.unlink()
            except OSError:
                pass
            await ctx["reply"](event, f"这张图片已收藏为 #{duplicate['id']}，不再重复收藏。")
            return
        item = {
            "id": next_id,
            "path": str(target),
            "text": target.name,
            "sender_id": event.get("user_id"),
            "sender_name": str(event.get("sender", {}).get("card") or event.get("sender", {}).get("nickname") or event.get("user_id", "")),
            "md5": md5_value,
        }
        items.append(item)
        common.save_items(items, next_id + 1, pool_name)
        await ctx["reply"](event, [{"type": "text", "data": {"text": f"已收藏为 #{next_id}\n"}}, common.image_segment(target)])

    permission_text = "仅 OP 或环境变量管理员可用：" if permission == "privileged" else ""
    return {
        "name": command_name,
        "usage": command_name,
        "description": f"{permission_text}收藏本条消息、被回复消息或发送者上一张图片，并复读原图。",
        "handler": handler,
    }


def create_pool_remove_command(
    pool_name: str,
    command_name: str,
    permission: ManagementPermission,
) -> dict[str, Any]:
    async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
        if not can_manage_pool(event, ctx, permission):
            await ctx["reply"](event, f"你没有权限使用 {command_name}。")
            return
        target_id = common.parse_id(arg.strip())
        if target_id is None:
            await ctx["reply"](event, f"用法：{command_name} <#编号>")
            return
        items, next_id = common.load_items(pool_name)
        removed: dict[str, Any] | None = None
        for index, item in enumerate(items):
            if int(item.get("id", 0)) == target_id:
                removed = items.pop(index)
                break
        if removed is None:
            await ctx["reply"](event, f"不存在编号 #{target_id}。")
            return
        path = common.image_record_path(removed)
        common.save_items(items, next_id, pool_name)
        if path.exists():
            await ctx["reply"](event, [{"type": "text", "data": {"text": f"已移除图片 #{target_id}，当前剩余 {len(items)} 张。\n"}}, common.image_segment(path)])
            path.unlink(missing_ok=True)
        else:
            await ctx["reply"](event, f"已移除图片 #{target_id}，但对应图片文件不存在。当前剩余 {len(items)} 张。")

    permission_text = "仅 OP 或环境变量管理员可用：" if permission == "privileged" else "仅环境变量管理员可用："
    return {
        "name": command_name,
        "usage": f"{command_name} <#编号>",
        "description": f"{permission_text}按编号移除收藏图片。",
        "handler": handler,
    }


def create_privileged_pool_commands(pool_name: str, command_name: str) -> list[dict[str, Any]]:
    return [
        create_pool_read_command(pool_name, command_name),
        create_pool_save_command(pool_name, f"{command_name}_s", "privileged"),
        create_pool_remove_command(pool_name, f"{command_name}_r", "privileged"),
    ]
