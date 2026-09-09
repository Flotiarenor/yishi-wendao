"""战斗规则（P4-R1）：纯函数伤害与乘区计算。

规格：`docs/战斗系统定案.md` §5/§6。本模块**无状态、无 I/O、无随机源**——
随机浮动由调用方先经 Rng 取好传入（随机流仍由 battle 独占，顺序可复现）。

伤害五段乘区（顺序冻结）：
  基础威力 = 技能基础威力 × 品阶系数(tier)
  伤害 = 基础威力
       × 灵气加成        # 1 + 投入灵气 × qi_efficiency（基本线性）
       × 时长加成        # 1 + (实际总时长 ÷ 基准时长) × duration_weight
       × (1 − 减伤)      # 减伤 = 防御 ÷ (防御 + K)
       × 五行            # 克环
       × 状态            # 攻方乘区 × 守方乘区
       × 随机浮动        # ±10%
  → max(1, round(...))

"威力 ∝ 时长"不是硬规则：duration_weight 只是可调权重之一，与灵气、品阶并列（用户拍板）。
"""

import math
from dataclasses import dataclass, field, replace

# ---------- 五行"克"环（沿用 P2） ----------
KE = {"金": "木", "木": "土", "土": "水", "水": "火", "火": "金"}


def ke_mult(att_el: str, def_el: str) -> float:
    """攻方五行 vs 守方五行 → 伤害系数（同/无 = 1.0）。"""
    if att_el == "无" or def_el == "无" or att_el == def_el:
        return 1.0
    if KE.get(att_el) == def_el:
        return 1.5
    if KE.get(def_el) == att_el:
        return 0.5
    return 1.0


# ---------- 数值参数（占位，平衡统一留 P10） ----------
DEF_K = 100.0            # 减伤曲线常数：减伤 = 防御 / (防御 + DEF_K)
JITTER_SPAN = 0.2        # 随机浮动幅度（±10%）
JITTER_LOW = 0.9
BASE_DURATION_LI = 200   # 时长加成的基准时长（厘息），= 平砍后摇

# 品阶 → 基础威力系数（tier 1..4）
TIER_MULT = {1: 1.0, 2: 1.3, 3: 1.7, 4: 2.2}


def tier_mult(tier: int) -> float:
    return TIER_MULT.get(int(tier), 1.0)


def mitigation(defense: float, k: float = DEF_K) -> float:
    """减伤率 ∈ [0,1)：防御 ÷ (防御 + K)。防御越高收益递减。"""
    d = max(0.0, float(defense))
    return d / (d + float(k)) if (d + k) > 0 else 0.0


def qi_bonus(qi_spent: int, qi_efficiency: float) -> float:
    """灵气加成 = 1 + 投入灵气 × 灵气效率（基本线性 ← 用户拍板）。

    qi_efficiency 是**技能自身属性**：引气流高、品阶流低（见定案 §6）。
    """
    return 1.0 + max(0, int(qi_spent)) * float(qi_efficiency)


def duration_bonus(actual_li: int, duration_weight: float,
                   base_li: int = BASE_DURATION_LI) -> float:
    """时长加成 = 1 + (实际总时长 ÷ 基准时长) × 权重。

    duration_weight = 0 → 完全不吃时长（多数技能）；
    蓄力流用高权重（见定案 §6）。
    """
    if duration_weight <= 0 or base_li <= 0:
        return 1.0
    return 1.0 + (max(0, int(actual_li)) / float(base_li)) * float(duration_weight)


def jitter(salt_roll: float) -> float:
    """随机浮动系数：入参为 [0,1) 的随机数 → 0.9~1.1。"""
    return JITTER_LOW + float(salt_roll) * JITTER_SPAN


# ---------- 状态乘区（一攻一守镜像） ----------
# 键 = 效果模板 key，值 = (作用方, 倍率)
#   作用方 "attacker" → 乘在"造成的伤害"上（虚弱/破势）
#   作用方 "defender" → 乘在"受到的伤害"上（脆弱）
STATUS_MULT = {
    "weaken": ("attacker", 0.70),      # 虚弱：自己输出降低
    "break": ("attacker", 0.50),       # 破势：自己输出大幅降低
    "vulnerable": ("defender", 1.50),  # 脆弱：受到的伤害提高
}


def status_mult(status_keys) -> tuple:
    """一组效果键 → (攻方乘区, 守方乘区)。默认 (1.0, 1.0)。

    status_keys: 可迭代的效果键（None/未知键忽略）。
    未知键不报错——效果模板可扩展，规则层不该认识所有键。
    """
    att, dfn = 1.0, 1.0
    for k in (status_keys or ()):
        spec = STATUS_MULT.get(k)
        if spec is None:
            continue
        side, mult = spec
        if side == "attacker":
            att *= mult
        else:
            dfn *= mult
    return att, dfn


# ---------- 伤害上下文与唯一入口 ----------
@dataclass
class DamageCtx:
    """一次伤害结算的全部输入（所有字段都有安全默认值）。"""
    base: float = 0.0             # 技能基础威力
    tier: int = 1                 # 品阶
    attack: float = 0.0           # 攻方攻击力
    attack_ratio: float = 0.0     # 攻击力转化率
    defense: float = 0.0          # 守方防御
    qi_spent: int = 0             # 本次投入灵气
    qi_efficiency: float = 1.0    # 灵气效率（技能属性）
    actual_li: int = 0            # 实际总时长（厘息）
    duration_weight: float = 0.0  # 时长权重（技能属性）
    element_mult: float = 1.0     # 五行系数
    attacker_status: tuple = ()   # 攻方身上相关效果键
    defender_status: tuple = ()   # 守方身上相关效果键
    jitter_roll: float = 0.5      # 已取好的随机数 [0,1)
    extra: dict = field(default_factory=dict)   # 修饰器扩展位（armor_pen/extra_dmg…）


def resolve_damage(ctx: DamageCtx) -> int:
    """唯一伤害入口（见定案 §8：全项目只允许这一条结算路径）。"""
    power = (ctx.base + ctx.attack * ctx.attack_ratio) * tier_mult(ctx.tier)
    v = power
    # 修饰器（扩展位：穿透/固定加伤等；本阶段无内置，保持接口）
    pen = ctx.extra.get("armor_pen")
    if pen:
        v += ctx.defense * float(pen)
    extra_dmg = ctx.extra.get("extra_dmg")
    if extra_dmg:
        v += float(extra_dmg)
    v *= qi_bonus(ctx.qi_spent, ctx.qi_efficiency)
    v *= duration_bonus(ctx.actual_li, ctx.duration_weight)
    v *= (1.0 - mitigation(ctx.defense))
    v *= float(ctx.element_mult)
    att_mult, _ = status_mult(ctx.attacker_status)
    _, dfn_mult = status_mult(ctx.defender_status)
    v *= att_mult
    v *= dfn_mult
    v *= jitter(ctx.jitter_roll)
    return max(1, int(round(v)))


def preview_damage(ctx: DamageCtx) -> dict:
    """伤害预览（UI 用）：返回各乘区明细，不消耗随机流（jitter 固定 0.5）。

    供前端"这一招大概打多少"提示；**不用于判定**。
    """
    c = replace(ctx, jitter_roll=0.5)
    att_mult, _ = status_mult(c.attacker_status)
    _, dfn_mult = status_mult(c.defender_status)
    return {
        "power": (c.base + c.attack * c.attack_ratio) * tier_mult(c.tier),
        "qi_bonus": qi_bonus(c.qi_spent, c.qi_efficiency),
        "duration_bonus": duration_bonus(c.actual_li, c.duration_weight),
        "mitigation": mitigation(c.defense),
        "element_mult": float(c.element_mult),
        "status_attacker": att_mult,
        "status_defender": dfn_mult,
        "final": resolve_damage(c),
    }


# ---------- 回灵 ----------
def qi_gain(base_rate: float, delta_li: int) -> float:
    """一段时间内自动回灵量 = 速率 × Δt（厘息 → 息）。与速度无关（定案 §5）。"""
    return max(0.0, float(base_rate)) * (max(0, int(delta_li)) / 100.0)


def qi_gain_with_boost(base_rate: float, boost: float, delta_li: int) -> float:
    """含灵石加速的回灵量（灵石加速 = 一段时间内 R_base + R_boost）。"""
    return max(0.0, float(base_rate) + float(boost)) * (max(0, int(delta_li)) / 100.0)


def apply_qi_gain(qi: float, gain: float, qi_max: float) -> tuple:
    """灵气累积并封顶。返回 (新灵气, 实际获得量)。"""
    new = min(float(qi_max), float(qi) + max(0.0, float(gain)))
    return new, new - float(qi)


def can_afford(qi: float, cost: int) -> bool:
    return float(qi) >= max(0, int(cost))


def effective_interval_li(recovery: int, speed: float, qi_cost: int,
                          qi_rate: float) -> int:
    """有效出手间隔 = max(后摇÷速度, 耗灵÷回灵速率)（定案 §5 双约束）。

    这是"速度支配但灵气节流"的核心式子：
      快招（低耗）→ 后摇项主导 → 速度说了算
      重招（高耗）→ 灵气项主导 → 再快也得等灵气
    返回值单位厘息；qi_rate ≤ 0 时灵气项视为无限（只能等后摇）。
    """
    rec = recovery_li_after_speed(recovery, speed)
    if qi_cost <= 0:
        return rec
    if qi_rate <= 0:
        return rec      # 无回灵：不额外限制（由"能不能付得起"决定）
    need_li = int(math.ceil(int(qi_cost) / float(qi_rate) * 100))
    return max(rec, need_li)


def recovery_li_after_speed(recovery: int, speed: float) -> int:
    """后摇经速度缩放（与 clock.recovery_li 同式，此处避免循环 import 而重列）。"""
    if recovery <= 0:
        return 0
    return int(round(recovery / max(0.01, float(speed))))
