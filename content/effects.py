"""效果模板目录（P3.8 起，P4-R4 校订；纯数据）。

状态 = **时间窗口**（`until` 厘息）；机械语义在 `engine/status.py`（唯一权威）。
本文件只提供内容层信息：

  key        稳定键（动作数据 `ApplyStatus.key` 引用，禁中文名）
  name       展示名（战报/UI；导出为 EFFECT_LABELS）
  tags       施加边约定：含 debuff/control → 目标袋；其余 → 自身袋
  default_li 默认窗口（厘息）；动作可用 `duration_li` 覆盖
  params     默认参数；动作可用 `params` 覆盖（engine.status 读这些参数）

新增一个状态 = `engine/status.py` 加一条行为 + 本文件加一条展示模板。
立即效果（回灵/治疗/购买）是**组件**（QiGain/Heal/Purchase），不是状态，不进本表。
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class EffectTemplate:
    key: str
    name: str
    tags: tuple = ()
    default_li: int = 300
    params: dict = field(default_factory=dict)
    desc: str = ""


_TEMPLATES = [
    # ---- 控制（推后 next_t；前摇中被打断） ----
    EffectTemplate("root", "定身", tags=("control",), default_li=300,
                   desc="被藤蔓/寒冰缚住，行动推后。"),
    EffectTemplate("stun", "晕眩", tags=("control",), default_li=500,
                   desc="被重击震晕，行动推后更久。"),
    # ---- 降速 ----
    EffectTemplate("slow", "迟钝", tags=("debuff",), default_li=500,
                   params={"speed_mult": 0.70}, desc="身形滞涩，后续动作变慢。"),
    # ---- 攻方乘区 ----
    EffectTemplate("weaken", "破势", tags=("debuff",), default_li=500,
                   params={"mult": 0.70}, desc="气机被扰，造成伤害降低。"),
    # ---- 守方乘区 ----
    EffectTemplate("vulnerable", "脆弱", tags=("debuff",), default_li=400,
                   params={"mult": 1.50}, desc="护体被破，受到伤害提高。"),
    EffectTemplate("guard", "护体", tags=("buff",), default_li=300,
                   params={"mult": 0.50}, desc="护体真气罩身，受到伤害降低。"),
    # ---- 命中判定 ----
    EffectTemplate("evade", "闪避", tags=("buff",), default_li=400,
                   params={"chance": 0.50}, desc="身法轻灵，概率闪开攻击。"),
]

EFFECTS: dict = {t.key: t for t in _TEMPLATES}
EFFECT_LABELS: dict = {t.key: t.name for t in _TEMPLATES}   # key→展示名（UI/兼容）


def by_key(key: str):
    """模板查找；未知键返回 None（数据层兜底）。"""
    return EFFECTS.get(key)


def register_effect(template: EffectTemplate):
    """追加/覆盖模板（生成器/测试用扩展点：新状态只加数据）。

    注意：只加模板**不会**产生机械效果——还要在 `engine/status.py` 注册行为。
    """
    EFFECTS[template.key] = template
    EFFECT_LABELS[template.key] = template.name