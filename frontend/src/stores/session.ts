import { defineStore } from "pinia";

import { api, actions, reasonText, type ApiResponse } from "@/api/client";
import type {
  ChronicleEntry,
  GongfaDetail,
  MarketData,
  RunMeta,
  StateData,
  StepResult,
} from "@/types/contract";
import { useUiStore } from "@/stores/ui";

export type LogClass = "meta" | "err" | "win" | "";

export interface LogEntry {
  t: number;
  text: string;
  cls: LogClass;
}

const LOG_MAX = 800;
const LS_LAST_RUN = "xiuxian.lastRun";
const LS_LOG_PREFIX = "xiuxian.log.";
const LS_CW_GONGFA = "xiuxian.cwGongfa";

function lsGet(k: string): string | null {
  try {
    return window.localStorage.getItem(k);
  } catch {
    return null;
  }
}
function lsSet(k: string, v: string) {
  try {
    window.localStorage.setItem(k, v);
  } catch {
    /* 隐私模式等：静默降级 */
  }
}

export const useSessionStore = defineStore("session", {
  state: () => ({
    runId: null as string | null,
    state: null as StateData | null,
    runs: [] as RunMeta[],
    log: [] as LogEntry[],
    /** 请求进行中（全局 UI 禁用，防连点重复发请求） */
    busy: false,
    market: null as MarketData | null,
    detail: null as GongfaDetail | null,
    chronicle: [] as ChronicleEntry[],
    /** 最近一次动作的 Result（供界面做局部反馈） */
    last: null as StepResult | null,
    /** 参悟目标（记住用户选择，跨刷新/跨视图保持） */
    cwGongfa: (() => {
      try {
        return window.localStorage.getItem(LS_CW_GONGFA) || "";
      } catch {
        return "";
      }
    })(),
  }),

  getters: {
    battle: (s) => s.state?.battle ?? null,
    dead: (s) => !!s.state && s.state.alive === false,
    inBattle(): boolean {
      return !!this.battle;
    },
    /** 非战斗、非死亡时才能进行日常动作 */
    canAct(): boolean {
      return !!this.state && !this.battle && !this.dead && !this.busy;
    },
    atMarket: (s) => (s.state?.location?.name || "") === "坊市",
    stones: (s) => s.state?.spirit_stones ?? 0,
    /** 可参悟（已看懂且未大成）的功法 */
    comprehensible: (s) =>
      (s.state?.owned || []).filter((o) => o.readable && o.familiarity < 100),
  },

  actions: {
    // ---------- 日志 ----------
    logText(text: string, cls: LogClass = "") {
      if (!text) return;
      for (const line of String(text).split("\n")) {
        this.log.push({ t: Date.now(), text: line, cls });
      }
      if (this.log.length > LOG_MAX) this.log.splice(0, this.log.length - LOG_MAX);
      this.persistLog();
    },
    logLines(lines: string[] | undefined) {
      (lines || []).forEach((l) => this.logText(l, "meta"));
    },
    persistLog() {
      if (!this.runId) return;
      lsSet(LS_LOG_PREFIX + this.runId, JSON.stringify(this.log.slice(-LOG_MAX)));
    },
    restoreLog(runId: string) {
      const raw = lsGet(LS_LOG_PREFIX + runId);
      if (!raw) return;
      try {
        const arr = JSON.parse(raw) as LogEntry[];
        if (Array.isArray(arr)) this.log = arr;
      } catch {
        /* 损坏则忽略 */
      }
    },
    clearLog() {
      this.log = [];
    },

    // ---------- 会话 ----------
    async bootstrap() {
      const ui = useUiStore();
      const r = await api.runs();
      if (!r.ok) {
        ui.notify("读取存档列表失败：" + reasonText(r.reason));
        return;
      }
      this.runs = r.runs;
      if (r.runs.length === 0) {
        this.logText("尚无任何存档 —— 点右上「新建一世」开始你的仙途。", "meta");
        return;
      }
      const last = lsGet(LS_LAST_RUN);
      if (last && r.runs.some((m) => String(m.run_id) === String(last))) {
        const ok = await this.loadRun(last);
        if (!ok) {
          ui.notify("自动续玩失败，请在右上角手动读档。");
          this.logText(`共找到 ${r.runs.length} 个存档 —— 请手动读档或新建一世。`, "meta");
        }
      } else {
        this.logText(`共找到 ${r.runs.length} 个存档 —— 在右上角选择读档，或新建一世。`, "meta");
      }
    },

    async refreshRuns() {
      const r = await api.runs();
      if (r.ok) this.runs = r.runs;
    },

    async newRun(seed?: number, name?: string) {
      const ui = useUiStore();
      if (this.busy) return false;
      if (this.state) {
        const ok = await ui.ask(
          "新建一世会立刻覆盖同种子的旧存档，当前进度不会保留。确定要开新局吗？",
        );
        if (!ok) return false;
      }
      this.busy = true;
      try {
        const r = await api.newRun(seed, name);
        if (!r.ok) {
          ui.notify("开局失败：" + reasonText(r.reason));
          return false;
        }
        this.clearLog();
        this.market = null;
        this.detail = null;
        this.chronicle = [];
        this.runId = r.run_id;
        this.state = r.state;
        lsSet(LS_LAST_RUN, r.run_id);
        this.logText(`━━━ 新一世 · 种子 ${r.run_id} ━━━（${r.state.name} · ${r.state.spirit_root}）`, "meta");
        this.logText(`${r.state.name} 生于凡尘，得入仙途。`, "meta");
        await this.refreshRuns();
        ui.close();
        return true;
      } finally {
        this.busy = false;
      }
    },

    async loadRun(runId: string) {
      const ui = useUiStore();
      if (!runId || this.busy) return false;
      if (this.state && this.runId !== String(runId)) {
        const ok = await ui.ask("读档会丢弃当前进度，确定切换存档吗？");
        if (!ok) return false;
      }
      this.busy = true;
      try {
        const r = await api.load(String(runId));
        if (!r.ok) {
          ui.notify("读档失败：" + reasonText(r.reason));
          return false;
        }
        this.runId = r.run_id;
        this.state = r.state;
        this.market = null;
        this.detail = null;
        this.chronicle = [];
        lsSet(LS_LAST_RUN, r.run_id);
        this.log = [];
        this.restoreLog(r.run_id);
        this.logText(`━━━ 续玩 · 种子 ${r.run_id} ━━━`, "meta");
        await this.refreshRuns();
        ui.close();
        return true;
      } finally {
        this.busy = false;
      }
    },

    async undo() {
      const ui = useUiStore();
      if (!this.runId || this.busy) return;
      this.busy = true;
      try {
        const r = await api.undo(this.runId);
        if (r.ok) {
          if (r.state) this.state = r.state;
          this.logText("你回溯到了上一节点（只退一步）。", "meta");
          ui.notify("已回溯到上一节点", "ok");
        } else {
          ui.notify("回溯失败：" + reasonText(r.reason));
        }
      } finally {
        this.busy = false;
      }
    },

    // ---------- 通用一步 ----------
    /** 所有动作的唯一入口：成败只看 ok/reason，text/lines 只进日志 */
    async run(action: string, kwargs: Record<string, unknown> = {}) {
      const ui = useUiStore();
      if (!this.runId) {
        ui.notify("请先「新建一世」或读档");
        return null;
      }
      if (this.busy) return null;
      this.busy = true;
      ui.loading = true;
      try {
        const resp: ApiResponse<StepResult> = await api.step(this.runId, action, kwargs);
        if (!resp.ok) {
          // 服务层错误（unknown_run/bad_request/network_error…）
          ui.notify(reasonText(resp.reason));
          this.logText(`〔行动未执行〕${reasonText(resp.reason)}`, "err");
          return null;
        }
        this.react(resp);
        return resp;
      } finally {
        this.busy = false;
        ui.loading = false;
      }
    },

    /** 记住参悟目标（用户不必每次重选） */
    setCwGongfa(name: string) {
      this.cwGongfa = name;
      try {
        window.localStorage.setItem(LS_CW_GONGFA, name);
      } catch {
        /* 忽略 */
      }
    },

    react(resp: StepResult) {
      const ui = useUiStore();
      this.last = resp;
      // 1) 叙事进日志（text 只进日志，绝不用于判成败）
      if (resp.text) {
        const cls: LogClass = resp.ok === false || resp.game_over ? "err" : resp.battle_over ? "win" : "";
        this.logText(resp.text, cls);
      }
      this.logLines(resp.lines);
      // 2) 成败提示 = reason 映射
      if (resp.ok === false) {
        ui.notify(reasonText(resp.reason));
      } else if (resp.game_over) {
        ui.notify("【道陨】本世已终，可「新建一世」或读档。", "err");
      }
      // 3) 状态（引擎拒绝分支不带 state → 保持原状态，但仍需给出反馈）
      if (resp.state) this.state = resp.state;
      // 战斗：中置覆盖层（方便点击）；战斗结束后自动收起，主内容区保持不变，
      // 因此探索的叙事文字会留在下方日志里继续可见（P3.7 布局修正）。
      if (resp.battle_started) ui.openBattle();
      if (resp.battle_over) {
        this.logText(`【战斗结束】${resp.battle_over}`, resp.battle_over === "win" ? "win" : "meta");
        ui.closeBattle();
      }
      if (resp.game_over || resp.battle_over) void this.refreshRuns();
      // 4) 离开坊市 → 货单数据失效，主内容区回到默认视图
      if (!this.atMarket && this.market) {
        this.market = null;
        if (ui.screen === "market") ui.open("map");
      }
    },

    // ---------- 业务动作 ----------
    async cultivate(days: number, usePill: boolean) {
      const r = await this.run(...actions.cultivate(days, usePill));
      if (r?.ok) {
        const d = r.data as { days?: number; capped?: boolean; exp_gain?: number };
        if (d.capped && typeof d.days === "number") {
          useUiStore().notify(
            `闭关 ${d.days} 日即已圆满（请求天数已封顶），可考虑突破。`,
            "info",
          );
        }
      }
      return r;
    },
    comprehend(gongfa: string, days: number): Promise<StepResult | null> {
      return this.run(...actions.comprehend(gongfa, days));
    },
    breakthrough(): Promise<StepResult | null> {
      return this.run(...actions.breakthrough());
    },
    agePass(days: number): Promise<StepResult | null> {
      return this.run(...actions.agePass(days));
    },
    async chronicleRun(): Promise<StepResult | null> {
      const r = await this.run(...actions.chronicle());
      if (r && r.ok) {
        const d = r.data as { entries?: ChronicleEntry[] };
        this.chronicle = d.entries || [];
      }
      return r;
    },

    async travel(site: string) {
      const r = await this.run(...actions.travel(site));
      if (r?.ok) this.afterMove();
      return r;
    },
    async explore(site: string) {
      const r = await this.run(...actions.explore(site));
      if (r?.ok) this.afterMove();
      return r;
    },
    afterMove() {
      const ui = useUiStore();
      // 移动/探索后主内容区停在地图——叙事文字在下方日志里持续可见
      if (!this.atMarket) {
        this.market = null;
        if (ui.screen === "market") ui.open("map");
      } else if (ui.screen !== "market") {
        // 抵达坊市：自动把货单放到主内容区（边看叙事边买）
        void this.openMarket();
      }
    },

    async openMarket() {
      const ui = useUiStore();
      if (!this.atMarket) {
        ui.notify("须先「前往」坊市才能看货单");
        return;
      }
      const r = await this.run(...actions.market());
      if (r?.ok) {
        this.market = (r.data || {}) as unknown as MarketData;
        ui.open("market");
      }
    },
    buy(item: string, qty = 1): Promise<StepResult | null> {
      return this.run(...actions.buy(item, qty));
    },
    usePill(item: string): Promise<StepResult | null> {
      return this.run(...actions.usePill(item));
    },

    async openDetail(name: string): Promise<StepResult | null> {
      const ui = useUiStore();
      const r = await this.run(...actions.detail(name));
      if (r && r.ok) {
        this.detail = r.data as unknown as GongfaDetail;
        ui.open("library");
      }
      return r;
    },
    async learn(gongfa: string, slot: string): Promise<StepResult | null> {
      const r = await this.run(...actions.learn(gongfa, slot));
      if (r && r.ok) await this.openDetail(gongfa);
      return r;
    },
    async forget(slot: string, name: string): Promise<StepResult | null> {
      const r = await this.run(...actions.forget(slot));
      if (r && r.ok) await this.openDetail(name);
      return r;
    },

    // ---------- 战斗（R3：入队 → 窗口满/执行 → 结算） ----------
    battleSubmit(key: string): Promise<StepResult | null> {
      return this.run(...actions.battleSubmit(key));
    },
    battleUnqueue(index: number): Promise<StepResult | null> {
      return this.run(...actions.battleUnqueue(index));
    },
    battleClear(): Promise<StepResult | null> {
      return this.run(...actions.battleClear());
    },
    battleSkip(): Promise<StepResult | null> {
      return this.run(...actions.battleSkip());
    },
  },
});
