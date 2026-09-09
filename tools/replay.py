"""指纹 / 重放工具：把"引擎行为有没有变"变成可对比的确定性快照。

背景
----
P3.8 / P3.9 的 A/B 对照是手搓 `git worktree` + 临时脚本，跑完就丢。本工具把它固化：

  * **指纹**：固定种子跑一局，抽出与玩法/随机流相关的稳定字段（境界/修为/寿元/灵石/
    背包/熟悉度/主功法/rng 游标/战斗统计…），规范化成 JSON + sha256 摘要。
  * **重放**：两种模式
      - `bot`    ：跑 `tests.smoke.play_game`（同一套 bot 策略）→ 整局指纹；
      - `script` ：按显式动作脚本重放 → 逐步结果 + 终局指纹（微复现某个 bug 用）。
  * **对比**：`--out baseline.json` 存基线，改代码后 `--compare baseline.json` 逐字段 diff。
    跨版本对照时，在旧提交里跑一次存 JSON，再在新提交里 `--compare`。

判读原则（沿用 `docs/实现路线图.md` P10 指标哲学）
--------------------------------------------------
指纹变了**不等于数值该调**，先问"是不是引擎行为变了"；`bot` 模式的结局分布只是
"固定种子+固定策略"的回归指纹，不是平衡指标。

运行
----
  .venv\\Scripts\\python.exe -X utf8 -m tools.replay --mode bot --seeds 1001-1020 --out base.json
  .venv\\Scripts\\python.exe -X utf8 -m tools.replay --mode bot --seeds 1001-1020 --compare base.json
  .venv\\Scripts\\python.exe -X utf8 -m tools.replay --mode script --script script.json
  .venv\\Scripts\\python.exe -X utf8 -m tools.replay --mode bot --seeds 1001-1005 --repeat 2

script 文件格式：
  {"seed": 42, "steps": [
     {"action": "cultivate", "kwargs": {"days": 30}},
     {"action": "breakthrough"},
     {"action": "explore", "kwargs": {"site": "1000001"}}
  ]}
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from engine import settings as S
from engine.game import Game

TOOL_VERSION = 1
_FLOAT_ROUND = {"exp": 6, "age_years": 2, "lifespan_years": 2, "qi": 3}


def _r(v, nd):
    return round(float(v), nd)


def fingerprint(game: Game, *, outcome: str = "", battle_stats: dict = None,
                extra: dict = None) -> dict:
    """一局游戏 → 稳定指纹（键序无关，值已规范化）。"""
    p = game.state.player
    fp = {
        "seed": game.seed,
        "turn": int(game.state.turn),
        "t": int(game.state.t),           # P4：唯一时钟（息）
        "day": int(game.state.day),
        # 用 Rng 的**实时**游标（state.rng_counter 只在 snapshot/落盘时同步，内存里是旧值）
        "rng_counter": int(game.rng.counter),
        "realm_idx": int(p.realm_idx),
        "exp": _r(p.exp, _FLOAT_ROUND["exp"]),
        "age_years": _r(p.age_years, _FLOAT_ROUND["age_years"]),
        "lifespan_years": _r(p.lifespan_years, _FLOAT_ROUND["lifespan_years"]),
        "heart_demon": int(p.heart_demon),
        "karma": int(p.karma),
        "alive": bool(p.alive),
        "death_cause": p.death_cause or "",
        "spirit_stones": int(p.spirit_stones),
        "qi": _r(p.qi, _FLOAT_ROUND["qi"]),
        "location": int(p.location) if isinstance(p.location, int) else str(p.location),
        "inventory": {str(k): int(v) for k, v in sorted(p.inventory.items())},
        "main_gongfa": p.main_gongfa,
        "owned_gongfa": sorted(int(g) for g in (p.owned_gongfa or [])),
        "familiarity": {str(k): int(v) for k, v in sorted((p.familiarity or {}).items())},
        "battle_gongfa": [g for g in (p.battle_gongfa or [])],
        "shenfa_gongfa": [g for g in (p.shenfa_gongfa or [])],
        "chronicle_len": len(game.state.chronicle.entries),
        "outcome": outcome,
    }
    if battle_stats is not None:
        fp["battles"] = int(battle_stats.get("battles", 0))
        fp["wins"] = int(battle_stats.get("win", 0))
        fp["losses"] = int(battle_stats.get("lose", 0))
        fp["fled"] = int(battle_stats.get("fled", 0))
    if extra:
        fp.update(extra)
    return fp


def digest(fp: dict) -> str:
    """指纹 → 短摘要（sha256 前 16 位）。"""
    blob = json.dumps(fp, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def run_bot(seed: int, max_turns: int = 20000) -> dict:
    """用 smoke bot 跑一整局，返回指纹。"""
    from tests import smoke
    stats: dict = {}
    game, outcome = smoke.play_game(seed, max_turns=max_turns,
                                    battle_stats=stats, out=lambda *a, **k: None)
    fp = fingerprint(game, outcome=outcome, battle_stats=stats)
    fp["digest"] = digest(fp)
    return fp


def run_script(seed: int, steps: list, max_turns: int = 20000) -> dict:
    """按显式动作脚本重放，返回指纹 + 逐步结果。"""
    game = Game(seed=seed)
    trail = []
    for i, step in enumerate(steps):
        action = step.get("action")
        kwargs = dict(step.get("kwargs") or {})
        r = game.step(action, **kwargs)
        trail.append({"i": i, "action": action,
                      "ok": r.ok, "reason": r.reason,
                      "battle_started": bool(r.battle_started),
                      "battle_over": r.battle_over or ""})
    fp = fingerprint(game, extra={"steps": trail,
                                  "steps_digest": digest({"steps": trail})})
    fp["digest"] = digest(fp)
    return fp


def compare(a: dict, b: dict, path: str = "") -> list:
    """递归对比两个指纹 → ["字段: a != b", ...]。"""
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k in ("digest",):
                continue
            p = f"{path}.{k}" if path else str(k)
            if k not in a:
                out.append(f"{p}: 缺失于 A（B={b[k]!r}）")
            elif k not in b:
                out.append(f"{p}: 缺失于 B（A={a[k]!r}）")
            else:
                out.extend(compare(a[k], b[k], p))
    elif a != b:
        out.append(f"{path}: {a!r} != {b!r}")
    return out


def _parse_seeds(expr: str) -> list:
    """'1001-1020,2000' → [1001..1020, 2000]"""
    out = []
    for part in expr.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            out.extend(range(int(lo), int(hi) + 1))
        else:
            out.append(int(part))
    return out


def _load_json(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: str, obj: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=True)


def _meta() -> dict:
    return {"tool_version": TOOL_VERSION, "python": sys.version.split()[0],
            "max_realm": S.MAX_REALM}


def main(argv=None):
    ap = argparse.ArgumentParser(description="指纹 / 重放（固定种子 → 可对比快照）")
    ap.add_argument("--mode", choices=("bot", "script"), default="bot")
    ap.add_argument("--seeds", default="1001-1020",
                    help="种子范围，如 1001-1020,2000（bot 模式）")
    ap.add_argument("--seed", type=int, default=None, help="单种子（script 模式）")
    ap.add_argument("--script", default="", help="script JSON 文件")
    ap.add_argument("--max-turns", type=int, default=20000)
    ap.add_argument("--out", default="", help="把指纹写入 JSON 基线")
    ap.add_argument("--compare", default="", help="与基线 JSON 对比")
    ap.add_argument("--repeat", type=int, default=1,
                    help="每个种子重复跑 N 次并自校验确定性")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args(argv)

    runs: dict = {}
    determinism_fail = []
    if args.mode == "script":
        if not args.script:
            print("[ERROR] script 模式需要 --script FILE")
            return 2
        spec = _load_json(args.script)
        seed = args.seed if args.seed is not None else int(spec.get("seed", 0))
        steps = spec.get("steps", [])
        fps = [run_script(seed, steps, args.max_turns) for _ in range(args.repeat)]
        runs[str(seed)] = fps[0]
        if any(f["digest"] != fps[0]["digest"] for f in fps[1:]):
            determinism_fail.append(seed)
    else:
        for seed in _parse_seeds(args.seeds):
            fps = [run_bot(seed, args.max_turns) for _ in range(args.repeat)]
            runs[str(seed)] = fps[0]
            if any(f["digest"] != fps[0]["digest"] for f in fps[1:]):
                determinism_fail.append(seed)

    payload = {"meta": _meta(), "mode": args.mode, "runs": runs}

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"mode={args.mode} 种子 {len(runs)} 个  tool_version={TOOL_VERSION}")
        for seed, fp in runs.items():
            print(f"  seed {seed:>6}  digest {fp['digest']}  档{fp['realm_idx']:>2} "
                  f"{fp['outcome'] or '(script)':<14} 年{fp['age_years']:>7.2f} "
                  f"rng{fp['rng_counter']:>6} 灵石{fp['spirit_stones']:>5}"
                  + (f" 战斗{fp.get('battles', 0)}" if "battles" in fp else ""))

    if determinism_fail:
        print(f"\n[FAIL] 非确定性种子（同种子重复跑结果不同）：{determinism_fail}")
        return 1

    if args.out:
        _save_json(args.out, payload)
        print(f"→ 基线已写入 {args.out}")

    if args.compare:
        base = _load_json(args.compare)
        base_runs = base.get("runs", {})
        diffs = []
        for seed, fp in runs.items():
            if seed not in base_runs:
                diffs.append(f"seed {seed}: 基线缺失（新增种子）")
                continue
            diffs.extend(compare(base_runs[seed], fp, f"seed{seed}"))
        for seed in sorted(set(base_runs) - set(runs), key=int):
            diffs.append(f"seed {seed}: 基线有但本次未跑")
        if diffs:
            print(f"\n== 指纹对比：{len(diffs)} 处不同 ==")
            for d in diffs:
                print("  " + d)
            return 1
        print(f"\n== 指纹对比：{len(runs)} 个种子逐字段一致 ==")
    return 0


if __name__ == "__main__":
    sys.exit(main())
