"""丹药目录（02 段：200001 起）。

规则：
  - 稳定身份 = id（int，见 content.ids 编码）。
  - 代码/掉落表引用一律用本模块导出的 id 常量（如 P.ZHUJI），禁止裸数字/中文名。
  - name 仅显示，可随意改名，不影响引用。
  - 突破丹：tier=目标大境界起点档(10/14/18/22)；bonus=成功率加成。
  - 辅助丹：effect 为行为字典。
"""
from dataclasses import dataclass, field

from content.ids import CAT_PILL, make_id

# ---- id 常量（改 id 只改这里；name 随便改，不动 id）----
ZHUJI = make_id(CAT_PILL, 1)      # 筑基丹（练气→筑基）
JIEJIN = make_id(CAT_PILL, 2)     # 结金丹（筑基→金丹）
NINGYING = make_id(CAT_PILL, 3)   # 凝婴丹（金丹→元婴）
WUDAO = make_id(CAT_PILL, 4)      # 悟道丹（元婴→化神）
QINGXIN = make_id(CAT_PILL, 5)    # 清心丹（压心魔）
JULING = make_id(CAT_PILL, 6)     # 聚灵丹（闭关加速）


@dataclass(frozen=True)
class Pill:
    id: int
    name: str
    kind: str            # "breakthrough" 突破丹 | "other" 辅助丹
    price: int           # 坊市售价（灵石）
    tier: int = 0        # 突破丹：目标大境界起点档（10/14/18/22）
    bonus: float = 0.0   # 突破丹：突破成功率加成
    effect: dict = field(default_factory=dict)  # 辅助丹：行为字典
    desc: str = ""


# ---- 突破丹 ----
_breakthrough = [
    Pill(ZHUJI, "筑基丹", "breakthrough", tier=10, bonus=0.15, price=120,
         desc="洗经伐髓，助练气圆满者筑就道基。"),
    Pill(JIEJIN, "结金丹", "breakthrough", tier=14, bonus=0.12, price=500,
         desc="凝气成丹，助筑基圆满者结成金丹。"),
    Pill(NINGYING, "凝婴丹", "breakthrough", tier=18, bonus=0.10, price=2000,
         desc="蕴神聚魂，助金丹圆满者凝结元婴。"),
    Pill(WUDAO, "悟道丹", "breakthrough", tier=22, bonus=0.10, price=8000,
         desc="感悟天道，助元婴圆满者勘破化神之门。"),
]

# ---- 辅助丹 ----
_other = [
    Pill(QINGXIN, "清心丹", "other", price=60,
         effect={"heart_demon": -30}, desc="涤荡心魔杂念。"),
    Pill(JULING, "聚灵丹", "other", price=80,
         effect={"cultivate_bonus": 0.5}, desc="闭关时服用，汇聚灵气加速修炼。"),
]

# ---- 注册表：id → Pill ----
PILLS: dict[int, Pill] = {p.id: p for p in _breakthrough + _other}

# 目标档号 → 突破丹（引擎跨大境界突破时按档查，不点名具体丹药）
BREAKTHROUGH_BY_TIER: dict[int, Pill] = {p.tier: p for p in _breakthrough}

# name → id（供 CLI 按中文名反查、旧存档中文名迁移）
ID_BY_NAME: dict[str, int] = {p.name: p.id for p in PILLS.values()}


def by_id(pid: int) -> Pill:
    return PILLS[pid]


def name_of(pid) -> str:
    if isinstance(pid, int):
        p = PILLS.get(pid)
        return p.name if p else str(pid)
    p = PILLS.get(int(pid))
    return p.name if p else str(pid)


def resolve(item) -> int:
    """玩家输入（整数 id 或中文名）→ id；找不到返回 None。"""
    if isinstance(item, int):
        return item if item in PILLS else None
    if isinstance(item, str) and item.lstrip("-").isdigit():
        pid = int(item)
        return pid if pid in PILLS else None
    return ID_BY_NAME.get(str(item))
