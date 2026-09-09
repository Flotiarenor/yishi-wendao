"""状态效果的**行为注册表**（P4-R4）：状态键 → 机械语义。

为什么需要它
------------
R3 时间轴重构后，状态只被"施加"（`Actor.statuses` 是时间窗口），但 `guard` / `evade` /
`root` 等键没有机械消费者——防御、闪避、定身类技能等于空转（见根 README「待修问题」1）。
本模块把"这个状态键到底做什么"收敛成**一张表**：`rules`（伤害乘区）、`action`（命中判定/
推后/速度）、`battle`（控制打断）都查它，`tools/content_check.py` 也用它判断模板有没有消费者。

四种行为（覆盖当前内容；新增行为 = 加一条 kind + 一个消费点）
------------------------------------------------------------
  damage_mult  伤害乘区。side=attacker（自己造成的伤害）× / side=defender（自己受到的伤害）×
  hit_negate   命中判定：以概率让打向自己的伤害落空
  push_back    施加瞬间推后**目标**的 next_t（厘息）——定身/晕眩的统一实现
  speed_mult   持续期内**自身**有效速度倍率（迟钝 = 后续动作变慢）

倍率/概率/推后量优先取 `params[param]`，缺省用 `default`。`params` 由动作数据
（`ApplyStatus.params`）声明，因此**新数值只改数据**。

标签：`push_back` 类（root/stun）在对手前摇期间还会触发打断（`battle._try_interrupt`）。
"""

from dataclasses import dataclass

# 行为种类（字符串常量，避免拼写漂移）
DMG = "damage_mult"
HIT = "hit_negate"
PUSH = "push_back"
SPEED = "speed_mult"


@dataclass(frozen=True)
class StatusRule:
    key: str
    kind: str
    side: str = ""            # damage_mult 用：attacker / defender
    default: float = 0.0
    param: str = ""           # params 中覆盖 default 的键名


# ---- 状态行为表（唯一权威；改机制改这里） ----
STATUS_RULES: dict = {r.key: r for r in (
    # 攻方乘区
    StatusRule("weaken", DMG, side="attacker", default=0.70, param="mult"),      # 破势
    StatusRule("break", DMG, side="attacker", default=0.50, param="mult"),       # 破势（强）
    # 守方乘区
    StatusRule("vulnerable", DMG, side="defender", default=1.50, param="mult"),  # 脆弱
    StatusRule("guard", DMG, side="defender", default=0.50, param="mult"),       # 护体
    # 命中判定
    StatusRule("evade", HIT, default=0.50, param="chance"),                      # 闪避
    # 控制（推后 next_t）
    StatusRule("root", PUSH, default=300, param="push_li"),                      # 定身
    StatusRule("stun", PUSH, default=500, param="push_li"),                      # 晕眩
    # 降速
    StatusRule("slow", SPEED, default=0.70, param="speed_mult"),                 # 迟钝
)}

CONTROL_KINDS = (PUSH,)
CONTROL_KEYS = frozenset(r.key for r in STATUS_RULES.values() if r.kind in CONTROL_KINDS)


def known_keys() -> frozenset:
    """引擎认识的全部状态键（含"施加后有效果"的）。"""
    return frozenset(STATUS_RULES)


def is_control(key: str) -> bool:
    return key in CONTROL_KEYS


def _params_map(statuses) -> dict:
    """归一化三种入参：

      - None / 空 → {}
      - 可迭代的 key 序列（旧 API / 测试）→ {key: {}}
      - {key: {"until":..., "params": {...}}}（Actor.statuses）或 {key: params}
    """
    if not statuses:
        return {}
    if not hasattr(statuses, "items"):
        return {k: {} for k in statuses}
    out = {}
    for k, v in statuses.items():
        if isinstance(v, dict) and isinstance(v.get("params"), dict):
            out[k] = v["params"]
        elif isinstance(v, dict):
            out[k] = v
        else:
            out[k] = {}
    return out


def _value(rule: StatusRule, params: dict) -> float:
    if rule.param and isinstance(params, dict) and rule.param in params:
        try:
            return float(params[rule.param])
        except (TypeError, ValueError):
            pass
    return float(rule.default)


def damage_mult(statuses) -> tuple:
    """状态集合 → (攻方乘区, 守方乘区)。默认 (1.0, 1.0)。"""
    att, dfn = 1.0, 1.0
    for key, params in _params_map(statuses).items():
        rule = STATUS_RULES.get(key)
        if rule is None or rule.kind != DMG:
            continue
        v = _value(rule, params)
        if rule.side == "attacker":
            att *= v
        else:
            dfn *= v
    return att, dfn


def hit_negate_chance(statuses) -> float:
    """打向该状态持有者的伤害被闪避的概率 ∈ [0,1]（取所有 hit_negate 状态的最大值）。"""
    best = 0.0
    for key, params in _params_map(statuses).items():
        rule = STATUS_RULES.get(key)
        if rule is None or rule.kind != HIT:
            continue
        best = max(best, _value(rule, params))
    return min(1.0, max(0.0, best))


def push_back_li(key: str, params: dict = None) -> int:
    """某状态施加瞬间推后目标的厘息数（非 push_back 类返回 0）。"""
    rule = STATUS_RULES.get(key)
    if rule is None or rule.kind != PUSH:
        return 0
    return max(0, int(round(_value(rule, params or {}))))


def speed_mult(statuses) -> float:
    """状态集合 → 自身有效速度倍率（多个乘性叠加，下限 0.05）。"""
    m = 1.0
    for key, params in _params_map(statuses).items():
        rule = STATUS_RULES.get(key)
        if rule is None or rule.kind != SPEED:
            continue
        m *= _value(rule, params)
    return max(0.05, m)
