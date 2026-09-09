<script setup lang="ts">
/** 通用进度条：a/b → 百分比宽度（b 为 0 时按 0 处理） */
const props = withDefaults(
  defineProps<{
    value: number;
    max: number;
    kind?: "exp" | "hp" | "enemy" | "qi" | "hd";
    title?: string;
  }>(),
  { kind: "exp", title: "" },
);

const width = () => {
  const b = props.max || 0;
  if (!b) return "0%";
  const p = Math.max(0, Math.min(100, (props.value / b) * 100));
  return p.toFixed(1) + "%";
};
</script>

<template>
  <div class="bar" :class="kind === 'exp' ? '' : kind" :title="title">
    <i :style="{ width: width() }"></i>
  </div>
</template>
