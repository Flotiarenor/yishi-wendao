"""项目唯一入口（仓库根级，不放在任何子文件夹内）。

用法（在项目根目录执行，用虚拟环境的 python）：

    python main.py                        # 默认：起 Web 壳，浏览器玩
    python main.py web [--host H --port P]
    python main.py cli [--seed N] [--resume] [--auto] [--name 道号]
    python main.py smoke [--lives 20] [--log]     # 自动 bot 回归
    python main.py test                            # 跑全部测试（单测 + 冒烟）

说明：
  - 子包内仍保留 `python -m cli.main` / `python -m server.main` 入口（调试与兼容用），
    本文件只是把入口统一到仓库根，避免"入口藏在文件夹里"。
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
  python main.py cli [--seed N]   终端调试壳（--resume 续玩最近存档）
  python main.py smoke [--lives N] [--log]   自动 bot 回归（记录分布与战斗统计）
  python main.py test             跑全部测试：test_battle / test_gongfa_deep / test_server / smoke
"""


def _run_web(argv):
    from server.main import main as web_main
    web_main(argv)


def _run_cli(argv):
    from cli.main import main as cli_main
    cli_main(argv)


def _run_smoke(argv):
    from tests.smoke import main as smoke_main
    smoke_main(argv)


def _run_tests(argv):
    """依次跑全部测试（子进程隔离；任一失败即非零退出）。"""
    py = sys.executable
    targets = [
        ("效果系统单测", [py, "-X", "utf8", os.path.join(ROOT, "tests", "test_effects.py")]),
        ("战斗单测", [py, "-X", "utf8", os.path.join(ROOT, "tests", "test_battle.py")]),
        ("功法深层单测", [py, "-X", "utf8", os.path.join(ROOT, "tests", "test_gongfa_deep.py")]),
        ("Web 壳单测", [py, "-X", "utf8", os.path.join(ROOT, "tests", "test_server.py")]),
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
    elif cmd == "cli":
        _run_cli(argv[1:])
    elif cmd == "smoke":
        _run_smoke(argv[1:])
    elif cmd == "test":
        _run_tests(argv[1:])
    elif cmd in ("-h", "--help", "help"):
        print(USAGE)
    else:
        print(f"未知子命令：{argv[0]}\n")
        print(USAGE)
        sys.exit(2)


if __name__ == "__main__":
    main()
