"""Web 端真浏览器冒烟（Selenium + Edge）——**补 jsdom 做不到的那一层**。

## 为什么要有它（和 `frontend/e2e/smoke.mjs` 的分工）

`frontend/e2e/smoke.mjs` 跑在 **jsdom** 里，快、适合断言协议与逻辑（reason 映射、队列结构、
localStorage 等）。但 jsdom 有两个**原理性盲区**，本项目已经实际吃过亏：

1. **不加载图片资源** → 舆图底图（`/api/map/img`）在 jsdom 里**从不被请求、从不被绘制**，
   所以"地图画出来没有、画得对不对"**根本无法验证**；
2. **是模拟 DOM** → 点击不判断可操作性，冷启动（建世界 6~10s）期间按钮 `disabled` 时点下去
   会被直接丢掉，只能靠手写"点到生效"重试来兜。

本脚本用**真 Edge**（本机 152.0.4191.66，**与游戏分发的 WebView2 同一版本**，保真度高）补这两点：
- **底图真的画出来了**：从 SVG `<image>` 取 href → 用 canvas 读像素 → 断言"非纯色 + 纸底 + 墨 + 水蓝"；
- **CJK 真的能显示**：量中文字串的渲染宽度（回退字体下中文会塌成窄块/方块）；
- 顺带：真实布局尺寸、点击可操作性、真实引擎不报错。

## 它会自动做什么

起一个**临时存档目录**的服务端（随机空闲端口）→ 无头 Edge → 建新局（等世界建好）→
断言 → 把截图落到 `logs/e2e_web.png` → 关浏览器、停服务 → 失败则非零退出。

## 底图基线

`tests/baselines/map_baseline.json` 存底图的 sha256 与像素统计（**入库，跟着代码走**）。
**地图渲染一改就会变红**——这正是 P4 想要的"改地图必须可验证"
（同类思路：`terrain_checksum`、smoke 指纹）。
首次运行或改完地图后，用 `--update-baseline` 重记基线。

用法：
  .venv\\Scripts\\python.exe -X utf8 tools\\e2e_web.py                # 跑（无头）
  .venv\\Scripts\\python.exe -X utf8 tools\\e2e_web.py --headed       # 看着它跑
  .venv\\Scripts\\python.exe -X utf8 tools\\e2e_web.py --update-baseline
  .venv\\Scripts\\python.exe -X utf8 tools\\e2e_web.py --keep-open    # 跑完不关，便于人工看
"""
import argparse
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

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


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(port: int, save_dir: str):
    """起服务端（子进程），等到 /health 可连。"""
    code = (
        "import sys; sys.path.insert(0, r'%s')\n"
        "import uvicorn\n"
        "from server.app import create_app\n"
        "uvicorn.run(create_app({'save_dir': r'%s'}), host='127.0.0.1', port=%d, log_level='error')\n"
        % (ROOT, save_dir, port)
    )
    proc = subprocess.Popen([sys.executable, "-X", "utf8", "-c", code], cwd=ROOT)
    import urllib.request
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
                if r.status == 200:
                    return proc
        except Exception:
            time.sleep(0.2)
    proc.terminate()
    raise RuntimeError("服务端没起来")


def read_image_stats(driver, href: str) -> dict:
    """把底图当普通图片在页面里解码，读像素统计（同源，canvas 可读）。

    返回 {natural, colors, paper_ratio, ink_ratio, water_ratio, sha256(近似: 由像素采样拼)}。
    """
    # ⚠️ 两个坑：① `execute_async_script` 的超时**默认是 0**（会立刻 TimeoutException），
    # 必须 `set_script_timeout()`；② 异步脚本要**调用最后一个参数（回调）**，
    # 返回 Promise 不会被 driver 等待。
    driver.set_script_timeout(60)
    js = """
    const href = arguments[0];
    const done = arguments[arguments.length - 1];
    (function () {
      const im = new Image();
      im.onload = () => {
        const c = document.createElement('canvas');
        c.width = im.naturalWidth; c.height = im.naturalHeight;
        const ctx = c.getContext('2d');
        ctx.drawImage(im, 0, 0);
        const d = ctx.getImageData(0, 0, c.width, c.height).data;
        let n = 0, paper = 0, ink = 0, water = 0;
        const seen = new Set();
        for (let i = 0; i < d.length; i += 4 * 7) {
          const r = d[i], g = d[i+1], b = d[i+2];
          n++;
          seen.add((r << 16) | (g << 8) | b);
          if (r > 200 && g > 190 && b > 150) paper++;
          if (r < 110 && g < 100 && b < 95) ink++;
          if (b > r + 10 && b > 120) water++;
        }
        done({natural: im.naturalWidth + 'x' + im.naturalHeight,
              colors: seen.size, samples: n,
              paper: paper / n, ink: ink / n, water: water / n});
      };
      im.onerror = () => done(null);
      im.src = href;
    })();
    """
    return driver.execute_async_script(js, href)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Web 端真浏览器冒烟（Selenium + Edge）")
    ap.add_argument("--headed", action="store_true", help="显示浏览器窗口（默认无头）")
    ap.add_argument("--keep-open", action="store_true", help="跑完不关浏览器（人工看效果）")
    ap.add_argument("--update-baseline", action="store_true", help="把当前底图指纹记为基线")
    ap.add_argument("--timeout", type=int, default=120, help="等世界建好的上限（秒）")
    ap.add_argument("--out", default=os.path.join(ROOT, "logs", "e2e_web.png"))
    ap.add_argument("--seed", type=int, default=20260910,
                    help="固定世界种子（默认 20260910）——底图基线必须绑种子，否则每次随机种子都不一致")
    a = ap.parse_args(argv)

    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.edge.options import Options
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait
    except ImportError:
        print("需要 selenium：.venv\\Scripts\\python.exe -m pip install selenium")
        return 2

    port = free_port()
    save_dir = os.path.join(ROOT, "logs", "_e2e_web_saves")
    os.makedirs(save_dir, exist_ok=True)
    print("== 起服务端（临时存档目录，端口 %d）==" % port)
    server = start_server(port, save_dir)

    opts = Options()
    if not a.headed:
        opts.add_argument("--headless=new")
    for arg in ("--disable-gpu", "--window-size=1500,1000", "--no-first-run",
                "--no-default-browser-check", "--force-device-scale-factor=1"):
        opts.add_argument(arg)
    driver = None
    try:
        t0 = time.time()
        driver = webdriver.Edge(options=opts)
        print("  Edge %s 就绪（%.1fs）" % (driver.capabilities.get("browserVersion"), time.time() - t0))

        driver.get(f"http://127.0.0.1:{port}/")
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, "#app")))
        check("页面在真实 Edge 里加载", True, driver.title)
        check("三区骨架就位",
              bool(driver.find_elements(By.CSS_SELECTOR, ".layout .main-slot"))
              and bool(driver.find_elements(By.CSS_SELECTOR, "h2")))

        # CJK 字体：中文渲染宽度应明显大于同长度 ASCII（回退字体下中文会塌/成方块）
        w_cjk = driver.execute_script("""
          const c = document.createElement('canvas').getContext('2d');
          c.font = '20px system-ui, "Microsoft YaHei", sans-serif';
          return c.measureText('青石镇一二三').width;
        """)
        w_ascii = driver.execute_script("""
          const c = document.createElement('canvas').getContext('2d');
          c.font = '20px system-ui, "Microsoft YaHei", sans-serif';
          return c.measureText('abcdef').width;
        """)
        check("中文可正常测量（CJK 字体可用）", w_cjk > w_ascii * 1.5,
              f"中文 {w_cjk:.0f}px vs ASCII {w_ascii:.0f}px")

        # 用**固定种子**开局：先经 API 建局（世界冷启动 6~10s），再让前端读同一档。
        # 为什么不点「新建一世」按钮：那是随机种子，底图基线没法比。
        import urllib.request
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/new",
            data=json.dumps({"seed": a.seed}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=180) as r:
            run_id = json.load(r)["run_id"]
        # 让前端记住"最近一局"再重新载入页面 → bootstrap 自动读这一档
        driver.execute_script("window.localStorage.setItem('xiuxian.lastRun', arguments[0]);", str(run_id))
        driver.get(f"http://127.0.0.1:{port}/")
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, "#app")))
        t1 = time.time()
        WebDriverWait(driver, a.timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "svg.map .towns .tw")))
        towns = len(driver.find_elements(By.CSS_SELECTOR, "svg.map .towns .tw"))
        check("地图就绪（世界已建好，真实引擎）", towns > 0, f"城镇点 {towns} 个，等了 {time.time()-t1:.1f}s")

        # ---- 核心：舆图底图**真的加载并画出来了** ----
        imgs = driver.find_elements(By.CSS_SELECTOR, "svg.map image.basemap")
        check("SVG 里有底图层（<image class=basemap>）", len(imgs) > 0, f"{len(imgs)} 个")
        stats = None
        if imgs:
            href = imgs[0].get_attribute("href") or ""
            check("底图 URL 指向 /api/map/img", "/api/map/img" in href, href[:80])
            stats = read_image_stats(driver, href)
            check("底图能被浏览器解码", bool(stats), "Image.onload 未触发（加载失败）")
            if stats:
                ratio = stats["paper"] + stats["ink"] + stats["water"]
                check("底图不是纯色（有地貌细节）", stats["colors"] >= 8,
                      f"不同颜色 {stats['colors']}")
                check("底图是纸底+墨+水（舆图特征成立）", ratio > 0.5,
                      "纸 %.2f 墨 %.2f 水 %.2f（采样 %d）" % (stats["paper"], stats["ink"],
                                                          stats["water"], stats["samples"]))
                check("底图有墨线（不是空白纸）", stats["ink"] > 0.005,
                      "墨占比 %.4f" % stats["ink"])
                check("底图有水系淡蓝", stats["water"] > 0.002, "水占比 %.4f" % stats["water"])
                # 实际画进页面的元素尺寸
                size = driver.execute_script("""
                  const i = document.querySelector('svg.map image.basemap');
                  return i ? i.width.baseVal.value + 'x' + i.height.baseVal.value : '';
                """)
                check("底图铺满地图视口", "x" in size and size.split("x")[0] not in ("", "0"), size)
                # 基线比对（地图渲染一改就红）
                import urllib.request
                raw = urllib.request.urlopen(f"http://127.0.0.1:{port}{href}", timeout=60).read()
                digest = hashlib.sha256(raw).hexdigest()[:16]
                # 基线放在 `tests/baselines/`（**入库**）而不是 `logs/`（整目录 gitignore）：
                # 基线不跟着代码走，换台机器/新克隆一跑就红，而"红"的原因却不是代码变了。
                # 与 `terrain_checksum` 同理——判据必须可复现。
                base_path = os.path.join(ROOT, "tests", "baselines", "map_baseline.json")
                os.makedirs(os.path.dirname(base_path), exist_ok=True)
                cur = {"seed": a.seed, "sha256_16": digest, "natural": stats["natural"],
                       "colors": stats["colors"], "paper": round(stats["paper"], 4),
                       "ink": round(stats["ink"], 4), "water": round(stats["water"], 4),
                       "href_shape": href.split("&x=")[1].split("&")[0] if "&x=" in href else ""}
                if a.update_baseline or not os.path.exists(base_path):
                    with open(base_path, "w", encoding="utf-8") as fh:
                        json.dump(cur, fh, ensure_ascii=False, indent=2)
                    print(f"  [基线] 已记录底图指纹 {digest} → {base_path}")
                else:
                    with open(base_path, encoding="utf-8") as fh:
                        old = json.load(fh)
                    same_seed = int(old.get("seed", -1)) == a.seed
                    check("基线绑定同一种子", same_seed,
                          f"基线种子 {old.get('seed')} vs 本次 {a.seed}")
                    check("底图与基线一致（改动需 --update-baseline 重记）",
                          old.get("sha256_16") == digest,
                          f"基线 {old.get('sha256_16')} → 现在 {digest}（种子 {a.seed}）")
                    # 稳定性：同参数再取一次，必须逐位一致（渲染确定性）
                    raw2 = urllib.request.urlopen(f"http://127.0.0.1:{port}{href}", timeout=60).read()
                    check("同参数底图两次一致（渲染确定）",
                          hashlib.sha256(raw2).hexdigest()[:16] == digest, "")

        # ---- 真浏览器里点击一次交互（可操作性等待 vs jsdom 的手点） ----
        dots = driver.find_elements(By.CSS_SELECTOR, "svg.map .towns .tw:not(.here)")
        if dots:
            dots[0].click()
            try:
                WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".side .card")))
                check("真浏览器点击城镇 → 侧栏出卡片", True, "")
                plan = driver.find_elements(
                    By.XPATH, "//*[contains(@class,'side')]//button[contains(., '前往')]")
                if plan:
                    # 点一次往往不够：planning 请求在冷启动下要几秒，而候选是**后渲染**的
                    # （与 jsdom 侧同一个坑：点完立刻查选择器会查空）。故"点到生效"。
                    ok = False
                    deadline = time.time() + 90
                    while time.time() < deadline and not ok:
                        if driver.find_elements(By.CSS_SELECTOR, ".ctxpanel .route"):
                            ok = True
                            break
                        btns = driver.find_elements(
                            By.XPATH, "//*[contains(@class,'side')]//button[contains(., '前往')]")
                        if btns:
                            try:
                                if btns[0].is_enabled():
                                    btns[0].click()
                            except Exception:
                                pass
                        time.sleep(0.4)
                    check("点「前往」→ 候选出现（真实耗时）", ok,
                          driver.find_element(By.CSS_SELECTOR, ".side").text[:60].replace("\n", " "))
            except Exception as e:      # noqa: BLE001
                check("真浏览器点击城镇 → 侧栏出卡片", False, repr(e))

        # ---- 缩放：**底图必须真的换一张** ----
        # 只查"城镇点变多"是不够的：用户实测反馈"地图不支持缩放"，而那种情况恰恰是
        # 头部数字变了、`<image>` 的 href 却没变（图上什么也没发生）。故这里**量 href**：
        #   span 必须跟着档位走，且换 span 后**底图的像素必须不同**。
        def _href():
            els = driver.find_elements(By.CSS_SELECTOR, "svg.map image.basemap")
            return els[0].get_attribute("href") if els else ""

        h0 = _href()
        span0 = re.search(r"[?&]span=(\d+)", h0 or "")
        zout = driver.find_elements(By.XPATH, "//*[contains(@class,'zoom')]//button[contains(., '－')]")
        if zout and span0:
            for _ in range(2):                      # 8000 → 20000（连点两次）
                try:
                    zout[0].click()
                except Exception:
                    pass
                time.sleep(1.2)
            # 等 href 真的变（底图 URL 是 computed，状态回来才重建）
            h1 = h0
            deadline = time.time() + 40
            while time.time() < deadline and h1 == h0:
                h1 = _href()
                time.sleep(0.4)
            span1 = re.search(r"[?&]span=(\d+)", h1 or "")
            check("缩放后底图 URL 的 span 变了", bool(h1) and h1 != h0 and bool(span1)
                  and span1.group(1) != span0.group(1),
                  f"span {span0.group(1) if span0 else '?'} → {span1.group(1) if span1 else '?'}")
            if h1 and h1 != h0:
                b0 = urllib.request.urlopen(f"http://127.0.0.1:{port}{h0}", timeout=120).read()
                b1 = urllib.request.urlopen(f"http://127.0.0.1:{port}{h1}", timeout=120).read()
                check("缩放后底图**内容**确实不同（不是同一张图）", b0 != b1,
                      f"{len(b0)} vs {len(b1)} bytes")
                # 顺手量一下"探索边界"在真实浏览器里到底占多少像素：
                # 这是用户反馈"没展示实景"的定量判据（只画几格时它确实小得看不见）。
                href_atlas = h1.replace("style=composed", "style=atlas")
                b_atlas = urllib.request.urlopen(
                    f"http://127.0.0.1:{port}{href_atlas}", timeout=120).read()
                check("底图走的是 composed（含探索边界）", "style=composed" in (h1 or ""),
                      (h1 or "")[:80])
                with open(os.path.join(ROOT, "logs", "e2e_web_basemap.png"), "wb") as fh:
                    fh.write(b1)
                with open(os.path.join(ROOT, "logs", "e2e_web_basemap_atlas.png"), "wb") as fh:
                    fh.write(b_atlas)
        else:
            check("缩放后底图 URL 的 span 变了", False,
                  f"zoom 按钮={bool(zout)} span={bool(span0)}")

        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        driver.save_screenshot(a.out)
        print("  截图 → %s（%.0f KB）" % (a.out, os.path.getsize(a.out) / 1024))
        print("  底图 → logs/e2e_web_basemap.png（另出 *_atlas.png 供对比）")

        if a.keep_open:
            print("== --keep-open：浏览器保持打开，按 Ctrl+C 结束 ==")
            while True:
                time.sleep(1)
    finally:
        if driver is not None and not a.keep_open:
            driver.quit()
        server.terminate()
        try:
            server.wait(timeout=5)
        except Exception:
            server.kill()

    print("\n== 结果：%d 过 / %d 败 ==" % (_PASS, _FAIL))
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
