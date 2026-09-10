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

# ---------- 时间（P4：统一到"息"，唯一刻度）----------
# 1 息 = 2 秒（战斗系统定案口径）。世界 / 战斗 / 移动共用这条整数轴。
DAYS_PER_YEAR = 360
DAYS_PER_MONTH = 30
SHICHEN_PER_DAY = 12       # 十二时辰
KE_PER_SHICHEN = 8         # 1 时辰 = 8 刻
SI_PER_KE = 450            # 1 刻 = 15 分
SI_PER_SHICHEN = 3600      # 1 时辰 = 2 小时 = 8 刻
SI_PER_DAY = 43200         # 1 日 = 12 时辰 = 96 刻
SI_PER_YEAR = SI_PER_DAY * DAYS_PER_YEAR

SHICHEN_NAMES = ("子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥")

# 昼夜五行段（设计定案 §六 威力层）：(段名, 时辰索引, 主五行)
# 子=0 丑=1 寅=2 卯=3 辰=4 巳=5 午=6 未=7 申=8 酉=9 戌=10 亥=11
DAY_PHASES = (
    ("夜半", (11, 0, 1), "水"),    # 亥子丑
    ("平旦", (2, 3, 4), "木"),     # 寅卯辰
    ("日中", (5, 6, 7), "火"),     # 巳午未（午时最盛）
    ("日入", (8, 9, 10), "金"),    # 申酉戌
)
# 土旺四季：辰/未/戌/丑 额外叠土
EARTH_SHICHEN = (1, 4, 7, 10)

_CN_DIGITS = "零一二三四五六七八九"


def _cn_num(n: int) -> str:
    """1..9999 的中文数字（用于古风时间显示）。"""
    n = int(n)
    if n <= 0:
        return _CN_DIGITS[0]
    if n < 10:
        return _CN_DIGITS[n]
    if n < 20:
        return "十" + (_CN_DIGITS[n % 10] if n % 10 else "")
    if n < 100:
        return _CN_DIGITS[n // 10] + "十" + (_CN_DIGITS[n % 10] if n % 10 else "")
    if n < 1000:
        s = _CN_DIGITS[n // 100] + "百"
        rem = n % 100
        if rem == 0:
            return s
        if rem < 10:
            return s + "零" + _CN_DIGITS[rem]
        return s + _cn_num(rem)
    s = _CN_DIGITS[n // 1000] + "千"
    rem = n % 1000
    if rem == 0:
        return s
    if rem < 100:
        return s + "零" + _cn_num(rem)
    return s + _cn_num(rem)


def day_of(t: int) -> int:
    """自开局起的第几日（0 起）。"""
    return int(t) // SI_PER_DAY


def shichen_index(t: int) -> int:
    """0=子 … 11=亥。"""
    return (int(t) % SI_PER_DAY) // SI_PER_SHICHEN


def shichen_of(t: int) -> str:
    return SHICHEN_NAMES[shichen_index(t)]


def day_phase(t: int) -> tuple:
    """返回 (段名, 主五行, 叠加五行或 "")。土旺四季在辰/未/戌/丑 叠加。"""
    idx = shichen_index(t)
    for name, hours, elem in DAY_PHASES:
        if idx in hours:
            return name, elem, ("土" if idx in EARTH_SHICHEN else "")
    return "平旦", "木", ""


def format_time(t: int) -> str:
    """古风时间串，如「第三日 · 午时」。"""
    return f"第{_cn_num(day_of(t) + 1)}日 · {shichen_of(t)}时"


# ---------- 灵石与经济 ----------
START_SPIRIT_STONES = 50          # 开局灵石
# ⚠️ TRAVEL_DAYS 已**退役**（P4-T3）：移动耗时改按路径积分真实结算（`PathResult.total_si`）。
# 常量仅保留给"无舆图手动探路"的单步上限之外的旧调用点兼容，**移动逻辑不得再读它**。
TRAVEL_DAYS = 3

# ---------- 移动（P4-T3，定案 §4）----------
MARCH_MAX_LI = 300.0              # 手动探路单次推进上限（里）：≈ 越野 14 日 / 沿路 7 日
TRAVEL_PROFILES = ("fastest", "safe", "stealth")   # 候选路径档位（详图给全 3 档，粗舆图只给首个）
NEAR_MOVE_LI = 60.0               # 近距移动阈值（里）：同一聚落内挪动不走世界寻路
NEAR_MOVE_DAYS = 0.5              # 近距移动耗时（日）——同一聚落内挪动，**不建世界**
MARKET_RADIUS_LI = 120.0          # 坊市判定半径（里）：距坊市锚点在此内即算"身处坊市"

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

# ---------- R3 时间轴战斗：灵气（定案 §5 / §11.1） ----------
# 战斗内回灵 1/息（1 息 = 2 秒）。战斗外恢复显著更慢（P4-T1.5 重标）：
# 每日恢复量固定为 60，换算成"每息"即 60 / 43200 —— 与旧口径等价，但支持亚日推进。
QI_REGEN_PER_DAY = 60.0                            # 战斗外每日灵气恢复量（占位）
QI_REGEN_PER_SI = QI_REGEN_PER_DAY / SI_PER_DAY    # ≈ 0.0013889 / 息

# ---------- P4-T2 世界地图（机制常量；地形/域数据在 content/regions.py）----------
WORLD_LI = 20000.0          # 世界跨度（里），见方
DOMAIN_GRID = 5             # 5×5 = 25 域
DOMAIN_LI = 4000.0          # 每域边长（里）
WORLD_CELL_LI = 50.0        # 内部生成栅格（里）——"格"只是加速结构，不是设计概念（2026-09-10：100→50）
WORLD_CELLS = 400           # 每轴格数 = WORLD_LI / WORLD_CELL_LI
ROAD_PLAN_MULT = 1          # 路网规划的**搜索栅格步长**（单位 = 格 = 50 里）：只影响建路 A* 的速度与
                            # 走线拐点密度（调粗 → 拐点变稀 → 路看着更直、规划更快），
                            # **不影响路面宽度**——路宽/判定容差是几何量（见 worldmap._ROAD_WIDTH / _ROAD_TOL）。

REALM_SPEED_MULT = (1.0, 1.5, 2.5, 4.0, 6.0)   # 练气/筑基/金丹/元婴/化神（定案 §4.1）
FLY_SPEED_LI_PER_DAY = 250.0                   # 飞行速度（定案 §4.3）
FLY_MIN_REALM = 14                             # 金丹·初期起可飞
SWIM_MIN_REALM = 10                            # 筑基·初期起可渡水
VISION_RADIUS_LI = (60.0, 150.0, 400.0, 1000.0, 2500.0)   # 神识半径：练气/筑基/金丹/元婴/化神（定案原值）
# 注：**不再要求** ≥ WORLD_CELL_LI——地形已连续采样，迷雾遮的是"内容点"而非"格"（2026-09-10 修正）
MAP_LEVELS = ("none", "coarse", "detail")      # 无舆图 / 粗舆图 / 详图（T4 用）
WORLD_CACHE_SIZE = 4                           # WorldMap 实例缓存条数（同种子复用）


def major_realm_of(realm_idx: int) -> int:
    """档号 1..25 → 大境界下标 0..4（1-9 练气、10-13 筑基、14-17 金丹、18-21 元婴、22-25 化神）。"""
    r = int(realm_idx)
    if r < 1:
        r = 1
    elif r > MAX_REALM:
        r = MAX_REALM
    for i in range(len(MAJOR_REALM_STARTS) - 1, -1, -1):
        if r >= MAJOR_REALM_STARTS[i]:
            return i
    return 0


def realm_speed_mult(realm_idx: int) -> float:
    """境界速度系数（里/日 的乘区）：练气 1.0 → 化神 6.0。"""
    return REALM_SPEED_MULT[major_realm_of(realm_idx)]


def vision_radius_li(realm_idx: int) -> float:
    """神识半径（里）：练气 60 → 化神 2500。"""
    return VISION_RADIUS_LI[major_realm_of(realm_idx)]
