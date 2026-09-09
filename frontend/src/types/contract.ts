/**
 * 服务端契约类型（唯一来源：engine/game.py `_status_data()` / `engine/battle.py Battle.state()`
 * / `_market_data()` / `_gongfa_detail_data()`，以及 server/app.py 的响应封装）。
 *
 * 铁律（P3.6 起）：前端**只按 `ok/reason` 判成败**，`text/lines` 仅进叙事日志。
 */

// ---------- 通用 ----------
export interface ApiError {
  ok: false;
  reason: string;
}

/** 引擎动作结果（server/app.py `_result_payload`） */
export interface StepResult {
  ok: boolean;
  reason: string;
  data: Record<string, unknown>;
  text: string;
  lines: string[];
  game_over: boolean;
  died: boolean;
  battle_started: boolean;
  /** "" | "win" | "lose" | "fled" */
  battle_over: string;
  state?: StateData;
}

// ---------- 状态快照 ----------
export interface InventoryItem {
  id: number;
  name: string;
  qty: number;
}

export interface PoolMain {
  id: number | null;
  name: string | null;
  /** 主修加成系数（1 + cultivate_bonus），无主修时为 null */
  bonus: number | null;
}

export interface PoolSlot {
  id: number | null;
  name: string | null;
}

export interface OwnedGongfa {
  id: number;
  name: string;
  tier: number;
  tier_label: string;
  /** main | battle | shenfa */
  slot_type: string;
  slot_label: string;
  readable: boolean;
  familiarity: number;
  /** 「已入门」|「参悟中」 */
  familiarity_state: string;
  /** 槽位标识（battle1..battle4 / main / shenfa），未入池为 null */
  slot: string | null;
}

export interface LocationInfo {
  id: number;
  name: string;
}

// ---------- 战斗（engine/battle.py Battle.state()） ----------
export interface BattleEnemy {
  id: number;
  name: string;
  element: string;
  realm_idx: number;
  hp: number;
  hp_max: number;
}

export interface BattlePlayer {
  hp: number;
  hp_max: number;
  qi: number;
  qi_max: number;
  /** 回灵速率（灵气/息） */
  qi_rate: number;
  stones: number;
  speed: number;
}

export interface BattleQueueItem {
  key: string;
  name: string;
  qi_cost: number;
  /** 该动作开始时刻（厘息） */
  start_t?: number;
  /** 效果落地时刻（厘息，= 开始 + 实际前摇） */
  land_t?: number;
  /** 该动作结束时刻（厘息） */
  end_t: number;
}

export interface BattleEffect {
  key: string;
  /** 失效时刻（厘息） */
  until: number;
  stacks: number;
}

export interface BattleAction {
  key: string;
  name: string;
  /** attack | defense | utility | special */
  kind: string;
  qi_cost: number;
  tier: number;
  windup: number;
  recovery: number;
  available: boolean;
  /** 不可用原因码（available=false 时非空） */
  reason: string;
  desc: string;
}

export interface BattleState {
  /** 全局时间轴（厘息，1 息 = 100 厘息） */
  t: number;
  enemy: BattleEnemy;
  player: BattlePlayer;
  queue: BattleQueueItem[];
  /** 决策窗口长度（厘息）= 敌方下次行动前的时间 */
  window_li: number;
  enemy_next_t: number;
  player_next_t: number;
  effects: { player: BattleEffect[]; enemy: BattleEffect[] };
  ended: boolean;
  outcome: string;
  actions: BattleAction[];
}

export interface StateData {
  name: string;
  spirit_root: string;
  root_mult: number;
  cultivation_mult: number;
  elements: Record<string, number>;
  realm_idx: number;
  realm_name: string;
  exp: number;
  exp_cap: number;
  age_years: number;
  lifespan_years: number;
  lifespan_left: number;
  heart_demon: number;
  karma: number;
  alive: boolean;
  spirit_stones: number;
  location: LocationInfo;
  inventory: InventoryItem[];
  pool: {
    main: PoolMain;
    battle: PoolSlot[];
    shenfa: PoolSlot;
  };
  owned: OwnedGongfa[];
  turn: number;
  seed: number;
  battle: BattleState | null;
}

// ---------- 坊市 ----------
export interface MarketPill {
  id: number;
  name: string;
  price: number;
  /** breakthrough | other */
  kind: string;
  desc?: string;
}

export interface MarketGongfa {
  /** 是否已拥有（服务端判定，勿在前端按背包名反查） */
  owned: boolean;
  id: number;
  name: string;
  price: number;
  element: string;
  tier: number;
  tier_label: string;
  slot_type: string;
  slot_label: string;
  readable: boolean;
  /** readable=false 时为 null */
  skill_count: number | null;
  cultivate_bonus: number | null;
  permanent_bonus: number | null;
  desc: string;
}

export interface MarketData {
  pills: MarketPill[];
  gongfa: MarketGongfa[];
}

// ---------- 书库 / 功法详情 ----------
export interface GongfaSkill {
  id: number;
  key: string;
  name: string;
  element: string;
  kind: string;
  qi_cost: number;
  power: number;
  requirement: string;
  /** 熟悉度达到此值才「亮出」 */
  unlock_fam: number;
  effect_key: string | null;
  windup: number;
  recovery: number;
  tier: number;
  label: string;
  /** 是否已亮出（熟悉度达标） */
  lit: boolean;
}

export interface GongfaDetail {
  id: number;
  name: string;
  tier: number;
  tier_label: string;
  element: string;
  slot_type: string;
  slot_label: string;
  readable: boolean;
  owned: boolean;
  familiarity: number;
  familiarity_state: string;
  slot: string | null;
  cultivate_bonus: number;
  permanent_bonus: number;
  desc: string;
  skills: GongfaSkill[];
  /** 未看懂时的压缩信息 */
  library?: OwnedGongfa[];
  error?: string;
}

// ---------- 会话 ----------
export interface RunMeta {
  run_id: string;
  seed: number;
  realm_name: string;
  realm_idx: number;
  age_years: number;
  alive: boolean;
  day: number;
  saved_at: number;
}

export interface ChronicleEntry {
  age: number;
  text: string;
}
