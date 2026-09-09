"""P4-R2 动作模型单测（纯函数，确定性）。

覆盖 `docs/战斗系统定案.md` §3/§6/§8 与 R2 验收判据：
  1. 基础动作数据化（平砍/防御/聚气/遁走/购买加速）
  2. 执行流程：条件 → 扣灵 → schedule → 组件
  3. 组件：Damage / ApplyStatus / QiGain / Purchase（含灵石不足）
  4. 条件：目标有状态 / 自身低血 / 不满足则拒绝
  5. 灵气与状态：累积封顶、时间窗口到期、加速覆盖（不可叠加）
  6. **验收：新增技能只加数据、engine 零改动**
  7. 确定性：同输入重复执行逐位一致

运行：.venv\\Scripts\\python.exe -X utf8 -m tests.test_action
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from content import actions as A
from engine.action import (Action, Actor, ApplyStatus, Damage, Purchase, QiGain,
                           can_execute, execute, require_hp_below,
                           require_target_has)
from engine.clock import SIDE_ENEMY, SIDE_PLAYER, Clock, Timing

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


def make(actor_qi=100.0, target_hp=1000.0, stones=1000):
    p = Actor(key="p", name="我", hp=500, hp_max=500, attack=40, defense=10,
              speed=1.0, element="无", qi=actor_qi, qi_max=100.0, qi_rate=3.0,
              stones=stones)
    e = Actor(key="e", name="木桩", hp=target_hp, hp_max=target_hp, attack=0,
              defense=20, speed=1.0, element="无", qi=0, qi_max=0, qi_rate=0.0)
    ck = Clock()
    ck.add("p", speed=p.speed, side=SIDE_PLAYER)
    ck.add("e", speed=e.speed, side=SIDE_ENEMY)
    return p, e, ck


# ============ 1. 基础动作数据化 ============
print("== 1 基础动作数据化 ==")
check("平砍是 Action", isinstance(A.ATTACK, Action) and A.ATTACK.key == "attack")
check("平砍不耗灵、后摇 200", A.ATTACK.qi_cost == 0 and A.ATTACK.timing.recovery == 200)
check("防御后摇极短（100）", A.DEFEND.timing.recovery == 100)
check("防御带 guard 时间窗口 300 厘息",
      A.DEFEND.components[0].key == "guard" and A.DEFEND.components[0].duration_li == 300)
check("聚气是 QiGain 组件", isinstance(A.GATHER.components[0], QiGain))
check("遁走不吃速度（speed=0）",
      A.FLEE.timing.recovery_speed == 0.0 and A.FLEE.timing.windup_speed == 0.0)
check("购买加速是 Purchase 组件（灵石=货币）",
      isinstance(A.BUY_QI_LOW.components[0], Purchase))
check("低阶/高阶两档：高阶更贵更强更久",
      A.BUY_QI_HIGH.components[0].cost > A.BUY_QI_LOW.components[0].cost
      and A.BUY_QI_HIGH.components[0].boost > A.BUY_QI_LOW.components[0].boost
      and A.BUY_QI_HIGH.components[0].T_max > A.BUY_QI_LOW.components[0].T_max)

# ============ 2. 执行流程 ============
print("== 2 执行流程 ==")
p, e, ck = make()
out = execute(p, e, A.ATTACK, ck, jitter_roll=0.5)
check("平砍 ok", out.ok and out.reason == "")
check("落地时刻 = 前摇(0)", out.land_t == 0)
check("可动时刻 = 后摇(200)", out.end_t == 200)
check("造成伤害 > 0", out.damage > 0, f"{out.damage}")
check("木桩掉血", e.hp < e.hp_max)
check("detail 含乘区明细", "mitigation" in out.detail)

p, e, ck = make(actor_qi=5.0)
out = execute(p, e, A.FENTIAN, ck)      # 耗 40
check("灵气不足 → low_qi 且不扣灵不推进",
      not out.ok and out.reason == "low_qi" and p.qi == 5.0 and ck.next_t("p") == 0,
      f"{out.reason} qi={p.qi} next={ck.next_t('p')}")

p, e, ck = make()
before = p.qi
out = execute(p, e, A.FENTIAN, ck)
check("耗灵已扣", abs(p.qi - (before - A.FENTIAN.qi_cost)) < 1e-9, f"{p.qi}")

# ============ 3. 组件 ============
print("== 3 组件 ==")
p, e, ck = make()
out = execute(p, e, A.QINGTENG, ck)
check("控制组件进目标袋（debuff/control → 目标）", e.has_status("root"))
check("自身未获得该状态", not p.has_status("root"))
p, e, ck = make()
out = execute(p, e, A.DEFEND, ck)
check("buff 组件进自身袋", p.has_status("guard"))
check("guard 窗口 = t + 300", p.statuses["guard"]["until"] == 300)

p, e, ck = make(actor_qi=0.0)
before = p.qi
out = execute(p, e, A.GATHER, ck)
check("聚气回灵 = 3 × 速率(3) = 9", abs(out.qi_gained - 9.0) < 1e-9, f"{out.qi_gained}")
check("聚气后灵气 = 9", abs(p.qi - 9.0) < 1e-9, f"{p.qi}")

p, e, ck = make(actor_qi=0.0)
p.qi_max = 5.0
execute(p, e, A.GATHER, ck)
check("聚气受灵气池上限封顶", abs(p.qi - 5.0) < 1e-9, f"{p.qi}")

p, e, ck = make(stones=1000)
out = execute(p, e, A.BUY_QI_LOW, ck)
check("购买加速扣灵石", p.stones == 1000 - 20, f"{p.stones}")
check("加速生效", p.current_qi_rate(ck.t) == 3.0 + 3.0,
      f"{p.current_qi_rate(ck.t)}")
p, e, ck = make(stones=5)
out = execute(p, e, A.BUY_QI_LOW, ck)
check("灵石不足 → no_stones 且不扣款", not out.ok and out.reason == "no_stones"
      and p.stones == 5)

p, e, ck = make(stones=1000)
execute(p, e, A.BUY_QI_LOW, ck)
execute(p, e, A.BUY_QI_HIGH, ck)
check("加速不可叠加：新的覆盖旧的", p.current_qi_rate(ck.t) == 3.0 + 15.0,
      f"{p.current_qi_rate(ck.t)}")

# ============ 4. 条件 ============
print("== 4 条件 ==")
p, e, ck = make()
out = execute(p, e, A.LIANJI, ck)       # 需要目标有 weaken
check("条件不满足 → condition_failed", not out.ok and out.reason == "condition_failed")
p, e, ck = make()
execute(p, e, A.DIXIAN, ck)             # 先施加 weaken
out = execute(p, e, A.LIANJI, ck)
check("满足条件后连击可执行", out.ok and out.damage > 0, f"{out.reason}")
check("连击两段伤害累加", out.damage > 0 and len(out.lines) >= 2, f"{len(out.lines)}")

p, e, ck = make()
out = execute(p, e, A.FENSHEN, ck)      # 需自身 HP<30%
check("低血条件不满足 → 拒绝", not out.ok and out.reason == "condition_failed")
p, e, ck = make()
p.hp = p.hp_max * 0.2
out = execute(p, e, A.FENSHEN, ck)
check("低血后焚身可执行", out.ok and out.damage > 0)

# ============ 5. 状态时间窗口 ============
print("== 5 状态时间窗口 ==")
p, e, ck = make()
execute(p, e, A.QINGTENG, ck)           # root 300 厘息
check("状态未到期时仍在", e.has_status("root"))
gone = e.expire_statuses(299)
check("t=299 未到期", gone == [] and e.has_status("root"))
gone = e.expire_statuses(300)
check("t=300 到期清理", gone == ["root"] and not e.has_status("root"))

p, e, ck = make(stones=1000)
execute(p, e, A.BUY_QI_LOW, ck)         # 800 厘息
check("加速期内速率提升", p.current_qi_rate(799) == 6.0,
      f"{p.current_qi_rate(799)}")
check("加速到期后恢复基础速率", p.current_qi_rate(800) == 3.0)

# ============ 6. 验收：新增技能只加数据 ============
print("== 6 验收：新增技能只加数据（engine 零改动） ==")
# 一个"打三下 + 附带中毒 + 目标有中毒时额外伤害"的新技能，全部用已有组件拼出
NEW_SKILL = Action(
    key="test_triple_poison", name="测试·三连毒", kind="attack", qi_cost=12, tier=3,
    timing=Timing(windup=50, recovery=350),
    components=(
        Damage(power=18, attack_ratio=0.2, element="木"),
        ApplyStatus(key="poison", duration_li=900, stacks=2, tags=("debuff",)),
        Damage(power=12, attack_ratio=0.1, element="木"),
    ),
    qi_efficiency=0.03,
)
p, e, ck = make()
out = execute(p, e, NEW_SKILL, ck)
check("新技能无需改 engine 即可执行", out.ok and out.damage > 0)
check("新技能施加中毒（带层数）",
      e.has_status("poison") and e.statuses["poison"]["stacks"] == 2)
check("多段伤害累加", len([l for l in out.lines if "伤害" in l]) == 2,
      f"{out.lines}")

# ============ 7. 确定性 ============
print("== 7 确定性 ==")
def script():
    p, e, ck = make()
    res = []
    for act in (A.ATTACK, A.RUIJIN, A.GATHER, A.QINGTENG, A.DIXIAN):
        o = execute(p, e, act, ck, jitter_roll=0.5)
        res.append((o.action_key, o.damage, o.end_t, round(p.qi, 6),
                    round(e.hp, 6), tuple(sorted(e.statuses))))
    return res
r1, r2 = script(), script()
check("同输入两次运行逐位一致", r1 == r2, f"{r1} vs {r2}")

check("can_execute 纯查询（不改状态）",
      can_execute(p, e, A.ATTACK, ck.t) == (True, ""))

# ============ 8. 乘区在真实执行路径上生效（端到端） ============
print("== 8 乘区端到端（脆弱/破势真的改变了伤害） ==")
# 脆弱：目标带 vulnerable 时受击提高
p, e, ck = make()
base = execute(p, e, A.ATTACK, ck, jitter_roll=0.5).damage
p2, e2, ck2 = make()
e2.add_status("vulnerable", 10 ** 9)
buffed = execute(p2, e2, A.ATTACK, ck2, jitter_roll=0.5).damage
check("脆弱让受击提高（守方乘区生效）", buffed > base,
      f"base={base} vulnerable={buffed}")
check("脆弱倍率 ≈ 1.5", abs(buffed / base - 1.5) < 0.03,
      f"{buffed / base:.3f}")

# 破势：自身带 weaken 时输出降低
p3, e3, ck3 = make()
p3.add_status("weaken", 10 ** 9)
weakened = execute(p3, e3, A.ATTACK, ck3, jitter_roll=0.5).damage
check("破势让输出降低（攻方乘区生效）", weakened < base,
      f"base={base} weaken={weakened}")
check("破势倍率 ≈ 0.7", abs(weakened / base - 0.7) < 0.03, f"{weakened / base:.3f}")

# 状态随时间窗口到期后不再生效
p4, e4, ck4 = make()
e4.add_status("vulnerable", 300)
ck4.t = 299
d299 = execute(p4, e4, A.ATTACK, ck4, jitter_roll=0.5).damage
e4.expire_statuses(300)
p5, e5, ck5 = make()
d_after = execute(p5, e5, A.ATTACK, ck5, jitter_roll=0.5).damage
check("脆弱窗口到期后回到基础伤害", abs(d299 - buffed) < 1e-9 and d_after == base,
      f"299={d299} after={d_after} base={base}")

# 时长加成端到端：蓄力技（duration_weight>0）伤害高于同威力的零权重动作
p6, e6, ck6 = make()
XULI_FAST = Action(key="xuli_fast", name="蓄力·零权重", kind="attack", qi_cost=6,
                   timing=Timing(windup=700, recovery=400, windup_speed=0.5),
                   components=(Damage(power=25, attack_ratio=0.5, element="土"),),
                   qi_efficiency=0.02, duration_weight=0.0, tier=2)
p7, e7, ck7 = make()
d_no_weight = execute(p6, e6, XULI_FAST, ck6, jitter_roll=0.5).damage
d_weight = execute(p7, e7, A.XULI, ck7, jitter_roll=0.5).damage
check("时长权重让蓄力技伤害更高", d_weight > d_no_weight,
      f"无权重={d_no_weight} 权重1.2={d_weight}")

# 品阶端到端（其余字段完全一致，只差 tier）
p8, e8, ck8 = make()
LOW_TIER = Action(key="low_tier", name="同数据低品阶", kind="attack", qi_cost=6,
                  timing=Timing(windup=700, recovery=400, windup_speed=0.5),
                  components=(Damage(power=25, attack_ratio=0.5, element="土"),),
                  qi_efficiency=0.02, duration_weight=0.4, tier=1)
SAME_TIER2 = Action(key="same_t2", name="同数据品阶2", kind="attack", qi_cost=6,
                    timing=Timing(windup=700, recovery=400, windup_speed=0.5),
                    components=(Damage(power=25, attack_ratio=0.5, element="土"),),
                    qi_efficiency=0.02, duration_weight=0.4, tier=2)
p9, e9, ck9 = make()
d_low = execute(p8, e8, LOW_TIER, ck8, jitter_roll=0.5).damage
d_t2 = execute(p9, e9, SAME_TIER2, ck9, jitter_roll=0.5).damage
check("品阶让同数据技能伤害更高", d_t2 > d_low, f"tier2={d_t2} tier1={d_low}")

# ============ 9. 标定不变量（qi_rate 降低后的尺度约束） ============
print("== 9 标定不变量 ==")
from engine import rules as R
# 高耗灵技能：加速能显著缩短有效间隔（说明灵气是真约束）
rec, cost, rate = 600, 40, 1.0
no_boost = R.effective_interval_li(rec, 1.0, cost, rate)
with_boost = R.effective_interval_li(rec, 1.0, cost, rate + 15.0)
check("高耗灵技能：加速显著缩短有效间隔", with_boost < no_boost,
      f"无加速 {no_boost} → 加速 {with_boost}")
check("高耗灵技能：基础回灵下灵气项压过后摇", no_boost > rec,
      f"间隔 {no_boost} vs 后摇 {rec}")
# 低耗灵技能：加速对间隔无影响（后摇主导）——耗灵 2 × 1/息 = 2 息 = 后摇 200 厘息
low_cost = R.effective_interval_li(200, 1.0, 2, 1.0)
low_cost_boost = R.effective_interval_li(200, 1.0, 2, 16.0)
check("低耗灵技能：加速对间隔无影响（后摇主导）", low_cost == low_cost_boost == 200,
      f"{low_cost} vs {low_cost_boost}")
check("引气流大招耗灵 ≥ 回灵×周期（否则加速失效）",
      A.FENTIAN.qi_cost >= 1.0 * (A.FENTIAN.timing.recovery / 100.0),
      f"耗灵{A.FENTIAN.qi_cost} vs 周期{A.FENTIAN.timing.recovery / 100.0}息×1/息")

print(f"\n== 结果：{_PASS} 过 / {_FAIL} 败 ==")
sys.exit(1 if _FAIL else 0)
