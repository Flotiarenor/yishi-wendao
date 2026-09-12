"""FastAPI 应用工厂 + 全部 API 路由（P3.6 最小 Web 闭环）。

- create_app(config) → FastAPI：config 支持 {"save_dir": ...}（测试注入临时目录）。
- 端点全用同步 def（FastAPI 线程池执行，不阻塞事件循环）；内部由 GameSession
  的 per-run threading.Lock 串行化引擎调用（引擎非线程安全）。
- 静态资源挂载在 **API 路由之后**（`app.mount("/", StaticFiles(html=True))`），
  `/api` 前缀的 404 不被 SPA fallback 吞成 index.html。
- 不引入 CORS（同源）、不做鉴权（本地单机）。
- 服务层错误（unknown_run / bad_request / no_checkpoint）以 HTTP 状态码 +
  JSON `{"ok": false, "reason": ...}` 表达；引擎拒绝分支则 HTTP 200 +
  `ok=false` + 引擎 reason 码原样透传。
"""
import os
from typing import Optional

from fastapi import FastAPI
from fastapi import Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from server.session import RunManager

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
# P3.7 正式前端：Vue3 构建产物（frontend/dist）。旧 P3.6 极简面板（server/static）已删除——
# 它的数据契约与 P3.7 前端不一致（战斗面板字段全错），保留只会成为误导性的死代码。
_DIST_DIR = os.path.join(_ROOT, "frontend", "dist")

_MISSING_DIST_HTML = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="UTF-8"><title>前端未构建</title></head>
<body style="background:#0f1420;color:#d7e0ef;font-family:sans-serif;padding:40px">
<h1 style="color:#d8b26a">前端尚未构建</h1>
<p>请先构建 P3.7 前端（Vue3 构建产物 frontend/dist）：</p>
<pre style="background:#1a2233;padding:12px;border-radius:6px">cd frontend
npm install
npm run build</pre>
<p>构建后刷新本页即可。<code>/api/*</code> 接口不受影响。</p>
</body></html>"""


def _has_dist() -> bool:
    """frontend/dist 是否已构建（存在 index.html 即视为可用）。"""
    return os.path.isfile(os.path.join(_DIST_DIR, "index.html"))


def _err(status_code: int, reason: str) -> JSONResponse:
    """服务层错误响应：HTTP 状态码 + {ok:false, reason}。"""
    return JSONResponse(status_code=status_code,
                        content={"ok": False, "reason": reason})


# ---------- 请求体（Pydantic 契约；字段全部可选，缺失由 handler 判 bad_request） ----------
class NewIn(BaseModel):
    seed: Optional[int] = None
    name: Optional[str] = ""


class RunIdIn(BaseModel):
    run_id: Optional[str] = None


class StepIn(BaseModel):
    run_id: Optional[str] = None
    action: Optional[str] = None
    kwargs: Optional[dict] = Field(default_factory=dict)


def _result_payload(r, state: dict) -> dict:
    """引擎 Result + 状态快照 → /api/step 统一响应体（ok/reason 原样透传）。"""
    ok = r.ok if r.ok is not None else True
    return {
        "ok": ok,
        "reason": r.reason or "ok",
        "data": r.data or {},
        "text": r.text or "",
        "lines": r.lines or [],
        "game_over": r.game_over,
        "died": r.died,
        "battle_started": r.battle_started,
        "battle_over": r.battle_over or "",
        "state": state,
    }


def _prewarm_map(sess, span: float = 12000.0, px: int = 1200, delay: float = 0.0):
    """（已停用；保留函数以免旧调用点炸）预热底图——**实测不划算，不要用**。

    数据：舆图渲染 0.37s / PNG 编码 0.07s / 建世界 ≈6s。
    预热要先建世界且长时间持 GIL，会把 `/api/new` 从 6~8s 拖到 11~24s（用户可见 + E2E 时序崩）。
    首个 `/api/map/img` 请求自然会建世界并进 LRU 缓存，因此不需要预热。
    """
    return
    """新局/读档后**后台**渲染一次出生地底图，让首开地图不付建世界那 ≈6 秒。

    只预渲一档（舆图风 12000 里）——覆盖默认视图；其余按需渲染并走 LRU 缓存。
    预热失败不抛（它只是优化，不该影响开局）。
    """
    try:
        from present import mapimg
        x, y = sess.g.pos()
        mapimg.prewarm(int(sess.g.seed), float(x), float(y), span=span, px=px,
                       style="atlas", delay=delay)
    except Exception:
        pass


def create_app(config: dict = None) -> FastAPI:
    """应用工厂：全部路由 + 静态伺服。config = {"save_dir": ...}。"""
    config = config or {}
    manager = RunManager(save_dir=config.get("save_dir"))
    app = FastAPI(title="仙途 · 文字修仙", version="0.3.6")

    # ---------- 缓存策略 ----------
    # index.html 引用带哈希的 JS/CSS；若浏览器缓存了旧 index.html，重建后普通刷新
    # 仍会加载旧 JS（用户曾误以为"改了没生效"）。故：HTML 不缓存（每次回源校验），
    # 带哈希的 /assets/* 长缓存。
    @app.middleware("http")
    async def _cache_headers(request, call_next):
        resp = await call_next(request)
        path = request.url.path
        if path.startswith("/api") or path == "/health":
            return resp
        if "text/html" in resp.headers.get("content-type", ""):
            resp.headers["Cache-Control"] = "no-cache"
        elif path.startswith("/assets/"):
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return resp

    # ---------- 健康检查 ----------
    @app.get("/health")
    def health():
        return {"status": "ok"}

    # ---------- 会话路由 ----------
    @app.get("/api/runs")
    def api_runs():
        return {"ok": True, "runs": manager.list_runs()}

    # ---------- 地图底图（P4：舆图风底图，pygame 渲染）----------
    @app.get("/api/map/img")
    def api_map_img(run_id: str = "", x: float = None, y: float = None,
                    span: float = 12000.0, px: int = 1200, style: str = "composed",
                    labels: int = 1):
        """世界地图底图 PNG。

        - 世界种子来自**存档**（`run_id` → seed），不信任前端传入的 seed（避免看别人的世界）；
        - `x`/`y` 缺省 = 玩家当前位置；`span` = 视图边长（里）；`px` = 输出边长（像素）；
        - `style`: composed（舆图底 + 踏勘过的格换实景，**默认**）| atlas（纯舆图）| real（纯实景）。
          `composed` 的探索依据取自**存档里的 `WorldState.explored`**——
          同样不信任前端参数（否则前端可以"假装走过全图"把迷雾全点亮）。
        - 同一参数组合有内存 LRU 缓存；舆图风是逐格扫描（与像素数无关，约 0.1s）。
        """
        sess = manager.load(run_id) if run_id else None
        if sess is None:
            return _err(404, "unknown_run")
        seed = int(sess.g.seed)
        if x is None or y is None:
            x, y = sess.g.pos()
        try:
            from present import mapimg
            data = mapimg.atlas_png_bytes(seed, float(x), float(y), float(span),
                                          int(px), style=style, labels=bool(labels),
                                          wm=getattr(sess.g, "wmap", None),
                                          explored=sess.g.state.world.explored)
        except Exception as e:      # 渲染失败不该把接口打成 500 裸栈
            return _err(500, "render_failed: %s" % e)
        return Response(content=data, media_type="image/png",
                        headers={"Cache-Control": "no-cache"})

    @app.post("/api/new")
    async def api_new(body: NewIn):
        # 注意：本路由是 **async**，故 `manager.new` / `state()` 跑在事件循环线程上——
        # 建世界本来就慢（≈6s），这里没有再叠加因素；
        # 关键是**预热必须晚于响应**（见 _prewarm_map 的 delay 说明）。
        sess = manager.new(seed=body.seed, name=body.name or "")
        # ⚠️ 曾经在这里挂过"后台预热底图"，实测**净亏损**并已撤掉：
        # 舆图渲染本身只要 0.37s，但预热线程要先建世界（≈6s）且大部分时间持 GIL，
        # 把 `/api/new` 从 6~8s 拖到 11~24s（还搞崩了 E2E 时序）。
        # 首个 `/api/map/img` 请求本来就会建好世界并带 LRU 缓存，无需预热。
        return {"ok": True, "run_id": sess.run_id, "state": sess.state()}

    @app.post("/api/load")
    async def api_load(body: RunIdIn):
        if not body.run_id:
            return _err(400, "bad_request")
        sess = manager.load(body.run_id)
        if sess is None:
            return _err(404, "unknown_run")
        return {"ok": True, "run_id": sess.run_id, "state": sess.state()}

    @app.post("/api/step")
    def api_step(body: StepIn):
        if not body.run_id or not body.action:
            return _err(400, "bad_request")
        sess = manager.load(body.run_id)      # 内存命中则复用；否则从 saves 读档
        if sess is None:
            return _err(404, "unknown_run")
        r, state = sess.step_with_state(body.action, **dict(body.kwargs or {}))
        return _result_payload(r, state)

    @app.post("/api/undo")
    def api_undo(body: RunIdIn):
        if not body.run_id:
            return _err(400, "bad_request")
        sess = manager.load(body.run_id)
        if sess is None:
            return _err(404, "unknown_run")
        ok, _res = sess.undo()
        if not ok:
            return {"ok": False, "reason": "no_checkpoint", "state": sess.state()}
        return {"ok": True, "reason": "ok", "state": sess.state()}

    @app.get("/api/state")
    def api_state(run_id: str = ""):
        if not run_id:
            return _err(400, "bad_request")
        sess = manager.load(run_id)
        if sess is None:
            return _err(404, "unknown_run")
        return {"ok": True, "state": sess.state()}

    # ---------- 静态前端挂载在 API 之后 ----------
    # 顺序要求：/api 前缀的 404 不被 SPA fallback 吞成 index.html。
    # dist 已构建 → StaticFiles(html=True) 伺服（未命中路径回退 index.html，
    # 兼容前端深链刷新）；未构建 → 返回一段构建提示页（API 仍完全可用）。
    if _has_dist():
        app.mount("/", StaticFiles(directory=_DIST_DIR, html=True), name="static")
    else:
        @app.get("/", include_in_schema=False)
        def _frontend_missing():
            return HTMLResponse(_MISSING_DIST_HTML)
    return app
