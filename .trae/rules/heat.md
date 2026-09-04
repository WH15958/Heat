---
alwaysApply: false
description: Heat 项目开发规则入口
---
# Heat 项目规则入口

处理 Heat 任务前先读取仓库根目录 `AGENTS.md` 和 `context/PROJECT_CONTEXT.md`。

- `AGENTS.md` 是开发、安全、验证、文档和 Git 工作流的主规则。
- `context/PROJECT_CONTEXT.md` 是当前项目事实、设备边界和历史决策的主来源。
- 本文件只用于 Trae 兼容入口，不重复维护命令、测试矩阵或硬件语义。

如果本文件与上述主来源不一致，以上述两份活动文档和当前代码为准。
