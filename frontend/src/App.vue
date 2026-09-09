<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";

import ConfirmDialog from "@/components/ConfirmDialog.vue";
import Toasts from "@/components/Toasts.vue";
import BattleScreen from "@/views/BattleScreen.vue";
import ChronicleScreen from "@/views/ChronicleScreen.vue";
import CultivationScreen from "@/views/CultivationScreen.vue";
import LibraryScreen from "@/views/LibraryScreen.vue";
import MapScreen from "@/views/MapScreen.vue";
import MarketScreen from "@/views/MarketScreen.vue";
import NarrativeLog from "@/views/NarrativeLog.vue";
import StatusPanel from "@/views/StatusPanel.vue";
import { useSessionStore } from "@/stores/session";
import { useUiStore } from "@/stores/ui";

const s = useSessionStore();
const ui = useUiStore();

const selLoad = ref("");
const center = ref<HTMLElement | null>(null);
const dragging = ref(false);

const runLabel = computed(() => (s.runId ? `本世 ${s.runId}` : "尚未开世"));

function onSelectRun(e: Event) {
  const v = (e.target as HTMLSelectElement).value;
  if (v) void s.loadRun(v);
  selLoad.value = "";
}

/** 拖拽调整「主内容 / 叙事日志」分界 */
function startDrag(e: PointerEvent) {
  e.preventDefault();
  dragging.value = true;
  const move = (ev: PointerEvent) => {
    const box = center.value;
    if (!box) return;
    const rect = box.getBoundingClientRect();
    // 日志区高度 = 容器底部到指针的距离
    ui.setLogHeight(rect.bottom - ev.clientY);
  };
  const up = () => {
    dragging.value = false;
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
}

function onKey(e: KeyboardEvent) {
  const t = e.target;
  if (t instanceof HTMLInputElement || t instanceof HTMLSelectElement) return;
  if (e.key === "Escape") {
    if (ui.battleOpen) return; // 战斗不靠 Esc 关闭（有「回地图」按钮）
    if (ui.screen !== "map") ui.close();
    return;
  }
  if (e.key === "m" || e.key === "M") ui.open("map");
  if (e.key === "c" || e.key === "C") ui.open("cultivation");
}

onMounted(() => {
  ui.restoreLogHeight();
  void s.bootstrap();
  window.addEventListener("keydown", onKey);
});
onUnmounted(() => window.removeEventListener("keydown", onKey));
</script>

<template>
  <header class="topbar">
    <h1>仙途 · 文字修仙</h1>
    <div class="top-right">
      <span v-if="s.busy" class="badge busy">处理中…</span>
      <span class="badge">{{ runLabel }}</span>
      <button
        class="btn"
        :disabled="s.busy || !s.runId"
        title="回溯到上一节点（只退一步）"
        @click="s.undo()"
      >
        回溯
      </button>
      <button class="btn primary" :disabled="s.busy" @click="s.newRun()">新建一世</button>
      <select class="sel" :disabled="s.busy" :value="selLoad" @change="onSelectRun">
        <option value="">— 读档 —</option>
        <option v-for="m in s.runs" :key="m.run_id" :value="m.run_id">
          {{ m.run_id }} · {{ m.realm_name || "?" }} · {{ m.alive ? "存活" : "已陨" }} · 年{{ Math.floor(m.age_years || 0) }}
        </option>
      </select>
    </div>
  </header>

  <main class="layout">
    <!-- 左：状态（常驻） -->
    <StatusPanel />

    <!-- 右：中上=主内容（地图/修炼/战斗/坊市/书库/编年史），中下=叙事日志（可拖拽高度） -->
    <section ref="center" class="center" :class="{ dragging }">
      <div class="main-slot card">
        <BattleScreen v-if="ui.battleOpen" />
        <CultivationScreen v-else-if="ui.screen === 'cultivation'" />
        <MarketScreen v-else-if="ui.screen === 'market'" />
        <LibraryScreen v-else-if="ui.screen === 'library'" />
        <ChronicleScreen v-else-if="ui.screen === 'chronicle'" />
        <MapScreen v-else />
      </div>

      <div class="splitter" title="拖拽调整叙事日志高度（双击复位）" @pointerdown="startDrag" @dblclick="ui.setLogHeight(240)">
        <span></span>
      </div>

      <div class="log-slot card" :style="{ height: (ui.logCollapsed ? 38 : ui.logHeight) + 'px' }">
        <NarrativeLog v-model:collapsed="ui.logCollapsed" />
      </div>
    </section>
  </main>

  <Toasts />
  <ConfirmDialog />
</template>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 16px;
  background: var(--panel2);
  border-bottom: 1px solid var(--line);
  flex: 0 0 auto;
  flex-wrap: wrap;
}
.topbar h1 {
  font-size: 17px;
  color: var(--gold);
  letter-spacing: 2px;
}
.top-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.badge {
  background: #2c3c28;
  color: var(--green);
  border: 1px solid var(--green);
  border-radius: 10px;
  padding: 2px 10px;
  font-size: 12px;
}
.badge.busy {
  background: #2a3350;
  color: var(--blue);
  border-color: var(--blue);
}

/* 左(状态) / 右(主内容 + 日志) */
.layout {
  flex: 1 1 auto;
  min-height: 0;
  display: grid;
  grid-template-columns: 330px minmax(0, 1fr);
  gap: var(--gap);
  padding: var(--gap);
}
.center {
  display: flex;
  flex-direction: column;
  min-height: 0;
  min-width: 0;
}
.center.dragging { cursor: row-resize; user-select: none; }
.main-slot {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.log-slot {
  flex: 0 0 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* 拖拽分隔条 */
.splitter {
  flex: 0 0 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: row-resize;
  touch-action: none;
}
.splitter span {
  display: block;
  width: 46px;
  height: 3px;
  border-radius: 2px;
  background: var(--line);
  transition: background .12s, width .12s;
}
.splitter:hover span { background: var(--gold); width: 78px; }

@media (max-width: 1100px) {
  .layout { grid-template-columns: 280px minmax(0, 1fr); }
}
@media (max-width: 900px) {
  .layout { grid-template-columns: 1fr; }
}
</style>
