"""对照"城墙被路撞穿"的两种口径，在已存模板上分别数一遍。

旧口径（编辑器 v3 原版 / 引擎 _EXPORTS 里存的历史数字）：只看固定几条线
    (2, x)、(H-3, x)、(y, 2)、(y, W-3) 上有多少 '+'。
新口径（编辑器修好后）：任意一格 '=' 若"左右都是路"或"上下都是路" → 撞穿。

用法：$env:PYTHONPATH=<repo>; python tools/_town_layouts_check.py
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from content.town_layouts import LAYOUTS  # noqa: E402


def old_holes(lay):
    w, h, rows = lay.w, lay.h, lay.rows
    n = 0
    hits = []
    for x in range(2, w - 2):
        if rows[2][x] == "+":
            n += 1
            hits.append((x, 2))
        if rows[h - 3][x] == "+":
            n += 1
            hits.append((x, h - 3))
    for y in range(2, h - 2):
        if rows[y][2] == "+":
            n += 1
            hits.append((2, y))
        if rows[y][w - 3] == "+":
            n += 1
            hits.append((w - 3, y))
    return n, hits


def new_holes(lay):
    hits = []
    for y in range(lay.h):
        for x in range(lay.w):
            if lay.tile_at(x, y) != "=":
                continue
            lr = lay.tile_at(x - 1, y) == "+" and lay.tile_at(x + 1, y) == "+"
            tb = lay.tile_at(x, y - 1) == "+" and lay.tile_at(x, y + 1) == "+"
            if lr or tb:
                hits.append((x, y))
    return len(hits), hits


for lay in LAYOUTS:
    o_n, o_hits = old_holes(lay)
    n_n, n_hits = new_holes(lay)
    print(f"模板「{lay.name}」 {lay.w}×{lay.h}")
    print(f"  旧口径（固定 y=2 / x=W-3 等 4 条线）: {o_n} 处 {o_hits[:16]}")
    print(f"  新口径（按格子自身判，任意墙位）    : {n_n} 处 {n_hits[:16]}")
    print(f"  引擎存档里记的 errors: {list(lay.errors)}")
    print(f"  → 新口径{'更完整' if n_n > o_n else '一致或更少'}；"
          f"漏掉的 {max(0, n_n - o_n)} 处是旧口径看不见的（不在那 4 条线上）")
