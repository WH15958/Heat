# 06 文档同步与实机 Smoke Test

## 目标

在后端、前端、YAML 自动化任务完成后，同步用户/开发/YAML 文档，并形成微波仪实机 smoke test 清单。此任务是收口任务，不新增主要功能。

## 输入资料

- `docs/dev_tasks/microwave/00_index.md`
- `docs/dev_tasks/microwave/01_protocol_register_map.md`
- `docs/dev_tasks/microwave/02_backend_driver.md`
- `docs/dev_tasks/microwave/03_backend_api_ws.md`
- `docs/dev_tasks/microwave/04_frontend_control_dashboard.md`
- `docs/dev_tasks/microwave/05_experiment_yaml_automation.md`
- `docs/user_guide.md`
- `docs/developer_guide.md`
- `docs/experiment_yaml_spec.md`
- `context/PROJECT_CONTEXT.md`

## 允许修改

- `docs/user_guide.md`
- `docs/developer_guide.md`
- `docs/experiment_yaml_spec.md`
- `context/PROJECT_CONTEXT.md`
- 可新增 `docs/microwave_smoke_test.md`，如果内容过长不适合塞进现有文档
- 当前任务文档的完成记录

## 不做

- 不新增业务代码。
- 不改前端。
- 不改测试，除非只是补文档引用导致的极小调整。
- 不执行真实微波启动，除非用户明确确认实验室条件已经准备好。

## 文档同步范围

`docs/user_guide.md`：

- 设备控制页新增微波仪说明。
- 微波启动前确认事项。
- 状态字段含义。
- 故障码显示原则。
- 明确 WebSocket/浏览器断开不等于停止设备。

`docs/developer_guide.md`：

- 微波仪驱动结构。
- Modbus 地址换算规则。
- 控制字 bit 语义。
- 自动控制默认禁用。
- fake 测试和实机验证边界。

`docs/experiment_yaml_spec.md`：

- 新增 `microwave.configure_manual`。
- 新增 `microwave.configure_auto_power`。
- 新增 `microwave.configure_constant_rate`。
- 新增 `microwave.start`。
- 新增 `microwave.stop`。
- 新增 `microwave_temperature_reached`。
- 新增 `microwave_complete`。
- 示例必须低风险，且明确不是化学工艺建议。

`context/PROJECT_CONTEXT.md`：

- 补充长期安全边界：
  - 微波自动控制默认禁用。
  - 实验室 smoke test 通过前不得启用真实自动启动。
  - 高压、门控、空载、看护要求由用户/实验室确认。

## Smoke Test 清单

实机验证必须由用户/实验室确认，软件测试不能替代。

本窗口已将可执行清单收口到 `docs/microwave_smoke_test.md`。下列内容保留为任务目标摘要；执行时以 `docs/microwave_smoke_test.md` 的记录模板和人工确认项为准。

### 0. 准备

- 设备型号与说明书一致。
- RS485 接线确认：DB9 3=485A，8=485B。
- 设备电源、接地、炉门、散热空间符合说明书。
- 反应瓶非空载。
- 光纤探头已没入物料。
- 现场有人看护。
- 配置仍保持 `allow_experiment_control=false`，先不允许 YAML 自动启动。

### 1. 只读连接

- 配置串口：9600/8/N/1，站号 1。
- 启动后端。
- 连接 `microwave1`。
- 读取状态寄存器：
  - `40106`
  - `40107`
  - `40108`
  - `40109`-`40114`
  - `40118`/`40119`
- 验收：不会启动微波，状态可读或失败原因明确。

### 2. 地址基准确认

- 在不启动微波的前提下写入一个安全参数。
- 读回同一寄存器。
- 验收：确认 `40001 -> 0` 的换算正确。

### 3. 控制字停止验证

- 在不启动真实微波输出或由设备处于安全可停状态时验证 stop 写入。
- 验收：写 stop 不导致异常启动。

### 4. 最小启动/停止验证

仅在实验室授权后执行：

- 低功率、短时、非空载。
- UI 二次确认后启动。
- 立即停止。
- 验收：
  - start 返回成功只在设备确实进入运行时出现。
  - stop 后状态变为停止。
  - 日志不把失败伪装成成功。

### 5. YAML 自动控制验证

仅在前面全部通过后执行：

- 将目标设备配置 `allow_experiment_control=true`。
- 使用最低风险 YAML。
- 验证 configure/start/wait/stop。
- 完成后恢复默认安全配置，除非用户明确要求保留。

## 验收

运行：

```powershell
git diff --check -- docs context
```

并做目标内容审查：

- 文档没有把 smoke test 写成普通用户操作。
- 文档没有承诺 AI 可以确认硬件安全。
- 文档没有新增未经确认的化学配方或工艺建议。
- 文档没有把微波仪当成普通加热器。

## 完成记录

- 状态：2026-06-17 已完成文档收口和微波仪实机 smoke test 清单。未新增功能代码，未修改前端/测试，未执行真实设备操作。
- 已完成：
  - `docs/user_guide.md` 增加微波仪控制页说明、启动前人工确认、状态字段、WebSocket 断开边界、默认安全闸和常见拒绝原因。
  - `docs/developer_guide.md` 增加微波仪同步驱动结构、Modbus `40001 -> 0` 地址换算、`40151` 控制字 bit、API/WS payload、默认禁用、fake 测试与实机验证边界。
  - `docs/experiment_yaml_spec.md` 将 05 留下的临时微波 YAML 说明收口为正式动作、参数、等待类型和低风险结构示例，并明确示例不是化学工艺建议。
  - `context/PROJECT_CONTEXT.md` 更新当前动作/等待类型清单和长期微波安全边界：`enable_control_writes=false`、`allow_experiment_control=false` 默认关闭，实机 smoke test 通过前不得启用真实自动启动。
  - 新增 `docs/microwave_smoke_test.md`，作为实验室人工执行的微波仪实机 smoke test 清单与记录模板。
- 必须由实验室人工确认：
  - 设备型号、RS485 接线、站号、串口号、电源、接地、炉门联锁、散热空间和现场环境。
  - 反应瓶非空载、光纤探头没入物料、现场有人看护、SOP 和试剂兼容性已批准。
  - `40118`/`40119` 浮点字序、`40151` stop 写 `0` 的真实语义、真实 start/stop、故障码 bit 和运行状态判断。
  - 是否临时或长期启用 `enable_control_writes=true`、`allow_experiment_control=true`。
- 验证：
  - `git diff --check -- docs`：通过，退出码 0；仅提示部分已编辑文本下次 Git 触碰时 LF/CRLF 转换，无 whitespace error。
  - `git diff --check -- docs context`：通过，退出码 0；仅提示部分已编辑文本下次 Git 触碰时 LF/CRLF 转换，无 whitespace error。
- 遗留问题：
  - 真实硬件未连接、未写入、未 smoke test；软件文档收口不能替代实验室实机确认。
  - 微波仪实际联调结果尚未回填；通过/失败、厂家建议 stop 控制字、故障码解释和状态枚举都需实验室记录。
  - 当前 `running` 仍基于后端保守 payload，不能替代实机确认的运行状态寄存器。
- 最终交接：
  - 下一步是实验室按 `docs/microwave_smoke_test.md` 执行人工 smoke test，并把记录结果回填到该文档或追加专门联调记录。
  - smoke test 通过前，保持 `enable_control_writes=false` 和 `allow_experiment_control=false` 默认关闭。
  - 若实验室确认需要修改 stop 控制字、状态枚举、故障码解释或自动控制默认值，应另开新窗口处理代码、测试和文档同步。
