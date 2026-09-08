"""机制数值设定集中区：改平衡只动这里，不动代码。

注意：本文件只放"机制/公式参数"（境界表、寿元曲线、成功率、时间……）。
所有"实体数据"（丹药、地点、将来的功法/技能/武器/敌人）在 content/ 包里，
按类别分文件存放、用 id 互相引用——不要在这里新增实体定义。

所有数值均为第一版占位，等可玩原型跑起来后统一标定。
"""

# ---------- 境界刻度：25 档 ----------
# 档号 1..25：练气一层..九层(1-9) + 筑基/金丹/元婴/化神 各 初期/中期/后期/大圆满
QI_BASE = 1  # 练气起始档
QI_LAYERS = 9  # 练气共九层

REALM_NAMES: list[str] = []
for i in range(1, 10):
    REALM_NAMES.append(f"练气·{['一','二','三','四','五','六','七','八','九'][i-1]}层")
for realm in ("筑基", "金丹", "元婴", "化神"):
    for step in ("初期", "中期", "后期", "大圆满"):
        REALM_NAMES.append(f"{realm}·{step}")
# REALM_NAMES[0..24] 即档号 1..25

MAX_REALM = 25  # 化神·大圆满 = 人间顶峰

# 大境界的起始档（用于判断"跨大境界突破"）
MAJOR_REALM_STARTS = [1, 10, 14, 18, 22]  # 练气/筑基/金丹/元婴/化神

# ---------- 寿元（岁），按档号 ----------
# 修仙观感分段：练气百岁内，筑基数百，金丹破千，元婴数千，化神上万（占位）
LIFESPAN_PER_REALM: list[int] = [0] * MAX_REALM  # 下标 = 档号-1
_qi = [70, 74, 78, 82, 86, 90, 94, 98, 105]        # 练气一至九层
_zj = [150, 170, 195, 220]                          # 筑基
_jd = [400, 500, 620, 750]                          # 金丹
_yy = [1200, 1500, 1900, 2400]                      # 元婴
_hs = [3600, 4600, 6000, 8000]                      # 化神
LIFESPAN_PER_REALM = _qi + _zj + _jd + _yy + _hs
assert len(LIFESPAN_PER_REALM) == MAX_REALM

# ---------- 修炼 ----------
# 每档所需修为（占位曲线：越往后越慢）
# 目标节奏：练气数年一档、筑基每阶十数年、金丹每阶数十年、元婴每阶百年、化神每阶数百年
def exp_cap(realm_idx: int) -> int:
    return round(40 * (realm_idx ** 1.9))

# 闭关每天基础修为收益（不随境界涨，靠"更高级功法/环境/灵根"涨；占位）
BASE_DAILY_EXP = 1.0
CULTIVATE_MIN_DAYS = 1  # 一次闭关最少天数（可输入）

# ---------- 突破 ----------
# 小境界内突破成功率
BASE_BREAKTHROUGH_SUCCESS = 0.85
# 跨大境界：成功率随大境界层次递减（练气→筑基 0.60 → … → 元婴→化神 0.25）
# MAJOR_REALM_STARTS = [1,10,14,18,22]，跨界后进入第 k 个大境界(k=1..4)
MAJOR_REALM_SUCCESS = {1: 0.60, 2: 0.45, 3: 0.35, 4: 0.25}
# 失败代价：扣修为比例 / 折寿上下限（岁）
FAIL_EXP_LOSS_RATIO = 0.30
FAIL_LIFESPAN_LOSS = (1, 8)
FAIL_HEART_DEMON_GAIN = 5  # 失败心魔 +5（0-100）
# 大境界失败折寿翻倍
MAJOR_FAIL_LIFESPAN_MULT = 2

# 心魔对突破的影响：心魔值每点扣减成功率
HEART_DEMON_PENALTY_PER = 0.002  # 心魔50 → -0.10

# ---------- 灵根（五行） ----------
ELEMENTS = ["金", "木", "水", "火", "土"]
# 灵根资质 → 修炼效率倍率（占位：生成角色时随机）
SPIRIT_ROOT_NAMES = ["废灵根", "杂灵根", "双灵根", "单灵根(地)", "天灵根"]
SPIRIT_ROOT_MULT = [0.4, 0.7, 1.0, 1.3, 1.8]

# ---------- 时间 ----------
DAYS_PER_YEAR = 360

# ---------- 灵石与经济 ----------
START_SPIRIT_STONES = 50          # 开局灵石
TRAVEL_DAYS = 3                   # 坊市/地点间移动耗时（天）

# 小境界突破耗灵石 = 基准 + 档号系数（随境界上涨，防止无脑冲）
BREAKTHROUGH_STONE_COST = 10
MAJOR_BREAKTHROUGH_STONE_COST = 50  # 大境界突破额外成本（丹药另算，见 content.pills）

# 聚灵丹闭关消耗节奏：每闭关 N 天消耗一颗
JULING_DAYS_PER_PILL = 10

# ---------- 功法深层（P3）：参悟 / 熟悉度 / 运转池槽位 ----------
# 全部为第一版占位数值，可标定。
FAM_MAX = 100              # 熟悉度上限 = 大成
FAM_ENTRY = 10             # ≥此 = 入门：可入运转池 + 道基被动生效
FAMILIARITY_PER_DAY = 2.0  # 闭关参悟每 1 天涨的熟悉度
FAMILIARITY_PER_USE = 1.0  # 战斗中使用该功法技能一次涨的熟悉度
BATTLE_SLOTS = 4           # 运转池·战斗槽
SHENFA_SLOTS = 1           # 运转池·身法槽（设计 1~2，P3 取 1）
