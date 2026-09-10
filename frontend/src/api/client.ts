/**
 * API 客户端：全部同源 `/api/*` 调用集中在此。
 *
 * 铁律：
 *  - 成败只看响应 `ok` + `reason`，**禁止解析 `text`**（text 只进叙事日志）；
 *  - HTTP 错误也要归一成 `{ok:false, reason}`，绝不把原始状态码抛给 UI；
 *  - 服务端 5xx 可能是 text/plain（FastAPI 默认异常响应），解析失败时给 `server_error`。
 */
import type {
  GongfaDetail,
  MarketData,
  RunMeta,
  StateData,
  StepResult,
} from "@/types/contract";

/** reason 码 → 中文提示（服务端缺码时回退显示原文码，绝不静默） */
export const REASON_TEXT: Record<string, string> = {
  ok: "成功",
  unknown_action: "未知动作",
  unknown_item: "查无此物 / 功法",
  unknown_enemy: "无此敌人",
  in_battle: "战斗中只能使用战斗指令",
  not_in_battle: "当前不在战斗中",
  not_owned: "尚未拥有该功法（先到坊市购得）",
  realm_gate: "境界未至，书文晦涩看不懂",
  not_entry: "尚未参悟入门（先闭关参悟）",
  fam_max: "已参悟至大成，无需再参悟",
  type_mismatch: "功法类型与所选槽位不符",
  slot_occupied: "槽位已被占据，先卸下再装",
  slot_invalid: "无效槽位",
  slot_empty: "该槽位为空",
  already_equipped: "该功法已在槽位中",
  dup_owned: "已拥有该功法，无需重复购买",
  not_market: "此物坊市不售",
  not_at_market: "须身处【坊市】才能看货单/购买",
  no_stones: "灵石不足",
  no_pill: "背包里没有此丹",
  pill_use_wrong: "此丹为突破丹药，不可直接服用",
  not_breakable: "修为未满，尚不可突破",
  max_realm: "已至人间顶峰，无更高境界",
  no_pill_data: "此境界突破丹药未配置",
  missing_pill: "缺少突破所需丹药",
  site_invalid: "无此地名",
  already_there: "你已在此地",
  site_unexplorable: "此地不可探索",
  need_map: "手中无舆图，不知路在何方——只能手动探路（按方向摸索）",
  route_invalid: "候选序号无效",
  no_path: "以你如今修为，此路不通",
  march_blocked: "前路被挡，只得停步（换个方向）",
  direction_invalid: "方向不明（东/西/南/北/东北/西北/东南/西南）",
  debug_disabled: "调试模式未开启（启动加 --debug）",
  debug_key: "未知调试项",
  low_qi: "灵气不足",
  skill_na: "该技能无法施放",
  unknown_skill: "无此技能",
  game_over: "身死道消，本世已终",
  no_checkpoint: "无可回溯节点",
  unknown_run: "该存档不存在",
  bad_request: "请求参数有误",
  battle_ended: "战斗已结束",
  window_open: "本轮已排满，点「执行」结算",
  queue_index: "队列序号无效（该动作已不存在）",
  server_error: "服务端异常（请查看控制台日志）",
  network_error: "连接服务端失败",
};

export function reasonText(reason: string | undefined | null): string {
  if (!reason) return "未知错误";
  return REASON_TEXT[reason] || reason;
}

/** 归一化后的 API 响应 */
export type ApiResponse<T> = ({ ok: true } & T) | { ok: false; reason: string };

interface RawResponse {
  ok?: boolean;
  reason?: string;
  [k: string]: unknown;
}

async function request<T>(
  path: string,
  method: "GET" | "POST",
  body?: unknown,
): Promise<ApiResponse<T>> {
  const opt: RequestInit = { method, headers: {} };
  if (body !== undefined) {
    (opt.headers as Record<string, string>)["Content-Type"] = "application/json";
    opt.body = JSON.stringify(body);
  }
  let resp: Response;
  try {
    resp = await fetch(path, opt);
  } catch {
    return { ok: false, reason: "network_error" };
  }
  let data: RawResponse | null = null;
  try {
    data = (await resp.json()) as RawResponse;
  } catch {
    data = null;
  }
  if (data === null) {
    // 非 JSON（例如 FastAPI 500 的 text/plain）
    return { ok: false, reason: resp.ok ? "server_error" : "server_error" };
  }
  if (data.ok === false) {
    return { ok: false, reason: String(data.reason || "server_error") };
  }
  return { ok: true, ...(data as unknown as T) };
}

// ---------- 会话级 ----------
export const api = {
  runs: () => request<{ runs: RunMeta[] }>("/api/runs", "GET"),

  newRun: (seed?: number, name?: string) =>
    request<{ run_id: string; state: StateData }>("/api/new", "POST", {
      seed: seed ?? null,
      name: name ?? "",
    }),

  load: (runId: string) =>
    request<{ run_id: string; state: StateData }>("/api/load", "POST", {
      run_id: runId,
    }),

  state: (runId: string) =>
    request<{ state: StateData }>("/api/state?run_id=" + encodeURIComponent(runId), "GET"),

  undo: (runId: string) =>
    request<{ state?: StateData }>("/api/undo", "POST", { run_id: runId }),

  step: (runId: string, action: string, kwargs: Record<string, unknown> = {}) =>
    request<StepResult>("/api/step", "POST", {
      run_id: runId,
      action,
      kwargs,
    }),
};

// ---------- 动作封装（薄，只为调用点可读） ----------
export const actions = {
  cultivate: (days: number, usePill: boolean) => ["cultivate", { days, use_pill: usePill }] as const,
  comprehend: (gongfa: string, days: number) => ["comprehend", { gongfa, days }] as const,
  breakthrough: () => ["breakthrough", {}] as const,
  agePass: (days: number) => ["age_pass", { days }] as const,
  travel: (site: string) => ["travel", { site }] as const,
  /** 执行第 N 条候选（不带 route 时只返回候选，不推进时间） */
  travelGo: (site: string, route: number) => ["travel", { site, route }] as const,
  /** 坐标目的地（地图右键"走到那里"）：不带 route = 预览候选，带 route = 执行 */
  travelToPoint: (x: number, y: number, route?: number) =>
    ["travel", route === undefined ? { x, y } : { x, y, route }] as const,
  /** 无舆图手动探路（八方向） */
  march: (direction: string) => ["march", { direction }] as const,
  explore: (site: string) => ["explore", { site }] as const,
  market: () => ["market", {}] as const,
  buy: (item: string, qty = 1) => ["buy", { item, qty }] as const,
  usePill: (item: string) => ["use_pill", { item }] as const,
  learn: (gongfa: string, slot: string) => ["learn", { gongfa, slot }] as const,
  forget: (slot: string) => ["forget", { slot }] as const,
  detail: (gongfa: string) => ["gongfa_detail", { gongfa }] as const,
  chronicle: () => ["chronicle", {}] as const,
  battleSubmit: (key: string) => ["battle_submit", { key }] as const,
  battleUnqueue: (index: number) => ["battle_unqueue", { index }] as const,
  battleClear: () => ["battle_clear", {}] as const,
  battleSkip: () => ["battle_skip", {}] as const,
};

export type MarketPayload = MarketData;
export type DetailPayload = GongfaDetail;
