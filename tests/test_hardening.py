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

print(f"\n== 结果：{_PASS} 过 / {_FAIL} 败 ==")
sys.exit(1 if _FAIL else 0)
