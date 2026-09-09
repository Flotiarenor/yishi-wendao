<script setup lang="ts">
/**
 * 主内容区面板外壳（嵌入中上栏，不是覆盖层）。
 * 标题栏 + 可滚动内容 + 可选页脚；关闭按钮回到主页面（地图）。
 */
import { useUiStore } from "@/stores/ui";

withDefaults(
  defineProps<{
    title: string;
    /** 关闭按钮文案（默认回地图） */
    closeText?: string;
    /** 是否显示关闭按钮 */
    closable?: boolean;
  }>(),
  { closeText: "回地图", closable: true },
);

const ui = useUiStore();
</script>

<template>
  <section class="main-panel">
    <header class="mp-head">
      <h2>{{ title }}</h2>
      <div class="mp-ops">
        <slot name="head" />
        <button v-if="closable" class="btn mini ghost" @click="ui.close()">{{ closeText }}</button>
      </div>
    </header>
    <div class="mp-body">
      <slot />
    </div>
    <footer v-if="$slots.footer" class="mp-foot">
      <slot name="footer" />
    </footer>
  </section>
</template>

<style scoped>
.main-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}
.mp-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding-bottom: 6px;
  border-bottom: 1px dashed var(--line);
  flex: 0 0 auto;
  flex-wrap: wrap;
}
.mp-head h2 { font-size: 13px; color: var(--gold); }
.mp-ops { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.mp-body { flex: 1 1 auto; overflow: auto; min-height: 0; padding-top: 8px; }
.mp-foot {
  flex: 0 0 auto;
  padding-top: 6px;
  border-top: 1px dashed var(--line);
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}
</style>
