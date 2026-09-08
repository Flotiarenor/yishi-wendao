"""引擎包：纯 Python 库，零 I/O、零界面依赖。

分层：settings(数值) → rng(随机流) → state(状态) → engine(行动逻辑)
界面(CLI/Web)只 import engine，负责展示与输入。
"""
