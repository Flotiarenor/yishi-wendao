"""桌面壳（pywebview）：把既有的 FastAPI app 塞进一个原生窗口。

**为什么是这个形态**（`docs/Web架构方案.md` §5「双模式」）：
开发期用浏览器（`main.py web`，热更新、可 DevTools），分发期用原生窗口（本文）——
**两者共用同一个 `server.app.create_app()` 与同一个 `frontend/dist`，前端零改动**
（前端一律走 HTTP `/api/*`，不依赖 `window.pywebview.api` 桥）。

⚠️ **窗口身份（Windows 上到底显示什么）——先把话说清楚**：

| 会被看到的地方 | 由谁决定 | 我们的做法 |
|---|---|---|
| 标题栏 / Alt-Tab 名称 | pywebview 窗口 `title` | 传「一世问道 · 文字修仙」 |
| 任务栏图标 | 进程可执行文件或窗口图标 | 传 `icon`（`assets/app.ico`，缺省则用 python 图标） |
| 任务栏分组 / 固定到任务栏 | **AppUserModelID** | `_set_app_user_model_id()` 显式设置为 `YishiWendao.Xiuxian`，并配一个同 AUMID 的快捷方式（`tools/make_shortcut.ps1`） |
| **音量合成器里的名字** | **WebView2（`msedgewebview2.exe`）** | ⚠️ **改不了**——这是 WebView2 的已知限制，任何 WebView2 壳层都一样 |

**关于音量合成器那条**：WebView2 把音频会话标成 `Microsoft Edge WebView2` 而不是宿主应用名，
是**上游未修**的问题（见 `docs/Web架构方案.md` 附录 A.2 的 issue 链接）。本游戏**当前没有音频**，
所以不影响；**要加音效时**按 **A.6 的实测结论**：**音效由宿主进程播、网页侧永不播音频**——
那样音量合成器里就只会有我们自己的那一条活跃会话，不必换壳。
（实测：网页播 → 会话归 `msedgewebview2`；宿主进程播 → 会话归我们自己；
而那台 `msedgewebview2` 会话在网页停音后**只是转为非活跃、不会消失**，
所以千万别"两边同时播"，否则音量合成器里真会出现两个应用。）
**全屏 / 置顶 / 托盘 / 通知**这类系统接口**不受这条限制**——它们是窗口/进程级能力，
在现在这个壳里就能加（拿 `win.native.Handle` 调 Win32，见 §附录 A.4）。

本模块**不做**任何玩法逻辑，只做窗口与进程身份。
"""
import inspect
import os
import socket
import threading
import time

# 进程身份：任务栏分组 / 固定 / 通知都靠它。改它等于换一个"应用"。
APP_USER_MODEL_ID = "YishiWendao.Xiuxian"
APP_TITLE = "一世问道 · 文字修仙"
APP_ICON = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "assets", "app.ico")
# WebView2 的数据目录（放用户目录，避免污染仓库；也避免只读安装目录下起不来）
USER_DATA_DIR = os.path.join(os.path.expanduser("~"), ".yishi-wendao", "webview")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8044


def set_app_user_model_id(aumid: str = APP_USER_MODEL_ID) -> bool:
    """把当前进程的 AppUserModelID 设成我们的 id（Windows 专用；其它平台返回 False）。

    为什么需要它：任务栏把窗口归到哪个图标、能不能固定、通知里显示谁，
    都由 AppUserModelID 决定；不设就会跟着 python.exe 走。
    """
    from ctypes import windll
    try:
        hres = windll.shell32.SetCurrentProcessExplicitAppUserModelID(str(aumid))
        return hres == 0
    except Exception:          # noqa: BLE001 —— 身份设置失败不该让游戏起不来
        return False


def _load_webview():
    """延迟导入 pywebview：没装时要能给出人话提示，而不是 ImportError 栈。"""
    try:
        import webview
        return webview
    except ImportError:
        raise SystemExit(
            "桌面壳需要 pywebview：\n"
            r"  .venv\Scripts\python.exe -m pip install pywebview" "\n"
            "（或者用浏览器模式：python main.py web）"
        )


def build_plan(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
               title: str = APP_TITLE, width: int = 1280, height: int = 860,
               icon: str = None, user_data_dir: str = None) -> dict:
    """**不启动任何东西**，只算出"窗口该怎么开"——便于单测与显式配置。"""
    ico = icon if icon is not None else APP_ICON
    return {
        "host": str(host),
        "port": int(port),
        "url": f"http://{host}:{port}/",
        "title": title,
        "width": int(width),
        "height": int(height),
        "min_size": (960, 640),
        "icon": ico if (ico and os.path.exists(ico)) else None,
        "user_data_dir": user_data_dir or USER_DATA_DIR,
        "aumid": APP_USER_MODEL_ID,
        "app_name": "一世问道",
    }


def _port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return False
        except OSError:
            return True


def _start_server(app, host: str, port: int, timeout: float = 20.0) -> threading.Thread:
    """在后台线程里跑 uvicorn，并**等到端口真的可连**再返回（否则窗口会加载到"连接被拒绝"）。

    `uvicorn.Server.run()` 自己会装信号处理器，而信号只能在主线程装 ——
    所以这里用 `Server(config)` 直接调 `run()`（它内部在非主线程时不会装 handler）。
    """
    import uvicorn
    cfg = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(cfg)
    th = threading.Thread(target=server.run, name="uvicorn", daemon=True)
    th.start()
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.25)
            if s.connect_ex((host, port)) == 0:
                return th
        time.sleep(0.05)
    raise RuntimeError(f"服务端在 {timeout:.0f}s 内没有起来（{host}:{port}）")


def parse_args(argv=None):
    """桌面壳自己的命令行（与 `main.py web` 的开关**不同名**，避免歧义：
    `--debug` 是**游戏**调试（发灵石 / 开 debug 动作），`--devtools` 才是开 F12）。"""
    import argparse
    ap = argparse.ArgumentParser(
        prog="main.py app", description="一世问道 · 桌面壳（pywebview 原生窗口）")
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=860)
    ap.add_argument("--debug", action="store_true",
                    help="游戏调试模式：新局自动发灵石、开放 step('debug')")
    ap.add_argument("--stones", type=int, default=None, help="配合 --debug 的初始灵石")
    ap.add_argument("--devtools", action="store_true", help="打开 DevTools（相当于 F12）")
    return ap.parse_args(argv)


def run(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, devtools: bool = False,
        title: str = APP_TITLE, width: int = 1280, height: int = 860,
        user_data_dir: str = None, on_ready=None) -> int:
    """起服务端 + 原生窗口；窗口关闭即返回（服务端是 daemon 线程，随进程退出）。

    `devtools=True`：额外开 DevTools（相当于浏览器模式的 F12）。
    """
    webview = _load_webview()
    if _port_in_use(host, port):
        print(f"⚠ 端口 {port} 已被占用（可能是上次没退出的服务）——"
              f"换端口：python main.py app --port 8045")
        return 1
    plan = build_plan(host=host, port=port, title=title, width=width, height=height,
                      user_data_dir=user_data_dir)

    from server.app import create_app
    set_app_user_model_id(plan["aumid"])
    print(f"一世问道 · 桌面壳 → {plan['url']}（AppUserModelID={plan['aumid']}）")
    _start_server(create_app(), host, port)
    if on_ready is not None:
        on_ready(plan)                     # 供测试/脚本注入（不弹窗口也能验证接线）

    kw = {}
    if plan["icon"]:
        kw["icon"] = plan["icon"]
    else:
        print("⚠ 未找到 assets/app.ico —— 任务栏会用 python 图标（放一张 ico 即可）")
    webview.create_window(plan["title"], plan["url"],
                          width=plan["width"], height=plan["height"],
                          min_size=plan["min_size"],
                          text_select=True,          # 文字游戏：能选中复制（日志里有用的信息多）
                          zoomable=True)             # 允许 Ctrl+滚轮 缩放（T6 的"缩放"另做，这是兜底）
    # ⚠️ pywebview 6 起 `icon` 属于 **start()**，不再是 create_window 的关键字
    # （5.x 时代在 create_window 上）——按签名探测，别写死版本号。
    start_kw = {"private_mode": False,   # 关掉隐私模式：localStorage 要留（前端靠它存偏好）
                "storage_path": plan["user_data_dir"],
                "debug": bool(devtools)}
    try:
        _sig = inspect.signature(webview.start)
        if "icon" in _sig.parameters:
            start_kw["icon"] = plan["icon"]
    except (TypeError, ValueError):
        pass
    if start_kw.get("icon") is None:
        start_kw.pop("icon", None)
    try:
        webview.start(**start_kw)
    except TypeError as e:
        # 老版本不认识某些关键字（如 storage_path / icon）——去掉重试一次，别让游戏起不来
        print(f"（pywebview 关键字不兼容：{e}；改用最小参数集启动）")
        webview.start(debug=bool(devtools))
    return 0
