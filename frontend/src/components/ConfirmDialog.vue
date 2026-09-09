<script setup lang="ts">
import { useUiStore } from "@/stores/ui";

const ui = useUiStore();
</script>

<template>
  <div v-if="ui.confirm" class="overlay" @click.self="ui.answer(false)">
    <div class="sheet" style="width: min(420px, 100%)">
      <header>
        <h2>请确认</h2>
      </header>
      <div class="body">{{ ui.confirm.text }}</div>
      <footer style="justify-content: flex-end">
        <button class="btn" @click="ui.answer(false)">取消</button>
        <button class="btn danger" @click="ui.answer(true)">确定</button>
      </footer>
    </div>
  </div>
</template>
