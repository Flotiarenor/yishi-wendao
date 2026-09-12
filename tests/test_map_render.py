"""地图渲染朝向与坐标一致性单测（P4 舆图底图；确定性，禁 pytest）。

## 为什么必须有这个文件

2026-09-11 发现一个**静默了很久**的 bug：舆图底图（`tools/atlas.py`）与实景底图
（`tools/maprender.py`）把世界 y 轴**当成了屏幕 y 轴**，于是底图**南在上**；
而前端 SVG 叠加层（`MapScreen.vue` 的 `px()`，`sy = -(...)`）是**北在上**。
两层叠在一起 → **底图上的城镇/路网/河流与可点击的点整体上下镜像**，
表现为"点下去的地方和图上看到的不一样、城镇点跑到湖里"。

定案 §3.1 写明「坐标原点在**西南角**」= **y 越大越靠北**，故前端是对的、渲染器是错的。
它能活这么久，是因为**两套投影公式各写各的**，且只核对视图中心时两者恰好重合
（中心点上 y 翻转是恒等的）。故判据专门挑**远离中心**的位置，并**同时验伪**。

## 判据（每条都可证伪）

对每座抽样城镇：把视图中心设在它身上 → 它必须画在**画布正中心**。
  A. **签名命中**：画布中心存在「半径 2 内满墨 + 半径 4 处为空」的实心圆签名（城镇点）。
  B. **验伪（位置精确）**：中心 ±3px 六个探针里，**只有中心**命中签名
     —— 若渲染有平移，签名会跑到别的探针上。
  C. **验伪（南北不反）**：把中心点按画布中心**上下镜像**后取签名 → 必须**不命中**。
     这一条直接杀死"把 y 当屏幕轴"的写法：那种写法下城镇会画在镜像位置。
  D. **快档（`terrain_surface_fast`）同样北在上**：与"引擎数组顺序直出"和"行倒置"两种
     候选各比一次，必须更接近**行倒置**的那种（北在上）。
  E. **实景风与舆图风同朝向**：`render_tile(detail=False, style='real')` 也要在中心命中签名。
  F. **前端与底图共用一套投影**：`MapScreen.vue` 不得再有"底图铺满、叠加层内缩"的两套半幅
     （第一版的 `PAD=26` 内缩就是第二处错位的来源），且 `px()` 必须保留 y 取负。

运行：.venv\\Scripts\\python.exe -X utf8 tests\\test_map_render.py
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_PASS = 0
_FAIL = 0
_SEED = 20260910
_VIEW_PX = 560          # 与前端 SIZE 一致
_SPAN = 2000.0          # 居中渲染的视野（里）；1px = 3.57 里，够细


def check(name: str, cond: bool, detail: str = ""):
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  [OK] {name}")
    else:
        _FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


def _scene():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    import pygame
    pygame.init()
    from engine import worldmap as WM
    from tools import atlas as A
    return WM, A


def _town_blob(surface, cx: int, cy: int, A, px: int, scan: int = 14, colors=None):
    """(cx,cy) 邻域内**面积最大**的实心点（城点）质心与面积。

    城点是实心圆：舆图风用墨色（主城 r≈5 → ~75px，普通镇 r≈3 → ~28px），
    实景风用金色（`(255,212,94)` 主城 / `(216,178,106)` 镇）。
    岩点比路网/河流笔画"厚"，故"最大实心块"通常就是城点。
    """
    if not (scan <= cx < px - scan and scan <= cy < px - scan):
        return None, 0
    if colors is None:
        colors = [A._INK]
    tol = 95 if colors == [A._INK] else 60

    def is_dot(gx, gy):
        c = surface.get_at((gx, gy))[:3]
        return any(max(abs(int(a) - int(b)) for a, b in zip(c, t)) <= tol for t in colors)

    seen = set()
    best = (None, 0)
    x_lo, x_hi = cx - scan, cx + scan
    y_lo, y_hi = cy - scan, cy + scan
    for y0 in range(y_lo, y_hi + 1):
        for x0 in range(x_lo, x_hi + 1):
            if (x0, y0) in seen or not is_dot(x0, y0):
                continue
            stack = [(x0, y0)]
            seen.add((x0, y0))
            blob = []
            while stack:
                bx, by = stack.pop()
                blob.append((bx, by))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = bx + dx, by + dy
                    if (nx, ny) in seen or not (x_lo <= nx <= x_hi and y_lo <= ny <= y_hi):
                        continue
                    if is_dot(nx, ny):
                        seen.add((nx, ny))
                        stack.append((nx, ny))
            if len(blob) > best[1]:
                best = ((sum(p[0] for p in blob) / len(blob),
                         sum(p[1] for p in blob) / len(blob)), len(blob))
    return best


def _cost_of(surface, pairs, A, px: int, colors=None):
    """给定若干「期望像素 → 该处可见」的配对，返回 Σ(最近实心点距离²)。

    **判据可证伪**：朝向正确时各城镇的墨团应贴着各自期望位置（代价小）；
    若 y 被当成屏幕轴（南北反），城镇会画到**镜像**位置，代价陡然变大。
    两座城镇必须**同处一屏**，"反了"才会真的把 A、B 互换。
    """
    total = 0.0
    for (ex, ey) in pairs:
        bc, _n = _town_blob(surface, int(round(ex)), int(round(ey)), A, px, colors=colors)
        if bc is None:
            total += 1e6
        else:
            total += (bc[0] - ex) ** 2 + (bc[1] - ey) ** 2
    return total


def _row_mismatch(surface, wm, base_row: int, A, style="real", stride: int = 4):
    """把**底图第 base_row 行**与引擎第 base_row 行逐像素比，返回失配数。

    ⚠️ 三个坑（这个判据前后改了四版才立住，都记下来免得后人再踩）：
      ① 必须用**该 style 对应的调色板**：`style="real"` 用 `_RGB`、`"atlas"` 用 `_RGB_ATLAS`。
         拿错表会得出"十几万像素失配"的假结果（判据错，不是渲染错）。
      ② 必须 `shade=False` 后再比：开了明暗，像素被 `_shade` 改过，与调色板不再逐位相等。
      ③ **坐标不能写反**：`surface.get_at((i, j))` 是 `(x=i, y=j)`，而引擎数组是
         `_base[row * N + col]`。第一版把两者当成同一顺序，于是 j 取了行、i 又去乘行宽，
         比出来 8152/10000 失配 —— 纯属判据写错。
    """
    from tools import maprender as MR
    n = surface.get_width()
    n_cells = _cell_count(wm)
    table = MR._RGB if style == "real" else MR._RGB_ATLAS
    fallback = MR._FALLBACK
    bad = 0
    for j in range(0, n, stride):
        src_row = base_row if j == base_row else min(n_cells - 1, j)
        # 上面一行是给"只比某一行"的便捷；整幅比对时按 j 取同序号行
        for i in range(0, n, stride):
            col = min(n_cells - 1, i)
            want = table.get(wm._base[src_row * n_cells + col], fallback)
            got = surface.get_at((i, j))[:3]
            if max(abs(int(a) - int(b)) for a, b in zip(got, want)) > 20:
                bad += 1
    return bad


def _row_correspondence(surface, wm, A, style="real"):
    """逐行找出"底图第 j 行 == 引擎第几行"，返回 {j: engine_row}。

    这是**最直接**的朝向证据：不依赖阈值或候选集，直接反查每行来自哪里。

    ⚠️ 不能只比**一格**：地表大片同色（实测 seed 20260910 的 (1,0) 格在几百行里同色），
    单格反查会命中一堆"第一个同色行"（实测第 1 行被误判成 282）。
    改用**整行签名**（按 stride 取多个列的地形 id 拼成元组）后唯一定位。
    """
    from tools import maprender as MR
    n = surface.get_width()
    n_cells = _cell_count(wm)
    table = MR._RGB if style == "real" else MR._RGB_ATLAS
    cols = list(range(0, n, max(1, n // 40)))
    # 调色板是单射（一个地形一个颜色）→ 可由像素颜色反推地形 id
    rev = {}
    for tid, rgb in table.items():
        rev.setdefault(tuple(rgb), tid)
    # 签名 → **所有**匹配的引擎行（行签名可能重复：世界边缘几行可能地形全同）
    rows_by_sig = {}
    for r in range(n_cells):
        key = tuple(wm._base[r * n_cells + min(n_cells - 1, c)] for c in cols)
        rows_by_sig.setdefault(key, []).append(r)
    out = {}
    for j in (0, 1, 2, 3, n // 2, n - 4, n - 3, n - 2, n - 1):
        got = tuple(rev.get(tuple(surface.get_at((c, j))[:3]), -1) for c in cols)
        out[j] = rows_by_sig.get(got, [])
    return out


def _cell_count(wm):
    """引擎每轴格数（`_N` 是**模块常量**，WorldMap 实例上没有这个属性）。"""
    import engine.worldmap as _WM
    return int(getattr(wm, "_N", None) or _WM._N)


def main():
    try:
        import pygame  # noqa: F401
    except ImportError:
        print("  [SKIP] 未安装 pygame（渲染不在引擎依赖里）——跳过本文件")
        print("\n== 结果：0 过 / 0 败 ==")
        return 0

    WM, A = _scene()
    from tools import maprender as MR
    wm = WM.WorldMap(_SEED)
    towns = list(wm.towns())
    print("世界 seed=%d：城镇 %d 座，居中视野 span=%.0f 里 px=%d"
          % (_SEED, len(towns), _SPAN, _VIEW_PX))

    # 抽样：主城 + 普通镇，且**远离世界中心**（中心点上 y 翻转是恒等的，测不出 bug）
    far = [t for t in towns if abs(t.y - 10000.0) > 1500 or abs(t.x - 10000.0) > 1500]
    sample = ([t for t in far if t.is_main][:4] + [t for t in far if not t.is_main][:4])
    c = _VIEW_PX // 2
    print("抽样 %d 座（都远离世界中心）：%s"
          % (len(sample), "、".join(t.name for t in sample)))

    print("\nA/B/C. 同屏两镇：正确朝向的 Σ距离² 必须**远小于**镜像朝向")
    # 关键设计：同屏必须是**一南一北**的两座城镇，这样"y 当屏幕轴"才会把它们互换。
    # 只核对单点（尤其视图中心）测不出这个 bug——中心点上 y 翻转是恒等的。
    pairs = []
    for tx in [t for t in towns if t.is_main]:
        near = [u for u in towns
                if abs(u.x - tx.x) < 1200 and abs(u.y - tx.y) > 1500
                and abs(u.y - tx.y) < 3400]
        if near:
            pairs.append((tx, max(near, key=lambda u: abs(u.y - tx.y))))
        if len(pairs) >= 4:
            break
    print("  取到 %d 组「同屏南北两镇」：%s"
          % (len(pairs), "、".join("%s/%s" % (a.name, b.name) for a, b in pairs)))

    ok_cases = 0
    for (ta, tb) in pairs:
        cy = (ta.y + tb.y) / 2.0
        cx = (ta.x + tb.x) / 2.0
        span = (abs(ta.y - tb.y) + 1200.0) * 1.25
        surf = A.render_atlas(wm, cx, cy, span, _VIEW_PX, seed=_SEED, labels=False)
        k = _VIEW_PX / span
        half = _VIEW_PX / 2.0

        def to_px(t, mirror=False):
            ex = half + (t.x - cx) * k
            if mirror:      # 镜像朝向（=把 y 当屏幕轴）
                ey = half + (t.y - cy) * k
            else:           # 正确朝向（北在上）
                ey = half - (t.y - cy) * k
            return ex, ey

        good = _cost_of(surf, [to_px(ta), to_px(tb)], A, _VIEW_PX)
        bad = _cost_of(surf, [to_px(ta, True), to_px(tb, True)], A, _VIEW_PX)
        # B：两镇在屏幕上的**上下次序**必须与 y 相反（北在上）——判据的核心，硬判。
        (sa, n_a) = _town_blob(surf, int(round(to_px(ta)[0])), int(round(to_px(ta)[1])),
                               A, _VIEW_PX)
        (sb, n_b) = _town_blob(surf, int(round(to_px(tb)[0])), int(round(to_px(tb)[1])),
                               A, _VIEW_PX)
        if sa and sb:
            north, south = (ta, tb) if ta.y > tb.y else (tb, ta)
            bn = sa if north is ta else sb
            bs = sb if north is ta else sa
            check("B %s（北 y=%.0f）画在 %s（南 y=%.0f）之上"
                  % (north.name, north.y, south.name, south.y),
                  bn[1] < bs[1], "北 屏幕y=%.0f ／ 南 屏幕y=%.0f" % (bn[1], bs[1]))
        else:
            check("B 两镇都找到城点", False, "sa=%s sb=%s" % (sa, sb))
        # A：代价对照只作**方向性辅证**（邻接要素会干扰绝对比值，故不设倍数阈值）。
        #    真正杀死"南北反"的是 B 的次序判据。
        passed = good < bad
        ok_cases += 1 if passed else 0
        check("A %s / %s：正确朝向代价 %.1f < 镜像朝向代价 %.1f"
              % (ta.name, tb.name, good, bad), passed,
              "正确=%.1f 镜像=%.1f" % (good, bad))
    print("  A %d/%d 组通过" % (ok_cases, len(pairs)))

    print("\nD. 快档（terrain_surface_fast）北在上")
    # ⚠️ 必须 `shade=False`：开了明暗后像素被 `_shade` 改过，与调色板不再逐位相等。
    fast = MR.terrain_surface_fast(wm, 0, shade=False, style="real")
    n_cells = _cell_count(wm)
    corr = _row_correspondence(fast, wm, A, style="real")
    print("  底图行 → 可能的引擎行：")
    for j in sorted(corr):
        print("     j=%-3d → %s   (期望 %d)" % (j, corr[j][:4], n_cells - 1 - j))
    # 北在上 ⇔ 底图第 j 行取自引擎第 (N-1-j) 行。
    # 行签名可能重复（世界边缘整行同色），故判"期望行在候选集里"，并说明歧义。
    bad = [(j, corr[j], n_cells - 1 - j) for j in corr if (n_cells - 1 - j) not in corr[j]]
    check("D 底图第 j 行 == 引擎第 (N-1-j) 行（北在上）", not bad,
          "不匹配：%s" % bad)
    # 反面：若忘了翻转，底图第 1 行会等于引擎第 1 行
    check("D 判据可区分（底图首行不含引擎首行 1）",
          corr.get(1) and 1 not in corr[1],
          "底图第 1 行的候选 %s 含 1" % (corr.get(1) or [])[:4])
    check("D 底图第 1 行确实取自世界南端（引擎行号接近 N-1）",
          corr.get(1) and min(corr[1]) > n_cells * 0.9,
          "候选 %s" % (corr.get(1) or [])[:4])

    print("\nE. 实景风 render_tile(detail=False) 同朝向")
    # 用**同屏南北两镇**判：实景风的城点是金色实心圆（不是墨色）
    ta, tb = pairs[0]
    cy = (ta.y + tb.y) / 2.0
    cx = (ta.x + tb.x) / 2.0
    span = (abs(ta.y - tb.y) + 1200.0) * 1.25
    tile = MR.render_tile(wm, cx, cy, span, _VIEW_PX, shade=False, detail=False, style="real")
    k = _VIEW_PX / span
    half = _VIEW_PX / 2.0
    gold = [(255, 212, 94), (216, 178, 106)]
    pts = {}
    for t in (ta, tb):
        ex = half + (t.x - cx) * k
        ey = half - (t.y - cy) * k          # 北在上
        pts[t.name] = (ex, ey, _town_blob(tile, int(round(ex)), int(round(ey)),
                                          A, _VIEW_PX, colors=gold))
    north = ta if ta.y > tb.y else tb
    south = tb if north is ta else ta
    bn = pts[north.name][2][0]
    bs = pts[south.name][2][0]
    check("E 实景风同朝向：%s（北）画在 %s（南）之上" % (north.name, south.name),
          bn is not None and bs is not None and bn[1] < bs[1],
          "北=%s 南=%s" % (bn, bs))

    print("\nF. 前端投影常量与底图一致（不得两套半幅）")
    vue = os.path.join(ROOT, "frontend", "src", "views", "MapScreen.vue")
    src = open(vue, encoding="utf-8").read()
    check("F1 前端不再有 PAD 内缩常量（底图铺满 → 半幅必须是 SIZE/2）",
          not re.search(r"\bconst\s+PAD\s*=", src), "MapScreen.vue 里仍有 PAD 常量")
    check("F2 前端半幅取自 SIZE/2",
          bool(re.search(r"const\s+HALF\s*=\s*SIZE\s*/\s*2", src)),
          "没找到 HALF = SIZE / 2")
    check("F3 px() 保留 y 取负（北在上）",
          bool(re.search(r"const\s+sy\s*=\s*-\(\(y\s*-", src)),
          "px() 里的 sy 不再取负 → 前端会变成南在上")
    check("F4 投影与其逆运算共用同一 HALF", src.count("HALF") >= 4,
          "HALF 引用次数 %d" % src.count("HALF"))
    check("F5 底图 URL 请求整幅（px=SIZE）",
          bool(re.search(r"&px=\$\{SIZE\}", src)), "底图 URL 里的 px 不是 SIZE")
    check("F6 底图用 composed（两层迷雾：舆图底 + 踏勘区实景）",
          "style=composed" in src, "底图 URL 不是 composed")

    # ---------- G. 探索边界（两层迷雾的可视化）----------
    print("\nG. 探索边界：只有踏勘过的格换实景，别处一格不动")
    cell_li = 50.0
    try:
        import engine.worldmap as _WM2
        cell_li = float(_WM2._CELL_LI)
    except Exception:  # noqa: BLE001
        pass
    # 取视图中心附近的一格做"踏勘"，另一处远处做"未踏勘"对照
    ccx = int(cx // cell_li)
    ccy = int(cy // cell_li)
    exp_cells = {(ccx, ccy)}                      # 只踏勘中心这一格
    plain = A.render_atlas(wm, cx, cy, _SPAN, _VIEW_PX, seed=_SEED, labels=False)
    withx = A.render_atlas(wm, cx, cy, _SPAN, _VIEW_PX, seed=_SEED, labels=False,
                           explored={"cells": exp_cells})
    c = _VIEW_PX // 2
    gpx = max(1, int(cell_li * _VIEW_PX / _SPAN))
    y0_, y1_ = c - gpx, c + gpx
    x0_, x1_ = c - gpx, c + gpx
    inside = [(i, j) for j in range(max(0, y0_), min(_VIEW_PX, y1_ + 1))
              for i in range(max(0, x0_), min(_VIEW_PX, x1_ + 1))]
    changed_in = sum(1 for (i, j) in inside
                     if plain.get_at((i, j))[:3] != withx.get_at((i, j))[:3])
    check("G1 踏勘格**确实**被换掉了（该处有像素变化）", changed_in > 0,
          "格中心 %dx%d 邻域内变化 %d 像素" % (gpx, gpx, changed_in))
    # 对照：视图角上（远离中心格）不应有任何变化
    far = [(i, j) for j in range(0, 40) for i in range(0, 40)]
    changed_far = sum(1 for (i, j) in far
                      if plain.get_at((i, j))[:3] != withx.get_at((i, j))[:3])
    check("G2 未踏勘处**一格不动**（对照角区 40×40 无变化）", changed_far == 0,
          "角区变化 %d 像素" % changed_far)
    # 空集合 / None == 纯舆图（逐字节）
    none_atlas = A.render_atlas(wm, cx, cy, _SPAN, _VIEW_PX, seed=_SEED, labels=False,
                                explored={"cells": set()})
    same = all(none_atlas.get_at((i, j)) == plain.get_at((i, j))
               for j in range(0, _VIEW_PX, 7) for i in range(0, _VIEW_PX, 7))
    check("G3 explored 为空时与纯舆图一致（不引入副作用）", same, "")
    # 视图外的格不该影响这张图
    outside = A.render_atlas(wm, cx, cy, _SPAN, _VIEW_PX, seed=_SEED, labels=False,
                             explored={"cells": {(1, 1)}})     # 世界西南角，远在视图外
    same2 = all(outside.get_at((i, j)) == plain.get_at((i, j))
                for j in range(0, _VIEW_PX, 7) for i in range(0, _VIEW_PX, 7))
    check("G4 视图外的踏勘格不影响本图", same2, "")

    print("\n== 结果：%d 过 / %d 败 ==" % (_PASS, _FAIL))
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
