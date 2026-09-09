"""P3.6 Web 壳验收测试（✓ 脚本式，风格同 test_gongfa_deep / test_battle）。

运行：.venv\\Scripts\\python.exe -X utf8 tests\\test_server.py

分组覆盖（任务书 F1~F12）：
  A. state_data() 只读无副作用（turn 与 rng 游标不变）
  B. GameSession：new 后落盘 / risky 写 .cp.json / 非 risky 不写
  C. GameSession.step 返回结构化 Result（ok/reason/data）
  D. undo：risky 后回退状态；无节点 → (False, None)
  E. RunManager：new/load/list/get；跨实例从磁盘恢复
  F. 重启续玩：新 RunManager 读同一 run_id 状态一致
  G. 并发锁：两线程各 step N 次 → turn 增量 = 2N
  H. HTTP 冒烟（stdlib urllib + 线程内 uvicorn，不新增测试依赖）
  I. 全流程（HTTP 级）：新局→参悟→装主修→货单→买锐金典→参悟→换主修→探索遇敌→战斗至结束
  J. 未知 action → unknown_action（引擎码经 step 透传）；未知 run_id → unknown_run；缺参 → bad_request
  L. R3 战斗契约（HTTP 级）：battle_submit 入队不推进时间轴 / 连续入队 / battle_skip 结算
  M. 书库详情回归：gongfa_detail 对全部功法 ok（P3.7 修 SkillSpec.element 的 500）
  N. 静态前端：dist 伺服（资产引用 / reason 映射字面量 / 无 CDN）；未构建则返回构建提示页
  K. 引擎回归：子进程重跑 test_battle_time.py / test_gongfa_deep.py 均 0 退出

注意：所有存档走临时目录注入 save_dir，不污染真实 saves/；服务结束后关闭、无残留进程。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from content import gongfa as G  # noqa: E402
from engine import settings as S  # noqa: E402
from engine.game import Game, R_OK, R_UNKNOWN_ACTION  # noqa: E402
from server import savefile as sv  # noqa: E402

_PASS = 0
_FAIL = 0


def check(name: str, cond: bool, detail: str = ""):
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  ✓ {name} {detail}")
    else:
        _FAIL += 1
        print(f"  ✗ {name} {detail}")


def fresh_dir(tag: str) -> str:
    return tempfile.mkdtemp(prefix=f"xiuxian_{tag}_")


# ============================================================
# A. 引擎只读访问器 state_data()
# ============================================================
print("== A state_data() 只读无副作用 ==")
g = Game(seed=900001)
turn0 = g.state.turn
c0 = g.rng.save()
day0 = g.state.day
sd1 = g.state_data()
check("返回 dict 且含状态键", isinstance(sd1, dict) and "realm_name" in sd1
      and "exp" in sd1 and "pool" in sd1 and "owned" in sd1)
sd2 = g.state_data()
check("调用前后 state.turn 不变", g.state.turn == turn0 == 0)
check("调用前后 rng 游标不变", g.rng.save() == c0)
check("调用前后 day 不变 / 两次快照一致", g.state.day == day0 and sd1 == sd2)
g.step("status")
check("state_data 自身不推进 turn（对照 status 才 +1）",
      g.state.turn == 1 and g.state_data()["turn"] == 1)

# ============================================================
# B. GameSession：落盘规则
# ============================================================
print("== B GameSession 落盘规则 ==")
d_b = fresh_dir("B")
from server.session import GameSession, RunManager  # noqa: E402

s1 = GameSession(seed=1001, save_dir=d_b)
p_run = os.path.join(d_b, "run_1001.json")
p_cp = os.path.join(d_b, "run_1001.cp.json")
check("new 后 run_<seed>.json 已落盘", os.path.exists(p_run))
check("new 后无 .cp.json", not os.path.exists(p_cp))
with open(p_run, encoding="utf-8") as f:
    check("落盘内容 seed 正确", json.load(f)["seed"] == 1001)
r = s1.step("cultivate", days=1)
check("risky 动作(cultivate) 落盘 .cp.json", os.path.exists(p_cp))
check("risky 后 run json 仍存在", os.path.exists(p_run))
check("cultivate 成功且推进 turn", r.ok is True and r.reason == R_OK
      and s1.state()["turn"] == 1)
s2 = GameSession(seed=1002, save_dir=d_b)
s2.step("status")
check("非 risky(status) 不写 .cp.json",
      not os.path.exists(os.path.join(d_b, "run_1002.cp.json")))
s2.step("learn", gongfa=G.name_of(G.TUNA_JUE), slot="main")
check("learn 未入门拒（not_entry 引擎码透传）", s2.state()["pool"]["main"]["id"] is None)

# ============================================================
# C. 结构化 Result
# ============================================================
print("== C 结构化 Result ==")
s3 = GameSession(seed=1003, save_dir=d_b)
r = s3.step("comprehend", gongfa=G.name_of(G.TUNA_JUE), days=5)
check("comprehend: ok/reason/data 结构齐", r.ok is True and r.reason == R_OK
      and r.data.get("gongfa_id") == G.TUNA_JUE and r.data.get("fam_after") == S.FAM_ENTRY)
check("comprehend: entered=True 且 data 有文本外的结构化字段",
      r.data.get("entered") is True and "fam_before" in r.data)
r2 = s3.step("learn", gongfa=G.name_of(G.TUNA_JUE), slot="main")
check("learn 成功 data 含槽位信息", r2.ok is True
      and r2.data.get("slot_kind") == "main")
sd = s3.state()
check("state() 反映装备主修", sd["pool"]["main"]["id"] == G.TUNA_JUE
      and sd["owned"][0]["slot"] == "主修位")

# ============================================================
# D. undo
# ============================================================
print("== D undo ==")
s4 = GameSession(seed=1004, save_dir=d_b)
s4.g.state.player.spirit_stones = 500           # 测试免经济奔波（直接置数，仅测试）
r = s4.step("buy", item="清心丹", qty=1)
check("risky 买丹成功扣灵石", r.ok is True
      and s4.state()["spirit_stones"] == 500 - 60)
ok, res = s4.undo()
check("undo 后灵石回到节点(500)", ok is True and res is None
      and s4.state()["spirit_stones"] == 500)
check("undo 后 turn 回退", s4.state()["turn"] == 0)
# cp 文件 = undo 后的 run 文件（节点一致）
with open(os.path.join(d_b, "run_1004.cp.json"), encoding="utf-8") as f:
    cp_data = json.load(f)
with open(os.path.join(d_b, "run_1004.json"), encoding="utf-8") as f:
    run_data = json.load(f)
check("undo 后 run json 与 .cp.json 节点一致", cp_data == run_data)
s5 = GameSession(seed=1005, save_dir=d_b)
ok2, res2 = s5.undo()
check("无节点 undo → (False, None)", ok2 is False and res2 is None)

# ============================================================
# E. RunManager
# ============================================================
print("== E RunManager ==")
d_e = fresh_dir("E")
m1 = RunManager(save_dir=d_e)
sessA = m1.new(seed=2001)
check("new 注册成功 / get 命中同一对象", m1.get("2001") is sessA)
check("list_runs 含 meta", m1.list_runs()[0]["run_id"] == "2001"
      and "realm_name" in m1.list_runs()[0])
m2 = RunManager(save_dir=d_e)
sessB = m2.load("2001")
check("新 RunManager 从磁盘 load 成功", sessB is not None and sessB.run_id == "2001")
check("跨实例读档状态一致", sessB.state()["name"] == sessA.state()["name"]
      and sessB.state()["realm_idx"] == sessA.state()["realm_idx"])
check("未知 run_id load → None", m2.load("404404") is None)
check("get 未注册 → None", m2.get("404404") is None)

# ============================================================
# F. 重启续玩（走若干步 → 新 RunManager → 状态一致）
# ============================================================
print("== F 重启续玩 ==")
d_f = fresh_dir("F")
ma = RunManager(save_dir=d_f)
sa = ma.new(seed=2002)
sa.step("comprehend", gongfa=G.name_of(G.TUNA_JUE), days=5)
sa.step("learn", gongfa=G.name_of(G.TUNA_JUE), slot="main")
sa.step("cultivate", days=30)
stateA = sa.state()
mb = RunManager(save_dir=d_f)
sb = mb.load("2002")
stateB = sb.state()
check("重启后境界一致", stateB["realm_idx"] == stateA["realm_idx"])
check("重启后灵石一致", stateB["spirit_stones"] == stateA["spirit_stones"])
check("重启后修为一致(浮点近似)",
      abs(stateB["exp"] - stateA["exp"]) < 1e-6)
famA = {o["id"]: o["familiarity"] for o in stateA["owned"]}
famB = {o["id"]: o["familiarity"] for o in stateB["owned"]}
check("重启后熟悉度一致(吐纳诀入门)", famA.get(G.TUNA_JUE) == S.FAM_ENTRY
      and famB.get(G.TUNA_JUE) == famA.get(G.TUNA_JUE))
check("重启后主修一致", stateB["pool"]["main"]["id"] == G.TUNA_JUE)

# ============================================================
# G. 并发锁
# ============================================================
print("== G 并发不丢步 ==")
d_g = fresh_dir("G")
sc = GameSession(seed=2003, save_dir=d_g)
N = 25
errs = []


def worker():
    try:
        for _ in range(N):
            sc.step("status")
    except Exception as e:  # noqa: BLE001
        errs.append(e)


ts = [threading.Thread(target=worker) for _ in range(2)]
[t.start() for t in ts]
[t.join() for t in ts]
check("两线程各 step 25 次 → turn=50", sc.state()["turn"] == 50 and not errs)
with open(os.path.join(d_g, "run_2003.json"), encoding="utf-8") as f:
    jd = json.load(f)
check("落盘 turn=50 不丢步", jd["turn"] == 50 and jd["player"]["alive"] is True)

# ============================================================
# H~J. HTTP 冒烟 + 全流程 + 错误码（线程内 uvicorn + stdlib urllib）
# ============================================================
print("== H/I/J HTTP 冒烟与全流程 ==")
import uvicorn  # noqa: E402

from server.app import create_app  # noqa: E402
from server.main import parse_args as _serve_args  # noqa: E402

# 启动参数：默认端口 8044（用户偏好），--port 可覆盖
check("Web 默认端口 = 8044", _serve_args([]).port == 8044, str(_serve_args([]).port))
check("--port 可覆盖默认端口", _serve_args(["--port", "9000"]).port == 9000)


class _Http:
    def __init__(self, save_dir):
        app = create_app({"save_dir": save_dir})
        self.server = uvicorn.Server(uvicorn.Config(
            app, host="127.0.0.1", port=0, log_config=None))
        self._t = threading.Thread(target=self.server.run, daemon=True)
        self._t.start()
        guard = 0
        while not self.server.started and guard < 200:
            time.sleep(0.02)
            guard += 1
        self.base = "http://127.0.0.1:%d" % \
            self.server.servers[0].sockets[0].getsockname()[1]

    def req(self, method, path, payload=None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(
            self.base + path, data=data, method=method,
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")

    def hdr(self, path):
        """GET → (status, headers)。用于校验缓存头。"""
        req = urllib.request.Request(self.base + path, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, {k.lower(): v for k, v in r.headers.items()}
        except urllib.error.HTTPError as e:
            return e.code, {k.lower(): v for k, v in e.headers.items()}

    def j(self, method, path, payload=None):
        st, raw = self.req(method, path, payload)
        try:
            return st, json.loads(raw)
        except Exception:
            return st, None

    def close(self):
        self.server.should_exit = True
        self._t.join(timeout=15)


d_h = fresh_dir("H")
http = _Http(d_h)
try:
    # ---- H 冒烟 ----
    st, d = http.j("GET", "/health")
    check("GET /health → 200 {status:ok}", st == 200 and d == {"status": "ok"})
    st, d = http.j("GET", "/api/runs")
    check("GET /api/runs 初始为空", st == 200 and d["ok"] is True and d["runs"] == [])

    st, d = http.j("POST", "/api/new", {"seed": 3001, "name": "测试"})
    check("POST /api/new 结构正确", st == 200 and d["ok"] is True
          and d["run_id"] == "3001" and "state" in d)
    rid = "3001"
    check("new 后存档写入目录(注入 save_dir)", os.path.exists(
        os.path.join(d_h, "run_3001.json")))

    def step(action, **kw):
        return http.j("POST", "/api/step",
                      {"run_id": rid, "action": action, "kwargs": kw})[1]

    r = step("cultivate", days=5)
    check("step cultivate ok + 统一响应键齐全", r["ok"] is True and r["reason"] == "ok"
          and {"ok", "reason", "data", "text", "lines", "game_over", "died",
               "battle_started", "battle_over", "state"} <= set(r))
    check("响应 state.turn 随步进推进", r["state"]["turn"] == 1)
    r = step("comprehend", gongfa="吐纳诀", days=5)
    check("step comprehend 透传 data(fam_after=10)",
          r["ok"] is True and r["data"]["fam_after"] == S.FAM_ENTRY)
    r = step("learn", gongfa="吐纳诀", slot="main")
    check("step learn 主修装备成功", r["ok"] is True
          and r["state"]["pool"]["main"]["name"] == "吐纳诀")
    r = step("market")
    check("step market data 含丹药表/功法表",
          r["ok"] is True and "pills" in r["data"] and "gongfa" in r["data"])
    r = step("buy", item="清心丹", qty=1)
    check("买不起(开局50<60) → no_stones 引擎码透传(HTTP200)",
          r["ok"] is False and r["reason"] == "no_stones")
    st, d = http.j("GET", "/api/state?run_id=" + rid)
    check("GET /api/state 结构正确", st == 200 and d["ok"] is True
          and d["state"]["seed"] == 3001)
    # turn 轨迹：new0→c1→cw2→learn3→market4→buy失败5（risky 存节点@4）→ undo 回 4
    st, d = http.j("POST", "/api/undo", {"run_id": rid})
    check("undo ok + turn 回到节点(4)", d["ok"] is True and d["reason"] == "ok"
          and d["state"]["turn"] == 4)
    check("undo 后主修仍在(节点含 learn 效果)", d["state"]["pool"]["main"]["id"] == G.TUNA_JUE)
    st, d = http.j("GET", "/api/runs")
    check("list_runs 含本档 meta", any(m["run_id"] == "3001" for m in d["runs"]))
    st, d = http.j("POST", "/api/load", {"run_id": rid})
    check("load 同 run_id 成功且状态一致",
          st == 200 and d["ok"] is True and d["run_id"] == "3001"
          and d["state"]["pool"]["main"]["id"] == G.TUNA_JUE)

    # 第二个 run：undo 无节点（服务层 no_checkpoint）
    http.j("POST", "/api/new", {"seed": 3002})
    st, d = http.j("POST", "/api/undo", {"run_id": "3002"})
    check("无 risky 的 run undo → no_checkpoint",
          st == 200 and d["ok"] is False and d["reason"] == "no_checkpoint")

    # ---- J 错误码 ----
    st, d = http.j("POST", "/api/step",
                   {"run_id": "3001", "action": "fly"})
    check("未知 action → unknown_action(引擎码透传)", d["ok"] is False
          and d["reason"] == "unknown_action" and R_UNKNOWN_ACTION == "unknown_action")
    r = step("battle_action", cmd="attack")
    check("场外 battle_action → not_in_battle(透传不崩)",
          r["ok"] is False and r["reason"] == "not_in_battle")
    st, d = http.j("POST", "/api/load", {"run_id": "999999"})
    check("未知 run_id load → HTTP404 unknown_run", st == 404
          and d == {"ok": False, "reason": "unknown_run"})
    st, d = http.j("GET", "/api/state?run_id=555555")
    check("未知 run_id state → HTTP404 unknown_run", st == 404
          and d["reason"] == "unknown_run")
    st, d = http.j("POST", "/api/step", {"action": "status"})
    check("step 缺 run_id → 400 bad_request", st == 400 and d["reason"] == "bad_request")
    st, d = http.j("POST", "/api/step", {"run_id": "3001"})
    check("step 缺 action → 400 bad_request", st == 400 and d["reason"] == "bad_request")
    st, d = http.j("POST", "/api/load", {})
    check("load 缺 run_id → 400 bad_request", st == 400 and d["reason"] == "bad_request")

    # ---- I 全流程（HTTP 级）：新局→参悟→装主修→买锐金典→参悟→换主修→探索遇敌→战斗至结束 ----
    flow_seed = 3100
    st, d = http.j("POST", "/api/new", {"seed": flow_seed})
    fid = str(flow_seed)
    flow_ok = {"v": d["ok"] is True}

    def fstep(action, **kw):
        rj = http.j("POST", "/api/step",
                    {"run_id": fid, "action": action, "kwargs": kw})[1]
        if rj is None:
            flow_ok["v"] = False
            return None
        return rj

    def fstate():
        return http.j("GET", "/api/state?run_id=" + fid)[1]["state"]

    # 1) 参悟吐纳诀至入门 → 装主修
    r = fstep("comprehend", gongfa="吐纳诀", days=5)
    r = fstep("learn", gongfa="吐纳诀", slot="main")
    check("I-1 开局参悟吐纳诀→装主修", flow_ok["v"] and r["ok"] is True
          and r["state"]["pool"]["main"]["id"] == G.TUNA_JUE)

    bought = False
    battles_done = []       # 战斗结局记录
    saw_battle_keys = False
    guard = 0
    MAX_LOOP = 700
    while guard < MAX_LOOP:
        guard += 1
        st = fstate()
        if st is None:
            flow_ok["v"] = False
            break
        b = st["battle"]
        if b:
            rr = fstep("battle_action", cmd="attack")
            if rr is not None:
                if all(k in rr for k in ("ok", "reason", "data", "text", "lines",
                                         "game_over", "died", "battle_started",
                                         "battle_over", "state")):
                    saw_battle_keys = True
                if rr.get("battle_over"):
                    battles_done.append(rr["battle_over"])
            continue
        if not bought:
            loc = st["location"]["name"]
            if loc != "坊市":
                if st["spirit_stones"] >= 330:
                    r = fstep("travel", site="坊市")
                else:
                    r = fstep("explore", site="灵脉山")
            else:
                if st["spirit_stones"] >= 330:
                    r = fstep("buy", item="锐金典", qty=1)
                    if r is not None and r["ok"]:
                        bought = True
                        r2 = fstep("comprehend", gongfa="锐金典", days=5)
                        r3 = fstep("forget", slot="main")
                        r4 = fstep("learn", gongfa="锐金典", slot="main")
                        check("I-2 买锐金典→参悟入门→卸吐纳诀→换主修锐金典",
                              r2["ok"] is True and r2["data"]["fam_after"] == S.FAM_ENTRY
                              and r3["ok"] is True and r4["ok"] is True
                              and r4["state"]["pool"]["main"]["id"] == G.RUIJIN_DIAN)
                        if not r4["ok"]:
                            flow_ok["v"] = False
                else:
                    r = fstep("explore", site="灵脉山")
        else:
            if battles_done:
                break                       # 已打过一场完整战斗
            r = fstep("explore", site="灵脉山")
    final = fstate()
    check("I-3 探索遇敌→战斗至结束(结局∈胜/败/逃) 且 state.battle 已清空",
          bool(battles_done)
          and all(o in ("win", "lose", "fled") for o in battles_done)
          and final["battle"] is None)
    check("I-5 battle_action 响应带统一结构键", saw_battle_keys)
    check("I-4 最终状态一致：存活 + 主修锐金典 + 已购已入门",
          flow_ok["v"] and final["alive"] is True
          and final["pool"]["main"]["id"] == G.RUIJIN_DIAN
          and any(o["id"] == G.RUIJIN_DIAN and o["familiarity"] >= S.FAM_ENTRY
                  for o in final["owned"]))

    # ---- L. R3 战斗契约（HTTP 级）：入队 battle_submit → 执行 battle_skip ----
    bq_seed = 3200
    http.j("POST", "/api/new", {"seed": bq_seed})
    bqid = str(bq_seed)

    def bstep(action, **kw):
        return http.j("POST", "/api/step",
                      {"run_id": bqid, "action": action, "kwargs": kw})[1]

    battle = None
    for _ in range(60):
        st_b = http.j("GET", "/api/state?run_id=" + bqid)[1]["state"]
        if st_b["battle"]:
            battle = st_b["battle"]
            break
        bstep("explore", site="灵脉山")
    check("L-1 探索遇敌 → state.battle 含 R3 时间轴字段",
          battle is not None
          and {"t", "queue", "window_li", "enemy_next_t", "player_next_t",
               "effects", "actions"} <= set(battle or {}),
          f"keys={sorted((battle or {}).keys())}")

    if battle:
        t0 = battle["t"]
        r1 = bstep("battle_submit", key="attack")
        q = (r1 or {}).get("state", {}).get("battle", {}).get("queue", [])
        check("L-2 battle_submit 入队且不推进时间轴",
              r1 is not None and r1["ok"] is True and len(q) == 1
              and r1["state"]["battle"]["t"] == t0
              and q[0]["end_t"] > t0,
              f"queue={q}")
        r2 = bstep("battle_submit", key="attack")
        q2 = (r2 or {}).get("state", {}).get("battle", {}).get("queue", [])
        check("L-3 可连续入队（无槽位上限，队列即规划）",
              r2 is not None and r2["ok"] is True and len(q2) >= 1
              and (len(q2) == 1 or q2[1]["end_t"] > q2[0]["end_t"]),
              f"queue_len={len(q2)}")
        r3 = bstep("battle_skip")
        st3 = (r3 or {}).get("state", {}).get("battle")
        check("L-4 battle_skip 结算队列并推进时间轴",
              r3 is not None and r3["ok"] is True
              and (st3 is None or (not st3["queue"] and st3["t"] > t0)),
              f"t={None if st3 is None else st3['t']}")
        r4 = bstep("battle_submit", key="not_a_real_action")
        check("L-5 未知战斗动作 → unknown_action 透传",
              r4 is not None and r4["ok"] is False and r4["reason"] == "unknown_action")
        # 收尾：把战斗打完，避免残留（不影响后续用例，save_dir 已隔离）
        for _ in range(80):
            st_b = http.j("GET", "/api/state?run_id=" + bqid)[1]["state"]
            if not st_b["battle"]:
                break
            bstep("battle_action", cmd="attack")

    # ---- M. 书库详情回归（P3.7 修复：12 本功法全部 ok，不再 500） ----
    gd_seed = 3300
    gd_dir = d_h
    _g = Game(seed=gd_seed, name="书库")
    _g.state.player.owned_gongfa = sorted(G.GONGFA.keys())
    sv.write(gd_seed, _g.snapshot(), save_dir=gd_dir)
    gdid = str(gd_seed)
    st, d = http.j("POST", "/api/load", {"run_id": gdid})
    check("M-0 全功法存档可载入", st == 200 and d["ok"] is True)

    gd_bad = []
    for _gid, _gf in sorted(G.GONGFA.items()):
        st, dj = http.j("POST", "/api/step",
                        {"run_id": gdid, "action": "gongfa_detail",
                         "kwargs": {"gongfa": _gf.name}})
        if st != 200 or dj.get("ok") is not True:
            gd_bad.append((_gf.name, st, dj.get("reason")))
    check("M-1 gongfa_detail 对全部功法 ok（防 500 回归）",
          not gd_bad, f"失败={gd_bad}")

    st, dj = http.j("POST", "/api/step",
                    {"run_id": gdid, "action": "gongfa_detail",
                     "kwargs": {"gongfa": "吐纳诀"}})
    els = [s["element"] for s in dj["data"].get("skills", [])] if dj.get("ok") else []
    check("M-2 纯辅助功法元素兜底为「无」（不再 AttributeError）",
          st == 200 and dj["ok"] is True and els == ["无"], f"elements={els}")

    st, dj = http.j("POST", "/api/step",
                    {"run_id": gdid, "action": "gongfa_detail", "kwargs": {"gongfa": ""}})
    check("M-3 gongfa_detail 空参数 → 返回书库列表（前端书库首屏）",
          st == 200 and dj["ok"] is True and "library" in dj["data"]
          and len(dj["data"]["library"]) == len(G.GONGFA))

    # ---- 静态前端（P3.7：伺服 frontend/dist；未构建则返回构建提示页） ----
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dist_dir = os.path.join(root_dir, "frontend", "dist")
    has_dist = os.path.isfile(os.path.join(dist_dir, "index.html"))
    st, html = http.req("GET", "/")
    if has_dist:
        assets = re.findall(r'(?:src|href)="\./?(assets/[^"]+)"', html)
        check("面板 / 伺服 frontend/dist（含构建资产引用）",
              st == 200 and 'id="app"' in html and len(assets) >= 2
              and all(os.path.isfile(os.path.join(dist_dir, a)) for a in assets),
              f"assets={len(assets)}")
        js_rel = next((a for a in assets if a.endswith(".js")), None)
        st, js = http.req("GET", "/" + js_rel) if js_rel else (0, "")
        # 注意：生产构建会压缩标识符（REASON_TEXT 变量名可能被改），
        # 因此断言「reason 码 + 中文提示」这类**字面量**，而不是内部变量名。
        check("dist JS 含 reason 映射与 R3 战斗动作（禁解析 text）",
              st == 200 and "no_stones" in js and "unknown_run" in js
              and "灵石不足" in js and "battle_submit" in js and "battle_skip" in js
              and "in r.text" not in js)
        css_rel = next((a for a in assets if a.endswith(".css")), None)
        st, css = http.req("GET", "/" + css_rel) if css_rel else (0, "")
        check("dist CSS 可伺服（含 .layout）", st == 200 and "layout" in css)
        check("dist 无 CDN 外部依赖（离线可跑）",
              "http://" not in html.replace("http://www.w3.org", "")
              and "https://" not in html)
        st, h = http.hdr("/")
        check("index.html 不缓存（no-cache，重建后普通刷新即生效）",
              st == 200 and h.get("cache-control") == "no-cache",
              str(h.get("cache-control")))
        st, h = http.hdr("/" + js_rel) if js_rel else (0, {})
        check("哈希资产长缓存（immutable）",
              st == 200 and "immutable" in h.get("cache-control", ""),
              str(h.get("cache-control")))
    else:
        # dist 未构建：/ 返回构建提示页（API 不受影响），不是旧 P3.6 面板
        check("dist 未构建时 / 返回构建提示页（旧 P3.6 面板已删除）",
              st == 200 and "前端尚未构建" in html and "npm run build" in html)
        st, _ = http.req("GET", "/health")
        check("dist 未构建时 API 仍可用", st == 200)
    st, d = http.j("GET", "/api/nope")
    check("/api 未知 GET 不被 SPA fallback 吞成 HTML", st == 404)
finally:
    http.close()

# ============================================================
# K. 引擎回归（子进程）
# ============================================================
print("== K 引擎回归子进程 ==")
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
run1 = subprocess.run([sys.executable, "-X", "utf8",
                       os.path.join(root, "tests", "test_battle_time.py")],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
check("test_battle_time.py 子进程 0 退出（时间轴战斗全过）", run1.returncode == 0,
      f"退出码 {run1.returncode}")
run2 = subprocess.run([sys.executable, "-X", "utf8",
                       os.path.join(root, "tests", "test_gongfa_deep.py")],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
check("test_gongfa_deep.py 子进程 0 退出", run2.returncode == 0,
      f"退出码 {run2.returncode}")

# 清理临时目录
for _d in [d_b, d_e, d_f, d_g, d_h]:
    shutil.rmtree(_d, ignore_errors=True)

print(f"\n== 结果：{_PASS} 过 / {_FAIL} 败 ==")
sys.exit(1 if _FAIL else 0)
