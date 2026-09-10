<script setup lang="ts">
/**
 * 地图 = 主页面（用户拍板方案 B）。
 *
 * P4-T3 重写：**不再读前端写死的地点清单**（旧的 `types/sites.ts` 那套是 P3.7 遗产，
 * 与真实世界地图无关）。数据源改为引擎下发的 `state.map`（见 `engine/game.py map_view()`）：
 *   - 世界坐标 → SVG 投影（等距圆柱，半径 `radius_li`，默认 4000 里 = 1 个域）
 *   - 城镇：名字 / 里程 / 是否到过 / 是否脚下这座
 *   - 内容点：known 才显示真名，未知显示「（未探明）」
 *   - 移动：点目的地 → 引擎给候选（最快/最安全/最隐蔽）→ 选定执行（**显示真实耗时**）
 *   - 无舆图（map_level=none）：不给候选，只给八方向「手动探路」
 */
import { computed, ref } from "vue";

import EmbeddedPanel from "@/components/EmbeddedPanel.vue";
import { useSessionStore } from "@/stores/session";
import { useUiStore } from "@/stores/ui";
import type { MapPoint, MapTown, TravelRoute } from "@/types/contract";

const s = useSessionStore();
const ui = useUiStore();

const st = computed(() => s.state);
const mv = computed(() => st.value?.map ?? null);
const curName = computed(() => st.value?.location?.name ?? "");
const mapLevel = computed(() => mv.value?.map_level ?? "none");
const hasMap = computed(() => mapLevel.value !== "none");
const detailed = computed(() => mapLevel.value === "detailed");

/** 候选路径（点目的地后引擎返回；null = 未选目的地） */
const routes = ref<TravelRoute[] | null>(null);
const routeDest = ref("");
const planning = ref(false);

const DIRS = ["北", "东北", "东", "东南", "南", "西南", "西", "西北"];

// ---------- SVG 投影 ----------
const SIZE = 560;
const PAD = 26;
const R = computed(() => mv.value?.radius_li || 4000);
const px = (x: number, y: number) => {
  const half = SIZE / 2 - PAD;
  const sx = ((x - (mv.value?.self.x ?? 0)) / R.value) * half;
  // 世界 y 向上（北），SVG y 向下 → 取负
  const sy = -((y - (mv.value?.self.y ?? 0)) / R.value) * half;
  return [SIZE / 2 + sx, SIZE / 2 + sy] as const;
};
const gridLines = computed(() => {
  const step = R.value / 4;
  const out: { d: string; label: string }[] = [];
  for (let i = -4; i <= 4; i++) {
    if (i === 0) continue;
    const off = (i * step * (SIZE / 2 - PAD)) / R.value;
    const c = SIZE / 2 + off;
    out.push({ d: `M ${c} ${PAD} L ${c} ${SIZE - PAD}`, label: `${Math.abs(i * step)}里` });
    out.push({ d: `M ${PAD} ${c} L ${SIZE - PAD} ${c}`, label: `${Math.abs(i * step)}里` });
  }
  return out;
});

// ---------- 点选 ----------
const sel = ref<{ kind: "town" | "point"; id: string } | null>(null);
const selTown = computed<MapTown | null>(() =>
  sel.value?.kind === "town" ? (mv.value?.towns.find((t) => t.id === sel.value!.id) ?? null) : null,
);
const selPoint = computed<MapPoint | null>(() =>
  sel.value?.kind === "point" ? (mv.value?.points.find((p) => p.id === sel.value!.id) ?? null) : null,
);

function pickTown(t: MapTown) {
  sel.value = { kind: "town", id: t.id };
  routes.value = null;
  routeDest.value = "";
}
function pickPoint(p: MapPoint) {
  sel.value = { kind: "point", id: p.id };
  routes.value = null;
  routeDest.value = "";
}

/** 点目的地 → 让引擎算候选（纯查询） */
async function plan(dest: string) {
  if (!s.canAct) return;
  planning.value = true;
  try {
    routes.value = await s.planTravel(dest);
    routeDest.value = dest;
    if (routes.value.length === 0) ui.notify("无路可通（或以你如今修为过不去）");
  } finally {
    planning.value = false;
  }
}

async function go(dest: string, route: number) {
  const r = await s.travelRoute(dest, route);
  if (r?.ok) {
    routes.value = null;
    sel.value = null;
  }
}

async function march(dir: string) {
  const r = await s.march(dir);
  if (r && !r.ok && r.reason === "march_blocked") {
    const d = r.data as { blocked_by?: string; li?: number };
    ui.notify(`前方【${d.blocked_by || "障碍"}】挡住去路（已走 ${Math.round(d.li || 0)} 里），换个方向`);
  }
}

async function explorePoint(p: MapPoint) {
  // 内容点暂以旧探索点通道进入（T5 会把设施与内容点正式接上）
  const r = await s.explore("灵脉山");
  if (r?.ok) sel.value = null;
  void p;
}

const kindLabel: Record<string, string> = {
  mine: "矿脉", herb: "灵草", lair: "兽巢", ruin: "遗迹",
  secret: "秘境入口", vein: "灵脉", post: "驿站",
};
const kindIcon: Record<string, string> = {
  mine: "⛏", herb: "🌿", lair: "🐾", ruin: "🏚", secret: "🌀", vein: "✨", post: "🏠",
};
</script>

<template>
  <EmbeddedPanel :title="`🗺 地图 · 当前位置【${curName}】`" :closable="false">
    <template #head>
      <span class="dim" style="font-size: 12px">
        <template v-if="!hasMap">无舆图 ｜ 只能按方向摸索（手动探路）</template>
        <template v-else>
          舆图：{{ mapLevel === "detailed" ? "详图" : "粗舆图" }} ｜
          周边 {{ Math.round(R).toLocaleString() }} 里 ｜
          神识视野 {{ Math.round(mv?.vision_li || 0) }} 里
        </template>
      </span>
    </template>

    <div class="wrap">
      <!-- ---------- 左：地图 ---------- -->
      <div class="mapbox">
        <svg :viewBox="`0 0 ${SIZE} ${SIZE}`" class="map">
          <rect x="0" y="0" :width="SIZE" :height="SIZE" class="bg" />
          <!-- 里数网格（方位参照） -->
          <g class="grid-lines">
            <path v-for="(g, i) in gridLines" :key="i" :d="g.d" />
          </g>
          <!-- 河流大势（只详图下发） -->
          <g class="rivers">
            <circle v-for="(pt, i) in mv?.rivers || []" :key="'r' + i"
                    :cx="px(pt[0], pt[1])[0]" :cy="px(pt[0], pt[1])[1]" r="1.6" />
          </g>
          <!-- 内容点 -->
          <g class="points">
            <circle v-for="p in mv?.points || []" :key="p.id"
                    :cx="px(p.x, p.y)[0]" :cy="px(p.x, p.y)[1]"
                    :r="p.known ? 4.5 : 3"
                    :class="['pt', p.known ? 'known' : 'unknown', { sel: sel?.id === p.id }]"
                    @click="pickPoint(p)" />
          </g>
          <!-- 城镇 -->
          <g class="towns">
            <g v-for="t in mv?.towns || []" :key="t.id" @click="pickTown(t)">
              <circle :cx="px(t.x, t.y)[0]" :cy="px(t.x, t.y)[1]"
                      :r="t.is_main ? 7 : 5"
                      :class="['tw', { main: t.is_main, visited: t.visited, here: t.here, sel: sel?.id === t.id }]" />
            </g>
          </g>
          <!-- 自己 -->
          <g class="me">
            <circle :cx="px(mv?.self.x || 0, mv?.self.y || 0)[0]"
                    :cy="px(mv?.self.x || 0, mv?.self.y || 0)[1]" r="6" />
          </g>
          <!-- 方位字 -->
          <text :x="SIZE / 2" :y="16" class="dir">北</text>
          <text :x="SIZE / 2" :y="SIZE - 6" class="dir">南</text>
          <text :x="10" :y="SIZE / 2" class="dir">西</text>
          <text :x="SIZE - 18" :y="SIZE / 2" class="dir">东</text>
        </svg>

        <!-- 无舆图：八方向手动探路 -->
        <div v-if="!hasMap" class="march">
          <span class="dim" style="font-size: 12px">手动探路（一次最多 300 里，遇阻挡会停下）：</span>
          <div class="dirs">
            <button v-for="d in DIRS" :key="d" class="btn mini"
                    :disabled="!s.canAct" @click="march(d)">{{ d }}</button>
          </div>
        </div>
      </div>

      <!-- ---------- 右：选中详情 / 候选路径 ---------- -->
      <div class="side">
        <p v-if="!sel" class="dim tip">
          <template v-if="!hasMap">
            你手中无舆图，山川形势一概不知。只能按方向摸索着走——走到哪里算哪里。
          </template>
          <template v-else>
            点击地图上的<span class="k tw-dot">圆点</span>（城镇）或
            <span class="k pt-dot">小点</span>（内容点）查看详情并前往。
            <template v-if="!detailed">（粗舆图只标城镇；换详图可看到灵草/矿脉/兽巢等）</template>
          </template>
        </p>

        <!-- 城镇 -->
        <div v-if="selTown" class="card">
          <div class="hd">
            <b>{{ selTown.name }}</b>
            <span v-if="selTown.here" class="tag tag-cur">脚下</span>
            <span v-else-if="selTown.visited" class="tag tag-cur">到过</span>
            <span v-if="selTown.is_main" class="tag tag-market">主城</span>
          </div>
          <div class="meta mono">
            {{ Math.round(selTown.dist_li).toLocaleString() }} 里 ｜ 影响半径 {{ Math.round(selTown.radius_li) }} 里
            <template v-if="selTown.tier"> ｜ {{ selTown.tier }}</template>
          </div>

          <div class="ops" v-if="!selTown.here">
            <button class="btn mini primary" :disabled="!s.canAct || planning"
                    @click="plan(selTown.name)">
              {{ planning ? "推演路径…" : "查看路线" }}
            </button>
          </div>

          <div v-if="routes && routeDest === selTown.name" class="routes">
            <div class="dim" style="font-size: 12px">选一条路走：</div>
            <button v-for="r in routes" :key="r.idx" class="route" :disabled="!s.canAct"
                    @click="go(selTown.name, r.idx)">
              <span class="rlabel">{{ r.label }}</span>
              <span class="rdays">{{ r.days }} 日</span>
              <span class="rmeta mono">
                {{ Math.round(r.li).toLocaleString() }} 里 ｜
                路网 {{ Math.round(r.road_share * 100) }}% ｜
                险地 {{ Math.round(r.danger_share * 100) }}%
              </span>
            </button>
          </div>
        </div>

        <!-- 内容点 -->
        <div v-if="selPoint" class="card">
          <div class="hd">
            <b>{{ kindIcon[selPoint.kind] || "📍" }} {{ selPoint.name_shown }}</b>
            <span class="tag">{{ kindLabel[selPoint.kind] || selPoint.kind }}</span>
            <span v-if="!selPoint.known" class="tag">未探明</span>
          </div>
          <div class="meta mono">
            {{ Math.round(selPoint.dist_li).toLocaleString() }} 里
            <template v-if="selPoint.known"> ｜ 五行 {{ selPoint.element }}</template>
          </div>
          <p v-if="!selPoint.known" class="dim" style="font-size: 12px; margin: 4px 0 0">
            只知此处"有这么一处"，究竟是何物，须亲身去看（或买情报）。
          </p>
          <div class="ops" v-if="selPoint.known">
            <button class="btn mini primary" :disabled="!s.canAct" @click="explorePoint(selPoint)">
              前往探索
            </button>
          </div>
        </div>

        <div v-if="hasMap" class="legend dim">
          <div><span class="k tw-dot"></span> 城镇 <span class="k tw-main"></span> 主城
            <span class="k tw-vis"></span> 到过</div>
          <div v-if="detailed">
            <span class="k pt-known"></span> 已发现 <span class="k pt-unk"></span> 未探明
            ｜ 共 {{ mv?.counts.towns }} 镇 / {{ mv?.counts.points }} 处（已知 {{ mv?.counts.known_points }}）
          </div>
          <div v-else>共 {{ mv?.counts.towns }} 镇</div>
        </div>
      </div>
    </div>
  </EmbeddedPanel>
</template>

<style scoped>
.wrap { display: grid; grid-template-columns: minmax(320px, 1fr) minmax(260px, 340px); gap: 12px; }
@media (max-width: 900px) { .wrap { grid-template-columns: 1fr; } }
.mapbox { display: flex; flex-direction: column; gap: 8px; }
.map { width: 100%; max-width: 560px; aspect-ratio: 1 / 1; background: var(--panel3); border: 1px solid var(--line); border-radius: 8px; }
.bg { fill: transparent; }
.grid-lines path { stroke: var(--line); stroke-width: .5; opacity: .5; }
.rivers circle { fill: var(--blue); opacity: .55; }
.tw { fill: var(--ink-dim); stroke: var(--panel3); stroke-width: 1.5; cursor: pointer; }
.tw.main { fill: var(--gold); }
.tw.visited { stroke: var(--gold); }
.tw.here { fill: var(--gold); stroke: #fff; stroke-width: 2; }
.tw.sel { stroke: var(--red); stroke-width: 2.5; }
.pt { cursor: pointer; }
.pt.known { fill: var(--green, #6cc07a); }
.pt.unknown { fill: var(--ink-dim); opacity: .5; }
.pt.sel { stroke: var(--red); stroke-width: 2; }
.me circle { fill: #fff; stroke: var(--gold); stroke-width: 2.5; }
.dir { fill: var(--ink-dim); font-size: 12px; text-anchor: middle; opacity: .7; }
.march { display: flex; flex-direction: column; gap: 6px; }
.dirs { display: flex; flex-wrap: wrap; gap: 5px; }
.side { display: flex; flex-direction: column; gap: 9px; min-width: 0; }
.tip { font-size: 12.5px; line-height: 1.6; margin: 0; }
.k { display: inline-block; width: 9px; height: 9px; border-radius: 50%; vertical-align: middle; }
.tw-dot { background: var(--ink-dim); }
.tw-main { background: var(--gold); }
.tw-vis { background: var(--ink-dim); box-shadow: 0 0 0 2px var(--gold); }
.pt-dot { background: #6cc07a; }
.pt-known { background: #6cc07a; }
.pt-unk { background: var(--ink-dim); opacity: .5; }
.card { background: var(--panel3); border: 1px solid var(--line); border-radius: 8px; padding: 9px 10px; display: flex; flex-direction: column; gap: 5px; }
.hd { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; }
.meta { font-size: 11.5px; color: var(--ink-dim); }
.ops { display: flex; gap: 6px; flex-wrap: wrap; }
.routes { display: flex; flex-direction: column; gap: 5px; margin-top: 3px; }
.route { display: grid; grid-template-columns: auto auto 1fr; gap: 5px 8px; align-items: baseline;
  text-align: left; background: var(--panel); border: 1px solid var(--line); border-radius: 6px;
  padding: 6px 8px; cursor: pointer; color: inherit; }
.route:hover { border-color: var(--gold); }
.route:disabled { opacity: .5; cursor: not-allowed; }
.rlabel { color: var(--gold); font-size: 12.5px; }
.rdays { font-size: 12.5px; }
.rmeta { grid-column: 1 / -1; font-size: 11px; color: var(--ink-dim); }
.legend { font-size: 11.5px; line-height: 1.9; }
.tag { font-size: 11px; border-radius: 9px; padding: 0 7px; border: 1px solid var(--line); }
.tag-cur { color: var(--gold); border-color: var(--gold); }
.tag-market { color: var(--blue); border-color: var(--blue); }
</style>
