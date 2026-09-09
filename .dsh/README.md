# .dsh —— 开发辅助脚本（非游戏代码）

- `patch.py`：带校验的文本补丁器。用法：

  ```powershell
  python .dsh/patch.py <目标文件> <old片段文件> <new片段文件> [出现次数]
  ```

  old/new 片段用 here-string 写到临时文件（多行代码零转义），工具会做 CRLF 归一、
  校验出现次数，失败时打印片段头部并**不写盘**。用于跨多文件、精确匹配易出错的编辑。