"""玩家与世界状态的数据结构（纯数据，无逻辑）。"""

from dataclasses import dataclass, field, asdict, fields
from typing import Optional

import engine.settings as S

# 心魔值 0-100
# 功德/业力：正=功德 负=业力
@dataclass
class Player:
    name: str = "无名散修"
    spirit_root: str = "杂灵根"          # 资质名
    root_mult: float = 1.0               # 修炼效率倍率
    elements: dict = field(default_factory=dict)  # 五行亲和 {金:0.2,...}
    realm_idx: int = 1                   # 档号 1..25
    exp: float = 0.0                     # 当前修为（对 exp_cap 的进度）
    age_years: float = 16.0              # 年龄（岁，含小数=天数折算）
    lifespan_years: float = 0.0          # 寿元上限（岁）
    lifespan_mult: float = 1.0           # 出身寿元系数（全程保留）
    heart_demon: int = 0                 # 心魔 0-100
    karma: int = 0                       # 功德/业力（本世）
    alive: bool = True
    death_cause: str = ""
    # --- 经济与探索 ---
    spirit_stones: int = 0               # 灵石
    qi: float = 0.0                      # 当前灵气（战斗间保留；上限随境界，R3）
    inventory: dict = field(default_factory=dict)  # {丹药名: 数量}
    location: str = ""                   # 所在地点（坊市/灵脉山/...）
    # --- 功法栏（运转池雏形，P1 只开放主修位）---
    main_gongfa: Optional[int] = None    # 当前主修功法 id（40 段；None=未装备）
    # --- P3 功法深层：领悟池 / 运转池 ----
    owned_gongfa: list = field(default_factory=list)   # 领悟池：已拥有/已获（可参悟资格）
    familiarity: dict = field(default_factory=dict)    # {功法id: 熟悉度 0..FAM_MAX}
    battle_gongfa: list = field(default_factory=list)  # 运转池·战斗槽（≤BATTLE_SLOTS，None 占位空槽）
    shenfa_gongfa: list = field(default_factory=list)  # 运转池·身法槽（≤SHENFA_SLOTS）

    def realm_name(self) -> str:
        return S.REALM_NAMES[self.realm_idx - 1]

    def exp_cap(self) -> int:
        return S.exp_cap(self.realm_idx)

    def lifespan_left_years(self) -> float:
        return max(0.0, round(self.lifespan_years - self.age_years, 1))

    # --- 经济便捷方法 ---
    def add_stones(self, n: int):
        self.spirit_stones += int(n)

    def spend_stones(self, n: int) -> bool:
        if self.spirit_stones < n:
            return False
        self.spirit_stones -= int(n)
        return True

    def add_item(self, name: str, qty: int = 1):
        self.inventory[name] = self.inventory.get(name, 0) + int(qty)

    def remove_item(self, name: str, qty: int = 1) -> bool:
        if self.inventory.get(name, 0) < qty:
            return False
        self.inventory[name] -= qty
        if self.inventory[name] <= 0:
            del self.inventory[name]
        return True

    def item_count(self, name: str) -> int:
        return self.inventory.get(name, 0)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Player":
        # 兼容旧存档：只取本类存在的字段，缺省用默认值
        valid = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in valid})


@dataclass
class Chronicle:
    """本世大事记（可回看的编年史）。"""
    entries: list = field(default_factory=list)  # [(age, text), ...]

    def add(self, age: float, text: str):
        self.entries.append((round(age, 1), text))

    def to_dict(self) -> dict:
        return {"entries": self.entries}

    @classmethod
    def from_dict(cls, d: dict) -> "Chronicle":
        c = cls()
        c.entries = list(d.get("entries", []))
        return c


@dataclass
class GameState:
    """一局（一世）完整状态。"""
    seed: int = 0
    rng_counter: int = 0
    day: int = 0                       # 已过天数（用于计算年龄）
    player: Player = field(default_factory=Player)
    chronicle: Chronicle = field(default_factory=Chronicle)
    turn: int = 0                      # 玩家操作次数

    def age_days_to_years(self, days: int) -> float:
        return days / S.DAYS_PER_YEAR

    def to_dict(self) -> dict:
        return {
            "seed": self.seed,
            "rng_counter": self.rng_counter,
            "day": self.day,
            "player": self.player.to_dict(),
            "chronicle": self.chronicle.to_dict(),
            "turn": self.turn,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "GameState":
        gs = cls()
        gs.seed = d["seed"]
        gs.rng_counter = d["rng_counter"]
        gs.day = d["day"]
        gs.player = Player.from_dict(d["player"])
        gs.chronicle = Chronicle.from_dict(d["chronicle"])
        gs.turn = d.get("turn", 0)
        return gs
