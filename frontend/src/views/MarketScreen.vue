<script setup lang="ts">
import { computed, ref, watch } from "vue";

import EmbeddedPanel from "@/components/EmbeddedPanel.vue";
import type { MarketGongfa, MarketPill } from "@/types/contract";
import { useSessionStore } from "@/stores/session";
import { useUiStore } from "@/stores/ui";

const s = useSessionStore();
const ui = useUiStore();

const qty = ref<Record<string, number>>({});

const st = computed(() => s.state);
const market = computed(() => s.market);
const stones = computed(() => s.stones);

function ownedQty(name: string): number {
  return (st.value?.inventory || [])
    .filter((i) => i.name === name)
    .reduce((a, b) => a + b.qty, 0);
}
function qtyOf(name: string): number {
  return Math.max(1, Math.min(99, qty.value[name] ?? 1));
}
function setQty(name: string, v: number) {
  qty.value[name] = Math.max(1, Math.min(99, Math.floor(Number(v) || 1)));
}
function canAfford(price: number, name: string): boolean {
  return stones.value >= price * qtyOf(name);
}
async function buy(name: string) {
  const r = await s.buy(name, qtyOf(name));
  if (r?.ok) await s.openMarket();
}

// 主内容区切到坊市且没有数据时拉一次货单
watch(
  () => ui.screen,
  (v) => {
    if (v === "market" && !s.market) void s.openMarket();
  },
  { immediate: true },
);

const pills = computed<MarketPill[]>(() => market.value?.pills || []);
const gongfa = computed<MarketGongfa[]>(() => market.value?.gongfa || []);
</script>

<template>
  <EmbeddedPanel title="🏪 坊市货单">
    <template #head>
      <span class="badge">灵石 {{ stones }} 枚</span>
      <button class="btn mini" :disabled="s.busy" @click="s.openMarket()">刷新</button>
    </template>

    <p v-if="!market" class="hint">（载入货单中……）</p>

    <template v-else>
      <h3 class="sec">丹药</h3>
      <table>
        <thead>
          <tr>
            <th>名称</th>
            <th>类别</th>
            <th>单价</th>
            <th>已有</th>
            <th>数量</th>
            <th>合计</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in pills" :key="p.id" :class="{ poor: !canAfford(p.price, p.name) }">
            <td>{{ p.name }}</td>
            <td>{{ p.kind === "breakthrough" ? "突破丹" : "辅助丹" }}</td>
            <td class="mono">{{ p.price }}</td>
            <td class="mono dim">{{ ownedQty(p.name) }}</td>
            <td>
              <input
                class="num"
                type="number"
                min="1"
                max="99"
                style="width: 58px"
                :value="qtyOf(p.name)"
                @input="setQty(p.name, ($event.target as HTMLInputElement).valueAsNumber)"
              />
            </td>
            <td class="mono">{{ p.price * qtyOf(p.name) }}</td>
            <td>
              <button
                class="btn mini"
                :disabled="!s.canAct || !canAfford(p.price, p.name)"
                :title="canAfford(p.price, p.name) ? '' : '灵石不足'"
                @click="buy(p.name)"
              >
                购买
              </button>
            </td>
          </tr>
        </tbody>
      </table>

      <h3 class="sec">功法（购得入领悟池；参悟入门后可装入运转池）</h3>
      <table>
        <thead>
          <tr>
            <th>名称</th>
            <th>简介</th>
            <th>价格</th>
            <th>加成</th>
            <th>已有</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="g in gongfa"
            :key="g.id"
            :class="{ poor: !canAfford(g.price, g.name), unreadable: !g.readable }"
          >
            <td>
              {{ g.name }}
              <div class="dim" style="font-size: 11px">
                {{ g.element }}系 · {{ g.tier_label }} · {{ g.slot_label }}类
              </div>
            </td>
            <td class="desc">{{ g.desc }}</td>
            <td class="mono">{{ g.price }}</td>
            <td class="desc">
              <template v-if="g.readable">
                <template v-if="g.cultivate_bonus">
                  主修加成 ×{{ (1 + g.cultivate_bonus).toFixed(2) }}<br />
                </template>
                <template v-if="g.permanent_bonus">
                  道基被动 +{{ Math.round(g.permanent_bonus * 100) }}%<br />
                </template>
                <span v-if="g.skill_count">{{ g.skill_count }} 技</span>
                <span v-if="!g.cultivate_bonus && !g.permanent_bonus && !g.skill_count" class="dim">—</span>
              </template>
              <span v-else class="dim">境界未至，仅识其名</span>
            </td>
            <td class="mono dim">{{ ownedQty(g.name) }}</td>
            <td>
              <button
                class="btn mini"
                :disabled="!s.canAct || !canAfford(g.price, g.name) || ownedQty(g.name) > 0"
                :title="ownedQty(g.name) > 0 ? '已拥有（不可重复购买）' : canAfford(g.price, g.name) ? '' : '灵石不足'"
                @click="buy(g.name)"
              >
                {{ ownedQty(g.name) > 0 ? "已拥有" : "购买" }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </template>

    <template #footer>
      <span class="dim" style="font-size: 12px">离开坊市后货单自动收起（须身处坊市才能购买）。</span>
    </template>
  </EmbeddedPanel>
</template>

<style scoped>
.badge {
  background: #2c3c28;
  color: var(--green);
  border: 1px solid var(--green);
  border-radius: 10px;
  padding: 2px 10px;
  font-size: 12px;
}
.sec { font-size: 12.5px; color: var(--gold); margin: 8px 0 5px; }
tr.poor { opacity: .5; }
tr.unreadable .desc { color: var(--ink-dim); }
.desc { font-size: 12px; line-height: 1.45; color: #a9b7d0; max-width: 300px; }
</style>
