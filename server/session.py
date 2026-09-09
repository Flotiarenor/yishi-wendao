"""会话层：GameSession + RunManager（Web 壳的核心）。

规则：
  - RISKY_ACTIONS（消耗时间/资源的动作）：执行前 g.save_checkpoint() → 落盘 .cp.json
    → 执行动作 → 落盘 run_<seed>.json；
  - 其它动作：执行 → 落盘 run_<seed>.json（每步都落盘）。
  - undo：g.load_checkpoint() 回退到上一节点；失败返回 (False, None)。

并发：每个 run 一把 threading.Lock，所有引擎调用都必须在锁内（引擎非线程安全）。

存档 I/O 用 `server/savefile.py`（write/read/list_saves/save_path），不改其文件格式；
save_dir 参数用于注入自定义存档目录（测试用临时目录、服务配置），None = 项目 saves/。
（CLI 已于 R3.4 下线，存档 I/O 由 cli/ 迁至 server/。）

服务层错误码（**不属于引擎 R_* 枚举**，只在 server 层使用）：
  unknown_run    run_id 不存在
  bad_request    参数缺失/类型错
  no_checkpoint  无可回溯节点（undo）
"""
import os
import random
import threading

from server import savefile as sv
from engine import settings as S
from engine.game import Game, Result

# 消耗时间/资源的动作先存节点
RISKY_ACTIONS = frozenset({
    "cultivate", "breakthrough", "age_pass", "travel",
    "explore", "buy", "use_pill", "comprehend",
})


class GameSession:
    """一个 run 的会话封装：Game + per-run 锁 + checkpoint/autosave 规则。"""

    def __init__(self, seed: int, name: str = "", load: dict = None,
                 save_dir: str = None):
        self.save_dir = save_dir          # None = cli.savefile.SAVE_DIR（项目 saves/）
        self.lock = threading.Lock()      # 所有引擎调用必须在 with self.lock 内
        self.g = Game(seed=seed, name=name, load=load)
        if load is None:
            # 新局即落盘初始档（等价 CLI 结束必存档）：run_<seed>.json 立刻存在，
            # /api/runs 重启扫描与"重启续玩"才能看到这一世。
            self._persist()

    # ---------- 属性 ----------
    @property
    def run_id(self) -> str:
        return str(self.g.seed)

    # ---------- 落盘 ----------
    def _persist(self, checkpoint: bool = False):
        sv.write(self.g.seed, self.g.snapshot(),
                 checkpoint=checkpoint, save_dir=self.save_dir)

    def _saved_at(self) -> float:
        p = sv.save_path(self.g.seed, save_dir=self.save_dir)
        try:
            return os.path.getmtime(p)
        except OSError:
            return 0.0

    # ---------- 动作 ----------
    def step(self, action: str, **kw) -> Result:
        """risky 动作先存节点再执行；每步都落盘。线程安全。"""
        with self.lock:
            return self._step_locked(action, **kw)

    def _step_locked(self, action: str, **kw) -> Result:
        if action in RISKY_ACTIONS:
            self.g.save_checkpoint()
            self._persist(checkpoint=True)   # 行动前节点（与 CLI risky() 顺序一致）
        r = self.g.step(action, **kw)
        self._persist()
        return r

    def step_with_state(self, action: str, **kw):
        """单把锁内执行一步并返回 (Result, 最新状态快照)。

        /api/step 用：响应里的 state 与 Result 原子一致，避免并发请求间
        state() 单独取锁读到"更新的一步"造成错位。
        """
        with self.lock:
            r = self._step_locked(action, **kw)
            return r, self.g.state_data()

    def undo(self) -> tuple:
        """回溯到上一节点（同 CLI load_checkpoint 语义）。失败返回 (False, None)。"""
        with self.lock:
            if not self.g.load_checkpoint():
                return False, None
            self._persist()
            return True, None

    def state(self) -> dict:
        """只读状态快照（g.state_data()，不推进 turn/不耗随机/不落盘）。"""
        with self.lock:
            return self.g.state_data()

    def meta(self) -> dict:
        """run 元信息（/api/runs 列表项）。"""
        with self.lock:
            p = self.g.state.player
            return {
                "run_id": self.run_id,
                "seed": self.g.seed,
                "realm_name": p.realm_name(),
                "realm_idx": p.realm_idx,
                "age_years": p.age_years,
                "alive": p.alive,
                "day": self.g.state.day,
                "saved_at": self._saved_at(),
            }


class RunManager:
    """会话注册表：run_id(=str(seed)) → GameSession；新局/续玩/列表/释放。

    save_dir: 存档目录（None = cli.savefile.SAVE_DIR）。同目录下 run_<seed>.json
    与 CLI 存档互通（同一档 CLI/Web 皆可续玩）。
    """

    def __init__(self, save_dir: str = None):
        self.save_dir = save_dir
        self._runs: dict = {}
        self._lock = threading.Lock()

    def new(self, seed: int = None, name: str = "") -> GameSession:
        """开新局（覆盖同 seed 旧档，同 CLI --seed 语义）；seed 缺省随机。"""
        if seed is None:
            seed = random.randint(0, 0xFFFFFFFF)
        seed = int(seed)
        with self._lock:
            sess = GameSession(seed=seed, name=name, save_dir=self.save_dir)
            self._runs[sess.run_id] = sess
            return sess

    def load(self, run_id: str) -> GameSession:
        """续玩：内存命中则复用；否则从存档目录读档恢复。无档返回 None。"""
        with self._lock:
            sess = self._runs.get(run_id)
            if sess is not None:
                return sess
            try:
                seed = int(run_id)
            except (TypeError, ValueError):
                return None
            data = sv.read(seed, save_dir=self.save_dir)
            if data is None:
                return None
            sess = GameSession(seed=seed, load=data, save_dir=self.save_dir)
            self._runs[run_id] = sess
            return sess

    def get(self, run_id: str) -> GameSession:
        """仅内存注册表查询（不读盘）；未命中返回 None。"""
        with self._lock:
            return self._runs.get(run_id)

    def list_runs(self) -> list:
        """扫描存档目录（跳过 .cp.json）生成 run meta 列表（按 seed 升序）。"""
        from engine import settings as _S
        out = []
        for fn in sv.list_saves(save_dir=self.save_dir):
            if not fn.startswith("run_") or not fn.endswith(".json") or ".cp." in fn:
                continue
            seed_s = fn[len("run_"):-len(".json")]
            try:
                seed = int(seed_s)
            except ValueError:
                continue
            data = sv.read(seed, save_dir=self.save_dir)
            if data is None:
                continue
            pl = data.get("player") or {}
            ridx = pl.get("realm_idx", 1)
            realm_name = "?"
            if isinstance(ridx, int) and 1 <= ridx <= len(_S.REALM_NAMES):
                realm_name = _S.REALM_NAMES[ridx - 1]
            p = sv.save_path(seed, save_dir=self.save_dir)
            saved_at = os.path.getmtime(p) if os.path.exists(p) else 0.0
            out.append({
                "run_id": str(seed), "seed": seed,
                "realm_name": realm_name, "realm_idx": ridx,
                "age_years": pl.get("age_years", 0),
                "alive": pl.get("alive", True),
                "day": data.get("day", 0),
                "saved_at": saved_at,
            })
        out.sort(key=lambda m: m["seed"])
        return out
