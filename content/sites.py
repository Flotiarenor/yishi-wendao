"""探索地点目录（10 段：坊市=1000000，探索点 1000001 起）。

规则：
  - 稳定身份 = id（int，见 content.ids 编码）。
  - pill_drops 引用丹药用 content.pills 的 id 常量（P.QINGXIN 等），禁止中文名。
  - realm_req：建议境界档（低于它硬闯 danger 翻倍、心魔+5）。
  - days_cost：单次探索耗时（天）；stone：(min,max) 灵石；danger：遇险概率。
"""
from dataclasses import dataclass, field

from content import pills as P
from content.ids import CAT_SITE, make_id

# ---- id 常量 ----
SHISHI = make_id(CAT_SITE, 0)     # 坊市（序号0，特殊：只交易不可探索）
LINGMAI = make_id(CAT_SITE, 1)    # 灵脉山
YOUGU = make_id(CAT_SITE, 2)      # 幽谷秘境
GUZHAN = make_id(CAT_SITE, 3)     # 古战场遗迹
SHANGGU = make_id(CAT_SITE, 4)    # 上古洞府


@dataclass(frozen=True)
class Site:
    id: int
    name: str
    desc: str
    realm_req: int
    days_cost: int
    stone: tuple           # (min, max)
    danger: float
    pill_drops: dict = field(default_factory=dict)  # {丹药id: 概率}


SITES: dict[int, Site] = {}


def _reg(site: Site):
    SITES[site.id] = site


_reg(Site(
    LINGMAI, "灵脉山",
    "山中灵脉隐现，可采灵石，偶有妖兽窥视。",
    realm_req=1, days_cost=20, stone=(8, 25), danger=0.08,
    pill_drops={P.QINGXIN: 0.05},
))
_reg(Site(
    YOUGU, "幽谷秘境",
    "谷中常年迷雾，灵草遍地，但深处凶险莫测。",
    realm_req=10, days_cost=40, stone=(30, 90), danger=0.18,
    pill_drops={P.QINGXIN: 0.08, P.ZHUJI: 0.05},
))
_reg(Site(
    GUZHAN, "古战场遗迹",
    "上古修士陨落之地，遗宝与杀机并存。",
    realm_req=14, days_cost=60, stone=(80, 220), danger=0.25,
    pill_drops={P.JULING: 0.10, P.JIEJIN: 0.04},
))
_reg(Site(
    SHANGGU, "上古洞府",
    "疑似化神大能坐化之所，机缘与死劫一线之隔。",
    realm_req=18, days_cost=90, stone=(700, 1600), danger=0.35,
    pill_drops={P.JULING: 0.10, P.NINGYING: 0.04},
))

# 显示名 → id（供 CLI 按中文名反查）
ID_BY_NAME: dict[str, int] = {s.name: s.id for s in SITES.values()}
ID_BY_NAME["坊市"] = SHISHI


def by_id(sid: int) -> Site:
    return SITES[sid]


def name_of(sid) -> str:
    if isinstance(sid, int):
        if sid == SHISHI:
            return "坊市"
        s = SITES.get(sid)
        return s.name if s else str(sid)
    s = SITES.get(int(sid))
    return s.name if s else str(sid)


def resolve(item) -> int:
    """玩家输入（整数 id 或中文名）→ id；找不到返回 None。"""
    if isinstance(item, int):
        return item if (item in SITES or item == SHISHI) else None
    if isinstance(item, str) and item.lstrip("-").isdigit():
        sid = int(item)
        return sid if (sid in SITES or sid == SHISHI) else None
    return ID_BY_NAME.get(str(item))
