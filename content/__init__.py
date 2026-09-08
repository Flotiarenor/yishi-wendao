"""内容包：所有"实体数据"按类别分文件存放，互相之间只用 id（int）引用。

当前类别（content/ids.py 定义分类段）：
  ids.py    编码规则（唯一权威）
  pills.py  丹药（20 段）
  sites.py  地点（10 段）
  skills.py 技能（30 段，P1 起仅数据）
  gongfa.py 功法（40 段，P1 开放主修位）
将来扩展（每类一个文件，用对应分类段）：
  items.py 器物(50)  enemies.py 敌人(60)

设计规则：
  1. 实体稳定身份 = int id（分类×100000+序号）。name 只是显示名，可随意改。
  2. 类别间引用一律写 id 常量（如 sites 引用 P.ZHUJI），禁止写对方中文名。
  3. 引擎/CLI 从各模块 resolve() 玩家输入 → id；显示时 name_of()。
"""
