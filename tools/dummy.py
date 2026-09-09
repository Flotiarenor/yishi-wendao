"""木桩试招工具（P4-R2 附属）：把动作/技能装在身上，打木桩看真实数值。

用途：在完整战斗循环（R3）落地前，**先用手感验证动作模型**——伤害、出手节奏、
灵气收支、灵石加速收益、各流派差异。

运行：
  .venv\\Scripts\\python.exe -X utf8 -m tools.dummy            # 全部流派对照
  .venv\\Scripts\\python.exe -X utf8 -m tools.dummy 引气流 -v  # 单个流派 + 逐招时间轴
  .venv\\Scripts\\python.exe -X utf8 -m tools.dummy --list     # 列出所有可用动作

设计说明：
  - 木桩 = 攻击 0 / 防御 20 / 速度 1.0 的靶子，不会反击也不会死（HP 极大）。
  - 每场试招在固定时长窗口内跑完，按"玩家优先"推进（与定案 §2 一致）。
  - 灵气随时间连续回复（定案 §5）；动作按双约束自然排队。
  - 本工具**不改动 engine**，只是消费 action/clock/rules 三个模块。
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from content import actions as A
from engine.action import Action, Actor, can_execute, execute
from engine.clock import SIDE_ENEMY, SIDE_PLAYER, Clock


# ------------------------------------------------------------
# 木桩与试招器
# ------------------------------------------------------------
def make_dummy(hp: float = 10 ** 7, defense: float = 20.0, speed: float = 1.0) -> Actor:
    """木桩：不反击、不会死（HP 极大），用于观察纯输出与节奏。"""
    return Actor(key="dummy", name="木桩", hp=hp, hp_max=hp, attack=0.0,
                 defense=defense, speed=speed, element="无",
                 qi=0.0, qi_max=0.0, qi_rate=0.0)


def make_player(attack: float = 40.0, defense: float = 10.0, speed: float = 1.0,
                qi_max: float = 100.0, qi_rate: float = 1.0,
                stones: int = 10000) -> Actor:
    """测试用玩家面板（数值占位，方便对照）。

    qi_rate 默认 1.0/息 = 标定后的基准（定案 §11.1）：技能耗灵 4~60、周期 2~7.5 息，
    因此高耗灵技能无法靠基础回灵撑住，必须聚气或买灵石加速。
    """
    return Actor(key="you", name="你", hp=500.0, hp_max=500.0,
                 attack=attack, defense=defense, speed=speed, element="无",
                 qi=qi_max, qi_max=qi_max, qi_rate=qi_rate, stones=stones)


class Trial:
    """一场木桩试招：在时长窗口内按"玩家优先"推进，记录每次出手。"""

    def __init__(self, player: Actor, dummy: Actor):
        self.p = player
        self.d = dummy
        self.clock = Clock()
        self.clock.add("you", speed=player.speed, side=SIDE_PLAYER)
        self.clock.add("dummy", speed=dummy.speed, side=SIDE_ENEMY)
        self.log: list = []          # [(t, 动作名, 伤害, 灵气, 说明)]
        self.rejected: dict = {}     # 被拒次数（原因码 → 次数）

    # ---------- 单步 ----------
    def _try(self, act: Action) -> bool:
        ok, reason = can_execute(self.p, self.d, act, self.clock.t)
        if not ok:
            self.rejected[reason] = self.rejected.get(reason, 0) + 1
            return False
        # 灵石加速不可叠加：已在加速期内则不重复购买（避免无脑重购刷掉出手）
        if act.kind == "special" and act.components and \
                hasattr(act.components[0], "boost"):
            if self.p.qi_boost and self.clock.t < self.p.qi_boost.get("until", 0):
                self.rejected["already_boosted"] = \
                    self.rejected.get("already_boosted", 0) + 1
                return False
        out = execute(self.p, self.d, act, self.clock, jitter_roll=0.5)
        self.log.append((self.clock.t, act.display(), out.damage,
                         round(self.p.qi, 1), "／".join(out.lines)))
        return True

    def run(self, plan: list, duration_li: int = 3000, gather_when_broke: bool = True):
        """跑一场：plan 为动作列表，**按游标轮转**（不是"第一个能打的"）。

        轮转规则：
          - 当前游标动作可执行 → 执行，游标前进（下一招）
          - 不可执行（灵气不足/条件不满足）→ 游标前进，试下一招
          - 一圈都不可执行 → 聚气（可选）；仍不行则推进时间避免空转
        这样每个动作都会轮到，而不是首招永远赢（否则测试会失真）。
        """
        end_t = self.clock.t + duration_li
        idx = 0
        guard = 0
        while self.clock.t < end_t and guard < 5000:
            guard += 1
            self.clock.advance_to_next()
            if self.clock.t >= end_t:
                break
            # 灵气随时间连续回复（定案 §5）
            self.p.gain_qi(1, self.clock.t)
            self.d.expire_statuses(self.clock.t)
            self.p.expire_statuses(self.clock.t)
            who = self.clock.actor_due()
            if who == "dummy":
                self.clock.schedule("dummy", A.ATTACK.timing)   # 木桩空挥，只推进时间
                continue
            # 玩家：从游标开始找一圈内第一个能执行的
            done = False
            for step in range(len(plan)):
                act = plan[(idx + step) % len(plan)]
                if self._try(act):
                    idx = (idx + step + 1) % len(plan)
                    done = True
                    break
            if not done and gather_when_broke:
                if self._try(A.GATHER):
                    done = True
            if not done:
                # 计划全不可用且不聚气 → 推进到下一个可动时刻，避免空转
                self.clock.set_next_t("you", self.clock.t + 1)
        return self.summary(duration_li)

    # ---------- 汇总 ----------
    def summary(self, duration_li: int) -> dict:
        total = sum(x[2] for x in self.log)
        acts = [x[1] for x in self.log]
        return {
            "总伤害": total,
            "出手数": len(self.log),
            "时长息": duration_li / 100.0,
            "每秒伤害": total / (duration_li / 100.0),
            "均次伤害": (total / len(self.log)) if self.log else 0.0,
            "剩余灵气": round(self.p.qi, 1),
            "剩余灵石": self.p.stones,
            "动作分布": {k: acts.count(k) for k in dict.fromkeys(acts)},
            "被拒": dict(self.rejected),
        }


def show_timeline(trial: Trial, limit: int = 40):
    """打印逐招时间轴（-v 用）。"""
    print(f"    {'时刻(息)':>8}  {'动作':<10} {'伤害':>6}  {'灵气':>6}  说明")
    for t, name, dmg, qi, line in trial.log[:limit]:
        print(f"    {t / 100:>8.2f}  {name:<10} {dmg:>6}  {qi:>6.1f}  {line[:70]}")
    if len(trial.log) > limit:
        print(f"    …… 共 {len(trial.log)} 次出手")


# ------------------------------------------------------------
# 流派预设（每个预设 = 一套技能 + 玩法循环）
# ------------------------------------------------------------
def scenarios() -> dict:
    return {
        "平砍基准": dict(
            plan=[A.ATTACK],
            desc="只用平砍：不耗灵，纯看速度与攻击力",
            player=dict(),
        ),
        "品阶流": dict(
            plan=[A.RUIJIN, A.XUANBING, A.ATTACK],
            desc="低耗中威力技能轮转，不依赖灵气池",
            player=dict(),
        ),
        "引气流": dict(
            plan=[A.FENTIAN, A.QIANJIAN, A.GATHER],
            desc="高耗大招 + 聚气补灵：不买加速基本放不出来（标定后灵气是真约束）",
            player=dict(qi_max=100, qi_rate=1.0),
        ),
        "蓄力流": dict(
            plan=[A.XULI, A.ATTACK],
            desc="长前摇换威力：duration_weight=0.4",
            player=dict(),
        ),
        "灵石加速流": dict(
            plan=[A.BUY_QI_HIGH, A.FENTIAN, A.QIANJIAN, A.GATHER],
            desc="花灵石买回灵加速，再放大招（引气流的开销换爆发）",
            player=dict(qi_max=100, qi_rate=1.0, stones=10000),
        ),
        "控制+条件流": dict(
            plan=[A.DIXIAN, A.LIANJI, A.QINGTENG, A.ATTACK],
            desc="先破势，再打需要破势的连击；穿插定身",
            player=dict(),
        ),
        "低血流": dict(
            plan=[A.FENSHEN, A.ATTACK],
            desc="低血触发的焚身（需 HP<30%；默认满血不触发，用 --start-hp 0.25 看效果）",
            player=dict(),
        ),
    }


def run_one(name: str, verbose: bool = False, duration_li: int = 3000,
            dummy_defense: float = 20.0, start_hp: float = 1.0):
    sc = scenarios()[name]
    p = make_player(**sc["player"])
    # 低血条件技：默认不伪造血量（打木桩本来就是满血，条件不成立是正确行为）。
    # 想看它生效用 --start-hp 0.25。
    if start_hp < 1.0:
        p.hp = p.hp_max * start_hp
    d = make_dummy(defense=dummy_defense)
    tr = Trial(p, d)
    s = tr.run(sc["plan"], duration_li=duration_li)
    print(f"\n━━━ {name} ━━━ {sc['desc']}")
    print(f"  玩家：攻{p.attack:.0f} 防{p.defense:.0f} 速{p.speed:.1f} "
          f"灵气池{p.qi_max:.0f} 回灵{p.qi_rate:.1f}/息 灵石{p.stones}"
          f"｜HP {p.hp:.0f}/{p.hp_max:.0f}")
    print(f"  木桩：防御 {dummy_defense:.0f}（不会反击）")
    print(f"  → 总伤害 {s['总伤害']}｜出手 {s['出手数']} 次｜均次 {s['均次伤害']:.1f}"
          f"｜每秒 {s['每秒伤害']:.1f}｜剩灵气 {s['剩余灵气']}｜剩灵石 {s['剩余灵石']}")
    print(f"  动作分布：{s['动作分布']}")
    if s["被拒"]:
        print(f"  被拒：{s['被拒']}")
    if verbose:
        show_timeline(tr)
    return s


def main(argv=None):
    ap = argparse.ArgumentParser(description="木桩试招（P4-R2）")
    ap.add_argument("name", nargs="?", help="流派名（省略则跑全部对照）")
    ap.add_argument("-v", "--verbose", action="store_true", help="打印逐招时间轴")
    ap.add_argument("--duration", type=float, default=30.0, help="试招时长（息）")
    ap.add_argument("--defense", type=float, default=20.0, help="木桩防御")
    ap.add_argument("--start-hp", type=float, default=1.0,
                    help="开局血量比例（0~1；低血条件技用 0.25）")
    ap.add_argument("--list", action="store_true", help="列出全部动作/技能数据")
    args = ap.parse_args(argv)

    if args.list:
        print("━━━ 基础动作 ━━━")
        for a in A.BASIC_ACTIONS:
            print(f"  {a.key:<12} {a.display():<8} 耗灵{a.qi_cost:<3} "
                  f"前摇{a.timing.windup:<5} 后摇{a.timing.recovery:<5} {a.desc}")
        print("━━━ 技能（品阶 → 流派） ━━━")
        for a in A.skills():
            print(f"  {a.key:<12} {a.display():<10} 品阶{a.tier} 耗灵{a.qi_cost:<3} "
                  f"前摇{a.timing.windup:<5} 后摇{a.timing.recovery:<5} "
                  f"灵气效率{a.qi_efficiency:<5} 时长权重{a.duration_weight:<4} {a.desc}")
        print("━━━ 灵石加速 ━━━")
        for a in (A.BUY_QI_LOW, A.BUY_QI_HIGH):
            c = a.components[0]
            print(f"  {a.key:<14} {a.display():<16} 花费{c.cost:<4}灵石 "
                  f"+{c.boost:.0f}/息 × {c.T_max / 100:.0f}息")
        return

    dur = int(args.duration * 100)
    if args.name:
        if args.name not in scenarios():
            print(f"未知流派：{args.name}")
            print("可用：" + "、".join(scenarios()))
            sys.exit(2)
        run_one(args.name, verbose=args.verbose, duration_li=dur,
                dummy_defense=args.defense, start_hp=args.start_hp)
        return

    print(f"══════ 木桩对照（{args.duration:.0f} 息窗口，木桩防御 {args.defense:.0f}）══════")
    rows = []
    for name in scenarios():
        s = run_one(name, verbose=False, duration_li=dur,
                    dummy_defense=args.defense, start_hp=args.start_hp)
        rows.append((name, s))
    print("\n══════ 汇总排行（每秒伤害）══════")
    for name, s in sorted(rows, key=lambda kv: -kv[1]["每秒伤害"]):
        print(f"  {name:<12} 每秒 {s['每秒伤害']:>7.1f}｜总伤 {s['总伤害']:>7}"
              f"｜出手 {s['出手数']:>3}｜均次 {s['均次伤害']:>6.1f}"
              f"｜剩灵 {s['剩余灵气']:>6.1f}｜剩灵石 {s['剩余灵石']}")


if __name__ == "__main__":
    main()
