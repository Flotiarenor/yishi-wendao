"""引擎冒烟测试：模拟一整局（真实经济闭环 + P2 战斗 bot + P3 功法参悟链）。

Bot 策略（反映设计意图，非上帝视角）：
  1. 修为满后尝试突破；失败先疗心魔/继续修。
  2. 小境界突破：需灵石护法 → 不够就去探索点赚。
  3. 大境界突破：需灵石 + 对应突破丹 → 探索攒灵石（顺带撞丹药掉落）或回坊市买。
  4. 心魔 > 50 时买/用清心丹压制。
  5. 探索遇敌 → 战斗 bot：粗估双方伤害，能赢就打（优先克制/高伤技能），
     不能赢（或自身 HP<30%）直接遁走。（utility 不参与 bot 决策，仅随局记录）
  6. P3 功法链（保守、低方差）：开局参悟《吐纳诀》至入门并装主修；
     灵石富余且境界够 → 按"主修加成+0.05 且技能数≥旧且含攻击技"规则购/参悟/换装更强主修；
     主修技能未解锁完时，隔周期把部分闭关日数投参悟主修。
  7. 死/通关/回合上限即结束。局末打印 20 局结局分布 + 战斗统计（次数/胜/负/逃）。

运行：.venv\\Scripts\\python.exe -X utf8 -m tests.smoke [seed] [--log [FILE]]
  seed       指定种子跑单局(verbose)；省略则跑默认 20 局统计
  --log FILE 把输出同时写入日志文件（tee）；FILE 省略时自动生成 logs/smoke-<时间戳>.log
"""
import argparse
import datetime
import math
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.game import Game, cultivation_mult
from engine import settings as S
from engine import battle as BTL
from content import gongfa as G
from content import pills as P
from content import sites as ST
from content import skills as SK


def _q(p, pid: int) -> int:
    """背包数量 by id。"""
    return p.item_count(pid)


def _main_mult(p) -> float:
    """闭关单日效率（复用 engine.game.cultivation_mult，含道基被动+主修加成）。"""
    return cultivation_mult(p)


def _stone_need(p) -> int:
    major_jump = (p.realm_idx + 1) in S.MAJOR_REALM_STARTS
    cost = S.BREAKTHROUGH_STONE_COST + p.realm_idx * 2
    if major_jump:
        cost += S.MAJOR_BREAKTHROUGH_STONE_COST
    return cost


def _needs(p) -> str:
    """修为满时返回缺口描述；否则空串。"""
    if p.exp < p.exp_cap():
        return ""
    if p.spirit_stones < _stone_need(p):
        return "缺灵石"
    if (p.realm_idx + 1) in S.MAJOR_REALM_STARTS:
        pill = P.BREAKTHROUGH_BY_TIER.get(p.realm_idx + 1)
        if pill is not None and _q(p, pill.id) < 1:
            return f"缺{pill.name}"
    return "可突破"


def _pick_site(p) -> int:
    """选当前境界够得着、单次收益较高的探索点 id。"""
    candidates = []
    for sid, cfg in ST.SITES.items():
        if p.realm_idx >= cfg.realm_req:
            avg = (cfg.stone[0] + cfg.stone[1]) / 2
            candidates.append((avg / cfg.days_cost, sid))
    if not candidates:
        best = min(ST.SITES.items(), key=lambda kv: kv[1].danger)
        return best[0]
    candidates.sort(reverse=True)
    return candidates[0][1]


# ---------- 战斗 bot（R3 时间轴版） ----------
def _battle_decision(g):
    """粗估双方输出 → 决定这一轮排什么动作。

    R3 起战斗是"决策窗口 + 队列"：bot 每轮排一个动作（够用且可复现），
    窗口由敌方速度决定，引擎自己把这一轮跑完。
    返回动作键（"attack" / 技能 key / "flee" / "gather"）。
    """
    b = g.battle()
    e = b.e
    # 我方每次出手的伤害粗估（平砍兜底，逐个攻击技取最大，含五行克制）
    plain = max(1.0, e.defense and (b.p.attack - e.defense * 0.4) or b.p.attack)
    best_dmg, best_key = float(plain), "attack"
    for a in b.actions.values():
        dmg_c = next((c for c in a.components if hasattr(c, "attack_ratio")), None)
        if dmg_c is None or a.kind != "attack":
            continue
        if b.p.qi < a.qi_cost:
            continue
        dmg = (dmg_c.power + b.p.attack * dmg_c.attack_ratio - e.defense * 0.3) \
            * BTL.ke_mult(dmg_c.element, e.element)
        if dmg > best_dmg:
            best_dmg, best_key = dmg, a.key
    # 敌方每次出手伤害粗估
    e_dmg = max(1.0, e.attack * 1.0 - b.p.defense * 0.0)   # 灵兽扑击 attack_ratio=1.0
    my_rounds = math.ceil(e.hp / max(1.0, best_dmg))
    e_rounds = math.ceil(b.p.hp / e_dmg)
    if b.p.hp <= b.p.hp_max * 0.3 or my_rounds > e_rounds - 1:
        return "flee"
    # 灵气不够就平砍（不耗灵）——**不要聚气**：聚气一轮等于白挨一击
    return best_key


def _fight(g, battle_stats: dict, verbose: bool = False, tag: int = 0) -> str:
    """把当前战斗打完（bot 逐轮排动作）。返回结局 win/lose/fled。"""
    b = g.battle()
    battle_stats["battles"] = battle_stats.get("battles", 0) + 1
    if verbose:
        print(f"  T{tag} 遇敌【{b.e.name}】HP{b.e.hp} vs 我HP{b.p.hp}")
    outcome = ""
    guard = 0
    # 开局决定一次：打不过就逃（逃不掉/或中途濒死再考虑），避免在"逃不掉"里空转
    flee_first = _battle_decision(g) == "flee"
    while g.battle_active() and guard < 200:
        if guard == 0 and flee_first:
            key = "flee"
        else:
            key = _battle_decision(g)
            if key == "flee":
                key = "attack"          # 开局已判定该逃；之后一律打完
        r = g.step("battle_action", cmd=key)
        if verbose:
            tail = r.text.splitlines()[-1] if r.text else ""
            print(f"  T{tag}B{guard} {key} -> {tail}")
        guard += 1
        if r.battle_over:
            outcome = r.battle_over
            break
    battle_stats[outcome or "fled"] = battle_stats.get(outcome or "fled", 0) + 1
    return outcome or "fled"


# ---------- P3 功法链 bot（保守、低方差） ----------
def _better_than(p, gf) -> bool:
    """gf 是否比现主修明确更优（加成+0.05 且技能数≥旧 且含攻击技；看懂前置由调用方保证）。"""
    cur_gf = G.GONGFA.get(p.main_gongfa)
    if cur_gf is None:
        return True
    if gf.cultivate_bonus < cur_gf.cultivate_bonus + 0.05:
        return False
    if len(gf.skill_ids) < len(cur_gf.skill_ids):
        return False
    if not any(SK.SKILLS[s].kind == "attack" for s in gf.skill_ids):
        return False
    return True


def _main_cand(p):
    """未拥有候选更强主修功法（看懂 + 含攻击技 + 明确更优）。返回 Gongfa 或 None。"""
    for gf in sorted(G.GONGFA.values(), key=lambda x: x.price):
        if not gf.market or gf.slot_type != "main":
            continue
        if gf.id == p.main_gongfa or gf.id in (p.owned_gongfa or []):
            continue
        if p.realm_idx < gf.tier:
            continue  # 需看懂才能参悟
        if not _better_than(p, gf):
            continue
        return gf
    return None


def _owned_better_main(p):
    """已拥有且未装主修、明确更优的主修功法中加成最高者（优先换装，防买而不用）。"""
    best = None
    for gid in (p.owned_gongfa or []):
        gf = G.GONGFA.get(gid)
        if gf is None or gf.slot_type != "main" or gf.id == p.main_gongfa:
            continue
        if p.realm_idx < gf.tier or not _better_than(p, gf):
            continue
        if best is None or gf.cultivate_bonus > G.GONGFA[best].cultivate_bonus:
            best = gid
    return best


def _gongfa_tick(g, turns: int) -> bool:
    """P3 功法链一步（一次动作）：吐纳诀入门装主修 / 换更强的已有主修 /
    坊市购新候选 / 参悟解锁技能。返回 True = 本回合已投入功法动作。"""
    p = g.state.player
    # 1) 开局：吐纳诀 参悟至 FAM_ENTRY → learn 装主修（此后效率含 +5% 永久被动）
    if p.main_gongfa is None:
        fam = p.familiarity.get(G.TUNA_JUE, 0)
        if G.TUNA_JUE in p.owned_gongfa and fam < S.FAM_ENTRY:
            days = max(1, math.ceil((S.FAM_ENTRY - fam) / S.FAMILIARITY_PER_DAY))
            g.step("comprehend", gongfa=G.name_of(G.TUNA_JUE), days=days)
            return True
        if G.TUNA_JUE in p.owned_gongfa:
            g.step("learn", gongfa=G.name_of(G.TUNA_JUE), slot="main")
            return True
        return False
    # 2) 换装"已拥有且更优"的主修：先参悟入门 → 卸旧主修换装
    owned_better = _owned_better_main(p)
    if owned_better is not None:
        fam = p.familiarity.get(owned_better, 0)
        if fam < S.FAM_ENTRY:
            days = max(1, math.ceil((S.FAM_ENTRY - fam) / S.FAMILIARITY_PER_DAY))
            g.step("comprehend", gongfa=G.name_of(owned_better), days=days)
            return True
        g.step("forget", slot="main")
        g.step("learn", gongfa=G.name_of(owned_better), slot="main")
        return True
    # 3) 未拥有候选：坊市且买得起 → 购得入领悟池（下回合走 2 参悟换装）
    cand = _main_cand(p)
    if cand is not None and p.location == ST.SHISHI and p.spirit_stones >= cand.price + 40:
        g.step("buy", item=str(cand.id), qty=1)
        return True
    # 4) 主修技能参悟：修为未满时隔周期把部分闭关日数投参悟主修，
    #    直至其全部技能 unlock_fam 达到（熟悉度只升不降）
    cur_gf = G.GONGFA.get(p.main_gongfa)
    if cur_gf is not None and p.exp < p.exp_cap():
        target = max([SK.SKILLS[s].unlock_fam for s in cur_gf.skill_ids] or [0])
        fam = p.familiarity.get(p.main_gongfa, 0)
        if fam < target and turns % 3 == 0:
            days = max(1, min(math.ceil((target - fam) / S.FAMILIARITY_PER_DAY), 90))
            g.step("comprehend", gongfa=G.name_of(p.main_gongfa), days=days)
            return True
    return False


def play(seed: int, max_turns: int = 20000, verbose: bool = False,
         battle_stats: dict = None):
    g = Game(seed=seed)
    p = g.state.player
    if battle_stats is None:
        battle_stats = {}
    print(f"seed={seed}  {p.name}  {p.spirit_root} 效率x{p.root_mult:.2f}"
          f" 主修:{G.name_of(p.main_gongfa) if p.main_gongfa else '无'} 灵石{p.spirit_stones}")
    turns = 0
    outcome = "回合上限"
    while p.alive and turns < max_turns:
        # 0) 战斗会话：上一轮探索触发的战斗先打完
        if g.battle_active():
            _fight(g, battle_stats, verbose, turns)
        # 1) 已至顶峰
        if p.realm_idx >= S.MAX_REALM and p.exp >= p.exp_cap():
            outcome = "通关·化神大圆满"
            break
        # 2) 心魔过重先清心
        if p.heart_demon > 50:
            if p.location != ST.SHISHI:
                g.step("travel", site=str(ST.SHISHI))
            if _q(p, P.QINGXIN) == 0 and p.spirit_stones >= P.by_id(P.QINGXIN).price:
                g.step("buy", item=str(P.QINGXIN), qty=1)
            if _q(p, P.QINGXIN) > 0:
                g.step("use_pill", item=str(P.QINGXIN))
                if verbose:
                    print(f"  T{turns} 服清心丹 心魔→{p.heart_demon}")
            else:
                g.step("age_pass", days=30)
                if verbose:
                    print(f"  T{turns} 心魔高无药，静养压制")
        # 2.5) P3 功法链（参悟入门/装主修/换装/解锁技能）
        if _gongfa_tick(g, turns):
            turns += 1
            continue
        cand = _main_cand(p)
        if cand is not None and p.location != ST.SHISHI \
                and p.spirit_stones >= cand.price + 80:
            g.step("travel", site=str(ST.SHISHI))
            if verbose:
                print(f"  T{turns} 灵石富余→回坊市购更强主修（{cand.name}）")
            turns += 1
            continue
        # 3) 修为满则准备突破
        if p.exp >= p.exp_cap():
            need = _needs(p)
            if need == "可突破":
                r = g.step("breakthrough")
                if verbose:
                    print(f"  T{turns} {r.text[:90]}")
            elif need == "缺灵石":
                site = _pick_site(p)
                r = g.step("explore", site=str(site))
                if verbose:
                    print(f"  T{turns} 缺灵石→探索 {r.text[-60:]}")
            else:  # 缺突破丹
                pill_name = need[1:]
                pid = P.ID_BY_NAME.get(pill_name)
                if pid is None:
                    site = _pick_site(p)
                    g.step("explore", site=str(site))
                    continue
                if p.location != ST.SHISHI:
                    g.step("travel", site=str(ST.SHISHI))
                if p.spirit_stones >= P.by_id(pid).price:
                    g.step("buy", item=str(pid), qty=1)
                    if verbose:
                        print(f"  T{turns} 坊市购{pill_name}")
                else:
                    site = _pick_site(p)
                    g.step("explore", site=str(site))
                    if verbose:
                        print(f"  T{turns} 灵石不足买{pill_name}→探索")
        else:
            need_days = int((p.exp_cap() - p.exp) / (S.BASE_DAILY_EXP * _main_mult(p))) + 1
            days = min(need_days, 120)
            use_pill = _q(p, P.JULING) > 0
            g.step("cultivate", days=days, use_pill=use_pill)
            if verbose and turns % 30 == 0:
                print(f"  T{turns} 闭关{int(p.exp)}/{p.exp_cap()}")
        turns += 1

    if not p.alive:
        outcome = f"道陨·{p.death_cause}"
    print(f"  结果: {outcome} | 境界档 {p.realm_idx} ({p.realm_name()}) | 年 {p.age_years:.0f} "
          f"| 心魔 {p.heart_demon} | 灵石 {p.spirit_stones} | 背包 {p.inventory}")
    print(f"  编年史 {len(g.state.chronicle.entries)} 条")
    return p.realm_idx, p.age_years, outcome


class _Tee:
    """同时写多个流（控制台 + 日志文件）。"""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for s in self.streams:
            s.write(data)

    def flush(self):
        for s in self.streams:
            s.flush()

    def isatty(self):
        return False


def _open_log(arg_log):
    """arg_log: None=不写日志；'__auto__'=自动命名；其它=文件名。返回文件对象或 None。"""
    if arg_log is None:
        return None
    if arg_log == "__auto__":
        logs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
        os.makedirs(logs_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        arg_log = os.path.join(logs_dir, f"smoke-{ts}.log")
    f = open(arg_log, "w", encoding="utf-8")
    print(f"▶ 日志写入: {os.path.abspath(arg_log)}")
    return f


def main(argv=None):
    ap = argparse.ArgumentParser(description="引擎冒烟测试（自动 bot 打局）")
    ap.add_argument("seed", type=int, nargs="?", default=None,
                    help="固定种子跑单局（verbose）；省略则默认 20 局统计")
    ap.add_argument("--log", nargs="?", const="__auto__", default=None,
                    help="输出 tee 到日志文件；不带文件名则自动生成 logs/smoke-<时间戳>.log")
    ap.add_argument("--lives", type=int, default=20, help="统计模式的局数（默认 20）")
    args = ap.parse_args(argv)

    logf = _open_log(args.log)
    if logf is not None:
        sys.stdout = _Tee(sys.__stdout__, logf)

    bstats = {}
    if args.seed is not None:
        play(args.seed, verbose=True, battle_stats=bstats)
        print(f"  战斗统计: {bstats}")
    else:
        outcomes = {}
        total = 0
        for s in range(args.lives):
            r, age, oc = play(1000 + s, battle_stats=bstats)
            total += r
            key = oc.split("·")[0]
            outcomes[key] = outcomes.get(key, 0) + 1
        print(f"\n{args.lives} 局平均最终档位: {total/args.lives:.1f} | 结局分布: {outcomes}")
        print(f"{args.lives} 局战斗统计: 次数 {bstats.get('battles', 0)}"
              f" | 胜 {bstats.get('win', 0)} | 负 {bstats.get('lose', 0)}"
              f" | 逃 {bstats.get('fled', 0)}")

    if logf is not None:
        sys.stdout.flush()
        logf.close()
        sys.stdout = sys.__stdout__
        print(f"▶ 日志已保存")


if __name__ == "__main__":
    main()
