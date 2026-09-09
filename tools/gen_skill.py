"""技能生成器：手写 / AI 起草 / 随机生成 三条路共用的技能数据入口。

为什么要有它
------------
技能数据此前有两个来源：`content/skills.py`（正式 21 技能，SkillSpec）与
`content/actions.py`（R2 demo 动作）。两条路各写各的、字段默认值不一致，且都没有
"先校验再落地"的关卡。本工具把技能统一成一份 **draft（JSON 友好）**：

    draft ──校验──> build_skill() ──> SkillSpec（引擎可直接跑）
             │
             ├── emit_code()  → 可直接粘进 content/skills.py 的 `_sk(...)` 行
             └── emit_json()  → 规范化 JSON（AI/生成器/存档互换）

**AI 生成也走这条路**：让模型只产出 draft JSON（字段级约束写在本文档里），
再用 `--strict` 校验、`--emit code` 落地。模型不需要知道 `_sk` 签名与引擎内部结构。

**为随机生成铺垫**：`--random N --seed S` 用模板 + 约束表填 draft，再走同一套校验；
后续 P9 生成器只需替换"填 draft"的策略，校验/落地链路不变。

draft 字段（JSON）
------------------
  id            整数（30 段）；省略 = 自动分配下一个空位
  name          显示名（必填，建议不与现有技能重名）
  element       金/木/水/火/土/无
  kind          attack/defense/utility
  requirement   free（独立术法）/ gentle（母功法在池即可）/ strict（主修位或大成）
  attach        母功法 id 列表（requirement≠free 时必填，否则技能永远不可用）
  unlock_fam    熟悉度解锁阈值 0..FAM_MAX
  qi_cost       耗灵（整数 ≥0）
  power         基础威力；attack_ratio  攻击力转化率
  tier          品阶 1..4（基础威力系数来源）
  windup/recovery  前摇/后摇（厘息，整数 ≥0）
  qi_efficiency 灵气加成系数（引气流高、品阶流低）
  duration_weight 时长加成权重（蓄力流高）
  effects       组件列表，见下
  conditions    条件字符串列表：target_has:<key> / self_has:<key> / self_hp_below:<ratio>
  desc          风味描述

effects 条目
------------
  {"type":"status","key":"weaken","duration_li":500,"stacks":1,"tags":["debuff"],"params":{...}}
  {"type":"qigain","rate_mult":3.0}
  {"type":"heal","amount":20}
  {"type":"purchase","cost":100,"boost":7.0,"T_max":1000}
  （省略 type 时，含 key 视为 status）

运行
----
  .venv\\Scripts\\python.exe -X utf8 -m tools.gen_skill --in draft.json --strict
  .venv\\Scripts\\python.exe -X utf8 -m tools.gen_skill --in draft.json --emit code
  .venv\\Scripts\\python.exe -X utf8 -m tools.gen_skill --random 5 --seed 42 --out drafts.json
  .venv\\Scripts\\python.exe -X utf8 -m tools.gen_skill --roundtrip     # 21 个现有技能无损往返
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field, fields
from typing import Optional

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from content import gongfa as G
from content import ids as IDS
from content import skills as SK
from engine import settings as S
from engine.action import (Action, ApplyStatus, Damage, Heal, Purchase, QiGain,
                           Timing, require_hp_below, require_self_has,
                           require_target_has)
from engine.rng import Rng
from tools import content_check as CC


class DraftError(ValueError):
    """draft 结构/类型错误（无法构成 Action）。"""


@dataclass
class SkillDraft:
    name: str = ""
    element: str = "无"
    kind: str = "attack"
    requirement: str = "free"
    id: Optional[int] = None
    key: str = ""
    unlock_fam: int = 0
    qi_cost: int = 0
    power: float = 0.0
    attack_ratio: float = 0.3
    tier: int = 1
    windup: int = 50
    recovery: int = 300
    qi_efficiency: float = 0.0
    duration_weight: float = 0.0
    effects: list = field(default_factory=list)
    conditions: list = field(default_factory=list)
    attach: list = field(default_factory=list)
    desc: str = ""

    # ---------- 序列化 ----------
    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


def draft_from_dict(obj: dict) -> SkillDraft:
    """dict → SkillDraft（严格类型检查，错就抛 DraftError）。"""
    if not isinstance(obj, dict):
        raise DraftError(f"draft 须为对象，实际 {type(obj).__name__}")
    known = {f.name for f in fields(SkillDraft)}
    unknown = set(obj) - known
    if unknown:
        raise DraftError(f"未知字段：{sorted(unknown)}（可选 {sorted(known)}）")
    kw = {}
    for f in fields(SkillDraft):
        if f.name not in obj:
            continue
        v = obj[f.name]
        if f.name in ("effects", "conditions", "attach"):
            if not isinstance(v, list):
                raise DraftError(f"{f.name} 须为 list，实际 {type(v).__name__}")
            kw[f.name] = list(v)
        elif f.name in ("id", "unlock_fam", "qi_cost", "tier", "windup", "recovery"):
            if v is None and f.name == "id":
                kw[f.name] = None
            elif isinstance(v, bool) or not isinstance(v, int):
                raise DraftError(f"{f.name} 须为整数，实际 {v!r}")
            else:
                kw[f.name] = v
        elif f.name in ("power", "attack_ratio", "qi_efficiency", "duration_weight"):
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise DraftError(f"{f.name} 须为数字，实际 {v!r}")
            kw[f.name] = v
        else:
            if not isinstance(v, str):
                raise DraftError(f"{f.name} 须为字符串，实际 {v!r}")
            kw[f.name] = v
    return SkillDraft(**kw)


def draft_from_skill(spec: SK.SkillSpec) -> SkillDraft:
    """现有 SkillSpec → draft（用于往返校验/批量改造）。"""
    a = spec.action
    d = SkillDraft(
        name=a.name, element=spec.element, kind=a.kind, requirement=spec.requirement,
        id=spec.id, key=a.key, unlock_fam=spec.unlock_fam, qi_cost=a.qi_cost,
        tier=a.tier, windup=a.timing.windup, recovery=a.timing.recovery,
        qi_efficiency=a.qi_efficiency, duration_weight=a.duration_weight,
        desc=a.desc,
    )
    for comp in a.components:
        if isinstance(comp, Damage):
            d.power, d.attack_ratio = comp.power, comp.attack_ratio
        elif isinstance(comp, ApplyStatus):
            d.effects.append({"type": "status", "key": comp.key,
                              "duration_li": comp.duration_li, "stacks": comp.stacks,
                              "tags": list(comp.tags), "params": dict(comp.params)})
        elif isinstance(comp, QiGain):
            d.effects.append({"type": "qigain", "rate_mult": comp.rate_mult})
        elif isinstance(comp, Heal):
            d.effects.append({"type": "heal", "amount": comp.amount})
        elif isinstance(comp, Purchase):
            d.effects.append({"type": "purchase", "cost": comp.cost,
                              "boost": comp.boost, "T_max": comp.T_max})
        else:
            raise DraftError(f"无法序列化组件 {type(comp).__name__}")
    return d


# ============================================================
# 组件 / 条件 构造
# ============================================================
def build_component(e: dict):
    if not isinstance(e, dict):
        raise DraftError(f"effects 条目须为对象，实际 {type(e).__name__}")
    etype = e.get("type") or ("status" if "key" in e else "")
    if etype == "status":
        key = e.get("key")
        if not isinstance(key, str) or not key:
            raise DraftError("status 效果缺少 key")
        tags = e.get("tags", [])
        if not isinstance(tags, list):
            raise DraftError("status.tags 须为 list")
        params = e.get("params", {})
        if not isinstance(params, dict):
            raise DraftError("status.params 须为对象")
        return ApplyStatus(key=key, duration_li=int(e.get("duration_li", 300)),
                           stacks=int(e.get("stacks", 1)), tags=tuple(tags),
                           params=dict(params))
    if etype == "qigain":
        return QiGain(rate_mult=float(e.get("rate_mult", 3.0)))
    if etype == "heal":
        return Heal(amount=float(e.get("amount", 0.0)))
    if etype == "purchase":
        return Purchase(cost=int(e.get("cost", 0)), boost=float(e.get("boost", 0.0)),
                        T_max=int(e.get("T_max", 0)))
    raise DraftError(f"未知效果类型：{etype!r}")


def build_condition(expr: str):
    if not isinstance(expr, str):
        raise DraftError(f"condition 须为字符串，实际 {expr!r}")
    if ":" not in expr:
        raise DraftError(f"condition 格式须为 <kind>:<arg>，实际 {expr!r}")
    kind, arg = expr.split(":", 1)
    if kind == "target_has":
        return require_target_has(arg)
    if kind == "self_has":
        return require_self_has(arg)
    if kind == "self_hp_below":
        try:
            return require_hp_below(float(arg))
        except ValueError:
            raise DraftError(f"self_hp_below 参数须为数字：{arg!r}")
    raise DraftError(f"未知 condition 类型：{kind!r}")


def build_action(draft: SkillDraft) -> Action:
    """draft → Action（不分配 id/不做注册表校验）。"""
    comps = []
    if draft.kind == "attack" or draft.power > 0:
        comps.append(Damage(power=float(draft.power),
                            attack_ratio=float(draft.attack_ratio),
                            element=draft.element))
    comps.extend(build_component(e) for e in draft.effects)
    conds = tuple(build_condition(c) for c in draft.conditions)
    key = draft.key or (f"sk{draft.id}" if draft.id is not None else "")
    return Action(key=key, name=draft.name, kind=draft.kind, qi_cost=int(draft.qi_cost),
                  timing=Timing(windup=int(draft.windup), recovery=int(draft.recovery)),
                  components=tuple(comps), conditions=conds,
                  qi_efficiency=float(draft.qi_efficiency),
                  duration_weight=float(draft.duration_weight), tier=int(draft.tier),
                  desc=draft.desc, id=draft.id)


def next_free_id(registry=None) -> int:
    """30 段下一个空位序号。"""
    seqs = {s.id - IDS.CAT_SKILL * 100000 for s in SK.SKILLS.values()}
    seq = 1
    while seq in seqs:
        seq += 1
    return IDS.make_id(IDS.CAT_SKILL, seq)


def build_skill(draft: SkillDraft, *, assign_id: bool = True) -> SK.SkillSpec:
    """draft → SkillSpec（可选自动分配 id/key）。"""
    d = SkillDraft(**draft.to_dict())
    if d.id is None and assign_id:
        d.id = next_free_id()
    if d.id is not None and not d.key:
        d.key = f"sk{d.id}"
    action = build_action(d)
    return SK.SkillSpec(action=action, requirement=d.requirement,
                        unlock_fam=int(d.unlock_fam))


# ============================================================
# 校验
# ============================================================
def validate_draft(draft: SkillDraft, out: Optional[list] = None,
                   *, existing_ids=None, existing_names=None) -> list:
    """draft 全量校验 → Issue 列表（复用 content_check 的字段规则）。

    `existing_ids`/`existing_names` 默认取当前 `content/skills.py` 注册表，
    因此"新技能 id 撞车 / 重名"默认就会报出来；若要校验"原地改某技能"，显式传 `set()`。
    """
    out = [] if out is None else out
    if existing_ids is None:
        existing_ids = set(SK.SKILLS)
    if existing_names is None:
        existing_names = {s.name for s in SK.SKILLS.values()}
    where = f"draft:{draft.id if draft.id is not None else '?'} {draft.name or '(未命名)'}"
    if not draft.name.strip():
        CC._err(where, "name 不能为空", out)
    if draft.element not in CC.ELEMENTS:
        CC._err(where, f"element 非法：{draft.element!r}（可选 {CC.ELEMENTS}）", out)
    if draft.kind not in CC.KINDS:
        CC._err(where, f"kind 非法：{draft.kind!r}（可选 {CC.KINDS}）", out)
    if draft.requirement not in CC.REQUIREMENTS:
        CC._err(where, f"requirement 非法：{draft.requirement!r}（可选 {CC.REQUIREMENTS}）", out)
    if draft.tier not in CC.ACTION_TIERS:
        CC._err(where, f"tier 须在 {CC.ACTION_TIERS}，实际 {draft.tier!r}", out)
    if not CC._is_int(draft.qi_cost) or draft.qi_cost < 0:
        CC._err(where, f"qi_cost 须为非负整数，实际 {draft.qi_cost!r}", out)
    if not CC._is_num(draft.power) or draft.power < 0:
        CC._err(where, f"power 须为非负数，实际 {draft.power!r}", out)
    if not CC._is_int(draft.unlock_fam) or not 0 <= draft.unlock_fam <= S.FAM_MAX:
        CC._err(where, f"unlock_fam 须在 0..{S.FAM_MAX}，实际 {draft.unlock_fam!r}", out)
    if draft.id is not None:
        if not CC._is_int(draft.id) or IDS.category_of(draft.id) != IDS.CAT_SKILL:
            CC._err(where, f"id 须为 {IDS.CAT_SKILL} 段整数，实际 {draft.id!r}", out)
        if existing_ids is not None and draft.id in existing_ids:
            CC._err(where, f"id {draft.id} 已存在（改 id 或用省略 id 自动分配）", out)
    if draft.requirement != "free" and not draft.attach:
        CC._err(where, f"requirement={draft.requirement} 但 attach 为空 → 无母功法，永远不可用", out)
    if draft.requirement == "free" and draft.attach:
        CC._warn(where, "requirement=free 却 attach 了母功法（自由技应独立）", out)
    for gid in draft.attach:
        gf = G.GONGFA.get(gid)
        if gf is None:
            CC._err(where, f"attach 引用不存在的功法 id {gid}", out)
        elif len(gf.skill_ids) >= 4:
            CC._err(where, f"attach 的功法 {gf.name} 已有 4 个技能（上限）", out)
    if existing_names is not None and draft.name in existing_names:
        CC._warn(where, f"name {draft.name!r} 与现有技能重名", out)
    # 构造 Action 并跑字段校验（无 id 的 draft 用"将会分配到的 id"做校验，
    # 否则 key 为空会被误判——build_skill 分配的是同一个确定性 id）
    try:
        probe = SkillDraft(**draft.to_dict())
        if probe.id is None:
            probe.id = next_free_id()
        if not probe.key:
            probe.key = f"sk{probe.id}"
        action = build_action(probe)
    except DraftError as exc:
        CC._err(where, f"无法构造 Action：{exc}", out)
        return out
    CC.check_action(action, where, out)
    for c in draft.conditions:
        try:
            build_condition(c)
        except DraftError as exc:
            CC._err(where, f"condition 非法：{exc}", out)
    return out


# ============================================================
# 代码 / JSON 输出
# ============================================================
def _num(v):
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return repr(v)


def _comp_code(comp) -> str:
    if isinstance(comp, ApplyStatus):
        parts = [f'key={comp.key!r}', f'duration_li={comp.duration_li}']
        if comp.stacks != 1:
            parts.append(f"stacks={comp.stacks}")
        if comp.tags:
            parts.append(f"tags={tuple(comp.tags)!r}")
        if comp.params:
            parts.append(f"params={comp.params!r}")
        return f"ApplyStatus({', '.join(parts)})"
    if isinstance(comp, QiGain):
        return f"QiGain(rate_mult={_num(comp.rate_mult)})"
    if isinstance(comp, Heal):
        return f"Heal(amount={_num(comp.amount)})"
    if isinstance(comp, Purchase):
        return (f"Purchase(cost={comp.cost}, boost={_num(comp.boost)}, "
                f"T_max={comp.T_max})")
    if isinstance(comp, Damage):
        return (f"Damage(power={_num(comp.power)}, "
                f"attack_ratio={_num(comp.attack_ratio)}, element={comp.element!r})")
    raise DraftError(f"无法生成代码：未知组件 {type(comp).__name__}")


_COND_CODE = {"target_has": "require_target_has", "self_has": "require_self_has",
              "self_hp_below": "require_hp_below"}


def _cond_code(expr: str) -> str:
    kind, arg = expr.split(":", 1)
    fn = _COND_CODE[kind]
    return f"{fn}({arg})" if kind == "self_hp_below" else f"{fn}({arg!r})"


def emit_code(draft: SkillDraft) -> str:
    """draft → 可粘进 content/skills.py 的 `_sk(...)` 行。"""
    action = build_action(draft)
    extra = [c for c in action.components if not isinstance(c, Damage)]
    lines = []
    needs = set()
    for c in extra:
        if isinstance(c, Heal):
            needs.add("Heal")
        if isinstance(c, Purchase):
            needs.add("Purchase")
    if needs:
        lines.append(f"# 需在 content/skills.py 顶部 import：{', '.join(sorted(needs))}")
    if draft.id is None:
        raise DraftError("emit_code 需要具体 id（先 assign_ids 或 build_skill 分配）")
    id_expr = "make_id(CAT_SKILL, %d)" % (draft.id - IDS.CAT_SKILL * 100000)
    cond_expr = ", ".join(_cond_code(c) for c in draft.conditions)
    extra_expr = ", ".join(_comp_code(c) for c in extra)
    parts = [
        f"_sk({id_expr}, {draft.name!r}, {draft.element!r}, {draft.kind!r}, "
        f"{int(draft.qi_cost)}, {_num(float(draft.power))}, {draft.requirement!r},",
        f"    {draft.desc!r}, unlock_fam={int(draft.unlock_fam)}, "
        f"windup={int(draft.windup)}, recovery={int(draft.recovery)}, "
        f"tier={int(draft.tier)}",
    ]
    if draft.qi_efficiency:
        parts[-1] += f", qi_eff={_num(float(draft.qi_efficiency))}"
    if draft.duration_weight:
        parts[-1] += f", dur_w={_num(float(draft.duration_weight))}"
    if draft.attack_ratio != 0.3:
        parts[-1] += f", attack_ratio={_num(float(draft.attack_ratio))}"
    if extra_expr:
        parts[-1] += f", extra=({extra_expr},)"
    if cond_expr:
        parts[-1] += f", conditions=({cond_expr},)"
    parts[-1] += "),"
    lines.extend(parts)
    if draft.attach:
        names = ", ".join(G.name_of(g) for g in draft.attach)
        lines.append(f"# 接线：把本技能 id 追加到 content/gongfa.py 的 skill_ids —— {names}")
    return "\n".join(lines)


# ============================================================
# 随机生成（P9 生成器的雏形；只负责"填 draft"，校验/落地走上面同一套）
# ============================================================
_ELEMENT_STEM = {
    "金": ["锐金", "庚锋", "裂石", "断岳", "鎏金"],
    "木": ["青藤", "生息", "缠枝", "木灵", "长春"],
    "水": ["玄冰", "沧澜", "寒潭", "叠浪", "流云"],
    "火": ["焚天", "烈焰", "赤炎", "火海", "炎爆"],
    "土": ["厚土", "撼岳", "地陷", "磐石", "落尘"],
    "无": ["灵光", "清心", "御风", "静虚", "无相"],
}
_KIND_SUFFIX = {
    "attack": ["斩", "击", "诀", "刺", "掌"],
    "defense": ["护体", "甲", "障", "壁", "罩"],
    "utility": ["术", "缚", "引", "遁", "禁"],
}
_POWER_BY_TIER = {1: (14, 30), 2: (24, 46), 3: (40, 62), 4: (60, 100)}
_QI_BY_TIER = {1: (2, 6), 2: (4, 10), 3: (8, 20), 4: (20, 40)}
_REC_BY_TIER = {1: (200, 300), 2: (200, 350), 3: (300, 450), 4: (400, 600)}
_STATUS_POOL = {
    "attack": [("vulnerable", 400, ("debuff",)), ("weaken", 500, ("debuff",))],
    "defense": [("guard", 400, ("buff",)), ("guard", 300, ("buff",))],
    "utility": [("root", 300, ("control",)), ("weaken", 500, ("debuff",)),
                ("evade", 400, ("buff",))],
}


def random_draft(rng: Rng, *, kind=None, tier=None, element=None,
                 requirement=None, attach=()) -> SkillDraft:
    """用约束表随机填一份 draft（保证字段合法；是否可落地仍由 validate_draft 判定）。"""
    kind = kind or rng.weighted_choice({"attack": 6, "defense": 2, "utility": 2},
                                       "gen_kind")
    tier = int(tier) if tier else rng.randint(1, 4, "gen_tier")
    element = element or rng.choice(list(CC.ELEMENTS), "gen_element")
    lo, hi = _POWER_BY_TIER[tier]
    power = rng.randint(lo, hi, "gen_power") if kind == "attack" else 0
    qlo, qhi = _QI_BY_TIER[tier]
    qi_cost = rng.randint(qlo, qhi, "gen_qi")
    rlo, rhi = _REC_BY_TIER[tier]
    recovery = rng.randint(rlo, rhi, "gen_rec")
    windup = rng.choice([50, 50, 100, 300, 700], "gen_windup") if rng.chance(0.25) else 50
    qi_eff = round(rng.roll("gen_qieff") * 0.08, 3) if kind == "attack" and rng.chance(0.4) else 0.0
    dur_w = round(rng.roll("gen_durw") * 0.5, 2) if windup >= 300 and rng.chance(0.6) else 0.0
    requirement = requirement or ("free" if not attach else rng.choice(["gentle", "gentle", "strict"], "gen_req"))
    unlock_fam = 0 if requirement == "free" else rng.choice([10, 30, 80], "gen_fam")
    effects = []
    if rng.chance(0.45):
        key, dur, tags = rng.choice(_STATUS_POOL[kind], "gen_fx")
        effects.append({"type": "status", "key": key, "duration_li": dur,
                        "stacks": 1, "tags": list(tags), "params": {}})
    if kind == "utility" and rng.chance(0.3):
        effects.append({"type": "qigain", "rate_mult": 3.0})
    if not effects and kind != "attack":
        # 非攻击技必须有组件，否则是"空动作"（校验会警告）
        key, dur, tags = _STATUS_POOL[kind][0]
        effects.append({"type": "status", "key": key, "duration_li": dur,
                        "stacks": 1, "tags": list(tags), "params": {}})
    conditions = []
    if any(e.get("key") == "weaken" for e in effects) and kind == "attack" and rng.chance(0.3):
        conditions.append("target_has:weaken")
    if kind == "attack" and rng.chance(0.15):
        conditions.append("self_hp_below:0.3")
    name = (rng.choice(_ELEMENT_STEM[element], f"gen_n1_{element}")
            + rng.choice(_KIND_SUFFIX[kind], f"gen_n2_{kind}"))
    return SkillDraft(
        name=name, element=element, kind=kind, requirement=requirement,
        unlock_fam=unlock_fam, qi_cost=qi_cost, power=power, tier=tier,
        windup=windup, recovery=recovery, qi_efficiency=qi_eff,
        duration_weight=dur_w, effects=effects, conditions=conditions,
        attach=list(attach),
        desc=f"随机生成（品阶{tier}·{element}系·{kind}），占位数值待标定。",
    )


# ============================================================
# CLI
# ============================================================
def _load_drafts(path: str) -> list:
    if path == "-":
        obj = json.load(sys.stdin)
    else:
        with open(path, encoding="utf-8") as f:
            obj = json.load(f)
    if isinstance(obj, dict):
        obj = obj.get("skills", [obj])
    if not isinstance(obj, list):
        raise DraftError("JSON 顶层须为 draft 对象或 draft 列表（或 {\"skills\": [...]}）")
    return [draft_from_dict(o) for o in obj]


def assign_ids(drafts: list) -> list:
    """给没有 id 的 draft 分配互不冲突的 30 段 id（不改原对象）。"""
    used = set(SK.SKILLS)
    nxt = next_free_id()
    out = []
    for d in drafts:
        dd = SkillDraft(**d.to_dict())
        if dd.id is None:
            while nxt in used:
                nxt += 1
            dd.id = nxt
            nxt += 1
        used.add(dd.id)
        if not dd.key:
            dd.key = f"sk{dd.id}"
        out.append(dd)
    return out


def _emit_drafts(drafts: list, mode: str) -> str:
    drafts = assign_ids(drafts)      # 让 emit 出来的代码/JSON 带具体 id
    if mode == "json":
        return json.dumps([d.to_dict() for d in drafts], ensure_ascii=False, indent=2)
    if mode == "code":
        return "\n\n".join(emit_code(d) for d in drafts)
    raise DraftError(f"未知输出格式：{mode!r}")


def _report(drafts: list, strict: bool) -> int:
    existing_ids = set(SK.SKILLS)
    existing_names = {s.name for s in SK.SKILLS.values()}
    issues = []
    for d in drafts:
        validate_draft(d, issues, existing_ids=existing_ids,
                       existing_names=existing_names)
    for i in issues:
        print(i)
    errors = sum(1 for i in issues if i.severity == CC.ERROR)
    warns = sum(1 for i in issues if i.severity == CC.WARN)
    print(f"\n== draft 校验：{len(drafts)} 份 / {errors} 错误 / {warns} 警告 ==")
    return 1 if errors or (strict and warns) else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="技能生成器（draft → 校验 → 代码/JSON）")
    ap.add_argument("--in", dest="inp", action="append", default=[],
                    help="draft JSON 文件（可重复；'-' 读 stdin）")
    ap.add_argument("--emit", choices=("none", "code", "json"), default="none",
                    help="校验通过后输出什么")
    ap.add_argument("--out", default="", help="输出文件（默认 stdout）")
    ap.add_argument("--strict", action="store_true", help="警告也算失败")
    ap.add_argument("--random", type=int, default=0, metavar="N",
                    help="随机生成 N 份 draft（走同一套校验）")
    ap.add_argument("--seed", type=int, default=0, help="随机种子")
    ap.add_argument("--attach", type=int, action="append", default=[],
                    help="随机/草稿的母功法 id（可重复）")
    ap.add_argument("--roundtrip", action="store_true",
                    help="校验现有 21 个技能 draft 往返无损")
    args = ap.parse_args(argv)

    if args.roundtrip:
        bad = []
        for spec in sorted(SK.SKILLS.values(), key=lambda s: s.id):
            d = draft_from_skill(spec)
            rebuilt = build_skill(d)
            a, b = spec.action, rebuilt.action
            same = (a.key, a.name, a.kind, a.qi_cost, a.tier, a.timing,
                    a.qi_efficiency, a.duration_weight, a.components,
                    spec.requirement, spec.unlock_fam) == \
                   (b.key, b.name, b.kind, b.qi_cost, b.tier, b.timing,
                    b.qi_efficiency, b.duration_weight, b.components,
                    rebuilt.requirement, rebuilt.unlock_fam)
            if not same:
                bad.append(spec.name)
        print(f"== 往返：{len(SK.SKILLS)} 个技能，{'全部无损' if not bad else '失败：' + str(bad)} ==")
        return 1 if bad else 0

    drafts = []
    for p in args.inp:
        try:
            drafts.extend(_load_drafts(p))
        except (DraftError, json.JSONDecodeError, OSError) as exc:
            print(f"[ERROR] 读取 {p} 失败：{exc}")
            return 1
    if args.random:
        rng = Rng(args.seed)
        drafts.extend(random_draft(rng, attach=args.attach) for _ in range(args.random))
    if not drafts:
        ap.print_help()
        return 2

    rc = _report(drafts, args.strict)
    if rc == 0 and args.emit != "none":
        text = _emit_drafts(drafts, args.emit)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(text + "\n")
            print(f"→ 已写入 {args.out}")
        else:
            print("\n" + text)
    return rc


if __name__ == "__main__":
    sys.exit(main())
