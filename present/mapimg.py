"""地图底图渲染模块（**pygame 的唯一入口**）。

## 为什么单独一层

1. **依赖方向**：`engine/` 与 `content/` **永不 import pygame**。本模块只在最外层
   （`server/` 路由 / `tools/`）被调用，保证"纯规则引擎 + 确定性指纹"这条底线不受影响。
2. **线程安全**：FastAPI 的**同步**路由跑在线程池里，而 pygame/SDL 要求在**同一线程**初始化——
   否则会报 "video system not initialized"。故这里用 `threading.local()` 做**每线程一次**的 init，
   并**强制 dummy 驱动**（服务器上没有显示器，也不该开窗）。
3. **缓存**：底图是 `(seed, style, x, y, span, px)` 的**纯函数**，结果可任意复用；
   这里做 LRU 限制，避免内存无界增长。

⚠️ 渲染本身很便宜：舆图风是**逐格**扫描（400×400 格），与输出像素数无关——
实测 1200px 约 **0.1s**；实景风走 `detail=False` 的**快档**（读引擎全图数组），
560px 只要 **0.66s**、1200px 约 0.06s（有缓存后），**两者都能进运行时**。

⚠️ 上面这句曾写成"实景风 1200px 约 50s、只用于离线"——那说的是
`tools/maprender.py` 的 **`detail=True` 逐像素档**（连续采样，确实 ~50s，只做离线成品图），
而 `style="real"` 在这里传的是 `detail=False`。**别把两档混为一谈**（2026-09-11 澄清）。
"""
import threading
import time as _time

_LOCK = threading.Lock()
_TLS = threading.local()
_CACHE = {}
_CACHE_MAX = 24
_CACHE_ORDER = []


def _ensure_pygame():
    """每线程初始化一次 pygame（dummy 驱动，不开窗、不需要音频设备）。"""
    import os
    if getattr(_TLS, "ready", False):
        return
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    import pygame
    pygame.init()
    _TLS.ready = True


def prewarm(seed: int, cx: float, cy: float, span: float = 12000.0, px: int = 1200,
            style: str = "atlas", labels: bool = True, delay: float = 0.0) -> None:
    """**后台预热**：新局时就先把出生地底图渲好，玩家点开地图即为缓存命中。

    为什么要预热：首次请求要付"建世界（≈6s）+ 渲染（≈0.1s）"，若等玩家点开地图才算，
    那 6 秒的空窗全落在第一次打开地图上。预热把它挪到"建世界"那一步之后（同一份世界对象，
    本来就要建），玩家感知为 0。失败**不抛**——预热只是优化，不该影响开局。
    """
    def _work():
        try:
            if delay > 0:
                # ⚠️ 实测教训：预热若与响应线程同时跑，建世界 + 渲染会长时间持 GIL，
                # 把 `/api/new` 从 6~8s 拖到 17~24s（还把 E2E 的时序搞崩）。
                # 故先让出一个窗口，等响应写回客户端之后再开吃 CPU。
                _time.sleep(delay)
            atlas_png_bytes(seed, cx, cy, span, px, style=style, labels=labels)
        except Exception:
            pass
    t = threading.Thread(target=_work, name="map-prewarm", daemon=True)
    t.start()


def atlas_png_bytes(seed: int, cx: float, cy: float, span: float, px: int,
                    style: str = "atlas", labels: bool = True, wm=None) -> bytes:
    """渲染一张地图底图并编码成 PNG 字节（给 HTTP 路由直接用）。

    `style`: "atlas" = 舆图风（未探索区）；"real" = 实景风（走过的地方）。
    """
    px = max(64, min(int(px), 2400))
    span = max(200.0, float(span))
    key = (int(seed), style, round(float(cx), 1), round(float(cy), 1),
           round(span, 1), px, bool(labels))
    with _LOCK:
        hit = _CACHE.get(key)
        if hit is not None:
            return hit
    _ensure_pygame()
    import os
    import tempfile

    from engine import worldmap as WM
    from tools import atlas as A
    from tools import maprender as MR

    # `wm` 可由调用方传入（会话里那份）——避免"会话一份、底图又建一份"的重复建世界
    if wm is None:
        wm = WM.WorldMap(int(seed))
    if style == "real":
        surf = MR.render_tile(wm, float(cx), float(cy), span, px, shade=True, detail=False)
    else:
        surf = A.render_atlas(wm, float(cx), float(cy), span, px, seed=int(seed), labels=labels)
    # pygame 的 PNG 编码只进文件，故走临时文件（save_extended 需要 SDL_image，已确认可用）
    import pygame
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        pygame.image.save_extended(surf, path)
        with open(path, "rb") as fh:
            data = fh.read()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    with _LOCK:
        if len(_CACHE_ORDER) >= _CACHE_MAX:
            old = _CACHE_ORDER.pop(0)
            _CACHE.pop(old, None)
        _CACHE[key] = data
        _CACHE_ORDER.append(key)
    return data
