<script setup lang="ts">
import { computed, onMounted } from "vue";

import EmbeddedPanel from "@/components/EmbeddedPanel.vue";
import { useSessionStore } from "@/stores/session";

const s = useSessionStore();

const entries = computed(() => [...s.chronicle].sort((a, b) => a.age - b.age));

onMounted(() => {
  if (!s.chronicle.length) void s.chronicleRun();
});
</script>

<template>
  <EmbeddedPanel :title="`📜 本世编年史（${entries.length} 条）`">
    <template #head>
      <button class="btn mini" :disabled="s.busy" @click="s.chronicleRun()">刷新</button>
    </template>

    <p v-if="s.busy && !entries.length" class="hint">（载入中……）</p>
    <p v-else-if="!entries.length" class="hint">（尚无大事）</p>

    <ol v-else class="tl">
      <li v-for="(e, i) in entries" :key="i">
        <span class="age mono">{{ e.age.toFixed(1) }} 岁</span>
        <span class="text">{{ e.text }}</span>
      </li>
    </ol>
  </EmbeddedPanel>
</template>

<style scoped>
.tl { list-style: none; margin: 0; padding: 0; }
.tl li {
  display: flex;
  gap: 12px;
  padding: 6px 4px;
  border-left: 2px solid var(--line);
  margin-left: 6px;
  position: relative;
}
.tl li::before {
  content: "";
  position: absolute;
  left: -6px;
  top: 12px;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--gold);
}
.age { color: var(--gold); width: 78px; flex: 0 0 auto; font-size: 12.5px; }
.text { font-size: 12.5px; line-height: 1.5; }
</style>
