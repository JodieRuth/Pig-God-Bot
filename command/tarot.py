from __future__ import annotations

import hashlib
import random
from collections import Counter
from typing import Any

MAJOR_ARCANA = [
    {
        "name": "愚者",
        "upright": "新的开始、自由探索、轻装上路、愿意踏入未知",
        "reversed": "鲁莽冲动、缺少准备、逃避责任、把未知误当成借口",
        "advice": [
            "可以开始，但先确认最低限度的安全边界。",
            "别等到所有条件完美才行动，先迈出可回收的一小步。",
            "把好奇心留下，把不必要的冒险拿掉。",
            "适合尝试新路线，但不要让兴奋替你做判断。",
        ],
    },
    {
        "name": "魔术师",
        "upright": "行动力、创造、资源整合、把想法落地",
        "reversed": "资源错配、表达失真、空有想法、技巧被用错方向",
        "advice": [
            "先盘点手上已有资源，再决定怎么推进。",
            "把目标拆成一个可验证的动作，不要停在构想阶段。",
            "表达要具体，越模糊越容易消耗机会。",
            "把能力用在解决问题上，而不是证明自己有能力。",
        ],
    },
    {
        "name": "女祭司",
        "upright": "直觉、秘密、潜意识、静观其变、等待信息浮现",
        "reversed": "忽略直觉、信息不透明、过度压抑、秘密带来误判",
        "advice": [
            "暂时别急着表态，先听见那些没有被明说的信号。",
            "把直觉写下来，再用事实逐项核对。",
            "不要逼问答案，先让信息自然浮出水面。",
            "保护隐私和边界，这会让判断更清醒。",
        ],
    },
    {
        "name": "女皇",
        "upright": "滋养、丰盛、关系成长、创造力、稳定的照料",
        "reversed": "过度付出、依赖舒适区、创造力堵塞、关系失衡",
        "advice": [
            "给事情一点成长空间，别用焦虑催熟它。",
            "照顾别人之前，先确认自己的消耗是否过量。",
            "适合用温和、持续的方式推进。",
            "把抽象期待变成具体照料，关系和成果都会更稳。",
        ],
    },
    {
        "name": "皇帝",
        "upright": "秩序、责任、边界、掌控局面、稳定结构",
        "reversed": "控制过度、僵化、责任逃避、边界混乱",
        "advice": [
            "先定规则和边界，再谈投入和期待。",
            "把主动权拿回来，但不要把控制欲当成安全感。",
            "适合用计划、制度和明确分工解决问题。",
            "如果局面松散，先搭一个能执行的框架。",
        ],
    },
    {
        "name": "教皇",
        "upright": "传统、学习、规则、寻求可靠建议、群体认同",
        "reversed": "盲从权威、规则束缚、价值观冲突、经验不再适配",
        "advice": [
            "找可靠的人或成熟经验参考，但保留自己的判断。",
            "先理解规则，再决定要遵守、调整还是突破。",
            "这件事需要名分、流程或共识来稳定。",
            "别为了显得合群而放弃真正重要的价值。",
        ],
    },
    {
        "name": "恋人",
        "upright": "选择、关系、价值观一致、真诚连接、相互吸引",
        "reversed": "摇摆不定、价值冲突、关系失衡、承诺含糊",
        "advice": [
            "回到价值观本身，别只被短期感受牵着走。",
            "重要选择需要诚实沟通，不适合靠猜。",
            "关系里的答案不只看喜欢，也看能否共同承担。",
            "先确认自己真正想选什么，再谈别人怎么回应。",
        ],
    },
    {
        "name": "战车",
        "upright": "意志、推进、胜利、控制方向、突破阻力",
        "reversed": "方向失控、急躁硬推、目标分裂、外强中干",
        "advice": [
            "把目标收束到一个方向，集中火力推进。",
            "适合主动争取，但速度必须服务于方向。",
            "别一边踩油门一边怀疑路线，先校准再加速。",
            "胜负心可以用，但不要让它盖过判断。",
        ],
    },
    {
        "name": "力量",
        "upright": "勇气、温柔的坚持、自我驯服、稳定耐力",
        "reversed": "信心不足、情绪失控、硬撑疲惫、内在拉扯",
        "advice": [
            "用稳定和耐心处理，不必靠强硬证明。",
            "先安顿情绪，再处理事件本身。",
            "真正的力量是可持续的，不是一次性硬撑。",
            "对自己温柔一点，事情反而更容易推进。",
        ],
    },
    {
        "name": "隐者",
        "upright": "独处、反思、寻找答案、内在智慧、暂离喧闹",
        "reversed": "孤立、拒绝交流、陷入过度分析、答案被拖延",
        "advice": [
            "给自己一点安静时间，答案需要沉淀。",
            "暂时减少外界噪音，先听清自己的判断。",
            "复盘是有用的，但别让复盘变成停滞。",
            "必要时找少数可信的人，而不是向所有人求证。",
        ],
    },
    {
        "name": "命运之轮",
        "upright": "转机、循环、不可控变化、顺势而为、阶段切换",
        "reversed": "时机不稳、反复卡关、抗拒变化、旧循环未结束",
        "advice": [
            "承认局势在变化，然后顺势调整策略。",
            "不要把暂时的起伏误判成最终结果。",
            "观察重复出现的模式，机会和问题都藏在那里。",
            "抓住能抓住的部分，放下暂时无法控制的部分。",
        ],
    },
    {
        "name": "正义",
        "upright": "公平、因果、判断、承担结果、理性权衡",
        "reversed": "偏见、不公、逃避责任、信息不全导致误判",
        "advice": [
            "把事实、责任和情绪分开看。",
            "重要决定要留证据、讲规则、看长期后果。",
            "别只问想不想，也要问是否公平、是否承担得起。",
            "如果哪里不对等，先把边界说清楚。",
        ],
    },
    {
        "name": "倒吊人",
        "upright": "暂停、换角度、牺牲、等待时机、主动让渡",
        "reversed": "无意义拖延、抗拒放手、卡在旧视角、牺牲失衡",
        "advice": [
            "暂缓不是失败，换角度后再动更有效。",
            "看清自己正在交换什么，别无意识地消耗。",
            "如果推不动，先暂停并重新定义问题。",
            "放下一部分执念，反而能释放新的选择。",
        ],
    },
    {
        "name": "死神",
        "upright": "结束、转化、告别旧模式、重生、清理旧负担",
        "reversed": "抗拒结束、拖延转变、旧问题反复、害怕失去",
        "advice": [
            "该结束的部分要好好收尾，新的空间才会出现。",
            "别把熟悉误认为合适，变化已经在发生。",
            "先清理旧模式，再期待新结果。",
            "接受告别带来的不适，它不是坏事的全部。",
        ],
    },
    {
        "name": "节制",
        "upright": "平衡、调和、耐心、稳定修复、资源配比",
        "reversed": "失衡、过度、节奏混乱、沟通与资源无法调和",
        "advice": [
            "不要走极端，用中间路线慢慢修复。",
            "把节奏放稳，持续的小调整比猛然改变更有用。",
            "适合协商、整合和重新分配资源。",
            "先降低冲突浓度，再谈下一步。",
        ],
    },
    {
        "name": "恶魔",
        "upright": "执念、诱惑、束缚、欲望、看见依赖关系",
        "reversed": "摆脱束缚、看清成瘾模式、松动执念、重新获得自由",
        "advice": [
            "诚实看见自己被什么吸引或绑住。",
            "别用短期满足交换长期自由。",
            "先识别依赖模式，再谈改变。",
            "欲望本身不可怕，可怕的是不承认它在影响判断。",
        ],
    },
    {
        "name": "高塔",
        "upright": "突变、崩塌、真相显现、重建基础、旧结构破裂",
        "reversed": "延迟爆发、逃避真相、小范围震荡、拒绝重建",
        "advice": [
            "先处理已经松动的基础，别等它彻底崩塌。",
            "真相出现时不要只忙着否认，先评估损失和机会。",
            "适合拆掉不可靠的结构，重建比粉饰更重要。",
            "把不可控冲击转化成一次彻底整理。",
        ],
    },
    {
        "name": "星星",
        "upright": "希望、疗愈、指引、长期信念、恢复感",
        "reversed": "信念动摇、期待落空、疗愈延迟、看不见方向",
        "advice": [
            "保留长期信念，但把希望落到现实行动里。",
            "别急着证明一切会好，先做能恢复状态的事。",
            "适合修复、休整和重新建立方向感。",
            "希望不是空想，它需要持续被照料。",
        ],
    },
    {
        "name": "月亮",
        "upright": "迷雾、焦虑、幻象、信息不明、潜意识波动",
        "reversed": "迷雾散去、误会松动、焦虑外显、真相逐渐清楚",
        "advice": [
            "信息不明时不要急着脑补结论。",
            "把猜测和事实分开，焦虑会因此下降。",
            "适合等待更多证据，暂时不宜重仓判断。",
            "留意情绪投射，它可能正在改变你看到的东西。",
        ],
    },
    {
        "name": "太阳",
        "upright": "清晰、快乐、成功、能量充足、坦率表达",
        "reversed": "过度乐观、能量透支、细节被忽略、快乐打折",
        "advice": [
            "可以更坦率一点，好消息需要被看见。",
            "顺利时也别跳过细节，稳定比一时明亮更重要。",
            "把积极状态转化成具体推进。",
            "让事情透明化，很多问题会自然变简单。",
        ],
    },
    {
        "name": "审判",
        "upright": "觉醒、复盘、召唤、重要决定、阶段性清算",
        "reversed": "迟迟不决、害怕评价、复盘失真、错过召唤",
        "advice": [
            "该复盘的就复盘，该决定的也不要无限拖延。",
            "听见内心真正的召唤，而不是只听外界评价。",
            "把过去的经验整理成下一步的判断。",
            "别用旧身份限制新的选择。",
        ],
    },
    {
        "name": "世界",
        "upright": "完成、整合、圆满、进入新阶段、全局视角",
        "reversed": "临门一脚、收尾不完整、整合不足、难以进入下一阶段",
        "advice": [
            "先完成收尾，再开启下一段。",
            "从全局看问题，别被一个细节困住。",
            "把已有成果整合起来，它们比你想的更有价值。",
            "如果卡在最后一步，检查缺的是资源、确认还是告别。",
        ],
    },
]

SUITS = {
    "权杖": {
        "element": "火",
        "theme": "行动、热情、事业、创造冲劲",
        "upright": "行动力被点燃，重点在推进、表达和创造",
        "reversed": "行动能量受阻，可能表现为急躁、分散或热情消退",
        "advice": [
            "先行动，再根据反馈修正。",
            "把热情集中到一个最值得推进的方向。",
            "注意别用忙碌掩盖真正的问题。",
            "需要更多主动表达，而不是等别人来确认。",
            "如果已经过热，先降速再判断。",
        ],
    },
    "圣杯": {
        "element": "水",
        "theme": "情感、关系、感受、内在满足",
        "upright": "情绪和关系正在发挥影响，重点在感受、连接与接纳",
        "reversed": "情绪流动受阻，可能有逃避、误解或期待失衡",
        "advice": [
            "先确认真实感受，再处理外在选择。",
            "关系问题需要表达，也需要倾听。",
            "别让情绪替你下最终结论。",
            "照顾内在需求，但不要把所有期待交给别人。",
            "适合用柔软方式修复，而不是硬碰硬。",
        ],
    },
    "宝剑": {
        "element": "风",
        "theme": "思考、沟通、冲突、理性判断",
        "upright": "理性、语言和判断成为关键，重点在看清事实与表达立场",
        "reversed": "思考或沟通出现偏差，可能有误判、争执或过度内耗",
        "advice": [
            "把事实列出来，先别急着代入立场。",
            "该沟通的要说清楚，但语气会影响结果。",
            "避免反复脑内推演，找一个能验证的证据。",
            "如果冲突升温，先处理信息差。",
            "重要话题适合写下来，减少误解。",
        ],
    },
    "星币": {
        "element": "土",
        "theme": "金钱、现实、身体、长期积累",
        "upright": "现实资源和长期建设是重点，适合稳步累积",
        "reversed": "现实层面有压力，可能是资源不足、拖延或投入产出失衡",
        "advice": [
            "先算清成本、时间和可用资源。",
            "从最现实的一步开始，稳定比漂亮更重要。",
            "别忽略身体、金钱和日常秩序的影响。",
            "适合慢慢累积，不适合只靠冲动。",
            "如果回报不明，先缩小投入再观察。",
        ],
    },
}

RANKS = {
    "王牌": {
        "upright": "开端、种子、机会刚刚出现",
        "reversed": "机会未成熟、起步困难、种子需要重新筛选",
        "advice": ["保护刚出现的机会。", "先验证起点是否真实可行。", "别急着放大规模。"],
    },
    "二": {
        "upright": "选择、平衡、关系中的拉扯",
        "reversed": "摇摆、失衡、选择被拖延或回避",
        "advice": ["把选项摆到台面上。", "先确定权衡标准。", "别让拖延伪装成谨慎。"],
    },
    "三": {
        "upright": "合作、表达、初步成果",
        "reversed": "协作不顺、表达受阻、成果还不稳定",
        "advice": ["确认协作分工。", "把初步成果继续打磨。", "别因为一点进展就忽略基础。"],
    },
    "四": {
        "upright": "稳定、停顿、安全感或固着",
        "reversed": "稳定被打破、过度防守、需要松动旧框架",
        "advice": ["先守住基本盘。", "检查安全感来自事实还是习惯。", "必要时给局面一点流动空间。"],
    },
    "五": {
        "upright": "冲突、损耗、挑战与调整",
        "reversed": "冲突后修复、损耗扩大、避免继续硬扛",
        "advice": ["承认损耗并及时止血。", "别把输赢看得比问题本身更大。", "先找到可以调整的一处。"],
    },
    "六": {
        "upright": "修复、流动、互助或阶段性改善",
        "reversed": "修复迟缓、互助不对等、旧事仍在影响当下",
        "advice": ["接受可用的帮助。", "让资源和情绪重新流动。", "修复关系时要看是否对等。"],
    },
    "七": {
        "upright": "评估、防守、诱惑或策略",
        "reversed": "防守过度、策略混乱、评估失准",
        "advice": ["重新评估投入产出。", "别被太多选项分散。", "先守住关键位置。"],
    },
    "八": {
        "upright": "推进、练习、速度与专注",
        "reversed": "进度延迟、重复低效、节奏失控",
        "advice": ["保持练习和执行频率。", "减少低效重复。", "把速度和质量重新校准。"],
    },
    "九": {
        "upright": "临界点、收获前夕、独立承受",
        "reversed": "疲惫累积、难以独撑、接近结果但状态不稳",
        "advice": ["别在最后阶段过度消耗。", "该求助时求助。", "确认坚持是否仍然值得。"],
    },
    "十": {
        "upright": "完成、累积结果、负担或圆满",
        "reversed": "负担过重、收尾困难、完成感被拖延",
        "advice": ["处理收尾和交付。", "卸下不该独自承担的部分。", "把结果整理成下一阶段的基础。"],
    },
    "侍从": {
        "upright": "学习者、消息、尝试、年轻能量",
        "reversed": "经验不足、消息不稳、尝试流于表面",
        "advice": ["允许自己先学习。", "消息要核实后再行动。", "从小实验开始积累经验。"],
    },
    "骑士": {
        "upright": "推进者、行动、追逐目标",
        "reversed": "冲太快、方向偏移、行动不够成熟",
        "advice": ["行动前先确认方向。", "把冲劲放进计划里。", "避免为了追逐而追逐。"],
    },
    "王后": {
        "upright": "成熟接纳、照料、内在掌控",
        "reversed": "过度照料、内在失衡、接纳变成纵容",
        "advice": ["用成熟方式回应，而不是本能反应。", "照顾别人也要照顾自己。", "保留温柔，也保留边界。"],
    },
    "国王": {
        "upright": "外在掌控、决策、责任与领导",
        "reversed": "掌控失衡、决策僵硬、责任压力过大",
        "advice": ["承担该承担的决策。", "用清晰规则带领局面。", "别让权威感变成压迫感。"],
    },
}

POSITIONS = [
    {
        "name": "现状",
        "description": "你当前最需要看见的核心能量",
        "templates": {
            "upright": [
                "这张牌落在现状位，说明当前局面正在顺着「{meaning}」展开，关键不是重新开局，而是看清这股力量已经在哪里发生。",
                "现状位强调「{meaning}」。它更像是局势的主旋律，提醒你先承认已经存在的趋势。",
                "在现状位，这张牌表示事情的表层之下有「{meaning}」在推动，适合先观察现实证据。",
            ],
            "reversed": [
                "这张牌逆位落在现状位，说明「{meaning}」没有顺畅流动，当前更像是被卡住、拖慢或反复消耗。",
                "现状位的逆位强调「{meaning}」的反面压力，问题可能不在目标，而在状态和节奏。",
                "它提示当前局面有一层不顺：你以为在处理事件，其实也在处理「{meaning}」带来的内耗。",
            ],
        },
    },
    {
        "name": "阻碍",
        "description": "正在卡住你或让局势变复杂的因素",
        "templates": {
            "upright": [
                "落在阻碍位时，「{meaning}」不是坏事本身，而是它占据了太多注意力，导致其他条件被忽略。",
                "阻碍位把「{meaning}」变成需要管理的变量：它可能有效，但如果过量就会卡住局面。",
                "这张牌在阻碍位提醒你，真正的难点可能是如何处理「{meaning}」带来的压力或诱惑。",
            ],
            "reversed": [
                "逆位在阻碍位会放大卡点，「{meaning}」说明问题可能已经不是外部阻力，而是内部失衡。",
                "阻碍位的逆位提示：先别急着推进，当前最需要松开的结是「{meaning}」。",
                "它说明局势复杂化的原因与「{meaning}」有关，越忽视它，越容易反复。",
            ],
        },
    },
    {
        "name": "建议",
        "description": "牌面给出的行动方向",
        "templates": {
            "upright": [
                "建议位的正位很直接：围绕「{meaning}」行动。可执行的方向是：{advice}",
                "这张牌在建议位表示可以顺势使用它的能量，重点是：{advice}",
                "建议位提醒你别只理解牌义，还要把「{meaning}」落成动作：{advice}",
            ],
            "reversed": [
                "建议位的逆位不是叫你放弃，而是先修正「{meaning}」里的失衡。可执行的方向是：{advice}",
                "逆位出现在建议位，表示行动前要先降噪、纠偏。现在更适合：{advice}",
                "这张牌提醒你不要硬推「{meaning}」，先做一个更稳的调整：{advice}",
            ],
        },
    },
    {
        "name": "可能结果",
        "description": "若维持当前趋势，较可能走向的结果",
        "templates": {
            "upright": [
                "作为可能结果，它表示如果当前趋势延续，「{meaning}」会成为较明显的落点。",
                "结果位的正位显示这件事有机会走向较清晰的阶段，最终体现为「{meaning}」。",
                "这张牌在结果位说明，持续当前路线时，局面更可能积累出「{meaning}」的结果。",
            ],
            "reversed": [
                "作为可能结果的逆位，它表示若不调整，最后容易以「{meaning}」的阻滞形式出现。",
                "结果位逆位提醒你：趋势不是没有结果，而是结果可能被拖延、打折或变形为「{meaning}」。",
                "这张牌提示当前路线需要修正，否则可能把「{meaning}」里的压力带到后面。",
            ],
        },
    },
]

TONE_ADVICE = {
    "smooth": [
        "正位较多，整体更适合主动推进，但推进时仍要保留复盘空间。",
        "牌面顺势感较强，可以把想法转成行动，不必一直等待更完美的时机。",
        "当前能量偏流动，适合把已有优势用起来，并用小成果稳定信心。",
        "这组牌更支持向前走，关键是别把顺利误认为可以跳过细节。",
    ],
    "blocked": [
        "逆位较多，当前更适合先整理状态、关系或资源，再决定是否加速。",
        "牌面阻滞感较强，硬推容易增加损耗，先修正卡点会更有效。",
        "这组牌提示问题不只是外部条件，也包括节奏、期待和判断方式的失衡。",
        "现在适合把目标缩小，先解决最影响全局的一个卡点。",
    ],
    "mixed": [
        "正逆位接近，说明局势不是单纯好坏，而是机会和压力同时存在。",
        "牌面呈现拉扯感，适合边推进边校准，别一次性押上全部筹码。",
        "当前既有可用能量，也有需要修正的部分，重点是辨别哪里该动、哪里该停。",
        "这组牌不鼓励极端判断，更适合稳步试探和持续反馈。",
    ],
}

ARCANA_ADVICE = {
    "major": [
        "大阿尔卡那较多，这件事带有阶段性意义，最好从长期变化而不是短期输赢来理解。",
        "大牌占比高，说明这不是单个细节的问题，更像是一次方向、身份或模式的调整。",
        "牌面重量偏高，建议认真对待其中的转折信号，别只把它当成日常小波动。",
        "这组牌更像在提示人生阶段或核心关系的变化，处理时需要留出足够空间。",
    ],
    "minor": [
        "小阿尔卡那较多，重点偏向日常选择、执行细节和资源安排。",
        "牌面更落在具体事务层面，先把能做的步骤做好，比追问大结论更有效。",
        "这件事的关键可能不在命运转折，而在沟通、节奏、分工和持续投入。",
        "小牌占比高，说明局面可调度的部分不少，行动质量会明显影响结果。",
    ],
}

SUIT_SUMMARY_ADVICE = {
    "权杖": [
        "权杖能量突出，行动和热情是突破口，但要避免冲得太散。",
        "这次牌面偏火元素，适合主动争取、表达立场和推进项目。",
        "权杖较强时，问题往往卡在要不要动、怎么动、由谁来带头。",
        "火元素提醒你把冲劲集中起来，别让热情被杂事消耗。",
    ],
    "圣杯": [
        "圣杯能量突出，关系、感受和真实需求会影响最终走向。",
        "这次牌面偏水元素，适合先处理情绪流动，再谈具体选择。",
        "圣杯较强时，答案通常不只在事实里，也在你是否愿意诚实面对感受。",
        "水元素提醒你关注连接与边界，别让沉默制造更多误会。",
    ],
    "宝剑": [
        "宝剑能量突出，沟通、判断和信息准确度是关键。",
        "这次牌面偏风元素，适合用事实、逻辑和清晰表达来破局。",
        "宝剑较强时，要小心脑内推演过多，真正有用的是可验证的信息。",
        "风元素提醒你说清楚、想明白，但不要让锋利变成伤害。",
    ],
    "星币": [
        "星币能量突出，现实资源、成本和长期积累会决定结果质量。",
        "这次牌面偏土元素，适合从时间、金钱、身体和执行条件入手。",
        "星币较强时，别只谈愿望，先看可持续性和投入产出。",
        "土元素提醒你慢慢做实，稳定的步骤比一时冲动更可靠。",
    ],
}

OBSTACLE_TEMPLATES = {
    "upright": [
        "优先处理阻碍位的「{card}」：不要让「{meaning}」占据全部视野，先分辨它是助力还是压力。",
        "阻碍位显示「{card}」需要被管理，建议先把与「{meaning}」有关的过量部分降下来。",
        "卡点来自「{card}」时，重点不是否定它，而是避免它变成唯一判断标准。",
        "先观察「{card}」在现实里对应的人、事或习惯，它可能正在悄悄影响选择。",
    ],
    "reversed": [
        "优先处理阻碍位逆位的「{card}」：先修正「{meaning}」带来的失衡，再谈推进。",
        "逆位阻碍说明卡点已经内化，建议先承认「{meaning}」造成的消耗。",
        "这张阻碍牌不适合硬扛，先把「{meaning}」里最混乱的一项整理出来。",
        "如果一直反复，问题多半与「{card}」逆位有关：越回避，越拖慢。",
    ],
}

RESULT_TEMPLATES = {
    "upright": [
        "结果位的「{card}」偏顺，说明保持正确节奏时，事情有机会走向「{meaning}」。",
        "可能结果并非固定命令，但「{card}」显示当前路线能积累出「{meaning}」的成果。",
        "如果建议位能落实，结果位的「{card}」更容易以正向方式显现。",
        "结果位给出的方向较清楚，重点是让「{meaning}」稳定落地。",
    ],
    "reversed": [
        "结果位的「{card}」逆位提醒：如果不调整，后续容易被「{meaning}」拖住。",
        "这不是坏结局判定，而是提示结果可能延迟或打折，尤其要留意「{meaning}」。",
        "若继续沿旧节奏前进，「{card}」逆位显示压力会在后段显形。",
        "结果位逆位说明还有可修正空间，越早处理「{meaning}」，越能改变走向。",
    ],
}


def stable_pick(options: list[str], *parts: object) -> str:
    if not options:
        return ""
    key = "|".join(str(part) for part in parts)
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    index = int.from_bytes(digest[:4], "big") % len(options)
    return options[index]


def build_deck() -> list[dict[str, Any]]:
    deck: list[dict[str, Any]] = []
    for card in MAJOR_ARCANA:
        deck.append({
            "name": card["name"],
            "upright": card["upright"],
            "reversed": card["reversed"],
            "advice": list(card["advice"]),
            "kind": "大阿尔卡那",
            "arcana": "major",
            "suit": "",
            "element": "",
        })
    for suit, suit_info in SUITS.items():
        for rank, rank_info in RANKS.items():
            deck.append({
                "name": f"{suit}{rank}",
                "upright": f"{suit_info['upright']}；{rank_info['upright']}",
                "reversed": f"{suit_info['reversed']}；{rank_info['reversed']}",
                "advice": list(suit_info["advice"]) + list(rank_info["advice"]),
                "kind": f"小阿尔卡那·{suit_info['element']}元素",
                "arcana": "minor",
                "suit": suit,
                "element": suit_info["element"],
            })
    return deck


def orientation_key(reversed_card: bool) -> str:
    return "reversed" if reversed_card else "upright"


def orientation_text(reversed_card: bool) -> str:
    return "逆位" if reversed_card else "正位"


def card_meaning(card: dict[str, Any], reversed_card: bool) -> str:
    return str(card[orientation_key(reversed_card)])


def card_advice(card: dict[str, Any], reversed_card: bool, question: str, position_name: str) -> str:
    return stable_pick(list(card.get("advice") or []), question, card["name"], orientation_key(reversed_card), position_name)


def interpret_card(position: dict[str, Any], card: dict[str, Any], reversed_card: bool, question: str) -> tuple[str, str, str]:
    key = orientation_key(reversed_card)
    meaning = card_meaning(card, reversed_card)
    advice = card_advice(card, reversed_card, question, position["name"])
    template = stable_pick(position["templates"][key], question, position["name"], card["name"], key)
    position_text = template.format(meaning=meaning, advice=advice, card=card["name"])
    return meaning, position_text, advice


def reading_signature(question: str, drawn: list[dict[str, Any]], reversals: list[bool]) -> str:
    cards = ",".join(f"{card['name']}:{orientation_key(reversed)}" for card, reversed in zip(drawn, reversals))
    return f"{question}|{cards}"


def dominant_suit(drawn: list[dict[str, Any]], signature: str) -> str:
    counts = Counter(str(card.get("suit") or "") for card in drawn if card.get("suit"))
    if not counts:
        return ""
    best_count = max(counts.values())
    candidates = sorted(suit for suit, count in counts.items() if count == best_count)
    return stable_pick(candidates, signature, "dominant-suit")


def derived_summary(question: str, drawn: list[dict[str, Any]], reversals: list[bool]) -> list[str]:
    signature = reading_signature(question, drawn, reversals)
    upright_count = sum(1 for item in reversals if not item)
    reversed_count = len(reversals) - upright_count
    major_count = sum(1 for card in drawn if card["arcana"] == "major")
    suit = dominant_suit(drawn, signature)

    if upright_count > reversed_count:
        tone_key = "smooth"
    elif reversed_count > upright_count:
        tone_key = "blocked"
    else:
        tone_key = "mixed"

    arcana_key = "major" if major_count >= 2 else "minor"
    obstacle_card = drawn[1]
    obstacle_reversed = reversals[1]
    advice_card_item = drawn[2]
    advice_reversed = reversals[2]
    result_card = drawn[3]
    result_reversed = reversals[3]

    lines = [
        f"本次牌面正位 {upright_count} 张、逆位 {reversed_count} 张，大阿尔卡那 {major_count} 张。",
        f"主线判断：{stable_pick(TONE_ADVICE[tone_key], signature, 'tone')}",
        f"牌面重量：{stable_pick(ARCANA_ADVICE[arcana_key], signature, 'arcana')}",
    ]
    if suit:
        lines.append(f"元素侧重：{stable_pick(SUIT_SUMMARY_ADVICE[suit], signature, 'suit', suit)}")

    obstacle_key = orientation_key(obstacle_reversed)
    obstacle_text = stable_pick(OBSTACLE_TEMPLATES[obstacle_key], signature, "obstacle")
    lines.append("优先处理：" + obstacle_text.format(card=obstacle_card["name"], meaning=card_meaning(obstacle_card, obstacle_reversed)))

    lines.append(
        f"行动落点：建议位给出的是「{advice_card_item['name']}（{orientation_text(advice_reversed)}）」；"
        f"{card_advice(advice_card_item, advice_reversed, question, '综合建议')}"
    )

    result_key = orientation_key(result_reversed)
    result_text = stable_pick(RESULT_TEMPLATES[result_key], signature, "result")
    lines.append("结果提醒：" + result_text.format(card=result_card["name"], meaning=card_meaning(result_card, result_reversed)))
    return lines


def tarot_reading(question: str) -> str:
    question = question.strip()
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
    for index, (position, card, reversed_card) in enumerate(zip(POSITIONS, drawn, reversals), 1):
        meaning, position_interpretation, advice = interpret_card(position, card, reversed_card, question)
        lines.append(f"{index}. {position['name']}：{card['name']}（{orientation_text(reversed_card)}，{card['kind']}）")
        lines.append(f"   牌面含义：{meaning}。")
        lines.append(f"   位置解读：{position_interpretation}")
        lines.append(f"   行动提示：{advice}")

    lines.extend([
        "",
        "综合占卜：",
        *derived_summary(question, drawn, reversals),
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
