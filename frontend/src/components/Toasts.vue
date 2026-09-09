<script setup lang="ts">
import { useUiStore } from "@/stores/ui";

const ui = useUiStore();
</script>

<template>
  <div class="toasts">
    <div
      v-for="t in ui.toasts"
      :key="t.id"
      class="toast"
      :class="t.kind === 'err' ? '' : t.kind"
      role="status"
      @click="ui.dismiss(t.id)"
    >
      {{ t.text }}
    </div>
  </div>
</template>
