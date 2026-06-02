# PROJECT_CONTEXT.md

> 仅供 AI / 自动化协作者使用。  
> 人类开发者优先看 `docs/developer_guide.md`，实验操作人员优先看 `docs/user_guide.md`。

最后更新：2026-06-01  
版本：v3.0-doc-reorg

---

## 你现在应该看什么

- 你是 AI：继续读完本文件，再动代码
- 你是人类开发者：转 [docs/developer_guide.md](../docs/developer_guide.md)
- 你是实验使用者：转 [docs/user_guide.md](../docs/user_guide.md)

---

## 1. 项目事实

### 1.1 项目定位

- 项目名称：Heat
- 领域：实验室 / 小型工业自动化控制
- 目标：统一管理加热器、蠕动泵、实验流程、实时监控、日志与样品记录
- 当前主运行方式：FastAPI + Vue Web 界面
- 辅助运行方式：`src/main.py` 中的本地控制入口仍存在，但不是主协作路径

### 1.2 当前真实技术栈

- Python 3.10
- FastAPI
- Vue 3 + Vite + Element Plus
- pyserial
- YAML 实验定义
- AIBUS / MODBUS RTU

### 1.3 当前真实路由与接口

- 前端页面路由：
  - `/`
  - `/control`
  - `/experiment`
  - `/history`
- 设备接口前缀：`/api`
- 实验接口前缀：`/api/experiments`
- WebSocket：`/ws`

### 1.4 当前实验动作与等待类型

动作类型：

- `heater.set_temperature`
- `heater.start`
- `heater.stop`
- `pump.start`
- `pump.stop`
- `pump.stop_channel`
- `wait`
- `emergency_stop`
- `log`

等待类型：

- `none`
- `duration`
- `temperature_reached`
- `pump_complete`

不要在文档或代码里编造当前不存在的动作名。

---

## 2. 不可破坏的系统不变量

这些不是“建议”，而是 AI 不能破坏的硬约束。

### 2.1 串口驱动必须纯同步、无线程

原因：

- 串口是半双工、请求-响应模型
- 并发访问会导致帧错乱、超时、状态不一致

要求：

- `src/devices/` 内禁止引入后台线程来做轮询、心跳、命令队列
- 设备方法保持同步阻塞
- 异步桥接只能在 Web / 上层调度层做

### 2.2 Web 层只能桥接，不应改写设备语义

原因：

- FastAPI 是异步框架，设备层是同步硬件控制
- Web 层的职责是 `run_in_executor` 桥接，而不是替设备“猜成功”

要求：

- 不要在 Web 层把失败吞掉伪装成成功
- 不要让 WebSocket 生命周期影响硬件生命周期
- 不要把 UI 便利性放在设备安全前面

### 2.3 引擎状态、日志状态、真实设备副作用必须一致

原因：

- 这是工业控制项目，报告“成功”但设备实际没执行，比直接失败更危险

要求：

- 设备返回 `False` 必须视为失败，而不是静默继续
- stop / pause / resume / complete 的状态机语义必须和日志语义一致
- 长时间等待必须可中断

### 2.4 串口与资源访问必须经过统一管理

要求：

- 串口获取和释放遵守 `SerialPortManager`
- 不要绕开已有资源锁做“临时直连”
- 不要引入第二套资源协调逻辑

### 2.5 运行产物不进版本控制

当前约定：

- `output/` 为运行和测试产物
- `src/web/static/` 为前端构建产物
- 文档里可描述这些目录的作用，但不要把它们当源码修改目标

---

## 3. AI 的唯一职责边界

AI 在这个仓库里应做的是：

- 读取当前代码和文档，理解真实实现
- 在不破坏硬约束的前提下修 bug、补测试、同步文档
- 主动发现文档与代码不一致的地方
- 把验证路径讲清楚

AI 不应做的是：

- 凭经验扩展出当前不存在的系统能力
- 把同步设备层“现代化”为驱动内异步/多线程
- 在没有代码证据的情况下改文档事实
- 忽略返回值、吞异常、弱化停止语义来换取“看起来流畅”

---

## 4. 修改前必查清单

每次修改前，AI 至少确认以下事实：

1. 当前真实路由、接口前缀、动作名、状态名是否与文档一致
2. 修改点是否触及设备同步模型、stop 语义、日志语义、样品记录链路
3. 是否需要同步以下文档之一：
   - `README.md`
   - `context/PROJECT_CONTEXT.md`
   - `docs/user_guide.md`
   - `docs/developer_guide.md`
   - 专题文档
4. 是否会产生运行产物，需要清理或忽略
5. 是否已有测试覆盖；如果没有，是否应该补测试

---

## 5. 文档同步规则

### 5.1 什么时候必须改文档

以下情况必须同步文档：

- 页面路由变化
- API 路径或请求体变化
- 实验动作 / 等待类型变化
- stop / pause / resume / wait / log 等行为语义变化
- 样品记录 / metadata / `sample_id` 逻辑变化
- merge / 测试 / 产物处理流程变化

### 5.2 文档主来源分工

- 项目入口与导航：`README.md`
- AI 规则、硬约束、历史问题：`PROJECT_CONTEXT.md`
- 用户操作和行为语义：`docs/user_guide.md`
- 开发架构与维护流程：`docs/developer_guide.md`
- YAML 规范：`docs/experiment_yaml_spec.md`
- 测试与合并流程：`docs/testing_and_merge_flow.md`
- 故障排查：`docs/troubleshooting.md`

同一规则只保留一个主来源，其他文档只做摘要和链接。

---

## 6. 合并前最小验证要求

软件层最小验证：

- `python tests\test_metadata.py`
- `python -c "import src.web.app; import src.web.api.experiments; import src.web.api.ws"`
- `cd frontend && npm run build`

如果改动触及以下区域，必须特别关注：

- `engine.py` / `executor.py`：检查 stop、wait、失败路径
- `api/ws.py`：检查 WebSocket 生命周期是否影响设备
- `parser.py` / YAML：检查动作名、字段名、文件名约束
- 样品记录：检查 `metadata -> sample_id -> samples.csv`

实机验证不是每次都必须做，但如果改动触及真实设备控制时序、协议写入顺序、串口管理，软件验证不足以替代实机验证。

---

## 7. 遇到关键问题时的排查路径

### 7.1 stop 不生效或停止慢

优先检查：

- `ExperimentEngine.stop()`
- `StepExecutor._wait_condition()`
- 是否仍有长 `sleep()` 无中断检查
- 是否在 stop 之前提前清理了引擎对象

### 7.2 wait 超时后系统却继续运行

优先检查：

- `_wait_condition()` 是否把 timeout 当成 `False`
- `execute()` 是否检查等待结果
- `engine._run()` 是否把失败分支和 stop 分支区分清楚

### 7.3 WebSocket 断开影响设备

优先检查：

- `src/web/api/ws.py` 中 websocket 断开路径
- 是否有 `finally` 中的停机逻辑
- 是否把“页面断开”错误地当成“设备应停止”

### 7.4 设备命令失败但日志显示成功

优先检查：

- executor 是否检查设备方法布尔返回值
- Web 层是否吞掉异常或忽略失败
- step 日志和 run 日志是否被错误写入 completed

### 7.5 metadata / sample_id 异常

优先检查：

- `src/science/sample_id.py`
- `src/science/sample_record.py`
- `src/experiment/experiment_logger.py`
- YAML metadata 字段是否与当前规范一致

---

## 8. 历史问题摘要

只保留对后续 AI 仍有指导意义的问题，不保留流水账。

### 8.1 metadata / sample_id 相关

- metadata 不能为空时要防御性拷贝
- `sample_index` 可能来自 YAML/前端，类型不可信，可能是 `str` / `int` / `None`
- `sample_id` 必须做唯一性处理，不能假设调用方传入值总是安全

### 8.2 stop / wait / WebSocket 相关

- stop 如果不能中断等待步骤，会造成极差的控制体验
- 设备返回值如果被忽略，会造成“表面成功、实际失败”
- WebSocket 生命周期不能控制设备生命周期
- 引擎清理应有唯一入口，避免 stop 路径和回调路径双重清理

---

## 9. 当前系统边界与未决事项

当前已知边界：

- 主流程文档化较完整，但仍依赖人对硬件场景的理解
- 测试以软件层为主，硬件 smoke test 仍需人工执行
- `src/main.py` 仍存在，但主线协作应以 Web 体系为准

当前未决事项：

- 是否要补专门的 API 参考文档
- 是否要为真实硬件联调补更明确的 smoke test 清单
- 是否要继续拆分历史问题库与 AI 规则库
