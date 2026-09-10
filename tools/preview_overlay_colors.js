// 把"叠加视图"的几种配色方案离屏画出来，编码成 PNG，便于人眼直接比。
//
//   用法：node tools/preview_overlay_colors.js   → 生成 docs/images/叠加视图配色对比.png
//
// 不依赖浏览器：自己实现一个只用到 fillRect / 多边形的 mini canvas + PNG 编码（zlib）。
const fs = require("fs");
const zlib = require("zlib");
const path = require("path");

// ---------- mini Canvas ----------
const RGBA_RE = /^rgba?\(([^)]+)\)$/;
function parseColor(c) {
  if (typeof c !== "string") return [0, 0, 0, 1];
  if (c[0] === "#") {
    const h = c.length >= 9 ? c : c + "ff";
    return [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16),
            parseInt(h.slice(7, 9), 16) / 255];
  }
  const m = RGBA_RE.exec(c);
  if (!m) return [0, 0, 0, 1];
  const p = m[1].split(",").map((s) => parseFloat(s.trim()));
  return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1];
}
class Ctx {
  constructor(w, h) { this.w = w; this.h = h; this.buf = new Float64Array(w * h * 3).fill(255); this.fillStyle = "#000"; }
  _blend(x, y, col) {
    if (x < 0 || y < 0 || x >= this.w || y >= this.h) return;
    const a = col[3];
    if (a <= 0) return;
    const i = (y * this.w + x) * 3;
    for (let k = 0; k < 3; k++) this.buf[i + k] = col[k] * a + this.buf[i + k] * (1 - a);
  }
  fillRect(x, y, w, h) {
    const col = parseColor(this.fillStyle);
    const x0 = Math.floor(x), y0 = Math.floor(y), x1 = Math.ceil(x + w), y1 = Math.ceil(y + h);
    for (let py = y0; py < y1; py++) for (let px = x0; px < x1; px++) this._blend(px, py, col);
  }
  // 简单的多边形扫描（只用于"斜纹"）
  fillPoly(pts) {
    const col = parseColor(this.fillStyle);
    let minY = Infinity, maxY = -Infinity;
    for (const [, py] of pts) { if (py < minY) minY = py; if (py > maxY) maxY = py; }
    for (let py = Math.floor(minY); py <= Math.ceil(maxY); py++) {
      const xs = [];
      for (let i = 0; i < pts.length; i++) {
        const [x1, y1] = pts[i], [x2, y2] = pts[(i + 1) % pts.length];
        if ((y1 <= py && y2 > py) || (y2 <= py && y1 > py)) xs.push(x1 + (py - y1) / (y2 - y1) * (x2 - x1));
      }
      xs.sort((a, b) => a - b);
      for (let i = 0; i + 1 < xs.length; i += 2)
        for (let px = Math.floor(xs[i]); px < Math.ceil(xs[i + 1]); px++) this._blend(px, py, col);
    }
  }
  toPNG() { return encodePNG(this.w, this.h, this.buf); }
}

function encodePNG(w, h, buf) {
  const raw = Buffer.alloc((w * 3 + 1) * h);
  let o = 0;
  for (let y = 0; y < h; y++) {
    raw[o++] = 0;
    for (let x = 0; x < w; x++) {
      const i = (y * w + x) * 3;
      for (let k = 0; k < 3; k++) raw[o++] = Math.max(0, Math.min(255, Math.round(buf[i + k])));
    }
  }
  const chunk = (type, data) => {
    const len = Buffer.alloc(4); len.writeUInt32BE(data.length);
    const td = Buffer.concat([Buffer.from(type, "ascii"), data]);
    const crc = Buffer.alloc(4); crc.writeUInt32BE(crc32(td) >>> 0);
    return Buffer.concat([len, td, crc]);
  };
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(w, 0); ihdr.writeUInt32BE(h, 4);
  ihdr[8] = 8; ihdr[9] = 2; ihdr[10] = 0; ihdr[11] = 0; ihdr[12] = 0;
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", ihdr), chunk("IDAT", zlib.deflateSync(raw, { level: 9 })), chunk("IEND", Buffer.alloc(0)),
  ]);
}
let CRC_T = null;
function crc32(buf) {
  if (!CRC_T) {
    CRC_T = new Int32Array(256);
    for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; CRC_T[n] = c; }
  }
  let c = -1;
  for (let i = 0; i < buf.length; i++) c = CRC_T[(c ^ buf[i]) & 0xff] ^ (c >>> 8);
  return c ^ -1;
}

// ---------- 与工具一致的要素表 / 分区表 ----------
const TILE = { ".": "#ffffff", "+": "#f2f2f2", "#": "#1b1b1b", G: "#c9a227", "=": "#6b6b6b",
               M: "#d8b26a", I: "#6aa8d8", L: "#a87ad8", R: "#6cc07a", T: "#2f6b3a", p: "#e8e0c0" };
const ZONE = { "": "#00000000", r: "#c9a22755", t: "#d8836a55", m: "#d8b26a66", c: "#a87ad855",
               w: "#8b857755", g: "#6cc07a55", o: "#6aa8d855", s: "#b0a08055" };
const ZONE_MAXA = 0x66;

const W = 48, H = 48, Z = 11, GAP = 26;
const { g, z } = sampleMap(W, H);

function sampleMap(W, H) {
  const g = [], z = [];
  for (let y = 0; y < H; y++) { g.push(new Array(W).fill(".")); z.push(new Array(W).fill("")); }
  const set = (x, y, c) => { if (x >= 0 && y >= 0 && x < W && y < H) g[y][x] = c; };
  const setZ = (x, y, c) => { if (x >= 0 && y >= 0 && x < W && y < H) z[y][x] = c; };
  for (let x = 2; x < W - 2; x++) { set(x, 2, "="); set(x, H - 3, "="); }
  for (let y = 2; y < H - 2; y++) { set(2, y, "="); set(W - 3, y, "="); }
  const cx = (W / 2) | 0, cy = (H / 2) | 0;
  for (let d = -1; d <= 1; d++) { set(cx + d, 2, "G"); set(cx + d, H - 3, "G"); set(2, cy + d, "G"); set(W - 3, cy + d, "G"); }
  for (let d = -1; d <= 1; d++) { for (let y = 0; y < H; y++) set(cx + d, y, "+"); for (let x = 0; x < W; x++) set(x, cy + d, "+"); }
  for (const bx of [8, 15, 33, 40]) for (let y = 3; y < H - 3; y++) set(bx, y, "+");
  for (const by of [8, 15, 33, 40]) for (let x = 3; x < W - 3; x++) set(x, by, "+");
  for (let y = 3; y < H - 3; y++) for (let x = 3; x < W - 3; x++) {
    if (g[y][x] !== ".") continue;
    let road = false;
    for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++)
      if (g[y + dy] && g[y + dy][x + dx] === "+") road = true;
    if (road && (x * 7 + y * 13) % 5 !== 0) set(x, y, "#");
  }
  for (const [c, fx, fy, fw, fh] of [["M", 11, 6, 4, 3], ["I", 28, 10, 3, 4], ["L", 35, 28, 4, 4], ["R", 7, 30, 3, 3], ["p", 22, 22, 5, 5]])
    for (let y = fy; y < fy + fh; y++) for (let x = fx; x < fx + fw; x++) set(x, y, c);
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    if (g[y][x] === "=" || g[y][x] === "G") continue;
    const man = Math.abs(x - cx) + Math.abs(y - cy);
    let zn;
    if (man < 7) zn = "m";
    else if (x < cx - 8 && y < cy - 8) zn = "r";
    else if (x > cx + 8 && y < cy - 8) zn = "t";
    else if (x < cx - 8 && y > cy + 8) zn = "w";
    else if (x > cx + 8 && y > cy + 8) zn = "c";
    else if (man > 18) zn = "s";
    else zn = (x + y) % 2 ? "g" : "o";
    setZ(x, y, zn);
  }
  return { g, z };
}

function rgbaColor(hex) {
  const h = hex.length >= 9 ? hex : hex + "ff";
  return [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16), parseInt(h.slice(7, 9), 16) / 255];
}function zoneStyle(zn, alpha) {
  // 分区表里的 alpha 直接当"分区色浓淡"，滑杆做整体倍率（与工具改后的实现一致）
  const c = rgbaColor(ZONE[zn] || "#00000000");
  return `rgba(${c[0]},${c[1]},${c[2]},${(c[3] * alpha).toFixed(3)})`;
}
function tileStyle(ch, alpha) {
  const c = rgbaColor(TILE[ch]);
  return `rgba(${c[0]},${c[1]},${c[2]},${alpha})`;
}
function paintCells(ctx, ox, oy, fn) {
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) fn(ctx, ox + x * Z, oy + y * Z, x, y);
}
function grid(ctx, ox, oy) {
  ctx.fillStyle = "rgba(0,0,0,0.09)";
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const X = ox + x * Z, Y = oy + y * Z;
    ctx.fillRect(X, Y, Z, 1); ctx.fillRect(X, Y, 1, Z);
  }
}
function hatch(ctx, ox, oy) {
  ctx.fillStyle = "rgba(0,0,0,0.10)";
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    if (g[y][x] !== "+") continue;
    const X = ox + x * Z, Y = oy + y * Z;
    ctx.fillPoly([[X, Y + Z * 0.72], [X + Z * 0.72, Y], [X + Z, Y], [X + Z, Y + Z * 0.28], [X + Z * 0.28, Y + Z], [X, Y + Z]]);
  }
}

// ---------- 四种方案 ----------
// 结论先说：分区色本身太淡（0.33 alpha 的浅色），想靠"给要素上色"来读出分区是不可能的
// （实测任意不透明度下分区间色距都 ≤4）。所以叠加视图给分区**单独一条视觉通道**：
// 底色 + 边界线（地形图的分区界），要素则按墨色正常画。
function drawZoneFill(ctx, ox, oy, alpha) {
  paintCells(ctx, ox, oy, (c, X, Y, x, y) => {
    const zn = z[y][x];
    if (zn) { c.fillStyle = zoneStyle(zn, alpha); c.fillRect(X, Y, Z, Z); }
  });
}
function drawElems(ctx, ox, oy, alpha, monochrome) {
  paintCells(ctx, ox, oy, (c, X, Y, x, y) => {
    const ch = g[y][x];
    if (ch === ".") return;
    const i = ch === "#" ? 0 : 1;
    c.fillStyle = monochrome ? `rgba(74,74,74,${alpha})` : tileStyle(ch, alpha);
    c.fillRect(X + i, Y + i, Z - i * 2, Z - i * 2);
  });
}// 分区边界：某格与邻格分区不同 → 在公共边上画一条该分区的实色线（2px）
function drawZoneBorders(ctx, ox, oy) {
  const w = Math.max(2, Math.round(Z * 0.22));
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const zn = z[y][x];
    if (!zn) continue;
    const X = ox + x * Z, Y = oy + y * Z;
    const c = rgbaColor(ZONE[zn]);
    ctx.fillStyle = `rgba(${c[0]},${c[1]},${c[2]},0.9)`;
    const same = (ax, ay) => {
      if (ax < 0 || ay < 0 || ax >= W || ay >= H) return true;   // 图外不算边界
      return z[ay][ax] === zn;
    };
    if (!same(x - 1, y)) ctx.fillRect(X, Y, w, Z);
    if (!same(x + 1, y)) ctx.fillRect(X + Z - w, Y, w, Z);
    if (!same(x, y - 1)) ctx.fillRect(X, Y, Z, w);
    if (!same(x, y + 1)) ctx.fillRect(X, Y + Z - w, Z, w);
  }
}

const panels = [
  ["A 现状：要素压成 #4a4a4a + 分区乘 0.6", "建筑/道路同为 74,74,74；分区差异只有 D4 —— 这就是「效果不理想」的原因", (ctx, ox, oy) => {
    drawElems(ctx, ox, oy, 1.0, true);
    paintCells(ctx, ox, oy, (c, X, Y, x, y) => { if (z[y][x]) { c.fillStyle = zoneStyle(z[y][x], 0.45 * 0.6); c.fillRect(X, Y, Z, Z); } });
  }],
  ["B 分区打底 0.45 + 要素 0.60", "要素变成灰纱（建筑/道路可分但要凑近看），分区仍只有 D2", (ctx, ox, oy) => {
    drawZoneFill(ctx, ox, oy, 0.45);
    drawElems(ctx, ox, oy, 0.6, false);
  }],
  ["C 分区打底 0.45 + 要素 0.85 + 分区边界线", "要素清楚(墨色/近白)，分区靠边界线读 —— 推荐", (ctx, ox, oy) => {
    drawZoneFill(ctx, ox, oy, 0.45);
    drawElems(ctx, ox, oy, 0.85, false);
    drawZoneBorders(ctx, ox, oy);
  }],
  ["D 只有边界线（分区底色 0.18）", "分区区域感弱一些，要素最干净", (ctx, ox, oy) => {
    drawZoneFill(ctx, ox, oy, 0.18);
    drawElems(ctx, ox, oy, 0.95, false);
    drawZoneBorders(ctx, ox, oy);
  }],
];

const cols = 2, rows = Math.ceil(panels.length / cols);
const PW = W * Z + GAP, PH = H * Z + GAP;
const ctx = new Ctx(PW * cols + GAP, PH * rows + GAP);
ctx.fillStyle = "#14161a";
ctx.fillRect(0, 0, ctx.w, ctx.h);
// 标题文字用"色块条"代替（mini canvas 不画字）：每条方案上方画一条代表色带
const accent = ["#c96a6a", "#6cc07a", "#6aa8d8", "#d8b26a"];
panels.forEach(([, , draw], i) => {
  const ox = GAP + (i % cols) * PW, oy = GAP + Math.floor(i / cols) * PH;
  ctx.fillStyle = "#ffffff"; ctx.fillRect(ox, oy, W * Z, H * Z);
  draw(ctx, ox, oy);
  grid(ctx, ox, oy);
  ctx.fillStyle = accent[i]; ctx.fillRect(ox, oy - 12, 60, 8);
});
// 落盘在最后（评分跑完之后），见文件末尾
console.log("左上=A现状，右上=B，左下=C，右下=D；每张图中间是主干街十字，四周是各分区。");
// ---------- 客观评分 ----------
// 两张表回答两个不同的问题（都取"最小色距"，越小越难分辨，人眼约 <10 基本看不出）：
//   T1 排列可分：不同 (要素, 分区) 组合之间会不会撞色 → 越大越好
//   T2 同要素看分区：同一要素下相邻分区的色距       → 越大越好（叠加视图的核心诉求）
//   T3 同分区看要素：同一分区下建筑 vs 道路的色距   → 越大越好
function cellsOf(ch, zn) {
  const out = [];
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) if (g[y][x] === ch && z[y][x] === zn) out.push([x, y]);
  return out;
}
function sampleAvg(ctx, ox, oy, ch, zn, aMap) {
  const cells = cellsOf(ch, zn);
  if (!cells.length) return null;
  const acc = [];
  for (const [x, y] of cells) {
    const px = ox + x * Z + (Z >> 1), py = oy + y * Z + (Z >> 1);
    const i = (py * ctx.w + px) * 3;
    acc.push([ctx.buf[i], ctx.buf[i + 1], ctx.buf[i + 2]]);
  }
  return [0, 1, 2].map((k) => acc.reduce((s, c) => s + c[k], 0) / acc.length);
}
const dist = (a, b) => (a && b ? Math.sqrt(a.reduce((s, v, i) => s + (v - b[i]) ** 2, 0)) : null);
const zonesOn = ["r", "t", "w", "c", "m", "s", "g", "o"];
const elems = ["#", "+", "M", "p"];

function score(ctx, ox, oy) {
  const pos = [];
  for (const ch of elems) for (const zn of zonesOn) {
    const c = sampleAvg(ctx, ox, oy, ch, zn);
    if (c) pos.push({ ch, zn, c });
  }
  let t1 = Infinity;
  for (let a = 0; a < pos.length; a++) for (let b = a + 1; b < pos.length; b++) {
    if (pos[a].ch === pos[b].ch && pos[a].zn === pos[b].zn) continue;
    t1 = Math.min(t1, dist(pos[a].c, pos[b].c));
  }
  // T2：同一要素下，各分区的两两最小色距（取所有要素里最差的那个）
  let t2 = Infinity;
  for (const ch of elems) {
    const list = pos.filter((p) => p.ch === ch).map((p) => p.c);
    for (let a = 0; a < list.length; a++) for (let b = a + 1; b < list.length; b++) t2 = Math.min(t2, dist(list[a], list[b]));
  }
  if (globalThis.__DBG) {
    const b = pos.filter((p) => p.ch === "#");
    console.log("    DBG 建筑采样:", b.map((p) => p.zn + "=" + p.c.map((v) => Math.round(v)).join(",")).join("  "));
    const r = pos.filter((p) => p.ch === "+");
    console.log("    DBG 道路采样:", r.map((p) => p.zn + "=" + p.c.map((v) => Math.round(v)).join(",")).join("  "));
    console.log("    DBG zoneStyle(r,0.45)=" + zoneStyle("r", 0.45) + "  parse=" + parseColor(zoneStyle("r", 0.45)).join(","));
  }
  // T3：同一分区下，建筑 vs 道路（取所有分区里最差的那个）
  let t3 = Infinity;
  for (const zn of zonesOn) {
    const a = pos.find((p) => p.ch === "#" && p.zn === zn);
    const b = pos.find((p) => p.ch === "+" && p.zn === zn);
    if (a && b) t3 = Math.min(t3, dist(a.c, b.c));
  }
  return { t1: Math.round(t1), t2: Math.round(t2), t3: Math.round(t3) };
}

const pngPath = path.join(__dirname, "..", "docs", "images", "叠加视图配色对比.png");
fs.mkdirSync(path.dirname(pngPath), { recursive: true });
fs.writeFileSync(pngPath, ctx.toPNG());
console.log("已生成 " + pngPath + `  (${ctx.w}×${ctx.h})`);
console.log("左上=A现状，右上=B，左下=C，右下=D；每张图中间是主干街十字，四周是各分区。");

console.log("");
console.log("方案                                 T1 排列可分   T2 同要素看分区   T3 同分区看要素");
panels.forEach(([title], i) => {
  const ox = GAP + (i % cols) * PW, oy = GAP + Math.floor(i / cols) * PH;
  const s = score(ctx, ox, oy);
  console.log(title.padEnd(34) + String(s.t1).padStart(6) + String(s.t2).padStart(14) + String(s.t3).padStart(15));
});
console.log("");
console.log("A 现状的 T3 = 0：建筑与道路在同一分区里像素完全相同（都被压成 #4a4a4a）。");
console.log("B/C/D 的 T3 很大（要素可分），但 T2 会暴露「分区色能不能透出来」——见下面的扫描表。");

// ---------- 扫描：要素不透明度 vs "分区色能透出多少" ----------
console.log("");
console.log("=== 扫描：要素不透明度 → 分区色还剩多少（以建筑为例，滑杆 0.45）===");
const backdrop = (zn) => {
  const c = rgbaColor(ZONE[zn]);
  const a = c[3] * 0.45;
  return [0, 1, 2].map((k) => c[k] * a + 255 * (1 - a));
};
for (const alpha of [0.95, 0.85, 0.75, 0.65, 0.6, 0.5, 0.4, 0.3]) {
  const base = rgbaColor(TILE["#"]);
  const cols2 = zonesOn.map((zn) => {
    const bd = backdrop(zn);
    return [0, 1, 2].map((k) => base[k] * alpha + bd[k] * (1 - alpha));
  });
  let mn = Infinity;
  for (let a = 0; a < cols2.length; a++) for (let b = a + 1; b < cols2.length; b++) mn = Math.min(mn, dist(cols2[a], cols2[b]));
  const roadSep = (() => {
    const rb = rgbaColor(TILE["+"]);
    const rc = zonesOn.map((zn) => { const bd = backdrop(zn); return [0, 1, 2].map((k) => rb[k] * alpha + bd[k] * (1 - alpha)); });
    const bd = backdrop("r");
    const bd2 = [0, 1, 2].map((k) => rb[k] * alpha + bd[k] * (1 - alpha));
    const bi = [0, 1, 2].map((k) => base[k] * alpha + bd[k] * (1 - alpha));
    return Math.sqrt(bd2.reduce((s, v, k) => s + (v - bi[k]) ** 2, 0));
  })();
  console.log(`  要素不透明度 ${alpha.toFixed(2)} → 分区间最小色距 ${String(Math.round(mn)).padStart(3)}`
    + `   建筑/道路可分 ${String(Math.round(roadSep)).padStart(3)}`
    + (mn >= 12 && roadSep >= 80 ? "   ← 两者兼顾" : ""));
}
console.log("（目标：分区间 ≥12 能看出区别；建筑/道路 ≥80 一眼分得开）");
