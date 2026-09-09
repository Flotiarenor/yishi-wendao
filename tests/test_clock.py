"""P4-R1 时间轴与规则层单测（纯函数，确定性）。

覆盖 `docs/战斗系统定案.md` §2/§3/§5/§6/§10：
  1. Timing 速度缩放（前后摇比例独立、可豁免）
  2. Clock 推进 / 同时到达玩家优先 / 确定性排序
  3. 决策窗口长度
  4. schedule 的落地时刻与可动时刻
  5. 控制技推后 next_t
  6. 伤害五段乘区（逐项 + 组合）
  7. 状态乘区（攻方/守方镜像）
  8. 回灵（连续累积、封顶、灵石加速）
  9. 双约束有效间隔 max(后摇÷速度, 耗灵÷回灵)
 10. 确定性：同输入重复调用逐位一致；preview 不消耗随机流

运行：.venv\\Scripts\\python.exe -X utf8 -m tests.test_clock
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import rules as R
from engine.clock import (LI, SIDE_ENEMY, SIDE_PLAYER, Clock, Timing,
                          recovery_li, total_li, windup_li)

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


# ============ 1. Timing 速度缩放 ============
print("== 1 Timing 速度缩放 ==")
t_plain = Timing(windup=0, recovery=200)
check("速度1.0 → 后摇不变", recovery_li(t_plain, 1.0) == 200)
check("速度2.0 → 后摇减半", recovery_li(t_plain, 2.0) == 100)
check("速度0.5 → 后摇加倍", recovery_li(t_plain, 0.5) == 400)
check("前摇0 → 恒0", windup_li(t_plain, 3.0) == 0)

t_big = Timing(windup=100, recovery=400, windup_speed=0.5, recovery_speed=1.0)
check("前后摇比例独立：前摇敏感0.5/后摇1.0",
      windup_li(t_big, 2.0) == 67 and recovery_li(t_big, 2.0) == 200,
      f"w={windup_li(t_big, 2.0)} r={recovery_li(t_big, 2.0)}")

t_fixed = Timing(windup=50, recovery=150, windup_speed=0.0, recovery_speed=0.0)
check("速度敏感0.0 → 完全不吃速度（固定耗时动作）",
      windup_li(t_fixed, 5.0) == 50 and recovery_li(t_fixed, 5.0) == 150)
check("总时长 = 实际前摇 + 实际后摇", total_li(t_big, 2.0) == 67 + 200)

# ============ 2. Clock 推进与确定性 ============
print("== 2 Clock 推进 / 同时到达 / 确定性 ==")
ck = Clock()
ck.add("player", speed=1.0, side=SIDE_PLAYER)
ck.add("enemy", speed=1.0, side=SIDE_ENEMY)
check("开局双方 next_t=0", ck.next_t("player") == 0 and ck.next_t("enemy") == 0)
ck.advance_to_next()
check("同时到达 → 玩家优先（不掷随机）", ck.actor_due() == "player")
check("due() 返回双方（同刻都可动）", set(ck.due()) == {"player", "enemy"})

# 确定性排序：输入顺序颠倒结果不变
a = [{"side": SIDE_ENEMY, "speed": 1.0, "key": "e"},
     {"side": SIDE_PLAYER, "speed": 1.0, "key": "p"}]
b = list(reversed(a))
from engine.clock import order
check("order() 稳定：不同输入顺序 → 同结果",
      [c["key"] for c in order(a)] == [c["key"] for c in order(b)] == ["p", "e"],
      f"{[c['key'] for c in order(a)]}")

ck2 = Clock()
ck2.add("slow", speed=0.5, side=SIDE_PLAYER)
ck2.add("fast", speed=2.0, side=SIDE_PLAYER)
check("同阵营按速度降序", [c["key"] for c in
                      order([{"side": 0, "speed": 0.5, "key": "slow"},
                             {"side": 0, "speed": 2.0, "key": "fast"}])] == ["fast", "slow"])

# ============ 3. 决策窗口 ============
print("== 3 决策窗口 ==")
ck = Clock()
ck.add("player", speed=1.0, side=SIDE_PLAYER)
ck.add("enemy", speed=1.0, side=SIDE_ENEMY)
ck.schedule("enemy", Timing(recovery=400))     # 敌先动，400 厘息后再动
check("窗口 = 敌方下次可动 − 当前", ck.window_li("player", "enemy") == 400,
      f"{ck.window_li('player', 'enemy')}")
ck.schedule("player", Timing(recovery=200))    # 玩家动完（t 未推进，next_t=200）
ck.advance_to_next()                           # t 推进到 200
check("t 推进后窗口缩短（敌方已更近）", ck.window_li("player", "enemy") == 200,
      f"t={ck.t} {ck.window_li('player', 'enemy')}")
ck3 = Clock()
ck3.add("p", speed=1.0, side=SIDE_PLAYER)
ck3.add("e", speed=1.0, side=SIDE_ENEMY)
ck3.set_next_t("e", 0)
check("窗口不为负", ck3.window_li("p", "e") == 0)

# ============ 4. schedule 落地/可动时刻 ============
print("== 4 schedule ==")
ck = Clock()
ck.add("p", speed=1.0, side=SIDE_PLAYER)
ck.add("e", speed=1.0, side=SIDE_ENEMY)
land, nxt = ck.schedule("p", Timing(windup=100, recovery=400))
check("落地时刻 = 起始 + 前摇", land == 100, f"{land}")
check("可动时刻 = 起始 + 前摇 + 后摇", nxt == 500, f"{nxt}")
land2 = ck.land_li("p", Timing(windup=100, recovery=400))
check("land_li 只算不改状态", land2 == 600, f"{land2}")
check("schedule 不污染 land_li 结果", ck.next_t("p") == 500)

# 用户原始算例：先出手 2s 攻击 → 3s 防御；对方平均 4s 一次
print("  -- 用户算例：2s攻击→3s防御 vs 4s一动的对手 --")
ck = Clock()
ck.add("p", speed=1.0, side=SIDE_PLAYER)
ck.add("e", speed=1.0, side=SIDE_ENEMY)
land, nxt = ck.schedule("p", Timing(recovery=200))       # t=0 攻击，2s
check("攻击后可动时刻 t=200", nxt == 200, f"{nxt}")
land, nxt = ck.schedule("p", Timing(recovery=300))       # t=200 防御，3s
check("防御后可动时刻 t=500（剩 300 厘息窗口）", nxt == 500, f"{nxt}")
check("此时对手 next_t=400 → 窗口已被跨越（跨界插入）",
      ck.window_li("p", "e") == 0, f"{ck.window_li('p', 'e')}")

# ============ 5. 控制技推后 next_t ============
print("== 5 控制 ==")
ck = Clock()
ck.add("p", speed=1.0, side=SIDE_PLAYER)
ck.add("e", speed=1.0, side=SIDE_ENEMY)
ck.set_next_t("e", 300)
ck.push_back("e", 200)
check("定身 = 推后 next_t", ck.next_t("e") == 500)
ck.push_back("e", -100)
check("推后不接受负值（不提前）", ck.next_t("e") == 500)

# ============ 6. 伤害五段乘区 ============
print("== 6 伤害乘区 ==")
check("品阶系数 1/2/3/4 递增", R.tier_mult(1) < R.tier_mult(2) < R.tier_mult(3) < R.tier_mult(4))
check("减伤：防御0 → 0", R.mitigation(0) == 0.0)
check("减伤：防御=K → 0.5", abs(R.mitigation(R.DEF_K) - 0.5) < 1e-9)
check("减伤递增且 <1", 0 < R.mitigation(50) < R.mitigation(200) < 1)
check("灵气加成线性：0灵 → 1.0", abs(R.qi_bonus(0, 0.05) - 1.0) < 1e-9)
check("灵气加成线性：20灵×0.05 → 2.0", abs(R.qi_bonus(20, 0.05) - 2.0) < 1e-9)
check("时长加成：权重0 → 1.0（威力不随时长）", abs(R.duration_bonus(600, 0.0) - 1.0) < 1e-9)
check("时长加成：权重1、600厘息/基准200 → 4.0",
      abs(R.duration_bonus(600, 1.0) - 4.0) < 1e-9)
check("jitter ∈ [0.9, 1.1)", R.jitter(0.0) == 0.9 and abs(R.jitter(1.0) - 1.1) < 1e-9)

ctx = R.DamageCtx(base=30, tier=1, attack=40, attack_ratio=0.5, defense=0,
                  jitter_roll=0.5)
check("基础伤害 = (30 + 40×0.5) × jitter1.0", R.resolve_damage(ctx) == 50,
      f"{R.resolve_damage(ctx)}")
ctx2 = R.DamageCtx(base=30, tier=1, attack=40, attack_ratio=0.5, defense=100,
                   jitter_roll=0.5)
check("防御100 → 减伤50%", R.resolve_damage(ctx2) == 25, f"{R.resolve_damage(ctx2)}")
check("伤害恒 ≥ 1", R.resolve_damage(R.DamageCtx(base=0, defense=9999)) == 1)
ctx3 = R.DamageCtx(base=30, attack=40, attack_ratio=0.5, qi_spent=20,
                   qi_efficiency=0.05, jitter_roll=0.5)
check("灵气加成生效：(50)×2.0 = 100", R.resolve_damage(ctx3) == 100,
      f"{R.resolve_damage(ctx3)}")

# ============ 7. 状态乘区 ============
print("== 7 状态乘区 ==")
check("无状态 → (1.0, 1.0)", R.status_mult([]) == (1.0, 1.0))
att, dfn = R.status_mult(["weaken"])
check("虚弱 → 攻方 0.7", abs(att - 0.7) < 1e-9 and dfn == 1.0)
att, dfn = R.status_mult(["vulnerable"])
check("脆弱 → 守方 1.5", att == 1.0 and abs(dfn - 1.5) < 1e-9)
att, dfn = R.status_mult(["weaken", "vulnerable"])
check("虚弱+脆弱 → 0.7 × 1.5 分列两侧", abs(att - 0.7) < 1e-9 and abs(dfn - 1.5) < 1e-9)
att, dfn = R.status_mult(["unknown_key"])
check("未知效果键忽略不报错", (att, dfn) == (1.0, 1.0))
c = R.DamageCtx(base=100, attack_ratio=0, defender_status=("vulnerable",), jitter_roll=0.5)
check("脆弱让受击变高：100 → 150", R.resolve_damage(c) == 150, f"{R.resolve_damage(c)}")

# ============ 8. 回灵 ============
print("== 8 回灵 ==")
check("连续回灵：3/息 × 200厘息 = 6", abs(R.qi_gain(3.0, 200) - 6.0) < 1e-9)
check("回灵与速度无关（接口只收速率与 Δt）", abs(R.qi_gain(3.0, 100) - 3.0) < 1e-9)
check("灵石加速：R_base+R_boost", abs(R.qi_gain_with_boost(3.0, 7.0, 100) - 10.0) < 1e-9)
q, got = R.apply_qi_gain(90.0, 50.0, 100.0)
check("灵气封顶", q == 100.0 and got == 10.0, f"q={q} got={got}")
q, got = R.apply_qi_gain(0.0, 0.0, 100.0)
check("无回灵不增长", q == 0.0 and got == 0.0)
check("can_afford", R.can_afford(10, 10) and not R.can_afford(9, 10))

# ============ 9. 双约束有效间隔 ============
print("== 9 双约束 max(后摇÷速度, 耗灵÷回灵) ==")
check("快招（0耗）→ 后摇主导", R.effective_interval_li(200, 1.0, 0, 3.0) == 200)
check("小技（耗6、回灵3）→ 灵气项 200 = 后摇项 → 200",
      R.effective_interval_li(200, 1.0, 6, 3.0) == 200,
      f"{R.effective_interval_li(200, 1.0, 6, 3.0)}")
check("大技（耗20、回灵3）→ 灵气项 667 主导",
      R.effective_interval_li(400, 1.0, 20, 3.0) == 667,
      f"{R.effective_interval_li(400, 1.0, 20, 3.0)}")
check("速度提升对重招无效（灵气卡住）：速2.0 仍是 667",
      R.effective_interval_li(400, 2.0, 20, 3.0) == 667,
      f"{R.effective_interval_li(400, 2.0, 20, 3.0)}")
check("速度提升对快招有效：速2.0 → 100",
      R.effective_interval_li(200, 2.0, 0, 3.0) == 100)
check("无回灵时不被灵气项卡死", R.effective_interval_li(200, 1.0, 20, 0.0) == 200)

# ============ 10. 确定性 ============
print("== 10 确定性 ==")
def run_script():
    ck = Clock()
    ck.add("p", speed=1.2, side=SIDE_PLAYER)
    ck.add("e", speed=0.8, side=SIDE_ENEMY)
    out = []
    for _ in range(6):
        ck.advance_to_next()
        who = ck.actor_due()
        out.append((ck.t, who))
        ck.schedule(who, Timing(windup=50, recovery=200))
    return out
r1, r2 = run_script(), run_script()
check("同输入两次运行逐位一致", r1 == r2, f"{r1} vs {r2}")
check("时间单调不减", all(r1[i][0] <= r1[i + 1][0] for i in range(len(r1) - 1)))

pv1 = R.preview_damage(ctx)
pv2 = R.preview_damage(ctx)
check("preview_damage 幂等（不消耗随机流）", pv1 == pv2)
check("preview 含各乘区明细", {"power", "qi_bonus", "duration_bonus", "mitigation",
                            "element_mult", "status_attacker", "status_defender",
                            "final"} <= set(pv1))

print(f"\n== 结果：{_PASS} 过 / {_FAIL} 败 ==")
sys.exit(1 if _FAIL else 0)
