import importlib.util
from pathlib import Path
from typing import Any

COMMON_MODULE = Path(__file__).with_name("zhubi_ext_common.py")
spec = importlib.util.spec_from_file_location("local_onebot_zhubi_ext_common_restart", COMMON_MODULE)
if spec is None or spec.loader is None:
    raise RuntimeError("无法加载猪币扩展模块")
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    common.flush_idle_data()
    if not ctx["is_admin_event"](event):
        await ctx["reply"](event, "你没有权限使用控制指令。")
        return
    ctx["bot_state"]["stopped"] = False
    await ctx["reply"](event, "已恢复响应。")


COMMAND = {
    "name": "/restart",
    "usage": "/restart",
    "description": "仅所有者可用：恢复 bot 响应。",
    "handler": handler,
}
