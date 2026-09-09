"""时间轴（P4-R1，战斗系统重构）：厘息整数时间推进与确定性行动序。

规格：`docs/战斗系统定案.md` §2/§3/§4。本模块**纯计算、零 I/O、零随机**——
只回答"谁在什么时候能行动"，不碰伤害/灵气/效果（那些在 rules.py / battle.py）。

单位：厘息（1 息 = 100 厘息）。**全程整数运算**，浮点只用于对外显示。
这样时间轴的比较、累加、相等判定都是精确的，不会出现"差 1e-13 导致永远排不上队"。

确定性：本模块不使用随机数。同时到达的仲裁由 `order()` 的固定规则给出
（玩家优先 → 速度高者 → 稳定 id），因此同种子 + 同操作序列必然逐位可复现。
"""

from dataclasses import dataclass

# 1 息 = 100 厘息
LI = 100

# 同时到达时的阵营优先级：数值小者先动（玩家优先 = 用户体验，且不消耗随机流）
SIDE_PLAYER = 0
SIDE_ENEMY = 1


@dataclass(frozen=True)
class Timing:
    """动作的时间成本（厘息）与速度敏感度。

    windup   : 前摇——效果何时落地；期间被打断则动作取消（见定案 §7）
    recovery : 后摇——多久之后能再行动
    windup_speed / recovery_speed : 速度敏感度。
      1.0 = 完全吃速度（除以速度）；0.0 = 完全不吃（固定耗时，如遁走/消耗灵石）。
      允许前后摇用不同比例（用户拍板："前后都缩但是比例不同"）。
    """

    windup: int = 0
    recovery: int = 200
    windup_speed: float = 1.0
    recovery_speed: float = 1.0


def _scaled(base: int, speed: float, sensitivity: float) -> int:
    """按速度缩放一段时长（厘息，向上取整，最小 0）。

    公式：base / (1 + (speed − 1) × sensitivity)
      speed=1.0 → base（不变）
      speed=2.0, sensitivity=1.0 → base/2（快一倍）
      sensitivity=0.0 → 恒为 base（不受速度影响）
    """
    if base <= 0:
        return 0
    denom = 1.0 + (float(speed) - 1.0) * float(sensitivity)
    if denom <= 0.01:          # 速度极低时的下限保护（避免除零/负时长）
        denom = 0.01
    return int(round(base / denom))


def windup_li(t: Timing, speed: float) -> int:
    """实际前摇（厘息）。"""
    return _scaled(t.windup, speed, t.windup_speed)


def recovery_li(t: Timing, speed: float) -> int:
    """实际后摇（厘息）。"""
    return _scaled(t.recovery, speed, t.recovery_speed)


def total_li(t: Timing, speed: float) -> int:
    """本次动作占用的总时长（前摇 + 后摇，厘息）。"""
    return windup_li(t, speed) + recovery_li(t, speed)


def order(cands: list) -> list:
    """确定性排序：同刻可动者按 (阵营优先级, 速度降序, key) 排列。

    cands: [{"side": SIDE_*, "speed": float, "key": hashable}, ...]
    —— 玩家永远排在前面（同时到达给玩家），其次速度高者先动，最后用 key 兜底保证
    任意输入顺序都得到同一结果（可复现）。
    """
    return sorted(cands, key=lambda c: (c["side"], -float(c["speed"]), str(c["key"])))


class Clock:
    """战斗时钟：维护全局时间 t 与各方"可动时刻" next_t。

    用法（battle.py 只消费这些查询，不自己算时间）：
      ck = Clock()
      ck.add("player", speed=1.0); ck.add("enemy", speed=0.8)
      ck.advance_to_next()        # 推进到下一个可动时刻
      ck.actor_due()              # 当前该谁动（按 order 规则）
      ck.window_li()              # 我方可用的决策窗口长度（厘息）
      ck.schedule("player", timing)  # 该动作结算后，其 next_t 推进
    """

    def __init__(self):
        self.t = 0
        self._speed: dict = {}      # key -> 速度
        self._side: dict = {}       # key -> 阵营
        self._next: dict = {}       # key -> 可动时刻

    # ---------- 注册 / 查询 ----------
    def add(self, key, speed: float, side: int, at: int = 0):
        """注册参战者（at = 初始可动时刻，默认 0 即开局即可动）。"""
        self._speed[key] = float(speed)
        self._side[key] = int(side)
        self._next[key] = int(at)

    def speed(self, key) -> float:
        return self._speed[key]

    def next_t(self, key) -> int:
        return self._next[key]

    def keys(self) -> list:
        return list(self._next)

    def set_next_t(self, key, value: int):
        """直接设置可动时刻（控制技推后 next_t 用；见定案 §7）。"""
        self._next[key] = int(value)

    def push_back(self, key, delta_li: int):
        """把某方的下次可动时刻推后（定身/晕眩/迟钝的统一实现）。"""
        self._next[key] = self._next[key] + max(0, int(delta_li))

    # ---------- 推进 ----------
    def earliest(self) -> int:
        """所有参战者中最早的可动时刻。"""
        return min(self._next.values())

    def advance_to_next(self) -> int:
        """把 t 推进到最早可动时刻（不早于当前 t）。返回推进后时间。"""
        nxt = self.earliest()
        if nxt > self.t:
            self.t = nxt
        return self.t

    def due(self) -> list:
        """当前时刻（t）已可动的参战者 key 列表，按确定性规则排序。"""
        cands = [{"side": self._side[k], "speed": self._speed[k], "key": k}
                 for k, v in self._next.items() if v <= self.t]
        return [c["key"] for c in order(cands)]

    def actor_due(self):
        """当前该行动的一方（无 → None）。"""
        d = self.due()
        return d[0] if d else None

    def window_li(self, mine, other) -> int:
        """我方的决策窗口长度 = 对手下次可动时刻 − 当前时刻（厘息，最小 0）。

        这就是"敌方触发下一段操作前，你能自由安排的时间"（定案 §4）。
        """
        return max(0, self._next[other] - self.t)

    # ---------- 结算 ----------
    def schedule(self, key, timing: Timing, speed: float = None):
        """某方完成一次动作：其可动时刻推进"实际总时长"，返回 (落地时刻, 新可动时刻)。

        speed 省略时用注册速度；传入时用**有效速度**（含迟钝等状态倍率，见 action.Actor）。
        落地时刻 = 动作开始 + 实际前摇（效果生效时点，供打断判定用）。
        """
        spd = self._speed[key] if speed is None else float(speed)
        w = windup_li(timing, spd)
        total = w + recovery_li(timing, spd)
        start = self._next[key]
        self._next[key] = start + total
        return start + w, self._next[key]

    def land_li(self, key, timing: Timing) -> int:
        """只算落地时刻（不改状态）——供"谁先落地"比较。"""
        return self._next[key] + windup_li(timing, self._speed[key])
