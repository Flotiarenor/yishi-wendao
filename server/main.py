"""Web 服务启动入口（P3.6 最小 Web 闭环）。

运行：
  python -m server.main [--host 127.0.0.1] [--port 8044]
浏览器打开 http://<host>:<port> 即进入极简面板（开发期直接浏览器玩，
阶段 2/3 的 Vue3 + pywebview 桌面壳复用同一 app 工厂）。

供测试/程序化使用：build_app(config=None) -> FastAPI（只建 app，不启动）。
"""
import argparse
import socket

import uvicorn


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="仙途文字修仙 · Web 壳（FastAPI）")
    ap.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1）")
    ap.add_argument("--port", type=int, default=8044, help="监听端口（默认 8044）")
    ap.add_argument("--debug", action="store_true",
                    help="开发调试模式：新局自动发灵石/丹药，并开放 step('debug') 动作")
    ap.add_argument("--stones", type=int, default=None,
                    help="配合 --debug：新局发放的灵石数（默认 999999）")
    return ap.parse_args(argv)


def build_app(config: dict = None):
    """只返回 FastAPI app（不启动服务），供测试导入 / 程序化启动复用。"""
    from server.app import create_app
    return create_app(config)


def _port_in_use(host: str, port: int) -> bool:
    """端口是否已被监听（**不加** SO_REUSEADDR——Windows 下加了会误判为可用）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return False
        except OSError:
            return True


def _free_port_hint(port: int) -> str:
    return (
        f"端口 {port} 已被占用——通常是上次没退出的服务残留"
        f"（VSCode 关终端不会自动杀子进程）。\n"
        f"  查占用：netstat -ano | findstr :{port}\n"
        f"  结束它：taskkill /PID <PID> /T /F\n"
        f"  或换端口：python main.py web --port 8044"
    )


def main(argv=None):
    args = parse_args(argv)
    if _port_in_use(args.host, args.port):
        print(f"⚠ {_free_port_hint(args.port)}")
        return 1
    if args.debug or args.stones is not None:
        # 调试模式：进程级开关 + "新局自动发资源"配置（见 engine/debug.py）
        from engine import debug as DBG
        DBG.enable(stones=(args.stones if args.stones is not None else DBG.DEFAULT_STONES))
        print(f"⚠ 调试模式已开启（--debug）：新局自动发 {DBG.peek_pending().stones} 灵石，"
              f"并可用 step('debug', key=…) 随时补资源。**勿在正式游玩时使用**")
    else:
        from engine import debug as DBG
        if DBG.sync_from_env():
            print(f"⚠ 调试模式已开启（XIUXIAN_DEBUG）：新局自动发 {DBG.DEFAULT_STONES} 灵石")
    print(f"仙途文字修仙 · 浏览器访问: http://{args.host}:{args.port}  （Ctrl+C 退出）")
    app = build_app()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    main()
