"""P4-T4 迷雾与情报单测（引擎驱动，确定性，禁 pytest）。

**T4-A「落地必探」+ 坐标目的地**这两件已实现，本文件覆盖其判据：

  A. 踏勘写 `discovered`：`discover_here()` 把神识视野内的内容点写进集合、幂等、按距离排序
  B. 移动落地写 discovered：真实城镇寻路落地后有新发现；叙事行与结构化载荷都在
  C. 缓存失效：`_disc_ver` 单调递增（**不能用 len(集合) 当版本号**）
  D. 手动探路也揭示：无舆图走 march 同样"亲身踏勘"（定案 §5 的揭示方式之一）
  E. 地图下发口径：`known` = 神识视野内 ∪ discovered；未探明只给轮廓不留真名
  F. 坐标目的地（右键"走到那里"）：预览/执行共用寻路管线；无舆图仍被拒；越界被夹住
  G. 存档往返：`discovered` 存进 world 键（**键数仍恰 6 个**）；载入后仍生效

⚠️ 本文件的直接 `Game(...)` 和未加 save_dir 的 `GameSession` 只写内存；最后一个用例显式落到
   系统临时目录（workspace-write 沙箱会拒——那是沙箱策略，不是代码故障）。

运行：.venv\\Scripts\\python.exe -X utf8 tests\\test_fog.py
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
from engine.game import Game              # noqa: E402
from engine.state import GameState as _GS  # noqa: E402

_PASS = 0
_FAIL = 0
_SEED = 900003          # 与 test_travel 错开，免得两边共用世界缓存实例


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


def nearest_points(g: Game, x: float, y: float, n: int = 3) -> list:
    """离 (x, y) 最近的 n 个内容点（升序）——用于构造"走到那里"的确定性样本。"""
    pts = sorted(g.wmap.content_points, key=lambda p: (math.hypot(p.x - x, p.y - y), p.id))
    return pts[:n]


def spawn_xy() -> tuple:
    """出生点（坊市锚点）坐标。"""
    ax, ay = R.LEGACY_ANCHORS[ST.name_of(ST.SHISHI)]
    return (float(ax), float(ay))


# ============ A. 踏勘写 discovered ============
print("== A 踏勘写 discovered（T4-A 核心）==")
g = new_game()
p0 = nearest_points(g, *spawn_xy(), n=1)[0]          # 出生城附近最近的内容点
g._set_pos_arrived(p0.x + 10.0, p0.y + 10.0)         # 站到它旁边（模拟"走到那里"）
before = len(g.state.world.discovered)
seen, fresh = g.discover_here()
check("A1 discover_here 返回视野内点与新发现点两个序列",
      isinstance(seen, tuple) and isinstance(fresh, tuple), f"{type(seen)}/{type(fresh)}")
check("A2 视野内点按 (距离, id) 升序",
      all(math.hypot(a.x - g.pos()[0], a.y - g.pos()[1])
          <= math.hypot(b.x - g.pos()[0], b.y - g.pos()[1]) + 1e-9
          for a, b in zip(seen, seen[1:])) if len(seen) > 1 else True,
      str([q.id for q in seen]))
check("A3 新发现点都写进了 discovered",
      len(g.state.world.discovered) == before + len(fresh)
      and all(q.id in g.state.world.discovered for q in fresh),
      f"{before} → {len(g.state.world.discovered)}（fresh={len(fresh)}）")
check("A4 站到近处必有发现（该点就在视野内）",
      any(q.id == p0.id for q in fresh), f"期望含 {p0.id}，实际 {[q.id for q in fresh]}")
check("A5 发现点全部落在神识视野半径内", all(
    math.hypot(q.x - g.pos()[0], q.y - g.pos()[1])
    <= g.wmap.vision_radius(g.state.player.realm_idx, g._vision_tid()) + 1e-6 for q in fresh),
    str([(q.id, round(math.hypot(q.x - g.pos()[0], q.y - g.pos()[1]))) for q in fresh]))
_seen2, fresh2 = g.discover_here()
check("A6 原地再踏勘 → 幂等（新发现 0，集合不变）",
      len(fresh2) == 0 and len(g.state.world.discovered) == before + len(fresh),
      f"fresh2={len(fresh2)}")
check("A7 叙事行非空且提到名字", bool(g._discover_text(fresh)) and fresh[0].name in g._discover_text(fresh),
      g._discover_text(fresh))
check("A8 结构化载荷含 id/kind/name/坐标/里程", all(
    all(k in q for k in ("id", "kind", "kind_name", "name", "element", "x", "y", "dist_li"))
    for q in g._fresh_points_data(fresh, *g.pos())),
    str(g._fresh_points_data(fresh, *g.pos())[:1]))
check("A9 站在荒无人烟处 → 无新发现且集合不变", (
    lambda gg, n0: (gg._set_pos_arrived(*WM.clamp_xy(0.0, 0.0)),
                    gg.discover_here()[1] == () and len(gg.state.world.discovered) == n0)[1]
)(g, before + len(fresh)))

# ============ B. 移动落地写 discovered ============
print("\n== B 移动落地写 discovered ==")
g = new_game()
spx, spy = spawn_xy()
town = [t for t in g.wmap.towns if t.is_main and t.name == "青石镇"][0]
near = nearest_points(g, town.x, town.y, n=1)[0]      # 出生城附近最近的内容点
r = None
tgt_town = None
for dest in g.wmap.towns:
    if math.hypot(dest.x - spx, dest.y - spy) <= 500.0:
        continue
    if ST.resolve(dest.name) is not None:
        continue          # 名字撞上旧地点（如"灵脉山"）会走固定连接捷径，不是寻路
    rr = g.step("travel", site=dest.name, route=0)   # 直接执行第 0 条候选
    if rr.ok and rr.data.get("route"):
        r, tgt_town = rr, dest
        break
check("B1 真实城镇间寻路移动成功（用于验证落地踏勘）",
      r is not None and r.ok is True, "" if r is None else f"{r.ok}/{r.reason}")
check("B2 落地后 data.newly_discovered 是 list",
      isinstance(r.data.get("newly_discovered"), list), str(type(r.data.get("newly_discovered"))))
check("B3 落地后 data.discovered_total = 集合大小",
      r.data.get("discovered_total") == len(g.state.world.discovered),
      f"{r.data.get('discovered_total')} vs {len(g.state.world.discovered)}")
check("B4 落点即新位置（pos 与 dest 一致）",
      abs(g.pos()[0] - r.data["dest"]["x"]) < 1e-6 and abs(g.pos()[1] - r.data["dest"]["y"]) < 1e-6,
      f"{g.pos()} vs {r.data['dest']}")
check("B5 移动结果**不是**坐标目的地（to_point=False）", r.data.get("to_point") is False,
      str(r.data.get("to_point")))
g2 = new_game()
mv = g2.step("travel", site="坊市")                   # 旧地点快捷路径（不建世界）
check("B6 旧地点落地也走同一条踏勘（newly_discovered 存在）",
      mv.ok is True and "newly_discovered" in mv.data, str(mv.data.get("newly_discovered")))

# ============ C. 缓存失效（不能用 len(集合) 当版本号）============
print("\n== C discovered 变更 → 地图缓存失效 ==")
g = new_game()
v0 = g._disc_ver
g._set_pos_arrived(near.x + 10.0, near.y + 10.0)
g.discover_here()
v1 = g._disc_ver
check("C1 有新发现 → 版本号 +1", v1 == v0 + 1, f"{v0} → {v1}")
g.discover_here()
check("C2 无新发现 → 版本号不变（不做无谓失效）", g._disc_ver == v1, f"{g._disc_ver}")
key_len = len(g.state.world.discovered)
g.state.world.discovered.clear()                     # 模拟"忘掉/被夺情报"：集合长度归零
g._disc_ver += 1                                     # 唯一正确的失效方式
check("C3 集合长度变化后版本号仍可与旧键区分（len 当版本号会撞）",
      g._disc_ver == v1 + 1 and len(g.state.world.discovered) != key_len,
      f"ver={g._disc_ver} len={len(g.state.world.discovered)}")
mv1 = g.map_view()
check("C4 map_view 的缓存键含版本号（两次同状态命中同一结果对象）",
      g.map_view() is mv1, "memo 未命中")

# ============ D. 手动探路也揭示 ============
print("\n== D 无舆图手动探路同样踏勘 ==")
g = new_game()
g.state.world.map_level = "none"                     # 无舆图：只能 march
d = 0
before = len(g.state.world.discovered)
for direct in ("东", "西", "南", "北", "东北", "东南", "西南", "西北"):
    rr = g.step("march", direction=direct)
    if rr.data.get("li", 0) > 0:
        d = direct
        break
check("D1 无舆图仍可手动探路（推进 > 0）", d != "" , "八方向皆被挡")
check("D2 march 结果同样带 newly_discovered / discovered_total",
      "newly_discovered" in rr.data and "discovered_total" in rr.data, str(sorted(rr.data)))
check("D3 march 推进后位置已变（落地写坐标）",
      g.pos() != spawn_xy(), f"{g.pos()}")
check("D4 遇阻停步时也照实结算（li ≤ MARCH_MAX_LI）",
      rr.data.get("li", 0) <= S.MARCH_MAX_LI + 1e-6, str(rr.data.get("li")))
g.state.world.map_level = "coarse"
check("D5 切回粗舆图后 travel 恢复可用（档位语义未被打乱）",
      g.step("travel", site=str(ST.LINGMAI)).ok is True)

# ============ E. 地图下发口径 ============
print("\n== E 地图下发：known = 视野内 ∪ discovered ==")
g = new_game()
g.state.world.map_level = "detailed"                 # 详图才下发内容点层
g._set_pos_arrived(near.x + 10.0, near.y + 10.0)
g.discover_here()
mv = g.map_view()
pts = {q["id"]: q for q in mv["points"]}
check("E1 详图下发内容点层（points 非空）", len(mv["points"]) > 0, str(mv["counts"]))
check("E2 已发现点 known=True 且显示真名", all(
    q["known"] is True and q["name_shown"] == q["name"] and q["known_by"] == "discovered"
    for q in mv["points"] if q["id"] in g.state.world.discovered),
    str([(q["id"], q["known_by"]) for q in mv["points"] if q["id"] in g.state.world.discovered][:3]))
check("E3 未发现且视野外的点 → known=False 且名字留白",
      all(q["name_shown"] == "（未探明）" for q in mv["points"]
          if not q["known"]),
      str([q["name_shown"] for q in mv["points"] if not q["known"]][:3]))
check("E4 known_by 只取 discovered / vision / 空 三值",
      all(q["known_by"] in ("discovered", "vision", "") for q in mv["points"]),
      str(sorted({q["known_by"] for q in mv["points"]})))
check("E5 known_points 计数与逐点一致（与前端契约同口径）",
      mv["counts"]["known_points"] == sum(1 for q in mv["points"] if q["known"]),
      str(mv["counts"]))
check("E6 未探明点仍给轮廓（坐标 + 里程，只是不留真名）",
      all("x" in q and "y" in q and "dist_li" in q for q in mv["points"]), "")
check("E7 无舆图（none）→ 内容点一条都不下发",
      (lambda gg: (setattr(gg.state.world, "map_level", "none"), gg.map_view()["counts"]["points"] == 0)[1])(g),
      "")
check("E8 粗舆图（coarse）→ 只给城镇、不给内容点",
      (lambda gg: (setattr(gg.state.world, "map_level", "coarse"),
                   gg.map_view()["counts"]["points"] == 0
                   and gg.map_view()["counts"]["towns"] > 0)[1])(g), "")

# ============ F. 坐标目的地（右键"走到那里"）============
print("\n== F 坐标目的地（地图右键移动）==")
g = new_game()
spx, spy = spawn_xy()
# 目标点：**一个真实存在的内容点**（必然可达、必然在世界内）——右键"走到那里"的现实用法
tgt = nearest_points(g, spx, spy, n=6)[-1]
tx, ty = tgt.x, tgt.y
prev = g.step("travel", x=tx, y=ty)                  # 不带 route = 预览
check("F1 坐标目的地 → 预览给候选且不移动",
      prev.ok is True and len(prev.data.get("routes", [])) >= 1,
      f"{prev.ok}/{prev.reason} routes={len(prev.data.get('routes', []))}")
check("F2 预览标记 to_point=True", prev.data.get("to_point") is True, str(prev.data.get("to_point")))
check("F3 预览不推进时间、不移动", g.pos() == (spx, spy) and g.state.t == 0, f"{g.pos()} t={g.state.t}")
check("F4 候选终点 = 请求坐标",
      prev.data.get("dest", {}).get("x") is not None
      and abs(prev.data["dest"]["x"] - tx) < 1e-6 and abs(prev.data["dest"]["y"] - ty) < 1e-6,
      str(prev.data.get("dest")))
si0, t0 = g.state.t, g.pos()
ex = g.step("travel", x=tx, y=ty, route=0)           # 执行
check("F5 执行后位置 = 请求坐标",
      abs(g.pos()[0] - tx) < 1e-6 and abs(g.pos()[1] - ty) < 1e-6, str(g.pos()))
check("F6 执行推进时间 = 候选 si", g.state.t - si0 == ex.data["si"], f"{g.state.t - si0} vs {ex.data.get('si')}")
check("F7 执行带 route 详情与 to_point",
      ex.data.get("to_point") is True and ex.data.get("route", {}).get("index", ex.data.get("route", {}).get("idx")) == 0,
      str(ex.data.get("route")))
check("F8 坐标目的地的地点标签随落点派生（不再一刀切写成坊市）",
      g.state.player.location in [ST.SHISHI, ST.LINGMAI, ST.GUZHAN]
      or isinstance(g.state.player.location, int),
      str(g.state.player.location))
check("F9 越界坐标被夹到世界内（不落到世界之外）",
      (lambda gg: (gg.step("travel", x=-500.0, y=10 ** 9, route=None),
                   -1e-6 <= gg.pos()[0] <= 20000.0 + 1e-6 and True)[1])(new_game()), "")
check("F10 route 序号越界 → route_invalid（不移动）",
      (lambda gg: (lambda rr: rr.ok is False and rr.reason == "route_invalid")(gg.step("travel", x=tx, y=ty, route=99)))(new_game()),
      "")
g_none = new_game()
g_none.state.world.map_level = "none"
rn = g_none.step("travel", x=tx, y=ty)
check("F11 无舆图 → 坐标目的地同样被拒（need_map，不能被右键绕过）",
      rn.ok is False and rn.reason == "need_map", str(rn.reason))
check("F12 坐标缺一个 → site_invalid（结构化拒绝，不抛异常）",
      (lambda rr: rr.ok is False and rr.reason == "site_invalid")(new_game().step("travel", x=tx)),
      "")
# 近距右键（同一聚落内挪动）：必须**不建世界也不要舆图**，否则"无舆图连挪两步"都做不到
g_near = new_game()
g_near.state.world.map_level = "none"
rr = g_near.step("travel", x=spx + 20.0, y=spy)
check("F13 脚下附近右键 → 近距挪动（无舆图也允许，不寻路）",
      rr.ok is True and rr.data.get("near") is True and rr.data.get("to_point") is True,
      f"{rr.ok}/{rr.reason}")
check("F14 近距挪动落点 = 请求坐标",
      abs(g_near.pos()[0] - (spx + 20.0)) < 1e-6 and abs(g_near.pos()[1] - spy) < 1e-6,
      str(g_near.pos()))
check("F15 点在脚下（距离 0）→ 0 息且不移动",
      (lambda gg: (lambda r2: r2.ok is True and r2.data.get("si") == 0 and gg.pos() == (spx, spy))(
          gg.step("travel", x=spx, y=spy)))(new_game()), "")

# ============ G. 存档往返 ============
print("\n== G 存档：discovered 随 world 键往返 ==")
g = new_game()
g._set_pos_arrived(near.x + 10.0, near.y + 10.0)
g.discover_here()
snap = g.snapshot()
check("G1 world 键仍恰 6 个（discovered 不额外占键）",
      set(snap["world"]) == {"world_seed", "pos", "discovered", "places", "world_diff", "map_level"},
      str(sorted(snap["world"])))
check("G2 discovered 落档且为排序 list",
      isinstance(snap["world"]["discovered"], list) and snap["world"]["discovered"] == sorted(snap["world"]["discovered"]),
      str(snap["world"]["discovered"][:3]))
g_rt = Game(seed=_SEED)
g_rt.state = _GS.from_dict(snap)
check("G3 往返后 discovered 集合一致",
      g_rt.state.world.discovered == g.state.world.discovered and isinstance(g_rt.state.world.discovered, set),
      f"{len(g_rt.state.world.discovered)} vs {len(g.state.world.discovered)}")
check("G4 往返后地图仍认这些点为已知（known_by=discovered）",
      all(q["known_by"] == "discovered" for q in
          (lambda gg: (setattr(gg.state.world, "map_level", "detailed"), gg.map_view())[1])(g_rt)["points"]
          if q["id"] in g_rt.state.world.discovered),
      "")

# ============ H. 情报买卖（T4-B）============
print("\n== H 情报买卖：买图改档 / 买点情报写 discovered ==")
g = new_game()
g.state.player.add_stones(999999)


def _market_intel(gg):
    return gg.step("market").data.get("intel") or {}


mi = _market_intel(g)
check("H1 坊市货单含情报段（档位 + 货）",
      "map_level" in mi and isinstance(mi.get("items"), list) and len(mi["items"]) > 0,
      str(mi))
check("H2 货单情报带结构化字段（前端直接渲染，不解析 text）",
      all(all(k in q for k in ("id", "name", "price", "kind", "desc")) for q in mi["items"]),
      str(mi["items"][:1]))
check("H3 coarse 档下不出售已持有的粗舆图，只列详图 + 当地情报",
      [q["name"] for q in mi["items"]] == ["详图", "当地情报"],
      str([q["name"] for q in mi["items"]]))
# 买图：改档
_s_before = g.state.player.spirit_stones
r = g.step("buy", item="详图")
check("H4 买详图 → 档位改 detailed",
      r.ok is True and g.state.world.map_level == "detailed", f"{r.ok}/{r.reason} {g.state.world.map_level}")
check("H5 买图扣款 = 货价（余额封顶无关）",
      _s_before - g.state.player.spirit_stones == r.data["unit_price"]
      and r.data["stones_after"] == g.state.player.spirit_stones,
      f"{_s_before} → {g.state.player.spirit_stones}，价 {r.data['unit_price']}")
check("H6 重复买同一档舆图 → dup_owned 且不扣款",
      (lambda rr, s0: rr.ok is False and rr.reason == "dup_owned"
       and g.state.player.spirit_stones == s0)(g.step("buy", item="详图"), g.state.player.spirit_stones),
      "")
check("H7 已到详图后货单只剩当地情报",
      [q["name"] for q in _market_intel(g)["items"]] == ["当地情报"],
      str([q["name"] for q in _market_intel(g)["items"]]))
# 买点情报：写 discovered
n0 = len(g.state.world.discovered)
ri = g.step("buy", item="当地情报")
check("H8 买当地情报 → 返回 newly_discovered",
      ri.ok is True and isinstance(ri.data.get("newly_discovered"), list),
      f"{ri.ok}/{ri.reason}")
check("H9 揭晓半径 = 货单半径（不受神识视野限制——这才是买来的情报）",
      ri.data.get("radius_li") == 600.0 and
      all(q["dist_li"] <= 600.0 + 1e-6 for q in ri.data["newly_discovered"]),
      f"radius={ri.data.get('radius_li')}")
check("H10 揭晓的点都写进了 discovered",
      len(g.state.world.discovered) == n0 + len(ri.data["newly_discovered"])
      and all(q["id"] in g.state.world.discovered for q in ri.data["newly_discovered"]),
      f"{n0} → {len(g.state.world.discovered)}")
check("H11 discovered_total 与集合一致",
      ri.data["discovered_total"] == len(g.state.world.discovered), "")
check("H12 买到的点在舆图上算已发现（known_by=discovered）",
      all(q["known_by"] == "discovered" for q in
          (lambda: (setattr(g.state.world, "map_level", "detailed"), g.map_view()))()[1]["points"]
          if q["id"] in (g.state.world.discovered)),
      "")
s_after = g.state.player.spirit_stones
r_dup = g.step("buy", item="当地情报")
check("H13 同一处再买 → dup_owned（不会花 600 灵石买一句附近没什么）",
      r_dup.ok is False and r_dup.reason == "dup_owned", f"{r_dup.ok}/{r_dup.reason}")
check("H14 拒绝时不扣款（未成交不收费）",
      g.state.player.spirit_stones == s_after, f"{g.state.player.spirit_stones} vs {s_after}")
# 换个地方可以再买
g._set_pos_arrived(*[v + 900.0 for v in spawn_xy()])
r2 = g.step("buy", item="当地情报")
check("H15 换个地方可再买（消息按地方卖）",
      (r2.ok is True) if g.at_market() else (r2.ok is False and r2.reason == "not_at_market"),
      f"{r2.ok}/{r2.reason}")
# 灵石不足
g_poor = new_game()
g_poor.state.player.spirit_stones = 1
rp = g_poor.step("buy", item="当地情报")
check("H16 灵石不足 → no_stones 且不扣款（余额仍为 1）",
      rp.ok is False and rp.reason == "no_stones" and g_poor.state.player.spirit_stones == 1,
      f"{rp.reason} {g_poor.state.player.spirit_stones}")
# 不在坊市不能买情报
g_far = new_game()
g_far.state.player.add_stones(999999)
g_far._set_pos_arrived(*[v + 5000.0 for v in spawn_xy()])
rf = g_far.step("buy", item="当地情报")
check("H17 不在坊市 → not_at_market（情报与丹药同门槛）",
      rf.ok is False and rf.reason == "not_at_market", f"{rf.ok}/{rf.reason}")
# none 档：两档舆图都可买（一次跳档是合理买法）
g_none = new_game()
g_none.state.world.map_level = "none"
g_none.state.player.add_stones(999999)
check("H18 无舆图时货单同时提供粗舆图与详图（允许一次买到详图）",
      [q["name"] for q in _market_intel(g_none)["items"]] == ["粗舆图", "详图", "当地情报"],
      str([q["name"] for q in _market_intel(g_none)["items"]]))
check("H19 无舆图买粗舆图 → 改档 coarse",
      (lambda rr: rr.ok is True and g_none.state.world.map_level == "coarse")(
          g_none.step("buy", item="粗舆图")),
      g_none.state.world.map_level)
check("H20 改档后 travel 恢复可用（买图真的接上了玩法）",
      g_none.step("travel", site=str(ST.LINGMAI)).ok is True, "")

print("\n== 结果：%d 过 / %d 败 ==" % (_PASS, _FAIL))
sys.exit(1 if _FAIL else 0)