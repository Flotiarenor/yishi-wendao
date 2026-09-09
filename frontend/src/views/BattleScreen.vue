<script setup lang="ts">
/**
 * 战斗界面 = 临时接管主内容区（用户拍板方案 B）。
 *
 * 交互依据 = docs/战斗系统定案.md §四：决策窗口 + 无槽位队列
 *   ① 排入动作（battle_submit，不推进时间轴）
 *   ② 队列累计时长 ≥ 窗口 或 点「执行本轮」→ 结算（battle_skip）
 * 数据依据 = engine/battle.py Battle.state()
 *
 * 布局取舍（用户拍板）：常用在上——气血/灵气/时间轴 + 平砍/防御/聚气/遁走 + 队列执行；
 * 技能列表折叠在下方，需要时展开。
 */
import { computed, ref } from "vue";

import Bar from "@/components/Bar.vue";
import EmbeddedPanel from "@/components/EmbeddedPanel.vue";
import { reasonText } from "@/api/client";
import { useSessionStore } from "@/stores/session";
import { useUiStore } from "@/stores/ui";

const s = useSessionStore();
const ui = useUiStore();

const b = computed(() => s.battle);
const showSkills = ref(false);

const BASIC_KEYS = ["attack", "defend", "gather", "flee"];

/** 厘息 → 息（显示用；判定始终用整数厘息） */
function li(v: number | undefined | null, digits = 1): string {
  if (v == null) return "—";
  return (v / 100).toFixed(digits);
}

/** 队列累计时长（厘息）= 最后一个动作结束时刻 − 当前时刻 */
const queueTotal = computed(() => {
  const st = b.value;
  if (!st || !st.queue.length) return 0;
  return st.queue[st.queue.length - 1].end_t - st.t;
});

const windowOpen = computed(() => {
  const st = b.value;
  if (!st) return false;
  return queueTotal.value >= st.window_li;
});

/** 时间轴可视区间（厘息） */
const axis = computed(() => {
  const st = b.value;
  if (!st) return { t0: 0, t1: 100, span: 100 };
  const candidates = [
    st.t,
    st.player_next_t,
    st.enemy_next_t,
    ...(st.queue || []).map((q) => q.end_t),
  ];
  const t0 = Math.min(...candidates);
  const rawMax = Math.max(...candidates);
  const span = Math.max(rawMax - t0, st.window_li || 100, 200);
  return { t0, t1: t0 + span * 1.12, span };
});

function pos(t: number | undefined): string {
  const { t0, t1 } = axis.value;
  const p = ((Math.max(t0, Math.min(t1, t ?? t0)) - t0) / (t1 - t0 || 1)) * 100;
  return p.toFixed(2) + "%";
}

interface QueueBar {
  key: string;
  name: string;
  left: string;
  width: string;
  /** 前摇占整条的比例（0~100） */
  windPct: number;
}

/** 时间轴上的队列条：**前摇段（暖金）+ 后摇段（冷蓝）** */
const queueBars = computed<QueueBar[]>(() => {
  const st = b.value;
  if (!st) return [];
  const { t0, t1 } = axis.value;
  const span = t1 - t0 || 1;
  const out: QueueBar[] = [];
  let prev = st.t;
  for (const q of st.queue) {
    const start = q.start_t ?? prev;
    const land = q.land_t ?? q.end_t;
    const end = q.end_t;
    const total = Math.max(1, end - start);
    const left = ((start - t0) / span) * 100;
    const width = ((end - start) / span) * 100;
    out.push({
      key: q.key + end,
      name: q.name,
      left: left.toFixed(2) + "%",
      width: Math.max(width, 0.6).toFixed(2) + "%",
      windPct: Math.max(0, Math.min(100, ((land - start) / total) * 100)),
    });
    prev = end;
  }
  return out;
});

/** 常用动作（基础四式，缺失则回退到动作池前几个） */
const basicActions = computed(() => {
  const st = b.value;
  if (!st) return [];
  const found = BASIC_KEYS.map((k) => st.actions.find((a) => a.key === k)).filter(Boolean);
  return found.length ? (found as typeof st.actions) : st.actions.slice(0, 4);
});

/** 技能列表（去掉基础动作，且需要技能本身的展示信息） */
const skillActions = computed(() => {
  const st = b.value;
  if (!st) return [];
  return st.actions.filter((a) => !BASIC_KEYS.includes(a.key));
});

/** 该动作已排入队列的份数 */
function queuedCount(key: string): number {
  const st = b.value;
  return st ? st.queue.filter((q) => q.key === key).length : 0;
}

/** 能否点击：已排的永远可点（用于撤回）；未排的需可用且窗口未满 */
function canClickAction(a: { key: string; available: boolean }): boolean {
  const st = b.value;
  if (!st || st.ended || s.busy) return false;
  if (queuedCount(a.key) > 0) return true;
  return a.available && !windowOpen.value;
}

/** 点击动作：未排 → 排入；已排 → 撤回最后一个（再点一次即撤销，用户要求） */
function submit(key: string) {
  const st = b.value;
  if (!st) return;
  let idx = -1;
  for (let i = st.queue.length - 1; i >= 0; i--) {
    if (st.queue[i].key === key) {
      idx = i;
      break;
    }
  }
  if (idx >= 0) void s.battleUnqueue(idx);
  else void s.battleSubmit(key);
}
function execute() {
  void s.battleSkip();
}
function unqueue(index: number) {
  void s.battleUnqueue(index);
}
function clearQueue() {
  void s.battleClear();
}
function backToMap() {
  ui.closeBattle();
  ui.open("map");
}

const enemyEffects = computed(() => b.value?.effects?.enemy || []);
const playerEffects = computed(() => b.value?.effects?.player || []);
</script>

<template>
  <EmbeddedPanel v-if="b" :title="`⚔ 战斗 · ${b.enemy.name}（${b.enemy.element}系·第${b.enemy.realm_idx}档）`">
    <template #head>
      <button class="btn mini ghost" @click="backToMap">回地图（战斗继续）</button>
    </template>

    <!-- ===== 双方状态（最常用，放最上） ===== -->
    <div class="sides">
      <div class="side">
        <div class="side-name">
          <b>{{ s.state?.name }}</b>
          <span class="dim mono">
            速 {{ b.player.speed.toFixed(2) }} ｜ 回灵 {{ b.player.qi_rate.toFixed(2) }}/息 ｜ 灵石 {{ b.player.stones }}
          </span>
        </div>
        <div class="row-line">
          <span class="lbl">气血</span>
          <Bar :value="b.player.hp" :max="b.player.hp_max" kind="hp" />
          <span class="mono num">{{ b.player.hp.toFixed(0) }}/{{ b.player.hp_max.toFixed(0) }}</span>
        </div>
        <div class="row-line">
          <span class="lbl">灵气</span>
          <Bar :value="b.player.qi" :max="b.player.qi_max" kind="qi" />
          <span class="mono num">{{ b.player.qi.toFixed(0) }}/{{ b.player.qi_max.toFixed(0) }}</span>
        </div>
        <div class="effects">
          <span v-if="!playerEffects.length" class="dim">（无状态）</span>
          <span v-for="e in playerEffects" :key="e.key" class="fx fx-buff">
            {{ e.key }}<template v-if="e.stacks > 1">×{{ e.stacks }}</template>
            <span class="dim"> {{ li(Math.max(0, e.until - b.t)) }}息</span>
          </span>
        </div>
      </div>

      <div class="side">
        <div class="side-name">
          <b class="enemy-name">{{ b.enemy.name }}</b>
          <span class="dim mono">{{ b.enemy.element }}系 · 第{{ b.enemy.realm_idx }}档</span>
        </div>
        <div class="row-line">
          <span class="lbl">气血</span>
          <Bar :value="b.enemy.hp" :max="b.enemy.hp_max" kind="enemy" />
          <span class="mono num">{{ b.enemy.hp.toFixed(0) }}/{{ b.enemy.hp_max.toFixed(0) }}</span>
        </div>
        <div class="effects">
          <span v-if="!enemyEffects.length" class="dim">（无状态）</span>
          <span v-for="e in enemyEffects" :key="e.key" class="fx fx-debuff">
            {{ e.key }}<template v-if="e.stacks > 1">×{{ e.stacks }}</template>
            <span class="dim"> {{ li(Math.max(0, e.until - b.t)) }}息</span>
          </span>
        </div>
      </div>
    </div>

    <!-- ===== 时间轴 ===== -->
    <div class="timeline">
      <div class="tl-head">
        <span class="dim">决策窗口</span>
        <span class="mono">
          已排 {{ li(queueTotal) }} / {{ li(b.window_li) }} 息
          <span v-if="windowOpen" class="gold">（已排满，点「执行本轮」）</span>
        </span>
      </div>
      <div class="tl-track">
        <div
          class="tl-window"
          :style="{
            left: pos(b.t),
            width: ((b.window_li / (axis.t1 - axis.t0)) * 100).toFixed(2) + '%',
          }"
          :title="`窗口 ${li(b.window_li)} 息（敌方下次行动前）`"
        ></div>
        <div
          v-for="q in queueBars"
          :key="q.key"
          class="tl-act"
          :style="{ left: q.left, width: q.width }"
          :title="`${q.name}（前摇 ${q.windPct.toFixed(0)}% / 后摇 ${(100 - q.windPct).toFixed(0)}%）`"
        >
          <span class="tl-wind" :style="{ width: q.windPct + '%' }"></span>
          <span class="tl-rec" :style="{ width: 100 - q.windPct + '%' }"></span>
          <span class="tl-act-name">{{ q.name }}</span>
        </div>
        <div class="tl-mark player" :style="{ left: pos(b.player_next_t) }" title="我方下次可动">我</div>
        <div class="tl-mark enemy" :style="{ left: pos(b.enemy_next_t) }" title="敌方下次出手">敌</div>
      </div>
      <div class="tl-foot mono dim">
        <span>t={{ li(b.t) }} 息</span>
        <span>我方下次可动 {{ li(b.player_next_t) }}</span>
        <span>敌方下次出手 {{ li(b.enemy_next_t) }}</span>
      </div>
    </div>

    <!-- ===== 常用动作 + 执行 ===== -->
    <div class="cmd-row">
      <button
        v-for="a in basicActions"
        :key="a.key"
        class="act"
        :class="{ na: !a.available && !queuedCount(a.key), queued: queuedCount(a.key) > 0 }"
        :disabled="!canClickAction(a)"
        :title="
          queuedCount(a.key)
            ? `点击撤回最后一个（已排 ${queuedCount(a.key)}）`
            : a.available
              ? a.desc
              : reasonText(a.reason)
        "
        @click="submit(a.key)"
      >
        <span class="act-name">
          {{ a.name }}
          <span v-if="queuedCount(a.key)" class="q-badge">已排×{{ queuedCount(a.key) }}</span>
        </span>
        <span class="act-meta mono">
          耗灵 {{ a.qi_cost }} ｜ <span class="rec">后摇 {{ li(a.recovery) }}</span>
        </span>
      </button>
      <button class="btn primary exec" :disabled="s.busy || !b" @click="execute">
        执行本轮（{{ b.queue.length }}）
      </button>
    </div>

    <!-- ===== 队列（点条目或再点动作按钮即可撤回；不推进时间轴/不消耗资源） ===== -->
    <div class="queue">
      <div class="q-head">
        <span class="dim">本轮队列（{{ b.queue.length }}）—— 点条目撤回</span>
        <button v-if="b.queue.length" class="btn mini ghost" :disabled="s.busy" @click="clearQueue">
          清空
        </button>
      </div>
      <span v-if="!b.queue.length" class="dim">
        （空 —— 点上方动作排入；再点同一动作即撤回）
      </span>
      <span
        v-for="(q, i) in b.queue"
        :key="i"
        class="q-item"
        title="点击撤回该动作"
        @click="unqueue(i)"
      >
        <span class="q-no">{{ i + 1 }}</span>
        <span>{{ q.name }}</span>
        <span class="dim mono">耗{{ q.qi_cost }} · 止于 {{ li(q.end_t) }}息</span>
        <span class="q-x">×</span>
      </span>
    </div>

    <!-- ===== 技能（折叠） ===== -->
    <div class="skills-head">
      <button class="btn mini ghost" @click="showSkills = !showSkills">
        {{ showSkills ? "▾" : "▸" }} 全部技能（{{ skillActions.length }}）
      </button>
      <span v-if="windowOpen" class="gold" style="font-size: 12px">窗口已排满，请先执行本轮</span>
    </div>
    <div v-if="showSkills" class="skills">
      <button
        v-for="a in skillActions"
        :key="a.key"
        class="act"
        :class="{ na: !a.available && !queuedCount(a.key), queued: queuedCount(a.key) > 0 }"
        :disabled="!canClickAction(a)"
        :title="
          queuedCount(a.key)
            ? `点击撤回最后一个（已排 ${queuedCount(a.key)}）`
            : a.available
              ? a.desc
              : reasonText(a.reason)
        "
        @click="submit(a.key)"
      >
        <span class="act-name">
          {{ a.name }}
          <span v-if="queuedCount(a.key)" class="q-badge">已排×{{ queuedCount(a.key) }}</span>
        </span>
        <span class="act-meta mono">
          耗灵 {{ a.qi_cost }} ｜
          <span class="wind">前摇 {{ li(a.windup) }}</span> ｜
          <span class="rec">后摇 {{ li(a.recovery) }}</span> ｜ 阶{{ a.tier }}
        </span>
        <span v-if="!a.available && !queuedCount(a.key)" class="act-reason">
          {{ reasonText(a.reason) }}
        </span>
      </button>
    </div>

    <template #footer>
      <span class="dim" style="font-size: 12px">
        执行后按序结算并推进时间轴到我方下次可动；跨界动作允许敌方插入（战报见下方叙事日志）。
      </span>
    </template>
  </EmbeddedPanel>
</template>

<style scoped>
/* ---------- 双方 ---------- */
.sides { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
@media (max-width: 1100px) { .sides { grid-template-columns: 1fr; } }
.side { background: var(--panel3); border: 1px solid var(--line); border-radius: 8px; padding: 7px 9px; }
.side-name { display: flex; justify-content: space-between; gap: 8px; margin-bottom: 5px; flex-wrap: wrap; }
.enemy-name { color: var(--red); }
.row-line { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.lbl { width: 30px; font-size: 12px; color: var(--ink-dim); }
.num { width: 92px; text-align: right; font-size: 12px; }
.effects { display: flex; gap: 5px; flex-wrap: wrap; font-size: 11.5px; min-height: 17px; }
.fx { border-radius: 10px; padding: 0 7px; border: 1px solid var(--line); }
.fx-buff { background: #1d3328; border-color: var(--green); color: #bfe8c9; }
.fx-debuff { background: #3a2430; border-color: var(--red); color: #ffc8c4; }

/* ---------- 时间轴 ---------- */
.timeline { margin: 10px 0 8px; }
.tl-head, .tl-foot { display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 3px; }
.tl-foot { margin-top: 3px; gap: 12px; flex-wrap: wrap; }
.tl-track {
  position: relative;
  height: 32px;
  background: #0b1020;
  border: 1px solid var(--line);
  border-radius: 6px;
  overflow: hidden;
}
.tl-window {
  position: absolute;
  top: 0;
  bottom: 0;
  background: rgba(121, 169, 255, .10);
  border-right: 1px dashed rgba(121, 169, 255, .5);
}
/* 队列条：前摇暖金 + 后摇冷蓝（同一根条按落地时刻切开） */
.tl-act {
  position: absolute;
  top: 5px;
  height: 21px;
  border-radius: 4px;
  overflow: hidden;
  display: flex;
  box-shadow: 0 0 0 1px rgba(111, 157, 255, .55);
}
.tl-wind { background: linear-gradient(180deg, #c08a34, #8a6220); }
.tl-rec { background: linear-gradient(180deg, #4a7bd8, #2c4a7a); }
.tl-act-name {
  position: absolute;
  inset: 0;
  padding: 0 4px;
  font-size: 11px;
  line-height: 21px;
  color: #eaf1ff;
  text-shadow: 0 1px 2px #000;
  pointer-events: none;
}
.tl-mark {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 16px;
  margin-left: -8px;
  text-align: center;
  font-size: 10px;
  font-weight: 700;
  line-height: 32px;
  color: #0b1020;
  border-radius: 3px;
}
.tl-mark.player { background: var(--green); }
.tl-mark.enemy { background: var(--red); }

/* ---------- 常用动作 ---------- */
.cmd-row { display: flex; gap: 7px; flex-wrap: wrap; align-items: stretch; }
.act {
  display: flex;
  flex-direction: column;
  gap: 1px;
  text-align: left;
  background: var(--panel2);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 5px 9px;
  cursor: pointer;
  color: var(--ink);
  min-width: 104px;
}
.act:hover:not(:disabled) { border-color: var(--gold); }
.act.na { opacity: .5; cursor: not-allowed; }
.act-name { font-size: 13px; }
.act-meta { font-size: 10.5px; color: var(--ink-dim); }
.act-reason { font-size: 11px; color: var(--red); }
.exec { min-width: 132px; }

/* ---------- 技能折叠 ---------- */
.skills-head { display: flex; align-items: center; gap: 10px; margin: 9px 0 5px; }
.skills { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 6px; }

/* ---------- 队列 ---------- */
.queue { display: flex; flex-direction: column; gap: 3px; font-size: 12.5px; margin-top: 9px; }
.q-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
/* 前摇=暖色（等待落地，易被打断）｜后摇=冷色（冷却） */
.wind { color: var(--gold); }
.rec { color: #79a9ff; }
.act.queued { border-color: var(--gold); box-shadow: inset 0 0 0 1px rgba(216, 178, 106, .35); }
.q-badge { font-size: 10px; color: var(--gold); margin-left: 5px; }
.q-no {
  width: 15px;
  text-align: center;
  color: var(--ink-dim);
  font-size: 11px;
}
.q-x { margin-left: auto; color: var(--ink-dim); font-weight: 700; }
.q-item { cursor: pointer; }
.q-item:hover { border-color: var(--gold); }
.q-item:hover .q-x { color: var(--gold); }
.q-item {
  background: var(--panel3);
  border: 1px solid var(--line);
  border-radius: 5px;
  padding: 3px 8px;
  display: flex;
  gap: 8px;
  align-items: baseline;
}
</style>
