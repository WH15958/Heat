# 06 文档同步与实机 Smoke Test

> 归档提示：本文件是已完成任务记录，不代表当前实现或实机验收结论。

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
- 前端手动控制、REST 控制和 YAML 自动控制按 2026-06-20 用户确认开放。
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
  - 微波软件控制路径已开放，不再由 `allow_*` / `enable_*` 字段阻断。
  - 页面加载、WebSocket 连接/断开和状态刷新不得触发写入。
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
- 配置已按当前开放语义复核为 `allow_experiment_control=true`、`allow_real_hardware_writes=true`、`enable_control_writes=true`。

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

- 使用最低风险 YAML。
- 验证 configure/start/wait/stop。
- 记录实验日志、HMI 状态、仪表盘状态和实际设备行为。

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

### 2026-06-20 第 1 阶段只读通信验证记录

- 执行范围：仅打开串口并读取只读状态保持寄存器；未写任何寄存器，未访问控制字 `40151`，未执行 start/stop，未修改前端写入禁用逻辑，未启用 YAML 自动控制。
- 串口与站号：COM12，9600/8/N/1，Modbus RTU 站号 1。
- 结论：COM12 可打开；站号 1 响应功能码 `0x03 read_holding_registers`；第 1 阶段只读通信验证通过，未触发停止条件。
- 安全检查：
  - `40106` 电流原始值：`0`
  - `40108` 实时功率原始值：`0`
  - `40112` fault_code：`0`
  - 串口操作结束后已关闭 COM12。
- 原始请求/响应：
  - 读取 `40106`-`40114`：PDU 起始地址 `105`，数量 `9`；请求帧 `01 03 00 69 00 09 55 D0`；响应帧 `01 03 12 00 00 00 15 00 00 00 00 00 00 00 00 00 00 00 04 00 00 66 4C`。
  - 读取 `40118`/`40119`：PDU 起始地址 `117`，数量 `2`；请求帧 `01 03 00 75 00 02 D5 D1`；响应帧 `01 03 04 41 AE 00 00 8F EE`。
- 原始寄存器值：
  - `40106` = `0`
  - `40107` = `21`
  - `40108` = `0`
  - `40109` = `0`
  - `40110` = `0`
  - `40111` = `0`
  - `40112` = `0`
  - `40113` = `4`
  - `40114` = `0`
  - `40118` = `16814`
  - `40119` = `0`
- 解析状态：
  - current_raw：`0`
  - material_temperature_raw：`21`
  - power_percent_raw：`0`
  - runtime：`0:00:00`
  - fault_code：`0`
  - current_segment：`4`
  - current_mode_code：`0`
  - material_temperature_float：`21.75`，按当前软件 helper 的 ABCD / 高字在前假设解析；`40118`/`40119` 真实字序仍需后续实机确认。
- 下一步：停在第 1 阶段，等待用户确认是否进入第 2 阶段。第 2 阶段涉及安全参数写入/地址基准确认，开始前必须再次确认允许范围。

### 2026-06-20 第 2 阶段受控写入验证记录

- 执行范围：先读取状态确认无输出，再对一个非控制字、非启动相关配置寄存器执行同值写回；未访问控制字 `40151`，未执行 start/stop，未启用 YAML 自动控制，未解锁前端默认写入逻辑。
- 串口与站号：COM12，9600/8/N/1，Modbus RTU 站号 1。
- 目标寄存器：`40001`，PDU 地址 `0`，手动段 1 加热温度。选择理由：非控制字配置寄存器；本阶段只写回已读原值，不改变设备运行参数。
- 写前状态复核：
  - `40106` 电流原始值：`0`
  - `40108` 实时功率原始值：`0`
  - `40112` fault_code：`0`
  - runtime：`0:00:00`
  - `40114` current_mode_code：`0`
- 同值写回结果：
  - 原值：`40`
  - 写回值：`40`
  - 读回值：`40`
  - 结果：第 2 阶段受控同值写回验证通过；未触发安全停止条件。
- 原始请求/响应：
  - 写前读取 `40106`-`40114`：PDU 起始地址 `105`，数量 `9`；请求帧 `01 03 00 69 00 09 55 D0`；响应帧 `01 03 12 00 00 00 15 00 00 00 00 00 00 00 00 00 00 00 04 00 00 66 4C`。
  - 读取原值 `40001`：PDU 地址 `0`，数量 `1`；请求帧 `01 03 00 00 00 01 84 0A`；响应帧 `01 03 02 00 28 B8 5A`。
  - 同值写回 `40001`：PDU 地址 `0`，功能码 `0x06 write_single_register`；请求帧 `01 06 00 00 00 28 89 D4`；响应帧 `01 06 00 00 00 28 89 D4`。
  - 写后读回 `40001`：PDU 地址 `0`，数量 `1`；请求帧 `01 03 00 00 00 01 84 0A`；响应帧 `01 03 02 00 28 B8 5A`。
  - 写后复核 `40106`-`40114`：PDU 起始地址 `105`，数量 `9`；请求帧 `01 03 00 69 00 09 55 D0`；响应帧 `01 03 12 00 00 00 15 00 00 00 00 00 00 00 00 00 00 00 04 00 00 66 4C`。
- 写后状态复核：
  - `40106` 电流原始值：`0`
  - `40108` 实时功率原始值：`0`
  - `40112` fault_code：`0`
  - runtime：`0:00:00`
  - `40113` current_segment：`4`
  - `40114` current_mode_code：`0`
  - 串口操作结束后已关闭 COM12。
- 下一步：停在第 2 阶段，等待用户确认是否进入第 3 阶段。第 3 阶段涉及控制字 stop 语义验证，开始前必须再次确认严格边界，尤其是不得启动微波输出。

### 2026-06-20 前端/后端受控写入开发记录

- 开发范围：在第 1 阶段只读通信和第 2 阶段同值写回通过后，增加普通配置写入的受控前后端路径；未开放 start/stop，未开放控制字 `40151`，未启用 YAML 自动控制。
- 后端安全门：
  - 新增 `allow_real_hardware_writes=false` 默认门，用于阻断普通配置寄存器真实写入。
  - 保留 `enable_control_writes=false` 作为更高风险门，用于阻断控制字 `40151` / start / stop 写入。
  - 保留 `allow_experiment_control=false` 作为 YAML 自动 configure/start 门。
  - 配置 API 请求必须携带 `confirm_real_hardware_write=true`，否则后端拒绝写入。
  - 配置寄存器批量写入会拒绝覆盖 `40151`。
- 前端安全门：
  - 微波仪控制卡片显示当前串口，例如 COM12。
  - UI 区分显示“受控配置写入”和“控制字写入”两个状态。
  - 配置按钮只在 `allow_real_hardware_writes=true` 时可用，并在写入前弹出明确确认。
  - 启动/停止按钮只在 `enable_control_writes=true` 时可用；普通配置写入通过不会解锁 start/stop。
  - 页面加载、WebSocket 连接和状态刷新仍只读，不会触发写入。
- 当前本地配置：`config/system_config.yaml` 的 `microwave1` 串口改为 COM12；`allow_experiment_control=false`、`allow_real_hardware_writes=false`、`enable_control_writes=false` 仍保持默认关闭。
- 仍需实验室确认：
  - 是否允许临时打开 `allow_real_hardware_writes=true` 做前端/后端配置写入实机验证。
  - `40151` stop 写 `0` 的真实语义、真实 start/stop、运行状态枚举、故障码 bit 和浮点字序仍未确认。
  - 是否允许临时或长期打开 `enable_control_writes=true`、`allow_experiment_control=true` 仍必须单独确认。
- 验证：
  - `python tests\\test_microwave.py`：通过，11 passed。
  - `python tests\\test_microwave_api_ws.py`：通过，9 passed。
  - `python tests\\test_microwave_experiment.py`：通过，14 passed。
  - `python tests\\test_metadata.py`：通过，36 passed。
  - `python -c "import src.web.app; import src.web.api.experiments; import src.web.api.ws; print('imports ok')"`：通过。
  - `cd frontend; npm run build -- --mode production`：通过，退出码 0。

### 2026-06-20 前端设备操作与实时曲线跟进记录

- 开发范围：按用户反馈调整控制页和仪表盘；未在本次开发中执行真实设备 start/stop，未把微波真实控制默认改为开放。
- 仪表盘：
  - 加热器 PV/SV 温度曲线与微波仪物料温度曲线拆成两张图。
  - 蠕动泵流量曲线继续单独显示。
  - 加热器、蠕动泵、微波仪卡片显示各自 connection_port，用于现场核对 COM 口。
- 控制页：
  - 加热器、蠕动泵和微波仪操作按钮不再因为未连接或安全门未开放而前端置灰；点击后先检查连接/状态并给出明确失败或确认提示。
  - 加热器设置温度和启动前提示检查串口、探头、加热对象、接线和现场看护。
  - 蠕动泵通道启动前提示检查串口、通道、模式、软管、流向、入口/出口、收集或废液容器和现场看护。
  - 微波仪启动前提示检查炉门、门控联锁、非空载、探头、参数和现场看护；若实时状态读取失败、fault_code 非零、功率或电流非零，前端不发送 start。
- 后端/API/WS：
  - DeviceManager.get_all_status()、加热器/泵读取结果和 WS 实时 payload 增加 heater/pump 的 connection_port。
  - 设备返回 False 时前端按失败显示；微波后端安全门仍决定是否允许真实写入。
- 门控说明：
  - 说明书/任务记录确认炉门未关严时设备/HMI 会禁止启动并提示“门未关严”。
  - 当前通信协议没有可靠门状态寄存器；软件不伪造 door_closed，仍由实验室人工确认设备面板和联锁。
- 仍需实验室确认：
  - 是否允许打开 enable_control_writes=true 进行第 3 阶段控制字 stop/start 语义验证。
  - 40151 stop 写 0 的真实语义、真实 start/stop、运行状态枚举和故障码 bit。
  - 微波门控联锁在前端 start 调用下的真实拒绝/提示行为。

### 2026-06-20 微波前端/后端/自动化控制开放记录

- 用户授权：用户明确要求取消微波后端安全边界，使微波仪像加热器 1/2 和蠕动泵一样，可通过前端按钮直接启动，也可通过自动化实验 YAML 直接 configure/start/stop。
- 后端/驱动：
  - `MicrowaveConfig`、`MicrowaveDeviceConfig` 和 `config/system_config.yaml` 中 `allow_experiment_control`、`allow_real_hardware_writes`、`enable_control_writes` 默认改为 `true`。
  - 驱动 `_write_register()` 不再按 `allow_real_hardware_writes` / `enable_control_writes` 阻断普通写入或控制字 `40151` 写入。
  - 批量配置写入仍拒绝覆盖控制字 `40151`，防止配置地址范围误伤 start/stop。
  - REST 配置接口继续兼容 `confirm_real_hardware_write` 字段，但不再因缺少该字段拒绝写入。
- 自动化实验：
  - `microwave.configure_*`、`microwave.start` 和 `microwave.stop` 不再检查 `allow_experiment_control`，直接调用 `DeviceManager`。
  - 设备方法返回 `False`、timeout 或异常仍会使步骤失败，不会静默继续。
- 前端：
  - 微波控制卡片显示串口 COM12，并显示配置写入、启动/停止和实验自动控制可用。
  - 配置、启动、停止按钮不再因旧安全字段 false 而拦截；点击后仍会检查连接和状态并弹出人工确认。
  - 启动前仍阻止状态读取失败、`fault_code` 非零、功率/电流非零等明显异常状态。
- 文档：
  - 已同步 `context/PROJECT_CONTEXT.md`、`docs/user_guide.md`、`docs/developer_guide.md`、`docs/experiment_yaml_spec.md`、`docs/microwave_smoke_test.md` 和本任务索引。
- 仍需实验室确认：
  - 本次没有执行真实硬件 start/stop 或 YAML 自动实验。
  - `40151` stop 写 `0` 的真实语义、真实 start/stop、运行状态枚举、故障码 bit、门控联锁拒绝行为、浮点字序和最小安全实验参数仍需按 `docs/microwave_smoke_test.md` 记录。
