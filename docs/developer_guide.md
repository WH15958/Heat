# Heat 开发者指南

## 搭建式转盘执行（2026-10-26）

`turntable.home_bottle/next_bottle/stop` 贯通动作枚举、parser、源文校验、编辑器和 StepExecutor。参数仅 `device_id`；限定 wait=none、on_error=stop。解析时检查启用步骤的本次回原点顺序及配置瓶数，执行时再次检查，不继承控制器既有可信瓶位。未引用转盘的旧配方不新增液路设备要求。

`turntable_sequence.py` 从原 GuidedTurntable 提取所有权、停止代次、动作ID、位置令牌、完成读回和停机确认；原 `GuidedTurntable` 保留薄封装及引导式准备/换瓶/收尾语义。`RecipeTurntable` 增加每次执行的瓶位基准、显式停止后重新回原点和正常静止释放。同步驱动未改动，不新增依赖或驱动后台任务。

启动通过既有资源协调占用所用转盘、两台注射泵和 valve1，手动泵阀写控制仍受实验注册锁保护。每次运动前在编排层新鲜读取 pump1 CH3/CH4、syringe_pump1/2 和 valve1，要求停泵及NC；不发隐式液路命令。占用工作线程取消时等待线程退出并登记结果，再回收资源，避免迟到的占用泄漏。停止代次在等待请求锁前生效；暂停只阻挡下一动作，不中断已发送转盘动作的监督。

正常结束新鲜确认静止后释放，不额外停止或回原点；状态未知时尝试停机并报告清理失败。运动/停止未确认保留转盘和液路占用，复用 PersistentExperimentEngine 的持久化恢复锁。STOP可在液路检查失败后执行，失败不重发运动。

步骤 `device_result` 包含 `operation/from_bottle/to_bottle/target_position`、控制器摘要、动作ID及停止结果；REST/WS `activity.devices` 保留当前/目标瓶号和停止状态。复用 run_id/sample_id；动作不新增样品记录或收取完成声明。设备REST接口保持不变，保存/预览/校验仅访问源码和配置。

验证入口：`tests/test_turntable_yaml.py`、原引导式转盘测试及 `frontend/tests/turntableAutomation.test.ts`。生产构建输出隔离到 `output/turntable-yaml-build`；最初源码交付不覆盖现场静态资源、不启动硬件；用户于2026-10-26追加授权打包，最新源码和重新构建前端已纳入0.1.4安装包，详见 desktop_app.md。

面向人类开发者与维护者。  
如果你是 AI / 自动化协作者，请先读 [../context/PROJECT_CONTEXT.md](../context/PROJECT_CONTEXT.md)。

---

## 你现在应该看什么

- 想理解系统结构：看“架构总览”
- 想选择网页热更新、源码桌面测试或安装版运行：看 [日常开发与运行选择](daily_development.md)
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

前端异步结果须匹配当前操作对象：普通实验详情与文件名仅在本次读取成功后一起提交选择，加载/失败时禁止启动，待确认时切换实验撤销旧启动；文件名路径段统一 URL 编码，保留 `#` 与字面 `%20`。Campaign 切换清空旧列表及 Trial 选择，过期读取不能回填；`run_id`/`sample_id` 分别 PATCH。控制确认在离页、设备断连、相关停止或 WebSocket 失联时撤销未提交动作，已发送动作仍由明确停止处理；失联不阻止用户明确确认急停。

控制参数的本机存储写入失败时保留输入并持续显示警告，下一次成功写入才清除。编辑器保存响应必须仍属于原文档；新导入/读取的文档不能被旧响应覆盖，同一文档提交保存后继续编辑也须保留为未保存修改。

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

- 同步设备调用通过线程桥接；持有实验注册锁的手动控制使用 `src/web/device_io.py` 的 `call_device`，请求被取消（包括重复取消）后仍等待实际工作线程结束，再释放锁并传播取消，避免后续实验与尚未完成的设备操作重叠。
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

#### Windows 桌面入口

`python -m src.desktop.main` 启动窗口和托盘，`src.desktop.backend` 为独立的本机单 worker 后台；二者通过认证的 Windows 命名管道交换 JSON。窗口生命周期不控制设备，明确退出经独立协调器完成停止、持久化及清理，失败保留后台。桌面后台在业务导入前设置 `HEAT_DATA_DIR`，可写数据位于 `%LOCALAPPDATA%\Heat\workspace`；静态页面仍属于安装资源，原 Web 启动的路径与入口保留。

退出协调器在执行器停止或保存失败时调用 `DeviceManager.cleanup(disconnect=False)`，继续停止其它设备并保留连接，供停止、急停和明确重试使用；全部确认后再正常清理断开。已结束运行的存储失败通过 `ExperimentLogger.retry_persistence()` 重试，仅修复样品和日志保存标志，不修改运行结果、结束时间或步骤，不再次发送结束事件；已保存的样品跳过写入。引导批次同步同一 `run_id` 的预充／组记录持久化字段，保留失败状态和恢复锁。

托盘原生菜单回调仅启动 `HeatShowWindow`／`HeatExit` 工作线程，避免确认、IPC 等待及 WinForms 同步 Invoke 占用托盘消息循环；`Desktop.operation` 仍负责启动／退出互斥。退出阶段和启动版本写入带时间戳的 `desktop/desktop.log`；排查时结合后台日志，不能仅凭确认框消失推定已结束。线程行为回归位于 `tests/test_desktop_tray_dispatch.py`。

首次迁移、WebView 资料目录、构建隔离环境、离线运行时、发布产物及 Windows 11 x64/真实设备待验收清单统一见 [desktop_app.md](desktop_app.md)。不得将开发机实际配置或历史目录作为发行默认资源。

### 3.2 实验引擎

- `src/experiment/parser.py`：解析 YAML、校验实验文件名
- `src/experiment/actions.py`：动作和等待类型定义
- `src/experiment/executor.py`：逐步执行动作，处理等待、失败和返回值
- `src/experiment/engine.py`：状态机与 run 生命周期
- `src/experiment/experiment_logger.py`：run / step 日志与持久化

普通实验、引导批次和微波托管的停止由各自持有的停止任务负责；调用方通过 `asyncio.shield` 等待，外部取消等待不会连带取消设备清理与最终持久化。停止或保存失败仍保留显式重试和恢复锁，不把调用方请求结束解释为停机成功；同步驱动及原有暂停语义不变。

### 3.3 设备与协议

- `src/devices/heater.py`：加热器同步控制
- `src/devices/peristaltic_pump.py`：多通道泵同步控制
- `src/devices/microwave.py`：MKM-AH1E 微波仪同步 Modbus 控制
- `src/devices/turntable.py` / `src/protocols/turntable.py`：CL-01A 转盘同步串口访问及厂家二进制协议；手动动作监督在 `src/web/turntable_control.py`
- `src/protocols/aibus.py`：加热器协议实现
- `src/protocols/modbus_rtu.py`：泵协议实现
- `src/protocols/microwave_params.py`：微波仪 Modbus 地址、模式和控制字常量

说明：蠕动泵在 Heat 中按 Modbus RTU 驱动，但现场物理接线不在软件层写死为 RS485。若实验室当前使用 RS232 线缆，以现场接线事实为准；不要把“协议是 Modbus RTU”和“物理层一定是 RS485”混为一谈。

串口跨进程所有权在系统临时目录 `heat_serial_locks` 中按端口管理：占用期间持有非阻塞 OS 文件锁（Windows `msvcrt`、POSIX `flock`），释放时才关闭句柄。1 字节 `.guard` 文件永久保留，不能通过删除它或换 inode 绕过锁；文件存在本身不代表端口仍被占用。`.lock` 另记 `owner_token`，非所有者不能删除，陈旧清理不能删除仍持有 OS 锁的记录；无 token 的旧版记录仅在确认原进程已死且取得 OS 锁后允许接管。维护时不要手工删除 guard 来“解锁”。

协议断开返回 `False` 时保留句柄和占用，未登记的本次自有句柄也须在释放占用前确认关闭。加热器、蠕动泵、微波和阀的连接清理／断开失败后，先显式断开成功再重新连接；蠕动泵原有重连路径清理失败后停止重试。注射泵后续显式连接会先重试旧资源清理，失败不得覆盖旧对象；协议未建立不算已连接，读状态失败但协议已建立时仍保留 STOP 通路。Modbus 响应 deadline 使用单调时钟，但不据此承诺整个串行 I/O 的严格总时限。

泵控制的防错边界：

- `POST /api/pump/{device_id}/start` 对通道、方向、模式、单位、有限数、协议流速范围（一般 `0.01-9999`，RPM 上限 `150`）、模式必填参数和重复间隔做请求校验；布尔值不能冒充数值，非法请求返回 `422`，不会调用设备管理器。
- `DeviceManager` 在任何配置写入前检查通道启用状态和 `max_flow_rate`，并在 `/api/devices` 的泵通道元数据中暴露配置的 `tube_model`、`max_flow_rate` 和启用状态供前端约束输入；启动事务先确认 `n001=0`，再写入并读回方向、软管、模式和当前模式参数，最后写启动并确认 `n001=1`。默认要求读回与请求相同；经 HMI 规格确认的固件差异只能通过具体泵的 `tube_model_readback_overrides` 配置，不能硬编码为所有泵的全局协议规则。`pump1` 当前唯一覆盖为 `11 -> 13`。stop/disconnect/cleanup 会与同一泵的启动事务协调，主动断开和 cleanup 只有在 stop 确认成功后才释放串口。
- 泵启动事务会读回使能、方向、模式、流速/单位及当前模式参数，最后读取 `n001` 确认启动；单通道停止和 `0010=0` 全停分别读取 `n001` 确认。非法枚举、超时或浮点读回异常均失败，缓存状态不能替代实读结果。
- `TIME_SPEED=2` 在 `DeviceManager` 内使用独立配置顺序：停止并确认 → 通道/软管/方向 → 切换模式并确认 → 时间/单位、重复次数及本次指定的间隔/单位 → 流量/单位。它不借道 `FLOW_MODE`，不写分装体积，也不补写或重试配置。全部写完后、启动前重读 `n006`、`n107/n109`、`n100`、本次指定的 `n101/n103`、`n110/n112`；启动确认后只复核模式与流量/单位，不比较倒计时。复用同步驱动的有界读回（最多 3 次，间隔 0.25 秒，浮点 `rel_tol=1e-5/abs_tol=1e-4`）及现有泵锁/停止取消机制。启动后核验失败或启动确认失败会停止该通道并读回确认，保留原始原因和停止结果，不重发启动。其他设备模式的配置逻辑不变；引导式通道四排液使用下述流量模式监督流程。
- 泵启动 API 保留原有响应字段，失败时可附加 `error`，包含通道、阶段及参数期望/读回证据；控制页直接显示该详情，实时值仍来自设备读回。YAML 的 `pump_start` 通过同一管理器路径执行，失败沿用执行器错误传播及清理流程。`tests/test_pump_time_speed.py` 用有状态寄存器模拟模式/时间联动与故障，不代表已证明固件按“15÷5”计算；实际协议拒绝原因查看 Modbus 日志，实机需按用户指南水测确认。
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

`samples.csv` 的写入、删除与编号分配先严格检查 CSV：表头不得重复或为空，须包含 `sample_id`、`run_id`，每行列数必须匹配。损坏时保留原文件并报告失败；兼容 UTF-8 BOM、缺少其他标准列的旧文件和已有扩展列，追加时补齐标准列并保留扩展数据。非严格的历史检查模式仍保持尽力读取，不用于写入或编号分配。

微波托管和引导批次的恢复扫描通过 `iterdir()` 枚举目录；只把目录不存在视为无记录。权限或其他读取错误必须传递为存储不可用，禁止用可能吞掉权限错误的 `glob()` 把恢复锁误判为空，停止入口仍保留。

普通实验页在接收 WebSocket 进度或结束事件时作废此前的 REST 请求。同一选择仅保留一个在途进度请求，6 秒超时后提示状态未确认，保留上次快照供停止操作使用；重新获得有效进度前禁止启动或恢复。图形编辑器对缺失的参数/等待映射显式创建 YAML 节点，模板批次对省略或 null 的 metadata 同样处理，避免 YAML 1.1 隐式生成 `!!omap` 或在普通 JS 对象上继续调用节点操作。

Campaign 参数与表征指标递归检查数值是否有限，含嵌套结构；NaN、Infinity 或 `1e309` 形成的溢出值返回 HTTP `400`，不写入数据，合法字符串、布尔值和 null 不因数值检查被转换。已有 Campaign JSON 或恢复日志若空白、损坏、结构非法或含非有限数值，按存储不可用返回 `503` 并保留原文件，不将坏文件当作空库覆盖，也不自动修复历史。

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
- 原始微波 REST `/stop` 在等待实验注册锁前调用 `request_microwave_stop()` 发布内存停止代次，取消在途启动尚未发出的核对或 START；此阶段不访问设备。实际 STOP 仍经原注册锁及设备控制锁执行、读取确认，不绕过实验占用协调。未知设备返回404。
- 微波配置的温度与保温偏差寄存器使用整数℃，未发现协议定义的小数缩放。驱动在任何写入前拒绝非整数；REST 共用模型、编排校验、YAML 解析、托管程序及引导请求同样校验，允许 `50.0`，拒绝 `50.9`。测量温度的浮点精度不变。
- `StepExecutor.execute` 在失败返回前保存驱动原始错误，避免后续 STOP 清理清空或覆盖它；微波到温/降温等待失败使用等待自身诊断。超时包含目标、容差、最后温度、扣除暂停的时长及控制状态/字。微波 configure/start/stop REST 失败响应优先返回 `get_last_command_error`，无详细原因时保留通用 HTTP 400。
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

`src/experiment/microwave_program.py` 使用既有 `ExperimentEngine`、`StepExecutor` 和运行日志：每个逻辑段编译 configure/start/monitored_hold/stop 四步，start 的到温等待要求目标±3℃连续稳定30秒，之后按设定时长普通计时保温。稳定期间越界或实际暂停重置稳定窗口；计时保温期间温度偏离仅提示记录，不冻结或清零计时。确认停止后切换下一目标。五个硬件段为同一目标及 `ceil(heating_timeout) + hold_seconds + 60` 秒保护时长，连续稳定包含在 heating_timeout 内，最大99时59分59秒，超出则写入前拒绝。启动后复核本次已知参数块，读回一致不能证明未公开的运行方案。段间停机，方案映射及计时重置仍须实机验收；原始REST/YAML不自动改用此计时策略。

完整程序注册在共享 `_engines`，与普通/引导实验互斥，运行和清理期间保留占用，阻止手动写控制和断开；手动停止及全局急停先禁止后续步骤。托管不暴露暂停/恢复，通用实验暂停/恢复端点对此返回409，避免冻结电脑计时而固件仍加热。原子记录位于 `output/microwave_programs/mwprogram_<request_id>.json`，启动意图必须先落盘，每步先保存进度；存储失败停止并保留锁，日志保存失败也显式报告。重启后未完成或待清理记录视为中断，锁住实验和手动运动控制；可连接、读取、停止后人工确认解除，解除记录保存失败仍锁定。页面/WS生命周期只读，服务正常关闭等待托管停机；进程崩溃无法保证立即停机，长硬件计时不能替代独立联锁。

- 实时采样在 Web 层并行读取加热器、蠕动泵、微波、阀和注射泵，各类内部仍顺序读取；转盘保持本轮最后读取，避免其他慢读消耗其独立 `read_at` 的6秒有效期；复用 `DeviceReadCoordinator` 的在途读取及现有设备/串口锁，避免整轮耗时逐类累加导致正常状态跨过前端6秒控制有效期。仍等待本轮结果后推送，不通过重复旧帧续期；真实慢读、超时或断线仍可能触发过期保护。驱动保持同步，采样不下发控制动作。
- WebSocket：实时 payload 包含 `microwaves`；各类设备读取超时（包括 Python 3.10 中不同的 `asyncio.TimeoutError` 与内置 `TimeoutError`）写入 `{"error": "read_timeout"}`，其他读取失败写入 `{"error": "read_failed"}`；WebSocket connect/disconnect 不控制硬件生命周期。
- 泵实时 payload 的每个通道包含 `running` 和 `read_ok`。历史 `flow_rate` 是设备设定/报告值，只有读取有效且确认运行的区间才表示软件确认的输运区间，不等价于外部流量计实测。

- `useWebSocket()` 的 `connected` 仅代表传输连接，建立后立即显示服务器通信正常；设备数据的等待、过期和未知单独显示。控制消费者的 `fresh` 为 6 秒，仪表盘使用独立的 `monitorData` / `monitorFresh`，有效期为 `MONITOR_FRESHNESS_MS`（15 秒）。`monitorState` 区分 connecting、waiting、live、stale、disconnected。实时包增加 `sampled_at_ms`（整轮采集结束的epoch毫秒），快照按原采集时间计算剩余有效期，旧帧不能覆盖新当前状态；旧服务缺该字段时兼容按接收时间处理。断线及最后一个订阅者卸载清空当前读数，各自超时只失效对应读数，旧 socket 回调不能覆盖新连接。
- `ConnectionManager` 从原有采集循环缓存最近1800帧趋势（温度、设温、流量及错误），无客户端时也保存；不增加设备读取、串口命令或后台设备轮询。首连注册连接后，通过每连接发送锁先发 `{type: monitor_history, frames: [...]}`，再发保留原时间的完整实时快照（`snapshot: true`），实时广播在该锁后发送，保留回放期间到达的采样；其他实验消息不进入缓存。历史仅填 `monitorHistory`，不恢复当前状态或控制资格；服务器重启清空内存缓存，不能恢复加载此版本之前的未缓存采样。
- `utils/monitorHistory.ts` 按服务端时间合并、排序去重服务器历史和SPA已收样本，`revision` 驱动补历史后的重绘，每条曲线最多1800点。加热器PV/SV独立校验；15秒以上间隔、设备读取失败/缺失保留空缺，真实历史覆盖断连期间时可补回实测曲线。泵必须有明确读取有效和运行状态，未知状态不能作为零流量。最后有效温度只用于灰色历史展示，不恢复当前状态。浏览器刷新后重新读取服务器缓存，不补造、不持久化。开发演示使用隔离的同类缓存和相同过期阈值。加热器图保留每台PV/SV各一条，设温相同时提示重合，绝不偏移坐标制造分离。
- 泵历史记录只接受显式 `read_ok=true` 和布尔 `running`；缺失值保留未知。`flow_unit` 缺失记为 `UNKNOWN`，一次记录中有效读取的单位发生变化记为 `MIXED`，已有 JSON 字段及数组结构不变。历史前端核对采样时间对齐，未知区间不补零、不跨越未知区间生成累计体积；RPM/未知/混合单位不积分。已有旧记录无法补造单位或运行证据。
- `protect_guided_devices` 同样保护普通 `ExperimentEngine`，在共享注册锁内拒绝运行、暂停及清理未确认期间的手动写入；只读请求不占锁，停止请求先设置活动引擎停止标志。函数名为兼容现有阀和注射泵路由引用而保留。

- 普通 Web YAML 使用 `PersistentExperimentEngine`（`src/experiment/yaml_recovery.py`），沿用同步执行器和原引擎。`output/yaml_runs/yaml_<uuid>.json` 保存启动意图、源文SHA256、步骤位置、run_id/sample_id和清理/恢复状态；同目录原子替换前flush/fsync。首次保存失败不执行动作，每步前保存失败请求停止并清理；完成清理和日志持久化后才能释放运行占用。`save_log=false` 不关闭恢复记录。引导/托管仍使用各自持久记录，未改它们的引擎语义。
- 新增 `GET /api/experiments/recovery/pending` 与 `POST /api/experiments/recovery/{recovery_id}/acknowledge`；后者严格接受 `{"devices_stopped_confirmed":true}`。重启后非终态/待清理/存储失败记录成为中断锁，不续跑；所有实验启动及手动写控制受共享恢复检查约束，读取、连接及停止入口保留（当前live占用仍遵守原连接保护）。人工解除在注册锁内执行；live任务未结束或停止未确认返回409，记录损坏/不可读或解除保存失败返回503，不清除锁。正常日志/样品和恢复记录分开保存；删除历史不会解除恢复锁。旧版本未保存过的启动意图不能追溯补造。
- `GET /api/devices` 的加热器条目新增 `min_temperature`、`max_temperature`，后者为配置最大温度与安全限值的较小值，供输入校验使用；设备端校验仍为最终约束。
- 泵整机错误、缺失设备或缺失通道的采样为已有通道追加未知点，避免历史积分跨过已知的读取空窗；完全没有采样事件的时间不能还原真实流量。
- 全局急停 `POST /api/devices/emergency_stop` 保留顶层 `success`，并返回 `devices` 明细；每项包含 `device_type`、`device_id`、`connected`、`attempted`、`command_result`、`final_state`、`success` 和 `reason`。已注册但未连接、命令失败或最终状态未确认都会使总体结果失败。
- 实验日志：`ExperimentLogger.record_sensor_data()` 会把实时 payload 中的微波仪 `material_temperature`、`power_percent`、`current`、`runtime_seconds` 分别保存到 `sensor_data.microwaves[device_id]` 下，供历史记录实验报告绘制微波温度、功率和电流曲线。
- 控制开放：按 2026-06-20 用户确认，`allow_real_hardware_writes`、`enable_control_writes`、`allow_experiment_control` 当前默认 `true`，且不再作为手动 REST/前端或 YAML 自动控制的阻断门；字段保留在配置和 payload 中用于兼容旧状态展示。
- 防错边界：普通配置批量写入仍拒绝覆盖控制字 `40151`；多段配置会先完整校验并转换全部段，任一后续段非法时不会写入前序段；完整配置写与 start/stop 使用同一设备锁，不能交错成“配置一半即启动”。总线在实际写入途中失败仍可能留下已写前序寄存器，不能把多次 Modbus 写误认为事务原子。
- 控制竞态：`DeviceManager` 对同一加热器或微波仪的写控制做串行协调，并用 stop 请求代次取消更早进入但尚未执行的 start，避免 stop 已返回成功后旧 start 再启动；全局急停和 shutdown cleanup 执行期间的新 start 会被拒绝。主动断开和 cleanup 按同一设备锁先 stop，stop 返回 `False` 或异常时保留连接供重试，不得继续 disconnect。
- 串口资源：AIBUS 与 Modbus RTU 在打开串口前统一通过 `SerialPortManager` 取得进程锁并登记句柄；同一进程内重复占用同一端口会被拒绝，连接失败或断开时会释放锁和句柄。管理器只登记 `atexit` 资源清理，不启动超时看门狗、不接管 `SIGTERM` 或调用 `os._exit()`；Web 服务由 Uvicorn/FastAPI lifespan 先执行设备 stop/cleanup，辅助 CLI 由应用级信号处理器执行同样的停机流程。
- 失败传播：设备返回 `False`、timeout 或异常必须向上传播为失败；WebSocket 和页面加载不能触发写入。
- 实验引擎：`microwave.configure_*`、`microwave.start` 和 `microwave.stop` 直接调用 `DeviceManager`，行为与加热器/蠕动泵动作一致，设备方法返回 `False` 时步骤失败。实验自然结束也会清理本次启动的设备；清理失败时运行标记为 `failed` 并阻止同一引擎重新启动，直到重试停机成功。普通实验、引导批次和托管程序在服务正常关闭时统一请求停止并等待记录收尾；清理未确认时 API/WS 暴露 `cleanup_pending`，前端保留重试入口。

fake 测试只能证明地址换算、参数校验、失败传播、API/WS payload 和 executor 调用链。真实串口、接线、写入顺序、浮点字序、运行状态、故障码 bit、门控联锁和 stop 语义必须由实验室按 [microwave_smoke_test.md](microwave_smoke_test.md) 人工确认。

`duration` 使用 `time.monotonic()` 统计未暂停的实际经过时间。事件循环延迟计入持续时间，暂停时间排除，等待循环保持短间隔检查 stop，避免按理想 sleep 分片累计造成系统性超时运行。

加热器到温、蠕动泵完成及微波完成等待，在同步读取返回后再次检查停止、暂停及超时；在途读数不能使已停止、暂停或超时的等待判定成功。同步串口调用本身仍受原有超时限制，不强制终止驱动线程。

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

普通 YAML 启动入口复用编辑器的整份源文校验，再解析同一份内存文本；无效参数在注册引擎或调用硬件前拒绝。急停先发布共享停止代次并派发设备停止，待启动请求及引导/托管预检在注册前复核代次；不绕过设备控制锁。历史删除的存储失败返回 HTTP 503，允许重试；缺少日志的有效 run_id 也可清理此前遗留的样品行。

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

合并前按 [AGENTS.md 的验证矩阵](../AGENTS.md#6-validation-matrix) 与 [测试指南 10.1 节](testing_and_merge_flow.md#101-按变更类型选择验证) 确认：

- 代码改动与文档改动一致
- 仅文档、规则或 Skill 改动完成 diff 和内容一致性检查
- 后端改动完成 metadata、相关导入及受影响的行为检查；前端源码改动完成生产构建
- 硬件控制语义改动另由用户／实验室确认实机 smoke test
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

`src/experiment/guided.py` 定义严格请求模型、后端条件组合、固定液路完整 recipe 和 GuidedBatch。调用原 parser、StepExecutor、ExperimentEngine 和 ExperimentLogger，每组一个真实运行及 sample_id；不用另建驱动或后台串口线程。总组数（含重复）不超过固定 turntable1 配置的 bottle_count，本机 12；每组最多 10 次清洗；加热温度及剂量以当前设备配置范围校验。

`/api/guided/preview` POST 只生成校验完整流程，返回 rows、recipes、yaml 和 total_groups，无硬件访问。请求 axes 是六个非空且不含重复数值的数值列表，依次为 A/B 温度、A/B 剂量、反应温度和保温分钟。repeats、speed_a/b、drain_flow、clean_volume、clean_flow、clean_dwell、clean_cycles 配置组合及固定操作。product_port 仅接受 NO（默认 NO），废液固定 NC；product_drain_seconds 与 clean_drain_seconds 均必填，0.1–9999 秒，分别用于正式收产物及每次清洗排液；clean_direction、drain_direction 指定现场泵向，plumbing_confirmed 在开始时必须为 true。默认 heating_timeout=600、syringe_timeout=120、cooling_timeout=3600，均可在模型范围内调整。

`/api/guided/start` POST 不携带 priming_batch_id 时，读设备就绪状态、预留注射泵、阀和转盘、原子保存计划，启动包含机械回零、初始化、预充及正式组的后台任务。预充成功后核对设备配置签名并严格重查可信零位等就绪状态，再自动开始正式组。`/prime` 保留单独预充能力；`/start` 携带同批 priming_batch_id 时沿用该预充结果，核对签名、重查就绪状态后只启动正式组。注册到原 experiments._engines 并使用 _source_lock，整批占用期间阻止其他实验启动。设备 REST 写入与批次注册串行；引导批次占用时拒绝手动配置/启动/断开，手动停止会同时请求停止整批。注射泵及阀保持既有所有权，跨组保留直到最终清理，普通实验默认清理行为不变。

GET `/api/guided/current`、`/api/guided/batches`、`/api/guided/{batch_id}` 返回状态、当前组、进度和单组 run_id/sample_id。POST `/{batch_id}/pause|resume|stop` 控制整批；stop 的 success=false 代表清理或保存未确认成功。逐组收取自动执行，没有换瓶确认接口或等待步骤。

双泵排液使用 syringe_pair.dispense，协调位于 StepExecutor 上层，每台同步 Controller 保持原锁与所有权。两路并行下发后分别监督完成，一路失败即停止两路；对整个双泵步骤执行暂停边界语义，不保证硬件同步触发。生成流程显式吸取本组剂量，正式进料不隐式回零；每批通过明确确认的预充入口依次执行已有 syringe_pump.initialize，确认完成及可信零位后才吸排预充液。

微波停止后使用 microwave_temperature_below，material_temperature 必须为有效非负有限数字且 ≤45℃，同时要求 fault_code=0、status_confirmed=true、control_active=false、output_active=false、stop_confirmed=true，read_ok 不得显式为 false；温度或停止状态未知、控制仍开启均不放行。收取前重复此检查，再切换产物出口及抽液。通道四排液使用 FLOW_MODE 及软件定时停泵，通道三清洗进液保留 TIME_QUANTITY、pump_complete 和显式 stop_channel；理论流量不冒充实际排空传感器。

启动前将完整 recipes 与请求快照单独保存至 output/guided_batches/plans/{batch_id}.json，GET /api/guided/{batch_id}/plan 可读取；单组 metadata.recipe_file 指向该快照，recipe_group 指明组号。批次 JSON 原子保存至 output/guided_batches，保存完整请求、组状态、当前步骤、run_id/sample_id 和 persistence_status；单组继续使用原实验历史及样品记录。保存失败不启动下一组，cleanup_pending 保留不确定停机的占用。服务重启后没有 live runner 的非终态或待清理记录标记 interrupted/recovery_required，所有实验启动入口均阻断。POST `/{batch_id}/acknowledge-interrupted` 需 devices_stopped_confirmed=true，人工确认后解除锁定但不续跑。

前端仅在显式按钮操作时发控制请求；定时读取状态及页面/WebSocket生命周期不启动或停止硬件。Campaign/planner 无自动连接。软件验证不替代设备验收。 BatchExperimentPage 启动成功或首次恢复批次时切换到集中进度视图，复用每 2 秒 GET /current；完成组数取 groups 的 completed 状态，当前动作由可选 progress.activity 展示；旧记录沿用 step_label。各组待执行条件取批次 request 快照，执行结果取 groups；整批用时取顶层 `elapsed_seconds`，由批次单调时钟从启动计至最终清理结束，包含暂停，终态冻结并随检查点保存。`progress.elapsed` 仍为各引擎运行用时，转盘编排不会影响整批计时；缺少 `elapsed_seconds` 的旧记录显示“未记录”，不以墙上时钟或当前组用时推算。读取失败保留最后状态并提示过期，不触发控制请求。


### 引导式转盘编排

引导式 `/api/guided/start` 和 `/api/guided/prime` 在启动入口读取已连接转盘的新鲜状态，新建批次在其他设备预检完成后、登记执行前再读取一次。读取复用 `DeviceReadCoordinator` 的在途查询及设备锁，然后执行原有内存空闲检查和停止代次校验；不通过扩大 6 秒有效期绕过检查。读取失败、超时、非停止状态或未确认停机均拒绝启动；这些检查只读取，不自动连接、回零或停止设备。

`GuidedRequest.turntable_drip_seconds` 为必填数值，范围 0–3600 秒，允许显式 0，不提供默认标定值；`bottles_confirmed` 默认为 false，preview 可为 false，start/prime 必须为 true。preview、预充启动及正式启动均检查固定 turntable1 已配置且启用、瓶位与回零/定位功能有效，并核对总组数不超过 bottle_count；缺字段的旧计划仅只读展示，不自动补值或复用预充资格。滴液时间进入参数签名及本机草稿，现场确认不进入草稿且修改参数后清除。

`src/experiment/guided_turntable.py` 的 `GuidedTurntable` 在批次上层复用同步控制器及原设备锁，执行准备、组间换瓶与收尾；不新增公开 YAML 动作，不在驱动中增加轮询。准备阶段先确认泵停止并切 NC，再机械回零、确认 1 号瓶，随后才初始化和预充；组间在本组产物收取、NC 清洗及停泵确认后执行单调时钟滴液等待，再以最新后端瓶位证据换下一瓶。机械原点已对齐 1 号，不另加 270°。最后一组不调用会循环复用的下一瓶动作，而在清洗、滴液等待和全停机后回零。暂停保留步骤与瓶位，不重放动作；停止/故障停止在当前位置，不自动回零或续跑，保留既有恢复锁。批次持有转盘占用，手动运动、回零、断开被拒绝；停止入口仍可请求停止整批。

状态新增 `phase=preparing|indexing|finishing`，原 priming/ready/experiments 保留。`preparation` 与 `finalization` 均含 `status=pending|running|completed|failed` 和可空 `error`；`turntable` 包含 `device_id/current_bottle/target_bottle/operation/status`，其中 current_bottle、target_bottle 和最新控制器摘要 status 可空。operation 为 pending、homing、settling、indexing、ready、stopped 或 failed。瓶位只显示后端确认值，不从当前组或坐标推算。步骤标识包含 `turntable_home_start/turntable_next/turntable_settle/turntable_home_finish`，前端将换瓶与收尾显示为第七阶段。

每个 groups 条目保存 `bottle_number`、`collection_status=pending|collecting|collected|possibly_partial` 及可选 collection_error；正式运行 metadata 保存 `bottle_number/collection_device_id/collection_status`。收取故障或中断不能标为完整收取。准备/收尾不增加科学样品或单独运行日志，事件保存在批次 `turntable_events`，完整 plan 的 `collection` 保存策略。完整导出保留批次事件、计划及预充和正式组日志。所有组 completed 而 finalization failed 时保持组和样品结果，界面单独提示收尾回零失败；新批次只有最终回零 completed 且无清理/恢复阻断才显示完整成功，旧历史无新增字段仍可查看。

软件检查使用假设备，不确认实际滴液、瓶口对齐、整批换瓶及回零联锁；需按转盘验收文档做现场确认。本次生产构建仅输出到 `output/turntable-review-build`，不覆盖在用静态资源、不构建或安装桌面包。

### 引导批次预充接口与状态

正式组的 `microwave_config` 与托管采用同样的五段覆盖策略：五段为当前组目标，保护时长 `ceil(heating_timeout) + hold_seconds + 60`；逐段写后读回，启动后再次有限读回本次参数块，不一致或读取失败则失败清理，不自动重写或重启。新编译流程到温等待为 `microwave_temperature_reached`、tolerance=3、seconds=30、timeout=heating_timeout，保温等待为 `microwave_monitored_hold`、目标温度、tolerance=3、hold_mode=timed、seconds=hold_seconds、timeout=hold_seconds（零秒时timeout=1），随后显式停止，不猜方案或起止段寄存器。新批次及导出YAML采用新规则，历史计划不改写；实际运行方案仍须厂家协议与实机确认。

引擎首次进入 completed/failed/stopped 时冻结 `progress.elapsed`，新运行启动时重置，暂停仍计入累计用时。批次检查点保存 progress，服务重启后可读取最后保存的用时。终态新建清空表单，沿用参数新建只复制保存值；两者清除名称、校验和启动确认，保留旧批次记录；恢复锁定沿用 acknowledge-interrupted，解除时保留原失败原因，不改写为服务中断。

`POST /api/guided/start` 无 `priming_batch_id` 时创建完整批次，初始化与预充成功后自动执行正式流程，任何准备失败或停止均不进入正式组。`POST /api/guided/prime` 保留为单独执行前置预充的接口；`/start` 携带 `priming_batch_id` 时只启动该批次签名匹配且预充成功的正式流程。创建整批和单独预充共用锁内的就绪、占用及服务中断检查；执行中重复启动返回 409，不创建第二个运动任务。`/preview` 增加 `priming` 流程，仍只校验、不控制硬件。`/prime` 携带已有批次 ID 且签名一致时返回现状，不重发运动。

GuidedRequest 新增 `prime_volume_a/b`（默认各 2 mL，须不超过实际泵容量）、`prime_cycles`（默认 2，1–10）、`prime_drain_seconds`（必填，0.1–9999 秒）、`prime_drain_flow`（必填，0.01–9999 mL/min），以及必填正数 `reactor_available_ml`、`source_available_a_ml`、`source_available_b_ml`、`waste_available_ml`。请求新增必填 `initialization_a/b` 对象，各含 `direction`（Z/Y）和 `initialization_code`，复用 SyringeCommand 校验并在编译时检查容量适用性；新增 `initialization_confirmed`（默认 false）。启动预充和正式运行均要求四项现场确认 `initialization_confirmed`、`priming_confirmed`、`plumbing_confirmed`、`bottles_confirmed` 为 true。初始化及滴液时间参数纳入预充签名，确认标志不纳入签名；缺少初始化参数的旧请求被拒绝，旧记录仅供查看。容量校验涵盖预充总量、正式单组量、整批耗液和清洗废液。

批次 checkpoint 新增 `phase`（preparing / priming / ready / experiments / indexing / finishing）和 `priming`（状态、SHA256 签名、已完成循环、步骤设备结果、run_id、持久化状态、失败停机确认）。计划快照包含独立 priming recipe。签名覆盖完整实验参数及固定设备配置，排除确认标志和批次 ID；正式启动前再次只读检查连接、故障、零位及输出停机状态。签名不符拒绝启动；设备状态异常会失效结果并设置恢复锁。

预充复用同步设备驱动、现有 StepExecutor、ExperimentEngine、资源预留和日志；不新增设备动作或 YAML 动作类型。一键启动的预充成功后自动进入 experiments，保留所有权；只有单独调用 /prime 的批次进入 paused/ready，其普通 resume 被拒绝，必须调用 start。失败会停止两台注射泵（含未启动那台）及排液通道；任何 False 或停机异常保留未确认状态，并可再次停止重试。恢复锁必须人工确认后通过现有 acknowledge-interrupted 接口解除，此接口也处理本服务中的预充失败。服务重启后 ready 不可自动复用或恢复。

预充排液使用 prime_drain_seconds / prime_drain_flow；正式收集及清洗排液使用 drain_flow 和各自独立的 product_drain_seconds / clean_drain_seconds。三处均下发 FLOW_MODE，流量单位 mL/min，时长作为编排参数 flow_duration_seconds，不向设备写时间或分装体积。清洗进液仍按 clean_volume / clean_flow 计算时间。每次清洗先 valve.switch NC 再进液，收产物固定 NO。单组 metadata 记录两个排液时长及 theoretical_product_volume_ml，名义排量不能冒充真实样品量；旧 prime_drain_factor、prime_extra_seconds 不再接受为新请求字段。前端高级容量设置默认折叠但继续必填，产物、清洗与批次确认页面移除理论排液时间和估算按钮，清洗页同步显示共用排液流量；预充页也不提供估算按钮；旧记录的旧公式转换仅用于显示，不更新持久化签名、不创建 live runner，也不允许复用旧预充资格。

### 自动化保护等待与计时

`StepExecutor` 在编排层执行 `microwave_monitored_hold`：复用已有每秒读取。`WaitCondition.hold_mode` 允许 qualified（默认）和 timed；qualified 保留旧目标YAML按相邻有效且达标样本累计的语义，越界不累计，实际暂停后重新建立采样边界；timed 按单调时钟普通计时，温度偏离只提示和记录。无目标旧YAML仍为纯计时监督。`microwave_temperature_reached.seconds` 表示连续稳定秒数，默认0兼容旧YAML；越界或实际暂停后重置稳定窗口，总到温超时包含稳定时间。新引导式和托管编译为目标±3℃稳定30秒后timed保温，温度调节和硬件控制判断不变。控制退出、状态未知、无效温度或故障始终先于完成判断；单次读取或采样间隔超过 `1 + 3 * microwave.config.timeout` 秒失败，默认7秒。保温计时及超时扣除实际暂停，引导式反应中的待处理暂停请求不扣时。失败返回False并进入既有清理与恢复锁。

状态响应只增加可选字段：引导式 `progress.activity` 与托管 `activity` 含 `hold_mode`、`qualified_seconds`、`hold_in_band`、`hold_timeout_seconds`。timed 下 `qualified_seconds=null`，`elapsed_seconds`/`duration_seconds`/`remaining_seconds` 是普通保温计时，`hold_in_band` 仅作提示；qualified 的剩余按有效时间计算。稳定到温由已有稳定窗口读数展示，页面不自行累计。步骤结果保存 `hold_summary`，新流程metadata中的 `microwave_hold_policy` 保存稳定容差、30秒稳定要求及计时后温漂继续策略；旧记录缺字段按原有效保温信息展示，不改写历史。

同步驱动的 `last_command_result` 保存配置块预期/实读、控制字及新鲜启动前后快照。启动顺序为读取空闲状态（控制关闭、无输出、无故障）→单独写模式位（START清零）→复查空闲→有限核对本次参数块→再次读取空闲→写模式位及START→既有有界启动确认→有限核对同一参数块及运行状态。模式位为只写，不用其回显或40114未知枚举确认实际模式；无固定延时、无后台轮询、无参数自动重写或启动重试。当前连接会话只在完整配置成功后保存预期寄存器；配置失败、参数核对失败或断开使其失效。无本会话配置的原始手动启动可沿用HMI，但标记 `configuration_verified=false`，不能声称方案已确认。设备管理器在原控制锁内进行有界核对，执行器透传停止检查回调；引擎停止请求或停止代次变化使尚未发出的核对读取取消，已在途的同步读取仍等待返回再清理；原布尔控制接口和REST请求不变。

启动诊断新增 `pre_start_blocks`、`pre_start_configuration_verified`、`before`、`after_mode_selection`、`before_start` 及各快照时间，记录两次控制字写入和是否已尝试。原始REST启动通过管理器内部 `cleanup_on_failure=True` 在同一控制锁内处理失败：仅本次已尝试模式/启动写入时发送failure_cleanup STOP，取消更早排队启动并分别保存原始失败及 `failure_cleanup` 结果；写入异常同样清理，停机未确认明确报错。启动前已有运行、未知、故障、无有效配置或停止请求导致的无写入拒绝不发送STOP。实验执行器仍使用既有清理入口，避免重复清理。

设备管理器仅从已有调用生成诊断事件，内存保留最近200条，执行器在既有读数/步骤及清理边界增量收集到运行JSON的 `microwave_events`；缓冲缺口显式记录 `diagnostic_gap`。配置、启动和正常停止事件同时进入对应步骤 `device_result.microwave_events`；清理事件保留在运行级列表，避免覆盖原始失败。终态后的恢复清理诊断再次原子保存至同一日志，不改写终态、结束时间或样品记录；保存失败标为持久化错误。事件含设备、序号、UTC时间、动作、来源、结果；停止来源区分 experiment_step、user_stop、failure_cleanup、normal_cleanup、manual_stop、emergency_stop、disconnect、service_cleanup。已有采样曲线补充控制字、段号、模式原码、故障及温度源；状态变化和计时归零复用已有读取，不增加驱动后台轮询。未发现本系统STOP时只报告设备侧退出或外部来源未确认，不猜厂家模式枚举或浮点字序。

引导式正式单组启用 `finish_reaction_before_pause`。微波启动至显式停止之间设置 `pause_pending`，不清除运行事件；停止成功后才真正暂停。停止请求清除 pending 并中断等待，恢复不重放。`GET /api/guided/current`、批次状态及普通实验 progress 响应增加布尔 `pause_pending`（普通实验默认 false）；路径不变。页面显示 pending 与 paused 两种状态，pending 时 resume 取消暂停请求。

固定等待和通用条件超时使用单调时钟。实际暂停起止由引擎通知执行器，等待时钟扣除真实暂停累计值；微波阶段 pending 不是实际暂停，持续计时。注射泵已发动作仍完成并持续读 Q。短蠕动泵动作的本次启动读回证据按设备及通道保存，等待消费一次；有效 STOP 才完成，未知或 PAUSE 不通过，新启动/停止/清理清除证据。

`compile_plan` 检查固定设备启用、通道启用和流量上限，模型检查预充、单组和每次清洗的反应器容量及源液/废液总量。`preflight` 在预充与正式启动前重做编译校验，再执行只读就绪检查；不连接或发送动作。预充入口使用 before_initialization 检查，允许故障码 0/7、位置未确认的空闲泵，其他故障阻止启动；正式入口仍要求 fault_code=0、已初始化、可信零位。预充流程在温度检查后显式执行两台泵的初始化，失败沿用批次清理及恢复锁。保存 YAML 的覆盖保护只检查文件实验注册键，批次标识不作为文件路径解析。预充维护 sample_id 由 logger 使用 batch_id 和 run_id 生成，CSV 保留 PRIMING 标记及维护 notes；历史编号不迁移。

软件回归入口：`tests/test_automation_safety_fixes.py`（时钟、状态联锁、暂停/停止、容量/流量、真实临时 CSV、文件保存），并执行既有后端和前端回归。实机验收按微波和注射泵验收文档回填，不用模拟器结果标记实机通过。

引导式正式组启用 `keep_heaters_on_completion=True`：移除反应前 heater.stop，成功组完成仅调用 `stop_active_devices(preserve_heaters=True)` 清理其他活动设备，保留加热器跟踪及批次资源。选择性清理不缓存为全停机，且仅在外层保留资源时生效；选择性清理失败则执行全清理并判本组失败。预充成功同样保留加热器；单独预充的 ready 等待期间继续保温并保持占用。普通实验及失败/停止仍全清理；整批 finally 关闭加热器。下一组重新设置目标并等待到温，暂停期间持续保温。批次 cleanup_required 包含未停止的活动设备，最终加热器停机失败必须持久化恢复锁定，服务重启也不能绕过。新排液时间进入完整请求签名，旧记录不回填或复用预充资格。

引导式每组使用 `heater_pair_stable` 等待：两个显式目标、tolerance=3、seconds=30、timeout=precursor_timeout（默认3600）。StepExecutor 在上层每秒读取两路温度，单调时钟连续计时；越界或实际暂停重置窗口，读取失败/无效值/超时立即失败。初始化进度记录为 prime_initialize_1/2，复用既有动作日志及维护样品编号，不改变微波自动功率配置。

加热预充流程：`prime_initialize_1/2` 后执行 `prime_heat_0/1_set/start`、`prime_heat_both_reached` 和 `prime_heat_duration`，然后才吸排液。`heater_pair_reached` 在既有双路等待循环中检查两路同轮有效读数均 `pv >= target_temperature`，目标取第一组条件；超过目标也视为达到，不要求容差或稳定时长。保留现有读取频率、故障、无效值、暂停、停止及 `precursor_timeout` 检查，不在设备层新增轮询。`prime_recheck_temperature` 等待反应液 ≤45℃ 后排废，超时/读温失败禁止排液。预充引擎启用 `keep_heaters_on_completion=True`，停止/失败仍全清理。签名使用 `priming_protocol=turntable_collection_v6` 并包含 heater1/2、config.turntables 等固定设备配置，旧预充签名不再匹配；旧流程快照和 YAML 不改写，正式组的 `heater_pair_stable` 及微波规则不变。

引导式 `prime_heat_minutes` 为必填数值（0–1440分钟、可换算为整秒），纳入预充签名。两路 heater.start 后先执行 `prime_heat_both_reached`；通过后 `prime_heat_duration` 使用既有 duration 等待，温度波动不改变计时，实际暂停扣时、停止可中断。`precursor_timeout` 独立控制预充及各组双路到温等待，默认3600秒，上限7200秒；原 heating_timeout 仍用于微波（默认600秒）。旧请求缺少加热时长不能新启动，旧记录不迁移或自动补0；签名包含本轮转盘配置与收集策略；旧预充结果不能直接获得新流程资格。


引导式 `GuidedRequest.experiment_name` 必填：严格字符串，去除首尾空格后1–80个Unicode字符，拒绝控制字符、格式控制及行/段分隔符，允许重名。名称纳入请求签名，保存到批次/计划顶层及流程metadata；运行name分别为“名称 · 预充”和“名称 · 第 N 组”，沿用现有历史接口及导出。旧记录只读兼容，不自动补名称，不复用旧预充资格；新请求缺少名称返回422。ID生成规则不变。

引导页使用 `?new=1` 标记新表单，独立于 `/api/guided/current` 返回的最近批次。终态轮询不覆盖新表单；运行/暂停、清理、恢复或持久化错误优先展示旧批次。每次刷新及显式切换递增响应序号，过期响应不得恢复参数。成功启动清除新建标记和本机草稿；刷新新建页按下述版本化草稿规则恢复输入。现场恢复确认只解除锁定并保留结果页，不自动续跑或创建新批次。


### 控制页批量连接协调

控制页通过前端 connectionBatch 协调现有单设备 connect 和只读状态接口，无新增后端 API。按设备类型及 ID 顺序逐台连接，明确检查 success，并将连接成功后的读取失败区分为“已连接，状态未知”。单台普通失败继续，HTTP 409 占用/冲突中止后续请求；急停入口及页面卸载取消未发出的请求，不通过页面生命周期断开或停止设备。

DeviceConnectionControls 统一连接按钮，利用页面提供的批量运行状态禁用冲突操作，并登记当前单设备操作的 loading 状态，避免与批量连接交错。驱动、资源锁及实验占用检查继续由既有后端执行。测试通过模拟 API 执行真实控制页处理函数，不连接硬件。

### 引导式只读动作快照（2026-10-16）

`GET /api/guided/current` 和既有批次状态响应的 `progress` 增加可选 `activity`，现有字段、请求与 YAML 不变。快照包括 `step_id/state/wait_type`、`stage/title/description/device_ids/parameters`，以及可用的 `readings/devices`、`elapsed_seconds/duration_seconds/remaining_seconds/reference`、`stable_seconds/stable_required_seconds`。阶段标识依次为 preparation、stabilizing、feeding、reaction、collection、cleaning；未知动作不推断阶段。温度读数包含 device_id、value、target、read_ok、tolerance、sampled_at；读取失败的值为 null。

`StepExecutor.activity_snapshot` 只复制执行时已有的观测；`ActivityProgress` 不访问设备。双路稳定循环记录实际稳定窗口，暂停清零；duration/monitored_hold 使用原暂停扣时单调时钟。泵在原 START 确认后记录单调时钟，reference=true 的剩余时长不因编排暂停冻结，也不参与完成判断。并行进料聚合子执行器已缓存的状态。切换步骤、装载新组时清除观测，步骤退出冻结快照，展示不改变驱动调用顺序或数量。引导层再按编译步骤生成动作说明，通用执行器不解释引导阶段。

预充前到温快照的 `wait_type=heater_pair_reached` 表示两路温度按“≥各自目标”判断，不显示连续稳定倒计时；旧记录的 `heater_pair_stable` 继续按原容差和稳定时长展示。

状态顶层新增 `stop_requested` 和 `cleanup_in_progress`；后者观察执行器清理及预充失败清理的在途调用。原 `cleanup_pending` 仍保留其资源/恢复含义，不能把它当作“正在清理”。已结束批次可能保留 stop_requested=true，客户端须优先判断终态。

前端保持 2 秒轮询，不自行递减动作剩余时间；独立检查距成功响应是否超过 6 秒。控制命令使用响应序号，停止可以覆盖待确认的暂停/继续；较早响应不得覆盖停止反馈。网络失败只通过读取核对，不自动重发。字段定位由本地校验及 422 loc 映射，设备/跨字段错误仍为页面提示。

历史页支持 `/history?batch_id=...`。使用日志 metadata.batch_id 与批次保存的 priming.run_id、groups[].run_id 取并集，绝不通过实验名称猜测关联。批次导出逐条读取并核对全部 run_id，沿用 `{exported_at,count,runs}` JSON 格式（另带 batch_id）；缺记录或读取/持久化错误整体失败。旧记录无 activity 时沿用步骤名称，不制造读数。


### 引导式流量排液的定时停止

`pump.start` 可选编排参数 `flow_duration_seconds`（0.1–9999 秒），仅允许显式 FLOW_MODE、启用、on_error=stop、无额外 wait，并禁止设备时间/体积/重复参数；解析及执行前均校验。REST StartPumpRequest 不新增字段，DeviceManager 和同步驱动接口不变。三处排液在同一步内完成启动→计时→停止确认，不依赖后续步骤发停泵。

`StepExecutor._run_timed_flow` 从 START 确认后按单调时钟计时，在 Web/编排层约每秒复用 read_pump_status 监督当前通道；读取失败或提前停止立即失败并清理。每次短睡眠最多 50ms，停止请求可中断；已发出的流量动作在暂停中仍计时、监督和到时停泵，步骤边界由引擎等待继续。所有退出路径尝试停止，停止未确认保留活动设备供原清理/恢复机制处理；不自动重启泵。串口调用耗时可能推迟停泵确认，不保证硬实时精度。进度 wait_type=flow_duration 是只读动作标记，不是新增 YAML wait 类型。

预充签名协议为 turntable_collection_v6，覆盖转盘配置与滴液参数，旧批次仅供查看，不复用旧预充资格。历史流程不改写。流量模式不能在后端进程崩溃、主机掉电或通信中断时保证自主定时停泵；持久化恢复锁用于禁止自动续跑，不能代替现场停机。实际流量、暂停到时停止及异常停机仍须实机水测。

进度设备快照保留 status_confirmed/control_word/current_segment/runtime_seconds；没有 read_ok 时，仅使用明确的 status_confirmed 归一化读取确认，显式 read_ok=false 优先。复用执行器已有读取，不增加设备轮询。

### 引导式批次入口与本机草稿

`GuidedEntryPage.vue` 承接 `/experiment/batch`，默认入口、`?view=history` 批次历史、`?view=history&batch_id=...` 详情；`?new=1` 挂载新建表单，`?resume=1` 挂载当前批次进度与恢复入口。复用只读 `/api/guided/current`、`/batches`、`/{id}`、`/{id}/plan` 与现有日志接口，没有新增设备操作路径。开始成功后转 `resume=1` 保持进度页。

表单以 `heat.guided-draft.v1` 在 localStorage 保存一份版本化草稿，仅包含输入和步骤，不含校验证据、人工确认、运行状态、batch_id 或预充资格。恢复按字段检查，旧终态记录不回填覆盖新草稿，活动/恢复/清理/保存错误优先处理且保留草稿。启动成功清除草稿；新建空白前确认替换。`batchExport` 复用精确 run_id/metadata 关联，在完整日志之外附带批次检查点与原始流程快照，快照不存在或批次身份不一致时拒绝完整导出。物理存储仍使用现有批次、plans 与运行日志目录，不复制或改写历史记录。

### CL-01A 转盘手动接入

2026-10-24 本机仓库配置经厂家报文和实机定位核验，已启用 `home_enabled` 与 `position_encoding_verified`；模型默认值仍为false，不推广到其它设备或桌面独立配置。证据与标定边界见 [实机核验记录](turntable_integration.md#2026-10-24-原点与有限定位核验)。

停止确认在 Web 协调层发送一次 STOP 后设定3秒单调时钟期限。读回的 OSError（含超时、短帧和未定义状态）记录到日志并清空连续稳定证据，在剩余期限内仅重试查询；写失败不重发，期限后的读回不接受为成功。仍要求连续两次 `0x20` 且坐标一致；单次同步读取可能使返回越过期限。到时运行的停止确认失败不会再误报“未确认连续运行”。

`SystemConfig.turntables` 默认空列表，旧配置无需新增字段；已配置转盘由 `DeviceManager` 注册。`TurntableDevice` 只进行同步串口调用，使用原 `SerialPortManager` 和指纹解析；`TurntableController` 在 Web 层串行协调读写、停止代次和完成判断，应用 lifespan 的监督任务仅监督已明确发起的运动，与浏览器连接无关。单次串口调用和监督调度可能延后定时停止，不承诺硬实时。

| 接口 | 行为 |
| --- | --- |
| `GET /api/devices`、`/ws` | 增加 `turntables` 字典 |
| `POST /api/turntable/{device_id}/connect` | 唯一绑定后打开串口并读取状态，不运动 |
| `POST /api/turntable/{device_id}/disconnect` | 确认停止后释放；失败保留连接及未确认状态 |
| `GET /api/turntable/{device_id}/status` | 只读状态；与 WebSocket 使用相同的读取协调键 |
| `POST /api/turntable/{device_id}/command` | 常用 `home_bottle`、`next_bottle`；高级 `move_relative`、`move_absolute`、`run`、`home`、`stop`；返回 `success/result/state`，`success=true` 不表示运动完成 |

瓶位模式由 `bottle_count` 控制，默认0保持旧配置的高级手动操作兼容；本机为12，`pulses_per_bottle=12000`、`bottle_speed=4000`、`bottle_home_speed=1000`、`bottle_home_timeout=180`。`home_bottle` 不接收其它字段，在 Web 协调层使用负向机械回零；`next_bottle` 必填 `expected_position`（最新有效坐标）及 `expected_bottle_token`，后端在设备锁内再次读取并比较，拒绝陈旧坐标或令牌，再向原协议发送目标为当前坐标加一个瓶位脉冲数的有限定位。每次成功回1号或换瓶生成新令牌，失效或运动中撤销，避免旧请求在再次回零到相同坐标后重放。瓶位命令只存在于Web请求模型，底层命令和协议保持原有动作。速度由配置确定；12到1继续同方向累计，不清零、不自动续跑。

启用瓶位模式时，配置校验要求 `bottle_home_timeout >= bottle_count * pulses_per_bottle / bottle_home_speed + 5`，并要求 `action_timeout >= pulses_per_bottle / bottle_speed + 5`，分别覆盖一圈回零和一格换瓶并保留至少5秒余量；降低速度时须相应延长超时。

瓶位状态由后端负责，包含 `bottle_count`、`pulses_per_bottle`、`current_bottle`、`next_bottle`、`bottle_token`、`bottle_ready` 和 `bottle_error`，动作可包含 `from_bottle`、`target_bottle`。只有 `home_bottle` 观察到回零过程、目标0和稳定停止后建立瓶位信任；换瓶准确到达目标并停止后才更新瓶号。启动、重连、复位、读取异常、意外坐标变化、高级运动或显式停止撤销信任，瓶号返回null，不能仅从坐标取模恢复。前端在状态过期或无效时隐藏瓶号，不自行计算，也不持久化瓶位以便重启续跑。

手动请求通过现有实验注册锁、恢复锁及占用保护；停止先撤销尚未下发的运动请求，随后在同一设备锁内发停止和确认。HTTP 调用被取消时仍等待底层同步任务退出，不能提前释放这次操作的保护。活动转盘、未知结果或连接后的过期读数会阻止普通实验、引导式批次及微波托管启动；全局停止和清理包括转盘。引导式自动接样在批次上层编排中复用这些控制器能力，搭建式的三个公开转盘动作见下文；两类编排共用瓶位执行部分。

手动写控制的恢复检查包含引导批次持久化的 `recovery_required` 和 `cleanup_required`；未解除返回409，记录不可读返回503，GET和STOP不受该恢复检查阻断。停止已确认后出现坐标变化会撤销 `stop_confirmed/homed` 并设置稳定性阻断，新的两次独立稳定停止读数可解除这一阻断，但不能清除未知运动或失败STOP留下的必须停止标志。

转盘状态快照增加 `state_session`（控制器对象创建时的UTC ISO微秒时间）和 `state_revision`（同会话递增整数），REST、设备列表和WS超时失效快照均携带。前端按会话及版本合并，拒绝迟到旧状态；`read_at` 只用于读数过期，不能作为无读数状态的排序依据。相同版本的本地HTTP失败可将状态降为读取失败，不得反向恢复确认。WS超时生成版本时不等待串口锁。

驱动首次连接失败后，即使句柄关闭失败而仍打开，也不报告已连接；重连先成功释放旧资源，再创建句柄和重新查询。退出清理由控制器区分“从未连通、未发运动”和“连接丢失或运动未知”：前者可直接释放，后者保留停止保护；释放失败继续阻止退出并允许重试。

状态包括 `read_ok/read_at/read_error`、坐标和原始速度/输入值、工作状态、`busy`、`stop_confirmed`、`homed`、`motion_blocked` 及动作结果。`connection_error` 保留连接失败原因，自动资源清理与未连接状态读取不清除，成功连接或明确断开后清除；原始错误进入日志。控制视图按实际读数时间保留 6 秒有效期，监测视图保留 15 秒；状态失效不发送停止。运动结果未知或停止未确认时禁止新动作，已连接的停止入口继续可用。协议字节序、默认禁用项、桌面配置更新和实机验收见 [转盘接入说明](turntable_integration.md)。
