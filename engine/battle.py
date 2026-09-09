"""时间轴战斗（P4-R3）：决策窗口 + 队列 + 前摇打断。

规格：`docs/战斗系统定案.md` §2/§3/§4/§7 与任务书 `docs/tasks/P4-R3-时间轴战斗.md`。
本模块**取代**旧的回合制 `Battle.do()`（回合制作废）。

核心语义：
  - 时间是唯一推进维度（厘息整数，见 engine.clock）
  - 玩家在"决策窗口"内排一串动作（无槽位，队列），窗口结束 = 玩家下次可动
  - 引擎把这一轮跑完：玩家动作按序落地；期间敌方按自己的节奏插入行动
  - 前摇中的动作可被控制打断（取消 + 退灵气 + 计后摇）
  - 敌人统一"灵兽进攻"（单动作 + 参数驱动，见 content/actions.ENEMY_STRIKE）

事件优先级（冻结，保证可复现）：
  1) 前摇落地（效果生效）
  2) 敌方行动
  3) 状态到期
  同一时刻按上述顺序；时刻相同则玩家动作先落地、敌后动（玩家体验优先）。

随机流：由构造传入的 Rng 独占；salt 含"行动实例序号"（不依赖调用次数），
因此敌方插入/打断改变调用次数也不影响可复现性。
"""

from dataclasses import dataclass, field

from engine import rules as R
from engine import status as ST
from engine.action import (Action, Actor, ActionOutcome, PendingAction, begin,
                           cancel, can_execute, land)
from engine.clock import (SIDE_ENEMY, SIDE_PLAYER, Clock, Timing, recovery_li,
                          total_li)

# 战斗结局
BATTLE_WIN = "win"
BATTLE_LOSE = "lose"
BATTLE_FLED = "fled"

# 无效指令原因码（对外契约，沿用旧名以便前端映射）
R_BATTLE_ENDED = "battle_ended"
R_UNKNOWN_ACTION = "unknown_action"
R_UNKNOWN_SKILL = "unknown_skill"
R_SKILL_NA = "skill_na"
R_LOW_QI = "low_qi"
R_CONDITION_FAILED = "condition_failed"
R_QUEUE_EMPTY = "queue_empty"
R_WINDOW_OPEN = "window_open"      # 队列未满窗口，需继续排或点跳过
R_QUEUE_INDEX = "queue_index"      # 撤回时队列序号无效

# 控制类效果（前摇被打断的触发源）——权威定义在 engine/status.py
CONTROL_KEYS = ST.CONTROL_KEYS

# 决策窗口下限（厘息）：保证玩家每轮至少能排一个基准动作
MIN_WINDOW_LI = 600

# 兼容导出（旧 API 形状：五行克环 / 效果展示名）
# engine.game 与 test_effects 仍在用；新代码请直接用 engine.rules / content.effects。
from content.effects import EFFECT_LABELS as UTIL_EFFECT_LABELS   # noqa: E402
from engine.rules import KE, ke_mult                              # noqa: E402,F401


def battle_stats(realm_idx: int, qi_max_base: int = 0) -> dict:
    """从境界档派生玩家本场面板（派生值，不入存档）。

    速度是**倍率**（1.0 基准）——新时间轴下"速度"用于缩放前后摇，
    不再是旧回合制的绝对速度值（旧的 8+档 会让一切动作只有几十厘息）。
    """
    hp = 60 + realm_idx * 25
    return dict(
        realm_idx=realm_idx,
        hp=hp, hp_max=hp,
        attack=8 + realm_idx * 4,
        defense=4 + realm_idx * 3,
        speed=1.0 + realm_idx * 0.02,   # 倍率：档1 → 1.02，档25 → 1.5
        qi_max=100 + qi_max_base,       # 标定：池不随境界膨胀（用户拍板）
        qi=100 + qi_max_base,
        qi_rate=1.0,                    # 标定：1/息（定案 §11.1）
    )


def enemy_speed_multiplier(raw_speed: float) -> float:
    """敌人原始速度（content 里 6~22）→ 时间轴倍率（1.0 基准）。

    8 ≈ 基准灵兽；快兽（22）≈ 1.7 倍；慢兽（6）≈ 0.9 倍。
    """
    return max(0.2, 1.0 + (float(raw_speed) - 8.0) / 20.0)


def actor_from_stats(stats: dict, key: str = "player", name: str = "你") -> Actor:
    """battle_stats() / Enemy → Actor。"""
    return Actor(
        key=key, name=name,
        hp=stats["hp"], hp_max=stats["hp_max"],
        attack=stats["attack"], defense=stats["defense"],
        speed=stats["speed"], element=stats.get("element", "无"),
        qi=stats.get("qi", 0), qi_max=stats.get("qi_max", 0),
        qi_rate=stats.get("qi_rate", 0.0),
        stones=stats.get("stones", 0),
    )


def actor_from_enemy(enemy) -> Actor:
    """content.enemies.Enemy → Actor（灵兽：无灵气系统）。"""
    return Actor(
        key="enemy", name=enemy.name,
        hp=enemy.hp, hp_max=enemy.hp,
        attack=enemy.attack, defense=enemy.defense,
        speed=enemy_speed_multiplier(enemy.speed), element=enemy.element,
        qi=0.0, qi_max=0.0, qi_rate=0.0,
    )


@dataclass
class WindowReport:
    """一次 run_window 的结果（叙事 + 结构化）。"""
    lines: list = field(default_factory=list)
    events: list = field(default_factory=list)     # 结构化事件流
    ended: bool = False
    outcome: str = ""
    used: set = field(default_factory=set)          # 本场用过的动作键
    interrupted: int = 0                            # 被中断次数


class Battle:
    """一场战斗的会话（运行时状态，不入存档）。"""

    def __init__(self, player_stats: dict, player_actions: list, enemy,
                 rng, battle_id: int = 0, enemy_actions: list = None):
        """
        player_stats  : battle_stats() 输出
        player_actions: 可用 Action 列表
        enemy         : content.enemies.Enemy
        rng           : 复用 Game 的 Rng（随机流由本层独占，按行动实例 salt 派生）
        battle_id     : 本场战斗序号（salt 的一部分，保证跨战斗不撞车）
        enemy_actions : 敌人可用动作（默认统一 ENEMY_STRIKE）
        """
        self.rng = rng
        self.battle_id = int(battle_id)
        self.enemy = enemy
        self.p = actor_from_stats(player_stats, "player", "你")
        self.stones0 = self.p.stones          # 开战灵石（结算只扣增量，不整体覆盖）
        self.e = actor_from_enemy(enemy)
        self.actions = {a.key: a for a in (player_actions or [])}
        self.enemy_actions = list(enemy_actions or [])
        self.clock = Clock()
        self.clock.add("player", speed=self.p.speed, side=SIDE_PLAYER, at=0)
        # 敌人首次行动时刻 = 其动作总时长，且不低于 MIN_WINDOW_LI
        # （否则快敌会让开局窗口只有几十厘息，玩家根本排不了动作）
        first = self.enemy_actions[0] if self.enemy_actions else None
        e_start = total_li(first.timing, self.e.speed) if first is not None else 400
        self.clock.add("enemy", speed=self.e.speed, side=SIDE_ENEMY,
                       at=max(MIN_WINDOW_LI, e_start))
        # 过程状态
        self.queue: list = []            # 待执行的动作键
        self.timeline: list = []         # 已发生事件（结构化）
        self.used: set = set()           # 本场用过的动作键
        self._seq = 0                    # 行动实例序号（salt 用，单调递增）
        self._ended = False
        self._outcome = ""
        self.last_reason = ""

    # ============================================================
    # 查询
    # ============================================================
    def ended(self) -> bool:
        return self._ended

    def outcome(self) -> str:
        return self._outcome

    def available(self) -> list:
        """可用动作（含可用性标注，供前端渲染）。"""
        out = []
        for a in sorted(self.actions.values(), key=lambda x: (x.tier, x.key)):
            ok, reason = can_execute(self.p, self.e, a, self.clock.t)
            out.append({"key": a.key, "name": a.display(), "kind": a.kind,
                        "qi_cost": a.qi_cost, "tier": a.tier,
                        "windup": a.timing.windup, "recovery": a.timing.recovery,
                        "available": ok, "reason": reason,
                        "desc": a.desc})
        return out

    def window_li(self) -> int:
        """当前决策窗口剩余（厘息）——敌方下次行动前的时间。"""
        return self.clock.window_li("player", "enemy")

    def view(self) -> str:
        return (f"你：HP {self.p.hp:.0f}/{self.p.hp_max:.0f}  灵气 {self.p.qi:.0f}/{self.p.qi_max:.0f}\n"
                f"敌：【{self.e.name}】（{self.e.element}系）HP {self.e.hp:.0f}/{self.e.hp_max:.0f}")

    def state(self) -> dict:
        """结构化快照（前端唯一数据源）。"""
        q = []
        acc = self.clock.t
        for key in self.queue:
            a = self.actions.get(key)
            if a is None:
                continue
            from engine.clock import total_li
            acc += total_li(a.timing, self.p.effective_speed())
            q.append({"idx": len(q), "key": key, "name": a.display(),
                      "qi_cost": a.qi_cost, "end_t": acc})
        return {
            "t": self.clock.t,
            "enemy": {"id": self.enemy.id, "name": self.e.name,
                      "element": self.e.element, "realm_idx": self.enemy.realm_idx,
                      "hp": self.e.hp, "hp_max": self.e.hp_max},
            "player": {"hp": self.p.hp, "hp_max": self.p.hp_max,
                       "qi": self.p.qi, "qi_max": self.p.qi_max,
                       "qi_rate": self.p.qi_rate, "stones": self.p.stones,
                       "speed": self.p.speed},
            "queue": q,
            "window_li": self.window_li(),
            "enemy_next_t": self.clock.next_t("enemy"),
            "player_next_t": self.clock.next_t("player"),
            "effects": {
                "player": [{"key": k, "until": v["until"], "stacks": v["stacks"]}
                           for k, v in self.p.statuses.items()],
                "enemy": [{"key": k, "until": v["until"], "stacks": v["stacks"]}
                          for k, v in self.e.statuses.items()],
            },
            "ended": self._ended, "outcome": self._outcome,
            "actions": self.available(),
        }

    # ============================================================
    # 队列操作
    # ============================================================
    def submit(self, action_key: str) -> tuple:
        """把一个动作排入队列。返回 (ok, reason)。

        规则：只要当前窗口还没被已排动作填满，就允许继续排——**即使该动作本身
        跨越敌方行动时刻**（那就是"允许跨界、敌方插入"的语义，定案 §4）。
        窗口已填满（累计时长 ≥ window_li）时拒绝，提示该点「跳过」执行。
        """
        self.last_reason = ""
        if self._ended:
            self.last_reason = R_BATTLE_ENDED
            return False, R_BATTLE_ENDED
        a = self.actions.get(action_key)
        if a is None:
            self.last_reason = R_UNKNOWN_ACTION
            return False, R_UNKNOWN_ACTION
        acc = sum(total_li(self.actions[k].timing, self.p.effective_speed())
                  for k in self.queue if k in self.actions)
        if acc >= self.window_li():
            self.last_reason = R_WINDOW_OPEN     # 这一轮已排满
            return False, R_WINDOW_OPEN
        ok, reason = can_execute(self.p, self.e, a, self.clock.t)
        if not ok:
            self.last_reason = reason
            return False, reason
        self.queue.append(action_key)
        return True, ""

    def skip(self) -> tuple:
        """结束本轮编排（立即执行队列）。"""
        return True, ""

    def clear_queue(self):
        self.queue.clear()

    def unqueue(self, index) -> tuple:
        """撤回队列中第 index 个动作（0 基；不推进时间轴、不消耗资源）。返回 (ok, reason)。"""
        self.last_reason = ""
        if self._ended:
            self.last_reason = R_BATTLE_ENDED
            return False, R_BATTLE_ENDED
        try:
            i = int(index)
        except (TypeError, ValueError):
            i = -1
        if not 0 <= i < len(self.queue):
            self.last_reason = R_QUEUE_INDEX
            return False, R_QUEUE_INDEX
        self.queue.pop(i)
        return True, ""

    # ============================================================
    # 主循环：跑完一个决策窗口
    # ============================================================
    def run_window(self) -> WindowReport:
        """执行当前队列并把时间轴推进到玩家下次可动。

        返回 WindowReport（叙事行 + 结构化事件流）。战斗结束则 ended=True。
        """
        rep = WindowReport(used=set())
        if self._ended:
            rep.ended = True
            rep.outcome = self._outcome
            return rep
        if not self.queue:
            self.last_reason = R_QUEUE_EMPTY
            return rep

        queue = list(self.queue)
        self.queue.clear()

        for action_key in queue:
            if self._ended:
                break
            a = self.actions.get(action_key)
            if a is None:
                continue
            # 遁走是特殊动作（无组件；判定成功即结束战斗）
            if a.key == "flee":
                ok_flee, _ = self.flee()
                rep.events.append({"t": self.clock.t, "type": "action",
                                   "actor": "player", "action": "flee",
                                   "damage": 0, "lines": []})
                if ok_flee:
                    rep.lines.append("你全力遁走，成功脱离战斗！")
                    self._check_end(rep)
                    rep.ended, rep.outcome = self._ended, self._outcome
                    return rep
                rep.lines.append("遁走失败，只得继续纠缠……")
                self._check_end(rep)
                continue
            self._seq += 1
            ok, reason, pa = begin(self.p, self.e, a, self.clock, seq=self._seq)
            if not ok:
                rep.lines.append(f"（{a.display()} 无法施展：{reason}）")
                continue
            self.used.add(a.key)
            rep.used.add(a.key)
            # 前摇期间：让敌方行动/其它事件先行（可能打断）
            if pa.land_t > self.clock.t:
                if not self._advance_until(pa.land_t, rep):
                    # 被打断或战斗结束
                    if pa.actor.pending is not pa:
                        rep.interrupted += 1
                    continue
            # 落地
            if pa.actor.pending is not pa:
                continue          # 已被打断
            out = land(pa, self.e, self.clock, self._jitter(pa), self._hit(pa))
            self._record(out, rep)
            self._check_end(rep)
        # 队列跑完后推进到玩家下次可动（敌方可能还有行动）
        if not self._ended:
            self._close_window(rep)
        return rep

    def _close_window(self, rep: WindowReport):
        """把时间轴推进到"玩家可决策"的状态。

        返回时保证：玩家没有未落地动作，且 `next_t(player) > clock.t`
        （否则前端拿到一个"已到期但无窗口"的状态，无法继续）。
        """
        self._advance_until(self.clock.next_t("player"), rep, stop_at_player=True)
        if self._ended:
            return
        if self.p.pending is None and self.clock.next_t("player") <= self.clock.t:
            # 玩家已到期且无事可做 → 从当前时刻起算下一个窗口
            self.clock.schedule("player", Timing(windup=0, recovery=200))

    # ============================================================
    # 内部：时间推进与事件
    # ============================================================
    def _advance_until(self, deadline: int, rep: WindowReport,
                       stop_at_player: bool = False) -> bool:
        """推进时间轴到 deadline。返回 False = 玩家前摇被打断。

        事件顺序（同一时刻按此顺序）：前摇落地 → 敌方行动 → 玩家可动。
        注意：`stop_at_player=True` 时"玩家可动"也视为可停事件，且**先于**敌方行动，
        否则玩家窗口结束时敌方会多打一下（时间轴对玩家不公平）。
        """
        guard = 0
        while guard < 10000:
            guard += 1
            if self._ended:
                return True
            pa = self.p.pending
            pnext = self.clock.next_t("player")
            enext = self.clock.next_t("enemy")

            cands = []
            if pa is not None:
                cands.append((pa.land_t, 0))
            if stop_at_player:
                cands.append((pnext, 2))
            cands.append((enext, 1))
            t_ev, kind = min(cands, key=lambda x: (x[0], x[1]))
            if t_ev > deadline:
                break
            if t_ev > self.clock.t:
                self._tick(t_ev, rep)
            if kind == 0:
                return True                       # 玩家动作可落地 → 交调用方
            if kind == 2:
                return True                       # 玩家可动 → 窗口结束
            if self.e.alive():
                self._enemy_turn(rep)
            self._check_end(rep)
            if self._ended:
                return True
        if deadline > self.clock.t:
            self._tick(deadline, rep)
        return True

    def _tick(self, t_new: int, rep: WindowReport):
        """时间从当前推进到 t_new：连续回灵 + 状态到期。"""
        delta = t_new - self.clock.t
        if delta <= 0:
            self.clock.t = max(self.clock.t, t_new)
            return
        for actor in (self.p, self.e):
            if actor.qi_max > 0:
                actor.gain_qi(delta, self.clock.t)
        self.clock.t = t_new
        for actor in (self.p, self.e):
            gone = actor.expire_statuses(t_new)
            for key in gone:
                rep.lines.append(f"【{actor.name}】的【{key}】状态消散。")
                rep.events.append({"t": t_new, "type": "expire",
                                   "actor": actor.key, "key": key})

    def _enemy_turn(self, rep: WindowReport):
        """敌人行动（统一灵兽进攻；按速度决定节奏）。"""
        if not self.enemy_actions:
            return          # 无动作配置：空挥（只推进时间）
        a = self.enemy_actions[0]
        self._seq += 1
        ok, reason, pa = begin(self.e, self.p, a, self.clock, seq=self._seq)
        if not ok:
            return
        # 敌人前摇期间玩家也可能行动 → 同样按时间先后处理
        if pa.land_t > self.clock.t:
            self._advance_until(pa.land_t, rep)
        if pa.actor.pending is not pa:
            return
        out = land(pa, self.p, self.clock, self._jitter(pa), self._hit(pa))
        self._record(out, rep)

    def _record(self, out: ActionOutcome, rep: WindowReport):
        rep.lines.extend(out.lines)
        rep.events.append({"t": self.clock.t, "type": "action",
                           "actor": out.actor, "action": out.action_key,
                           "damage": out.damage, "lines": out.lines})
        self.timeline.append({"t": self.clock.t, "actor": out.actor,
                              "action": out.action_key, "damage": out.damage})
        # 控制类效果 → 打断对方未落地的动作（退灵气 + 计后摇）
        self._try_interrupt(out)

    def _try_interrupt(self, out: ActionOutcome):
        """若目标方持有控制效果，则打断其正在前摇的动作（退灵气 + 计后摇）。"""
        dst = self.e if out.actor == "player" else self.p
        if not (CONTROL_KEYS & set(dst.statuses.keys())):
            return
        pa = dst.pending
        if pa is None or pa.land_t <= self.clock.t:
            return          # 没有未落地动作 / 前摇已完成
        refund = cancel(pa)
        # 后摇照常推进（"退灵气 + 算后摇"）
        from engine.clock import recovery_li
        dst_next = pa.start_t + recovery_li(pa.action.timing, dst.effective_speed())
        self.clock.set_next_t(dst.key, max(self.clock.next_t(dst.key), dst_next))
        self.timeline.append({"t": self.clock.t, "type": "interrupt",
                              "actor": dst.key, "action": pa.action.key,
                              "refund": refund})

    def _check_end(self, rep: WindowReport):
        if self._ended:
            return
        if not self.e.alive():
            self._ended, self._outcome = True, BATTLE_WIN
            rep.lines.append(f"【{self.e.name}】轰然倒地，战斗结束！")
        elif not self.p.alive():
            self._ended, self._outcome = True, BATTLE_LOSE
            rep.lines.append("你伤势过重，眼前一黑，轰然倒下……")
        rep.ended = self._ended
        rep.outcome = self._outcome

    def _jitter(self, pa: PendingAction) -> float:
        """伤害浮动随机数：salt 含行动实例序号。"""
        salt = f"bat{self.battle_id}:{pa.actor.key}:{pa.action.key}:{pa.seq}"
        return self.rng.roll(salt)

    def _hit(self, pa: PendingAction) -> float:
        """命中判定随机数（闪避用）：与伤害浮动分不同 salt，互不串流。"""
        salt = f"bat{self.battle_id}:hit:{pa.actor.key}:{pa.action.key}:{pa.seq}"
        return self.rng.roll(salt)

    # ============================================================
    # 遁走 / 放弃
    # ============================================================
    def flee(self) -> tuple:
        """遁走判定（成功=结束战斗）。"""
        if self._ended:
            return False, R_BATTLE_ENDED
        chance = 0.5 + (self.p.speed - self.e.speed) * 0.02
        chance = max(0.2, min(0.9, chance))
        self._seq += 1
        if self.rng.chance(chance, f"bat{self.battle_id}:flee:{self._seq}"):
            self._ended, self._outcome = True, BATTLE_FLED
            return True, ""
        # 失败：推进一个动作的时间
        self.clock.schedule("player", Timing(windup=0, recovery=200))
        return False, ""

    def quit(self):
        """直接结束（无结算）——玩家主动放弃兜底用。"""
        self._ended = True
        self._outcome = self._outcome or BATTLE_FLED
