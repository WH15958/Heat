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
- `src/web/api/experiments.py`：实验启动、暂停、恢复、停止、进度、历史
- `src/web/api/campaigns.py`：`/api/campaigns` 下的 Campaign、Trial、Recommendation 与表征结果接口
- `src/web/api/ws.py`：WebSocket 推送与连接管理

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
- `DeviceManager` 在任何配置写入前检查通道启用状态和 `max_flow_rate`，并在 `/api/devices` 的泵通道元数据中暴露配置的 `tube_model`、`max_flow_rate` 和启用状态供前端约束输入；启动事务先 stop，再写入并读回软管型号。默认要求写入值与读回值相同；经 HMI 规格确认的固件差异只能通过具体泵的 `tube_model_readback_overrides` 配置，不能硬编码为所有泵的全局协议规则。stop/disconnect/cleanup 会与同一泵的启动事务协调，主动断开和 cleanup 只有在 stop 确认成功后才释放串口。
- 泵启动事务会读回使能、方向、模式、流速/单位及当前模式参数，最后读取 `n001` 确认启动；单通道停止和 `0010=0` 全停分别读取 `n001` 确认。非法枚举、超时或浮点读回异常均失败，缓存状态不能替代实读结果。
- 泵 stop 使用请求代次取消更早进入但尚未拿到事务锁的 start，避免 stop 已返回成功后旧 start 再启动；`TIME_QUANTITY` 同时校验声明流量与体积/时间推导流量。
- Modbus 读写除 CRC 外还必须匹配 slave、function、长度、byte count 和写响应 echo；CRC 正确但属于其他请求或设备的帧不能算成功。
- `ConfigManager.load()` 对硬件配置验证失败时直接抛错；有限数、整数和布尔配置按声明类型严格校验，`connection.stopbits`、`connection.bytesize`、泵通道 `max_flow_rate` 和设备级 `tube_model_readback_overrides` 会透传到 Web/CLI 设备配置，不再静默忽略。读回覆盖的键和值必须是 `0-13` 的整数。
- 加热器 OUTPUT_STATUS 读取失败或枚举未知时使用 `RunStatus.UNKNOWN`，不能用默认 RUN/STOP 伪装确定状态。

Web 静态 fallback 只服务前端路由；未知 `/api/*`、`/ws/*` 保持 `404`，解析后的静态文件路径必须仍位于 `src/web/static` 内。

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
- 状态：`DeviceManager.read_microwave_data()` 暴露 `connection_port`、`running`、`mode`、`current_segment`、`material_temperature`、`temperature_source`、`power_percent`、`current`、`runtime_seconds`、`fault_code`、`current_mode_code`、`allow_experiment_control`、`allow_real_hardware_writes`、`enable_control_writes`。`running` 以功率或电流大于 0 为准；`mode` 只对仓库已确认的控制掩码做保守解码，无法识别时继续返回 `unknown` 并保留原始 `current_mode_code`。
- 串口展示：`DeviceManager.get_all_status()`、加热器/泵读取结果和 WebSocket 实时 payload 会为 heater/pump/microwave 暴露 `connection_port`，用于前端确认当前连接的 COM 口；该字段只读展示，不改变设备控制语义。

## 串口稳定绑定

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
- WebSocket：实时 payload 包含 `microwaves`，读取失败时写入 `{"error": "read_failed"}`；WebSocket connect/disconnect 不控制硬件生命周期。
- 实验日志：`ExperimentLogger.record_sensor_data()` 会把实时 payload 中的微波仪 `material_temperature`、`power_percent`、`current`、`runtime_seconds` 分别保存到 `sensor_data.microwaves[device_id]` 下，供历史记录实验报告绘制微波温度、功率和电流曲线。
- 控制开放：按 2026-06-20 用户确认，`allow_real_hardware_writes`、`enable_control_writes`、`allow_experiment_control` 当前默认 `true`，且不再作为手动 REST/前端或 YAML 自动控制的阻断门；字段保留在配置和 payload 中用于兼容旧状态展示。
- 防错边界：普通配置批量写入仍拒绝覆盖控制字 `40151`；多段配置会先完整校验并转换全部段，任一后续段非法时不会写入前序段；完整配置写与 start/stop 使用同一设备锁，不能交错成“配置一半即启动”。总线在实际写入途中失败仍可能留下已写前序寄存器，不能把多次 Modbus 写误认为事务原子。
- 控制竞态：`DeviceManager` 对同一加热器或微波仪的写控制做串行协调，并用 stop 请求代次取消更早进入但尚未执行的 start，避免 stop 已返回成功后旧 start 再启动；全局急停和 shutdown cleanup 执行期间的新 start 会被拒绝。主动断开和 cleanup 按同一设备锁先 stop，stop 返回 `False` 或异常时保留连接供重试，不得继续 disconnect。
- 进程退出：`SerialPortManager` 只登记 `atexit` 资源清理，不接管 `SIGTERM` 或调用 `os._exit()`；Web 服务由 Uvicorn/FastAPI lifespan 先执行设备 stop/cleanup，辅助 CLI 由应用级信号处理器执行同样的停机流程。
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

- `master` 是唯一长期稳定主线
- 每个新需求从最新 `master` 切分支
- 一个分支只做一个主题
- 合并进 `master` 后默认删除该任务分支

推荐命名：

- `feature/<topic>`
- `fix/<topic>`
- `docs/<topic>`

不建议继续复用已经合并完成的历史开发分支，因为这会把不同阶段的需求混在一起，削弱回溯和 review 边界。

只有在大型集成项目里，才允许临时保留阶段性集成分支；但必须提前说明用途、生命周期和删除条件。

当前下一阶段硬件集成建议使用独立分支：

- `feature/automation-valve-microwave`

这条分支只承载以下工作：

- 电磁阀控制接入
- 切换阀控制接入
- 微波合成仪自动化控制接入
- 与上述设备直接相关的 API、实验动作、测试和文档同步

不要把无关前端重构、历史清理或通用 UI 美化混入这条分支。
