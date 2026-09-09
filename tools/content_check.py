"""内容校验器：content/ 数据的结构、引用与取值体检（开发期工具）。

定位：引擎运行时**不依赖**本模块。用途有三：

  1. 新增/修改 `content/*.py` 后跑一次，防 id 撞车、引用悬空、数值越界；
  2. `tests/test_content_tools.py` 直接调用 `check_content()`，把"内容合法"变成可回归契约；
  3. 技能生成器（`tools/gen_skill.py`）复用本模块的字段校验——手写 / AI 起草 / 随机生成
     三条路走同一套规则。

分级：
  ERROR = 结构或引用错误（必须修；CLI 退出码 1）
  WARN  = 语义可疑（如效果键无引擎消费者、demo 动作无人引用；默认不失败，`--strict` 才失败）

运行：
  .venv\\Scripts\\python.exe -X utf8 -m tools.content_check            # 人读报告
  .venv\\Scripts\\python.exe -X utf8 -m tools.content_check --json      # 机读
  .venv\\Scripts\\python.exe -X utf8 -m tools.content_check --strict    # 警告也算失败
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from content import actions as CA
from content import effects as CE
from content import enemies as EM
from content import gongfa as G
from content import ids as IDS
from content import pills as P
from content import sites as ST
from content import skills as SK
from engine import battle as BTL
from engine import rules as R
from engine import settings as S
from engine.action import (Action, ApplyStatus, Damage, Heal, Purchase, QiGain,
                           Timing)

# ---------- 取值域（改设计时改这里，校验器与生成器共用） ----------
ELEMENTS = ("金", "木", "水", "火", "土", "无")
KINDS = ("attack", "defense", "utility", "special")
REQUIREMENTS = ("free", "gentle", "strict")
SLOTS = ("main", "battle", "shenfa")
TARGETS = ("self", "enemy", "all_enemies")
TAGS = ("buff", "debuff", "control")
PILL_KINDS = ("breakthrough", "other")
PILL_EFFECT_KEYS = ("heart_demon", "cultivate_bonus")
# 立即结算键（效果模板 apply_key 指向的函数）：与 engine.effects.APPLY_FX 的内置项对应。
# 不 import 那个模块——它已被标记为待删除的死代码，校验器不该依赖它。
IMMEDIATE_FX_KEYS = ("restore_qi",)
GONGFA_TIERS = tuple(sorted(G.TIER_LABELS))          # (1,10,14,18,22)
ACTION_TIERS = (1, 2, 3, 4)                          # engine.rules.TIER_MULT
SKILL_ID_PREFIX = "sk"

ERROR = "error"
WARN = "warn"


@dataclass(frozen=True)
class Issue:
    severity: str          # ERROR / WARN
    where: str             # 定位串，如 "skills:3000001 烈焰斩"
    message: str

    def to_dict(self) -> dict:
        return {"severity": self.severity, "where": self.where,
                "message": self.message}

    def __str__(self) -> str:
        return f"[{self.severity.upper():<5}] {self.where}: {self.message}"


def _err(where, msg, out):
    out.append(Issue(ERROR, where, msg))


def _warn(where, msg, out):
    out.append(Issue(WARN, where, msg))


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


# ============================================================
# 字段级校验（生成器复用这些）
# ============================================================
def check_timing(t: Timing, where: str, out: list):
    for name in ("windup", "recovery"):
        v = getattr(t, name)
        if not _is_int(v) or v < 0:
            _err(where, f"timing.{name} 须为非负整数，实际 {v!r}", out)
    for name in ("windup_speed", "recovery_speed"):
        v = getattr(t, name)
        if not _is_num(v) or v < 0:
            _err(where, f"timing.{name} 须为非负数，实际 {v!r}", out)


def check_action(action: Action, where: str, out: list):
    """校验一个动作的字段与组件（不做跨引用检查）。"""
    if not isinstance(action.key, str) or not action.key:
        _err(where, "action.key 不能为空", out)
    elif not action.key.isascii():
        _err(where, f"action.key 禁中文/非 ASCII：{action.key!r}", out)
    if action.kind not in KINDS:
        _err(where, f"kind 非法：{action.kind!r}（可选 {KINDS}）", out)
    if action.target not in TARGETS:
        _err(where, f"target 非法：{action.target!r}（可选 {TARGETS}）", out)
    if not _is_int(action.qi_cost) or action.qi_cost < 0:
        _err(where, f"qi_cost 须为非负整数，实际 {action.qi_cost!r}", out)
    if action.tier not in ACTION_TIERS:
        _err(where, f"tier 须在 {ACTION_TIERS}，实际 {action.tier!r}", out)
    for name in ("qi_efficiency", "duration_weight"):
        v = getattr(action, name)
        if not _is_num(v) or v < 0:
            _err(where, f"{name} 须为非负数，实际 {v!r}", out)
    check_timing(action.timing, where, out)
    if not action.components and action.kind != "special":
        _warn(where, "components 为空（动作不会产生任何效果）", out)
    has_damage = False
    for i, comp in enumerate(action.components):
        cw = f"{where} 组件[{i}]{type(comp).__name__}"
        if isinstance(comp, Damage):
            has_damage = True
            if not _is_num(comp.power) or comp.power < 0:
                _err(cw, f"power 须为非负数，实际 {comp.power!r}", out)
            if not _is_num(comp.attack_ratio) or comp.attack_ratio < 0:
                _err(cw, f"attack_ratio 须为非负数，实际 {comp.attack_ratio!r}", out)
            if comp.element not in ELEMENTS:
                _err(cw, f"element 非法：{comp.element!r}", out)
        elif isinstance(comp, ApplyStatus):
            if not isinstance(comp.key, str) or not comp.key:
                _err(cw, "ApplyStatus.key 不能为空", out)
            elif not comp.key.isascii():
                _err(cw, f"ApplyStatus.key 禁中文：{comp.key!r}", out)
            if not _is_int(comp.duration_li) or comp.duration_li <= 0:
                _err(cw, f"duration_li 须为正整数（厘息），实际 {comp.duration_li!r}", out)
            if not _is_int(comp.stacks) or comp.stacks < 1:
                _err(cw, f"stacks 须 ≥1，实际 {comp.stacks!r}", out)
            for tag in comp.tags:
                if tag not in TAGS:
                    _warn(cw, f"未知 tag：{tag!r}（施加边由 debuff/control 决定）", out)
            if comp.key not in CE.EFFECTS:
                _warn(cw, f"状态键 {comp.key!r} 无效果模板（UI 无展示名）", out)
        elif isinstance(comp, QiGain):
            if not _is_num(comp.rate_mult) or comp.rate_mult < 0:
                _err(cw, f"rate_mult 须为非负数，实际 {comp.rate_mult!r}", out)
        elif isinstance(comp, Heal):
            if not _is_num(comp.amount) or comp.amount < 0:
                _err(cw, f"amount 须为非负数，实际 {comp.amount!r}", out)
        elif isinstance(comp, Purchase):
            if not _is_int(comp.cost) or comp.cost < 0:
                _err(cw, f"cost 须为非负整数，实际 {comp.cost!r}", out)
            if not _is_num(comp.boost) or comp.boost < 0:
                _err(cw, f"boost 须为非负数，实际 {comp.boost!r}", out)
            if not _is_int(comp.T_max) or comp.T_max <= 0:
                _err(cw, f"T_max 须为正整数，实际 {comp.T_max!r}", out)
        else:
            _err(cw, f"未知组件类型：{type(comp).__name__}", out)
    if action.kind == "attack" and not has_damage:
        _warn(where, "kind=attack 但无 Damage 组件", out)


def check_skill(spec: SK.SkillSpec, where: str, out: list):
    """校验一个技能（动作 + 谱系字段 + 注册表一致性）。"""
    if not _is_int(spec.id):
        _err(where, f"id 须为整数，实际 {spec.id!r}", out)
    elif IDS.category_of(spec.id) != IDS.CAT_SKILL:
        _err(where, f"id 分类须为 {IDS.CAT_SKILL}（技能段），实际 {IDS.category_of(spec.id)}", out)
    if spec.key != f"{SKILL_ID_PREFIX}{spec.id}":
        _err(where, f"key 须为 '{SKILL_ID_PREFIX}{spec.id}'，实际 {spec.key!r}", out)
    if spec.requirement not in REQUIREMENTS:
        _err(where, f"requirement 非法：{spec.requirement!r}（可选 {REQUIREMENTS}）", out)
    if not _is_int(spec.unlock_fam) or not 0 <= spec.unlock_fam <= S.FAM_MAX:
        _err(where, f"unlock_fam 须在 0..{S.FAM_MAX}，实际 {spec.unlock_fam!r}", out)
    check_action(spec.action, where, out)
    mothers = G.mother_gongfas(spec.id)
    if spec.requirement != "free" and not mothers:
        _err(where, f"requirement={spec.requirement} 但无母功法引用 → 永远不可用", out)
    if spec.requirement == "free" and mothers:
        _warn(where, f"requirement=free 却挂在功法 {mothers} 上（自由技应独立）", out)
    try:
        spec.element  # noqa: B018  —— 属性实现出错（如首个组件无 element）会在此暴露
    except Exception as exc:                      # pragma: no cover - 防御
        _err(where, f"element 属性取值抛异常：{exc}", out)


def check_gongfa(gf: G.Gongfa, where: str, out: list):
    if IDS.category_of(gf.id) != IDS.CAT_GONGFA:
        _err(where, f"id 分类须为 {IDS.CAT_GONGFA}，实际 {IDS.category_of(gf.id)}", out)
    if not gf.name:
        _err(where, "name 不能为空", out)
    if gf.slot_type not in SLOTS:
        _err(where, f"slot_type 非法：{gf.slot_type!r}（可选 {SLOTS}）", out)
    if gf.element not in ELEMENTS:
        _err(where, f"element 非法：{gf.element!r}", out)
    if gf.tier not in GONGFA_TIERS:
        _warn(where, f"tier={gf.tier} 不在大境界起点档 {GONGFA_TIERS}（看懂门槛语义可疑）", out)
    if not _is_int(gf.price) or gf.price < 0:
        _err(where, f"price 须为非负整数，实际 {gf.price!r}", out)
    for name in ("cultivate_bonus", "permanent_bonus"):
        v = getattr(gf, name)
        if not _is_num(v) or v < 0:
            _err(where, f"{name} 须为非负数，实际 {v!r}", out)
    if not isinstance(gf.skill_ids, list):
        _err(where, "skill_ids 须为 list", out)
        return
    if len(gf.skill_ids) > 4:
        _err(where, f"skill_ids 超过 4 个（设计：一本功法 1~4 技能），实际 {len(gf.skill_ids)}", out)
    if len(set(gf.skill_ids)) != len(gf.skill_ids):
        _err(where, "skill_ids 含重复", out)
    for sid in gf.skill_ids:
        if sid not in SK.SKILLS:
            _err(where, f"skill_ids 引用不存在的技能 id {sid}", out)
    if gf.slot_type == "main" and not gf.skill_ids:
        _warn(where, "主修功法无自带技能（只吃 cultivate_bonus）", out)


def check_pill(pill: P.Pill, where: str, out: list):
    if IDS.category_of(pill.id) != IDS.CAT_PILL:
        _err(where, f"id 分类须为 {IDS.CAT_PILL}，实际 {IDS.category_of(pill.id)}", out)
    if pill.kind not in PILL_KINDS:
        _err(where, f"kind 非法：{pill.kind!r}（可选 {PILL_KINDS}）", out)
    if not _is_int(pill.price) or pill.price < 0:
        _err(where, f"price 须为非负整数，实际 {pill.price!r}", out)
    if pill.kind == "breakthrough":
        if pill.tier not in S.MAJOR_REALM_STARTS[1:]:
            _err(where, f"突破丹 tier 须为大境界起点档 {S.MAJOR_REALM_STARTS[1:]}，实际 {pill.tier}", out)
        if not _is_num(pill.bonus) or not 0 <= pill.bonus <= 1:
            _err(where, f"突破丹 bonus 须在 0..1，实际 {pill.bonus!r}", out)
    else:
        for k in pill.effect:
            if k not in PILL_EFFECT_KEYS:
                _warn(where, f"辅助丹 effect 键 {k!r} 引擎不识别（_use_pill 只处理 {PILL_EFFECT_KEYS}）", out)


def check_site(site: ST.Site, where: str, out: list):
    if IDS.category_of(site.id) != IDS.CAT_SITE:
        _err(where, f"id 分类须为 {IDS.CAT_SITE}，实际 {IDS.category_of(site.id)}", out)
    if site.id == ST.SHISHI:
        _err(where, "坊市不应出现在 SITES（它由 SHISHI 常量特判）", out)
    if not _is_int(site.realm_req) or not 1 <= site.realm_req <= S.MAX_REALM:
        _err(where, f"realm_req 须在 1..{S.MAX_REALM}，实际 {site.realm_req!r}", out)
    if not _is_int(site.days_cost) or site.days_cost < 1:
        _err(where, f"days_cost 须 ≥1，实际 {site.days_cost!r}", out)
    if (not isinstance(site.stone, tuple) or len(site.stone) != 2
            or not all(_is_int(x) for x in site.stone) or site.stone[0] > site.stone[1]):
        _err(where, f"stone 须为 (min,max) 且 min≤max，实际 {site.stone!r}", out)
    if not _is_num(site.danger) or not 0 <= site.danger <= 1:
        _err(where, f"danger 须在 0..1，实际 {site.danger!r}", out)
    for pid, prob in site.pill_drops.items():
        if pid not in P.PILLS:
            _err(where, f"pill_drops 引用不存在的丹药 id {pid}", out)
        if not _is_num(prob) or not 0 < prob <= 1:
            _err(where, f"pill_drops[{pid}] 概率须在 (0,1]，实际 {prob!r}", out)


def check_enemy(enemy: EM.Enemy, where: str, out: list):
    if IDS.category_of(enemy.id) != IDS.CAT_ENEMY:
        _err(where, f"id 分类须为 {IDS.CAT_ENEMY}，实际 {IDS.category_of(enemy.id)}", out)
    if enemy.site_id not in ST.SITES:
        _err(where, f"site_id 引用不存在的探索点 {enemy.site_id}", out)
    if not _is_int(enemy.realm_idx) or not 1 <= enemy.realm_idx <= S.MAX_REALM:
        _err(where, f"realm_idx 须在 1..{S.MAX_REALM}，实际 {enemy.realm_idx!r}", out)
    if enemy.element not in ELEMENTS:
        _err(where, f"element 非法：{enemy.element!r}", out)
    for name in ("hp", "attack", "defense", "speed"):
        v = getattr(enemy, name)
        if not _is_num(v) or v <= 0:
            _err(where, f"{name} 须为正数，实际 {v!r}", out)
    if (not isinstance(enemy.loot_stones, tuple) or len(enemy.loot_stones) != 2
            or not all(_is_int(x) for x in enemy.loot_stones)
            or enemy.loot_stones[0] > enemy.loot_stones[1]):
        _err(where, f"loot_stones 须为 (min,max) 且 min≤max，实际 {enemy.loot_stones!r}", out)
    for pid, prob in enemy.loot_pills.items():
        if pid not in P.PILLS:
            _err(where, f"loot_pills 引用不存在的丹药 id {pid}", out)
        if not _is_num(prob) or not 0 < prob <= 1:
            _err(where, f"loot_pills[{pid}] 概率须在 (0,1]，实际 {prob!r}", out)


# ============================================================
# 注册表级校验（静态扫描 + 跨引用）
# ============================================================
_ID_LITERAL_RE = re.compile(r"make_id\(\s*(CAT_[A-Z_]+)\s*,\s*(\d+)\s*\)")


def scan_id_literals() -> list:
    """静态扫描 content/*.py 的 make_id(CAT_*, n) 字面量，返回 [(cat,seq,file), ...]。

    字典注册表会把重复 id 静默覆盖，所以必须从源码层面查重。
    """
    out = []
    content_dir = os.path.join(_ROOT, "content")
    for name in sorted(os.listdir(content_dir)):
        if not name.endswith(".py"):
            continue
        path = os.path.join(content_dir, name)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        for m in _ID_LITERAL_RE.finditer(text):
            cat_name, seq = m.group(1), int(m.group(2))
            cat = getattr(IDS, cat_name, None)
            if cat is None:
                out.append((cat_name, seq, name, False))
            else:
                out.append((cat, seq, name, True))
    return out


def check_id_literals(out: list):
    seen = {}
    for cat, seq, fname, known in scan_id_literals():
        if not known:
            _err(f"ids:{fname}", f"make_id 使用了未知分类常量 {cat}", out)
            continue
        key = (cat, seq)
        if key in seen:
            _err(f"ids:{fname}", f"id 撞车：{cat}×100000+{seq} 已在 {seen[key]} 出现", out)
        else:
            seen[key] = fname
        if not 0 <= seq <= 99999:
            _err(f"ids:{fname}", f"序号越界：{seq}", out)


def check_settings(out: list):
    if len(S.REALM_NAMES) != S.MAX_REALM:
        _err("settings", f"REALM_NAMES 长度 {len(S.REALM_NAMES)} ≠ MAX_REALM {S.MAX_REALM}", out)
    if len(S.LIFESPAN_PER_REALM) != S.MAX_REALM:
        _err("settings", "LIFESPAN_PER_REALM 长度 ≠ MAX_REALM", out)
    starts = list(S.MAJOR_REALM_STARTS)
    if starts != sorted(set(starts)) or starts[0] != 1 or starts[-1] > S.MAX_REALM:
        _err("settings", f"MAJOR_REALM_STARTS 须为递增且首项=1 的档号序列，实际 {starts}", out)
    caps = [S.exp_cap(i) for i in range(1, S.MAX_REALM + 1)]
    if any(caps[i] >= caps[i + 1] for i in range(len(caps) - 1)):
        _warn("settings", "exp_cap 随档号非严格递增", out)
    if S.FAM_ENTRY > S.FAM_MAX:
        _err("settings", f"FAM_ENTRY {S.FAM_ENTRY} 不得大于 FAM_MAX {S.FAM_MAX}", out)


def check_registries(out: list):
    """注册表内部一致性：键/id/name 唯一，BY_KEY 指向同一对象。"""
    for where, mapping, id_of, key_of, name_of, by_key in (
        ("skills", SK.SKILLS, lambda s: s.id, lambda s: s.key, lambda s: s.name, SK.BY_KEY),
        ("gongfa", G.GONGFA, lambda g: g.id, lambda g: g.id, lambda g: g.name, None),
        ("pills", P.PILLS, lambda p: p.id, lambda p: p.id, lambda p: p.name, None),
        ("sites", ST.SITES, lambda s: s.id, lambda s: s.id, lambda s: s.name, None),
        ("enemies", EM.ENEMIES, lambda e: e.id, lambda e: e.id, lambda e: e.name, None),
    ):
        names = {}
        for obj in mapping.values():
            nm = name_of(obj)
            if nm in names:
                _err(f"{where}", f"name 重复：{nm!r}（与 {names[nm]} 冲突；中文名反查会串）", out)
            else:
                names[nm] = id_of(obj)
            if by_key is not None:
                k = key_of(obj)
                if by_key.get(k) is not obj:
                    _err(f"{where}", f"BY_KEY[{k!r}] 未指向同一对象", out)
    # id 反查表长度
    for where, mapping, id_by_name in (
        ("skills", SK.SKILLS, SK.ID_BY_NAME),
        ("gongfa", G.GONGFA, G.ID_BY_NAME),
        ("pills", P.PILLS, P.ID_BY_NAME),
        ("sites", ST.SITES, ST.ID_BY_NAME),
    ):
        if len(id_by_name) < len(mapping):
            _err(where, f"ID_BY_NAME 条目 {len(id_by_name)} < 注册表 {len(mapping)}（中文名重复）", out)


def check_actions(out: list):
    """动作池：键唯一、必备动作存在、demo 孤儿动作提示。"""
    all_actions = {}
    for a in (list(CA.BASIC_ACTIONS) + list(CA.ENEMY_ACTIONS)
              + list(CA.SKILLS.values()) + [CA.BUY_QI_LOW, CA.BUY_QI_HIGH, CA.BUY_QI_BOOST]):
        if a.key in all_actions and all_actions[a.key] is not a:
            _err("actions", f"动作键撞车：{a.key!r}", out)
        all_actions[a.key] = a
    required = {"attack", "defend", "gather", "flee", "enemy_strike"}
    missing = required - set(all_actions)
    if missing:
        _err("actions", f"缺少必备动作：{sorted(missing)}", out)
    for a in all_actions.values():
        check_action(a, f"actions:{a.key}", out)
    # 游戏实际可用动作 = 基础 + 技能(21) + 买加速(low/high)
    game_keys = ({a.key for a in CA.BASIC_ACTIONS} | {s.key for s in SK.SKILLS.values()}
                 | {CA.BUY_QI_LOW.key, CA.BUY_QI_HIGH.key})
    for key, a in CA.SKILLS.items():
        if key not in game_keys:
            _warn("actions", f"demo 动作 {key!r}（{a.display()}）未被游戏引用"
                             f"（仅 tools.dummy / tests 使用）", out)
    if CA.BUY_QI_BOOST.key not in game_keys:
        _warn("actions", f"{CA.BUY_QI_BOOST.key!r} 未被游戏引用（游戏只用 low/high 两档）", out)


def check_effects(out: list):
    """效果模板：引擎消费者、孤儿模板、ApplyStatus 键无模板。"""
    # 真正有机械效果的键 = 乘区 + 控制 + 立即结算（breath 经 apply_key 生效）
    for key, tpl in CE.EFFECTS.items():
        recognized = (key in R.STATUS_MULT or key in BTL.CONTROL_KEYS
                      or (tpl.apply_key and tpl.apply_key in IMMEDIATE_FX_KEYS))
        if not recognized:
            _warn("effects", f"模板 {key!r}（{tpl.name}）无引擎消费者 → 施加后不生效"
                             f"（STATUS_MULT/CONTROL_KEYS/APPLY_FX 都不认识）", out)
    used = set()
    for spec in SK.SKILLS.values():
        for comp in spec.action.components:
            if isinstance(comp, ApplyStatus):
                used.add(comp.key)
    for a in list(CA.BASIC_ACTIONS) + list(CA.SKILLS.values()):
        for comp in a.components:
            if isinstance(comp, ApplyStatus):
                used.add(comp.key)
    for key in sorted(used):
        if key not in CE.EFFECTS:
            _warn("effects", f"动作施加的状态键 {key!r} 无模板（UI 无展示名）", out)
    for key in sorted(set(CE.EFFECTS) - used):
        _warn("effects", f"模板 {key!r} 未被任何动作施加（孤儿模板）", out)


def check_cross_refs(out: list):
    for sid, site in ST.SITES.items():
        if not EM.pool_for(sid):
            _warn(f"sites:{sid} {site.name}", "无敌人（探索遇敌会走旧折寿兜底）", out)
    for tier, pill in P.BREAKTHROUGH_BY_TIER.items():
        if pill.tier != tier:
            _err("pills", f"BREAKTHROUGH_BY_TIER[{tier}] 指向的丹 tier={pill.tier}", out)
    for el, gid in G.FOUNDATION_BY_ELEMENT.items():
        if el not in ELEMENTS or gid not in G.GONGFA:
            _err("gongfa", f"FOUNDATION_BY_ELEMENT[{el!r}]={gid} 非法", out)
    perms = [gf.name for gf in G.GONGFA.values() if gf.permanent_bonus > 0]
    if len(perms) > 1:
        _warn("gongfa", f"permanent_bonus 功法多于 1 本：{perms}（P3 锚点：仅《吐纳诀》）", out)
    # 技能 id 引用：gongfa.skill_ids 已在 check_gongfa 覆盖
    for cid in (IDS.CAT_SITE, IDS.CAT_PILL, IDS.CAT_SKILL, IDS.CAT_GONGFA,
                IDS.CAT_ITEM, IDS.CAT_ENEMY):
        if cid not in IDS._CAT_NAMES:
            _warn("ids", f"分类 {cid} 无中文名（_CAT_NAMES 缺项）", out)


# ============================================================
# 总入口
# ============================================================
def check_content() -> list:
    """跑全部检查，返回 Issue 列表（不抛异常）。"""
    out: list = []
    check_id_literals(out)
    check_settings(out)
    check_registries(out)
    for spec in sorted(SK.SKILLS.values(), key=lambda s: s.id):
        check_skill(spec, f"skills:{spec.id} {spec.name}", out)
    for gf in sorted(G.GONGFA.values(), key=lambda g: g.id):
        check_gongfa(gf, f"gongfa:{gf.id} {gf.name}", out)
    for pill in sorted(P.PILLS.values(), key=lambda p: p.id):
        check_pill(pill, f"pills:{pill.id} {pill.name}", out)
    for site in sorted(ST.SITES.values(), key=lambda s: s.id):
        check_site(site, f"sites:{site.id} {site.name}", out)
    for enemy in sorted(EM.ENEMIES.values(), key=lambda e: e.id):
        check_enemy(enemy, f"enemies:{enemy.id} {enemy.name}", out)
    check_actions(out)
    check_effects(out)
    check_cross_refs(out)
    return out


def summarize(issues: list) -> dict:
    errors = [i for i in issues if i.severity == ERROR]
    warns = [i for i in issues if i.severity == WARN]
    return {"errors": len(errors), "warnings": len(warns),
            "issues": issues, "error_list": errors, "warn_list": warns}


def main(argv=None):
    ap = argparse.ArgumentParser(description="content/ 数据校验器")
    ap.add_argument("--json", action="store_true", help="输出 JSON（机读）")
    ap.add_argument("--strict", action="store_true", help="警告也算失败（退出码 1）")
    ap.add_argument("--quiet", action="store_true", help="只输出汇总")
    args = ap.parse_args(argv)

    issues = check_content()
    s = summarize(issues)
    if args.json:
        print(json.dumps({"errors": s["errors"], "warnings": s["warnings"],
                          "issues": [i.to_dict() for i in issues]},
                         ensure_ascii=False, indent=2))
    else:
        if not args.quiet:
            for i in issues:
                print(i)
        print(f"\n== 内容校验：{s['errors']} 错误 / {s['warnings']} 警告 ==")
    failed = s["errors"] > 0 or (args.strict and s["warnings"] > 0)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
