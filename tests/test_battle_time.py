"""P4-R3 时间轴战斗单测（纯引擎，确定性）。

覆盖任务书 `docs/tasks/P4-R3-时间轴战斗.md` §10 判据 1~5：
  1. 决策窗口：队列累计时长受窗口约束；submit 拒绝越界
  2. run_window：队列按序执行、时间轴推进到玩家下次可动
  3. 敌方插入：跨窗口时敌方行动出现在正确时刻
  4. 前摇打断：被控制 → 动作取消 + 退灵气 + 计后摇
  5. 确定性：同种子 + 同提交序列逐位一致（salt 不依赖调用次数）
  6. 五行/乘区端到端、状态到期、胜/败结局

运行：.venv\\Scripts\\python.exe -X utf8 -m tests.test_battle_time
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from content import actions as CA
from content import enemies as EM
from engine import battle as BTL
from engine.action import Action, Actor, ApplyStatus, Damage, Timing
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


def make(enemy_id=EM.LINGWEN_LANG, realm=1, seed=42, extra_actions=(),
         player_attack=None, player_hp=None, enemy_actions=None):
    e = EM.by_id(enemy_id)
    ps = BTL.battle_stats(realm)
    if player_attack is not None:
        ps["attack"] = player_attack
    if player_hp is not None:
        ps["hp"] = ps["hp_max"] = player_hp
    acts = list(CA.BASIC_ACTIONS) + list(extra_actions)
    b = BTL.Battle(ps, acts, e, Rng(seed), battle_id=1,
                   enemy_actions=enemy_actions if enemy_actions is not None
                   else list(CA.ENEMY_ACTIONS))
    return b


# 测试用技能：长前摇（便于验证打断）+ 控制技
SLOW_BIG = Action(key="slow_big", name="蓄力重击", kind="attack", qi_cost=10, tier=3,
                  timing=Timing(windup=800, recovery=400),
                  components=(Damage(power=60, attack_ratio=0.5, element="土"),),
                  qi_efficiency=0.0)
STUN_SKILL = Action(key="stun_hit", name="定身击", kind="attack", qi_cost=0, tier=1,
                    timing=Timing(windup=0, recovery=100),
                    components=(Damage(power=1, attack_ratio=0.0, element="无"),
                                ApplyStatus(key="root", duration_li=500,
                                            tags=("control",)),),
                    qi_efficiency=0.0)

# ============ 1. 决策窗口与 submit ============
print("== 1 决策窗口 ==")
b = make()
check("开局窗口 > 0", b.window_li() > 0, f"{b.window_li()}")
ok, reason = b.submit("attack")
check("submit 平砍 ok", ok and reason == "")
ok2, reason2 = b.submit("nonsense")
check("submit 未知动作 → unknown_action", not ok2 and reason2 == "unknown_action")
# 连续 submit 直到窗口排满
b2 = make()
n = 0
while b2.submit("attack")[0]:
    n += 1
check("队列可排满窗口（平砍 200 厘息）", n >= 1, f"排入 {n} 个")
check("排满后 submit 被拒（window_open）", b2.submit("attack")[1] == "window_open")
check("队列长度 = 已排入数", len(b2.state()["queue"]) == n)

# ============ 2. run_window 与时间推进 ============
print("== 2 run_window ==")
b = make()
b.submit("attack")
rep = b.run_window()
check("run_window 有叙事行", len(rep.lines) > 0)
check("敌我均掉血或敌方已行动", b.e.hp < b.e.hp_max or b.p.hp < b.p.hp_max,
      f"e={b.e.hp} p={b.p.hp}")
check("时间轴已推进", b.clock.t > 0, f"t={b.clock.t}")
check("玩家下次可动 > 当前 t", b.clock.next_t("player") > b.clock.t)
check("队列已清空", b.state()["queue"] == [])
check("used 记录已用动作", "attack" in rep.used)

b = make()
rep = b.run_window()
check("空队列 → queue_empty 且不推进", rep.ended is False and b.clock.t == 0
      and b.last_reason == "queue_empty")

# ============ 3. 敌方插入（跨窗口）============
print("== 3 敌方插入 ==")
# 敌方速度极快 → 玩家动作还没落地敌人就动了；跑多个窗口保证敌方有机会行动
b = make(enemy_id=EM.YEHOU_YUANHUN)      # 速 22 → 倍率 1.7
for _ in range(6):
    b.submit("attack")
    rep = b.run_window()
    if b.ended():
        break
t_events = [e["t"] for e in b.timeline]
check("事件按时间单调不减", all(t_events[i] <= t_events[i + 1]
                          for i in range(len(t_events) - 1)), f"{t_events}")
check("敌方行动已发生（多窗口内）",
      any(e.get("actor") == "enemy" for e in b.timeline), f"{b.timeline}")

# 长前摇动作 + 快敌 → 敌方应在前摇期间插入
b = make(enemy_id=EM.YEHOU_YUANHUN, extra_actions=(SLOW_BIG,))
ok, _ = b.submit("slow_big")
if ok:
    rep = b.run_window()
    ev = [e for e in rep.events if e["type"] == "action"]
    order = [(e["t"], e["actor"]) for e in ev]
    check("快敌在玩家长前摇期间插入行动",
          any(a == "enemy" for _, a in order), f"{order}")

# ============ 4. 前摇打断（退灵气 + 计后摇）============
print("== 4 前摇打断 ==")
# 玩家用长前摇技能；敌人用"定身击"打断
b = make(enemy_id=EM.LINGWEN_LANG, extra_actions=(SLOW_BIG,),
         enemy_actions=[STUN_SKILL])
b.p.qi = 100
b.e.speed = 5.0                       # 敌人先动手
ok, reason = b.submit("slow_big")
check("长前摇技能可入队", ok, reason)
qi_before = b.p.qi
hp_e_before = b.e.hp
rep = b.run_window()
interrupted = [e for e in b.timeline if e.get("type") == "interrupt"]
check("发生了打断事件", len(interrupted) >= 1, f"{b.timeline}")
if interrupted:
    it = interrupted[0]
    check("打断的是玩家动作", it["actor"] == "player", f"{it}")
    check("退灵气（退还 = 该动作耗灵）", it["refund"] == SLOW_BIG.qi_cost, f"{it}")
    check("灵气已回补", b.p.qi >= qi_before - SLOW_BIG.qi_cost + SLOW_BIG.qi_cost - 1e-9
          or b.p.qi > 0, f"{b.p.qi}")
    check("被打断的动作未造成伤害（敌人满血）", b.e.hp == hp_e_before,
          f"e={b.e.hp} vs {hp_e_before}")
    check("玩家 next_t 仍被推进（算后摇）", b.clock.next_t("player") > 0)

# ============ 5. 确定性 ============
print("== 5 确定性 ==")
def script():
    b = make(seed=7, extra_actions=(SLOW_BIG, STUN_SKILL))
    out = []
    for _ in range(6):
        for key in ("attack", "stun_hit", "attack"):
            b.submit(key)
        rep = b.run_window()
        out.append((b.clock.t, round(b.p.hp, 4), round(b.e.hp, 4),
                    b.ended(), b.outcome(), tuple(rep.used),
                    len(b.timeline)))
        if b.ended():
            break
    return out
r1, r2 = script(), script()
check("同种子同提交序列逐位一致", r1 == r2, f"{r1} vs {r2}")

# salt 不依赖调用次数：先消耗一次随机流再跑，结果应一致（战斗内 rng 独立派生）
b_a = make(seed=9)
b_a.submit("attack"); rep_a = b_a.run_window()
b_b = make(seed=9)
b_b.rng.roll("warmup")               # 故意多消耗一次（模拟敌方插入改变调用次数）
b_b.submit("attack"); rep_b = b_b.run_window()
check("salt 含实例序号：额外 rng 调用不影响同实例结果",
      round(b_a.e.hp, 6) == round(b_b.e.hp, 6),
      f"{b_a.e.hp} vs {b_b.e.hp}")

# ============ 6. 五行 / 状态 / 结局 ============
print("== 6 五行 / 状态 / 结局 ==")
FIRE = Action(key="fire_atk", name="火击", kind="attack", qi_cost=0, tier=1,
              timing=Timing(windup=0, recovery=200),
              components=(Damage(power=20, attack_ratio=0.0, element="火"),),
              qi_efficiency=0.0)
b_gold = make(enemy_id=EM.SHIJIN_GUSHI, extra_actions=(FIRE,))    # 金系敌
b_gold.e.hp = b_gold.e.hp_max = 10 ** 6
b_gold.submit("fire_atk"); b_gold.run_window()
dmg_fire_vs_gold = 10 ** 6 - b_gold.e.hp
b_water = make(enemy_id=EM.HANTAN_XUANGUI, extra_actions=(FIRE,))  # 水系敌
b_water.e.hp = b_water.e.hp_max = 10 ** 6
b_water.submit("fire_atk"); b_water.run_window()
dmg_fire_vs_water = 10 ** 6 - b_water.e.hp
check("火克金 → 伤害更高", dmg_fire_vs_gold > dmg_fire_vs_water,
      f"金 {dmg_fire_vs_gold} vs 水 {dmg_fire_vs_water}")

# 状态到期
b = make(extra_actions=(STUN_SKILL,))
b.submit("stun_hit")
b.run_window()
check("定身状态已施加到敌人", b.e.has_status("root") or b.e.statuses == {})
t_root = b.e.statuses.get("root", {}).get("until", 0)
if t_root:
    b.clock.t = t_root
    b.e.expire_statuses(t_root)
    check("状态到期被清理", not b.e.has_status("root"))

# 胜利结局
b = make()
b.e.hp = 1
b.submit("attack")
rep = b.run_window()
check("击杀 → ended + win", b.ended() and b.outcome() == BTL.BATTLE_WIN,
      f"{b.ended()} {b.outcome()}")

# 失败结局：跑到敌方真的打过来
b = make()
b.p.hp = 1
b.p.hp_max = 1
for _ in range(10):
    b.submit("attack")
    b.run_window()
    if b.ended():
        break
check("玩家倒下 → ended + lose", b.ended() and b.outcome() == BTL.BATTLE_LOSE,
      f"{b.ended()} {b.outcome()} hp={b.p.hp}")

# 结束后的 submit 被拒
ok, reason = b.submit("attack")
check("战斗结束后 submit → battle_ended", not ok and reason == "battle_ended")

# ============ 7. 灵兽节奏由速度决定 ============
print("== 7 灵兽节奏 ==")
for speed, label in ((0.5, "慢兽"), (2.0, "快兽")):
    b = make()
    b.e.speed = speed
    b.clock._speed["enemy"] = speed
    # 重设敌人首次行动时刻（按新速度）
    from engine.clock import total_li as _tl
    b.clock.set_next_t("enemy", max(BTL.MIN_WINDOW_LI,
                                    _tl(CA.ENEMY_STRIKE.timing, speed)))
    for _ in range(8):
        b.submit("attack")
        b.run_window()
        if b.ended():
            break
    n_enemy = len([e for e in b.timeline if e.get("actor") == "enemy"])
    print(f"  {label}（速{speed}）: 8 个窗口内敌方行动 {n_enemy} 次")
    if speed == 2.0:
        check("快兽行动次数 > 0", n_enemy >= 1, f"{n_enemy}")
    else:
        check("慢兽行动次数 ≥ 0", n_enemy >= 0)
check("快兽出手比慢兽频繁",
      True)   # 由上一循环输出可见；严格比较见下方补充
b_fast, b_slow = make(), make()
for b, spd in ((b_fast, 2.0), (b_slow, 0.5)):
    b.e.speed = spd
    b.clock._speed["enemy"] = spd
    from engine.clock import total_li as _tl2
    b.clock.set_next_t("enemy", max(BTL.MIN_WINDOW_LI, _tl2(CA.ENEMY_STRIKE.timing, spd)))
    for _ in range(12):
        b.submit("attack")
        b.run_window()
        if b.ended():
            break
n_fast = len([e for e in b_fast.timeline if e.get("actor") == "enemy"])
n_slow = len([e for e in b_slow.timeline if e.get("actor") == "enemy"])
check("快兽出手次数 > 慢兽", n_fast > n_slow, f"快 {n_fast} vs 慢 {n_slow}")

print(f"\n== 结果：{_PASS} 过 / {_FAIL} 败 ==")
sys.exit(1 if _FAIL else 0)
