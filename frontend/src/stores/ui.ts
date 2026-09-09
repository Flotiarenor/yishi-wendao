import { defineStore } from "pinia";

export type ToastKind = "err" | "ok" | "info";

export interface Toast {
  id: number;
  text: string;
  kind: ToastKind;
}

/** 主内容区（中上栏）视图 —— 默认地图；战斗临时接管，不在此枚举内 */
export type Screen = "map" | "cultivation" | "market" | "library" | "chronicle";

const LS_LOG_H = "xiuxian.ui.logHeight";

let toastSeq = 0;

export const useUiStore = defineStore("ui", {
  state: () => ({
    /** 主内容区当前视图（嵌入中上栏；战斗不在此列——战斗是临时接管主内容区） */
    screen: "map" as Screen,
    /** 战斗是否正在接管主内容区 */
    battleOpen: false,
    toasts: [] as Toast[],
    /** 加载中（请求进行中，UI 全局禁用） */
    loading: false,
    /** 二次确认弹窗 */
    confirm: null as { text: string; resolve: (v: boolean) => void } | null,
    /** 叙事日志区高度（px，用户可拖拽调整，持久化） */
    logHeight: 240,
    logCollapsed: false,
  }),

  actions: {
    open(screen: Screen) {
      this.screen = screen;
    },
    /** 回到主页面（地图） */
    close() {
      this.screen = "map";
    },
    toggle(screen: Screen) {
      this.screen = this.screen === screen ? "map" : screen;
    },
    /** 战斗接管主内容区 */
    openBattle() {
      this.battleOpen = true;
    },
    /** 交还主内容区（回到地图） */
    closeBattle() {
      this.battleOpen = false;
    },

    /** 拖拽调整日志区高度（夹在 80~70vh 之间） */
    setLogHeight(px: number) {
      const max = Math.max(160, Math.round(window.innerHeight * 0.7));
      this.logHeight = Math.max(80, Math.min(max, Math.round(px)));
      try {
        window.localStorage.setItem(LS_LOG_H, String(this.logHeight));
      } catch {
        /* 隐私模式等：忽略 */
      }
    },
    restoreLogHeight() {
      try {
        const v = Number(window.localStorage.getItem(LS_LOG_H));
        if (Number.isFinite(v) && v > 0) this.logHeight = v;
      } catch {
        /* 忽略 */
      }
    },

    notify(text: string, kind: ToastKind = "err") {
      const id = ++toastSeq;
      this.toasts.push({ id, text, kind });
      const ttl = kind === "err" ? 6000 : 3000;
      window.setTimeout(() => this.dismiss(id), ttl);
      if (this.toasts.length > 6) this.toasts.shift();
    },
    dismiss(id: number) {
      const i = this.toasts.findIndex((t) => t.id === id);
      if (i >= 0) this.toasts.splice(i, 1);
    },

    /** 破坏性操作二次确认（新建一世会覆盖同 seed 旧档） */
    ask(text: string): Promise<boolean> {
      return new Promise((resolve) => {
        this.confirm = { text, resolve };
      });
    },
    answer(v: boolean) {
      const c = this.confirm;
      this.confirm = null;
      if (c) c.resolve(v);
    },
  },
});
