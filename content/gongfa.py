"""功法目录（40 段：4000001 起）。

规则：
  - 稳定身份 = id（int，见 content.ids 编码）。
  - 代码引用一律用本模块导出的 id 常量（如 G.YANYANG_JUE），禁止裸数字/中文名。
  - skill_ids 引用 content.skills 的 id 常量（SK.YANLIAN_ZHAN 等），禁止中文名。
  - slot_type：main 主修 / battle 战斗槽 / shenfa 身法槽（P3 起三槽全部开放）。
  - tier：看懂门槛 = 境界档号（p.realm_idx >= gf.tier 才看得懂）；1/10/14/18/22
    对应 练气/筑基/金丹/元婴/化神 级，恒取大境界起点档。
  - cultivate_bonus：装为主修后的修炼效率加成（乘进 1+bonus，见 engine.game.cultivation_mult）。
  - permanent_bonus：道基被动——熟悉度 ≥ FAM_ENTRY（已入门）即永久生效、不占槽。
    仅《吐纳诀》一册为 permanent_bonus 功法（"余位被动"验证例），勿再新增第二本。
  - market：False = 坊市不售（如开局赠书《吐纳诀》）。
"""
from dataclasses import dataclass

from content import skills as SK
from content.ids import CAT_GONGFA, make_id

# 玩家可见的功法层级称谓（与境界层级共用语言，仅展示用）
TIER_LABELS: dict[int, str] = {
    1: "练气级", 10: "筑基级", 14: "金丹级", 18: "元婴级", 22: "化神级",
}
# 槽位类型称谓（仅展示用）
SLOT_LABELS: dict[str, str] = {
    "main": "主修", "battle": "战斗", "shenfa": "身法",
}

# ---- id 常量（改 id 只改这里；name 随便改，不动 id）----
# 练气级五大行主修（P3 起引擎开局/迁移不再按灵根赠送，仅作坊市可购主修）
YANYANG_JUE = make_id(CAT_GONGFA, 1)      # 炎阳诀（火）
XUANSHUI_ZHENJING = make_id(CAT_GONGFA, 2)  # 玄水真经（水）
QINGMU_GONG = make_id(CAT_GONGFA, 3)      # 青木功（木）
HOUTU_JUE = make_id(CAT_GONGFA, 4)        # 厚土诀（土）
RUIJIN_DIAN = make_id(CAT_GONGFA, 5)      # 锐金典（金）
# 筑基级更强主修
FENTIAN_JUE = make_id(CAT_GONGFA, 6)      # 焚天诀（火，筑基级）
# battle / shenfa（P3 槽位开放）
GENJIN_SHAJIAN = make_id(CAT_GONGFA, 7)   # 庚金杀剑（战斗类·金丹级）
YUFENG_BUFA = make_id(CAT_GONGFA, 8)      # 御风步法（身法类·练气级）
# P3 新增：seq9~12（吐纳诀 + 战斗/身法升级功法）
TUNA_JUE = make_id(CAT_GONGFA, 9)         # 吐纳诀（主修类·练气级·基础吐纳，永久被动）
HANYUE_JUE = make_id(CAT_GONGFA, 10)      # 撼岳诀（战斗类·练气级·土）
CANGLAN_JUE = make_id(CAT_GONGFA, 11)     # 沧澜诀（战斗类·筑基级·水）
TAYUN_BU = make_id(CAT_GONGFA, 12)        # 踏云步（身法类·筑基级·无）

# 五行 → 练气级主修功法映射。
# P3 起引擎开局/旧档迁移不再调用（开局只赠吐纳诀）；P6 转世开局或可复用，故保留勿删。
FOUNDATION_BY_ELEMENT: dict[str, int] = {
    "火": YANYANG_JUE,
    "水": XUANSHUI_ZHENJING,
    "木": QINGMU_GONG,
    "土": HOUTU_JUE,
    "金": RUIJIN_DIAN,
}


@dataclass(frozen=True)
class Gongfa:
    id: int
    name: str
    slot_type: str        # main / battle / shenfa
    element: str          # 主五行倾向
    tier: int             # 看懂门槛 = 境界档号（1/10/14/18/22）
    price: int            # 坊市售价（灵石；market=False 时仅存档字段）
    cultivate_bonus: float  # 主修修炼效率加成（乘进 1+bonus）
    skill_ids: list       # 自带技能（0~4 个，content.skills 的 id 常量）
    desc: str = ""
    permanent_bonus: float = 0.0  # 道基被动（习得即永久修炼效率加成，不占槽；P3）
    market: bool = True          # False = 坊市不售（P3）


# ---- 功法数据 ----
_gongfa = [
    Gongfa(YANYANG_JUE, "炎阳诀", "main", "火", tier=1, price=200,
           cultivate_bonus=0.30, skill_ids=[SK.YANLIAN_ZHAN],
           desc="火系练气入门主修，引烈日炎阳之气淬体焚敌。"),
    Gongfa(XUANSHUI_ZHENJING, "玄水真经", "main", "水", tier=1, price=260,
           cultivate_bonus=0.35, skill_ids=[SK.XUANBING_CI, SK.XUANSHUI_HUSHEN],
           desc="水系练气入门主修，纳百川寒流为己用，绵长不绝。"),
    Gongfa(QINGMU_GONG, "青木功", "main", "木", tier=1, price=180,
           cultivate_bonus=0.25, skill_ids=[SK.QINGTENG_CHAN, SK.QINGMU_HUICHUN],
           desc="木系练气入门主修，生机生生不息，滋养道基。"),
    Gongfa(HOUTU_JUE, "厚土诀", "main", "土", tier=1, price=220,
           cultivate_bonus=0.30, skill_ids=[SK.HOUTU_JIA, SK.DIXIAN_SHU],
           desc="土系练气入门主修，厚德载物，根基稳固。"),
    Gongfa(RUIJIN_DIAN, "锐金典", "main", "金", tier=1, price=300,
           cultivate_bonus=0.35, skill_ids=[SK.RUIJIN_JIANQI, SK.JINZHONG_HUTI],
           desc="金系练气入门主修，金行肃杀锋锐，修炼增益颇丰。"),
    Gongfa(FENTIAN_JUE, "焚天诀", "main", "火", tier=10, price=1500,
           cultivate_bonus=0.80,
           skill_ids=[SK.YANLIAN_ZHAN, SK.BAOYAN_SHU, SK.FENTIAN_HUOHAI],
           desc="筑基级火系主修大法，炎势滔天，三式火法尽在其中。"),
    Gongfa(GENJIN_SHAJIAN, "庚金杀剑", "battle", "金", tier=14, price=1000,
           cultivate_bonus=0.0, skill_ids=[SK.RUIJIN_JIANQI, SK.QIANJIAN_JUE],
           desc="金丹级战斗类剑经，杀伐凌厉，装战斗槽后其剑气随行随放。"),
    Gongfa(YUFENG_BUFA, "御风步法", "shenfa", "无", tier=1, price=150,
           cultivate_bonus=0.0, skill_ids=[SK.YUFENG_SHU],
           desc="练气身法，步若御风，装身法槽后于战斗中腾挪闪避。"),
    # P3 新增
    Gongfa(TUNA_JUE, "吐纳诀", "main", "无", tier=1, price=0,
           cultivate_bonus=0.0, skill_ids=[SK.TUNA_SHU], market=False,
           permanent_bonus=0.05,
           desc="基础吐纳导引之术，人人可修；参悟入门后道基受用终身（修炼效率永久 +5%）。"),
    Gongfa(HANYUE_JUE, "撼岳诀", "battle", "土", tier=1, price=250,
           cultivate_bonus=0.0, skill_ids=[SK.ZHUIYUE_ZHANG, SK.SHIFU_JIA],
           desc="练气级战斗功法，引岳之势攻守兼备，装战斗槽即可临阵施展。"),
    Gongfa(CANGLAN_JUE, "沧澜诀", "battle", "水", tier=10, price=800,
           cultivate_bonus=0.0, skill_ids=[SK.CANGLAN_ZHANG, SK.BINGFU_SHU],
           desc="筑基级战斗功法，沧澜叠浪绵密无尽，冰缚困敌出其不意。"),
    Gongfa(TAYUN_BU, "踏云步", "shenfa", "无", tier=10, price=600,
           cultivate_bonus=0.0, skill_ids=[SK.LINGXU_BU],
           desc="筑基级身法，足踏云气，凌虚而遁，敌攻难及。"),
]

# ---- 注册表：id → Gongfa ----
GONGFA: dict[int, Gongfa] = {gf.id: gf for gf in _gongfa}

# name → id（供 CLI 按中文名反查）
ID_BY_NAME: dict[str, int] = {gf.name: gf.id for gf in GONGFA.values()}


def by_id(gid: int) -> Gongfa:
    return GONGFA[gid]


def name_of(gid) -> str:
    if isinstance(gid, int):
        gf = GONGFA.get(gid)
        return gf.name if gf else str(gid)
    gf = GONGFA.get(int(gid))
    return gf.name if gf else str(gid)


def resolve(item) -> int:
    """玩家输入（整数 id 或中文名）→ id；找不到返回 None。"""
    if isinstance(item, int):
        return item if item in GONGFA else None
    if isinstance(item, str) and item.lstrip("-").isdigit():
        gid = int(item)
        return gid if gid in GONGFA else None
    return ID_BY_NAME.get(str(item))


def mother_gongfas(skill_id: int) -> list:
    """反向引用：返回 skill_ids 含该技能的全部功法 id 列表。

    供需求谱系判定（一技能被多本功法引用时，任一母功法满足即视为满足）
    与战斗熟悉度成长结算使用。
    """
    return [gf.id for gf in GONGFA.values() if skill_id in gf.skill_ids]
