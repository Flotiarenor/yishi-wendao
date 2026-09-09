<script setup lang="ts">
import { computed } from "vue";

import Bar from "@/components/Bar.vue";
import { useSessionStore } from "@/stores/session";
import { useUiStore } from "@/stores/ui";

const s = useSessionStore();
const ui = useUiStore();

const st = computed(() => s.state);
const FAM_MAX = 100;

const mainTxt = computed(() => {
  const m = st.value?.pool?.main;
  if (!m || !m.name) return "（空）";
  const b = m.bonus == null ? "" : ` ×${m.bonus.toFixed(2)}`;
  return `【${m.name}】${b}`;
});

const battleSlots = computed(() =>
  (st.value?.pool?.battle || []).map((b, i) => `${i + 1}【${b.name || "空"}】`).join("　"),
);

const shenfa = computed(() => {
  const v = st.value?.pool?.shenfa;
  return v && v.name ? `【${v.name}】` : "（空）";
});

const elements = computed(() =>
  Object.entries(st.value?.elements || {}).map(([k, v]) => `${k}${v}`).join(" "),
);

function fmt1(x: number | undefined) {
  return (Math.round((x ?? 0) * 10) / 10).toFixed(1);
}
function pctText(a: number, b: number) {
  if (!b) return "0%";
  return Math.min(100, (a / b) * 100).toFixed(0) + "%";
}
</script>

<template>
  <section class="card">
    <h2>
      状态
      <span v-if="st" class="dim" style="font-size: 12px">{{ st.location.name }}</span>
    </h2>

    <p v-if="!st" class="hint">
      尚未开世 —— 点右上「新建一世」开始仙途；<br />已有存档可在「— 读档 —」中选择。
    </p>

    <template v-else>
      <div class="kv">
        <span>{{ st.name }} · <b>{{ st.realm_name }}</b>（第{{ st.realm_idx }}档）</span>
        <span class="dim">{{ st.alive ? "" : "☠ 已陨" }}</span>
      </div>

      <div class="row-line">
        <Bar :value="st.exp" :max="st.exp_cap" kind="exp" :title="`修为 ${st.exp} / ${st.exp_cap}`" />
        <span class="mono small">{{ fmt1(st.exp) }} / {{ st.exp_cap }}（{{ pctText(st.exp, st.exp_cap) }}）</span>
      </div>

      <div class="kv">
        <span>闭关效率 ×{{ st.cultivation_mult.toFixed(2) }}</span>
        <span>资质 {{ st.spirit_root }} ×{{ st.root_mult.toFixed(2) }}</span>
      </div>
      <div class="kv">
        <span class="dim">五行亲和</span>
        <span class="mono small">{{ elements || "—" }}</span>
      </div>
      <div class="kv">
        <span>寿元</span>
        <span>{{ fmt1(st.age_years) }} / {{ fmt1(st.lifespan_years) }} 岁（余 {{ fmt1(st.lifespan_left) }}）</span>
      </div>

      <div class="row-line">
        <span class="dim small">心魔</span>
        <Bar :value="st.heart_demon" :max="100" kind="hd" />
        <span class="mono small">{{ st.heart_demon }}/100</span>
      </div>

      <div class="kv">
        <span>灵石 {{ st.spirit_stones }} 枚 ｜ 业力 {{ st.karma }}</span>
      </div>
      <div class="kv dim small">
        <span>第 {{ st.turn }} 次操作 ｜ 种子 {{ st.seed }}</span>
      </div>

      <div class="quick">
        <button class="btn mini" :class="{ active: ui.screen === 'map' && !ui.battleOpen }" @click="ui.open('map')">
          地图
        </button>
        <button
          class="btn mini"
          :class="{ active: ui.screen === 'cultivation' }"
          title="闭关 / 参悟 / 突破 / 静养"
          @click="ui.open('cultivation')"
        >
          修炼
        </button>
        <button
          class="btn mini"
          :disabled="s.busy || !s.atMarket"
          :title="s.atMarket ? '查看坊市货单' : '须先前往坊市'"
          @click="s.openMarket()"
        >
          坊市
        </button>
        <button class="btn mini" :class="{ active: ui.screen === 'library' }" @click="ui.open('library')">
          书库
        </button>
        <button
          class="btn mini"
          :class="{ active: ui.screen === 'chronicle' }"
          @click="s.chronicleRun().then(() => ui.open('chronicle'))"
        >
          编年史
        </button>
      </div>

      <div class="sect">
        <h4>背包</h4>
        <p v-if="!(st.inventory || []).length" class="dim">（空）</p>
        <span v-for="it in st.inventory" :key="it.id" class="pill-chip">
          {{ it.name }}×{{ it.qty }}
          <button class="btn mini" :disabled="!s.canAct" @click="s.usePill(it.name)">服</button>
        </span>
      </div>

      <div class="sect">
        <h4>运转池（池外功法不生效）</h4>
        <div>主修位：{{ mainTxt }}</div>
        <div>战斗槽：{{ battleSlots || "（空）" }}</div>
        <div>身法槽：{{ shenfa }}</div>
      </div>

      <div class="sect">
        <h4>领悟池（已拥有 {{ (st.owned || []).length }} 本）</h4>
        <p v-if="!(st.owned || []).length" class="dim">（空）</p>
        <div
          v-for="o in st.owned"
          :key="o.id"
          class="owned"
          :class="{ dim: !o.readable }"
          @click="s.openDetail(o.name)"
        >
          ・{{ o.name }}（{{ o.tier_label }}·{{ o.slot_label }}类）
          <template v-if="o.readable">
            熟悉 {{ o.familiarity }}/{{ FAM_MAX }} · {{ o.familiarity_state }} ·
            {{ o.slot ? "在" + o.slot : "未入池" }}
          </template>
          <template v-else><span class="dim">未看懂</span></template>
        </div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.kv { display: flex; justify-content: space-between; gap: 8px; line-height: 1.65; }
.kv b { color: var(--blue); }
.row-line { display: flex; align-items: center; gap: 8px; margin: 2px 0 6px; }
.small { font-size: 12px; }
.sect { margin-top: 10px; font-size: 12.5px; }
.sect h4 { margin: 6px 0 3px; color: var(--ink-dim); font-size: 12px; }
.pill-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: #172038;
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 1px 6px 1px 10px;
  margin: 2px 4px 2px 0;
  font-size: 12px;
}
.owned { cursor: pointer; padding: 1px 4px; border-radius: 4px; }
.owned:hover { background: #24304d; }
.quick { display: flex; gap: 6px; flex-wrap: wrap; margin: 10px 0 2px; }
</style>
