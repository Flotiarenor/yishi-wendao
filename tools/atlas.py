"""舆图渲染器（**纸底 + 单色墨**，离线工具）。

和 `tools/maprender.py` 的分工：
  - `maprender` = **实景风**（地形色块 + 高程明暗 + 精确路网）——"你亲自走过的地方"该有的样子
  - `atlas`（本文件） = **舆图风**——"只买过情报、还没去过的地方"该有的样子

## 舆图的画法约束（用户拍板，别自作聪明加东西）

1. **不画高程明暗、不做地形分区**。舆图没有测高能力，明暗分区是现代地图语言。
2. **单一墨色**（`#3a3226`）。只有**水系用淡蓝**（用户实测确认：古舆图里海也是带点蓝的）。
3. **粗粒度地貌**：海 / 山 / 沙漠 / 水，各用一种"墨迹母题"（波浪、山峰、点阵、横线）。
   凡是母题，都按格**稀疏撒点**（由格坐标哈希决定），不是满涂。
4. **路网必须"拟合现有路径"，不许自己生成**：取 `wm.roads()` 的真实折线，
   做**截断傅里叶级数**平滑 + 轻微手抖，模拟人拿笔的样子。
5. **城镇是墨点，主城加注地名**（楷体；pygame 默认字体没有 CJK，必须显式指定系统字体）。

⚠️ 依赖方向：本文件只读引擎，`engine/` 与 `content/` **永不 import pygame**。
"""
import math
import os

_PAPER = (240, 230, 205)          # 纸底
_INK = (32, 26, 18)               # 墨（主色，2026-09-11 调浓：用户反馈偏淡）
_INK_LABEL = (18, 14, 8)          # 地名专用：比主墨再浓一档，保证压在线条上也清楚
_INK_LIGHT = (96, 84, 64)         # 淡墨（次要元素：小径、小城、地貌细笔）
# 水只有**一种**浅蓝：舆图测不出深浅，深蓝=假装知道海底高差（用户指出）
_SEA = (150, 186, 202)

# 地貌归类（用 `content/regions.py` 的地形 id）
def _groups(R):
    """地形 id → 舆图类别。

    只分"能画出来"的几类——这正是舆图的粒度：**海 / 水 / 山 / 沙 / 林 / 沼 / 其他**。
    官方道与小径不算地貌（它们是路，单独画）。
    """
    return {
        "sea":   {R.T_DEEPSEA, R.T_WATER, R.T_FORD},
        "mount": {R.T_MOUNTAIN, R.T_CLIFF, R.T_HILL, R.T_CANYON, R.T_SNOW, R.T_LAVA},
        "sand":  {R.T_DESERT},
        "forest": {R.T_FOREST},
        "swamp": {R.T_SWAMP},
        "ward":  {R.T_WARD},
        "road":  {R.T_ROAD, R.T_TRAIL},
        "grass": {R.T_GRASS},                     # ⚠️ 不能并进 plain：并进去就等于"没有母题分支"，
                                                  #    实测草原区笔画像素只有 0.54%（= 完全留白）。用户指出过。
        "plain": {R.T_PLAIN, R.T_VOID},
    }


def _hash01(i: int, j: int, salt: int = 0) -> float:
    """格坐标 → [0,1) 的确定性伪随机（不依赖 random 模块，保证同种子同图）。"""
    h = (i * 73856093) ^ (j * 19349663) ^ (salt * 83492791)
    h &= 0xFFFFFFFF
    h ^= h >> 13
    h = (h * 1274126177) & 0xFFFFFFFF
    h ^= h >> 16
    return (h & 0xFFFFFF) / float(0x1000000)


# ---------------- 手绘感平滑：Catmull-Rom（**不是**傅里叶）----------------
#
# 教训（2026-09-11，用户实测发现"满屏乱画直线"）：原先用截断傅里叶级数拟合路网，
# 结果**205 段路里前 20 段全部被放大上百倍**（实测：5 点 / 241 里的折线拟合后变 29968 里 = 124×，
# 最差 386×）。原因是路网折线多数只有 **5~9 个点**，级数在样本极少时剧烈外插——
# 短折线必然爆炸。**傅里叶只适合长序列**（几十上百点），不适合本项目这种碎折线。
#
# 改用 Catmull-Rom（向心参数化）：
#   - 它是**局部插值**：每个输出点只由相邻 4 个控制点决定，**不可能外插到远处**；
#   - 天然穿过所有原始点（路该过哪就过哪），只把折角磨圆；
#   - 无随机、无全局拟合，确定性且长度可控（$KEEP_LEN$）。
_CR_MIN_POINTS = 4          # 少于这个点数就原样返回（短折线没什么可平滑的）
_CR_SEG_SAMPLES = 6         # 每段插值出的点数（1 = 不平滑）


def smooth_polyline(points, seg_samples=_CR_SEG_SAMPLES, wobble=0.0):
    """**均匀参数化 Catmull-Rom**：把折角磨圆，同时严格贴住原线（不过冲、不插值到远处）。

    为什么不用向心参数化：我第一版照搬了向心公式，但把"局部 t 区间"与"全局结点 τ"搞混，
    等于沿 τ 外插，实测把 241 里的折线拉成 1628 里（6.7 倍）。而**均匀参数化**在 t∈[0,1]
    上是标准 Hermite 形式，几何意义清楚、过冲有界，不会出现这种膨胀。

    `seg_samples`：每段插值出的点数（1 = 原样返回，4~8 已经够圆）。
    `wobble`     ：轻微手抖（相对该段长度），0 = 完全按几何走（推荐先这样，别抖）。
    """
    pts = [(float(x), float(y)) for x, y in points]
    if len(pts) < _CR_MIN_POINTS or seg_samples <= 1:
        return pts

    def _cr(p0, p1, p2, p3, t):
        # 均匀 Catmull-Rom 的 Hermite 形式：m1/m2 由相邻点差分给出
        m1 = ((p2[0] - p0[0]) * 0.5, (p2[1] - p0[1]) * 0.5)
        m2 = ((p3[0] - p1[0]) * 0.5, (p3[1] - p1[1]) * 0.5)
        t2 = t * t
        t3 = t2 * t
        h00 = 2 * t3 - 3 * t2 + 1
        h10 = t3 - 2 * t2 + t
        h01 = -2 * t3 + 3 * t2
        h11 = t3 - t2
        x = h00 * p1[0] + h10 * m1[0] + h01 * p2[0] + h11 * m2[0]
        y = h00 * p1[1] + h10 * m1[1] + h01 * p2[1] + h11 * m2[1]
        return (x, y)

    ext = [pts[0]] + pts + [pts[-1]]          # 两端补点，保证首尾段也有切线
    out = []
    for i in range(1, len(ext) - 2):
        p0, p1, p2, p3 = ext[i - 1], ext[i], ext[i + 1], ext[i + 2]
        seg_len = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        for s in range(seg_samples):
            t = s / float(seg_samples)
            x, y = _cr(p0, p1, p2, p3, t)
            if wobble:
                u = t * 2.0 * math.pi
                x += seg_len * wobble * math.sin(u)
                y += seg_len * wobble * math.sin(u * 1.3 + 1.0)
            out.append((x, y))
    out.append(pts[-1])
    return out


def brush_stroke(surf, pts, color, width=2, taper=True):
    """毛笔感描线：分段画、线宽两端细中间粗、末尾补一笔断墨。

    比 `pygame.draw.lines` 均匀描边更像手写——但**不做随机**（确定性优先，可像素回归）。
    """
    import pygame
    n = len(pts)
    if n < 2:
        return
    for k in range(n - 1):
        t = k / float(n - 1)
        if taper:
            w = width * (0.55 + 0.9 * math.sin(math.pi * min(1.0, t * 1.05)))
        else:
            w = width
        w = max(1, int(round(w)))
        pygame.draw.line(surf, color, pts[k], pts[k + 1], w)


# ---------------- 地貌母题 ----------------
def _wave(surf, x, y, s, color=_INK_LIGHT, rows=3):
    """水的母题：几道短波浪线（淡墨，压在浅蓝底上）。"""
    import pygame
    for r in range(rows):
        yy = y + r * s * 0.30
        # 用折线近似正弦小波：比"之"字形更接近舆图上的水纹
        pts = []
        n = 7
        for i in range(n):
            t = i / float(n - 1)
            pts.append((x + t * s * 1.5, yy + (s * 0.085) * (1 if (i % 2) else -1)))
        pygame.draw.lines(surf, color, False, pts, 1)


def _peak(surf, x, y, s, color=_INK):
    """山的母题：一个三角山尖 + 侧脊阴影线（舆图最经典的画法）。"""
    import pygame
    top = (x, y - s * 0.55)
    left = (x - s * 0.5, y + s * 0.3)
    right = (x + s * 0.5, y + s * 0.3)
    pygame.draw.lines(surf, color, False, [left, top, right], 2)
    pygame.draw.line(surf, color, top, (x + s * 0.16, y + s * 0.3), 1)
    pygame.draw.line(surf, color, (x - s * 0.16, y + s * 0.14), (x + s * 0.16, y + s * 0.3), 1)


def _dune(surf, x, y, s, color=_INK_LIGHT):
    """沙漠的母题：**点阵沙粒**（用户选定）。

    为什么不用"沙丘弧"：弧线是有方向的符号，和水纹（本身就是波浪）容易混淆；
    舆图上的"沙"应该是**质感**而非结构——用散点更贴切，远看留白、近看有沙。
    点位置由坐标哈希决定（确定性，同种子同图）。
    """
    import pygame
    for k in range(5):
        hx = _hash01(int(x), int(y), 20 + k)
        hy = _hash01(int(x), int(y), 40 + k)
        pygame.draw.circle(surf, color, (int(x + (hx - 0.5) * s * 1.1),
                                         int(y + (hy - 0.5) * s * 0.9)), 1)


def _tuft(surf, x, y, s, color=_INK_LIGHT):
    """草原的母题：**三根草簇**（用户选定）。

    草原密度是沙漠的 6 倍，故笔触要更轻（用淡墨）且更小，否则整张图会被草纹铺满。
    """
    import pygame
    for dx in (-s * 0.16, 0.0, s * 0.16):
        pygame.draw.line(surf, color, (x + dx, y + s * 0.14), (x + dx * 1.5, y - s * 0.14), 1)


def _tree(surf, x, y, s, color=_INK):
    """林木的母题：小三角（松）+ 竖干。"""
    import pygame
    pygame.draw.line(surf, color, (x, y - s * 0.15), (x, y + s * 0.25), 1)
    pygame.draw.lines(surf, color, False,
                      [(x - s * 0.22, y + s * 0.1), (x, y - s * 0.45), (x + s * 0.22, y + s * 0.1)], 1)


def _marsh(surf, x, y, s, color=_INK_LIGHT):
    """沼泽的母题：三道短横线（芦苇/水草）。"""
    import pygame
    for k in (-1, 0, 1):
        pygame.draw.line(surf, color, (x - s * 0.3, y + k * s * 0.18),
                         (x - s * 0.05 + (s * 0.1 if k else 0), y + k * s * 0.18), 1)


def _ward(surf, x, y, s, color=_INK):
    """禁制的母题：一个圈 + 十字（"此地不可入"的记号）。"""
    import pygame
    pygame.draw.circle(surf, color, (int(x), int(y)), int(s * 0.3), 1)
    pygame.draw.line(surf, color, (x - s * 0.42, y), (x + s * 0.42, y), 1)
    pygame.draw.line(surf, color, (x, y - s * 0.42), (x, y + s * 0.42), 1)


def render_atlas(wm, cx, cy, span, px, seed=20260910, labels=True,
                 max_labels=40, show_rivers=True, show_roads=True, explored=None):
    """渲染一张舆图：纸底 + 单色墨线 + 粗粒度地貌 + 拟合路网 + 城镇/地名。

    逐格扫描（读 `_base` 数组，400×400 = 16 万格，约 30 ms），
    故与输出像素数无关——**天生可实时**。

    ## `explored`：探索边界（定案 §5「两层迷雾」的可视化）

    传 `{"cells": {(cx, cy), …}}` 时，**视野内这些格会被"实景风"覆盖**——
    走过的地方撕开舆图的纸面、露出真地形，没走过的仍是纸上淡墨。
    这正是定案 §5 的两层：

    | 层 | 表现 | 依据 |
    |---|---|---|
    | **舆图**（我听说过/买来的） | 纸底 + 粗粒度墨色母题 | 全图铺底 |
    | **实景**（我亲自到过的） | 真地形色块 + 高程明暗 | `WorldState.explored` |

    ⚠️ **依据必须是 `explored`（真的站过），不是 `discovered`**：
    后者会被"买情报"灌入（听说），拿它画实景会让买一份情报就点亮一片。

    ⚠️ **必须画在纸纹之后、水系/母题之前**：舆图的淡蓝水色与墨是**半透明**的，
    实景若压在它们**下面**会被透出来，"撕开纸面"的效果就不成立。
    又因为实景块是**不透明**的，它天然把该处的纸底与母题遮住——不需要额外的遮罩。
    """
    import pygame
    from content import regions as R
    from engine import worldmap as WM

    n = WM._N
    cell = float(WM._CELL_LI)
    wm._ensure_terrain()
    base = wm._base
    G = _groups(R)

    x0, y0 = cx - span / 2.0, cy - span / 2.0
    k = px / span                      # 里 → 像素

    def w2p(x, y):
        """世界坐标 → 像素。

        ⚠️ **y 必须翻转**：定案 §3.1 明确"坐标原点在**西南角**"，即 **y 越大越靠北**；
        而屏幕像素 **y 越大越靠下**。所以屏幕 y = 视野**北边**的 y 减去世界 y。

        这条曾经漏掉，代价很大：底图（本函数）把北画在了下面，而前端 SVG 叠加层
        （`MapScreen.vue` 的 `sy = -((y - self.y)/R)*half`）画的是正确的朝向——
        于是**底图上的城镇点 / 路网 / 河流与可点击的城镇点整体上下镜像**，
        表现为"点下去的地方和图上看到的不一样、城镇点跑到湖里"
        （离视图中心越远偏得越多；中心恰好重合，所以早期只在中心附近核对时看不出来）。
        2026-09-11 修正。
        """
        return ((x - x0) * k, (y0 + span - y) * k)

    surf = pygame.Surface((px, px))
    # 1) 纸底 + 极轻的纸纹（确定性，避免"塑料感"）
    surf.fill(_PAPER)
    for j in range(0, px, 3):
        for i in range(0, px, 3):
            v = _hash01(i // 3, j // 3, 7)
            if v < 0.34:
                d = int(-6 + 12 * v)
                surf.set_at((i, j), (max(0, _PAPER[0] + d), max(0, _PAPER[1] + d), max(0, _PAPER[2] + d)))

    # 1.5) **探索边界**：踏勘过的格用实景风盖掉纸面（见 docstring）。
    # 这里只准备"实景底图"与"格级掩膜"，真正的合成在最后一步（要盖在母题之上）。
    real_surf = None
    exp_cells = None
    if explored:
        exp_cells = {(int(c[0]), int(c[1]))
                     for c in (explored.get("cells") if isinstance(explored, dict)
                               else explored)}
        if exp_cells:
            from tools import maprender as MR
            real_surf = (explored.get("real_surface") if isinstance(explored, dict)
                         else None)
            if real_surf is None:
                real_surf = MR.terrain_surface_fast(wm, 0, shade=True, style="real")

    # 2) 水系：先铺淡蓝（格级块），再描海岸线 + 撒波浪母题
    i_lo = max(0, int(math.floor(x0 / cell)))
    i_hi = min(n - 1, int(math.ceil((x0 + span) / cell)))
    j_lo = max(0, int(math.floor(y0 / cell)))
    j_hi = min(n - 1, int(math.ceil((y0 + span) / cell)))
    grid = {}
    for j in range(j_lo, j_hi + 1):
        row = j * n
        for i in range(i_lo, i_hi + 1):
            tid = base[row + i]
            grid[(i, j)] = tid
            if tid in G["sea"]:
                gx, gy = w2p((i + 0.5) * cell, (j + 0.5) * cell)
                sz = cell * k + 1
                pygame.draw.rect(surf, _SEA,
                                 pygame.Rect(int(gx - sz / 2), int(gy - sz / 2), int(sz) + 1, int(sz) + 1))

    # 海岸墨线（水格与非水格的边界）+ 波浪母题
    for (i, j), tid in grid.items():
        if tid not in G["sea"]:
            continue
        gx, gy = w2p((i + 0.5) * cell, (j + 0.5) * cell)
        sz = cell * k
        for di, dj, a, b in ((1, 0, 1, 0), (-1, 0, 0, 0), (0, 1, 0, 1), (0, -1, 0, 0)):
            nb = grid.get((i + di, j + dj))
            if nb is None or nb in G["sea"]:
                continue
            if di:
                xx = gx + a * sz / 2
                pygame.draw.line(surf, _INK, (xx, gy - sz / 2), (xx, gy + sz / 2), 1)
            else:
                yy = gy + b * sz / 2
                pygame.draw.line(surf, _INK, (gx - sz / 2, yy), (gx + sz / 2, yy), 1)
        if _hash01(i, j, 11) < 0.05:
            _wave(surf, gx - sz * 0.4, gy, max(6.0, sz), rows=2)

    # 3) 地貌母题：按格稀疏撒点（不是满涂）；山最密，其余更疏
    # 母题密度：山最密；沙漠/沼泽/林地中等；**草原要疏**（它占 10.7% 的格，密了会铺满整张图）
    motif_rate = {"mount": 0.16, "sand": 0.10, "forest": 0.10, "swamp": 0.10, "grass": 0.06}
    for (i, j), tid in grid.items():
        if tid in G["sea"]:
            continue
        gx, gy = w2p((i + 0.5) * cell, (j + 0.5) * cell)
        s = max(5.0, cell * k)
        if tid in G["mount"]:
            if _hash01(i, j, 3) < motif_rate["mount"]:
                _peak(surf, gx + (s * 0.2 * (_hash01(i, j, 4) - 0.5)), gy, s)
        elif tid in G["sand"]:
            if _hash01(i, j, 5) < motif_rate["sand"]:
                _dune(surf, gx, gy, s * 1.3)
        elif tid in G["grass"]:
            if _hash01(i, j, 12) < motif_rate["grass"]:
                _tuft(surf, gx, gy, s * 1.2)
        elif tid in G["forest"]:
            if _hash01(i, j, 6) < motif_rate["forest"]:
                _tree(surf, gx, gy, s * 1.1)
        elif tid in G["swamp"]:
            if _hash01(i, j, 8) < motif_rate["swamp"]:
                _marsh(surf, gx, gy, s * 1.1)
        elif tid in G["ward"]:
            # 禁制：圈 + 十字（用户选定），但**只在近景画**——整世界尺度下 50% 密度会糊成一片符号
            if k >= 0.05 and _hash01(i, j, 9) < 0.5:
                _ward(surf, gx, gy, s * 1.4)

    # 4) 河：细淡墨线（真实折线，轻傅里叶平滑）
    if show_rivers:
        for rv in wm.rivers():
            pts = [w2p(px_, py_) for px_, py_ in smooth_polyline(rv.points, seg_samples=4)]
            inside = [(x, y) for x, y in pts if -50 <= x <= px + 50 and -50 <= y <= px + 50]
            if len(inside) >= 2:
                brush_stroke(surf, inside, _INK_LIGHT, width=2, taper=True)

    # 5) 路网：**拟合真实路径**（不是你要求的"生成"）——傅里叶平滑 + 毛笔感
    if show_roads:
        for rd in wm.roads():
            pts = [w2p(px_, py_) for px_, py_ in smooth_polyline(rd.points, seg_samples=4)]
            inside = [(x, y) for x, y in pts if -60 <= x <= px + 60 and -60 <= y <= px + 60]
            if len(inside) < 2:
                continue
            if rd.kind == "road":
                brush_stroke(surf, inside, _INK, width=3, taper=True)
            else:
                brush_stroke(surf, inside, _INK_LIGHT, width=2, taper=True)

    # 6) 城镇：墨点（主城更大 + 双圈），主城注地名
    towns = list(wm.towns())
    towns.sort(key=lambda t: (not t.is_main, t.name))
    labeled = 0
    font = None
    if labels:
        font = _cjk_font(max(13, int(px / 78)))
    for t in towns:
        gx, gy = w2p(t.x, t.y)
        if not (-20 <= gx <= px + 20 and -20 <= gy <= px + 20):
            continue
        if t.is_main:
            pygame.draw.circle(surf, _INK, (int(gx), int(gy)), 5)
            pygame.draw.circle(surf, _PAPER, (int(gx), int(gy)), 3)
            pygame.draw.circle(surf, _INK, (int(gx), int(gy)), 2)
            if font is not None and labeled < max_labels:
                txt = font.render(t.name, True, _INK_LABEL)
                rect = txt.get_rect(left=int(gx + 8), top=int(gy - txt.get_height() // 2))
                # 透明背景：不用纸色底块（那会像贴了块补丁，压住地貌母题很不协调），
                # 改为沿八方向描一圈极淡的纸色描边，让字从墨线里"浮"出来。
                halo = font.render(t.name, True, _PAPER)
                surf.blit(halo, rect.move(-1, 0))
                surf.blit(halo, rect.move(1, 0))
                surf.blit(halo, rect.move(0, -1))
                surf.blit(halo, rect.move(0, 1))
                surf.blit(txt, rect)
                labeled += 1
        else:
            pygame.draw.circle(surf, _INK, (int(gx), int(gy)), 3)

    # 7) 探索边界合成：把踏勘过的格换成实景
    if real_surf is not None and exp_cells:
        _apply_explored(surf, real_surf, wm, exp_cells, cx, cy, span, px, n, cell)
    return surf


def _apply_explored(surf, real_surf, wm, exp_cells, cx, cy, span, px, n, cell):
    """把 `exp_cells`（踏勘过的格）处的舆图画换成实景（**格级**，与迷雾粒度一致）。

    做法：裁出视图对应的实景块 → 按视图内的格画一张**二值掩膜** → 用掩膜把实景块
    贴上去。掩膜写成**格**而不是像素：
      - 定案 §5 的迷雾遮的是"内容点/格"这一层，不是面；
      - 格级掩膜的计算量与踏勘格数成正比（几百格），与像素数无关；
      - 边缘会沿 50 里格呈阶梯状——**与迷雾粒度一致**，不是缺陷。
    """
    import pygame
    rn = real_surf.get_width()
    rsc = rn / float(n)                          # 引擎格 → 实景底图像素
    half = span / 2.0
    # 视图对应的源矩形。`real_surf` 是**北在上**，故源矩形上边 = 视野北边 `cy + half`
    src = pygame.Rect(int(round((cx - half) / cell * rsc)),
                      int(round((n * cell - (cy + half)) / cell * rsc)),
                      max(1, int(round(span / cell * rsc))),
                      max(1, int(round(span / cell * rsc))))
    sub = pygame.Surface((max(1, src.w), max(1, src.h)))
    sub.blit(real_surf, (0, 0), src)

    # ⚠️ **alpha 处理的三个坑**（这版之前连着错了三次，都记下来）：
    #   ① `real_surf` 是 **24 位无 alpha**；`smoothscale` 出来的 tile 也没有有效 alpha，
    #      直接拿掩膜做 `BLEND_RGBA_MULT` 会把**未探索处涂成黑色**（实测整图变黑）；
    #   ② 用 `tile.set_alpha(255)` 补 alpha 也不行——`set_alpha` 是**整面** alpha，
    #      会覆盖掉逐像素 alpha，于是掩膜失效、**整张图都变成实景**（实测 100% 像素变了）；
    #   ③ 正解：**把 tile 建成 32 位带 alpha 的表面**（`convert_alpha()` 在无显示器的
    #      服务器上会报 "No convert format has been set"，**不能用**），
    #      用 `fill(..., BLEND_RGBA_MAX)` 把逐像素 alpha 抬到不透明，再让掩膜乘下去。
    tile = pygame.Surface((px, px), pygame.SRCALPHA)     # 32 位，带逐像素 alpha
    tile.fill((0, 0, 0, 0))
    _sc = pygame.transform.smoothscale(sub, (px, px))
    tile.blit(_sc, (0, 0))
    tile.fill((255, 255, 255, 255), None, pygame.BLEND_RGBA_MAX)   # 只抬 alpha，不改颜色

    # 格级掩膜：视图内的格 → px/span*cellsize 像素块
    mask = pygame.Surface((px, px), pygame.SRCALPHA)
    mask.fill((255, 255, 255, 0))                # 全透明 = "未探索，别盖"
    gpx = cell * px / span                       # 一格多少像素
    for (ci, cj) in exp_cells:
        cwx, cwy = (ci + 0.5) * cell, (cj + 0.5) * cell
        if abs(cwx - cx) > half + cell or abs(cwy - cy) > half + cell:
            continue
        sx = (cwx - (cx - half)) / span * px
        sy = ((cy + half) - cwy) / span * px
        mask.fill((255, 255, 255, 255),
                  pygame.Rect(int(sx - gpx / 2), int(sy - gpx / 2),
                              max(1, int(gpx)), max(1, int(gpx))))
    tile.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    surf.blit(tile, (0, 0))


_FONT_CACHE = {}


def _cjk_font(size):
    """取一个能渲染中文的字体（pygame 默认字体无 CJK）。

    优先楷体（最像舆图上的手写地名），其次黑体/宋体。
    """
    import pygame
    if size in _FONT_CACHE:
        return _FONT_CACHE[size]
    for name in ("KaiTi", "SimHei", "Microsoft YaHei", "SimSun"):
        path = pygame.font.match_font(name)
        if path:
            try:
                f = pygame.font.Font(path, size)
                if f.size("镇")[0] > 0 and f.size("镇")[1] > 0:
                    _FONT_CACHE[size] = f
                    return f
            except Exception:
                continue
    _FONT_CACHE[size] = None
    return None
