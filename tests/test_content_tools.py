"""内容工具单测（内容校验器 + 技能生成器）。

覆盖：
  1. content_check：现有内容 0 错误；坏数据能被抓出来（元素/品阶/引用/概率/条件…）
  2. gen_skill：draft 解析/校验/构造；现有 21 技能往返无损；生成技能能真打；
     随机生成全部合法；emit_code 可被 compile()
  3. 三条路（手写 / AI 起草 / 随机）共用同一套校验

运行：.venv\\Scripts\\python.exe -X utf8 -m tests.test_content_tools
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from content import actions as CA
from content import enemies as EM
from content import gongfa as G
from content import ids as IDS
from content import pills as P
from content import sites as ST
from content import skills as SK
from engine import battle as BTL
from engine.action import Action, ApplyStatus, Damage, Timing
from engine.rng import Rng
from tools import content_check as CC
from tools import gen_skill as GS

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


def has_error(issues):
    return any(i.severity == CC.ERROR for i in issues)


def _raises(fn) -> bool:
    try:
        fn()
        return False
    except Exception:
        return True


def _compiles(code: str) -> bool:
    try:
        compile(code, "<gen_skill>", "exec")
        return True
    except SyntaxError:
        return False


# ============================================================
print("== 1 内容校验器 ==")
issues = CC.check_content()
errs = [i for i in issues if i.severity == CC.ERROR]
warns = [i for i in issues if i.severity == CC.WARN]
check("现有内容 0 错误", not errs, f"{errs[:3]}")
print(f"  （当前 {len(warns)} 条警告：效果无消费者 / demo 动作孤儿等，属已知问题）")
check("校验器能报出 guard/evade 无引擎消费者（回归护栏）",
      any("guard" in i.message or "evade" in i.message for i in warns))
check("id 字面量扫描可用", len(CC.scan_id_literals()) >= 20,
      f"{len(CC.scan_id_literals())}")
check("settings 校验不报错", not has_error([i for i in issues if i.where == "settings"]))

# 坏数据：动作字段
bad = Action(key="坏键", name="坏", kind="nope", qi_cost=-1, tier=9,
             timing=Timing(windup=-5, recovery=200),
             components=(Damage(power=-1, attack_ratio=-2, element="雷"),))
bout = []
CC.check_action(bad, "synthetic", bout)
msgs = " ".join(i.message for i in bout)
check("坏动作：key/kind/qi_cost/tier/timing/element 全被抓",
      all(k in msgs for k in ("key", "kind", "qi_cost", "tier", "windup", "element")),
      msgs)

# 坏数据：跨引用
bad_gf = G.Gongfa(id=IDS.make_id(IDS.CAT_GONGFA, 999), name="坏功法", slot_type="nope",
                  element="雷", tier=7, price=-1, cultivate_bonus=-1,
                  skill_ids=[9999999, 9999999])
gout = []
CC.check_gongfa(bad_gf, "synthetic_gf", gout)
gmsgs = " ".join(i.message for i in gout)
check("坏功法：槽位/元素/引用/重复全被抓",
      all(k in gmsgs for k in ("slot_type", "element", "不存在", "重复")), gmsgs)

bad_site = ST.Site(id=IDS.make_id(IDS.CAT_SITE, 99), name="坏地", desc="",
                   realm_req=0, days_cost=0, stone=(9, 1), danger=2.0,
                   pill_drops={9999999: 5.0})
sout = []
CC.check_site(bad_site, "synthetic_site", sout)
smsgs = " ".join(i.message for i in sout)
check("坏地点：门槛/耗时/区间/危险/掉落全被抓",
      all(k in smsgs for k in ("realm_req", "days_cost", "stone", "danger", "不存在")), smsgs)

bad_enemy = EM.Enemy(id=IDS.make_id(IDS.CAT_ENEMY, 999), name="坏敌", site_id=9999999,
                     realm_idx=99, element="雷", hp=0, attack=-1, defense=0, speed=-1,
                     loot_stones=(5, 1), loot_pills={9999999: 2.0})
eout = []
CC.check_enemy(bad_enemy, "synthetic_enemy", eout)
emsgs = " ".join(i.message for i in eout)
check("坏敌人：归属/档位/元素/数值/掉落全被抓",
      all(k in emsgs for k in ("site_id", "realm_idx", "element", "hp", "attack", "loot")), emsgs)

# ============================================================
print("== 2 技能生成器：draft / 校验 ==")
d = GS.SkillDraft(name="测试斩", element="火", kind="attack", power=40, tier=2,
                  qi_cost=0, requirement="free",
                  effects=[{"type": "status", "key": "vulnerable", "duration_li": 400,
                            "tags": ["debuff"]}],
                  conditions=["target_has:weaken"])
check("合法 draft 0 错误", not has_error(GS.validate_draft(d)),
      [i.message for i in GS.validate_draft(d)])
spec = GS.build_skill(d)
check("build_skill 自动分配 30 段 id", spec.id == GS.next_free_id(), f"{spec.id}")
check("build_skill 键规范", spec.key == f"sk{spec.id}")
check("draft→skill→draft 幂等",
      GS.draft_from_skill(GS.build_skill(GS.draft_from_skill(spec))).to_dict()
      == GS.draft_from_skill(spec).to_dict())

for label, bad_draft in (
    ("name 空", GS.SkillDraft(name="", element="火")),
    ("元素非法", GS.SkillDraft(name="x", element="雷")),
    ("品阶非法", GS.SkillDraft(name="x", tier=9)),
    ("gentle 无母功法", GS.SkillDraft(name="x", requirement="gentle")),
    ("条件非法", GS.SkillDraft(name="x", conditions=["bogus:1"])),
    ("效果类型非法", GS.SkillDraft(name="x", effects=[{"type": "nope"}])),
    ("id 撞车", GS.SkillDraft(name="x", id=next(iter(SK.SKILLS)))),
):
    check(f"坏 draft 被抓：{label}", has_error(GS.validate_draft(bad_draft)),
          [i.message for i in GS.validate_draft(bad_draft)])

check("draft_from_dict 拒绝未知字段",
      _raises(lambda: GS.draft_from_dict({"name": "x", "nope": 1})))
check("draft_from_dict 拒绝坏类型",
      _raises(lambda: GS.draft_from_dict({"name": "x", "tier": "高"})))


# 现有 21 技能往返无损
bad_rt = []
for s in sorted(SK.SKILLS.values(), key=lambda x: x.id):
    rebuilt = GS.build_skill(GS.draft_from_skill(s))
    a, b = s.action, rebuilt.action
    if (a.key, a.name, a.kind, a.qi_cost, a.tier, a.timing, a.qi_efficiency,
        a.duration_weight, a.components, s.requirement, s.unlock_fam) != \
       (b.key, b.name, b.kind, b.qi_cost, b.tier, b.timing, b.qi_efficiency,
        b.duration_weight, b.components, rebuilt.requirement, rebuilt.unlock_fam):
        bad_rt.append(s.name)
check("21 个现有技能 draft 往返无损", not bad_rt, str(bad_rt))

# 生成技能真能打
atk = GS.build_skill(GS.SkillDraft(name="测试斩", element="火", kind="attack",
                                   power=40, tier=2, qi_cost=0, requirement="free"))
b = BTL.Battle(BTL.battle_stats(1), list(CA.BASIC_ACTIONS) + [atk.action],
               EM.by_id(EM.LINGWEN_LANG), Rng(1), battle_id=1,
               enemy_actions=list(CA.ENEMY_ACTIONS))
ok, reason = b.submit(atk.key)
rep = b.run_window()
check("生成的攻击技能可入队执行", ok, reason)
check("生成的攻击技能造成伤害", b.e.hp < b.e.hp_max, f"{b.e.hp}")

ctrl = GS.build_skill(GS.SkillDraft(name="测试缚", element="无", kind="utility",
                                    requirement="free",
                                    effects=[{"type": "status", "key": "root",
                                              "duration_li": 500, "tags": ["control"]}]))
b2 = BTL.Battle(BTL.battle_stats(1), list(CA.BASIC_ACTIONS) + [ctrl.action],
                EM.by_id(EM.LINGWEN_LANG), Rng(2), battle_id=1,
                enemy_actions=list(CA.ENEMY_ACTIONS))
b2.submit(ctrl.key)
b2.run_window()
check("生成的辅助技能把状态施加到敌人", b2.e.has_status("root"), f"{b2.e.statuses}")

# ============================================================
print("== 3 技能生成器：随机生成（P9 铺垫） ==")
rng = Rng(2026)
drafts = [GS.random_draft(rng) for _ in range(40)]
all_ok = True
for i, dd in enumerate(drafts):
    iv = GS.validate_draft(dd)
    if has_error(iv):
        all_ok = False
        print(f"    随机 #{i} {dd.name} 非法：{[x.message for x in iv if x.severity == CC.ERROR]}")
check("40 份随机 draft 全部 0 错误", all_ok)
check("随机 draft 覆盖三种 kind",
      len({d.kind for d in drafts}) == 3, str({d.kind for d in drafts}))
check("随机 draft 覆盖多个元素",
      len({d.element for d in drafts}) >= 3, str({d.element for d in drafts}))
built = [GS.build_skill(d) for d in drafts]
check("随机 draft 全部可构造为 SkillSpec", all(s.id and s.key for s in built))
code = GS.emit_code(GS.assign_ids([drafts[0]])[0])
check("emit_code 可被 compile()", _compiles(code), code[:80])
check("emit_code 含 _sk( 与技能名", "_sk(" in code and drafts[0].name in code)
import json as _json  # noqa: E402
json_txt = GS._emit_drafts(drafts[:3], "json")
check("emit json 可反解析回 draft",
      len([GS.draft_from_dict(o) for o in _json.loads(json_txt)]) == 3)

print(f"\n== 结果：{_PASS} 过 / {_FAIL} 败 ==")
sys.exit(1 if _FAIL else 0)
