<script setup lang="ts">
/**
 * 地图 = 主页面（用户拍板方案 B）。
 * 战斗期间由 BattleScreen 临时接管主内容区，地图数据不丢。
 */
import { computed } from "vue";

import EmbeddedPanel from "@/components/EmbeddedPanel.vue";
import { SITES } from "@/types/sites";
import { useSessionStore } from "@/stores/session";

const s = useSessionStore();

const st = computed(() => s.state);
const curName = computed(() => st.value?.location?.name ?? "");
const realmIdx = computed(() => st.value?.realm_idx ?? 1);

function underlevel(req: number) {
  return realmIdx.value < req;
}
function travel(name: string) {
  void s.travel(name);
}
function explore(name: string) {
  void s.explore(name);
}
</script>

<template>
  <EmbeddedPanel :title="`🗺 地图 · 当前位置【${curName}】`" :closable="false">
    <template #head>
      <span class="dim" style="font-size: 12px">移动 3 日 ｜ 探索按地点耗时</span>
    </template>

    <div class="grid">
      <div
        v-for="site in SITES"
        :key="site.id"
        class="site"
        :class="{ current: site.name === curName, danger: site.explorable && underlevel(site.realmReq) }"
      >
        <div class="site-head">
          <b>{{ site.name }}</b>
          <span v-if="site.name === curName" class="tag tag-cur">当前</span>
          <span v-if="!site.explorable" class="tag tag-market">坊市</span>
        </div>
        <p class="desc dim">{{ site.desc }}</p>
        <div class="meta mono">
          <template v-if="site.explorable">
            建议第{{ site.realmReq }}档 ｜ {{ site.daysCost }} 日 ｜ 遇险 {{ (site.danger * 100).toFixed(0) }}%
          </template>
          <template v-else>交易地点（不可探索）</template>
        </div>
        <p v-if="site.explorable && underlevel(site.realmReq)" class="warn">⚠ 境界不足：遇险翻倍、心魔 +5</p>

        <div class="ops">
          <button
            class="btn mini"
            :disabled="!s.canAct || site.name === curName"
            :title="site.name === curName ? '你已在此地' : ''"
            @click="travel(site.name)"
          >
            {{ site.name === curName ? "已在此地" : "前往" }}
          </button>
          <button
            v-if="site.explorable"
            class="btn mini primary"
            :disabled="!s.canAct"
            @click="explore(site.name)"
          >
            探索
          </button>
          <button
            v-if="site.name === '坊市'"
            class="btn mini"
            :disabled="!s.canAct || curName !== '坊市'"
            :title="curName === '坊市' ? '' : '须先前往坊市'"
            @click="s.openMarket()"
          >
            货单
          </button>
        </div>
      </div>
    </div>
  </EmbeddedPanel>
</template>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 9px;
}
.site {
  background: var(--panel3);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 9px 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.site.current { border-color: var(--gold); box-shadow: 0 0 0 1px rgba(216, 178, 106, .25) inset; }
.site.danger { border-color: #5a3a3a; }
.site-head { display: flex; align-items: center; gap: 8px; }
.desc { margin: 0; font-size: 12px; line-height: 1.45; }
.meta { font-size: 11.5px; color: var(--ink-dim); }
.warn { margin: 0; font-size: 11.5px; color: var(--red); }
.ops { display: flex; gap: 6px; margin-top: 3px; flex-wrap: wrap; }
.tag { font-size: 11px; border-radius: 9px; padding: 0 7px; border: 1px solid var(--line); }
.tag-cur { color: var(--gold); border-color: var(--gold); }
.tag-market { color: var(--blue); border-color: var(--blue); }
</style>
