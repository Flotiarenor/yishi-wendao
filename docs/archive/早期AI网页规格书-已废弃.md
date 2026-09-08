我明白你的意思了。你需要的是一份**可以直接输入给AI编程助手**的**详细逻辑规格说明书**，让AI按照这份文档来生成代码。下面我就提供一份面向AI的、结构清晰的开发规格，包含数据模型、API路由、核心业务规则、随机性控制、边界处理等。你可以把这份文档直接丢给Codex或类似工具，让它逐步实现。

---

# 修仙文字游戏 - AI编程规格说明书

**项目目标**：开发一个纯文字+简单UI的修仙风格小游戏（单机Web版），玩家通过修炼、探索秘境、战斗来提升境界，并通过交易和拍卖系统进行资源交换。

**技术栈**：
- 后端：Python 3 + Flask（或FastAPI） + SQLAlchemy + SQLite
- 前端：原生HTML/CSS/JavaScript（无框架，使用fetch调用API）
- 游戏核心：Python类，不依赖外部服务

**架构**：
- 前后端分离（后端提供RESTful API，前端通过JavaScript调用）
- 所有数据持久化到SQLite数据库，使用SQLAlchemy ORM

---

## 一、数据库模型定义

使用SQLAlchemy定义以下模型（需包含字段类型和约束）：

1. **Player**（玩家表）
   - `id` (Integer, PK)
   - `nickname` (String, unique, 非空)
   - `password_hash` (String, 非空)（用werkzeug安全模块）
   - `realm` (Integer, 境界等级，1=炼气,2=筑基,...)
   - `experience` (Integer, 经验值)
   - `max_hp` (Integer, 最大生命)
   - `hp` (Integer, 当前生命)
   - `max_mp` (Integer, 最大法力)
   - `mp` (Integer, 当前法力)
   - `attack` (Integer, 攻击力)
   - `defense` (Integer, 防御力)
   - `speed` (Integer, 速度)
   - `element` (String, 灵根属性，可选“金木水火土”)
   - `inventory` = relationship("Inventory", backref="player")
   - `last_login` (DateTime, 自动更新)

2. **Item**（物品表）
   - `id` (Integer, PK)
   - `name` (String, 物品名)
   - `type` (String, 类型：丹药、法宝、材料、功法、神秘物)
   - `quality` (String, 品质：凡品、下品、中品、上品、极品)
   - `description` (Text)
   - `effect` (JSON，使用Text存储，如{"hp":50} 或 {"mp":20} 或 {"exp":100})
   - `value` (Integer, 基准价格灵石)

3. **Inventory**（背包表）
   - `id` (Integer, PK)
   - `player_id` (Integer, FK->player.id)
   - `item_id` (Integer, FK->item.id)
   - `quantity` (Integer, 默认1，>=0)

4. **Enemy**（敌人表）
   - `id` (Integer, PK)
   - `name` (String)
   - `realm` (Integer, 对应境界等级)
   - `hp`, `attack`, `defense`, `speed` (Integer)
   - `exp_reward` (Integer, 经验奖励)
   - `loot_table` (Text, JSON格式，如{"item_id":概率, ...})

5. **Instance**（秘境表）
   - `id` (Integer, PK)
   - `name` (String)
   - `difficulty` (Integer, 推荐境界等级)
   - `map_data` (Text, JSON格式，5x5网格，每个格子包含事件类型代码)

6. **Skill**（技能表）
   - `id` (Integer, PK)
   - `name` (String)
   - `mp_cost` (Integer)
   - `damage_multiplier` (Float, 攻击加成)
   - `element` (String, 可选，无则物理)
   - `description`

7. **PlayerSkill**（玩家技能表）用于多对多关系
   - `player_id` (Integer, FK)
   - `skill_id` (Integer, FK)
   - `skill_level` (Integer, 技能等级，默认1)

8. **Transaction**（交易记录，后期扩展拍卖）
   - `id` (Integer, PK)
   - `seller_id` (Integer, FK->player.id)
   - `buyer_id` (Integer, FK->player.id, 可空)
   - `item_id` (Integer)
   - `quantity` (Integer)
   - `price` (Integer)
   - `status` (String: listing, sold, cancelled)
   - `created_at` (DateTime)

---

## 二、API接口设计

所有接口返回JSON格式，错误时返回 `{"error": "消息"}`。

### 认证模块
- `POST /register`：`{nickname, password}` → 创建玩家，初始化属性。
- `POST /login`：`{nickname, password}` → 返回session token或使用Flask-Login（建议用session）。

### 玩家操作
- `GET /player/profile`：返回玩家当前属性、境界、背包内容。
- `POST /player/cultivate`：执行修炼（增加经验），参数可指定时间（如30秒一次，可传递duration）。
- `POST /player/breakthrough`：尝试突破境界，返回成功/失败概率结果。

### 探索模块
- `GET /instance/<id>/view`：返回秘境地图的JSON表示（如5x5矩阵，标记当前坐标）。
- `POST /instance/<id>/move`：`{direction: up/down/left/right}`，返回新格子的事件数据或状态。
- `GET /instance/<id>/event`：当玩家位于某个格子，返回该格子事件（若有）：战斗、宝箱、陷阱等。

### 战斗模块
- `POST /battle/start`：`{enemy_id}` 或 `{instance_cell_event}` → 初始化战斗，返回战斗状态。
- `POST /battle/action`：`{action: attack/skill/defend/flee, skill_id?}` → 执行一次回合，返回回合结果（双方血量、伤害、结果）。
- `GET /battle/status`：返回战斗当前状态。

### 背包与物品
- `GET /inventory`：列出背包所有物品。
- `POST /inventory/use`：`{item_id, quantity}` → 使用物品（如火系丹药增加HP，经验丹增加经验）。
- `POST /inventory/drop`：丢弃物品。

### 商店系统（NPC）
- `GET /shop/list`：列出NPC出售物品（可配置固定列表）。
- `POST /shop/buy`：`{item_id, quantity}` → 购买，扣灵石，加背包。
- `POST /shop/sell`：`{item_id, quantity}` → 出售，获得灵石（价格按一定机制）。

### 拍卖行（可选扩展）
- `GET /auction/listings`：列出所有在卖物品。
- `POST /auction/list`：`{item_id, quantity, price}` → 挂单。
- `POST /auction/bid`：`{listing_id, price}` → 出价。
- 定时任务处理到期拍卖（可用Flask-APScheduler或手动触发）。

### 存档（自动）
- 每次关键操作后自动保存（通过数据库事务），无需专门接口。

---

## 三、核心业务逻辑规则（详细描述，供AI实现）

### 1. 修炼与境界突破
- 玩家点击“修炼”后，每次修炼消耗30秒（前端计时），后端接口 `POST /cultivate` 返回增加的经验，并更新玩家属性。
- 经验公式：`exp_gain = 10 * player.realm + random(0, 5)`。
- 破境所需经验：`need_exp = 100 * realm * realm`（例如炼气1→筑基需要200经验）。
- 突破概率：基础成功率 = `max(0.5, 0.9 - (realm * 0.02))`，每使用一枚“突破丹”增加20%概率，突破丹需在背包中扣除。
- 突破失败：扣除一半当前经验，返回失败消息。成功后 `realm += 1`，并重置经验为0，同时更新属性（hp+=20, attack+=5, defense+=3, speed+=1）。

### 2. 战斗系统
- 回合制，速度高先出手。
- 攻击伤害公式：`damage = max(1, attacker.attack - defender.defense / 2 + random.randint(-5, 5))`。
- 技能伤害：`damage * skill.damage_multiplier`，消耗MP，MP不足则无法使用。
- 五行克制：若技能或普攻有元素，对照五行相克（金克木、木克土、土克水、水克火、火克金），克制时伤害×2，被克制×0.5。玩家灵根决定其技能伤害加成（若相同+10%）。
- 防御指令：本回合减伤50%，但下回合无法防御。
- 逃跑：成功率 = `30% + (player.speed - enemy.speed) * 2%`，最低10%，成功结束战斗。
- 战斗胜利：获得经验，并按照敌人loot_table随机掉落物品进入背包（概率可配置）。

### 3. 秘境生成与探索
- 秘境地图为5x5网格，每个格子代表一种事件类型：
  - 0: 空（可通行）
  - 1: 普通怪物（按境界随机）
  - 2: 精英怪物（掉落更好，但更强）
  - 3: 宝箱（随机获得灵石或物品）
  - 4: 陷阱（损失HP）
  - 5: 机缘（随机获得技能或属性提升）
  - 6: 出口/终点（返回出发地并额外奖励）
- 生成算法：使用随机种子（如实例ID），固定每个格子的事件类型（保证可重复性）。起始位置为 (0,0)，终点为 (4,4)。
- 探索规则：每移动一格消耗1“精力”（可用体力值，初始100，回复1/分钟）。精力为0则无法移动，只能休息（返回）。
- 事件触发：到达新格子后，自动触发该格子默认事件。战斗中允许逃跑，但逃跑视为离开秘境（返回出发点）。

### 4. 交易系统（NPC商店）
- 预设一个商店物品列表（可存在数据库或常量表），包含丹药、材料、装备等。
- 买价格 = item.value * 1.2（溢价），卖价格 = item.value * 0.8（折扣）。
- 购买时检查灵石足够，数量不超过背包上限（每物品上限999）。

### 5. 背包物品使用
- 丹药类 `type == "丹药"`：效果存储在item.effect的JSON中，如`{"hp":50}`，使用后恢复对应属性，并删除一个。
- 经验丹效果：`{"exp":100}`，直接增加经验。
- 材料类不可使用，可出售。

### 6. 存档与异常处理
- 使用SQLAlchemy的session自动持久化，每次操作后commit。
- 遇到非法操作（如背包无物品）返回错误码，且不执行状态变化。

---

## 四、前端交互说明（指导AI生成HTML/JS）

- 页面分主页面：
  - **登录/注册页**：表单，POST到API。
  - **游戏主页面**：分区块展示：
    - 玩家状态栏（境界、HP/MP、经验条、灵石）。
    - 操作按钮（修炼、突破、探索秘境、商店、背包）。
    - 信息输出区（文本日志流）。
    - 当前地图或事件区域（可选，用表格显示地图格子）。
- 前端通过 `fetch` 请求API，根据返回JSON更新DOM。
- 按钮点击后需禁用直到响应完成，避免重复提交。

---

## 五、随机性控制细节

- 所有随机数使用 `random` 模块，在需要重现的情况下（如秘境地图）用固定种子。
- 掉落概率表采用权重方式，放在敌人配置中，例如：
  ```json
  {"item_id": 3, "probability": 0.2, "min_qty":1, "max_qty":1}
  ```
  实现时用 `random() < probability` 判断是否掉落。
- 突破概率需使用玩家当前境界，并确保结果可被测试（可传入固定种子）。

---

## 六、边界条件与错误处理

- 玩家HP/MP不能小于0，不能超过最大值。
- 灵石不能为负。
- 地图移动不能越界（0-4行/列）。
- 当背包满（物品数量达到999），禁止再获得新物品，并提示。
- 战斗时不允许打开背包使用物品（简化规则，可后续扩展）。
- 所有API需处理非法参数（如负数、不存在ID），返回400错误。

---

## 七、开发步骤建议（供AI逐步实现）

请按以下顺序实现功能模块，每完成一个模块进行测试：

1. 数据库模型（所有表）和SQLAlchemy配置。
2. 注册/登录API。
3. 玩家基础属性展示和修炼API。
4. 战斗系统（敌人模型、战斗路由、攻击逻辑）。
5. 背包管理和物品使用。
6. 秘境生成和探索API。
7. NPC商店交易API。
8. 前端页面整合（登录、主界面）。
9. 突破系统整合。
10. 可选：拍卖行API（需要定时任务处理到期）。

---

## 八、代码风格要求

- 使用类型提示（Python3.6+）。
- 所有函数添加docstring。
- 遵循PEP8规范。
- 错误信息用中文或英文均可，但要统一。

---

以上规格可以完整地交给AI助手，让它一步步实现。你还可以根据实际需要调整细节，比如增加技能系统、宗门等，但核心逻辑已覆盖。祝开发顺利！