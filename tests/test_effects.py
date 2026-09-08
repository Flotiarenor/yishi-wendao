"""P3.8 效果/状态系统验收测试（✓ 脚本式，风格同 test_gongfa_deep / test_battle）。

覆盖任务书 F 分组（≥25 项）：
  1. 模板注册表：5 内置模板存在/字段合法；by_key；register_effect 追加；EFFECT_LABELS
  2. EffectBag：apply 入袋 / refresh 重置 / stack 叠层封顶 / ignore 不重复 / has·get·remove·clear
  3. tick()：duration-1、到期移除并返回键；多层多效果顺序稳定
  4. EffectInstance to_dict/from_dict 往返一致（含 JSON 序列化）
  5. resolve_damage：平砍/技能/敌攻三种参数与现状公式逐位一致（jitter=1.0 精确断言）
  6. 修饰器：armor_pen（0/0.5/1 边界）、extra_dmg、两者共存按 MODIFIER_ORDER
  7. register_modifier 注册测试修饰器 → 生效且追加到顺序末尾（扩展点）
  8. breath 立即结算：不入袋、回灵 = min(3×regen, 上限)
  9. 四状态效果行为与旧语义一致（root 跳过 / weaken 减半 / evade 分支 / guard 减半）
 10. 兼容 property：guard/enemy_rooted/enemy_weakened/self_evading 派生正确
 11. 回合末清理：本回合效果不泄漏到下一回合
 12. 扩展点（数据即扩展）：register_effect 新模板 + 技能 effect_key → 不改结算代码即可施加
 13. 回归子进程：test_battle(52)/test_gongfa_deep(89)/test_server(69) 均 0 退出

运行：.venv\\Scripts\\python.exe -X utf8 tests\\test_effects.py
"""
import dataclasses
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from content import effects as CE
from content import enemies as EM
from content import skills as SK
from content.ids import CAT_SKILL, make_id as _mkid
from engine import battle as BTL
from engine import effects as EFF

_PASS = 0
_FAIL = 0


def check(name: str, cond: bool, detail: str = ""):
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  ✓ {name} {detail}")
    else:
        _FAIL += 1
        print(f"  ✗ {name} {detail}")


class FakeRng:
    """脚本化随机流（同 test_battle/test_gongfa_deep）。"""

    def __init__(self, roll=0.5, chance=True, randint_lo=True):
        self.roll_v = roll
        self.chance_v = chance
        self.randint_lo = randint_lo
        self.chance_last = None

    def roll(self, salt: str = "") -> float:
        return self.roll_v

    def chance(self, p: float, salt: str = "") -> bool:
        self.chance_last = p
        return self.chance_v

    def randint(self, lo: int, hi: int, salt: str = "") -> int:
        return lo if self.randint_lo else hi

    def choice(self, seq, salt: str = ""):
        return seq[0]

    def weighted_choice(self, items, salt: str = ""):
        return list(items)[0]

    def save(self) -> int:
        return 0

    def restore(self, counter: int):
        pass


def make_battle(enemy_id: int, realm: int = 1, skills=None, qi=None, rng=None):
    e = EM.ENEMIES[enemy_id]
    if skills is None:
        skills = [SK.by_id(SK.LINGLI_CHONGJI), SK.by_id(SK.HUTI_LINGGUANG)]
    ps = BTL.battle_stats(realm)
    if qi is not None:
        ps["qi"] = qi
    return BTL.Battle(ps, skills, e, rng or FakeRng())


# ============ 1. 模板注册表 ============
print("== 1 模板注册表 ==")
check("5 个内置模板存在", all(k in CE.EFFECTS for k in
                              ("root", "weaken", "evade", "guard", "breath")))
check("模板字段合法（duration/apply_key/tags）",
      CE.EFFECTS["breath"].duration == 0 and CE.EFFECTS["breath"].apply_key == "restore_qi"
      and CE.EFFECTS["root"].duration == 1 and CE.EFFECTS["root"].tags == ("control",))
check("默认参数入模板（weaken mult / evade chance / guard mult）",
      CE.EFFECTS["weaken"].params == {"mult": 0.5}
      and CE.EFFECTS["evade"].params == {"chance": 0.5}
      and CE.EFFECTS["guard"].params == {"mult": 0.5})
check("EFFECT_LABELS 键→名正确", CE.EFFECT_LABELS ==
      {"root": "定身", "weaken": "破势", "evade": "闪避", "guard": "护体", "breath": "吐纳"})
check("by_key 命中/未知返回 None", CE.by_key("root") is CE.EFFECTS["root"]
      and CE.by_key("不存在的效果") is None)
check("UTIL_EFFECT_LABELS 由模板 name 生成（含旧四键映射不变）",
      all(BTL.UTIL_EFFECT_LABELS[k] == CE.EFFECT_LABELS[k] for k in
          ("breath", "root", "weaken", "evade")))
new_tpl = CE.EffectTemplate(key="test_bind", name="测试·捆绑", tags=("control",),
                            duration=2, desc="测试本地模板")
EFF.register_effect(new_tpl)
check("register_effect 追加新模板（content 注册表 + 标签同步）",
      CE.EFFECTS["test_bind"] is new_tpl and CE.EFFECT_LABELS["test_bind"] == "测试·捆绑")

# ============ 2. EffectBag 施加/叠层规则 ============
print("== 2 EffectBag ==")
bag = EFF.EffectBag()
inst = bag.apply("guard", duration=5)
check("apply 入袋（参数取模板默认 mult=0.5）",
      bag.has("guard") and inst.duration == 5 and inst.params.get("mult") == 0.5)
inst2 = bag.apply("guard", duration=2)
check("refresh：重置持续、层数保持 1",
      inst2 is inst and inst.duration == 2 and inst.stacks == 1)
EFF.register_effect(CE.EffectTemplate(key="test_stack", name="测试·叠层",
                                      tags=("debuff",), duration=5, max_stacks=3,
                                      stack_rule="stack"))
stbag = EFF.EffectBag()
stbag.apply("test_stack")
a1 = stbag.get("test_stack").stacks            # 第 1 次：1
stbag.apply("test_stack")
a2 = stbag.get("test_stack").stacks            # 第 2 次：2
stbag.apply("test_stack")
stbag.apply("test_stack")                      # 第 4 次：封顶 3 并重置持续
check("stack：逐层 +1、封顶 max_stacks=3 且重置持续",
      (a1, a2, stbag.get("test_stack").stacks) == (1, 2, 3)
      and stbag.get("test_stack").duration == 5)
EFF.register_effect(CE.EffectTemplate(key="test_ign", name="测试·不重复",
                                      tags=("buff",), duration=5,
                                      stack_rule="ignore"))
i1 = bag.apply("test_ign")
i2 = bag.apply("test_ign", duration=3)
check("ignore：已存在不重复施加（持续不被重置）",
      i2 is i1 and i1.duration == 5 and bag.get("test_ign") is i1)
check("apply 参数覆盖模板默认", bag.apply("weaken", duration=3,
                                       params={"mult": 0.8}).params["mult"] == 0.8)
check("未知键 apply → None；duration=0 不入袋", bag.apply("nope") is None
      and bag.apply("breath") is None and not bag.has("breath"))
check("has/get/remove/clear", bag.get("guard").key == "guard"
      and bag.remove("guard") is True and bag.remove("guard") is False
      and not bag.has("guard"))
bag.clear()
check("clear 清空", bag.to_list() == [])

# ============ 3. tick() ============
print("== 3 tick ==")
bag2 = EFF.EffectBag()
bag2.apply("root", duration=1)
bag2.apply("weaken", duration=1)
exp1 = bag2.tick()
check("duration=1 一次 tick 全到期并返回键（顺序稳定）",
      exp1 == ["root", "weaken"] and not bag2.has("root") and not bag2.has("weaken"))
bag3 = EFF.EffectBag()
bag3.apply("root", duration=2)
bag3.apply("weaken", duration=1)
exp_a = bag3.tick()
check("tick：duration-1，未到期保留、到期移除返回",
      exp_a == ["weaken"] and bag3.get("root").duration == 1)
exp_b = bag3.tick()
check("tick：第二回合到期", exp_b == ["root"] and bag3.to_list() == [])

# ============ 4. EffectInstance 序列化 ============
print("== 4 EffectInstance 往返 ==")
ei = EFF.EffectInstance(key="weaken", source="enemy", stacks=2, duration=3,
                        params={"mult": 0.5, "note": "测试"})
d = ei.to_dict()
back = EFF.EffectInstance.from_dict(d)
check("to_dict/from_dict 往返一致",
      back.key == "weaken" and back.source == "enemy" and back.stacks == 2
      and back.duration == 3 and back.params == {"mult": 0.5, "note": "测试"})
check("to_dict 可 JSON 序列化（战报用）", json.loads(json.dumps(d)) == d)
check("from_dict 容忍缺省字段",
      EFF.EffectInstance.from_dict({"key": "root"}).duration == 1
      and EFF.EffectInstance.from_dict({"key": "root"}).params == {})

# ============ 5. resolve_damage 与现状公式逐位一致 ============
print("== 5 resolve_damage ==")
check("MODIFIER_ORDER 初值冻结", EFF.MODIFIER_ORDER == ("armor_pen", "extra_dmg"))
# 平砍参数：atk×1.0 − def×0.4（现状公式）
exp = max(1, round((12 - 3 * 0.4) * 1.0))
check("平砍参数逐位一致（jitter=1.0）",
      EFF.resolve_damage(EFF.DamageCtx(attack=12, attack_ratio=1.0,
                                       defense=3, defense_ratio=0.4, jitter=1.0)) == exp,
      f"→ {exp}")
# 技能参数：power + atk×0.5 − def×0.3，×元素 1.5（现状公式）
exp = max(1, round((32 + 28 * 0.5 - 3 * 0.3) * 1.5 * 1.0))
check("技能参数（元素×1.5）逐位一致",
      EFF.resolve_damage(EFF.DamageCtx(base=32, attack=28, attack_ratio=0.5,
                                       defense=3, defense_ratio=0.3,
                                       element_mult=1.5, jitter=1.0)) == exp,
      f"→ {exp}")
# 敌攻参数：enemy.atk×0.6 − 玩家def×0.3（现状公式）
exp = max(1, round((22 * 0.6 - 7 * 0.3) * 1.0))
check("敌攻参数逐位一致",
      EFF.resolve_damage(EFF.DamageCtx(attack=22, attack_ratio=0.6,
                                       defense=7, defense_ratio=0.3, jitter=1.0)) == exp,
      f"→ {exp}")
for jit in (0.9, 1.1):   # 浮动边界（roll=0.5 → 1.0 已在上面覆盖）
    exp = max(1, round((12 - 3 * 0.4) * jit))
    check(f"平砍 jitter={jit} 一致",
          EFF.resolve_damage(EFF.DamageCtx(attack=12, attack_ratio=1.0,
                                           defense=3, defense_ratio=0.4,
                                           jitter=jit)) == exp)
exp = max(1, round((2 - 3 * 0.4) * 1.0))
check("伤害下限 max(1,…)", EFF.resolve_damage(EFF.DamageCtx(attack=2, attack_ratio=1.0,
                                                            defense=3, defense_ratio=0.4,
                                                            jitter=1.0)) == 1)

# ============ 6. 修饰器 ============
print("== 6 修饰器（armor_pen / extra_dmg）==")
# 基准：v = 20 − 10×0.4 = 16（构造整数避免半分）
def ctx_m(mods, jit=1.0, mult=1.0):
    return EFF.DamageCtx(attack=20, attack_ratio=1.0, defense=10, defense_ratio=0.4,
                         element_mult=mult, jitter=jit, modifiers=mods)

check("armor_pen=0：不变", EFF.resolve_damage(ctx_m({"armor_pen": 0.0})) == 16)
check("armor_pen=0.5：+def×ratio×0.5", EFF.resolve_damage(ctx_m({"armor_pen": 0.5})) == 18)
check("armor_pen=1.0：穿透全部防御", EFF.resolve_damage(ctx_m({"armor_pen": 1.0})) == 20)
check("extra_dmg=10：固定加伤", EFF.resolve_damage(ctx_m({"extra_dmg": 10})) == 26)
both = EFF.resolve_damage(ctx_m({"armor_pen": 0.5, "extra_dmg": 10}))
check("两者共存：先 armor_pen 后 extra_dmg（MODIFIER_ORDER）", both == 28, f"→ {both}")
check("修饰器随元素乘区生效", EFF.resolve_damage(ctx_m({"extra_dmg": 10}, mult=0.5)) == 13)

# ============ 7. register_modifier（扩展点） ============
print("== 7 register_modifier ==")


def _pct(ctx, v, params):
    return v + v * params   # 按当前值加 params 比例


EFF.register_modifier("test_pct", _pct)
check("register_modifier 追加到顺序末尾",
      EFF.MODIFIER_ORDER == ("armor_pen", "extra_dmg", "test_pct"))
check("自定义修饰器生效", EFF.resolve_damage(ctx_m({"test_pct": 0.5})) == 24)   # 16×1.5
tri = EFF.resolve_damage(ctx_m({"armor_pen": 0.5, "extra_dmg": 10, "test_pct": 0.5}))
# 顺序：16 → +2 → +10 → ×1.5 = 42（若 pct 提前则不同）
check("自定义修饰器最后执行（顺序可观测）", tri == 42, f"→ {tri}")

# ============ 8. breath 立即结算 ============
print("== 8 breath（立即结算不入袋）==")
b5 = make_battle(EM.LINGWEN_LANG, realm=1, skills=[SK.by_id(SK.TUNA_SHU)], qi=2)
t5, _, _ = b5.do("skill", SK.TUNA_SHU)
reg = b5.p_qi_regen
expect = 2 + reg - SK.by_id(SK.TUNA_SHU).qi_cost + 3 * reg   # = 2+6−2+18 = 24
check("breath 回灵=3×regen 且叙事含 +N", b5.p_qi == expect and f"灵气 +{3 * reg}" in t5,
      f"qi→{b5.p_qi}（期望{expect}）")
check("breath 不入效果袋", b5.p_bag.to_list() == [] and b5.e_bag.to_list() == [])
b5c = make_battle(EM.LINGWEN_LANG, realm=1, skills=[SK.by_id(SK.TUNA_SHU)], qi=63)
b5c.do("skill", SK.TUNA_SHU)   # 65 − 2 后回灵被封顶 → 65
check("breath 回灵封顶 qi_max", b5c.p_qi == b5c.p_qi_max, f"qi→{b5c.p_qi}")

# ============ 9. 四状态效果行为（与旧语义一致） ============
print("== 9 四状态效果 ==")
# root：敌方本回合跳过
b = make_battle(EM.LINGWEN_LANG, realm=1, skills=[SK.by_id(SK.QINGTENG_CHAN)])
hp0 = b.p_hp
t, ended, _ = b.do("skill", SK.QINGTENG_CHAN)
check("root：敌方本回合被缚不行动", "动弹不得" in t and b.p_hp == hp0 and not ended)
# weaken：敌方本回合伤害减半（敌攻公式独立手算）
base_exp = max(1, round(EM.by_id(EM.CHIYAN_HU).attack * 0.6 - BTL.battle_stats(1)["defense"] * 0.3))
weak_exp = max(1, round(base_exp * 0.5))
b1 = make_battle(EM.CHIYAN_HU, realm=1, skills=[SK.by_id(SK.DIXIAN_SHU)])
b1.do("skill", SK.DIXIAN_SHU)
b2 = make_battle(EM.CHIYAN_HU, realm=1)
b2.do("attack")
check("weaken：敌方本回合伤害减半", (b1.p_hp_max - b1.p_hp) == weak_exp
      and (b2.p_hp_max - b2.p_hp) == base_exp,
      f"破势受{b1.p_hp_max - b1.p_hp}（期望{weak_exp}）/平砍受{b2.p_hp_max - b2.p_hp}")
# evade：50% 落空（钉住概率恰为 0.5，来自模板 params）
rng_ev = FakeRng(chance=True)
b3 = make_battle(EM.LINGWEN_LANG, realm=1, skills=[SK.by_id(SK.YUFENG_SHU)], rng=rng_ev)
t3, _, _ = b3.do("skill", SK.YUFENG_SHU)
check("evade：判定落空 → 无伤 + 概率钉 0.5",
      "堪堪避开" in t3 and b3.p_hp == b3.p_hp_max and rng_ev.chance_last == 0.5)
b4 = make_battle(EM.LINGWEN_LANG, realm=1, skills=[SK.by_id(SK.YUFENG_SHU)],
                 rng=FakeRng(chance=False))
t4, _, _ = b4.do("skill", SK.YUFENG_SHU)
check("evade：判定命中 → 正常受创", b4.p_hp < b4.p_hp_max and "堪堪避开" not in t4)
# guard：防御/防御技 受创减半（同 test_battle 判据3 语义）
b_def = make_battle(EM.CHIYAN_HU, realm=1)
b_def.do("defend")
b_atk = make_battle(EM.CHIYAN_HU, realm=1)
b_atk.do("attack")
d_plain = b_atk.p_hp_max - b_atk.p_hp
check("guard（防御）：受创减半", (b_def.p_hp_max - b_def.p_hp) == max(1, round(d_plain / 2)),
      f"防御受{b_def.p_hp_max - b_def.p_hp} vs 平砍受{d_plain}")
b_sk = make_battle(EM.CHIYAN_HU, realm=1, qi=65)
b_sk.do("skill", SK.HUTI_LINGGUANG)
check("guard（防御技）：受创减半", (b_sk.p_hp_max - b_sk.p_hp) == max(1, round(d_plain / 2)))

# ============ 10. 兼容 property（派生自效果袋） ============
print("== 10 兼容 property ==")
bp = make_battle(EM.LINGWEN_LANG, realm=1)
check("初始四属性全 False", bp.guard is False and bp.enemy_rooted is False
      and bp.enemy_weakened is False and bp.self_evading is False)
bp.p_bag.apply("guard")
check("guard 派生自玩家袋", bp.guard is True and bp.p_bag.has("guard"))
bp.p_bag.remove("guard")
bp.e_bag.apply("root")
bp.e_bag.apply("weaken")
bp.p_bag.apply("evade")
check("enemy_rooted/enemy_weakened/self_evading 派生正确",
      bp.enemy_rooted is True and bp.enemy_weakened is True and bp.self_evading is True)
bp.p_bag.clear()
bp.e_bag.clear()
check("清袋后全 False", bp.guard is False and bp.enemy_rooted is False
      and bp.self_evading is False)
check("effects_data 结构 = 双方列表", bp.effects_data() == {"player": [], "enemy": []})

# ============ 11. 回合末清理：不泄漏到下一回合 ============
print("== 11 回合末清理 ==")
bq = make_battle(EM.LINGWEN_LANG, realm=1, skills=[SK.by_id(SK.QINGTENG_CHAN)])
bq.do("skill", SK.QINGTENG_CHAN)          # T1：root → 敌方跳过
check("T1 回合末 tick 移除 root", bq.e_bag.to_list() == [] and not bq.enemy_rooted)
hp_t1 = bq.p_hp
t2, _, _ = bq.do("attack")                # T2：敌方应正常行动
check("T2 效果不泄漏（敌方正常行动造成伤害）", bq.p_hp < hp_t1, f"HP {hp_t1}→{bq.p_hp}")
bv = make_battle(EM.LINGWEN_LANG, realm=1, skills=[SK.by_id(SK.YUFENG_SHU)])
bv.do("skill", SK.YUFENG_SHU)             # T1：evade → 触发落空分支
check("T1 回合末移除 evade（效果袋空）", bv.p_bag.to_list() == [] and not bv.self_evading)

# ============ 12. 扩展点：新效果/新修饰器只加数据 ============
print("== 12 扩展点（数据即扩展）==")
# 12a 状态效果：注册模板 → 技能 effect_key 引用 → 施加入敌袋（不改结算代码）
sk_bind = dataclasses.replace(SK.by_id(SK.QINGTENG_CHAN), id=_mkid(CAT_SKILL, 210),
                              name="测试·缚灵", effect_key="test_bind")
bb = make_battle(EM.LINGWEN_LANG, realm=1, skills=[sk_bind])
tbb, _, _ = bb.do("skill", sk_bind.id)
bi = bb.e_bag.get("test_bind")
check("新状态模板仅靠技能数据施加（入敌袋，duration=2→tick 后 1）",
      bi is not None and bi.duration == 1 and bi.source == "player"
      and "施加【测试·捆绑】" in tbb)
# 12b 立即效果：注册 duration=0 模板（复用内置 restore_qi）→ 技能数据即可施放
EFF.register_effect(CE.EffectTemplate(key="test_qi", name="测试·畅息", tags=("buff",),
                                      duration=0, apply_key="restore_qi",
                                      params={"regen_mult": 3}))
sk_qi = dataclasses.replace(SK.by_id(SK.TUNA_SHU), id=_mkid(CAT_SKILL, 211),
                            name="测试·吐息", effect_key="test_qi")
bq2 = make_battle(EM.LINGWEN_LANG, realm=1, skills=[sk_qi], qi=2)
bq2.do("skill", sk_qi.id)
check("新立即模板不入袋且回灵（同 restore_qi 语义）",
      bq2.p_qi == 2 + bq2.p_qi_regen - sk_qi.qi_cost + 3 * bq2.p_qi_regen
      and bq2.p_bag.to_list() == [] and bq2.e_bag.to_list() == [])
# 12c 修饰器随攻击技能生效（技能 modifiers 数据 → 伤害变化，结算代码未改）
sk_pen = dataclasses.replace(SK.by_id(SK.LINGLI_CHONGJI), id=_mkid(CAT_SKILL, 212),
                             name="测试·穿透冲击", modifiers={"armor_pen": 1.0})
bp2 = make_battle(EM.LINGWEN_LANG, realm=1, skills=[sk_pen])   # 敌 def=3
hp0 = bp2.e_hp
bp2.do("skill", sk_pen.id)
base = SK.by_id(SK.LINGLI_CHONGJI).power + bp2.p_attack * 0.5 - EM.ENEMIES[EM.LINGWEN_LANG].defense * 0.3
exp_pen = max(1, round((base + EM.ENEMIES[EM.LINGWEN_LANG].defense * 0.3 * 1.0) * 1.0 * 1.0))
check("armor_pen=1.0 随攻击技能结算（穿透全部防御）", (hp0 - bp2.e_hp) == exp_pen,
      f"敌方-{hp0 - bp2.e_hp} vs 期望{exp_pen}")
# 12d 未知效果键：同现状数据层兜底（可施放但不产生效果）
sk_void = dataclasses.replace(SK.by_id(SK.YUFENG_SHU), id=_mkid(CAT_SKILL, 213),
                              name="测试·未知效果", effect_key="不存在的键")
bvd = make_battle(EM.LINGWEN_LANG, realm=1, skills=[sk_void])
qi0 = bvd.p_qi
tvd, ended, _ = bvd.do("skill", sk_void.id)
check("未知效果键兜底：施放无效果不报错", ended is False and bvd.p_qi == qi0 - sk_void.qi_cost
      and bvd.e_bag.to_list() == [] and bvd.p_bag.to_list() == [])

# ============ 13. 回归子进程 ============
print("== 13 回归子进程 ==")
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for name, fname in (("test_battle", "test_battle.py"),
                    ("test_gongfa_deep", "test_gongfa_deep.py"),
                    ("test_server", "test_server.py")):
    run = subprocess.run([sys.executable, "-X", "utf8",
                          os.path.join(root, "tests", fname)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    check(f"{name}.py 子进程 0 退出", run.returncode == 0, f"退出码 {run.returncode}")

print(f"\n== 结果：{_PASS} 过 / {_FAIL} 败 ==")
sys.exit(1 if _FAIL else 0)
