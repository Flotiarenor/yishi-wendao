"""技能目录（30 段：3000001 起）。

规则：
  - 稳定身份 = id（int，见 content.ids 编码）。
  - 代码/功法 skill_ids 引用一律用本模块导出的 id 常量（如 SK.YANLIAN_ZHAN），
    禁止裸数字/中文名。
  - name 仅显示，可随意改名，不影响引用。
  - element：五行 "金"/"木"/"水"/"火"/"土"/"无"。
  - kind：attack 攻击 / defense 防御 / utility 辅助（P3.8：utility 须有 effect_key 才可入战斗池）。
  - qi_cost / power：灵气消耗与攻击基准（P2 用；非攻击技能 power=0）。
  - requirement：需求谱系 "free" 自由 / "gentle" 温和 / "strict" 严格（P3 生效）。
    free = 独立术法（无母功法依赖，恒入战斗池）；gentle = 母功法在运转池任意槽；
    strict = 母功法在主修位 或 其熟悉度达 FAM_MAX 大成。
  - unlock_fam：母功法熟悉度 ≥ 此值该技能才"亮出"（亮出 ≠ 可施放，施放还看谱系）。
  - effect_key：技能效果键（P3.8 起任何 kind 可用；模板见 content/effects.py 的 EFFECTS，
    breath/root/weaken/evade…），空串 = 无效果；utility 无效果不入战斗池。
    防御类技能不填 effect_key——战斗中由管线按 kind=="defense" 施加等价护体。
  - modifiers：修饰器键→参数（随 attack 技能结算，见 engine/effects.py MODIFIERS；
    穿透 armor_pen∈[0,1] 比例 / 固定加伤 extra_dmg 数值）。
"""
from dataclasses import dataclass, field

from content.ids import CAT_SKILL, make_id

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
YUFENG_SHU = make_id(CAT_SKILL, 13)       # 御风术（御风步法身法技，P3 改 gentle）
# 无属性 · 人人可用的 free 基础术法（P2 战斗必备：基础攻击/基础减伤）
LINGLI_CHONGJI = make_id(CAT_SKILL, 14)   # 灵力冲击（无属性基础攻击）
HUTI_LINGGUANG = make_id(CAT_SKILL, 15)   # 护体灵光（无属性基础防御）
# P3 新增：seq16 起（吐纳诀/撼岳诀/沧澜诀/踏云步 之技）
TUNA_SHU = make_id(CAT_SKILL, 16)         # 吐纳术（吐纳诀入门技，吐纳回气）
ZHUIYUE_ZHANG = make_id(CAT_SKILL, 17)    # 坠岳掌（撼岳诀·攻）
SHIFU_JIA = make_id(CAT_SKILL, 18)        # 石肤甲（撼岳诀·守）
CANGLAN_ZHANG = make_id(CAT_SKILL, 19)    # 沧澜掌（沧澜诀·攻）
BINGFU_SHU = make_id(CAT_SKILL, 20)       # 冰缚术（沧澜诀·困敌）
LINGXU_BU = make_id(CAT_SKILL, 21)        # 凌虚步（踏云步·身法闪避）


@dataclass(frozen=True)
class Skill:
    id: int
    name: str
    element: str          # 金/木/水/火/土/无
    kind: str             # attack/defense/utility
    qi_cost: int          # 灵气消耗
    power: int            # 攻击基准（非攻击技能 0）
    requirement: str      # free/gentle/strict
    desc: str = ""
    unlock_fam: int = 0        # 母功法熟悉度 ≥ 此值才亮出（P3；free 技能 0 恒亮）
    effect_key: str = ""       # 技能效果键（模板 key；utility 须非空才入战斗池，P3.8）
    modifiers: dict = field(default_factory=dict)   # 修饰器键→参数（P3.8，随攻击结算）


# ---- 技能数据 ----
_skills = [
    # 火系
    Skill(YANLIAN_ZHAN, "烈焰斩", "火", "attack", qi_cost=8, power=32,
          requirement="gentle", desc="焰随剑走，灼烧敌躯的火系入门攻伐。",
          unlock_fam=10),
    Skill(BAOYAN_SHU, "爆炎术", "火", "attack", qi_cost=12, power=46,
          requirement="gentle", desc="压缩炎气于一点轰然爆开，势大力沉。",
          unlock_fam=30),
    Skill(FENTIAN_HUOHAI, "焚天火海", "火", "attack", qi_cost=26, power=100,
          requirement="strict", desc="焚天诀终极杀招，火海焚天。",
          unlock_fam=80),
    # 木系
    Skill(QINGTENG_CHAN, "青藤缠", "木", "utility", qi_cost=6, power=0,
          requirement="gentle", desc="藤蔓自地底涌出，缠缚困敌。",
          unlock_fam=10, effect_key="root"),
    Skill(QINGMU_HUICHUN, "青木回春", "木", "defense", qi_cost=8, power=0,
          requirement="gentle", desc="引木灵温养己身，愈伤续战。",
          unlock_fam=30),
    # 水系
    Skill(XUANBING_CI, "玄冰刺", "水", "attack", qi_cost=8, power=30,
          requirement="gentle", desc="玄水凝冰成刺，透骨奇寒。",
          unlock_fam=10),
    Skill(XUANSHUI_HUSHEN, "玄水护身", "水", "defense", qi_cost=6, power=0,
          requirement="gentle", desc="水幕绕体流转，卸去攻伐之力。",
          unlock_fam=30),
    # 土系
    Skill(HOUTU_JIA, "厚土甲", "土", "defense", qi_cost=6, power=0,
          requirement="gentle", desc="土灵附体成甲，硬撼重击。",
          unlock_fam=10),
    Skill(DIXIAN_SHU, "地陷术", "土", "utility", qi_cost=5, power=0,
          requirement="gentle", desc="脚下大地塌陷，乱敌阵脚。",
          unlock_fam=30, effect_key="weaken"),
    # 金系
    Skill(RUIJIN_JIANQI, "锐金剑气", "金", "attack", qi_cost=9, power=34,
          requirement="gentle", desc="凝金气为剑气，锋锐裂石。",
          unlock_fam=10),
    Skill(JINZHONG_HUTI, "金钟护体", "金", "defense", qi_cost=7, power=0,
          requirement="gentle", desc="罡气凝钟护体，金鸣阵阵。",
          unlock_fam=30),
    Skill(QIANJIAN_JUE, "千剑诀", "金", "attack", qi_cost=20, power=80,
          requirement="strict", desc="庚金剑经杀式，千剑齐发。",
          unlock_fam=80),
    # 无属性
    Skill(YUFENG_SHU, "御风术", "无", "utility", qi_cost=3, power=0,
          requirement="gentle", desc="风随步起，身法轻灵如御风而行。",
          unlock_fam=10, effect_key="evade"),
    Skill(LINGLI_CHONGJI, "灵力冲击", "无", "attack", qi_cost=4, power=14,
          requirement="free", desc="灵力聚于指尖凝为冲击，人人可修的基础攻伐术。"),
    Skill(HUTI_LINGGUANG, "护体灵光", "无", "defense", qi_cost=4, power=0,
          requirement="free", desc="灵光罩体卸去攻伐，人人可修的基础护身术。"),
    # P3 新增：吐纳诀技（seq16）
    Skill(TUNA_SHU, "吐纳术", "无", "utility", qi_cost=2, power=0,
          requirement="gentle", desc="吐纳调息，采天地灵气补益自身。",
          unlock_fam=10, effect_key="breath"),
    # 撼岳诀（练气级战斗功法·土）两技
    Skill(ZHUIYUE_ZHANG, "坠岳掌", "土", "attack", qi_cost=7, power=28,
          requirement="gentle", desc="引地气凝于掌，如山岳倾坠般砸下。",
          unlock_fam=10),
    Skill(SHIFU_JIA, "石肤甲", "土", "defense", qi_cost=6, power=0,
          requirement="gentle", desc="土灵凝肤为甲，硬撼外击。",
          unlock_fam=30),
    # 沧澜诀（筑基级战斗功法·水）两技
    Skill(CANGLAN_ZHANG, "沧澜掌", "水", "attack", qi_cost=12, power=52,
          requirement="gentle", desc="掌出如沧澜叠浪，一浪高过一浪。",
          unlock_fam=10),
    Skill(BINGFU_SHU, "冰缚术", "水", "utility", qi_cost=8, power=0,
          requirement="gentle", desc="寒气凝冰缚敌足胫，使其动弹不得。",
          unlock_fam=30, effect_key="root"),
    # 踏云步（筑基级身法功法·无）一技
    Skill(LINGXU_BU, "凌虚步", "无", "utility", qi_cost=6, power=0,
          requirement="gentle", desc="身若凌虚，敌攻难及。",
          unlock_fam=10, effect_key="evade"),
]

# ---- 注册表：id → Skill ----
SKILLS: dict[int, Skill] = {sk.id: sk for sk in _skills}

# name → id（供 CLI 按中文名反查）
ID_BY_NAME: dict[str, int] = {sk.name: sk.id for sk in SKILLS.values()}


def by_id(skid: int) -> Skill:
    return SKILLS[skid]


def name_of(skid) -> str:
    if isinstance(skid, int):
        sk = SKILLS.get(skid)
        return sk.name if sk else str(skid)
    sk = SKILLS.get(int(skid))
    return sk.name if sk else str(skid)


def resolve(item) -> int:
    """玩家输入（整数 id 或中文名）→ id；找不到返回 None。"""
    if isinstance(item, int):
        return item if item in SKILLS else None
    if isinstance(item, str) and item.lstrip("-").isdigit():
        sid = int(item)
        return sid if sid in SKILLS else None
    return ID_BY_NAME.get(str(item))
