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
SIX_GOD_CYCLE = ["青龙", "朱雀", "勾陈", "腾蛇", "白虎", "玄武"]
SIX_GOD_START_BY_DAY_STEM = {"甲": 0, "乙": 0, "丙": 1, "丁": 1, "戊": 2, "己": 3, "庚": 4, "辛": 4, "壬": 5, "癸": 5}
LINE_NAMES = ["初爻", "二爻", "三爻", "四爻", "五爻", "上爻"]
LINE_POSITION_TEXT = {
    1: "初爻主起点和根基，动在这里，多是事情刚被触发，先看基础是否稳。",
    2: "二爻主内部执行和实际状态，动在这里，说明关键在具体落实。",
    3: "三爻主进退关口，动在这里，容易有压力、犹豫或临界选择。",
    4: "四爻主外部机会和临近位置，动在这里，外界条件开始影响结果。",
    5: "五爻主核心和主导，动在这里，关键人物、规则或主要决定会推动变化。",
    6: "上爻主收束和过度，动在这里，说明事情已近尾声或容易走到极端。",
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
    upper_element = upper_info["element"]
    lower_element = lower_info["element"]
    if upper_element == lower_element:
        brief = "上下同气，局势会在同一种力量里打转，重在稳住节奏。"
    elif GENERATES[upper_element] == lower_element:
        brief = "上卦在生下卦，说明上层力量愿意往下落，推进感较强。"
    elif GENERATES[lower_element] == upper_element:
        brief = "下卦在生上卦，底层条件在托举上层，适合顺势借力。"
    elif CONTROLS[upper_element] == lower_element:
        brief = "上卦能压住下卦，能推动，但也容易用力过猛。"
    elif CONTROLS[lower_element] == upper_element:
        brief = "下卦反过来制住上卦，外部变量更强，先缓冲更合适。"
    else:
        brief = "上下卦处在拉扯态，重点看动爻和后续变化。"
    return {"name": f"{upper}上{lower}下", "upper": upper, "lower": lower, "brief": brief}


def changed_hexagram(hexagram: dict[str, Any], moving_line: int) -> dict[str, Any]:
    changed_lines = list(TRIGRAMS[hexagram["lower"]]["lines"] + TRIGRAMS[hexagram["upper"]]["lines"])
    changed_lines[moving_line - 1] = 0 if changed_lines[moving_line - 1] else 1
    lower = TRIGRAM_BY_LINES[tuple(changed_lines[:3])]
    upper = TRIGRAM_BY_LINES[tuple(changed_lines[3:])]
    return hexagram_from_trigrams(upper, lower)


def line_symbol(is_yang: int) -> str:
    return "━━━" if is_yang else "━ ━"


def six_gods(day_stem: str) -> list[str]:
    start = SIX_GOD_START_BY_DAY_STEM.get(day_stem, 0)
    return [SIX_GOD_CYCLE[(start + index) % len(SIX_GOD_CYCLE)] for index in range(6)]


def line_branches(upper: str, lower: str) -> tuple[str, ...]:
    return tuple(NAJIA_BRANCHES[lower]["inner"] + NAJIA_BRANCHES[upper]["outer"])


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


def weighted_element_score(element: str, month_element: str, day_element: str, time_element: str) -> tuple[int, str]:
    parts = [("月建", month_element, 2), ("日辰", day_element, 2), ("时辰", time_element, 1)]
    score = sum(influence_score(element, source) * weight for _, source, weight in parts)
    detail = "、".join(f"{label}{source}" for label, source, _ in parts)
    if score >= 6:
        strength = "旺"
    elif score >= 3:
        strength = "得助"
    elif score >= 0:
        strength = "平"
    elif score >= -3:
        strength = "偏弱"
    else:
        strength = "受制"
    return score, f"{detail}，{element}气为{strength}"


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


def describe_record(record: dict[str, Any]) -> str:
    markers = f"[{' '.join(record['markers'])}]" if record["markers"] else ""
    flags = f"（{'、'.join(record['flags'])}）" if record["flags"] else ""
    return f"{record['name']}{markers}{record['relative']}{record['branch']}{record['element']}{flags}"


def status_from_flags(record: dict[str, Any]) -> str:
    flags = set(record["flags"])
    notes: list[str] = []
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


def question_theme(question: str) -> str:
    q = question.strip().lower()
    if not q:
        return "整体走势"
    if any(keyword.lower() in q for keyword in RELATIONSHIP_KEYWORDS):
        return "关系/对方"
    for _, label, keywords in TOPIC_RULES:
        if any(keyword.lower() in q for keyword in keywords):
            return label
    return "综合事项"


def relation_advice(relation_key: str) -> str:
    if relation_key == "体生用":
        return "你这边会更费力一些，适合小步推进，不适合一下子把筹码压满。"
    if relation_key == "用生体":
        return "外部条件在帮你，适合顺势把事推一段。"
    if relation_key == "体克用":
        return "你有处理局面的能力，但要收着力，别把自己也耗进去。"
    if relation_key == "用克体":
        return "外部压力更大，先缓一缓、先减损，不要正面硬碰。"
    return "双方力量比较接近，最重要的是稳住节奏，别自己先乱。"


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


def conclusion_advice(conclusion: str) -> str:
    if conclusion == "偏顺，可推进":
        return "整体可以往前走，但别把顺势误当成可以跳步骤。"
    if conclusion == "有机会，宜稳步试探":
        return "有机会，不过更像试探式推进，先看回响再加码。"
    if conclusion == "中平偏谨慎，先处理卡点":
        return "现在更像卡在中段，先拆掉最碍事的那个点，结果会清楚很多。"
    return "眼下压力偏重，硬顶只会更累，换方法或先缓一缓更合适。"


def build_line_records(hexagram: dict[str, Any], moving_line: int, lunar: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    upper = hexagram["upper"]
    lower = hexagram["lower"]
    lines = TRIGRAMS[lower]["lines"] + TRIGRAMS[upper]["lines"]
    branches = line_branches(upper, lower)
    day_stem = lunar.getDayGanExact()
    gods = six_gods(day_stem)
    month_branch = lunar.getMonthZhiExact()
    day_branch = lunar.getDayZhiExact()
    xun_kong = lunar.getDayXunKongExact()
    shi_line = ((TRIGRAMS[upper]["number"] + TRIGRAMS[lower]["number"] + moving_line) % 6) + 1
    ying_line = 7 - shi_line
    records: list[dict[str, Any]] = []
    for index, (is_yang, branch, god) in enumerate(zip(lines, branches, gods), start=1):
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
            "relative": relative_by_palace(TRIGRAMS[upper]["element"], element),
            "god": god,
            "markers": markers,
            "flags": branch_flags(branch, month_branch, day_branch, xun_kong),
        })
    meta = {
        "shi_line": shi_line,
        "ying_line": ying_line,
        "palace": upper,
        "palace_element": TRIGRAMS[upper]["element"],
        "stage": "简化盘",
    }
    return records, meta


def format_line_records(records: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for record in reversed(records):
        markers = f" [{' '.join(record['markers'])}]" if record["markers"] else ""
        flags = f"（{'、'.join(record['flags'])}）" if record["flags"] else ""
        lines.append(f"{record['name']} {record['god']} {record['relative']} {record['branch']}{record['element']} {record['symbol']}{markers}{flags}")
    return lines


def infer_question_focus(question: str, records: list[dict[str, Any]], meta: dict[str, Any]) -> list[str]:
    q = question.strip()
    if not q:
        return ["这次没有指定具体问题，所以先按整体局势来读。"]
    lower_q = q.lower()
    if any(keyword.lower() in lower_q for keyword in RELATIONSHIP_KEYWORDS):
        shi = records[meta["shi_line"] - 1]
        ying = records[meta["ying_line"] - 1]
        relation, relation_text, _ = element_relation(shi["element"], ying["element"], "世", "应")
        return [
            "这件事更像关系/对方题，先看世应。",
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
            lines = [f"这件事更像{label}题，重点先看{relative}爻。"]
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
    return ["没有命中特定主题，先看体用、世应和动爻的关系。"]


def build_human_summary_lines(
    question: str,
    original: dict[str, Any],
    changed: dict[str, Any],
    moving_record: dict[str, Any],
    moving_line: int,
    relation_key: str,
    relation_text: str,
    conclusion: str,
) -> list[str]:
    theme = question_theme(question)
    q = question.strip()
    moving_name = LINE_NAMES[moving_line - 1]
    lines: list[str] = []
    lines.append(f"对象：{q or '整体走势'}，这卦更偏{theme}。")
    lines.append(f"现状：本卦{original['name']}，味道是「{original['brief']}」。")
    lines.append(f"转折：{moving_name}发动，变化点在这里；{LINE_POSITION_TEXT[moving_line]}")
    lines.append(f"阻碍：{status_from_flags(moving_record)}。")
    lines.append(f"体用：{relation_key}。{relation_text}{relation_advice(relation_key)}")
    lines.append(f"后势：变卦{changed['name']}，后面更像「{changed['brief']}」。")
    lines.append(f"建议：{conclusion_advice(conclusion)}")
    lines.append(f"结论：{conclusion}。")
    return lines


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
        f"本卦：{original['name']}（{trigram_label(original['upper'])} / {trigram_label(original['lower'])}）",
        f"卦意：{original['brief']}",
        f"变卦：{changed['name']}（{trigram_label(changed['upper'])} / {trigram_label(changed['lower'])}）",
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
        "盘面提示：",
        *infer_question_focus(question, records, meta),
        "",
        "综合判断：",
        f"体卦：{trigram_label(body_trigram)}；用卦：{trigram_label(use_trigram)}。",
        f"体用关系：{relation_key}，{relation_text}",
        f"时令气势：体卦{body_score_text}；用卦{use_score_text}。",
        f"主线结论：{conclusion}。",
        "",
        "解读：",
        *build_human_summary_lines(question, original, changed, moving_record, moving_line, relation_key, relation_text, conclusion),
        "这卦更适合当作参考和提醒，不必把它当成唯一答案。",
    ]
    return "\n".join(lines)
