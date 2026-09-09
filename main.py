"""项目唯一入口（仓库根级，不放在任何子文件夹内）。

用法（在项目根目录执行，用虚拟环境的 python）：

    python main.py                        # 默认：起 Web 壳，浏览器玩
    python main.py web [--host H --port P]
    python main.py smoke [--lives 20] [--log]     # 自动 bot 回归
    python main.py test                            # 跑全部测试（单测 + 冒烟）
    python main.py check [--strict]                # content/ 数据校验（开发期）

开发期工具（详见 tools/）：
    python -m tools.gen_skill --in draft.json --strict   # 技能生成器（手写/AI/随机共用）
    python -m tools.replay --mode bot --seeds 1001-1020  # 指纹/重放（A/B 对照）
    python -m tools.dummy                                # 木桩试招

说明：
  - CLI 已于 R3.4 下线（正式形态是 Web 壳）；子包 `python -m server.main` 入口保留。
  - 引擎（engine/）与内容（content/）保持零 I/O、零 Web 依赖；本文件不做任何玩法逻辑。
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

USAGE = """仙途 · 文字修仙 —— 统一入口

  python main.py                  起 Web 壳（默认，浏览器打开 http://127.0.0.1:8000）
  python main.py web [--port N]   同上（可指定端口）
  python main.py smoke [--lives N] [--log]   自动 bot 回归（记录分布与战斗统计）
  python main.py test             跑全部测试（时间轴/动作/战斗/加固/内容工具 + 冒烟）
  python main.py check [--strict]  content/ 数据校验（id/引用/取值；--strict 警告也失败）

开发期工具（python -m tools.<名>，详见 tools/）：
  gen_skill  技能生成器（draft → 校验 → content/skills.py 代码 / JSON）
  replay     指纹 / 重放（固定种子 → 可对比快照，A/B 对照）
  dummy      木桩试招
"""


def _run_web(argv):
    from server.main import main as web_main
    rc = web_main(argv)
    if rc:
        sys.exit(rc)


def _run_smoke(argv):
    from tests.smoke import main as smoke_main
    smoke_main(argv)


def _run_check(argv):
    from tools.content_check import main as check_main
    check_main(argv)


def _run_tests(argv):
    """依次跑全部测试（子进程隔离；任一失败即非零退出）。"""
    py = sys.executable
    targets = [
        ("效果系统单测", [py, "-X", "utf8", os.path.join(ROOT, "tests", "test_effects.py")]),
        ("引擎加固单测", [py, "-X", "utf8", os.path.join(ROOT, "tests", "test_hardening.py")]),
        ("时间轴/规则单测", [py, "-X", "utf8", os.path.join(ROOT, "tests", "test_clock.py")]),
        ("动作模型单测", [py, "-X", "utf8", os.path.join(ROOT, "tests", "test_action.py")]),
        ("时间轴战斗单测", [py, "-X", "utf8", os.path.join(ROOT, "tests", "test_battle_time.py")]),
        ("功法深层单测", [py, "-X", "utf8", os.path.join(ROOT, "tests", "test_gongfa_deep.py")]),
        ("Web 壳单测", [py, "-X", "utf8", os.path.join(ROOT, "tests", "test_server.py")]),
        ("内容工具单测", [py, "-X", "utf8", os.path.join(ROOT, "tests", "test_content_tools.py")]),
        ("指纹/重放单测", [py, "-X", "utf8", os.path.join(ROOT, "tests", "test_replay.py")]),
        ("冒烟回归 20 局", [py, "-X", "utf8", "-m", "tests.smoke"]),
    ]
    failed = []
    for name, cmd in targets:
        print(f"\n===== {name} =====")
        rc = subprocess.call(cmd, cwd=ROOT)
        if rc != 0:
            failed.append(name)
    if failed:
        print(f"\n[FAIL] 未通过：{'、'.join(failed)}")
        sys.exit(1)
    print("\n[OK] 全部测试通过")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0].lower() if argv else "web"
    if cmd in ("web", "serve", "server"):
        _run_web(argv[1:])
    elif cmd == "smoke":
        _run_smoke(argv[1:])
    elif cmd == "test":
        _run_tests(argv[1:])
    elif cmd in ("check", "content"):
        _run_check(argv[1:])
    elif cmd in ("-h", "--help", "help"):
        print(USAGE)
    else:
        print(f"未知子命令：{argv[0]}\n")
        print(USAGE)
        sys.exit(2)


if __name__ == "__main__":
    main()
