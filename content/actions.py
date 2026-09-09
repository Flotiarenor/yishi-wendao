"""动作数据（P4-R2）：所有战斗动作 = 纯数据。

规格：`docs/战斗系统定案.md` §3/§6。**本文件是唯一需要改动的战斗内容层**——
新增技能只在这里加一条 `Action`，`engine/` 零改动（这是 R2 的验收判据）。

动作分类：
  基础动作（人人可用，无灵气成本或固定成本）：平砍 / 防御 / 聚气 / 遁走 / 购买加速
  技能（品阶 1~4，各有流派倾向）：引气流（qi_efficiency 高）/ 品阶流（tier 高）/
                                  蓄力流（duration_weight 高 + 长前摇）

数值全部占位，平衡统一留 P10。
"""

from engine.action import (Action, ApplyStatus, Damage, Purchase, QiGain, Timing,
                           require_hp_below, require_target_has)

# ============================================================
# 基础动作（框架内建，不属于任何功法）
# ============================================================
ATTACK = Action(
    key="attack", name="平砍", kind="attack",
    timing=Timing(windup=0, recovery=200),
    components=(Damage(power=0, attack_ratio=1.0, element="无"),),
    qi_efficiency=0.0,          # 不耗灵，灵气加成无意义
    tier=1,
    desc="不耗灵气的基线出手，速度越快打得越密。",
)

DEFEND = Action(
    key="defend", name="防御", kind="defense",
    timing=Timing(windup=0, recovery=100),
    components=(ApplyStatus(key="guard", duration_li=300, tags=("buff",),
                            params={"mult": 0.5}),),
    desc="开一个 3 息的护体窗口（不锁后摇，可与后续动作叠加）。",
)

GATHER = Action(
    key="gather", name="聚气", kind="special",
    timing=Timing(windup=0, recovery=300),
    components=(QiGain(rate_mult=3.0),),
    desc="放弃出手，3 息换 3 倍回灵的灵气。",
)

FLEE = Action(
    key="flee", name="遁走", kind="special",
    timing=Timing(windup=0, recovery=150, windup_speed=0.0, recovery_speed=0.0),
    desc="固定耗时 1.5 息，不受速度影响。",
)

# 购买"回灵加速"：灵石是货币，买的是加速效果（定案 §5）
BUY_QI_BOOST = Action(
    key="buy_qi", name="购灵加速", kind="special",
    timing=Timing(windup=50, recovery=150),
    components=(Purchase(cost=100, boost=7.0, T_max=1000),),
    desc="支付 100 灵石，10 息内回灵 +7/息。",
)

# 低阶/高阶两档（体现"低阶回复不上来、高阶昂贵"）
# 标定后 qi_rate=1/息：加速是引气流的"开关"——实测无加速 DPS 16.3 → +15/息 后 48.9。
# 产出 = boost × T_max：低阶 24 灵气、高阶 225 灵气。
BUY_QI_LOW = Action(
    key="buy_qi_low", name="购灵加速·低阶", kind="special",
    timing=Timing(windup=50, recovery=150),
    components=(Purchase(cost=20, boost=3.0, T_max=800),),
    desc="支付 20 灵石，8 息内回灵 +3/息（共 24 灵气；后期杯水车薪）。",
)
BUY_QI_HIGH = Action(
    key="buy_qi_high", name="购灵加速·高阶", kind="special",
    timing=Timing(windup=50, recovery=150),
    components=(Purchase(cost=200, boost=15.0, T_max=1500),),
    desc="支付 200 灵石，15 息内回灵 +15/息（共 225 灵气；引气流的核心开销）。",
)

BASIC_ACTIONS = (ATTACK, DEFEND, GATHER, FLEE)

# ============================================================
# 敌人动作（用户拍板：所有敌人统一"灵兽进攻"，不做每敌技能表）
# ============================================================
# 威力全部来自敌人自身 attack（power=0, attack_ratio=1.0）；
# 前摇 1 息 → 给玩家"打断/防御"的窗口；无灵气系统（灵兽只有节奏）。
ENEMY_STRIKE = Action(
    key="enemy_strike", name="扑击", kind="attack",
    timing=Timing(windup=100, recovery=600),
    components=(Damage(power=0, attack_ratio=1.0, element="无"),),
    qi_efficiency=0.0, tier=1,
    desc="灵兽扑击：威力取决于其攻击力，节奏取决于其速度。",
)

ENEMY_ACTIONS = (ENEMY_STRIKE,)


# ============================================================
# 技能：三种流派
# ============================================================
# ---- 引气流：qi_efficiency 高 → 灵气越多越猛 ----
# 标定（qi_rate=1/息、池100）：威力/耗灵比要让"基础回灵撑不住、加速撑得住"。
# 实测焚天火海：威力60/耗灵40 → 无加速 39.0，+15/息 加速 58.5（+50%）。
# 耗灵若降到 30（=基础回灵×周期）则加速边际为 0 —— 别再把耗灵往下调。
QIANJIAN = Action(
    key="qianjian", name="千剑诀", kind="attack", qi_cost=40, tier=3,
    timing=Timing(windup=100, recovery=400),
    components=(Damage(power=60, attack_ratio=0.4, element="金"),),
    qi_efficiency=0.06, duration_weight=0.0,
    desc="引气流：灵气投入线性放大威力；实测无加速 24.4 → 加速 48.8。",
)

FENTIAN = Action(
    key="fentian", name="焚天火海", kind="attack", qi_cost=40, tier=4,
    timing=Timing(windup=150, recovery=600),
    components=(Damage(power=60, attack_ratio=0.4, element="火"),
                ApplyStatus(key="vulnerable", duration_li=400, tags=("debuff",))),
    qi_efficiency=0.08,
    desc="引气流大招：极高耗灵 + 附带脆弱；不买加速会明显掉档。",
)

# ---- 品阶流：tier 高、基础威力高、qi_efficiency 低 ----
# 后摇 200（= 平砍级）+ 低耗灵：出手频率追上平砍，靠"单次威力"取胜。
# 实测（对手速1.0/回灵3）：单次 61、间隔 2.5 息、DPS ≈ 24.4（平砍 16.5）。
RUIJIN = Action(
    key="ruijin", name="锐金剑气", kind="attack", qi_cost=4, tier=2,
    timing=Timing(windup=50, recovery=200),
    components=(Damage(power=40, attack_ratio=0.3, element="金"),),
    qi_efficiency=0.02,
    desc="品阶流：低耗高频，基础威力与品阶撑伤害，不依赖灵气池。",
)

XUANBING = Action(
    key="xuanbing", name="玄冰刺", kind="attack", qi_cost=4, tier=2,
    timing=Timing(windup=50, recovery=250),
    components=(Damage(power=38, attack_ratio=0.3, element="水"),
                ApplyStatus(key="slow", duration_li=500, tags=("debuff", "control"))),
    qi_efficiency=0.02,
    desc="品阶流：略慢但附带迟钝（推后对手行动）。",
)

# ---- 蓄力流：长前摇 + duration_weight ----
# 后摇 400 + 前摇 7 息 → 实测间隔 11 息（单技能循环）；威力按目标 DPS 下调。
XULI = Action(
    key="xuli", name="蓄力一击", kind="attack", qi_cost=6, tier=2,
    timing=Timing(windup=700, recovery=400, windup_speed=0.5),
    components=(Damage(power=24, attack_ratio=0.5, element="土"),),
    qi_efficiency=0.02, duration_weight=0.4,
    desc="蓄力流：前摇 7 息换威力，期间被打断则全损（退灵气 + 算后摇）。",
)

# ---- 控制/辅助 ----
QINGTENG = Action(
    key="qingteng", name="青藤缠", kind="utility", qi_cost=6, tier=1,
    timing=Timing(windup=50, recovery=200),
    components=(ApplyStatus(key="root", duration_li=300, tags=("control",)),),
    desc="定身：推后对手行动（本阶段以状态标记，推后量由 battle 层结算）。",
)

DIXIAN = Action(
    key="dixian", name="地陷术", kind="utility", qi_cost=5, tier=1,
    timing=Timing(windup=50, recovery=200),
    components=(ApplyStatus(key="weaken", duration_li=500, tags=("debuff",)),),
    desc="破势：对手输出降低（攻方乘区 0.7）。",
)

# ---- 条件型（演示"条件配合"：目标有虚弱时额外伤害） ----
LIANJI = Action(
    key="lianji", name="连击", kind="attack", qi_cost=8, tier=2,
    timing=Timing(windup=50, recovery=300),
    components=(Damage(power=22, attack_ratio=0.3, element="无"),
                Damage(power=15, attack_ratio=0.2, element="无")),
    conditions=(require_target_has("weaken"),),
    qi_efficiency=0.02,
    desc="条件技：目标处于破势时才能施展（组合式框架的条件演示）。",
)

# ---- 低血触发 ----
# 用户拍板：低血流就是"以降低生存换取输出"，因此威力不因条件苛刻而下调。
FENSHEN = Action(
    key="fenshen", name="焚身", kind="attack", qi_cost=0, tier=3,
    timing=Timing(windup=100, recovery=400),
    components=(Damage(power=60, attack_ratio=0.8, element="火"),),
    conditions=(require_hp_below(0.3),),
    qi_efficiency=0.0,
    desc="条件技：自身气血低于三成才可发动（不耗灵，以生存换输出）。",
)

SKILLS = {
    a.key: a for a in (
        QIANJIAN, FENTIAN, RUIJIN, XUANBING, XULI,
        QINGTENG, DIXIAN, LIANJI, FENSHEN,
    )
}

ALL_ACTIONS = {a.key: a for a in (BASIC_ACTIONS + ENEMY_ACTIONS
                                  + tuple(SKILLS.values())
                                  + (BUY_QI_LOW, BUY_QI_HIGH, BUY_QI_BOOST))}


def by_key(key: str):
    return ALL_ACTIONS.get(key)


def skills() -> list:
    """全部技能（不含基础动作），按品阶→key 排序。"""
    return sorted(SKILLS.values(), key=lambda a: (a.tier, a.key))
