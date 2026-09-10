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


# 设施要素：**一块连通的同类格子 = 一个设施**（占地 3×3 也只算一处）。
# 语义：玩家站在其中任意一格 → "身处该设施"；面板只有一个，不按格重复开。
FACILITY_CHARS: dict = {
    "M": "坊市", "I": "客栈", "L": "藏经阁", "R": "静室", "p": "广场", "G": "城门",
}
# 作为"建筑/设施"参与连通判定的字符（城墙 `=`、道路 `+` 不算设施）
_FACILITY_SET = frozenset(FACILITY_CHARS)
_NEIGH4 = ((1, 0), (-1, 0), (0, 1), (0, -1))


@dataclass(frozen=True)
class Facility:
    """城内一处设施（由连通的同类格子合并而成）。

    - `cells` = 占用的格子（可能很多格，甚至 3×3）；
    - `x`/`y` = **代表点**（取格心均值，用于导航与显示）；
    - `on_road` = 是否有格子在道路两格内（体检项：走不到 = 假设施）。
    """
    kind: str                 # M/I/L/R/p/G
    name: str                 # 坊市 / 客栈 / …
    cells: tuple              # ((x, y), …)
    x: float
    y: float
    on_road: bool = True

    @property
    def size(self) -> int:
        return len(self.cells)


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

    def cells_of(self, ch: str) -> list:
        """某字符的**全部格子** `[(x, y), …]`（3×3 坊市会返回 9 格）。"""
        out = []
        for y, row in enumerate(self.rows):
            for x, c in enumerate(row):
                if c == ch:
                    out.append((x, y))
        return out

    def facilities(self, kind: str = None) -> tuple:
        """识别设施：**把连通的同类格子合成一处**（3×3 坊市 = 1 个 Facilities，不是 9 个）。

        判定规则：4 邻接同字符 → 同一设施（对角相邻不算连通，避免两个斜角的坊市被并成一个）。
        `kind=None` 时返回全部设施，按 (kind, y, x) 排序，保证确定性。
        """
        kinds = [kind] if kind else sorted(_FACILITY_SET)
        is_road = [[self.tile_at(x, y) == "+" for x in range(self.w)] for y in range(self.h)]
        out = []
        for k in kinds:
            seen = [[False] * self.w for _ in range(self.h)]
            for y, row in enumerate(self.rows):
                for x, c in enumerate(row):
                    if c != k or seen[y][x]:
                        continue
                    # 洪泛取连通块
                    stack, cells = [(x, y)], []
                    seen[y][x] = True
                    while stack:
                        cx, cy = stack.pop()
                        cells.append((cx, cy))
                        for dx, dy in _NEIGH4:
                            nx, ny = cx + dx, cy + dy
                            if 0 <= nx < self.w and 0 <= ny < self.h \
                                    and not seen[ny][nx] and self.tile_at(nx, ny) == k:
                                seen[ny][nx] = True
                                stack.append((nx, ny))
                    # 是否有格子在道路 2 格内（否则玩家走不到）
                    near = False
                    for cx, cy in cells:
                        for r in range(1, 3):
                            for dx, dy in ((r, 0), (-r, 0), (0, r), (0, -r)):
                                nx, ny = cx + dx, cy + dy
                                if 0 <= nx < self.w and 0 <= ny < self.h and is_road[ny][nx]:
                                    near = True
                    out.append(Facility(
                        kind=k, name=FACILITY_CHARS[k], cells=tuple(sorted(cells)),
                        x=round(sum(c[0] for c in cells) / len(cells) + 0.5, 2),
                        y=round(sum(c[1] for c in cells) / len(cells) + 0.5, 2),
                        on_road=near))
        out.sort(key=lambda f: (f.kind, f.y, f.x))
        return tuple(out)

    def facility_at(self, x: int, y: int):
        """某格属于哪个设施（不属于任何设施返回 None）——用于"你站在坊市了吗"。"""
        ch = self.tile_at(x, y)
        if ch not in _FACILITY_SET:
            return None
        for f in self.facilities(ch):
            if (x, y) in f.cells:
                return f
        return None

    def stats(self) -> dict:
        from collections import Counter
        t = Counter("".join(self.rows))
        z = Counter("".join(self.zone_rows)) if self.zone_rows else Counter()
        z.pop(" ", None)
        fac = Counter(f.name for f in self.facilities())
        return {"tiles": dict(t), "zones": dict(z), "facilities": dict(fac)}


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
