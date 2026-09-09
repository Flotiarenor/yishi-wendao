# 修仙文字游戏（working title）

Python 单机文字修仙游戏。终端可玩，纯规则引擎 + 确定性随机，**运行时零 AI**。

> ⚠️ **给新会话的入口**：先读本 README 的「当前状态」与「文档地图」，再读
> `docs/会话交接.md`（最后的决策与未决问题）。深读顺序：`docs/设计定案.md`（规则）
> → `docs/实现路线图.md`（进度）→ `docs/tasks/P<n>.md`（当前阶段任务书）。

## 运行

```powershell
cd D:\project\Python\game
.venv\Scripts\python.exe -X utf8 main.py            # 统一入口：默认起 Web 壳（浏览器玩）
.venv\Scripts\python.exe -X utf8 main.py web --port 8000   # 同上，指定端口
.venv\Scripts\python.exe -X utf8 main.py cli --seed 42     # 终端调试壳
.venv\Scripts\python.exe -X utf8 main.py smoke --lives 20  # 自动 bot 回归（记录分布/战斗统计）
.venv\Scripts\python.exe -X utf8 main.py test              # 一键跑全部测试
```

（子包入口仍可用：`python -m cli.main` / `python -m server.main`；`python -m tests.smoke` 等测试命令照旧。）

游戏内指令：`s`状态 ｜ `c N[ p]`闭关 ｜ `cw N 功法名`参悟 ｜ `b`突破 ｜ `m`坊市货单 ｜
`t/e 地点` 移动/探索 ｜ `buy 品名` 购买 ｜ `g 功法名 [槽位]`装入运转池（空=主修/1~4战斗/s身法）｜
`gf [槽位]`卸下 ｜ `gd [功法名]`书库/详情 ｜ `use 品名` 服丹 ｜ 遇敌进战斗后 `ba 1~5`。

## 当前状态（2026-09-09）

- ✅ **P0** 生存循环+经济：角色生成/时间/闭关/突破(灵石+丹药门槛)/寿元/存档回溯/探索/坊市/丹药
- ✅ **P1** 功法浅层：13 技能 / 8 功法 / 主修被动加成修炼 / 开局赠书 / learn/forget / 坊市卖功法
- ✅ **P2** 战斗最小闭环：8 敌人 / 回合状态机(平砍/技能/防御/遁走/聚气) / 五行克环 / 探索遇敌 / 胜败逃三结局 / CLI 战斗子循环 / 49 项单测
- ✅ **P3** 功法深层：理解锁(看不懂只见名/层级/来历) / 参悟(cw 投天数) / 熟悉度(技能 unlock_fam 逐层亮) / 需求谱系生效(free/温和/严格) / 领悟池 vs 运转池(主修1+战斗4+身法1) / 池外不生效 / battle+shenfa 槽开放 / utility 最小战斗效果(定身/破势/闪避/吐纳) / 开局赠《吐纳诀》(参悟入门→永久+5% 道基被动) / 21 技能 12 功法 / 52+83 项单测
- ✅ **P3.5** 动作结果结构化：`Result` 增 `ok/reason/data`（原因码 R_* 枚举）；状态/市场/详情改为「数据 + 渲染」分离；测试判定改用 reason/data（不再刮文案）；`52+89` 项单测
- ✅ **P3.6** 最小 Web 闭环：FastAPI 服务端 + `GameSession`/`RunManager` 会话层 + `/api/new|load|step|undo|state|runs` 结构化接口 + 极简 HTML 面板（`python -m server.main` → http://127.0.0.1:8000）；`tests/test_server.py` 69 项；smoke 20 局不变（18/2、482 场）
- ✅ **P3.8** 效果/状态系统（组件化最小核心）：效果=实体（`content/effects.py` 模板袋）+ 固定管线（`engine/battle.py`）+ 修饰器扩展点（`engine/effects.py`，`register_effect`/`register_modifier`）；四 flag → 效果袋 + 兼容只读 property；`Skill.effect_key`/`modifiers`；战报 data 含双方效果列表；`tests/test_effects.py` 61 项；52+89+69 与 smoke 20 局逐位不变
- ✅ **P3.9** 引擎加固（代码审查后修复 5 项，`tests/test_hardening.py` 55 项）：① `step()` 数值参数经 `_as_int` 转换——Web 传坏值不再 500（此前 `days="abc"` → HTTP 500）；② 身死拦截（`alive=False` 时除 status/chronicle 一律 `game_over`，此前死后还能探索赚灵石）；③ 突破寿元改为「加基准差额」（此前成功即重置，把累积折寿一次抹平）；④ 闭关修为封顶（收敛到「刚好圆满的那一天」+ 浮点 epsilon 吸附，不再溢出浪费寿元，也不会 0 天空转）；⑤ `market` 与 `buy` 统一要求身处坊市；`Result.pill_line` 转正式字段
- ⬜ **P3.7 / P4 起未做**（详见 `docs/实现路线图.md`）：正式 Vue3+Vite 前端 + pywebview 桌面壳、突破考验、五行宝光、死亡转世、人物势力、事件化、生成器、平衡标定

⚠️ **平衡说明（2026-09-09 修正）**：smoke 的通关率是**固定种子+固定策略的回归指纹**，不是平衡指标
（换 bot 策略数字就变，与游戏好不好玩无关）。数值平衡统一在 P10 用多策略采样 + 支配策略/资源曲线等
指标做，**不设目标通关率**。当前记录仅用于"引擎行为有没有变"的对照。

## 目录结构

```
main.py    统一入口（仓库根级）：web / cli / smoke / test 四个子命令
engine/    纯逻辑引擎（无 I/O）：game 主循环 / battle 战斗 / effects 效果运行时 / rng 确定性随机 / state 状态 / settings 数值
content/   实体数据（id 编码）：ids / effects 效果模板 / pills(20段) / sites(10段) / skills(30段) / gongfa(40段) / enemies(60段)
cli/       终端壳：main 主程序 / savefile 存档（server 会话层复用其 I/O）
server/    Web 壳：session 会话层(GameSession/RunManager) / app FastAPI 路由 / main 启动 / static 极简面板
tests/     smoke 自动 bot 回归 / test_battle 战斗单测 / test_gongfa_deep 功法深层 / test_server Web 壳 / test_effects 效果系统 / test_hardening 引擎加固
docs/      见文档地图
saves/     （运行时自动生成、已 gitignore；CLI 与 server 共用 run_<seed>.json 档）
.git/      本地仓库（根级；.venv/saves/logs 已忽略）
.venv/     虚拟环境（Python 3.13）
```

## 架构要点（改代码前必读）

1. **引擎与界面分层**：engine 纯逻辑零 I/O，cli 只做展示与输入，content 是纯数据。
2. **id 编码**（`content/ids.py`）：`id = 分类×100000 + 序号`（7 位整数，前 2 位分类）。
   10=地点 20=丹药 30=技能 40=功法 50=器物 60=敌人。引用一律 id 常量，禁中文名/裸数字。
3. **确定性随机**：固定种子 + 随机流游标（`engine/rng.py`）；存档存游标 → 可复现、可回溯。
4. **存档/回溯**：节点式 checkpoint（杀戮尖塔式，只退一步）；战斗为运行时状态不入存档。
5. **数值集中在 `engine/settings.py`**；平衡改动只动它与 content 数值。
6. **动作结果结构化（P3.5）**：`Result.ok/reason/data` 是机器契约（原因码 `R_*`），
   `text` 只是叙事渲染；测试/前端禁止解析文案，一律看 `ok/reason/data`。
   渲染函数只消费 `_status_data()/_market_data()/_gongfa_detail_data()`。
7. **效果=实体+固定管线+修饰器（P3.8）**：效果模板是数据实体（`content/effects.py`，新效果 =
   `register_effect` 加模板）；结算走固定管线（`engine/battle.py` 回合内：施加→敌行动→回合末
   tick），伤害统一 `resolve_damage`（无修饰器与旧公式逐位一致）；修饰器（`armor_pen`/`extra_dmg`
   /`register_modifier` 追加）随攻击结算。新增内容只加数据/注册函数，不改结算代码。
8. **入口参数一律经 `_as_int`（P3.9）**：`step()` 内禁止裸 `int(kw[...])`——Web 壳的 kwargs 不可信，
   坏值必须回退默认并走结构化拒绝，绝不能抛异常变成 HTTP 500。
9. **修为封顶与寿元差额（P3.9）**：闭关收敛到「刚好圆满的那一天」（`data.capped`）；突破成功只
   `寿元 += (新基准−旧基准)`，不得重置寿元（否则折寿被抹平）。
