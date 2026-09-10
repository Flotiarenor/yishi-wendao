// 把给定的城镇 JSON 喂给 tools/town_editor.html 里的 diagnose()，原样打印它报什么。
//   用法：node tools/run_town_diagnose.js tools/_user_town.json
//
// 注意：诊断脚本里**不要**用 api.grid 去扫图——那个绑定在这个作用域里不存在，
// 会静默拿到空桩；一律用 api.at(x, y) / api.snapshot()。
const fs = require("fs");
const path = require("path");
const html = fs.readFileSync(path.join(__dirname, "town_editor.html"), "utf8");
const code = html.match(/<script>([\s\S]*?)<\/script>/)[1];

// ---------- 最小 DOM 桩 ----------
const elements = {};
const ctx = {
  fillStyle: "", strokeStyle: "", lineWidth: 1,
  fillRect() {}, strokeRect() {}, beginPath() {}, moveTo() {}, lineTo() {}, ellipse() {},
  stroke() {}, rect() {}, save() {}, restore() {},
};
const mkEl = (id) => ({
  id, value: id === "gw" || id === "gh" ? "48" : id === "gz" ? "12" : id === "roadW" ? "3" : "",
  textContent: "", innerHTML: "", style: {}, dataset: {}, children: [], checked: false, files: null,
  classList: { toggle() {}, add() {}, remove() {} },
  appendChild(c) { this.children.push(c); }, addEventListener() {},
  getContext: () => ctx, getBoundingClientRect: () => ({ left: 0, top: 0 }),
  setPointerCapture() {}, click() { this.onclick && this.onclick(); },
  parentElement: { scrollLeft: 0, scrollTop: 0 },
});
const document = {
  getElementById: (id) => elements[id] || (elements[id] = mkEl(id)),
  createElement: () => ({ style: {}, dataset: {}, children: [], classList: { toggle() {} }, appendChild() {}, set innerHTML(v) {}, get innerHTML() { return ""; } }),
  addEventListener() {}, querySelector: () => null,
};
const window = { clipboard: { writeText: async () => {} }, addEventListener() {} };
const navigator = { clipboard: { writeText: async () => {} } };
globalThis.confirm = () => true;
const FileReader = class { readAsText() {} };
const requestAnimationFrame = (f) => setTimeout(f, 0);

const api = new Function(
  "document", "window", "navigator", "FileReader", "requestAnimationFrame", "confirm",
  code + "\n;return { importJson, diagnose, get W(){return W}, get H(){return H}, at, " +
  "snapshot(){ return { rows: grid.map(r => r.join('')), zone_rows: zones.map(r => r.map(c => c || ' ').join('')) }; } };"
)(document, window, navigator, FileReader, requestAnimationFrame, confirm);

const text = fs.readFileSync(process.argv[2], "utf8");
const ok = api.importJson(text);
console.log("导入结果 =", ok, `  画布 ${api.W}×${api.H}`);
const d = api.diagnose();
console.log("\nerrors:");
if (!d.errs.length) console.log("  （无）");
d.errs.forEach((e) => console.log("  ✗ " + e));
console.log("warnings:");
if (!d.warns.length) console.log("  （无）");
d.warns.forEach((e) => console.log("  ! " + e));
console.log(`\n道路连通段=${d.comps}（城内 ${d.insideSegs}，最大 ${d.biggest}）｜ 城门格=${d.gates} ｜ 空旷率=${(d.emptyRatio * 100).toFixed(0)}%`);
console.log("设施=" + JSON.stringify(d.fac));

// 逐门打印四个邻居
const G = [];
for (let y = 0; y < api.H; y++) for (let x = 0; x < api.W; x++) if (api.at(x, y) === "G") G.push([x, y]);
console.log(`\n共 ${G.length} 个城门格，各自四正方向邻居：`);
for (const [x, y] of G) {
  const nb = `上${api.at(x, y - 1)} 下${api.at(x, y + 1)} 左${api.at(x - 1, y)} 右${api.at(x + 1, y)}`;
  const ok4 = [api.at(x, y - 1), api.at(x, y + 1), api.at(x - 1, y), api.at(x + 1, y)].includes("+");
  console.log(`  (${x},${y}) ${nb}  → ${ok4 ? "有路可走" : "✗ 四面无路"}`);
}
