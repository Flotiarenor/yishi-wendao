"""全库 id 编码规则（唯一权威）。

id = 分类 × 100000 + 序号（分类 10~99 两位，序号 00000~99999 五位）
生成结果恒为 7 位整数：前两位数字 = 分类，后五位 = 内容序号。
例：20×100000+1 = 2000001 → 分类 20、序号 00001。

分类段（10 的倍数，肉眼可辨；10~99 范围可扩展）：
  10 = 地点（坊市 = 1000000，即序号 00000）
  20 = 丹药
  30 = 技能（预留）
  40 = 功法（预留）
  50 = 器物/武器（预留）
  60 = 敌人（预留）
  70/80/90 = 按需新增（宗门/事件/天赋…）
"""
CAT_SITE = 10      # 地点
CAT_PILL = 20      # 丹药
CAT_SKILL = 30     # 技能（预留）
CAT_GONGFA = 40    # 功法（预留）
CAT_ITEM = 50      # 器物（预留）
CAT_ENEMY = 60     # 敌人（预留）

_CAT_NAMES = {
    CAT_SITE: "地点", CAT_PILL: "丹药", CAT_SKILL: "技能",
    CAT_GONGFA: "功法", CAT_ITEM: "器物", CAT_ENEMY: "敌人",
}


def make_id(cat: int, seq: int) -> int:
    """按 分类×100000+序号 生成 id。cat 限 10~99，seq 限 0~99999。"""
    if not 10 <= cat <= 99:
        raise ValueError(f"分类段越界(需10~99): {cat}")
    if not 0 <= seq <= 99999:
        raise ValueError(f"序号越界(需0~99999): {seq}")
    return cat * 100000 + seq


def category_of(eid: int) -> int:
    """从 id 反查分类段（前两位）。"""
    return eid // 100000


def cat_name(eid: int) -> str:
    return _CAT_NAMES.get(category_of(eid), "未知")
