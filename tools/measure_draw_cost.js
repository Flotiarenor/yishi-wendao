// 验证 town_editor.html 的分层渲染：既"便宜"（每帧调用数）也"正确"（离线层真的画出了地图、
// drawImage 真的把两层合成到一起）。用用户自己的青石镇数据。
//
//   用法：node tools/measure_draw_cost.js tools/_user_town.json
//
// 本脚本自带一个**会真写像素**的 mini canvas（fillRect / drawImage / clearRect 都实现），
// 所以能直接对"最后画面"取样，判断地图有没有被画出来、光标框有没有动、缓存有没有生效。
const fs = require("fs");
const path = require("path");
const html = fs.readFileSync(path.join(__dirname, "town_editor.html"), "utf8");
const code = html.match(/<script>([\s\S]*?)<\/script>/)[1];

const stats = { fillRect: 0, strokeRect: 0, rect: 0, stroke: 0, drawImage: 0, clearRect: 0 };

// ---------- 会真写像素的 mini canvas ----------
function parseColor(c) {
  if (typeof c !== "string") return [0, 0, 0, 1];
  if (c[0] === "#") {
    let h = c.slice(1);
    if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];   // #fff → #ffffff（浏览器支持的简写）
    if (h.length === 6) h += "ff";
    if (h.length !== 8) return [0, 0, 0, 1];
    return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16), parseInt(h.slice(6, 8), 16) / 255];
  }
  const m = /^rgba?\(([^)]+)\)$/.exec(c);
  if (!m) return [0, 0, 0, 1];
  const p = m[1].split(",").map((s) => parseFloat(s.trim()));
  return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1];
}
let allocCount = 0;
class MiniCanvas {  constructor() {
    this._w = 0; this._h = 0; this._ctx = new MiniCtx(this);
    // 也要能被当成普通元素用（工具会用 createElement("canvas") 的外壳；按钮则走 mkEl）
    this.dataset = {}; this.style = {}; this.children = [];
    this.classList = { toggle() {}, add() {}, remove() {} };
    this.appendChild = (c) => this.children.push(c);
    this.addEventListener = () => {};
  }
  get width() { return this._w; }
  // ⚠️ 真实 canvas 只在**值真的变了**时才重建后备缓冲；无条件重建会把已经画好的内容清掉
  set width(v) { v = v | 0; if (v === this._w) return; this._w = v; this._ctx._alloc(); }
  get height() { return this._h; }
  set height(v) { v = v | 0; if (v === this._h) return; this._h = v; this._ctx._alloc(); }
  getContext() { return this._ctx; }
}
class MiniCtx {
  constructor(cv) { this.cv = cv; this.fillStyle = "#000"; this.strokeStyle = "#000"; this.lineWidth = 1; this.buf = null; this.paintCount = 0; }
  _alloc() {
    allocCount++;
    if (globalThis.__ALLOC_TRACE) {
      const st = new Error().stack.split("\n").slice(2, 4).map((s) => s.trim().replace(/^at\s+/, "")).join("  ←  ");
      console.log(`  [alloc] ${this.cv.width}×${this.cv.height} 第${allocCount}次  ${st}`);
    }
    this.buf = new Float64Array(Math.max(1, this.cv.width * this.cv.height * 3)).fill(255);
    // ⚠️ 真实 canvas 初始是**全透明**的；只存 RGB 会让"叠层贴图"把地图整幅刷白
    this.alpha = new Float64Array(Math.max(1, this.cv.width * this.cv.height));
  }
  _blend(x, y, col) {
    const w = this.cv.width, h = this.cv.height;
    if (x < 0 || y < 0 || x >= w || y >= h) return;
    const a = col[3];
    if (a <= 0) return;
    if (!Number.isFinite(a) || !Number.isFinite(col[0])) {
      if (!this._badColor) { this._badColor = String(this.fillStyle); console.log("  ✗ 非法颜色（导致 NaN）：", JSON.stringify(String(this.fillStyle))); }
      return;
    }
    const i = (y * w + x) * 3, pi = y * w + x;
    this.alpha[pi] = a + this.alpha[pi] * (1 - a);      // 记住不透明度，叠层贴图要按它合成
    for (let k = 0; k < 3; k++) this.buf[i + k] = col[k] * a + this.buf[i + k] * (1 - a);
  }
  fillRect(x, y, w, h) {
    stats.fillRect++; this.paintCount++;
    const col = parseColor(this.fillStyle);
    for (let py = Math.floor(y); py < Math.ceil(y + h); py++) for (let px = Math.floor(x); px < Math.ceil(x + w); px++) this._blend(px, py, col);
  }
  clearRect(x, y, w, h) {
    stats.clearRect++;
    const W = this.cv.width, H = this.cv.height;
    for (let py = Math.max(0, Math.floor(y)); py < Math.min(H, Math.ceil(y + h)); py++)
      for (let px = Math.max(0, Math.floor(x)); px < Math.min(W, Math.ceil(x + w)); px++) {
        const i = (py * W + px) * 3;
        this.buf[i] = this.buf[i + 1] = this.buf[i + 2] = 255;
        this.alpha[py * W + px] = 0;                   // 真实 clearRect 之后是透明的
      }
  }
  drawImage(src, dx, dy) {
    stats.drawImage++;
    if (!src || !src._ctx || !src._ctx.buf) return;
    const W = this.cv.width, H = this.cv.height, sw = src.width;
    const sb = src._ctx.buf, sa = src._ctx.alpha;
    for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
      const si = (y * sw + x) * 3, di = (y * W + x) * 3, pi = y * W + x;
      if (si + 2 >= sb.length) continue;
      const a = sa ? sa[pi] : 1;
      if (a <= 0) continue;                            // 源像素透明 → 完全不影响底下（关键）
      for (let k = 0; k < 3; k++) this.buf[di + k] = sb[si + k] * a + this.buf[di + k] * (1 - a);
      if (this.alpha) this.alpha[pi] = a + this.alpha[pi] * (1 - a);
    }
  }
  beginPath() {} moveTo() {} lineTo() {} ellipse() {}
  rect(x, y, w, h) { stats.rect++; this.fillRect(x, y, w, h); }     // 网格线 path：近似成细矩形
  stroke() { stats.stroke++; }
  strokeRect(x, y, w, h) { stats.strokeRect++; this.fillRect(x, y, 1, h); this.fillRect(x + w, y, 1, h); this.fillRect(x, y, w, 1); this.fillRect(x, y + h, w, 1); }
  save() {} restore() {} setTransform() {}
  pixel(x, y) { const i = (y * this.cv.width + x) * 3; return [this.buf[i], this.buf[i + 1], this.buf[i + 2]].map(Math.round); }
}

const elements = {};
const mkEl = (id) => ({
  id, value: id === "gw" || id === "gh" ? "48" : id === "gz" ? "12" : id === "roadW" ? "3" : "",
  textContent: "", innerHTML: "", style: {}, dataset: {}, children: [], checked: false,
  classList: { toggle() {}, add() {}, remove() {} },
  appendChild(c) { this.children.push(c); }, addEventListener() {},
  getContext() { return mainCtx; }, getBoundingClientRect: () => ({ left: 0, top: 0 }),
  setPointerCapture() {}, click() {}, parentElement: { scrollLeft: 0, scrollTop: 0 },
});
// 主画布：自己就是一个"元素 + canvas"两用的对象（不要用 Object.assign 去拼，
// 否则 ctx.cv 指向的是原来那个对象，blit 就会复制错的缓冲区）
const mainCv = new MiniCanvas();
const mainCtx = mainCv._ctx;
mainCv.id = "cv"; mainCv.value = ""; mainCv.textContent = ""; mainCv.innerHTML = "";
mainCv.checked = false; mainCv.files = null;
mainCv.getBoundingClientRect = () => ({ left: 0, top: 0 });
mainCv.setPointerCapture = () => {};
mainCv.click = () => {};
mainCv.parentElement = { scrollLeft: 0, scrollTop: 0 };
elements["cv"] = mainCv;
mainCv.width = 576; mainCv.height = 576;

const offscreens = [];
const document = {
  getElementById: (id) => elements[id] || (elements[id] = mkEl(id)),
  createElement: () => { const c = new MiniCanvas(); offscreens.push(c); return c; },
  addEventListener() {}, querySelector: () => null,
};
const window = { clipboard: { writeText: async () => {} }, addEventListener() {} };
const navigator = { clipboard: { writeText: async () => {} } };
globalThis.confirm = () => true;
const FileReader = class { readAsText() {} };
const requestAnimationFrame = (f) => f();

// 先把要驱动的控件**建好**，再让工具脚本去绑事件（否则我后面新建的对象上没有绑定）
elements["zedge"] = Object.assign(mkEl("zedge"), { checked: true });
elements["zalpha"] = Object.assign(mkEl("zalpha"), { value: "45" });
elements["talpha"] = Object.assign(mkEl("talpha"), { value: "85" });
elements["gw"] = Object.assign(mkEl("gw"), { value: "48" });
elements["gh"] = Object.assign(mkEl("gh"), { value: "48" });
elements["gz"] = Object.assign(mkEl("gz"), { value: "12" });
elements["roadW"] = Object.assign(mkEl("roadW"), { value: "3" });

const codePatched = code.replace("function renderMap(context) {", "function renderMap(context) {\n  globalThis.__RENDERMAP_CALLS = (globalThis.__RENDERMAP_CALLS || 0) + 1;");
const api = new Function(
  "document", "window", "navigator", "FileReader", "requestAnimationFrame", "confirm",
  codePatched + "\n;return { importJson, draw, setView, get W(){return W}, get H(){return H}, get Z(){return Z}, " +
  "get currentView(){return view}, get currentMapDirty(){return mapDirty}, " +
  // 用来看 setView 到底干了什么：包一层，前后各读一次 mapDirty
  "setViewChecked(v){ const a = mapDirty; setView(v); return [a, mapDirty, view]; }, " +
  // 统一的"改动 → 是否标脏 → 是否真的重画"探针（绕过测试自己的计时问题）
  "probeMutation(fn){ if (mapCtx) mapCtx.paintCount = 0; fn(); const dirtyRightAfter = mapDirty; " +
  "  if (dirtyRightAfter) draw();  const painted = mapCtx ? mapCtx.paintCount : 0; " +
  "  return { dirtyRightAfter, painted }; }, " +
  // 这三个模拟"滑杆/开关动了"：与 #zalpha / #talpha / #zedge 的处理器做的事一致
  "sliderZAlpha(v){ zoneAlpha = v; markMapDirty(); }, " +
  "sliderTAlpha(v){ tileAlpha = v; markMapDirty(); }, " +
  "sliderZEdge(v){ showZoneEdge = v; markMapDirty(); }, " +
  "set zalpha(v){zoneAlpha=v}, set talpha(v){tileAlpha=v}, set zedge(v){showZoneEdge=v}, " +
  "set showGrid(v){showGrid=v}, setHover(h){ hover = h; }, scheduleDraw, setTile, markMapDirty, " +
  "get mapDirty(){return mapDirty}, get mapCvRef(){return mapCv}, get mapCtxRef(){return mapCtx}, get hoverCvRef(){return hoverCv} };"
)(document, window, navigator, FileReader, requestAnimationFrame, confirm);

const town = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const Z = 12;
const at = (x, y) => [x, y];

function reset() {
  for (const k of Object.keys(stats)) stats[k] = 0;
  if (mapCanvas) mapCanvas._ctx.paintCount = 0;
}
function total() { return stats.fillRect + stats.strokeRect + stats.rect + stats.stroke + stats.drawImage; }
// 只统计离屏 canvas（工具也用 createElement 造按钮，别把按钮算进来）
function canvases() { return offscreens.filter((c) => c instanceof MiniCanvas && c.width > 10 && c.height > 10); }
// 先画一帧，确定地图层到底是哪一个离屏 canvas（按钮是 0×0，会被过滤掉）
api.draw();
let mapCanvas = canvases()[0] || null;
function mapLayerPaints() { return mapCanvas ? mapCanvas._ctx.paintCount : -1; }
function frame(label, note) {
  reset();
  globalThis.__RENDERMAP_CALLS = 0;
  api.draw();
  console.log(`  ${label.padEnd(30)} 调用 ${String(total()).padStart(5)} 次   地图层重画 ${String(mapLayerPaints()).padStart(5)} 格`
    + `   renderMap=${globalThis.__RENDERMAP_CALLS} 次   ${note || ""}`);
  return { total: total(), mapPaints: mapLayerPaints(), renders: globalThis.__RENDERMAP_CALLS };
}

console.log(`地图 ${api.W}×${api.H}，格 ${Z}px，画布 ${mainCv.width}×${mainCv.height}\n`);
api.importJson(JSON.stringify(town));
api.setHover([20, 20]);

console.log("【每帧开销】");
api.setView("tile"); api.showGrid = true;
const a1 = frame("要素视图 → 换视图", "首帧要重画整张地图");
const a2 = frame("要素视图 → 再画一次", "缓存命中，应几乎为 0");
api.setView("both"); api.sliderZAlpha(0.45); api.sliderTAlpha(0.85); api.sliderZEdge(true);
const b1 = frame("叠加+边界线 → 换视图", "首帧要重画整张地图");
const b2 = frame("叠加+边界线 → 再画一次", "缓存命中");
api.setHover([21, 20]);
const c1 = frame("光标移到隔壁格", "只动光标层");
api.setHover([21, 20]);

console.log("\n【正确性：主画布上真的有地图吗】");
function probe(label) {
  // 全画布网格采样，统计非白像素
  let nonWhite = 0, totalPx = 0, dark = 0;
  for (let y = 6; y < mainCv.height; y += 7) for (let x = 6; x < mainCv.width; x += 7) {
    const p = mainCtx.pixel(x, y);
    totalPx++;
    if (p[0] < 250 || p[1] < 250 || p[2] < 250) nonWhite++;
    if (p[0] < 80 && p[1] < 80 && p[2] < 80) dark++;   // 建筑近黑
  }
  const pct = (nonWhite / totalPx * 100).toFixed(1);
  console.log(`  ${label.padEnd(20)} 采样 ${totalPx} 点：非白 ${nonWhite}（${pct}%），其中近黑（建筑）${dark} → ${nonWhite > totalPx * 0.2 ? "有地图 ✓" : "✗ 几乎是空白"}`);
  return { nonWhite, dark, totalPx };
}
api.view = "tile"; api.showGrid = true; api.setHover([20, 20]);
api.setView("tile"); api.showGrid = true; api.setHover([20, 20]);
frame("（画一帧）");
console.log("  调试 地图→主画布同一像素:", api.mapCtxRef.buf[(300 * 576 + 300) * 3], "→", mainCtx.buf[(300 * 576 + 300) * 3],
  (mainCtx.buf[(300 * 576 + 300) * 3] === api.mapCtxRef.buf[(300 * 576 + 300) * 3] ? "（一致 ✓）" : "（不一致 ✗）"));
const paintedTile = probe("要素视图");
api.view = "both"; api.zalpha = 0.45; api.talpha = 0.85; api.zedge = true;
frame("（切到叠加）");
const paintedBoth = probe("叠加视图");

console.log("\n【缓存失效链】（走工具自己的事件处理器，别直接改变量）");
// 先确认 markMapDirty() 本身有效（若这一步就失败，说明是探针/作用域问题，不是工具的错）
api.markMapDirty();
console.log("  自检：调用 markMapDirty() 后 mapDirty =", api.mapDirty, api.mapDirty ? "✓" : "✗（探针读不到真实变量，后面的结论无效）");
const checks = [
  ["setTile 改格子", () => api.setTile(31, 31, "#")],
  ["切到要素视图", () => api.setView("tile")],
  ["切到叠加视图", () => api.setView("both")],
  ["分区浓淡 0.7", () => api.sliderZAlpha(0.7)],
  ["要素浓淡 0.6", () => api.sliderTAlpha(0.6)],
  ["关掉分区边界线", () => api.sliderZEdge(false)],
];
let allOk = true;
for (const [name, mut] of checks) {
  // 判据（两选一即可，别苛求两者都成立）：
  //   · 改完之后 mapDirty == true  → 下一帧会重画；或
  //   · 改完当场就重画了（setView / 滑杆处理器内部会顺手 draw()，脏标记已被消费）
  // 关键在于"必须有重画发生"，否则用户看到的就是画面僵住。
  const res = api.probeMutation(mut);
  const ok = res.painted > 0;
  allOk = allOk && ok;
  console.log(`  ${name.padEnd(18)} 标脏=${res.dirtyRightAfter ? "✓" : "（已当帧消费）"}  重画 ${String(res.painted).padStart(5)} 格  ${ok ? "✓" : "✗ 地图不会更新"}`);
}
// 单独把 setView 这一个拿细看
api.setView("both");
console.log(`  细看 setView：view=${api.currentView}，当次重画 ${mapCanvas._ctx.paintCount} 格（内部自己 draw 了，所以 mapDirty 已是 false）`);

console.log("\n结论：");
console.log(`  换视图首帧：${Math.max(a1.mapPaints, b1.mapPaints)} 格逐格绘制（这是必须付的钱）`);
console.log(`  稳态每帧：地图层 0 格，总计 ${b2.total} 次调用（2 次贴图 + 光标框）`);
console.log(`  相比改造前（叠加+边界线 6453 次/帧）：约 ${(6453 / Math.max(b2.total, 1)).toFixed(0)}× 的下降`);
console.log(`  主画布内容：要素视图非白 ${paintedTile.nonWhite}/${paintedTile.totalPx}，叠加视图非白 ${paintedBoth.nonWhite}/${paintedBoth.totalPx}`
  + ` → ${paintedBoth.nonWhite > paintedBoth.totalPx * 0.2 ? "地图真的画出来了 ✓" : "✗ 画面是空的"}`);
console.log(`  缓存失效链：${allOk ? "改内容/改样式后都会重画 ✓" : "有漏 ✗"}`);
