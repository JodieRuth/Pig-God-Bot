from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

COMMON_MODULE = Path(__file__).with_name("zhubi_ext_common.py")
spec = importlib.util.spec_from_file_location("local_onebot_zhubi_ext_common_clear", COMMON_MODULE)
if spec is None or spec.loader is None:
    raise RuntimeError("无法加载猪币扩展模块")
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)
zhubi = common.zhubi


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    if not ctx["is_admin_event"](event):
        await ctx["reply"](event, "你没有权限使用猪币清除指令。")
        return
    user_id = arg.strip()
    if not user_id.isdigit():
        await ctx["reply"](event, "用法：/zhubi_clear <QQ号>")
        return
    data = zhubi.load_data()
    common.apply_idle_income(data)
    users = data.setdefault("users", {})
    if user_id not in users:
        zhubi.save_data(data)
        await ctx["reply"](event, f"QQ {user_id} 没有猪币数据。")
        return
    users[user_id] = common.zhubi.normalize_user_data({})
    zhubi.save_data(data)
    await ctx["reply"](event, f"已清空 QQ {user_id} 的全部猪币数据。")


COMMAND = {
    "name": "/zhubi_clear",
    "usage": "/zhubi_clear <QQ号>",
    "description": "仅所有者可用：清空指定QQ的全部猪币数据（主钱包、idle、升级等）。",
    "handler": handler,
}
