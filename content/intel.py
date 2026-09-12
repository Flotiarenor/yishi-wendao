"""情报货单（P4-T4B，定案 §5「情报是资源，可买卖」）。

**为什么单独一个模块**：`content/regions.py` 是**世界生成的确定性来源**（种子 → 地形/城镇/内容点），
往里加"货价"这种纯玩法数据会污染生成器的纯粹性（那里任何改动都要重基世界指纹）。
情报只影响**玩家已知什么**，不影响世界长什么样，故独立成 `content/intel.py`。

两类货：

| 类型 | 作用 | 可重复买 |
|---|---|---|
| **舆图**（`kind="map"`） | 升 `WorldState.map_level`（无 → 粗 → 详），**只能往上、不能降** | 否（买到顶即止） |
| **点情报**（`kind="point_intel"`） | 买一份**当地情报**：把当前位置 `radius_li` 内的内容点写进 `WorldState.discovered` | 是（可换个地方再买） |

⚠️ **第一版数值待标定**：价格是占位数（见 `engine/settings.py` 情报段注释），
应与内容点密度一起调。改价不影响世界指纹（不动地形/路网/内容点）。
"""
from dataclasses import dataclass

from engine import settings as S


@dataclass(frozen=True)
class IntelItem:
    id: str
    name: str
    price: int
    kind: str                 # "map" = 舆图档位；"point_intel" = 当地点情报
    desc: str = ""
    map_level: str = ""       # kind="map"：买到后成为哪一档（engine/settings.py MAP_LEVEL_ORDER）
    radius_li: float = 0.0    # kind="point_intel"：揭示半径（里；0 = 用 settings 默认）


# 货单（顺序 = 展示顺序）
ITEMS: tuple = (
    IntelItem(
        id="map_coarse", name="粗舆图", price=300, kind="map", map_level="coarse",
        desc="山川大势与周边城镇方位——买不起详图时的将就之选。",
    ),
    IntelItem(
        id="map_detailed", name="详图", price=2000, kind="map", map_level="detailed",
        desc="标注灵草、矿脉、兽巢之所出；路径取舍也随之看得更清（最快/最安全/最隐蔽）。",
    ),
    IntelItem(
        id="point_intel", name="当地情报", price=600, kind="point_intel",
        radius_li=S.INTEL_REVEAL_RADIUS_LI,
        desc=f"向识途的商队买一份近处虚实：{S.INTEL_REVEAL_RADIUS_LI:.0f} 里内的内容点尽入舆图。",
    ),
)

BY_ID: dict = {it.id: it for it in ITEMS}
# name → id（供按中文名反查；与丹药/功法的 id 空间不重叠，见 game._buy 的解析顺序）
ID_BY_NAME: dict = {it.name: it.id for it in ITEMS}


def by_id(iid: str) -> IntelItem:
    return BY_ID[iid]


def items_for_level(map_level: str) -> tuple:
    """当前舆图档位下**还值得买**的货：已持有同级或更高档的舆图不列（买它只会被拒）。

    点情报恒在（数量不限，换个地方再买即可）。
    `none` 档两档舆图都列——"无舆图 → 详图"一次跳档是合理买法
    （贵得多与否由**定价**决定，不由逻辑禁；硬禁会让玩家只能先买粗图过渡）。
    """
    cur = S.MAP_LEVEL_ORDER.index(map_level) if map_level in S.MAP_LEVEL_ORDER else 0
    out = []
    for it in ITEMS:
        if it.kind == "map":
            if it.map_level in S.MAP_LEVEL_ORDER and S.MAP_LEVEL_ORDER.index(it.map_level) <= cur:
                continue          # 已有同级或更高档：不卖
        out.append(it)
    return tuple(out)


def resolve(item) -> str:
    """玩家输入（id 或中文名）→ id；找不到返回 None。"""
    name = str(item or "").strip()
    if not name:
        return None
    if name in BY_ID:
        return name
    return ID_BY_NAME.get(name)
