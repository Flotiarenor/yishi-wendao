"""开发期调试开关（P4-T3 后：用户要求"能加 debug 模式拿灵石用于测试"）。

**定位**：只服务开发/联调，不参与玩法平衡，**不进存档、不改变世界生成**。
- 默认 **关闭**：`ENABLED = False`，所有调试动作直接拒（`debug_disabled`）。
- 打开方式（任选）：
  1. 命令行：`python main.py web --debug`（可选 `--stones N`）；
  2. 环境变量：`XIUXIAN_DEBUG=1`（可选 `XIUXIAN_DEBUG_STONES=N`）；
  3. 程序内：`from engine import debug; debug.enable(stones=999999)`。
- 入口在**根 `main.py`**（唯一入口），本模块只提供开关与"发资源"的纯逻辑。

⚠️ **只在开发机用**：打开后可以随意给自己发灵石 / 丹药 / 舆图，
    因此**不要**在正式发布或联机场景下开启（本项目为单机，风险仅限"自己存档变得不可比"）。
"""
from dataclasses import dataclass, field
import os

# 调试总开关（模块级；默认关）
ENABLED: bool = False

# 默认发放量：够测试全部购买/突破路径
DEFAULT_STONES = 999_999


@dataclass
class DebugConfig:
    """一次"发资源"的申请（由 `Game._debug_grant` 消费）。"""
    stones: int = DEFAULT_STONES
    pills: dict = field(default_factory=dict)     # {丹药 id: 数量}
    map_level: str = ""                           # "" = 不改；"coarse"/"detailed" = 直接给舆图
    full_fam: bool = False                        # 把已拥有功法熟悉度拉满（参悟路径测试用）


def enable(stones: int = DEFAULT_STONES) -> None:
    """打开调试模式（程序内/环境变量共用入口）。"""
    global ENABLED, _PENDING
    ENABLED = True
    _PENDING = DebugConfig(stones=int(stones)) if stones is not None else None


def disable() -> None:
    global ENABLED, _PENDING
    ENABLED = False
    _PENDING = None


# 新建局时要自动发的资源（`--debug --stones N` 走这条；一次性）
_PENDING: DebugConfig = None


def pending() -> DebugConfig:
    """取出并清空"新局自动发放"配置（消费一次即失效）。"""
    global _PENDING
    cfg, _PENDING = _PENDING, None
    return cfg


def peek_pending() -> DebugConfig:
    return _PENDING


def enabled() -> bool:
    return bool(ENABLED)


def sync_from_env() -> bool:
    """按环境变量同步开关（服务启动时调用）。返回是否开启。"""
    raw = str(os.environ.get("XIUXIAN_DEBUG", "")).strip().lower()
    if raw in ("1", "true", "yes", "on"):
        try:
            stones = int(os.environ.get("XIUXIAN_DEBUG_STONES", DEFAULT_STONES))
        except (TypeError, ValueError):
            stones = DEFAULT_STONES
        enable(stones=stones)
        return True
    return False
