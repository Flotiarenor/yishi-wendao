"""技能目录（30 段：3000001 起）—— **动作数据（Action）**。

R3 起技能就是 `engine.action.Action`（不再有独立的 Skill 类）：
前后摇、灵气效率、时长权重、组件、条件全部是数据，新增技能只改本文件。

字段约定：
  id         : 稳定整数 id（30 段）；功法 skill_ids 引用它
  key        : 稳定字符串键（动作池引用键）；`sk<id>` 规则生成，禁止手写中文
  element    : 五行 金/木/水/火/土/无
  kind       : attack 攻击 / defense 防御 / utility 辅助
  qi_cost    : 灵气消耗（标定后尺度：1/息 回灵，故高耗技能需聚气/灵石加速）
  timing     : 前摇/后摇（厘息）+ 速度敏感度
  components : Damage / ApplyStatus / QiGain …
  requirement: 需求谱系 free 自由 / gentle 温和 / strict 严格（P3 生效）
    free   = 独立术法（无母功法依赖，恒入战斗池）
    gentle = 母功法在运转池任意槽
    strict = 母功法在主修位 或 其熟悉度达 FAM_MAX 大成
  unlock_fam : 母功法熟悉度 ≥ 此值该技能才"亮出"（亮出 ≠ 可施放，施放还看谱系）
  tier       : 品阶（基础威力系数）
"""
from dataclasses import dataclass, field

from content.ids import CAT_SKILL, make_id
from engine.action import Action, ApplyStatus, Damage, QiGain, Timing

# ---- id 常量（改 id 只改这里；name 随便改，不动 id）----
# 火系
YANLIAN_ZHAN = make_id(CAT_SKILL, 1)      # 烈焰斩（炎阳诀入门火法）
BAOYAN_SHU = make_id(CAT_SKILL, 2)        # 爆炎术（焚天诀中坚火法）
FENTIAN_HUOHAI = make_id(CAT_SKILL, 3)    # 焚天火海（焚天诀终式）
# 木系
QINGTENG_CHAN = make_id(CAT_SKILL, 4)     # 青藤缠（困敌辅助）
QINGMU_HUICHUN = make_id(CAT_SKILL, 5)    # 青木回春（愈伤续战）
# 水系
XUANBING_CI = make_id(CAT_SKILL, 6)       # 玄冰刺（寒冰攻伐）
XUANSHUI_HUSHEN = make_id(CAT_SKILL, 7)   # 玄水护身（水幕防御）
# 土系
HOUTU_JIA = make_id(CAT_SKILL, 8)         # 厚土甲（土灵附体防御）
DIXIAN_SHU = make_id(CAT_SKILL, 9)        # 地陷术（地形扰敌辅助）
# 金系
RUIJIN_JIANQI = make_id(CAT_SKILL, 10)    # 锐金剑气（金系攻伐）
JINZHONG_HUTI = make_id(CAT_SKILL, 11)    # 金钟护体（罡气防御）
QIANJIAN_JUE = make_id(CAT_SKILL, 12)     # 千剑诀（庚金剑经杀式）
# 无属性
YUFENG_SHU = make_id(CAT_SKILL, 13)       # 御风术（御风步法身法技）
LINGLI_CHONGJI = make_id(CAT_SKILL, 14)   # 灵力冲击（无属性基础攻击）
HUTI_LINGGUANG = make_id(CAT_SKILL, 15)   # 护体灵光（无属性基础防御）
TUNA_SHU = make_id(CAT_SKILL, 16)         # 吐纳术（吐纳诀入门技，吐纳回气）
ZHUIYUE_ZHANG = make_id(CAT_SKILL, 17)    # 坠岳掌（撼岳诀·攻）
SHIFU_JIA = make_id(CAT_SKILL, 18)        # 石肤甲（撼岳诀·守）
CANGLAN_ZHANG = make_id(CAT_SKILL, 19)    # 沧澜掌（沧澜诀·攻）
BINGFU_SHU = make_id(CAT_SKILL, 20)       # 冰缚术（沧澜诀·困敌）
LINGXU_BU = make_id(CAT_SKILL, 21)        # 凌虚步（踏云步·身法闪避）


def skey(sid: int) -> str:
    """技能 id → 动作键（稳定、无中文）。"""
    return f"sk{sid}"


@dataclass(frozen=True)
class SkillSpec:
    """技能 = Action + 功法谱系字段（requirement / unlock_fam）。"""
    action: Action
    requirement: str = "free"
    unlock_fam: int = 0

    # 便捷透传（内容层与 game 层大量使用）
    @property
    def id(self) -> int:
        return self.action.id

    @property
    def key(self) -> str:
        return self.action.key

    @property
    def name(self) -> str:
        return self.action.name

    @property
    def element(self) -> str:
        """展示用五行：取**首个带 element 的组件**（Damage 优先），全无则「无」。

        注意：不能假设 components[0] 是 Damage —— 纯防御/辅助技能的首个组件是
        ApplyStatus / QiGain，它们没有 element 属性（P3.7 修复：此前会让
        `gongfa_detail` 对 12 本功法中的 7 本抛 AttributeError → HTTP 500）。
        """
        for c in self.action.components:
            el = getattr(c, "element", None)
            if el:
                return el
        return "无"

    @property
    def kind(self) -> str:
        return self.action.kind

    @property
    def qi_cost(self) -> int:
        return self.action.qi_cost

    @property
    def power(self) -> float:
        for c in self.action.components:
            if isinstance(c, Damage):
                return c.power
        return 0.0

    @property
    def effect_key(self) -> str:
        for c in self.action.components:
            if isinstance(c, ApplyStatus):
                return c.key
        return ""


def _sk(sid, name, element, kind, qi_cost, power, requirement, desc,
        unlock_fam=0, windup=50, recovery=300, tier=1, qi_eff=0.0,
        dur_w=0.0, extra=(), conditions=(), attack_ratio=0.3) -> SkillSpec:
    """构造一条技能数据（统一默认值，避免每条都写全字段）。"""
    comps = []
    if kind in ("attack",) or power > 0:
        comps.append(Damage(power=power, attack_ratio=attack_ratio, element=element))
    comps.extend(extra)
    act = Action(key=skey(sid), name=name, kind=kind, qi_cost=qi_cost,
                 timing=Timing(windup=windup, recovery=recovery),
                 components=tuple(comps), conditions=tuple(conditions),
                 qi_efficiency=qi_eff, duration_weight=dur_w, tier=tier,
                 desc=desc, id=sid)
    return SkillSpec(action=act, requirement=requirement, unlock_fam=unlock_fam)


# ---- 技能数据 ----
_skills = [
    # 火系
    _sk(YANLIAN_ZHAN, "烈焰斩", "火", "attack", 8, 32, "gentle",
        "焰随剑走，灼烧敌躯的火系入门攻伐。", unlock_fam=10, recovery=300, tier=2),
    _sk(BAOYAN_SHU, "爆炎术", "火", "attack", 12, 46, "gentle",
        "压缩炎气于一点轰然爆开，势大力沉。", unlock_fam=30, recovery=400, tier=2),
    _sk(FENTIAN_HUOHAI, "焚天火海", "火", "attack", 30, 100, "strict",
        "焚天诀终极杀招，火海焚天。", unlock_fam=80, windup=150, recovery=600, tier=4),
    # 木系
    _sk(QINGTENG_CHAN, "青藤缠", "木", "utility", 6, 0, "gentle",
        "藤蔓自地底涌出，缠缚困敌。", unlock_fam=10, recovery=200,
        extra=(ApplyStatus(key="root", duration_li=300, tags=("control",)),)),
    _sk(QINGMU_HUICHUN, "青木回春", "木", "defense", 8, 0, "gentle",
        "引木灵温养己身，愈伤续战。", unlock_fam=30, recovery=300,
        extra=(ApplyStatus(key="guard", duration_li=400, tags=("buff",),
                           params={"mult": 0.5}),)),
    # 水系
    _sk(XUANBING_CI, "玄冰刺", "水", "attack", 4, 38, "gentle",
        "玄水凝冰成刺，透骨奇寒。", unlock_fam=10, recovery=250, tier=2),
    _sk(XUANSHUI_HUSHEN, "玄水护身", "水", "defense", 6, 0, "gentle",
        "水幕绕体流转，卸去攻伐之力。", unlock_fam=30, recovery=250,
        extra=(ApplyStatus(key="guard", duration_li=400, tags=("buff",),
                           params={"mult": 0.5}),)),
    # 土系
    _sk(HOUTU_JIA, "厚土甲", "土", "defense", 6, 0, "gentle",
        "土灵附体成甲，硬撼重击。", unlock_fam=10, recovery=250,
        extra=(ApplyStatus(key="guard", duration_li=400, tags=("buff",),
                           params={"mult": 0.5}),)),
    _sk(DIXIAN_SHU, "地陷术", "土", "utility", 5, 0, "gentle",
        "脚下大地塌陷，乱敌阵脚。", unlock_fam=30, recovery=200,
        extra=(ApplyStatus(key="weaken", duration_li=500, tags=("debuff",),
                           params={"mult": 0.7}),)),
    # 金系
    _sk(RUIJIN_JIANQI, "锐金剑气", "金", "attack", 4, 40, "gentle",
        "凝金气为剑气，锋锐裂石。", unlock_fam=10, recovery=200, tier=2),
    _sk(JINZHONG_HUTI, "金钟护体", "金", "defense", 7, 0, "gentle",
        "罡气凝钟护体，金鸣阵阵。", unlock_fam=30, recovery=250,
        extra=(ApplyStatus(key="guard", duration_li=400, tags=("buff",),
                           params={"mult": 0.5}),)),
    _sk(QIANJIAN_JUE, "千剑诀", "金", "attack", 40, 60, "strict",
        "庚金剑经杀式，千剑齐发。", unlock_fam=80, windup=100, recovery=400,
        tier=3, qi_eff=0.06, attack_ratio=0.4),
    # 无属性
    _sk(YUFENG_SHU, "御风术", "无", "utility", 3, 0, "gentle",
        "风随步起，身法轻灵如御风而行。", unlock_fam=10, recovery=200,
        extra=(ApplyStatus(key="evade", duration_li=400, tags=("buff",),
                           params={"chance": 0.5}),)),
    _sk(LINGLI_CHONGJI, "灵力冲击", "无", "attack", 4, 14, "free",
        "灵力聚于指尖凝为冲击，人人可修的基础攻伐术。", recovery=200),
    _sk(HUTI_LINGGUANG, "护体灵光", "无", "defense", 4, 0, "free",
        "灵光罩体卸去攻伐，人人可修的基础护身术。", recovery=200,
        extra=(ApplyStatus(key="guard", duration_li=300, tags=("buff",),
                           params={"mult": 0.5}),)),
    # 吐纳诀
    _sk(TUNA_SHU, "吐纳术", "无", "utility", 2, 0, "gentle",
        "吐纳调息，采天地灵气补益自身。", unlock_fam=10, recovery=300,
        extra=(QiGain(rate_mult=3.0),)),
    # 撼岳诀（练气级战斗功法·土）
    _sk(ZHUIYUE_ZHANG, "坠岳掌", "土", "attack", 7, 28, "gentle",
        "引地气凝于掌，如山岳倾坠般砸下。", unlock_fam=10, recovery=300, tier=2),
    _sk(SHIFU_JIA, "石肤甲", "土", "defense", 6, 0, "gentle",
        "土灵凝肤为甲，硬撼外击。", unlock_fam=30, recovery=250,
        extra=(ApplyStatus(key="guard", duration_li=400, tags=("buff",),
                           params={"mult": 0.5}),)),
    # 沧澜诀（筑基级战斗功法·水）
    _sk(CANGLAN_ZHANG, "沧澜掌", "水", "attack", 12, 52, "gentle",
        "掌出如沧澜叠浪，一浪高过一浪。", unlock_fam=10, recovery=350, tier=3),
    _sk(BINGFU_SHU, "冰缚术", "水", "utility", 8, 0, "gentle",
        "寒气凝冰缚敌足胫，使其动弹不得。", unlock_fam=30, recovery=250,
        extra=(ApplyStatus(key="root", duration_li=400, tags=("control",)),)),
    # 踏云步（筑基级身法功法·无）
    _sk(LINGXU_BU, "凌虚步", "无", "utility", 6, 0, "gentle",
        "身若凌虚，敌攻难及。", unlock_fam=10, recovery=200,
        extra=(ApplyStatus(key="evade", duration_li=500, tags=("buff",),
                           params={"chance": 0.5}),)),
]

# ---- 注册表 ----
SKILLS: dict[int, SkillSpec] = {s.id: s for s in _skills}
BY_KEY: dict[str, SkillSpec] = {s.key: s for s in SKILLS.values()}
ID_BY_NAME: dict[str, int] = {s.name: s.id for s in SKILLS.values()}


def by_id(sid: int) -> SkillSpec:
    return SKILLS[sid]


def by_key(key: str):
    return BY_KEY.get(key)


def name_of(sid) -> str:
    if isinstance(sid, int):
        s = SKILLS.get(sid)
        return s.name if s else str(sid)
    s = SKILLS.get(int(sid))
    return s.name if s else str(sid)


def resolve(item) -> int:
    """玩家输入（整数 id 或中文名）→ id；找不到返回 None。"""
    if isinstance(item, int):
        return item if item in SKILLS else None
    if isinstance(item, str) and item.lstrip("-").isdigit():
        sid = int(item)
        return sid if sid in SKILLS else None
    return ID_BY_NAME.get(str(item))


def action_of(sid: int):
    """技能 id → Action（战斗层用）。"""
    s = SKILLS.get(sid)
    return s.action if s else None
