"""P4 地图离线渲染器（pygame 版，**离线工具，不进游戏循环**）。

和 `tools/mapview.py` 的分工：
  - `mapview`  = 控制台 ASCII + 浏览器 HTML（**要开浏览器才能看图**）
  - `maprender` = **pygame 直接渲成 PNG**：无窗口、无浏览器、纯离线、可脚本化、可纳入测试做像素回归

为什么值得存在（P4 的"改地图必须可验证"纪律缺的那一环）：
  渲染器是**纯函数**（world_seed + 视图参数 → 图像）。改了地形/路网/城镇生成之后，
  出一张基准图 + sha256 就能回答"画面到底变了哪一块"，而不是靠人眼比对 HTML。

⚠️ 与既有纪律的关系（重要）：
  - 本工具**只读**引擎（`engine/worldmap.py` 的 `base_terrain_at` / `elevation_at` / 路网 / 城镇 …），
    **不写任何状态、不改世界**；`engine/` 与 `content/` **永不 import pygame**——依赖方向单向。
  - 取色复用 `tools/mapview.py` 的调色板（单一来源），免得两处各有一套颜色。

用法：
  python -m tools.maprender                          # 出生地周边 12000 里见方，PNG → logs/map_<seed>.png
  python -m tools.maprender --radius 4000 --px 1000  # 缩小视野 / 改分辨率
  python -m tools.maprender --whole --px 1600        # 整世界（20000 里见方）
  python -m tools.maprender --x 16000 --y 4000       # 指定中心（世界坐标，里）
  python -m tools.maprender --no-shade               # 关掉高程明暗（纯平涂）
  python -m tools.maprender --sheets 2               # 分块渲染（每块单独 PNG，便于放大看细节）
"""
import argparse
import hashlib
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from content import regions as R          # noqa: E402
from engine import worldmap as WM         # noqa: E402
from tools.mapview import _PALETTE        # noqa: E402  ← 调色板单一来源


def _hex_to_rgb(h: str):
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


# 地形 id → RGB（与 mapview 同源）
_RGB = {tid: _hex_to_rgb(c) for tid, c, _n in _PALETTE}
_FALLBACK = _RGB[R.T_PLAIN]
# 快档底图缓存：{(worldmap id, shade): Surface}——同一世界只建一次
_FAST_CACHE = {}

# ---------------- 舆图风（未探索区的"纸上图"配色）----------------
# 用途：只知方位、没有实地细节的区域。**不使用 `_PALETTE`**——那是"实景"色，
# 这里要有纸面/墨线的质感，所以单独一张表；键与 `_PALETTE` 一一对应（同 18 种地形）。
_STYLE_ATLAS = {
    R.T_DEEPSEA: "#c9b98f",   # 深海：纸上留白偏深（舆图不画海色，用淡墨）
    R.T_CLIFF:   "#8a7f66",
    R.T_WARD:    "#b09a6a",
    R.T_VOID:    "#efe6cd",   # 虚空：纸边留白
    R.T_ROAD:    "#7a5c33",   # 官道：浓墨
    R.T_TRAIL:   "#9a8156",   # 小径：淡墨
    R.T_PLAIN:   "#efe3c4",
    R.T_GRASS:   "#eadfc0",
    R.T_FOREST:  "#d8cea6",
    R.T_HILL:    "#e2d5b2",
    R.T_DESERT:  "#f4ead0",
    R.T_MOUNTAIN:"#bfae88",
    R.T_CANYON:  "#c6b48d",
    R.T_SWAMP:   "#d5cdae",
    R.T_SNOW:    "#f7f2e2",
    R.T_LAVA:    "#c9a98c",
    R.T_WATER:   "#cdbf9b",   # 水域：浅墨（舆图多用留白+墨线表示水）
    R.T_FORD:    "#b9a882",
}
_RGB_ATLAS = {tid: _hex_to_rgb(c) for tid, c in _STYLE_ATLAS.items()}


def _shade(rgb, elev: float, strength: float = 0.28):
    """按高程给底色加明暗（坡度感），让"平涂"变成"地形"。

    elevator 归一到 [0,1] 后做一次轻微对比拉伸；强度可调，0 = 关闭。
    """
    k = 1.0 + (elev - 0.5) * 2.0 * strength
    if k < 0.35:
        k = 0.35
    elif k > 1.75:
        k = 1.75
    return (int(min(255, rgb[0] * k)), int(min(255, rgb[1] * k)), int(min(255, rgb[2] * k)))


def _view(args):
    """返回 (cx, cy, span_li)：视图中心与边长（正方形，单位里）。"""
    if args.whole:
        return (WM._WORLD_LI / 2.0, WM._WORLD_LI / 2.0, float(WM._WORLD_LI))
    cx = float(args.x) if args.x is not None else R.LEGACY_ANCHORS["坊市"][0]
    cy = float(args.y) if args.y is not None else R.LEGACY_ANCHORS["坊市"][1]
    return (cx, cy, float(args.radius) * 2.0)


def terrain_surface_fast(wm, px, shade=True, style="real"):
    """style: "real" = 实景色（`_PALETTE`）；"atlas" = 舆图纸面色（`_STYLE_ATLAS`）"""
    """**整世界底图（快档）**：直接读引擎缓存的全图数组，一次渲成一张底图。

    为什么快：引擎在生成期就把每个格的基础地形与高程算好存着了——
    `wm._base`（bytearray，每格 1 字节地形 id）与 `wm._elev`（每格 1 个高程）。
    实测：数组直取整张 400×400 格面 **0.035s**，而逐点连续采样同样 16 万点要 **6.45s**（**183×**）。

    ⚠️ 这是**格级**底图（会有格的方块感，因为世界栅格只有 400×400 = 50 里/格）。
    它用于"整世界 / 远距离"以及**实时平移缩放**；近距离要连续采样时用 `render_tile(detail=True)`。
    """
    import pygame
    n = WM._N                      # ⚠️ 是**模块常量** WM._N，不是实例属性
    wm._ensure_terrain()
    base = wm._base
    elev = wm._elev
    table = _RGB_ATLAS if style == "atlas" else _RGB
    strength = 0.10 if style == "atlas" else 0.28    # 舆图只做很轻的明暗，免得失去平面感
    buf = bytearray(n * n * 3)
    k = 0
    if shade:
        for idx in range(n * n):
            r, g, b = _shade(table.get(base[idx], _FALLBACK), elev[idx], strength)
            buf[k] = r; buf[k + 1] = g; buf[k + 2] = b
            k += 3
    else:
        for idx in range(n * n):
            r, g, b = table.get(base[idx], _FALLBACK)
            buf[k] = r; buf[k + 1] = g; buf[k + 2] = b
            k += 3
    surf = pygame.image.frombuffer(bytes(buf), (n, n), "RGB")
    if px and px != n:
        surf = pygame.transform.smoothscale(surf, (px, px))
    return surf


def render_tile(wm, cx, cy, span, px, shade=True, detail=True, style="real"):
    """渲染一块正方形视图：世界坐标 (cx,cy) 为中心、span 里见方 → px×px 的 Surface。

    逐像素**连续采样**（`base_terrain_at`），故格内不会出现"常数方块"（P4-T2 的既有口径）。
    """
    import pygame

    half = span / 2.0
    x0, y0 = cx - half, cy - half
    step = span / px

    # ---- 地形底图 ----
    if detail:
        # 细档：逐像素**连续采样**（无格块感，最好看）——实测 1200×1200 约 50s，适合离线出成品图。
        buf = bytearray(px * px * 3)
        base_terrain_at = wm.base_terrain_at
        elevation_at = wm.elevation_at
        table = _RGB_ATLAS if style == "atlas" else _RGB
        strength = 0.10 if style == "atlas" else 0.28
        k = 0
        for j in range(px):
            y = y0 + (j + 0.5) * step
            for i in range(px):
                x = x0 + (i + 0.5) * step
                rgb = table.get(base_terrain_at(x, y), _FALLBACK)
                if shade:
                    rgb = _shade(rgb, elevation_at(x, y), strength)
                buf[k] = rgb[0]; buf[k + 1] = rgb[1]; buf[k + 2] = rgb[2]
                k += 3
        surf = pygame.image.frombuffer(bytes(buf), (px, px), "RGB")
    else:
        # 快档：整世界底图（数组直取，约 30ms）→ 按需裁切/缩放。
        # 一次建好可复用（`_fast_cache`），故实时平移缩放只需一次 blit/scale。
        key = (id(wm), bool(shade), style)
        cached = _FAST_CACHE.get(key)
        if cached is None:
            cached = terrain_surface_fast(wm, 0, shade=shade, style=style)
            _FAST_CACHE[key] = cached
        full = cached                                   # n×n，一格一像素
        n = full.get_width()
        cell = WM._CELL_LI
        # 视图在世界里的格坐标范围 → 源矩形
        sx0 = (x0 / cell) * (n / (WM._N * 1.0))
        sy0 = (y0 / cell) * (n / (WM._N * 1.0))
        ssz = (span / cell) * (n / (WM._N * 1.0))
        src = pygame.Rect(int(round(sx0)), int(round(sy0)), max(1, int(round(ssz))), max(1, int(round(ssz))))
        sub = pygame.Surface((max(1, src.w), max(1, src.h)))
        sub.blit(full, (0, 0), src)
        surf = pygame.transform.smoothscale(sub, (px, px))

    def to_px(x, y):
        return ((x - x0) / step, (y - y0) / step)

    # ---- 河流（按长度渐变的视觉宽度；真实宽度在定案 §4.4，此处只求可读）----
    for rv in wm.rivers():
        pts = [to_px(px_, py_) for (px_, py_) in rv.points]
        w = 1.2 + min(2.0, len(rv.points) / 40.0)
        if len(pts) >= 2:
            pygame.draw.lines(surf, (77, 143, 208), False, pts, int(round(w)))
            pygame.draw.lines(surf, (120, 180, 230), False, pts, 1)   # 高光

    # ---- 路网（官道粗暖金 / 小径细暗金）----
    for rd in wm.roads():
        pts = [to_px(px_, py_) for (px_, py_) in rd.points]
        if len(pts) < 2:
            continue
        if rd.kind == "road":
            pygame.draw.lines(surf, (232, 201, 138), False, pts, 2)
        else:
            pygame.draw.lines(surf, (156, 134, 84), False, pts, 1)

    # ---- 内容点（已知/未知不在本层体现：这是"引擎视角"的图，供调试用）----
    for p in wm.content_points():
        xi, yi = to_px(p.x, p.y)
        if 0 <= xi < px and 0 <= yi < px:
            surf.set_at((int(xi), int(yi)), (245, 245, 245))

    # ---- 城镇：按影响半径画圈（半透明）----
    overlay = pygame.Surface((px, px), pygame.SRCALPHA)
    for t in wm.towns():
        xi, yi = to_px(t.x, t.y)
        r_li = wm.town_radius(t)
        r_px = r_li / step
        if -r_px <= xi <= px + r_px and -r_px <= yi <= px + r_px:
            pygame.draw.circle(overlay, (216, 178, 106, 26), (int(xi), int(yi)), max(1, int(r_px)))
            pygame.draw.circle(overlay, (216, 178, 106, 90), (int(xi), int(yi)), max(1, int(r_px)), 1)
    surf.blit(overlay, (0, 0))

    # ---- 城镇点（主城更大更亮）----
    for t in wm.towns():
        xi, yi = to_px(t.x, t.y)
        if 0 <= xi < px and 0 <= yi < px:
            r = 3 if t.is_main else 2
            pygame.draw.circle(surf, (255, 212, 94) if t.is_main else (216, 178, 106),
                               (int(xi), int(yi)), r)
            pygame.draw.circle(surf, (26, 26, 26), (int(xi), int(yi)), r, 1)

    # ---- 出生地（坊市锚点）----
    ax, ay = R.LEGACY_ANCHORS["坊市"]
    xi, yi = to_px(ax, ay)
    if 0 <= xi < px and 0 <= yi < px:
        pygame.draw.circle(surf, (255, 255, 255), (int(xi), int(yi)), 5, 2)

    # ---- 参考网格 + 坐标标注（每 1000 里一格，让它像"舆图"而不只是一张色块）----
    if px >= 300:
        grid = pygame.Surface((px, px), pygame.SRCALPHA)
        step_li = 1000.0
        gx = (int(x0 // step_li) + 1) * step_li
        while gx < x0 + span:
            gpx = (gx - x0) / step
            pygame.draw.line(grid, (255, 255, 255, 34), (gpx, 0), (gpx, px), 1)
            gx += step_li
        gy = (int(y0 // step_li) + 1) * step_li
        while gy < y0 + span:
            gpy = (gy - y0) / step
            pygame.draw.line(grid, (255, 255, 255, 34), (0, gpy), (px, gpy), 1)
            gy += step_li
        surf.blit(grid, (0, 0))

    return surf


def save_png(surf, path):
    """存 PNG。

    ⚠️ 坑：`pygame.image.save()` 只能存它**核心支持**的格式（实测 BMP 可以、PNG 会抛
    `NotImplementedError: saving images of extended format is not available`）——
    存 PNG/JPG 必须走 `pygame.image.save_extended()`。故这里优先用它，失败再退回 save。
    """
    import pygame
    os.makedirs(os.path.dirname(path), exist_ok=True)
    saver = getattr(pygame.image, "save_extended", None)
    try:
        if saver is not None:
            saver(surf, path)
        else:
            pygame.image.save(surf, path)
    except Exception:
        pygame.image.save(surf, path)
    return os.path.getsize(path)


def main(argv=None):
    ap = argparse.ArgumentParser(description="世界地图离线渲染器（pygame → PNG）")
    ap.add_argument("--seed", type=int, default=20260910)
    ap.add_argument("--px", type=int, default=1200, help="输出像素边长")
    ap.add_argument("--radius", type=float, default=6000.0, help="视野半径（里）——视图为 2r 见方")
    ap.add_argument("--whole", action="store_true", help="渲染整个世界（20000 里见方）")
    ap.add_argument("--x", type=float, default=None, help="视图中心 x（里）")
    ap.add_argument("--y", type=float, default=None, help="视图中心 y（里）")
    ap.add_argument("--no-shade", action="store_true", help="关闭高程明暗（纯平涂）")
    ap.add_argument("--fast", action="store_true",
                    help="快档：读引擎全图数组（约 30ms，格级/有方块感）；默认细档=逐像素连续采样（好看但慢）")
    ap.add_argument("--style", choices=("real", "atlas"), default="real",
                    help="配色：real=实景（现有好看的那套）；atlas=舆图纸面（给'未探索但有情报'的区域）")
    ap.add_argument("--compare", action="store_true",
                    help="出一张四象限对照图：实景 / 舆图 / 灰度反差 / 着色反差（用来挑毛病）")
    ap.add_argument("--sheets", type=int, default=1, help="分块数 N：把视野切成 N×N 块分别出图")
    ap.add_argument("--out", default="", help="输出 PNG 路径（默认 logs/map_<seed>.png）")
    a = ap.parse_args(argv)

    # ⚠️ 要在 import/init **之前**设：只用 Surface、不开窗口（否则会尝试开一个 SDL 窗口）
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")   # 渲染工具不需要音频设备
    import pygame
    pygame.init()

    t_world = time.time()
    wm = WM.WorldMap(a.seed)
    t_world = time.time() - t_world
    wm.towns(); wm.roads(); wm.rivers(); wm.content_points()   # 触发惰性生成，计时才算全

    cx, cy, span = _view(a)
    print("== 世界 seed=%d ==" % a.seed)
    print("  河 %d / 镇 %d / 路 %d 段 / 内容点 %d / checksum %s（生成 %.1fs）"
          % (len(wm.rivers()), len(wm.towns()), len(wm.roads()), len(wm.content_points()),
             wm.terrain_checksum(), t_world))
    print("  视图中心 (%.0f, %.0f)  边长 %.0f 里  输出 %d px  %s"
          % (cx, cy, span, a.px, "（整世界）" if a.whole else ""))
    print("  采样密度 %.2f 里/像素（格宽 %.0f 里 → 每格约 %.1f 像素）"
          % (span / a.px, WM._CELL_LI, a.px / (span / WM._CELL_LI)))

    t0 = time.time()
    if a.sheets > 1:
        n = a.sheets
        sub = span / n
        for sj in range(n):
            for si in range(n):
                scx = cx - span / 2 + sub * (si + 0.5)
                scy = cy - span / 2 + sub * (sj + 0.5)
                surf = render_tile(wm, scx, scy, sub, a.px, shade=not a.no_shade,
                                   detail=not a.fast)
                out = os.path.join(ROOT, "logs", "map_%d_%d%d.png" % (a.seed, sj, si))
                size = save_png(surf, out)
                print("  块 %d%d → %s（%.0f KB）" % (sj, si, out, size / 1024.0))
    else:
        surf = render_tile(wm, cx, cy, span, a.px, shade=not a.no_shade,
                           detail=not a.fast, style=a.style)
        out = a.out or os.path.join(ROOT, "logs", "map_%d.png" % a.seed)
        size = save_png(surf, out)
        h = hashlib.sha256(open(out, "rb").read()).hexdigest()[:16]
        print("  渲染 %.1fs → %s（%.0f KB，图像 sha256=%s）"
              % (time.time() - t0, out, size / 1024.0, h))
    print("  注：本工具只读引擎、不写状态；engine/content 永不 import pygame")
    pygame.quit()


if __name__ == "__main__":
    main()
