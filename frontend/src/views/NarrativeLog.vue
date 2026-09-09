<script setup lang="ts">
import { nextTick, ref, watch } from "vue";

import { useSessionStore } from "@/stores/session";

const props = withDefaults(defineProps<{ collapsed?: boolean }>(), { collapsed: false });
const emit = defineEmits<{ (e: "update:collapsed", v: boolean): void }>();

const s = useSessionStore();
const box = ref<HTMLElement | null>(null);
const autoScroll = ref(true);

function onScroll() {
  const el = box.value;
  if (!el) return;
  autoScroll.value = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
}

watch(
  () => [s.log.length, props.collapsed],
  async () => {
    if (props.collapsed || !autoScroll.value) return;
    await nextTick();
    const el = box.value;
    if (el) el.scrollTop = el.scrollHeight;
  },
);

function hhmm(t: number) {
  const d = new Date(t);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}
</script>

<template>
  <div class="log-wrap">
    <header class="log-head">
      <h2>叙事日志<span class="dim" style="font-size: 12px">（{{ s.log.length }} 行）</span></h2>
      <div class="ops">
        <button
          class="btn mini ghost"
          :class="{ active: autoScroll }"
          :title="autoScroll ? '已跟随最新' : '已停止跟随'"
          @click="autoScroll = !autoScroll"
        >
          {{ autoScroll ? "跟随中" : "已暂停" }}
        </button>
        <button class="btn mini ghost" :disabled="!s.log.length" @click="s.clearLog()">清空</button>
        <button class="btn mini ghost" @click="emit('update:collapsed', !collapsed)">
          {{ collapsed ? "展开 ▴" : "收起 ▾" }}
        </button>
      </div>
    </header>

    <div v-show="!collapsed" ref="box" class="log" @scroll="onScroll">
      <p v-if="!s.log.length" class="hint">（等待开局……）</p>
      <p v-for="(l, i) in s.log" :key="i" class="log-line" :class="l.cls">
        <span class="ts mono">{{ hhmm(l.t) }}</span>{{ l.text }}
      </p>
    </div>
  </div>
</template>

<style scoped>
.log-wrap { display: flex; flex-direction: column; height: 100%; min-height: 0; }
.log-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex: 0 0 auto;
  border-bottom: 1px dashed var(--line);
  padding-bottom: 4px;
}
.log-head h2 { font-size: 13px; color: var(--gold); display: flex; gap: 6px; align-items: baseline; }
.ops { display: flex; gap: 5px; }
.log { flex: 1 1 auto; overflow-y: auto; min-height: 0; padding-top: 6px; }
.log-line {
  margin: 0 0 4px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 13px;
}
.log-line.err { color: #ffb4ac; }
.log-line.win { color: #bfe8c9; }
.log-line.meta { color: var(--ink-dim); font-size: 12.5px; }
.ts { color: #5c6c8c; font-size: 11px; margin-right: 6px; }
</style>
