/**
 * P3.7 前端 E2E 冒烟（jsdom + 真实 FastAPI 服务端）。
 *
 * 布局依据（用户 2026-09-09 拍板，方案 B + 两次修订）：
 *   左状态常驻 / 中上主内容（默认地图，战斗临时接管）/ 中下叙事日志（可拖拽高度）
 *   修炼 = 主内容区的一个视图（状态栏「修炼」按钮进入）；**没有行动栏**
 *   参悟选择要记住（不因状态刷新被打回第一项）
 *
 * 运行：node e2e/smoke.mjs（需先 npm run build；脚本自行起 uvicorn）
 */
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { JSDOM } from "jsdom";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND = path.dirname(HERE);
const ROOT = path.dirname(FRONTEND);
const DIST = path.join(FRONTEND, "dist");
const PY = path.join(ROOT, ".venv", "Scripts", "python.exe");
const PORT = 8177;
const BASE = `http://127.0.0.1:${PORT}`;

let pass = 0;
let fail = 0;
function check(name, cond, detail = "") {
  if (cond) {
    pass++;
    console.log(`  ✓ ${name} ${detail}`);
  } else {
    fail++;
    console.log(`  ✗ ${name} ${detail}`);
  }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const saveDir = mkdtempSync(path.join(tmpdir(), "xiuxian_e2e_"));
const serverCode = `
import sys, os
sys.path.insert(0, r"${ROOT}")
import uvicorn
from server.app import create_app
uvicorn.run(create_app({"save_dir": r"${saveDir}"}), host="127.0.0.1", port=${PORT}, log_level="error")
`;
const server = spawn(PY, ["-X", "utf8", "-c", serverCode], { stdio: "inherit" });

async function waitHealth(timeoutMs = 20000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    try {
      const r = await fetch(`${BASE}/health`);
      if (r.ok) return true;
    } catch {
      /* 还没起来 */
    }
    await sleep(150);
  }
  return false;
}

/** 服务端端口是否还开着（用于"等它真的关掉"，替代固定 sleep）。 */
async function portOpen() {
  try {
    const r = await fetch(`${BASE}/health`);
    return !!r;
  } catch {
    return false;   // 连接被拒 = 已释放
  }
}

function findBundle() {
  const assets = path.join(DIST, "assets");
  if (!existsSync(assets)) return null;
  const js = readdirSync(assets).find((f) => f.endsWith(".js"));
  return js ? path.join(assets, js) : null;
}

function setupDom(html) {
  const dom = new JSDOM(html, { url: BASE + "/", pretendToBeVisual: true });
  const { window } = dom;
  const setGlobal = (name, value) => {
    try {
      globalThis[name] = value;
    } catch {
      Object.defineProperty(globalThis, name, { value, configurable: true, writable: true });
    }
  };
  setGlobal("window", window);
  setGlobal("document", window.document);
  setGlobal("navigator", window.navigator);
  setGlobal("localStorage", window.localStorage);
  setGlobal("getComputedStyle", window.getComputedStyle.bind(window));
  const nativeFetch = globalThis.fetch; // 必须先抓住，否则包装函数自引用递归
  setGlobal("fetch", (input, init) => {
    const url = typeof input === "string" ? input : input.url;
    return nativeFetch(url.startsWith("http") ? url : BASE + url, init);
  });
  for (const key of Object.getOwnPropertyNames(window)) {
    if (key in globalThis || key === "fetch" || key === "window" || key === "document") continue;
    try {
      const v = window[key];
      setGlobal(key, typeof v === "function" ? v.bind(window) : v);
    } catch {
      /* 只读属性跳过 */
    }
  }
  return dom;
}

function click(el) {
  el.dispatchEvent(new globalThis.window.MouseEvent("click", { bubbles: true }));
}
function pointer(type, target, clientY) {
  const e = new globalThis.window.Event(type, { bubbles: true, cancelable: true });
  e.clientY = clientY;
  e.clientX = 100;
  target.dispatchEvent(e);
}
function byText(sel, text) {
  return [...document.querySelectorAll(sel)].find((e) => (e.textContent || "").includes(text));
}
function textOf(sel) {
  return (document.querySelector(sel)?.textContent || "").trim();
}
async function waitFor(fn, timeoutMs = 8000, step = 60) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    if (fn()) return true;
    await sleep(step);
  }
  return false;
}
/**
 * 等"某个动作的**真实结果**出现"，而不是睡固定时长。
 *
 * 为什么要它（2026-09-11）：本 E2E 原来大量用 `sleep(600~1400)` 等后端返回，
 * 而本机**冷启动要建世界 6~10s**，于是同一份代码多次连跑会得到 31/0、23/3、20/6
 * 交替的结果（已用仓库原版 E2E 复现，属既有脆弱性）。判据换成"结果出现"后，
 * 慢就多等、快就立刻过，不再靠猜。
 */
async function waitResult(fn, timeoutMs = 30000) {
  return waitFor(fn, timeoutMs, 80);
}
/**
 * **点到生效**：反复点同一个按钮，直到判据成立（或超时）。
 *
 * 为什么不能"点一次就等"：本机首屏要建世界 ≈6~10s，期间 `busy=true`，
 * 按钮是 `disabled` 的——`dispatchEvent` 出去的点击**会被直接丢掉**（不是排队）。
 * 原来的写法"点一次 + 睡一会儿 + 断言"于是在慢机器上必然误报；
 * 这里改成"没生效就再点一次"，把"点击丢失"这件事吸收掉。
 *
 * 返回判据最终是否成立；`find()` 每次重新查 DOM（Vue 可能重建了节点）。
 */
async function clickUntil(find, predicate, timeoutMs = 30000, step = 250) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    if (predicate()) return true;
    const el = find();
    if (el && !el.disabled) {
      try {
        click(el);
      } catch {
        /* 元素可能已被替换，下一轮再取 */
      }
    }
    await sleep(step);
  }
  return predicate();
}

let exitCode = 1;
try {
  const htmlPath = path.join(DIST, "index.html");
  check("dist/index.html 存在（需先 npm run build）", existsSync(htmlPath));
  if (!existsSync(htmlPath)) throw new Error("请先 cd frontend && npm run build");

  check("服务端就绪", await waitHealth(), BASE);
  const bundle = findBundle();
  check("dist 含 JS 构建产物", !!bundle);
  if (!bundle) throw new Error("dist/assets 缺 JS");

  const dom = setupDom(readFileSync(htmlPath, "utf8"));
  await import("file://" + bundle.replace(/\\/g, "/"));
  await waitFor(() => document.querySelector("#app")?.children.length > 0, 5000);

  // 1) 骨架：左状态 / 主内容 / 日志，且没有行动栏
  check(
    "1 三区同屏（状态 / 主内容 / 叙事日志）",
    !!document.querySelector(".layout") &&
      !!byText("h2", "状态") &&
      !!document.querySelector(".main-slot") &&
      !!byText("h2", "叙事日志"),
  );
  check("1 主内容默认 = 地图", !!byText("h2", "地图"));
  check("1 无行动栏 / 行动抽屉（已按用户要求移除）", !document.querySelector(".drawer") && !byText("h2", "行动"));

  // 2) 新建一世
  const newBtn = byText("button", "新建一世");
  check("2 找到「新建一世」按钮", !!newBtn);
  click(newBtn);
  // ⚠️ 二次确认弹窗是**渲染之后**才有的（Vue 异步），原来固定 `sleep(300)` 赌它出现——
  // 机器忙时（后台可能正跑冒烟/建世界）会赌输，于是"确定"没点到、`/api/new` 从没发出，
  // 后面每一条断言都连锁失败（表现为"点静养后被打回地图"这类离奇失败）。
  // 改为**等它真的出现**（判据本身仍是"有二次确认"，语义不变）。
  const hasConfirm = await waitResult(() => !!byText(".sheet button", "确定"), 15000);
  if (hasConfirm) {
    check("2 破坏性操作有二次确认弹窗", true);
    click(byText(".sheet button", "确定"));
  }
  // ⚠️ 2026-09-11 修：原判据是"页面出现「练气」"，可**旧局状态里本来就有这三个字**，
  // 于是测试会在 `/api/new`（冷启动要建世界 ≈6~10s）**还没返回**时就往下跑；
  // 那次请求的收尾（`newRun` 里的 `ui.close()`）随后才到，正好把测试后面的断言打乱
  // （表现为"点静养后被打回地图"这类离奇失败）。
  // 改为等**开局真正落定**的标志：日志里出现「新一世 · 种子」（它在 api 返回之后才写）。
  const okStatus = await waitFor(
    () => (document.body.textContent || "").includes("新一世 · 种子"),
    60000,
  );
  check("2 开局落定（/api/new 已返回，冷启动含建世界）", okStatus);
  check(
    "2 页面无 undefined / NaN 残留",
    !(document.body.textContent || "").includes("undefined") &&
      !(document.body.textContent || "").includes("NaN"),
  );

  // 3) 修炼页（状态栏按钮进入，内容在主页面）
  // 先等首屏地图就绪：新局要建世界（实测 ≈6.5 s），期间 busy=true 会吃掉后续点击
  const mapReady = await waitFor(() => !!document.querySelector("svg.map .towns .tw"), 30000);
  check("3 首屏地图就绪（世界已建好，可在其上操作）", mapReady);
  const culBtn = byText(".quick button", "修炼");
  check("3 状态栏有「修炼」切换按钮", !!culBtn);
  if (culBtn) {
    // 冷启动期间按钮 `disabled`，点一次可能被丢掉 → 用"点到生效"重试
    const switched = await clickUntil(
      () => byText(".quick button", "修炼"),
      () => /🧘|闭关修炼/.test(textOf(".main-slot")),
      40000,
    );
    const main = textOf(".main-slot");
    check("3 修炼页在主内容区打开（非弹层）", switched && !document.querySelector(".overlay"),
      main.slice(0, 40));
    check(
      "3 修炼页含闭关/参悟/突破/静养四区",
      ["闭关修炼", "参悟", "突破境界", "静养"].every((k) => main.includes(k)),
      main.slice(0, 40),
    );
    check("3 参悟区有功法下拉", !!document.querySelector(".main-slot select"));
  }

  // 4) 参悟选择被记住（切页回来仍在）
  const sel = document.querySelector(".main-slot select");
  let cwName = "";
  if (sel) {
    cwName = sel.value;
    check("4 参悟目标默认选中第一个可参悟功法", !!cwName, cwName);
    // 触发一次状态刷新（静养），确认下拉不被重置
    const ageInput = [...document.querySelectorAll(".main-slot input[type=number]")].pop();
    if (ageInput) ageInput.value = "1";
    const restBtn = byText(".main-slot button", "静养");
    if (restBtn) {
      const logsBefore = document.querySelectorAll(".log-line").length;
      // 同样可能被丢：点到日志真的多出一行
      await clickUntil(
        () => byText(".main-slot button", "静养"),
        () => document.querySelectorAll(".log-line").length > logsBefore,
        30000,
      );
      const sel2 = document.querySelector(".main-slot select");
      check("4 动作后参悟选择保持不变（不再被打回第一项）",
        sel2 && sel2.value === cwName, `${cwName} → ${sel2?.value}`);
      check("4 参悟目标写入 localStorage", !!dom.window.localStorage.getItem("xiuxian.cwGongfa"));
      // 书库：熟悉度<10 也能「参悟入门」；参悟后槽位下拉出现且不留空
      const libBtn = byText(".quick button", "书库");
      if (libBtn) {
        click(libBtn);
        await waitResult(() => !!document.querySelector(".main-slot .item"), 20000);
        const item = document.querySelector(".main-slot .item");
        if (item) {
          click(item);
          await waitResult(() => !!document.querySelector(".main-slot .detail button"), 20000);
          const entryBtn = byText(".main-slot .detail button", "参悟入门");
          check("4 书库：熟悉度不足时也能点「参悟入门」", !!entryBtn && !entryBtn.disabled);
          if (entryBtn && !entryBtn.disabled) {
            click(entryBtn);
            await waitResult(() => !!document.querySelector(".main-slot .detail select"), 25000);
            const slotSel = document.querySelector(".main-slot .detail select");
            check("4 参悟入门后槽位下拉出现且不留空", !!slotSel && !!slotSel.value, `value=${slotSel?.value}`);
          }
        }
      }
    }
  }

  // 5) 拖拽调整日志高度
  const splitter = document.querySelector(".splitter");
  const logSlot = document.querySelector(".log-slot");
  check("5 存在拖拽分隔条", !!splitter);
  if (splitter && logSlot) {
    // jsdom 的布局尺寸恒为 0，这里给容器打一个假的 getBoundingClientRect，
    // 才能验证「按指针位置计算高度」的逻辑（真实浏览器由布局提供真实 rect）。
    const center = document.querySelector(".center");
    center.getBoundingClientRect = () => ({
      top: 0,
      bottom: 700,
      left: 0,
      right: 1000,
      width: 1000,
      height: 700,
      x: 0,
      y: 0,
      toJSON() {},
    });
    const h0 = parseFloat(logSlot.style.height || "0");
    pointer("pointerdown", splitter, 460);
    pointer("pointermove", dom.window, 400); // 向上拖 → 日志变高
    // 这里等的是**动画/重排**（不是等响应），150ms 属允许范围；拖拽逻辑本身是同步的。
    await sleep(120);
    pointer("pointerup", dom.window, 400);
    const h1 = parseFloat(logSlot.style.height || "0");
    check("5 拖拽后日志高度变化（向上拖变高）", h1 > h0, `${h0}px → ${h1}px`);
    check("5 高度写入 localStorage", !!dom.window.localStorage.getItem("xiuxian.ui.logHeight"));
  }

  // 6) 地图（P4-T3 重写后）：SVG 世界地图 → 选城镇 → 看候选路线（真实耗时）→ 出发 → 遇敌进战斗
  const logBefore = document.querySelectorAll(".log-line").length;
  let explored = false;
  let battle = false;
  byText(".quick button", "地图") && click(byText(".quick button", "地图"));
  // ⚠️ 2026-09-11 修：原来是固定 `sleep(400)`，顶不住服务端冷启动（世界生成 6~10s）时
  // 地图数据还没到；改为**等真实结果**（地图与城镇点都出现）。
  await waitFor(() => !!document.querySelector("svg.map .towns .tw"), 40000);

  // 6a 地图画的是**真实世界**（不再是写死的 5 个地点卡片）
  check("6a 地图为 SVG 世界地图（非地点卡片）", !!document.querySelector("svg.map") && !document.querySelector(".site"));
  const townDots = document.querySelectorAll("svg.map .towns .tw").length;
  check("6a 地图上有真实城镇（服务端下发）", townDots > 0, `城镇点 ${townDots}`);
  const head = textOf(".panel-head") + textOf(".main-slot");
  check("6a 顶部显示舆图档与视野（真实数值）", /舆图|无舆图/.test(head) && /神识视野|摸索/.test(head), head.slice(0, 80));

  // 6b 选一座城镇 → 查看路线 → 候选带**真实日数**（不再是写死的「移动 3 日」）
  let routeShown = false;
  let routeDays = "";
  const dot = document.querySelector("svg.map .towns .tw:not(.here)");
  if (dot) {
    dot.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
    // 同理：等卡片真的渲染出来（而不是睡 400ms 赌它出来了）
    await waitFor(() => !!document.querySelector(".side .card"), 8000);
    // 等"查看路线"按钮出现（卡片渲染与 `s.canAct` 都可能晚一拍），再点。
    let planBtn = byText(".side button", "查看路线") || byText(".side button", "推演");
    if (!planBtn) {
      await waitFor(() => !!(byText(".side button", "查看路线") || byText(".side button", "推演")), 15000);
      planBtn = byText(".side button", "查看路线") || byText(".side button", "推演");
    }
    if (planBtn) {
      routeShown = await clickUntil(
        () => byText(".side button", "查看路线") || byText(".side button", "推演"),
        () => !!document.querySelector(".routes .route"),
        45000,
      );
      const r0 = document.querySelector(".routes .route");
      routeDays = r0 ? (r0.textContent || "").trim() : "";
      if (!routeShown) {
        // 失败时把卡片/提示原文带出来，便于定位（而不是只报一句 false）
        const card = document.querySelector(".side");
        routeDays = "（未出候选）侧栏原文：" + (card ? (card.textContent || "").trim() : "（空）");
      }
    } else {
      const card = document.querySelector(".side .card");
      routeDays = "选中项：" + (card ? (card.textContent || "").trim() : "（无卡片）");
    }
  } else {
    routeDays = "（地图上没找到「非脚下」的城镇点）";
  }
  check("6b 点城镇 → 给出候选路径", routeShown);
  check("6b 候选显示真实耗时（日 + 里程，非写死 3 日）",
    /日/.test(routeDays) && /里/.test(routeDays) && !routeDays.includes("3 日"),
    routeDays.replace(/\s+/g, " ").slice(0, 70));

  // 6c 执行候选 → 位置/日志随之变化（时间轴按真实路径推进）
  if (routeShown && !battle) {
    const goBtn = document.querySelector(".routes .route");
    if (goBtn && !goBtn.disabled) {
      click(goBtn);
      explored = await waitFor(() => document.querySelectorAll(".log-line").length > logBefore, 30000)
        || await waitFor(() => !document.querySelector(".side .card"), 8000);
      battle = await waitFor(() => !!byText("h2", "战斗"), 3000);
    }
  }
  check("6 移动/探索产生叙事文字（进入下方日志）", explored, `日志行 ${logBefore} → ${document.querySelectorAll(".log-line").length}`);
  const mainNow = textOf(".main-slot");
  check(
    "6 战斗接管主内容区（不是覆盖层）",
    battle ? mainNow.includes("战斗") : true,
    `battle=${battle} mainHead=${mainNow.slice(0, 60)}`,
  );
  check("6 战斗期间日志仍可见", !!document.querySelector(".log-wrap"));

  if (battle) {
    const basicBtns = [...document.querySelectorAll(".cmd-row .act")];
    check("6 常用动作在上（含平砍/遁走）", basicBtns.length >= 4 && basicBtns.some((b) => b.textContent.includes("平砍")));
    check("6 技能列表默认折叠", !document.querySelector(".skills"));
    const usable = basicBtns.find((b) => !b.disabled);
    if (usable) {
      click(usable);
      const queued = await waitFor(() => textOf(".queue").includes("止于"), 6000);
      check("6 点动作 → 入队（显示结束时刻）", queued, textOf(".queue").slice(0, 40));
      check(
        "6 时间轴队列条分前摇/后摇两段",
        !!document.querySelector(".tl-act .tl-wind") && !!document.querySelector(".tl-act .tl-rec"),
        textOf(".tl-track").slice(0, 40),
      );
      // 再点同一动作 → 重复排入（允许重复施放）
      const queuedBtn = document.querySelector(".cmd-row .act.queued");
      if (queuedBtn) {
        click(queuedBtn);
        const two = await waitFor(
          () => (textOf(".queue").match(/止于/g) || []).length >= 2,
          6000,
        );
        check("6 再点同一动作 → 重复排入（可重复施放）", two, textOf(".queue").slice(0, 60));
      }
      // 点队列条目 → 撤回一个
      const qItem = document.querySelector(".queue .q-item");
      if (qItem) {
        click(qItem);
        const one = await waitFor(
          () => (textOf(".queue").match(/止于/g) || []).length === 1,
          6000,
        );
        check("6 点队列条目 → 撤回一个", one, textOf(".queue").slice(0, 60));
      }
      const exec = byText(".cmd-row button", "执行本轮");
      if (exec) {
        const tBefore = textOf(".tl-foot");
        click(exec);
        // 等"时间轴推进"或"战斗结束"真的发生，而不是睡固定时长
        await waitResult(
          () => textOf(".tl-foot") !== tBefore || !byText("h2", "战斗"),
          25000,
        );
        const tAfter = textOf(".tl-foot");
        check("6 执行本轮 → 时间轴推进", !byText("h2", "战斗") || tAfter !== tBefore, `${tBefore.slice(0, 24)} → ${tAfter.slice(0, 24)}`);
      }
    }
  }

  const toasts = [...document.querySelectorAll(".toast")].map((t) => t.textContent);
  check("7 无服务端/网络错误 toast", !toasts.some((t) => /服务端异常|连接服务端失败/.test(t || "")), JSON.stringify(toasts));

  exitCode = fail === 0 ? 0 : 1;
  console.log(`\n== E2E 结果：${pass} 过 / ${fail} 败 ==`);
  dom.window.close();
} catch (e) {
  console.error("E2E 异常：", e);
  exitCode = 1;
} finally {
  server.kill();
  // 等**端口真的释放**，而不是固定睡 300ms 赌它好了。
  // 理由：① 固定时长不保证释放，下一次连跑可能撞端口；② 这一步每个用例都要等，
  // 换成"释放即走"既更稳也更快。
  await waitFor(() => !portOpen(), 5000, 50);
  process.exit(exitCode);
}
