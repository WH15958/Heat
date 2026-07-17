# 微波仪接入任务索引

本文是 `MKM-AH1E环形聚焦单模微波化学合成仪` 接入 Heat 的拆分索引。每个新对话窗口只处理一个编号目标，先读本文件，再读当前目标文件。

## 当前状态

- 分支：`feature/automation-valve-microwave`
- 资料来源：
  - `docs/device_materials/MKM-AH1E环形聚焦单模微波化学合成仪-说明书.doc`
  - `docs/device_materials/微波反应仪通信协议.md`（由 `26.6.10-单模modbus地址.xlsx` 转换并校验一致）
  - 当前代码：`src/devices/`、`src/protocols/`、`src/web/`、`src/experiment/`、`frontend/src/`
- 全局状态：01-06 的软件接入、前端控制和 YAML 自动化已完成；真实硬件 smoke test 尚待实验室完整确认。

## 全局安全规则

- 微波仪是硬件邻近、高压、加热、微波释放设备，不按普通 Web 功能处理。
- 不在 `src/devices/` 内加入后台线程、轮询、心跳或命令队列。
- 设备驱动保持同步阻塞；FastAPI 侧只用 `run_in_executor` 桥接。
- 任何设备方法返回 `False`、超时或通信失败，都必须向上传递为失败。
- 不让 WebSocket 连接或断开启动、停止或改变硬件状态。
- 按 2026-06-20 用户确认，前端手动按钮、REST 路径和 YAML 自动实验可以直接配置、启动和停止微波仪，行为与加热器/蠕动泵保持一致。
- `allow_real_hardware_writes`、`enable_control_writes`、`allow_experiment_control` 字段保留用于兼容配置和状态展示，但当前不再作为控制阻断门。
- 真实启动、停机、门控联锁、故障码和运行状态仍需要实验室 smoke test 记录确认。
- 不编造文档或协议中没有的动作、状态、故障码、化学配方或实验方案。

## 通用窗口规则

每个窗口开始时：

1. 读 `docs/dev_tasks/microwave/00_index.md`。
2. 读当前编号目标文档。
3. 读 `context/PROJECT_CONTEXT.md` 和相关代码。
4. 检查工作树，保护已有用户改动。

每个窗口执行时：

- 只完成当前目标文件定义的范围。
- 不顺手做后续编号任务。
- 新增或修改的测试必须与当前目标范围匹配。
- 对 docs/rules-only 任务使用窄验证，不跑无关构建。

每个窗口结束时：

- 更新当前目标文档的“完成记录”。
- 写清楚已完成项、验证命令、遗留问题、下一窗口交接。
- 不自动 push。

## 任务顺序

| 顺序 | 文档 | 目标 | 依赖 |
| --- | --- | --- | --- |
| 1 | `01_protocol_register_map.md` | 整理协议事实、寄存器映射、安全语义 | 原始 Word/Excel |
| 2 | `02_backend_driver.md` | 实现同步驱动、协议常量、配置和设备管理基础 | 01 |
| 3 | `03_backend_api_ws.md` | 暴露 REST API、WebSocket payload、急停接入 | 02 |
| 4 | `04_frontend_control_dashboard.md` | 前端手动控制和仪表盘展示 | 03 |
| 5 | `05_experiment_yaml_automation.md` | 实验 YAML 动作和等待条件 | 02、03 |
| 6 | `06_docs_and_smoke_test.md` | 用户/开发/YAML 文档和实机 smoke test 清单 | 02-05 |

## 建议提交边界

- `01_protocol_register_map.md` 可单独提交，属于协议整理。
- `02_backend_driver.md` 建议单独提交，便于 review 驱动和测试。
- `03_backend_api_ws.md` 可与后端驱动分开提交。
- `04_frontend_control_dashboard.md` 单独提交，避免混入后端 diff。
- `05_experiment_yaml_automation.md` 单独提交，因为它改变实验语义。
- `06_docs_and_smoke_test.md` 单独提交，作为文档收口。

## 完成记录

- 2026-06-15：创建微波仪接入拆分目标文档。实际开发未开始。
- 2026-07-17：复核当前代码和 01-06 完成记录，软件接入已完成；实机确认继续按 [微波仪实机 Smoke Test](../../microwave_smoke_test.md) 执行。
