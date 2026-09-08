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
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from server.session import RunManager

_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


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


def create_app(config: dict = None) -> FastAPI:
    """应用工厂：全部路由 + 静态伺服。config = {"save_dir": ...}。"""
    config = config or {}
    manager = RunManager(save_dir=config.get("save_dir"))
    app = FastAPI(title="仙途 · 文字修仙", version="0.3.6")

    # ---------- 健康检查 ----------
    @app.get("/health")
    def health():
        return {"status": "ok"}

    # ---------- 会话路由 ----------
    @app.get("/api/runs")
    def api_runs():
        return {"ok": True, "runs": manager.list_runs()}

    @app.post("/api/new")
    def api_new(body: NewIn):
        sess = manager.new(seed=body.seed, name=body.name or "")
        return {"ok": True, "run_id": sess.run_id, "state": sess.state()}

    @app.post("/api/load")
    def api_load(body: RunIdIn):
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

    # ---------- 静态（极简面板）挂载在 API 之后 ----------
    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
    return app
