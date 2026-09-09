# Web 化架构方案（一世问道 · 壳层）

> 状态：✅ 方案定稿（2026-09-09）。CLI 只是开发调试工具、**已定死亡**；正式形态 =
> 本地服务端（FastAPI）+ 浏览器前端，最终以 pywebview 桌面壳分发（双模式，见 §5）。
> 本文是 Web 壳层的唯一依据；引擎玩法设计仍以 `设计定案.md` / `实现路线图.md` 为准。
> 已拍板决策见 §2 决策记录（修改本方案 = 修改本文件）。

## 1. 背景与动机

1. **CLI 产出不可玩**：中文文本流 + 无状态面板，只能算调试通道，不是产品形态。
2. **测试刮文本 = 架构症状**（2026-09-09 用户指出）：`"尚未拥有" in r.text` 一类断言占
   `test_gongfa_deep.py` 一半，因为引擎动作层只通过 `Result.text`（渲染散文）汇报结果，
   没有"成功/失败 + 稳定原因码 + 结构化数据"通道 → 测试只能刮文案当原因枚举。
3. **设计定案原则未兑现**：「状态机与叙述分离——文字只是状态的渲染」目前只做到
   *持久状态 vs 叙事* 分离；*动作结果语义 vs 叙事* 尚未分离。Web UI 需要结构化结果，
   否则前端将被迫反向解析中文散文（比测试刮文本更糟）。

## 2. 决策记录（已拍板）

| # | 决策 | 拍板人/日 |
|---|---|---|
| 1 | Web 是唯一正式形态；CLI 降级为调试工具（smoke/bot 仍直连引擎层） | 用户 2026-09-09 |
| 2 | 后端框架 = **FastAPI**（Pydantic 契约 + /docs 调试；引擎同步代码用 sync 端点线程池 + per-run 锁） | 用户 2026-09-09 |
| 3 | 实施顺序：P3.5 引擎结构化 Result → P3.6 最小 Web 闭环 → 阶段2 正式 Vue3 前端 + pywebview | 用户 2026-09-09（先方案后动手） |
| 4 | 前端技术栈 = Vue3 + Vite + Pinia + TS（与 OmniBox 同栈，用户已熟） | 参考项目调研结论 |
| 5 | 引擎保持零 web 依赖、零 I/O（现状不变）；存档/会话逻辑抽成独立层供 CLI 与 Web 共用 | 主会话建议 |

## 3. 参考项目调研结论（D:\project\Python\通用架构程序工具组 = OmniBox）

可迁移的三件套：

1. **双模式启动，同一套前端**（`main.py` L124-161）：
   - `--web-only`：纯服务端进程（浏览器 / nginx / SSH 隧道访问）；
   - 默认：Flask（`threaded=True`）后台线程 + **pywebview 窗口**指向 `http://host:port`，
     `js_api` 注入系统方法。
   → 修仙游戏复制此形态：开发期浏览器玩，分发期 pywebview 包壳，前端零改动。
2. **前端桥接层**（`file_server.py` L193-217）：前端统一调 `window.pywebview.api.<method>`；
   浏览器模式下后端 `POST /api/<path> {args,kwargs}` 原样桥接 → `{result}` / `{error}`。
   → 前端只需写一套 Bridge 层。
3. **后端形态**：应用工厂（`create_app(config, manager)`）+ SPA fallback（`/api` 404 不被
   fallback 吞成 index.html）+ 静态伺服 + 令牌鉴权（本地单机可简化）；前端栈 Vue3+Vite+TS。
   → 修仙游戏：FastAPI 应用工厂 + `StaticFiles` 伺服前端 dist + SPA fallback。

## 4. 分层架构

```
┌────────────────────────────────────────────────────────────┐
│ frontend/   Vue3+Vite（阶段1：server/static 内嵌极简 HTML）  │
│   全部经 Bridge 调 api：桌面=window.pywebview.api ｜ 浏览器=POST /api/... │
├────────────────────────────────────────────────────────────┤
│ server/     FastAPI 壳：路由 /api/new|list|step / 静态伺服  │
│   session.py: RunManager(注册表 run_id→GameSession)         │
│   GameSession: Game + per-run Lock + checkpoint/autosave 规则│
├────────────────────────────────────────────────────────────┤
│ cli/        保留（调试）：直连 engine，经同一 GameSession 规则 │
│ tests/      直连 engine（不经 web，不进 session）            │
├────────────────────────────────────────────────────────────┤
│ engine/    纯逻辑 零I/O 零web：game/battle/rng/state/settings│
│   Result 扩展 ok/reason/data（P3.5）                        │
└────────────────────────────────────────────────────────────┘
```

要点：**玩法逻辑永远只在 engine**；server 只做 会话装配/序列化/路由；前端只消费结构化
`data` 渲染面板，`text` 进"叙事日志流"展示。

## 5. 引擎契约（P3.5 · 地基）

### 5.1 Result 扩展（engine/game.py）

```python
@dataclass
class Result:
    text: str = ""              # 叙事（给人看；CLI 照旧用它，不改）
    ok: Optional[bool] = None   # None=信息型动作(如 status/market)；True/False=成败
    reason: str = ""            # 稳定失败码（见 5.2 枚举）；成功可为空或 "ok"
    data: dict = ...            # 结构化负载（见 5.3）
    game_over/died/...          # 既有字段保留
```

- 所有拒绝分支补 `r.ok=False; r.reason=…`；成功动作 `r.ok=True` + `data` 填关键结构。
- **CLI 显示零改动**（`text` 保持完整）；只新增字段。

### 5.2 reason 码枚举（草案，命名即文档）

| 码 | 含义 | 典型动作 |
|---|---|---|
| `not_owned` | 未拥有（先坊市购得） | learn/comprehend |
| `realm_gate` | 境界未至看不懂 | learn/comprehend/buy 提示 |
| `not_entry` | 未参悟入门（fam<FAM_ENTRY） | learn |
| `fam_max` | 已大成无需再参悟 | comprehend |
| `type_mismatch` | 功法类与槽位不匹配 | learn |
| `slot_occupied` | 目标槽被占（先卸） | learn |
| `slot_invalid` | 槽位不存在/越界 | learn/forget |
| `dup_owned` | 已拥有（重复购） | buy |
| `not_market` | 坊市不售该物 | buy |
| `no_stones` | 灵石不足 | buy/breakthrough |
| `not_at_market` | 不在坊市 | buy |
| `unknown_item` / `unknown_action` | 解析失败 | 各动作 |
| `in_battle` | 战斗中只许战斗指令 | step 兜底 |
| `not_in_battle` | 不在战斗 | battle_action |
| `low_qi` / `skill_na` / `unknown_skill` | 战斗技能拒绝 | battle_action |
| `game_over` | 已身死 | 各动作 |
| `no_checkpoint` | 无可回溯节点 | undo |

### 5.3 data 负载建议（按动作）

| action | data 关键字段 |
|---|---|
| status | player 快照（境界/效率/寿元/心魔/灵石/地点/背包/运转池三槽/领悟池） |
| market | 丹药表、功法表（含"是否看懂/隐藏"标记，UI 据此分级展示） |
| gongfa_detail / book | 该功法（或书库列表）的结构化详情 |
| comprehend / learn / forget / buy / cultivate / breakthrough / use_pill | 影响的 id/数值/新状态增量（如 fam、效率、灵石余额） |
| explore | 结果类型：得石/得丹/**遇敌**(enemy 摘要) |
| battle_action | 回合战报（双方 HP/灵气/敌状态）、可用技能池、结局码 |
| chronicle | entries 列表 |

> 判定迁移（与 §1.2 呼应）：引擎单测从 `"尚未拥有" in r.text` 迁移到
> `r.reason == "not_owned"` + 状态断言；文案断言只保留给 UI 信息分级契约用例
> （market/gd 看不懂只见书名/来历等，那些本质是展示层契约，可逐步移到前端测试）。

## 6. 会话层（CLI 与 Web 共用）

现状：CLI 主循环手写"消耗时间动作前 save_checkpoint → 执行 → 落盘"（`cli/main.py` 的
`risky()`）。Web 需要同一规则 → 抽成独立类，CLI 与 server 都复用：

```python
# server/session.py（未来 engine/ 旁或独立包，仅依赖 engine + cli.savefile）
class GameSession:
    """一个 run 的会话封装：Game + Lock + checkpoint/autosave 规则。"""
    def __init__(self, seed, name="", load=None, save_dir=None): ...
    def snapshot/step(action, **kw) -> (Result, state_meta)
        # risky 类动作自动：save_checkpoint→执行→落盘（同现 CLI 规则）
        # 每步落盘 run_<seed>.json；checkpoint 写 .cp.json
    lock: threading.Lock

class RunManager:
    """注册表：run_id→GameSession；新局/续玩/列表/释放。"""
```

- `cli/main.py` 后续可瘦身复用 GameSession（可选，非阻塞）。
- 存档文件沿用 `saves/run_<seed>.json` / `run_<seed>.cp.json`（`cli/savefile.py` 结构不改，
  兼容 `--resume` 旧档）。

## 7. API 契约（P3.6 · FastAPI）

```
GET  /health
GET  /api/runs                    → 存档列表（seed/时间/境界概要）
POST /api/new   {seed?, name?}    → {run_id, state}（固定种子可指定）
POST /api/load  {run_id}          → {run_id, state}
POST /api/step  {run_id, action, kwargs} → {ok, reason, data, lines[], battle?}
POST /api/undo  {run_id}          → checkpoint 回溯（会话内，同现逻辑）
```

统一响应（step）示例：

```json
{
  "ok": true,
  "reason": "",
  "data": {"player": {...}, "log": "闭关30日…"},
  "lines": ["闭关30日…", "年龄…"],          // 叙事日志流（前端滚动区）
  "battle": {"active": true, "p_hp": 95, "p_qi": 65, ...},
  "game_over": false, "died": false
}
```

- 端点用 `def`（sync）→ FastAPI 线程池跑；每个 run 一把 `threading.Lock`，handler 内
  `with lock: session.step(...)`（引擎非线程安全）。
- 静态：`app.mount("/", StaticFiles(directory=frontend_dist, html=True))` + SPA fallback
  守卫 `/api` 404 不被吞（OmniBox 同款教训）。
- 单机模式可免令牌；若将来局域网分享再加 OmniBox 式 Cookie/Header token。
- 依赖新增：`fastapi`、`uvicorn`（pywebview 留到阶段2 再装）。

## 8. 前端路线

- **阶段 1（P3.6）**：`server/static/` 极简 HTML+JS（无构建）打通闭环：
  新局 → 状态面板 → 闭关/参悟 → 市场/购 → 探索 → 战斗按钮流。目的：验证协议、
  让真实玩家在浏览器里试玩 P0-P3 全部系统（UI 丑没关系）。**P3.7 起已删除**。
- **阶段 2（P3.7，✅ 已落地）**：正式 Vue3+Vite+Pinia+TS 工程（`frontend/`），API 客户端统一
  走 `fetch('/api/...')`（同源，无 CORS）；dist 由 FastAPI 伺服。UI 形态由用户拍板（含修订）：
  **左状态（含切换按钮）/ 中上主内容 / 中下叙事日志（可拖拽高度）**；
  **地图是主页面，战斗临时接管主内容区**（时间轴 + 决策窗口 + 队列），坊市/书库/编年史为临时视图；
  **无行动栏**——闭关/参悟/突破/静养收进「修炼页」（主内容区视图）。
  （首版把地图/坊市做成覆盖层 → 探索后看不到文字；第二版用行动抽屉 → 用户改为日常动作直接进主页面。）
- **阶段 3**：pywebview 桌面壳（Windows 分发），复用 OmniBox `main.py` 双模式启动写法。
  （`vite.config.ts` 已设 `base: "./"`，file:// 加载无需改动）

## 9. 里程碑与验收判据

### P3.5 · 引擎动作结果结构化（✅ 已完成 2026-09-09，主会话直接实现）
- [x] Result 增 `ok/reason/data`（默认值向后兼容；`_reject`/`_accept` 统一助手）
- [x] 全动作拒绝分支补 reason 码（R_* 常量 26 个）；成功动作补 data（§5.3 表全覆盖）
- [x] status/market/gongfa_detail 改「数据 + 渲染」分离（渲染只消费 `*_data()`）
- [x] battle 层 `last_reason`（low_qi/skill_na/unknown_skill/unknown_action/battle_ended）
- [x] 测试迁移：`test_gongfa_deep.py` 89 项、`test_battle.py` 52 项，判定改 reason/data（文案仅存渲染冒烟）
- [x] 验收：smoke 20 局结果与重构前逐位一致（18 通关/2 道陨、482 场 481 胜/1 逃）；变异测试（改原因码）立即 2 红

### P3.6 · 最小 Web 闭环（✅ 已完成 2026-09-09，subagent 实现 + 主会话独立复核通过）
- [x] `server/` 包：session.py（GameSession/RunManager）+ FastAPI 应用工厂 + `/health` + `/api/new|load|step|undo|state|runs`
- [x] 依赖 fastapi 0.141.1 / uvicorn 0.52.4；`python -m server.main` 可起（打印地址后 uvicorn.run）
- [x] 极简 HTML 面板全流程可玩（新局/闭关/参悟/换功法/市场/探索/战斗/回溯/服丹/编年史；原生 JS + REASON_TEXT 错误映射）
- [x] 每步落盘 + 重启后续玩（RunManager 从 saves/ 恢复；familiarity int 键 JSON 往返修复）
- [x] 回归：`test_server.py` 69 项；CLI/smoke/tests 全部不受影响（smoke 20 局 18/2、482 场不变）
- 验收数字：判据 10/10 过（见任务书 `docs/archive/tasks/P3_6-Web壳.md` 验收节与 subagent 报告）

### P3.7 · 正式前端（✅ 已完成 2026-09-09，Vue3 + Vite + Pinia + TS）
- [x] `frontend/` Vue3+Vite+Pinia+TS 工程；`npm run build`（vue-tsc 类型检查 + vite build）→ `frontend/dist`
- [x] FastAPI 伺服 `dist` + SPA fallback（`html=True`；`/api` 404 不被吞）；未构建时返回构建提示页
- [x] 面板：状态 / 修炼 / 编年史 / 书库(gd) / 货单 / 战斗 / 回档；布局 = 左状态（含切换按钮）+
      中上主内容 + 中下日志（可拖拽高度）；**无行动栏**
- [x] 战斗**临时接管主内容区**（地图为主页面），按 `docs/战斗系统定案.md` §四：时间轴 + 决策窗口 +
      队列（入队/执行）+ 效果列表 + 动作可用性；常用动作在上、技能折叠
- [x] 修炼页：闭关/参悟/突破/静养（参悟选择记忆；场所限制留待 P7 客栈/洞府）
- [x] 无 CDN / 无构建期外部依赖；离线可跑（产物 JS 114 kB / CSS 13 kB）
- [x] 顺带修复 `SkillSpec.element`（12 本功法中 7 本 `gongfa_detail` 抛 500）；`tests/test_server.py` 79 项
- [x] 旧 P3.6 极简面板（`server/static`）删除——其战斗字段与引擎契约不符，属误导性死代码
- [ ] （可选）pywebview 桌面壳

## 10. 风险与取舍

1. 引擎 `data` 负载会随玩法扩展（P4 地图/P11 突破考验/P7 势力）持续增字段——接口版本化暂不做，
   单机自洽项目保持"最新即契约"，文档随任务书更新。
2. FastAPI 依赖新增进 `.venv`；项目仍零运行时 AI、确定性可复现不变。
3. CLI 保留成本低（调试/bot），但**新功能默认不做 CLI 适配**，验收以 Web 冒烟为主——
   本决策生效后，P4+ 任务书的验收判据改以引擎单测 + Web 冒烟为准。
4. 平衡标定（P12）与 Web 化正交，互不阻塞。

## 11. 相关文档

- 前置工作 P3.5（动作结果结构化）由主会话直接实现，**从未落盘任务书**（原计划的
  `P3_5-动作结果结构化.md` 不存在，勿再引用）；产出见 `docs/实现路线图.md` P3.5 条目。
- 参考项目：`D:\project\Python\通用架构程序工具组\main.py`（双模式）、
  `shell\backend\file_server.py`（app 工厂 + api 桥 + SPA fallback）
- 设计定案：§一.2（状态机与叙述分离）、§十三（素材/机制层分离——Web 壳同理属"壳层"）
