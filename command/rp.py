from __future__ import annotations

import random
from datetime import datetime, time, timezone, timedelta
from typing import Any

BEIJING_TZ = timezone(timedelta(hours=8))

MESSAGES = [
    [
        "今天像小猪踩进泥坑，越扑腾越狼狈。",
        "猪神看了你的猪鼻子一眼，然后默默把好运盆端走了。",
        "今日猪运偏低，建议缩进猪窝里先别拱事。",
    ],
    [
        "小猪电量不足，拱白菜都可能拱歪。",
        "今天猪蹄有点打滑，走路都要慢半拍。",
        "猪圈风水一般，先苟住，别和命运硬拱。",
    ],
    [
        "猪运勉强上线，像刚睡醒的小猪还在哼哼。",
        "今天适合吃糠咽菜，不适合挑战猪生巅峰。",
        "猪神给你留了半根胡萝卜，面子有，但不多。",
    ],
    [
        "普通偏低，像猪槽里只剩最后一口饭。",
        "今天可以出猪窝，但最好别离猪圈太远。",
        "猪鼻子闻到了好运味，但风一吹又没了。",
    ],
    [
        "中规中矩，是一只平平无奇但能吃饱的小猪。",
        "今日猪运像温水泡猪蹄，平淡但舒服。",
        "可以正常拱地，别突然幻想自己是野猪王。",
    ],
    [
        "猪运略有起色，适合去猪槽旁边占个好位置。",
        "猪神今天心情还行，顺手给你加了半勺饲料。",
        "小猪状态回暖，拱小事能成，拱大事看猪脸。",
    ],
    [
        "人品不错，今天是能抢到第一口猪食的水平。",
        "猪鼻子很灵，今天大概率能闻到一点好运。",
        "状态在线，适合趁猪蹄热乎把事拱完。",
    ],
    [
        "猪运发亮，像刚洗完澡还会反光的小猪。",
        "今天适合冲一手，但别把猪圈门都拱塌了。",
        "猪神给你盖了好运猪蹄印，限今日有效。",
    ],
    [
        "猪运爆棚，连路过的白菜都想自己滚进你碗里。",
        "今天是高光猪日，适合拱奖励、抢饭点、挑好吃的。",
        "好运浓度太高，建议分一点猪气给群友防止溢出。",
    ],
    [
        "今日天选之猪，猪圈里的风都在给你让路。",
        "猪神亲自开光，你的猪蹄今天踩哪哪旺。",
        "猪运封顶，概率见了你都得叫一声猪王。",
    ],
]


def beijing_midnight_timestamp() -> int:
    now = datetime.now(BEIJING_TZ)
    midnight = datetime.combine(now.date(), time.min, tzinfo=BEIJING_TZ)
    return int(midnight.timestamp())


def rp_for_user(user_id: int) -> tuple[int, str]:
    day_seed = beijing_midnight_timestamp()
    rng = random.Random(f"{user_id}:{day_seed}")
    value = rng.randint(1, 100)
    bucket = min(9, (value - 1) // 10)
    message = rng.choice(MESSAGES[bucket])
    return value, message


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    user_id = int(event.get("user_id", 0))
    value, message = rp_for_user(user_id)
    await ctx["reply"](event, f"今天你的人品是：{value}\n{message}")


COMMAND = {
    "name": "/rp",
    "usage": "/rp",
    "description": "查看今日人品。",
    "handler": handler,
}
