<script setup lang="ts">
/**
 * 修炼页（主内容区视图，与地图/坊市同级）。
 *
 * 用户拍板（2026-09-09）：
 *   - 修炼/参悟/突破/静养**直接在主页面**，不再有「行动栏」；
 *   - 参悟选择要**记住**，不要每次刷新重新选（原先下拉被重渲染打回第一项）；
 *   - 场所限制暂不做（野外也能闭关参悟），但布局按「场所」分区预留（见 footer 提示）。
 */
import { computed, ref, watch } from "vue";

import EmbeddedPanel from "@/components/EmbeddedPanel.vue";
import Bar from "@/components/Bar.vue";
import { useSessionStore } from "@/stores/session";
import { useUiStore } from "@/stores/ui";

const s = useSessionStore();
const ui = useUiStore();

const FAM_MAX = 100;
const cultivateDays = ref(30);
const usePill = ref(false);
const cwDays = ref(5);
const ageDays = ref(30);

const st = computed(() => s.state);
const canAct = computed(() => s.canAct);

// ---- 参悟目标：由 store 记住（跨刷新/跨页保持） ----
const cwTarget = computed({
  get: () => s.cwGongfa,
  set: (v: string) => s.setCwGongfa(v),
});

// 目标失效（已大成/被卸下/换了存档）时回退到第一个可参悟功法
watch(
  () => s.comprehensible.map((o) => o.name).join("|"),
  () => {
    if (!s.comprehensible.length) return;
    if (!s.comprehensible.some((o) => o.name === s.cwGongfa)) {
      s.setCwGongfa(s.comprehensible[0].name);
    }
  },
  { immediate: true },
);

// ---- 突破前置信息（与服务端 settings 同源常量；避免「点了才知道缺什么」） ----
const STONE_BASE = 10;
const STONE_MAJOR = 50;
const MAJOR_STARTS = [1, 10, 14, 18, 22];
const BREAKTHROUGH_PILLS = ["筑基丹", "结金丹", "凝婴丹", "悟道丹"];

const btInfo = computed(() => {
  const v = st.value;
  if (!v) return null;
  const cur = v.realm_idx;
  const major = MAJOR_STARTS.includes(cur + 1);
  const stones = STONE_BASE + cur * 2 + (major ? STONE_MAJOR : 0);
  const pillInBag = (v.inventory || []).find((it) => BREAKTHROUGH_PILLS.includes(it.name));
  const expLeft = Math.max(0, v.exp_cap - v.exp);
  return {
    major,
    stones,
    enoughStones: v.spirit_stones >= stones,
    expFull: v.exp >= v.exp_cap,
    expLeft,
    pillInBag: pillInBag?.name ?? null,
    needPill: major,
    /** 按当前效率粗估还需天数（仅提示，实际闭关会封顶到圆满那天） */
    estDays: Math.max(0, Math.ceil(expLeft / Math.max(0.01, v.cultivation_mult))),
  };
});

const selected = computed(() => s.comprehensible.find((o) => o.name === s.cwGongfa) || null);

function doCultivate() {
  void s.cultivate(Math.max(1, Math.min(3650, Number(cultivateDays.value) || 30)), usePill.value);
}
function doComprehend() {
  const name = s.cwGongfa || s.comprehensible[0]?.name || "";
  if (!name) {
    ui.notify("无可参悟的功法（先在书库确认是否看懂）");
    return;
  }
  void s.comprehend(name, Math.max(1, Math.min(3650, Number(cwDays.value) || 5)));
}
function doBreakthrough() {
  void s.breakthrough();
}
function doAgePass() {
  void s.agePass(Math.max(1, Math.min(3650, Number(ageDays.value) || 30)));
}
</script>

<template>
  <EmbeddedPanel title="🧘 修炼" :closable="false">
    <template #head>
      <span class="dim" style="font-size: 12px">
        当前在【{{ st?.location?.name || "—" }}】· 闭关效率 ×{{ st?.cultivation_mult.toFixed(2) }}
      </span>
    </template>

    <p v-if="!st" class="hint">尚未开世 —— 先「新建一世」。</p>

    <template v-else>
      <!-- 修为总览 -->
      <div class="overview">
        <div class="row-line">
          <span class="lbl">修为</span>
          <Bar :value="st.exp" :max="st.exp_cap" />
          <span class="mono num">{{ st.exp.toFixed(1) }} / {{ st.exp_cap }}</span>
        </div>
        <div class="kv dim">
          <span>资质 {{ st.spirit_root }} ×{{ st.root_mult.toFixed(2) }}</span>
          <span>寿元 {{ st.age_years.toFixed(1) }} / {{ st.lifespan_years.toFixed(1) }} 岁（余 {{ st.lifespan_left.toFixed(1) }}）</span>
          <span>心魔 {{ st.heart_demon }}/100</span>
        </div>
      </div>

      <div class="grid">
        <!-- 闭关 -->
        <fieldset class="block">
          <legend>闭关修炼</legend>
          <p class="desc dim">按天推进，修为按「闭关效率 × 资质」累积；圆满的那天自动封顶。</p>
          <label>天数 <input v-model.number="cultivateDays" type="number" min="1" max="3650" class="num" /></label>
          <label class="chk"><input v-model="usePill" type="checkbox" /> 用聚灵丹（闭关加速）</label>
          <div class="ops">
            <button class="btn mini primary" :disabled="!canAct" @click="doCultivate">闭关</button>
            <span v-if="btInfo && !btInfo.expFull" class="dim small">
              约需 {{ btInfo.estDays }} 日修为圆满
            </span>
            <span v-else class="ok-text small">修为已满，可突破</span>
          </div>
        </fieldset>

        <!-- 参悟 -->
        <fieldset class="block">
          <legend>参悟（熟悉度 → 技能亮出）</legend>
          <p class="desc dim">
            已看懂且未大成的功法可参悟；熟悉度 {{ 10 }} 入门即可入运转池，{{ FAM_MAX }} 为大成。
          </p>
          <label>
            功法
            <select v-model="cwTarget" class="sel" :disabled="!canAct || !s.comprehensible.length">
              <option v-if="!s.comprehensible.length" value="">（无可参悟）</option>
              <option v-for="o in s.comprehensible" :key="o.id" :value="o.name">
                {{ o.name }}（{{ o.familiarity }}/{{ FAM_MAX }}）
              </option>
            </select>
          </label>
          <label>天数 <input v-model.number="cwDays" type="number" min="1" max="3650" class="num" /></label>
          <div class="ops">
            <button
              class="btn mini primary"
              :disabled="!canAct || !s.comprehensible.length"
              @click="doComprehend"
            >
              参悟
            </button>
            <span v-if="selected" class="dim small">
              {{ selected.name }}：熟悉 {{ selected.familiarity }}/{{ FAM_MAX }}（{{ selected.familiarity_state }}）
            </span>
          </div>
        </fieldset>

        <!-- 突破 -->
        <fieldset class="block">
          <legend>突破境界</legend>
          <template v-if="btInfo">
            <p class="desc dim">
              第 {{ st.realm_idx }} 档 → 第 {{ st.realm_idx + 1 }} 档<template v-if="btInfo.major">（跨大境界）</template>
            </p>
            <ul class="req">
              <li :class="btInfo.expFull ? 'ok-text' : 'err-text'">
                修为圆满：{{ btInfo.expFull ? "已满" : `还差 ${btInfo.expLeft.toFixed(1)}` }}
              </li>
              <li :class="btInfo.enoughStones ? 'ok-text' : 'err-text'">
                护法灵石：需 {{ btInfo.stones }}，有 {{ st.spirit_stones }}
              </li>
              <li v-if="btInfo.needPill" :class="btInfo.pillInBag ? 'ok-text' : 'err-text'">
                突破丹：{{ btInfo.pillInBag ? `背包有【${btInfo.pillInBag}】` : "缺少（坊市可购）" }}
              </li>
            </ul>
          </template>
          <div class="ops">
            <button class="btn mini primary" :disabled="!canAct" @click="doBreakthrough">突破</button>
          </div>
        </fieldset>

        <!-- 静养 -->
        <fieldset class="block">
          <legend>静养</legend>
          <p class="desc dim">不涨修为，纯粹推进时间（等丹方冷却 / 等寿元结算等场合用）。</p>
          <label>天数 <input v-model.number="ageDays" type="number" min="1" max="3650" class="num" /></label>
          <div class="ops">
            <button class="btn mini" :disabled="!canAct" @click="doAgePass">静养</button>
          </div>
        </fieldset>
      </div>
    </template>

    <template #footer>
      <span class="dim" style="font-size: 12px">
        场所系统（客栈 / 野外洞府）尚未实现：当前在任意地点都能闭关参悟；
        后续接入时按场所解锁/加成，本页按分区预留。
      </span>
    </template>
  </EmbeddedPanel>
</template>

<style scoped>
.overview {
  background: var(--panel3);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 8px 10px;
  margin-bottom: 10px;
}
.row-line { display: flex; align-items: center; gap: 8px; margin-bottom: 5px; }
.lbl { width: 30px; font-size: 12px; color: var(--ink-dim); }
.num { width: 110px; text-align: right; font-size: 12px; }
.kv { display: flex; gap: 14px; flex-wrap: wrap; font-size: 12px; }

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 10px;
}
.block {
  border: 1px solid var(--line);
  border-radius: 8px;
  margin: 0;
  padding: 8px 10px;
  background: var(--panel3);
}
legend { font-size: 12.5px; color: var(--gold); padding: 0 4px; }
.desc { font-size: 12px; line-height: 1.45; margin: 0 0 6px; }
label { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; margin: 0 8px 5px 0; }
.ops { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 3px; }
.small { font-size: 11.5px; }
.req { margin: 0 0 6px; padding-left: 16px; font-size: 12px; line-height: 1.6; }
</style>
