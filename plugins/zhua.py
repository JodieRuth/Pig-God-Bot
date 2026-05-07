import time
from collections import defaultdict, deque
from typing import Any

TRIGGERS = {"zhua", "猪啊", "猪a", "dazhua", "大猪a", "zaoa", "早a", "🐷", "🐖", "🐽","铸啊","猪","铸","铸揉","zhu啊"}
WINDOW_SECONDS = 180
MAX_REPLIES = 3
recent_replies: dict[str, deque[float]] = defaultdict(deque)


async def handler(event: dict[str, Any], text: str, ctx: dict[str, Any]) -> bool:
    if str(event.get("user_id")) == str(ctx.get("bot_qq")):
        return False
    if text.strip() not in TRIGGERS:
        return False
    scope = ctx["scope_key"](event)
    now = time.time()
    bucket = recent_replies[scope]
    while bucket and now - bucket[0] >= WINDOW_SECONDS:
        bucket.popleft()
    if len(bucket) >= MAX_REPLIES:
        return True
    bucket.append(now)
    await ctx["reply"](event, "zhua")
    return True


PLUGIN = {
    "name": "zhua",
    "description": "有猪a",
    "handler": handler,
}
