"""确定性随机流：固定种子 + 游标计数。

核心思想：每次取随机数 = 对 (seed, salt, counter) 做哈希派生。
存档只记 counter；回溯 = 游标回卷 → 不改选择结果必复现，改选择自然不同。
"""

import hashlib

_U64 = (1 << 64) - 1


class Rng:
    def __init__(self, seed: int):
        self.seed = int(seed) & 0xFFFFFFFF
        self.counter = 0

    def _derive(self, salt: str) -> float:
        h = hashlib.blake2b(
            f"{self.seed}:{salt}:{self.counter}".encode("utf-8"),
            digest_size=8,
        ).digest()
        self.counter += 1
        return int.from_bytes(h, "big") / (1 << 64)

    def roll(self, salt: str = "") -> float:
        """[0,1) 均匀随机。"""
        return self._derive(salt)

    def randint(self, lo: int, hi: int, salt: str = "") -> int:
        return lo + int(self._derive(salt) * (hi - lo + 1))

    def chance(self, p: float, salt: str = "") -> bool:
        """以概率 p 命中。p 应已含一切修正。"""
        return self._derive(salt) < p

    def choice(self, seq, salt: str = ""):
        if not seq:
            raise ValueError("choice from empty seq")
        return seq[self.randint(0, len(seq) - 1, salt)]

    def weighted_choice(self, items: dict, salt: str = ""):
        """items: {key: weight}"""
        total = sum(items.values())
        if total <= 0:
            keys = list(items)
            return keys[self.randint(0, len(keys) - 1, salt)] if keys else None
        r = self._derive(salt) * total
        acc = 0.0
        for k, w in items.items():
            acc += w
            if r <= acc:
                return k
        return list(items)[-1]

    def save(self) -> int:
        return self.counter

    def restore(self, counter: int):
        self.counter = int(counter)
