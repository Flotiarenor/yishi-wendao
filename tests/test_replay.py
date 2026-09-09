"""指纹 / 重放单测（tools/replay.py）。

覆盖：
  1. 指纹字段齐全、摘要稳定、随机游标是实时值
  2. script 模式：同种子 + 同脚本 → 逐位一致；不同种子 → 不同
  3. bot 模式：同一局重跑 digest 一致（确定性护栏）
  4. compare：能逐字段报差异；digest 随字段变化

运行：.venv\\Scripts\\python.exe -X utf8 -m tests.test_replay
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.game import Game
from tools import replay as RP

_PASS = 0
_FAIL = 0


def check(name: str, cond: bool, detail: str = ""):
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  [OK] {name}")
    else:
        _FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


STEPS = [
    {"action": "cultivate", "kwargs": {"days": 30}},
    {"action": "status"},
    {"action": "explore", "kwargs": {"site": "1000001"}},
]

print("== 1 指纹 ==")
fp = RP.run_script(42, STEPS)
required = {"seed", "turn", "day", "rng_counter", "realm_idx", "exp", "age_years",
            "lifespan_years", "heart_demon", "karma", "alive", "spirit_stones", "qi",
            "location", "inventory", "main_gongfa", "owned_gongfa", "familiarity",
            "battle_gongfa", "shenfa_gongfa", "chronicle_len", "outcome",
            "steps", "steps_digest", "digest"}
check("指纹字段齐全", required <= set(fp), f"缺 {required - set(fp)}")
check("脚本模式记录逐步结果", len(fp["steps"]) == len(STEPS))
check("rng 游标为实时值（非 state 的旧值）", fp["rng_counter"] > 0, f"{fp['rng_counter']}")
check("digest 为 16 位十六进制", len(fp["digest"]) == 16
      and all(c in "0123456789abcdef" for c in fp["digest"]), fp["digest"])

g = Game(seed=7)
g.step("cultivate", days=30)
fp2 = RP.fingerprint(g)
check("fingerprint(Game) 可直接用", fp2["seed"] == 7 and fp2["turn"] == 1)
check("字段变化 → digest 变化",
      RP.digest({**fp2, "spirit_stones": fp2["spirit_stones"] + 1}) != RP.digest(fp2))

print("== 2 script 模式确定性 ==")
a = RP.run_script(42, STEPS)
b = RP.run_script(42, STEPS)
check("同种子同脚本 digest 一致", a["digest"] == b["digest"], f"{a['digest']} vs {b['digest']}")
check("同种子同脚本逐字段一致", RP.compare(a, b) == [])
c = RP.run_script(43, STEPS)
check("不同种子 digest 不同", a["digest"] != c["digest"])

print("== 3 bot 模式确定性（短局种子 1003） ==")
r1 = RP.run_bot(1003)
r2 = RP.run_bot(1003)
check("同种子重跑 digest 一致", r1["digest"] == r2["digest"], f"{r1['digest']} vs {r2['digest']}")
check("bot 指纹含战斗统计", "battles" in r1 and "wins" in r1)
check("bot 指纹含结局", bool(r1["outcome"]), r1["outcome"])

print("== 4 compare ==")
changed = {**r1, "spirit_stones": r1["spirit_stones"] + 1}
diffs = RP.compare(r1, changed)
check("compare 报出差异", len(diffs) == 1 and "spirit_stones" in diffs[0], str(diffs))
check("compare 忽略 digest 字段本身", RP.compare(r1, {**r1, "digest": "x"}) == [])
check("compare 报缺失键", any("缺失" in d for d in RP.compare(r1, {k: v for k, v in r1.items()
                                                                    if k != "qi"})))
check("_parse_seeds 支持区间与逗号", RP._parse_seeds("1-3,5") == [1, 2, 3, 5],
      str(RP._parse_seeds("1-3,5")))

print(f"\n== 结果：{_PASS} 过 / {_FAIL} 败 ==")
sys.exit(1 if _FAIL else 0)
