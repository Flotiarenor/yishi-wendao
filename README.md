# 一世问道 · 文字修仙

Python 单机文字修仙游戏。终端可玩，纯规则引擎 + 确定性随机，**运行时零 AI**。

> ⚠️ **给新会话的入口**：先读本 README 的「当前状态」，再读 `docs/README.md`（文档地图：
> 谁管什么、谁还算数），然后 `docs/会话交接.md`（取舍与未决问题）。深读顺序：
> `docs/设计定案.md`（规则）→ `docs/实现路线图.md`（进度）→ `docs/tasks/`（未开始阶段的任务书；
> 已完成的在 `docs/archive/tasks/`）。

## 运行

```powershell
cd D:\project\Python\yishi-wendao
.venv\Scripts\python.exe -X utf8 main.py            # 统一入口：起 Web 壳（浏览器玩）
.venv\Scripts\python.exe -X utf8 main.py web --port 8000   # 覆盖默认端口（默认 8044）
.venv\Scripts\python.exe -X utf8 main.py smoke --lives 20  # 自动 bot 回归（记录分布/战斗统计）
.venv\Scripts\python.exe -X utf8 main.py test              # 一键跑全部测试（9 个单测 + 冒烟）
.venv\Scripts\python.exe -X utf8 main.py check             # content/ 数据校验（--strict 警告也失败）
.venv\Scripts\python.exe -X utf8 -m tools.dummy            # 木桩试招（7 流派对照）
```

### 开发期工具（`tools/`，引擎运行时零依赖）

```powershell
python -m tools.content_check                  # 内容校验器：id 撞车/引用悬空/取值越界
python -m tools.gen_skill --in draft.json --strict --emit code   # 技能生成器（draft → 校验 → 代码）
python -m tools.gen_skill --random 10 --seed 42 --out drafts.json  # 随机生成（P9 铺垫）
python -m tools.gen_skill --roundtrip          # 21 个现有技能 draft 往返无损
python -m tools.replay --mode bot --seeds 1001-1020 --out base.json   # 指纹基线
python -m tools.replay --mode bot --seeds 1001-1020 --compare base.json  # A/B 对照
python -m tools.replay --mode script --script script.json             # 显式脚本重放
```

- **统一技能入口**：手写 / AI 起草 / 随机生成都产出同一份 `draft`（JSON），
  经 `tools/gen_skill.py` 校验后落成 `content/skills.py` 的 `_sk(...)` 行或规范化 JSON。
  AI 只需产出 draft，不必知道引擎内部结构。
- **指纹/重放**：固定种子 + 固定策略/脚本 → 稳定 JSON 快照 + sha256 摘要，
  用于"改代码后引擎行为有没有变"的 A/B 对照（替代此前手搓的 worktree 脚本）。

### 前端构建（P3.7，Vue3）

前端源码在 `frontend/`（Vue3 + Vite + Pinia + TS，**无 CDN、离线可跑**），
构建产物 `frontend/dist` 由 FastAPI 伺服（`server/app.py`）。**首次运行或改前端后需构建**：

```powershell
cd frontend
npm install            # 首次
npm run build          # vue-tsc 类型检查 + vite build → dist/
npm run e2e            # 前端 E2E 冒烟（jsdom + 自起服务端，驱动到中置战斗界面）
# 开发模式（热更新，/api 自动代理到 127.0.0.1:8044；可用 XIUXIAN_BACKEND 覆盖）
npm run dev
```

未构建时访问 `/` 会显示构建提示页（`/api/*` 不受影响）。

（CLI 已于 R3.4 下线；子包 `python -m server.main` 入口保留。木桩工具见 `tools/dummy.py`。）

Web 界面布局（P3.7）：**左=状态常驻**（含地图/修炼/坊市/书库/编年史切换按钮）/
**中上=主内容区**（默认地图，遇敌时战斗临时接管，打完自动交还）/**中下=叙事日志**
（可折叠、**可拖拽调整高度**，探索与战斗的文字一直可见）。**没有行动栏**——闭关/参悟/突破/静养
都在**修炼页**（状态栏「修炼」按钮，快捷键 `C`；地图快捷键 `M`）。
战斗中在**决策窗口**内把动作排入队列（`battle_submit`，不推进时间轴），点「执行本轮」或窗口
排满后结算（`battle_skip`）；界面显示时间轴、双方 `next_t`、队列各动作的结束时刻、双方状态效果
与动作可用性（不可用禁用并显示原因）。窗口长度 = 敌方下次出手前的时间。

## 提交

提交信息格式见 `docs/提交规范.md`——**Conventional Commits + 中文**：`feat(map): P4 世界地图内核`。
一个提交一件事，文档与代码分开提。

## 当前状态（2026-09-10）

- ✅ **P0** 生存循环+经济：角色生成/时间/闭关/突破(灵石+丹药门槛)/寿元/存档回溯/探索/坊市/丹药
- ✅ **P1** 功法浅层：13 技能 / 8 功法 / 主修被动加成修炼 / 开局赠书 / learn/forget / 坊市卖功法
- ✅ **P2** 战斗最小闭环：8 敌人 / 回合状态机(平砍/技能/防御/遁走/聚气) / 五行克环 / 探索遇敌 / 胜败逃三结局 / CLI 战斗子循环 / 49 项单测
- ✅ **P3** 功法深层：理解锁(看不懂只见名/层级/来历) / 参悟(cw 投天数) / 熟悉度(技能 unlock_fam 逐层亮) / 需求谱系生效(free/温和/严格) / 领悟池 vs 运转池(主修1+战斗4+身法1) / 池外不生效 / battle+shenfa 槽开放 / utility 最小战斗效果(定身/破势/闪避/吐纳) / 开局赠《吐纳诀》(参悟入门→永久+5% 道基被动) / 21 技能 12 功法 / 52+83 项单测
- ✅ **P3.5** 动作结果结构化：`Result` 增 `ok/reason/data`（原因码 R_* 枚举）；状态/市场/详情改为「数据 + 渲染」分离；测试判定改用 reason/data（不再刮文案）；`52+89` 项单测
- ✅ **P3.6** 最小 Web 闭环：FastAPI 服务端 + `GameSession`/`RunManager` 会话层 + `/api/new|load|step|undo|state|runs` 结构化接口 + 极简 HTML 面板（`python -m server.main` → http://127.0.0.1:8000）；`tests/test_server.py` 69 项；smoke 20 局不变（18/2、482 场）
- ✅ **P3.8** 效果/状态系统（组件化最小核心）：效果=实体（`content/effects.py` 模板袋）+ 固定管线（`engine/battle.py`）+ 修饰器扩展点（`engine/effects.py`，`register_effect`/`register_modifier`）；四 flag → 效果袋 + 兼容只读 property；`Skill.effect_key`/`modifiers`；战报 data 含双方效果列表；`tests/test_effects.py` 61 项；52+89+69 与 smoke 20 局逐位不变。⚠️ **R3 重构后**：`engine/effects.py` 已无任何引用（死代码），`test_effects.py` 重建为 33 项——本条为 P3.8 历史记录
- ✅ **P3.9** 引擎加固（代码审查后修复 5 项，`tests/test_hardening.py` 55 项）：① `step()` 数值参数经 `_as_int` 转换——Web 传坏值不再 500（此前 `days="abc"` → HTTP 500）；② 身死拦截（`alive=False` 时除 status/chronicle 一律 `game_over`，此前死后还能探索赚灵石）；③ 突破寿元改为「加基准差额」（此前成功即重置，把累积折寿一次抹平）；④ 闭关修为封顶（收敛到「刚好圆满的那一天」+ 浮点 epsilon 吸附，不再溢出浪费寿元，也不会 0 天空转）；⑤ `market` 与 `buy` 统一要求身处坊市；`Result.pill_line` 转正式字段
- ✅ **P4-R3** 战斗系统重构（**回合制作废 → 连续时间轴**，`docs/战斗系统定案.md`）：
  `engine/clock.py` 厘息时间轴（同时到达玩家优先、决策窗口、控制推后 next_t）+
  `engine/rules.py` 纯函数五段乘区 + `engine/action.py` 动作模型（组件/条件/前摇打断）+
  `engine/battle.py` 时间轴战斗（决策窗口 + 队列 + 敌方插入 + 统一灵兽进攻）+
  `content/actions.py` 动作数据化 + `tools/dummy.py` 木桩；CLI 下线（存档 I/O 迁 `server/`）。
  基线：`test_effects` 39 + `test_hardening` 75 + `test_clock` 59 + `test_action` 53 +
  `test_battle_time` 45 + `test_gongfa_deep` 91 + `test_server` 83 = **445 项**
  （+ `test_content_tools` 32 + `test_replay` 16 = **493 项**）；
  smoke 20 局 = **19 通关/1 道陨、425 场、平均终档 24.4**
- ✅ **P4-R4** 状态效果补全（**修复 R3 回归**）：新增 `engine/status.py` 行为注册表
  （damage_mult / hit_negate / push_back / speed_mult 四类，倍率取 `ApplyStatus.params`）——
  `guard`（守方乘区）、`evade`（命中判定，battle 按行动实例派生 `hit_roll`）、`root`/`stun`
  （施加瞬间推后 `next_t`）、`slow`（有效速度倍率）全部生效；`clock.schedule` 支持有效速度；
  **删除死代码 `engine/effects.py`**（双 `resolve_damage` 消失，伤害唯一入口落实）；
  `content/effects.py` 改时间窗口语义并补 `stun`/`slow`/`vulnerable` 模板；
  内容补：玄冰刺+迟钝、焚天火海+脆弱、撼岳诀+崩山式（晕眩）→ **22 技能 12 功法**；
  `test_effects` 39 项（四类行为端到端）、`test_battle_time` 36 项（Battle 级闪避/迟钝）
- ✅ **P4-R5** 战斗结算灵石修复（2026-09-10，用户报"击杀/逃跑后灵石消失"）：根因两处——
  `actor_from_stats` 漏拷 `stones`（战斗 Actor 恒 0），`_finish_battle` 又用 `b.p.stones`
  覆盖世界层（胜利战利品先加、随即被清零）→ **每场战斗后灵石归零**；另补 `can_execute`
  对购灵加速的灵石检查（买不起不再显示"可用"）。`test_hardening` 61 项（+6）。
  smoke 20 局 = **19 通关/1 道陨、436 场（331 胜/0 负/105 逃）、平均终档 24.4**
  ——战斗次数从 3874 降到 436，正是"灵石不再每战清零、bot 不必反复刷探索"的体现。
- ✅ **P4-R6** 队列撤回 + 交互细节（2026-09-10，用户要求）：引擎加 `battle_unqueue`
  （撤回单个动作）/`battle_clear`（清空）两个动作 + 队列项 `idx`；战斗界面队列每项带
  「撤回」、队首带「清空」（不推进时间轴、不消耗资源）；灵石结算改为**增量扣款**
  （只扣战斗内花费，不整体覆盖，对以后加战斗内消费更稳）；下拉框默认选中
  （书库槽位/读档显示当前存档/参悟目标）。`test_battle_time` 42、`test_hardening` 65、
  前端 E2E 28 项。
- ✅ **P4-R7** 交互修复（2026-09-10，用户反馈）：① 坊市功法"已有"改由服务端 `owned` 字段判定
  （此前前端按背包名反查 → 永远 0）；② 闭关封顶改为**含聚灵丹**计算"刚好圆满的天数"，
  丹药按**实际天数**消耗（每 10 天 1 颗、受背包限制、覆盖时段 +50%），返回 `pill_qty`/`pill_days`；
  ③ 修炼页显示聚灵丹存量、无丹禁用并自动取消勾选、闭关后 toast 反馈；④ 书库槽位下拉改为
  **永不留空**的 computed（优先空位 战斗1→4，占用项禁用）。`test_hardening` 75（+10）、
  前端 E2E 29（+1）；smoke 20 局 = 19/1、425 场、均终档 24.4。
- ✅ **P4-R8** 战斗/书库交互再打磨（2026-09-10，用户反馈）：① 书库「参悟入门（5 日）」按钮
  从 `canEquip` 里挪出（此前熟悉度 <10 时永不显示 = 永远点不到），参悟后自动刷新详情；
  ② 战斗队列上移到动作按钮正下方；队列条目可点击撤回（整条 + ×）；③ 动作按钮左键
  **toggle**——未排入则排入、已排则撤回最后一个（按钮显示「已排×N」+ 金色描边），
  窗口排满时已排动作仍可点撤回；④ 前摇/后摇改为**异色**（前摇暖金 `--gold`、后摇冷蓝）。
  前端 E2E 31（+2：toggle 撤回 / 点条目撤回）。
  ⚠️ **③ 的 toggle 已于 P4-R13 回退**（它导致同一技能无法连排）。
- ✅ **P4-R9** 前端缓存策略（2026-09-10，用户"重建了看不到变化"）：`server/app.py` 加中间件——
  `index.html` 响应 `Cache-Control: no-cache`（每次回源校验），带哈希的 `/assets/*` 长缓存
  （`immutable`）。此前无缓存头，浏览器可能拿旧 `index.html` → 重建后仍加载旧 JS。
  `test_server` 81（+2 缓存头）。
- ✅ **P4-R10** 启动器端口占用提示（2026-09-10，用户"重启 VSCode 仍报 8000 占用"）：根因是
  VSCode 关终端**不杀子进程** → 孤儿 `main.py` 一直占着端口。`server/main.py` 启动前检测端口，
  占用时打印「`netstat -ano | findstr :PORT` 找 PID / `taskkill /PID <PID> /T /F` / 或
  `--port 8044`」并返回退出码 1；根 `main.py` 透传退出码。
- ✅ **P4-R11** 默认端口改 **8044**（2026-09-10，用户偏好）：`server/main.py` `--port` 默认
  8000→8044（`--port` 仍可覆盖）；根 `main.py` 用法提示同步；`frontend/vite.config.ts` 开发代理
  默认指向 8044（环境变量 `XIUXIAN_BACKEND` 可覆盖）；`test_server` 83（+2 默认端口/覆盖）。
- ✅ **P4-R12** 时间轴队列条按前摇/后摇分段上色（2026-09-10，用户指出 `.tl-queue` 仍整根蓝）：
  `Battle.state().queue[]` 增 `start_t`/`land_t`（按**有效速度**算实际前摇），前端把队列条拆成
  **前摇段（暖金）+ 后摇段（冷蓝）**，分界 = 效果落地时刻；`test_battle_time` 45（+3）、
  前端 E2E 32（+1）。
- ✅ **P4-R13** 恢复重复施放（2026-09-10，用户反馈）：P4-R8 的「点同一动作 toggle 撤回」
  导致**同一技能无法连排**。已回退——点动作按钮**永远排入**（可重复），撤回只走
  **点下方队列条目**（P4-R8 的条目可点保留）。前端 E2E 32（重复排入 + 点条目撤回各 1 项）。
- ✅ **P3.7** 正式前端（Vue3 + Vite + Pinia + TS，`frontend/`）：FastAPI 伺服 `frontend/dist`（SPA fallback，`/api` 404 不被吞）；布局 = **左状态（含切换按钮）/ 中上主内容（地图为主页面）/ 中下叙事日志（可拖拽高度）**，遇敌时**战斗临时接管主内容区**（时间轴 / 决策窗口 / 队列入队-执行 / 双方效果 / 动作可用性，常用动作在上、技能折叠）+ **修炼页**（闭关/参悟/突破/静养，参悟选择记忆）+ 坊市（灵石/背包/购买数量/买不起置灰）+ 书库（详情/装备/卸下）+ 编年史时间线 + 状态面板（五行亲和/业力）；旧 P3.6 极简面板删除（`server/static`）；顺带修复 `gongfa_detail` 对 7/12 功法抛 500 的 `SkillSpec.element` bug；`tests/test_server.py` 79 项 + 前端 E2E 27 项
- ✅ **P4-T2** 世界地图内核（2026-09-10，subagent 实现 + **主会话独立复核**）：
  `content/regions.py`（12 主地形 + 4 硬阻挡 + 湖泊/渡口；25 域 5×5、五行浓度、旧地点锚点）+
  `engine/worldmap.py`（200×200 格 = 20 000 里见方；多倍频值噪声 + 对比度拉伸 → 地形 / 水系 + 渡口 / 灵脉与内容点 /
  城镇选址 / 路网全部由 `world_seed` 确定性重建；代价场 6 种 profile + 窗口化 A\*（防穿角）+ 神识视野 +
  `WorldState` 只存差异）。**行为中性**：地形不进游戏循环——`tools/replay --compare` 20 个种子逐字段一致，
  `game.py`/`state.py` 零改动。`tests/test_worldmap.py` 114 项。
- ⬜ **P4 起未做**（详见 `docs/实现路线图.md`）：**P4 地图与时间地基（进行中：T1/T2 已完成，下一步 T3 移动）**、五行宝光（P5）、死亡转世（P6）、人物势力（P7）、事件化（P8）、生成器（P9）、洞府子系统（P10）、突破考验（P11）、平衡标定（P12）、pywebview 桌面壳
- ✅ **工具链（2026-09-10）**：`tools/content_check.py` 内容校验器（当前 0 错误 / 10 警告，
  全部为"demo 动作孤儿"这类预期提示；P4-R4 前它曾报 `guard`/`evade` 无消费者=回归护栏）；
  `tools/gen_skill.py` 统一技能生成器（`draft → 校验 → content/skills.py 代码 / JSON`，
  手写 / AI 起草 / 随机生成共用一套规则；21 个现有技能往返无损）；
  `tools/replay.py` 指纹/重放（`bot` / `script` 两模式 + `--compare` A/B 对照）；
  `tests/test_content_tools.py` 32 项 + `tests/test_replay.py` 16 项；新增 `main.py check`

⚠️ **平衡说明（2026-09-09 修正）**：smoke 的通关率是**固定种子+固定策略的回归指纹**，不是平衡指标
（换 bot 策略数字就变，与游戏好不好玩无关）。数值平衡统一在 P12 用多策略采样 + 支配策略/资源曲线等
指标做，**不设目标通关率**。当前记录仅用于"引擎行为有没有变"的对照。

## 待修问题（2026-09-10 审查）

> 前四项已在 **P4-R4** 修复（状态效果回归 / 双伤害入口与死代码 / 测试恒真断言 / 身法槽空转），
> 详见上方 P4-R4 条目。以下为**仍未修**的，动手前先跑 `python main.py test` 基线。

1. **RNG 顺序无关性名不副实**：`engine/rng.Rng._derive` 的哈希含 `counter`，多消耗一次
   随机流会改变同一 salt 的结果；`test_battle_time.py` §5 的"额外 rng 调用不影响"断言
   靠整数舍入偶然通过（实测 roll 0.6206 vs 0.6404）。要么按"回溯靠 counter 复原"的口径
   改文档，要么给战斗/探索分独立子流（`Rng.fork`）。
2. **木桩工具与正式内容脱节**：`tools/dummy.py` 只测 `content/actions.py` 的 9 个 R2 demo
   动作，**不测** `content/skills.py` 的 22 个正式技能（技能入口已由 `tools/gen_skill.py` 统一）。
3. **五行单向**：玩家 `Actor.element` 恒为「无」；敌人 `ENEMY_STRIKE.element="无"`，
   敌方元素只作"被克靶子"——是否让敌方攻击也吃自己的五行，待定。
4. 文档：`docs/会话交接.md` 偏大且历史数字多（已加口径提醒）。

## 目录结构

```
main.py    统一入口（仓库根级）：web / smoke / test / check 四个子命令
engine/    纯逻辑引擎（无 I/O）：clock 时间轴 / rules 纯函数规则 / action 动作模型 / battle 时间轴战斗 / game 主循环 / status 状态行为表 / rng 确定性随机 / state 状态 / settings 数值
content/   实体数据（id 编码）：ids / effects 效果模板 / actions 动作数据 / pills(20段) / sites(10段) / skills(30段) / gongfa(40段) / enemies(60段)
server/    Web 壳：session 会话层(GameSession/RunManager) / savefile 存档 I/O / app FastAPI 路由（伺服 frontend/dist）/ main 启动
frontend/  正式前端（Vue3+Vite+Pinia+TS）：src/api 客户端 / src/stores Pinia / src/views 各界面 / dist 构建产物（gitignore）
tools/     开发期工具：dummy 木桩 / content_check 内容校验 / gen_skill 技能生成器 / replay 指纹重放
tests/     smoke 自动 bot 回归 / test_clock 时间轴 / test_action 动作 / test_battle_time 时间轴战斗 / test_effects 效果 / test_gongfa_deep 功法深层 / test_server Web 壳 / test_hardening 引擎加固 / test_content_tools 内容工具 / test_replay 指纹重放
docs/      见 docs/README.md 文档地图
saves/     （运行时自动生成、已 gitignore；run_<seed>.json 档）
.git/      本地仓库（根级；.venv/saves/logs/node_modules/dist 已忽略）
.venv/     虚拟环境（Python 3.13）
```

## 架构要点（改代码前必读）

1. **引擎与界面分层**：engine 纯逻辑零 I/O，server 只做展示与输入，content 是纯数据。
2. **id 编码**（`content/ids.py`）：`id = 分类×100000 + 序号`（7 位整数，前 2 位分类）。
   10=地点 20=丹药 30=技能 40=功法 50=器物 60=敌人。引用一律 id 常量，禁中文名/裸数字。
3. **确定性随机**：固定种子 + 随机流游标（`engine/rng.py`）；存档存游标 → 可复现、可回溯。
4. **存档/回溯**：节点式 checkpoint（杀戮尖塔式，只退一步）；战斗为运行时状态不入存档。
5. **数值集中在 `engine/settings.py`**；平衡改动只动它与 content 数值。
6. **动作结果结构化（P3.5）**：`Result.ok/reason/data` 是机器契约（原因码 `R_*`），
   `text` 只是叙事渲染；测试/前端禁止解析文案，一律看 `ok/reason/data`。
   渲染函数只消费 `_status_data()/_market_data()/_gongfa_detail_data()`。
7. **效果=实体 + 固定管线 + 修饰器**：效果模板是数据实体（`content/effects.py`，
   新效果 = `register_effect` 加模板）；状态是**时间窗口**（`until` 厘息，不再是"回合数"）；
   伤害统一走 `engine/rules.resolve_damage`（唯一入口，五段乘区）；修饰器
   （`armor_pen`/`extra_dmg`，`ctx.extra` 传入）随攻击结算。新增内容只加数据，不改结算代码。
8. **入口参数一律经 `_as_int`（P3.9）**：`step()` 内禁止裸 `int(kw[...])`——Web 壳的 kwargs 不可信，
   坏值必须回退默认并走结构化拒绝，绝不能抛异常变成 HTTP 500。
9. **修为封顶与寿元差额（P3.9）**：闭关收敛到「刚好圆满的那一天」（`data.capped`）；突破成功只
   `寿元 += (新基准−旧基准)`，不得重置寿元（否则折寿被抹平）。
10. **战斗是时间轴（P4-R3，`docs/战斗系统定案.md`）**：厘息整数时间轴，无回合；
    速度是**倍率**（1.0 基准），灵气节流 = `max(后摇÷速度, 耗灵÷回灵)`；
    动作是数据（`content/actions.py`），新增技能只改数据；前摇可被控制打断（退灵气 + 计后摇）；
    随机流 salt 含**行动实例序号**（不依赖 rng 调用次数）。
