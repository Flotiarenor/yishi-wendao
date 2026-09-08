"""终端命令行（CLI）壳：第一版可玩闭环。

操作：
  新建：python -m cli.main
  自动模式（测试/管道）：python -m cli.main --seed 42 --auto < 输入流

命令（主循环）：
  s          查看状态
  c N        闭关修炼 N 天
  cw N 功法名 闭关参悟 N 天（熟悉度 → 入门后可装运转池）
  b          尝试突破
  l          本世编年史
  w N        静养度日 N 天
  m          坊市货单（丹药+功法）
  buy 名 N   坊市购买（须在坊市）
  use 名     服用丹药
  g 功法名 [槽位] 装入运转池：无槽位=主修 / 1..4=战斗槽 / s=身法槽（learn）
  gf [槽位]  卸下槽位功法：无槽位=主修（forget）
  gd [功法名] 书库列表 / 单本详情（P3 理解锁：未看懂只显书名层级来历）
  q          结束本世（结算）
  undo       回溯到上一节点（杀戮尖塔式，只退一步）
  save       手动存档

战斗（探索遇敌自动进入，结束后自动回主循环）：
  ba 1 平砍 / ba 2 技能名 / ba 3 防御 / ba 4 遁走 / ba 5 聚气
  （auto 模式下由内置 bot 自动打完全场）
"""

import argparse
import random
import sys


def _utf8():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdin.reconfigure(encoding="utf-8")
    except Exception:
        pass


def parse_args(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=None, help="固定种子")
    ap.add_argument("--name", type=str, default="", help="道号/姓名")
    ap.add_argument("--auto", action="store_true", help="自动模式：从 stdin 读命令")
    ap.add_argument("--resume", action="store_true", help="续玩最近存档")
    return ap.parse_args(argv)


MENU = """
━━━ 仙途 · 菜单 ━━━
  s    查看状态          c N[ p] 闭关 N 天（p=用聚灵丹）
  cw N 功法名 参悟 N 天   b    尝试突破        l    编年史
  m    坊市货单          buy 品名 [数量] 购买（须在坊市）
  g 功法名 [槽位] 装入运转池（空=主修/1~4=战斗/s=身法）
  gf [槽位] 卸下槽位功法   gd [功法名] 书库/详情
  t 地点  前往地点       e 地点  探索地点（采灵石/寻丹）
  use 品名  服用丹药     w N  静养 N 天
  undo 回溯一步          save 存档   q 结束本世
  （战斗中：ba 1平砍 ba 2技能 ba 3防御 ba 4遁走 ba 5聚气）
━━━━━━━━━━━━━━━━━━━━━━━"""


def prompt(gs, auto: bool) -> str:
    if auto:
        line = sys.stdin.readline()
        return line.strip()
    try:
        return input("\n指令> ").strip()
    except EOFError:
        return "q"


# ---------- 战斗子循环 ----------

def _battle_cmd(line: str):
    """解析战斗指令行（可带 ba 前缀）。返回 (canonical_action, 技能输入 or None)；无法识别返回 None。

    例子：ba 1 / ba 2 烈焰斩 / ba skill 灵力冲击 / ba 3 / ba 4 / ba 5
    """
    parts = line.split()
    if not parts:
        return None
    if parts[0].lower() in ("ba", "battle"):
        parts = parts[1:]
        if not parts:
            return None
    head = parts[0].lower()
    if head in ("1", "attack", "atk", "平砍", "a"):
        return ("attack", None)
    if head in ("2", "skill", "技", "技能", "s"):
        rest = " ".join(parts[1:]).strip()
        return ("skill", rest or None)
    if head in ("3", "defend", "def", "防御", "防", "d"):
        return ("defend", None)
    if head in ("4", "flee", "run", "遁走", "逃", "f"):
        return ("flee", None)
    if head in ("5", "gather", "聚气", "聚", "g"):
        return ("gather", None)
    # 其余（技能中文名/编号）→ 视为施放技能
    return ("skill", line.strip())


def _auto_battle_cmd(b):
    """CLI auto 模式内置 bot（简单策略）：自己 HP<30% 遁走；
    有克制该敌的攻击技能且灵气够 → 放技能；否则平砍。
    """
    if b.p_hp < b.p_hp_max * 0.3:
        return "flee", None
    for sk in b.available_skills():
        if sk.kind == "attack" and b.p_qi >= sk.qi_cost and b.ke(sk.element) > 1.0:
            return "skill", sk.id
    return "attack", None


def main(argv=None):
    _utf8()
    args = parse_args(argv)
    from engine.game import Game
    from cli import savefile as sv

    g = None
    # 续玩 or 新建
    if args.resume:
        saves = sv.list_saves()
        runs = sorted({int(f.split("_")[1].split(".")[0]) for f in saves if f.startswith("run_") and not ".cp." in f})
        if runs:
            seed = runs[-1]
            data = sv.read(seed)
            g = Game(seed=seed, load=data)
            print(f"续玩种子 {seed}")
        else:
            print("无存档，新建游戏。")
    if g is None:
        seed = args.seed if args.seed is not None else random.randint(0, 0xFFFFFFFF)
        g = Game(seed=seed, name=args.name)
        print(f"━━━ 新一世 · 种子 {seed} ━━━")
        print(g.step("status").text)

    def run_battle_session():
        """战斗子循环：交互读 ba 指令，auto 用内置 bot 自动打完；结束后自动回主循环。"""
        guard = 0
        while g.battle_active() and guard < 500:
            b = g.battle()
            if args.auto:
                act, skid = _auto_battle_cmd(b)
            else:
                print(b.view())
                print("战斗动作：1 平砍 ｜ 2 技能 <名> ｜ 3 防御 ｜ 4 遁走 ｜ 5 聚气 ｜ q 放弃")
                line = prompt(g.state, False)
                low = (line or "").strip().lower()
                if low in ("q", "quit", "exit", "放弃", "abandon", "undo"):
                    ok = g.load_checkpoint()
                    if ok:
                        print("你放弃了战斗，退回进入战斗前的节点。")
                    else:
                        g.quit_battle()
                        print("你放弃了这场战斗（无回溯节点，就地脱离）。")
                    break
                parsed = _battle_cmd(line)
                if parsed is None:
                    print("指令格式：ba 1 ｜ ba 2 <技能名> ｜ ba 3 ｜ ba 4 ｜ ba 5")
                    continue
                act, skid = parsed
            res = g.step("battle_action", cmd=act, skill_id=skid)
            print(res.text)
            guard += 1
        sv.write(seed, g.snapshot())

    try:
        while True:
            p = g.state.player
            if not p.alive:
                break
            if g.battle_active():
                run_battle_session()
                continue
            print(MENU)
            cmd = prompt(g.state, args.auto)
            if not cmd:
                continue
            parts = cmd.split()
            op = parts[0].lower()

            def arg(i: int, default: str = "") -> str:
                return parts[i] if len(parts) > i else default

            def num(i: int, default: int = 30) -> int:
                return int(parts[i]) if len(parts) > i and parts[i].lstrip("-").isdigit() else default

            # 消耗时间/资源类动作：先存节点，完成后落盘
            def risky(action_fn):
                g.save_checkpoint()
                sv.write(seed, g.snapshot(), checkpoint=True)
                res = action_fn()
                print(res.text)
                sv.write(seed, g.snapshot())
                return res

            def slot_arg(i: int, default: str = "") -> str:
                """槽位参数：1..4 → battleN；s/身法 → shenfa；其余 → 原样。"""
                s = arg(i, default).strip()
                if s.isdigit():
                    return f"battle{s}"
                if s.lower() in ("s", "身法", "身法槽"):
                    return "shenfa"
                return s

            if op == "s":
                print(g.step("status").text)
            elif op == "m":
                print(g.step("market").text)
            elif op == "c":
                use_pill = arg(2, "").lower() in ("p", "pill", "1", "y")
                risky(lambda: g.step("cultivate", days=num(1), use_pill=use_pill))
            elif op == "cw":
                risky(lambda: g.step("comprehend", gongfa=arg(2), days=num(1)))
            elif op == "w":
                risky(lambda: g.step("age_pass", days=num(1)))
            elif op == "b":
                risky(lambda: g.step("breakthrough"))
            elif op == "t":
                risky(lambda: g.step("travel", site=arg(1)))
            elif op == "e":
                risky(lambda: g.step("explore", site=arg(1)))
            elif op == "buy":
                risky(lambda: g.step("buy", item=arg(1), qty=num(2, 1)))
            elif op == "use":
                risky(lambda: g.step("use_pill", item=arg(1)))
            elif op == "g":
                res = g.step("learn", gongfa=arg(1), slot=slot_arg(2, "main"))
                print(res.text)
                sv.write(seed, g.snapshot())
            elif op == "gf":
                res = g.step("forget", slot=slot_arg(1, "main"))
                print(res.text)
                sv.write(seed, g.snapshot())
            elif op == "gd":
                print(g.step("gongfa_detail", gongfa=arg(1)).text)
            elif op == "l":
                for line in g.step("chronicle").lines:
                    print(line)
            elif op == "undo":
                ok = g.load_checkpoint()
                print("已回溯到上一节点。" if ok else "无可回溯节点。")
                sv.write(seed, g.snapshot())
            elif op == "save":
                sv.write(seed, g.snapshot())
                print("已存档。")
            elif op == "q":
                print("你选择了结束此世。")
                break
            else:
                print("未知指令。")
    except KeyboardInterrupt:
        print("\n（中断）")
    finally:
        sv.write(seed, g.snapshot())
        # 结算
        p = g.state.player
        print("\n" + "═" * 30)
        if not p.alive:
            print(f"【道陨】{p.name} · {p.death_cause}")
        else:
            print(f"【此世终】{p.name} · {p.realm_name()} · 年{p.age_years:.0f}岁")
        for line in g.step("chronicle").lines:
            print(line)


if __name__ == "__main__":
    main()
