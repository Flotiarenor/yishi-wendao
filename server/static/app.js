/* 极简修仙面板（P3.6 · 原生 JS，无构建无 CDN）
 *
 * 规则：
 *  - 一切成败只看响应 `ok/reason`（REASON_TEXT 映射中文提示），**禁止解析 text 判断成败**；
 *  - `text`/`lines` 只追加进叙事日志流；
 *  - 状态面板/战斗面板只消费 `state`（服务端 Game.state_data() 快照）。
 */
"use strict";

const $ = (id) => document.getElementById(id);

// ---------- reason → 中文提示（错误提示唯一来源，不解析 text） ----------
const REASON_TEXT = {
  ok: "成功",
  unknown_action: "未知动作",
  unknown_item: "查无此物 / 功法",
  unknown_enemy: "无此敌人",
  in_battle: "战斗中只能使用战斗指令",
  not_in_battle: "当前不在战斗中",
  not_owned: "尚未拥有该功法（先到坊市购得）",
  realm_gate: "境界未至，书文晦涩看不懂",
  not_entry: "尚未参悟入门（先闭关参悟）",
  fam_max: "已参悟至大成，无需再参悟",
  type_mismatch: "功法类型与所选槽位不符",
  slot_occupied: "槽位已被占据，先卸下再装",
  slot_invalid: "无效槽位",
  slot_empty: "该槽位为空",
  already_equipped: "该功法已在槽位中",
  dup_owned: "已拥有该功法，无需重复购买",
  not_market: "此物坊市不售",
  not_at_market: "须身处【坊市】才能看货单/购买",
  no_stones: "灵石不足",
  no_pill: "背包里没有此丹",
  pill_use_wrong: "此丹为突破丹药，不可直接服用",
  not_breakable: "修为未满，尚不可突破",
  max_realm: "已至人间顶峰，无更高境界",
  no_pill_data: "此境界突破丹药未配置",
  missing_pill: "缺少突破所需丹药",
  site_invalid: "无此地名",
  already_there: "你已在此地",
  site_unexplorable: "此地不可探索",
  low_qi: "灵气不足",
  skill_na: "该技能无法施放",
  unknown_skill: "无此技能",
  game_over: "身死道消，本世已终",
  no_checkpoint: "无可回溯节点",
  unknown_run: "该存档不存在",
  bad_request: "请求参数有误",
  battle_ended: "战斗已结束",
};

const SITES_TRAVEL = [
  "坊市", "灵脉山", "幽谷秘境", "古战场遗迹", "上古洞府",
];
const SITES_EXPLORE = SITES_TRAVEL.slice(1);
const SLOT_KINDS = {
  main: "main", battle: "battle1", shenfa: "shenfa",
};
const FAM_MAX = 100;

// ---------- 会话状态 ----------
let cur = { runId: null, state: null };
let busy = false;
let showMarket = false, showBook = false;
let lastMarket = null, lastDetail = null;

// ---------- 小工具 ----------
function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
function pct(a, b) {
  if (!b) return 0;
  return Math.max(0, Math.min(100, (a / b) * 100));
}
function fmt1(x) { return Math.round(x * 10) / 10; }

async function api(path, method, body) {
  const opt = { method: method || "GET", headers: {} };
  if (body !== undefined) {
    opt.headers["Content-Type"] = "application/json";
    opt.body = JSON.stringify(body);
  }
  const resp = await fetch(path, opt);
  let data = null;
  try { data = await resp.json(); } catch (e) { data = null; }
  if (!resp.ok && data === null) {
    toast(`HTTP ${resp.status}`, "");
    return null;
  }
  return data;
}

function toast(msg, isOk) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast" + (isOk ? " ok" : "");
  clearTimeout(t._h);
  t._h = setTimeout(() => { t.className = "toast hidden"; }, 2600);
}

function logText(text, cls) {
  if (!text) return;
  const box = $("log");
  if (box.querySelector(".hint")) box.innerHTML = "";
  const p = document.createElement("p");
  p.className = "log-line" + (cls ? " " + cls : "");
  p.textContent = text;
  box.appendChild(p);
  // 日志过长裁剪（保留最近 600 条）
  while (box.childElementCount > 600) box.removeChild(box.firstChild);
  box.scrollTop = box.scrollHeight;
}

// ---------- 会话级操作 ----------
function applyRun(runId, state) {
  cur.runId = runId;
  cur.state = state;
  try { localStorage.setItem("xiuxian.lastRun", runId); } catch (e) {}
  $("run-badge").textContent = "本世 " + runId;
  $("run-badge").classList.remove("hidden");
  refreshRuns();
  renderAll();
}

async function newRun() {
  if (busy) return;
  busy = true;
  try {
    const resp = await api("/api/new", "POST", {});
    if (!resp || resp.ok === false) { toast((resp && REASON_TEXT[resp.reason]) || "开局失败", ""); return; }
    const st = resp.state;
    logText(`━━━ 新一世 · 种子 ${resp.run_id} ━━━（${st.name} · ${st.spirit_root}）`, "meta");
    logText(st.name + " 生于凡尘，得入仙途。", "meta");
    showMarket = showBook = false;
    lastMarket = lastDetail = null;
    applyRun(resp.run_id, st);
  } finally { busy = false; }
}

async function loadRun(runId) {
  if (!runId) return;
  if (busy) return;
  busy = true;
  try {
    const resp = await api("/api/load", "POST", { run_id: String(runId) });
    if (!resp || resp.ok === false) {
      toast((resp && REASON_TEXT[resp.reason]) || "读档失败", "");
      return;
    }
    logText(`━━━ 续玩 · 种子 ${resp.run_id} ━━━`, "meta");
    showMarket = showBook = false;
    lastMarket = lastDetail = null;
    applyRun(resp.run_id, resp.state);
  } finally { busy = false; }
}

async function refreshRuns() {
  try {
    const resp = await api("/api/runs");
    const sel = $("sel-load");
    const curVal = cur.runId || "";
    sel.innerHTML = '<option value="">— 读档 —</option>';
    (resp && resp.runs || []).forEach((m) => {
      const opt = document.createElement("option");
      opt.value = m.run_id;
      opt.textContent = `${m.run_id} · ${m.realm_name || "?"} · ${m.alive ? "存活" : "已陨"} · 年${Math.floor(m.age_years || 0)}`;
      sel.appendChild(opt);
    });
    if (curVal) sel.value = curVal;
    return resp ? resp.runs || [] : [];
  } catch (e) { return []; }
}

async function undoRun() {
  if (!cur.runId) { toast("尚无本世可回溯", ""); return; }
  if (busy) return;
  busy = true;
  try {
    const resp = await api("/api/undo", "POST", { run_id: cur.runId });
    if (!resp) return;
    if (resp.ok) {
      logText("你回溯到了上一节点（杀戮尖塔式，只退一步）。", "meta");
      cur.state = resp.state;
      renderAll();
    } else {
      toast(REASON_TEXT[resp.reason] || resp.reason || "回溯失败", "");
      if (resp.state) { cur.state = resp.state; renderAll(); }
    }
  } finally { busy = false; }
}

// ---------- 通用一步（全部经 /api/step；成败只信 ok/reason） ----------
async function step(action, kwargs) {
  if (!cur.runId) { toast("请先「新建一世」或读档", ""); return null; }
  if (busy) return null;
  busy = true;
  try {
    const resp = await api("/api/step", "POST",
      { run_id: cur.runId, action: action, kwargs: kwargs || {} });
    if (!resp) return null;
    react(resp);
    return resp;
  } finally { busy = false; }
}

function react(resp) {
  // 1) 叙事进日志流（text 只进日志，绝不用它判成败）
  if (resp.text) {
    let cls = "";
    if (resp.ok === false) cls = "err";
    else if (resp.game_over) cls = "err";
    else if (resp.battle_over) cls = "win";
    logText(resp.text, cls);
  }
  (resp.lines || []).forEach((l) => logText(l, "meta"));
  // 2) 成败提示 = reason 映射
  if (resp.ok === false) {
    toast(REASON_TEXT[resp.reason] || resp.reason || "行动失败", "");
  } else if (resp.game_over) {
    toast("【道陨】本世已终，可「新建一世」或读档。", "");
  }
  if (resp.state) cur.state = resp.state;
  renderAll();
}

// ---------- 渲染：状态面板 / 动作可用性 / 战斗面板 / 数据面板 ----------
function renderAll() {
  const st = cur.state;
  const actions = $("actions-body");
  if (!st) {
    actions.classList.add("locked");
    $("battle-panel").classList.add("hidden");
    renderNoRun();
    return;
  }
  const inBattle = !!st.battle;
  const dead = st.alive === false;
  const atMarket = ((st.location && st.location.name) || "") === "坊市";
  actions.classList.toggle("locked", inBattle || dead);
  // 货单是"坊市现场"信息：离开坊市即收起面板，避免离开后仍能点「购」（引擎会拒）
  if (!atMarket) { showMarket = false; lastMarket = null; }
  $("market-panel").classList.toggle("hidden", !showMarket);
  const mBtn = $("btn-market");
  mBtn.disabled = !atMarket;
  mBtn.title = atMarket ? "查看坊市货单" : "须先「前往」坊市";
  renderStatus(st, dead);
  renderBattle(st);
  refreshCombo(st);
  if (showMarket) renderMarket();
  if (showBook) renderBook(st);
  $("sel-load").value = cur.runId || "";
}

function renderNoRun() {
  $("status-body").innerHTML =
    '<p class="hint">尚未开世 —— 点右上「新建一世」开始仙途；<br>已有存档可在「— 读档 —」中选择。</p>';
}

function renderStatus(st, dead) {
  const inv = (st.inventory || []).map((it) =>
    `<span class="pill-chip">${esc(it.name)}×${it.qty}` +
    ` <button class="btn mini" data-act="use-pill" data-name="${esc(it.name)}">服</button></span>`
  ).join(" ") || "（空）";

  const pool = st.pool || {};
  const main = pool.main || {};
  const mainTxt = main.name ? `【${esc(main.name)}】` + (main.bonus ? ` (×${main.bonus.toFixed ? main.bonus.toFixed(2) : main.bonus})` : "") : "（空）";
  const battleSlots = (pool.battle || []).map((b, i) =>
    `${i + 1}【${b.name ? esc(b.name) : "空"}】`).join("　");
  const shenfa = (pool.shenfa && pool.shenfa.name) ? `【${esc(pool.shenfa.name)}】` : "（空）";

  const ownedRows = (st.owned || []).map((o) => {
    const base = `${esc(o.name)}（${esc(o.tier_label || "")}·${esc(o.slot_label || "")}类）`;
    if (!o.readable) return `・${base} <span class="dim">未看懂</span>`;
    return `・${base} 熟悉 ${o.familiarity}/${FAM_MAX} · ${esc(o.familiarity_state || "")} · ${o.slot ? "在" + esc(o.slot) : "未入池"}`;
  }).join("<br>") || "（空）";

  const locName = (st.location && st.location.name) || "";
  $("status-body").innerHTML = `
    <div class="kv"><span>${esc(st.name)} · <b>${esc(st.realm_name)}</b>（第${st.realm_idx}档）</span></div>
    <div class="bar" title="修为 ${fmt1(st.exp)} / ${st.exp_cap}">
      <i style="width:${pct(st.exp, st.exp_cap)}%"></i></div>
    <div class="kv"><span>修为</span><span>${fmt1(st.exp)} / ${st.exp_cap}</span></div>
    <div class="kv"><span>闭关效率 ×${st.cultivation_mult ? st.cultivation_mult.toFixed(2) : "-"}</span>
      <span>资质 ${esc(st.spirit_root)} ×${st.root_mult.toFixed ? st.root_mult.toFixed(2) : st.root_mult}</span></div>
    <div class="kv"><span>寿元</span><span>${fmt1(st.age_years)} / ${fmt1(st.lifespan_years)} 岁（余 ${fmt1(st.lifespan_left)}）</span></div>
    <div class="kv"><span>心魔</span><span>${st.heart_demon}/100</span></div>
    <div class="bar hd"><i style="width:${pct(st.heart_demon, 100)}%"></i></div>
    <div class="kv"><span>灵石 ${st.spirit_stones} ｜ 地点 ${esc(locName)}</span></div>
    <div class="kv dim"><span>世数 ${st.turn} 步 ｜ 种子 ${st.seed} ｜ 日 ${st.day}</span></div>
    ${dead ? `<p class="err-text">☠ 道陨：${esc(st.alive === false ? "本世已终" : "")}</p>` : ""}
    <div class="sect"><h4>背包</h4>${inv}</div>
    <div class="sect"><h4>运转池（池外功法不生效）</h4>
      主修位：${mainTxt}<br>战斗槽：${battleSlots || "（空）"}<br>身法槽：${shenfa}</div>
    <div class="sect"><h4>领悟池（已拥有 ${(st.owned || []).length} 本）</h4>${ownedRows}</div>`;
}

function renderBattle(st) {
  const panel = $("battle-panel");
  const b = st.battle;
  if (!b) { panel.classList.add("hidden"); panel.innerHTML = ""; return; }
  panel.classList.remove("hidden");
  const skills = (b.skills || []).map((sk) =>
    `<button class="btn mini" data-act="battle-skill" data-id="${sk.id}" title="${esc(sk.label || "")}">` +
    `${esc(sk.name)}（${esc(sk.element)}·${esc(sk.kind)}·耗${sk.qi_cost}）</button>`).join("");
  panel.innerHTML = `
    <h3>⚔ 战斗 · 第 ${b.turn} 回合</h3>
    <div class="hprow"><span class="who">${esc(b.enemy_name)}</span>
      <div class="bar"><i style="width:${pct(b.enemy_hp, b.enemy_hp_max)}%"></i></div>
      <b>${b.enemy_hp}/${b.enemy_hp_max}</b></div>
    <div class="hprow"><span class="who">${esc(st.name)}</span>
      <div class="bar"><i style="width:${pct(b.p_hp, b.p_hp_max)}%"></i></div>
      <b>${b.p_hp}/${b.p_hp_max}</b></div>
    <div class="hprow"><span class="who">灵气</span>
      <div class="bar"><i style="width:${pct(b.p_qi, b.p_qi_max)}%"></i></div>
      <b>${b.p_qi}/${b.p_qi_max}</b></div>
    <div class="skills">${skills || ""}</div>
    <div class="b-cmd">
      <button class="btn mini" data-act="battle-cmd" data-cmd="attack">平砍</button>
      <button class="btn mini" data-act="battle-cmd" data-cmd="defend">防御</button>
      <button class="btn mini" data-act="battle-cmd" data-cmd="flee">遁走</button>
      <button class="btn mini" data-act="battle-cmd" data-cmd="gather">聚气</button>
    </div>`;
}

function refreshCombo(st) {
  // 地点下拉
  const siteSel = $("sel-site");
  const curLoc = (st.location && st.location.name) || "";
  siteSel.innerHTML = SITES_TRAVEL.map((n) =>
    `<option value="${n}">${n}${n === curLoc ? "（当前）" : ""}</option>`).join("");
  // 参悟功法下拉（已看懂且未大成）
  const selG = $("sel-gongfa");
  const opts = (st.owned || []).filter((o) => o.readable && o.familiarity < FAM_MAX);
  selG.innerHTML = opts.map((o) =>
    `<option value="${esc(o.name)}">${esc(o.name)}（${o.familiarity}/${FAM_MAX}）</option>`).join("")
    || '<option value="">（无可参悟）</option>';
}

// ---------- 数据面板（货单 / 书库） ----------
async function fetchMarket() {
  const resp = await step("market");
  if (resp) { showMarket = true; lastMarket = resp.data; renderMarket(); }
}

function renderMarket() {
  const wrap = $("market-panel");
  const d = lastMarket || {};
  const pills = (d.pills || []).map((p) =>
    `<tr><td>${esc(p.name)}</td><td>${p.kind === "breakthrough" ? "突破丹" : "辅助丹"}</td>` +
    `<td>${p.price}</td><td><button class="btn mini" data-act="buy" data-name="${esc(p.name)}">购</button></td></tr>`).join("");
  const gfs = (d.gongfa || []).map((g) =>
    `<tr><td>${esc(g.name)}</td><td>${esc(g.element || "-")}系·${esc(g.tier_label || "")}·${esc(g.slot_label || "")}类</td>` +
    `<td>${g.price}</td><td>${g.readable
      ? (g.cultivate_bonus ? `主修加成×${(1 + g.cultivate_bonus).toFixed(2)}` : "") + (g.skill_count ? `·${g.skill_count}技` : "")
      : '<span class="dim">境界未至</span>'}</td>` +
    `<td><button class="btn mini" data-act="buy" data-name="${esc(g.name)}">购</button></td></tr>`).join("");
  wrap.innerHTML = `
    <h3>坊市货单 <button class="btn mini" data-act="close-panel" data-p="market">收起</button></h3>
    <table><tr><th>丹药</th><th>类别</th><th>灵石</th><th></th></tr>${pills}</table>
    <table style="margin-top:6px"><tr><th>功法</th><th>简介</th><th>灵石</th><th>加成</th><th></th></tr>${gfs}</table>`;
}

async function fetchBook() {
  const resp = await step("gongfa_detail", { gongfa: "" });
  if (resp) { showBook = true; renderBook(cur.state); }
}

function renderBook(st) {
  const wrap = $("book-panel");
  wrap.classList.remove("hidden");
  const lib = (lastDetail && lastDetail.library) || (st.owned || []);
  const rows = (lib || []).map((o) => {
    const famState = o.familiarity_state ? `熟悉 ${o.familiarity}/${FAM_MAX}（${esc(o.familiarity_state)}）` : (o.readable ? "" : "未看懂");
    return `<div class="book-item" data-act="detail" data-name="${esc(o.name)}">` +
      `【${esc(o.name)}】${esc(o.tier_label || "")}·${esc(o.slot_label || "")}类` +
      (famState ? ` ｜ ${famState}` : "") + (o.slot ? ` ｜ 在${esc(o.slot)}` : "") +
      ` ｜ <button class="btn mini" data-act="detail" data-name="${esc(o.name)}">详情</button></div>`;
  }).join("") || "（领悟池为空）";
  wrap.innerHTML = `<h3>书库 · 领悟池 <button class="btn mini" data-act="close-panel" data-p="book">收起</button></h3>${rows}${renderDetail(st)}`;
}

function renderDetail(st) {
  const d = lastDetail;
  if (!d || !d.id) return "";
  const slotOpts = d.slot_type === "battle"
    ? ["battle1", "battle2", "battle3", "battle4"].map((s, i) => `<option value="${s}">战斗槽${i + 1}</option>`).join("")
    : d.slot_type === "shenfa"
      ? '<option value="shenfa">身法槽</option>'
      : '<option value="main">主修位</option>';
  const skills = (d.skills || []).map((sk) =>
    `<div class="skill-line ${sk.lit ? "lit" : "dim"}">・${esc(sk.name)}（${esc(sk.element)}·${esc(sk.kind)}` +
    (sk.utility_effect ? `·${esc(sk.utility_effect)}` : "") + `·耗${sk.qi_cost}）` +
    (sk.lit ? "·已参悟" : `·需熟悉度 ${sk.unlock_fam}`) + `</div>`).join("");
  const canEquip = d.readable && d.owned && (d.familiarity || 0) >= 10 && !d.slot;
  const canForget = d.slot;
  return `
    <div style="margin-top:8px;border-top:1px dashed var(--line);padding-top:6px">
      <h3>━━ ${esc(d.name)} ━━（${esc(d.tier_label || "")}·${esc(d.slot_label || "")}类）</h3>
      ${d.readable
        ? `<p class="dim">五行 ${esc(d.element || "-")} ｜ 熟悉 ${d.familiarity}/${FAM_MAX}（${esc(d.familiarity_state || "")}）` +
          (d.slot ? ` ｜ 在${esc(d.slot)}` : "") + `</p>` +
          (d.cultivate_bonus ? `<p>主修修炼加成 ×${(1 + d.cultivate_bonus).toFixed(2)}</p>` : "") +
          (d.permanent_bonus ? `<p>道基被动：习得后修炼效率永久 +${Math.round(d.permanent_bonus * 100)}%</p>` : "") +
          `<div class="dim">${esc(d.desc || "")}</div><div>${skills}</div>`
        : `<p class="unreadable">境界未至，书文晦涩难明（只识其名与来历）。</p>`}
      ${canEquip
        ? `<p><select id="sel-detail-slot" class="sel">${slotOpts}</select>
            <button class="btn mini primary" data-act="learn" data-name="${esc(d.name)}">装备</button>
            <button class="btn mini" data-act="cw" data-name="${esc(d.name)}">参悟入门</button></p>`
        : ""}
      ${canForget
        ? `<button class="btn mini danger" data-act="forget" data-name="${esc(d.name)}" data-slot="${esc(d.slot)}">卸下（${esc(d.slot)}）</button>`
        : ""}
    </div>`;
}

// ---------- 事件绑定 ----------
function slotFromKind(kind) { return SLOT_KINDS[kind] || "main"; }

async function onAction(el) {
  const act = el.getAttribute("data-act");
  const name = el.getAttribute("data-name") || "";
  switch (act) {
    case "buy":
      await step("buy", { item: name, qty: 1 });
      break;
    case "use-pill":
      await step("use_pill", { item: name });
      break;
    case "cw": {
      const daysSel = $("inp-cw-days");
      await step("comprehend", { gongfa: name, days: parseInt(daysSel.value, 10) || 5 });
      await step("gongfa_detail", { gongfa: name });
      break;
    }
    case "detail": {
      const resp = await step("gongfa_detail", { gongfa: name });
      if (resp) lastDetail = resp.data;
      break;
    }
    case "learn": {
      const slot = ($("sel-detail-slot") && $("sel-detail-slot").value) || "main";
      await step("learn", { gongfa: name, slot: slot });
      const resp = await step("gongfa_detail", { gongfa: name });
      if (resp) lastDetail = resp.data;
      break;
    }
    case "forget": {
      const slot = el.getAttribute("data-slot") || "main";
      await step("forget", { slot: slot });
      const resp = await step("gongfa_detail", { gongfa: name });
      if (resp) lastDetail = resp.data;
      break;
    }
    case "close-panel": {
      const p = el.getAttribute("data-p");
      if (p === "market") showMarket = false;
      if (p === "book") showBook = false;
      renderAll();
      break;
    }
    case "battle-skill":
      await step("battle_action", { cmd: "skill", skill_id: parseInt(el.getAttribute("data-id"), 10) });
      break;
    case "battle-cmd":
      await step("battle_action", { cmd: el.getAttribute("data-cmd") });
      break;
    default:
      break;
  }
}

function bind() {
  $("btn-new").onclick = newRun;
  $("sel-load").onchange = (e) => loadRun(e.target.value);
  $("btn-undo").onclick = undoRun;

  $("btn-cultivate").onclick = () => step("cultivate", {
    days: parseInt($("inp-cultivate-days").value, 10) || 30,
    use_pill: $("chk-pill").checked,
  });
  $("btn-cw").onclick = () => {
    const name = $("sel-gongfa").value;
    if (!name) { toast("无可参悟的功法（先在书库看是否看懂）", ""); return; }
    step("comprehend", { gongfa: name, days: parseInt($("inp-cw-days").value, 10) || 5 });
  };
  $("btn-breakthrough").onclick = () => step("breakthrough");
  $("btn-age-pass").onclick = () => step("age_pass", { days: parseInt($("inp-age-days").value, 10) || 30 });
  $("btn-travel").onclick = () => step("travel", { site: $("sel-site").value });
  $("btn-explore").onclick = () => step("explore", { site: $("sel-site").value });
  $("btn-market").onclick = fetchMarket;
  $("btn-book").onclick = fetchBook;
  $("btn-chronicle").onclick = () => step("chronicle");

  document.addEventListener("click", (e) => {
    const el = e.target.closest("[data-act]");
    if (el) onAction(el);
  });
}

// ---------- 启动 ----------
(async function boot() {
  bind();
  const runs = await refreshRuns();
  // 首次打开无存档 → 停留在「新建一世」提示页
  let lastRun = null;
  try { lastRun = localStorage.getItem("xiuxian.lastRun"); } catch (e) {}
  if (runs.length === 0) {
    logText("尚无任何存档。点右上「新建一世」开始你的仙途。", "meta");
    renderNoRun();
    return;
  }
  if (lastRun && runs.some((m) => String(m.run_id) === String(lastRun))) {
    await loadRun(lastRun);   // 自动续玩最近一世
  } else {
    logText(`共找到 ${runs.length} 个存档 —— 在右上角选择读档，或新建一世。`, "meta");
    renderNoRun();
  }
})();
