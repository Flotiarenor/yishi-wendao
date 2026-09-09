"""世界地图静态数据层：地形表 / 25 域 / 五行浓度换算 / 命名与旧地点锚点（P4-T2）。

设计依据：`docs/地图与场所定案.md` §3 空间模型（3.1 尺度 / 3.3 地形表 / 3.4 生成）、
§7 存档模型（老档迁移锚点）。本文件**只有数据与纯换算**：零 I/O、零随机、零副作用。

内容：
  - `Terrain` + `TERRAINS`：12 种主地形 + 4 类硬阻挡 + 湖泊/河流 + 渡口（id 与速度逐位照定案 §3.3）；
  - `Domain` + `DOMAINS`：25 域（5×5），每域 4000 里见方，含五行加成与噪声场偏移；
  - `element_concentration`：地形主五行 + 域级加成 → 归一化（定案「地形主属性映射 + 区域叠加」）；
  - `LEGACY_ANCHORS`：`content/sites.py` 的 5 个旧地点名 → 核心域固定坐标（旧档可继续玩）；
  - 命名表与内容点种类表（`TOWN_PREFIXES` / `CONTENT_KINDS` …）。
"""
from dataclasses import dataclass

from engine import settings as S

# ============ 一、地形（定案 §3.3） ============
# id 段：1~4 = 硬阻挡；11~24 = 可通行地形 / 条件水域。
T_DEEPSEA = 1    # 深海：硬阻挡（飞行可越）
T_CLIFF = 2      # 绝壁：硬阻挡
T_WARD = 3       # 禁制：硬阻挡（飞行也挡）
T_VOID = 4       # 虚空：世界边界环
T_ROAD = 11      # 官道：驿站 / 盘查（暴露高）
T_TRAIL = 12     # 小径：路况未知
T_PLAIN = 13     # 平原：越野基线
T_GRASS = 14     # 草原
T_FOREST = 15    # 林地：遮蔽视野、利于甩脱
T_HILL = 16      # 丘陵
T_DESERT = 17    # 沙漠：缺水
T_MOUNTAIN = 18  # 山地：需轻身术
T_CANYON = 19    # 峡谷：通道型、易设伏
T_SWAMP = 20     # 沼泽：泥泞
T_SNOW = 21      # 雪原：天候恶劣
T_LAVA = 22      # 火山熔岩：高温
T_WATER = 23     # 湖泊 / 河流：swim_only（筑基起可渡）
T_FORD = 24      # 渡口 / 桥：路网跨水时生成


@dataclass(frozen=True)
class Terrain:
    """一种地形的静态属性（速度单位：里/日；0 = 硬阻挡）。"""
    id: int
    name: str
    speed: float
    elements: tuple          # 主五行（1~2 个）
    passable: bool           # 练气期（realm_idx < SWIM_MIN_REALM）是否可通行
    swim_only: bool = False  # 需筑基渡水（湖泊 / 河流）
    flags: frozenset = frozenset()  # road/trail/water/forest/mountain/desert/settlement/block
    danger: float = 0.0      # 遇险权重（T3 用；本阶段只存不用）
    exposure: float = 0.0    # 暴露权重（T3 用；本阶段只存不用）


TERRAINS: dict[int, Terrain] = {}


def _reg(t: Terrain) -> None:
    TERRAINS[t.id] = t


# ---- 硬阻挡（速度 0）----
_reg(Terrain(T_DEEPSEA, "深海", 0.0, ("水",), False,
             flags=frozenset({"water", "block"})))
_reg(Terrain(T_CLIFF, "绝壁", 0.0, ("土", "金"), False,
             flags=frozenset({"mountain", "block"})))
_reg(Terrain(T_WARD, "禁制", 0.0, (), False,
             flags=frozenset({"block"})))
_reg(Terrain(T_VOID, "虚空", 0.0, (), False,
             flags=frozenset({"block"})))
# ---- 可通行地形 ----
_reg(Terrain(T_ROAD, "官道", 44.0, (), True,
             flags=frozenset({"road", "settlement"}), exposure=1.0))
_reg(Terrain(T_TRAIL, "小径", 33.0, (), True,
             flags=frozenset({"trail"}), exposure=0.4))
_reg(Terrain(T_PLAIN, "平原", 22.0, ("土",), True))
_reg(Terrain(T_GRASS, "草原", 22.0, ("木",), True))
_reg(Terrain(T_FOREST, "林地", 17.0, ("木",), True,
             flags=frozenset({"forest"}), danger=0.3, exposure=0.2))
_reg(Terrain(T_HILL, "丘陵", 14.0, ("土",), True))
_reg(Terrain(T_DESERT, "沙漠", 11.0, ("火",), True,
             flags=frozenset({"desert"}), danger=0.4, exposure=0.3))
_reg(Terrain(T_MOUNTAIN, "山地", 8.0, ("土", "金"), True,
             flags=frozenset({"mountain"}), danger=0.5))
_reg(Terrain(T_CANYON, "峡谷", 7.0, ("土", "金"), True,
             flags=frozenset({"mountain"}), danger=0.8, exposure=0.2))
_reg(Terrain(T_SWAMP, "沼泽", 6.0, ("水",), True,
             flags=frozenset({"water"}), danger=0.6))
_reg(Terrain(T_SNOW, "雪原", 6.0, ("水", "金"), True,
             danger=0.5))
_reg(Terrain(T_LAVA, "火山熔岩", 4.0, ("火",), True,
             danger=0.9, exposure=0.5))
# ---- 条件水域 ----
_reg(Terrain(T_WATER, "湖泊/河流", 4.0, ("水",), False, swim_only=True,
             flags=frozenset({"water"})))
_reg(Terrain(T_FORD, "渡口/桥", 10.0, ("水",), True,
             flags=frozenset({"water"}), danger=0.2, exposure=0.3))

# 12 种主地形 + 渡口（不含湖泊/河流与 4 类硬阻挡）
PASSABLE_IDS: frozenset = frozenset({
    T_ROAD, T_TRAIL, T_PLAIN, T_GRASS, T_FOREST, T_HILL,
    T_DESERT, T_MOUNTAIN, T_CANYON, T_SWAMP, T_SNOW, T_LAVA, T_FORD,
})
# 4 类硬阻挡
HARD_BLOCK_IDS: frozenset = frozenset({T_DEEPSEA, T_CLIFF, T_WARD, T_VOID})
# 12 种主地形（判据用：不含路 / 渡口 / 水域 / 硬阻挡）
MAIN_TERRAIN_IDS: tuple = (T_PLAIN, T_GRASS, T_FOREST, T_HILL, T_DESERT,
                           T_MOUNTAIN, T_CANYON, T_SWAMP, T_SNOW, T_LAVA,
                           T_ROAD, T_TRAIL)


def terrain_by_id(tid: int) -> Terrain:
    """按 id 取地形定义；未知 id 抛 KeyError（数据错误应尽早暴露）。"""
    return TERRAINS[int(tid)]


def terrain_speed(tid: int) -> float:
    """地形越野速度（里/日）；硬阻挡与湖泊/河流的原始值分别为 0 / 4。"""
    return TERRAINS[int(tid)].speed


def terrain_elements(tid: int) -> tuple:
    """地形主五行（1~2 个），如山地 → ("土", "金")。"""
    return TERRAINS[int(tid)].elements


# ============ 二、五行（与 settings.ELEMENTS 同序，直接引用不复制） ============
ELEMENTS = tuple(S.ELEMENTS)   # ("金", "木", "水", "火", "土")


# ============ 三、25 域（5×5，每域 4000 里） ============
@dataclass(frozen=True)
class Domain:
    """一个域：位置、古风名、内容密度档、五行加成、噪声场偏移。"""
    idx: int                 # 0..24 = iy*5 + ix
    ix: int
    iy: int
    name: str                # 古风域名，全局唯一
    tier: str                # "core" / "near" / "outer"
    element_bias: dict       # {"土": 0.30, "木": 0.20} —— 域级五行加成（0~0.6）
    field_bias: dict         # {"elev": +0.02, ...} —— 噪声场偏移（-0.15~+0.15）


CORE_DOMAIN_IDX = 12          # ix=2, iy=2（世界正中）
CORE_DOMAIN_NAME = "青石域"
CORE_DOMAIN_CENTER = (10000.0, 10000.0)

# 25 条手写域数据：南（iy=0）→ 北（iy=4），每行自西向东。
_DOMAIN_ROWS = (
    # iy = 0（南）
    ("赤沙域", "outer", {"火": 0.35, "土": 0.25}, {"moist": -0.10, "temp": 0.06}),
    ("丹霞域", "outer", {"火": 0.30, "土": 0.20}, {"temp": 0.05, "elev": 0.03}),
    ("苍梧域", "outer", {"木": 0.35, "水": 0.15}, {"moist": 0.08}),
    ("落霞域", "outer", {"火": 0.25, "金": 0.25}, {"temp": 0.04}),
    ("玄水域", "outer", {"水": 0.40, "木": 0.10}, {"moist": 0.10, "temp": -0.04}),
    # iy = 1
    ("黑砂域", "outer", {"土": 0.35, "火": 0.15}, {"moist": -0.08}),
    ("赤炎域", "outer", {"火": 0.45, "土": 0.10}, {"fire": 0.12, "temp": 0.08}),
    ("白水域", "near", {"水": 0.35, "木": 0.15}, {"moist": 0.10}),
    ("青岚域", "outer", {"木": 0.30, "水": 0.20}, {"moist": 0.06}),
    ("沧溟域", "outer", {"水": 0.45, "金": 0.10}, {"moist": 0.12, "elev": -0.05}),
    # iy = 2（世界腰部）
    ("黄沙域", "outer", {"土": 0.40, "火": 0.10}, {"moist": -0.10}),
    ("云梦域", "near", {"水": 0.30, "木": 0.25}, {"moist": 0.08}),
    ("青石域", "core", {"土": 0.30, "木": 0.20}, {"elev": 0.02}),
    ("赤壁域", "near", {"土": 0.25, "金": 0.30}, {"elev": 0.06}),
    ("东海域", "outer", {"水": 0.40, "金": 0.10}, {"moist": 0.12, "elev": -0.06}),
    # iy = 3
    ("落雁域", "outer", {"金": 0.35, "土": 0.15}, {"elev": 0.05}),
    ("碧波域", "outer", {"水": 0.30, "木": 0.20}, {"moist": 0.09}),
    ("金乌域", "near", {"火": 0.40, "金": 0.15}, {"fire": 0.10, "temp": 0.06}),
    ("幽篁域", "outer", {"木": 0.40, "水": 0.10}, {"moist": 0.07}),
    ("玄冰域", "outer", {"水": 0.30, "金": 0.25}, {"temp": -0.12}),
    # iy = 4（北）
    ("雪岭域", "outer", {"水": 0.25, "金": 0.30}, {"temp": -0.12, "elev": 0.08}),
    ("寒松域", "outer", {"木": 0.30, "水": 0.20}, {"temp": -0.08, "moist": 0.05}),
    ("玄天域", "outer", {"金": 0.40, "土": 0.10}, {"elev": 0.07, "temp": -0.05}),
    ("白霜域", "outer", {"水": 0.30, "金": 0.20}, {"temp": -0.10, "moist": 0.05}),
    ("极北域", "outer", {"水": 0.30, "金": 0.30}, {"temp": -0.14, "elev": 0.06}),
)

DOMAINS: tuple = tuple(
    Domain(idx=i, ix=i % S.DOMAIN_GRID, iy=i // S.DOMAIN_GRID,
           name=row[0], tier=row[1], element_bias=dict(row[2]), field_bias=dict(row[3]))
    for i, row in enumerate(_DOMAIN_ROWS)
)


def domain_by_idx(idx: int) -> Domain:
    """按域下标取域；越界抛 IndexError（调用方应先 clamp）。"""
    return DOMAINS[int(idx)]


def domain_of_cell(cx: int, cy: int) -> int:
    """栅格坐标 → 域下标（越界 clamp 到边界域，不抛异常）。"""
    ix = int(cx) // (S.WORLD_CELLS // S.DOMAIN_GRID)
    iy = int(cy) // (S.WORLD_CELLS // S.DOMAIN_GRID)
    if ix < 0:
        ix = 0
    elif ix > S.DOMAIN_GRID - 1:
        ix = S.DOMAIN_GRID - 1
    if iy < 0:
        iy = 0
    elif iy > S.DOMAIN_GRID - 1:
        iy = S.DOMAIN_GRID - 1
    return iy * S.DOMAIN_GRID + ix


def domain_at_xy(x: float, y: float) -> int:
    """连续坐标（里）→ 域下标（越界 clamp）。"""
    ix = int(x // S.DOMAIN_LI)
    iy = int(y // S.DOMAIN_LI)
    if ix < 0:
        ix = 0
    elif ix > S.DOMAIN_GRID - 1:
        ix = S.DOMAIN_GRID - 1
    if iy < 0:
        iy = 0
    elif iy > S.DOMAIN_GRID - 1:
        iy = S.DOMAIN_GRID - 1
    return iy * S.DOMAIN_GRID + ix


def neighbors_of(idx: int) -> tuple:
    """四邻域下标（角 2 个 / 边 3 个 / 内部 4 个），按 (西, 东, 南, 北) 固定顺序。"""
    d = DOMAINS[int(idx)]
    out = []
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        nx, ny = d.ix + dx, d.iy + dy
        if 0 <= nx < S.DOMAIN_GRID and 0 <= ny < S.DOMAIN_GRID:
            out.append(ny * S.DOMAIN_GRID + nx)
    return tuple(out)


# ============ 四、五行浓度（纯换算，定案「地形主属性 + 区域叠加」） ============
def element_concentration(tid: int, domain: Domain) -> dict:
    """某地形在某域下的五行浓度：地形主五行 +1，叠加域加成后归一化到和 = 1。

    全零时退化为五行各 0.2。返回的 dict 恒含 ELEMENTS 五项（顺序即 ELEMENTS 顺序）。
    """
    conc = {e: 0.0 for e in ELEMENTS}
    for e in terrain_elements(tid):
        if e in conc:
            conc[e] += 1.0
    for e, v in domain.element_bias.items():
        if e in conc:
            conc[e] += float(v)
    total = 0.0
    for e in ELEMENTS:
        v = conc[e]
        if v < 0.0:
            v = 0.0
            conc[e] = 0.0
        total += v
    if total <= 0.0:
        return {e: 0.2 for e in ELEMENTS}
    for e in ELEMENTS:
        conc[e] = conc[e] / total
    return conc


# ============ 五、命名表与旧地点锚点 ============
# 5 个旧地点（content/sites.py 的名字）→ 核心域内互不重合的固定坐标（间距 ≥ 800 里）。
LEGACY_ANCHORS: dict = {
    "坊市": (10000.0, 10000.0),        # 青石镇（核心域中心）
    "灵脉山": (11200.0, 10600.0),
    "幽谷秘境": (8800.0, 11200.0),
    "古战场遗迹": (11600.0, 8800.0),
    "上古洞府": (8400.0, 8600.0),
}

TOWN_PREFIXES: tuple = (
    "青石", "白水", "丹霞", "苍梧", "落霞", "玄水", "黑砂", "赤炎",
    "青岚", "沧溟", "黄沙", "云梦", "赤壁", "东海", "落雁", "碧波",
    "金乌", "幽篁", "玄冰", "雪岭", "寒松", "玄天", "白霜", "极北",
    "流云", "望仙", "归墟", "玉京",
)
TOWN_SUFFIXES: tuple = ("镇", "城", "坊", "关", "集")
# 每域城镇数（core 10 / near 9 / outer 8 → 总数 206，落在定案 200~300 区间内）
TOWN_COUNT_BY_TIER: dict = {"core": 10, "near": 9, "outer": 8}
MAIN_TOWN_NAME = "青石镇"          # 核心域主城（锚在 LEGACY_ANCHORS["坊市"]）

# 内容点种类：键 = 英文 id 前缀；density = 每格命中概率（core > near > outer）
CONTENT_KINDS: dict = {
    "mine": {"name": "矿脉", "weight": 1.0,
             "density": {"core": 0.0167, "near": 0.0100, "outer": 0.0050}},
    "herb": {"name": "灵草", "weight": 1.2,
             "density": {"core": 0.0200, "near": 0.0120, "outer": 0.0060}},
    "lair": {"name": "兽巢", "weight": 0.9,
             "density": {"core": 0.0150, "near": 0.0090, "outer": 0.0045}},
    "ruin": {"name": "遗迹", "weight": 0.8,
             "density": {"core": 0.0133, "near": 0.0080, "outer": 0.0040}},
    "secret": {"name": "秘境入口", "weight": 0.4,
               "density": {"core": 0.0067, "near": 0.0040, "outer": 0.0020}},
    "vein": {"name": "灵脉", "weight": 0.6,
             "density": {"core": 0.0100, "near": 0.0060, "outer": 0.0030}},
    "post": {"name": "驿站", "weight": 1.1,
             "density": {"core": 0.0183, "near": 0.0110, "outer": 0.0055}},
}
CONTENT_KIND_ORDER: tuple = ("mine", "herb", "lair", "ruin", "secret", "vein", "post")
CONTENT_POINT_ID_SEQ_WIDTH = 2     # id 形如 f"{kind}_{domain.name}_{seq:02d}"
# 灵脉每域个数区间（任务书 §4.2 步骤 6）
VEIN_PER_DOMAIN = (3, 6)
