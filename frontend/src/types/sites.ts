/**
 * 地点元信息（**镜像 `content/sites.py`**）。
 *
 * ⚠️ 技术债：服务端 `/api` 目前不下发地点清单（`state.location` 只给当前地点 id/name），
 * 因此前端只能镜像这份静态表来做「地图」界面的展示与门槛提示。
 * 引擎改动（在 `_status_data()` 里补 `sites` 字段）后应删除本文件——
 * 届时地图界面的数据源改为 `state.sites`。
 *
 * 判定仍以服务端为准：这里的 realm_req 只用于**提示**（低于门槛时警告危险翻倍、心魔+5）。
 */
export interface SiteMeta {
  id: number;
  name: string;
  desc: string;
  realmReq: number;
  daysCost: number;
  danger: number;
  explorable: boolean;
}

export const SITES: SiteMeta[] = [
  {
    id: 1000000,
    name: "坊市",
    desc: "修士云集，丹药功法皆可购得。",
    realmReq: 1,
    daysCost: 0,
    danger: 0,
    explorable: false,
  },
  {
    id: 1000001,
    name: "灵脉山",
    desc: "山中灵脉隐现，可采灵石，偶有妖兽窥视。",
    realmReq: 1,
    daysCost: 20,
    danger: 0.08,
    explorable: true,
  },
  {
    id: 1000002,
    name: "幽谷秘境",
    desc: "谷中常年迷雾，灵草遍地，但深处凶险莫测。",
    realmReq: 10,
    daysCost: 40,
    danger: 0.18,
    explorable: true,
  },
  {
    id: 1000003,
    name: "古战场遗迹",
    desc: "上古修士陨落之地，遗宝与杀机并存。",
    realmReq: 14,
    daysCost: 60,
    danger: 0.25,
    explorable: true,
  },
  {
    id: 1000004,
    name: "上古洞府",
    desc: "疑似化神大能坐化之所，机缘与死劫一线之隔。",
    realmReq: 18,
    daysCost: 90,
    danger: 0.35,
    explorable: true,
  },
];
