"""P3.9 引擎加固测试（纯引擎驱动，确定性）。

覆盖本轮审查确认的 5 项修复：
  A. 参数类型加固：step() 的数值参数经 _as_int 转换，坏值不抛异常（Web 不再 500）
  B. 身死拦截：alive=False 时除 status/chronicle 外一律 game_over 拒绝
  C. 突破寿元：成功只补"大境界基准差额"，已累积的折寿不被抹平
  D. 闭关封顶：修为不超 exp_cap；请求天数收敛到"圆满那一天"
  E. 坊市门槛：market 与 buy 一致要求身处坊市
  F. Result.pill_line 为正式字段（不再是动态挂属性）

运行：.venv\\Scripts\\python.exe -X utf8 -m tests.test_hardening
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from content import enemies as EM
from content import gongfa as G
from content import pills as P
from content import sites as ST
from engine import settings as S
from engine.game import Game, Result, _as_int

_PASS = 0
_FAIL = 0


def check(name: str, cond: bool, detail: str = ""):
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  [OK] {name}")
    else:
        _FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


def new_game(seed: int = 1, stones: int = 50000) -> Game:
    g = Game(seed=seed)
    g.state.player.spirit_stones = stones
    return g


def p_of(g: Game):
    return g.state.player


# ============ A. 参数类型加固 ============
print("== A 参数类型加固（坏值 → 结构化结果，不抛异常） ==")
check("_as_int: 非数字串 → default", _as_int("abc", 30) == 30)
check("_as_int: None → default", _as_int(None, 30) == 30)
check("_as_int: 空串 → default", _as_int("", 30) == 30)
check("_as_int: 数字串 → 数值", _as_int("7", 30) == 7)
check("_as_int: float 截断", _as_int(1.9, 30) == 1)
check("_as_int: bool 保持", _as_int(True, 0) == 1)
check("_as_int: dict → default", _as_int({"a": 1}, 30) == 30)

g = new_game(1)
# 每个坏值用独立新局 + 固定资质，避免修为推满/随机资质影响"回退默认天数"的期望
for kw in [{"days": "abc"}, {"days": None}, {"days": {}}, {"days": []}]:
    gg = new_game(1)
    gg.state.player.root_mult = 1.0
    try:
        r = gg.step("cultivate", **kw)
        check(f"cultivate {kw} 不抛异常且回退默认天数(30)",
              r.ok is True and r.data["days"] == 30, f"{r.ok} {r.data.get('days')}")
    except Exception as e:  # noqa: BLE001
        check(f"cultivate {kw} 不抛异常", False, f"{type(e).__name__}: {e}")

gg = new_game(1)
try:
    r = gg.step("buy", item="清心丹", qty="x")     # qty 坏值 → 回退 1
    check("buy qty='x' 不抛异常（回退 qty=1 正常买入）",
          r.ok is True and r.data["qty"] == 1, f"{r.ok} {r.data.get('qty')}")
except Exception as e:  # noqa: BLE001
    check("buy qty='x' 不抛异常", False, f"{type(e).__name__}: {e}")

gg = new_game(1)
try:
    r = gg.step("buy", item="清心丹", qty="x")
    check("buy qty 坏值不产生负数/异常数量", r.data.get("qty") == 1)
except Exception as e:  # noqa: BLE001
    check("buy qty 坏值不抛异常", False, f"{type(e).__name__}: {e}")

g = new_game(2)
try:
    r = g.step("age_pass", days="oops")
    check("age_pass days='oops' 回退默认 30", r.ok is True and r.data["days"] == 30)
except Exception as e:  # noqa: BLE001
    check("age_pass days='oops' 不抛异常", False, f"{type(e).__name__}: {e}")

# ============ B. 身死拦截 ============
print("== B 身死拦截 ==")
g = new_game(3)
p = p_of(g)
p.alive = False
BLOCKED = [
    ("cultivate", dict(days=1)), ("comprehend", dict(gongfa="吐纳诀", days=1)),
    ("breakthrough", {}), ("explore", dict(site="灵脉山")),
    ("travel", dict(site="灵脉山")), ("age_pass", dict(days=1)),
    ("use_pill", dict(item="清心丹")), ("buy", dict(item="清心丹")),
    ("learn", dict(gongfa="吐纳诀")), ("forget", dict(slot="main")),
    ("market", {}),
]
for act, kw in BLOCKED:
    r = g.step(act, **kw)
    check(f"身死拒 {act}（game_over）",
          r.ok is False and r.reason == "game_over" and r.game_over is True,
          f"ok={r.ok} reason={r.reason}")
for act, kw in [("status", {}), ("chronicle", {})]:
    r = g.step(act, **kw)
    check(f"身死仍可查看 {act}", r.ok is True and r.reason == "ok", f"{r.reason}")

# 探索不再能"死后赚灵石"
g = new_game(4)
p = p_of(g)
p.alive = False
before = p.spirit_stones
g.step("explore", site="灵脉山")
check("身死后 explore 不得灵石", p.spirit_stones == before,
      f"{before} -> {p.spirit_stones}")

# ============ C. 突破寿元差额 ============
print("== C 突破寿元只补基准差额 ==")
g = new_game(5)
p = p_of(g)
p.realm_idx = 9
p.age_years = 60.0
p.exp = p.exp_cap()
p.lifespan_years = S.LIFESPAN_PER_REALM[8] * p.lifespan_mult - 40   # 模拟累积折寿 40
p.add_item(P.ZHUJI, 1)
old_base = S.LIFESPAN_PER_REALM[8] * p.lifespan_mult
new_base = S.LIFESPAN_PER_REALM[9] * p.lifespan_mult
life_before = p.lifespan_years
r = g.step("breakthrough")
check("突破成功", r.ok is True and p.realm_idx == 10)
check("寿元 = 旧寿元 + (新基准-旧基准)，折寿 40 未被抹平",
      abs(p.lifespan_years - (life_before + (new_base - old_base))) < 1e-6,
      f"{life_before:.1f} + {new_base - old_base:.1f} = {p.lifespan_years:.1f}")
check("寿元 < 新基准（折寿保留）",
      p.lifespan_years < new_base - 1, f"{p.lifespan_years:.1f} vs {new_base:.1f}")
check("突破丹已消耗", p.item_count(P.ZHUJI) == 0)

# 小境界：基准不变 → 成功时寿元不变（失败会折寿，故只在成功分支断言）
g = new_game(6)
p = p_of(g)
p.realm_idx = 3
p.age_years = 30.0
p.exp = p.exp_cap()
p.lifespan_years = S.LIFESPAN_PER_REALM[2] * p.lifespan_mult - 25
p.add_item(P.ZHUJI, 1)
life_before = p.lifespan_years
r = g.step("breakthrough")
if r.data.get("success"):
    check("小境界突破成功且寿元不变（基准相同）",
          abs(p.lifespan_years - life_before) < 1e-6,
          f"{life_before:.1f} -> {p.lifespan_years:.1f}")
else:
    # 失败分支：寿元应减少（不是被重置回基准），且减少量 = randint(1,8)
    check("小境界突破失败：寿元按折寿减少且未被重置回基准",
          p.lifespan_years < life_before
          and p.lifespan_years < S.LIFESPAN_PER_REALM[2] * p.lifespan_mult,
          f"{life_before:.1f} -> {p.lifespan_years:.1f}")

# ============ D. 闭关封顶 ============
print("== D 闭关修为封顶 ==")
g = new_game(7)
p = p_of(g)
p.root_mult = 100.0
r = g.step("cultivate", days=300)
cap = p.exp_cap()
check("修为不超过 exp_cap", p.exp <= cap + 1e-9, f"exp={p.exp} cap={cap}")
check("data.full=True", r.data["full"] is True)
check("data.capped=True", r.data["capped"] is True)
check("days 收敛到圆满所需天数（<请求天数）", r.data["days"] < 300,
      f"days={r.data['days']}")
check("天数照实推进（day 与收敛天数一致）",
      g.state.day == r.data["days"], f"day={g.state.day} days={r.data['days']}")

# 已圆满后再闭关：0 天、不推进、不浪费
g = new_game(8)
p = p_of(g)
p.root_mult = 100.0
g.step("cultivate", days=300)
day_before, exp_before = g.state.day, p.exp
r = g.step("cultivate", days=100)
check("已圆满再闭关：days=0", r.data["days"] == 0, f"{r.data['days']}")
check("已圆满再闭关：修为不涨", abs(p.exp - exp_before) < 1e-9)
check("已圆满再闭关：时间不推进", g.state.day == day_before)
check("已圆满再闭关：仍 ok=True 且提示可突破", r.ok is True and r.data["full"] is True)

# 不越界：正常闭关仍按请求天数推进
g = new_game(9)
p = p_of(g)
p.root_mult = 1.0
r = g.step("cultivate", days=5)
check("未触顶时 days 原样", r.data["days"] == 5 and r.data["capped"] is False,
      f"{r.data['days']} capped={r.data['capped']}")
check("未触顶时 exp = 5×1.0×root", abs(p.exp - 5.0 * 1.0) < 1e-9, f"{p.exp}")

# 边界：只差"不足一天"即圆满 → 只推进所需 1 天，exp 恰好落在 cap（不溢出）
g = new_game(10)
p = p_of(g)
p.root_mult = 1.0
cap = p.exp_cap()
p.exp = cap - 0.5          # 0.5 < 1 天收益 → need_days = 1
r = g.step("cultivate", days=30)
check("差不足一天圆满：只推进 1 天且 exp 恰为 cap（不溢出）",
      r.data["days"] == 1 and p.exp == cap,
      f"days={r.data['days']} exp={p.exp!r} cap={cap}")

# 浮点吸附：exp 距 cap 极小（浮点误差）→ 吸附为 cap 并判为已圆满（不再空转闭关）
g = new_game(10)
p = p_of(g)
p.root_mult = 1.0
cap = p.exp_cap()
p.exp = cap - 1e-13        # 典型浮点误差量级
r = g.step("cultivate", days=30)
check("浮点误差（cap−1e-13）→ 吸附为 cap 且 days=0（不空转）",
      r.data["days"] == 0 and p.exp == cap and r.data["full"] is True,
      f"days={r.data['days']} exp={p.exp!r}")

# 真实未满（差 0.5）不能被误判为已满
g = new_game(10)
p = p_of(g)
p.root_mult = 1.0
p.exp = p.exp_cap() - 0.5
r = g.step("cultivate", days=1)
check("差 0.5 未满 → 仍可闭关 1 天", r.data["days"] == 1, f"{r.data['days']}")

# ============ E. 坊市门槛 ============
print("== E 坊市门槛（market 与 buy 一致） ==")
g = new_game(11)
p = p_of(g)
check("新局在坊市", p.location == ST.SHISHI)
r = g.step("market")
check("坊市看货单 ok", r.ok is True and "pills" in r.data and "gongfa" in r.data)
g.step("travel", site="灵脉山")
r = g.step("market")
check("离开坊市看货单 → not_at_market",
      r.ok is False and r.reason == "not_at_market", f"{r.reason}")
r = g.step("buy", item="清心丹", qty=1)
check("离开坊市购买 → not_at_market（与 market 同码）", r.reason == "not_at_market")
g.step("travel", site="坊市")
r = g.step("market")
check("回到坊市可看货单", r.ok is True)

# ============ F. Result.pill_line 正式字段 ============
print("== F Result.pill_line 正式字段 ==")
check("Result 有 pill_line 字段", "pill_line" in Result.__dataclass_fields__)
g = new_game(11)
p = p_of(g)
p.add_item(P.JULING, 3)
r = g.step("cultivate", days=30, use_pill=True)
check("用聚灵丹闭关 → pill_line 有内容且非动态属性",
      bool(r.pill_line) and r.data["pill_qty"] > 0, f"{r.pill_line!r}")
r2 = g.step("cultivate", days=1)
check("未用丹 → pill_line 为空串", r2.pill_line == "", f"{r2.pill_line!r}")

# ============ G. 战斗结算灵石不丢失（2026-09-10 修复） ============
print("== G 战斗结算灵石 ==")
E = EM.by_id(EM.LINGWEN_LANG)

g = new_game(21, stones=1000)
g.start_battle(E.id)
check("战斗 Actor 灵石 = 世界灵石（此前 actor_from_stats 漏拷恒为 0）",
      g.battle().p.stones == 1000, f"{g.battle().p.stones}")

g = new_game(22, stones=1000)
g.start_battle(E.id)
g.battle().e.hp = 1
g.battle().submit("attack")
r = g.step("battle_skip")
check("胜利后灵石 > 初始（战利品不再被回写覆盖）",
      r.battle_over == "win" and g.state.player.spirit_stones > 1000,
      f"{r.battle_over} {g.state.player.spirit_stones}")

g = new_game(23, stones=1000)
g.start_battle(E.id)
b = g.battle()
ok, reason = b.submit("buy_qi_low")
check("够灵石时购灵加速可入队", ok, reason)
b.e.hp = 1
b.submit("attack")
g.step("battle_skip")
check("购买花费扣除且战利品保留（> 980）", g.state.player.spirit_stones > 980,
      f"{g.state.player.spirit_stones}")

g = new_game(24, stones=1000)
g.start_battle(E.id)
r = g.step("battle_action", cmd="flee")
check("遁走后灵石不变", g.state.player.spirit_stones == 1000,
      f"{r.battle_over} {g.state.player.spirit_stones}")

g = new_game(25, stones=10)
g.start_battle(E.id)
b = g.battle()
ok, reason = b.submit("buy_qi_high")
av = [a for a in b.available() if a["key"] == "buy_qi_high"][0]
check("买不起购灵加速 → no_stones 且动作标记不可用",
      not ok and reason == "no_stones" and av["available"] is False
      and av["reason"] == "no_stones", f"{ok} {reason} {av}")

# ============ H. 战斗队列撤回（游戏动作层） ============
print("== H 战斗队列撤回 ==")
g = new_game(31)
g.start_battle(E.id)
b = g.battle()
b.submit("attack")
b.submit("attack")
r = g.step("battle_unqueue", index=1)
check("battle_unqueue 成功且返回队列",
      r.ok is True and len(r.data["queue"]) == 1, f"{r.ok} {r.reason}")
r2 = g.step("battle_unqueue", index=99)
check("battle_unqueue 越界 → queue_index",
      r2.ok is False and r2.reason == "queue_index", f"{r2.ok} {r2.reason}")
r3 = g.step("battle_clear")
check("battle_clear 清空队列", r3.ok is True and r3.data["queue"] == [])
r4 = g.step("explore", site=str(ST.LINGMAI))
check("战斗中日常动作仍被拒", r4.ok is False and r4.reason == "in_battle")

# ============ I. 坊市"已拥有"标记 ============
print("== I 坊市已拥有标记 ==")
g = new_game(41, stones=5000)
g.state.player.location = ST.SHISHI
md = g.step("market").data


def _gf(data, name):
    return next(x for x in data["gongfa"] if x["name"] == name)


check("未购功法 owned=False", _gf(md, "炎阳诀")["owned"] is False)
g.step("buy", item=str(G.YANYANG_JUE), qty=1)
md2 = g.step("market").data
check("购得后 owned=True", _gf(md2, "炎阳诀")["owned"] is True)
check("未购的其它功法仍 owned=False", _gf(md2, "玄水真经")["owned"] is False)

# ============ J. 聚灵丹与封顶（P4-R7） ============
print("== J 聚灵丹与封顶 ==")
g = new_game(51)
p = p_of(g)
p.add_item(P.JULING, 5)
cap = p.exp_cap()
r = g.step("cultivate", days=365, use_pill=True)
check("有丹闭关到圆满：exp == cap", abs(p.exp - cap) < 1e-6, f"{p.exp}/{cap}")
check("有丹闭关：天数收敛（capped=True 且 <365）",
      r.data["capped"] is True and r.data["days"] < 365,
      f"days={r.data['days']} capped={r.data['capped']}")
check("有丹闭关：扣丹数与加速天数一致",
      r.data["pill_qty"] > 0 and r.data["pill_days"] > 0,
      f"qty={r.data['pill_qty']} days={r.data['pill_days']}")
check("有丹闭关：剩余丹药 = 5 − 消耗",
      p.item_count(P.JULING) == 5 - r.data["pill_qty"], f"{p.item_count(P.JULING)}")

g = new_game(52)
r = g.step("cultivate", days=10, use_pill=True)
check("无丹勾选：pill_qty=0 且正常闭关",
      r.data["pill_qty"] == 0 and r.data["days"] == 10,
      f"qty={r.data['pill_qty']} days={r.data['days']}")

g = new_game(53)
p = p_of(g)
p.add_item(P.JULING, 3)
r = g.step("cultivate", days=5, use_pill=True)
check("短闭关（5 天）只扣 1 颗",
      r.data["pill_qty"] == 1 and p.item_count(P.JULING) == 2,
      f"qty={r.data['pill_qty']} left={p.item_count(P.JULING)}")

g1 = new_game(54)
r1 = g1.step("cultivate", days=10)
g2 = new_game(54)
p_of(g2).add_item(P.JULING, 1)
r2 = g2.step("cultivate", days=10, use_pill=True)
check("聚灵丹加速生效（同 10 天修为更高）",
      r2.data["exp_gained"] > r1.data["exp_gained"],
      f"{r1.data['exp_gained']} → {r2.data['exp_gained']}")

print(f"\n== 结果：{_PASS} 过 / {_FAIL} 败 ==")
sys.exit(1 if _FAIL else 0)
