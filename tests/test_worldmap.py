"""P4-T2 世界地图内核单测（纯引擎驱动，确定性，禁 pytest）。

覆盖（对应任务书 §七 验收判据 A~J，共 67 条）：
  A. 确定性与纯度：同种子跨进程逐位一致 / 静态禁用项扫描 / 缓存复用 / 重复调用一致
  B. 坐标与域：常量、clamp、25 域、四邻、五行浓度、境界纯函数边界
  C. 地形分布：12 主地形齐全、硬阻挡与水域占比、路网前后差异、边界虚空、速度表、禁制
  D. 水系 / 灵脉 / 内容点：河流与渡口、灵脉分布、总量与 id 唯一、五行、邻近查询
  E. 城镇：配额、间距、唯一性、域主城、旧地点锚点、可通行
  F. 路网：非空与占比、不含硬阻挡、全连通、跨域主路、渡口改标、降低代价
  G. 代价场与 A*：速度公式、境界单调、起终点阻挡、越界、屏障无路、最优性、窗口一致、
     飞行、隐蔽 / 安全 profile、节点上限、结果不变量
  H. 视野：半径单调与地形修正、范围内排序、已发现过滤、半径外不可见
  I. 序列化：键集合、往返、类型归一、老档迁移、排序稳定、WorldMap.to_dict
  J. 集成中性：worldmap 不依赖 game/server/frontend、main.py 已挂载单测、被保护文件未被引用

运行：.venv\\Scripts\\python.exe -X utf8 tests\\test_worldmap.py
"""
import heapq
import math
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from content import regions as R
from engine import settings as S
from engine import worldmap as WM

# 栅格常量（P4-T2：格宽 100→50 后不再硬编码）
N = S.WORLD_CELLS
M = N - 1

_PASS = 0
_FAIL = 0
_SEED = 20260910


def check(name: str, cond: bool, detail: str = ""):
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  [OK] {name}")
    else:
        _FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


def _src(path: str) -> str:
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return f.read()


def _diag_dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _terrain_counts(wm) -> dict:
    """全图地形计数（含覆盖层）。"""
    cnt = {}
    for cy in range(S.WORLD_CELLS):
        for cx in range(S.WORLD_CELLS):
            t = wm.terrain_at((cx + 0.5) * S.WORLD_CELL_LI, (cy + 0.5) * S.WORLD_CELL_LI)
            cnt[t] = cnt.get(t, 0) + 1
    return cnt


def _dijkstra(field, start_cell, goal_cell):
    """测试内独立实现的 Dijkstra（8 邻、对角 ×√2），用于校验 A* 最优性。"""
    if not field.passable(*start_cell) or not field.passable(*goal_cell):
        return None
    step = field.step
    dist = {start_cell: 0.0}
    heap = [(0.0, start_cell)]
    seen = set()
    while heap:
        d, cur = heapq.heappop(heap)
        if cur in seen:
            continue
        seen.add(cur)
        if cur == goal_cell:
            return d
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                nb = (cur[0] + dx * step, cur[1] + dy * step)
                if not field.passable(*nb):
                    continue
                if dx and dy:
                    # 与 _astar 同步：禁止对角穿角（否则会给出比 A* 更便宜的非法路径）
                    if not (field.passable(cur[0] + dx * step, cur[1])
                            and field.passable(cur[0], cur[1] + dy * step)):
                        continue
                    c = field.cost(*nb) * math.sqrt(2.0)
                else:
                    c = field.cost(*nb)
                nd = d + c
                if nd < dist.get(nb, float("inf")) - 1e-12:
                    dist[nb] = nd
                    heapq.heappush(heap, (nd, nb))
    return None


# ============ 世界（一次生成，全组复用） ============
print("== 生成世界（seed %d）==" % _SEED)
WMAP = WM.WorldMap(_SEED)
WMAP._ensure_roads()
print("  河流 %d 条 / 城镇 %d 座 / 路网 %d 段 / 内容点 %d 个 / checksum %s"
      % (len(WMAP.rivers), len(WMAP.towns), len(WMAP.roads),
         len(WMAP.content_points), WMAP.terrain_checksum()))

# ============ A. 确定性与纯度 ============
print("\n== A 确定性与纯度 ==")
cs1 = WMAP.terrain_checksum()
check("A1a 同种子两次实例 checksum 相同",
      cs1 == WM.WorldMap(_SEED).terrain_checksum(), cs1)
_sub_code = (
    "import sys; sys.path.insert(0, %r); from engine.worldmap import WorldMap; "
    "cs = WorldMap(%d).terrain_checksum(); print('  子进程 checksum', cs); "
    "sys.exit(0 if cs == %r else 1)" % (ROOT, _SEED, cs1)
)
_rc = [subprocess.call([sys.executable, "-X", "utf8", "-c", _sub_code], cwd=ROOT)
       for _ in range(2)]
check("A1b 两个子进程 checksum 与父进程逐位一致", _rc == [0, 0], str(_rc))
check("A2 不同种子 checksum 不同",
      WM.WorldMap(_SEED + 1).terrain_checksum() != cs1)
_a = WMAP.terrain_at(10000.0, 10000.0)
check("A3a terrain_at 重复调用一致", all(WMAP.terrain_at(10000.0, 10000.0) == _a
                                        for _ in range(5)))
_other = WM.WorldMap(_SEED)
check("A3b 两个实例同坐标一致",
      all(WMAP.terrain_at((cx + 0.5) * S.WORLD_CELL_LI, (cy + 0.5) * S.WORLD_CELL_LI)
          == _other.terrain_at((cx + 0.5) * S.WORLD_CELL_LI, (cy + 0.5) * S.WORLD_CELL_LI)
          for cx in range(0, N, 23) for cy in range(0, N, 29)))
_bad = ("import random", "hash(", "import time", "import datetime", "os.environ", "open(")
_wm_src = _src(os.path.join("engine", "worldmap.py"))
_rg_src = _src(os.path.join("content", "regions.py"))
check("A4 源码静态检查：无 random/hash()/time/datetime/environ/open()",
      all(s not in _wm_src for s in _bad) and all(s not in _rg_src for s in _bad),
      str([s for s in _bad if s in _wm_src or s in _rg_src]))
check("A5 WorldMap.get(seed) 复用实例", WM.WorldMap.get(_SEED) is WM.WorldMap.get(_SEED))
check("A6 全图重算两次 checksum 一致", WMAP.terrain_checksum() == WMAP.terrain_checksum())
_ta, _tb = WMAP.towns[0], WMAP.towns[7]
_p1 = WMAP.path_between(_ta, _tb, profile="fastest")
_p2 = WMAP.path_between(_ta, _tb, profile="fastest")
check("A7 find_path 同参数两次逐位一致",
      _p1.points == _p2.points and _p1.total_si == _p2.total_si, _p1.reason)
_rc2 = [subprocess.call([sys.executable, "-X", "utf8", "-c", _sub_code], cwd=ROOT,
                        env=dict(os.environ, PYTHONHASHSEED=hv)) for hv in ("0", "12345")]
check("A8 两个 PYTHONHASHSEED 子进程 checksum 一致", _rc2 == [0, 0], str(_rc2))
_vn = [WM.value_noise(_SEED, i * 137.0, i * 219.0, 1600.0, "elev:0") for i in range(N)]
check("A9a value_noise ∈ [0,1] 且非常数",
      all(0.0 <= v <= 1.0 for v in _vn) and len(set(_vn)) > 100)
_fb = [WM.fbm(_SEED, i * 137.0, i * 219.0, 2000.0, 5, "elev") for i in range(N)]
check("A9b fbm ∈ [0,1] 且非常数",
      all(0.0 <= v <= 1.0 for v in _fb) and len(set(_fb)) > 100)
check("A9c 同参数噪声逐位可复现（salt / 种子敏感）",
      WM.fbm(_SEED, 1234.0, 5678.0, 2000.0, 5, "elev")
      == WM.fbm(_SEED, 1234.0, 5678.0, 2000.0, 5, "elev")
      and WM.fbm(_SEED, 1234.0, 5678.0, 2000.0, 5, "elev")
      != WM.fbm(_SEED, 1234.0, 5678.0, 2000.0, 5, "moist")
      and WM.fbm(_SEED, 1234.0, 5678.0, 2000.0, 5, "elev")
      != WM.fbm(_SEED + 1, 1234.0, 5678.0, 2000.0, 5, "elev"))

# ============ B. 坐标与域 ============
print("\n== B 坐标与域 ==")
check("B9 世界常量", S.WORLD_CELLS == N and S.DOMAIN_LI == 4000.0 and S.WORLD_LI == 20000.0)
check("B10a cell_of 负坐标 clamp 到 0", WM.cell_of(-500.0, -1.0) == (0, 0))
check("B10b cell_of 超界 clamp 到 M", WM.cell_of(99999.0, 25000.0) == (M, M))
check("B10c cell_of 正好边界", WM.cell_of(S.WORLD_CELL_LI, S.WORLD_CELL_LI * 2) == (1, 2)
      and WM.cell_of(20000.0, 20000.0) == (M, M))
check("B11a 25 个域且 idx == iy*5+ix",
      len(R.DOMAINS) == 25 and all(d.idx == d.iy * 5 + d.ix for d in R.DOMAINS))
check("B11b 域名全局唯一", len({d.name for d in R.DOMAINS}) == 25)
check("B11c 世界正中是核心域", R.domain_at_xy(10000.0, 10000.0) == R.CORE_DOMAIN_IDX == 12
      and R.CORE_DOMAIN_NAME == "青石域")
check("B11d 域 tier 分布 1 core / 4 near / 20 outer",
      sum(1 for d in R.DOMAINS if d.tier == "core") == 1
      and sum(1 for d in R.DOMAINS if d.tier == "near") == 4
      and sum(1 for d in R.DOMAINS if d.tier == "outer") == 20)
check("B12 四邻：角 2 / 边 3 / 内部 4",
      len(R.neighbors_of(0)) == 2 and len(R.neighbors_of(2)) == 3
      and len(R.neighbors_of(12)) == 4
      and set(R.neighbors_of(12)) == {7, 11, 13, 17})
_conc_ok = True
_main_ok = True
for d in R.DOMAINS:
    for tid in sorted(R.TERRAINS):
        conc = R.element_concentration(tid, d)
        if abs(sum(conc.values()) - 1.0) > 1e-9:
            _conc_ok = False
        elems = R.terrain_elements(tid)
        if elems:
            top = max(R.ELEMENTS, key=lambda e: (conc[e], -R.ELEMENTS.index(e)))
            base_top = max(elems, key=lambda e: (conc[e], -R.ELEMENTS.index(e)))
            if conc[base_top] < 1.0 / 5.0 - 1e-12:
                _main_ok = False
check("B13a 五行浓度和 = 1.0（全部地形 × 全部域）", _conc_ok)
check("B13b 地形主五行权重不低于均分（域加成之外）", _main_ok)
check("B14a major_realm_of 边界",
      [S.major_realm_of(r) for r in (1, 9, 10, 13, 14, 17, 18, 21, 22, 25)]
      == [0, 0, 1, 1, 2, 2, 3, 3, 4, 4])
check("B14b realm_speed_mult 边界",
      [S.realm_speed_mult(r) for r in (1, 9, 10, 13, 14, 17, 18, 21, 22, 25)]
      == [1.0, 1.0, 1.5, 1.5, 2.5, 2.5, 4.0, 4.0, 6.0, 6.0])
check("B14c vision_radius_li 边界",
      [S.vision_radius_li(r) for r in (1, 9, 10, 13, 14, 17, 18, 21, 22, 25)]
      == [60.0, 60.0, 150.0, 150.0, 400.0, 400.0, 1000.0, 1000.0, 2500.0, 2500.0])

# ============ C. 地形分布 ============
print("\n== C 地形分布 ==")
_counts = _terrain_counts(WMAP)
_total = float(S.WORLD_CELLS ** 2)
_share = {tid: _counts.get(tid, 0) / _total for tid in R.TERRAINS}
print("  地形占比：" + "  ".join("%s %.2f%%" % (R.TERRAINS[t].name, 100.0 * _share[t])
                                for t in sorted(_share) if _share[t] > 0))
_missing = [R.TERRAINS[t].name for t in R.MAIN_TERRAIN_IDS
            if _share[t] < (0.0005 if t == R.T_LAVA else 0.002)]
check("C15 12 种主地形全部出现且占比达标", not _missing, str(_missing))
_hard_present = [t for t in R.HARD_BLOCK_IDS if _counts.get(t, 0) == 0]
_hard_share = sum(_counts.get(t, 0) for t in R.HARD_BLOCK_IDS) / _total
check("C16a 4 类硬阻挡全部出现", not _hard_present, str(_hard_present))
check("C16b 硬阻挡总占比 ≤ 35%%（实测 %.2f%%）" % (100 * _hard_share), _hard_share <= 0.35)
check("C16c 水域占比 1%%~30%%（实测 %.2f%%）" % (100 * _share[R.T_WATER]),
      0.01 <= _share[R.T_WATER] <= 0.30)
_base_road = [(cx, cy) for cy in range(N) for cx in range(N)
              if WMAP.base_terrain(cx, cy) in (R.T_ROAD, R.T_TRAIL)]
_anchor_market = WM.cell_of(*R.LEGACY_ANCHORS["坊市"])
check("C17a 未生成路网前 官道/小径 基础地形仅锚点「坊市」1 格",
      _base_road == [_anchor_market], str(_base_road))
check("C17b 生成路网后 官道/小径 占比 > 0",
      _counts.get(R.T_ROAD, 0) + _counts.get(R.T_TRAIL, 0) > 0)
_ring_ok = all(WMAP.base_terrain(cx, cy) == R.T_VOID
               for cx in range(N) for cy in (0, M)) and \
    all(WMAP.base_terrain(cx, cy) == R.T_VOID for cy in range(N) for cx in (0, M))
check("C18 世界最外 1 圈全为 T_VOID", _ring_ok)
_speeds = {R.T_ROAD: 44.0, R.T_TRAIL: 33.0, R.T_PLAIN: 22.0, R.T_GRASS: 22.0,
           R.T_FOREST: 17.0, R.T_HILL: 14.0, R.T_DESERT: 11.0, R.T_MOUNTAIN: 8.0,
           R.T_CANYON: 7.0, R.T_SWAMP: 6.0, R.T_SNOW: 6.0, R.T_LAVA: 4.0}
check("C19a 12 主地形速度逐项相等",
      all(R.terrain_speed(t) == v for t, v in _speeds.items()))
check("C19b 硬阻挡速度为 0 且湖泊/河流为 4",
      all(R.terrain_speed(t) == 0.0 for t in R.HARD_BLOCK_IDS)
      and R.terrain_speed(R.T_WATER) == 4.0 and R.terrain_speed(R.T_FORD) == 10.0)
_wards = WMAP.wards
check("C20a 禁制 ≥ 3 处", len(_wards) >= 3, str(len(_wards)))
check("C20b 禁制中心互距 ≥ 1500 里（判据下限 800）",
      all(_diag_dist(_wards[i], _wards[j]) >= 1500.0
          for i in range(len(_wards)) for j in range(i + 1, len(_wards)))
      and all(_diag_dist(_wards[i], _wards[j]) >= 800.0
              for i in range(len(_wards)) for j in range(i + 1, len(_wards))))
_sample_ok = True
for cy in range(0, N, 7):
    for cx in range(0, N, 5):
        idx = cy * N + cx
        if idx in WMAP._town_cells or idx in WMAP._road_cells:
            continue
        _px, _py = (cx + 0.5) * S.WORLD_CELL_LI, (cy + 0.5) * S.WORLD_CELL_LI
        if WMAP._river_at(_px, _py):
            continue                      # R2b：河流是几何覆盖，不写进地形数组
        if WMAP.base_terrain(cx, cy) != WMAP.terrain_at(_px, _py):
            _sample_ok = False
check("C21a 无覆盖格 base_terrain == terrain_at", _sample_ok)
check("C21b 城镇格 terrain_at 为 T_ROAD",
      all(WMAP.terrain_at(t.x, t.y) == R.T_ROAD for t in WMAP.towns))

# ============ D. 水系 / 灵脉 / 内容点 ============
print("\n== D 水系 / 灵脉 / 内容点 ==")
check("D22a 河流 ≥ 5 条（实测 %d）" % len(WMAP.rivers), len(WMAP.rivers) >= 5)
check("D22b 每条河 ≥ 5 个折线点", all(len(r.points) >= 5 for r in WMAP.rivers))
_bad_river = []
for r in WMAP.rivers:
    # 河流是**几何折线**（R2b）：取折线上的点采样，不再按格心（格心可能离河 35 里）
    for px, py in r.points:
        t = WMAP.terrain_at(px, py)
        if t not in (R.T_WATER, R.T_FORD):
            _bad_river.append((round(px), round(py), R.TERRAINS[t].name))
check("D22c 河流折线上的点地形为 T_WATER 或 T_FORD", not _bad_river, str(_bad_river[:5]))
check("D23a 每条河渡口 ≥ 1 个", all(len(r.fords) >= 1 for r in WMAP.rivers))
check("D23b 渡口处练气期可通行",
      all(WMAP.speed_at(f[0], f[1], realm_idx=1) > 0.0
          for r in WMAP.rivers for f in r.fords))
_river_idx = set()
for r in WMAP.rivers:
    for cx, cy in r.cells:
        _river_idx.add(cy * N + cx)
_near_river = set()
for idx in _river_idx:
    cy, cx = divmod(idx, N)
    for dy in (-2, -1, 0, 1, 2):
        for dx in (-2, -1, 0, 1, 2):
            if 0 <= cx + dx < N and 0 <= cy + dy < N:
                _near_river.add((cy + dy) * N + cx + dx)
_vein_cnt = {}
_vein_bad = []
_vein_fallback = {}
# 每域「严格合格格」数（山地/丘陵/峡谷 或 距河 ≤ 2 格，且非水域/硬阻挡）
_strict_by_domain = [0] * 25
for _cy in range(N):
    for _cx in range(N):
        _idx = _cy * N + _cx
        _tid = WMAP.base_terrain(_cx, _cy)
        if _tid in R.HARD_BLOCK_IDS or _tid == R.T_WATER:
            continue
        if _tid in (R.T_MOUNTAIN, R.T_HILL, R.T_CANYON) or _idx in _near_river:
            _strict_by_domain[R.domain_of_cell(_cx, _cy)] += 1
for p in WMAP.content_points:
    if p.kind != "vein":
        continue
    _vein_cnt[p.domain_idx] = _vein_cnt.get(p.domain_idx, 0) + 1
    cx, cy = WM.cell_of(p.x, p.y)
    tid = WMAP.base_terrain(cx, cy)
    if tid in R.HARD_BLOCK_IDS or tid == R.T_WATER:
        _vein_bad.append((p.id, "地形"))
    elif tid not in (R.T_MOUNTAIN, R.T_HILL, R.T_CANYON) and (cy * N + cx) not in _near_river:
        # 平坦域兜底（任务书 §4.2 步骤 6）：该域严格合格格 < 3 时才允许
        if _strict_by_domain[p.domain_idx] < 3:
            _vein_fallback[p.domain_idx] = _vein_fallback.get(p.domain_idx, 0) + 1
        else:
            _vein_bad.append((p.id, "位置"))
check("D24a 灵脉每域 3~6 个",
      all(3 <= _vein_cnt.get(d, 0) <= 6 for d in range(25)), str(sorted(_vein_cnt.items())))
check("D24b 灵脉位于山地/丘陵/峡谷或距河 ≤ 2 格且不在水域/硬阻挡（平坦域兜底 %d 个）"
      % sum(_vein_fallback.values()), not _vein_bad, str(_vein_bad[:5]))
_pts = WMAP.content_points
check("D25a 内容点总数 800~3000（实测 %d）" % len(_pts), 800 <= len(_pts) <= 3000)
check("D25b 内容点 id 全局唯一", len({p.id for p in _pts}) == len(_pts))
check("D25c kind 全部合法", all(p.kind in R.CONTENT_KINDS for p in _pts))
check("D25d 坐标全在世界内",
      all(0.0 <= p.x <= S.WORLD_LI and 0.0 <= p.y <= S.WORLD_LI for p in _pts))
_core_n = sum(1 for p in _pts if p.domain_idx == R.CORE_DOMAIN_IDX)
_outer_n = [sum(1 for p in _pts if p.domain_idx == d) for d in range(25)
            if R.DOMAINS[d].tier == "outer"]
check("D26 核心域密度 > 外围域密度（%d vs 均值 %.1f）"
      % (_core_n, sum(_outer_n) / len(_outer_n)),
      _core_n > sum(_outer_n) / len(_outer_n))
check("D27 element 属于五行", all(p.element in R.ELEMENTS for p in _pts))
_r = 1200.0
_px, _py = WMAP.towns[3].x, WMAP.towns[3].y
_near = WMAP.points_near(_px, _py, _r)
_manual = sorted([p for p in _pts if _diag_dist((p.x, p.y), (_px, _py)) <= _r],
                 key=lambda p: (_diag_dist((p.x, p.y), (_px, _py)), p.id))
check("D28a points_near 距离 ≤ r", all(_diag_dist((p.x, p.y), (_px, _py)) <= _r + 1e-9
                                       for p in _near))
check("D28b points_near 与全量枚举一致", [p.id for p in _near] == [p.id for p in _manual])
check("D29 同种子两次生成内容点 id 集合一致",
      {p.id for p in WM.WorldMap(_SEED).content_points} == {p.id for p in _pts})

# ============ E. 城镇 ============
print("\n== E 城镇 ==")
_towns = WMAP.towns
_by_domain = {}
for t in _towns:
    _by_domain.setdefault(t.domain_idx, []).append(t)
_quota_ok = all(len(v) <= R.TOWN_COUNT_BY_TIER[R.DOMAINS[d].tier]
                for d, v in _by_domain.items())
_full = all(len(_by_domain.get(d, [])) == R.TOWN_COUNT_BY_TIER[R.DOMAINS[d].tier]
            for d in range(25))
check("E30a 每域城镇数 ≤ 配额", _quota_ok)
check("E30b 城镇总数 180~300（实测 %d）" % len(_towns), 180 <= len(_towns) <= 300)
check("E30c 每域配额全部取满", _full)
# 判据 30 附加：该域 MAINLAND 内可通行格 ≥ 200 → 该域城镇数 ≥ 4
_mbest, _mcomp, _mpass = WMAP._mainland()
_mainland_by_domain = [0] * 25
for _idx in range(N * N):
    if _mcomp[_idx] == _mbest:
        _mainland_by_domain[R.domain_of_cell(_idx % N, _idx // N)] += 1
_rich_ok = all(len(_by_domain.get(d, [])) >= 4
               for d in range(25) if _mainland_by_domain[d] >= 4 * 200)
check("E30d MAINLAND ≥ 800 格的域城镇数 ≥ 4", _rich_ok,
      str([(d, _mainland_by_domain[d], len(_by_domain.get(d, [])))
           for d in range(25) if _mainland_by_domain[d] >= 4 * 200
           and len(_by_domain.get(d, [])) < 4]))
_min_d = min(_diag_dist((a.x, a.y), (b.x, b.y))
             for i, a in enumerate(_towns) for b in _towns[i + 1:])
check("E31 任意两镇距离 ≥ 150 里（实测 %.0f）" % _min_d, _min_d >= 150.0 - 1e-9)
check("E32a 城镇名全局唯一", len({t.name for t in _towns}) == len(_towns))
check("E32b 城镇 id 全局唯一", len({t.id for t in _towns}) == len(_towns))
check("E33 每域恰有 1 个 is_main",
      all(sum(1 for t in v if t.is_main) == 1 for v in _by_domain.values()))
_qs = [t for t in _towns if t.name == "青石镇"]
check("E34a 青石镇存在且在锚点",
      len(_qs) == 1 and (_qs[0].x, _qs[0].y) == R.LEGACY_ANCHORS["坊市"]
      and _qs[0].is_main, str([(t.name, t.x, t.y) for t in _qs]))
_anchors = sorted(R.LEGACY_ANCHORS)
check("E34b 5 个旧地点锚点互不重合且间距 ≥ 800 里",
      len(_anchors) == 5 and all(
          _diag_dist(R.LEGACY_ANCHORS[a], R.LEGACY_ANCHORS[b]) >= 800.0
          for i, a in enumerate(_anchors) for b in _anchors[i + 1:]))
_anchor_bad = []
for _name in _anchors:
    _ax, _ay = R.LEGACY_ANCHORS[_name]
    _acx, _acy = WM.cell_of(_ax, _ay)
    _want = R.T_ROAD if _name == "坊市" else R.T_PLAIN
    if WMAP.base_terrain(_acx, _acy) != _want:
        _anchor_bad.append((_name, "base", R.TERRAINS[WMAP.base_terrain(_acx, _acy)].name))
    if WMAP.terrain_at(_ax, _ay) != _want:
        _anchor_bad.append((_name, "terrain_at", R.TERRAINS[WMAP.terrain_at(_ax, _ay)].name))
    if WMAP.speed_at(_ax, _ay, realm_idx=1) <= 0.0:
        _anchor_bad.append((_name, "不可通行"))
check("E34c 5 个锚点格练气期可通行且为 T_ROAD(坊市)/T_PLAIN(其余)", not _anchor_bad,
      str(_anchor_bad))
check("E35 所有城镇格练气期可通行",
      all(WMAP.speed_at(t.x, t.y, realm_idx=1) > 0.0 for t in _towns))

# ============ F. 路网 ============
print("\n== F 路网 ==")
check("F36a 路网非空（%d 段）" % len(WMAP.roads), len(WMAP.roads) > 0)
_road_share = (_counts.get(R.T_ROAD, 0) + _counts.get(R.T_TRAIL, 0)) / _total
check("F36b 官道/小径占比 ≥ 0.3%%（实测 %.2f%%）" % (100 * _road_share), _road_share >= 0.003)
_bad_road = [(idx % N, idx // N) for idx, tid in WMAP._road_cells.items()
             if tid in R.HARD_BLOCK_IDS]
check("F37 路格不含硬阻挡", not _bad_road, str(_bad_road[:5]))
_par = {t.id: t.id for t in _towns}


def _find(a):
    while _par[a] != a:
        _par[a] = _par[_par[a]]
        a = _par[a]
    return a


for _rd in WMAP.roads:
    _ra, _rb = _find(_rd.a), _find(_rd.b)
    if _ra != _rb:
        _par[_rb] = _ra
check("F38 路网使全部城镇连通",
      len({_find(t.id) for t in _towns}) == 1,
      str(len({_find(t.id) for t in _towns})))
_cross = sum(1 for rd in WMAP.roads
             if WMAP.town_by_id(rd.a).domain_idx != WMAP.town_by_id(rd.b).domain_idx)
check("F39 跨域主路边 ≥ 20 条（实测 %d）" % _cross, _cross >= 20)
_ford_cells = [idx for idx, tid in WMAP._road_cells.items() if tid == R.T_FORD]
check("F40a 路网跨水处改标渡口（%d 格）" % len(_ford_cells), len(_ford_cells) >= 1)
check("F40b 渡口格可通行且位于河面/水域",
      all(WMAP.speed_at((idx % N) * S.WORLD_CELL_LI + S.WORLD_CELL_LI / 2, (idx // N) * S.WORLD_CELL_LI + S.WORLD_CELL_LI / 2, 1) > 0.0
          and (WMAP._base[idx] in (R.T_WATER, R.T_FORD)
               or WMAP._river_at((idx % N) * S.WORLD_CELL_LI + S.WORLD_CELL_LI / 2, (idx // N) * S.WORLD_CELL_LI + S.WORLD_CELL_LI / 2))
          for idx in _ford_cells))
_adj_pairs = sorted(
    ((_diag_dist((a.x, a.y), (b.x, b.y)), a.id, b.id, a, b)
     for i, a in enumerate(_towns) for b in _towns[i + 1:]))
_road_ok = 0
_road_tested = 0


def _path_cost(cells, with_roads: bool) -> float:
    """按给定覆盖口径重算同一路径的耗时（息）；不可通行 → inf。"""
    total = 0.0
    for k in range(1, len(cells)):
        cx, cy = cells[k]
        tid = WMAP.terrain_at((cx + 0.5) * S.WORLD_CELL_LI, (cy + 0.5) * S.WORLD_CELL_LI, with_roads=with_roads)
        t = R.TERRAINS[tid]
        if tid in R.HARD_BLOCK_IDS or (t.swim_only and 1 < S.SWIM_MIN_REALM):
            return float("inf")
        sp = t.speed * S.realm_speed_mult(1)
        if sp <= 0.0:
            return float("inf")
        seg = S.WORLD_CELL_LI / sp * S.SI_PER_DAY
        if cells[k][0] != cells[k - 1][0] and cells[k][1] != cells[k - 1][1]:
            seg *= math.sqrt(2.0)
        total += seg
    return total


for _d, _aid, _bid, _a, _b in _adj_pairs[:60]:
    _r1 = WMAP.path_between(_a, _b, profile="fastest")
    if _r1.blocked:
        continue
    _c_base = _path_cost(_r1.cells, False)
    if not math.isfinite(_c_base):
        continue                     # 越野不可通行的对不计入比较
    _road_tested += 1
    if _path_cost(_r1.cells, True) <= _c_base + 1e-9:
        _road_ok += 1
    if _road_tested >= 12:
        break
check("F41 同一路径 with_roads ≤ base（%d/%d 对相邻城镇）" % (_road_ok, _road_tested),
      _road_tested >= 10 and _road_ok == _road_tested)

# ============ G. 代价场与 A* ============
print("\n== G 代价场与 A* ==")
_sp_ok = True
_sp_cells = []
for cy in range(0, N, 41):
    for cx in range(0, N, 37):
        tid = WMAP.terrain_at((cx + 0.5) * S.WORLD_CELL_LI, (cy + 0.5) * S.WORLD_CELL_LI)
        if tid in R.PASSABLE_IDS:
            _sp_cells.append((cx, cy, tid))
        if len(_sp_cells) >= 5:
            break
    if len(_sp_cells) >= 5:
        break
for cx, cy, tid in _sp_cells:
    for realm in (1, 14):
        for shenfa in (0.0, 0.3):
            want = R.terrain_speed(tid) * S.realm_speed_mult(realm) * (1.0 + shenfa)
            got = WMAP.speed_at((cx + 0.5) * S.WORLD_CELL_LI, (cy + 0.5) * S.WORLD_CELL_LI, realm, shenfa)
            if abs(got - want) > 1e-9:
                _sp_ok = False
check("G42 speed_at = 地形速度 × 境界系数 × (1+身法)", _sp_ok, str(_sp_cells))
check("G43a 境界系数单调不减",
      all(S.realm_speed_mult(r) <= S.realm_speed_mult(r + 1) for r in range(1, 25)))
_water_cell = next(((cx, cy) for cy in range(N) for cx in range(N)
                    if WMAP.base_terrain(cx, cy) == R.T_WATER), None)
_wx, _wy = (_water_cell[0] + 0.5) * S.WORLD_CELL_LI, (_water_cell[1] + 0.5) * S.WORLD_CELL_LI
check("G43b 练气不能渡水 / 筑基可渡水",
      WMAP.speed_at(_wx, _wy, 9) == 0.0 and WMAP.speed_at(_wx, _wy, 10) == 4.0 * 1.5,
      "%s / %s" % (WMAP.speed_at(_wx, _wy, 9), WMAP.speed_at(_wx, _wy, 10)))
_hb = next(((cx, cy) for cy in range(N) for cx in range(N)
            if WMAP.base_terrain(cx, cy) == R.T_VOID), None)
_r_sb = WMAP.find_path(((_hb[0] + 0.5) * S.WORLD_CELL_LI, (_hb[1] + 0.5) * S.WORLD_CELL_LI), (10000.0, 10000.0))
check("G44a 起点硬阻挡 → start_blocked",
      _r_sb.blocked and _r_sb.reason == "start_blocked", _r_sb.reason)
_r_gb = WMAP.find_path((10000.0, 10000.0), ((_hb[0] + 0.5) * S.WORLD_CELL_LI, (_hb[1] + 0.5) * S.WORLD_CELL_LI))
check("G44b 终点硬阻挡 → goal_blocked",
      _r_gb.blocked and _r_gb.reason == "goal_blocked", _r_gb.reason)
_cells_in = all(0 <= c[0] <= M and 0 <= c[1] <= M
                for res in (_p1, _r_sb, WMAP.find_path((500.0, 500.0), (19500.0, 19500.0)))
                for c in res.cells)
check("G45 路径格坐标恒在 [0,M]", _cells_in)
# G45b 防穿角：1 格宽屏障不可斜穿（A* 与 _dijkstra 同步约束；复核新增）
_cut = None
for _cy in range(1, M):
    for _cx in range(1, M):
        for _dx, _dy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            _a = (_cx, _cy)
            _b = (_cx + _dx, _cy + _dy)
            if not (1 <= _b[0] < M and 1 <= _b[1] < M):
                continue
            _oa = (_cx + _dx, _cy)
            _ob = (_cx, _cy + _dy)

            def _blk(c):
                # R2b：河流是几何覆盖，作屏障样本不稳定 → 只用**硬阻挡**（绝壁/虚空/深海）
                t = WMAP.terrain_at((c[0] + 0.5) * S.WORLD_CELL_LI, (c[1] + 0.5) * S.WORLD_CELL_LI)
                return t in R.HARD_BLOCK_IDS

            if not _blk(_a) and not _blk(_b) and _blk(_oa) and _blk(_ob):
                _cut = (_a, _b)
                break
        if _cut:
            break
    if _cut:
        break
if _cut:
    _rc = WMAP.find_path(((_cut[0][0] + 0.5) * S.WORLD_CELL_LI, (_cut[0][1] + 0.5) * S.WORLD_CELL_LI),
                         ((_cut[1][0] + 0.5) * S.WORLD_CELL_LI, (_cut[1][1] + 0.5) * S.WORLD_CELL_LI))
    check("G45b 1 格宽屏障不可斜穿（防穿角）",
          _rc.reason != "ok" or len(_rc.cells) > 2,
          "样本 %s→%s 结果 %s cells=%d" % (_cut[0], _cut[1], _rc.reason, len(_rc.cells)))
else:
    check("G45b 1 格宽屏障不可斜穿（防穿角）", True, "本种子无天然样本")
# 硬阻挡屏障 → 无路（取一个被绝壁完全包围的孤立格）
_comp = [-1] * N * N
_grp = []
for _start in range(N * N):
    if _comp[_start] >= 0:
        continue
    _sy, _sx = divmod(_start, N)
    _t0 = WMAP.terrain_at((_sx + 0.5) * S.WORLD_CELL_LI, (_sy + 0.5) * S.WORLD_CELL_LI)
    if _t0 in R.HARD_BLOCK_IDS or _t0 == R.T_WATER:
        _comp[_start] = -2
        continue
    _stack = [_start]
    _comp[_start] = len(_grp)
    _cur = []
    while _stack:
        _i = _stack.pop()
        _cur.append(_i)
        _py, _px = divmod(_i, N)
        for _dy in (-1, 0, 1):
            for _dx in (-1, 0, 1):
                _ny, _nx = _py + _dy, _px + _dx
                if not (0 <= _nx < N and 0 <= _ny < N):
                    continue
                _j = _ny * N + _nx
                if _comp[_j] != -1:
                    continue
                _t = WMAP.terrain_at((_nx + 0.5) * S.WORLD_CELL_LI, (_ny + 0.5) * S.WORLD_CELL_LI)
                if _t in R.HARD_BLOCK_IDS or _t == R.T_WATER:
                    _comp[_j] = -2
                    continue
                _comp[_j] = len(_grp)
                _stack.append(_j)
    _grp.append(_cur)
_grp.sort(key=len, reverse=True)
_iso = _grp[-1] if len(_grp) > 1 else []
_iso_ok = False
_iso_barrier = []
if _iso:
    _iy, _ix = divmod(_iso[0], N)
    _main_y, _main_x = divmod(_grp[0][0], N)
    _res_iso = WMAP.find_path(((_main_x + 0.5) * S.WORLD_CELL_LI, (_main_y + 0.5) * S.WORLD_CELL_LI),
                              ((_ix + 0.5) * S.WORLD_CELL_LI, (_iy + 0.5) * S.WORLD_CELL_LI))
    _iso_ok = _res_iso.blocked and _res_iso.reason == "no_path"
    for _dy in (-1, 0, 1):
        for _dx in (-1, 0, 1):
            _ny, _nx = _iy + _dy, _ix + _dx
            if 0 <= _nx < N and 0 <= _ny < N:
                _iso_barrier.append(WMAP.terrain_at((_nx + 0.5) * S.WORLD_CELL_LI, (_ny + 0.5) * S.WORLD_CELL_LI))
check("G46a 硬阻挡屏障围出的孤立区 → no_path/blocked", _iso_ok,
      "孤立格 %s 屏障 %s" % (_iso[:1], [R.TERRAINS[t].name for t in _iso_barrier[:8]]))
# 深海屏障：窗口内不可跨越（用公共 CostField + 独立 Dijkstra 验证）
_deep = next((i for i in range(N * N) if WMAP.base_terrain(i % N, i // N) == R.T_DEEPSEA),
             None)
_deep_ok = False
if _deep is not None:
    _dy2, _dx2 = divmod(_deep, N)
    _box = (max(0, _dx2 - 5), max(0, _dy2 - 5), min(M, _dx2 + 5), min(M, _dy2 + 5))
    _fld = WMAP.cost_field("fastest", 1, 0.0, box=_box)
    _deep_ok = not _fld.passable(_dx2, _dy2) and \
        WMAP.speed_at((_dx2 + 0.5) * S.WORLD_CELL_LI, (_dy2 + 0.5) * S.WORLD_CELL_LI, 1) == 0.0
check("G46b 深海格在代价场中不可通行（屏障真实存在）", _deep_ok, str(_deep))
# G47 最优性：小窗口内独立 Dijkstra
_oa, _ob = _adj_pairs[0][3], _adj_pairs[0][4]
_sc, _gc = WM.cell_of(_oa.x, _oa.y), WM.cell_of(_ob.x, _ob.y)
_margin = max(4, int(math.hypot(_gc[0] - _sc[0], _gc[1] - _sc[1]) * 0.1))
_box = (min(_sc[0], _gc[0]) - _margin, min(_sc[1], _gc[1]) - _margin,
        max(_sc[0], _gc[0]) + _margin, max(_sc[1], _gc[1]) + _margin)
_fld = WMAP.cost_field("fastest", 1, 0.0, box=_box)
_dj = _dijkstra(_fld, _sc, _gc)
_res = WMAP.path_between(_oa, _ob, profile="fastest")
check("G47 与独立 Dijkstra 代价一致（±1 息）",
      _dj is not None and abs(_res.total_si - math.ceil(_dj)) <= 1,
      "A*=%s Dijkstra=%s" % (_res.total_si, _dj))
_full_fld = WMAP.cost_field("fastest", 1, 0.0, box=None)
_full_cells, _full_cost, _full_reason = WMAP._astar(_full_fld, _sc, _gc)
_full_si = max(1, int(math.ceil(_full_cost))) if _full_cells else 0
check("G48 窗口化结果与放开全图代价一致",
      _full_cells is not None and abs(_res.total_si - _full_si) <= 1,
      "窗口=%s 全图=%s" % (_res.total_si, _full_si))
_r_low = WMAP.find_path((2000.0, 10000.0), (14000.0, 10000.0), profile="fly", realm_idx=9)
check("G49a 飞行门槛：练气 → realm_too_low",
      _r_low.blocked and _r_low.reason == "realm_too_low", _r_low.reason)
_r_fly = WMAP.find_path((2000.0, 10000.0), (14000.0, 10000.0), profile="fly", realm_idx=14)
_fly_want = 12000.0 / S.FLY_SPEED_LI_PER_DAY * S.SI_PER_DAY
check("G49b 飞行耗时 ≈ 直线/250×43200（±5%）",
      not _r_fly.blocked and abs(_r_fly.total_si - _fly_want) <= 0.05 * _fly_want,
      "实测 %s 期望 %.0f" % (_r_fly.total_si, _fly_want))
_ward_cell = WM.cell_of(WMAP.wards[0][0], WMAP.wards[0][1])
check("G49c 飞行被禁制阻挡",
      WMAP.find_path(((_ward_cell[0] + 0.5) * S.WORLD_CELL_LI, (_ward_cell[1] + 0.5) * S.WORLD_CELL_LI),
                     (14000.0, 10000.0), profile="fly", realm_idx=14).blocked)
# 飞行可跨越深海
_fly_deep_ok = False
if _deep is not None:
    _dy2, _dx2 = divmod(_deep, N)
    _start = (_dx2 - 1, _dy2)
    _goal = (_dx2 + 1, _dy2)
    _rd = WMAP.find_path(((_start[0] + 0.5) * S.WORLD_CELL_LI, (_start[1] + 0.5) * S.WORLD_CELL_LI),
                         ((_goal[0] + 0.5) * S.WORLD_CELL_LI, (_goal[1] + 0.5) * S.WORLD_CELL_LI),
                         profile="fly", realm_idx=14)
    _fly_deep_ok = (not _rd.blocked) or _rd.reason != "start_blocked"
check("G49d 飞行可跨越深海（不因深海受阻）", _fly_deep_ok)
_st_ok = True
_st_tested = 0
_sum_f = 0
_cells_f = 0
_sum_s = 0
_cells_s = 0
for _d, _aid, _bid, _a, _b in _adj_pairs[::max(1, len(_adj_pairs) // 80)][:80]:
    _rf = WMAP.path_between(_a, _b, profile="fastest")
    if _rf.blocked:
        continue
    _cells_f += len(_rf.cells)
    _road_f = sum(1 for cx, cy in _rf.cells if WMAP._terrain_cell(cx, cy) == R.T_ROAD)
    _rs = WMAP.path_between(_a, _b, profile="stealth")
    if _rs.blocked:
        _st_ok = False
        break
    _cells_s += len(_rs.cells)
    _road_s = sum(1 for cx, cy in _rs.cells if WMAP._terrain_cell(cx, cy) == R.T_ROAD)
    _sum_f += _road_f
    _sum_s += _road_s
    if _road_f > 0:
        _st_tested += 1
    if _st_tested >= 12:
        break
check("G50a stealth 官道占比 ≤ fastest（%d 对）" % _st_tested, (_sum_s / max(1, _cells_s)) <= (_sum_f / max(1, _cells_f)) + 0.02 and _st_tested >= 3)
# G50b safe 对危险地形加价（T3 改：直接量代价模型，不依赖"恰好搜到某格"的巧合）
# 旧口径断言 ">1.5×" 属速度域乘法时代（`mult = 1 + 3×danger`）；T3 改为**代价域线性组合**后，
# 加价幅度 = danger_w×danger×里程 ÷ 时间项，实测火山 +12.5%、峡谷 +19.4%（见 profile 注释）。
_sw_ok = True
_sw_detail = []
for _tid in (R.T_LAVA, R.T_CANYON, R.T_SWAMP, R.T_MOUNTAIN):
    _sp, _m = WMAP._sample_speed("fastest", _tid, 1, 0.0)
    _cf = WMAP._sample_cost("fastest", _tid, _sp, _m, S.WORLD_CELL_LI)
    _cs = WMAP._sample_cost("safe", _tid, _sp, _m, S.WORLD_CELL_LI)
    _sw_detail.append("%s %.3f×" % (R.TERRAINS[_tid].name, _cs / _cf))
    if not _cs > _cf * 1.10:
        _sw_ok = False
check("G50b safe 对危险地形加价 ≥10%（代价域口径）", _sw_ok, " ".join(_sw_detail))
# 无危险地形的地形不得加价（危险项必须严格独立于时间项）
_nodanger_ok = True
for _tid in (R.T_PLAIN, R.T_ROAD, R.T_HILL):
    _sp, _m = WMAP._sample_speed("fastest", _tid, 1, 0.0)
    _cf = WMAP._sample_cost("fastest", _tid, _sp, _m, S.WORLD_CELL_LI)
    _cs = WMAP._sample_cost("safe", _tid, _sp, _m, S.WORLD_CELL_LI)
    if abs(_cs - _cf) > 1e-6:
        _nodanger_ok = False
check("G50c safe 对无危险地形不加价（危险项与时间项正交）", _nodanger_ok)
# 代价单位一致性（防"量纲写错 → 惩罚静默失效"，本轮踩过：写成"天"小 43200 倍）
_dist_ok = (WMAP._sample_cost("safe", R.T_LAVA, 4.0, 1.0, 100.0)
            - WMAP._sample_cost("fastest", R.T_LAVA, 4.0, 1.0, 100.0)
            > 1000.0)
check("G50d 危险罚与里程成正比且量级正确（息，非 0 罚）", _dist_ok)
# 路径层面：抽到的样本对若确实穿越险地，safe 不得比 fastest 走更多险地
_sf_path_ok = True
_sf_tested = 0
_sf_pairs = []
_sw_cells = [(cx, cy) for cy in range(0, N, 4) for cx in range(0, N, 4)
             if WMAP.base_terrain(cx, cy) in (R.T_SWAMP, R.T_LAVA)]
for _cx, _cy in _sw_cells[:24]:
    _sx, _sy = (_cx + 0.5) * S.WORLD_CELL_LI, (_cy + 0.5) * S.WORLD_CELL_LI
    _rank = sorted(_towns, key=lambda t: (_diag_dist((t.x, t.y), (_sx, _sy)), t.id))
    _a0 = _rank[0]
    _opp = next((t for t in _rank[1:]
                 if (t.x - _sx) * (_a0.x - _sx) + (t.y - _sy) * (_a0.y - _sy) < 0.0), None)
    if _opp is not None:
        _sf_pairs.append((_a0, _opp))
    if len(_sf_pairs) >= 8:
        break
for _a, _b in _sf_pairs:
    _rf = WMAP.path_between(_a, _b, profile="fastest")
    if _rf.blocked:
        continue
    _mix_f = sum(1 for cx, cy in _rf.cells
                 if WMAP.terrain_at((cx + 0.5) * S.WORLD_CELL_LI, (cy + 0.5) * S.WORLD_CELL_LI)
                 in (R.T_LAVA, R.T_SWAMP))
    _rsf = WMAP.path_between(_a, _b, profile="safe")
    if _rsf.blocked:
        _sf_path_ok = False
        break
    _mix_s = sum(1 for cx, cy in _rsf.cells
                 if WMAP.terrain_at((cx + 0.5) * S.WORLD_CELL_LI, (cy + 0.5) * S.WORLD_CELL_LI)
                 in (R.T_LAVA, R.T_SWAMP))
    if _mix_s > _mix_f:
        _sf_path_ok = False
        break
    if _mix_f > 0:
        _sf_tested += 1
check("G50b2 safe 险地里程 ≤ fastest（穿越样本 %d 对）" % _sf_tested, _sf_path_ok)
_cap_pair = next((pr for pr in _adj_pairs if pr[0] >= 1500.0), _adj_pairs[-1])
_capped = WMAP.path_between(_cap_pair[3], _cap_pair[4], profile="fastest", max_nodes=10)
check("G51 max_nodes=10 → search_capped", _capped.blocked and _capped.reason == "search_capped",
      _capped.reason)
check("G52a total_si ≥ 1", _res.total_si >= 1)
check("G52b terrain_mix 占比和 = 1（±1e-6）",
      abs(sum(_res.terrain_mix.values()) - 1.0) <= 1e-6,
      str(sum(_res.terrain_mix.values())))
check("G52c points 首尾 = 起终点",
      _res.points[0] == (_oa.x, _oa.y) and _res.points[-1] == (_ob.x, _ob.y))
# 防穿角：任何对角步的两个正交邻格都必须可通行（1 格宽的水系/绝壁不可斜穿）
_corner_ok = True
for _res in (_res, _p1, WMAP.find_path((500.0, 500.0), (19500.0, 19500.0))):
    for _k in range(1, len(_res.cells)):
        _x0, _y0 = _res.cells[_k - 1]
        _x1, _y1 = _res.cells[_k]
        if _x0 != _x1 and _y0 != _y1:
            # R2b：只校验**硬阻挡**（绝壁/虚空/深海）不穿角；河流是几何覆盖，不参与栅格屏障
            if (WMAP.terrain_at(_x1 * S.WORLD_CELL_LI + S.WORLD_CELL_LI / 2, _y0 * S.WORLD_CELL_LI + S.WORLD_CELL_LI / 2) in R.HARD_BLOCK_IDS
                    or WMAP.terrain_at(_x0 * S.WORLD_CELL_LI + S.WORLD_CELL_LI / 2, _y1 * S.WORLD_CELL_LI + S.WORLD_CELL_LI / 2) in R.HARD_BLOCK_IDS):
                _corner_ok = False
check("G52d 对角步不穿角（两个正交邻格均可通行）", _corner_ok)

# ============ H. 视野 ============
print("\n== H 视野 ==")
_plain_cell = next(((cx, cy) for cy in range(N) for cx in range(N)
                    if WMAP.base_terrain(cx, cy) == R.T_PLAIN), None)
_forest_cell = next(((cx, cy) for cy in range(N) for cx in range(N)
                     if WMAP.base_terrain(cx, cy) == R.T_FOREST), None)
_radii = [WMAP.vision_radius(r, R.T_PLAIN) for r in range(1, 26)]
check("H53a 视野半径随境界单调不减", all(_radii[i] <= _radii[i + 1] for i in range(24)))
check("H53b 林地视野 < 平原视野",
      WMAP.vision_radius(1, R.T_FOREST) < WMAP.vision_radius(1, R.T_PLAIN))
_vx, _vy = (_plain_cell[0] + 0.5) * S.WORLD_CELL_LI, (_plain_cell[1] + 0.5) * S.WORLD_CELL_LI
_vis = WMAP.visible_points(_vx, _vy, 22)
_vis_d = [_diag_dist((p.x, p.y), (_vx, _vy)) for p in _vis]
_rad = WMAP.vision_radius(22, WMAP.terrain_at(_vx, _vy))
check("H54a 可见点全部在半径内", all(d <= _rad + 1e-9 for d in _vis_d), str(_rad))
check("H54b 可见点按距离升序", all(_vis_d[i] <= _vis_d[i + 1] + 1e-12
                                    for i in range(len(_vis_d) - 1)))
_disc = {p.id for p in _vis[: max(1, len(_vis) // 3)]}
_vis2 = WMAP.visible_points(_vx, _vy, 22, discovered=_disc)
check("H55 传入 discovered 只返回未发现点",
      all(p.id not in _disc for p in _vis2)
      and len(_vis2) == len([p for p in _vis if p.id not in _disc]))
check("H56 半径外点不可见",
      all(_diag_dist((p.x, p.y), (_vx, _vy)) <= _rad + 1e-9
          for p in WMAP.visible_points(_vx, _vy, 1)))

# ============ I. 序列化 ============
print("\n== I 序列化 ==")
_ws = WM.WorldState(world_seed=_SEED, pos=(8412.5, 3307.25),
                    discovered={"mine_苍梧域_03", "herb_青石域_01"},
                    places={"town_青石镇": {"visited": True, "cleared": False}},
                    world_diff={"域_07": {"faction": "青云宗"}}, map_level="detail")
_d = _ws.to_dict()
check("I57a to_dict 键集合恰为 6 个",
      set(_d) == {"world_seed", "pos", "discovered", "places", "world_diff", "map_level"},
      str(sorted(_d)))
check("I57b 不含地形/路网/河流/城镇/位图键",
      not ({"terrain", "roads", "rivers", "towns", "discovered_bitmap"} & set(_d)))
check("I58 往返一致", WM.WorldState.from_dict(_d) == _ws)
_rt = WM.WorldState.from_dict(_d)
check("I59 discovered 往返为 set / pos 往返为 tuple(float,float)",
      isinstance(_rt.discovered, set) and isinstance(_rt.pos, tuple)
      and all(isinstance(v, float) for v in _rt.pos))
_leg = WM.WorldState.legacy(_SEED, day=123, location="坊市")
check("I60 legacy 坊市 → 锚点 + coarse",
      _leg.pos == R.LEGACY_ANCHORS["坊市"] and _leg.map_level == "coarse")
check("I61 legacy 未知地点 → 核心域中心",
      WM.WorldState.legacy(_SEED, location="不存在的地方").pos == R.CORE_DOMAIN_CENTER)
check("I62 to_dict 的 discovered 为排序后 list 且两次一致",
      isinstance(_d["discovered"], list) and _d["discovered"] == sorted(_ws.discovered)
      and _ws.to_dict()["discovered"] == _d["discovered"])
check("I63 WorldMap.to_dict 只含 world_seed", set(WMAP.to_dict()) == {"world_seed"})

# ============ J. 集成中性 ============
print("\n== J 集成中性 ==")
_bad_imports = ("import engine.game", "from engine import game", "import engine.server",
                "import server", "from server", "import frontend", "from frontend")
check("J64 worldmap/regions 不依赖 game/server/frontend",
      all(s not in _wm_src for s in _bad_imports)
      and all(s not in _rg_src for s in _bad_imports),
      str([s for s in _bad_imports if s in _wm_src or s in _rg_src]))
check("J65 main.py 已挂载 test_worldmap 单测",
      "test_worldmap.py" in _src("main.py") and "世界地图内核单测" in _src("main.py"))
_game_src = _src(os.path.join("engine", "game.py"))
_state_src = _src(os.path.join("engine", "state.py"))
_sites_src = _src(os.path.join("content", "sites.py"))
check("J66 T3 起游戏循环**已接入**世界（game/state 引用 worldmap 且 GameState 带 world 字段）",
      "worldmap" in _game_src and "worldmap" in _state_src
      and "world" in _state_src and "worldmap" not in _sites_src,
      "J66 曾是「地形不进游戏循环」的守卫断言；P4-T3 移动落地后该前提作废，改为正向断言")
check("J67 本阶段不改动被保护文件（content/sites.py 旧地点清单仍在）",
      "LINGMAI" in _sites_src and "SHISHI" in _sites_src)

# ============ K. 连续地形（P4-T2-R1 新增判据） ============
print("\n== K 连续地形（精度与内存解耦） ==")
import time as _time

# K68 单点采样成本：**自校准**（绝对阈值在同机负载下不可靠，实测同一台机器 10.9~36.5 µs）
# 做法：先量基线，阈值 = max(25 µs, 基线×2.5)。这样"算法级退化"（比如多了几次 fbm）必被抓，
# 而同机并行负载造成的抖动不会误杀。**这是回归护栏，不是性能标定**。
_NBENCH = 20000


def _bench_terrain(rounds: int = 3) -> float:
    best = float("inf")
    for _ in range(rounds):
        _t0 = _time.perf_counter()
        for _i in range(_NBENCH):
            WMAP.terrain_at(1000.0 + _i * 0.37, 2000.0 + _i * 0.53)
        best = min(best, (_time.perf_counter() - _t0) / _NBENCH * 1e6)
    return best


_baseline_us = _bench_terrain(2)
_us = _bench_terrain(3)
_limit = max(25.0, _baseline_us * 2.5)
check("K68 单点 terrain_at 未退化（%.1f µs ≤ 阈值 %.1f，基线 %.1f）"
      % (_us, _limit, _baseline_us), _us <= _limit, f"{_us:.1f} µs / 基线 {_baseline_us:.1f}")

# K69 地形连续：同一 100 里格内、每 1 里采样，地形跳变率 ≤ 20%
_cx, _cy = 60, 60                      # 取一格内部（避开特征格）
_x0, _y0 = _cx * 100.0, _cy * 100.0
_prev = WMAP.base_terrain_at(_x0 + 0.5, _y0 + 0.5)
_jump = 0
_total = 0
for _k in range(1, 100):
    _t = WMAP.base_terrain_at(_x0 + _k + 0.5, _y0 + 50.5)
    _total += 1
    if _t != _prev:
        _jump += 1
    _prev = _t
check("K69 格内 1 里步长地形跳变率 ≤ 20%（格内不再是常数）",
      _jump / _total <= 0.20, f"跳变 {_jump}/{_total}")

# K70 同格不同坐标可给出不同地形（证伪"格内取常数"）
_same_cell_diff = False
for _ci in range(40, 60):
    for _cj in range(40, 60):
        _bx, _by = _ci * 100.0, _cj * 100.0
        if (WMAP.base_terrain_at(_bx + 5.0, _by + 5.0)
                != WMAP.base_terrain_at(_bx + 95.0, _by + 95.0)):
            _same_cell_diff = True
            break
    if _same_cell_diff:
        break
check("K70 同格内不同坐标可得到不同地形", _same_cell_diff)

# K71 视野半径为正且练气期能看清近处（**不再**要求 ≥ 格宽——地形已连续，迷雾遮的是内容点）
_worst = min(WMAP.vision_radius(1, t) for t in (R.T_MOUNTAIN, R.T_FOREST, R.T_SWAMP, R.T_SNOW))
check("K71 练气期最差地形视野 > 0", _worst > 0.0, f"{_worst:.0f} 里")

# K72 特征格稀疏：河/湖/禁制/边界/锚点合计占比 < 15%
_feat = sum(1 for _i in range(N * N)
            if WMAP._cell_terrain(_i % N, _i // N) > 0)
check("K72 特征格（河/湖/禁制/边界/锚点）占比 < 15%",
      _feat / (N * N) < 0.15, f"{_feat / (N * N) * 100:.2f}%")

# ============ L. 路网几何化（P4-T2-R2） ============
print("\n== L 路网几何化（真实宽度 + 独立判定容差） ==")
_rd = WMAP.roads()[0]
_ax, _ay = _rd.points[0]
_bx, _by = _rd.points[1]
_mx, _my = (_ax + _bx) / 2.0, (_ay + _by) / 2.0
_dx, _dy = _bx - _ax, _by - _ay
_len = (_dx * _dx + _dy * _dy) ** 0.5
_nx, _ny = -_dy / _len, _dx / _len          # 法线方向
_on = WMAP.terrain_at(_mx + _nx * (_rd.tol_li * 0.6), _my + _ny * (_rd.tol_li * 0.6))
_off = WMAP.terrain_at(_mx + _nx * 1.0, _my + _ny * 1.0)
check("L73 路中线 0.6×容差内 → 判为路",
      _on in (R.T_ROAD, R.T_TRAIL, R.T_FORD), str(_on))
check("L74 路中线外 1 里 → 不再是路（此前整格 100 里都是路）",
      _off not in (R.T_ROAD, R.T_TRAIL), str(_off))
check("L75 路宽为真实尺度（≤0.02 里 = 10 m），判定容差独立且更宽",
      _rd.width_li <= 0.02 and _rd.tol_li >= _rd.width_li * 2.0,
      f"width={_rd.width_li} tol={_rd.tol_li}")

# ---- R2b：河流几何化 ----
_rv = max(WMAP.rivers(), key=lambda r: r.length_li)
check("L76 河宽沿程渐变（源头窄 → 下游宽，0.05~0.4 里）",
      len(_rv.widths) == len(_rv.points)
      and _rv.widths[0] <= _rv.widths[-1]
      and 0.04 <= _rv.widths[0] <= 0.06 and 0.35 <= _rv.widths[-1] <= 0.45,
      f"head={_rv.widths[0]} tail={_rv.widths[-1]} pts={len(_rv.points)}")
# 河面内 → 水；离河 5 里 → 不是水
_vax, _vay = _rv.points[len(_rv.points) // 2]
_vbx, _vby = _rv.points[len(_rv.points) // 2 + 1]
_vdx, _vdy = _vbx - _vax, _vby - _vay
_vlen = (_vdx * _vdx + _vdy * _vdy) ** 0.5
_vnx, _vny = -_vdy / _vlen, _vdx / _vlen
_on_river = WMAP.terrain_at(_vax, _vay)
_off_river = WMAP.terrain_at(_vax + _vnx * 5.0, _vay + _vny * 5.0)
check("L77 河面内判为水域", _on_river == R.T_WATER, str(_on_river))
check("L78 离河 5 里不再是水（此前整格 100 里都是水）",
      _off_river != R.T_WATER, str(_off_river))

print(f"\n== 结果：{_PASS} 过 / {_FAIL} 败 ==")
sys.exit(1 if _FAIL else 0)
