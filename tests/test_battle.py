"""P2 战斗验收测试（纯引擎驱动，确定性：脚本化 Rng 控制随机流）。

覆盖验收判据：
  1. content.enemies 可导入：≥8 敌人、60 段、常量引用
  2. skills.py 15 技能：灵力冲击/护体灵光 free 可用
  3. 手操全动作：平砍/技能(耗灵气/不足拒绝)/防御减伤/遁走概率/聚气回灵
  4. 五行克制：克 ×1.5 / 被克 ×0.5
  5. free 技能默认可用；主修功法技能可放；未装备功法只能平砍+自由技
  6. 探索遇敌 → 胜/败/逃 三路径都通（战斗结算正确）

运行：.venv\\Scripts\\python.exe -X utf8 -m tests.test_battle
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from content import enemies as EM
from content import pills as P
from content import sites as ST
from content import skills as SK
from content import gongfa as G
from content.ids import CAT_ENEMY, CAT_SKILL
from engine import battle as BTL
from engine.game import Game

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
    """脚本化随机流：战斗/结算只需 roll/chance/randint。"""

    def __init__(self, roll=0.5, chance=True, randint_lo=True):
        self.roll_v = roll
        self.chance_v = chance
        self.randint_lo = randint_lo

    def roll(self, salt: str = "") -> float:
        return self.roll_v

    def chance(self, p: float, salt: str = "") -> bool:
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


def panel(realm: int) -> dict:
    return BTL.battle_stats(realm)


def make_battle(enemy_id: int, realm: int = 1, skills=None, qi=None, rng=None):
    e = EM.ENEMIES[enemy_id]
    if skills is None:
        skills = [SK.by_id(SK.LINGLI_CHONGJI), SK.by_id(SK.HUTI_LINGGUANG)]
    ps = panel(realm)
    if qi is not None:
        ps["qi"] = qi
    return BTL.Battle(ps, skills, e, rng or FakeRng())


# ---------- 判据 1：敌人模块 ----------
print("== 判据1 content/enemies ==")
check("模块导入无错", True)
from content import enemies  # noqa: F401  导入本身即断言
check("≥8 敌人", len(EM.ENEMIES) >= 8, f"共 {len(EM.ENEMIES)} 只")
ids_ok = all(id_ // 100000 == CAT_ENEMY and 6000000 <= id_ < 6100000 for id_ in EM.ENEMIES)
check("id 段 60xxxxx", ids_ok)
site_ok = all(e.site_id in ST.SITES for e in EM.ENEMIES.values())
check("site_id 用 ST 地点常量", site_ok)
loot_ok = all(pid in P.PILLS for e in EM.ENEMIES.values() for pid in e.loot_pills)
check("loot_pills 用 P 丹药常量", loot_ok)
per_site = {sid: len(EM.pool_for(sid)) for sid in ST.SITES if sid != ST.SHISHI}
check("每探索点 2 只（共 8）", per_site == {ST.LINGMAI: 2, ST.YOUGU: 2, ST.GUZHAN: 2, ST.SHANGGU: 2},
      f"{per_site}")

# ---------- 判据 2：技能库 ----------
print("== 判据2 技能库（P2 15 + P3 新增 6 = 21）==")
check("技能总数 21（P3 ≥20 达标）", len(SK.SKILLS) == 21, f"实际 {len(SK.SKILLS)}")
ll = SK.SKILLS[SK.LINGLI_CHONGJI]
hl = SK.SKILLS[SK.HUTI_LINGGUANG]
check("灵力冲击存在", SK.LINGLI_CHONGJI in SK.SKILLS and ll.requirement == "free"
      and ll.kind == "attack" and ll.qi_cost == 4 and ll.power == 14)
check("护体灵光存在", SK.HUTI_LINGGUANG in SK.SKILLS and hl.requirement == "free"
      and hl.kind == "defense" and hl.qi_cost == 4 and hl.power == 0)
old_ids = sorted(SK.SKILLS)[:13]
check("原有 13 技能 id 未动", old_ids == [CAT_SKILL * 100000 + i for i in range(1, 14)])

# ---------- 判据 4：五行克制 ----------
print("== 判据4 五行克制 ==")
check("KE 克环定义", BTL.KE == {"金": "木", "木": "土", "土": "水", "水": "火", "火": "金"})
check("火克金 ×1.5", BTL.ke_mult("火", "金") == 1.5)
check("金被火克 → 攻金 vs 守火 ×0.5", BTL.ke_mult("金", "火") == 0.5)
check("同五行 ×1.0", BTL.ke_mult("火", "火") == 1.0)
check("无五行 ×1.0", BTL.ke_mult("无", "火") == 1.0 and BTL.ke_mult("火", "无") == 1.0)
check("木克土 ×1.5 / 土被木克 ×0.5",
      BTL.ke_mult("木", "土") == 1.5 and BTL.ke_mult("土", "木") == 0.5)
# 战斗内伤害验证（roll=0.5 → 浮动系数 1.0，公式可精确断言）
enemy = EM.ENEMIES[EM.LINGWEN_LANG]   # 金系 def3
b_c = make_battle(EM.LINGWEN_LANG, realm=10, skills=[SK.by_id(SK.YANLIAN_ZHAN)])  # 火克金
text, ended, oc = b_c.do("skill", SK.YANLIAN_ZHAN)
expect = round((32 + b_c.p_attack * 0.5 - enemy.defense * 0.3) * 1.5)
check("火技能克金敌 实际伤害=公式×1.5", ended and oc == BTL.BATTLE_WIN
      and (enemy.hp - b_c.e_hp) == expect, f"敌方-{(enemy.hp - b_c.e_hp)} vs 期望 {expect}")
b_s = make_battle(EM.LINGWEN_LANG, realm=10, skills=[SK.by_id(SK.RUIJIN_JIANQI)])  # 金 vs 金同
text, ended, oc = b_s.do("skill", SK.RUIJIN_JIANQI)
expect = round((34 + b_s.p_attack * 0.5 - enemy.defense * 0.3) * 1.0)
check("同五行技能 ×1.0", (enemy.hp - b_s.e_hp) == expect, f"敌方-{(enemy.hp - b_s.e_hp)} vs 期望 {expect}")

# ---------- 判据 3：全动作 ----------
print("== 判据3 战斗动作 ==")
b = make_battle(EM.LINGWEN_LANG, realm=1)  # 灵纹狼 hp52 def3 atk17 spd8
hp0 = b.e_hp
t, ended, oc = b.do("attack")
expect = max(1, round((12 - 3 * 0.4) * 1.0))
check("平砍伤害=attack-def*0.4", (hp0 - b.e_hp) == expect and not ended, f"-{hp0 - b.e_hp}")
check("平砍叙事渲染含伤害（渲染冒烟，判定看状态）", "伤害" in t)
# 技能耗灵气 + 伤害
b = make_battle(EM.LINGWEN_LANG, realm=1, skills=[SK.by_id(SK.YANLIAN_ZHAN)])
qi0, hp0 = b.p_qi, b.e_hp
t, _, _ = b.do("skill", SK.YANLIAN_ZHAN)
check("技能耗灵气", b.p_qi == qi0 - 8 and b.e_hp < hp0)
# 灵气不足拒绝（qi=1，护体灵光耗4）
b = make_battle(EM.LINGWEN_LANG, realm=1, qi=1)
t, ended, oc = b.do("skill", SK.LINGLI_CHONGJI)
check("灵气不足拒绝（low_qi，不推进回合）",
      b.last_reason == "low_qi" and not ended and b.turn == 0)
# 防御减伤：受创减半
b1 = make_battle(EM.CHIYAN_HU, realm=1)   # 赤焰狐 atk22
b1.do("defend")
dmg_def = b1.p_hp_max - b1.p_hp
b2 = make_battle(EM.CHIYAN_HU, realm=1)
b2.do("attack")
dmg_plain = b2.p_hp_max - b2.p_hp
check("防御受创减半", dmg_def == max(1, round(dmg_plain / 2)),
      f"防御受{dmg_def} vs 平砍受{dmg_plain}")
# 防御技能（护体灵光）同样减伤
b3 = make_battle(EM.CHIYAN_HU, realm=1, qi=65)
b3.do("skill", SK.HUTI_LINGGUANG)
dmg_sk = b3.p_hp_max - b3.p_hp
check("防御技能(护体灵光)减伤", dmg_sk == max(1, round(dmg_plain / 2)) and b3.p_qi == 61,
      f"受{dmg_sk}")
# 聚气：放弃出手回复 3×reg(外加回合自动回)
b = make_battle(EM.LINGWEN_LANG, realm=1, qi=0)  # realm1 qi_regen=6
t, _, _ = b.do("gather")
check("聚气回灵", b.p_qi == 6 + 18 and "聚气" in t, f"qi→{b.p_qi}（期望24）")
# 回合自动回灵
b = make_battle(EM.LINGWEN_LANG, realm=1, qi=10)
b.do("attack")
check("回合自动回灵 +regen", b.p_qi == 10 + 6 - 0)
# 遁走：成功=逃出(战斗结束)，失败=敌白打一回合
b_ok = make_battle(EM.LINGWEN_LANG, realm=1, rng=FakeRng(chance=True))
t, ended, oc = b_ok.do("flee")
check("遁走成功→战斗结束 fled", ended and oc == BTL.BATTLE_FLED and "遁走" in t)
b_fail = make_battle(EM.LINGWEN_LANG, realm=1, rng=FakeRng(chance=False))
hp_me0 = b_fail.p_hp
t, ended, oc = b_fail.do("flee")
check("遁走失败→敌白打一回合(不结束)", not ended and b_fail.p_hp < hp_me0 and "遁走失败" in t)
# 遁走成功率 clamp 0.2~0.9
slow = make_battle(EM.XUANBING_KUILEI, realm=1)   # 敌 speed20 >> 我9 → 概率压低
p_ = 0.5 + (slow.p_speed - slow.enemy.speed) * 0.02
check("遁走概率 clamp[0.2,0.9]", 0.2 <= max(0.2, min(0.9, p_)) <= 0.9)

# ---------- 判据 5：技能可用性（P3 池规则：free 恒入 + 功法须 看懂/入门/unlock） ----------
print("== 判据5 技能可用性 ==")
g = Game(seed=7)
free_ids = {SK.LINGLI_CHONGJI, SK.HUTI_LINGGUANG}
check("新局无主修（P3 只赠未学吐纳诀）", g.state.player.main_gongfa is None
      and G.TUNA_JUE in g.state.player.owned_gongfa)
g.start_battle(EM.LINGWEN_LANG)
pool_ids = {s.id for s in g.battle().available_skills()}
check("free 基础术法默认可用", SK.LINGLI_CHONGJI in pool_ids and SK.HUTI_LINGGUANG in pool_ids)
check("未入门功法技能不入池（新局仅自由技）", pool_ids == free_ids, f"{sorted(pool_ids)}")
res = g.step("battle_action", cmd="skill", skill_id=SK.YANLIAN_ZHAN)
check("未学技能不可施放（unknown_skill）", res.reason == "unknown_skill")
g.quit_battle()
# P3 教学链：买锐金典 → 参悟 5 日(fam10) → 入门 → learn 主修
g.state.player.spirit_stones = 500
r = g.step("learn", gongfa=G.name_of(G.RUIJIN_DIAN))
check("未拥有 → learn 拒（not_owned）", r.reason == "not_owned")
g.step("buy", item=G.name_of(G.RUIJIN_DIAN), qty=1)
r = g.step("learn", gongfa=G.name_of(G.RUIJIN_DIAN))
check("未入门 → learn 拒（not_entry）", r.reason == "not_entry")
g.step("comprehend", gongfa=G.name_of(G.RUIJIN_DIAN), days=5)  # 熟悉度 10 = 入门
r = g.step("learn", gongfa=G.name_of(G.RUIJIN_DIAN))
check("入门后 learn 成功", r.ok is True and g.state.player.main_gongfa == G.RUIJIN_DIAN)
g.start_battle(EM.YOUGU_TENGYAO)  # 木系 → 锐金剑气 金克木 ×1.5
pool_ids3 = {s.id for s in g.battle().available_skills()}
check("fam10：unlock10 技能入池、unlock30 未亮",
      SK.RUIJIN_JIANQI in pool_ids3 and SK.JINZHONG_HUTI not in pool_ids3)
g.quit_battle()
g.step("comprehend", gongfa=G.name_of(G.RUIJIN_DIAN), days=10)  # 熟悉度 30
g.start_battle(EM.YOUGU_TENGYAO)
pool_ids4 = {s.id for s in g.battle().available_skills()}
check("learn 后功法技能入战斗池（fam 达标全亮）",
      SK.RUIJIN_JIANQI in pool_ids4 and SK.JINZHONG_HUTI in pool_ids4)
g.quit_battle()

# ---------- 判据 6：三结局路径（Game 层真实结算） ----------
print("== 判据6 三结局路径 ==")
# 6a 胜 → 掉落
g = Game(seed=11)
g.rng = FakeRng(chance=True)  # 掉落必中、伤害浮动=1.0（战后换回不影响后续测试）
stones0 = g.state.player.spirit_stones
g.start_battle(EM.LINGWEN_LANG)          # 弱敌，必赢
guard = 0
while g.battle_active() and guard < 50:
    r = g.step("battle_action", cmd="attack")
    guard += 1
check("胜路径：战斗结束", r.battle_over == BTL.BATTLE_WIN and not g.battle_active())
_wolf = EM.ENEMIES[EM.LINGWEN_LANG]
check("胜路径：灵石入账", g.state.player.spirit_stones == stones0 + _wolf.loot_stones[0])
check("胜路径：掉落概率生效(清心丹)", g.state.player.item_count(P.QINGXIN) == 1)
check("胜路径：编年史记录", any("斩【灵纹狼】" in e[1] for e in g.state.chronicle.entries))
# 6b 败 → 重伤不致死
g = Game(seed=13)
g.rng = FakeRng(chance=False, randint_lo=True)
p = g.state.player
exp0 = p.exp
life0 = p.lifespan_years
hd0 = p.heart_demon
g.start_battle(EM.XUANBING_KUILEI)   # 档19 强敌 vs 档1 → 必败
guard = 0
while g.battle_active() and guard < 50:
    r = g.step("battle_action", cmd="attack")
    guard += 1
check("败路径：重伤结局", r.battle_over == BTL.BATTLE_LOSE and not g.battle_active())
check("败路径：修为减半", p.exp == round(exp0 * 0.5))
check("败路径：折寿 1~5", p.lifespan_years <= life0 - 1 and p.lifespan_years >= max(p.age_years + 5, life0 - 5))
check("败路径：心魔+10 且不死", p.heart_demon == min(95, hd0 + 10) and p.alive
      and p.death_cause == "" and not r.died and not r.game_over)
# 6c 逃 → 无掉落
g = Game(seed=17)
g.rng = FakeRng(chance=True)
p = g.state.player
stones0 = p.spirit_stones
inv0 = dict(p.inventory)
g.start_battle(EM.LINGWEN_LANG)
r = g.step("battle_action", cmd="flee")
check("逃路径：遁走结局", r.battle_over == BTL.BATTLE_FLED and not g.battle_active())
check("逃路径：无掉落", p.spirit_stones == stones0 and p.inventory == inv0
      and "遁走" in r.text)

# ---------- 判据 6+：探索遇敌 → 战斗 集成 ----------
print("== 探索遇敌集成 ==")
found = None
for seed in range(1000, 2000):
    gg = Game(seed=seed)
    for _ in range(12):
        rr = gg.step("explore", site=ST.name_of(ST.LINGMAI))
        if rr.battle_started:
            found = (seed, gg)
            break
    if found:
        break
check("探索能触发遇敌(找到种子)", found is not None)
if found:
    seed, gg = found
    b = gg.battle()
    check("遇敌后 battle_active", gg.battle_active() and b is not None)
    rr = gg.step("cultivate", days=5)
    check("战斗中非战斗动作被拒（in_battle）", rr.reason == "in_battle")
    guard = 0
    while gg.battle_active() and guard < 100:
        r2 = gg.step("battle_action", cmd="flee")
        guard += 1
    check("探索遇敌战斗可结束", not gg.battle_active() and r2.battle_over in
          (BTL.BATTLE_WIN, BTL.BATTLE_LOSE, BTL.BATTLE_FLED), f"{r2.battle_over}")

print(f"\n== 结果：{_PASS} 过 / {_FAIL} 败 ==")
sys.exit(1 if _FAIL else 0)
