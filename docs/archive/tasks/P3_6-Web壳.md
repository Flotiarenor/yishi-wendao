# P3.6 任务书：最小 Web 闭环（FastAPI 服务端 + 会话层 + 极简面板）

> 实现者 = subagent（看不到历史对话）。本文档自包含；配合下列必读文件。
> 若与现有代码冲突：以"不破坏 P0~P3.5 已验收行为"为准，并在报告中记录取舍。
> 规格来源 = `docs/Web架构方案.md`（§4 分层 / §6 会话层 / §7 API 契约 / §9 判据）；**本任务书是它的落地细化**。

## 必读（按顺序）

1. `docs/Web架构方案.md`（全篇，尤其 §4/§6/§7/§9）
2. `README.md`（运行方式、架构要点；含 P3.5 结构化契约说明）
3. `docs/会话交接.md`（工作方式、已知取舍、Web 拍板记录）
4. `engine/game.py`（`Result.ok/reason/data`、`step()` 动作表、`snapshot()/save_checkpoint()/load_checkpoint()`、`_status_data()`）
5. `engine/state.py`、`engine/settings.py`（状态结构与数值；本任务**不改玩法数值**）
6. `cli/main.py`（现有 `risky()` 存档规则、`undo` 语义）、`cli/savefile.py`（存档文件格式与目录）
7. `tests/smoke.py`、`tests/test_gongfa_deep.py`（✓ 脚本式测试风格；本任务新增测试照此写）
8. 参考项目（**只借鉴结构，不引入其插件体系**）：`D:\project\Python\通用架构程序工具组\main.py`（双模式启动/等待就绪）、`shell\backend\file_server.py`（app 工厂、SPA fallback、`/api` 前缀不被吞）

## 目标

浏览器可玩最小闭环：**FastAPI 服务端 + 会话注册表 + `/api/step` 结构化接口 + 极简 HTML 面板**。
CLI 保留为调试工具；**引擎玩法规则与数值零改动**。

**明确不做**：Vue3 工程化前端（P3.7）、pywebview 桌面壳（P3.7）、鉴权/多用户、12 格技能栏 UI、
玩法规则改动、平衡数值调整、CLI 新功能。

## 规格

### A. 引擎补一个只读访问器（`engine/game.py`，唯一允许的引擎改动）

现状：`_status_data()` 私有，且 `step("status")` 会 `turn += 1`；Web 每次响应都要带状态快照，不能靠 step。
新增公开只读方法：

```python
def state_data(self) -> dict:
    """只读状态快照（不推进 turn、不消耗随机流、不落盘）。"""
    return self._status_data()
```

验收：调用前后 `state.turn` 与 `rng.save()` 均不变。

### B. 会话层 `server/session.py`

```python
# 与 cli/main.py 的 risky() 规则保持一致（消耗时间/资源的动作先存节点）
RISKY_ACTIONS = frozenset({
    "cultivate", "breakthrough", "age_pass", "travel",
    "explore", "buy", "use_pill", "comprehend",
})

class GameSession:
    """一个 run 的会话封装：Game + per-run 锁 + checkpoint/autosave 规则。"""
    def __init__(self, seed: int, name: str = "", load: dict = None, save_dir: str = None): ...
    lock: threading.Lock                      # 所有引擎调用必须在 with self.lock 内
    def step(self, action: str, **kw) -> Result
        # action ∈ RISKY_ACTIONS → g.save_checkpoint(); 执行; 落盘(含 .cp.json)
        # 其它动作 → 执行; 落盘(仅 run_<seed>.json)
        # 每步都落盘（等价 CLI 的 sv.write(seed, g.snapshot())）
    def undo(self) -> tuple[bool, Result | None]   # g.load_checkpoint()；失败返回 (False, None)
    def state(self) -> dict                        # g.state_data()
    def meta(self) -> dict                         # {run_id, seed, realm_name, realm_idx, age_years, alive, day, saved_at}
class RunManager:
    def __init__(self, save_dir: str = None): ...
    def new(self, seed: int = None, name: str = "") -> GameSession   # seed 缺省随机 0..0xFFFFFFFF
    def load(self, run_id: str) -> GameSession                       # 内存命中则复用；否则从 saves 读档
    def get(self, run_id: str) -> GameSession | None
    def list_runs(self) -> list[dict]                                # 由 saves/ 目录扫描 + 读档生成 meta
```

约束：
- **`run_id = str(seed)`**（与存档文件名 `run_<seed>.json` 一致，便于 CLI 续玩同一档）。
- 存档 I/O **复用 `cli/savefile.py`**（`write/read/list_saves/save_path`），不复制实现、不改其格式。
- 并发：每 session 一把 `threading.Lock`；handler 内 `with session.lock:` 调引擎。
- 服务层错误码（**不属于引擎 R_* 枚举**，只在 server 层使用）：
  `unknown_run`（run_id 不存在）、`bad_request`（参数缺失/类型错）、`no_checkpoint`（无可回溯节点）。

### C. FastAPI 应用 `server/app.py`

```python
def create_app(config: dict | None = None) -> FastAPI
```

路由（全部 JSON；统一响应结构见下）：

| 方法 | 路径 | 请求 | 响应 |
|---|---|---|---|
| GET | `/health` | — | `{"status": "ok"}` |
| GET | `/api/runs` | — | `{"ok": true, "runs": [meta...]}` |
| POST | `/api/new` | `{seed?, name?}` | `{"ok": true, "run_id", "state"}` |
| POST | `/api/load` | `{run_id}` | 同 new；不存在 → HTTP 404 + `{"ok": false, "reason": "unknown_run"}` |
| POST | `/api/step` | `{run_id, action, kwargs?}` | 见下 |
| POST | `/api/undo` | `{run_id}` | `{"ok", "reason", "state"}` |
| GET | `/api/state` | `?run_id=` | `{"ok": true, "state"}` |

`/api/step` 响应（Result 透传 + 状态快照）：

```json
{
  "ok": true, "reason": "ok", "data": {...},
  "text": "……", "lines": [...],
  "game_over": false, "died": false,
  "battle_started": false, "battle_over": "",
  "state": { ...Game.state_data()... }
}
```

实现要点：
- 端点用**同步 `def`**（FastAPI 线程池执行，不阻塞事件循环）；内部 `with session.lock:`。
- 静态资源：`app.mount("/", StaticFiles(directory=<server/static>, html=True), name="static")`
  —— 必须**在 API 路由注册之后**挂载；`/api` 前缀的 404 保持 JSON（FastAPI 默认行为即可）。
- 不引入 CORS（同源）；不做鉴权（本地单机）。
- `config` 支持 `{"save_dir": ...}` 便于测试注入临时目录。

### D. 启动入口 `server/main.py`

- `python -m server.main [--host 127.0.0.1] [--port 8000]`；打印可访问地址后 `uvicorn.run(...)`。
- 另提供 `build_app(config=None) -> FastAPI`（只返回 app，不启动），供测试导入。
- 参考 `通用架构程序工具组\main.py` 的"启动后等待就绪"思路，但**不需要 pywebview**（P3.7 才做）。

### E. 极简前端 `server/static/`（无构建、无 CDN、原生 JS）

- `index.html` + `app.js` + `style.css`；`fetch` 调 `/api/*`。
- 布局：左=**状态面板**（从响应 `state` 渲染：境界/修为条/闭关效率/寿元/心魔/灵石/地点/背包/
  运转池三槽/领悟池列表）；中=**叙事日志流**（追加 `text`、`lines`，自动滚动）；右=**动作区 + 战斗面板**。
- 动作区（全部走 `/api/step`）：新局/读档、闭关（天数 + 用聚灵丹）、参悟（功法下拉 + 天数）、突破、
  静养、移动/探索（地点下拉）、货单（表格 + 购买）、书库（详情 + 装备槽位选择 / 卸下）、编年史、回溯。
- 战斗面板：`state.battle` 存在时显示双方 HP/灵气条 + 技能按钮（取 `state.battle.skills`）
  + 平砍/防御/遁走/聚气；`battle` 为 null 时隐藏。
- **错误提示用 `reason` 映射**：JS 内一份 `REASON_TEXT`（reason → 中文提示），
  **禁止解析 `text` 判断成败**（text 只进日志流）。
- 首次打开无存档 → 显示"新建一世"。

### F. 测试 `tests/test_server.py`（≥20 项，✓ 脚本式，风格同 test_gongfa_deep）

分组覆盖：
1. `GameSession`：new 后落盘文件存在；risky 动作写 `.cp.json`；非 risky 不写 `.cp.json`
2. `GameSession.step` 返回结构化 `Result`（ok/reason/data）
3. `undo`：risky 动作后回退状态（修为/灵石回到节点）→ ok；无节点 → `(False, None)`
4. `RunManager`：new/load/list/get；`load` 能从磁盘恢复（新建 RunManager 实例）
5. **重启续玩**：session 走若干步 → 新 RunManager → `load` 同 run_id → 境界/修为/灵石/familiarity 一致
6. **并发锁**：两线程各 step N 次 → `turn` 增量 = 2N（不丢步、状态不损坏）
7. **HTTP 冒烟**（stdlib `urllib` + 线程内 uvicorn 或 `TestClient`）：`/health`、`/api/new`、
   `/api/step`（cultivate/comprehend/learn/buy）、`/api/state`、`/api/undo`、`/api/runs` 结构正确
8. **全流程（HTTP 级）**：新局 → 参悟吐纳诀至入门 → 装备主修 → 货单 → 买锐金典 → 参悟 → 换主修
   → 探索遇敌 → 战斗至结束 → 状态正确（胜负逃任一结局都算通过，断言状态一致）
9. 未知 `action` → `ok=false, reason="unknown_action"`（引擎码经 step 透传）
10. 未知 `run_id` → `unknown_run`；缺参数 → `bad_request`
11. `state_data()` 无副作用（turn 与 rng 游标不变）
12. 引擎回归：子进程跑 `tests/test_battle.py`（52）与 `tests/test_gongfa_deep.py`（89）均 0 退出

测试注意：
- 用 `tmp_path`/临时目录注入 `save_dir`，**不得污染真实 `saves/`**（测试结束清理）。
- 起 HTTP 服务用后台线程 + 可关闭的 uvicorn Server（`uvicorn.Server` + `should_exit`），
  或 `fastapi.testclient.TestClient`（若安装 `httpx` 不可得，就用 urllib + 线程方案，**不要新增测试依赖**）。
- Windows 控制台中文：`.venv\Scripts\python.exe -X utf8 ...`。

### G. 依赖与文档

- 新建 `requirements.txt`（写实际安装版本：fastapi、uvicorn；uvicorn 标准依赖按 pip 结果）。
- `README.md`：运行方式加 `python -m server.main` + 浏览器地址；当前状态加 P3.6 条目；目录结构加 `server/`。
- `docs/Web架构方案.md`：§9 P3.6 勾选并补验收数字。
- `docs/实现路线图.md`：P3.6 节勾选 + 验收数字。
- `docs/会话交接.md`：§2 补 P3.6、§4 更新下一步（主会话复核后会再校，实现者先补事实）。

## 验收判据（全部通过才算完成）

1. `pip install -r requirements.txt` 可装；`python -m server.main` 起服务，`GET /health` 返回 200
2. `/api/new`、`/api/load`、`/api/runs` 正常；存档写入 `saves/run_<seed>.json`
3. `/api/step` 全动作可用，响应含 `ok/reason/data/text/state`；引擎 reason 码原样透传
4. **战斗闭环**：探索遇敌 → `battle_action` 多回合 → 胜/败/逃 三结局至少各验证一条，
   `state.battle` 正确出现/消失
5. `undo` 语义与 CLI 一致（risky 动作可回溯，非 risky 不可）
6. **重启续玩**：新进程/新 RunManager `load` 同一 run_id，状态一致
7. **并发**：两线程 step 不丢步（turn 正确）
8. **极简面板可玩**：手工浏览器流程走通（新局→参悟→装备→闭关→货单购买→探索→战斗→回溯），
   错误用 `reason` 提示；报告中贴关键步骤记录
9. **回归**：`test_battle.py` 52、`test_gongfa_deep.py` 89、`tests.smoke` 20 局（18 通关/2 道陨、
   482 场 481 胜/1 逃）全部不变
10. **CLI 仍可用**：`--seed 42 --auto` 脚本输入冒烟不崩（文本输出不变）

## 报告格式（返回给主会话）

- 改了哪些文件（列表）+ 新增依赖与版本
- 10 条验收判据逐条 ✅/❌ + 一句证据
- 手工浏览器验证记录（步骤 + 观察到什么）
- 新增测试项数与本机运行命令
- 遗留问题 ≤3 条（含你的取舍说明）
