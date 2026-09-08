"""敌人目录（60 段：6000001 起）。

规则：
  - 稳定身份 = id（int，见 content.ids 编码）。
  - site_id 引用 content.sites 的 id 常量（ST.LINGMAI 等）——敌人按地点归属，不改 sites.py。
  - loot_pills 引用 content.pills 的 id 常量（P.QINGXIN 等），禁止中文名/裸数字。
  - realm_idx：境界档参照，与该地 realm_req 相称（玩家每次战斗临时面板按自身境界派生，
    敌人数值写死在这里，强度随档上涨）。
  - element：五行（战斗克制用，"克"环见 engine.battle.KE）。
  - 数值为第一版占位，可标定：hp ≈ 34+16×档、攻 ≈ 10+5.6×档、防 ≈ 1+1.5×档、速 ≈ 6+档，
    单只按特点微调，保证同档玩家（基础技能+平砍）可胜、但受创真实。
"""
from dataclasses import dataclass, field

from content import pills as P
from content import sites as ST
from content.ids import CAT_ENEMY, make_id

# ---- id 常量（改 id 只改这里；name 随便改，不动 id）----
# 灵脉山（练气初期）
LINGWEN_LANG = make_id(CAT_ENEMY, 1)    # 灵纹狼（金）
CHIYAN_HU = make_id(CAT_ENEMY, 2)       # 赤焰狐（火）
# 幽谷秘境（筑基初期）
YOUGU_TENGYAO = make_id(CAT_ENEMY, 3)   # 幽谷藤妖（木）
HANTAN_XUANGUI = make_id(CAT_ENEMY, 4)  # 寒潭玄龟（水）
# 古战场遗迹（金丹初期）
SHIJIN_GUSHI = make_id(CAT_ENEMY, 5)    # 噬金古尸（金）
YEHOU_YUANHUN = make_id(CAT_ENEMY, 6)   # 业火怨魂（火）
# 上古洞府（元婴初期）
DONGFU_SHILING = make_id(CAT_ENEMY, 7)  # 洞府石灵（土）
XUANBING_KUILEI = make_id(CAT_ENEMY, 8) # 玄冰傀儡（水）


@dataclass(frozen=True)
class Enemy:
    id: int
    name: str
    site_id: int            # 归属探索点地点 id（引用 ST 常量）
    realm_idx: int          # 境界档参照（与 site.realm_req 相称）
    element: str            # 五行（金/木/水/火/土）
    hp: int
    attack: int
    defense: int
    speed: int
    loot_stones: tuple      # (min, max) 胜后灵石
    loot_pills: dict = field(default_factory=dict)  # {丹药id: 概率}
    desc: str = ""


ENEMIES: dict[int, Enemy] = {}


def _reg(e: Enemy):
    ENEMIES[e.id] = e


_reg(Enemy(
    LINGWEN_LANG, "灵纹狼", site_id=ST.LINGMAI, realm_idx=1, element="金",
    hp=52, attack=17, defense=3, speed=8,
    loot_stones=(12, 30), loot_pills={P.QINGXIN: 0.12},
    desc="灵脉山浅层的独狼，皮坚齿利，金行煞气内敛。",
))
_reg(Enemy(
    CHIYAN_HU, "赤焰狐", site_id=ST.LINGMAI, realm_idx=2, element="火",
    hp=66, attack=22, defense=4, speed=10,
    loot_stones=(16, 40), loot_pills={P.QINGXIN: 0.15},
    desc="尾尖燃火的灵狐，迅捷狡黠，被咬一口如遭火燎。",
))
_reg(Enemy(
    YOUGU_TENGYAO, "幽谷藤妖", site_id=ST.YOUGU, realm_idx=10, element="木",
    hp=215, attack=80, defense=16, speed=14,
    loot_stones=(80, 170), loot_pills={P.QINGXIN: 0.20, P.ZHUJI: 0.10},
    desc="幽谷迷雾中成精的古藤，枝蔓缠人，木灵浓郁。",
))
_reg(Enemy(
    HANTAN_XUANGUI, "寒潭玄龟", site_id=ST.YOUGU, realm_idx=11, element="水",
    hp=250, attack=88, defense=24, speed=10,
    loot_stones=(90, 200), loot_pills={P.ZHUJI: 0.15},
    desc="寒潭深处的百年玄龟，甲坚如铁，吐息冰寒彻骨。",
))
_reg(Enemy(
    SHIJIN_GUSHI, "噬金古尸", site_id=ST.GUZHAN, realm_idx=14, element="金",
    hp=290, attack=112, defense=26, speed=13,
    loot_stones=(160, 380), loot_pills={P.JULING: 0.20, P.JIEJIN: 0.10},
    desc="古战场尸煞所化的金尸，身坚逾铁，掌风带金锐之气。",
))
_reg(Enemy(
    YEHOU_YUANHUN, "业火怨魂", site_id=ST.GUZHAN, realm_idx=15, element="火",
    hp=300, attack=116, defense=22, speed=22,
    loot_stones=(180, 420), loot_pills={P.JIEJIN: 0.14},
    desc="战殁修士怨念所凝，魂火灼人，飘忽难测。",
))
_reg(Enemy(
    DONGFU_SHILING, "洞府石灵", site_id=ST.SHANGGU, realm_idx=18, element="土",
    hp=365, attack=138, defense=34, speed=15,
    loot_stones=(420, 950), loot_pills={P.JULING: 0.20, P.NINGYING: 0.12},
    desc="上古洞府门户石兽通灵所化，撼地一击势大力沉。",
))
_reg(Enemy(
    XUANBING_KUILEI, "玄冰傀儡", site_id=ST.SHANGGU, realm_idx=19, element="水",
    hp=375, attack=144, defense=32, speed=20,
    loot_stones=(450, 1000), loot_pills={P.NINGYING: 0.15},
    desc="大能遗留的守府傀儡，通体玄冰，拳风所过霜华遍地。",
))


def by_id(eid: int) -> Enemy:
    return ENEMIES[eid]


def name_of(eid) -> str:
    if isinstance(eid, int):
        e = ENEMIES.get(eid)
        return e.name if e else str(eid)
    e = ENEMIES.get(int(eid))
    return e.name if e else str(eid)


def pool_for(site_id: int) -> list:
    """某探索点的敌人池（探索遇敌从中抽取）。"""
    return [e for e in ENEMIES.values() if e.site_id == site_id]
