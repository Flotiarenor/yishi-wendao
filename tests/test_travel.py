"""P4-T3 移动单测（引擎驱动，确定性，禁 pytest）。

覆盖任务书 `docs/tasks/P4-T3-移动.md` §四 判据：
  A. 时间接真：移动耗时 = 路径 total_si（不再固定 3 日；随境界下降）
  B. 两段式 travel：预览是纯查询（不推进 t / 不移动）；route=<n> 才执行
  C. 舆图档位：none 只给 march；coarse 给 1 条；detailed 给 3 条
  D. 手动探路：直线推进；遇硬阻挡 / 水域停下；绝不自动绕行；上限 300 里
  E. 存档：world 键恰 6 个；往返一致；老档（无 world）迁到锚点
  F. 旧地点连接：不建世界即可互访；坊市门槛按坐标距离
  G. 近距/派生标签：同聚落挪动走捷径；location 标签随移动更新

运行：.venv\\Scripts\\python.exe -X utf8 tests\\test_travel.py
"""
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from content import regions as R          # noqa: E402
from content import sites as ST           # noqa: E402
from engine import settings as S          # noqa: E402
from engine import worldmap as WM         # noqa: E402
from engine.game import Game, MARCH_DIRS, _legacy_li   # noqa: E402

_PASS = 0
_FAIL = 0
_SEED = 900001


def check(name: str, cond: bool, detail: str = ""):
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  [OK] {name}")
    else:
        _FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


def new_game(seed: int = _SEED) -> Game:
    return Game(seed=seed)


# ============ A. 时间接真 ============
print("== A 移动耗时接真实路径 ==")
g = new_game()
p = g.state.player
spawn = R.LEGACY_ANCHORS[ST.name_of(ST.SHISHI)]
check("A1 开局坐标 = 坊市锚点", g.pos() == (spawn[0], spawn[1]), str(g.pos()))
li_lingmai = _legacy_li(ST.name_of(ST.SHISHI), ST.name_of(ST.LINGMAI))
t0 = g.state.t
r = g.step("travel", site=str(ST.LINGMAI))
expect_si = int(math.ceil(li_lingmai / 22.0 * S.SI_PER_DAY))
check("A2 旧地点互访耗时 = 里程/越野基线（非固定 3 日）",
      r.ok is True and r.data["si"] == expect_si,
      f"实测 {r.data.get('si')} 期望 {expect_si}（{li_lingmai:.0f} 里）")
check("A3 时间轴推进了对应息数", g.state.t - t0 == expect_si,
      f"Δ={g.state.t - t0} 期望 {expect_si}")
check("A4 旧地点互访不建世界（不付生成成本）", g.state.world.world_seed == _SEED,
      str(g.state.world.world_seed))

# 境界越高，同一段路越快（走真实寻路的城镇对）
g2 = new_game(seed=_SEED)
g2.wmap                                    # 显式建世界
towns = [t for t in g2.wmap.towns if math.hypot(t.x - spawn[0], t.y - spawn[1]) > 3000]
tgt = min(towns, key=lambda t: math.hypot(t.x - spawn[0], t.y - spawn[1]))
res_low = g2.wmap.find_path(spawn, (tgt.x, tgt.y), profile="fastest", realm_idx=1)
res_high = g2.wmap.find_path(spawn, (tgt.x, tgt.y), profile="fastest", realm_idx=14)
check("A5 同路径 + 境界 → 耗时单调下降（练气 > 化神）",
      res_low.total_si > res_high.total_si and not res_low.blocked,
      f"{res_low.total_si} vs {res_high.total_si}")

# ============ B. 两段式 travel ============
print("\n== B 两段式 travel（先预览、后执行） ==")
g = new_game(seed=_SEED)
g.state.world = g.state.world.__class__(
    world_seed=_SEED, pos=g.pos(), map_level="detailed")
t_before = g.state.t
pos_before = g.pos()
r = g.step("travel", site=tgt.name)
check("B1 预览：ok 且带 routes（不推进时间）", r.ok is True and len(r.data["routes"]) >= 1,
      str(r.reason))
check("B2 预览不推进时间（纯查询）", g.state.t == t_before, f"Δ={g.state.t - t_before}")
check("B3 预览不移动位置", g.pos() == pos_before, str(g.pos()))
first = r.data["routes"][0]
r2 = g.step("travel", site=tgt.name, route=0)
check("B4 route=0 执行：位置 = 目的地", r2.ok is True
      and abs(g.pos()[0] - tgt.x) < 1e-6 and abs(g.pos()[1] - tgt.y) < 1e-6,
      str(g.pos()))
check("B5 执行推进时间 = 候选 si", g.state.t - t_before == first["si"],
      f"Δ={g.state.t - t_before} 期望 {first['si']}")
check("B6 执行 data 带 route 详情（days/li/profile）",
      r2.data.get("route", {}).get("profile") == "fastest"
      and r2.data.get("days") == first["days"])
# 越界序号：换一个**未到达**的目的地（否则会先被"已在目的地"拦下，测不到序号校验）
far = max((t for t in g.wmap.towns if not t.is_main),
          key=lambda t: math.hypot(t.x - g.pos()[0], t.y - g.pos()[1]))
r3 = g.step("travel", site=far.name, route=9)
check("B7 候选序号越界 → route_invalid（不推进时间）",
      r3.ok is False and r3.reason == "route_invalid", r3.reason)

# ============ C. 舆图档位 ============
print("\n== C 舆图档位决定候选数 ==")
for lvl, want in (("none", None), ("coarse", 1), ("detailed", 3)):
    gg = new_game(seed=_SEED)
    gg.state.world = gg.state.world.__class__(
        world_seed=_SEED, pos=gg.pos(), map_level=lvl)
    rr = gg.step("travel", site=tgt.name)
    if lvl == "none":
        check("C1 无舆图 → need_map（不给寻路，只能手动探路）",
              rr.ok is False and rr.reason == "need_map", rr.reason)
        mm = gg.step("march", direction="东")
        check("C2 无舆图仍可手动探路", mm.ok is True and mm.data["li"] > 0, mm.reason)
    else:
        check(f"C{lvl} 舆图 {lvl} → {want} 条候选",
              rr.ok is True and len(rr.data["routes"]) == want,
              f"{len(rr.data.get('routes', []))}")

# ============ D. 手动探路 ============
print("\n== D 手动探路（直线 · 遇阻停下 · 不绕行） ==")
g = new_game(seed=_SEED)
r = g.step("march", direction="东")
check("D1 方向合法 → 推进 > 0 且 ≤ 上限",
      r.ok is True and 0 < r.data["li"] <= S.MARCH_MAX_LI + 1e-6,
      f"{r.data.get('li')}")
check("D2 推进上限 = MARCH_MAX_LI（不会一步跨半个世界）",
      abs(r.data["li"] - S.MARCH_MAX_LI) < 60.0 or r.data["blocked"],
      str(r.data))
check("D3 八方向全部可解析", all(d in MARCH_DIRS for d in
                              ("东", "西", "南", "北", "东北", "西北", "东南", "西南")))
bad = g.step("march", direction="东北偏东")
check("D4 非法方向 → direction_invalid",
      bad.ok is False and bad.reason == "direction_invalid", bad.reason)

# 直线性：march 的落点必须在起点与该方向的射线上（不拐弯）
g = new_game(seed=_SEED)
sx, sy = g.pos()
r = g.step("march", direction="东")
nx, ny = g.pos()
check("D5 march 走直线（东 → y 不变、x 增大）",
      abs(ny - sy) < 1e-9 and nx > sx, f"({sx},{sy}) -> ({nx},{ny})")

# 遇硬阻挡停下：把玩家放到一处硬阻挡的西侧，向东 march 必须停下
wm = g.wmap
hard = R.HARD_BLOCK_IDS
found = None
for cy in range(0, S.WORLD_CELLS):
    for cx in range(2, S.WORLD_CELLS - 2):
        if wm._terrain_cell(cx, cy, True) in hard and \
                wm._terrain_cell(cx - 1, cy, True) not in hard:
            found = (cx, cy)
            break
    if found:
        break
check("D6 世界上存在硬阻挡样本（用于遇阻断言）", found is not None, str(found))
if found:
    cx, cy = found
    g2 = new_game(seed=_SEED)
    g2._set_pos((cx - 1 + 0.5) * S.WORLD_CELL_LI, (cy + 0.5) * S.WORLD_CELL_LI)
    r = g2.step("march", direction="东")
    check("D7 前方硬阻挡 → blocked + blocked_by 为地形名",
          r.ok is False and r.reason == "march_blocked"
          and r.data["blocked"] is True and r.data["blocked_by"] != "",
          f"blocked_by={r.data.get('blocked_by')!r} li={r.data.get('li')}")
    check("D8 遇阻不越界（落点仍在阻挡西侧）", g2.pos()[0] < (cx + 0.5) * S.WORLD_CELL_LI,
          str(g2.pos()))

# 遇水域停下（练气不可渡）
water = None
for cy in range(0, S.WORLD_CELLS):
    for cx in range(2, S.WORLD_CELLS - 2):
        if wm._terrain_cell(cx, cy, True) == R.T_WATER and \
                wm._terrain_cell(cx - 1, cy, True) not in hard \
                and wm._terrain_cell(cx - 1, cy, True) != R.T_WATER:
            water = (cx, cy)
            break
    if water:
        break
if water:
    cx, cy = water
    g3 = new_game(seed=_SEED)
    g3._set_pos((cx - 1 + 0.5) * S.WORLD_CELL_LI, (cy + 0.5) * S.WORLD_CELL_LI)
    r = g3.step("march", direction="东")
    check("D9 前方水域（练气不可渡）→ 停下",
          r.ok is False and r.reason == "march_blocked", f"{r.reason} {r.data.get('blocked_by')}")
else:
    check("D9 世界含水域样本", False, "未找到水域样本")

# ============ E. 存档 ============
print("\n== E 存档（world 键 + 旧档迁移） ==")
g = new_game(seed=_SEED)
g.state.world = g.state.world.__class__(
    world_seed=_SEED, pos=g.pos(), map_level="detailed",
    discovered={"p_1", "p_2"})
snap = g.snapshot()
check("E1 to_dict 含 world 键", "world" in snap)
check("E2 world 键恰 6 个", len(snap["world"]) == 6, str(sorted(snap["world"])))
g_town = next(t for t in g.wmap.towns if not t.is_main)
g.step("travel", site=g_town.name, route=0)
snap2 = g.snapshot()
g_load = Game(seed=_SEED, load=snap2)
check("E3 载入后坐标一致", abs(g_load.pos()[0] - g_town.x) < 1e-6
      and abs(g_load.pos()[1] - g_town.y) < 1e-6, str(g_load.pos()))
check("E4 载入后舆图档位保留", g_load.state.world.map_level == "detailed")
# 旧档：无 world 键，location=灵脉山
legacy = {
    "seed": _SEED, "rng_counter": 0, "t": 12345, "turn": 3,
    "player": {"name": "旧档", "location": ST.name_of(ST.LINGMAI)},
    "chronicle": {"entries": []},
}
try:
    g_leg = Game(seed=_SEED, load=legacy)
    exp = R.LEGACY_ANCHORS[ST.name_of(ST.LINGMAI)]
    check("E5 老档（无 world 键）→ 迁到旧地点锚点",
          abs(g_leg.pos()[0] - exp[0]) < 1e-6 and abs(g_leg.pos()[1] - exp[1]) < 1e-6,
          f"{g_leg.pos()} 期望 {exp}")
    check("E6 老档 map_level = coarse（定案 §7）", g_leg.state.world.map_level == "coarse")
except Exception as e:  # noqa: BLE001
    check("E5 老档迁移不抛异常", False, repr(e))

# ============ F. 旧地点连接与坊市门槛 ============
print("\n== F 旧地点连接 / 坊市门槛 ==")
g = new_game(seed=_SEED)
r = g.step("travel", site=str(ST.SHISHI))
check("F1 已在坊市 → 仍在坊市（近距/原地）", g.at_market() is True, str(g.pos()))
g.step("travel", site=str(ST.LINGMAI))
check("F2 去灵脉山后不在坊市", g.at_market() is False, str(g.pos()))
check("F3 地点标签同步为灵脉山", g.state.player.location == ST.LINGMAI,
      str(g.state.player.location))
g.step("travel", site=str(ST.SHISHI))
check("F4 回坊市后 at_market 恢复", g.at_market() is True)
mr = g.step("market")
check("F5 坊市货单可看（门槛按坐标）", mr.ok is True and "pills" in mr.data)
g.step("travel", site=str(ST.GUZHAN if hasattr(ST, "GUZHAN") else ST.LINGMAI))
br = g.step("buy", item="清心丹", qty=1)
check("F6 离开坊市购买被拒（not_at_market）", br.ok is False and br.reason == "not_at_market",
      br.reason)

# ============ G. 状态快照 ============
print("\n== G 状态快照 ==")
g = new_game(seed=_SEED)
sd = g.state_data()
check("G1 location 含坐标与舆图档",
      all(k in sd["location"] for k in ("id", "name", "x", "y", "map_level")),
      str(sorted(sd["location"])))
check("G2 state_data 不触发世界生成（坐标来自存档）",
      g.state.world.map_level == "coarse" and g.pos() == (10000.0, 10000.0))
sd2 = g.state_data()
check("G3 state_data 幂等（两次一致）", sd == sd2)

print("\n== 结果：%d 过 / %d 败 ==" % (_PASS, _FAIL))
sys.exit(1 if _FAIL else 0)
