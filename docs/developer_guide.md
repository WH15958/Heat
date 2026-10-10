# Heat 开发者指南

面向人类开发者与维护者。  
如果你是 AI / 自动化协作者，请先读 [../context/PROJECT_CONTEXT.md](../context/PROJECT_CONTEXT.md)。

---

## 你现在应该看什么

- 想理解系统结构：看“架构总览”
- 想扩展实验能力：看“新增实验动作 / 等待条件标准流程”
- 想接入新设备：看“新增设备驱动标准流程”
- 想确认 merge 前要做什么：看 [testing_and_merge_flow.md](testing_and_merge_flow.md)
- 想排查线上/联调问题：看 [troubleshooting.md](troubleshooting.md)

---

## 1. 架构总览

当前主路径是 Web 架构：

```text
Vue 前端
  -> FastAPI Web 层
  -> Experiment 引擎
  -> Devices 同步驱动
  -> Protocols
  -> 串口资源管理
```

主线模块：

- `src/web/`：REST API、WebSocket、应用生命周期
- `src/experiment/`：YAML 解析、状态机、步骤执行、实验日志
- `src/devices/`：加热器、泵和微波仪的同步设备驱动
- `src/protocols/`：AIBUS、MODBUS RTU、参数定义和微波仪寄存器常量
- `src/utils/`：配置、日志、串口资源管理
- `src/science/`：`sample_id` 和 `samples.csv` 记录链路
- `src/campaigns/`：Campaign、Trial、Recommendation 与表征结果存储
- `src/ml/`：人工 planner 接口与后续 planner 扩展点

前端主要页面：

- `/`
- `/control`
- `/experiment`
- `/campaigns`
- `/history`

---

### 前端主题维护

全局导航位于 `frontend/src/App.vue`，页面切换时会卸载旧页面，以便清理轮询和 WebSocket，并在再次进入设备控制页时刷新设备状态。蓝白主题与响应式断点集中在 `frontend/src/styles/theme.css`。主题覆盖 Element Plus 展示样式，设备控制页通过 `device-columns` 组织两列独立内容；小于 1200px 使用单列，小于 768px 展开式导航。其他页面沿用原有业务布局。

本地装饰资源位于 `frontend/src/assets/theme/`，由用户提供的图片裁切并压缩为 WebP。插画使用空 `alt` 和非交互样式；状态、故障和参数必须继续使用真实文本及现有数据源。修改主题时同时检查 Element Plus 懒加载样式的优先级和弹窗，不将设备事件处理迁入展示层。

## 2. 核心开发约束

### 2.1 设备驱动必须保持同步

不要在 `src/devices/` 内做这些事情：

- 后台线程轮询
- 内部异步任务调度
- 命令队列线程
- 页面生命周期联动控制

原因：

- 串口是半双工，请求-响应强依赖顺序
- 驱动层并发会破坏稳定性

### 2.2 Web 层必须用桥接思维

FastAPI 是异步的，但设备是同步的。  
开发原则：

- 设备调用通过 `run_in_executor`
- 不在 Web 层伪造成功状态
- 不让 WebSocket 断开影响设备运行

### 2.3 语义一致性优先

以下三者必须一致：

- 引擎状态
- 日志状态
- 真实设备副作用

尤其注意：

- 设备方法返回 `False` 不能被忽略
- wait 超时不能静默继续
- stop 要尽快生效，但状态必须落到正确终态
- 引擎只清理本次运行曾尝试启动的设备；停机返回失败时不得报告 `stopped` 或 `completed`

---

## 3. 代码结构与职责

### 3.1 Web 层

- `src/web/app.py`：创建 FastAPI 应用、加载配置、挂载静态资源、启动推送循环
- `src/web/api/devices.py`：设备连接、控制、状态接口；包含微波仪 `/api/microwave/{device_id}/...` 路由
- `src/web/api/experiments.py`：实验启动、暂停、恢复、停止、进度、历史，以及编排器的 YAML 读取、校验和版本保护保存
- `src/experiment/editor.py`：无硬件访问的 YAML 编排校验、设备引用提示和原子文件保存
- `src/experiment/parameter_models.py`：设备 REST 与编排器共用的纯参数契约
- `src/web/api/campaigns.py`：`/api/campaigns` 下的 Campaign、Trial、Recommendation 与表征结果接口
- `src/web/api/ws.py`：WebSocket 推送与连接管理

#### 实验编排接口

前端路由 `/experiment/editor` 通过可选 `filename` 查询参数打开已有文件，使用 `yaml` 文档树及 CodeMirror 6 编辑同一份原文。

| 接口 | 请求 / 返回 |
| --- | --- |
| `GET /api/experiments/{filename}/source` | 返回 `{filename, content, revision}`；revision 为原始 UTF-8 字节的 SHA-256 摘要 |
| `POST /api/experiments/validate` | 请求 `{content}`；返回 `{valid, errors, warnings}`，各条问题包含 `message, path, step_id, line, column`（行列从 1 开始） |
| `PUT /api/experiments/{filename}/source` | 请求 `{content, revision}`；新建时 revision 为 null，更新时传读取版本；返回新的 source 对象 |

内容上限为 1,000,000 字符。保存前执行纯结构/参数校验，失败返回 422；同名创建、版本变化、运行或清理中的文件覆盖返回 409。文件名错误返回 400，读取不存在文件返回 404，文件 I/O 失败返回 500。保存与启动装载使用同一进程内锁；文件写入同目录临时文件、flush/fsync 后原子替换，不强制覆盖冲突。当前协调适用于单个后端进程，多 worker 部署需要额外的跨进程协调。

`parse_experiment_data` / `parse_experiment_content` 共享解析器规则，编排时关闭设备存在性阻断并返回设备警告；启动仍保留默认严格检查。编排接口不获取 DeviceManager，不连接或控制设备。软件校验通过不等于设备就绪或安全确认。

Windows 双击入口为 `start_heat.bat`，负责选择虚拟环境/Conda/PATH Python；`scripts/launch_heat.py` 负责前置检查、日志和启动互斥，并在主线程执行原有 `run_server.py`，保留 Uvicorn 的 Ctrl+C/lifespan 退出流程。`output/heat-launcher.lock` 为进程持有的 Windows 文件锁，退出时自动释放，空闲锁文件无需删除。就绪检测线程仅在启动阶段读取 `/openapi.json` 和首页，不触发设备操作；其回归测试为 `python -m unittest discover -s tests -p test_launcher.py`。

### 3.2 实验引擎

- `src/experiment/parser.py`：解析 YAML、校验实验文件名
- `src/experiment/actions.py`：动作和等待类型定义
- `src/experiment/executor.py`：逐步执行动作，处理等待、失败和返回值
- `src/experiment/engine.py`：状态机与 run 生命周期
- `src/experiment/experiment_logger.py`：run / step 日志与持久化

### 3.3 设备与协议

- `src/devices/heater.py`：加热器同步控制
- `src/devices/peristaltic_pump.py`：多通道泵同步控制
- `src/devices/microwave.py`：MKM-AH1E 微波仪同步 Modbus 控制
- `src/protocols/aibus.py`：加热器协议实现
- `src/protocols/modbus_rtu.py`：泵协议实现
- `src/protocols/microwave_params.py`：微波仪 Modbus 地址、模式和控制字常量

说明：蠕动泵在 Heat 中按 Modbus RTU 驱动，但现场物理接线不在软件层写死为 RS485。若实验室当前使用 RS232 线缆，以现场接线事实为准；不要把“协议是 Modbus RTU”和“物理层一定是 RS485”混为一谈。

泵控制的防错边界：

- `POST /api/pump/{device_id}/start` 对通道、方向、模式、单位、有限数、协议流速范围（一般 `0.01-9999`，RPM 上限 `150`）、模式必填参数和重复间隔做请求校验；布尔值不能冒充数值，非法请求返回 `422`，不会调用设备管理器。
- `DeviceManager` 在任何配置写入前检查通道启用状态和 `max_flow_rate`，并在 `/api/devices` 的泵通道元数据中暴露配置的 `tube_model`、`max_flow_rate` 和启用状态供前端约束输入；启动事务先确认 `n001=0`，再写入并读回方向、软管、模式和当前模式参数，最后写启动并确认 `n001=1`。默认要求读回与请求相同；经 HMI 规格确认的固件差异只能通过具体泵的 `tube_model_readback_overrides` 配置，不能硬编码为所有泵的全局协议规则。`pump1` 当前唯一覆盖为 `11 -> 13`。stop/disconnect/cleanup 会与同一泵的启动事务协调，主动断开和 cleanup 只有在 stop 确认成功后才释放串口。
- 泵启动事务会读回使能、方向、模式、流速/单位及当前模式参数，最后读取 `n001` 确认启动；单通道停止和 `0010=0` 全停分别读取 `n001` 确认。非法枚举、超时或浮点读回异常均失败，缓存状态不能替代实读结果。
- 泵 stop 使用请求代次取消更早进入但尚未拿到事务锁的 start，避免 stop 已返回成功后旧 start 再启动；`TIME_QUANTITY` 同时校验声明流量与体积/时间推导流量。
- Modbus 读写除 CRC 外还必须匹配 slave、function、长度、byte count 和写响应 echo；CRC 正确但属于其他请求或设备的帧不能算成功。
- `ConfigManager.load()` 对硬件配置验证失败时直接抛错；有限数、整数和布尔配置按声明类型严格校验，`connection.stopbits`、`connection.bytesize`、泵通道 `max_flow_rate` 和设备级 `tube_model_readback_overrides` 会透传到 Web/CLI 设备配置，不再静默忽略。读回覆盖的键和值必须是 `0-13` 的整数。
- 加热器 OUTPUT_STATUS 使用宇电协议参数 `77`；启停确认直接对该参数做有界读回，避免套用完整数据读取的重试层。读取失败或枚举未知时使用 `RunStatus.UNKNOWN`，不能用默认 RUN/STOP 伪装确定状态；主动断开确认失败时 `/api/heater/{device_id}/disconnect` 返回 `400` 和驱动失败详情，同时保留串口连接供重试。
- 加热器 RUN/STOP 和急停在状态读回前必须确认 AIBUS 写命令返回成功；写入失败不能由碰巧匹配的旧状态读回覆盖。泵诊断读取与 WebSocket 状态读取共享每泵单飞协调器；诊断等待超时后，后续读取继续等待同一个底层串口任务，不另起并发访问。泵通道读取失败时实时状态值设为 `null`、`run_status=UNKNOWN` 且 `read_ok=false`，消费者不得把缓存值解释为当前状态。

Web 静态 fallback 只服务前端路由；未知 `/api/*`、`/ws/*` 保持 `404`，解析后的静态文件路径必须仍位于 `src/web/static` 内。HTML 页面返回 `Cache-Control: no-store`，确保重新打开页面时读取当前构建入口；带内容哈希的资源仍由静态资源服务处理。

### 3.4 样品与记录

- `src/science/sample_id.py`：`sample_id`、`batch_id`、`condition_id`
- `src/science/sample_record.py`：`samples.csv` 写入与去重
- `ExperimentRun.persistence_status` 独立记录追踪持久化结果；`log_saved`、`sample_record_saved` 和 `persistence_errors` 用于区分“设备流程完成”和“记录完整落盘”
- 实验日志、`samples.csv` 和 campaign JSON 采用同目录临时文件加 `os.replace()` 的原子替换；进程内写入使用锁保护读改写序列

---

## 4. 新增设备驱动标准流程

### 4.1 目标

把“新设备”纳入现有体系，而不是单独起一套旁路实现。

### 4.2 标准步骤

1. 明确协议层边界
   - 协议编解码写在 `src/protocols/`
   - 协议层不要承载设备状态
2. 在 `src/devices/` 实现同步驱动
   - 保持同步阻塞
   - 使用现有锁与资源管理模式
3. 在配置层接入
   - 补 `config/system_config.yaml` 对应结构
   - 补 `utils/config.py` 的解析逻辑（若需要）
   - `src/web/app.py -> DeviceManager -> DeviceConfig` 必须透传连接超时、重试、温度/功率上限等安全字段，不能只传端口和波特率
4. 在 `DeviceManager` 中注册并暴露控制入口
5. 如需 Web 控制，再补 `api/devices.py`
6. 如需实验引擎接入，再扩动作和执行器
7. 补软件测试与最小联调说明
8. 同步文档

### 4.3 禁止事项

- 直接在 Web 层拼协议帧
- 为新设备绕过 `DeviceManager`
- 在驱动内偷偷起线程

### 4.4 微波仪当前接入事实

微波仪接入遵守与其他设备相同的同步驱动边界，但安全等级更高：

- 驱动：`MicrowaveDevice` 是同步阻塞驱动，不创建后台线程、轮询、心跳或命令队列。
- 协议：原始协议表使用 `40001` 风格保持寄存器地址；代码必须通过 `holding_address()` 转成 PDU 地址，例如 `40001 -> 0`、`40151 -> 150`。
- 控制字：`40151` 对应 PDU 地址 `150`，bit15 为恒速率、bit14 为自动功率、bit13 为手动功率、bit12 为微波启动；当前 stop 实现写 `0`，真实语义仍需实机确认。
- 微波配置写入后按协议对可读段寄存器做精确读回。启停确认只使用 40151 中声明可读的 bit12；停止还要求状态块中的功率和电流归零。模式位不因整字可读而被假定可读。
- 状态：`DeviceManager.read_microwave_data()` 暴露 `connection_port`、`running`、`control_word`、`control_active`、`output_active`、`stop_confirmed`、`status_confirmed`、`mode`、`current_segment`、`material_temperature`、`temperature_source`、`power_percent`、`current`、`runtime_seconds`、`fault_code`、`current_mode_code` 及兼容控制字段。`control_active` 只解释协议声明可读的启动位；`output_active` 由功率/电流判断；`stop_confirmed` 要求启动位清除且无输出；状态读取失败不得用缓存的停止值替代。`mode` 只对仓库已确认的控制掩码做保守解码。
- 串口展示：`DeviceManager.get_all_status()`、加热器/泵读取结果和 WebSocket 实时 payload 会为 heater/pump/microwave 暴露 `connection_port`，用于前端确认当前连接的 COM 口；该字段只读展示，不改变设备控制语义。

## 串口稳定绑定

Windows 串口锁使用 `port_COMx.lock` 命名；不得使用 `COMx.lock`，因为 `COM1`–`COM9` 即使带扩展名仍是 Windows 保留设备名，可能被解释为设备而非普通文件。

蠕动泵初始化逐项检查命令结果，失败时返回 `False` 并保留 `ERROR` 状态及 `connection_error`；`/api/devices` 的泵状态透传该字段。此时 `is_connected()` 仍反映可用的串口连接，以保留停止、断开和清理路径，但上层禁止启动。重开串口不会清除初始化失败。串口锁删除遇到权限错误最多尝试三次，间隔 50 ms；持续失败时保留资源占用记录，供后续释放重试，不报告成功。

Heat 现在把“设备身份解析”和“驱动按端口连接”分开处理：

- 配置层：`DeviceConnectionConfig.binding`
  - `mode=fixed_port` 兼容旧行为
  - `mode=fingerprint` 按 `serial_number`、`vid/pid`、`location`、`description_regex` 等规则找设备
- 解析层：`src/utils/serial_binding.py`
  - 只负责枚举 `serial.tools.list_ports.comports()`
  - 只返回唯一命中的端口，0 命中或多命中都算失败
  - 仅在 `fallback_to_port=true` 且配置了 `port` 时允许回退
- 驱动层：`src/devices/`
  - 仍然只接收最终解析出的端口名
  - 不增加扫描、轮询、识别逻辑

只读状态字段：

- `connection_binding_mode`
- `binding_label`
- `binding_resolved`
- `binding_match_count`
- `binding_error`
- `binding_candidates`

后端在绑定未解析时会阻止 `connect_*`，避免把设备误连到不确定串口。
- 绑定刷新：`POST /api/devices/refresh_bindings` 会重新运行串口解析并更新已注册设备实例的最终端口；控制页发现“未匹配”时会自动调用一次，用于处理设备晚于后端启动才被 Windows 枚举出来的情况。
- API：`/api/microwave/{device_id}/connect`、`disconnect`、`data`、`configure/manual`、`configure/auto_power`、`configure/constant_rate`、`start`、`stop` 只桥接到同步 `DeviceManager` 方法，返回 `False` 时不能包装成成功。配置请求必须包含 1-5 段，数值字段拒绝布尔值；请求体仍兼容 `confirm_real_hardware_write` 字段，但后端不再把它作为拒绝条件。

手动页默认 1 个逻辑段，可添加至 5 段，只能移除末段。草稿段数不持久化，页面刷新恢复 1 段并只读恢复后端托管进度。`hostedMicrowavePayload` 校验所有使用段并转换时分秒为保温整秒；只支持 `auto_power` / `manual_power`。`configuredProgramKey` 是当前会话的预检查证据，模式、使用段参数、段数或连接变化即失效；迟到的校验响应不能恢复失效证据。预检查不访问硬件，启动后消费证据；网络重试沿用 `request_id` 防重放，重新检查产生新标识。

电脑托管 API 前缀为 `/api/microwave-program/{device_id}`：`POST /preview` 仅编译校验；`POST /start` 接收 `request_id`（32位小写十六进制）、`mode`、`stages`（1–5个 `{temperature, hold_seconds, power_percent}`）、可选 `heating_timeout`（默认600，1–3600秒）及显式 `hardware_confirmed=true`；`GET /current` 返回状态、逻辑段、阶段、错误和恢复/清理锁；`POST /stop` 停止本服务中的执行；`POST /acknowledge-interrupted` 要求 `{devices_stopped_confirmed: true}`，只解除现场确认后的锁，不重放。重复标识和相同请求返回原记录，参数不同返回409；旧标识即使完成、停止或解除锁定也不能再次执行。连接、有限非负温度、无故障、控制位清除和输出停止均需后端只读检查，不自动连接。

`src/experiment/microwave_program.py` 使用既有 `ExperimentEngine`、`StepExecutor` 和运行日志：每个逻辑段以原有 configure/start/monitored_hold/stop 动作编译四步，到目标 ±1℃ 后才开始保温；确认停止后才切换下一目标。每次配置五个硬件段为同一目标及 `heating_timeout + hold_seconds + 60` 秒保温，最大99时59分59秒。只写已知参数寄存器，不写未知起止段地址或将零秒解释为跳段；设备启动范围/方案与参数映射、计时重置仍待实机验收。段间停机，原始 REST/YAML/引导流程不改为此托管模式。

完整程序注册在共享 `_engines`，与普通/引导实验互斥，运行和清理期间保留占用，阻止手动写控制和断开；手动停止及全局急停先禁止后续步骤。托管不暴露暂停/恢复，通用实验暂停/恢复端点对此返回409，避免冻结电脑计时而固件仍加热。原子记录位于 `output/microwave_programs/mwprogram_<request_id>.json`，启动意图必须先落盘，每步先保存进度；存储失败停止并保留锁，日志保存失败也显式报告。重启后未完成或待清理记录视为中断，锁住实验和手动运动控制；可连接、读取、停止后人工确认解除，解除记录保存失败仍锁定。页面/WS生命周期只读，服务正常关闭等待托管停机；进程崩溃无法保证立即停机，长硬件计时不能替代独立联锁。

- WebSocket：实时 payload 包含 `microwaves`；各类设备读取超时（包括 Python 3.10 中不同的 `asyncio.TimeoutError` 与内置 `TimeoutError`）写入 `{"error": "read_timeout"}`，其他读取失败写入 `{"error": "read_failed"}`；WebSocket connect/disconnect 不控制硬件生命周期。
- 泵实时 payload 的每个通道包含 `running` 和 `read_ok`。历史 `flow_rate` 是设备设定/报告值，只有读取有效且确认运行的区间才表示软件确认的输运区间，不等价于外部流量计实测。
- 全局急停 `POST /api/devices/emergency_stop` 保留顶层 `success`，并返回 `devices` 明细；每项包含 `device_type`、`device_id`、`connected`、`attempted`、`command_result`、`final_state`、`success` 和 `reason`。已注册但未连接、命令失败或最终状态未确认都会使总体结果失败。
- 实验日志：`ExperimentLogger.record_sensor_data()` 会把实时 payload 中的微波仪 `material_temperature`、`power_percent`、`current`、`runtime_seconds` 分别保存到 `sensor_data.microwaves[device_id]` 下，供历史记录实验报告绘制微波温度、功率和电流曲线。
- 控制开放：按 2026-06-20 用户确认，`allow_real_hardware_writes`、`enable_control_writes`、`allow_experiment_control` 当前默认 `true`，且不再作为手动 REST/前端或 YAML 自动控制的阻断门；字段保留在配置和 payload 中用于兼容旧状态展示。
- 防错边界：普通配置批量写入仍拒绝覆盖控制字 `40151`；多段配置会先完整校验并转换全部段，任一后续段非法时不会写入前序段；完整配置写与 start/stop 使用同一设备锁，不能交错成“配置一半即启动”。总线在实际写入途中失败仍可能留下已写前序寄存器，不能把多次 Modbus 写误认为事务原子。
- 控制竞态：`DeviceManager` 对同一加热器或微波仪的写控制做串行协调，并用 stop 请求代次取消更早进入但尚未执行的 start，避免 stop 已返回成功后旧 start 再启动；全局急停和 shutdown cleanup 执行期间的新 start 会被拒绝。主动断开和 cleanup 按同一设备锁先 stop，stop 返回 `False` 或异常时保留连接供重试，不得继续 disconnect。
- 串口资源：AIBUS 与 Modbus RTU 在打开串口前统一通过 `SerialPortManager` 取得进程锁并登记句柄；同一进程内重复占用同一端口会被拒绝，连接失败或断开时会释放锁和句柄。管理器只登记 `atexit` 资源清理，不启动超时看门狗、不接管 `SIGTERM` 或调用 `os._exit()`；Web 服务由 Uvicorn/FastAPI lifespan 先执行设备 stop/cleanup，辅助 CLI 由应用级信号处理器执行同样的停机流程。
- 失败传播：设备返回 `False`、timeout 或异常必须向上传播为失败；WebSocket 和页面加载不能触发写入。
- 实验引擎：`microwave.configure_*`、`microwave.start` 和 `microwave.stop` 直接调用 `DeviceManager`，行为与加热器/蠕动泵动作一致，设备方法返回 `False` 时步骤失败。实验自然结束也会清理本次启动的设备；清理失败时运行标记为 `failed` 并阻止同一引擎重新启动，直到重试停机成功。

fake 测试只能证明地址换算、参数校验、失败传播、API/WS payload 和 executor 调用链。真实串口、接线、写入顺序、浮点字序、运行状态、故障码 bit、门控联锁和 stop 语义必须由实验室按 [microwave_smoke_test.md](microwave_smoke_test.md) 人工确认。

`duration` 使用 `time.monotonic()` 统计未暂停的实际经过时间。事件循环延迟计入持续时间，暂停时间排除，等待循环保持短间隔检查 stop，避免按理想 sleep 分片累计造成系统性超时运行。

---

## 5. 新增实验动作 / 等待条件标准流程

### 5.1 新增动作

1. 在 `actions.py` 增加 `ActionType`
2. 在 `parser.py` 的 `ACTION_MAP` 注册字符串映射
3. 在 `executor.py` 增加执行逻辑
4. 如需要，补前端展示和用户文档
5. 补测试
6. 同步 [experiment_yaml_spec.md](experiment_yaml_spec.md)

### 5.2 新增等待条件

1. 在 `actions.py` 增加 `WaitType`
2. 在 `parser.py` 的 `WAIT_MAP` 注册
3. 在 `executor.py` 的 `_wait_condition()` 增加处理
4. 明确 timeout 和 stop 的语义
5. 补测试
6. 同步 YAML 规范文档

### 5.3 特别注意

新增等待逻辑时必须回答清楚：

- stop 是否可中断
- timeout 后是失败还是继续
- 需要读取哪个设备状态
- 失败时如何写日志

---

## 6. 测试分层策略

### 6.1 纯软件验证

适合日常开发和合并前检查：

- `python tests\test_metadata.py`
- 模块导入检查
- 前端构建

### 6.2 需要实机验证的改动

以下改动不应只靠软件测试：

- 串口时序调整
- 协议写寄存器顺序变化
- 泵模式参数写入策略变化
- 真实设备 stop / start 时序变化
- 微波仪 `enable_control_writes`、`allow_experiment_control`、start/stop、控制字或状态寄存器语义变化

### 6.3 本项目测试重点

当前最重要的非硬件测试点：

- YAML 解析
- metadata / `sample_id`
- `samples.csv`
- 单实验保护
- stop / wait 语义
- pause 必须暂停当前等待的计时与轮询，并阻止步骤在 paused 状态下完成
- `pump_complete` 只接受新鲜读取，并要求观察到 running 后的停止转换
- 急停跳过未连接设备时总体结果必须为失败，不能报告全部停机成功
- 日志或 `samples.csv` 写入失败时保留设备执行状态，同时把 `persistence_status` 标成 `error`
- WebSocket 断开不影响设备
- 微波仪前端手动控制和 YAML 自动启动已开放，但真实硬件行为仍需实验室确认

---

## 7. 调试与排错

优先使用这几个入口做定位：

- `src/web/api/experiments.py`：实验生命周期问题
- `src/experiment/executor.py`：动作失败、等待失败、返回值失败
- `src/web/api/ws.py`：实时推送、连接副作用
- `src/science/sample_record.py`：样品记录异常

常见问题请直接看：

- [troubleshooting.md](troubleshooting.md)

---

## 8. 文档同步规则（开发者视角）

以下改动后必须同步文档：

- 页面路由变化
- API 路径变化
- 实验动作 / wait 类型变化
- 行为语义变化，例如 stop、timeout、日志保存、样品记录
- 测试与 merge 流程变化

文档职责分工：

- `README.md`：入口与导航
- `PROJECT_CONTEXT.md`：AI 规则、历史问题、系统不变量
- `user_guide.md`：使用方式和行为语义
- `developer_guide.md`：开发维护方式
- `experiment_yaml_spec.md`：实验格式规范
- `testing_and_merge_flow.md`：测试、commit、push、双远程流程

---

## 9. 合并前检查清单

合并前至少确认：

- 代码改动与文档改动一致
- `tests/test_metadata.py` 通过
- Web 关键模块可导入
- 前端 `npm run build` 通过
- 临时产物未误入版本控制

更详细的流程见：

- [testing_and_merge_flow.md](testing_and_merge_flow.md)

---

## 10. 发布 / 推送流程（双远程）

本仓库当前常用双远程：

- `origin`：Gitee
- `github`：GitHub

标准流程：

1. 本地验证
2. 文档同步
3. `git add`
4. `git commit`
5. 推送到当前工作分支
6. 同步推送到两个远程

命令和规则细节统一见：

- [testing_and_merge_flow.md](testing_and_merge_flow.md)

---

## 11. Review Checklist

- 是否破坏了同步驱动模型
- 是否忽略了设备返回值
- 是否让 stop / timeout 语义变模糊
- 是否让页面连接状态影响设备状态
- 是否把微波仪真实硬件确认误写成软件验证结论
- 是否同步了 YAML 文档 / 用户文档 / AI 文档
- 是否把运行产物错误纳入版本控制

---

## 12. 分支管理规则（开发者视角）

当前仓库采用任务分支制：

- `master` 是唯一长期稳定主线，只用于合并已验证分支及发布、核验操作，不直接修改代码、测试、文档或规则
- 每个新需求从最新 `master` 切分支
- 一个分支只做一个主题
- 合并进 `master` 后，先创建并推送附注归档标签，确认主线及标签在所有已配置远程一致后，再删除该任务分支；归档失败时保留分支。命名和核验步骤见 [测试与合并流程](testing_and_merge_flow.md#9-分支管理规则)

推荐命名：

- `feature/<topic>`
- `fix/<topic>`
- `docs/<topic>`

不建议继续复用已经合并完成的历史开发分支，因为这会把不同阶段的需求混在一起，削弱回溯和 review 边界。

只有在大型集成项目里，才允许临时保留阶段性集成分支；但必须提前说明用途、生命周期和删除条件。

`feature/automation-valve-microwave` 和 `codex/fix-heater-disconnect` 已于 2026-09-11
线性快进合并到 `master`（`b30a095`），并删除分支引用。历史尖端由以下归档标签保留：

- `archive/2026-09-11/automation-valve-microwave`
- `archive/2026-09-11/heater-disconnect`

后续工作应从最新 `master` 新建任务分支，不要继续使用已归档分支。项目进度汇报的 HTML、
PPTX 和组会展示材料属于仓库外产物，应存放在独立汇报目录，不作为项目文档提交。


## MSP1-CX 注射泵架构

全局急停 REST 接口与实验启动共用注册锁，先同步设置活动引擎的停止标志，再执行设备急停并等待实验清理。WS 注射泵读取超时的响应直接标记未知，不在事件循环中同步等待仍被读取线程占用的控制器锁。断开的加热器、蠕动泵和微波设备在重新连接前会重新解析 fingerprint；已连接设备保留当前串口绑定。

新增独立 `syringe_pump` 类型，配置来自 `SystemConfig.syringe_pumps`。协议 `src/protocols/syringe_pump.py` 实现 OEM/DT、错误解码和有界程序校验；`src/devices/syringe_pump.py` 保持同步，复用 SerialPortManager，无驱动线程或队列。请求模型 `SyringeCommand` 同时供 REST/YAML 使用。

`src/web/syringe_control.py` 按设备协调 REST、WS 和实验访问，使用实验所有权及停止世代号阻止手动插入/过期命令。串口等待不跨动作执行周期占锁；Web层监督动作超时，GET/WS读本身不控制硬件。DeviceManager统一注册、绑定刷新、急停和关闭清理。接口为 `/api/syringe_pump/{device_id}/connect|disconnect|status|diagnostics|programs|command`，方法、请求及状态字段详见 [注射泵接入说明](syringe_pump_integration.md#api-与状态)。

实验日志新增可选 `steps[].device_result` 及 `sensor_data.syringe_pumps`，保留旧记录兼容。EEPROM登记位于忽略目录 `data/syringe_programs/`，原子替换文件；设备不能可靠读回的内容标记未验证，重连撤销槽位执行资格。Campaign/planner边界不变。

相关软件测试为 `tests/test_syringe_pump.py`；禁止测试打开真实COM。真实时序、液路和停机需 [实机验收](syringe_pump_acceptance.md)。

## 继电器三通阀接入

`src/devices/relay_valve.py` 是同步驱动，复用 ModbusRTUProtocol 和 SerialPortManager。依据中盛《数字量输入输出系列使用手册（RS485/RS232版）》V3.0 的保持寄存器定义，当前只支持站号1、第1通道（协议地址0）：0x06写0/1，核对响应回显后用0x03读取0/1。参数为38400、8N1；阀系列依据 Bürkert 0127 数据表，实际阀型号、电压、流路仍按现场铭牌确认。

配置 `valves[]` 使用现有 DeviceConnectionConfig，唯一序列号 DU0ER6Y3A 绑定，禁止指纹失配后回退 COM7。启动只注册，手动连接后只读确认。Web DeviceManager 协调每设备操作锁及全局停止世代号，阻止急停期间及急停前排队的切换。驱动没有轮询线程或写入重试。

接口：POST `/api/valve/{id}/connect|disconnect`，GET `/api/valve/{id}/status`，POST `/api/valve/{id}/switch`，请求为 `{"energized": true/false}`（严格布尔）。设备不存在返回404、参数非法422、全局停止冲突409、通信或读回失败503。成功载荷包含 `connected`、`read_ok`、`relay_energized`、串口绑定信息和 `physical_route_confirmed=false`。GET `/api/devices` 的 `valves` 仅返回缓存摘要，不访问串口。

断开和服务关闭保持阀位；未确认安全流路时全局急停保留阀位、返回未确认报告，不宣称流路全部关闭。软件驱动读回只确认继电器寄存器，不能确认管路实态。提供手动控制与 valve.switch YAML 动作；执行器在启动时占用阀门，清理成功后释放。停止世代号及停止检查取消排队切换，不自动复位。WebSocket 通过现有读取协调器发送 valves，读取失败或超时表示未知。实验记录 steps[].device_result 与 sensor_data.valves；physical_route_confirmed 始终为 false。

软件检查：`python -m unittest tests.test_relay_valve -v`，覆盖只读连接/刷新、超时不重试、读回不一致、失败状态失信、API错误与全局停止；实机切换和流路检查由现场验收。
### 批量条件设计前端

`/experiment/batch/template` 使用现有实验列表、source、validate 和 source PUT 接口，无新增后端接口或硬件调用。`frontend/src/experiment/batch.ts` 从真实模板发现有限类型的数值参数，通过现有文档树局部修改生成组合。最多 200 组，校验逐组调用原后端，保存传空 revision 仅创建新文件。来源为加载时的文件快照，页面显示来源摘要；修改模板后需要重新加载。

每组沿用 metadata 的既有 batch_id、condition_id、sample_index 字段，并移除模板的 sample_id，使原运行链重新生成样品身份。未实现持久化批次队列和自动启动；与 Campaign/planner 无自动连接。测试：`cd frontend; npx tsx --test tests/batch.test.ts tests/experimentDocument.test.ts`。

### 引导式完整后端

`src/experiment/guided.py` 定义严格请求模型、后端条件组合、固定液路完整 recipe 和 GuidedBatch。调用原 parser、StepExecutor、ExperimentEngine 和 ExperimentLogger，每组一个真实运行及 sample_id；不用另建驱动或后台串口线程。最多 200 组、每组最多 10 次清洗；加热温度及剂量以当前设备配置范围校验。

`/api/guided/preview` POST 只生成校验完整流程，返回 rows、recipes、yaml 和 total_groups，无硬件访问。请求 axes 是六个非空且不含重复数值的数值列表，依次为 A/B 温度、A/B 剂量、反应温度和保温分钟。repeats、speed_a/b、drain_flow、clean_volume、clean_flow、clean_dwell、clean_cycles 配置组合及固定操作。product_port 仅接受 NO（默认 NO），废液固定 NC；product_drain_seconds 与 clean_drain_seconds 均必填，0.1–9999 秒，分别用于正式收产物及每次清洗排液；clean_direction、drain_direction 指定现场泵向，plumbing_confirmed 在开始时必须为 true。默认 heating_timeout=600、syringe_timeout=120、cooling_timeout=3600，均可在模型范围内调整。

`/api/guided/start` POST 不携带 priming_batch_id 时，读设备就绪状态、预留注射泵和阀、原子保存计划，启动包含初始化、预充及正式组的后台任务。预充成功后核对设备配置签名并严格重查可信零位等就绪状态，再自动开始正式组。`/prime` 保留单独预充能力；`/start` 携带同批 priming_batch_id 时沿用该预充结果，核对签名、重查就绪状态后只启动正式组。注册到原 experiments._engines 并使用 _source_lock，整批占用期间阻止其他实验启动。设备 REST 写入与批次注册串行；引导批次占用时拒绝手动配置/启动/断开，手动停止会同时请求停止整批。注射泵及阀保持既有所有权，跨组保留直到最终清理，普通实验默认清理行为不变。

GET `/api/guided/current`、`/api/guided/batches`、`/api/guided/{batch_id}` 返回状态、当前组、进度和单组 run_id/sample_id。POST `/{batch_id}/pause|resume|stop` 控制整批；stop 的 success=false 代表清理或保存未确认成功。逐组收取自动执行，没有换瓶确认接口或等待步骤。

双泵排液使用 syringe_pair.dispense，协调位于 StepExecutor 上层，每台同步 Controller 保持原锁与所有权。两路并行下发后分别监督完成，一路失败即停止两路；对整个双泵步骤执行暂停边界语义，不保证硬件同步触发。生成流程显式吸取本组剂量，正式进料不隐式回零；每批通过明确确认的预充入口依次执行已有 syringe_pump.initialize，确认完成及可信零位后才吸排预充液。

微波停止后使用 microwave_temperature_below，material_temperature 必须为有效非负有限数字且 ≤45℃；温度读取失败、微波故障或仍输出不放行。收取前重复此检查，再切换产物出口及抽液。pump.start 使用已有 TIME_QUANTITY、pump_complete 和显式 stop_channel，理论流量不冒充实际排空传感器。

启动前将完整 recipes 与请求快照单独保存至 output/guided_batches/plans/{batch_id}.json，GET /api/guided/{batch_id}/plan 可读取；单组 metadata.recipe_file 指向该快照，recipe_group 指明组号。批次 JSON 原子保存至 output/guided_batches，保存完整请求、组状态、当前步骤、run_id/sample_id 和 persistence_status；单组继续使用原实验历史及样品记录。保存失败不启动下一组，cleanup_pending 保留不确定停机的占用。服务重启后没有 live runner 的非终态或待清理记录标记 interrupted/recovery_required，所有实验启动入口均阻断。POST `/{batch_id}/acknowledge-interrupted` 需 devices_stopped_confirmed=true，人工确认后解除锁定但不续跑。

前端仅在显式按钮操作时发控制请求；定时读取状态及页面/WebSocket生命周期不启动或停止硬件。Campaign/planner 无自动连接。软件验证不替代设备验收。 BatchExperimentPage 启动成功或首次恢复批次时切换到集中进度视图，复用每 2 秒 GET /current；完成组数取 groups 的 completed 状态，当前步骤序号由后端零基 current_step 转为一基显示。各组待执行条件取批次 request 快照，执行结果取 groups；累计用时沿用 progress.elapsed（含暂停），不推算剩余时间。读取失败保留最后状态并提示过期，不触发控制请求。


### 引导批次预充接口与状态

`POST /api/guided/start` 无 `priming_batch_id` 时创建完整批次，初始化与预充成功后自动执行正式流程，任何准备失败或停止均不进入正式组。`POST /api/guided/prime` 保留为单独执行前置预充的接口；`/start` 携带 `priming_batch_id` 时只启动该批次签名匹配且预充成功的正式流程。创建整批和单独预充共用锁内的就绪、占用及服务中断检查；执行中重复启动返回 409，不创建第二个运动任务。`/preview` 增加 `priming` 流程，仍只校验、不控制硬件。`/prime` 携带已有批次 ID 且签名一致时返回现状，不重发运动。

GuidedRequest 新增 `prime_volume_a/b`（默认各 2 mL，须不超过实际泵容量）、`prime_cycles`（默认 2，1–10）、`prime_drain_seconds`（必填，0.1–9999 秒）、`prime_drain_flow`（必填，0.01–9999 mL/min），以及必填正数 `reactor_available_ml`、`source_available_a_ml`、`source_available_b_ml`、`waste_available_ml`。请求新增必填 `initialization_a/b` 对象，各含 `direction`（Z/Y）和 `initialization_code`，复用 SyringeCommand 校验并在编译时检查容量适用性；新增 `initialization_confirmed`（默认 false）。启动预充和正式运行均要求三项现场确认 `initialization_confirmed`、`priming_confirmed`、`plumbing_confirmed` 为 true。初始化参数纳入预充签名，三项确认标志不纳入签名；缺少初始化参数的旧请求被拒绝，旧记录仅供查看。容量校验涵盖预充总量、正式单组量、整批耗液和清洗废液。

批次 checkpoint 新增 `phase`（priming / ready / experiments）和 `priming`（状态、SHA256 签名、已完成循环、步骤设备结果、run_id、持久化状态、失败停机确认）。计划快照包含独立 priming recipe。签名覆盖完整实验参数及固定设备配置，排除确认标志和批次 ID；正式启动前再次只读检查连接、故障、零位及输出停机状态。签名不符拒绝启动；设备状态异常会失效结果并设置恢复锁。

预充复用同步设备驱动、现有 StepExecutor、ExperimentEngine、资源预留和日志；不新增设备动作或 YAML 动作类型。一键启动的预充成功后自动进入 experiments，保留所有权；只有单独调用 /prime 的批次进入 paused/ready，其普通 resume 被拒绝，必须调用 start。失败会停止两台注射泵（含未启动那台）及排液通道；任何 False 或停机异常保留未确认状态，并可再次停止重试。恢复锁必须人工确认后通过现有 acknowledge-interrupted 接口解除，此接口也处理本服务中的预充失败。服务重启后 ready 不可自动复用或恢复。

预充排液直接使用 prime_drain_seconds / prime_drain_flow 下发 TIME_QUANTITY，理论等效排量为 秒数×流量÷60；正式收集及清洗排液使用 drain_flow 和各自独立的 product_drain_seconds / clean_drain_seconds，名义排量同样为 秒数×流量÷60。清洗进液仍按 clean_volume / clean_flow 计算时间。每次清洗先 valve.switch NC 再进液，收产物固定 NO。单组 metadata 记录两个排液时长及 theoretical_product_volume_ml，名义排量不能冒充真实样品量；旧 prime_drain_factor、prime_extra_seconds 不再接受为新请求字段。前端高级容量设置默认折叠但继续必填，产物、清洗与批次确认页面移除理论排液时间和估算按钮，清洗页同步显示共用排液流量；预充页仍保留明确点击的估算按钮；旧记录的旧公式转换仅用于显示，不更新持久化签名、不创建 live runner，也不允许复用旧预充资格。

### 自动化保护等待与计时

同步驱动及设备管理器保持原接口。`StepExecutor` 在编排层实现 `microwave_monitored_hold`：每秒同步读取经线程桥接的微波状态，校验有限非负物料温度、fault_code=0、可靠控制状态，保温控制提前结束超过 1 秒失败。到温等待也校验故障与控制。失败返回 False，由引擎停止已启动设备、记录失败，不进入收取或下一组。硬件保温时、分、秒寄存器由引导编译器根据整秒时长生成。

引导式正式单组启用 `finish_reaction_before_pause`。微波启动至显式停止之间设置 `pause_pending`，不清除运行事件；停止成功后才真正暂停。停止请求清除 pending 并中断等待，恢复不重放。`GET /api/guided/current`、批次状态及普通实验 progress 响应增加布尔 `pause_pending`（普通实验默认 false）；路径不变。页面显示 pending 与 paused 两种状态，pending 时 resume 取消暂停请求。

固定等待和通用条件超时使用单调时钟。实际暂停起止由引擎通知执行器，等待时钟扣除真实暂停累计值；微波阶段 pending 不是实际暂停，持续计时。注射泵已发动作仍完成并持续读 Q。短蠕动泵动作的本次启动读回证据按设备及通道保存，等待消费一次；有效 STOP 才完成，未知或 PAUSE 不通过，新启动/停止/清理清除证据。

`compile_plan` 检查固定设备启用、通道启用和流量上限，模型检查预充、单组和每次清洗的反应器容量及源液/废液总量。`preflight` 在预充与正式启动前重做编译校验，再执行只读就绪检查；不连接或发送动作。预充入口使用 before_initialization 检查，允许故障码 0/7、位置未确认的空闲泵，其他故障阻止启动；正式入口仍要求 fault_code=0、已初始化、可信零位。预充流程在温度检查后显式执行两台泵的初始化，失败沿用批次清理及恢复锁。保存 YAML 的覆盖保护只检查文件实验注册键，批次标识不作为文件路径解析。预充维护 sample_id 由 logger 使用 batch_id 和 run_id 生成，CSV 保留 PRIMING 标记及维护 notes；历史编号不迁移。

软件回归入口：`tests/test_automation_safety_fixes.py`（时钟、状态联锁、暂停/停止、容量/流量、真实临时 CSV、文件保存），并执行既有后端和前端回归。实机验收按微波和注射泵验收文档回填，不用模拟器结果标记实机通过。

引导式正式组启用 `keep_heaters_on_completion=True`：移除反应前 heater.stop，成功组完成仅调用 `stop_active_devices(preserve_heaters=True)` 清理其他活动设备，保留加热器跟踪及批次资源。选择性清理不缓存为全停机，且仅在外层保留资源时生效；选择性清理失败则执行全清理并判本组失败。普通实验、预充、失败/停止默认全清理；整批 finally 关闭加热器。下一组重新设置目标并等待到温，暂停期间持续保温。批次 cleanup_required 包含未停止的活动设备，最终加热器停机失败必须持久化恢复锁定，服务重启也不能绕过。新排液时间进入完整请求签名，旧记录不回填或复用预充资格。

引导式每组使用 `heater_pair_stable` 等待：两个显式目标、tolerance=3、seconds=30、timeout=heating_timeout（默认600）。StepExecutor 在上层每秒读取两路温度，单调时钟连续计时；越界或实际暂停重置窗口，读取失败/无效值/超时立即失败。初始化进度记录为 prime_initialize_1/2，复用既有动作日志及维护样品编号，不改变微波自动功率配置。
