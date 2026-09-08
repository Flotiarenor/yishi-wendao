"""效果模板目录（P3.8，纯数据）。

规则：
  - 稳定键 = key（字符串；技能数据 effect_key 引用它，禁中文名）。
  - duration：回合数；0 = 立即生效不入效果袋（须配 apply_key）。
  - stack_rule：refresh 重置持续层数保持 / stack 叠层封顶 max_stacks / ignore 已存在不重复。
  - params：模板默认参数（施加时可被覆盖），如 weaken {"mult": 0.5}。
  - 标签 tags 决定施加边：含 "debuff"/"control" → 敌效果袋；其余 → 自身效果袋（见 battle 管线）。
  - 引擎不在此 import；本模块保持纯数据，可被 content 生成器/测试直接 import。
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class EffectTemplate:
    key: str
    name: str
    tags: tuple = ()
    duration: int = 1            # 0 = 立即生效不入袋
    max_stacks: int = 1
    stack_rule: str = "refresh"  # refresh / stack / ignore
    apply_key: str = ""          # 立即结算函数键（duration=0 必填）
    tick_key: str = ""           # 每回合结算函数键（预留）
    params: dict = field(default_factory=dict)
    desc: str = ""


# ---- 内置模板（键名不可改：现有技能数据引用它们）----
_TEMPLATES = [
    EffectTemplate("root", "定身", tags=("control",), duration=1,
                   desc="敌方本回合跳过行动。"),
    EffectTemplate("weaken", "破势", tags=("debuff",), duration=1,
                   params={"mult": 0.5}, desc="敌方本回合造成伤害 ×0.5。"),
    EffectTemplate("evade", "闪避", tags=("buff",), duration=1,
                   params={"chance": 0.5}, desc="自身本回合敌攻五成落空。"),
    EffectTemplate("guard", "护体", tags=("buff",), duration=1,
                   params={"mult": 0.5}, desc="自身本回合受创 ×0.5。"),
    EffectTemplate("breath", "吐纳", tags=("buff",), duration=0,
                   apply_key="restore_qi", params={"regen_mult": 3},
                   desc="立即回灵（不入袋）。"),
]

EFFECTS: dict = {t.key: t for t in _TEMPLATES}
EFFECT_LABELS: dict = {t.key: t.name for t in _TEMPLATES}   # key→展示名（UI/兼容）


def by_key(key: str):
    """模板查找；未知键返回 None（数据层兜底）。"""
    return EFFECTS.get(key)


def register_effect(template: EffectTemplate):
    """追加/覆盖模板（生成器/测试用扩展点：新效果只加数据）。"""
    EFFECTS[template.key] = template
    EFFECT_LABELS[template.key] = template.name
