# PROJECT_CONTEXT.md

> 仅供 AI / 自动化协作者使用。  
> 人类开发者优先看 `docs/developer_guide.md`，实验操作人员优先看 `docs/user_guide.md`。

最后更新：2026-06-20
版本：v3.3-microwave-direct-control

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
- `microwave.configure_manual`
- `microwave.configure_auto_power`
- `microwave.configure_constant_rate`
- `microwave.start`
- `microwave.stop`
- `wait`
- `emergency_stop`
- `log`

等待类型：

- `none`
- `duration`
- `temperature_reached`
- `pump_complete`
- `microwave_temperature_reached`
- `microwave_complete`

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
- pause 必须暂停当前等待的计时与轮询，不能让步骤在 `paused` 状态下完成
- 设备执行状态与追踪持久化状态分开记录；日志或 `samples.csv` 写入失败必须显式暴露为 `persistence_status=error`

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

### 2.6 微波仪真实控制已按用户授权开放

原因：

- MKM-AH1E 微波仪涉及高压、加热、微波输出、门控联锁、空载风险和现场看护要求
- 软件测试只能验证 fake protocol、API/WS、YAML 执行链和失败传播，不能确认真实硬件安全
- 2026-06-20 用户明确要求取消微波后端安全边界，使其像加热器 1/2 一样可通过前端按钮和自动化实验直接启动

要求：

- `allow_real_hardware_writes`、`enable_control_writes`、`allow_experiment_control` 当前默认 `true`；这些字段可继续出现在配置和状态 payload 中，但不应作为手动 REST/前端或 YAML 自动控制的阻断门
- 前端按钮和 YAML 自动实验可以调用微波 configure/start/stop；设备返回 `False`、异常或 timeout 必须表现为失败，不能包装成成功
- 页面加载、WebSocket 连接/断开和状态刷新仍不得触发任何写入、启动或停止
- 前端启动前继续做连接、状态读取、`fault_code`、功率/电流和人工确认提示；通信协议没有可靠门状态寄存器，不得伪造 `door_closed`
- 普通配置批量写入仍不得意外覆盖控制字 `40151`
- AI 不能确认设备身份、接线、接地、炉门、非空载、探头浸没、通风散热、SOP 或真实 stop 语义；这些必须由用户/实验室确认
- 实机联调按 `docs/microwave_smoke_test.md` 执行，联调结果必须由实验室回填记录

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

补充：

- 串口稳定绑定属于上层配置/启动解析逻辑；底层驱动仍然只消费最终解析出的端口名

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
- 微波仪：检查 `allow_real_hardware_writes`、`enable_control_writes`、`allow_experiment_control`、控制字写入、状态 payload 和 `docs/microwave_smoke_test.md`

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

## 8. 当前分支执行原则

- 当前长期主线是 `master`
- 当前仓库正式采用任务分支制，而不是长期 `develop` 模式
- 每个新需求应从最新 `master` 切出独立任务分支
- 任务分支合并进 `master` 后默认删除
- `develop-web` 已完成阶段使命；后续不应继续承载新需求开发
- AI 不要在 `master` 上直接展开常规开发
- AI 不要默认复用已经合并完成的旧开发分支
- 当前下一阶段计划分支名：`feature/automation-valve-microwave`

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
- 微波仪软件路径已按 2026-06-20 用户授权开放前端手动和 YAML 自动控制；真实硬件行为、门控联锁、负载安全、故障码和 stop 语义仍需要实验室 smoke test 确认

当前未决事项：

- 是否要补专门的 API 参考文档
- 微波仪真实硬件联调结果尚未回填
- 是否要继续拆分历史问题库与 AI 规则库
