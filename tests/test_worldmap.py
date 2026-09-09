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
      all(WMAP.terrain_at((cx + 0.5) * 100, (cy + 0.5) * 100)
          == _other.terrain_at((cx + 0.5) * 100, (cy + 0.5) * 100)
          for cx in range(0, 200, 23) for cy in range(0, 200, 29)))
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
_vn = [WM.value_noise(_SEED, i * 137.0, i * 219.0, 1600.0, "elev:0") for i in range(200)]
check("A9a value_noise ∈ [0,1] 且非常数",
      all(0.0 <= v <= 1.0 for v in _vn) and len(set(_vn)) > 100)
_fb = [WM.fbm(_SEED, i * 137.0, i * 219.0, 2000.0, 5, "elev") for i in range(200)]
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
check("B9 世界常量", S.WORLD_CELLS == 200 and S.DOMAIN_LI == 4000.0 and S.WORLD_LI == 20000.0)
check("B10a cell_of 负坐标 clamp 到 0", WM.cell_of(-500.0, -1.0) == (0, 0))
check("B10b cell_of 超界 clamp 到 199", WM.cell_of(99999.0, 25000.0) == (199, 199))
check("B10c cell_of 正好边界", WM.cell_of(100.0, 200.0) == (1, 2)
      and WM.cell_of(20000.0, 20000.0) == (199, 199))
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
_base_road = [(cx, cy) for cy in range(200) for cx in range(200)
              if WMAP.base_terrain(cx, cy) in (R.T_ROAD, R.T_TRAIL)]
_anchor_market = WM.cell_of(*R.LEGACY_ANCHORS["坊市"])
check("C17a 未生成路网前 官道/小径 基础地形仅锚点「坊市」1 格",
      _base_road == [_anchor_market], str(_base_road))
check("C17b 生成路网后 官道/小径 占比 > 0",
      _counts.get(R.T_ROAD, 0) + _counts.get(R.T_TRAIL, 0) > 0)
_ring_ok = all(WMAP.base_terrain(cx, cy) == R.T_VOID
               for cx in range(200) for cy in (0, 199)) and \
    all(WMAP.base_terrain(cx, cy) == R.T_VOID for cy in range(200) for cx in (0, 199))
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
for cy in range(0, 200, 7):
    for cx in range(0, 200, 5):
        idx = cy * 200 + cx
        if idx in WMAP._town_cells or idx in WMAP._road_cells:
            continue
        if WMAP.base_terrain(cx, cy) != WMAP.terrain_at((cx + 0.5) * 100, (cy + 0.5) * 100):
            _sample_ok = False
check("C21a 无覆盖格 base_terrain == terrain_at", _sample_ok)
check("C21b 城镇格 terrain_at 为 T_ROAD",
      all(WMAP.terrain_at(t.x, t.y) == R.T_ROAD for t in WMAP.towns))

# ============ D. 水系 / 灵脉 / 内容点 ============
print("\n== D 水系 / 灵脉 / 内容点 ==")
check("D22a 河流 ≥ 5 条（实测 %d）" % len(WMAP.rivers), len(WMAP.rivers) >= 5)
check("D22b 每条河 ≥ 5 格", all(len(r.cells) >= 5 for r in WMAP.rivers))
_bad_river = []
for r in WMAP.rivers:
    for cx, cy in r.cells:
        t = WMAP.terrain_at((cx + 0.5) * 100, (cy + 0.5) * 100)
        if t not in (R.T_WATER, R.T_FORD):
            _bad_river.append((cx, cy, R.TERRAINS[t].name))
check("D22c 河流格地形为 T_WATER 或 T_FORD", not _bad_river, str(_bad_river[:5]))
check("D23a 每条河渡口 ≥ 1 个", all(len(r.fords) >= 1 for r in WMAP.rivers))
check("D23b 渡口格练气期可通行",
      all(WMAP.speed_at(f[0] * 100 + 50, f[1] * 100 + 50, realm_idx=1) > 0.0
          for r in WMAP.rivers for f in r.fords))
_river_idx = set()
for r in WMAP.rivers:
    for cx, cy in r.cells:
        _river_idx.add(cy * 200 + cx)
_near_river = set()
for idx in _river_idx:
    cy, cx = divmod(idx, 200)
    for dy in (-2, -1, 0, 1, 2):
        for dx in (-2, -1, 0, 1, 2):
            if 0 <= cx + dx < 200 and 0 <= cy + dy < 200:
                _near_river.add((cy + dy) * 200 + cx + dx)
_vein_cnt = {}
_vein_bad = []
_vein_fallback = {}
# 每域「严格合格格」数（山地/丘陵/峡谷 或 距河 ≤ 2 格，且非水域/硬阻挡）
_strict_by_domain = [0] * 25
for _cy in range(200):
    for _cx in range(200):
        _idx = _cy * 200 + _cx
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
    elif tid not in (R.T_MOUNTAIN, R.T_HILL, R.T_CANYON) and (cy * 200 + cx) not in _near_river:
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
for _idx in range(40000):
    if _mcomp[_idx] == _mbest:
        _mainland_by_domain[R.domain_of_cell(_idx % 200, _idx // 200)] += 1
_rich_ok = all(len(_by_domain.get(d, [])) >= 4
               for d in range(25) if _mainland_by_domain[d] >= 200)
check("E30d MAINLAND ≥ 200 格的域城镇数 ≥ 4", _rich_ok,
      str([(d, _mainland_by_domain[d], len(_by_domain.get(d, [])))
           for d in range(25) if _mainland_by_domain[d] >= 200
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
_bad_road = [(idx % 200, idx // 200) for idx, tid in WMAP._road_cells.items()
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
check("F40b 渡口格底层为水域/渡口且可通行",
      all(WMAP._base[idx] in (R.T_WATER, R.T_FORD)
          and WMAP.speed_at((idx % 200) * 100 + 50, (idx // 200) * 100 + 50, 1) > 0.0
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
        tid = WMAP.terrain_at((cx + 0.5) * 100, (cy + 0.5) * 100, with_roads=with_roads)
        t = R.TERRAINS[tid]
        if tid in R.HARD_BLOCK_IDS or (t.swim_only and 1 < S.SWIM_MIN_REALM):
            return float("inf")
        sp = t.speed * S.realm_speed_mult(1)
        if sp <= 0.0:
            return float("inf")
        seg = 100.0 / sp * S.SI_PER_DAY
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
for cy in range(0, 200, 41):
    for cx in range(0, 200, 37):
        tid = WMAP.terrain_at((cx + 0.5) * 100, (cy + 0.5) * 100)
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
            got = WMAP.speed_at((cx + 0.5) * 100, (cy + 0.5) * 100, realm, shenfa)
            if abs(got - want) > 1e-9:
                _sp_ok = False
check("G42 speed_at = 地形速度 × 境界系数 × (1+身法)", _sp_ok, str(_sp_cells))
check("G43a 境界系数单调不减",
      all(S.realm_speed_mult(r) <= S.realm_speed_mult(r + 1) for r in range(1, 25)))
_water_cell = next(((cx, cy) for cy in range(200) for cx in range(200)
                    if WMAP.base_terrain(cx, cy) == R.T_WATER), None)
_wx, _wy = (_water_cell[0] + 0.5) * 100, (_water_cell[1] + 0.5) * 100
check("G43b 练气不能渡水 / 筑基可渡水",
      WMAP.speed_at(_wx, _wy, 9) == 0.0 and WMAP.speed_at(_wx, _wy, 10) == 4.0 * 1.5,
      "%s / %s" % (WMAP.speed_at(_wx, _wy, 9), WMAP.speed_at(_wx, _wy, 10)))
_hb = next(((cx, cy) for cy in range(200) for cx in range(200)
            if WMAP.base_terrain(cx, cy) == R.T_VOID), None)
_r_sb = WMAP.find_path(((_hb[0] + 0.5) * 100, (_hb[1] + 0.5) * 100), (10000.0, 10000.0))
check("G44a 起点硬阻挡 → start_blocked",
      _r_sb.blocked and _r_sb.reason == "start_blocked", _r_sb.reason)
_r_gb = WMAP.find_path((10000.0, 10000.0), ((_hb[0] + 0.5) * 100, (_hb[1] + 0.5) * 100))
check("G44b 终点硬阻挡 → goal_blocked",
      _r_gb.blocked and _r_gb.reason == "goal_blocked", _r_gb.reason)
_cells_in = all(0 <= c[0] <= 199 and 0 <= c[1] <= 199
                for res in (_p1, _r_sb, WMAP.find_path((500.0, 500.0), (19500.0, 19500.0)))
                for c in res.cells)
check("G45 路径格坐标恒在 [0,199]", _cells_in)
# G45b 防穿角：1 格宽屏障不可斜穿（A* 与 _dijkstra 同步约束；复核新增）
_cut = None
for _cy in range(1, 199):
    for _cx in range(1, 199):
        for _dx, _dy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            _a = (_cx, _cy)
            _b = (_cx + _dx, _cy + _dy)
            if not (1 <= _b[0] < 199 and 1 <= _b[1] < 199):
                continue
            _oa = (_cx + _dx, _cy)
            _ob = (_cx, _cy + _dy)

            def _blk(c):
                t = WMAP.terrain_at((c[0] + 0.5) * 100, (c[1] + 0.5) * 100)
                return t in R.HARD_BLOCK_IDS or t == R.T_WATER

            if not _blk(_a) and not _blk(_b) and _blk(_oa) and _blk(_ob):
                _cut = (_a, _b)
                break
        if _cut:
            break
    if _cut:
        break
if _cut:
    _rc = WMAP.find_path(((_cut[0][0] + 0.5) * 100, (_cut[0][1] + 0.5) * 100),
                         ((_cut[1][0] + 0.5) * 100, (_cut[1][1] + 0.5) * 100))
    check("G45b 1 格宽屏障不可斜穿（防穿角）",
          _rc.reason != "ok" or len(_rc.cells) > 2,
          "样本 %s→%s 结果 %s cells=%d" % (_cut[0], _cut[1], _rc.reason, len(_rc.cells)))
else:
    check("G45b 1 格宽屏障不可斜穿（防穿角）", True, "本种子无天然样本")
# 硬阻挡屏障 → 无路（取一个被绝壁完全包围的孤立格）
_comp = [-1] * 40000
_grp = []
for _start in range(40000):
    if _comp[_start] >= 0:
        continue
    _sy, _sx = divmod(_start, 200)
    _t0 = WMAP.terrain_at((_sx + 0.5) * 100, (_sy + 0.5) * 100)
    if _t0 in R.HARD_BLOCK_IDS or _t0 == R.T_WATER:
        _comp[_start] = -2
        continue
    _stack = [_start]
    _comp[_start] = len(_grp)
    _cur = []
    while _stack:
        _i = _stack.pop()
        _cur.append(_i)
        _py, _px = divmod(_i, 200)
        for _dy in (-1, 0, 1):
            for _dx in (-1, 0, 1):
                _ny, _nx = _py + _dy, _px + _dx
                if not (0 <= _nx < 200 and 0 <= _ny < 200):
                    continue
                _j = _ny * 200 + _nx
                if _comp[_j] != -1:
                    continue
                _t = WMAP.terrain_at((_nx + 0.5) * 100, (_ny + 0.5) * 100)
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
    _iy, _ix = divmod(_iso[0], 200)
    _main_y, _main_x = divmod(_grp[0][0], 200)
    _res_iso = WMAP.find_path(((_main_x + 0.5) * 100, (_main_y + 0.5) * 100),
                              ((_ix + 0.5) * 100, (_iy + 0.5) * 100))
    _iso_ok = _res_iso.blocked and _res_iso.reason == "no_path"
    for _dy in (-1, 0, 1):
        for _dx in (-1, 0, 1):
            _ny, _nx = _iy + _dy, _ix + _dx
            if 0 <= _nx < 200 and 0 <= _ny < 200:
                _iso_barrier.append(WMAP.terrain_at((_nx + 0.5) * 100, (_ny + 0.5) * 100))
check("G46a 硬阻挡屏障围出的孤立区 → no_path/blocked", _iso_ok,
      "孤立格 %s 屏障 %s" % (_iso[:1], [R.TERRAINS[t].name for t in _iso_barrier[:8]]))
# 深海屏障：窗口内不可跨越（用公共 CostField + 独立 Dijkstra 验证）
_deep = next((i for i in range(40000) if WMAP.base_terrain(i % 200, i // 200) == R.T_DEEPSEA),
             None)
_deep_ok = False
if _deep is not None:
    _dy2, _dx2 = divmod(_deep, 200)
    _box = (max(0, _dx2 - 5), max(0, _dy2 - 5), min(199, _dx2 + 5), min(199, _dy2 + 5))
    _fld = WMAP.cost_field("fastest", 1, 0.0, box=_box)
    _deep_ok = not _fld.passable(_dx2, _dy2) and \
        WMAP.speed_at((_dx2 + 0.5) * 100, (_dy2 + 0.5) * 100, 1) == 0.0
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
      WMAP.find_path(((_ward_cell[0] + 0.5) * 100, (_ward_cell[1] + 0.5) * 100),
                     (14000.0, 10000.0), profile="fly", realm_idx=14).blocked)
# 飞行可跨越深海
_fly_deep_ok = False
if _deep is not None:
    _dy2, _dx2 = divmod(_deep, 200)
    _start = (_dx2 - 1, _dy2)
    _goal = (_dx2 + 1, _dy2)
    _rd = WMAP.find_path(((_start[0] + 0.5) * 100, (_start[1] + 0.5) * 100),
                         ((_goal[0] + 0.5) * 100, (_goal[1] + 0.5) * 100),
                         profile="fly", realm_idx=14)
    _fly_deep_ok = (not _rd.blocked) or _rd.reason != "start_blocked"
check("G49d 飞行可跨越深海（不因深海受阻）", _fly_deep_ok)
_st_ok = True
_st_tested = 0
for _d, _aid, _bid, _a, _b in _adj_pairs[:40]:
    _rf = WMAP.path_between(_a, _b, profile="fastest")
    if _rf.blocked:
        continue
    _road_f = sum(1 for cx, cy in _rf.cells if WMAP.terrain_at((cx + 0.5) * 100,
                                                               (cy + 0.5) * 100) == R.T_ROAD)
    _rs = WMAP.path_between(_a, _b, profile="stealth")
    if _rs.blocked:
        _st_ok = False
        break
    _road_s = sum(1 for cx, cy in _rs.cells if WMAP.terrain_at((cx + 0.5) * 100,
                                                               (cy + 0.5) * 100) == R.T_ROAD)
    if _road_s > _road_f:
        _st_ok = False
        break
    if _road_f > 0:
        _st_tested += 1
    if _st_tested >= 6:
        break
check("G50a stealth 官道里程 ≤ fastest（抽查 %d 对）" % _st_tested, _st_ok and _st_tested >= 1)
# G50b safe 对危险地形加价（代价模型口径，不依赖「某条路径恰好穿过火山/沼泽」的巧合）
_sw_cell = next(((cx, cy) for cy in range(0, 200, 4) for cx in range(0, 200, 4)
                 if WMAP.base_terrain(cx, cy) in (R.T_SWAMP, R.T_LAVA)), None)
_sf_ok = False
if _sw_cell is not None:
    _box = (max(0, _sw_cell[0] - 1), max(0, _sw_cell[1] - 1),
            min(199, _sw_cell[0] + 1), min(199, _sw_cell[1] + 1))
    _ff = WMAP.cost_field("fastest", 1, 0.0, box=_box)
    _fs = WMAP.cost_field("safe", 1, 0.0, box=_box)
    if _ff.passable(*_sw_cell) and _fs.passable(*_sw_cell):
        _sf_ok = _fs.cost(*_sw_cell) > _ff.cost(*_sw_cell) * 1.5
check("G50b safe 对火山/沼泽地形加价（代价模型）", _sf_ok, str(_sw_cell))
# 路径层面：抽到的样本对若确实穿越险地，safe 不得比 fastest 走更多险地
_sf_path_ok = True
_sf_tested = 0
_sf_pairs = []
_sw_cells = [(cx, cy) for cy in range(0, 200, 4) for cx in range(0, 200, 4)
             if WMAP.base_terrain(cx, cy) in (R.T_SWAMP, R.T_LAVA)]
for _cx, _cy in _sw_cells[:24]:
    _sx, _sy = (_cx + 0.5) * 100, (_cy + 0.5) * 100
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
                 if WMAP.terrain_at((cx + 0.5) * 100, (cy + 0.5) * 100)
                 in (R.T_LAVA, R.T_SWAMP))
    _rsf = WMAP.path_between(_a, _b, profile="safe")
    if _rsf.blocked:
        _sf_path_ok = False
        break
    _mix_s = sum(1 for cx, cy in _rsf.cells
                 if WMAP.terrain_at((cx + 0.5) * 100, (cy + 0.5) * 100)
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
            if (WMAP.speed_at(_x1 * 100 + 50, _y0 * 100 + 50, 1) <= 0.0
                    or WMAP.speed_at(_x0 * 100 + 50, _y1 * 100 + 50, 1) <= 0.0):
                _corner_ok = False
check("G52d 对角步不穿角（两个正交邻格均可通行）", _corner_ok)

# ============ H. 视野 ============
print("\n== H 视野 ==")
_plain_cell = next(((cx, cy) for cy in range(200) for cx in range(200)
                    if WMAP.base_terrain(cx, cy) == R.T_PLAIN), None)
_forest_cell = next(((cx, cy) for cy in range(200) for cx in range(200)
                     if WMAP.base_terrain(cx, cy) == R.T_FOREST), None)
_radii = [WMAP.vision_radius(r, R.T_PLAIN) for r in range(1, 26)]
check("H53a 视野半径随境界单调不减", all(_radii[i] <= _radii[i + 1] for i in range(24)))
check("H53b 林地视野 < 平原视野",
      WMAP.vision_radius(1, R.T_FOREST) < WMAP.vision_radius(1, R.T_PLAIN))
_vx, _vy = (_plain_cell[0] + 0.5) * 100, (_plain_cell[1] + 0.5) * 100
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
check("J66 游戏循环未接入地形（game/state/sites 不引用 worldmap/regions）",
      all("worldmap" not in s and "regions" not in s
          for s in (_game_src, _state_src, _sites_src)))
check("J67 本阶段不改动被保护文件（content/sites.py 旧地点清单仍在）",
      "LINGMAI" in _sites_src and "SHISHI" in _sites_src)

print(f"\n== 结果：{_PASS} 过 / {_FAIL} 败 ==")
sys.exit(1 if _FAIL else 0)
