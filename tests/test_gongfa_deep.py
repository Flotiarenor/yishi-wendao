"""P3 功法深层验收测试（纯引擎驱动，确定性：脚本化 Rng 控制随机流）。

覆盖任务书 H1 分组（1~18）：
  1. 理解锁派生（含大境界交界 9/10、13/14）
  2. 参悟校验：未拥有拒 / 未看懂拒 / 天数推进与熟悉度封顶
  3. 熟悉度≥FAM_ENTRY → 可入运转池；< ENTRY 拒装
  4. unlock_fam 前技能不进战斗池；达到后进（同一本功法放主修位对照）
  5. 谱系温和：battle 槽功法（非主修）技能可入池可施放；shenfa 槽同理
  6. 谱系严格：主修位路径 vs battle 槽大成路径
  7. free：灵力冲击/护体灵光无母功法恒在池
  8. utility 四效果（root/weaken/evade/breath）+ 无效果 utility 拒放
  9. 拥有校验：learn 未购拒；buy 后 learn；重复购拒
  10. 战斗使用 → 战斗结束 familiarity 按 PER_USE 增长（含共享技能多母功法）
  11. 槽位：上限 / 类型匹配 / 同功法不占两槽 / 先卸后装
  12. 旧档迁移：无新键存档 → owned/familiarity(FAM_ENTRY) 规则
  13. 吐纳诀永久加成：装/卸主修与否 cultivation_mult 恒含 +5%
  14. 修炼效率公式 root×(1+perm)×(1+main) 组合断言
  15. market：吐纳诀不售；未看懂功法隐藏机制信息
  16. gongfa_detail：看懂前后文本差异
  17. status：运转池槽位块与熟悉度显示不崩
  18. 逆向回归：test_battle.py 全过（本文件末尾子进程重跑）

运行：.venv\\Scripts\\python.exe -X utf8 -m tests.test_gongfa_deep
"""
import math
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from content import actions as CA
from content import enemies as EM
from engine import rules as R
from content import gongfa as G
from content import pills as P
from content import sites as ST
from content import skills as SK
from engine import battle as BTL
from engine import settings as S
from engine.game import Game, combat_skills, cultivation_mult, understandable

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
    """脚本化随机流（同 test_battle）：roll/chance/randint 可控。"""

    def __init__(self, roll=0.5, chance=True, randint_lo=True):
        self.roll_v = roll
        self.chance_v = chance
        self.randint_lo = randint_lo
        self.chance_last = None   # 记录最近一次 chance 被询问的概率（用于钉住阈值，如 evade=0.5）

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


# ---------- 工具 ----------
def new_game(seed: int = 1) -> Game:
    g = Game(seed=seed)
    g.state.player.spirit_stones = 50000  # 测试免经济奔波（buy 需在坊市，新局即坊市）
    return g


def p_of(g: Game):
    return g.state.player


def buy(g: Game, name: str):
    return g.step("buy", item=name, qty=1)


def cw(g: Game, name: str, days: int):
    return g.step("comprehend", gongfa=name, days=days)


def fam_days(target) -> int:
    """闭关参悟到某熟悉度所需整天数（按 FAMILIARITY_PER_DAY 向上取整）。

    期望值一律经此换算，避免把"ENTRY÷PER_DAY"等推导硬编码成魔法天数。
    """
    return max(1, math.ceil(float(target) / S.FAMILIARITY_PER_DAY))


def cw_to(g: Game, name: str, target: int):
    """参悟到熟悉度 ≥ target（按当前熟悉度自动算最少整天数；封顶由引擎负责）。"""
    cur = g.state.player.familiarity.get(G.resolve(name), 0)
    return cw(g, name, fam_days(target - cur))


def learn(g: Game, name: str, slot: str = "main"):
    return g.step("learn", gongfa=name, slot=slot)


def pool_ids(g: Game) -> set:
    """当前战斗动作池里的技能 id 集合（R3：从动作池读，而非旧 available_skills）。"""
    b = g.battle()
    return {a.id for a in b.actions.values() if a.id is not None}


def make_battle(enemy_id: int, realm: int = 1, skills=None, qi=None, rng=None):
    """构造一场战斗（R3 时间轴 Battle）。skills 为 SkillSpec 列表。"""
    e = EM.ENEMIES[enemy_id]
    if skills is None:
        skills = [SK.by_id(SK.LINGLI_CHONGJI), SK.by_id(SK.HUTI_LINGGUANG)]
    ps = BTL.battle_stats(realm)
    if qi is not None:
        ps["qi"] = qi
    acts = list(CA.BASIC_ACTIONS) + [s.action for s in skills]
    return BTL.Battle(ps, acts, e, rng or FakeRng(), battle_id=1,
                      enemy_actions=list(CA.ENEMY_ACTIONS))


def cast(g_or_b, skill_id=None, cmd="attack", windows: int = 8):
    """在战斗里施放一个动作并跑到结束/多轮（R3：队列式）。

    返回 (叙事文本, 是否结束, 结局)。
    """
    b = g_or_b if isinstance(g_or_b, BTL.Battle) else g_or_b.battle()
    key = None
    if skill_id is not None:
        sk = SK.SKILLS.get(skill_id) if isinstance(skill_id, int) else None
        key = sk.key if sk else None
    if key is None:
        key = {"attack": "attack", "defend": "defend",
               "gather": "gather", "flee": "flee"}.get(cmd, cmd)
    texts = []
    for _ in range(windows):
        if b.ended():
            break
        ok, reason = b.submit(key)
        if not ok:
            return (f"（无法施展：{reason}）", b.ended(), b.outcome())
        rep = b.run_window()
        texts.extend(rep.lines)
    return ("\n".join(texts), b.ended(), b.outcome())


# ============ 1. 理解锁派生 ============
print("== 1 理解锁派生 ==")
check("档9 < tier10 → 未看懂", understandable(9, 10) is False)
check("档10 ≥ tier10 → 看懂", understandable(10, 10) is True)
check("档13 < tier14 → 未看懂", understandable(13, 14) is False)
check("档14 ≥ tier14 → 看懂", understandable(14, 14) is True)
check("练气档1 看懂 tier1", understandable(1, 1) is True)

# ============ 2. 参悟校验（判定看 reason/data，不刮文案） ============
print("== 2 参悟校验 ==")
g = new_game(2)
p = p_of(g)
r = cw(g, "炎阳诀", fam_days(S.FAM_ENTRY))
check("未拥有 → 参悟拒（not_owned）", r.ok is False and r.reason == "not_owned"
      and p.familiarity.get(G.YANYANG_JUE) is None)
buy(g, "炎阳诀")
day0 = g.state.day
r = cw_to(g, "炎阳诀", S.FAM_ENTRY)  # 需 fam_days(10)=5 日（PER_DAY=2）→ 熟悉度 10
check("看懂后参悟至入门：ok + 熟悉度=FAM_ENTRY",
      r.ok is True and r.data["fam_after"] == S.FAM_ENTRY
      and r.data["entered"] is True and p.familiarity.get(G.YANYANG_JUE) == S.FAM_ENTRY)
check("参悟消耗真实天数", g.state.day == day0 + fam_days(S.FAM_ENTRY))
exp0 = p.exp
r = cw(g, "炎阳诀", fam_days(S.FAM_MAX * 2))  # 远超所需天数 → 引擎封顶 FAM_MAX
check("熟悉度封顶 FAM_MAX", r.data["fam_after"] == S.FAM_MAX
      and p.familiarity[G.YANYANG_JUE] == S.FAM_MAX)
d1 = g.state.day
r = cw(g, "炎阳诀", fam_days(S.FAM_MAX * 2))
check("大成后再参悟拒（fam_max，不再耗天数）",
      r.ok is False and r.reason == "fam_max" and g.state.day == d1)
check("参悟不动修为", p.exp == exp0)
# 未看懂拒：焚天诀 tier10
buy(g, "焚天诀")
d2 = g.state.day
r = cw(g, "焚天诀", fam_days(S.FAM_ENTRY))
check("未看懂（练气）→ 参悟拒（realm_gate）且不耗天数", r.reason == "realm_gate"
      and p.familiarity.get(G.FENTIAN_JUE) is None and g.state.day == d2)
p.realm_idx = 10
r = cw_to(g, "焚天诀", S.FAM_ENTRY)
check("破境（档10）后可参悟焚天诀", r.ok is True
      and r.data["fam_after"] == S.FAM_ENTRY)

# ============ 3. 入门阈值 ============
print("== 3 入门 → 可入运转池 ==")
g = new_game(3)
p = p_of(g)
cw(g, "吐纳诀", fam_days(S.FAM_ENTRY) - 1)  # 差 1 天：熟悉度 8 < 10（PER_DAY=2）
r = learn(g, "吐纳诀")
check("熟悉度<FAM_ENTRY 拒装（not_entry）",
      r.ok is False and r.reason == "not_entry" and p.main_gongfa is None)
cw_to(g, "吐纳诀", S.FAM_ENTRY)  # 补 1 日 → 10
r = learn(g, "吐纳诀")
check("熟悉度=FAM_ENTRY 入门 → 可装入主修",
      r.ok is True and r.data["slot_kind"] == "main" and p.main_gongfa == G.TUNA_JUE)

# ============ 4. unlock_fam 亮出门槛（主修位对照） ============
print("== 4 unlock_fam 亮出门槛 ==")
g = new_game(4)
p = p_of(g)
p.realm_idx = 10
buy(g, "焚天诀")
cw_to(g, "焚天诀", SK.by_id(SK.YANLIAN_ZHAN).unlock_fam)  # fam10：仅烈焰斩(10) 亮
learn(g, "焚天诀")
g.start_battle(EM.LINGWEN_LANG)
ids = pool_ids(g)
check("fam10：unlock10 烈焰斩在池", SK.YANLIAN_ZHAN in ids)
check("fam10：unlock30 爆炎术不在池", SK.BAOYAN_SHU not in ids)
check("fam10：unlock80 焚天火海不在池", SK.FENTIAN_HUOHAI not in ids)
g.quit_battle()
p.familiarity[G.FENTIAN_JUE] = 80
g.start_battle(EM.LINGWEN_LANG)
ids = pool_ids(g)
check("fam80：三式火法全在池（主修位+温和/严格主修路径）",
      {SK.YANLIAN_ZHAN, SK.BAOYAN_SHU, SK.FENTIAN_HUOHAI} <= ids)
g.quit_battle()

# ============ 5. 谱系温和：battle 槽功法技能可入池可施放 ============
print("== 5 谱系温和（battle/shenfa 槽）==")
g = new_game(5)
p = p_of(g)
buy(g, "撼岳诀")
cw_to(g, "撼岳诀", SK.by_id(SK.SHIFU_JIA).unlock_fam)  # fam 30（unlock_fam 上限）→ 两技全亮
learn(g, "撼岳诀", "battle1")
check("battle 槽装战斗类功法成功", p.battle_gongfa == [G.HANYUE_JUE])
g.start_battle(EM.LINGWEN_LANG)
ids = pool_ids(g)
check("battle 槽功法技能入池（温和）", SK.ZHUIYUE_ZHANG in ids and SK.SHIFU_JIA in ids)
g.rng = FakeRng(roll=0.5, chance=True)
e_hp0 = g.battle().e.hp
r = g.step("battle_action", cmd="skill", skill_id=SK.ZHUIYUE_ZHANG)
check("battle 槽功法技能可实际施放（ok + 敌HP下降）",
      r.ok is True and g.battle() is not None and g.battle().e.hp < e_hp0)
g.quit_battle()
# shenfa 槽功法（御风步法 → 御风术 evade）
buy(g, "御风步法")
cw_to(g, "御风步法", SK.by_id(SK.YUFENG_SHU).unlock_fam)
learn(g, "御风步法", "shenfa")
g.start_battle(EM.LINGWEN_LANG)
check("shenfa 槽功法技能入池（温和·utility）", SK.YUFENG_SHU in pool_ids(g))
g.quit_battle()

# ============ 6. 谱系严格 ============
print("== 6 谱系严格 ==")
# 主修位路径：焚天诀 fam80 在池（已在 4 验证），此处补施放断言
g2 = new_game(6)
p2 = p_of(g2)
p2.realm_idx = 10
buy(g2, "焚天诀")
p2.familiarity[G.FENTIAN_JUE] = 80
learn(g2, "焚天诀")
g2.start_battle(EM.LINGWEN_LANG)
check("strict 技：主修位 + fam80 → 在池",
      SK.FENTIAN_HUOHAI in pool_ids(g2))
r2 = g2.step("battle_action", cmd="skill", skill_id=SK.FENTIAN_HUOHAI)
check("strict 技：焚天火海主修位实际施放（一击击杀）",
      r2.ok is True and r2.data["outcome"] == "win" and not g2.battle_active())
g2.quit_battle()
# 大成路径：庚金杀剑（battle 槽）fam80 vs fam100
g3 = new_game(6)
p3 = p_of(g3)
p3.realm_idx = 14
buy(g3, "庚金杀剑")
p3.familiarity[G.GENJIN_SHAJIAN] = 80
learn(g3, "庚金杀剑", "battle1")
g3.start_battle(EM.LINGWEN_LANG)
ids3 = pool_ids(g3)
check("battle 槽 fam80：gentle 锐金剑气在池（亮）", SK.RUIJIN_JIANQI in ids3)
check("battle 槽 fam80：strict 千剑诀不在池（亮而未放）", SK.QIANJIAN_JUE not in ids3)
g3.quit_battle()
p3.familiarity[G.GENJIN_SHAJIAN] = 90  # 大成线必须=100：90 仍不可施放
g3.start_battle(EM.LINGWEN_LANG)
check("battle 槽 fam90（未大成）：strict 千剑诀仍不在池", SK.QIANJIAN_JUE not in pool_ids(g3))
g3.quit_battle()
p3.familiarity[G.GENJIN_SHAJIAN] = 100  # 大成
g3.start_battle(EM.LINGWEN_LANG)
check("battle 槽 fam100（大成）：strict 千剑诀在池", SK.QIANJIAN_JUE in pool_ids(g3))
g3.quit_battle()

# ============ 7. free 恒在池 ============
print("== 7 free 独立术法 ==")
g = new_game(7)
g.start_battle(EM.LINGWEN_LANG)
ids = pool_ids(g)
check("无任何功法 → free 攻/防恒在池",
      SK.LINGLI_CHONGJI in ids and SK.HUTI_LINGGUANG in ids)
g.rng = FakeRng(roll=0.5, chance=True)
e_hp0 = g.battle().e.hp
r = g.step("battle_action", cmd="skill", skill_id=SK.LINGLI_CHONGJI)
check("free 技能实际可施放（ok + 敌HP下降）",
      r.ok is True and g.battle() is not None and g.battle().e.hp < e_hp0)
g.quit_battle()

# ============ 8. 技能效果在时间轴战斗中生效（R3 重写） ============
print("== 8 技能效果（时间轴） ==")
# root：定身 → 敌方被控制（其前摇动作会被打断 / 行动被推后）
b = make_battle(EM.LINGWEN_LANG, realm=1, skills=[SK.by_id(SK.QINGTENG_CHAN)])
b.p.qi = 100
cast(b, SK.QINGTENG_CHAN, windows=1)
check("root：定身状态进入敌方袋", b.e.has_status("root"), f"{b.e.statuses}")
check("root：状态带时间窗口（until > t）",
      b.e.statuses.get("root", {}).get("until", 0) > b.clock.t)

# guard：防御技 → 自身护体状态
b = make_battle(EM.LINGWEN_LANG, realm=1, skills=[SK.by_id(SK.HUTI_LINGGUANG)])
b.p.qi = 100
cast(b, SK.HUTI_LINGGUANG, windows=1)
check("guard：护体状态进入自身袋", b.p.has_status("guard"), f"{b.p.statuses}")
check("guard：参数含减伤倍率",
      b.p.statuses.get("guard", {}).get("params", {}).get("mult") == 0.5)

# weaken（破势）：进敌方袋 + rules 攻方乘区认识
b = make_battle(EM.LINGWEN_LANG, realm=1, skills=[SK.by_id(SK.DIXIAN_SHU)])
b.p.qi = 100
cast(b, SK.DIXIAN_SHU, windows=1)
check("weaken：破势状态进入敌方袋", b.e.has_status("weaken"))
check("weaken：rules 攻方乘区认识该键",
      R.STATUS_MULT.get("weaken", (None, 0))[0] == "attacker")

# evade：闪避 → 自身袋
b = make_battle(EM.LINGWEN_LANG, realm=1, skills=[SK.by_id(SK.YUFENG_SHU)])
b.p.qi = 100
cast(b, SK.YUFENG_SHU, windows=1)
check("evade：闪避状态进入自身袋", b.p.has_status("evade"))

# breath：吐纳 → 立即回灵（QiGain 组件，不入状态袋）
b = make_battle(EM.LINGWEN_LANG, realm=1, skills=[SK.by_id(SK.TUNA_SHU)], qi=10)
cast(b, SK.TUNA_SHU, windows=1)
check("breath：吐纳立刻回灵（qi 上升）", b.p.qi > 10, f"qi={b.p.qi}")
check("breath：吐纳不入状态袋", not b.p.has_status("breath"))

# 灵气不足 → 队列拒绝（low_qi）
b = make_battle(EM.LINGWEN_LANG, realm=1, qi=1)
ok_ll, reason_ll = b.submit(SK.by_id(SK.LINGLI_CHONGJI).key)
check("灵气不足 → 拒入队（low_qi）", not ok_ll and reason_ll == "low_qi")

# ============ 9. 拥有校验（learn/buy） ============
print("== 9 拥有校验 ==")
g = new_game(9)
p = p_of(g)
r = learn(g, "锐金典")
check("未购功法 → learn 拒（not_owned）", r.reason == "not_owned")
buy(g, "锐金典")
r = buy(g, "锐金典")
check("重复购同功法 → 拒（dup_owned）", r.reason == "dup_owned")
cw_to(g, "锐金典", S.FAM_ENTRY)
r = learn(g, "锐金典")
check("购得+入门后 → learn 成功", r.ok is True
      and r.data["slot_kind"] == "main" and p.main_gongfa == G.RUIJIN_DIAN)

# ============ 10. 战斗使用 → 熟悉度成长（含多母功法） ============
print("== 10 战斗使用成长 ==")
g = new_game(10)
p = p_of(g)
buy(g, "锐金典")
cw_to(g, "锐金典", S.FAM_ENTRY)  # fam 10
learn(g, "锐金典")
g.rng = FakeRng(roll=0.5, chance=True)
g.start_battle(EM.LINGWEN_LANG)
g.step("battle_action", cmd="skill", skill_id=SK.RUIJIN_JIANQI)
guard = 0
while g.battle_active() and guard < 50:  # 平砍收尾确保胜利结算
    g.step("battle_action", cmd="attack")
    guard += 1
check("使用一次功法技后主修熟悉度 +1",
      p.familiarity.get(G.RUIJIN_DIAN) == S.FAM_ENTRY + S.FAMILIARITY_PER_USE,
      f"现 {p.familiarity.get(G.RUIJIN_DIAN)}")
# 共享技能多母功法：锐金剑气 = 锐金典(main) + 庚金杀剑(battle) 都在池 → 各自 +1
g2 = new_game(11)
p2 = p_of(g2)
p2.realm_idx = 14
buy(g2, "锐金典")
buy(g2, "庚金杀剑")
p2.familiarity[G.RUIJIN_DIAN] = 10
p2.familiarity[G.GENJIN_SHAJIAN] = 10
learn(g2, "锐金典", "main")
learn(g2, "庚金杀剑", "battle1")
g2.rng = FakeRng(roll=0.5, chance=True)
g2.start_battle(EM.LINGWEN_LANG)
check("共享技入池（双母功法均满足温和）", SK.RUIJIN_JIANQI in pool_ids(g2))
g2.step("battle_action", cmd="skill", skill_id=SK.RUIJIN_JIANQI)
up = S.FAM_ENTRY + S.FAMILIARITY_PER_USE  # 10 + 1 = 11
check("多母功法：两本在池母功法各 +1",
      p2.familiarity[G.RUIJIN_DIAN] == up and p2.familiarity[G.GENJIN_SHAJIAN] == up,
      f"{p2.familiarity[G.RUIJIN_DIAN]}/{p2.familiarity[G.GENJIN_SHAJIAN]}")

# ============ 11. 槽位 ============
print("== 11 槽位规则 ==")
g = new_game(12)
p = p_of(g)
buy(g, "撼岳诀")
buy(g, "沧澜诀")
buy(g, "焚天诀")
p.realm_idx = 10
cw_to(g, "撼岳诀", S.FAM_ENTRY)
cw_to(g, "沧澜诀", S.FAM_ENTRY)
cw_to(g, "焚天诀", S.FAM_ENTRY)
cw_to(g, "吐纳诀", S.FAM_ENTRY)
r = learn(g, "撼岳诀", "battle5")
check("battle5 越界拒（slot_invalid）",
      r.reason == "slot_invalid" and p.battle_gongfa == [])
r = learn(g, "撼岳诀", "main")
check("类型不匹配：battle 类不可装主修位（type_mismatch）",
      r.reason == "type_mismatch" and p.main_gongfa is None)
r = learn(g, "焚天诀", "battle1")
check("类型不匹配：main 类不可装战斗槽（type_mismatch）",
      r.reason == "type_mismatch" and p.battle_gongfa == [])
r = learn(g, "吐纳诀", "shenfa")
check("类型不匹配：main 类不可装身法槽（type_mismatch）",
      r.reason == "type_mismatch" and p.shenfa_gongfa == [] and p.main_gongfa is None)
learn(g, "撼岳诀", "battle1")
r = learn(g, "沧澜诀", "battle1")
check("槽被占 → 先卸（slot_occupied）", r.reason == "slot_occupied")
r = learn(g, "撼岳诀", "battle2")
check("同功法不占两槽（already_equipped）", r.reason == "already_equipped")
r = learn(g, "沧澜诀", "battle2")
check("装第 2 个战斗槽成功（battle_gongfa 长度 2）",
      r.ok is True and p.battle_gongfa == [G.HANYUE_JUE, G.CANGLAN_JUE])
# 满槽：占满 4 格后学第 5 本战斗功法 → 任一槽都被占而拒（引擎同时拒 battle5 越界）
p.battle_gongfa = [G.HANYUE_JUE, G.CANGLAN_JUE, G.HANYUE_JUE, G.CANGLAN_JUE]
p.realm_idx = 14
buy(g, "庚金杀剑")
cw_to(g, "庚金杀剑", S.FAM_ENTRY)
r = learn(g, "庚金杀剑", "battle1")
check("满槽学第 5 本战斗功法 → slot_occupied", r.reason == "slot_occupied")
r = learn(g, "庚金杀剑", "battle3")
check("满槽：其余槽同样被占拒", r.reason == "slot_occupied" and len(p.battle_gongfa) == 4)
p.battle_gongfa = [G.HANYUE_JUE]
r = g.step("forget", slot="battle1")
check("forget 战斗槽成功", r.ok is True and p.battle_gongfa == [])
# 身法槽 1 上限
p.shenfa_gongfa = [G.YUFENG_BUFA]
buy(g, "踏云步")
cw_to(g, "踏云步", S.FAM_ENTRY)
r = learn(g, "踏云步", "shenfa")
check("身法槽被占 → slot_occupied", r.reason == "slot_occupied")
r = learn(g, "踏云步", "battle1")
check("类型不匹配：shenfa 类不可装战斗槽", r.reason == "type_mismatch")
# learn/forget 不带 slot（旧调用）仍默认主修
buy(g, "锐金典")
cw_to(g, "锐金典", S.FAM_ENTRY)
r = learn(g, "锐金典")
check("learn 无槽位参数 = 主修（兼容旧调用）",
      r.ok is True and r.data["slot_kind"] == "main" and p.main_gongfa == G.RUIJIN_DIAN)
r = g.step("forget")
check("forget 无槽位参数 = 卸主修（兼容旧调用）",
      r.ok is True and r.data["slot_kind"] == "main" and p.main_gongfa is None)

# ============ 12. 旧档迁移 ============
print("== 12 旧档迁移 ==")
ELEMS = {e: 0.5 for e in S.ELEMENTS}


def old_save(main_gid, with_main_key=True, extra_player=None):
    pl = {
        "name": "旧档散修", "spirit_root": "双灵根", "root_mult": 1.0,
        "elements": ELEMS, "realm_idx": 5, "exp": 12.0, "age_years": 40.0,
        "lifespan_years": 200.0, "lifespan_mult": 1.0, "heart_demon": 0,
        "karma": 0, "alive": True, "death_cause": "",
        "spirit_stones": 100, "inventory": {"聚灵丹": 2}, "location": "坊市",
    }
    if with_main_key:
        pl["main_gongfa"] = main_gid
    if extra_player:
        pl.update(extra_player)
    return {"seed": 3, "rng_counter": 0, "day": 0, "turn": 0,
            "player": pl, "chronicle": {"entries": []}}


g = Game(seed=3, load=old_save(G.RUIJIN_DIAN))
p = p_of(g)
check("有主修旧档 → owned 含主修且熟悉度=入门",
      p.owned_gongfa == [G.RUIJIN_DIAN] and p.familiarity.get(G.RUIJIN_DIAN) == S.FAM_ENTRY
      and p.main_gongfa == G.RUIJIN_DIAN)
g = Game(seed=3, load=old_save(None))
p = p_of(g)
check("无主修旧档 → 补吐纳诀入 owned、主修空",
      G.TUNA_JUE in p.owned_gongfa and p.main_gongfa is None and not p.familiarity)
g = Game(seed=3, load=old_save(None, with_main_key=False))
p = p_of(g)
check("无主修键旧档（P0 级）→ 同样补吐纳诀",
      G.TUNA_JUE in p.owned_gongfa and p.main_gongfa is None)
check("迁移后背包键归一为 int id", p.inventory.get(P.JULING) == 2)
# 新键齐全的存档 → 不再走补赠迁移
g = Game(seed=3, load=old_save(G.RUIJIN_DIAN,
        extra_player={"owned_gongfa": [G.YANYANG_JUE],
                      "familiarity": {G.YANYANG_JUE: 40}, "battle_gongfa": [],
                      "shenfa_gongfa": []}))
p = p_of(g)
check("已有新键存档不重复补赠/迁主修", p.owned_gongfa == [G.YANYANG_JUE]
      and p.familiarity.get(G.YANYANG_JUE) == 40 and p.main_gongfa == G.RUIJIN_DIAN)

# ============ 13. 吐纳诀永久加成 ============
print("== 13 吐纳诀永久加成 ==")
g = new_game(13)
p = p_of(g)
p.root_mult = 1.0
base = cultivation_mult(p)
p.familiarity[G.TUNA_JUE] = S.FAM_ENTRY
after_entry = cultivation_mult(p)
check("入门后效率 = 资质 ×1.05", abs(after_entry - 1.05) < 1e-9 and after_entry > base)
learn(g, "吐纳诀")
equipped = cultivation_mult(p)
check("装入主修后仍含 ×1.05（+主修0%不改变）", abs(equipped - 1.05) < 1e-9)
r = g.step("forget")
g_equip = cultivation_mult(p)
check("卸下主修后永久加成仍生效 ×1.05", abs(g_equip - 1.05) < 1e-9)
# 真实状态断言（替代纯文案 check）：闭关实得修为 = 天数×BASE×道基加成
tuna = G.by_id(G.TUNA_JUE)
exp0 = p.exp
g.rng = FakeRng(chance=False)  # 关闭关随机事件，修为增量确定
r = g.step("cultivate", days=30)
gained_exp = (30 * S.BASE_DAILY_EXP
              * (1 + tuna.permanent_bonus) * (1 + tuna.cultivate_bonus))  # 30×1.05=31.5
check("闭关实得修为 = 天数×BASE×道基加成（主修空仍生效）",
      abs(p.exp - exp0 - gained_exp) < 1e-9,
      f"exp+{p.exp - exp0:.2f}（期望 {gained_exp:.2f}）")
check("闭关结果数据含道基加成（perm_bonus）",
      abs(r.data["perm_bonus"] - tuna.permanent_bonus) < 1e-9)

# ============ 14. 修炼效率公式 ============
print("== 14 效率公式组合 ==")
g = new_game(14)
p = p_of(g)
p.root_mult = 2.0
p.familiarity[G.TUNA_JUE] = S.FAM_ENTRY  # perm +0.05
p.main_gongfa = G.FENTIAN_JUE            # main bonus +0.80（直接置位，仅验证公式）
m = cultivation_mult(p)
check("root×(1+perm)×(1+main) = 2×1.05×1.80", abs(m - 3.78) < 1e-9, f"{m}")
p.main_gongfa = None
m2 = cultivation_mult(p)
check("无主修：root×(1+perm) = 2×1.05", abs(m2 - 2.1) < 1e-9, f"{m2}")
p.familiarity.clear()
m3 = cultivation_mult(p)
check("未入门：无任何加成 = root", abs(m3 - 2.0) < 1e-9, f"{m3}")

# ============ 15. market（结构化：读 data 而非文案） ============
print("== 15 market 理解锁展示 ==")
g = new_game(15)
p_of(g).location = ST.SHISHI          # P3.9：货单须身处坊市
md = g.step("market").data
names = [x["name"] for x in md["gongfa"]]
check("吐纳诀不售（market=False 不入货单）", "吐纳诀" not in names)
hanyue = next(x for x in md["gongfa"] if x["id"] == G.HANYUE_JUE)
check("练气档看懂 tier1 功法（skill_count=2）",
      hanyue["readable"] is True and hanyue["skill_count"] == 2)
ft = next(x for x in md["gongfa"] if x["id"] == G.FENTIAN_JUE)
check("tier10 功法对练气档隐藏机制（readable=False 且无技能/加成字段值）",
      ft["readable"] is False and ft["skill_count"] is None
      and ft["cultivate_bonus"] is None)
r = buy(g, "吐纳诀")
check("坊市买不到吐纳诀（not_market）", r.reason == "not_market")
p_of(g).realm_idx = 10
md2 = g.step("market").data
ft2 = next(x for x in md2["gongfa"] if x["id"] == G.FENTIAN_JUE)
check("破境后 market 展开 tier10 详情（skill_count=3）",
      ft2["readable"] is True and ft2["skill_count"] == 3)

# ============ 16. gongfa_detail（结构化：读 data） ============
print("== 16 gongfa_detail ==")
g = new_game(16)
p = p_of(g)
d = g.step("gongfa_detail", gongfa="焚天诀").data
check("未看懂 → 只暴露 名/层级/槽类/来历（无 skills/element）",
      d["readable"] is False and "skills" not in d and "element" not in d
      and bool(d["desc"]) and d["tier_label"] == "筑基级")
p.realm_idx = 10
buy(g, "焚天诀")
d2 = g.step("gongfa_detail", gongfa="焚天诀").data
sk2 = {s["name"]: s for s in d2["skills"]}
check("看懂 → 技能表 + 加成 + 谱系全展示",
      d2["readable"] is True and d2["cultivate_bonus"] == 0.80
      and sk2["烈焰斩"]["unlock_fam"] == 10 and sk2["烈焰斩"]["lit"] is False
      and sk2["焚天火海"]["requirement"] == "strict")
cw_to(g, "焚天诀", S.FAM_ENTRY)
d3 = g.step("gongfa_detail", gongfa="焚天诀").data
sk3 = {s["name"]: s for s in d3["skills"]}
check("fam10 → 烈焰斩已亮 / 爆炎术未亮",
      sk3["烈焰斩"]["lit"] is True and sk3["爆炎术"]["lit"] is False)
lib_ids = [x["id"] for x in g.step("gongfa_detail", gongfa="").data["library"]]
check("书库列表含吐纳诀+焚天诀", G.TUNA_JUE in lib_ids and G.FENTIAN_JUE in lib_ids)
r = g.step("gongfa_detail", gongfa="不存在的功法")
check("查无此功法 → unknown_item", r.reason == "unknown_item")

# ============ 17. status（结构化：读 data；文本仅作渲染冒烟） ============
print("== 17 status ==")
g = new_game(17)
p = p_of(g)
p.root_mult = 1.0                     # 固定资质，效率期望可独立手算
p.familiarity[G.TUNA_JUE] = 40        # ≥FAM_ENTRY：道基被动生效
learn(g, "吐纳诀")                     # 主修（cultivate_bonus=0）
buy(g, "撼岳诀")
p.familiarity[G.HANYUE_JUE] = 30
learn(g, "撼岳诀", "battle2")
sd = g.step("status").data
check("status 数据：运转池三槽",
      sd["pool"]["main"]["id"] == G.TUNA_JUE
      and sd["pool"]["battle"][1]["id"] == G.HANYUE_JUE
      and sd["pool"]["shenfa"]["id"] is None)
owned17 = {o["id"]: o for o in sd["owned"]}
check("status 数据：领悟池含熟悉度与所在槽",
      owned17[G.TUNA_JUE]["familiarity"] == 40
      and owned17[G.TUNA_JUE]["slot"] == "主修位"
      and owned17[G.HANYUE_JUE]["slot"] == "战斗槽2")
tuna = G.by_id(G.TUNA_JUE)
exp_mult = 1.0 * (1 + tuna.permanent_bonus) * (1 + tuna.cultivate_bonus)  # = ×1.05
check("status 数据：修炼效率含道基×1.05",
      abs(sd["cultivation_mult"] - exp_mult) < 1e-9, f"期望 ×{exp_mult:.2f}")
r = g.step("forget", slot="battle2")
sd2 = g.step("status").data
check("卸下后 status 数据：战斗槽2 为空", sd2["pool"]["battle"][1]["id"] is None)
# 渲染层冒烟（语义已由数据断言覆盖，此处只确保文本渲染不崩）
txt = g.step("status").text
check("status 文本渲染含运转池/领悟池标题", "运转池" in txt and "领悟池" in txt)
# 实战回归：重装撼岳诀为战斗槽后在战斗中可放 坠岳掌
learn(g, "撼岳诀", "battle1")
g.rng = FakeRng(roll=0.5, chance=True)
g.start_battle(EM.LINGWEN_LANG)
e_hp0 = g.battle().e.hp
r = g.step("battle_action", cmd="skill", skill_id=SK.ZHUIYUE_ZHANG)
check("战斗列表/施放正常（含 battle 槽技）",
      r.ok is True and g.battle() is not None and g.battle().e.hp < e_hp0)
g.quit_battle()

# ============ 18. 逆向回归：时间轴战斗单测 ============
print("== 18 逆向回归 test_battle_time.py ==")
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
run = subprocess.run([sys.executable, "-X", "utf8",
                      os.path.join(root, "tests", "test_battle_time.py")],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
check("test_battle.py 子进程 0 退出（原 49+ 全过）", run.returncode == 0,
      f"退出码 {run.returncode}")

print(f"\n== 结果：{_PASS} 过 / {_FAIL} 败 ==")
sys.exit(1 if _FAIL else 0)
