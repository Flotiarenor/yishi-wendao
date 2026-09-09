"""P4-T1 时间刻度统一到息（纯引擎驱动，确定性）。

覆盖：
  A. 单位换算与纯函数（day_of / shichen_of / day_phase / format_time）
  B. GameState.t 是唯一时钟，day 为派生属性（恒等于 t // SI_PER_DAY）
  C. 旧档迁移：只有 day 的存档 → t = day × SI_PER_DAY
  D. 战斗耗时接回世界轴（胜 / 败 / 逃 三条路径都推进 t）
  E. state_data() 暴露 t / shichen / time_text 且只读
  F. 闭关 / 静养 / 探索 仍按整天推进（行为中性）

运行：.venv\\Scripts\\python.exe -X utf8 -m tests.test_time
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from content import enemies as EM
from content import sites as ST
from engine import settings as S
from engine.game import Game
from engine.state import GameState

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


# ============ A. 单位换算与纯函数 ============
print("== A 单位换算与纯函数 ==")
check("1 刻 = 450 息", S.SI_PER_KE == 450)
check("1 时辰 = 8 刻 = 3600 息", S.KE_PER_SHICHEN == 8 and S.SI_PER_SHICHEN == 3600)
check("1 日 = 12 时辰 = 43200 息", S.SHICHEN_PER_DAY == 12 and S.SI_PER_DAY == 43200)
check("1 年 = 360 日 = 15552000 息", S.SI_PER_YEAR == 15_552_000)
check("12 个时辰名", len(S.SHICHEN_NAMES) == 12 and S.SHICHEN_NAMES[0] == "子")

check("day_of(0) = 0", S.day_of(0) == 0)
check("day_of(SI_PER_DAY) = 1", S.day_of(S.SI_PER_DAY) == 1)
check("day_of(2 日 + 1 时辰) = 2", S.day_of(2 * S.SI_PER_DAY + S.SI_PER_SHICHEN) == 2)
check("shichen_of(0) = 子", S.shichen_of(0) == "子")
check("shichen_of(6 时辰) = 午", S.shichen_of(6 * S.SI_PER_SHICHEN) == "午")
check("shichen_of(11 时辰) = 亥", S.shichen_of(11 * S.SI_PER_SHICHEN) == "亥")

# 12 个时辰的昼夜段覆盖完整且无遗漏
phases = [S.day_phase(i * S.SI_PER_SHICHEN) for i in range(12)]
check("12 时辰全部有昼夜段", all(p[0] for p in phases))
check("午时属日中·火", S.day_phase(6 * S.SI_PER_SHICHEN)[:2] == ("日中", "火"))
check("子时属夜半·水", S.day_phase(0)[:2] == ("夜半", "水"))
check("卯时属平旦·木", S.day_phase(3 * S.SI_PER_SHICHEN)[:2] == ("平旦", "木"))
check("酉时属日入·金", S.day_phase(9 * S.SI_PER_SHICHEN)[:2] == ("日入", "金"))
check("土旺四季：辰时叠土", S.day_phase(4 * S.SI_PER_SHICHEN)[2] == "土")
check("土旺四季：未时叠土", S.day_phase(7 * S.SI_PER_SHICHEN)[2] == "土")
check("非四季末不叠土：卯时", S.day_phase(3 * S.SI_PER_SHICHEN)[2] == "")

check("format_time 古风串", S.format_time(2 * S.SI_PER_DAY + 6 * S.SI_PER_SHICHEN)
      == "第三日 · 午时", S.format_time(2 * S.SI_PER_DAY + 6 * S.SI_PER_SHICHEN))
check("format_time 第一日", S.format_time(0) == "第一日 · 子时", S.format_time(0))
check("format_time 第十日", S.format_time(9 * S.SI_PER_DAY).startswith("第十日"),
      S.format_time(9 * S.SI_PER_DAY))

# ============ B. t 是唯一时钟 ============
print("\n== B t 是唯一时钟（day 派生） ==")
gs = GameState(seed=1, t=3 * S.SI_PER_DAY + 123)
check("day = t // SI_PER_DAY", gs.day == 3)
gs2 = GameState(seed=1, t=S.SI_PER_DAY - 1)
check("不足一日 → day=0", gs2.day == 0)
gs3 = GameState(seed=1, t=S.SI_PER_DAY)
check("刚好一日 → day=1", gs3.day == 1)
check("to_dict 同时含 t 与 day", gs.to_dict()["t"] == gs.t and gs.to_dict()["day"] == gs.day)
check("往返一致", GameState.from_dict(gs.to_dict()).t == gs.t)

# ============ C. 旧档迁移 ============
print("\n== C 旧档迁移（只有 day） ==")
old = {"seed": 7, "rng_counter": 3, "day": 12,
       "player": {"name": "旧档", "age_years": 16.0},
       "chronicle": {"entries": []}, "turn": 5}
mig = GameState.from_dict(old)
check("旧档 day → t = day × 43200", mig.t == 12 * S.SI_PER_DAY, f"t={mig.t}")
check("旧档 day 语义不变", mig.day == 12)
check("旧档 turn 保留", mig.turn == 5)

# ============ D. 战斗耗时接回世界轴 ============
print("\n== D 战斗耗时接回世界轴 ==")


def _run_battle(g: Game, enemy_id: int):
    """直接开战 → 每轮排入平砍并执行，直到结束；返回 (outcome, si_before, si_after, data)。"""
    g.start_battle(enemy_id)
    if g._active_battle is None:
        return None, 0, 0, {}
    t0 = g.state.t
    for _ in range(400):
        if g._active_battle is None:
            break
        if not g._active_battle.queue:
            g.step("battle_submit", key="attack")
        rr = g.step("battle_skip")
        if g._active_battle is None:
            return rr.data.get("outcome"), t0, g.state.t, rr.data
    return None, 0, 0, {}


enemy_ids = sorted(EM.ENEMIES.keys())[:3]
check("敌人目录非空", len(enemy_ids) >= 3, f"{len(enemy_ids)}")

for eid in enemy_ids:
    g = Game(seed=100 + eid)
    g.state.player.spirit_stones = 5000
    outcome, t0, t1, data = _run_battle(g, eid)
    check(f"敌人{eid} 战斗结束（{outcome}）后 t 增加",
          outcome is not None and t1 > t0, f"t {t0} → {t1}")
    check(f"敌人{eid} data 含 battle_si ≥ 1",
          int(data.get("battle_si", 0)) >= 1, f"battle_si={data.get('battle_si')}")
    check(f"敌人{eid} 战斗耗时 < 1 日（不推动 day）",
          (t1 - t0) < S.SI_PER_DAY, f"Δ={t1 - t0} 息")

# ============ E. state_data 暴露且只读 ============
print("\n== E state_data 暴露时间且只读 ==")
g = Game(seed=2026)
g.step("age_pass", days=30)
sd = g.state_data()
t_before = g.state.t
check("state_data 含 t", "t" in sd and sd["t"] == g.state.t)
check("state_data 含 day", "day" in sd and sd["day"] == g.state.day)
check("state_data 含 shichen", sd.get("shichen") in S.SHICHEN_NAMES, f"{sd.get('shichen')}")
check("state_data 含 time_text（古风）", "日" in sd.get("time_text", "") and "时" in sd.get("time_text", ""),
      f"{sd.get('time_text')}")
check("state_data 含 day_phase", sd.get("day_phase") in ("平旦", "日中", "日入", "夜半"),
      f"{sd.get('day_phase')}")
g.state_data()
check("state_data 只读（t 不变）", g.state.t == t_before)

# ============ F. 整天推进仍等价 ============
print("\n== F 整天推进行为中性 ==")
g1 = Game(seed=42)
r1 = g1.step("cultivate", days=30)
check("闭关 30 天 → t = 30 × 43200", g1.state.t == 30 * S.SI_PER_DAY, f"t={g1.state.t}")
check("闭关 30 天 → day = 30", g1.state.day == 30)
check("闭关 30 天 → 年龄 = 16 + 30/360", g1.state.player.age_years == round(16 + 30 / 360, 2),
      f"{g1.state.player.age_years}")

g2 = Game(seed=42)
g2.step("age_pass", days=7)
check("静养 7 天 → day = 7", g2.state.day == 7)
check("静养 7 天 → t = 7 × 43200", g2.state.t == 7 * S.SI_PER_DAY)

print(f"\n== 结果：{_PASS} 过 / {_FAIL} 败 ==")
sys.exit(1 if _FAIL else 0)
