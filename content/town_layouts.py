"""城镇布局模板（由 `tools/town_editor.html` 导出，引擎侧消费）。

用途（P4-T5 起）：主城进入"城内"视图时，用这里的字符网格渲染城内布局 + 设施点定位。
**本文件只存数据与解码，不含玩法逻辑**；`engine/` 侧通过 `layouts_for_tier()` 取模板。

字符表（与标注工具一致）：
    . 空 / 未定   + 道路   # 建筑（涂黑）   = 城墙   G 城门
    M 坊市        I 客栈   L 藏经阁         R 静室   T 树林   p 广场
分区字符（`zone_rows`，只"留位"、内容以后填）：
    r 居民区  t 茶楼/餐馆  m 坊市/商铺  c 寺观/祠堂
    w 作坊    g 园林/空地  o 衙署/广场  s 仓储/货栈

⚠️ 水渠（原 `W`）已废：城内水系会切断道路，实测无收益。
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class TownLayout:
    """一份城镇布局模板。"""
    name: str
    tier: str                       # core / near / outer
    rows: tuple                     # 字符网格（要素层）
    zone_rows: tuple = ()           # 字符网格（分区层，可空）
    road_width: int = 3
    legend: dict = field(default_factory=dict)
    zone_legend: dict = field(default_factory=dict)
    # 导出时工具给的体检结果（errors 非空 = 这份布局有硬伤，生成时应拒用）
    errors: tuple = ()
    warnings: tuple = ()
    road_components: int = 0
    gates: int = 0

    @property
    def w(self) -> int:
        return max((len(r) for r in self.rows), default=0)

    @property
    def h(self) -> int:
        return len(self.rows)

    def tile_at(self, x: int, y: int) -> str:
        """取某格要素字符（越界返回 `.`）。"""
        if y < 0 or y >= self.h or x < 0 or x >= len(self.rows[y]):
            return "."
        return self.rows[y][x]

    def zone_at(self, x: int, y: int) -> str:
        """取某格分区字符（越界或未画返回空串）。"""
        if not self.zone_rows or y < 0 or y >= len(self.zone_rows):
            return ""
        row = self.zone_rows[y]
        if x < 0 or x >= len(row):
            return ""
        ch = row[x]
        return "" if ch == " " else ch

    def facilities(self, ch: str) -> list:
        """某类设施的坐标表 `[(x, y), …]`（ch 取 M/I/L/R/p）。"""
        out = []
        for y, row in enumerate(self.rows):
            for x, c in enumerate(row):
                if c == ch:
                    out.append((x, y))
        return out

    def stats(self) -> dict:
        from collections import Counter
        t = Counter("".join(self.rows))
        z = Counter("".join(self.zone_rows)) if self.zone_rows else Counter()
        z.pop(" ", None)
        return {"tiles": dict(t), "zones": dict(z)}


def _parse_legend(items) -> dict:
    """把工具导出的 `["+ = 道路", …]` 解析成 `{"+": "道路", …}`。"""
    out = {}
    for it in items or ():
        s = str(it)
        if "=" not in s:
            continue
        k, _, v = s.partition("=")
        k = k.strip()
        if k:
            out[k] = v.strip()
    return out


def _from_export(d: dict) -> TownLayout:
    """把标注工具导出的 JSON 转成 `TownLayout`。"""
    diag = d.get("diagnostics") or {}
    return TownLayout(
        name=str(d.get("name") or "无名镇"),
        tier=str(d.get("tier") or "outer"),
        rows=tuple(str(r) for r in (d.get("rows") or ())),
        zone_rows=tuple(str(r) for r in (d.get("zone_rows") or ())),
        road_width=int(d.get("road_width") or 3),
        legend=_parse_legend(d.get("legend")),
        zone_legend=_parse_legend(d.get("zone_legend")),
        errors=tuple(diag.get("errors") or ()),
        warnings=tuple(diag.get("warnings") or ()),
        road_components=int(diag.get("road_components") or 0),
        gates=int(diag.get("gates") or 0),
    )


# ---------- 模板（用户用 tools/town_editor.html 画好导出） ----------
# 记录：每份附带导出时的体检结果，供"能不能用"一眼判断。
_EXPORTS: list = [
    {
        # 用户第二版手绘（2026-09-10）。骨架已通、密度足够（建筑 688 格、道路 769 格），
        # 但有**12 处城墙被路撞穿**（南北主街与环墙交叉未开门）→ 标为"不可直接用"，
        # 保留作"密度/分区参考"，等补门后启用。
        "name": "青石镇",
        "tier": "outer",
        "road_width": 3,
        "legend": [". = 空 / 未定", "+ = 道路", "# = 建筑（涂黑）", "= = 城墙",
                   "M = 坊市", "I = 客栈", "L = 藏经阁", "R = 静室", "p = 广场"],
        "zone_legend": ["r = 居民区", "t = 茶楼 / 餐馆", "m = 坊市 / 商铺", "c = 寺观 / 祠堂",
                        "w = 作坊 / 工坊", "g = 园林 / 空地", "o = 衙署 / 广场", "s = 仓储 / 货栈"],
        "diagnostics": {
            "errors": ["道路分成 4 段互不相通（最大一段 759 格）——城内走不通",
                       "城墙被道路直接穿过 12 处（应改为开门 G）"],
            "warnings": ["客栈：2/39 格两格内没有路（玩家走不到）"],
            "road_components": 4,
            "gates": 0,
        },
        "rows": [
            ".......................+++......................",
            ".......................+++......................",
            "..=====================+++====================..",
            "..=RR+++++++###########+++##++##############.=..",
            "..=+++###.#+###########+++#.+++++++++++++++#.=..",
            "..=##++##.#+#####+#####+++##+#.#+#+#######+##=..",
            "..=###++++++++++++++++++++#.+###+#++++++++++#=..",
            "..=###+####+###########+++##+++++###+#++#####=..",
            "..=###++#.#+#.+I......#+++#.+###+++++++#.#...=..",
            "..=###+R#.#+#.+I......#+++##+#.#####+#+++##..=..",
            "..=###RR#.#+#+++++++++++++#.+#.....#+###++##.=..",
            "..=###R+#.#+###II######+++#.+##....#+#.##++#.=..",
            "..=###++++++++++++++++++++##++#....#+#..#.+#.=..",
            "..=###+####+####+#+####+++++++######+###.###.=..",
            "..=#+++#..#+#..#I#+#+.#+++###++++++++++++#...=..",
            "..=#+#+#..#+####.#+#++#+++#.+####+######+#...=..",
            "..=#+#+####+++++##+#++#+++##+#+##+.++#.#+#...=..",
            "..=#+#++++++###++++pp+p+++#.+##II+##+#.#+#...=..",
            "..=#+#+####+#.##.#+pp+++++##+#..#+#.++.#+##..=..",
            "..=++++#I+#+++++###pp+++++#.+#I##+###+.#++#..=..",
            "..=#+#+##+#####++++pp+++++#++#+#.+++++###+#..=..",
            "..=#+#++++++++++.I.pp+p+++#..#+#..#.#....#...=..",
            ".#=###+##MMM#######pp+p+++####.##############=#.",
            "++++++++++++++++++++++++++++++++++++++++++++++++",
            "++++++++++++++++++++++++++++++++++++++++++++++++",
            "++++++++++++++++++++++++++++++++++++++++++++++++",
            ".#=###+#########+######+++###########+#######=#.",
            "..=..#+++++++++++#.+++++++#...+#.....+#......=..",
            "..=..#+LIIIIIIII+#++++++++####+######+#......=..",
            "..=..#+LIIIII###+######+++#.++++++++#+#...II.=..",
            "..=###++++++++++++++I+++++#++#+####+++#......=..",
            "..=++++++++++++L###+I+#+++#+##+#..#.#+#......=..",
            "..=#+#+###.##LLL++++I+#+++#..#+####.##+###...=..",
            "..=#+#+++#.#.#####III##+++#.##++++III++++##..=..",
            "..=#+#+#++++++++++++++++++#.#++##+++++#+++#..=..",
            "..=#+#+#.###MMM########+++#.#+I#.####+#.#+#..=..",
            "..=#+#+#........#++++.#+++###+I.....#+###+##.=..",
            "..=#+#+#.###.###++##+##+++++++#.....#++##++#.=..",
            "..=#+#+#.#+###+++#.#+##+++#.#+#####.##+++###.=..",
            "..=#+#+#.#+++++###.#++++++#.#+++++##.#+#++.##=..",
            "..=#+#+#.#.#.#.#....###+++#.#####+++##+#.+++#=..",
            "..=#+#++#.#III#######.#+++#.....###+++#####+#=..",
            "..=#+#.++#++++++++++++#+++#.......###++++####=..",
            "..=#++##+++###########++++#.........######...=..",
            "..=#########.........##+++#..................=..",
            "..=====================+++====================..",
            "......................#+++#.....................",
            ".......................+++......................",
        ],
        "zone_rows": [
            "                                                ",
            "                                                ",
            "                                                ",
            "            ttttttttttt   wwwwwwwwwwwwwwww      ",
            "            t      tttt   wwwwwwwwwww  www      ",
            "            ttttttttttt   wwwwwwwwwwwwwwww      ",
            "  cccc                    ww wwwwwww wwwww      ",
            "   ccc        ttttttttt   ww ww wwwwwwwwww      ",
            "   ccc                    ww wwwww wwwwwww      ",
            "   ccc                    ww wwwwwwwwwwwww      ",
            "   ccc                    ww wwwwwwwwwwwww      ",
            "   ccc                    wwwwwwwwwwwwwwww      ",
            "   ccc                    wwwwwwwwwwwwwwww      ",
            "                          wwwwwwwwwwwwwwww      ",
            "                          wwwwwwwwwwwwwwww      ",
            "                                                ",
            "                                                ",
            "                                                ",
            "                                                ",
            "                                                ",
            "                                                ",
            "       mmmmmmmmm                                ",
            "      mmmmmmmmm                                 ",
            "                                                ",
            "                                                ",
            "                                                ",
            "                                                ",
            "                                                ",
            "       sssssssss                                ",
            "               s                                ",
            "       sssssssss                                ",
            "                                                ",
            "                                                ",
            "                              ssss              ",
            "                              sssssss           ",
            "         mmmmmmmmm            sssss s           ",
            "         mmmmmmmmm            sssssss           ",
            "         mmmmmmmmm            sssssss           ",
            "         mmmmmmmmm            ss ssss           ",
            "                                ssssss          ",
            "                                   sss          ",
            "                                                ",
            "                                                ",
            "                                                ",
            "                                                ",
            "                                                ",
            "                                                ",
            "                                                ",
        ],
    },
]

LAYOUTS: tuple = tuple(_from_export(d) for d in _EXPORTS)


def layouts_for_tier(tier: str, usable_only: bool = True) -> tuple:
    """取某档位可用的布局模板。

    `usable_only=True`（默认）会**剔除体检有硬伤的模板**（`errors` 非空）——
    否则城里会出现"门后无路 / 走不通"的镇子。
    """
    out = []
    for lay in LAYOUTS:
        if lay.tier != tier:
            continue
        if usable_only and lay.errors:
            continue
        out.append(lay)
    return tuple(out)


def all_layouts() -> tuple:
    return LAYOUTS
