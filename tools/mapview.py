"""地图查看器（P4-T2 工具）：生成世界 → 控制台 ASCII / HTML 预览。

纯查看工具，不参与游戏循环、不写存档。

用法：
  python -m tools.mapview                          # 控制台 ASCII（默认 120×60）
  python -m tools.mapview --seed 7 --w 160 --h 80  # 指定种子与尺寸
  python -m tools.mapview --html                   # 额外生成 HTML 预览并打印路径
  python -m tools.mapview --html --px 720          # 指定画布像素（越大越细）
  python -m tools.mapview --html --no-roads        # 不画路网

说明：
  - 地形用**连续采样**（`base_terrain_at`）逐点取色 → 没有"格内常数"的方块感。
  - 路 / 河用**几何折线**绘制（视觉宽度固定 1~2 px），与真实宽度无关（定案 §4.4）。
  - 城镇按 `radius_li` 画圆点。
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from content import regions as R          # noqa: E402
from engine import worldmap as WM         # noqa: E402

# 地形 id → (字符索引, 颜色)
_PALETTE = [
    (R.T_DEEPSEA, "#0b2b4a", "深海"),
    (R.T_CLIFF, "#4a4a52", "绝壁"),
    (R.T_WARD, "#6b2f6b", "禁制"),
    (R.T_VOID, "#101010", "虚空"),
    (R.T_ROAD, "#d8b26a", "官道"),
    (R.T_TRAIL, "#a08a5a", "小径"),
    (R.T_PLAIN, "#8aa860", "平原"),
    (R.T_GRASS, "#7fa055", "草原"),
    (R.T_FOREST, "#3f6b3a", "林地"),
    (R.T_HILL, "#7a8a55", "丘陵"),
    (R.T_DESERT, "#d6c07a", "沙漠"),
    (R.T_MOUNTAIN, "#8a8a8a", "山地"),
    (R.T_CANYON, "#a06a4a", "峡谷"),
    (R.T_SWAMP, "#4f6b4a", "沼泽"),
    (R.T_SNOW, "#e8eef2", "雪原"),
    (R.T_LAVA, "#b03a2a", "火山"),
    (R.T_WATER, "#2f6fa8", "水域"),
    (R.T_FORD, "#7fb0d8", "渡口"),
]
_INDEX = {tid: i for i, (tid, _c, _n) in enumerate(_PALETTE)}


def _ascii(wm, w: int, h: int, show_roads: bool = True) -> str:
    return wm.ascii_map(width=w, height=h, show_roads=show_roads, show_towns=True)


def _sample_rows(wm, px: int):
    """逐像素连续采样地形 → 每行一个字符串（字符 = 调色板索引 + 'A'）。"""
    span = float(WM._WORLD_LI)
    step = span / px
    rows = []
    for j in range(px):
        y = (j + 0.5) * step
        chars = []
        for i in range(px):
            x = (i + 0.5) * step
            tid = wm.base_terrain_at(x, y)
            chars.append(chr(65 + _INDEX.get(tid, _INDEX[R.T_PLAIN])))
        rows.append("".join(chars))
    return rows


def _build_html(wm, px: int, seed: int, show_roads: bool) -> str:
    rows = _sample_rows(wm, px)
    colors = [c for _t, c, _n in _PALETTE]
    names = [n for _t, _c, n in _PALETTE]

    roads = []
    if show_roads:
        for rd in wm.roads():
            roads.append({"pts": [list(p) for p in rd.points],
                          "kind": rd.kind})
    rivers = []
    for rv in wm.rivers():
        rivers.append({"pts": [list(p) for p in rv.points]})
    towns = [{"x": t.x, "y": t.y, "n": t.name, "m": bool(t.is_main)}
             for t in wm.towns()]
    pts = [{"x": p.x, "y": p.y, "k": p.kind} for p in wm.content_points()]

    data = {
        "px": px,
        "world": float(WM._WORLD_LI),
        "rows": rows,
        "colors": colors,
        "names": names,
        "roads": roads,
        "rivers": rivers,
        "towns": towns,
        "points": pts,
        "seed": seed,
        "cell_li": float(WM._CELL_LI),
        "checksum": wm.terrain_checksum(),
    }
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return _HTML_TMPL.replace("__DATA__", payload)


_HTML_TMPL = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>一世问道 · 世界地图预览</title>
<style>
  body{margin:0;background:#141414;color:#ddd;font:13px/1.5 system-ui,"Microsoft YaHei",sans-serif}
  header{padding:8px 12px;border-bottom:1px solid #333;display:flex;gap:16px;align-items:center;flex-wrap:wrap}
  #wrap{padding:10px}
  canvas{display:block;image-rendering:pixelated;background:#000;border:1px solid #333}
  .dim{color:#888}
  .tag{display:inline-block;padding:1px 6px;border:1px solid #444;border-radius:8px;margin-right:4px}
  .sw{display:inline-block;width:11px;height:11px;border:1px solid #555;vertical-align:-1px;margin-right:4px}
</style></head><body>
<header>
  <b>一世问道 · 世界地图预览</b>
  <span class="dim">seed <span id="seed"></span> ｜ 世界 <span id="world"></span> 里见方 ｜ 采样 <span id="px"></span>×<span id="px2"></span> ｜ 栅格 <span id="cell"></span> 里/格 ｜ checksum <span id="cs"></span></span>
  <span id="legend"></span>
</header>
<div id="wrap"><canvas id="cv"></canvas></div>
<script>
const D = __DATA__;
const cv = document.getElementById('cv');
const ctx = cv.getContext('2d');
const PX = D.px, SPAN = D.world;
cv.width = PX; cv.height = PX;
// 地形底图
for (let j = 0; j < PX; j++) {
  const row = D.rows[j];
  for (let i = 0; i < PX; i++) {
    ctx.fillStyle = D.colors[row.charCodeAt(i) - 65];
    ctx.fillRect(i, j, 1, 1);
  }
}
const s = PX / SPAN;
// 河流（视觉宽度 1.5px）
ctx.lineCap = 'round';
ctx.strokeStyle = '#4d8fd0'; ctx.lineWidth = 1.5;
for (const rv of D.rivers) {
  ctx.beginPath();
  rv.pts.forEach((p, k) => k ? ctx.lineTo(p[0]*s, p[1]*s) : ctx.moveTo(p[0]*s, p[1]*s));
  ctx.stroke();
}
// 路网（官道 1.6px 暖金 / 小径 0.9px 暗金）
for (const rd of D.roads) {
  ctx.strokeStyle = rd.kind === 'road' ? '#e8c98a' : '#9c8654';
  ctx.lineWidth = rd.kind === 'road' ? 1.6 : 0.9;
  ctx.beginPath();
  rd.pts.forEach((p, k) => k ? ctx.lineTo(p[0]*s, p[1]*s) : ctx.moveTo(p[0]*s, p[1]*s));
  ctx.stroke();
}
// 内容点（1px 小点）
ctx.fillStyle = 'rgba(255,255,255,.45)';
for (const p of D.points) ctx.fillRect(p.x*s, p.y*s, 1, 1);
// 城镇
for (const t of D.towns) {
  ctx.beginPath();
  ctx.arc(t.x*s, t.y*s, t.m ? 3.2 : 2.0, 0, 6.2832);
  ctx.fillStyle = t.m ? '#ffd45e' : '#d8b26a';
  ctx.fill();
  ctx.strokeStyle = '#1a1a1a'; ctx.lineWidth = 0.6; ctx.stroke();
}
// 标题栏信息 + 图例
document.getElementById('seed').textContent = D.seed;
document.getElementById('world').textContent = SPAN;
document.getElementById('px').textContent = PX;
document.getElementById('px2').textContent = PX;
document.getElementById('cell').textContent = D.cell_li;
document.getElementById('cs').textContent = D.checksum;
const lg = document.getElementById('legend');
lg.innerHTML = D.names.map((n, i) =>
  `<span class="tag"><span class="sw" style="background:${D.colors[i]}"></span>${n}</span>`).join('');
</script>
</body></html>
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description="世界地图查看器")
    ap.add_argument("--seed", type=int, default=20260910)
    ap.add_argument("--w", type=int, default=120, help="ASCII 宽（字符）")
    ap.add_argument("--h", type=int, default=60, help="ASCII 高（行）")
    ap.add_argument("--html", action="store_true", help="额外生成 HTML 预览")
    ap.add_argument("--px", type=int, default=560, help="HTML 画布边长（像素）")
    ap.add_argument("--no-roads", action="store_true", help="ASCII/HTML 不画路网")
    ap.add_argument("--out", default="", help="HTML 输出路径（默认 logs/map_<seed>.html）")
    a = ap.parse_args(argv)

    wm = WM.WorldMap(a.seed)
    print("== 生成世界 seed=%d ==" % a.seed)
    print("  河流 %d 条 / 城镇 %d 座 / 路网 %d 段 / 内容点 %d 个 / checksum %s"
          % (len(wm.rivers()), len(wm.towns()), len(wm.roads()),
             len(wm.content_points()), wm.terrain_checksum()))
    print("  图例：深=深海 崖=绝壁 禁=禁制 空=虚空 道=官道 径=小径 平=平原 草=草原")
    print("        林=林地 丘=丘陵 沙=沙漠 山=山地 峡=峡谷 沼=沼泽 雪=雪原 火=火山")
    print("        水=水域 渡=渡口 镇=城镇")
    print()
    print(_ascii(wm, a.w, a.h, show_roads=not a.no_roads))

    if a.html:
        html = _build_html(wm, a.px, a.seed, not a.no_roads)
        out = a.out or os.path.join(ROOT, "logs", "map_%d.html" % a.seed)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(html)
        print()
        print("== HTML 预览已生成 ==")
        print("  " + out)
        print("  用浏览器打开即可（含地形底图 / 河流 / 路网 / 城镇 / 内容点）")


if __name__ == "__main__":
    main()
