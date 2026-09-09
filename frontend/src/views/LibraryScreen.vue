<script setup lang="ts">
import { computed, ref } from "vue";

import EmbeddedPanel from "@/components/EmbeddedPanel.vue";
import type { GongfaDetail } from "@/types/contract";
import { useSessionStore } from "@/stores/session";

const s = useSessionStore();

const FAM_MAX = 100;
const FAM_ENTRY = 10;

const selName = ref("");
const rawSlot = ref("");

const owned = computed(() => s.state?.owned || []);
const detail = computed<GongfaDetail | null>(() => s.detail);

interface SlotOpt {
  value: string;
  label: string;
  occupied: boolean;
}

/** 槽位候选：战斗类按 战斗1→4（带占用者）；主修/身法各一 */
const slotOptions = computed<SlotOpt[]>(() => {
  const d = detail.value;
  if (!d) return [];
  const pool = s.state?.pool;
  const mk = (value: string, label: string, cur: { id: number | null; name: string | null } | undefined): SlotOpt => ({
    value,
    label: cur?.id ? `${label}（${cur.name}）` : label,
    occupied: !!cur?.id,
  });
  if (d.slot_type === "battle") {
    const slots = pool?.battle || [];
    return [1, 2, 3, 4].map((i) => mk(`battle${i}`, `战斗槽${i}`, slots[i - 1]));
  }
  if (d.slot_type === "shenfa") return [mk("shenfa", "身法槽", pool?.shenfa)];
  return [mk("main", "主修位", pool?.main)];
});

/** 默认槽位：优先第一个**空**位（战斗1→4）；全占用则第一个 */
const defaultSlot = computed(() => {
  const opts = slotOptions.value;
  return (opts.find((o) => !o.occupied) || opts[0])?.value || "";
});

/** 下拉绑定值：永远指向一个有效选项（不留空白；显示与取值一致） */
const selSlot = computed({
  get: () => {
    const opts = slotOptions.value;
    if (!opts.length) return "";
    if (rawSlot.value && opts.some((o) => o.value === rawSlot.value)) return rawSlot.value;
    return defaultSlot.value;
  },
  set: (v: string) => {
    rawSlot.value = v;
  },
});

/** 是否还有空槽可装 */
const hasFreeSlot = computed(() => slotOptions.value.some((o) => !o.occupied));

const canEquip = computed(() => {
  const d = detail.value;
  return !!d && d.readable && d.owned && d.familiarity >= FAM_ENTRY && !d.slot;
});

function open(name: string) {
  selName.value = name;
  void s.openDetail(name);
}
function equip() {
  const d = detail.value;
  if (!d) return;
  const slot = selSlot.value || defaultSlot.value;
  if (!slot) return;
  void s.learn(d.name, slot);
}
/** 参悟入门后刷新详情（否则面板仍显示旧熟悉度） */
async function comprehendEntry() {
  const d = detail.value;
  if (!d) return;
  const r = await s.comprehend(d.name, 5);
  if (r?.ok) await s.openDetail(d.name);
}
function unload() {
  const d = detail.value;
  if (!d || !d.slot) return;
  void s.forget(d.slot, d.name);
}
function pct(x: number | undefined) {
  return Math.round((x ?? 0) * 100);
}
</script>

<template>
  <EmbeddedPanel :title="`📚 书库 · 领悟池（${owned.length} 本）`">
    <div class="two-col">
      <div class="list">
        <p v-if="!owned.length" class="hint">（领悟池为空 —— 先到坊市购得功法）</p>
        <div
          v-for="o in owned"
          :key="o.id"
          class="item"
          :class="{ active: selName === o.name, dim: !o.readable }"
          @click="open(o.name)"
        >
          <div class="item-head">
            <b>【{{ o.name }}】</b>
            <span class="dim" style="font-size: 11.5px">{{ o.tier_label }}·{{ o.slot_label }}类</span>
          </div>
          <div class="item-meta" :class="o.readable ? '' : 'dim'">
            <template v-if="o.readable">
              熟悉 {{ o.familiarity }}/{{ FAM_MAX }} · {{ o.familiarity_state }}
              <span v-if="o.slot" class="gold">· 在{{ o.slot }}</span>
              <span v-else class="dim">· 未入池</span>
            </template>
            <template v-else><span class="dim">境界未至，未看懂</span></template>
          </div>
        </div>
      </div>

      <div class="detail">
        <p v-if="!detail" class="hint">← 点击左侧功法查看详情 / 装备 / 卸下</p>

        <template v-else>
          <h3 class="title">
            ━━ {{ detail.name }} ━━
            <span class="dim" style="font-size: 12px">（{{ detail.tier_label }}·{{ detail.slot_label }}类）</span>
          </h3>

          <template v-if="detail.readable">
            <p class="kv">
              <span>五行 {{ detail.element || "无" }} 系</span>
              <span>熟悉 {{ detail.familiarity }}/{{ FAM_MAX }}（{{ detail.familiarity_state }}）</span>
              <span v-if="detail.slot" class="gold">在{{ detail.slot }}</span>
            </p>
            <p v-if="detail.cultivate_bonus" class="kv">
              主修修炼加成 ×{{ (1 + detail.cultivate_bonus).toFixed(2) }}
            </p>
            <p v-if="detail.permanent_bonus" class="kv">
              道基被动：习得后修炼效率永久 +{{ pct(detail.permanent_bonus) }}%
            </p>
            <p class="desc dim">{{ detail.desc }}</p>

            <h4 class="sub">技能（熟悉度达标才「亮出」）</h4>
            <div v-for="sk in detail.skills" :key="sk.id" class="skill" :class="sk.lit ? 'lit' : 'dim'">
              <span>・{{ sk.name }}</span>
              <span class="mono small">
                {{ sk.element }}·{{ sk.kind }} ｜ 耗{{ sk.qi_cost }} ｜ 前摇
                {{ (sk.windup / 100).toFixed(1) }} ｜ 后摇 {{ (sk.recovery / 100).toFixed(1) }}
              </span>
              <span v-if="sk.lit" class="ok-text small">已亮出</span>
              <span v-else class="small">需熟悉度 {{ sk.unlock_fam }}</span>
            </div>

            <div class="ops">
              <template v-if="canEquip">
                <select v-model="selSlot" class="sel">
                  <option
                    v-for="o in slotOptions"
                    :key="o.value"
                    :value="o.value"
                    :disabled="o.occupied"
                  >
                    {{ o.label }}
                  </option>
                </select>
                <button class="btn mini primary" :disabled="s.busy || !hasFreeSlot" @click="equip">
                  装备
                </button>
                <span v-if="!hasFreeSlot" class="dim small">槽位已满，先卸下一个</span>
              </template>
              <button v-else-if="detail.slot" class="btn mini danger" :disabled="s.busy" @click="unload">
                卸下（{{ detail.slot }}）
              </button>
              <span v-else-if="!detail.owned" class="dim small">尚未拥有（先到坊市购得）</span>
              <template v-else>
                <span class="dim small">熟悉度需 ≥ {{ FAM_ENTRY }} 才能入池</span>
                <!-- 已拥有且看懂、尚未入门时也能点（此前被 canEquip 挡住 → 永远点不到） -->
                <button class="btn mini" :disabled="s.busy" @click="comprehendEntry">
                  参悟入门（5 日）
                </button>
              </template>
            </div>
          </template>

          <p v-else class="unreadable">境界未至，书文晦涩难明（只识其名与来历）。</p>
        </template>
      </div>
    </div>

    <template #footer>
      <span class="dim" style="font-size: 12px">
        池外功法不生效：装备后按槽位（主修位 / 战斗槽 1-4 / 身法槽）参与战斗与修炼。
      </span>
    </template>
  </EmbeddedPanel>
</template>

<style scoped>
.two-col { display: grid; grid-template-columns: 280px minmax(0, 1fr); gap: 12px; }
@media (max-width: 1100px) { .two-col { grid-template-columns: 1fr; } }
.list { display: flex; flex-direction: column; gap: 4px; }
.item {
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 5px 8px;
  cursor: pointer;
  background: var(--panel3);
}
.item:hover { border-color: var(--gold); }
.item.active { border-color: var(--blue); background: #1b2a4a; }
.item.dim { opacity: .7; }
.item-head { display: flex; justify-content: space-between; gap: 6px; }
.item-meta { font-size: 11.5px; color: var(--ink-dim); }
.detail { min-width: 0; }
.title { font-size: 13.5px; color: var(--gold); margin-bottom: 6px; }
.kv { display: flex; gap: 12px; flex-wrap: wrap; margin: 2px 0; font-size: 12.5px; }
.desc { font-size: 12.5px; line-height: 1.5; }
.sub { font-size: 12.5px; color: var(--ink-dim); margin: 9px 0 4px; }
.skill {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  align-items: baseline;
  padding: 3px 6px;
  border-bottom: 1px dashed var(--line);
  font-size: 12.5px;
}
.skill.lit { color: var(--green); }
.skill .small, .small { font-size: 11.5px; }
.ops { display: flex; gap: 8px; align-items: center; margin-top: 10px; flex-wrap: wrap; }
.unreadable { color: var(--ink-dim); font-style: italic; }
</style>
