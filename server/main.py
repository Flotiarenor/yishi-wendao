"""Web 服务启动入口（P3.6 最小 Web 闭环）。

运行：
  python -m server.main [--host 127.0.0.1] [--port 8000]
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
    ap.add_argument("--port", type=int, default=8000, help="监听端口（默认 8000）")
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
    print(f"仙途文字修仙 · 浏览器访问: http://{args.host}:{args.port}  （Ctrl+C 退出）")
    app = build_app()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    main()
