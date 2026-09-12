"""给用户看效果：把「探索边界」走一段路之后的底图导出来。

为什么要它：本模型读不了图，效果验收只能靠**用户的眼睛**。
所以这里不做像素断言（那部分在 `tests/test_map_render.py` G 组），只负责
"跑一段真实的移动 → 把前端实际会拿到的那张底图落盘"。

产出：`logs/explore_before.png`（刚开局）/ `logs/explore_after.png`（走一段之后）

用法：.venv\\Scripts\\python.exe -X utf8 tools\\shot_explore.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

SPAN, PX = 8000.0, 900


def main():
    import pygame
    pygame.init()
    from engine.game import Game
    from present import mapimg

    g = Game(seed=20260910)
    out = os.path.join(ROOT, "logs")

    def shot(name):
        x, y = g.pos()
        blob = mapimg.atlas_png_bytes(int(g.seed), x, y, SPAN, PX, style="composed",
                                      wm=g.wmap, explored=g.state.world.explored)
        path = os.path.join(out, name)
        with open(path, "wb") as fh:
            fh.write(blob)
        print("%-22s %5.1f KB  位置=(%.0f, %.0f)  踏勘格=%d"
              % (name, len(blob) / 1024, x, y, len(g.state.world.explored)))
        return path

    shot("explore_before.png")

    # 走一条折线（每段都让引擎真实结算寻路 + 时间）
    path = [(10200., 10050.), (10500., 10200.), (10850., 10550.),
            (10600., 10900.), (10300., 10600.)]
    for (tx, ty) in path:
        r = g.step("travel", x=tx, y=ty, route=0)
        print("  → (%.0f, %.0f) %s  %s" % (tx, ty, "OK" if r.ok else r.reason,
                                           (r.data or {}).get("days", "")))
    shot("explore_after.png")
    print("\n用浏览器打开这两张图对比：走过的地方应该从「纸上淡墨」变成「真地形」。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
