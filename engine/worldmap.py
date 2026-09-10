"""世界地图内核：连续坐标 + 代价场 + A* + 生成式地形 / 水系 / 灵脉 / 城镇 / 路网。

**纯逻辑、零 I/O**（不读文件、不写文件、不打印调试、不依赖 Web 层与游戏循环）。
**确定性唯一来源 = `world_seed`**：同一 seed 下地形 / 河流 / 城镇 / 路网 / 内容点 /
`terrain_checksum()` 跨进程、跨调用逐位一致（不用 `random`、不用内置哈希、
不依赖 `PYTHONHASHSEED`、不依赖 `set`/`dict` 迭代顺序——要顺序就 `sorted()`）。

**"格"只是加速结构**：位置是连续坐标（float64，单位里），`WORLD_CELL_LI=100` 的内部栅格
仅用于生成与寻路；地形按格取常数，玩家无感（`docs/地图与场所定案.md` §一.2）。

生成管线（惰性 + 实例内缓存，顺序固定，见任务书 §4.2）：
    1 地形场（fbm 噪声）→ 2 地形分类（含边界虚空 / 禁制）
    → 3 水系（河 / 湖 / 渡口）→ 4 城镇选址 → 5 路网（A* 最小代价 + Kruskal 连通）
    → 6 内容点与灵脉 → 7 覆盖层合成（`terrain_at` = 路网/城镇覆盖 → 基础地形）
"""

import functools
import hashlib
import heapq
import math
from dataclasses import dataclass, field

from content import regions as R
from engine import settings as S

# ============ 常量 ============
_MASK64 = (1 << 64) - 1
_SQRT2 = math.sqrt(2.0)
_CELL_LI = S.WORLD_CELL_LI              # 100.0
_N = S.WORLD_CELLS                      # 200
_WORLD_LI = S.WORLD_LI
_DOMAIN_CELLS = S.WORLD_CELLS // S.DOMAIN_GRID   # 每域 40 格
_PLAN = S.ROAD_PLAN_MULT                # 2（路网规划粗栅格：2 格 = 200 里）
_SI_PER_DAY = float(S.SI_PER_DAY)

_HARD = R.HARD_BLOCK_IDS
_T_DEEPSEA = R.T_DEEPSEA
_T_CLIFF = R.T_CLIFF
_T_WARD = R.T_WARD
_T_VOID = R.T_VOID
_T_ROAD = R.T_ROAD
_T_TRAIL = R.T_TRAIL
_T_PLAIN = R.T_PLAIN
_T_GRASS = R.T_GRASS
_T_FOREST = R.T_FOREST
_T_HILL = R.T_HILL
_T_DESERT = R.T_DESERT
_T_MOUNTAIN = R.T_MOUNTAIN
_T_CANYON = R.T_CANYON
_T_SWAMP = R.T_SWAMP
_T_SNOW = R.T_SNOW
_T_LAVA = R.T_LAVA
_T_WATER = R.T_WATER
_T_FORD = R.T_FORD

# 地形分类阈值（任务书 §4.2 步骤 2 的阈值；顺序：沙漠/沼泽/林地早于丘陵）
_TH_DEEPSEA = 0.18
_TH_WATER = 0.24
_TH_CLIFF = 0.90
_TH_LAVA_FIRE = 0.80
_TH_LAVA_ELEV = 0.55
_TH_SNOW = 0.16
_TH_DESERT_MOIST = 0.22
_TH_DESERT_TEMP = 0.62
_TH_DESERT_ELEV = 0.78
_TH_SWAMP_MOIST = 0.76
_TH_SWAMP_ELEV = 0.50
_TH_MOUNTAIN = 0.80
_TH_CANYON_ELEV = 0.66
_TH_CANYON_SLOPE = 0.04
_TH_FOREST = 0.60
_TH_HILL = 0.60
_TH_PLAIN = 0.44

# 对比度拉伸（任务书 §4.2 步骤 1）：把集中在 0.5 附近的 fbm 推向两端，
# 否则沙漠/山地/雪原几乎不出现（不拉伸时沙漠 0.02%、丘陵独占 38%）。
_CONTRAST_K = 1.8

# 噪声场参数（任务书 §4.2 步骤 1）：(基周期里, 倍频数)
_PERIOD_ELEV, _OCT_ELEV = 6400.0, 5
_PERIOD_MOIST, _OCT_MOIST = 4800.0, 5
_PERIOD_TEMP, _OCT_TEMP = 8000.0, 4
_PERIOD_FIRE, _OCT_FIRE = 3000.0, 3

# 3×3 采样偏移（四角内缩 + 四边中点 + 格心；样本严格落在格内，任务书 §4.3）
_SAMPLES = (0.15, 0.5, 0.85)

# 禁制：3 处，中心互距 ≥ 1500 里（不满足则重掷 ≤20 次；仍不满足则减量但保底 1 处）
_WARD_COUNT = 3
_WARD_MIN_GAP_LI = 1500.0
_WARD_R_MIN = 200.0
_WARD_R_MAX = 400.0
_WARD_RETRY = 20

# 城镇：最小间距逐级放宽（里）
_TOWN_R_MIN = 200.0          # 城镇影响半径下限（里）
_TOWN_R_MAX = 620.0          # 上限
_MAIN_TOWN = R.MAIN_TOWN_NAME

# 内容点 id 序号位宽
_SEQ_W = R.CONTENT_POINT_ID_SEQ_WIDTH
_CN_ORDINALS = ("二", "三", "四", "五", "六", "七", "八", "九", "十")

# 路宽（里，定案 §4.4）：真实路面 + **独立**判定容差
_ROAD_WIDTH = 0.02        # 官道 10 m
_TRAIL_WIDTH = 0.004      # 小径 2 m
_ROAD_TOL = 0.05          # 官道判定容差 25 m
_TRAIL_TOL = 0.02         # 小径判定容差 10 m

# 河宽（里，定案 §4.4）：**沿程渐变**——源头窄、下游宽
_RIVER_W_HEAD = 0.05      # 25 m
_RIVER_W_TAIL = 0.40      # 200 m
_FORD_R = 0.03            # 渡口判定半径（里）= 15 m
_FORD_SPACING_LI = 600.0  # 渡口沿河间距（里）


def _dist_point_seg(px: float, py: float, ax: float, ay: float,
                    bx: float, by: float) -> float:
    """点到线段的最短距离（里）。"""
    dx = bx - ax
    dy = by - ay
    if dx == 0.0 and dy == 0.0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    if t < 0.0:
        t = 0.0
    elif t > 1.0:
        t = 1.0
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


# ============ 稳定哈希与噪声（参考实现，跨实现可复现） ============
@functools.lru_cache(maxsize=8192)
def _fnv1a(s: str) -> int:
    """FNV-1a 64 位（对 salt 字符串 memoize，噪声热路径会被调用百万次）。"""
    h = 0xCBF29CE484222325
    for b in s.encode("utf-8"):
        h = ((h ^ b) * 0x100000001B3) & _MASK64
    return h


def _splitmix64(z: int) -> int:
    """splitmix64 位混合（与 hash01 一起构成稳定派生）。"""
    z = (z + 0x9E3779B97F4A7C15) & _MASK64
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _MASK64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _MASK64
    return (z ^ (z >> 31)) & _MASK64


def hash01(seed: int, salt: str, i: int, j: int) -> float:
    """(seed, salt, i, j) → [0,1) 的稳定浮点。跨进程 / 跨平台一致。"""
    z = (int(seed) * 0x9E3779B97F4A7C15
         + _fnv1a(salt)
         + (i & _MASK64) * 0xC2B2AE3D27D4EB4F
         + (j & _MASK64) * 0x165667B19E3779F9) & _MASK64
    return (_splitmix64(z) >> 11) / float(1 << 53)


def _smooth(t: float) -> float:
    """smoothstep 3t² − 2t³。"""
    return t * t * (3.0 - 2.0 * t)


def _contrast(v: float) -> float:
    """对比度拉伸 clamp((v−0.5)×1.8+0.5, 0, 1)（任务书 §4.2 步骤 1）。"""
    v = (v - 0.5) * _CONTRAST_K + 0.5
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v


# 格点阵缓存：(seed, salt, period) → n×n 随机值阵（每个倍频独立，避免高频混叠）
_LATTICE_CACHE: dict = {}
_LATTICE_CACHE_MAX = 512


def _lattice(seed: int, salt: str, period: float):
    """取（或构造）周期为 period 的格点阵；每轴格点数 = int(WORLD_LI / period) + 2。"""
    key = (int(seed), salt, float(period))
    lat = _LATTICE_CACHE.get(key)
    if lat is not None:
        return lat
    n = int(_WORLD_LI / period) + 2
    lat = [[hash01(seed, salt, i, j) for i in range(n)] for j in range(n)]
    if len(_LATTICE_CACHE) >= _LATTICE_CACHE_MAX:
        _LATTICE_CACHE.pop(next(iter(_LATTICE_CACHE)))
    _LATTICE_CACHE[key] = lat
    return lat


def value_noise(seed: int, x: float, y: float, period: float, salt: str) -> float:
    """周期为 period（里）的二维值噪声，返回 [0,1]（smoothstep 双线性插值）。"""
    px = x / period
    py = y / period
    i0 = int(math.floor(px))
    j0 = int(math.floor(py))
    fx = _smooth(px - i0)
    fy = _smooth(py - j0)
    lat = _lattice(seed, salt, period)
    n = len(lat)
    i1 = i0 + 1
    j1 = j0 + 1
    if i0 < 0:
        i0 = 0
    elif i0 > n - 1:
        i0 = n - 1
    if i1 < 0:
        i1 = 0
    elif i1 > n - 1:
        i1 = n - 1
    if j0 < 0:
        j0 = 0
    elif j0 > n - 1:
        j0 = n - 1
    if j1 < 0:
        j1 = 0
    elif j1 > n - 1:
        j1 = n - 1
    row0 = lat[j0]
    row1 = lat[j1]
    a = row0[i0]
    v0 = a + (row0[i1] - a) * fx
    b = row1[i0]
    v1 = b + (row1[i1] - b) * fx
    return v0 + (v1 - v0) * fy


def fbm(seed: int, x: float, y: float, base_period: float, octaves: int,
        salt: str, gain: float = 0.5, lacunarity: float = 2.0) -> float:
    """多倍频叠加，归一化到 [0,1]。第 k 倍频周期 = base_period / lacunarity**k，且用独立格点阵。

    **倍频 salt 约定**（实现细节，任务书 §4.1 口径说明）：第 k 倍频的格点阵 salt = `salt + ":" + str(k)`，
    即每个倍频有独立的随机格点阵（避免高频倍频与低频混叠）；`hash01` 本身与参考实现逐位一致。
    """
    total = 0.0
    amp = 1.0
    norm = 0.0
    p = float(base_period)
    for k in range(int(octaves)):
        total += amp * value_noise(seed, x, y, p, salt + ":" + str(k))
        norm += amp
        amp *= gain
        p /= lacunarity
    return total / norm


# ============ 连续地形采样（P4-T2-R1：地形真相 = 纯函数，零存储） ============
# 定案 §3.5：全局只物化稀疏特征（河/路/城/灵脉），**地形一律按需采样**。
_SLOPE_EPS = 100.0        # 坡度采样半径（里）——**固定 100 里**（与格宽解耦，保证峡谷分布不随格宽漂移）
# 内容点密度按**面积**归一：格变小 → 每格命中概率等比缩小，世界内容总量不随格宽膨胀
_DENSITY_SCALE = (_CELL_LI / 100.0) ** 2
_SLOPE_OFFS = ((1.0, 0.0), (-1.0, 0.0), (0.0, 1.0), (0.0, -1.0),
               (1.0, 1.0), (1.0, -1.0), (-1.0, 1.0), (-1.0, -1.0))


def _clamp01(v: float) -> float:
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v


def _domain_bias_at(x: float, y: float) -> tuple:
    """域级场偏置——**双线性平滑**（2026-09-10：修"地图上的切片/断层痕迹"）。

    域是 5×5 方格。若把偏置按域硬加，边界会出现阶跃（实测 elev 在 x=8000 处跳 +0.02，
    temp 最大 ±0.14）→ 地图上出现沿域边界的直线断层。这里按**域中心**做双线性插值，
    过渡自然。域仍是离散概念（五行浓度 / 势力归属等照旧按域判定）。
    """
    g = S.DOMAIN_GRID
    fx = x / S.DOMAIN_LI - 0.5
    fy = y / S.DOMAIN_LI - 0.5
    ix = int(math.floor(fx))
    iy = int(math.floor(fy))
    tx = fx - ix
    ty = fy - iy

    def _at(px: int, py: int) -> tuple:
        if px < 0:
            px = 0
        elif px > g - 1:
            px = g - 1
        if py < 0:
            py = 0
        elif py > g - 1:
            py = g - 1
        fb = R.DOMAINS[py * g + px].field_bias
        return (fb.get("elev", 0.0), fb.get("moist", 0.0),
                fb.get("temp", 0.0), fb.get("fire", 0.0))

    b00 = _at(ix, iy)
    b10 = _at(ix + 1, iy)
    b01 = _at(ix, iy + 1)
    b11 = _at(ix + 1, iy + 1)
    return tuple(
        (b00[k] * (1.0 - tx) + b10[k] * tx) * (1.0 - ty)
        + (b01[k] * (1.0 - tx) + b11[k] * tx) * ty
        for k in range(4)
    )


def sample_fields(seed: int, x: float, y: float) -> tuple:
    """任意坐标 → (elev, moist, temp, fire)，均归一化 [0,1]。纯函数、零存储。

    与首版全图数组的取值口径**逐位一致**（同一 fbm / 对比度 / 域偏置 / 纬度项）。
    """
    seed = int(seed)
    x = float(x)
    y = float(y)
    b = _domain_bias_at(x, y)
    half = _WORLD_LI / 2.0
    lat = 1.0 - abs(y - half) / half
    e = _clamp01(_contrast(fbm(seed, x, y, _PERIOD_ELEV, _OCT_ELEV, "elev")) + b[0])
    m = _clamp01(_contrast(fbm(seed, x, y, _PERIOD_MOIST, _OCT_MOIST, "moist")) + b[1])
    t = _clamp01(_contrast(fbm(seed, x, y, _PERIOD_TEMP, _OCT_TEMP, "temp")) * 0.7
                 + 0.5 * lat + b[2])
    f = _clamp01(_contrast(fbm(seed, x, y, _PERIOD_FIRE, _OCT_FIRE, "fire")) + b[3])
    return e, m, t, f


def _slope_at(seed: int, x: float, y: float, e0: float) -> float:
    """四向高程最大差。**仅在可能判为峡谷时调用**（省 4 次采样）。"""
    b0 = _domain_bias_at(x, y)[0]
    slope = 0.0
    for dx, dy in _SLOPE_OFFS:
        ee = _clamp01(_contrast(fbm(seed, x + dx * _SLOPE_EPS, y + dy * _SLOPE_EPS,
                                    _PERIOD_ELEV, _OCT_ELEV, "elev")) + b0)
        d = ee - e0
        if d < 0.0:
            d = -d
        if d > slope:
            slope = d
    return slope


def classify_point(seed: int, x: float, y: float) -> int:
    """任意坐标 → **基础**地形 id（不含覆盖层）。纯函数、无实例状态。"""
    e, m, t, f = sample_fields(seed, x, y)
    slope = _slope_at(seed, x, y, e) if e > _TH_CANYON_ELEV else 0.0
    return _classify(e, m, t, f, slope)


# ============ 坐标工具 ============
def clamp_xy(x: float, y: float) -> tuple:
    """把坐标 clamp 到世界内 [0, WORLD_LI]（负坐标同样 clamp，不抛异常）。"""
    fx = float(x)
    fy = float(y)
    if fx < 0.0:
        fx = 0.0
    elif fx > _WORLD_LI:
        fx = _WORLD_LI
    if fy < 0.0:
        fy = 0.0
    elif fy > _WORLD_LI:
        fy = _WORLD_LI
    return fx, fy


def cell_of(x: float, y: float) -> tuple:
    """连续坐标 → 栅格 (cx, cy)，越界 clamp 到边界格。"""
    cx = int(math.floor(float(x) / _CELL_LI))
    cy = int(math.floor(float(y) / _CELL_LI))
    if cx < 0:
        cx = 0
    elif cx > _N - 1:
        cx = _N - 1
    if cy < 0:
        cy = 0
    elif cy > _N - 1:
        cy = _N - 1
    return cx, cy


def center_of(cx: int, cy: int) -> tuple:
    """格心坐标（里）。"""
    return ((cx + 0.5) * _CELL_LI, (cy + 0.5) * _CELL_LI)


@functools.lru_cache(maxsize=8192)
def _town_radius_cached(seed: int, cx: int, cy: int) -> float:
    """`_town_radius` 的纯函数缓存。

    城镇影响半径在生成期与查询期都会被算到（"这个坐标在不在某镇内"要遍历全部城镇），
    每次重算都要走 `hash01`；生成完的世界里 `(seed, cx, cy) → 半径` 是**纯函数**，
    故直接缓存（无状态、跨实例安全）。
    """
    return _town_radius(seed, cx, cy)


def _town_radius(seed: int, cx: int, cy: int) -> float:
    """城镇影响半径（里）——**可变**：200~620 里，偏小分布。

    统一半径会让城镇均匀铺排、连成直线；可变半径才有"集镇群 + 孤悬边镇"的层次。
    """
    u = hash01(seed, "townr", cx, cy)
    return _TOWN_R_MIN + (_TOWN_R_MAX - _TOWN_R_MIN) * (u * u)


def _town_xy(seed: int, cx: int, cy: int) -> tuple:
    """城镇实际坐标 = 格心 + **确定性抖动**（±0.5 格）。

    无抖动时候选格按固定步长采样 → 城镇全落在 100 里格点上，地图上排成整齐行列
    （实测 seed 20260910：205 座城镇的 x%100、y%100 全为 25，同一条水平线最多 22 座）。
    """
    x, y = center_of(cx, cy)
    jx = (hash01(seed, "townjx", cx, cy) - 0.5) * _CELL_LI
    jy = (hash01(seed, "townjy", cx, cy) - 0.5) * _CELL_LI
    return x + jx, y + jy


# ============ 数据记录 ============
@dataclass(frozen=True)
class Town:
    """一个城镇（世界层的一个地点）。`id = f"town_{name}"`。"""
    id: str
    name: str
    x: float
    y: float
    domain_idx: int
    tier: str
    is_main: bool


@dataclass(frozen=True)
class ContentPoint:
    """一个内容点（矿脉 / 灵草 / 兽巢 / 遗迹 / 秘境入口 / 灵脉 / 驿站）。"""
    id: str
    kind: str
    name: str
    x: float
    y: float
    domain_idx: int
    element: str
    tier: str


class _FeatureTuple(tuple):
    """要素元组：既可用属性取用（`wm.towns`），也可按任务书 §4.0 方法调用（`wm.towns()`）。

    两种取用方式返回同一个对象，保证 `wm.towns() == wm.towns`。
    """

    __slots__ = ()

    def __call__(self):
        return self


@dataclass(frozen=True)
class River:
    """一条河（折线 + 格序列 + 长度 + **沿程渐变的河宽**）。

    `cells` 与 `fords` 均为 **(cx, cy) 格坐标**（`cells` 仅供调试 / ASCII）。
    `widths` 与 `points` 等长：源头 `_RIVER_W_HEAD` → 下游 `_RIVER_W_TAIL`（里）。
    """
    points: tuple
    cells: tuple
    length_li: float
    fords: tuple = ()
    widths: tuple = ()


@dataclass(frozen=True)
class Road:
    """一段路（A* 最小代价路径 = **图上的边**；宽度见定案 §4.4）。"""
    kind: str            # "road"（跨域主路 / 域主城相连）/ "trail"（域内支路）
    points: tuple
    cells: tuple         # 降采样格序列（**仅供调试 / ASCII**，不作地形真相）
    length_li: float
    a: str
    b: str
    width_li: float = _ROAD_WIDTH    # 真实路面（里）
    tol_li: float = _ROAD_TOL        # 判定容差（里）


@dataclass
class PathResult:
    """一次寻路的结果（折线 / 格序列 / 耗时 / 地形构成 / 失败原因）。"""
    points: tuple = ()
    cells: tuple = ()
    total_si: int = 0
    total_li: float = 0.0
    terrain_mix: dict = field(default_factory=dict)
    blocked: bool = False
    reason: str = "ok"


@dataclass
class WorldState:
    """存档里的世界差异（**只存差异**：地形 / 路网 / 城镇都是 `f(world_seed)` 重建）。"""
    world_seed: int = 0
    pos: tuple = (0.0, 0.0)
    discovered: set = field(default_factory=set)
    places: dict = field(default_factory=dict)
    world_diff: dict = field(default_factory=dict)
    map_level: str = "none"

    def to_dict(self) -> dict:
        """序列化；键集合**恰为** 6 个（地形 / 路网 / 位图一律不存）。"""
        return {
            "world_seed": int(self.world_seed),
            "pos": [float(self.pos[0]), float(self.pos[1])],
            "discovered": sorted(self.discovered),
            "places": dict(self.places),
            "world_diff": dict(self.world_diff),
            "map_level": str(self.map_level),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "WorldState":
        """反序列化：pos 归一为 (float, float)、discovered 归一为 set、缺字段用默认值。"""
        d = d or {}
        pos = d.get("pos", (0.0, 0.0))
        try:
            px, py = float(pos[0]), float(pos[1])
        except (TypeError, ValueError, IndexError):
            px, py = 0.0, 0.0
        return cls(
            world_seed=int(d.get("world_seed", 0)),
            pos=(px, py),
            discovered=set(d.get("discovered", ()) or ()),
            places=dict(d.get("places", {}) or {}),
            world_diff=dict(d.get("world_diff", {}) or {}),
            map_level=str(d.get("map_level", "none")),
        )

    @classmethod
    def legacy(cls, world_seed: int, day: int = 0, location: str = "") -> "WorldState":
        """老档迁移：旧地点名 → 核心域固定锚点；无舆图状态给 `coarse`（定案 §7）。

        `day` 仅为旧调用点兼容保留（时间由 `GameState.t` 唯一承载，不进 WorldState）。
        """
        pos = R.LEGACY_ANCHORS.get(location, R.CORE_DOMAIN_CENTER)
        return cls(world_seed=int(world_seed), pos=(float(pos[0]), float(pos[1])),
                   map_level="coarse")

    def with_pos(self, x: float, y: float) -> "WorldState":
        """返回一个只改了位置的副本（不可变式更新）。"""
        return WorldState(world_seed=self.world_seed, pos=(float(x), float(y)),
                          discovered=set(self.discovered), places=dict(self.places),
                          world_diff=dict(self.world_diff), map_level=self.map_level)


class CostField:
    """采样好的代价场（按需在 box 内生成；"格"为加速结构）。

    - `passable(cx, cy)` / `cost(cx, cy)` 接收**细格坐标**（100 里格）；
    - `step` 为栅格步长（细格数）：1 = 细格寻路，ROAD_PLAN_MULT = 路网规划粗栅格；
    - 单位代价为「移动一个 field 格」的耗时（息）。
    """

    __slots__ = ("cx0", "cy0", "cx1", "cy1", "step", "ncols", "nrows",
                 "max_speed", "profile", "box", "_pass", "_cost")

    def __init__(self, cx0, cy0, cx1, cy1, step, max_speed, profile):
        self.cx0 = cx0
        self.cy0 = cy0
        self.cx1 = cx1
        self.cy1 = cy1
        self.step = step
        self.ncols = (cx1 - cx0) // step + 1
        self.nrows = (cy1 - cy0) // step + 1
        self.max_speed = max_speed
        self.profile = profile
        self.box = (cx0, cy0, cx1, cy1)
        self._pass = bytearray(self.ncols * self.nrows)
        self._cost = [0.0] * (self.ncols * self.nrows)

    def _index(self, cx: int, cy: int) -> int:
        return ((cy - self.cy0) // self.step) * self.ncols + ((cx - self.cx0) // self.step)

    def inside(self, cx: int, cy: int) -> bool:
        """坐标是否落在本场覆盖范围内。"""
        return (self.cx0 <= cx <= self.cx1 and self.cy0 <= cy <= self.cy1
                and (cx - self.cx0) % self.step == 0 and (cy - self.cy0) % self.step == 0)

    def passable(self, cx: int, cy: int) -> bool:
        """该格对本 profile 是否可通行（越界 / 非栅格对齐 → False）。"""
        if not self.inside(cx, cy):
            return False
        return bool(self._pass[self._index(cx, cy)])

    def cost(self, cx: int, cy: int) -> float:
        """该格的单位代价（息 / 格）；不可通行返回 inf。"""
        if not self.passable(cx, cy):
            return float("inf")
        return self._cost[self._index(cx, cy)]

    def cell_li(self) -> float:
        """一个 field 格的边长（里）。"""
        return self.step * _CELL_LI


# ============ Profile 参数表 ============
# 代价模型（T3 改）：**代价域线性组合**
#   格代价 = 时间项(息) + 危险项(息) + 隐蔽项(息)
#     t_cost = 采样点里程 / 速度 × 43200 × mult        # mult 只含森林偏好等"速度型"偏好
#     d_cost = danger_w × danger × 采样点里程
#     s_cost = route_pen × 采样点里程                  # stealth 避官道
# 为什么不用"速度域乘法"（旧实现 `mult = 1 + 3×danger`）：每格取 9 点采样的**最小代价**，
# 而乘法惩罚是逐点的 → 格内只要有一点是好地形，惩罚就被 `min` 抹平（实测：危险权重从 3 扫到 100，
# 路径的危险地形占比反而 86%→99%、耗时翻 70 倍）。改成**相加**后，绕开危险地形必然省钱。
PROFILES: dict = {
    "fastest": {"desc": "纯时间最小", "water": "realm", "fly": False},
    # danger_w 单位 = 息 /（危险点·里）。**必须与代价同量纲**（代价单位是息，
    # 每 50 里的时间项是 4.9e4~5.4e5 息）——写成"天"会让惩罚小 43 200 倍而静默失效。
    # 标定（2026-09-10）：1500 ≈ 50 里火山多花 1.2 日，只在真正极端地形上推动绕行；
    # 再大（≥3000）会让 safe 在"两端本身就在火山带"的样本上绕远 2~3 倍却一点没绕开。
    "safe": {"desc": "代价域加危险罚（时间 + danger_w×danger×里程）", "water": "realm", "fly": False,
             "danger_w": 1500.0},
    # route_pen / exposure_pen 单位同上。官道优势是 2× 速度（44 vs 22 里/日），
    # 故避路罚取 2000 ≈ 50 里官道多花 2.3 日，足以让"慢路 + 绕行"胜过蹭路。
    # 标定：2000 → 长距离路网占比 89%→6~11%、耗时 1.70×（达标）；再大只涨耗时不再降路网占比。
    "stealth": {"desc": "避开官道、偏爱林地（暴露低）", "water": "realm", "fly": False,
                "forest_mult": 0.85, "route_pen": 2000.0, "exposure_pen": 1000.0},
    "fly": {"desc": "飞行：忽略地形，仅禁制 / 虚空阻挡", "water": "always", "fly": True},
    "road_plan": {"desc": "建路规划：湖泊 / 河流视为可通行（4 里/日）", "water": "plan", "fly": False,
                  "slope_pen": 3.0, "jitter": 1.10},
    "road_forced": {"desc": "建路兜底：水视为可通行（6 里/日），深海 / 绝壁仍阻挡",
                    "water": "forced", "fly": False},
}

# 危险项上界（A* 启发式可采纳用）：所有地形中最大的 danger
_MAX_TERRAIN_DANGER = max(t.danger for t in R.TERRAINS.values())

# 视野地形修正（任务书 §4.5）
_VISION_TERRAIN_MULT = {
    _T_FOREST: 0.5, _T_SWAMP: 0.6, _T_MOUNTAIN: 0.7, _T_CANYON: 0.7,
    _T_SNOW: 0.8, _T_HILL: 0.9, _T_ROAD: 1.1, _T_TRAIL: 1.1,
}

# ASCII 地图字符（每格一个）
_ASCII_CHARS = {
    _T_DEEPSEA: "深", _T_CLIFF: "崖", _T_WARD: "禁", _T_VOID: "空",
    _T_ROAD: "道", _T_TRAIL: "径", _T_PLAIN: "平", _T_GRASS: "草",
    _T_FOREST: "林", _T_HILL: "丘", _T_DESERT: "沙", _T_MOUNTAIN: "山",
    _T_CANYON: "峡", _T_SWAMP: "沼", _T_SNOW: "雪", _T_LAVA: "火",
    _T_WATER: "水", _T_FORD: "渡",
}


def _union_find_find(par: dict, a):
    while par[a] != a:
        par[a] = par[par[a]]
        a = par[a]
    return a


def _union_find_union(par: dict, rank: dict, a, b) -> bool:
    ra, rb = _union_find_find(par, a), _union_find_find(par, b)
    if ra == rb:
        return False
    if rank[ra] < rank[rb]:
        ra, rb = rb, ra
    par[rb] = ra
    if rank[ra] == rank[rb]:
        rank[ra] += 1
    return True


class WorldMap:
    """一个确定性世界（同一 `world_seed` → 逐位相同）。

    构造时不做事；地形 / 水系 / 城镇 / 路网 / 内容点均在首次访问时惰性生成并缓存。
    """

    def __init__(self, world_seed: int):
        self.world_seed = int(world_seed)
        self._base = None            # bytearray 基础地形（**生成用真相**；查询经 `_cell_terrain` 判定）
        self._cell_tcache = {}       # idx → 特征地形 id（>0）或 -1（=纯噪声，走连续采样）
        self._road_idx = None        # 路网线段空间索引（100 里格分桶）——几何判定用
        self._river_idx = None       # 河流线段空间索引（同上）
        self._elev = None            # list[float] 高程场（城镇评分用）
        self._wards = None           # tuple[(x, y, r), ...]
        self._rivers = None          # tuple[River, ...]
        self._river_cells = None     # frozenset[int] 河格（含渡口格）
        self._towns = None           # tuple[Town, ...]
        self._town_rl = ()           # tuple[float, ...]：与 `_towns` 同序的影响半径
        self._roads = None           # tuple[Road, ...]
        self._points = None          # tuple[ContentPoint, ...]
        self._town_cells = {}        # idx → T_ROAD（城镇覆盖层）
        self._road_cells = {}        # idx → T_ROAD / T_TRAIL / T_FORD（路网覆盖层）
        self._near_river = None      # frozenset[int] 距河 ≤ 2 格的格
        self._comp = None            # 粗栅格连通分量（城镇选址用）
        self._field_cache = {}       # (profile, realm, shenfa, box, roads, step) → CostField
        self._checksum = None
        # 旧地点锚点格（路网落格时跳过，保证锚点基础地形不被覆盖）
        self._anchor_cells = set()
        for _name in sorted(R.LEGACY_ANCHORS):
            _ax, _ay = R.LEGACY_ANCHORS[_name]
            _acx, _acy = cell_of(_ax, _ay)
            self._anchor_cells.add(_acy * _N + _acx)

    # ---------- 通用访问器 ----------
    @classmethod
    def get(cls, world_seed: int) -> "WorldMap":
        """模块级 LRU 缓存（WORLD_CACHE_SIZE 条），同种子复用实例。"""
        key = int(world_seed)
        wm = _WORLD_CACHE.get(key)
        if wm is None:
            wm = cls(key)
            if len(_WORLD_CACHE) >= S.WORLD_CACHE_SIZE:
                _WORLD_CACHE.pop(next(iter(_WORLD_CACHE)))
            _WORLD_CACHE[key] = wm
        return wm

    def to_dict(self) -> dict:
        """只存种子（地形 / 路网纯函数重建）。"""
        return {"world_seed": int(self.world_seed)}

    # ---------- 坐标 / 域 / 五行（任务书 §4.0 实例方法） ----------
    def cell_of(self, x: float, y: float) -> tuple:
        """连续坐标 → 栅格 (cx, cy)，越界 clamp（模块级 `cell_of` 的实例入口）。"""
        return cell_of(x, y)

    def center_of(self, cx: int, cy: int) -> tuple:
        """格心坐标（里）。"""
        return center_of(cx, cy)

    def domain_of(self, x: float, y: float):
        """连续坐标 → 所属 `Domain`（越界 clamp 到边界域）。"""
        return R.DOMAINS[R.domain_at_xy(x, y)]

    def element_at(self, x: float, y: float) -> dict:
        """该点五行浓度 = 地形主五行 + 域级加成（归一化到和 = 1）。"""
        tid = self.terrain_at(x, y, True)
        return R.element_concentration(tid, R.DOMAINS[R.domain_at_xy(x, y)])

    def terrain_at_cell(self, cx: int, cy: int) -> int:
        """格坐标 → **含覆盖层**的地形 id（= 该格中心采样；越界 clamp）。"""
        self._ensure_terrain()
        self._ensure_roads()
        if cx < 0:
            cx = 0
        elif cx > _N - 1:
            cx = _N - 1
        if cy < 0:
            cy = 0
        elif cy > _N - 1:
            cy = _N - 1
        return self._terrain_cell(cx, cy, True)

    def base_terrain(self, cx: int, cy: int) -> int:
        """格坐标 → **不含**覆盖层的基础地形 id（= 该格中心连续采样；越界 clamp）。"""
        if cx < 0:
            cx = 0
        elif cx > _N - 1:
            cx = _N - 1
        if cy < 0:
            cy = 0
        elif cy > _N - 1:
            cy = _N - 1
        return self.base_terrain_at(*center_of(cx, cy))

    def _cell_terrain(self, cx: int, cy: int) -> int:
        """格 → **特征地形** id；该格若无特征（= 纯噪声分类）返回 -1。

        判据：生成期把河 / 湖 / 禁制 / 世界边界 / 旧地点锚点直接写进了 `_base`；
        凡 `_base[idx] != classify_point(格心)` 的格即为"特征格"（稀疏，数量级 10³），
        查询时按格取值；其余格一律走**连续采样**（这就是"精度与内存解耦"的落点）。
        """
        idx = cy * _N + cx
        t = self._cell_tcache.get(idx)
        if t is not None:
            return t
        t = self._base[idx]
        if t != classify_point(self.world_seed, *center_of(cx, cy)):
            self._cell_tcache[idx] = t
            return t
        self._cell_tcache[idx] = -1
        return -1

    def base_terrain_at(self, x: float, y: float) -> int:
        """任意**连续坐标** → **不含覆盖层**的基础地形 id（特征格优先，否则连续采样）。"""
        self._ensure_terrain()
        cx, cy = cell_of(x, y)
        t = self._cell_terrain(cx, cy)
        if t > 0:
            return t
        return classify_point(self.world_seed, x, y)

    def terrain_at(self, x: float, y: float, with_roads: bool = True) -> int:
        """任意**连续坐标** → 地形 id（路网/城镇覆盖 → 特征格 → 连续采样）。

        P4-T2-R1：地形不再"按格取常数"——同一格内不同坐标可以有不同地形。
        """
        self._ensure_terrain()
        if with_roads:
            self._ensure_roads()
        else:
            self._ensure_towns()
        cx, cy = cell_of(x, y)
        idx = cy * _N + cx
        t = self._cell_terrain(cx, cy)
        if t == _T_VOID or t == _T_WARD:
            return t
        if t == _T_FORD:
            return t
        if self._road_cells.get(idx) == _T_FORD:
            return _T_FORD                # 路网跨水处（桥 / 渡）——优先于河流与湖泊
        tt = self._town_cells.get(idx)
        if tt is not None:
            return tt
        tt = self._river_at(x, y)
        if tt:
            return tt                     # 河流是屏障（渡口除外）——先于路网判定
        if with_roads:
            tt = self._road_at(x, y)
            if tt:
                return tt
        if t > 0:
            return t                      # 湖泊
        return classify_point(self.world_seed, x, y)

    def elevation_at(self, x: float, y: float) -> float:
        """连续高程 [0,1]（城镇选址评分 / 调试用）——不再取格值。"""
        return sample_fields(self.world_seed, x, y)[0]

    def _terrain_cell(self, cx: int, cy: int, with_roads: bool = True) -> int:
        """格坐标 → 地形 id（**该格中心的采样** + 覆盖层）——内部调用/渲染降采样用。"""
        idx = cy * _N + cx
        t = self._cell_terrain(cx, cy)
        if t == _T_VOID or t == _T_WARD:
            return t                      # 世界边界 / 禁制：硬阻挡优先
        if t == _T_FORD:
            return t                      # 渡口按格（保证 MAINLAND 连通）
        if self._road_cells.get(idx) == _T_FORD:
            return _T_FORD                # 路网跨水处（桥 / 渡）——优先于河流与湖泊
        tt = self._town_cells.get(idx)
        if tt is not None:
            return tt
        x, y = center_of(cx, cy)
        tt = self._river_at(x, y)
        if tt:
            return tt                     # 河流是屏障（渡口除外）——先于路网判定
        if with_roads:
            tt = self._road_at(x, y)
            if tt:
                return tt
            # **格级采样**：只要格内有路经过就算路——路宽仅 0.02 里，
            # 若只按格心判定，50 里格的代价场几乎感知不到路网（stealth/fastest 会失效）。
            # 点级 `terrain_at(x, y)` 仍按真实路面宽度判定（定案 §4.4）。
            if self._road_idx is None:
                self._ensure_roads()
            segs = self._road_idx.get(idx)
            if segs:
                for _s in segs:
                    if _s[5] == _T_ROAD:
                        return _T_ROAD
                return _T_TRAIL
        if t > 0:
            return t                      # 湖泊（面积型特征）
        return classify_point(self.world_seed, x, y)

    # ---------- 惰性生成入口 ----------
    def _ensure_terrain(self):
        if self._base is not None:
            return
        self._build_terrain()

    def _ensure_rivers(self):
        if self._rivers is not None:
            return
        self._ensure_terrain()
        self._build_rivers()

    def _ensure_towns(self):
        if self._towns is not None:
            return
        self._ensure_rivers()
        self._build_towns()

    def _ensure_roads(self):
        if self._roads is not None:
            return
        self._ensure_towns()
        self._build_roads()
        self._build_road_index()

    def _build_road_index(self):
        """把路网折线按 100 里格分桶（线段注册到其覆盖的格），供几何判定 O(1) 查询。"""
        idx = {}
        for rd in (self._roads or ()):
            tol = rd.tol_li
            pts = rd.points
            for k in range(1, len(pts)):
                ax, ay = pts[k - 1]
                bx, by = pts[k]
                c0x, c0y = cell_of(min(ax, bx) - tol, min(ay, by) - tol)
                c1x, c1y = cell_of(max(ax, bx) + tol, max(ay, by) + tol)
                seg = (ax, ay, bx, by, tol,
                       _T_ROAD if rd.kind == "road" else _T_TRAIL)
                for cy in range(c0y, c1y + 1):
                    for cx in range(c0x, c1x + 1):
                        idx.setdefault(cy * _N + cx, []).append(seg)
        self._road_idx = idx

    def _build_river_index(self):
        """把河流折线按 100 里格分桶（河宽 ≤0.2 里，线段自身覆盖的格即可）。"""
        idx = {}
        for rv in (self._rivers or ()):
            pts = rv.points
            wds = rv.widths
            for k in range(1, len(pts)):
                ax, ay = pts[k - 1]
                bx, by = pts[k]
                w = ((wds[k - 1] + wds[k]) * 0.5) if wds else _RIVER_W_HEAD
                c0x, c0y = cell_of(min(ax, bx), min(ay, by))
                c1x, c1y = cell_of(max(ax, bx), max(ay, by))
                seg = (ax, ay, bx, by, w)
                for cy in range(c0y, c1y + 1):
                    for cx in range(c0x, c1x + 1):
                        idx.setdefault(cy * _N + cx, []).append(seg)
        self._river_idx = idx

    def _river_at(self, x: float, y: float) -> int:
        """几何判定：该点是否在河面内（渡口优先）。返回 T_WATER / T_FORD，否则 0。"""
        if self._river_idx is None:
            self._ensure_rivers()
            self._build_river_index()
        cx, cy = cell_of(x, y)
        segs = self._river_idx.get(cy * _N + cx)
        if not segs:
            return 0
        for ax, ay, bx, by, w in segs:
            if _dist_point_seg(x, y, ax, ay, bx, by) <= w * 0.5:
                for rv in self._rivers:
                    for (fx, fy) in rv.fords:
                        if (x - fx) ** 2 + (y - fy) ** 2 <= _FORD_R * _FORD_R:
                            return _T_FORD
                return _T_WATER
        return 0

    def _road_at(self, x: float, y: float) -> int:
        """几何判定：该点是否在路面判定容差内。返回 T_ROAD / T_TRAIL，否则 0。

        **不看格**——路宽 0.02 里（10 m），与格宽（100 里）相差 5000 倍，
        用格表达不了（定案 §4.4）。
        """
        if self._road_idx is None:
            self._build_road_index()
        cx, cy = cell_of(x, y)
        segs = self._road_idx.get(cy * _N + cx)
        if not segs:
            return 0
        for ax, ay, bx, by, tol, tid in segs:
            if _dist_point_seg(x, y, ax, ay, bx, by) <= tol:
                return tid
        return 0

    def _ensure_points(self):
        if self._points is not None:
            return
        self._ensure_towns()
        self._build_points()

    # ---------- 步骤 1+2：地形场与分类 ----------
    def _build_terrain(self):
        seed = self.world_seed
        n = _N
        size = n * n
        elev = [0.0] * size
        moist = [0.0] * size
        temp = [0.0] * size
        fire = [0.0] * size
        bias_cache = {}
        half = _WORLD_LI / 2.0
        for cy in range(n):
            y = (cy + 0.5) * _CELL_LI
            lat = 1.0 - abs(y - half) / half       # 赤道 1 → 两极 0
            row = cy * n
            for cx in range(n):
                x = (cx + 0.5) * _CELL_LI
                d = R.domain_of_cell(cx, cy)
                bias = _domain_bias_at(x, y)      # 双线性平滑，与查询路径同一函数
                e = _contrast(fbm(seed, x, y, _PERIOD_ELEV, _OCT_ELEV, "elev")) + bias[0]
                m = _contrast(fbm(seed, x, y, _PERIOD_MOIST, _OCT_MOIST, "moist")) + bias[1]
                t0 = _contrast(fbm(seed, x, y, _PERIOD_TEMP, _OCT_TEMP, "temp"))
                t = t0 * 0.7 + 0.5 * lat + bias[2]     # 赤道最低 0.5，两极可低到 0
                f = _contrast(fbm(seed, x, y, _PERIOD_FIRE, _OCT_FIRE, "fire")) + bias[3]
                if e < 0.0:
                    e = 0.0
                elif e > 1.0:
                    e = 1.0
                if m < 0.0:
                    m = 0.0
                elif m > 1.0:
                    m = 1.0
                if t < 0.0:
                    t = 0.0
                elif t > 1.0:
                    t = 1.0
                if f < 0.0:
                    f = 0.0
                elif f > 1.0:
                    f = 1.0
                i = row + cx
                elev[i] = e
                moist[i] = m
                temp[i] = t
                fire[i] = f

        base = bytearray(size)
        for cy in range(n):
            row = cy * n
            y = (cy + 0.5) * _CELL_LI
            for cx in range(n):
                i = row + cx
                x = (cx + 0.5) * _CELL_LI
                e = elev[i]
                # 坡度：与查询路径**同一函数**（±1 格、8 向），保证"格心采样 == 连续采样"
                slope = _slope_at(seed, x, y, e) if e > _TH_CANYON_ELEV else 0.0
                base[i] = _classify(e, moist[i], temp[i], fire[i], slope)

        # 世界边界：最外 1 圈强制 T_VOID
        for cx in range(n):
            base[cx] = _T_VOID
            base[(n - 1) * n + cx] = _T_VOID
        for cy in range(n):
            base[cy * n] = _T_VOID
            base[cy * n + n - 1] = _T_VOID

        self._base = base
        self._elev = elev

        # 禁制：最多 3 处，中心互距 ≥ 1500 里（重掷 ≤20 次；仍不满足则减量但保底 1 处）
        wards = []
        for k in range(_WARD_COUNT):
            chosen = None
            for t in range(_WARD_RETRY):
                wx = hash01(seed, "ward", k * 32 + t, 0) * (_WORLD_LI - 1000.0) + 500.0
                wy = hash01(seed, "ward", k * 32 + t, 1) * (_WORLD_LI - 1000.0) + 500.0
                wr = _WARD_R_MIN + hash01(seed, "ward", k * 32 + t, 2) * (_WARD_R_MAX - _WARD_R_MIN)
                gap = 1e9
                for p in wards:
                    g = math.hypot(wx - p[0], wy - p[1])
                    if g < gap:
                        gap = g
                if not wards or gap >= _WARD_MIN_GAP_LI:
                    chosen = (wx, wy, wr)
                    break
            if chosen is None:
                if wards:
                    break          # 减量但保底 1 处
                chosen = (hash01(seed, "ward", k * 32, 0) * (_WORLD_LI - 1000.0) + 500.0,
                          hash01(seed, "ward", k * 32, 1) * (_WORLD_LI - 1000.0) + 500.0,
                          _WARD_R_MIN + hash01(seed, "ward", k * 32, 2) * (_WARD_R_MAX - _WARD_R_MIN))
            wards.append(chosen)
        for wx, wy, wr in wards:
            c0 = max(0, int((wx - wr) // _CELL_LI))
            c1 = min(n - 1, int((wx + wr) // _CELL_LI))
            r0 = max(0, int((wy - wr) // _CELL_LI))
            r1 = min(n - 1, int((wy + wr) // _CELL_LI))
            for cy in range(r0, r1 + 1):
                cyy = (cy + 0.5) * _CELL_LI
                for cx in range(c0, c1 + 1):
                    if base[cy * n + cx] == _T_VOID:
                        continue
                    cxx = (cx + 0.5) * _CELL_LI
                    if math.hypot(cxx - wx, cyy - wy) <= wr:
                        base[cy * n + cx] = _T_WARD
        self._wards = _FeatureTuple(wards)
        # 锚点保底：在禁制 / 边界覆盖之后执行（任务书 §4.2 步骤 2）
        self._force_anchors_walkable()

    # ---------- 步骤 3：水系 ----------
    def _build_rivers(self):
        seed = self.world_seed
        n = _N
        base = self._base
        elev = self._elev
        sources = []
        for cy in range(1, n - 1):
            row = cy * n
            for cx in range(1, n - 1):
                e = elev[row + cx]
                if e <= 0.72:
                    continue
                lower = 0
                for dy in (-1, 0, 1):
                    nrow = (cy + dy) * n
                    for dx in (-1, 0, 1):
                        if dx == 0 and dy == 0:
                            continue
                        if elev[nrow + cx + dx] < e:
                            lower += 1
                if lower < 6:
                    continue
                ok = True
                for sy, sx in sources:
                    if abs(sy - cy) < 8 and abs(sx - cx) < 8:
                        ok = False
                        break
                if ok:
                    sources.append((cy, cx))

        rivers = []
        river_cell_set = set()
        lake_budget = 30
        _step = _CELL_LI * 0.5                       # 步长 25 里
        _dirs = tuple((math.cos(i * math.pi / 12.0), math.sin(i * math.pi / 12.0))
                      for i in range(24))            # 24 方向（15° 分辨率，避免"只有 45°"）
        _lo = _CELL_LI
        _hi = _WORLD_LI - _CELL_LI

        def _elev_lerp(px: float, py: float) -> float:
            """高程双线性插值（生成期网格）——比重采 fbm 快得多。"""
            fx = px / _CELL_LI - 0.5
            fy = py / _CELL_LI - 0.5
            ix = int(math.floor(fx))
            iy = int(math.floor(fy))
            tx = fx - ix
            ty = fy - iy
            if ix < 0:
                ix, tx = 0, 0.0
            elif ix > n - 2:
                ix, tx = n - 2, 1.0
            if iy < 0:
                iy, ty = 0, 0.0
            elif iy > n - 2:
                iy, ty = n - 2, 1.0
            i00 = iy * n + ix
            e00 = elev[i00]
            e10 = elev[i00 + 1]
            e01 = elev[i00 + n]
            e11 = elev[i00 + n + 1]
            return ((e00 * (1.0 - tx) + e10 * tx) * (1.0 - ty)
                    + (e01 * (1.0 - tx) + e11 * tx) * ty)

        for sy, sx in sources:
            cur = ((sx + 0.5) * _CELL_LI, (sy + 0.5) * _CELL_LI)
            pts = [cur]
            end = cur
            reason = "capped"
            while len(pts) < 600:
                e0 = _elev_lerp(cur[0], cur[1])
                best = None
                best_e = e0
                for dx, dy in _dirs:
                    nx = cur[0] + dx * _step
                    ny = cur[1] + dy * _step
                    if nx < _lo or ny < _lo or nx > _hi or ny > _hi:
                        continue
                    e = _elev_lerp(nx, ny)
                    if e < best_e - 1e-9:
                        best_e = e
                        best = (nx, ny)
                if best is None:
                    end = cur
                    reason = "sink"
                    break
                cur = best
                pts.append(cur)
                cx, cy = cell_of(cur[0], cur[1])
                bidx = cy * n + cx
                tid = base[bidx]
                if tid == _T_DEEPSEA or tid == _T_WATER or bidx in river_cell_set:
                    end = cur
                    reason = "water"
                    break
                if tid == _T_VOID:
                    end = cur
                    reason = "edge"
                    break
            else:
                end = cur
                reason = "capped"

            # R2b：**不把河写进地形数组**——河流是几何覆盖（折线 + 沿程渐变宽度）。
            # 生成期"河流是屏障"由 river_cell_set 承担。
            # 局部洼地 → 小湖（总湖面积 ≤ 30 格）
            if reason == "sink" and end is not None:
                ex, ey = cell_of(end[0], end[1])
                if elev[ey * n + ex] < 0.40 and lake_budget > 0:
                    blob = [(ey, ex)]
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            if dx == 0 and dy == 0:
                                continue
                            ny2, nx2 = ey + dy, ex + dx
                            if 0 < ny2 < n - 1 and 0 < nx2 < n - 1:
                                blob.append((ny2, nx2))
                    for cy2, cx2 in blob:
                        if lake_budget <= 0:
                            break
                        if base[cy2 * n + cx2] != _T_VOID:
                            base[cy2 * n + cx2] = _T_WATER
                            lake_budget -= 1
            if len(pts) >= 8:
                pts = tuple(pts)
                length = _polyline_li(pts)
                _m = len(pts) - 1
                widths = tuple(_RIVER_W_HEAD + (_RIVER_W_TAIL - _RIVER_W_HEAD) * (i / _m)
                               for i in range(len(pts)))
                cells = tuple(cell_of(px, py) for px, py in pts)
                rivers.append([cells, pts, length, widths])
                for cx2, cy2 in cells:
                    river_cell_set.add(cy2 * n + cx2)

        # 渡口：每条河上按序每 ≥25 格挑一个高程最低的格；两端各留 1 格
        out = []
        for cells, pts, length, widths in rivers:
            # 渡口：沿弧长每 ~600 里一个（坐标 = 河面上的点，浮点里）
            fords = []
            _acc = 0.0
            for _k in range(1, len(pts) - 1):
                _acc += math.hypot(pts[_k][0] - pts[_k - 1][0],
                                   pts[_k][1] - pts[_k - 1][1])
                if _acc >= _FORD_SPACING_LI:
                    fords.append(pts[_k])
                    _acc = 0.0
            if not fords and len(pts) >= 3:
                fords.append(pts[len(pts) // 2])
            for _fx, _fy in fords:
                _fcx, _fcy = cell_of(_fx, _fy)
                base[_fcy * n + _fcx] = _T_FORD
                river_cell_set.add(_fcy * n + _fcx)
            out.append(River(points=pts, cells=cells, length_li=length,
                             fords=tuple(fords), widths=widths))
        self._rivers = _FeatureTuple(out)
        self._river_cells = frozenset(river_cell_set)
        self._force_anchors_walkable()

    def _force_anchors_walkable(self):
        """旧地点锚点保底（任务书 §4.2 步骤 2）：5 个固定坐标强制为可通行地形。

        `"坊市"` → `T_ROAD`，其余 4 个 → `T_PLAIN`；无条件覆盖（否则老档迁移会卡在深海 / 绝壁 / 湖里）。
        """
        for name in sorted(R.LEGACY_ANCHORS):
            x, y = R.LEGACY_ANCHORS[name]
            cx, cy = cell_of(x, y)
            idx = cy * _N + cx
            self._base[idx] = _T_ROAD if name == "坊市" else _T_PLAIN

    def _near_river_cells(self) -> frozenset:
        """距最近河格 ≤ 2 格（切比雪夫）的格集合。"""
        if self._near_river is not None:
            return self._near_river
        out = set()
        n = _N
        for idx in self._river_cells:
            cy, cx = divmod(idx, n)
            for dy in (-2, -1, 0, 1, 2):
                ny = cy + dy
                if ny < 0 or ny >= n:
                    continue
                for dx in (-2, -1, 0, 1, 2):
                    nx = cx + dx
                    if 0 <= nx < n:
                        out.add(ny * n + nx)
        self._near_river = frozenset(out)
        return self._near_river

    # ---------- 大陆连通分量（城镇选址保证路网可连通） ----------
    def _mainland(self):
        """练气期可通行口径的**全局最大连通分量** `MAINLAND`（细格，8 连通 + 防穿角）。

        可通行 = 非硬阻挡且非湖泊/河流（渡口可通行），与 `profile="fastest"`、`realm_idx=1` 一致。
        返回 `(最大分量 id, 每格分量 id 数组, 可通行位图)`；城镇候选格必须落在 `MAINLAND` 内。
        """
        if self._comp is not None:
            return self._comp
        n = _N
        base = self._base
        passable = bytearray(n * n)
        for idx in range(n * n):
            t = base[idx]
            passable[idx] = 0 if (t in _HARD or t == _T_WATER
                                  or (idx in self._river_cells and t != _T_FORD)) else 1
        comp = [-1] * (n * n)
        best_id = -1
        best_size = -1
        cur = 0
        for start in range(n * n):
            if passable[start] == 0 or comp[start] >= 0:
                continue
            stack = [start]
            comp[start] = cur
            size = 0
            while stack:
                i = stack.pop()
                size += 1
                py, px = divmod(i, n)
                for dy in (-1, 0, 1):
                    ny = py + dy
                    if ny < 0 or ny >= n:
                        continue
                    for dx in (-1, 0, 1):
                        if dx == 0 and dy == 0:
                            continue
                        nx = px + dx
                        if nx < 0 or nx >= n:
                            continue
                        j = ny * n + nx
                        if passable[j] == 0 or comp[j] >= 0:
                            continue
                        if dx and dy:
                            # 防穿角（与 A* 同步）：两个正交邻格都要可通行
                            if passable[py * n + nx] == 0 or passable[ny * n + px] == 0:
                                continue
                        comp[j] = cur
                        stack.append(j)
            if size > best_size:
                best_size = size
                best_id = cur
            cur += 1
        self._comp = (best_id, comp, passable)
        return self._comp

    # ---------- 步骤 4：城镇选址 ----------
    def _build_towns(self):
        seed = self.world_seed
        n = _N
        near_river = self._near_river_cells()
        best_comp, comp, _pass = self._mainland()
        base = self._base
        elev = self._elev
        towns = []
        _rl = []            # 与 towns 同序的影响半径缓存（见 town_radius 注释）
        # 主城名先占位，保证随机命名不会抢走「青石镇」
        used_names = {_MAIN_TOWN: True}
        _acx, _acy = cell_of(R.LEGACY_ANCHORS["坊市"][0], R.LEGACY_ANCHORS["坊市"][1])
        _anchor_idx = _acy * _N + _acx          # 坊市锚点格（留给青石镇）
        all_towns = []      # P4-T2：跨域最小间距（格宽变细后相邻域的镇会挤在 100 里内）

        for d in range(len(R.DOMAINS)):
            dom = R.DOMAINS[d]
            quota = R.TOWN_COUNT_BY_TIER[dom.tier]
            cx0 = dom.ix * _DOMAIN_CELLS
            cy0 = dom.iy * _DOMAIN_CELLS
            cands = []
            for cy in range(cy0, cy0 + _DOMAIN_CELLS, 2):
                row = cy * n
                for cx in range(cx0, cx0 + _DOMAIN_CELLS, 2):
                    idx = row + cx
                    tid = base[idx]
                    if (tid in _HARD or tid == _T_WATER or tid == _T_FORD
                            or idx in self._river_cells):
                        continue
                    if comp[idx] != best_comp:      # 前置：候选必须落在 MAINLAND 内
                        continue
                    if idx in self._anchor_cells and idx != _anchor_idx:
                        continue                    # 旧地点锚点格只留给锚点本身
                    e = elev[idx]
                    score = 0.0
                    if idx in near_river:
                        score += 3.0
                    if tid == _T_PLAIN or tid == _T_GRASS:
                        score += 2.0
                    elif tid == _T_HILL or tid == _T_FOREST:
                        score += 1.0
                    if e > 0.75:
                        score -= 0.8
                    if tid in (_T_DESERT, _T_SNOW, _T_SWAMP, _T_LAVA):
                        score -= 0.6
                    cands.append((-score, cy, cx, 1))
            cands.sort()

            accepted = []
            if d == R.CORE_DOMAIN_IDX:
                ax, ay = R.LEGACY_ANCHORS["坊市"]
                acx, acy = cell_of(ax, ay)
                accepted.append((acy, acx, True, _TOWN_R_MIN))
                all_towns.append((acy, acx, True, _TOWN_R_MIN))
            picked = set()
            # **可变影响半径**（200~620 里，偏小分布）：间距不再统一，
            # 既有扎堆的集镇群，也有孤悬的边镇（此前统一 300 里 → 均匀铺排、连成直线）
            for negscore, cy, cx, in_main in cands:
                if len(accepted) >= quota:
                    break
                if not in_main:
                    continue
                key = (cy, cx)
                if key in picked:
                    continue
                x, y = _town_xy(seed, cx, cy)
                r_new = _town_radius(seed, cx, cy)
                ok = True
                for acy, acx, _a, r_old in accepted + all_towns:
                    ax, ay = _town_xy(seed, acx, acy)
                    need = r_new if r_new > r_old else r_old
                    dx = ax - x
                    dy = ay - y
                    if dx * dx + dy * dy < need * need - 1e-9:
                        ok = False
                        break
                if ok:
                    picked.add(key)
                    accepted.append((cy, cx, False, r_new))
                    all_towns.append((cy, cx, False, r_new))

            for k, (cy, cx, is_anchor, _r) in enumerate(accepted):
                idx = cy * n + cx
                self._town_cells[idx] = _T_ROAD
                if is_anchor:
                    name = _MAIN_TOWN
                    x, y = R.LEGACY_ANCHORS["坊市"]
                else:
                    pi = int(hash01(seed, "townname", d, k) * len(R.TOWN_PREFIXES))
                    si = int(hash01(seed, "townsuffix", d, k) * len(R.TOWN_SUFFIXES))
                    if pi >= len(R.TOWN_PREFIXES):
                        pi = len(R.TOWN_PREFIXES) - 1
                    if si >= len(R.TOWN_SUFFIXES):
                        si = len(R.TOWN_SUFFIXES) - 1
                    name = R.TOWN_PREFIXES[pi] + R.TOWN_SUFFIXES[si]
                    x, y = _town_xy(seed, cx, cy)      # 带抖动，避免格点行列
                    if name in used_names:
                        base_name = name
                        dup = 0
                        while name in used_names:
                            dup += 1
                            if dup <= len(_CN_ORDINALS):
                                name = base_name + "·" + _CN_ORDINALS[dup - 1]
                            else:
                                name = base_name + "·" + str(dup + 1)
                used_names[name] = True
                main = is_anchor if d == R.CORE_DOMAIN_IDX else (k == 0)
                towns.append(Town(id="town_" + name, name=name, x=float(x), y=float(y),
                                  domain_idx=d, tier=dom.tier, is_main=bool(main)))
                # 影响半径与 `towns` **同序**缓存：位置查询（"这坐标在不在某镇内"）要遍历
                # 全部城镇，若每次重算半径会变成状态快照里的热点（实测首访 3.8 s）。
                _rl.append(_town_radius(seed, cx, cy))
        self._towns = _FeatureTuple(towns)
        self._town_rl = tuple(_rl)

    # ---------- 步骤 5：路网 ----------
    def _plan_field(self, profile: str = "road_plan") -> CostField:
        """路网规划用的全图粗栅格代价场（不含路网覆盖，湖泊/河流按 profile 处理）。"""
        return self.cost_field(profile, realm_idx=1, shenfa=0.0, box=None,
                               with_roads=False, step=_PLAN)

    def _build_roads(self):
        towns = self._towns
        by_id = {t.id: t for t in towns}
        field = self._plan_field("road_plan")
        forced = None

        # --- 候选边 ---
        cand = {}
        for t in towns:
            same = [o for o in towns if o.domain_idx == t.domain_idx and o.id != t.id]
            same.sort(key=lambda o: ((o.x - t.x) ** 2 + (o.y - t.y) ** 2, o.id))
            for o in same[:2]:
                key = (t.id, o.id) if t.id < o.id else (o.id, t.id)
                if key not in cand:
                    cand[key] = math.hypot(o.x - t.x, o.y - t.y)
        # 跨域：25 个域主城两两取欧氏 MST（Prim，同权按 domain_idx 升序）
        mains = sorted([t for t in towns if t.is_main], key=lambda t: t.domain_idx)
        if len(mains) > 1:
            in_tree = {mains[0].id}
            while len(in_tree) < len(mains):
                best = None
                for a in mains:
                    if a.id not in in_tree:
                        continue
                    for b in mains:
                        if b.id in in_tree:
                            continue
                        dist = math.hypot(b.x - a.x, b.y - a.y)
                        key = (a.id, b.id) if a.id < b.id else (b.id, a.id)
                        item = (dist, b.domain_idx, key)
                        if best is None or item < best:
                            best = item
                if best is None:
                    break
                key = best[2]
                cand.setdefault(key, best[0])
                in_tree.add(key[0] if key[0] not in in_tree else key[1])

        # --- 每条候选边求最小代价路径 ---
        paths = {}
        costs = {}
        for key in sorted(cand):
            a, b = by_id[key[0]], by_id[key[1]]
            ca, cb = cell_of(a.x, a.y), cell_of(b.x, b.y)
            cells, cost, reason = self._astar(field, ca, cb)
            if cells is None:
                if forced is None:
                    forced = self._plan_field("road_forced")
                cells, cost, reason = self._astar(forced, ca, cb)
            if cells is None:
                continue
            paths[key] = cells
            costs[key] = cost

        # --- Kruskal 取最小生成森林 ---
        par = {t.id: t.id for t in towns}
        rank = {t.id: 0 for t in towns}
        accepted = []
        for key in sorted(costs, key=lambda k: (costs[k], k)):
            if _union_find_union(par, rank, key[0], key[1]):
                accepted.append(key)

        # --- 连通性补边（分量间最近欧氏距离对，最多若干次尝试） ---
        def _ncomp():
            roots = set()
            for t in towns:
                roots.add(_union_find_find(par, t.id))
            return len(roots)

        pairs = []
        for i in range(len(towns)):
            for j in range(i + 1, len(towns)):
                a, b = towns[i], towns[j]
                pairs.append((math.hypot(b.x - a.x, b.y - a.y), a.id, b.id))
        pairs.sort()
        failed = set()
        paths_fine = set()
        attempts = 0
        while _ncomp() > 1 and attempts < 120:
            idx = 0
            pick = None
            while idx < len(pairs):
                dist, aid, bid = pairs[idx]
                key = (aid, bid) if aid < bid else (bid, aid)
                if key in failed or _union_find_find(par, aid) == _union_find_find(par, bid):
                    idx += 1
                    continue
                pick = (key, dist)
                break
            if pick is None:
                break
            key = pick[0]
            a, b = by_id[key[0]], by_id[key[1]]
            ca, cb = cell_of(a.x, a.y), cell_of(b.x, b.y)
            attempts += 1
            cells, cost, reason = self._astar(field, ca, cb)
            if cells is None:
                if forced is None:
                    forced = self._plan_field("road_forced")
                cells, cost, reason = self._astar(forced, ca, cb)
            if cells is None:
                # 细格兜底：粗栅格 9 点采样可能切断 1 格宽的陆桥，而 MAINLAND 是细格连通的
                cells, cost, reason = self._route_fine(ca, cb, margin=12, full=True)
                if cells is not None:
                    paths_fine.add(key)
            if cells is None:
                failed.add(key)
                continue
            paths[key] = cells
            costs[key] = cost
            if _union_find_union(par, rank, key[0], key[1]):
                accepted.append(key)

        # --- 落格：粗路径 → 细格折线（跨水改标渡口） ---
        roads = []
        for key in accepted:
            a, b = by_id[key[0]], by_id[key[1]]
            kind = "road" if (a.domain_idx != b.domain_idx or (a.is_main and b.is_main)) else "trail"
            if key in paths_fine:
                fine = self._mark_road_cells(paths[key], kind)     # 细格兜底路径直接落格
            else:
                fine = self._mark_road_path(paths[key], kind)
            if not fine:
                continue
            pts = tuple(center_of(cx, cy) for cx, cy in fine)
            roads.append(Road(kind=kind, points=pts, cells=tuple(fine),
                              length_li=_polyline_li(pts), a=a.id, b=b.id,
                              width_li=_ROAD_WIDTH if kind == "road" else _TRAIL_WIDTH,
                              tol_li=_ROAD_TOL if kind == "road" else _TRAIL_TOL))
        # 收尾不变式：Road.cells 的每一格都必须有路/小径/渡口标记
        # （细格兜底路径可能带入未落格的格；T6 逐格取色依赖这条）
        # 例外：5 个旧地点锚点格刻意保持 T_PLAIN/T_ROAD（不落路网覆盖），跳过。
        _anchor_idx = set()
        for _ax, _ay in R.LEGACY_ANCHORS.values():
            _acx, _acy = cell_of(_ax, _ay)
            _anchor_idx.add(_acy * _N + _acx)
        for _rd in roads:
            _fallback = _T_TRAIL if _rd.kind == "trail" else _T_ROAD
            for _cx, _cy in _rd.cells:
                _idx = _cy * _N + _cx
                if _idx in _anchor_idx:
                    continue
                if _idx not in self._road_cells and _idx not in self._town_cells:
                    self._road_cells[_idx] = _fallback
        self._roads = _FeatureTuple(roads)

    def _mark_road_path(self, coarse_cells, kind: str) -> list:
        """把粗栅格路径落成细格路（每步直线栅格化，遇硬阻挡局部绕行）。

        `coarse_cells` 是粗栅格的**细格坐标**（step 的整数倍），其覆盖的细格中心即 +1。
        """
        reps = [(cx + 1, cy + 1) for cx, cy in coarse_cells]
        fine = [reps[0]] if reps else []
        for i in range(1, len(reps)):
            seg = _line_cells(reps[i - 1], reps[i])
            hit = False
            for cx, cy in seg:
                if self._base[cy * _N + cx] in _HARD:
                    hit = True
                    break
            if hit:
                routed, _c, _r = self._route_fine(reps[i - 1], reps[i])
                if routed:
                    seg = routed
            fine.extend(seg[1:])
        return self._mark_road_cells(fine, kind)

    def _mark_road_cells(self, fine, kind: str) -> list:
        """细格序列落格：跨水改标渡口；硬阻挡 / 城镇格 / 旧地点锚点格不覆盖。"""
        out = []
        for cx, cy in fine:
            idx = cy * _N + cx
            tid = self._base[idx]
            if tid in _HARD:
                continue
            if idx in self._town_cells or idx in self._anchor_cells:
                out.append((cx, cy))
                continue
            if tid == _T_WATER or tid == _T_FORD:
                self._road_cells[idx] = _T_FORD
            else:
                self._road_cells[idx] = _T_ROAD if kind == "road" else _T_TRAIL
            out.append((cx, cy))
        return out

    def _route_fine(self, a: tuple, b: tuple, margin: int = 6, full: bool = False):
        """细格寻路（profile="road_plan"）：局部绕行或全图兜底；返回 (cells 或 None, cost, reason)。"""
        if full:
            field = self.cost_field("road_plan", realm_idx=1, shenfa=0.0, box=None,
                                    with_roads=False, step=1)
        else:
            box = (max(0, min(a[0], b[0]) - margin), max(0, min(a[1], b[1]) - margin),
                   min(_N - 1, max(a[0], b[0]) + margin), min(_N - 1, max(a[1], b[1]) + margin))
            field = self.cost_field("road_plan", realm_idx=1, shenfa=0.0, box=box,
                                    with_roads=False, step=1)
        return self._astar(field, a, b)

    # ---------- 步骤 6：内容点与灵脉 ----------
    def _build_points(self):
        seed = self.world_seed
        n = _N
        near_river = self._near_river_cells()
        base = self._base
        tier_idx = {"core": 0, "near": 1, "outer": 2}
        kinds = [k for k in R.CONTENT_KIND_ORDER if k != "vein"]
        dens = {}
        for k in kinds:
            d = R.CONTENT_KINDS[k]["density"]
            dens[k] = (d["core"] * _DENSITY_SCALE, d["near"] * _DENSITY_SCALE,
                       d["outer"] * _DENSITY_SCALE)
        vein_dens = R.CONTENT_KINDS["vein"]["density"]
        vein_dens_t = (vein_dens["core"] * _DENSITY_SCALE, vein_dens["near"] * _DENSITY_SCALE,
                       vein_dens["outer"] * _DENSITY_SCALE)
        vein_terrain = (_T_MOUNTAIN, _T_HILL, _T_CANYON)

        cands = []
        vein_dense = [[] for _ in range(len(R.DOMAINS))]
        vein_all = [[] for _ in range(len(R.DOMAINS))]
        domain_land = [[] for _ in range(len(R.DOMAINS))]
        for cy in range(n):
            row = cy * n
            for cx in range(n):
                idx = row + cx
                tid = base[idx]
                if tid in _HARD or tid == _T_WATER or idx in self._river_cells:
                    continue
                d = R.domain_of_cell(cx, cy)
                ti = tier_idx[R.DOMAINS[d].tier]
                domain_land[d].append((cy, cx))
                for k in kinds:
                    if hash01(seed, "cp:" + k, cx, cy) < dens[k][ti]:
                        cands.append((cy, cx, k))
                if tid in vein_terrain or idx in near_river:
                    vein_all[d].append((cy, cx))
                    if hash01(seed, "cp:vein", cx, cy) < vein_dens_t[ti]:
                        vein_dense[d].append((cy, cx))

        # 灵脉：每域 3~6 个；平坦域兜底——严格条件格 < 3 时纳入该域全部可通行非水域格
        for d in range(len(R.DOMAINS)):
            n_want = R.VEIN_PER_DOMAIN[0] + int(
                hash01(seed, "veincnt", d, 0) * (R.VEIN_PER_DOMAIN[1] - R.VEIN_PER_DOMAIN[0] + 1))
            if n_want > R.VEIN_PER_DOMAIN[1]:
                n_want = R.VEIN_PER_DOMAIN[1]
            chosen = sorted(vein_dense[d])[:n_want]
            if len(chosen) < R.VEIN_PER_DOMAIN[0]:
                have = set(chosen)
                pool = vein_all[d]
                if len(pool) < R.VEIN_PER_DOMAIN[0]:
                    pool = domain_land[d]          # 平坦域兜底
                rest = [c for c in pool if c not in have]
                rest.sort(key=lambda c: (hash01(seed, "veinpool", c[1], c[0]), c[1], c[0]))
                for c in rest:
                    if len(chosen) >= R.VEIN_PER_DOMAIN[0]:
                        break
                    chosen.append(c)
                    have.add(c)
            for cy, cx in chosen:
                cands.append((cy, cx, "vein"))

        cands.sort()
        seq = {}
        points = []
        for cy, cx, kind in cands:
            d = R.domain_of_cell(cx, cy)
            dom = R.DOMAINS[d]
            key = (kind, d)
            s = seq.get(key, 0) + 1
            seq[key] = s
            x, y = center_of(cx, cy)
            tid = base[cy * n + cx]
            conc = R.element_concentration(tid, dom)
            best_e = R.ELEMENTS[0]
            best_v = -1.0
            for e in R.ELEMENTS:
                v = conc[e]
                if v > best_v + 1e-12:
                    best_v = v
                    best_e = e
            points.append(ContentPoint(
                id="%s_%s_%0*d" % (kind, dom.name, _SEQ_W, s),
                kind=kind,
                name=R.CONTENT_KINDS[kind]["name"] + dom.name[-2:],
                x=x, y=y, domain_idx=d, element=best_e, tier=dom.tier))
        self._points = _FeatureTuple(points)

    # ---------- 对外数据（返回 `_FeatureTuple`：属性取用 / §4.0 方法调用都可用） ----------
    @property
    def wards(self) -> tuple:
        """禁制中心元组：(x, y, 半径里)。"""
        self._ensure_terrain()
        return self._wards

    @property
    def rivers(self) -> tuple:
        """全部河流（含渡口格）；`wm.rivers` 与 `wm.rivers()` 等价。"""
        self._ensure_rivers()
        return self._rivers

    @property
    def towns(self) -> tuple:
        """全部城镇（生成顺序：域 idx 升序、域内评分降序）；`wm.towns` 与 `wm.towns()` 等价。"""
        self._ensure_towns()
        return self._towns

    @property
    def roads(self) -> tuple:
        """全部路网段（A* 最小代价路径落格而成）；`wm.roads` 与 `wm.roads()` 等价。"""
        self._ensure_roads()
        return self._roads

    @property
    def content_points(self) -> tuple:
        """全部内容点；`wm.content_points` 与 `wm.content_points()` 等价。"""
        self._ensure_points()
        return self._points

    def town_by_id(self, town_id: str):
        """按 id 取城镇；找不到返回 None。"""
        self._ensure_towns()
        for t in self._towns:
            if t.id == town_id:
                return t
        return None

    def town_radius(self, town) -> float:
        """城镇影响半径（里）——与生成期同口径，**生成期已算好存入 `_town_rl`**。

        半径在生成时是**可变**的（200~620 里），故不写进 `Town` 字段，而在 `_ensure_towns()`
        时按镇序缓存（`_town_rl` 与 `_towns` 同序）。`town` 可传 `Town` 实例或坐标 tuple。
        """
        self._ensure_towns()
        if not isinstance(town, (tuple, list)):
            seq = self._town_rl
            if seq:
                for i, t in enumerate(self._towns):
                    if t is town or t.id == getattr(town, "id", None):
                        return seq[i]
            cx, cy = cell_of(float(town.x), float(town.y))
        else:
            cx, cy = cell_of(float(town[0]), float(town[1]))
        return _town_radius_cached(self.world_seed, cx, cy)

    def point_by_id(self, point_id: str):
        """按 id 取内容点；找不到返回 None。"""
        self._ensure_points()
        for p in self._points:
            if p.id == point_id:
                return p
        return None

    def points_near(self, x: float, y: float, r: float) -> tuple:
        """半径 r（里）内的内容点，按 (距离, id) 升序。"""
        self._ensure_points()
        out = []
        r2 = float(r) * float(r)
        for p in self._points:
            dx = p.x - x
            dy = p.y - y
            d2 = dx * dx + dy * dy
            if d2 <= r2:
                out.append((math.sqrt(d2), p.id, p))
        out.sort(key=lambda t: (t[0], t[1]))
        return tuple(t[2] for t in out)

    # ---------- 代价场 ----------
    def _profile_params(self, profile: str) -> dict:
        prm = PROFILES.get(profile)
        if prm is None:
            raise KeyError("未知 profile：%s" % profile)
        return prm

    def _sample_speed(self, profile: str, tid: int, realm_idx: int,
                      shenfa: float) -> tuple:
        """返回 (速度里/日, 代价乘区)；速度 ≤ 0 表示不可通行。"""
        if profile == "fly":
            if tid == _T_WARD or tid == _T_VOID:
                return 0.0, 1.0
            return S.FLY_SPEED_LI_PER_DAY, 1.0
        t = R.TERRAINS[tid]
        if profile == "road_plan" or profile == "road_forced":
            if tid in _HARD:
                return 0.0, 1.0
            if t.swim_only:
                return (4.0 if profile == "road_plan" else 6.0), 1.0
            return t.speed * S.realm_speed_mult(realm_idx) * (1.0 + shenfa), 1.0
        speed = t.speed
        if speed <= 0.0:
            return 0.0, 1.0
        if t.swim_only and realm_idx < S.SWIM_MIN_REALM:
            return 0.0, 1.0
        speed = speed * S.realm_speed_mult(realm_idx) * (1.0 + shenfa)
        prm = PROFILES[profile]
        mult = 1.0
        if profile == "stealth" and tid == _T_FOREST:
            mult = prm["forest_mult"]
        # 注意：危险 / 避路惩罚**不在速度域**——它们是代价域的加法项，
        # 由 `_sample_cost` 统一处理（T3 修：速度域乘法会被格内 9 点最小代价抹平）。
        return speed, mult

    def _sample_cost(self, profile: str, tid: int, sp: float, mult: float,
                     li: float) -> float:
        """采样点代价（息）：时间项 + 危险项 + 隐蔽项（**代价域线性组合**）。

        `li` = 该采样点代表的里程（里）。三项同量纲，故格内取 `min` 时惩罚不会被抹平。
        """
        prm = PROFILES[profile]
        cost = li / sp * _SI_PER_DAY * mult
        dw = prm.get("danger_w")
        if dw:
            cost += dw * R.TERRAINS[tid].danger * li
        if profile == "stealth":
            t = R.TERRAINS[tid]
            rp = prm.get("route_pen")
            if rp and tid in (_T_ROAD, _T_TRAIL):
                cost += rp * li                       # 避开官道 / 小径
            ep = prm.get("exposure_pen")
            if ep and t.exposure:
                cost += ep * t.exposure * li          # 避开暴露高的开敞地
        return cost

    def speed_at(self, x: float, y: float, realm_idx: int = 1,
                 shenfa: float = 0.0, with_roads: bool = True) -> float:
        """有效速度（里/日）= 地形速度 × 境界系数 × (1+身法)；硬阻挡 / 不可渡 → 0.0。"""
        tid = self.terrain_at(x, y, with_roads)
        sp, _m = self._sample_speed("fastest", tid, realm_idx, shenfa)
        return sp

    def passable(self, x: float, y: float, realm_idx: int = 1,
                 profile: str = "fastest") -> bool:
        """该点在本 profile 下是否可通行（含境界门槛：湖泊需筑基、飞行需金丹）。"""
        self._profile_params(profile)
        if profile == "fly" and realm_idx < S.FLY_MIN_REALM:
            return False
        cx, cy = cell_of(x, y)
        tid = self._terrain_cell(cx, cy, True)
        sp, _m = self._sample_speed(profile, tid, realm_idx, 0.0)
        return sp > 0.0

    def _heuristic_max_speed(self, profile: str, realm_idx: int, shenfa: float) -> float:
        """A* 启发式用的速度上界（必须可采纳，不得高估）。"""
        if profile == "fly":
            return S.FLY_SPEED_LI_PER_DAY
        max_terrain = 0.0
        for t in R.TERRAINS.values():
            if t.speed > max_terrain:
                max_terrain = t.speed
        return max_terrain * S.realm_speed_mult(realm_idx) * (1.0 + shenfa)

    def _heuristic_danger_pen(self, profile: str) -> float:
        """启发式的危险项下界（息/里）。

        T3 修：代价里多了"危险项"后，启发式必须同步加上它的下界，否则 A* 不再是可采纳的
        （= 可能给出次优路径）。这里用"该档最危险地形的惩罚"作下界——真实路径上每一点的
        危险 ≤ 该上界，故 `danger_w × danger × 里程 ≥ 此下界`，**不会高估**。
        """
        dw = PROFILES[profile].get("danger_w")
        if not dw:
            return 0.0
        return dw * _MAX_TERRAIN_DANGER

    def cost_field(self, profile: str = "fastest", realm_idx: int = 1, shenfa: float = 0.0,
                   box: tuple = None, with_roads: bool = True, step: int = 1) -> CostField:
        """在 box（细格坐标，含端点）内采样代价场；box=None 表示全图。

        每格采样 3×3 点（格心 + 四角内缩 + 四边中点）；任一样本不可通行 → 该格不可通行；
        否则格代价 = 各样本代价的最小值（保证窄于格宽的路 / 渡口被连续捕捉）。
        """
        self._profile_params(profile)
        _prm = PROFILES[profile]
        if with_roads:
            self._ensure_roads()
        else:
            self._ensure_towns()
        # 建路专用：坡度惩罚 + 确定性抖动 → 路沿河谷 / 山口走，不再笔直
        # （**必须在 _ensure_\* 之后读 `_elev`**，否则首次调用时它还是 None）
        _slope_pen = float(_prm.get("slope_pen", 0.0))
        _jit = float(_prm.get("jitter", 0.0))
        _seed = self.world_seed
        _elev = self._elev
        step = int(step)
        if step < 1:
            step = 1
        if box is None:
            cx0, cy0, cx1, cy1 = 0, 0, _N - 1, _N - 1
        else:
            cx0, cy0, cx1, cy1 = (int(box[0]), int(box[1]), int(box[2]), int(box[3]))
        if cx0 < 0:
            cx0 = 0
        if cy0 < 0:
            cy0 = 0
        if cx1 > _N - 1:
            cx1 = _N - 1
        if cy1 > _N - 1:
            cy1 = _N - 1
        if cx1 < cx0 or cy1 < cy0:
            cx0 = cy0 = cx1 = cy1 = 0
        # 对齐到 step 栅格（向下取整），保证格心落在 100 里格边界上
        cx0 -= cx0 % step
        cy0 -= cy0 % step
        key = (profile, int(realm_idx), float(shenfa), (cx0, cy0, cx1, cy1),
               bool(with_roads), step)
        fld = self._field_cache.get(key)
        if fld is not None:
            return fld

        max_speed = self._heuristic_max_speed(profile, realm_idx, shenfa)
        if max_speed <= 0.0:
            max_speed = 1.0
        fld = CostField(cx0, cy0, cx1, cy1, step, max_speed, profile)
        base = self._base
        road_cells = self._road_cells
        town_cells = self._town_cells
        ncols = fld.ncols
        w = step * _CELL_LI
        for r in range(fld.nrows):
            cy = cy0 + r * step
            y0 = cy * _CELL_LI
            out_row = r * ncols
            for c in range(ncols):
                cx = cx0 + c * step
                x0 = cx * _CELL_LI
                best = float("inf")
                ok = True
                for oy in _SAMPLES:
                    fy = int((y0 + w * oy) // _CELL_LI)
                    if fy > _N - 1:
                        fy = _N - 1
                    frow = fy * _N
                    for ox in _SAMPLES:
                        fx = int((x0 + w * ox) // _CELL_LI)
                        if fx > _N - 1:
                            fx = _N - 1
                        idx = frow + fx
                        if with_roads:
                            tid = road_cells.get(idx)
                            if tid is None:
                                tid = town_cells.get(idx)
                                if tid is None:
                                    tid = base[idx]
                        else:
                            tid = town_cells.get(idx)
                            if tid is None:
                                tid = base[idx]
                        sp, mult = self._sample_speed(profile, tid, realm_idx, shenfa)
                        if sp <= 0.0:
                            ok = False
                            break
                        cst = self._sample_cost(profile, tid, sp, mult, w)
                        if _slope_pen:
                            _e0 = _elev[fy * _N + fx]
                            _e1 = _elev[(fy + 1 if fy + 1 < _N else fy) * _N + fx]
                            _e2 = _elev[fy * _N + (fx + 1 if fx + 1 < _N else fx)]
                            cst *= 1.0 + _slope_pen * (abs(_e1 - _e0) + abs(_e2 - _e0)) * 14.0
                        if _jit:
                            cst *= 1.0 + _jit * (hash01(_seed, "roadjit", fx, fy) - 0.5)
                        if cst < best:
                            best = cst
                    if not ok:
                        break
                i = out_row + c
                if ok:
                    fld._pass[i] = 1
                    fld._cost[i] = best
        if len(self._field_cache) >= 32:
            self._field_cache.pop(next(iter(self._field_cache)))
        self._field_cache[key] = fld
        return fld

    # ---------- A* ----------
    def _astar(self, fld: CostField, start_cell: tuple, goal_cell: tuple,
               max_nodes: int = 200_000):
        """在代价场上跑 8 向 A*；返回 (cells 或 None, 总代价, reason)。"""
        if not fld.passable(*start_cell):
            return None, 0.0, "start_blocked"
        if not fld.passable(*goal_cell):
            return None, 0.0, "goal_blocked"
        ncols, nrows = fld.ncols, fld.nrows
        gx0, gy0, step = fld.cx0, fld.cy0, fld.step
        cost_arr = fld._cost
        pass_arr = fld._pass
        cell_li = fld.cell_li()
        inv_max = _SI_PER_DAY / fld.max_speed
        # T3：危险项（息/里）的下界，保证启发式仍可采纳
        danger_per_li = self._heuristic_danger_pen(fld.profile)

        scol = (start_cell[0] - gx0) // step
        srow = (start_cell[1] - gy0) // step
        gcol = (goal_cell[0] - gx0) // step
        grow = (goal_cell[1] - gy0) // step
        si = srow * ncols + scol
        gi = grow * ncols + gcol
        if si == gi:
            return [tuple(start_cell)], 0.0, "ok"

        total = ncols * nrows
        gcost = [float("inf")] * total
        parent = [-1] * total
        closed = bytearray(total)
        gcost[si] = 0.0

        def _h(col: int, row: int) -> float:
            dx = col - gcol
            if dx < 0:
                dx = -dx
            dy = row - grow
            if dy < 0:
                dy = -dy
            if dx < dy:
                mn, mx = dx, dy
            else:
                mn, mx = dy, dx
            octile = mx + (_SQRT2 - 1.0) * mn
            li = octile * cell_li
            # 危险项按"经过的格数"计（下限 = 至少 1 格），叠加在时间项上
            cells = mx if mx > 1 else 1
            return li * inv_max + danger_per_li * cells * cell_li

        heap = [(_h(scol, srow), _h(scol, srow), si)]
        heap_push = heapq.heappush
        heap_pop = heapq.heappop
        expanded = 0
        found = False
        while heap:
            f, h, cur = heap_pop(heap)
            if closed[cur]:
                continue
            closed[cur] = 1
            if cur == gi:
                found = True
                break
            expanded += 1
            if expanded > max_nodes:
                return None, 0.0, "search_capped"
            row, col = divmod(cur, ncols)
            gcur = gcost[cur]
            for dy in (-1, 0, 1):
                nr = row + dy
                if nr < 0 or nr >= nrows:
                    continue
                for dx in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    nc = col + dx
                    if nc < 0 or nc >= ncols:
                        continue
                    ni = nr * ncols + nc
                    if not pass_arr[ni] or closed[ni]:
                        continue
                    if dx and dy:
                        # 防穿角：两个正交邻格都必须可通行（否则 1 格宽的水系/绝壁/虚空会被斜穿）
                        if not pass_arr[row * ncols + nc] or not pass_arr[nr * ncols + col]:
                            continue
                        step_cost = cost_arr[ni] * _SQRT2
                    else:
                        step_cost = cost_arr[ni]
                    ng = gcur + step_cost
                    if ng < gcost[ni] - 1e-12:
                        gcost[ni] = ng
                        parent[ni] = cur
                        hh = _h(nc, nr)
                        heap_push(heap, (ng + hh, hh, ni))
        if not found:
            return None, 0.0, "no_path"
        cells = []
        cur = gi
        while cur != -1:
            row, col = divmod(cur, ncols)
            cells.append((gx0 + col * step, gy0 + row * step))
            cur = parent[cur]
        cells.reverse()
        return cells, gcost[gi], "ok"

    def find_path(self, start, goal, profile: str = "fastest", realm_idx: int = 1,
                  shenfa: float = 0.0, max_nodes: int = 200_000,
                  with_roads: bool = True) -> PathResult:
        """唯一寻路算法：代价场上的 A*（8 向，对角 ×√2，octile 可采纳启发式）。

        窗口化：以起终点格盒外扩 max(4 格, 10% 对角距离)，无解则 margin ×2 重试，
        最多 4 轮，最后放开到全图。起终点先 clamp 到世界内并转格。
        """
        sx, sy = clamp_xy(*start)
        gx, gy = clamp_xy(*goal)
        if profile == "fly" and realm_idx < S.FLY_MIN_REALM:
            return PathResult(blocked=True, reason="realm_too_low")
        sc = cell_of(sx, sy)
        gc = cell_of(gx, gy)
        diag = math.hypot(gc[0] - sc[0], gc[1] - sc[1])
        margin = int(diag * 0.1)
        if margin < 4:
            margin = 4
        reason = "no_path"
        cells = None
        fld = None
        for _round in range(4):
            # 搜索窗 = 起终点格盒（取并集）外扩 margin
            box = (min(sc[0], gc[0]) - margin, min(sc[1], gc[1]) - margin,
                   max(sc[0], gc[0]) + margin, max(sc[1], gc[1]) + margin)
            fld = self.cost_field(profile, realm_idx, shenfa, box=box,
                                  with_roads=with_roads)
            cells, cost, reason = self._astar(fld, sc, gc, max_nodes=max_nodes)
            if cells is not None:
                break
            if reason in ("start_blocked", "goal_blocked", "search_capped"):
                return PathResult(blocked=True, reason=reason)
            margin *= 2
        if cells is None:
            fld = self.cost_field(profile, realm_idx, shenfa, box=None,
                                  with_roads=with_roads)
            cells, cost, reason = self._astar(fld, sc, gc, max_nodes=max_nodes)
            if cells is None:
                return PathResult(blocked=True, reason=reason)
        return self._make_result(cells, cost, fld, sx, sy, gx, gy)

    def _make_result(self, cells, cost, fld: CostField, sx, sy, gx, gy) -> PathResult:
        cell_li = fld.cell_li()
        pts = [center_of(cx, cy) for cx, cy in cells]
        points = [ (sx, sy) ] + pts[1:-1] + [ (gx, gy) ] if len(pts) > 1 else [ (sx, sy), (gx, gy) ]
        mix = {}
        total_cost = 0.0
        for k in range(1, len(cells)):
            cx, cy = cells[k]
            c = fld.cost(cx, cy)
            if cells[k][0] != cells[k - 1][0] and cells[k][1] != cells[k - 1][1]:
                c *= _SQRT2
            tid = self._terrain_cell(cx, cy, True)
            name = R.TERRAINS[tid].name
            mix[name] = mix.get(name, 0.0) + c
            total_cost += c
        if total_cost > 0.0:
            for k in mix:
                mix[k] = mix[k] / total_cost
        else:
            mix = {}
        total_li = _polyline_li(points)
        total_si = int(math.ceil(cost)) if cost > 0.0 else 0
        if total_si < 1:
            total_si = 1
        return PathResult(points=tuple(points), cells=tuple(cells), total_si=total_si,
                          total_li=total_li, terrain_mix=mix, blocked=False, reason="ok")

    def path_between(self, a, b, **kw) -> PathResult:
        """按对象 / id / 坐标寻路（路网与测试的便捷入口）。"""
        return self.find_path(self._resolve_pos(a), self._resolve_pos(b), **kw)

    def _resolve_pos(self, item) -> tuple:
        if isinstance(item, (Town, ContentPoint)):
            return (item.x, item.y)
        if isinstance(item, str):
            t = self.town_by_id(item)
            if t is not None:
                return (t.x, t.y)
            p = self.point_by_id(item)
            if p is not None:
                return (p.x, p.y)
            raise KeyError("未知地点 id：%s" % item)
        if isinstance(item, (tuple, list)) and len(item) == 2:
            return (float(item[0]), float(item[1]))
        raise TypeError("无法解析的寻路端点：%r" % (item,))

    # ---------- 视野 ----------
    def vision_radius(self, realm_idx: int, tid: int) -> float:
        """神识半径（里）= 境界基础半径 × 地形遮蔽修正。"""
        return S.vision_radius_li(realm_idx) * _VISION_TERRAIN_MULT.get(int(tid), 1.0)

    def visible_points(self, x: float, y: float, realm_idx: int,
                       discovered=None) -> tuple:
        """半径内的内容点，按 (距离, id) 升序。

        v1 不做视线遮挡（山地 / 林地只缩半径，不挡视线）——遮挡留给 T4 迷雾玩法。
        `discovered` 传入已发现 id 集合时只返回**未发现**的点；None 返回全部范围内点。
        """
        self._ensure_roads()      # 视野修正依赖含路网覆盖的有效地形
        self._ensure_points()
        cx, cy = cell_of(x, y)
        radius = self.vision_radius(realm_idx, self._terrain_cell(cx, cy, True))
        r2 = radius * radius
        skip = set(discovered) if discovered else None
        out = []
        for p in self._points:
            if skip is not None and p.id in skip:
                continue
            dx = p.x - x
            dy = p.y - y
            d2 = dx * dx + dy * dy
            if d2 <= r2:
                out.append((math.sqrt(d2), p.id, p))
        out.sort(key=lambda t: (t[0], t[1]))
        return tuple(t[2] for t in out)

    # ---------- 调试视图与校验和 ----------
    def terrain_checksum(self) -> str:
        """16 位十六进制摘要：世界种子 + 基础地形 + 覆盖层 + 河流 + 城镇 + 内容点 id。"""
        if self._checksum is not None:
            return self._checksum
        self._ensure_points()
        self._ensure_roads()
        h = hashlib.blake2b(digest_size=8)
        h.update(("seed=%d;" % self.world_seed).encode("utf-8"))
        h.update(bytes(self._base))
        for idx in sorted(self._road_cells):
            h.update(("%d:%d;" % (idx, self._road_cells[idx])).encode("utf-8"))
        for idx in sorted(self._town_cells):
            h.update(("t%d:%d;" % (idx, self._town_cells[idx])).encode("utf-8"))
        for rv in self._rivers:
            for cy, cx in rv.cells:
                h.update(("%d,%d;" % (cy, cx)).encode("utf-8"))
        for t in self._towns:
            h.update(("%s@%r,%r;" % (t.id, t.x, t.y)).encode("utf-8"))
        for p in self._points:
            h.update((p.id + ";").encode("utf-8"))
        self._checksum = h.hexdigest()
        return self._checksum

    def ascii_map(self, width: int = 100, height: int = 50,
                  show_roads: bool = True, show_towns: bool = True) -> str:
        """每格一个字符的地形速览（人眼 / 单测消费，T6 兜底视图复用）。"""
        self._ensure_roads()
        if width < 1:
            width = 1
        if height < 1:
            height = 1
        town_idx = set(self._town_cells) if show_towns else set()
        rows = []
        for r in range(height):
            y = (r + 0.5) * _WORLD_LI / height
            cy = int(y // _CELL_LI)
            if cy > _N - 1:
                cy = _N - 1
            line = []
            for c in range(width):
                x = (c + 0.5) * _WORLD_LI / width
                cx = int(x // _CELL_LI)
                if cx > _N - 1:
                    cx = _N - 1
                idx = cy * _N + cx
                if idx in town_idx:
                    line.append("镇")
                    continue
                tid = self._terrain_cell(cx, cy, show_roads)
                line.append(_ASCII_CHARS.get(tid, "?"))
            rows.append("".join(line))
        return "\n".join(rows)


def _classify(e: float, m: float, t: float, f: float, slope: float) -> int:
    """地形分类（按序判定，第一条命中即定；任务书 §4.2 步骤 2，沙漠/沼泽/林地早于丘陵）。"""
    if e < _TH_DEEPSEA:
        return _T_DEEPSEA
    if e < _TH_WATER:
        return _T_WATER
    if e > _TH_CLIFF:
        return _T_CLIFF
    if f > _TH_LAVA_FIRE and e > _TH_LAVA_ELEV:
        return _T_LAVA
    if t < _TH_SNOW:
        return _T_SNOW
    if m < _TH_DESERT_MOIST and t > _TH_DESERT_TEMP and e < _TH_DESERT_ELEV:
        return _T_DESERT
    if m > _TH_SWAMP_MOIST and e < _TH_SWAMP_ELEV:
        return _T_SWAMP
    if e > _TH_MOUNTAIN:
        return _T_MOUNTAIN
    if e > _TH_CANYON_ELEV and slope > _TH_CANYON_SLOPE:
        return _T_CANYON
    if m > _TH_FOREST:
        return _T_FOREST
    if e > _TH_HILL:
        return _T_HILL
    if m > _TH_PLAIN:
        return _T_PLAIN
    return _T_GRASS


def _polyline_li(points) -> float:
    """折线总长（里）。"""
    total = 0.0
    for i in range(1, len(points)):
        total += math.hypot(points[i][0] - points[i - 1][0],
                            points[i][1] - points[i - 1][1])
    return total


def _line_cells(a: tuple, b: tuple) -> list:
    """Bresenham 栅格化（细格，8 连通），返回含两端点的格序列。"""
    x0, y0 = int(a[0]), int(a[1])
    x1, y1 = int(b[0]), int(b[1])
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    out = []
    while True:
        out.append((x0, y0))
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x0 += sx
        if e2 < dx:
            err += dx
            y0 += sy
    return out


# 模块级世界缓存（LRU，容量 WORLD_CACHE_SIZE）
_WORLD_CACHE: dict = {}
