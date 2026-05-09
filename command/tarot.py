from __future__ import annotations

import random
from typing import Any

MAJOR_ARCANA = [
    ("愚者", "新的开始、自由、冒险、未知旅程"),
    ("魔术师", "行动力、创造、资源整合、把想法落地"),
    ("女祭司", "直觉、秘密、潜意识、静观其变"),
    ("女皇", "滋养、丰盛、关系成长、创造力"),
    ("皇帝", "秩序、责任、边界、掌控局面"),
    ("教皇", "传统、学习、规则、寻求可靠建议"),
    ("恋人", "选择、关系、价值观一致、真诚连接"),
    ("战车", "意志、推进、胜利、控制方向"),
    ("力量", "勇气、温柔的坚持、自我驯服"),
    ("隐者", "独处、反思、寻找答案、内在智慧"),
    ("命运之轮", "转机、循环、不可控变化、顺势而为"),
    ("正义", "公平、因果、判断、承担结果"),
    ("倒吊人", "暂停、换角度、牺牲、等待时机"),
    ("死神", "结束、转化、告别旧模式、重生"),
    ("节制", "平衡、调和、耐心、稳定修复"),
    ("恶魔", "执念、诱惑、束缚、看见欲望"),
    ("高塔", "突变、崩塌、真相显现、重建基础"),
    ("星星", "希望、疗愈、指引、长期信念"),
    ("月亮", "迷雾、焦虑、幻象、信息不明"),
    ("太阳", "清晰、快乐、成功、能量充足"),
    ("审判", "觉醒、复盘、召唤、重要决定"),
    ("世界", "完成、整合、圆满、进入新阶段"),
]

SUITS = {
    "权杖": ("行动、热情、事业、创造冲劲", "火"),
    "圣杯": ("情感、关系、感受、内在满足", "水"),
    "宝剑": ("思考、沟通、冲突、理性判断", "风"),
    "星币": ("金钱、现实、身体、长期积累", "土"),
}

RANKS = {
    "王牌": "开端、种子、机会刚刚出现",
    "二": "选择、平衡、关系中的拉扯",
    "三": "合作、表达、初步成果",
    "四": "稳定、停顿、安全感或固着",
    "五": "冲突、损耗、挑战与调整",
    "六": "修复、流动、互助或阶段性改善",
    "七": "评估、防守、诱惑或策略",
    "八": "推进、练习、速度与专注",
    "九": "临界点、收获前夕、独立承受",
    "十": "完成、累积结果、负担或圆满",
    "侍从": "学习者、消息、尝试、年轻能量",
    "骑士": "推进者、行动、追逐目标",
    "王后": "成熟接纳、照料、内在掌控",
    "国王": "外在掌控、决策、责任与领导",
}

POSITIONS = [
    ("现状", "你当前最需要看见的核心能量"),
    ("阻碍", "正在卡住你或让局势变复杂的因素"),
    ("建议", "牌面给出的行动方向"),
    ("可能结果", "若维持当前趋势，较可能走向的结果"),
]

REVERSED_HINTS = [
    "能量受阻，需要先处理内耗或拖延。",
    "这张牌的课题偏向内在，别急着向外证明。",
    "牌意可能以延迟、过度或反面形式出现。",
    "提醒你降低执念，重新校准方向。",
]

FINAL_ADVICE = [
    "先把问题说清楚，再决定下一步；清晰本身就是力量。",
    "不要只看结果，也要看过程里你正在形成的习惯。",
    "今天适合做一个小但确定的行动，让局势开始流动。",
    "保持弹性，命运给出的不是命令，而是可调整的路线图。",
    "若局面混乱，优先处理最现实、最可执行的一件事。",
]


def build_deck() -> list[dict[str, str]]:
    deck = [{"name": name, "meaning": meaning, "kind": "大阿尔卡那"} for name, meaning in MAJOR_ARCANA]
    for suit, (suit_meaning, element) in SUITS.items():
        for rank, rank_meaning in RANKS.items():
            deck.append({
                "name": f"{suit}{rank}",
                "meaning": f"{suit_meaning}；{rank_meaning}",
                "kind": f"小阿尔卡那·{element}元素",
            })
    return deck


def orientation_text(reversed_card: bool) -> str:
    return "逆位" if reversed_card else "正位"


def interpret_card(card: dict[str, str], reversed_card: bool) -> str:
    if reversed_card:
        return f"{card['meaning']}。{random.choice(REVERSED_HINTS)}"
    return f"{card['meaning']}。这股能量较顺畅，可以直接作为判断依据。"


def tarot_reading(question: str) -> str:
    deck = build_deck()
    random.shuffle(deck)
    cut_index = random.randint(10, len(deck) - 10)
    deck = deck[cut_index:] + deck[:cut_index]
    drawn = deck[:len(POSITIONS)]
    reversals = [random.choice([False, True]) for _ in drawn]

    lines = [
        "🔮 标准塔罗牌占卜开始",
        f"问题：{question or '未指定具体问题，本次按「近期整体运势与行动建议」解读。'}",
        "流程：洗牌 → 切牌 → 四张牌阵抽牌 → 逐张解读 → 综合建议",
        "牌阵：现状 / 阻碍 / 建议 / 可能结果",
        "",
        "抽牌结果：",
    ]
    for index, ((position, description), card, reversed_card) in enumerate(zip(POSITIONS, drawn, reversals), 1):
        lines.append(f"{index}. {position}：{card['name']}（{orientation_text(reversed_card)}，{card['kind']}）")
        lines.append(f"   含义：{description}。{interpret_card(card, reversed_card)}")

    upright_count = sum(1 for item in reversals if not item)
    reversed_count = len(reversals) - upright_count
    major_count = sum(1 for card in drawn if card["kind"] == "大阿尔卡那")
    tone = "整体能量偏顺，适合主动推进。" if upright_count >= reversed_count else "整体能量有阻滞，适合先整理问题再行动。"
    weight = "大阿尔卡那较多，说明这件事带有更强的阶段性意义。" if major_count >= 2 else "小阿尔卡那较多，说明重点更偏向日常选择与具体执行。"

    lines.extend([
        "",
        "综合占卜：",
        f"本次牌面正位 {upright_count} 张、逆位 {reversed_count} 张，大阿尔卡那 {major_count} 张。{tone}{weight}",
        f"最终建议：{random.choice(FINAL_ADVICE)}",
        "仅供娱乐与自我反思，请不要把占卜当作唯一决策依据。",
    ])
    return "\n".join(lines)


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    await ctx["reply"](event, tarot_reading(arg.strip()))


COMMAND = {
    "name": "/tarot",
    "usage": "/tarot [想占卜的问题]",
    "description": "进行一次标准塔罗牌占卜流程，并回复抽牌与解读结果。",
    "handler": handler,
}
