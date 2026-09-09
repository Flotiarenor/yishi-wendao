"""效果/状态系统单测（P4-R4 版：时间窗口 + 行为注册表 + 机械效果）。

锁住四件事：
  1. 模板注册表（content/effects.py：展示名/标签/默认参数）
  2. 模板 ↔ engine/status.py 行为表一致（没有"施加后不生效"的孤儿模板）
  3. 四种行为真的生效：damage_mult / hit_negate / push_back / speed_mult
  4. 扩展点：register_effect 只加数据；未知键安全；修饰器 armor_pen/extra_dmg

运行：.venv\\Scripts\\python.exe -X utf8 -m tests.test_effects
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from content import effects as CE
from engine import rules as R
from engine import status as STATUS
from engine.action import (Action, Actor, ApplyStatus, Damage, QiGain, Timing,
                           execute)
from engine.clock import SIDE_ENEMY, SIDE_PLAYER, Clock

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


ATK = Action(key="t_atk", name="打", kind="attack", qi_cost=0, tier=1,
             timing=Timing(windup=0, recovery=200),
             components=(Damage(power=30, attack_ratio=0.0),), qi_efficiency=0.0)


# ============ 1. 模板注册表 ============
print("== 1 模板注册表 ==")
check("7 个内置模板存在", all(k in CE.EFFECTS for k in
                              ("root", "stun", "slow", "weaken", "vulnerable",
                               "guard", "evade")))
check("root 带 control 标签", CE.EFFECTS["root"].tags == ("control",))
check("slow 带 debuff 标签且默认降速 0.7",
      CE.EFFECTS["slow"].tags == ("debuff",)
      and CE.EFFECTS["slow"].params == {"speed_mult": 0.70})
check("guard 默认参数 mult=0.5", CE.EFFECTS["guard"].params == {"mult": 0.5})
check("evade 默认参数 chance=0.5", CE.EFFECTS["evade"].params == {"chance": 0.5})
check("EFFECT_LABELS 键→名正确",
      CE.EFFECT_LABELS["root"] == "定身" and CE.EFFECT_LABELS["stun"] == "晕眩"
      and CE.EFFECT_LABELS["slow"] == "迟钝" and CE.EFFECT_LABELS["vulnerable"] == "脆弱")
check("by_key 命中/未知返回 None", CE.by_key("root") is CE.EFFECTS["root"]
      and CE.by_key("不存在") is None)

# ============ 2. 模板 ↔ 行为表一致（关键契约） ============
print("== 2 模板 ↔ 行为表一致 ==")
unknown = [k for k in CE.EFFECTS if k not in STATUS.known_keys()]
check("每个模板都有引擎行为（无'施加后不生效'的孤儿模板）", not unknown, f"孤儿：{unknown}")
check("行为表覆盖控制键", STATUS.CONTROL_KEYS == frozenset({"root", "stun"}),
      str(STATUS.CONTROL_KEYS))
check("未知状态键乘区中性且不报错", R.status_mult({"totally_unknown": {}}) == (1.0, 1.0))

# ============ 3. 状态施加与时间窗口 ============
print("== 3 状态施加与时间窗口 ==")
ROOT = Action(key="t_root", name="定身击", kind="utility", qi_cost=0, tier=1,
              timing=Timing(windup=0, recovery=200),
              components=(ApplyStatus(key="root", duration_li=500,
                                      tags=("control",)),))
p, e, ck = make()
execute(p, e, ROOT, ck)
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

# ============ 4. damage_mult：weaken / vulnerable / guard ============
print("== 4 伤害乘区 ==")
p0, e0, ck0 = make()
base = execute(p0, e0, ATK, ck0, jitter_roll=0.5).damage

p1, e1, ck1 = make()
e1.add_status("vulnerable", 10 ** 9, 1, {"mult": 1.5})
vuln = execute(p1, e1, ATK, ck1, jitter_roll=0.5).damage
check("脆弱（守方乘区）受击 ×1.5", abs(vuln / base - 1.5) < 0.03, f"{base} → {vuln}")

p2, e2, ck2 = make()
p2.add_status("weaken", 10 ** 9, 1, {"mult": 0.7})
weak = execute(p2, e2, ATK, ck2, jitter_roll=0.5).damage
check("破势（攻方乘区）输出 ×0.7", abs(weak / base - 0.7) < 0.03, f"{base} → {weak}")

p3, e3, ck3 = make()
e3.add_status("guard", 10 ** 9, 1, {"mult": 0.5})
g = execute(p3, e3, ATK, ck3, jitter_roll=0.5).damage
check("护体（守方乘区）受创 ×0.5", abs(g / base - 0.5) < 0.03, f"{base} → {g}")

p4, e4, ck4 = make()
e4.add_status("guard", 10 ** 9, 1, {"mult": 0.25})
g2 = execute(p4, e4, ATK, ck4, jitter_roll=0.5).damage
check("护体倍率取 params（0.25 覆盖默认 0.5）", abs(g2 / base - 0.25) < 0.03,
      f"{base} → {g2}")

# ============ 5. hit_negate：闪避 ============
print("== 5 闪避 ==")
p, e, ck = make()
e.add_status("evade", 10 ** 9, 1, {"chance": 0.5})
miss = execute(p, e, ATK, ck, jitter_roll=0.5, hit_roll=0.0).damage
p, e, ck = make()
e.add_status("evade", 10 ** 9, 1, {"chance": 0.5})
hit = execute(p, e, ATK, ck, jitter_roll=0.5, hit_roll=0.99).damage
check("闪避：命中判定落空 → 0 伤害", miss == 0, f"{miss}")
check("闪避：命中判定未落空 → 正常伤害", hit == base, f"{hit} vs {base}")
p, e, ck = make()
p.add_status("evade", 10 ** 9, 1, {"chance": 1.0})
p, e, ck2 = make()
out = execute(p, e, ATK, ck2, jitter_roll=0.5, hit_roll=0.0).damage
check("闪避只保护持有者自己（未持有时照常受击）", out == base, f"{out} vs {base}")

# ============ 6. push_back：定身 / 晕眩 ============
print("== 6 控制推后 ==")
p, e, ck = make()
before = ck.next_t("e")
execute(p, e, ROOT, ck)
check("定身：敌方 next_t +300（默认）", ck.next_t("e") == before + 300,
      f"{before} → {ck.next_t('e')}")
STUN = Action(key="t_stun", name="晕", kind="utility", qi_cost=0, tier=1,
              timing=Timing(windup=0, recovery=200),
              components=(ApplyStatus(key="stun", duration_li=500,
                                      tags=("control",), params={"push_li": 800}),))
p, e, ck = make()
before = ck.next_t("e")
execute(p, e, STUN, ck)
check("晕眩：推后量取 params（800）", ck.next_t("e") == before + 800,
      f"{before} → {ck.next_t('e')}")
p, e, ck = make()
before = ck.next_t("e")
execute(p, e, GUARD, ck)          # 护体是自身 buff，不该推后敌方
check("非控制状态不推后 next_t", ck.next_t("e") == before)

# ============ 7. speed_mult：迟钝 ============
print("== 7 迟钝 ==")
p, e, ck = make()
p.add_status("slow", 10 ** 9, 1, {"speed_mult": 0.5})
out = execute(p, e, ATK, ck)
check("迟钝：有效速度 ×0.5 → 动作耗时翻倍", out.end_t == 400, f"end_t={out.end_t}")
check("Actor.effective_speed 反映迟钝", abs(p.effective_speed() - 0.5) < 1e-9,
      f"{p.effective_speed()}")

# ============ 8. 立即效果（吐纳 = QiGain） ============
print("== 8 立即效果 ==")
TUNA = Action(key="t_tuna", name="吐纳", kind="utility", qi_cost=2, tier=1,
              timing=Timing(windup=0, recovery=300),
              components=(QiGain(rate_mult=3.0),))
p, e, ck = make(actor_qi=10.0)
execute(p, e, TUNA, ck)
check("吐纳：耗灵 2 后回灵 3×速率(1.0)=3", abs(p.qi - (10 - 2 + 3)) < 1e-9, f"qi={p.qi}")
p, e, ck = make(actor_qi=99.0)
execute(p, e, TUNA, ck)
check("回灵受 qi_max 封顶", p.qi == 100.0, f"qi={p.qi}")

# ============ 9. 扩展点 ============
print("== 9 扩展点 ==")
new_tpl = CE.EffectTemplate(key="test_bind", name="测试·捆绑", tags=("control",),
                            default_li=400, desc="测试本地模板")
CE.register_effect(new_tpl)
check("register_effect 追加模板", CE.EFFECTS["test_bind"] is new_tpl
      and CE.EFFECT_LABELS["test_bind"] == "测试·捆绑")
BIND = Action(key="t_bind", name="捆绑", kind="utility", qi_cost=0, tier=1,
              timing=Timing(windup=0, recovery=200),
              components=(ApplyStatus(key="test_bind", duration_li=400,
                                      tags=("control",)),))
p, e, ck = make()
execute(p, e, BIND, ck)
check("新模板无需改引擎即可施加（进敌方袋）", e.has_status("test_bind"))
check("但未注册行为的新模板不产生机械效果（乘区中性）",
      R.status_mult({"test_bind": {}}) == (1.0, 1.0))

from dataclasses import replace as _dc_replace
p, e, ck = make()
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