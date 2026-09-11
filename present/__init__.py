"""表现层（present）：把世界画成图/放成声的**外层**代码。

**纪律（别破坏）**：
- `engine/` 与 `content/` 是纯规则层，**永不 import 本包**、也永不 import pygame；
- 依赖方向单向：`tools/` 与 `server/` 可以 import `present/`，反过来不行；
- 本包只做"渲染/播放"，**不含任何玩法逻辑**（不读不写 GameState）。

放这里的东西：地图底图渲染（pygame）、音频播放（后续）。
"""
