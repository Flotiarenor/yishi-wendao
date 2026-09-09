"""动作模型与执行器（P4-R2）：动作是一等公民，技能只是数据。

规格：`docs/战斗系统定案.md` §3/§6/§8。设计约束：

1. **动作 = 数据**。平砍/防御/聚气/遁走/购买灵石加速/所有技能，都是 `Action` 实例；
   框架不认识任何具体技能，只解释 `components`。
2. **加内容不改结算代码**。新增技能 = 在 `content/actions.py` 加一条数据；
   本文件只提供组件种类与执行顺序。
3. **纯逻辑零 I/O**；随机浮动由调用方先取好传入（随机流仍由上层独占）。

执行顺序（冻结）：
    条件检查 → 扣灵气 → 前摇（可被打断）→ 组件逐个结算 → 后摇（推进 next_t）
"""

from dataclasses import dataclass, field, replace
from typing import Callable, Optional

from engine import rules as R
from engine import status as ST
from engine.clock import Clock, Timing


# ============================================================
# 组件：动作的构成单元（"组合式框架"的落地）
# ============================================================
@dataclass(frozen=True)
class Damage:
    """伤害组件。power=技能基础威力；attack_ratio=攻方攻击力转化率。"""
    power: float = 0.0
    attack_ratio: float = 0.0
    element: str = "无"


@dataclass(frozen=True)
class ApplyStatus:
    """施加状态组件（时间窗口语义）。tags 含 debuff/control → 目标；其余 → 自身。"""
    key: str = ""
    duration_li: int = 300        # 持续时间（厘息）
    stacks: int = 1
    tags: tuple = ()
    params: dict = field(default_factory=dict)


@dataclass(frozen=True)
class QiGain:
    """灵气生成组件（聚气/吐纳）。倍率 × 施法者回灵速率。"""
    rate_mult: float = 3.0


@dataclass(frozen=True)
class Heal:
    """治疗组件（占位：现有内容无 heal，接口先留）。"""
    amount: float = 0.0


@dataclass(frozen=True)
class Purchase:
    """购买"回灵加速"效果组件（灵石是货币，买的是加速）。

    cost   : 支付灵石数量
    boost  : 加速提供的额外回灵速率
    T_max  : 加速持续时间（厘息）
    """
    cost: int = 0
    boost: float = 0.0
    T_max: int = 0


# ============================================================
# 条件：动作的前置/触发条件（数据化，不写 if）
# ============================================================
def require_target_has(key: str) -> Callable:
    """条件：目标身上有此状态。"""
    return lambda actor, target: target.has_status(key)


def require_self_has(key: str) -> Callable:
    """条件：自身身上有此状态。"""
    return lambda actor, target: actor.has_status(key)


def require_hp_below(ratio: float) -> Callable:
    """条件：自身 HP 低于某比例。"""
    return lambda actor, target: actor.hp_ratio() < ratio


# ============================================================
# 动作
# ============================================================
@dataclass(frozen=True)
class Action:
    """一个可执行的战斗动作（数据）。

    id        : 内容层整数 id（30 段技能 id；基础/敌人动作可为 None）。
                仅用于"功法 skill_ids ↔ 动作"的引用，引擎结算不使用。
    key       : 稳定字符串键（动作池引用键，禁中文名）
    kind      : attack / defense / utility / special（仅展示与筛选用，不参与结算）
    qi_cost   : 消耗灵气
    target    : self / enemy / all_enemies（字段先留，暂只实现单目标）
    timing    : 前摇/后摇与速度敏感度
    components: 组件列表，按顺序结算
    conditions: 全部满足才允许执行（不满足 → 动作被拒，原因码 condition_failed）
    qi_efficiency  : 灵气加成系数（技能自身属性，见定案 §6）。
                     **默认 0.0 = 灵气不额外放大伤害**（安全默认值：忘记填不会炸数值）。
    duration_weight: 时长加成权重（0 = 完全不吃时长）
    tier      : 品阶
    """
    key: str
    name: str = ""
    kind: str = "attack"
    qi_cost: int = 0
    target: str = "enemy"
    timing: Timing = field(default_factory=Timing)
    components: tuple = ()
    conditions: tuple = ()
    qi_efficiency: float = 0.0
    duration_weight: float = 0.0
    tier: int = 1
    desc: str = ""
    id: Optional[int] = None

    def display(self) -> str:
        return self.name or self.key


# ============================================================
# 参战者（R2 的最小承载：R3 由 battle.py 扩展）
# ============================================================
@dataclass
class Actor:
    """参战者。只放"结算需要读到的量"，不含流程状态。"""
    key: str
    name: str = ""
    hp: float = 100.0
    hp_max: float = 100.0
    attack: float = 10.0
    defense: float = 0.0
    speed: float = 1.0
    element: str = "无"
    qi: float = 0.0
    qi_max: float = 100.0
    qi_rate: float = 3.0            # 基础回灵速率（/息）；与速度无关
    stones: int = 0                 # 灵石余额（货币）
    # 状态：key -> {"until": 失效时刻(厘息), "stacks": n, "params": {...}}
    statuses: dict = field(default_factory=dict)
    # 回灵加速（灵石买来的）：{"until": t, "boost": r}
    qi_boost: Optional[dict] = None
    # 正在前摇中的动作（R3 打断判定用；None = 没有未落地的动作）
    pending: Optional["PendingAction"] = None

    # ---------- 查询 ----------
    def has_status(self, key: str) -> bool:
        return key in self.statuses

    def hp_ratio(self) -> float:
        return self.hp / self.hp_max if self.hp_max > 0 else 0.0

    def alive(self) -> bool:
        return self.hp > 0

    def status_keys(self) -> tuple:
        return tuple(self.statuses.keys())

    def status_params(self) -> dict:
        """{key: params} —— 供 engine.status 查询（含 ApplyStatus 声明的 params）。"""
        return {k: dict(v.get("params") or {}) for k, v in self.statuses.items()}

    def effective_speed(self) -> float:
        """基础速度 × 状态速度倍率（迟钝等）；clock 用它算前后摇。"""
        return max(0.05, float(self.speed) * ST.speed_mult(self.statuses))

    def current_qi_rate(self, t: int) -> float:
        """当前回灵速率（含灵石加速；加速到期自动失效）。"""
        rate = self.qi_rate
        if self.qi_boost and t < self.qi_boost.get("until", 0):
            rate += self.qi_boost.get("boost", 0.0)
        return rate

    # ---------- 变更 ----------
    def add_status(self, key: str, until: int, stacks: int = 1, params: dict = None):
        cur = self.statuses.get(key)
        if cur:
            cur["until"] = max(cur["until"], until)
            cur["stacks"] += stacks
        else:
            self.statuses[key] = {"until": until, "stacks": stacks,
                                  "params": dict(params or {})}

    def expire_statuses(self, t: int) -> list:
        """清理到期状态，返回到期键列表。"""
        gone = [k for k, v in self.statuses.items() if v["until"] <= t]
        for k in gone:
            del self.statuses[k]
        if self.qi_boost and self.qi_boost.get("until", 0) <= t:
            self.qi_boost = None
        return gone

    def gain_qi(self, delta_li: int, t: int) -> float:
        """按当前速率累积灵气并封顶，返回实际获得量。"""
        gain = R.qi_gain_with_boost(self.qi_rate,
                                    (self.qi_boost or {}).get("boost", 0.0)
                                    if self.qi_boost and t < self.qi_boost.get("until", 0)
                                    else 0.0,
                                    delta_li)
        self.qi, got = R.apply_qi_gain(self.qi, gain, self.qi_max)
        return got

    def take_damage(self, dmg: float) -> float:
        """扣血，返回实际损失。"""
        before = self.hp
        self.hp = max(0.0, self.hp - float(dmg))
        return before - self.hp


# ============================================================
# 执行结果
# ============================================================
@dataclass
class PendingAction:
    """一次"已投入但未落地"的动作（前摇中）。被控制打断时取消并退灵气。"""
    actor: "Actor"
    action: Action
    start_t: int
    land_t: int
    end_t: int
    qi_spent: int = 0
    seq: int = 0


@dataclass
class ActionOutcome:
    """一次动作执行的完整记录（战报/测试/前端共用）。"""
    ok: bool = True
    reason: str = ""                 # 空=成功；否则拒绝原因码
    action_key: str = ""
    actor: str = ""
    target: str = ""
    start_t: int = 0
    land_t: int = 0                  # 效果落地时刻
    end_t: int = 0                   # 可再动时刻
    qi_spent: int = 0
    qi_gained: float = 0.0
    damage: int = 0
    lines: list = field(default_factory=list)
    detail: dict = field(default_factory=dict)   # 各乘区明细（preview 用）


# ============================================================
# 执行器
# ============================================================
def can_execute(actor: Actor, target: Actor, action: Action, t: int) -> tuple:
    """能否执行 → (ok, reason)。条件不满足/灵气不足/灵石不足都给明确原因码。"""
    for cond in action.conditions:
        if not cond(actor, target):
            return False, "condition_failed"
    if action.qi_cost > 0 and actor.qi < action.qi_cost:
        return False, "low_qi"
    for comp in action.components:
        if isinstance(comp, Purchase) and actor.stones < comp.cost:
            return False, "no_stones"
    return True, ""


def begin(actor: Actor, target: Actor, action: Action, clock: Clock,
          seq: int = 0) -> tuple:
    """动作起手（R3 时间轴用）：条件/灵气检查 → 扣灵 → 登记 pending（前摇中）。

    返回 (ok, reason, pending)。**不结算任何组件**——组件在落地时由 `land()` 结算。
    这样前摇期间被控制就能取消动作（退灵气 + 计后摇，见定案 §7）。
    """
    t = clock.t
    ok, reason = can_execute(actor, target, action, t)
    if not ok:
        return False, reason, None
    spent = 0
    if action.qi_cost > 0:
        actor.qi -= action.qi_cost
        spent = action.qi_cost
    land_t, end_t = clock.schedule(actor.key, action.timing,
                                   speed=actor.effective_speed())
    pa = PendingAction(actor=actor, action=action, start_t=t, land_t=land_t,
                       end_t=end_t, qi_spent=spent, seq=seq)
    actor.pending = pa
    return True, "", pa


def land(pending: PendingAction, target: Actor, clock: Clock,
         jitter_roll: float = 0.5, hit_roll: float = 1.0) -> ActionOutcome:
    """动作落地：结算全部组件。调用方须已确认前摇完成且未被取消。

    hit_roll 为命中判定随机数（闪避用）；默认 1.0 = 不触发闪避（木桩/单测友好）。
    """
    actor, action = pending.actor, pending.action
    out = ActionOutcome(action_key=action.key, actor=actor.key,
                        target=target.key, start_t=pending.start_t,
                        land_t=pending.land_t, end_t=pending.end_t,
                        qi_spent=pending.qi_spent)
    for comp in action.components:
        _run_component(comp, actor, target, action, clock, out, jitter_roll, hit_roll)
    if actor.pending is pending:
        actor.pending = None
    return out


def cancel(pending: PendingAction) -> int:
    """打断一个前摇中的动作：退灵气（用户拍板），返回退还量。

    后摇不退还（由调用方照常推进 next_t）——即"退灵气 + 算后摇"。
    """
    actor = pending.actor
    refund = pending.qi_spent
    actor.qi = min(actor.qi_max, actor.qi + refund)
    if actor.pending is pending:
        actor.pending = None
    return refund


def execute(actor: Actor, target: Actor, action: Action, clock: Clock,
            jitter_roll: float = 0.5, hit_roll: float = 1.0) -> ActionOutcome:
    """起手 + 立即落地（便捷入口：无前摇打断场景，如木桩工具/单测）。

    有前摇的动作仍会推进 next_t，但组件当刻结算——**真战斗请用 begin()/land()**。
    """
    ok, reason, pa = begin(actor, target, action, clock)
    out = ActionOutcome(action_key=action.key, actor=actor.key,
                        target=target.key, start_t=clock.t)
    if not ok:
        out.ok = False
        out.reason = reason
        return out
    return land(pa, target, clock, jitter_roll, hit_roll)


def _run_component(comp, actor: Actor, target: Actor, action: Action,
                   clock: Clock, out: ActionOutcome, jitter_roll: float,
                   hit_roll: float = 1.0):
    if isinstance(comp, Damage):
        # 闪避：目标持有 evade 且命中判定落空 → 本次伤害归零（随机数由 battle 传入）
        chance = ST.hit_negate_chance(target.statuses)
        if chance > 0 and hit_roll < chance:
            out.lines.append(
                f"【{target.name or target.key}】身形一晃，闪开了【{action.display()}】。")
            return
        total_li = out.end_t - out.start_t
        ctx = R.DamageCtx(
            base=comp.power,
            tier=action.tier,
            attack=actor.attack,
            attack_ratio=comp.attack_ratio,
            defense=target.defense,
            qi_spent=out.qi_spent,
            qi_efficiency=action.qi_efficiency,
            actual_li=total_li,
            duration_weight=action.duration_weight,
            element_mult=R.ke_mult(comp.element, target.element),
            attacker_status=actor.status_params(),
            defender_status=target.status_params(),
            jitter_roll=jitter_roll,
        )
        dmg = R.resolve_damage(ctx)
        target.take_damage(dmg)
        out.damage += dmg
        out.detail = R.preview_damage(ctx)
        out.lines.append(
            f"【{action.display()}】命中【{target.name or target.key}】，造成 {dmg} 点伤害。")
    elif isinstance(comp, ApplyStatus):
        side = target if ("debuff" in comp.tags or "control" in comp.tags) else actor
        side.add_status(comp.key, clock.t + comp.duration_li,
                        comp.stacks, comp.params)
        out.lines.append(
            f"【{action.display()}】对【{side.name or side.key}】施加"
            f"【{comp.key}】（{comp.duration_li / 100:.1f} 息）。")
        # 控制类：施加瞬间推后目标 next_t（定身/晕眩；迟钝走速度倍率）
        push = ST.push_back_li(comp.key, comp.params)
        if side is target and push:
            clock.push_back(side.key, push)
            out.lines.append(
                f"【{side.name or side.key}】被控，行动推后 {push / 100:.1f} 息。")
    elif isinstance(comp, QiGain):
        got = min(actor.qi_max - actor.qi,
                  comp.rate_mult * actor.current_qi_rate(clock.t))
        actor.qi += max(0.0, got)
        out.qi_gained += max(0.0, got)
        out.lines.append(f"【{action.display()}】聚气，灵气 +{got:.0f}。")
    elif isinstance(comp, Heal):
        before = actor.hp
        actor.hp = min(actor.hp_max, actor.hp + comp.amount)
        out.lines.append(
            f"【{action.display()}】回复 {actor.hp - before:.0f} 点气血。")
    elif isinstance(comp, Purchase):
        if actor.stones < comp.cost:
            out.ok = False
            out.reason = "no_stones"
            out.lines.append(f"灵石不足：需 {comp.cost}，你有 {actor.stones}。")
            return
        actor.stones -= comp.cost
        until = clock.t + comp.T_max
        actor.qi_boost = {"until": until, "boost": comp.boost}   # 不可叠加：覆盖
        out.lines.append(
            f"你支付 {comp.cost} 灵石，购得回灵加速：{comp.boost:.0f}/息，"
            f"持续 {comp.T_max / 100:.1f} 息。")
    else:
        raise TypeError(f"未知组件类型：{type(comp).__name__}")


# ============================================================
# 便捷：构造动作的常用形态（内容层复用）
# ============================================================
def attack_action(key: str, name: str, power: float, qi_cost: int = 0,
                  element: str = "无", tier: int = 1,
                  recovery: int = 200, windup: int = 0,
                  qi_efficiency: float = 0.0,
                  attack_ratio: float = 0.0,
                  extra_components: tuple = ()) -> Action:
    """构造一个"攻击型"动作（含伤害组件 + 可选附加组件）。"""
    comps = (Damage(power=power, attack_ratio=attack_ratio, element=element),) \
        + tuple(extra_components)
    return Action(key=key, name=name, kind="attack", qi_cost=qi_cost,
                  timing=Timing(windup=windup, recovery=recovery),
                  components=comps, qi_efficiency=qi_efficiency, tier=tier)
