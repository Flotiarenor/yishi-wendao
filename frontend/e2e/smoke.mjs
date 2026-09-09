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
  await sleep(300);
  const confirmBtn = byText(".sheet button", "确定");
  if (confirmBtn) {
    check("2 破坏性操作有二次确认弹窗", true);
    click(confirmBtn);
  }
  const okStatus = await waitFor(() => (document.body.textContent || "").includes("练气"), 10000);
  check("2 状态面板出现真实数据（境界）", okStatus);
  check(
    "2 页面无 undefined / NaN 残留",
    !(document.body.textContent || "").includes("undefined") &&
      !(document.body.textContent || "").includes("NaN"),
  );

  // 3) 修炼页（状态栏按钮进入，内容在主页面）
  const culBtn = byText(".quick button", "修炼");
  check("3 状态栏有「修炼」切换按钮", !!culBtn);
  if (culBtn) {
    click(culBtn);
    await sleep(300);
    const main = textOf(".main-slot");
    check("3 修炼页在主内容区打开（非弹层）", main.includes("修炼") && !document.querySelector(".overlay"));
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
      click(restBtn);
      await sleep(1200);
      const sel2 = document.querySelector(".main-slot select");
      check("4 动作后参悟选择保持不变（不再被打回第一项）", sel2 && sel2.value === cwName, `${cwName} → ${sel2?.value}`);
      check("4 参悟目标写入 localStorage", !!dom.window.localStorage.getItem("xiuxian.cwGongfa"));
      // 参悟入门 → 书库槽位下拉应出现且不留空（用户报"书库空白选项"回归）
      const cwBtn = byText(".main-slot button", "参悟");
      if (cwBtn) {
        click(cwBtn);
        await sleep(1200);
        const libBtn = byText(".quick button", "书库");
        if (libBtn) {
          click(libBtn);
          await sleep(600);
          const item = document.querySelector(".main-slot .item");
          if (item) {
            click(item);
            await sleep(700);
            const slotSel = document.querySelector(".main-slot .detail select");
            check("4 书库槽位下拉不留空", !!slotSel && !!slotSel.value, `value=${slotSel?.value}`);
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
    await sleep(120);
    pointer("pointerup", dom.window, 400);
    const h1 = parseFloat(logSlot.style.height || "0");
    check("5 拖拽后日志高度变化（向上拖变高）", h1 > h0, `${h0}px → ${h1}px`);
    check("5 高度写入 localStorage", !!dom.window.localStorage.getItem("xiuxian.ui.logHeight"));
  }

  // 6) 探索 → 文字进日志；遇敌 → 战斗接管主内容区
  const logBefore = document.querySelectorAll(".log-line").length;
  let explored = false;
  let battle = false;
  byText(".quick button", "地图") && click(byText(".quick button", "地图"));
  await sleep(250);
  for (let i = 0; i < 25 && !battle; i++) {
    const ex = byText(".site button", "探索");
    if (!ex) break;
    click(ex);
    explored = await waitFor(() => document.querySelectorAll(".log-line").length > logBefore, 4000);
    battle = await waitFor(() => !!byText("h2", "战斗"), 4000);
  }
  check("6 探索产生叙事文字（进入下方日志）", explored, `日志行 ${logBefore} → ${document.querySelectorAll(".log-line").length}`);
  const mainNow = textOf(".main-slot");
  check(
    "6 战斗接管主内容区（不是覆盖层）",
    battle && mainNow.includes("战斗"),
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
      // 队列撤回：已排动作可撤销（不推进时间轴、不消耗资源）
      const undo = document.querySelector(".queue .q-undo");
      if (undo) {
        click(undo);
        const cleared = await waitFor(() => !textOf(".queue").includes("止于"), 6000);
        check("6 队列动作可撤回", cleared, textOf(".queue").slice(0, 40));
        const usable2 = [...document.querySelectorAll(".cmd-row .act")].find((b) => !b.disabled);
        if (usable2) {
          click(usable2);
          await waitFor(() => textOf(".queue").includes("止于"), 6000);
        }
      }
      const exec = byText(".cmd-row button", "执行本轮");
      if (exec) {
        const tBefore = textOf(".tl-foot");
        click(exec);
        await sleep(1400);
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
  await sleep(300);
  process.exit(exitCode);
}
