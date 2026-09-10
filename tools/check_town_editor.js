// 用最小 DOM 桩在 Node 里跑 tools/town_editor.html 的完整逻辑
// （初始化 + 生成器 + 体检 + 撤销 + 导入导出），改完工具先跑一遍做回归。
//
//   用法：node tools/check_town_editor.js tools/town_editor.html [content/town_layouts.py]
//
// 配套：tools/check_town_layouts.py（引擎侧 facilities() / 道路分段口径对照）。
const fs = require("fs");
const html = fs.readFileSync(process.argv[2], "utf8");
const code = html.match(/<script>([\s\S]*?)<\/script>/)[1];

const ids = [...html.matchAll(/id="([^"]+)"/g)].map((m) => m[1]);
const stats = { fillRect: 0, strokeRect: 0, stroke: 0, rect: 0 };
const elements = {};
for (const id of ids) {
  elements[id] = {
    id, value: id === "gw" ? "48" : id === "gh" ? "48" : id === "gz" ? "12" : id === "roadW" ? "3" : "",
    textContent: "", innerHTML: "", style: {}, dataset: {}, children: [],
    classList: { toggle() {}, add() {}, remove() {} },
    checked: false, files: null,
    appendChild(c) { this.children.push(c); },
    addEventListener() {}, removeEventListener() {},
    getContext() { return ctx; },
    getBoundingClientRect() { return { left: 0, top: 0, width: 0, height: 0 }; },
    setPointerCapture() {}, click() { if (this.onclick) this.onclick(); },
    parentElement: { scrollLeft: 0, scrollTop: 0 },
    querySelector() { return null; },
  };
}
// 记录每次 fillRect 用的颜色：stub 不画像素，颜色是断言"渲染成什么样"的唯一可靠依据
const paints = [];
const ctx = {
  fillStyle: "", strokeStyle: "", lineWidth: 1,
  fillRect(x, y, w, h) { stats.fillRect++; paints.push(String(this.fillStyle)); },
  strokeRect() { stats.strokeRect++; },
  beginPath() {}, moveTo() {}, lineTo() {}, ellipse() {}, stroke() { stats.stroke++; },
  rect() { stats.rect++; }, save() {}, restore() {},
};
// #cv 的宽高要跟 setter 一起记账
let canvasW = 0, canvasH = 0;
elements["cv"] = Object.assign(elements["cv"], {
  _w: { v: 0 }, _h: { v: 0 },
  get width() { return this._w.v; }, set width(v) { this._w.v = v; canvasW = v; },
  get height() { return this._h.v; }, set height(v) { this._h.v = v; canvasH = v; },
});

const docHandlers = {};
const document = {
  getElementById: (id) => elements[id] || (elements[id] = { style: {}, classList: { toggle() {} }, children: [], appendChild() {}, dataset: {} }),
  createElement: () => ({
    style: {}, dataset: {}, children: [],
    classList: { toggle() {}, add() {}, remove() {} },
    set innerHTML(v) { this._h = v; }, get innerHTML() { return this._h; },
    set onclick(f) { this._f = f; }, get onclick() { return this._f; },
    appendChild() {},
  }),
  addEventListener: (t, f) => { (docHandlers[t] = docHandlers[t] || []).push(f); },
  querySelector: () => null,
};
const window = { clipboard: { writeText: async () => {} }, addEventListener() {} };
let confirmed = null;
globalThis.confirm = (m) => { confirmed = m; return true; };
const alert = () => {};
const requestAnimationFrame = (f) => setTimeout(f, 0);
const navigator = { clipboard: { writeText: async () => {} } };
const FileReader = class { readAsText() {} };

// document 里 #out 的初始文本（导入空判断要用）
elements["out"].textContent = "（导出结果会出现在这里；也可以把 JSON 粘进来再点「从下面文本框导入」）";

const run = new Function(
  "document", "window", "navigator", "FileReader", "requestAnimationFrame", "confirm", "alert",
  code + "\n;return { get grid(){return grid}, get zones(){return zones}, get W(){return W}, get H(){return H}, " +
  "get undoStack(){return undoStack}, get redoStack(){return redoStack}, get at(){return at}, " +
  "genGridRoads, genWall, genBlocks, genZones, genFill, genTidy, diagnose, facilityCounts, " +
  "wallBreaches, roadComponents, roadDistMap, facilitiesDetailed, exportJson, undo, redo, " +
  "setTile, setZone, blank, resizeCanvas, draw, beginGesture, endGesture, applyBrushAt, bucket, " +
  "setMode, setTool, setView, zoneMult, tileStyleOf, TILE, get tileAlphaRaw(){return typeof tileAlpha === \"undefined\" ? \"UNDEF\" : tileAlpha}, get viewRaw(){return view}, zoneStyles, zoneEdgeStyles, buildZoneLegend, " +
  "get view(){return view}, set view(v){view=v}, get zoneAlpha(){return zoneAlpha}, set zoneAlpha(v){zoneAlpha=v}, " +
  "get tileAlpha(){return tileAlpha}, set tileAlpha(v){tileAlpha=v}, " +
  "get showZoneEdge(){return showZoneEdge}, set showZoneEdge(v){showZoneEdge=v}, " +
  "importJson, keydownHandler: null, get canvasSize(){return [cv.width, cv.height]} };"
);
const api = run(document, window, navigator, FileReader, requestAnimationFrame, confirm, alert);

function rowCounts(g) {
  const c = {};
  for (const row of g) for (const ch of row) c[ch] = (c[ch] || 0) + 1;
  return c;
}
const log = (s) => console.log(s);

log("=== 初始化 ===");
log(`画布 ${api.W}×${api.H}，canvas 像素 ${api.canvasSize[0]}×${api.canvasSize[1]}，格 ${JSON.parse(JSON.stringify(api.W)) * 0 + 12}px`);
log(`初次 draw 统计：fillRect ${stats.fillRect}，strokeRect ${stats.strokeRect}，批量 rect ${stats.rect}，stroke ${stats.stroke}`);
log("（网格线已批量：strokeRect 应为 0，rect 应为 48*48=2304）");

log("\n=== 生成器 ===");
api.genGridRoads();
log("正交街网：" + JSON.stringify(rowCounts(api.grid)["+"] ? { 道路: rowCounts(api.grid)["+"] } : {}));
api.genWall();
let c1 = rowCounts(api.grid);
log("城墙+四门：" + JSON.stringify({ 墙: c1["="], 门: c1["G"], 路: c1["+"] }));
api.genBlocks();
api.genZones();
let c2 = rowCounts(api.grid);
log("沿街补建筑：" + JSON.stringify({ 建筑: c2["#"] }));
let d1 = api.diagnose();
log("体检#1 errors=" + d1.errs.length + " warnings=" + d1.warns.length);
d1.errs.forEach((e) => log("  ✗ " + e));
d1.warns.slice(0, 3).forEach((e) => log("  ! " + e));
log("  道路段=" + d1.comps + " 城内段=" + d1.insideSegs + " 城门=" + d1.gates);
log("  设施=" + JSON.stringify(d1.fac));

log("\n=== 城墙撞穿检测（按格子判，不再写死 y=2）===");
// 把墙挪到 y=4 手画（旧版只在 y=2 找），再让一条路真的穿过墙体
api.blank(48, 48);
for (let x = 1; x < 47; x++) { api.setTile(x, 4, "="); api.setTile(x, 43, "="); }
for (let y = 1; y < 47; y++) { api.setTile(4, y, "="); api.setTile(43, y, "="); }
api.setTile(19, 3, "+"); api.setTile(20, 3, "+"); api.setTile(21, 3, "+");   // 墙北侧一条路
api.setTile(19, 5, "+"); api.setTile(20, 5, "+"); api.setTile(21, 5, "+");   // 墙南侧一条路
// 于是 (20,4) 这格城墙"左右/上下都有路" —— 路真的从墙上穿过去了
let br = api.wallBreaches();
const brOk = br.length === 3 && br.every(([, y]) => y === 4);
log("墙在 y=4（旧版只查 y=2），撞穿点=" + JSON.stringify(br) + (brOk ? "  ✓ 检出 3 格（旧版固定 y===2 会报 0）" : "  ✗ 漏报/误报"));

log("\n=== 城门判据（用户的青石镇实测：8/8 假警报）===");
api.blank(24, 24);
// 横墙上开一个门，门上下两侧都有路 → 必须判"通"
for (let x = 5; x < 19; x++) api.setTile(x, 5, "=");
api.setTile(11, 5, "G");
api.setTile(11, 4, "+"); api.setTile(11, 6, "+");     // 门上方 + 下方都有路
let g = api.diagnose();
log("门上下有路时 errors=" + g.errs.length + (g.errs.length === 0 ? "  ✓ 不误报（旧版按坐标猜朝向，会报成 8/8 全坏）" : "  ✗ 仍误报：" + g.errs[0]));
// 真正的坏门：四周一点路都没有 → 必须报
api.blank(24, 24);
for (let x = 5; x < 19; x++) api.setTile(x, 5, "=");
api.setTile(11, 5, "G");
g = api.diagnose();
log("门四周无路时 errors=" + g.errs.length + (g.errs.length === 1 && g.errs[0].includes("四面都没有路") ? "  ✓ 真问题报得出" : "  ✗ 漏报"));
// 斜向有路：按"四正方向"判 → 仍应算不通（引擎口径也是四正方向）
api.setTile(11, 4, ".");                              // 撤掉正上方的路，只留斜向
api.setTile(12, 4, "+");
g = api.diagnose();
log("只有斜向有路时 errors=" + g.errs.length + (g.errs.length === 1 ? "  ✓ 仍算不通（斜向不算挨着）" : "  ✗ 判成通了"));

log("\n=== genFill（城内铺满）===");
api.blank(48, 48);
for (let x = 2; x < 46; x++) { api.setTile(x, 2, "="); api.setTile(x, 45, "="); }
for (let y = 2; y < 46; y++) { api.setTile(2, y, "="); api.setTile(45, y, "="); }
api.setTile(24, 2, "G"); api.setTile(24, 45, "G");
api.setTile(24, 3, "+"); api.setTile(24, 24, "+"); api.setTile(24, 44, "+");
api.genFill();
const fc = rowCounts(api.grid);
let outsideEmpty = 0;
for (let y = 0; y < 48; y++) for (let x = 0; x < 48; x++) if (api.grid[y][x] === "." && (x < 2 || y < 2 || x > 45 || y > 45)) outsideEmpty++;
log("城内补建筑后：" + JSON.stringify({ 建筑: fc["#"], 空: fc["."], 墙外仍空: outsideEmpty }));
log(outsideEmpty === 368 ? "  ✓ 城外没被误填（368 = 城墙外环）" : "  ✗ 城外被误填");

log("\n=== genTidy（补门路 + 接孤岛 + 设施拉路）===");
api.blank(20, 20);
api.setTile(10, 10, "+");
api.setTile(15, 15, "+");        // 孤岛一格
api.setTile(5, 5, "I");          // 不贴路的客栈
api.genTidy();
const tc = rowCounts(api.grid);
log("接回后道路=" + tc["+"]);
const comps = api.roadComponents();
log("道路段数=" + comps.length + (comps.length === 1 ? "  ✓ 已接成一网" : "  ✗ 仍有孤岛：" + JSON.stringify(comps.map((c) => c.slice(0, 6)))));
const inn = api.facilitiesDetailed().find((f) => f.name === "客栈");
log("客栈 on_road=" + (inn && inn.onRoad) + (inn && inn.onRoad ? "  ✓ 已拉路" : "  ✗ 仍不可达"));

log("\n=== 设施口径与引擎对齐（含城门 G、只认四正方向 2 格内）===");
api.blank(20, 20);
api.setTile(5, 5, "I");           // 客栈
api.setTile(7, 5, "+");           // 正东 2 格有路 → 引擎 r=1..2 判"可达"
const d2 = api.roadDistMap();
log("(5,5) 到最近道路的正交距离=" + d2[5 * 20 + 5] + " → 引擎口径 on_road=" + (d2[5 * 20 + 5] <= 2) + "，编辑器=" + api.facilitiesDetailed()[0].onRoad);
log("✓ 编辑器与引擎同口径（旧版用 5×5 方框，斜向有路也会判可达）");
api.setTile(10, 10, "G");
const kinds = api.facilityCounts();
log("设施计数=" + JSON.stringify(kinds) + (kinds["城门"] === 1 ? "  ✓ 城门已计入（与引擎 FACILITY_CHARS 一致）" : "  ✗ 城门漏了"));

log("\n=== 叠加视图配色（本次重做）===");
api.blank(20, 20);
api.setTile(5, 5, "#");          // 建筑
api.setZone(5, 5, "r");
api.setTile(6, 5, "+");          // 道路
api.setZone(6, 5, "r");
api.setZone(7, 5, "t");          // 换一种分区 → 应该出现边界线
api.view = "both"; api.zoneAlpha = 0.45; api.tileAlpha = 0.85;
log("zoneMult() = " + api.zoneMult() + (api.zoneMult() === 0.45 ? "  ✓ 分区底色不再被额外乘 0.6（旧版乘了 0.6，等于白画）" : "  ✗"));
log("tileStyleOf('#') = " + api.tileStyleOf("#") + (api.tileStyleOf("#").startsWith("rgba(") ? "  ✓ 叠加时按不透明度画（旧版一律 #4a4a4a）" : "  ✗ 仍是原色，会盖死分区底色"));
log("tileStyleOf('#', 1.0) = " + api.tileStyleOf("#", 1.0) + "（要素浓淡拉满 → 回原色）");

// 端到端：让编辑器自己画一遍，看它实际提交给 canvas 的颜色
paints.length = 0;
api.draw();
const uniq = [...new Set(paints)].map((c) => c.replace(/,(0?\.\d+)\)$/, (_, n) => "," + Number(n).toFixed(2) + ")"));
const paintOk = {
  "建筑墨色 rgba(27,27,27,0.85)": uniq.includes("rgba(27,27,27,0.85)"),
  "道路墨色 rgba(242,242,242,0.85)": uniq.includes("rgba(242,242,242,0.85)"),
  "分区底色 rgba(201,162,39,0.15)": uniq.includes("rgba(201,162,39,0.15)"),
  "分区边界线 rgba(201,162,39,0.92)": uniq.includes("rgba(201,162,39,0.92)"),
};
log("编辑器实画颜色：" + Object.entries(paintOk).map(([k, v]) => (v ? "✓ " : "✗ ") + k).join("  "));
log("  用到的颜色：" + uniq.join(" | "));
paints.length = 0;
api.showZoneEdge = false; api.draw();
const withoutEdge = paints.some((c) => c === "rgba(201,162,39,0.92)");
api.showZoneEdge = true;
log("关掉「分区边界线」后还画边界线吗：" + (withoutEdge ? "✗ 还画" : "✓ 不画了（开关有效）"));
paints.length = 0;
api.view = "tile"; api.draw();
const leaked = [...new Set(paints)].some((c) => c.includes("201,162,39"));
log("切回要素视图后有没有残留分区色：" + (leaked ? "✗ 有残留" : "✓ 没有（干净）"));
api.view = "both";

log("\n=== 撤销：空操作不入栈 ===");
api.blank(20, 20);
const u0 = api.undoStack.length;
api.beginGesture(); api.applyBrushAt(3, 3, false); api.endGesture();
const u1 = api.undoStack.length;
api.beginGesture(); api.applyBrushAt(3, 3, false); api.endGesture();   // 同一格重复画
const u2 = api.undoStack.length;
log(`初始 ${u0} → 画 1 格 ${u1} → 同格重画 ${u2}` + (u1 === u0 + 1 && u2 === u1 ? "  ✓ 空操作未入栈" : "  ✗ 仍占栈"));

log("\n=== 撤销：跨尺寸后尺寸输入框自动同步 ===");
api.blank(20, 20);
elements["gw"].value = "30"; elements["gh"].value = "30"; elements["gz"].value = "8";
elements["apply"].onclick();          // 走应用自己的「应用尺寸」处理器（含 confirm）
log(`应用尺寸后 ${api.W}×${api.H}，输入框 gw=${elements["gw"].value}`);
api.undo();                           // 再撤销回 20×20
const syncOk = String(elements["gw"].value) === String(api.W) && String(elements["gh"].value) === String(api.H);
log(`撤销后 W×H=${api.W}×${api.H}，输入框 gw=${elements["gw"].value} gh=${elements["gh"].value} | 网格 ${api.grid.length}×${api.grid[0].length}`
  + (syncOk ? "  ✓ 输入框跟着撤销走（旧版会停在 30×30）" : "  ✗ 输入框与画布不一致"));
log("\n=== 导出 JSON ===");
api.blank(48, 48);
api.genWall();
api.setTile(10, 10, "M"); api.setTile(24, 24, "p");
api.exportJson();
const out = JSON.parse(elements["out"].textContent);
log("字段：" + Object.keys(out).join(", "));
log(`w=${out.w} h=${out.h} rows=${out.rows.length} zone_rows=${out.zone_rows.length} editor=${out.editor}`);
log("facilities=" + JSON.stringify(out.facilities));
log("facility_detail[0]=" + JSON.stringify(out.facility_detail[0]));
log("zone_rows 行宽是否都等于 48：" + (out.zone_rows.every((r) => r.length === 48) ? "✓" : "✗ " + out.zone_rows.map((r) => r.length).join(",")));
log("rows 行宽是否都等于 48：" + (out.rows.every((r) => r.length === 48) ? "✓" : "✗"));

log("\n=== 导入回环 ===");
const ok = api.importJson(elements["out"].textContent);
log("importJson=" + ok + ` 尺寸 ${api.W}×${api.H}`);
log("提示：" + elements["impMsg"].innerHTML.replace(/<[^>]+>/g, "").trim());

log("\n=== 性能：120×120 全图 draw 的格子级 API 调用 ===");
api.blank(120, 120);
for (let x = 0; x < 120; x++) for (let y = 0; y < 120; y++) { if ((x + y) % 7 === 0) api.setTile(x, y, "+"); }
stats.fillRect = stats.strokeRect = stats.rect = stats.stroke = 0;
const t0 = process.hrtime.bigint();
api.draw();
const t1 = process.hrtime.bigint();
log(`14400 格 draw：${Number(t1 - t0) / 1e6}ms（桩函数，仅作结构参考）；fillRect=${stats.fillRect} rect=${stats.rect} stroke=${stats.stroke}`);
log("（优化前：每格 1 次 strokeRect 网格线；现在网格线合计 1 次 stroke）");

if (!process.argv[3]) {
  log("\n（未传 content/town_layouts.py，跳过模板回放）");
  process.exit(0);
}
log("\n=== 回放仓库里已存的青石镇模板（content/town_layouts.py 的 _EXPORTS[0]）===");
const py = fs.readFileSync(process.argv[3], "utf8");
const block = py.slice(py.indexOf("_EXPORTS"), py.indexOf("LAYOUTS:"));
const tileBlock = block.slice(0, block.indexOf('"zone_rows"'));
const zoneBlock = block.slice(block.indexOf('"zone_rows"'));
const rows = [...tileBlock.matchAll(/"([.+#=MILRTp]{48})"/g)].map((m) => m[1]);
const zoneRows = [...zoneBlock.matchAll(/"([ rt mcwgos]{48})"/g)].map((m) => m[1]);
const legacy = { name: "青石镇", tier: "outer", road_width: 3, rows, zone_rows: zoneRows };
log(`从模板取出 rows=${rows.length} 行，zone_rows=${zoneRows.length} 行`);
const legacyOk = api.importJson(JSON.stringify(legacy));
log("导入=" + legacyOk + ` 尺寸 ${api.W}×${api.H}`);
const ld = api.diagnose();
log("体检：errors=" + ld.errs.length + " warnings=" + ld.warns.length);
ld.errs.forEach((e) => log("  ✗ " + e));
log("城门=" + ld.gates + " 道路段=" + ld.comps + " 城内段=" + ld.insideSegs);
log("设施=" + JSON.stringify(ld.fac));
log("（引擎侧同图 facilities() 的计数应与此一致：坊市/客栈/藏经阁/静室/广场/城门）");
