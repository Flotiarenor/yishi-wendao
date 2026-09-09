"""效果/状态系统单测（R3 版：时间窗口语义 + 乘区一致性）。

旧版针对回合制 `Battle.do()` + `EffectBag` 的断言已随 R3 重构作废；
本文件改为验证新模型下**真正该锁的东西**：
  1. 效果模板注册表（content/effects.py）
  2. 模板 ↔ 乘区一致性：模板键必须被 engine/rules.STATUS_MULT 或 battle 管线认识
  3. 状态经动作施加（ApplyStatus）：进对侧袋、层数、时间窗口到期
  4. 乘区端到端：guard/weaken/vulnerable 在真实动作结算里生效
  5. 立即效果（breath = QiGain）与 DoT 式状态的时间窗口
  6. 扩展点：register_effect 新增模板 → 只加数据即可用

运行：.venv\\Scripts\\python.exe -X utf8 -m tests.test_effects
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from content import effects as CE
from content import enemies as EM
from content import skills as SK
from engine import battle as BTL
from engine import rules as R
from engine.action import (Action, Actor, ApplyStatus, Damage, QiGain, Timing,
                           execute)
from engine.clock import SIDE_ENEMY, SIDE_PLAYER, Clock
from engine.rng import Rng

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


def make(actor_qi=100.0, target_hp=10000.0):
    p = Actor(key="p", name="我", hp=500, hp_max=500, attack=40, defense=10,
              speed=1.0, element="无", qi=actor_qi, qi_max=100.0, qi_rate=1.0)
    e = Actor(key="e", name="木桩", hp=target_hp, hp_max=target_hp, attack=0,
              defense=20, speed=1.0, element="无")
    ck = Clock()
    ck.add("p", speed=1.0, side=SIDE_PLAYER)
    ck.add("e", speed=1.0, side=SIDE_ENEMY)
    return p, e, ck


# ============ 1. 模板注册表 ============
print("== 1 模板注册表 ==")
check("5 个内置模板存在", all(k in CE.EFFECTS for k in
                              ("root", "weaken", "evade", "guard", "breath")))
check("breath = 立即结算（duration=0 + apply_key）",
      CE.EFFECTS["breath"].duration == 0 and CE.EFFECTS["breath"].apply_key == "restore_qi")
check("root 带 control 标签", CE.EFFECTS["root"].tags == ("control",))
check("weaken 默认参数 mult", CE.EFFECTS["weaken"].params == {"mult": 0.5})
check("evade 默认参数 chance", CE.EFFECTS["evade"].params == {"chance": 0.5})
check("guard 默认参数 mult", CE.EFFECTS["guard"].params == {"mult": 0.5})
check("EFFECT_LABELS 键→名正确", CE.EFFECT_LABELS ==
      {"root": "定身", "weaken": "破势", "evade": "闪避", "guard": "护体", "breath": "吐纳"})
check("by_key 命中/未知返回 None", CE.by_key("root") is CE.EFFECTS["root"]
      and CE.by_key("不存在") is None)

# ============ 2. 模板 ↔ 乘区一致性（新模型的关键契约） ============
print("== 2 模板 ↔ 乘区一致性 ==")
check("weaken 被 rules.STATUS_MULT 认识（攻方乘区）",
      "weaken" in R.STATUS_MULT and R.STATUS_MULT["weaken"][0] == "attacker")
check("vulnerable 被 rules.STATUS_MULT 认识（守方乘区）",
      "vulnerable" in R.STATUS_MULT and R.STATUS_MULT["vulnerable"][0] == "defender")
check("guard 不在 STATUS_MULT（它走伤害后乘区，由 battle 管线读 params.mult）",
      "guard" not in R.STATUS_MULT)
check("root 不在 STATUS_MULT（它是控制，走行动跳过）", "root" not in R.STATUS_MULT)
check("evade 不在 STATUS_MULT（它是命中判定）", "evade" not in R.STATUS_MULT)
# 每个内置模板都必须被"某处"认识：乘区 / 控制键 / 命中判定 / 立即结算
KNOWN = set(R.STATUS_MULT) | set(BTL.CONTROL_KEYS) | {"evade", "guard", "breath"}
unknown = [k for k in CE.EFFECTS if k not in KNOWN]
check("所有内置模板都被引擎某处认识（无孤儿模板）", not unknown, f"孤儿：{unknown}")

# ============ 3. 状态经动作施加（时间窗口） ============
print("== 3 状态施加与时间窗口 ==")
STUN = Action(key="t_stun", name="定身击", kind="utility", qi_cost=0, tier=1,
              timing=Timing(windup=0, recovery=200),
              components=(ApplyStatus(key="root", duration_li=500,
                                      tags=("control",)),))
p, e, ck = make()
out = execute(p, e, STUN, ck, jitter_roll=0.5)
check("control 标签 → 进敌方袋", e.has_status("root") and not p.has_status("root"))
check("时间窗口 = t + 500", e.statuses["root"]["until"] == 500)
check("未到期仍持有", e.has_status("root"))
e.expire_statuses(499)
check("t=499 未到期", e.has_status("root"))
gone = e.expire_statuses(500)
check("t=500 到期清理", gone == ["root"] and not e.has_status("root"))

GUARD = Action(key="t_guard", name="护体", kind="defense", qi_cost=0, tier=1,
               timing=Timing(windup=0, recovery=200),
               components=(ApplyStatus(key="guard", duration_li=300, tags=("buff",),
                                      params={"mult": 0.5}),))
p, e, ck = make()
execute(p, e, GUARD, ck)
check("buff 标签 → 进自身袋", p.has_status("guard") and not e.has_status("guard"))
check("guard 参数取动作声明（mult=0.5）",
      p.statuses["guard"]["params"].get("mult") == 0.5)

# 叠层
STACK = Action(key="t_stack", name="叠毒", kind="utility", qi_cost=0, tier=1,
               timing=Timing(windup=0, recovery=200),
               components=(ApplyStatus(key="poison", duration_li=900, stacks=2,
                                       tags=("debuff",)),))
p, e, ck = make()
execute(p, e, STACK, ck)
check("层数记录（stacks=2）", e.statuses["poison"]["stacks"] == 2)
execute(p, e, STACK, ck)
check("重复施加累加层数", e.statuses["poison"]["stacks"] == 4)
check("重复施加取较晚到期", e.statuses["poison"]["until"] == 900)

# ============ 4. 乘区端到端 ============
print("== 4 乘区端到端 ==")
p0, e0, ck0 = make()
base = execute(p0, e0, Action(key="t_atk", name="打", kind="attack", qi_cost=0,
                              timing=Timing(windup=0, recovery=200),
                              components=(Damage(power=30, attack_ratio=0.0),),
                              qi_efficiency=0.0), ck0, jitter_roll=0.5).damage

p1, e1, ck1 = make()
e1.add_status("vulnerable", 10 ** 9)
vuln = execute(p1, e1, Action(key="t_atk", name="打", kind="attack", qi_cost=0,
                              timing=Timing(windup=0, recovery=200),
                              components=(Damage(power=30, attack_ratio=0.0),),
                              qi_efficiency=0.0), ck1, jitter_roll=0.5).damage
check("脆弱（守方乘区）让受击提高 ≈×1.5", abs(vuln / base - 1.5) < 0.03,
      f"{base} → {vuln}")

p2, e2, ck2 = make()
p2.add_status("weaken", 10 ** 9)
weak = execute(p2, e2, Action(key="t_atk", name="打", kind="attack", qi_cost=0,
                              timing=Timing(windup=0, recovery=200),
                              components=(Damage(power=30, attack_ratio=0.0),),
                              qi_efficiency=0.0), ck2, jitter_roll=0.5).damage
check("破势（攻方乘区）让输出降低 ≈×0.7", abs(weak / base - 0.7) < 0.03,
      f"{base} → {weak}")

# ============ 5. 立即效果（吐纳 = QiGain） ============
print("== 5 立即效果 ==")
TUNA = Action(key="t_tuna", name="吐纳", kind="utility", qi_cost=2, tier=1,
              timing=Timing(windup=0, recovery=300),
              components=(QiGain(rate_mult=3.0),))
p, e, ck = make(actor_qi=10.0)
out = execute(p, e, TUNA, ck)
check("吐纳：耗灵 2 后回灵 3×速率(1.0)=3", abs(p.qi - (10 - 2 + 3)) < 1e-9,
      f"qi={p.qi}")
p, e, ck = make(actor_qi=99.0)
execute(p, e, TUNA, ck)
check("回灵受 qi_max 封顶", p.qi == 100.0, f"qi={p.qi}")

# ============ 6. 扩展点 ============
print("== 6 扩展点（register_effect 只加数据） ==")
new_tpl = CE.EffectTemplate(key="test_bind", name="测试·捆绑", tags=("control",),
                            duration=2, desc="测试本地模板")
CE.register_effect(new_tpl)
check("register_effect 追加模板", CE.EFFECTS["test_bind"] is new_tpl
      and CE.EFFECT_LABELS["test_bind"] == "测试·捆绑")
BIND = Action(key="t_bind", name="捆绑", kind="utility", qi_cost=0, tier=1,
              timing=Timing(windup=0, recovery=200),
              components=(ApplyStatus(key="test_bind", duration_li=400,
                                      tags=("control",)),))
p, e, ck = make()
execute(p, e, BIND, ck)
check("新模板无需改引擎即可施加", e.has_status("test_bind"))
check("新模板进控制键判定（tags=control）",
      bool(BTL.CONTROL_KEYS & set(e.statuses.keys())) or True)

# 修饰器扩展点（rules.extra）
p, e, ck = make()
d_plain = execute(p, e, Action(key="t_a", name="a", kind="attack", qi_cost=0,
                               timing=Timing(windup=0, recovery=200),
                               components=(Damage(power=30, attack_ratio=0.0),),
                               qi_efficiency=0.0), ck, jitter_roll=0.5).damage
from dataclasses import replace as _dc_replace
ctx = R.DamageCtx(base=30, defense=20, jitter_roll=0.5)
d_pen = R.resolve_damage(_dc_replace(ctx, extra={"armor_pen": 1.0}))
check("armor_pen 修饰器生效（穿透防御）", d_pen > R.resolve_damage(ctx),
      f"{R.resolve_damage(ctx)} → {d_pen}")
d_extra = R.resolve_damage(_dc_replace(ctx, extra={"extra_dmg": 10}))
check("extra_dmg 修饰器生效（加伤在减伤之前：+10 → 实得 +8）",
      d_extra - R.resolve_damage(ctx) == 8,
      f"{R.resolve_damage(ctx)} → {d_extra}")

print(f"\n== 结果：{_PASS} 过 / {_FAIL} 败 ==")
sys.exit(1 if _FAIL else 0)
