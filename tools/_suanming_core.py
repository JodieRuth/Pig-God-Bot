from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from lunar_python import Solar

BEIJING_TZ = timezone(timedelta(hours=8))

STEMS = list("甲乙丙丁戊己庚辛壬癸")
BRANCHES = list("子丑寅卯辰巳午未申酉戌亥")
BRANCH_NUMBERS = {branch: index + 1 for index, branch in enumerate(BRANCHES)}
BRANCH_ELEMENTS = {
    "子": "水",
    "丑": "土",
    "寅": "木",
    "卯": "木",
    "辰": "土",
    "巳": "火",
    "午": "火",
    "未": "土",
    "申": "金",
    "酉": "金",
    "戌": "土",
    "亥": "水",
}
BRANCH_OPPOSITES = {
    "子": "午",
    "丑": "未",
    "寅": "申",
    "卯": "酉",
    "辰": "戌",
    "巳": "亥",
    "午": "子",
    "未": "丑",
    "申": "寅",
    "酉": "卯",
    "戌": "辰",
    "亥": "巳",
}
GENERATES = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
CONTROLS = {"木": "土", "土": "水", "水": "火", "火": "金", "金": "木"}

TRIGRAMS: dict[str, dict[str, Any]] = {
    "乾": {"number": 1, "symbol": "☰", "nature": "天", "element": "金", "lines": (1, 1, 1), "image": "健、主动、开创、规则"},
    "兑": {"number": 2, "symbol": "☱", "nature": "泽", "element": "金", "lines": (1, 1, 0), "image": "悦、表达、交换、缺口"},
    "离": {"number": 3, "symbol": "☲", "nature": "火", "element": "火", "lines": (1, 0, 1), "image": "明、显现、依附、判断"},
    "震": {"number": 4, "symbol": "☳", "nature": "雷", "element": "木", "lines": (1, 0, 0), "image": "动、启动、惊动、突破"},
    "巽": {"number": 5, "symbol": "☴", "nature": "风", "element": "木", "lines": (0, 1, 1), "image": "入、渗透、沟通、渐进"},
    "坎": {"number": 6, "symbol": "☵", "nature": "水", "element": "水", "lines": (0, 1, 0), "image": "险、阻隔、流动、隐藏"},
    "艮": {"number": 7, "symbol": "☶", "nature": "山", "element": "土", "lines": (0, 0, 1), "image": "止、界限、积累、等待"},
    "坤": {"number": 8, "symbol": "☷", "nature": "地", "element": "土", "lines": (0, 0, 0), "image": "顺、承载、配合、稳定"},
}
NUMBER_TO_TRIGRAM = {1: "乾", 2: "兑", 3: "离", 4: "震", 5: "巽", 6: "坎", 7: "艮", 8: "坤", 0: "坤"}
TRIGRAM_BY_LINES = {tuple(info["lines"]): name for name, info in TRIGRAMS.items()}

HEXAGRAM_NAMES: dict[tuple[str, str], str] = {
    ("乾", "乾"): "乾为天",
    ("坤", "坤"): "坤为地",
    ("坎", "震"): "水雷屯",
    ("艮", "坎"): "山水蒙",
    ("坎", "乾"): "水天需",
    ("乾", "坎"): "天水讼",
    ("坤", "坎"): "地水师",
    ("坎", "坤"): "水地比",
    ("巽", "乾"): "风天小畜",
    ("乾", "兑"): "天泽履",
    ("坤", "乾"): "地天泰",
    ("乾", "坤"): "天地否",
    ("乾", "离"): "天火同人",
    ("离", "乾"): "火天大有",
    ("坤", "艮"): "地山谦",
    ("震", "坤"): "雷地豫",
    ("兑", "震"): "泽雷随",
    ("艮", "巽"): "山风蛊",
    ("坤", "兑"): "地泽临",
    ("巽", "坤"): "风地观",
    ("离", "震"): "火雷噬嗑",
    ("艮", "离"): "山火贲",
    ("艮", "坤"): "山地剥",
    ("坤", "震"): "地雷复",
    ("乾", "震"): "天雷无妄",
    ("艮", "乾"): "山天大畜",
    ("艮", "震"): "山雷颐",
    ("兑", "巽"): "泽风大过",
    ("坎", "坎"): "坎为水",
    ("离", "离"): "离为火",
    ("兑", "艮"): "泽山咸",
    ("震", "巽"): "雷风恒",
    ("乾", "艮"): "天山遁",
    ("震", "乾"): "雷天大壮",
    ("离", "坤"): "火地晋",
    ("坤", "离"): "地火明夷",
    ("巽", "离"): "风火家人",
    ("离", "兑"): "火泽睽",
    ("坎", "艮"): "水山蹇",
    ("震", "坎"): "雷水解",
    ("艮", "兑"): "山泽损",
    ("巽", "震"): "风雷益",
    ("兑", "乾"): "泽天夬",
    ("乾", "巽"): "天风姤",
    ("兑", "坤"): "泽地萃",
    ("坤", "巽"): "地风升",
    ("兑", "坎"): "泽水困",
    ("坎", "巽"): "水风井",
    ("兑", "离"): "泽火革",
    ("离", "巽"): "火风鼎",
    ("震", "震"): "震为雷",
    ("艮", "艮"): "艮为山",
    ("巽", "艮"): "风山渐",
    ("震", "兑"): "雷泽归妹",
    ("震", "离"): "雷火丰",
    ("离", "艮"): "火山旅",
    ("巽", "巽"): "巽为风",
    ("兑", "兑"): "兑为泽",
    ("巽", "坎"): "风水涣",
    ("坎", "兑"): "水泽节",
    ("巽", "兑"): "风泽中孚",
    ("震", "艮"): "雷山小过",
    ("坎", "离"): "水火既济",
    ("离", "坎"): "火水未济",
}

HEXAGRAM_BRIEFS = {
    "乾为天": "气势强而主动，适合开局、争取、定规则，但要避免只凭强势硬推。",
    "坤为地": "重在承接、配合和积累，宜顺势铺垫，不宜急着抢先。",
    "水雷屯": "新事初起而多阻，先稳住基础，再一点点疏通。",
    "山水蒙": "信息未明，适合学习、求证、请教，不宜凭猜测定论。",
    "水天需": "有所等待，条件未齐，守住节奏比急进更重要。",
    "天水讼": "有争执和分歧，先讲证据、规则和边界。",
    "地水师": "需要组织、纪律和统一方向，众力可用但要防内耗。",
    "水地比": "讲联结与依附，适合寻找同盟，也要分辨谁可靠。",
    "风天小畜": "小有积蓄但未到大成，先收束资源，等待突破口。",
    "天泽履": "行事如履薄冰，礼数、分寸和风险意识是关键。",
    "地天泰": "上下相通，局势有打开感，适合推进与协作。",
    "天地否": "上下不通，沟通受阻，先别硬冲，需另寻通路。",
    "天火同人": "适合公开沟通、求同存异，以共同目标聚人。",
    "火天大有": "资源较足，机会明显，但越顺越要管好分配和尺度。",
    "地山谦": "以退为进，谦逊守分反而能得势。",
    "雷地豫": "有发动和鼓舞之象，适合预备、动员，但要防空热闹。",
    "泽雷随": "随势而行，跟对节奏有利，别被短期情绪牵走。",
    "山风蛊": "旧问题需要整理修复，先处理积弊，再谈新局。",
    "地泽临": "机会靠近，适合主动接触，但要稳住承诺。",
    "风地观": "先观察全局，少急表态，多看真实反馈。",
    "火雷噬嗑": "有阻隔需咬开，适合处理规则、冲突、卡点。",
    "山火贲": "外在包装和表达重要，但不能只顾好看。",
    "山地剥": "局势有剥落消耗，宜保守减损，先护住核心。",
    "地雷复": "转机初回，适合修复、回头、重新开始。",
    "天雷无妄": "顺其正道，不宜妄动；越真实越安全。",
    "山天大畜": "力量在蓄积，先储备能力和资源，等待更大时机。",
    "山雷颐": "重在养护与口舌，管住输入输出，先补状态。",
    "泽风大过": "压力超载，梁木将弯，必须调整结构和承重。",
    "坎为水": "险象重复，宜谨慎探路，不要一次押满。",
    "离为火": "事情显现、信息变亮，适合看清真相，也要防过热。",
    "泽山咸": "感应、吸引、互动明显，关系和情绪会放大影响。",
    "雷风恒": "贵在稳定持续，短期波动不如长期节奏重要。",
    "天山遁": "退避不是失败，暂离压力源可保全主动权。",
    "雷天大壮": "势头很强，宜正当用力，忌逞强越界。",
    "火地晋": "有上升和被看见之象，适合展示成果、争取机会。",
    "地火明夷": "光明受伤，宜低调保护自己，等待环境转明。",
    "风火家人": "内部秩序、亲近关系和分工会决定外部结果。",
    "火泽睽": "意见相左，各看各的理；先求小同，再谈大合。",
    "水山蹇": "前路受阻，宜回身修路，求助比硬闯有效。",
    "雷水解": "阻滞有解开之机，适合松绑、和解、调整压力。",
    "山泽损": "有取舍和减法，舍小可保大，别怕删减。",
    "风雷益": "有增益和互助之象，行动越具体，收益越明显。",
    "泽天夬": "需要决断和摊牌，拖延会让问题继续膨胀。",
    "天风姤": "意外相遇、突发机会，也要防来得快去得快。",
    "泽地萃": "人事聚集，适合会合资源，但需防杂乱。",
    "地风升": "渐进上升，靠积累、耐心和正确路径取胜。",
    "泽水困": "受困受限，先保状态，少做无效消耗。",
    "水风井": "资源可用但要打通渠道，重在长期供给。",
    "泽火革": "旧局要变，适合改革、换法，但需先取得认可。",
    "火风鼎": "有更新与成器之象，适合重组资源、做成熟成品。",
    "震为雷": "动象强，事情会被触发；先稳住反应，再借势行动。",
    "艮为山": "止而不动，适合设边界、暂停、观察。",
    "风山渐": "循序渐进，慢慢靠近比一步到位更稳。",
    "雷泽归妹": "关系与安排未必正位，宜慎承诺、看条件。",
    "雷火丰": "盛大而明亮，机会多但也容易过满，注意收束。",
    "火山旅": "处在过渡和客位，适合灵活处理，不宜久恋一处。",
    "巽为风": "渗透、沟通、反复确认，柔进比硬冲有效。",
    "兑为泽": "表达、交换、喜悦之象，口头承诺需落到实处。",
    "风水涣": "散而需聚，先化开僵局，再重建共识。",
    "水泽节": "节制和规则是关键，定边界反而让局面可行。",
    "风泽中孚": "诚信、内外一致，真话和信任会影响结果。",
    "雷山小过": "小事可过，大事宜谨慎；细节比声势重要。",
    "水火既济": "阶段已成但仍需维护，别在收尾处松手。",
    "火水未济": "尚未完成，方向已见但条件仍需校准。",
}

PALACE_SEQUENCES = {
    "乾": ["乾为天", "天风姤", "天山遁", "天地否", "风地观", "山地剥", "火地晋", "火天大有"],
    "坎": ["坎为水", "水泽节", "水雷屯", "水火既济", "泽火革", "雷火丰", "地火明夷", "地水师"],
    "艮": ["艮为山", "山火贲", "山天大畜", "山泽损", "火泽睽", "天泽履", "风泽中孚", "风山渐"],
    "震": ["震为雷", "雷地豫", "雷水解", "雷风恒", "地风升", "水风井", "泽风大过", "泽雷随"],
    "巽": ["巽为风", "风天小畜", "风火家人", "风雷益", "天雷无妄", "火雷噬嗑", "山雷颐", "山风蛊"],
    "离": ["离为火", "火山旅", "火风鼎", "火水未济", "山水蒙", "风水涣", "天水讼", "天火同人"],
    "坤": ["坤为地", "地雷复", "地泽临", "地天泰", "雷天大壮", "泽天夬", "水天需", "水地比"],
    "兑": ["兑为泽", "泽水困", "泽地萃", "泽山咸", "水山蹇", "地山谦", "雷山小过", "雷泽归妹"],
}
PALACE_LOOKUP: dict[str, tuple[str, int]] = {}
for palace_name, sequence in PALACE_SEQUENCES.items():
    for stage_index, hexagram_name in enumerate(sequence):
        PALACE_LOOKUP[hexagram_name] = (palace_name, stage_index)

STAGE_NAMES = ["本宫六世", "一世", "二世", "三世", "四世", "五世", "游魂", "归魂"]
SHI_YING_BY_STAGE = {
    0: (6, 3),
    1: (1, 4),
    2: (2, 5),
    3: (3, 6),
    4: (4, 1),
    5: (5, 2),
    6: (4, 1),
    7: (3, 6),
}

NAJIA_BRANCHES = {
    "乾": {"inner": ("子", "寅", "辰"), "outer": ("午", "申", "戌")},
    "坤": {"inner": ("未", "巳", "卯"), "outer": ("丑", "亥", "酉")},
    "震": {"inner": ("子", "寅", "辰"), "outer": ("午", "申", "戌")},
    "巽": {"inner": ("丑", "亥", "酉"), "outer": ("未", "巳", "卯")},
    "坎": {"inner": ("寅", "辰", "午"), "outer": ("申", "戌", "子")},
    "离": {"inner": ("卯", "丑", "亥"), "outer": ("酉", "未", "巳")},
    "艮": {"inner": ("辰", "午", "申"), "outer": ("戌", "子", "寅")},
    "兑": {"inner": ("巳", "卯", "丑"), "outer": ("亥", "酉", "未")},
}

LINE_NAMES = ["初爻", "二爻", "三爻", "四爻", "五爻", "上爻"]
LINE_POSITION_TEXT = {
    1: "初爻主起点和根基，动在这里，多是事情刚被触发，先看基础是否稳。",
    2: "二爻主内部执行和实际状态，动在这里，说明关键在具体落实。",
    3: "三爻主进退关口，动在这里，容易有压力、犹豫或临界选择。",
    4: "四爻主外部机会和临近位置，动在这里，外界条件开始影响结果。",
    5: "五爻主核心和主导，动在这里，关键人物、规则或主要决定会推动变化。",
    6: "上爻主收束和过度，动在这里，说明事情已近尾声或容易走到极端。",
}

SIX_GOD_CYCLE = ["青龙", "朱雀", "勾陈", "腾蛇", "白虎", "玄武"]
SIX_GOD_START_BY_DAY_STEM = {
    "甲": 0,
    "乙": 0,
    "丙": 1,
    "丁": 1,
    "戊": 2,
    "己": 3,
    "庚": 4,
    "辛": 4,
    "壬": 5,
    "癸": 5,
}

RELATIONSHIP_KEYWORDS = ["感情", "恋爱", "喜欢", "复合", "分手", "暧昧", "对象", "伴侣", "婚", "前任", "他", "她", "ta", "TA", "对方"]
TOPIC_RULES = [
    ("父母", "文书/考试/消息", ["考试", "成绩", "证书", "合同", "消息", "回复", "通知", "文书", "论文", "申请", "签证", "offer", "录取"]),
    ("妻财", "财务/资源/收益", ["钱", "财", "工资", "收入", "投资", "买", "卖", "生意", "资源", "收益", "回款", "中奖", "价格"]),
    ("官鬼", "工作/职位/压力/规则", ["工作", "面试", "职位", "升职", "事业", "领导", "官司", "诉讼", "压力", "规则", "公司", "项目"]),
    ("兄弟", "朋友/同伴/竞争", ["朋友", "同事", "同学", "队友", "合作", "竞争", "群", "关系网"]),
    ("子孙", "作品/子女/宠物/放松", ["孩子", "子女", "宠物", "作品", "创作", "娱乐", "休息", "病好", "恢复"]),
]


def normalize_datetime(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(BEIJING_TZ)
    if now.tzinfo is None:
        return now.replace(tzinfo=BEIJING_TZ)
    return now.astimezone(BEIJING_TZ)


def mod_to_trigram_number(value: int) -> int:
    remainder = value % 8
    return 8 if remainder == 0 else remainder


def mod_to_moving_line(value: int) -> int:
    remainder = value % 6
    return 6 if remainder == 0 else remainder


def hexagram_from_trigrams(upper: str, lower: str) -> dict[str, Any]:
    upper_info = TRIGRAMS[upper]
    lower_info = TRIGRAMS[lower]
    lines = tuple(lower_info["lines"] + upper_info["lines"])
    name = HEXAGRAM_NAMES.get((upper, lower), f"{upper}{lower}卦")
    return {
        "name": name,
        "upper": upper,
        "lower": lower,
        "lines": lines,
        "brief": HEXAGRAM_BRIEFS.get(name, "此卦重在观察上下卦的生克与动爻变化，按当前趋势审慎推进。"),
    }


def changed_hexagram(hexagram: dict[str, Any], moving_line: int) -> dict[str, Any]:
    changed_lines = list(hexagram["lines"])
    changed_lines[moving_line - 1] = 0 if changed_lines[moving_line - 1] else 1
    lower = TRIGRAM_BY_LINES[tuple(changed_lines[:3])]
    upper = TRIGRAM_BY_LINES[tuple(changed_lines[3:])]
    return hexagram_from_trigrams(upper, lower)


def line_symbol(is_yang: int) -> str:
    return "━━━" if is_yang else "━ ━"


def element_relation(actor_element: str, target_element: str, actor_label: str = "体", target_label: str = "用") -> tuple[str, str, int]:
    if actor_element == target_element:
        return "比和", f"{actor_label}{target_label}同气，事情较容易同频，但也可能互相牵制。", 1
    if GENERATES[actor_element] == target_element:
        return f"{actor_label}生{target_label}", f"{actor_label}去生{target_label}，多为自己付出、投入资源换进展。", -1
    if GENERATES[target_element] == actor_element:
        return f"{target_label}生{actor_label}", f"{target_label}来生{actor_label}，外部条件或事情本身对你有助力。", 2
    if CONTROLS[actor_element] == target_element:
        return f"{actor_label}克{target_label}", f"{actor_label}能制{target_label}，可主动处理，但要注意别用力过猛。", 1
    if CONTROLS[target_element] == actor_element:
        return f"{target_label}克{actor_label}", f"{target_label}克{actor_label}，压力在外部，当前不宜硬碰硬。", -2
    return "不明", "体用关系不明，先按动爻和日月旺衰观察。", 0


def influence_score(target_element: str, source_element: str) -> int:
    if target_element == source_element:
        return 2
    if GENERATES[source_element] == target_element:
        return 2
    if GENERATES[target_element] == source_element:
        return -1
    if CONTROLS[source_element] == target_element:
        return -2
    if CONTROLS[target_element] == source_element:
        return 1
    return 0


def score_label(score: int) -> str:
    if score >= 6:
        return "旺"
    if score >= 3:
        return "得助"
    if score >= 0:
        return "平"
    if score >= -3:
        return "偏弱"
    return "受制"


def weighted_element_score(element: str, month_element: str, day_element: str, time_element: str) -> tuple[int, str]:
    parts = [("月建", month_element, 2), ("日辰", day_element, 2), ("时辰", time_element, 1)]
    score = sum(influence_score(element, source) * weight for _, source, weight in parts)
    detail = "、".join(f"{label}{source}" for label, source, _ in parts)
    return score, f"{detail}，{element}气为{score_label(score)}"


def relative_by_palace(palace_element: str, line_element: str) -> str:
    if palace_element == line_element:
        return "兄弟"
    if GENERATES[palace_element] == line_element:
        return "子孙"
    if GENERATES[line_element] == palace_element:
        return "父母"
    if CONTROLS[palace_element] == line_element:
        return "妻财"
    if CONTROLS[line_element] == palace_element:
        return "官鬼"
    return "六亲"


def six_gods(day_stem: str) -> list[str]:
    start = SIX_GOD_START_BY_DAY_STEM.get(day_stem, 0)
    return [SIX_GOD_CYCLE[(start + index) % len(SIX_GOD_CYCLE)] for index in range(6)]


def line_branches(upper: str, lower: str) -> tuple[str, ...]:
    return tuple(NAJIA_BRANCHES[lower]["inner"] + NAJIA_BRANCHES[upper]["outer"])


def branch_flags(branch: str, month_branch: str, day_branch: str, xun_kong: str) -> list[str]:
    flags: list[str] = []
    if branch in xun_kong:
        flags.append("空")
    if branch == month_branch:
        flags.append("临月")
    if branch == day_branch:
        flags.append("临日")
    if BRANCH_OPPOSITES.get(branch) == month_branch:
        flags.append("月破")
    if BRANCH_OPPOSITES.get(branch) == day_branch:
        flags.append("日冲")
    return flags


def build_line_records(hexagram: dict[str, Any], moving_line: int, lunar: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    palace, stage_index = PALACE_LOOKUP.get(hexagram["name"], (hexagram["upper"], 0))
    palace_element = TRIGRAMS[palace]["element"]
    shi_line, ying_line = SHI_YING_BY_STAGE.get(stage_index, (6, 3))
    branches = line_branches(hexagram["upper"], hexagram["lower"])
    day_stem = lunar.getDayGanExact()
    month_branch = lunar.getMonthZhiExact()
    day_branch = lunar.getDayZhiExact()
    xun_kong = lunar.getDayXunKongExact()
    gods = six_gods(day_stem)
    records: list[dict[str, Any]] = []
    for index, (is_yang, branch, god) in enumerate(zip(hexagram["lines"], branches, gods), start=1):
        element = BRANCH_ELEMENTS[branch]
        markers: list[str] = []
        if index == shi_line:
            markers.append("世")
        if index == ying_line:
            markers.append("应")
        if index == moving_line:
            markers.append("动")
        records.append({
            "index": index,
            "name": LINE_NAMES[index - 1],
            "yang": bool(is_yang),
            "symbol": line_symbol(is_yang),
            "branch": branch,
            "element": element,
            "relative": relative_by_palace(palace_element, element),
            "god": god,
            "markers": markers,
            "flags": branch_flags(branch, month_branch, day_branch, xun_kong),
        })
    meta = {
        "palace": palace,
        "palace_element": palace_element,
        "stage": STAGE_NAMES[stage_index],
        "shi_line": shi_line,
        "ying_line": ying_line,
        "day_stem": day_stem,
        "month_branch": month_branch,
        "day_branch": day_branch,
        "xun_kong": xun_kong,
    }
    return records, meta


def format_line_records(records: list[dict[str, Any]]) -> list[str]:
    lines = []
    for record in reversed(records):
        markers = f" [{' '.join(record['markers'])}]" if record["markers"] else ""
        flags = f"（{'、'.join(record['flags'])}）" if record["flags"] else ""
        lines.append(
            f"{record['name']} {record['god']} {record['relative']} {record['branch']}{record['element']} {record['symbol']}{markers}{flags}"
        )
    return lines


def describe_record(record: dict[str, Any]) -> str:
    markers = f"[{' '.join(record['markers'])}]" if record["markers"] else ""
    flags = f"（{'、'.join(record['flags'])}）" if record["flags"] else ""
    return f"{record['name']}{markers}{record['relative']}{record['branch']}{record['element']}{flags}"


def status_from_flags(record: dict[str, Any]) -> str:
    flags = set(record["flags"])
    notes = []
    if "空" in flags:
        notes.append("空亡，当前像是未落实、悬着或有名无实")
    if "临月" in flags or "临日" in flags:
        notes.append("得日月照应，力量较明显")
    if "月破" in flags:
        notes.append("月破，受大环境冲散")
    if "日冲" in flags:
        notes.append("日冲，短期有波动或被触发")
    if "动" in record["markers"]:
        notes.append("发动，代表事情会有变化点")
    return "；".join(notes) if notes else "状态中平，需结合体用和动爻看"


def infer_question_focus(question: str, records: list[dict[str, Any]], meta: dict[str, Any]) -> list[str]:
    q = question.strip()
    if not q:
        return ["问题取象：未指定具体问题，本次按近期整体趋势、行动时机和外部阻力来解读。"]

    lower_q = q.lower()
    if any(keyword.lower() in lower_q for keyword in RELATIONSHIP_KEYWORDS):
        shi = records[meta["shi_line"] - 1]
        ying = records[meta["ying_line"] - 1]
        relation, relation_text, _ = element_relation(shi["element"], ying["element"], "世", "应")
        return [
            "问题取象：此问偏关系/对方，先看世应。",
            f"世爻：{describe_record(shi)}；{status_from_flags(shi)}。",
            f"应爻：{describe_record(ying)}；{status_from_flags(ying)}。",
            f"世应关系：{relation}，{relation_text}",
        ]

    for relative, label, keywords in TOPIC_RULES:
        if any(keyword.lower() in lower_q for keyword in keywords):
            targets = [record for record in records if record["relative"] == relative]
            active = [record for record in targets if "动" in record["markers"]]
            empty = [record for record in targets if "空" in record["flags"]]
            broken = [record for record in targets if "月破" in record["flags"] or "日冲" in record["flags"]]
            lines = [f"问题取象：此问偏{label}，先看{relative}爻。"]
            if targets:
                lines.append("相关爻位：" + "；".join(describe_record(record) for record in targets) + "。")
            if active:
                lines.append("用神发动：" + "；".join(describe_record(record) for record in active) + "，事情有明显变化点。")
            if empty:
                lines.append("用神空亡：" + "；".join(describe_record(record) for record in empty) + "，当前不宜按已经落实来判断。")
            if broken:
                lines.append("用神受冲破：" + "；".join(describe_record(record) for record in broken) + "，短期波动偏大。")
            if len(lines) == 1:
                lines.append("相关爻状态不突出，回到体用关系和动爻看整体趋势。")
            return lines

    return ["问题取象：未命中特定六亲关键词，本次以体用关系、世应、动爻和变卦综合判断。"]


def build_time_context(now: datetime) -> dict[str, Any]:
    solar = Solar.fromYmdHms(now.year, now.month, now.day, now.hour, now.minute, now.second)
    lunar = solar.getLunar()
    lunar_month = lunar.getMonth()
    lunar_month_number = abs(int(lunar_month))
    lunar_day = int(lunar.getDay())
    year_branch = lunar.getYearZhiExact()
    time_branch = lunar.getTimeZhi()
    year_number = BRANCH_NUMBERS[year_branch]
    time_number = BRANCH_NUMBERS[time_branch]
    upper_source = year_number + lunar_month_number + lunar_day
    lower_source = upper_source + time_number
    upper_number = mod_to_trigram_number(upper_source)
    lower_number = mod_to_trigram_number(lower_source)
    moving_line = mod_to_moving_line(lower_source)
    upper = NUMBER_TO_TRIGRAM[upper_number]
    lower = NUMBER_TO_TRIGRAM[lower_number]
    original = hexagram_from_trigrams(upper, lower)
    changed = changed_hexagram(original, moving_line)
    return {
        "solar": solar,
        "lunar": lunar,
        "lunar_month_number": lunar_month_number,
        "lunar_day": lunar_day,
        "year_branch": year_branch,
        "time_branch": time_branch,
        "year_number": year_number,
        "time_number": time_number,
        "upper_source": upper_source,
        "lower_source": lower_source,
        "upper_number": upper_number,
        "lower_number": lower_number,
        "moving_line": moving_line,
        "original": original,
        "changed": changed,
    }


def trigram_label(name: str) -> str:
    info = TRIGRAMS[name]
    return f"{info['nature']}{name}{info['symbol']}（{info['element']}，{info['image']}）"


def lunar_date_text(lunar: Any) -> str:
    leap = "闰" if int(lunar.getMonth()) < 0 else ""
    return f"{lunar.getYearInChinese()}年{leap}{lunar.getMonthInChinese()}月{lunar.getDayInChinese()}"


def jieqi_text(lunar: Any) -> str:
    prev_jie = lunar.getPrevJie()
    next_jie = lunar.getNextJie()
    prev_text = f"{prev_jie.getName()}({prev_jie.getSolar().toYmd()})" if prev_jie else "无"
    next_text = f"{next_jie.getName()}({next_jie.getSolar().toYmd()})" if next_jie else "无"
    return f"上一节：{prev_text}；下一节：{next_text}"


def list_text(items: list[str], limit: int = 5) -> str:
    return "、".join(str(item) for item in items[:limit]) if items else "无"


def conclusion_label(relation_key: str, relation_score: int, body_score: int, moving_record: dict[str, Any]) -> str:
    flags = set(moving_record["flags"])
    total = relation_score + body_score
    if "月破" in flags:
        total -= 2
    if "空" in flags:
        total -= 1
    if "临日" in flags or "临月" in flags:
        total += 1
    if relation_key.endswith("生体") or relation_key == "比和":
        total += 1
    if relation_key.endswith("克体"):
        total -= 2
    if total >= 4:
        return "偏顺，可推进"
    if total >= 1:
        return "有机会，宜稳步试探"
    if total >= -2:
        return "中平偏谨慎，先处理卡点"
    return "压力较大，宜缓行或换法"


def suanming_reading(question: str, now: datetime | None = None) -> str:
    question = question.strip()
    current = normalize_datetime(now)
    context = build_time_context(current)
    lunar = context["lunar"]
    original = context["original"]
    changed = context["changed"]
    moving_line = int(context["moving_line"])
    records, meta = build_line_records(original, moving_line, lunar)
    moving_record = records[moving_line - 1]

    body_trigram = original["upper"] if moving_line <= 3 else original["lower"]
    use_trigram = original["lower"] if moving_line <= 3 else original["upper"]
    body_element = TRIGRAMS[body_trigram]["element"]
    use_element = TRIGRAMS[use_trigram]["element"]
    relation_key, relation_text, relation_score = element_relation(body_element, use_element, "体", "用")

    month_element = BRANCH_ELEMENTS[lunar.getMonthZhiExact()]
    day_element = BRANCH_ELEMENTS[lunar.getDayZhiExact()]
    time_element = BRANCH_ELEMENTS[lunar.getTimeZhi()]
    body_score, body_score_text = weighted_element_score(body_element, month_element, day_element, time_element)
    use_score, use_score_text = weighted_element_score(use_element, month_element, day_element, time_element)
    conclusion = conclusion_label(relation_key, relation_score, body_score, moving_record)

    time_yi = list_text(lunar.getTimeYi())
    time_ji = list_text(lunar.getTimeJi())
    time_luck = lunar.getTimeTianShenLuck()
    time_tian_shen = lunar.getTimeTianShen()

    lines = [
        "🔮 六爻时间起卦",
        f"问题：{question or '未指定具体问题，本次按近期整体趋势与行动建议解读。'}",
        f"北京时间：{current.strftime('%Y-%m-%d %H:%M:%S')}",
        f"农历：{lunar_date_text(lunar)}",
        f"四柱：{lunar.getYearInGanZhiExact()}年 {lunar.getMonthInGanZhiExact()}月 {lunar.getDayInGanZhiExact()}日 {lunar.getTimeInGanZhi()}时",
        f"节令：{jieqi_text(lunar)}",
        f"旬空：日旬空 {lunar.getDayXunKongExact()}；时旬空 {lunar.getTimeXunKong()}",
        f"时辰参考：{lunar.getTimeZhi()}时天神 {time_tian_shen}，吉凶 {time_luck}；宜：{time_yi}；忌：{time_ji}",
        "",
        "起卦算法：",
        f"上卦 = 年支数({context['year_branch']}={context['year_number']}) + 农历月({context['lunar_month_number']}) + 农历日({context['lunar_day']}) = {context['upper_source']}，取八数为 {context['upper_number']} → {trigram_label(original['upper'])}",
        f"下卦 = 上式 + 时支数({context['time_branch']}={context['time_number']}) = {context['lower_source']}，取八数为 {context['lower_number']} → {trigram_label(original['lower'])}",
        f"动爻 = {context['lower_source']} 取六数为 {moving_line} → {LINE_NAMES[moving_line - 1]}",
        "",
        f"本卦：{original['name']}（{TRIGRAMS[original['upper']]['nature']}{original['upper']}上 / {TRIGRAMS[original['lower']]['nature']}{original['lower']}下）",
        f"卦意：{original['brief']}",
        f"变卦：{changed['name']}（{TRIGRAMS[changed['upper']]['nature']}{changed['upper']}上 / {TRIGRAMS[changed['lower']]['nature']}{changed['lower']}下）",
        f"变卦提示：{changed['brief']}",
        f"卦宫：{meta['palace']}宫{meta['palace_element']}，{meta['stage']}；世爻在{LINE_NAMES[meta['shi_line'] - 1]}，应爻在{LINE_NAMES[meta['ying_line'] - 1]}",
        "",
        "六爻排盘：",
        *format_line_records(records),
        "",
        "动爻解读：",
        f"{describe_record(moving_record)}发动，原为{'阳爻' if moving_record['yang'] else '阴爻'}，变为{'阴爻' if moving_record['yang'] else '阳爻'}。",
        LINE_POSITION_TEXT[moving_line],
        f"动爻状态：{status_from_flags(moving_record)}。",
        "",
        "问题取象：",
        *infer_question_focus(question, records, meta),
        "",
        "综合判断：",
        f"体卦：{trigram_label(body_trigram)}；用卦：{trigram_label(use_trigram)}。",
        f"体用关系：{relation_key}，{relation_text}",
        f"时令气势：体卦{body_score_text}；用卦{use_score_text}。",
        f"主线结论：{conclusion}。本卦看当前局面，变卦看后续趋势；这次结果更适合当作娱乐占卜和决策前的自我提醒。",
    ]
    return "\n".join(lines)
