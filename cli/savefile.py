"""存档管理（I/O 层，只在 CLI/会话层使用，engine 保持纯净）。

- saves/run_<seed>.json    本世当前状态
- saves/run_<seed>.cp.json 最近一个节点（回溯用）

所有函数都支持可选的 save_dir 参数（默认 = 项目 saves/ 目录）：
P3.6 起 server 会话层与测试用它注入自定义目录（如临时目录），
存档文件格式不变（不改其格式、不复制实现）。
"""
import json
import os

SAVE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "saves")


def save_path(seed: int, checkpoint: bool = False, save_dir: str = None) -> str:
    tag = ".cp" if checkpoint else ""
    base = save_dir or SAVE_DIR
    return os.path.join(base, f"run_{seed}{tag}.json")


def ensure_dir(save_dir: str = None):
    os.makedirs(save_dir or SAVE_DIR, exist_ok=True)


def write(seed: int, data: dict, checkpoint: bool = False, save_dir: str = None):
    ensure_dir(save_dir)
    with open(save_path(seed, checkpoint, save_dir), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def read(seed: int, checkpoint: bool = False, save_dir: str = None):
    p = save_path(seed, checkpoint, save_dir)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def delete(seed: int, checkpoint: bool = False, save_dir: str = None):
    p = save_path(seed, checkpoint, save_dir)
    if os.path.exists(p):
        os.remove(p)


def list_saves(save_dir: str = None):
    base = save_dir or SAVE_DIR
    ensure_dir(base)
    out = []
    for fn in sorted(os.listdir(base)):
        if fn.endswith(".json"):
            out.append(fn)
    return out
