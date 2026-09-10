"""引擎核心：一局游戏的完整流程（纯逻辑，不碰 I/O）。

对外暴露：
  - Game(seed, name, load) -> Game
  - Game.step(action, **kw) -> Result  单次玩家操作

动作：
  - "status" 查看状态
  - "cultivate" {days,use_pill} 闭关修炼（可用聚灵丹加速）
  - "comprehend" {gongfa,days} 闭关参悟某功法（P3：投天数 → 熟悉度）
  - "breakthrough" 尝试突破
  - "chronicle" 查看大事记
  - "age_pass" {days} 静养度日
  - "travel" {site} 前往地点   "explore" {site} 探索
  - "travel" {site}（不带 route）= **只看候选路径**（不推进时间、不移动）
  - "travel" {site, route=N} = 执行第 N 条候选（按路径真实耗时结算，P4-T3）
  - "march" {direction} 无舆图**手动探路**（八方向直线推进，遇硬阻挡/水域停下，P4-T3）
  - "debug" {key, amount} 调试发资源（**默认关闭**，见 engine/debug.py；P4-T3）
  - "market" 坊市货单          "buy" {item,qty} 购买（丹药/功法）
  - "use_pill" {item} 服用丹药
  - "learn" {gongfa,slot} 装备功法入运转池槽位  "forget" {slot} 卸下
    （slot：""/"main" 主修位；"battle1".."battleN" 战斗槽；"shenfa" 身法槽）
  - "gongfa_detail" {gongfa or ""} 书库列表 / 单本详情（P3：理解锁分级展示）
  - "battle_action" {cmd,skill_id} 战斗回合指令（战斗中专用）

战斗会话（P2）：
  - Game.start_battle(enemy_id)：构造 Battle 存 self._active_battle（运行时状态，不入存档）
  - Game.battle_action(...)：驱动一回合；战斗结束即结算（胜=掉落/败=重伤/逃=无得，
    另按 used 技能给在池母功法加熟悉度）并清空
  - 探索遇敌：_explore 原"危险折寿"改为遇敌率 → 命中后自动 start_battle

P3 功法深层规则要点：
  - 看懂 = 派生：p.realm_idx >= gf.tier（tier 恒取大境界起点档 1/10/14/18/22）。
  - 熟悉度 0..FAM_MAX 只升不降；来源 = 参悟（cw，days×FAMILIARITY_PER_DAY）+ 战斗使用。
  - 领悟池 owned（无限）vs 运转池（主修1 + 战斗BATTLE_SLOTS + 身法SHENFA_SLOTS）；
    池外功法完全不生效（道基被动例外：习得即永久）。
  - 战斗技能池 = free 独立术法 + 运转池功法已解锁技能（按谱系过滤），见 combat_skills()。

结构化结果契约（P3.5）：
  - 每个 Result 带 ok(True/False/None) + reason(稳定原因码 R_*) + data(结构化负载)。
  - **测试与前端只按 ok/reason/data 判定**；text/lines 仅作叙事渲染（CLI 与 Web 日志流）。
  - 渲染函数（_status_text / _market_text / _gongfa_detail_text）只消费对应 *_data()，不参与判定。
  - 原因码清单见本文件 R_* 常量与 docs/Web架构方案.md §5.2。

内容引用规范：
  - 玩家输入一律经 content.resolve() 转 id；引擎内部只存/比 int id。
  - 显示名只在拼文案时用 name_of() 映射。
  - 背包键、地点字段存 int id（旧档载入时自动迁移）。
"""

import math
from dataclasses import dataclass, field
from typing import Optional

import engine.settings as S
from content import actions as CA
from content import enemies as EM
from content import gongfa as G
from content import intel as IN             # P4-T4B：情报货单（买图 / 买当地情报）
from content import pills as P
from content import regions as R
from content import sites as ST
from content import skills as SK
from engine import battle as BTL
from engine import debug as DBG             # P4-T3：开发期调试开关（默认关）
from engine import worldmap as WM          # P4-T3：世界地图内核（连续坐标 / 代价场 / 寻路）
from engine.clock import LI as LI_PER_SI   # 1 息 = 100 厘息（P4：战斗耗时接回世界轴）
from engine.rng import Rng
from engine.state import GameState, Player, Chronicle

NAME_PREFIX = ["李", "王", "张", "赵", "陈", "林", "苏", "白", "叶", "萧"]
NAME_SUFFIX = ["尘", "玄", "清", "云", "风", "月", "寒", "尘子", "真人", "散人"]
ORIGINS = [
    # (出身名, 修炼效率系数, 寿元系数全程保留)
    ("山村遗孤", 0.85, 0.92),
    ("修仙家族旁支", 1.10, 1.08),
    ("落难宗门弟子", 1.15, 1.05),
    ("边关武将之子", 0.95, 0.98),
    ("药谷采药童", 1.00, 1.02),
]

ELEMENT_DIST = {
    "金": 0.5, "木": 0.5, "水": 0.5, "火": 0.5, "土": 0.5,
}

# 需求谱系中文（展示用）
REQ_LABELS = {"free": "自由", "gentle": "温和", "strict": "严格"}


# ---------- 动作结果原因码（P3.5 结构化契约） ----------
# 测试/前端按 reason 判定成败与原因，**禁止依赖 text 文案**；text 只作叙事渲染。
# 码值即文档：新增码请同步 docs/Web架构方案.md §5.2。
R_OK = "ok"
R_UNKNOWN_ACTION = "unknown_action"
R_UNKNOWN_ITEM = "unknown_item"
R_UNKNOWN_ENEMY = "unknown_enemy"
R_IN_BATTLE = "in_battle"
R_NOT_IN_BATTLE = "not_in_battle"   # P3.6 补漏：§5.2 文档有码但常量缺失 → battle_action 场外必 500
R_GAME_OVER = "game_over"
# 功法/参悟
R_NOT_OWNED = "not_owned"
R_REALM_GATE = "realm_gate"
R_NOT_ENTRY = "not_entry"
R_FAM_MAX = "fam_max"
R_TYPE_MISMATCH = "type_mismatch"
R_SLOT_OCCUPIED = "slot_occupied"
R_SLOT_INVALID = "slot_invalid"
R_SLOT_EMPTY = "slot_empty"
R_ALREADY_EQUIPPED = "already_equipped"
# 交易/物品
R_DUP_OWNED = "dup_owned"
R_NOT_MARKET = "not_market"
R_NOT_AT_MARKET = "not_at_market"
R_NO_STONES = "no_stones"
R_NO_PILL = "no_pill"
R_PILL_USE_WRONG = "pill_use_wrong"
# 突破
R_NOT_BREAKABLE = "not_breakable"
R_MAX_REALM = "max_realm"
R_NO_PILL_DATA = "no_pill_data"
R_MISSING_PILL = "missing_pill"
# 地点
R_SITE_INVALID = "site_invalid"
R_ALREADY_THERE = "already_there"
R_SITE_UNEXPLORABLE = "site_unexplorable"
# 移动（P4-T3，定案 §4）
R_NEED_MAP = "need_map"              # 无舆图：不给目的地寻路，只能手动探路
R_ROUTE_INVALID = "route_invalid"    # 候选序号越界 / 该档位未开放
R_NO_PATH = "no_path"                # 寻路失败（被屏障阻断）
R_MARCH_BLOCKED = "march_blocked"    # 手动探路遇阻停下（硬阻挡 / 水域）
R_DIRECTION_INVALID = "direction_invalid"
# 调试（engine/debug.py；默认关闭）
R_DEBUG_DISABLED = "debug_disabled"  # 未开 --debug 时拒所有 debug 动作
R_DEBUG_KEY = "debug_key"            # 未知的调试项目


@dataclass
class Result:
    """一次操作的返回：**结构化结果 + 叙事文本**。

    结构化字段（P3.5）：
      ok     : True=成功 / False=被拒 / None=信息型动作（status/market/chronicle…）
      reason : 稳定原因码（见上方 R_* 常量）；成功为 R_OK 或 ""
      data   : 结构化负载（前端面板直接消费，勿让 UI 解析 text）
    text/lines 只作叙事渲染（CLI 与 Web 日志流共用），语义判定一律看 ok/reason/data。
    """
    text: str = ""
    lines: list = field(default_factory=list)
    ok: Optional[bool] = None
    reason: str = ""
    data: dict = field(default_factory=dict)
    game_over: bool = False
    died: bool = False
    saved_checkpoint: bool = False
    # 战斗标记（P2）：battle_started=本次操作进入战斗；battle_over=战斗结束的结局
    battle_started: bool = False
    battle_over: str = ""   # win / lose / fled（空=非战斗或战斗未结束）
    # 闭关用附加叙事行（P3.9 起为正式字段，不再动态挂属性）
    pill_line: str = ""


def _reject(r: Result, reason: str, text: str) -> Result:
    """统一的拒绝结果：ok=False + 原因码 + 叙事文案。"""
    r.ok = False
    r.reason = reason
    r.text = text
    return r


def _accept(r: Result, text: str, data: dict = None) -> Result:
    """统一的成功结果：ok=True + 原因码 R_OK + 叙事文案 + 结构化负载。"""
    r.ok = True
    r.reason = R_OK
    r.text = text
    if data:
        r.data = data
    return r


def _loc_name(loc) -> str:
    """地点 id → 显示名。"""
    return ST.name_of(loc) if isinstance(loc, int) else str(loc)


# ============ P4-T3 世界层辅助 ============
# 八方向（与 worldmap._SLOPE_OFFS 同口径：正交 + 对角）
MARCH_DIRS: dict = {
    "东": (1, 0), "东北": (1, 1), "北": (0, 1), "西北": (-1, 1),
    "西": (-1, 0), "西南": (-1, -1), "南": (0, -1), "东南": (1, -1),
}
# 旧地点（content/sites.py）在 `content/regions.LEGACY_ANCHORS` 里的名字
_LEGACY_SITE_ANCHOR = {
    ST.name_of(sid): sid for sid in [ST.SHISHI] + list(ST.SITES)
}
_PROFILE_LABELS = {"fastest": "最快", "safe": "最安全", "stealth": "最隐蔽"}
# 内容点种类 id → 中文名（与 `content/regions.CONTENT_KINDS` 单一来源；T4 迷雾叙事用）
_KIND_NAME = {k: v.get("name", k) for k, v in R.CONTENT_KINDS.items()}


def _legacy_li(a: str, b: str) -> float:
    """两个**旧地点**之间的里程（里，锚点欧氏距离）。

    为什么需要它：`content/sites.py` 的 5 个旧地点有一条**固定连接**语义（互相可达），
    而新世界是连续坐标——若每次旧地点互访都去跑世界寻路，就会为每次挪步付一次
    世界生成（实测 ≈6 s），smoke 20 局直接跑不完。**这是 T3 的过渡桥**：
    旧地点清单在 T5 被城镇设施取代后，函数与调用点一并删除。
    """
    ax, ay = R.LEGACY_ANCHORS.get(a, R.CORE_DOMAIN_CENTER)
    bx, by = R.LEGACY_ANCHORS.get(b, R.CORE_DOMAIN_CENTER)
    return math.hypot(bx - ax, by - ay)


# 越野基线（里/日）：旧地点连接按"无路可循"估算，与定案 §4 「越野基线 22」一致
_OFFROAD_LI_PER_DAY = 22.0


def _as_int(v, default: int = 0) -> int:
    """外部输入 → int（P3.9 加固：Web 壳 kwargs 不可信，坏值不抛异常）。

    非法输入（None/空串/非数字串/字典…）返回 default；float 截断（int(1.5)==1）。
    step() 内所有数值参数一律经此转换，保证"引擎拒绝"永远是结构化 Result，
    而不是把 ValueError 抛到 server 层变成 HTTP 500。
    """
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def understandable(realm_idx: int, tier: int) -> bool:
    """看懂门槛 = 功法 tier 档号（派生判定，不存档）。"""
    return realm_idx >= tier


def cultivation_mult(p: Player) -> float:
    """闭关单日效率 = root_mult × (1 + Σ已习得功法permanent_bonus) × (1 + 主修cultivate_bonus)。

    - Σ 遍历"熟悉度≥FAM_ENTRY 且 permanent_bonus>0"的功法（P3 只有吐纳诀命中）；
    - 主修加成仅当主修位装有功法时生效。
    供 game._cultivate 与 tests/smoke 共用（消除重复实现）。
    """
    perm = sum(
        G.GONGFA[g].permanent_bonus
        for g, f in p.familiarity.items()
        if f >= S.FAM_ENTRY and g in G.GONGFA and G.GONGFA[g].permanent_bonus
    )
    main = 1.0
    if p.main_gongfa is not None and p.main_gongfa in G.GONGFA:
        main = 1 + G.GONGFA[p.main_gongfa].cultivate_bonus
    return p.root_mult * (1 + perm) * main


# ---------- 运转池槽位工具 ----------
def _norm_slot(slot: str):
    """槽位参数归一化 → (kind, idx)。kind: main/battle/shenfa；battle 的 idx 为 0 基。
    无效输入返回 (None, None)。"""
    s = (slot or "main").strip().lower()
    if s in ("", "main", "主修", "主修位"):
        return ("main", None)
    if s in ("shenfa", "s", "身法", "身法槽"):
        return ("shenfa", None)
    num = None
    if s.startswith("battle"):
        num = s[len("battle"):]
    elif s.isdigit():
        num = s
    if num is not None and num.isdigit() and 1 <= int(num) <= S.BATTLE_SLOTS:
        return ("battle", int(num) - 1)
    return (None, None)


def _slot_label(kind: str) -> str:
    """槽位类别 → 玩家可见名（"主修位"/"战斗槽"/"身法槽"）。"""
    if kind == "main":
        return "主修位"
    if kind == "battle":
        return f"战斗槽（1..{S.BATTLE_SLOTS}）"
    return "身法槽"


def _slot_pos_name(kind: str, idx) -> str:
    """具体槽位显示名（含序号）：主修位 / 战斗槽1 / 身法槽。"""
    if kind == "main":
        return "主修位"
    if kind == "battle":
        return f"战斗槽{idx + 1}"
    return "身法槽"


def _slot_get(p: Player, kind: str, idx):
    """读某槽位当前功法 id（空/越界 → None）。"""
    if kind == "main":
        return p.main_gongfa
    if kind == "battle":
        slots = p.battle_gongfa or []
        return slots[idx] if idx < len(slots) else None
    if kind == "shenfa":
        slots = p.shenfa_gongfa or []
        return slots[0] if slots else None
    return None


def _slot_set(p: Player, kind: str, idx, gid):
    """写某槽位（gid=None 表示卸下）。战斗槽用 None 占位保持序号稳定，尾部空槽压缩。"""
    if kind == "main":
        p.main_gongfa = gid
    elif kind == "shenfa":
        p.shenfa_gongfa = [gid] if gid is not None else []
    else:
        slots = list(p.battle_gongfa or [])
        while len(slots) <= idx:
            slots.append(None)
        slots[idx] = gid
        while slots and slots[-1] is None:
            slots.pop()
        p.battle_gongfa = slots


def _slot_of(p: Player, gid: int):
    """功法当前所在槽位显示名；不在运转池返回 None。"""
    if p.main_gongfa == gid:
        return "主修位"
    for i, x in enumerate(p.battle_gongfa or []):
        if x == gid:
            return f"战斗槽{i + 1}"
    if (p.shenfa_gongfa or []) and p.shenfa_gongfa[0] == gid:
        return "身法槽"
    return None


def _pool_gongfas(p: Player) -> list:
    """运转池全部功法 id（主修 → 战斗槽 → 身法槽，去重，含 None 过滤）。"""
    out = []
    for gid in ([p.main_gongfa] + list(p.battle_gongfa or [])
                + list(p.shenfa_gongfa or [])):
        if gid is not None and gid not in out:
            out.append(gid)
    return out


def combat_skills(p: Player) -> list:
    """P3 战斗技能池（重写 P2 的 _battle_skill_pool）：

    1) free 独立术法：恒入池（unlock_fam=0）；kind ∈ attack/defense，
       或 utility 且 effect_key 非空；
    2) 运转池功法（主修 → 战斗槽 → 身法槽，去重）逐本：
       若 realm < tier 或 familiarity < FAM_ENTRY：跳过（保险，正常不会在池）；
       对本功法 skill_ids 每个技能：
         requirement=free → 已在 1) 处理，跳过；
         familiarity < unlock_fam → 跳过（未参悟解锁，不亮）；
         kind 不可战（utility 且无 effect）→ 跳过；
         gentle → 入池（遍历池内每本母功法都会走到，天然满足"任一母功法在池"）；
         strict → 仅当 该 gid 是主修 或 熟悉度 ≥ FAM_MAX（大成）才入池。
    返回按 id 升序去重的技能对象列表。
    """
    out: dict[int, SK.SkillSpec] = {}
    # 1) free 独立术法
    for sk in SK.SKILLS.values():
        if sk.requirement == "free":
            if sk.kind in ("attack", "defense") or (sk.kind == "utility" and sk.effect_key):
                out[sk.id] = sk
    # 2) 运转池功法
    for gid in _pool_gongfas(p):
        gf = G.GONGFA.get(gid)
        if gf is None:
            continue
        fam = p.familiarity.get(gid, 0)
        if p.realm_idx < gf.tier or fam < S.FAM_ENTRY:
            continue  # 保险（learn 已保证在池即看懂且已入门）
        for sid in gf.skill_ids:
            sk = SK.SKILLS.get(sid)
            if sk is None or sk.requirement == "free":
                continue
            if fam < sk.unlock_fam:
                continue  # 未参悟解锁，不亮
            if sk.kind == "utility" and not sk.effect_key:
                continue  # 无战斗效果不入池
            if sk.requirement == "gentle":
                out[sk.id] = sk
            elif sk.requirement == "strict":
                if gid == p.main_gongfa or fam >= S.FAM_MAX:
                    out[sk.id] = sk
    return [out[i] for i in sorted(out)]


def combat_actions(p: Player) -> list:
    """战斗动作池（R3 起战斗层只认 Action）= 基础动作 + 可用技能 + 灵石加速。"""
    from content import actions as CA
    acts = list(CA.BASIC_ACTIONS)          # 平砍/防御/聚气/遁走
    acts += [s.action for s in combat_skills(p)]
    acts += [CA.BUY_QI_LOW, CA.BUY_QI_HIGH]
    seen = {}
    for a in acts:
        seen[a.key] = a
    return list(seen.values())


def _skill_tag(sk) -> str:
    """技能展示串（utility 显示效果名，供战斗开始/菜单用）。"""
    base = f"{sk.element}·{sk.kind}"
    if sk.kind == "utility" and sk.effect_key:
        fx = BTL.UTIL_EFFECT_LABELS.get(sk.effect_key, sk.effect_key)
        base = f"{sk.element}·utility·{fx}"
    return f"{sk.name}（{base}·耗{sk.qi_cost}）"


def _skill_data(sk) -> dict:
    """技能 → 结构化负载（战斗面板/技能列表用）。"""
    t = sk.action.timing
    return {
        "id": sk.id, "key": sk.key, "name": sk.name,
        "element": sk.element, "kind": sk.kind,
        "qi_cost": sk.qi_cost, "power": sk.power,
        "requirement": sk.requirement,
        "unlock_fam": sk.unlock_fam,
        "effect_key": sk.effect_key,
        "windup": t.windup, "recovery": t.recovery,
        "tier": sk.action.tier,
        "label": _skill_tag(sk),
    }


def _new_player(rng: Rng) -> Player:
    p = Player()
    p.name = rng.choice(NAME_PREFIX) + rng.choice(NAME_SUFFIX)
    origin, mult, life = rng.choice(ORIGINS)
    # 灵根资质：偏向天灵根的抽法
    roll = rng.roll()
    if roll < 0.05:
        root_idx = 4  # 天灵根
    elif roll < 0.2:
        root_idx = 3
    elif roll < 0.6:
        root_idx = 2
    elif roll < 0.9:
        root_idx = 1
    else:
        root_idx = 0
    p.spirit_root = S.SPIRIT_ROOT_NAMES[root_idx]
    p.root_mult = S.SPIRIT_ROOT_MULT[root_idx] * mult
    # 五行亲和：主灵根随机一个主属性
    main_el = rng.choice(list(ELEMENT_DIST))
    p.elements = {e: 0.5 for e in S.ELEMENTS}
    p.elements[main_el] = 1.0
    # 寿元 = 档位基准 × 出身系数（出身影响全程保留），年龄 16
    p.lifespan_mult = life
    p.lifespan_years = S.LIFESPAN_PER_REALM[0] * life
    p.age_years = 16.0
    # P3：只赠基础吐纳诀入领悟池，不赠五行主修、不自动装槽（熟悉度 0，走参悟教学链）
    p.owned_gongfa = [G.TUNA_JUE]
    p.familiarity = {}
    return p


class Game:
    def __init__(self, seed: int, name: str = "", load: Optional[dict] = None):
        self.seed = seed
        self.rng = Rng(seed)
        if load is not None:
            # 旧档迁移：先判"存档原文是否含 main_gongfa 键"（None=玩家主动卸下，不再补赠）
            pl = load.get("player") or {}
            had_gongfa = "main_gongfa" in pl
            # P3：旧档（P1/P2）无功法深层字段 → 需把主修功法迁入领悟池/补赠吐纳诀
            legacy_gongfa = not any(
                k in pl for k in ("owned_gongfa", "familiarity",
                                  "battle_gongfa", "shenfa_gongfa")
            )
            self.state = GameState.from_dict(load)
            self.rng.restore(self.state.rng_counter)
            self._migrate_state(had_gongfa=had_gongfa, legacy_gongfa=legacy_gongfa,
                                had_world=("world" in load))
        else:
            self.state = GameState(seed=seed)
            self.state.player = _new_player(self.rng)
            if name:
                self.state.player.name = name
            p = self.state.player
            p.spirit_stones = S.START_SPIRIT_STONES
            # P4-T3：位置真相 = 世界坐标（坊市锚点）；地图档位：开局给粗舆图（定案 §5）。
            # `Player.location` 是**标签**，开局显式置为坊市 id（不做坐标投影，避免建世界）。
            self.state.world = WM.WorldState.legacy(
                int(seed), location=ST.name_of(ST.SHISHI))
            self._set_pos(*R.LEGACY_ANCHORS.get(ST.name_of(ST.SHISHI),
                                                R.CORE_DOMAIN_CENTER))
            p.location = ST.SHISHI
            # 出生地记入 places。**不建世界**：先记锚点名（"坊市"），
            # 首次真正需要显示真实城镇名时由 `place_name()` 懒填充成"青石镇"。
            _bx, _by = self.pos()
            _bcx, _bcy = WM.cell_of(_bx, _by)
            self.state.world.places["place:%d" % (_bcy * WM._N + _bcx)] = ST.name_of(ST.SHISHI)
            # 开局灵气 = 当前境界灵气池上限（否则所有技能都因 low_qi 放不出来）
            p.qi = float(BTL.battle_stats(p.realm_idx)["qi_max"])
            self.state.chronicle.add(
                p.age_years,
                f"生于凡尘，得入仙途，身具【{p.spirit_root}】。",
            )
            self.state.chronicle.add(
                p.age_years,
                f"获赠基础功法【{G.name_of(G.TUNA_JUE)}】。"
                f"闭关参悟（cw N {G.name_of(G.TUNA_JUE)}）至入门后，"
                f"可用 g {G.name_of(G.TUNA_JUE)} 装入主修位。",
            )
        self._checkpoint = None  # 节点回溯快照
        self._active_battle = None  # 战斗会话（运行时状态，不入存档）
        self._route_memo = {}    # (起点,终点,档位,境界,舆图档) → 候选路径（纯缓存，不入存档）
        self._map_memo = {}      # (坐标,舆图档,境界,发现版本,半径) → map_view 结果（纯缓存）
        self._disc_ver = 0       # T4：`discovered` 每变更一次 +1（**不存档**，只作缓存失效用）
        self._intel_bought = set()  # T4-B：已买过情报的位置 (round(x,3), round(y,3))（不存档）
        # 调试：新局自动发资源（只在 `--debug` 时挂上，见 engine/debug.py）
        if DBG.enabled():
            _cfg = DBG.pending()
            if _cfg is not None:
                self.apply_debug(_cfg)

    # ---------- 旧档迁移 ----------
    def _migrate_state(self, had_gongfa: bool = False, legacy_gongfa: bool = False,
                       had_world: bool = False):
        """兼容旧存档：背包键/地点可能存中文名或字符串数字 → 统一为 int id。

        had_gongfa=False 表示存档原文没有 main_gongfa 字段（旧版）。
        legacy_gongfa=True 表示存档原文缺 P3 功法深层字段（P1/P2 旧档）：
          ① 有主修功法 → 迁入领悟池并视为已入门（familiarity=FAM_ENTRY，
             保"在池即已入门"不变量）；
          ② 无主修 → 按吐纳诀补 owned（沿用"无主修则补赠"思路；P3 起补吐纳诀而非五行功法）。
        """
        p = self.state.player
        new_inv: dict = {}
        for key, qty in (p.inventory or {}).items():
            pid = P.resolve(key)
            if pid is None and isinstance(key, str) and key.isdigit():
                pid = int(key)
            if pid is not None:
                new_inv[pid] = new_inv.get(pid, 0) + int(qty)
        p.inventory = new_inv
        # 熟悉度字典：JSON 对象键恒为 str，而引擎内恒用 int 功法 id 键 →
        # 读档后把数字形键归一为 int（同 inventory 的存档往返修复；P3.6 重启续玩暴露）。
        if isinstance(p.familiarity, dict):
            p.familiarity = {
                int(k) if isinstance(k, str) and k.lstrip("-").isdigit() else k: v
                for k, v in p.familiarity.items()
            }
        # 地点：中文名/字符串 → id
        if isinstance(p.location, str):
            lid = ST.resolve(p.location)
            p.location = lid if lid is not None else ST.SHISHI
        elif p.location is None:
            p.location = ST.SHISHI
        # P4-T3 世界层迁移：
        #   ① 存档带 `world` 键 → 坐标为真相；`Player.location` 标签保留存档里的值
        #      （**不做投影**——投影要遍历城镇列表，会触发世界生成，读档不该付这个成本）；
        #   ② 老档（P4-T3 之前无 `world` 键）→ 按旧地点名映射到锚点（WorldState.legacy）。
        if not (had_world and self.state.world.world_seed):
            self.state.world = WM.WorldState.legacy(
                int(self.seed), location=ST.name_of(p.location))
            _lx, _ly = self.pos()
            _lcx, _lcy = WM.cell_of(_lx, _ly)
            self.state.world.places["place:%d" % (_lcy * WM._N + _lcx)] = ST.name_of(p.location)
        # 功法栏（P3）：旧档无新字段 → 主修迁入领悟池 / 无主修补吐纳诀
        if legacy_gongfa:
            old_main = p.main_gongfa
            if old_main is not None and old_main in G.GONGFA:
                if old_main not in p.owned_gongfa:
                    p.owned_gongfa.append(old_main)
                p.familiarity[old_main] = S.FAM_ENTRY
                self.state.chronicle.add(
                    p.age_years,
                    f"整理旧档：主修【{G.name_of(old_main)}】归入领悟池，并视为已入门。",
                )
            else:
                # 无主修（含玩家曾主动卸下）：补赠基础吐纳诀（P3 起补吐纳诀）
                if G.TUNA_JUE not in p.owned_gongfa:
                    p.owned_gongfa.append(G.TUNA_JUE)
                self.state.chronicle.add(
                    p.age_years,
                    f"补赠基础功法【{G.name_of(G.TUNA_JUE)}】。",
                )

    # ---------- 存档快照 ----------
    def snapshot(self) -> dict:
        self.state.rng_counter = self.rng.save()
        return self.state.to_dict()

    def save_checkpoint(self):
        """在当前节点存档（行动前调用）。"""
        self.state.rng_counter = self.rng.save()
        self._checkpoint = GameState.from_dict(self.state.to_dict())

    def load_checkpoint(self) -> bool:
        """回溯到上一节点。"""
        if self._checkpoint is None:
            return False
        self.state = GameState.from_dict(self._checkpoint.to_dict())
        self.rng.restore(self.state.rng_counter)
        self._active_battle = None  # 战斗不跨存档：读档即回战斗前节点
        return True

    # ---------- 工具 ----------
    def _advance_days(self, days: int):
        """推进整数天（世界层动作仍以"天"为输入，内部统一折算为息）。"""
        self._advance_si(int(days) * S.SI_PER_DAY)

    def _advance_si(self, si: int, regen: bool = True):
        """推进时间（息，P4 统一刻度）。年龄仍按**整日**计算（寿元按天/年结算）。

        regen=False：战斗结束后接回世界轴时用——那时灵气已按战斗结果同步，不再重复回灵。
        """
        si = max(0, int(si))
        self.state.t += si
        p = self.state.player
        p.age_years = round(
            self.state.age_days_to_years(self.state.day) + 16.0, 2
        )
        if regen:
            self._regen_qi_si(si)

    def _regen_qi(self, days: int):
        self._regen_qi_si(int(days) * S.SI_PER_DAY)

    def _regen_qi_si(self, si: int):
        """战斗外灵气随时间恢复（按息结算）。

        整日部分仍走 `days × QI_REGEN_PER_DAY`（与 P4 前逐位等价，避免浮点漂移）；
        不足一日的余量按 `SI_PER_SI` 折算——这是"战斗耗时计入世界时间"后的新增能力。
        """
        p = self.state.player
        cap = float(BTL.battle_stats(p.realm_idx)["qi_max"])
        days, rem = divmod(max(0, int(si)), S.SI_PER_DAY)
        gain = days * S.QI_REGEN_PER_DAY + rem * S.QI_REGEN_PER_SI
        p.qi = min(cap, max(0.0, p.qi) + gain)

    def _check_death(self) -> bool:
        p = self.state.player
        if p.age_years >= p.lifespan_years:
            p.alive = False
            p.death_cause = f"寿元耗尽，坐化于{p.realm_name()}（享年{int(p.age_years)}岁）"
            self.state.chronicle.add(p.age_years, "寿元耗尽，道消身陨。")
            return True
        if p.heart_demon >= 100:
            p.alive = False
            p.death_cause = "心魔反噬，走火入魔而亡"
            self.state.chronicle.add(p.age_years, "心魔爆发，走火入魔而亡。")
            return True
        return False

    # ---------- 主循环动作 ----------
    def step(self, action: str, **kw) -> Result:
        r = Result()
        p = self.state.player
        # 身死：只允许查看类动作（P3.9 加固：此前只有 cultivate/breakthrough 自查 alive，
        # 死后仍能 comprehend/explore/age_pass 等——引擎契约与 Web 面板锁不一致）
        if not p.alive and action not in ("status", "chronicle"):
            r.game_over = True
            return _reject(r, R_GAME_OVER, "你已身死道消，本世已终。")
        # 战斗中：只允许战斗指令（status 可查看含战况）
        if self._active_battle is not None and action not in (
                "battle_action", "battle_submit", "battle_skip",
                "battle_unqueue", "battle_clear", "status"):
            b = self._active_battle
            return _reject(
                r, R_IN_BATTLE,
                f"你正与【{b.enemy.name}】激战，只能输入战斗指令"
                f"（battle_submit 入队 / battle_skip 执行）。",
            )
        if action == "status":
            r.ok = True
            r.reason = R_OK
            r.data = self._status_data()
            r.text = self._status_text()
        elif action == "cultivate":
            r = self._cultivate(_as_int(kw.get("days", 30), 30), bool(kw.get("use_pill", False)))
        elif action == "comprehend":
            r = self._comprehend(str(kw.get("gongfa", "")), _as_int(kw.get("days", 30), 30))
        elif action == "breakthrough":
            r = self._breakthrough()
        elif action == "chronicle":
            r.ok = True
            r.reason = R_OK
            r.data = {"entries": [{"age": age, "text": text}
                                  for age, text in self.state.chronicle.entries]}
            r.lines = self._chronicle_text()
        elif action == "age_pass":
            r = self._age_pass(_as_int(kw.get("days", 30), 30))
        elif action == "travel":
            r = self._travel(str(kw.get("site", "")),
                             route=kw.get("route", None),
                             profile=(str(kw.get("profile", "")) or None),
                             x=kw.get("x", None), y=kw.get("y", None))
        elif action == "march":
            r = self._march(str(kw.get("direction", "") or kw.get("dir", "")))
        elif action == "debug":
            r = self._debug(str(kw.get("key", "") or kw.get("grant", "")),
                            _as_int(kw.get("amount", 0), 0))
        elif action == "explore":
            r = self._explore(str(kw.get("site", "")))
        elif action == "buy":
            r = self._buy(str(kw.get("item", "")), _as_int(kw.get("qty", 1), 1))
        elif action == "use_pill":
            r = self._use_pill(str(kw.get("item", "")))
        elif action == "learn":
            r = self._learn(str(kw.get("gongfa", "")), str(kw.get("slot", "main")))
        elif action == "forget":
            r = self._forget(str(kw.get("slot", "main")))
        elif action == "gongfa_detail":
            data = self._gongfa_detail_data(str(kw.get("gongfa", "")))
            if data.get("error"):
                r = _reject(r, data["error"], self._gongfa_detail_text(str(kw.get("gongfa", ""))))
            else:
                r.ok = True
                r.reason = R_OK
                r.data = data
                r.text = self._gongfa_detail_text(str(kw.get("gongfa", "")))
        elif action == "market":
            r = self._market()
        elif action == "battle_submit":
            r = self._battle_submit(str(kw.get("key", "") or kw.get("cmd", "")))
        elif action == "battle_skip":
            r = self._battle_skip()
        elif action == "battle_unqueue":
            r = self._battle_unqueue(kw.get("index", -1))
        elif action == "battle_clear":
            r = self._battle_clear()
        elif action == "battle_action":
            return self._battle_action(str(kw.get("cmd", "")), kw.get("skill_id"))
        else:
            return _reject(r, R_UNKNOWN_ACTION, "未知动作。")
        if action == "status" and self._active_battle is not None:
            r.text += "\n" + self._active_battle.view()
        self.state.turn += 1
        if not r.died and self._check_death():
            r.game_over = True
            r.died = True
            r.text += "\n【道陨】" + self.state.player.death_cause
        return r

    # ---------- 移动/探索/交易 ----------
    # ===== P4-T3：世界层（连续坐标 + 代价场寻路 + 手动探路）=====
    @property
    def wmap(self) -> "WM.WorldMap":
        """本局世界（同 seed 复用；地形/路网/城镇均为纯函数重建）。

        ⚠️ 首次访问会**触发世界生成（实测 ≈6 s）**，故只在真正需要坐标/寻路时才碰它
        （如"同镇内移动"就走 `NEAR_MOVE_*` 快捷路径，不建世界）。
        """
        return WM.WorldMap.get(int(self.state.world.world_seed or self.seed))

    def pos(self) -> tuple:
        """玩家当前世界坐标（里）。"""
        return (float(self.state.world.pos[0]), float(self.state.world.pos[1]))

    def _set_pos(self, x: float, y: float):
        """写回世界坐标（**不动 `Player.location`**，避免为此触发世界生成）。"""
        self.state.world = self.state.world.with_pos(float(x), float(y))

    def _set_pos_arrived(self, x: float, y: float):
        """移动**落地**时写坐标并更新派生标签（地名 + 旧地点 id）。

        为什么只在落地时算：算"这是哪座城镇"要遍历城镇列表（需世界）。
        移动本身已经付过这个成本，落地时多算一次 ≈ 1 ms；若放进 `state_data()`
        就会让**每次状态快照**都触发世界生成（实测把 `/api/new` 拖到 2.8~4 s）。
        结果存进 `WorldState.places`（键 `place:<格序号>`），状态快照 O(1) 读取。

        例外：**旧地点锚点不建世界就直接记名**（坊市/灵脉山/幽谷秘境/古战场遗迹/上古洞府），
        这样"旧地点之间互访"这条快捷路径不会被拖成一次 6 秒世界生成。
        """
        self._set_pos(x, y)
        cx, cy = WM.cell_of(x, y)
        name = None
        for nm in R.LEGACY_ANCHORS:
            ax, ay = R.LEGACY_ANCHORS[nm]
            if math.hypot(ax - x, ay - y) <= 60.0:
                name = nm
                break
        if name is None:
            name = self._place_name(x, y)
        self.state.world.places["place:%d" % (cy * WM._N + cx)] = name
        self._sync_location()

    def place_name(self) -> str:
        """当前位置的显示名（城镇名 / 旧地点名 / 野外）——读缓存，**不建世界**。

        缓存未命中且只落到"野外"时，才去算一次城镇名（需世界，≈1 ms + 首次生成）；
        因为"野外"多半意味着附近真没城镇，也算给下次留个准值。
        旧地点锚点（坊市/灵脉山…）不建世界即可判定，恰好覆盖开局与探索点——故开局零成本。
        """
        x, y = self.pos()
        cx, cy = WM.cell_of(x, y)
        hit = self.state.world.places.get("place:%d" % (cy * WM._N + cx))
        if hit:
            return hit
        for nm in R.LEGACY_ANCHORS:
            ax, ay = R.LEGACY_ANCHORS[nm]
            if math.hypot(ax - x, ay - y) <= 60.0:
                return nm
        t = self._near_town(x, y)
        if t is not None:
            self.state.world.places["place:%d" % (cy * WM._N + cx)] = t.name
            return t.name
        return "野外"

    def _place_name(self, x: float, y: float) -> str:
        """坐标 → 显示名（城镇名优先）。**会触发世界生成，只在落地时调用。**"""
        for nm in R.LEGACY_ANCHORS:
            ax, ay = R.LEGACY_ANCHORS[nm]
            if math.hypot(ax - x, ay - y) <= 60.0:
                return nm
        t = self._near_town(x, y)
        return t.name if t is not None else "野外"

    def at_market(self) -> bool:
        """是否身处坊市（按**到坊市锚点的距离**判定，不依赖世界生成）。

        P3.9 起 `market` 与 `buy` 共用此门槛；T3 把它从"地点 id 相等"改为"坐标距离"，
        因为城内设施坐标是同一世界坐标的小数部分（定案 §6.1）——整座青石镇都算坊市范围。
        """
        x, y = self.pos()
        ax, ay = R.LEGACY_ANCHORS.get(ST.name_of(ST.SHISHI), R.CORE_DOMAIN_CENTER)
        return math.hypot(ax - x, ay - y) <= S.MARKET_RADIUS_LI

    def _near_town(self, x: float, y: float):
        """坐标落在哪个城镇的影响半径内（无则 None）。**会触发世界生成**。"""
        wmap = self.wmap
        for t in wmap.towns:
            if math.hypot(t.x - x, t.y - y) <= wmap.town_radius(t):
                return t
        return None

    def _town_at_or_nearest(self, x: float, y: float):
        """先判"在不在镇内"，否则退到最近城镇（用于位置标签）。"""
        t = self._near_town(x, y)
        if t is not None:
            return t
        best = None
        best_d = float("inf")
        for tw in self.wmap.towns:
            d = (tw.x - x) ** 2 + (tw.y - y) ** 2
            if d < best_d:
                best_d = d
                best = tw
        return best

    def _site_of_pos(self, x: float, y: float) -> int:
        """世界坐标 → 旧地点 id（`Player.location` 的兼容投影）。

        规则（`Player.location` 只是**标签**，位置真相在 `WorldState.pos`）：
        ① 落在旧地点锚点附近（≤60 里）→ 该旧地点 id；
        ② 否则落在**核心域主城**（坊市锚点所在城镇）内 → 坊市（交易面板依赖此 id）；
        ③ 其余 → 最近的旧探索点（仅供显示与旧测试兼容）。
        """
        for name, sid in _LEGACY_SITE_ANCHOR.items():
            ax, ay = R.LEGACY_ANCHORS.get(name, (x, y))
            if math.hypot(ax - x, ay - y) <= 60.0:
                return sid
        t = self._town_at_or_nearest(x, y)
        if t is not None and getattr(t, "is_main", False):
            mx, my = R.LEGACY_ANCHORS.get(ST.name_of(ST.SHISHI), (t.x, t.y))
            if math.hypot(mx - t.x, my - t.y) <= 80.0 + self.wmap.town_radius(t):
                return ST.SHISHI
        # 兜底：最近的旧探索点（保持 int id，前端契约不变）
        best_sid = ST.SHISHI
        best_d = float("inf")
        for name, sid in _LEGACY_SITE_ANCHOR.items():
            ax, ay = R.LEGACY_ANCHORS.get(name, (x, y))
            dd = (ax - x) ** 2 + (ay - y) ** 2
            if dd < best_d:
                best_d = dd
                best_sid = sid
        return best_sid

    def _sync_location(self):
        """把世界坐标投影成 `Player.location`（旧地点 id）。

        方向：`WorldState.pos` 是**位置真相**；`Player.location` 是**派生标签**
        （前端契约 / smoke / 旧测试都用它，故保持 int id 不变）。
        """
        self.state.player.location = self._site_of_pos(*self.pos())

    def _place_label(self, x: float, y: float) -> str:
        """坐标 → 显示名（**会触发世界生成**；日常显示请用 `place_name()`）。"""
        for nm in R.LEGACY_ANCHORS:
            ax, ay = R.LEGACY_ANCHORS[nm]
            if math.hypot(ax - x, ay - y) <= 60.0:
                return nm
        t = self._near_town(x, y)
        return t.name if t is not None else "野外"

    def _dest_pos(self, dest: str):
        """目的地输入 → (名字, x, y)；支持旧地点名与城镇名/id。找不到返回 None。"""
        name = str(dest or "").strip()
        if not name:
            return None
        sid = ST.resolve(name)
        if sid is not None:
            lname = ST.name_of(sid)
            ax, ay = R.LEGACY_ANCHORS.get(lname, R.CORE_DOMAIN_CENTER)
            return (lname, float(ax), float(ay))
        t = self.wmap.town_by_id(name) if name.startswith("town_") else None
        if t is None:
            for tw in self.wmap.towns:
                if tw.name == name:
                    t = tw
                    break
        if t is None:
            return None
        return (t.name, float(t.x), float(t.y))

    def _clamp_target(self, x, y):
        """坐标目的地归一化：解析为 float 并 clamp 到世界边界；非法返回 None。

        防的是"前端点了地图边缘"这类越界点击——`cell_of` 会把越界坐标 clamp 到边界格，
        路径照算，但落点会跑到世界之外，所以在这里先夹住。
        """
        try:
            fx = float(x)
            fy = float(y)
        except (TypeError, ValueError):
            return None
        if math.isnan(fx) or math.isnan(fy):
            return None
        return WM.clamp_xy(fx, fy)

    def _plan_routes(self, dest: str, profile: str = None, limit: int = 1, d=None):
        """规划候选路径（纯查询，不动状态）：返回 (目的地 tuple, [route dict…])。

        `d` = 直接给目的地三元组 `(名字, x, y)`（**坐标目的地**用；给了就不再解析 `dest`）。

        带一层**实例内 memo**：同一 (起点, 终点, 档位, 境界, 舆图档) 只算一次。
        没有它时每次查询都是"建窗口代价场 + A*"（实测单次 0.1~1.2 s，首次还要叠
        世界生成 ≈6 s），而 bot / 前端会反复查同一对起终点。
        """
        if d is None:
            d = self._dest_pos(dest)
        if d is None:
            return None, []
        name, gx, gy = d
        x, y = self.pos()
        realm = self.state.player.realm_idx
        profiles = list(S.TRAVEL_PROFILES[:limit])
        if profile:
            profiles = [profile if profile in S.TRAVEL_PROFILES else "fastest"]
        mkey = (round(x, 3), round(y, 3), round(gx, 3), round(gy, 3),
                tuple(profiles), int(realm), self.state.world.map_level)
        hit = self._route_memo.get(mkey)
        if hit is not None:
            return (name, gx, gy), hit
        out = []
        tid_by_name = {t.name: i for i, t in R.TERRAINS.items()}
        for idx, prof in enumerate(profiles):
            res = self.wmap.find_path((x, y), (gx, gy), profile=prof, realm_idx=realm)
            if res.blocked:
                continue
            road = sum(v for k, v in res.terrain_mix.items() if k in ("官道", "小径"))
            danger = sum(v for k, v in res.terrain_mix.items()
                         if tid_by_name.get(k) is not None
                         and R.TERRAINS[tid_by_name[k]].danger >= 0.5)
            out.append({
                "idx": idx, "profile": prof, "label": _PROFILE_LABELS.get(prof, prof),
                "si": int(res.total_si), "days": round(res.total_si / S.SI_PER_DAY, 1),
                "li": round(res.total_li, 1),
                "terrain_mix": {k: round(v, 4) for k, v in res.terrain_mix.items()},
                "road_share": round(road, 4), "danger_share": round(danger, 4),
                "dest": {"name": name, "x": gx, "y": gy},
            })
        if len(self._route_memo) >= 64:
            self._route_memo.clear()
        self._route_memo[mkey] = out
        return (name, gx, gy), out

    def _travel(self, dest_input: str, route=None, profile: str = None,
                x=None, y=None) -> Result:
        """前往地点 / **指定坐标**：**两段式**（定案 §4.2）。

        - 不带 `route`：只给候选路径（不推进时间、不移动）——无舆图则拒（`need_map`）。
        - 带 `route`：执行选中候选，按路径 `total_si` 推进真实时间。

        **坐标目的地**（T4 附赠：地图上右键"走到那里"）：给 `x`/`y` 时 `dest_input` 留空，
        终点就是该**世界坐标**（里），名字显示为该点附近地名（无城镇则"野外"）。
        与地名目的地共用同一条代价场寻路管线，故**同样需要舆图**——定案 §4.2
        "无舆图只能手动探路、不自动绕行"这条语义不能被右键点击绕过。

        旧地点之间（如坊市 ↔ 灵脉山）走**固定连接**语义：同一聚落内挪动或旧地点互访**不建世界**
        （否则每次挪步都要付一次世界生成，实测 ≈6 s；真实城镇之间的移动才做寻路）。
        """
        r = Result()
        p = self.state.player
        to_point = x is not None or y is not None
        d = self._dest_pos(dest_input) if not to_point else None
        if to_point:
            pt = self._clamp_target(x, y)
            if pt is None:
                return _reject(r, R_SITE_INVALID, "坐标不明：需要 x 与 y（世界坐标，单位里）。")
            d = (self._place_label(*pt), pt[0], pt[1])
        if d is None:
            names = "、".join([ST.name_of(i) for i in [ST.SHISHI] + list(ST.SITES)])
            return _reject(r, R_SITE_INVALID,
                           f"无此地名。可去：{names}；或已探索的城镇名。")
        name, gx, gy = d
        x, y = self.pos()
        tgt_site = ST.resolve(name)
        if to_point and math.hypot(gx - x, gy - y) <= S.NEAR_MOVE_LI:
            # 右键点在脚下附近（同一聚落内挪动，定案：不走世界寻路）。
            # 这一支必须在 `map_level` 门槛**之前**——否则"无舆图连挪两步到村口"都做不到。
            li = math.hypot(gx - x, gy - y)
            si = int(math.ceil(li / _OFFROAD_LI_PER_DAY * S.SI_PER_DAY)) if li > 0 else 0
            if si > 0:
                self._advance_si(si)
            self._set_pos_arrived(gx, gy)
            _seen, _fresh = self.discover_here()
            days = round(si / S.SI_PER_DAY, 1)
            r.data = {"planned": False, "near": True, "to_point": True,
                      "dest": {"name": name, "x": gx, "y": gy},
                      "li": round(li, 1), "si": si, "days": days, "pos": [gx, gy],
                      "newly_discovered": self._fresh_points_data(_fresh, gx, gy),
                      "discovered_total": len(self.state.world.discovered),
                      "location": {"id": p.location, "name": self.place_name()}}
            r.text = (f"近处挪动 {li:.0f} 里，现处【{self.place_name()}】。"
                      if si else "你已在此处。")
            _dt = self._discover_text(_fresh)
            if _dt:
                r.text += "\n" + _dt
            return _accept(r, r.text, r.data)
        if tgt_site is not None:
            cur_site = ST.resolve(_loc_name(p.location))
            if cur_site is not None or math.hypot(gx - x, gy - y) <= S.NEAR_MOVE_LI:
                if cur_site is not None:
                    li = _legacy_li(_loc_name(cur_site), name)
                else:
                    li = math.hypot(gx - x, gy - y)
                si = int(math.ceil(li / _OFFROAD_LI_PER_DAY * S.SI_PER_DAY)) if li > 0 else 0
                if si > 0:
                    self._advance_si(si)
                self._set_pos_arrived(gx, gy)
                p.location = tgt_site
                _seen, _fresh = self.discover_here()
                days = round(si / S.SI_PER_DAY, 1)
                r.data = {"planned": False, "near": True, "legacy_move": True,
                          "dest": {"name": name, "x": gx, "y": gy}, "li": round(li, 1),
                          "si": si, "days": days, "pos": [gx, gy],
                          "newly_discovered": self._fresh_points_data(_fresh, gx, gy),
                          "discovered_total": len(self.state.world.discovered),
                          "location": {"id": tgt_site, "name": _loc_name(tgt_site)}}
                r.text = (f"赶路{days}日，抵达【{name}】。" if si else f"你已在【{name}】。")
                _dt = self._discover_text(_fresh)
                if _dt:
                    r.text += "\n" + _dt
                return _accept(r, r.text, r.data)
        if self.state.world.map_level == "none":
            return _reject(r, R_NEED_MAP,
                           "你手中无舆图，不知路在何方。只能按方向摸索着走"
                           "（march <东/东北/…>）。")
        dest, routes = self._plan_routes(dest_input, profile=profile,
                                         limit=self._route_limit(),
                                         d=None if not to_point else (name, gx, gy))
        if dest is None:
            return _reject(r, R_SITE_INVALID, "无此地名。")
        if not routes:
            if to_point:
                return _reject(r, R_NO_PATH,
                               f"此处（{gx:.0f}, {gy:.0f}）以你如今修为无路可通"
                               f"（绝壁 / 深海 / 禁制所阻），换个去处。")
            return _reject(r, R_NO_PATH,
                           f"以你如今修为，从【{self.place_name()}】到【{name}】"
                           f"无路可通（绝壁 / 深海 / 禁制所阻）。")
        if route is None:
            r.ok = True
            r.reason = R_OK
            r.data = {"planned": True, "dest": {"name": name, "x": gx, "y": gy},
                      "to_point": bool(to_point),
                      "routes": routes, "map_level": self.state.world.map_level}
            r.text = self._routes_text(name, routes)
            return r
        idx = _as_int(route, -1)
        pick = next((q for q in routes if q["idx"] == idx), None)
        if pick is None:
            return _reject(r, R_ROUTE_INVALID,
                           f"候选序号 {idx} 无效（可选："
                           f"{'、'.join(str(q['idx']) for q in routes)}）。")
        self._advance_si(pick["si"])
        self._set_pos_arrived(gx, gy)
        if tgt_site is not None:
            p.location = tgt_site
        # 坐标目的地：`Player.location` 由 `_set_pos_arrived` 里的 `_sync_location()` 派生，
        # 不再一刀切写成坊市（那会让"走到旷野"也显示身处坊市）。
        _seen, _fresh = self.discover_here()
        r.data = {"planned": False, "dest": {"name": name, "x": gx, "y": gy},
                  "to_point": bool(to_point),
                  "route": pick, "si": pick["si"], "days": pick["days"],
                  "li": pick["li"], "pos": [gx, gy],
                  "newly_discovered": self._fresh_points_data(_fresh, gx, gy),
                  "discovered_total": len(self.state.world.discovered),
                  "location": {"id": p.location, "name": self.place_name()}}
        r.text = (f"沿【{pick['label']}】一路而行，{pick['days']} 日"
                  f"（{pick['li']:.0f} 里）抵达【{name}】。")
        _dt = self._discover_text(_fresh)
        if _dt:
            r.text += "\n" + _dt
        self.state.chronicle.add(p.age_years, f"自别处动身，{pick['days']} 日后抵【{name}】。")
        return _accept(r, r.text, r.data)

    # ===== 调试（engine/debug.py；默认关闭，见该模块说明）=====
    def apply_debug(self, cfg=None) -> dict:
        """按调试配置直接发资源（**不进存档逻辑、不改世界**）。返回发了什么。

        典型用法（新局自动发）：`Game(debug_cfg=...)` 或建会话时调用。
        """
        if cfg is None:
            return {}
        p = self.state.player
        granted = {}
        if cfg.stones:
            p.add_stones(int(cfg.stones))
            granted["stones"] = int(cfg.stones)
        for pid, qty in (cfg.pills or {}).items():
            p.add_item(pid, int(qty))
            granted["pills"] = granted.get("pills", 0) + 1
        if cfg.map_level:
            self.state.world.map_level = str(cfg.map_level)
            granted["map_level"] = str(cfg.map_level)
        if cfg.full_fam:
            n = 0
            for gid in list(p.owned_gongfa or []):
                if p.familiarity.get(gid, 0) < S.FAM_MAX:
                    p.familiarity[gid] = S.FAM_MAX
                    n += 1
            granted["fam_set"] = n
        return granted

    def _debug(self, key: str, amount: int = 0) -> Result:
        """调试动作（`step("debug", key=…)`）。**默认关闭 → `debug_disabled`。**"""
        r = Result()
        if not DBG.enabled():
            return _reject(r, R_DEBUG_DISABLED,
                           "调试模式未开启。启动加 --debug，或设 XIUXIAN_DEBUG=1。")
        p = self.state.player
        key = str(key or "").strip().lower()
        if key in ("stones", "stone", "灵石"):
            n = int(amount) if amount else DBG.DEFAULT_STONES
            p.add_stones(n)
            return _accept(r, f"[调试] 灵石 +{n}（现有 {p.spirit_stones}）。",
                           {"debug": True, "key": "stones", "amount": n,
                            "spirit_stones": p.spirit_stones})
        if key in ("pills", "pill", "丹药"):
            from content import pills as _P
            n = int(amount) if amount else 5
            for pid in _P.PILLS:
                p.add_item(pid, n)
            return _accept(r, f"[调试] 每种丹药 +{n}。",
                           {"debug": True, "key": "pills", "amount": n,
                            "kinds": len(_P.PILLS)})
        if key in ("map", "舆图", "map_level"):
            lvl = "detailed" if (amount or 0) != 0 else "coarse"
            self.state.world.map_level = lvl
            return _accept(r, f"[调试] 舆图档 → {lvl}。",
                           {"debug": True, "key": "map", "map_level": lvl})
        if key in ("fam", "熟悉度"):
            n = 0
            for gid in list(p.owned_gongfa or []):
                p.familiarity[gid] = S.FAM_MAX
                n += 1
            return _accept(r, f"[调试] {n} 本功法熟悉度拉满。",
                           {"debug": True, "key": "fam", "count": n})
        if key in ("qi", "灵气"):
            p.qi = float(BTL.battle_stats(p.realm_idx)["qi_max"])
            return _accept(r, f"[调试] 灵气回满（{p.qi:.0f}）。",
                           {"debug": True, "key": "qi", "qi": p.qi})
        return _reject(r, R_DEBUG_KEY,
                       "未知调试项。可用：stones / pills / map / fam / qi。")

    def _vision_tid(self) -> int:
        """玩家所在格的地形 id（用于视野地形遮蔽）。**会触发世界生成。**"""
        cx, cy = WM.cell_of(*self.pos())
        return self.wmap.terrain_at_cell(cx, cy)

    def _in_vision(self, px: float, py: float, x: float, y: float, realm: int) -> bool:
        """内容点是否在神识视野内（半径 × 地形遮蔽，按**玩家所在地形**计，与 data 层一致）。

        ⚠️ T4 起**判定真相收敛到 `WorldMap.visible_points()`**（那个函数才是"视野内有哪些点"的
        唯一实现）。本方法只保留给"单点是否可见"的轻量问法，语义与之等价：
        `visible_points` 用 `_terrain_cell(cx, cy, True)` 取玩家所在地形，而这里用
        `terrain_at_cell(cx, cy)`——后者内部就是 `_terrain_cell(cx, cy, True)`，故两者同值。
        """
        wm = self.wmap
        vis = wm.vision_radius(realm, self._vision_tid())
        return math.hypot(px - x, py - y) <= vis

    # ===== T4 迷雾：内容点发现（`discovered` 的**唯一**写入路径）=====
    _DISCOVER_TEXT_KINDS = ("vein", "secret")   # 典籍里可循迹者：报真名

    def discover_here(self, pos=None) -> tuple:
        """在指定坐标（默认当前位置）做一次**神识踏勘**，把视野内的内容点写进 `discovered`。

        定案 §5：实地层（矿脉/灵草/兽巢/遗迹/秘境入口/小径/驿站）**未知，需揭示**，
        揭示方式之一是**神识半径**（随境界、按地形遮蔽缩减）。
        T4 之前 `discovered` **只有读没有写**（`map_view` 用来判"已知"，却没人往里放东西），
        所以"已知"实际等价于"此刻在视野内"——走过的地方一转身就忘了。
        本方法把那条缺失的写入路径补上：**"走过即知"**。

        语义（**唯一的判据来源**）：`discovered` = 玩家**曾亲身到过的位置**的神识视野内的内容点全集。
        视野判定一律委托 `WorldMap.visible_points()`（不再自己算半径），避免出现第二套口径。

        ⚠️ 会触发世界生成（首次 ≈6 s）——**只在移动落地时调用**，绝不可放进 `state_data()`。

        返回 `((点…), (新发现的点…))`；新发现按 (距离, id) 升序。
        """
        wm = self.wmap
        x, y = self.pos() if pos is None else (float(pos[0]), float(pos[1]))
        realm = int(self.state.player.realm_idx)
        seen = wm.visible_points(x, y, realm)
        disc = self.state.world.discovered
        fresh = tuple(p for p in seen if p.id not in disc)
        if fresh:
            for p in fresh:
                disc.add(p.id)
            # 缓存失效版本号：`discovered` 是**集合**，用 len() 当版本号会在
            # "加一个减一个"时长度相同 → `_map_memo` 静默返回过期的迷雾结果。
            self._disc_ver += 1
        return seen, fresh

    def _discover_text(self, fresh: tuple) -> str:
        """新发现内容点的叙事行（纯文本，供日志流）。"""
        if not fresh:
            return ""
        near, far = fresh[0], fresh[-1]
        d = math.hypot(near.x - self.pos()[0], near.y - self.pos()[1])
        if near.id == far.id:
            head = f"神识扫过，察觉{_KIND_NAME.get(near.kind, near.kind)}【{near.name}】"
        else:
            head = (f"神识扫过，察觉{near.name}（{_KIND_NAME.get(near.kind, near.kind)}）"
                    f"与【{far.name}】（{_KIND_NAME.get(far.kind, far.kind)}）等 "
                    f"{len(fresh)} 处")
        return head + f"（最近约 {d:.0f} 里），已记入舆图。"

    @staticmethod
    def _fresh_points_data(fresh: tuple, x: float, y: float) -> list:
        """新发现内容点的结构化载荷（前端可直接标到图上）。"""
        return [{"id": p.id, "kind": p.kind,
                 "kind_name": _KIND_NAME.get(p.kind, p.kind),
                 "name": p.name, "element": p.element,
                 "x": round(p.x, 1), "y": round(p.y, 1),
                 "dist_li": round(math.hypot(p.x - x, p.y - y), 1)}
                for p in fresh]

    # ===== T4-B 情报买卖（买图 / 买点情报）=====
    def reveal_map_intel(self, x: float, y: float, radius_li: float) -> list:
        """**买来的情报**：把 (x, y) 半径内的内容点写进 `discovered`（返回新揭晓的点）。

        与 `discover_here()` 的区别（两者共用同一份"已发现"真相，只是来源不同）：
          - `discover_here()` = **亲自踏勘**：以**神识视野**（随境界 + 地形遮蔽）为半径；
          - `reveal_map_intel()` = **买来的消息**：以**货单给的半径**为准，
            **不受境界与地形遮蔽限制**（这就是"情报是资源"的意思——弱者也能买到强信息）。
        未探明的内容点**不下发**（不是"给轮廓"，而是连"这里有一处"都不知道）。
        """
        wm = self.wmap
        disc = self.state.world.discovered
        fresh = []
        for p in wm.content_points:
            if p.id in disc:
                continue
            if math.hypot(p.x - float(x), p.y - float(y)) <= float(radius_li):
                disc.add(p.id)
                fresh.append(p)
        if fresh:
            self._disc_ver += 1
        fresh.sort(key=lambda p: (math.hypot(p.x - x, p.y - y), p.id))
        return self._fresh_points_data(tuple(fresh), x, y)

    def _intel_data(self) -> dict:
        """坊市货单里的情报段（只列当前档位下**还值得买**的舆图货 + 点情报）。"""
        lvl = str(self.state.world.map_level or "none")
        out = []
        for it in IN.items_for_level(lvl):
            out.append({
                "id": it.id, "name": it.name, "price": it.price, "kind": it.kind,
                "desc": it.desc,
                "map_level": it.map_level,
                "map_level_label": S.MAP_LEVEL_LABELS.get(it.map_level, "") if it.map_level else "",
                "radius_li": (it.radius_li or S.INTEL_REVEAL_RADIUS_LI)
                if it.kind == "point_intel" else 0.0,
            })
        return {"map_level": lvl, "map_level_label": S.MAP_LEVEL_LABELS.get(lvl, lvl),
                "items": out}

    def _buy_intel(self, iid: str) -> Result:
        """买情报（须身处坊市）：舆图档位 / 当地点情报。"""
        r = Result()
        p = self.state.player
        if not self.at_market():
            return _reject(r, R_NOT_AT_MARKET, "须先前往【坊市】方能购买（travel 坊市）。")
        it = IN.by_id(iid)
        x, y = self.pos()
        if it.kind == "map":
            cur = str(self.state.world.map_level or "none")
            if (cur in S.MAP_LEVEL_ORDER and it.map_level in S.MAP_LEVEL_ORDER
                    and S.MAP_LEVEL_ORDER.index(it.map_level) <= S.MAP_LEVEL_ORDER.index(cur)):
                return _reject(r, R_DUP_OWNED,
                               f"你手中的舆图已经是【{S.MAP_LEVEL_LABELS.get(cur, cur)}】，"
                               f"不必再买【{it.name}】。")
            if p.spirit_stones < it.price:
                return _reject(r, R_NO_STONES,
                               f"灵石不足：需 {it.price}，你有 {p.spirit_stones}。")
            p.spend_stones(it.price)
            self.state.world.map_level = it.map_level
            self._map_memo.clear()          # 档位变了 → 缓存必须失效
            self.state.chronicle.add(p.age_years, f"于坊市购得【{it.name}】。")
            label = S.MAP_LEVEL_LABELS.get(it.map_level, it.map_level)
            return _accept(
                r,
                f"购得【{it.name}】（花费 {it.price} 灵石，余 {p.spirit_stones}）。"
                f"舆图档位 → 【{label}】。{it.desc}",
                {"kind": "intel", "id": it.id, "name": it.name, "intel_kind": it.kind,
                 "unit_price": it.price, "total": it.price,
                 "stones_after": p.spirit_stones,
                 "map_level": it.map_level, "map_level_label": label,
                 "newly_discovered": [], "discovered_total": len(self.state.world.discovered)},
            )
        # 点情报：揭示当前位置周边的内容点
        if p.spirit_stones < it.price:
            return _reject(r, R_NO_STONES,
                           f"灵石不足：需 {it.price}，你有 {p.spirit_stones}。")
        radius = float(it.radius_li or S.INTEL_REVEAL_RADIUS_LI)
        # 「当地情报」卖的是**这一带**的消息：同一处买过就不该再卖
        # （否则第二次是花 600 灵石换一句"附近没什么"——实测踩过）。
        # 判据按世界坐标三位小数取整比较，与地图/寻路的坐标粒度一致。
        spot = (round(x, 3), round(y, 3))
        if spot in self._intel_bought:
            return _reject(r, R_DUP_OWNED,
                           f"这一带的【{it.name}】你已经买过了（商队不会再卖同一份消息）。"
                           f"换个地方再问——走一段路后再买。")
        fresh = self.reveal_map_intel(x, y, radius)
        p.spend_stones(it.price)
        self._intel_bought.add(spot)
        self.state.chronicle.add(p.age_years, f"于坊市购得【{it.name}】。")
        if fresh:
            head = fresh[0]
            tail = f"，另有 {len(fresh) - 1} 处" if len(fresh) > 1 else ""
            body = (f"购得【{it.name}】（花费 {it.price} 灵石，余 {p.spirit_stones}）。"
                    f"商队头领铺开旧图，指认 {radius:.0f} 里内 {len(fresh)} 处虚实："
                    f"{head['kind_name']}【{head['name']}】{tail}——已入舆图。")
        else:
            body = (f"购得【{it.name}】（花费 {it.price} 灵石，余 {p.spirit_stones}）。"
                    f"商队头领摇头：这附近 {radius:.0f} 里内并无什么值得记的东西。")
        return _accept(
            r, body,
            {"kind": "intel", "id": it.id, "name": it.name, "intel_kind": it.kind,
             "unit_price": it.price, "total": it.price,
             "stones_after": p.spirit_stones,
             "radius_li": radius,
             "newly_discovered": fresh, "discovered_total": len(self.state.world.discovered)},
        )

    # ===== 地图信息出口（T4 迷雾的前置；P4-T3 后补：UI 要显示真实地图）=====
    def map_view(self, radius_li: float = None) -> dict:
        """当前位置周边的地图信息（**按舆图档下发**，定案 §5）。

        | 舆图档 | 下发内容 |
        |---|---|
        | `none`   | 只有自身坐标（无舆图 = 两眼一抹黑） |
        | `coarse` | 周边**城镇**（名字 / 方位 / 里程 / 是否曾到过） |
        | `detailed` | 再加**内容点**（视野内 + 已知）与**河流大势** |

        内容点分三档可见性（T4 会把"已知"接成真机制，现在 `discovered` 已就位）：
        ① 神识视野内（随境界，地形遮蔽）；② `world.discovered` 里记着的；③ 其余不给。

        ⚠️ 本方法**会触发世界生成**（首次 ≈6 s），故只在需要时调；结果按
        (坐标, 舆图档, 境界, discovered 版本) 缓存，状态快照不会反复触发。
        """
        lvl = str(self.state.world.map_level or "none")
        x, y = self.pos()
        rad = float(radius_li if radius_li is not None else S.MAP_VIEW_RADIUS_LI)
        realm = int(self.state.player.realm_idx)
        disc = self.state.world.discovered
        # 缓存键用 `_disc_ver`（单调递增），**不用 `len(disc)`**：`discovered` 是集合，
        # 长度在"加一个减一个"时不变 → 会静默返回过期的迷雾结果（T4 踩过）。
        key = (round(x, 1), round(y, 1), lvl, realm, self._disc_ver, rad)
        hit = self._map_memo.get(key)
        if hit is not None:
            return hit
        out = {
            "self": {"x": x, "y": y, "name": self.place_name()},
            "map_level": lvl,
            "radius_li": rad,
            "vision_li": round(self.wmap.vision_radius(realm, self._vision_tid()), 1),
            "towns": [], "points": [], "rivers": [], "counts": {},
        }
        if lvl == "none":
            # 无舆图：只给自身坐标（"两眼一抹黑"，定案 §5）
            out["counts"] = {"towns": 0, "points": 0, "known_points": 0, "rivers": 0}
            self._map_memo.clear()
            self._map_memo[key] = out
            return out
        wm = self.wmap
        _scx, _scy = WM.cell_of(x, y)
        for t in wm.towns:
            d = math.hypot(t.x - x, t.y - y)
            if d > rad:
                continue
            _tcx, _tcy = WM.cell_of(t.x, t.y)
            out["towns"].append({
                "id": t.id, "name": t.name, "x": round(t.x, 1), "y": round(t.y, 1),
                "dist_li": round(d, 1), "is_main": bool(t.is_main),
                "tier": t.tier, "radius_li": round(wm.town_radius(t), 1),
                "visited": ("place:%d" % (_tcy * WM._N + _tcx)) in self.state.world.places,
                "here": (abs(_tcx - _scx) <= 1 and abs(_tcy - _scy) <= 1),
            })
        out["towns"].sort(key=lambda q: (q["dist_li"], q["id"]))
        if lvl == "detailed":
            # 「已知」的唯一口径（T4 拍板）：**此刻神识视野内 ∪ discovered**。
            # 视野判定委托 `WorldMap.visible_points()`——不要在引擎里再算第二套半径。
            vis_ids = {p.id for p in wm.visible_points(x, y, realm)}
            for p in wm.content_points:
                d = math.hypot(p.x - x, p.y - y)
                if d > rad:
                    continue
                known = p.id in disc or p.id in vis_ids
                out["points"].append({
                    "id": p.id, "kind": p.kind, "name": p.name,
                    "element": p.element, "x": round(p.x, 1), "y": round(p.y, 1),
                    "dist_li": round(d, 1), "known": bool(known),
                    # 未知点：只给"有此一处"的轮廓，名字与归属留白（T4 迷雾语义）
                    "known_by": ("discovered" if p.id in disc else
                                 ("vision" if p.id in vis_ids else "")),
                    "name_shown": p.name if known else "（未探明）",
                })
            out["points"].sort(key=lambda q: (not q["known"], q["dist_li"], q["id"]))
            for rv in wm.rivers:
                for (rx, ry) in rv.points[::S.MAP_RIVER_STRIDE]:
                    if math.hypot(rx - x, ry - y) <= rad:
                        out["rivers"].append([round(rx, 1), round(ry, 1)])
        out["counts"] = {"towns": len(out["towns"]), "points": len(out["points"]),
                         "known_points": sum(1 for q in out["points"] if q["known"]),
                         "rivers": len(out["rivers"])}
        self._map_memo.clear()
        self._map_memo[key] = out
        return out

    def _route_limit(self) -> int:
        """按舆图档位决定给几条候选（定案 §5：无舆图 / 粗舆图 / 详图）。"""
        lvl = self.state.world.map_level
        if lvl == "detailed":
            return len(S.TRAVEL_PROFILES)
        return 1

    def _routes_text(self, name: str, routes: list) -> str:
        lines = [f"往【{name}】的路数条，各有取舍："]
        for q in routes:
            lines.append(
                "  [%d] %s：%s 日 / %.0f 里（路网 %.0f%%、险地 %.0f%%）"
                % (q["idx"], q["label"], q["days"], q["li"],
                   q["road_share"] * 100, q["danger_share"] * 100))
        lines.append("选定后 travel <地名> route=<序号>。")
        return "\n".join(lines)

    def _march(self, direction: str) -> Result:
        """手动探路（无舆图）：沿指定方向直线推进，**遇硬阻挡 / 水域停下问玩家**。

        定案 §4.2：不自动寻路、不绕行——玩家自己承担绕行代价，也不额外掷骰惩罚。
        """
        r = Result()
        p = self.state.player
        d = MARCH_DIRS.get(str(direction or "").strip())
        if d is None:
            return _reject(r, R_DIRECTION_INVALID,
                           "方向不明。可用：" + "、".join(MARCH_DIRS.keys()))
        wmap = self.wmap
        step_li = S.WORLD_CELL_LI
        sx, sy = self.pos()
        cx, cy = WM.cell_of(sx, sy)
        # 直线经过的格（Bresenham），跳过起点格
        cells = WM._line_cells((cx, cy), (cx + d[0] * 64, cy + d[1] * 64))[1:]
        diag = (d[0] != 0 and d[1] != 0)
        seg_li = step_li * (math.sqrt(2.0) if diag else 1.0)
        travelled = 0.0
        si = 0.0
        blocked = None
        realm = p.realm_idx
        for (ncx, ncy) in cells:
            if ncx < 0 or ncy < 0 or ncx > WM._N - 1 or ncy > WM._N - 1:
                blocked = "世界边界"
                break
            tid = wmap._terrain_cell(ncx, ncy, True)
            sp = wmap._sample_speed("fastest", tid, realm, 0.0)[0]
            if sp <= 0.0:
                # 硬阻挡 / 不可渡水域：停下来让玩家决定方向（**不自动绕行**，定案 §4.2）
                blocked = R.TERRAINS[tid].name
                break
            travelled += seg_li
            si += seg_li / sp * S.SI_PER_DAY
            if travelled >= S.MARCH_MAX_LI:
                break
        if travelled <= 0.0:
            blocked = blocked or "原地不动"
        # 落位：沿方向推进实际里程（保持连续坐标语义）
        along = math.hypot(d[0], d[1])
        nx = sx + d[0] / along * travelled
        ny = sy + d[1] / along * travelled
        nx, ny = WM.clamp_xy(nx, ny)
        if travelled > 0.0:
            self._advance_si(int(math.ceil(si)))
            self._set_pos_arrived(nx, ny)
        _seen, _fresh = self.discover_here((nx, ny)) if travelled > 0.0 else ((), ())
        label = self.place_name()
        if blocked:
            r.reason = R_MARCH_BLOCKED
            r.ok = False
            r.text = (f"你向【{direction}】摸索 {travelled:.0f} 里"
                      f"（{int(math.ceil(si))} 息），前路被【{blocked}】挡住，只得停步。")
        else:
            r.ok = True
            r.reason = R_OK
            r.text = (f"你向【{direction}】摸索 {travelled:.0f} 里"
                      f"（{int(math.ceil(si))} 息），现处【{label}】。")
        # 无舆图也在**亲身踏勘**——定案 §5 的四种揭示方式之一，故探路同样写 discovered
        _dt = self._discover_text(_fresh)
        if _dt:
            r.text += "\n" + _dt
        r.data = {"direction": direction, "li": round(travelled, 1),
                  "si": int(math.ceil(si)), "blocked": bool(blocked),
                  "blocked_by": blocked or "", "pos": [nx, ny],
                  "newly_discovered": self._fresh_points_data(_fresh, nx, ny),
                  "discovered_total": len(self.state.world.discovered),
                  "place": label, "map_level": self.state.world.map_level}
        return r

    def _explore(self, site_input: str) -> Result:
        """在指定探索点探索一次（耗时 days_cost，可能遇险/得宝/遇敌）。"""
        r = Result()
        p = self.state.player
        site = ST.resolve(site_input.strip())
        if site is None or site == ST.SHISHI:
            names = "、".join(ST.name_of(i) for i in ST.SITES)
            return _reject(r, R_SITE_UNEXPLORABLE, f"此地不可探索。可探索：{names}")
        cfg = ST.by_id(site)
        site_name = cfg.name
        # 境界门槛：不足则危险翻倍、心魔+5
        underlevel = p.realm_idx < cfg.realm_req
        # 先移动到该处（P4-T3：按真实路径耗时结算，不再是固定 3 日）。
        # 走 `_travel` 而不是直接 `_plan_routes`：旧地点之间有固定连接语义，
        # 由 `_travel` 判定并走"不建世界"的快捷路径；只有**真实城镇**才需要寻路。
        move_txt = ""
        move_fresh = []
        if p.location != site:
            mv = self._travel(site_name)
            if mv.ok:
                days = mv.data.get("days", 0)
                if mv.data.get("legacy_move"):
                    move_txt = f"赶路{days}日，抵达【{site_name}】。"
                elif mv.data.get("near"):
                    move_txt = f"在聚落内辗转，抵达【{site_name}】。"
                else:
                    move_txt = (f"赶路{days}日（{mv.data.get('li', 0):.0f} 里）"
                                f"抵达【{site_name}】。")
                move_fresh = list(mv.data.get("newly_discovered") or [])
            else:
                return _reject(r, mv.reason, mv.text)
        else:
            # 已在原地：`_travel` 不会跑，故这里补一次踏勘（探索本身也是"亲身到过"）
            _seen, _f = self.discover_here()
            move_fresh = self._fresh_points_data(_f, *self.pos())
        self._advance_days(cfg.days_cost)
        lo, hi = cfg.stone
        gain = self.rng.randint(lo, hi, f"explore_stone_{site}")
        lines = [move_txt] if move_txt else []
        if move_fresh:
            lines.append(f"（神识所及，新记入舆图 {len(move_fresh)} 处。）")
        pills_gained = []
        if underlevel:
            p.heart_demon = min(100, p.heart_demon + 5)
            lines.append(f"（你的境界不足，深入【{site_name}】心神紧绷，心魔+5）")
        p.add_stones(gain)
        lines.append(f"在【{site_name}】探索{cfg.days_cost}日，收获灵石 {gain} 枚。")
        # 丹药掉落（id → 显示名）
        for pill_id, prob in cfg.pill_drops.items():
            if self.rng.chance(prob, f"explore_pill_{site}_{pill_id}"):
                p.add_item(pill_id)
                pills_gained.append(pill_id)
                lines.append(f"意外寻得【{P.name_of(pill_id)}】×1！")
        data = {
            "site_id": site, "site_name": site_name, "days": cfg.days_cost,
            "stones": gain, "pills": [{"id": pid, "name": P.name_of(pid)}
                                      for pid in pills_gained],
            "underlevel": underlevel, "battle_started": False,
            "enemy_id": None, "enemy_name": None, "lifespan_loss": 0,
            # T4 迷雾：途中神识踏勘新记入舆图的内容点（含终点落地的）
            "newly_discovered": move_fresh,
            "discovered_total": len(self.state.world.discovered),
        }
        # 遇敌判定（P2：替代旧"危险=概率折寿"）：危险命中 → 从该地敌人池抽一只进战斗
        danger = cfg.danger * (2.0 if underlevel else 1.0)
        if self.rng.chance(danger, f"explore_danger_{site}"):
            pool = EM.pool_for(site)
            if pool:
                enemy = self.rng.choice(pool, f"explore_enemy_{site}")
                self.state.chronicle.add(
                    p.age_years, f"探索【{site_name}】时遭遇【{enemy.name}】。"
                )
                rb = self.start_battle(enemy.id)
                r.text = "\n".join(lines) + "\n⚠ 探索途中遇敌！\n" + rb.text
                r.battle_started = True
                data.update({"battle_started": True, "enemy_id": enemy.id,
                             "enemy_name": enemy.name, "battle": self._battle_data()})
                return _accept(r, r.text, data)
            # 兜底（当前四个探索点均有敌人池，正常不走到）：退回旧折寿
            yrs = self.rng.randint(1, 6, "explore_hurt")
            if underlevel:
                yrs *= 2
            p.lifespan_years = max(p.age_years + 3, p.lifespan_years - yrs)
            p.heart_demon = min(100, p.heart_demon + 10)
            data["lifespan_loss"] = yrs
            lines.append(f"⚠ 遭遇凶险，重伤遁走，折寿{yrs}年，心魔+10！")
        self.state.chronicle.add(p.age_years, f"探索【{site_name}】，得灵石{gain}。")
        return _accept(r, "\n".join(lines), data)

    def _market(self) -> Result:
        """坊市货单（须身处坊市）。

        P3.9：货单与购买的地点门槛统一——此前 market 在任何地点都能看到全部货单，
        而 buy 却要求身处坊市，信息面与交易面不一致。现在两者都要求身处坊市。
        T3：门槛由"地点 id 相等"改为 `at_market()`（到坊市锚点的距离）。
        """
        r = Result()
        p = self.state.player
        if not self.at_market():
            return _reject(r, R_NOT_AT_MARKET,
                           f"此处并非坊市（当前在【{self._place_label(*self.pos())}】），"
                           f"看不到货单。前往坊市：travel 坊市。")
        return _accept(r, self._market_text(), self._market_data())

    def _market_data(self) -> dict:
        """坊市货单的结构化数据（未看懂功法只给压缩字段：readable=False）。"""
        p = self.state.player
        pills = [{"id": pill.id, "name": pill.name, "price": pill.price,
                  "kind": pill.kind} for pill in sorted(P.PILLS.values(),
                                                        key=lambda x: x.price)]
        gongfa = []
        for gf in sorted((g for g in G.GONGFA.values() if g.market),
                         key=lambda x: x.price):
            readable = understandable(p.realm_idx, gf.tier)
            gongfa.append({
                "id": gf.id, "name": gf.name, "price": gf.price,
                "element": gf.element, "tier": gf.tier,
                "tier_label": G.TIER_LABELS.get(gf.tier, f"档{gf.tier}"),
                "slot_type": gf.slot_type,
                "slot_label": G.SLOT_LABELS.get(gf.slot_type, gf.slot_type),
                "readable": readable,
                "owned": gf.id in (p.owned_gongfa or []),
                "skill_count": len(gf.skill_ids) if readable else None,
                "cultivate_bonus": gf.cultivate_bonus if readable else None,
                "permanent_bonus": gf.permanent_bonus if readable else None,
                "desc": gf.desc,
            })
        return {"pills": pills, "gongfa": gongfa, "intel": self._intel_data()}

    def _market_text(self) -> str:
        """坊市货单的叙事渲染（数据源 = _market_data）。"""
        d = self._market_data()
        lines = ["━━━ 坊市货单 ━━━", "── 丹药 ──"]
        for pill in d["pills"]:
            if pill["kind"] == "breakthrough":
                lines.append(f"{pill['name']}：{pill['price']} 灵石（突破大境界所需）")
            else:
                lines.append(f"{pill['name']}：{pill['price']} 灵石")
        lines.append("── 功法（购得入领悟池；参悟入门后 g 功法名 可装入运转池）──")
        for gf in d["gongfa"]:
            if gf["readable"]:
                bonus = ""
                if gf["cultivate_bonus"] and gf["cultivate_bonus"] > 0:
                    bonus = f"·主修加成×{1 + gf['cultivate_bonus']:.2f}"
                lines.append(
                    f"{gf['name']}：{gf['price']} 灵石（{gf['element']}系·{gf['tier_label']}"
                    f"·{gf['slot_label']}类·含{gf['skill_count']}门技{bonus}）{gf['desc']}"
                )
            else:
                lines.append(
                    f"{gf['name']}：{gf['price']} 灵石（{gf['tier_label']}·{gf['slot_label']}类）"
                    f"{gf['desc']}（境界未至【{gf['tier_label']}】，详情晦涩）"
                )
        it = d.get("intel") or {}
        if it.get("items"):
            lines.append(f"── 情报（现持【{it.get('map_level_label', '')}】）──")
            for q in it["items"]:
                extra = (f"→【{q['map_level_label']}】" if q["kind"] == "map"
                         else f"（{q['radius_li']:.0f} 里内）")
                lines.append(f"{q['name']}：{q['price']} 灵石{extra} {q['desc']}")
        return "\n".join(lines)

    def _buy(self, item_input: str, qty: int) -> Result:
        r = Result()
        p = self.state.player
        if not self.at_market():
            return _reject(r, R_NOT_AT_MARKET, "须先前往【坊市】方能购买（travel 坊市）。")
        qty = max(1, min(qty, 99))
        # 情报优先（T4-B）：舆图档位 / 当地点情报——id 与中文名都只在本货单内解析，
        # 「粗舆图」这类名字不会与丹药/功法撞车
        iid = IN.resolve(item_input)
        if iid is not None:
            return self._buy_intel(iid)
        # 丹药优先，其次功法（名字不冲突时互不影响）
        pid = P.resolve(item_input.strip())
        if pid is not None:
            pill = P.by_id(pid)
            total = pill.price * qty
            if p.spirit_stones < total:
                return _reject(r, R_NO_STONES,
                               f"灵石不足：需 {total}，你有 {p.spirit_stones}。")
            p.spend_stones(total)
            p.add_item(pid, qty)
            return _accept(
                r, f"购得【{pill.name}】×{qty}，花费 {total} 灵石（余 {p.spirit_stones}）。",
                {"kind": "pill", "id": pid, "name": pill.name, "qty": qty,
                 "unit_price": pill.price, "total": total,
                 "stones_after": p.spirit_stones},
            )
        gid = G.resolve(item_input.strip())
        if gid is None:
            return _reject(r, R_UNKNOWN_ITEM, "坊市无此物。看货单：market")
        gf = G.by_id(gid)
        if not gf.market:
            return _reject(r, R_NOT_MARKET, f"【{gf.name}】不在此坊市售卖。")
        if gid in (p.owned_gongfa or []):
            return _reject(r, R_DUP_OWNED,
                           f"你已拥有【{gf.name}】（在领悟池内），无需重复购买。")
        total = gf.price
        if p.spirit_stones < total:
            return _reject(r, R_NO_STONES,
                           f"灵石不足：需 {total}，你有 {p.spirit_stones}。")
        p.spend_stones(total)
        if gid not in p.owned_gongfa:
            p.owned_gongfa.append(gid)
        self.state.chronicle.add(p.age_years, f"于坊市购得功法【{gf.name}】。")
        # 槽位安装提示
        slot_hint = {
            "main": f"g {gf.name} 装入主修位",
            "battle": f"g {gf.name} 1..{S.BATTLE_SLOTS} 装入战斗槽",
            "shenfa": f"g {gf.name} s 装入身法槽",
        }.get(gf.slot_type, "")
        if not understandable(p.realm_idx, gf.tier):
            note = "（境界未至，暂无法参悟——破境后方可闭关参悟）"
        else:
            note = f"（cw N {gf.name} 参悟入门后，{slot_hint}）"
        return _accept(
            r,
            f"已购得功法【{gf.name}】（花费 {total} 灵石，余 {p.spirit_stones}）。"
            f"已入领悟池。{note}",
            {"kind": "gongfa", "id": gid, "name": gf.name, "qty": 1,
             "unit_price": gf.price, "total": total,
             "stones_after": p.spirit_stones,
             "readable": understandable(p.realm_idx, gf.tier),
             "slot_type": gf.slot_type},
        )

    def _use_pill(self, item_input: str) -> Result:
        r = Result()
        p = self.state.player
        pid = P.resolve(item_input.strip())
        if pid is None:
            return _reject(r, R_UNKNOWN_ITEM, "此物不可直接服用。")
        pill = P.by_id(pid)
        if pill.kind != "other":
            return _reject(r, R_PILL_USE_WRONG,
                           f"【{pill.name}】是突破丹药，须在突破时使用。")
        if not p.remove_item(pid):
            return _reject(r, R_NO_PILL, f"你没有【{pill.name}】。")
        fx = pill.effect
        if "heart_demon" in fx:
            p.heart_demon = max(0, min(100, p.heart_demon + fx["heart_demon"]))
            return _accept(r, f"服用【{pill.name}】，心魔降至 {p.heart_demon}。",
                           {"pill_id": pid, "name": pill.name, "effect": dict(fx),
                            "heart_demon": p.heart_demon})
        if "cultivate_bonus" in fx:
            p.add_item(pid)
            return _accept(r, f"【{pill.name}】无需直接服用，闭关时加参数 p 自动使用。",
                           {"pill_id": pid, "name": pill.name, "effect": dict(fx),
                            "returned": True})
        return _accept(r, f"服用【{pill.name}】，并无特别感受。",
                       {"pill_id": pid, "name": pill.name, "effect": dict(fx)})

    # ---------- 功法栏（learn/forget，P3 支持三槽） ----------
    def _learn(self, gongfa_input: str, slot: str = "main") -> Result:
        """把一本"已拥有+看懂+已入门"的功法装入运转池指定槽位（P3）。

        槽位只能装同 slot_type 的功法；槽被占须先 forget 卸下（保留 P1 交互）。
        """
        r = Result()
        p = self.state.player
        kind, idx = _norm_slot(slot)
        if kind is None:
            return _reject(
                r, R_SLOT_INVALID,
                f"无效槽位：{slot}（可用：main 主修位 / battle1..{S.BATTLE_SLOTS} "
                f"战斗槽 / shenfa 身法槽）。",
            )
        gid = G.resolve(gongfa_input.strip())
        if gid is None:
            return _reject(r, R_UNKNOWN_ITEM, "无此功法。坊市货单：market")
        gf = G.by_id(gid)
        # 校验链：拥有 → 看懂 → 已入门 → 槽类型匹配 → 槽空/同 id
        if gid not in (p.owned_gongfa or []):
            return _reject(r, R_NOT_OWNED,
                           f"你尚未拥有【{gf.name}】（坊市购得后方可参悟与装备）。")
        if not understandable(p.realm_idx, gf.tier):
            return _reject(
                r, R_REALM_GATE,
                f"境界未至，【{gf.name}】书文晦涩如天书，无从参研"
                f"（需{G.TIER_LABELS.get(gf.tier, gf.tier)}方可看懂）。",
            )
        fam = p.familiarity.get(gid, 0)
        if fam < S.FAM_ENTRY:
            return _reject(
                r, R_NOT_ENTRY,
                f"【{gf.name}】尚在参悟中（熟悉度 {fam}/{S.FAM_MAX}，"
                f"未达入门 {S.FAM_ENTRY}）：先闭关参悟 cw N {gf.name}。",
            )
        if gf.slot_type != kind:
            hint = {
                "main": f"主修位（g {gf.name}）",
                "battle": f"战斗槽（g {gf.name} 1..{S.BATTLE_SLOTS}）",
                "shenfa": f"身法槽（g {gf.name} s）",
            }.get(gf.slot_type, "对应槽位")
            return _reject(
                r, R_TYPE_MISMATCH,
                f"【{gf.name}】是{G.SLOT_LABELS.get(gf.slot_type)}类功法，只能装入{hint}。",
            )
        pos = _slot_pos_name(kind, idx)
        cur = _slot_get(p, kind, idx)
        if cur == gid:
            return _reject(r, R_ALREADY_EQUIPPED, f"你已将【{gf.name}】装在{pos}。")
        # 同一功法不得占两个同类型槽
        for other_i in range(S.BATTLE_SLOTS if kind == "battle" else 1):
            other = _slot_get(p, kind, other_i if kind == "battle" else 0)
            if other == gid and other != cur:
                return _reject(r, R_ALREADY_EQUIPPED,
                               f"【{gf.name}】已在{_slot_pos_name(kind, other_i)}，勿重复装入。")
        if cur is not None:
            return _reject(
                r, R_SLOT_OCCUPIED,
                f"{pos}已被【{G.name_of(cur)}】占据：先 forget "
                f"{pos}（gf [槽位]）卸下再换。",
            )
        _slot_set(p, kind, idx, gid)
        self.state.chronicle.add(p.age_years, f"参研【{gf.name}】，装入{pos}。")
        data = {"gongfa_id": gid, "name": gf.name, "slot_kind": kind,
                "slot_index": idx, "slot_label": pos, "main": kind == "main"}
        if kind == "main":
            return _accept(
                r,
                f"你已将【{gf.name}】定为当前主修功法"
                f"（修炼效率加成 ×{1 + gf.cultivate_bonus:.2f}）。",
                data,
            )
        return _accept(r, f"你已将【{gf.name}】装入{pos}（其已解锁技能可入战斗池）。", data)

    def _forget(self, slot: str = "main") -> Result:
        """卸下某槽位功法（主修置 None，其余清槽）。"""
        r = Result()
        p = self.state.player
        kind, idx = _norm_slot(slot)
        if kind is None:
            return _reject(r, R_SLOT_INVALID,
                           f"无效槽位：{slot}（可用：main / battle1..{S.BATTLE_SLOTS} / shenfa）。")
        pos = _slot_pos_name(kind, idx)
        cur = _slot_get(p, kind, idx)
        if cur is None:
            if kind == "main":
                return _reject(r, R_SLOT_EMPTY, "你当前未装备任何主修功法。")
            if kind == "battle":
                return _reject(r, R_SLOT_EMPTY, f"战斗槽{idx + 1}为空，无需卸下。")
            return _reject(r, R_SLOT_EMPTY, "你当前未装备任何身法功法。")
        old_name = G.name_of(cur)
        _slot_set(p, kind, idx, None)
        self.state.chronicle.add(p.age_years, f"放下【{old_name}】，不再占{pos}。")
        data = {"gongfa_id": cur, "name": old_name, "slot_kind": kind,
                "slot_index": idx, "slot_label": pos}
        if kind == "main":
            return _accept(r, f"你卸下了主修【{old_name}】，其主修加成不再生效。", data)
        return _accept(r, f"你卸下了{pos}的【{old_name}】。", data)

    # ---------- 参悟（P3） ----------
    def _comprehend(self, gongfa_input: str, days: int) -> Result:
        """闭关参悟：投真实天数 → 熟悉度上涨（days×FAMILIARITY_PER_DAY，封顶 FAM_MAX）。

        校验：拥有 → 看懂；参悟不要求目标功法曾在槽位；无随机；记编年史。
        """
        r = Result()
        p = self.state.player
        days = max(S.CULTIVATE_MIN_DAYS, min(days, 3650))
        gid = G.resolve(gongfa_input.strip())
        if gid is None:
            return _reject(r, R_UNKNOWN_ITEM, "无此功法。坊市货单：market")
        gf = G.by_id(gid)
        if gid not in (p.owned_gongfa or []):
            return _reject(r, R_NOT_OWNED,
                           f"你尚未拥有【{gf.name}】（坊市购得后方可参悟）。")
        if not understandable(p.realm_idx, gf.tier):
            return _reject(
                r, R_REALM_GATE,
                f"境界未至，【{gf.name}】书文晦涩如天书，无从参悟"
                f"（只识其名——需{G.TIER_LABELS.get(gf.tier, gf.tier)}方可参研）。",
            )
        fam0 = p.familiarity.get(gid, 0)
        if fam0 >= S.FAM_MAX:
            return _reject(r, R_FAM_MAX,
                           f"【{gf.name}】已参悟至大成（{S.FAM_MAX}/{S.FAM_MAX}），无需再参悟。")
        gained = int(round(days * S.FAMILIARITY_PER_DAY))
        fam = min(S.FAM_MAX, fam0 + gained)
        actual = fam - fam0
        p.familiarity[gid] = fam
        self._advance_days(days)
        self.state.chronicle.add(
            p.age_years, f"闭关参悟【{gf.name}】{days}日，熟悉度+{actual}。",
        )
        text = (f"闭关参悟【{gf.name}】{days}日（{days // S.DAYS_PER_YEAR}年"
                f"{days % S.DAYS_PER_YEAR}日），心领神会，熟悉度 +{actual}"
                f"（{fam}/{S.FAM_MAX}）。")
        entered = fam0 < S.FAM_ENTRY <= fam
        if entered:
            text += f"\n参悟入门！【{gf.name}】已可装入运转池（g {gf.name} [槽位]）。"
            if gf.permanent_bonus > 0:
                pct = int(round(gf.permanent_bonus * 100))
                text += f"\n道基受用：修炼效率永久 +{pct}%（不占槽生效）。"
        elif fam >= S.FAM_MAX:
            text += "\n熟悉度已至大成！"
        return _accept(r, text, {
            "gongfa_id": gid, "name": gf.name, "days": days,
            "fam_before": fam0, "fam_after": fam, "gained": actual,
            "entered": entered, "permanent_bonus": gf.permanent_bonus,
            "realm_idx": p.realm_idx,
        })

    # ---------- 书库 / 功法详情（P3 理解锁分级展示） ----------
    def _gongfa_detail_data(self, gongfa_input: str) -> dict:
        """功法详情的结构化数据；未看懂只暴露 名/层级/槽类/来历（信息不对称）。"""
        p = self.state.player
        if not gongfa_input.strip():
            return {"library": [self._owned_entry(g) for g in sorted(p.owned_gongfa or [])
                                if g in G.GONGFA]}
        gid = G.resolve(gongfa_input.strip())
        if gid is None:
            return {"error": R_UNKNOWN_ITEM}
        gf = G.by_id(gid)
        readable = understandable(p.realm_idx, gf.tier)
        data = {
            "id": gid, "name": gf.name, "tier": gf.tier,
            "tier_label": G.TIER_LABELS.get(gf.tier, f"档{gf.tier}"),
            "slot_type": gf.slot_type,
            "slot_label": G.SLOT_LABELS.get(gf.slot_type, gf.slot_type),
            "readable": readable,
            "owned": gid in (p.owned_gongfa or []),
        }
        if not readable:
            data["desc"] = gf.desc
            return data
        fam = p.familiarity.get(gid, 0)
        data.update({
            "element": gf.element, "desc": gf.desc,
            "cultivate_bonus": gf.cultivate_bonus,
            "permanent_bonus": gf.permanent_bonus,
            "familiarity": fam,
            "familiarity_state": "已入门" if fam >= S.FAM_ENTRY else "参悟中",
            "slot": _slot_of(p, gid),
            "skills": [dict(_skill_data(SK.by_id(sid)), lit=fam >= SK.by_id(sid).unlock_fam)
                       for sid in gf.skill_ids if sid in SK.SKILLS],
        })
        return data

    def _gongfa_detail_text(self, gongfa_input: str) -> str:
        """书库/功法详情的叙事渲染（数据源 = _gongfa_detail_data）。"""
        d = self._gongfa_detail_data(gongfa_input)
        if "error" in d:
            return "无此功法。可查：gd（书库列表）"
        if "library" in d:
            lines = ["━━━ 书库 · 领悟池 ━━━"]
            if not d["library"]:
                lines.append("（空——功法自坊市购得或机缘获赠后，于此参悟研读）")
            for o in d["library"]:
                if not o["readable"]:
                    lines.append(f"【{o['name']}】{o['tier_label']}·{o['slot_label']}类 —— "
                                 f"未看懂（境界未至【{o['tier_label']}】），详情晦涩")
                else:
                    loc_txt = f"在{o['slot']}" if o["slot"] else "未入池"
                    lines.append(f"【{o['name']}】{o['tier_label']}·{o['slot_label']}类 —— "
                                 f"熟悉度 {o['familiarity']}/{S.FAM_MAX}"
                                 f"（{o['familiarity_state']}）·{loc_txt}")
            return "\n".join(lines)
        lines = [f"━━━ {d['name']} ━━━",
                 f"层级：{d['tier_label']}（看懂需境界档 {d['tier']}）｜ 类型：{d['slot_label']}类"]
        if not d["readable"]:
            lines.append(f"来历：{d['desc']}")
            lines.append("（境界未至，书文晦涩难明——其余内容如雾里观花。）")
            return "\n".join(lines)
        lines.append(f"五行倾向：{d['element']}｜ 来历：{d['desc']}")
        if d["cultivate_bonus"] > 0:
            lines.append(f"主修修炼加成：×{1 + d['cultivate_bonus']:.2f}")
        elif d["slot_type"] == "main":
            lines.append("主修修炼加成：无（此类功法侧重他途）")
        if d["permanent_bonus"] > 0:
            pct = int(round(d["permanent_bonus"] * 100))
            lines.append(f"道基被动：熟悉度 ≥ {S.FAM_ENTRY}（习得）后，"
                         f"修炼效率永久 +{pct}%，不占槽")
        if d["owned"]:
            loc_txt = f"在{d['slot']}" if d["slot"] else "未入池"
            lines.append(f"拥有状态：已拥有｜熟悉度 {d['familiarity']}/{S.FAM_MAX}"
                         f"（{d['familiarity_state']}）｜{loc_txt}")
        else:
            lines.append("拥有状态：未拥有（坊市购得后可参悟）")
        lines.append("─ 自带技能（熟悉度 ≥ 门槛即亮出；施放还需谱系满足）─")
        for sk in d["skills"]:
            req = REQ_LABELS.get(sk["requirement"], sk["requirement"])
            lock_txt = "已参悟" if sk["lit"] else f"未解锁（需熟悉度 {sk['unlock_fam']}）"
            util_txt = ""
            if sk["kind"] == "utility" and sk["effect_key"]:
                # 效果展示名取自 content.effects 模板 name（经 BTL.UTIL_EFFECT_LABELS）
                fx = BTL.UTIL_EFFECT_LABELS.get(sk["effect_key"], sk["effect_key"])
                util_txt = f"·{fx}"
            lines.append(
                f"・{sk['name']}（{sk['element']}·{sk['kind']}{util_txt}·{req}"
                f"·耗{sk['qi_cost']}）解锁：{lock_txt}"
            )
        return "\n".join(lines)

    # ---------- 闭关修炼 ----------
    def _cultivate(self, days: int, use_pill: bool = False) -> Result:
        """闭关修炼（P4-R7：封顶与聚灵丹统一按"实际闭关天数"结算）。

        设计要点：
          1. **封顶**：先算"刚好圆满需要几天"（**含聚灵丹加速**），请求天数收敛到那一天；
             多余天数不推进、不浪费寿元。
          2. **聚灵丹**：每 `JULING_DAYS_PER_PILL` 天消耗 1 颗，覆盖时段内日率 ×(1+bonus)；
             只按**实际闭关天数**消耗，且受背包数量限制（不够则后半段按基础日率）。
          3. 返回值带 `pill_qty`（实际消耗）/`pill_days`（被加速天数），供 UI 反馈。
        """
        r = Result()
        days = max(S.CULTIVATE_MIN_DAYS, min(days, 3650))
        p = self.state.player
        if not p.alive:
            r.game_over = True
            return _reject(r, R_GAME_OVER, "你已身死道消。")
        mult = cultivation_mult(p)                 # 基础倍率（不含丹药）
        base_rate = S.BASE_DAILY_EXP * mult
        cap = p.exp_cap()
        EPS = 1e-9

        # ---- 已圆满：不推进时间 ----
        if cap - p.exp <= EPS:
            p.exp = float(cap)
            return _accept(
                r,
                f"你已修为圆满（{int(p.exp)}/{cap}），无需再闭关——"
                f"尝试突破：b（突破前先备齐灵石/突破丹）。",
                {"days": 0, "exp_before": p.exp, "exp_gained": 0.0,
                 "exp_after": p.exp, "exp_cap": cap, "full": True,
                 "mult": mult, "main_bonus": 1.0, "perm_bonus": 0.0,
                 "pill_id": None, "pill_qty": 0, "pill_days": 0,
                 "capped": True, "event": None},
            )

        # ---- 聚灵丹：可用颗数 → 加速窗口 ----
        pill = P.by_id(P.JULING)
        pill_bonus = float(pill.effect.get("cultivate_bonus", 0.0))
        avail = p.item_count(P.JULING) if use_pill else 0
        boost_cap_days = avail * S.JULING_DAYS_PER_PILL
        boost_rate = base_rate * (1 + pill_bonus)

        def exp_for(d: int) -> float:
            boosted = min(d, boost_cap_days)
            return boost_rate * boosted + base_rate * (d - boosted)

        # ---- 封顶：收敛到"刚好圆满的那一天"（含丹药） ----
        capped = False
        if base_rate > 0:
            remaining = cap - p.exp
            if boost_cap_days > 0 and boost_rate * boost_cap_days >= remaining:
                need = math.ceil(remaining / boost_rate - EPS)
            else:
                rest = remaining - boost_rate * boost_cap_days
                need = boost_cap_days + (math.ceil(rest / base_rate - EPS) if rest > 0 else 0)
            if need < days:
                days = max(0, need)
                capped = True

        if days <= 0:
            return _accept(
                r,
                f"你已修为圆满（{int(p.exp)}/{cap}），无需再闭关——"
                f"尝试突破：b（突破前先备齐灵石/突破丹）。",
                {"days": 0, "exp_before": p.exp, "exp_gained": 0.0,
                 "exp_after": p.exp, "exp_cap": cap, "full": True,
                 "mult": mult, "main_bonus": 1.0, "perm_bonus": 0.0,
                 "pill_id": None, "pill_qty": 0, "pill_days": 0,
                 "capped": True, "event": None},
            )

        # ---- 扣丹：按实际闭关天数（向上取整，受背包限制） ----
        pill_qty = 0
        pill_days = 0
        if avail > 0:
            pill_qty = min(avail, max(1, math.ceil(days / S.JULING_DAYS_PER_PILL)))
            p.remove_item(P.JULING, pill_qty)
            pill_days = min(days, pill_qty * S.JULING_DAYS_PER_PILL)
            r.pill_line = f"（闭关消耗【{pill.name}】×{pill_qty}，{pill_days} 日修炼加速）"

        # ---- 加成说明 ----
        parts = []
        perm = sorted(
            (g, G.GONGFA[g].permanent_bonus) for g, f in p.familiarity.items()
            if f >= S.FAM_ENTRY and g in G.GONGFA and G.GONGFA[g].permanent_bonus > 0
        )
        for g, b in perm:
            parts.append(f"道基被动【{G.name_of(g)}】×{1 + b:.2f}")
        main_bonus = 1.0
        if p.main_gongfa is not None:
            gf = G.GONGFA.get(p.main_gongfa)
            if gf is not None:
                main_bonus = 1 + gf.cultivate_bonus
                parts.append(f"主修【{gf.name}】×{main_bonus:.2f}")
        if pill_qty:
            parts.append(f"聚灵丹×{pill_qty}（+{int(pill_bonus * 100)}%）")

        # ---- 结算 ----
        exp0 = p.exp
        gained = exp_for(days)
        p.exp += gained
        self._advance_days(days)
        if cap - p.exp <= EPS:
            p.exp = float(cap)          # 浮点吸附：算术已满 → 与 cap 严格相等
        full = p.exp >= cap
        extra = "，修为已圆满可尝试突破" if full else ""
        if capped and not full:
            extra = "（闭关已至圆满之日，多余天数未再推进）"
        # 偶尔的闭关小事件（心魔/顿悟）——先极简
        event = None
        if self.rng.chance(0.05, "seclusion_event"):
            ev = self.rng.choice(
                [
                    ("杂念丛生，修炼事倍功半", -0.3 * gained),
                    ("偶有所悟，修为精进", 0.8 * gained),
                    ("气血翻涌，略有损伤", -10),
                ]
            )
            p.exp = max(0.0, min(float(cap), p.exp + ev[1]))
            event = ev[0]
            self.state.chronicle.add(p.age_years, f"闭关期间{ev[0]}。")
        self.state.chronicle.add(p.age_years, f"闭关{days}日，修为+{int(p.exp - exp0)}。")
        bonus_txt = f"（{'、'.join(parts)}）" if parts else ""
        return _accept(
            r,
            f"闭关{days}日（{days // S.DAYS_PER_YEAR}年{days % S.DAYS_PER_YEAR}日）"
            f"{bonus_txt}，修为 +{int(p.exp - exp0)}，当前 {int(p.exp)}/{cap}{extra}。"
            f"\n年龄 {p.age_years} 岁 / 寿元 {p.lifespan_years} 岁（余 {p.lifespan_left_years()} 岁）。",
            {"days": days, "exp_before": exp0, "exp_gained": p.exp - exp0,
             "exp_after": p.exp, "exp_cap": cap, "full": full, "capped": capped,
             "mult": mult, "main_bonus": main_bonus,
             "perm_bonus": sum(b for _, b in perm),
             "pill_id": P.JULING if pill_qty else None, "pill_qty": pill_qty,
             "pill_days": pill_days, "event": event},
        )

    # ---------- 突破 ----------
    def _breakthrough(self) -> Result:
        r = Result()
        p = self.state.player
        if not p.alive:
            r.game_over = True
            return _reject(r, R_GAME_OVER, "你已身死道消。")
        if p.exp < p.exp_cap():
            return _reject(r, R_NOT_BREAKABLE,
                           f"修为未满（{int(p.exp)}/{p.exp_cap()}），尚不可突破。")
        if p.realm_idx >= S.MAX_REALM:
            return _reject(r, R_MAX_REALM,
                           "你已至化神大圆满、人间顶峰，凡尘再无更高境界可破。")
        cur = p.realm_idx
        major_jump = (cur + 1) in S.MAJOR_REALM_STARTS  # 从大境界末尾跨入下个大境界

        # ---- 灵石/丹药门槛 ----
        stone_cost = S.BREAKTHROUGH_STONE_COST + cur * 2
        if major_jump:
            stone_cost += S.MAJOR_BREAKTHROUGH_STONE_COST
        if p.spirit_stones < stone_cost:
            return _reject(
                r, R_NO_STONES,
                f"突破需 {stone_cost} 灵石护法（你有 {p.spirit_stones}），灵石不足，无法安心冲关。",
            )
        pill = None
        if major_jump:
            pill = P.BREAKTHROUGH_BY_TIER.get(cur + 1)
            if pill is None:
                return _reject(r, R_NO_PILL_DATA,
                               "此境界突破无需丹药（数据未配置对应突破丹）。")
            if p.item_count(pill.id) < 1:
                return _reject(
                    r, R_MISSING_PILL,
                    f"跨越大境界需【{pill.name}】一枚（坊市可购）。无丹强行冲关，十死无生。",
                )
            p.remove_item(pill.id)
        p.spend_stones(stone_cost)

        if major_jump:
            target_major = S.MAJOR_REALM_STARTS.index(cur + 1)  # 目标大境界层次 1..4
            success_p = S.MAJOR_REALM_SUCCESS.get(target_major, 0.3)
        else:
            success_p = S.BASE_BREAKTHROUGH_SUCCESS
        # 丹药加成
        if pill is not None:
            success_p += pill.bonus
        # 心魔拖累
        success_p -= p.heart_demon * S.HEART_DEMON_PENALTY_PER
        success_p = max(0.05, min(0.95, success_p))
        success = self.rng.chance(success_p, f"bt_{cur}")
        old_realm = p.realm_name()
        cost_txt = f"（耗费{stone_cost}灵石" + (f"、{pill.name}" if pill else "") + "）"
        data = {"success": success, "realm_before": cur, "realm_after": cur,
                "stone_cost": stone_cost, "pill_id": pill.id if pill else None,
                "pill_name": pill.name if pill else None,
                "success_p": success_p, "major_jump": major_jump}
        if success:
            p.realm_idx += 1
            p.exp = 0.0
            # 寿元只按"大境界基准增量"补发（P3.9）：此前直接重置为基准×系数，
            # 会把突破失败/战败累积的折寿一次性抹平（破境即回满血），
            # 使"寿元驱动 roguelite"的压力在本世内失效。改为加差额：
            #   新基准 - 旧基准（小境界通常为 0，跨大境界为正），已折损量得以保留。
            new_base = S.LIFESPAN_PER_REALM[p.realm_idx - 1] * p.lifespan_mult
            old_base = S.LIFESPAN_PER_REALM[cur - 1] * p.lifespan_mult
            p.lifespan_years = max(p.age_years + 5.0,
                                   p.lifespan_years + (new_base - old_base))
            new_realm = p.realm_name()
            p.heart_demon = max(0, p.heart_demon - 10)  # 突破成功略压心魔
            data.update({"realm_after": p.realm_idx, "realm_name": new_realm,
                         "lifespan_after": p.lifespan_years,
                         "heart_demon": p.heart_demon})
            if major_jump:
                self.state.chronicle.add(
                    p.age_years,
                    f"跨越大境界，踏入【{new_realm}】！寿元增至{int(p.lifespan_years)}岁。",
                )
                text = f"{cost_txt} 天雷淬体，道基重铸——你成功踏入【{new_realm}】！"
            else:
                self.state.chronicle.add(p.age_years, f"水到渠成，修为晋入【{new_realm}】。")
                text = f"{cost_txt} 瓶颈应声而破，修为晋入【{new_realm}】。"
            if p.realm_idx >= S.MAX_REALM:
                text += "\n【人间顶峰】你已至化神大圆满，凡间再难有敌！"
        else:
            loss = p.exp * S.FAIL_EXP_LOSS_RATIO
            p.exp = max(0.0, p.exp - loss)
            yrs = self.rng.randint(*S.FAIL_LIFESPAN_LOSS, "bt_fail_life")
            if major_jump:
                yrs *= S.MAJOR_FAIL_LIFESPAN_MULT
            p.lifespan_years = max(p.age_years + 5, p.lifespan_years - yrs)
            p.heart_demon = min(100, p.heart_demon + S.FAIL_HEART_DEMON_GAIN)
            data.update({"exp_loss": loss, "lifespan_loss": yrs,
                         "lifespan_after": p.lifespan_years,
                         "heart_demon": p.heart_demon})
            self.state.chronicle.add(
                p.age_years,
                f"突破【{old_realm}】失败！修为跌落，折寿{yrs}年，心魔滋生。",
            )
            text = (
                f"冲击瓶颈失败！灵力反噬：修为跌落{int(loss)}，折寿{yrs}年，"
                f"心魔 +{S.FAIL_HEART_DEMON_GAIN}（当前{p.heart_demon}）。"
            )
        return _accept(r, text, data)

    # ---------- 静养 ----------
    def _age_pass(self, days: int) -> Result:
        r = Result()
        days = max(1, min(days, 3650))
        self._advance_days(days)
        p = self.state.player
        self.state.chronicle.add(p.age_years, f"静养{days}日。")
        return _accept(
            r, f"静养{days}日，无甚大事。年龄 {p.age_years} 岁（余 {p.lifespan_left_years()} 岁）。",
            {"days": days, "age_years": p.age_years,
             "lifespan_left": p.lifespan_left_years()},
        )

    # ---------- 战斗会话（P2/P3）----------
    def battle_active(self) -> bool:
        """是否正处战斗中（战斗会话是否未结束）。"""
        return self._active_battle is not None

    def battle(self):
        """当前战斗对象（None=不在战斗）；供 CLI bot / 测试读取决策信息。"""
        return self._active_battle

    def quit_battle(self) -> bool:
        """直接结束当前战斗（无结算、无奖惩）——玩家主动放弃/中断兜底用（正常走 checkpoint 回溯）。"""
        if self._active_battle is None:
            return False
        self._active_battle = None
        return True

    def _battle_panel(self) -> dict:
        """玩家本场战斗面板：境界档派生 + 玩家当前灵气/灵石（R3）。"""
        p = self.state.player
        ps = BTL.battle_stats(p.realm_idx)
        ps["qi"] = min(p.qi, ps["qi_max"])
        ps["stones"] = p.spirit_stones
        return ps

    def _battle_data(self):
        """当前战斗会话 → 结构化快照（None=不在战斗；前端战斗面板直接消费）。"""
        b = self._active_battle
        if b is None:
            return None
        return b.state()

    def start_battle(self, enemy_id: int) -> Result:
        """构造一场战斗并存入 self._active_battle（运行时状态，不入存档）。

        动作池 = combat_actions()（基础动作 + 可用技能 + 灵石加速）。
        """
        r = Result()
        if self._active_battle is not None:
            return _reject(r, R_IN_BATTLE, "你正身陷战斗，无法再开一场。")
        e = EM.ENEMIES.get(enemy_id)
        if e is None:
            return _reject(r, R_UNKNOWN_ENEMY, "无此敌人。")
        self._battle_seq = getattr(self, "_battle_seq", 0) + 1
        self._active_battle = BTL.Battle(
            player_stats=self._battle_panel(),
            player_actions=combat_actions(self.state.player),
            enemy=e,
            rng=self.rng,
            battle_id=self._battle_seq,
            enemy_actions=list(CA.ENEMY_ACTIONS),
        )
        b = self._active_battle
        acts_txt = " ／ ".join(a["label"] if "label" in a else a["name"]
                              for a in b.available()[:12])
        r.battle_started = True
        return _accept(
            r,
            f"⚠ 遭遇【{e.name}】（{e.element}系·档{e.realm_idx}）！\n"
            f"{b.view()}\n"
            f"决策窗口 {b.window_li() / 100:.1f} 息（敌方下次出手前可安排动作）\n"
            f"可用动作：{acts_txt}",
            {"enemy_id": e.id, "enemy_name": e.name, "enemy_element": e.element,
             "enemy_realm_idx": e.realm_idx, "battle": self._battle_data()},
        )

    # ---------- R3 战斗：入队 / 执行 ----------
    def _battle_submit(self, action_key: str) -> Result:
        """把一个动作排入本轮队列（不推进时间）。"""
        r = Result()
        if self._active_battle is None:
            return _reject(r, R_NOT_IN_BATTLE, "当前不在战斗中。")
        b = self._active_battle
        ok, reason = b.submit(action_key)
        if not ok:
            return _reject(r, reason, f"无法排入【{action_key}】（{reason}）。")
        return _accept(r, f"已排入【{action_key}】。",
                       {"queue": b.state()["queue"], "battle": self._battle_data()})

    def _battle_skip(self) -> Result:
        """执行本轮队列并推进时间轴到玩家下次可动。"""
        r = Result()
        if self._active_battle is None:
            return _reject(r, R_NOT_IN_BATTLE, "当前不在战斗中。")
        return self._battle_advance(r)

    def _battle_unqueue(self, index) -> Result:
        """撤回队列中第 index 个动作（不推进时间轴、不消耗资源）。"""
        r = Result()
        if self._active_battle is None:
            return _reject(r, R_NOT_IN_BATTLE, "当前不在战斗中。")
        b = self._active_battle
        ok, reason = b.unqueue(_as_int(index, -1))
        if not ok:
            return _reject(r, reason, "撤回失败（队列序号无效）。")
        return _accept(r, "已撤回一个动作。",
                       {"queue": b.state()["queue"], "battle": self._battle_data()})

    def _battle_clear(self) -> Result:
        """清空本轮队列（不推进时间轴、不消耗资源）。"""
        r = Result()
        if self._active_battle is None:
            return _reject(r, R_NOT_IN_BATTLE, "当前不在战斗中。")
        b = self._active_battle
        n = len(b.queue)
        b.clear_queue()
        return _accept(r, f"已清空本轮队列（{n} 个动作）。",
                       {"queue": [], "battle": self._battle_data()})

    def _battle_advance(self, r: Result) -> Result:
        """执行窗口 + 结束结算（submit/skip 与兼容别名共用）。"""
        b = self._active_battle
        rep = b.run_window()
        r.text = "\n".join(rep.lines)
        data = {"events": rep.events, "used": sorted(rep.used),
                "interrupted": rep.interrupted,
                "outcome": b.outcome(), "battle": self._battle_data()}
        if b.last_reason and not rep.lines:
            r.ok = False
            r.reason = b.last_reason
        else:
            r.ok = True
            r.reason = R_OK
        # 战斗结束 → 结算
        if b.ended():
            r.battle_over = b.outcome()
            data["battle_si"] = self._finish_battle(b, b.outcome(), r)
            data["battle"] = None
            data["enemy_id"] = b.enemy.id
            data["enemy_name"] = b.enemy.name
        r.data = data
        return r

    def _battle_action(self, cmd: str, skill_id=None) -> Result:
        """兼容入口：`cmd` 为动作键或中文技能名 → 入队并立即执行一轮。"""
        r = Result()
        if self._active_battle is None:
            return _reject(r, R_NOT_IN_BATTLE, "当前不在战斗中。")
        b = self._active_battle
        key = None
        if skill_id is not None:
            sid = SK.resolve(skill_id) if not isinstance(skill_id, int) else skill_id
            if sid is not None and sid in SK.SKILLS:
                key = SK.SKILLS[sid].key
        if key is None:
            key = _resolve_action_key(cmd, b)
        if key is None:
            return _reject(r, R_UNKNOWN_ACTION, f"未知战斗动作：{cmd}")
        ok, reason = b.submit(key)
        if not ok:
            return _reject(r, reason, f"无法施展【{cmd}】（{reason}）。")
        return self._battle_advance(r)

    def _finish_battle(self, b, outcome: str, r: Result):
        """战斗结束的资源结算（胜=掉落 ｜ 败=重伤不致死 ｜ 逃=无得），
        随后按用过的动作给"在运转池的母功法"结算熟悉度成长，最后清空战斗。"""
        p = self.state.player
        e = b.enemy
        tail = []
        # 0) 把战斗内的消耗同步回世界层：**增量扣款**（只扣战斗内花掉的，不整体覆盖），
        #    这样胜负奖励加进来不会被抹掉（P4-R5；b.stones0 = 开战时的灵石）。
        p.qi = max(0.0, min(b.p.qi, BTL.battle_stats(p.realm_idx)["qi_max"]))
        spent = max(0, int(getattr(b, "stones0", p.spirit_stones)) - int(b.p.stones))
        p.spirit_stones = max(0, p.spirit_stones - spent)
        # 0.5) 战斗耗时接回世界时间轴（P4-T1.4）：厘息 → 息（向上取整，最小 1 息）。
        #      灵气已按战斗结果同步，故 regen=False（避免重复回灵）。
        battle_li = int(b.state().get("t", 0) or 0)
        battle_si = max(1, (battle_li + LI_PER_SI - 1) // LI_PER_SI)
        self._advance_si(battle_si, regen=False)
        if outcome == BTL.BATTLE_WIN:
            lo, hi = e.loot_stones
            stones = self.rng.randint(lo, hi, f"battle_loot_stone_{e.id}")
            p.add_stones(stones)
            tail.append(f"【战胜】你斩【{e.name}】于剑下，拾得灵石 {stones} 枚。")
            for pill_id, prob in e.loot_pills.items():
                if self.rng.chance(prob, f"battle_loot_pill_{e.id}_{pill_id}"):
                    p.add_item(pill_id)
                    tail.append(f"战利品中翻出【{P.name_of(pill_id)}】×1！")
            self.state.chronicle.add(
                p.age_years, f"于{ST.name_of(e.site_id)}斩【{e.name}】，得灵石{stones}。"
            )
        elif outcome == BTL.BATTLE_LOSE:
            # 重伤（不致死）：修为减半 + 折寿 1~5 + 心魔（封顶 95，保证不会探索即死）
            p.exp = round(p.exp * 0.5)
            yrs = self.rng.randint(1, 5, f"battle_loss_life_{e.id}")
            p.lifespan_years = max(p.age_years + 5, p.lifespan_years - yrs)
            p.heart_demon = min(95, p.heart_demon + 10)
            self.state.chronicle.add(
                p.age_years,
                f"败于【{e.name}】，重伤遁走，修为折半，折寿{yrs}年，心魔滋生。",
            )
            tail.append(
                f"【战败·重伤】你重伤遁走：修为减半（现 {int(p.exp)}），折寿{yrs}年，"
                f"心魔+10（现 {p.heart_demon}/100）。"
            )
        else:  # 遁走
            self.state.chronicle.add(p.age_years, f"自【{e.name}】爪下遁走，全身而退。")
            tail.append("【遁走】你全身而退，未获分毫。")
        # 战斗使用成长：用过的动作 → 其"在运转池的母功法"熟悉度 +PER_USE
        pool = _pool_gongfas(p)
        for akey in sorted(b.used):
            sk = SK.BY_KEY.get(akey)
            if sk is None:
                continue
            for gid in G.mother_gongfas(sk.id):
                if gid in pool:
                    p.familiarity[gid] = min(
                        S.FAM_MAX, int(p.familiarity.get(gid, 0) + S.FAMILIARITY_PER_USE)
                    )
        self._active_battle = None
        if r.text:
            r.text += "\n" + "\n".join(tail)
        else:
            r.text = "\n".join(tail)
        return battle_si

    # ---------- 显示 ----------
    # ---------- 状态：结构化数据 + 叙事渲染（P3.5 分离） ----------
    def state_data(self) -> dict:
        """只读状态快照（P3.6 Web 壳用）：不推进 turn、不消耗随机流、不落盘。

        与 step("status") 的区别：status 会 turn += 1；本方法纯读，
        供会话层在每次 Web 响应中携带最新状态而不扰动确定性游标。
        """
        return self._status_data()

    def _owned_entry(self, gid: int) -> dict:
        """一本已拥有功法的结构化状态（status 领悟池 / gd 书库共用）。"""
        p = self.state.player
        gf = G.by_id(gid)
        fam = p.familiarity.get(gid, 0)
        return {
            "id": gid, "name": gf.name, "tier": gf.tier,
            "tier_label": G.TIER_LABELS.get(gf.tier, f"档{gf.tier}"),
            "slot_type": gf.slot_type,
            "slot_label": G.SLOT_LABELS.get(gf.slot_type, gf.slot_type),
            "readable": understandable(p.realm_idx, gf.tier),
            "familiarity": fam,
            "familiarity_state": "已入门" if fam >= S.FAM_ENTRY else "参悟中",
            "slot": _slot_of(p, gid),
        }

    def _status_data(self) -> dict:
        """玩家/世界状态的结构化快照（前端面板的唯一数据源）。"""
        p = self.state.player
        main = p.main_gongfa
        main_bonus = (1 + G.by_id(main).cultivate_bonus) if (main and main in G.GONGFA) else None
        shenfa_gid = _slot_get(p, "shenfa", 0)
        return {
            "name": p.name, "spirit_root": p.spirit_root,
            "root_mult": p.root_mult, "cultivation_mult": cultivation_mult(p),
            "elements": dict(p.elements),
            "realm_idx": p.realm_idx, "realm_name": p.realm_name(),
            "exp": p.exp, "exp_cap": p.exp_cap(),
            "age_years": p.age_years, "lifespan_years": p.lifespan_years,
            "lifespan_left": p.lifespan_left_years(),
            "heart_demon": p.heart_demon, "karma": p.karma, "alive": p.alive,
            "spirit_stones": p.spirit_stones,
            "location": {"id": p.location, "name": self.place_name(),
                         "x": self.pos()[0], "y": self.pos()[1],
                         "map_level": self.state.world.map_level},
            "map": self.map_view(),
            "inventory": [{"id": pid, "name": P.name_of(pid), "qty": qty}
                          for pid, qty in p.inventory.items()],
            "pool": {
                "main": {"id": main, "name": G.name_of(main) if main else None,
                         "bonus": main_bonus},
                "battle": [{"id": gid, "name": G.name_of(gid) if gid else None}
                           for gid in (_slot_get(p, "battle", i)
                                       for i in range(S.BATTLE_SLOTS))],
                "shenfa": {"id": shenfa_gid,
                           "name": G.name_of(shenfa_gid) if shenfa_gid else None},
            },
            "owned": [self._owned_entry(g) for g in sorted(p.owned_gongfa or [])
                      if g in G.GONGFA],
            "turn": self.state.turn, "seed": self.seed,
            # P4：统一时间轴（t 为唯一时钟；day 派生保留兼容）
            "t": self.state.t, "day": self.state.day,
            "shichen": S.shichen_of(self.state.t),
            "day_phase": S.day_phase(self.state.t)[0],
            "time_text": S.format_time(self.state.t),
            "battle": self._battle_data(),
        }

    def _status_text(self) -> str:
        """status 的叙事渲染（数据源 = _status_data，本函数不含判定逻辑）。"""
        d = self._status_data()
        p = self.state.player
        el = " ".join(f"{k}{v:g}" for k, v in d["elements"].items())
        inv = "、".join(f"{it['name']}×{it['qty']}" for it in d["inventory"]) or "（空）"
        lines = [
            f"━━━ {d['name']} ━━━",
            f"境界：{d['realm_name']}（第{d['realm_idx']}档）",
            f"修为：{int(d['exp'])} / {d['exp_cap']}",
            f"闭关效率：×{d['cultivation_mult']:.2f}（资质 ×{d['root_mult']:.2f}）",
            f"灵根：{d['spirit_root']}",
            f"亲和：{el}",
            "─ 运转池（池外功法不生效）─",
        ]
        main = d["pool"]["main"]
        if main["id"] is not None and main["bonus"] is not None:
            lines.append(f"主修位：【{main['name']}】（主修加成 ×{main['bonus']:.2f}）")
        else:
            lines.append("主修位：（空）")
        battle_txt = [f"{i + 1}【{s['name'] or '空'}】"
                      for i, s in enumerate(d["pool"]["battle"])]
        lines.append(f"战斗槽：{' '.join(battle_txt)}")
        lines.append(f"身法槽：【{d['pool']['shenfa']['name'] or '空'}】")
        owned = d["owned"]
        lines.append(f"─ 领悟池（已拥有 {len(owned)} 本）─")
        if not owned:
            lines.append("（空——坊市购得功法或获赠后于此参悟）")
        for o in owned:
            if not o["readable"]:
                lines.append(f"・{o['name']}（{o['tier_label']}·{o['slot_label']}类）"
                             f"未看懂（境界未至【{o['tier_label']}】）")
                continue
            loc_txt = f"在{o['slot']}" if o["slot"] else "未入池"
            lines.append(
                f"・{o['name']}（{o['tier_label']}·{o['slot_label']}类）"
                f"熟悉度 {o['familiarity']}/{S.FAM_MAX}·{o['familiarity_state']}·{loc_txt}"
            )
        # 引导提示（开局教学：参悟 → 装备）
        tuna = next((o for o in owned if o["id"] == G.TUNA_JUE), None)
        if main["id"] is None and tuna is not None:
            if p.familiarity.get(G.TUNA_JUE, 0) < S.FAM_ENTRY:
                lines.append(f"提示：cw N {G.name_of(G.TUNA_JUE)} 参悟至入门"
                             f"（熟悉度 {S.FAM_ENTRY}）后，用 g {G.name_of(G.TUNA_JUE)} 装入主修位。")
            else:
                lines.append(f"提示：{G.name_of(G.TUNA_JUE)} 已入门，用 g {G.name_of(G.TUNA_JUE)} "
                             f"装入主修位；也可到坊市（travel 坊市）购更强主修。")
        lines += [
            f"年龄：{d['age_years']} 岁 ｜ 寿元：{d['lifespan_years']} 岁"
            f" ｜ 余年：{d['lifespan_left']} 岁",
            f"心魔：{d['heart_demon']}/100 ｜ 功德/业力：{d['karma']}",
            f"灵石：{d['spirit_stones']} 枚 ｜ 地点：{d['location']['name']}",
            f"背包：{inv}",
            f"世数：第 {d['turn']} 次操作 ｜ 种子：{d['seed']}",
        ]
        return "\n".join(lines)

    def _chronicle_text(self) -> list:
        lines = ["━━━ 本世编年史 ━━━"]
        for age, text in self.state.chronicle.entries:
            lines.append(f"〔{age:6.1f}岁〕{text}")
        if not self.state.chronicle.entries:
            lines.append("（尚无大事）")
        return lines


def _resolve_action_key(cmd: str, battle):
    """把玩家/bot 的指令（动作键/中文名/别名）解析成动作键。"""
    s = (cmd or "").strip()
    if not s:
        return None
    low = s.lower()
    alias = {"attack": "attack", "平砍": "attack", "攻": "attack",
             "defend": "defend", "防御": "defend", "防": "defend",
             "gather": "gather", "聚气": "gather", "聚": "gather",
             "flee": "flee", "遁走": "flee", "逃": "flee"}
    if low in alias:
        return alias[low]
    if s in battle.actions:
        return s
    sid = SK.resolve(s)
    if sid is not None and sid in SK.SKILLS:
        return SK.SKILLS[sid].key
    return None
