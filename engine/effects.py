"""效果运行时（P3.8）：EffectInstance / EffectBag / 伤害结算与修饰器注册表。

纯逻辑零 I/O。职责分工：
  - content.effects  = 效果模板（纯数据；新效果 = register_effect 加模板，不改结算代码）
  - engine.effects  = 运行时：实例/效果袋/叠层规则/立即结算注册表/伤害公式/修饰器
  - engine.battle   = 固定管线按模板驱动施加与查询（本模块不 import battle，无环）

伤害结算 resolve_damage（无修饰器时与 P2/P3 现状公式逐位一致）：
  v = base + attack×attack_ratio − defense×defense_ratio
  → 按 MODIFIER_ORDER 应用 ctx.modifiers → ×element_mult → ×jitter → max(1, round(v))
  jitter 由调用方先经 rng 取好传入（随机流仍由 battle 独占，顺序可复现）。
"""
from dataclasses import dataclass, field

from content.effects import by_key as template_by_key
from content.effects import EffectTemplate, register_effect  # noqa: F401  (re-export)


# ---------- 立即结算 / 回合结算注册表 ----------
# fn(ctx, EffectInstance) -> list[str]：ctx 为调用方（Battle 或同构对象），返回文本行。
APPLY_FX: dict = {}      # 立即结算（duration=0 的效果；内置 "restore_qi"）
TICK_FX: dict = {}       # 每回合结算（预留；本阶段无内置）


def _restore_qi(ctx, inst):
    """吐纳：立即回灵 = regen_mult × 灵气回复速度，封顶灵气上限（不入袋）。"""
    regen_mult = inst.params.get("regen_mult", 3)
    got = min(regen_mult * ctx.p_qi_regen, ctx.p_qi_max - ctx.p_qi)
    got = int(got)
    ctx.p_qi += got
    return [f"灵气 +{got}（当前 {ctx.p_qi}/{ctx.p_qi_max}）"]


APPLY_FX["restore_qi"] = _restore_qi


# ---------- 效果实例与效果袋 ----------
@dataclass
class EffectInstance:
    key: str
    source: str = "player"
    stacks: int = 1
    duration: int = 1
    params: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"key": self.key, "source": self.source, "stacks": self.stacks,
                "duration": self.duration, "params": dict(self.params)}

    @classmethod
    def from_dict(cls, d) -> "EffectInstance":
        return cls(key=d["key"], source=d.get("source", "player"),
                   stacks=d.get("stacks", 1), duration=d.get("duration", 1),
                   params=dict(d.get("params") or {}))


class EffectBag:
    """挂在参战者身上的效果袋：按模板 stack_rule 处理 refresh/stack/ignore。

    apply 仅处理 duration>0 的"状态效果"入袋；duration=0（立即结算）
    由调用方经 APPLY_FX 直接结算，不入袋。
    """

    def __init__(self):
        self._items: dict = {}

    def apply(self, key, source="player", stacks=1, duration=None,
              params=None) -> EffectInstance | None:
        tpl = template_by_key(key)
        if tpl is None:
            return None
        dur = tpl.duration if duration is None else duration
        if dur <= 0:
            return None          # 立即效果不入袋
        merged = dict(tpl.params)
        if params:
            merged.update(params)
        inst = self._items.get(key)
        if inst is None:
            inst = EffectInstance(key=key, source=source,
                                  stacks=max(1, min(tpl.max_stacks, stacks)),
                                  duration=dur, params=merged)
            self._items[key] = inst
        elif tpl.stack_rule == "ignore":
            return inst          # 已存在则不重复施加
        elif tpl.stack_rule == "stack":
            inst.stacks = min(tpl.max_stacks, inst.stacks + stacks)
            inst.duration = dur
        else:                    # refresh：重置持续、层数保持 1
            inst.duration = dur
        inst.params = merged
        return inst

    def has(self, key) -> bool:
        return key in self._items

    def get(self, key) -> EffectInstance | None:
        return self._items.get(key)

    def remove(self, key) -> bool:
        return self._items.pop(key, None) is not None

    def tick(self) -> list:
        """duration-1；≤0 移除并返回其 key（本回合效果不泄漏下一回合）。"""
        expired = []
        for key in list(self._items):
            inst = self._items[key]
            inst.duration -= 1
            if inst.duration <= 0:
                del self._items[key]
                expired.append(key)
        return expired

    def to_list(self) -> list:
        return [i.to_dict() for i in self._items.values()]

    def clear(self):
        self._items.clear()


# ---------- 修饰器（伤害修正；作用在"防御项/固定加伤"上） ----------
MODIFIER_ORDER = ("armor_pen", "extra_dmg")   # 修饰器执行顺序（追加到末尾）

MODIFIERS: dict = {}


def _armor_pen(ctx, v, params):
    """穿透：v += 敌方防御×防御系数×params（params∈[0,1] 穿透比例）。"""
    return v + ctx.defense * ctx.defense_ratio * params


def _extra_dmg(ctx, v, params):
    """固定加伤：v += params。"""
    return v + params


MODIFIERS["armor_pen"] = _armor_pen
MODIFIERS["extra_dmg"] = _extra_dmg


def register_modifier(key, fn):
    """追加修饰器到 MODIFIER_ORDER 末尾（扩展点：新修饰器不改结算代码）。"""
    if key not in MODIFIERS:
        global MODIFIER_ORDER
        MODIFIER_ORDER = MODIFIER_ORDER + (key,)
    MODIFIERS[key] = fn


# ---------- 伤害结算 ----------
@dataclass
class DamageCtx:
    base: float = 0.0
    attack: float = 0.0
    attack_ratio: float = 0.0
    defense: float = 0.0
    defense_ratio: float = 0.0
    element_mult: float = 1.0
    jitter: float = 1.0
    modifiers: dict = field(default_factory=dict)


def resolve_damage(ctx) -> int:
    """伤害结算（见模块 docstring 公式；无修饰器时与现状逐位一致）。"""
    v = ctx.base + ctx.attack * ctx.attack_ratio - ctx.defense * ctx.defense_ratio
    for key in MODIFIER_ORDER:
        if key in ctx.modifiers:
            v = MODIFIERS[key](ctx, v, ctx.modifiers[key])
    v *= ctx.element_mult
    v *= ctx.jitter
    return max(1, round(v))
