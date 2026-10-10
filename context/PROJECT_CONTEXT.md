# PROJECT_CONTEXT.md

> 仅供 AI / 自动化协作者使用。  
> 人类开发者优先看 `docs/developer_guide.md`，实验操作人员优先看 `docs/user_guide.md`。

最后更新：2026-09-30

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
- 目标：统一管理加热器、蠕动泵、注射泵、实验流程、实时监控、日志与样品记录
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
  - `/experiment/editor`（图形编排 / YAML 编辑）
  - `/experiment/batch`（中文引导式固定装置条件组合与完整后端批次执行）
  - `/experiment/batch/template`（已有模板参数设计与单组另存）
  - `/campaigns`
  - `/history`
- 设备接口前缀：`/api`
- 实验接口前缀：`/api/experiments`
- 引导式批次接口前缀：`/api/guided`
- Campaign 接口前缀：`/api/campaigns`
- WebSocket：`/ws`

实验编排接口为 `GET/PUT /api/experiments/{filename}/source` 与 `POST /api/experiments/validate`。编辑器保留 YAML 原文，图形操作局部修改文档树；校验与保存不访问硬件。保存使用内容摘要、同目录原子替换，并与启动装载共用锁；运行或清理中的同名文件不得覆盖。未知设备在编排时提示，启动仍执行原有设备检查。

### 1.4 当前实验动作与等待类型

动作类型：

- `heater.set_temperature`
- `heater.start`
- `heater.stop`
- `pump.start`
- `pump.stop`
- `pump.stop_channel`
- `valve.switch`
- `syringe_pair.dispense`
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
- `heater_pair_stable`
- `pump_complete`
- `microwave_temperature_reached`
- `microwave_temperature_below`
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
- 区分“命令已发送”“寄存器写后读回一致”“最终设备状态已确认”和“物理动作已由现场确认”；任何一层都不能替代后一层

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

### 2.7 当前设备兼容与确认事实

- 当前设备注册身份、串口指纹/序列号、通信参数、配置 fallback COM 号和通道参数以 `config/system_config.yaml` 为准；先读该配置和设备资料索引，再询问用户已登记的信息。fingerprint 模式的 fallback COM 不是保证的实际端口，运行时以唯一解析结果为准。验收清单应与当前配置一致，不能沿用历史 COM 号。
- `pump1` 的软管型号仅允许设备级映射 `写入 11 -> 读回 13`；该映射已由当前设备 HMI 的 `1.52 x 0.86` 显示确认，不得推广为全局协议规则
- 泵关键参数、启停和全部停止均要求有界读回；历史中的 `flow_rate` 是设备设定/报告值，只有 `running=true` 且 `read_ok=true` 的区间才可解释为输运区间
- 宇电加热器输出状态参数使用协议参数 `77`；设置温度、RUN/STOP 后必须读取 SV 或输出状态确认。STOP 时还要记录 `Srun`、MV、HMI/输出端口和物理状态，不能只凭瞬时 MV 值判定
- 微波状态需分别记录控制位、真实输出和停止确认。`control_active`、`output_active`、`stop_confirmed`、`status_confirmed` 已进入状态载荷，但控制字模式位读回、浮点字序、真实输出、门控联锁和物理 stop 语义仍待实机确认
- 手动页微波程序采用电脑托管逻辑段：默认1段，可添加至5段；只支持自动/手动功率。每个逻辑段覆盖五个硬件槽为同一目标及长保温时间，复用后端引擎等待到温、计时监督保温、确认停止后进入下一段，不猜起止段寄存器、不使用零秒跳段。段间停机，固件方案映射/计时重置待实机验收。共享实验占用、持久化进度、请求防重放和失败/中断人工恢复锁；托管不支持暂停，页面生命周期不控制设备。服务崩溃不能保证立即停机，原始REST/YAML及引导流程仍使用各自执行语义。

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

软件层最小验证按变更范围选择：

- `python tests\test_metadata.py`
- `python -c "import src.web.app; import src.web.api.experiments; import src.web.api.ws"`
- 前端源码变更时执行 `npm --prefix frontend run build`

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
- 当前仓库采用任务分支制，而不是长期开发分支模式
- 每个新需求应从最新 `master` 切出独立任务分支
- 任务分支合并进 `master` 后，先在分支最终提交上创建附注归档标签，确认主线和标签已同步到所有已配置远程，再删除本地及远程分支；归档失败时保留分支。具体规范见 `docs/testing_and_merge_flow.md` 第 9 节
- AI 不要在 `master` 上直接展开常规开发
- AI 不要默认复用已经合并完成的旧开发分支

---

## 9. 历史问题摘要

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

## 10. 当前系统边界与未决事项

当前已知边界：

- 主流程文档化较完整，但仍依赖人对硬件场景的理解
- 测试以软件层为主，硬件 smoke test 仍需人工执行
- `src/main.py` 仍存在，但主线协作应以 Web 体系为准
- 微波仪软件路径已按 2026-06-20 用户授权开放前端手动和 YAML 自动控制；真实硬件行为、门控联锁、负载安全、故障码和 stop 语义仍需要实验室 smoke test 确认

当前未决事项：

- 是否要补专门的 API 参考文档
- 微波仪真实硬件联调结果尚未回填
- 是否要继续拆分历史问题库与 AI 规则库


## 11. MSP1-CX 注射泵接入（2026-09-28）

- 独立 `syringe_pump` 设备类型；当前只支持两台三口Y型阀的独立USB串口，OEM/DT，RS232/RS485，不支持CAN及共用串口总线。
- `syringe_pump1` 配置COM12、唯一转换器序列号ASDNB2A7N12、拨盘0；`syringe_pump2`配置COM13、唯一转换器序列号A9BSB2A7N11、拨盘1。两台RS232由用户于2026-10-01确认；默认2.5mL、9600/8N1，配置文件为身份事实来源。
- 启动服务、页面加载、GET和WebSocket生命周期不连接/初始化/运行泵。驱动同步、复用SerialPortManager；上层协调读写、实验所有权和动作超时。
- 运动超时不自动重发，未知/过载/停止后位置失信。不能用旧读数掩盖读取失败；体积只代表理论排量，软件没有漏液/水到位传感器。
- 本文2.3通用暂停规则对注射泵有明确例外：按用户选择，当前已发动作/有限程序继续完成，暂停不发下一步，恢复不重放；暂停期间仍读Q监督故障和处理停止。引擎步骤/运行完成状态仍等待恢复；故障则立即进入失败清理。
- 新API前缀 `/api/syringe_pump/{device_id}`。新增 `syringe_pump.initialize/configure/move/aspirate/dispense/valve/stop/resume/io/program_load/program_store/program_run/repeat` YAML动作和 `syringe_pump_complete` 等待；h硬件暂停为手动入口。
- `steps[].device_result`记录短动作终态，历史采样增加 `sensor_data.syringe_pumps`，复用run_id/sample_id及原持久化失败报告。Planner仍不能直接控制泵。
- 本轮仅软件验证，无实机通信/运动验收。不能可靠读回的配置/EEPROM标记已发送待验证；程序槽位重新连接后须重新登记。详见 `docs/syringe_pump_integration.md` 与 `docs/syringe_pump_acceptance.md`。

## 12. 继电器三通阀手动控制（2026-10-07）

- 独立 valve 设备类型，valve1 通过中盛继电器第1通道控制；配置 fingerprint 序列号 DU0ER6Y3A，fallback COM7、38400/8N1、站号1，禁止失配回退。
- 保持寄存器0，0x06写0/1、0x03读回；驱动纯同步、复用串口管理、写入不自动重试。启动/页面/状态读取不控制阀位。
- `/api/valve/{id}` 提供 connect/disconnect/status/switch；控制页新增三通阀，按继电器通电/断电位置显示，不冒充实际流路反馈。新增 valve.switch YAML动作（position 为 NO/NC），仪表盘、实时状态、图形编排和历史记录已接入。实验占用期间禁止手动切换/断开；暂停、停止、完成及失败保持当前阀位，恢复不重放已完成切换。
- 三通阀断电不等于流路全部关闭。安全流路未由现场确认，因此断开与清理保持阀位，全局急停保持阀位并明确报告停止未确认，取消过期排队切换。实际切换、阀体T版本、电压、线圈极性、出口映射均需现场验收。

### 引导式产物收集边界（2026-10-08）

- 引导式 Demo 不包含圆盘或自动收液装置，也不设置收集位置。产物从三通阀产物出口排出，由现场安排产物瓶更换，程序不等待换瓶确认。完整后端现已接通，降温达标并在收取前复查后自动切阀、抽液。

引导式完整后端已接通：guided.py 固定流程编译及 GuidedBatch 复用既有引擎、记录和设备接口，/api/guided 提供 preview/start/status/pause/resume/stop。双泵 syringe_pair.dispense 由上层并行下发各自完成，一路失败停止两路。45℃降温判断和收取前温度复查串联产物阀及抽液；泵液使用真实定时定量模式及完成读回。跨组保留泵/阀所有权，注册到 _engines 并与普通实验互斥。批次原子记录位于 output/guided_batches，完整流程快照位于其 plans 子目录，每组仍有 run_id/sample_id。服务重启不自动续跑，中断/待清理记录阻止所有实验启动，须人工确认设备停止解除。页面生命周期不控制硬件，启动不自动连接；初始化只在明确确认的一键批次启动或单独预充入口执行。仅通过软件验证，液路、流量、停止及温度行为待实验室验收。


### 引导批次预充边界

`/experiment/batch` 在正式确认前设置前驱体预充参数，点击开始自动实验后先自动执行预充：先泵1全部循环再泵2，最后阀切废液并用 pump1 通道4按独立的预充排液时间及流量排液。POST `/api/guided/start` 无 priming_batch_id 时创建完整批次，初始化及预充成功后核对配置签名并严格重查就绪，再自动进入正式组。POST `/api/guided/prime` 仍可单独运行前置阶段，成功进入 paused/ready 并保留设备占用；`/start` 携带该批次 priming_batch_id 时沿用匹配签名的预充结果。页面读取和刷新不启动或重复预充，不得绕过预充。 一键启动后自动显示集中进度视图，复用批次状态轮询与暂停/继续/停止入口，刷新只恢复显示。预充不启动加热/微波、不自动连接；检查温度后按明确确认的参数依次初始化两台泵，确认可信零位才执行预充循环，每批一次；只验证动作及读回，不能证明排气/排空。失败、主动停止预充及服务中断需现场恢复确认。维护日志 run_kind=priming，不属于正式实验 groups 或 planner 样品。

### 自动化安全修复边界

引导式保温同步配置微波段时、分、秒，并使用 `microwave_monitored_hold` 每秒监督温度有效性、故障及控制状态。故障/读取失败停止，零功率不单独判故障，设备提前结束超过 1 秒判失败。反应启动后暂停为 `pause_pending`，继续升温/保温监督，显式停微波后真正暂停；停止始终可中断，恢复不重放。通用等待/超时采用单调时钟并扣除实际暂停。

预览和两次启动均校验固定设备、启用通道和流量上限，容量含累计预充、单组剂量及每次清洗量。预充维护编号为 `{batch_id}_PRIMING_{run_id}`，正式 S001 起，历史不改号。短泵等待消费本次启动读回证据，只有有效 STOP 才完成；不证明真实液量/排空。软件测试不代替实机到温计时、结束边界、短泵读回、45℃降温和停机验收；保留无圆盘、无换瓶等待及失败后不自动续跑。

### 引导式固定液路及跨组保温

引导式固定 NO 收产物、NC 排废液，每轮清洗切 NC 在注液之前；搭建式仍自由选择阀位。正式收产物及清洗排液分别必填 product_drain_seconds / clean_drain_seconds（0.1–9999 秒），共用 drain_flow，沿用预充的定时定量模式（名义排量=时间×流量÷60），清洗进液仍按体积/流量。时间和完成读回均不证明排空，须现场标定死体积、背压和空转条件。新字段纳入预充签名，旧历史不修改、不自动复用。

前驱体加热器在微波反应、降温、清洗、组间及暂停持续运行，下一组调整目标并重新等待两路同时在各自目标 ±3℃ 内持续 30 秒；只在整批结束、失败或停止关闭。成功组选择性清理保留活动加热器跟踪，失败/停止/最终清理始终全停机。最终停机失败须保留 live 占用及持久化 cleanup_required，服务重启仍需人工恢复确认。

引导式初始化参数 initialization_a/b（方向及代码）和 initialization_confirmed 已接入；预充前只读检查允许故障码0/7的空闲泵，正式启动仍严格确认可信零位。heater_pair_stable 在上层进行双路稳定等待，越界或暂停重置30秒窗口，读温失败/无效/超时禁止进料。正式产物及清洗页面只保留现场填写的排液时间，不展示理论时间；清洗页显示共用流量，预充估算保留。
