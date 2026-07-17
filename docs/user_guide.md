# Heat 使用者指南

面向实验操作人员。本文只回答三类问题：怎么启动、怎么操作、出问题怎么看。  
如果你要修改代码，请转 [developer_guide.md](developer_guide.md)。

---

## 你现在应该看什么

- 想启动系统：看“系统启动”
- 想操作页面：看“页面与操作”
- 想编写实验：先看本文，再看 [experiment_yaml_spec.md](experiment_yaml_spec.md)
- 想搭建设备就位后的水/替代液 MVP：看 [mvp_device_ready_runbook.md](mvp_device_ready_runbook.md)
- 想做批次式人工闭环优化：看 [campaign_workflow.md](campaign_workflow.md)
- 想排错：看 [troubleshooting.md](troubleshooting.md)

---

## 1. 系统启动

### 1.1 启动后端服务

```bash
conda activate heat
python run_server.py
```

默认访问地址：

- `http://localhost:8000`

### 1.2 前端更新后的处理

如果有人修改了前端代码，需要重新构建：

```bash
cd frontend
npm run build
```

构建产物会写入 `src/web/static/`。如果页面看起来没更新，先按 `Ctrl+Shift+R` 强制刷新浏览器。

---

## 2. 页面与操作

### 2.1 页面入口

系统包含 4 个主要页面：

| 页面 | 路径 | 作用 |
|------|------|------|
| 实时仪表盘 | `/` | 查看实时温度、泵状态、微波仪状态与推送数据 |
| 设备控制 | `/control` | 连接设备、控制加热器、泵与微波仪 |
| 实验页面 | `/experiment` | 选择 YAML 实验、启动、暂停、恢复、停止 |
| 智能实验 | `/campaigns` | 管理 Campaign、Trial、人工推荐与离线表征结果 |
| 历史记录 | `/history` | 查看实验历史记录和已保存日志 |

智能实验页面使用 `/api/campaigns` 接口，完整人工闭环流程见 [campaign_workflow.md](campaign_workflow.md)。

### 2.2 设备连接

在设备控制页面中：

1. 找到目标设备
2. 点击“连接”
3. 连接成功后状态会更新
4. 控制卡片会显示注册串口，例如加热器 `COM7`/`COM9`、蠕动泵 `COM10`；微波仪以当前 `system_config.yaml` 为准（本地当前为 `COM17`）。

设备参数可以在连接前预填。写入、启动或停止按钮不再仅靠前端置灰来拦截；点击后会先做连接/状态检查，必要时弹出设备检查确认。未连接、后端返回 `False`、超时或状态异常都会显示为失败。

点击“断开”时，后端会先取消尚未执行的启动请求并确认对应设备已停止；只有 stop 成功后才释放串口。如果 stop 返回 `False` 或抛出异常，系统会保留连接并报告断开失败，此时必须按现场 SOP 停机或使用物理急停，不能把“断开”当作急停手段。

如果连接失败，优先检查：

- 设备是否通电
- 串口号是否与 `config/system_config.yaml` 一致
- 是否有其他程序占用串口

### 2.3 加热器操作

可执行的核心操作：

- 设置目标温度
- 启动加热
- 停止加热

设置温度和启动加热前，页面会提示确认串口、温度探头、加热对象、接线和现场看护。设备未连接或后端返回失败时，页面不会显示为成功。

### 2.4 蠕动泵操作

每个泵可按通道独立控制。当前支持 4 种模式：

- `FLOW_MODE`
- `TIME_QUANTITY`
- `TIME_SPEED`
- `QUANTITY_SPEED`

如果你只需要会用，直接在页面里选模式、填参数即可。  
如果你需要理解 YAML 字段和单位，请看 [experiment_yaml_spec.md](experiment_yaml_spec.md)。
如果你要把蠕动泵接入前驱体管路、微波入口或长管路定量输运，请先按 [system_engineering_design.md](system_engineering_design.md) 做死体积、预灌和真实流量标定。
如果你要从设备就位推进到水/替代液闭环 MVP，请按 [mvp_device_ready_runbook.md](mvp_device_ready_runbook.md) 先完成设备确认、三层液路标定和运行记录。

Heat 在软件层按 Modbus RTU 控制蠕动泵；现场物理接线可能是 RS232，也可能是设备支持的其他串口接法。界面里的 COM 口和驱动协议不等于强制要求现场一定使用 RS485。

泵管型号必须按现场实际泵管填写，不要凭示例照抄。LabSmart 泵头/软管编号表见 [device_materials/多通道蠕动泵MODBUS通信协议.md](device_materials/多通道蠕动泵MODBUS通信协议.md) 的“表 1：泵头 & 软管编号”。如果实验日志出现 `tube_model mismatch`，例如写入 11 但读回 13，说明 YAML/配置和设备当前泵管设置不一致；在确认真实泵管前，不要把流量或体积结果当作定量数据。

启动泵通道前，页面会提示确认串口、通道、模式、软管、流向、入口/出口、收集或废液容器和现场看护。停止操作仍应优先用于安全停机；如果泵设备返回失败，页面会明确显示失败。

页面按实际单位显示泵流量；`TIME_QUANTITY` 会先把体积和时间换算为 `mL/min`。输入上限取所选管型额定上限与通道配置 `max_flow_rate` 的较小值；若换算后某单位没有满足协议最小值 `0.01` 的合法区间，该单位会被禁用。流量曲线统一换算为 `mL/min` 后绘制，RPM 或未知单位不会与体积流量混在同一坐标轴。某通道状态读取失败时会明确显示“读取失败”，该次缓存值不会继续画入曲线或写入实验传感器日志。

### 2.5 微波仪操作

微波仪是高压、加热、微波输出设备，不能按普通加热器处理。当前页面支持连接、断开、刷新状态、配置参数、启动和停止；按 2026-06-20 用户确认，微波仪手动前端控制已像加热器/蠕动泵一样开放。页面会显示当前注册串口（本地当前为 COM17）；按钮可以点击，但未连接、状态读取失败、故障码非零、已有功率/电流输出、用户取消确认或设备返回失败时，不会显示为成功。

启动微波前，页面会要求二次确认。实验室人员必须人工确认：

- 炉门已关闭。
  - 说明书/任务记录显示，炉门未关严时设备/HMI 会禁止启动并提示“门未关严”。当前通信协议没有可靠门状态寄存器，软件不会伪造 `door_closed`，仍需人工看面板和设备联锁。
- 反应瓶非空载，光纤探头已没入物料。
- 温度、功率和时间参数已核对。
- 设备运行期间有人现场看护。
- 设备电源、接地、通风和散热空间符合说明书要求。

微波仪状态字段：

实时仪表盘会显示已注册的微波仪；设备未连接时显示为离线，连接并读取成功后显示实时温度、功率、电流、运行时间、当前段、当前模式和故障码。温度曲线分为两张图：加热器 PV/SV 曲线和微波仪物料温度曲线；蠕动泵流量曲线单独显示。

| 字段 | 含义 |
|------|------|
| 物料温度 | 当前从设备状态读到的物料温度；浮点字序仍需实机确认 |
| 功率 | 当前实时功率百分数 |
| 电流 | 当前工作电流原始显示值 |
| 运行时间 | 由时、分、秒状态组合得到 |
| 当前段 | 当前段号，来自设备状态 |
| 当前模式 | 当前后端可识别模式；未知枚举会显示为未知 |
| 故障码 | 原始故障码；协议未确认 bit 含义前不解释成具体故障 |

`allow_real_hardware_writes`、`enable_control_writes`、`allow_experiment_control` 仍可能出现在配置或状态 payload 中，用于兼容旧版本和现场记录；当前软件不再把它们作为前端手动或 YAML 自动控制的阻断门。真实硬件安全仍由实验室 SOP、现场看护、设备面板和设备自身门控联锁确认。

---

## 3. 实验执行

### 3.1 启动实验

1. 打开 `/experiment`
2. 在左侧选择 YAML 实验
3. 确认是否开启“保存日志”
4. 点击“启动”

### 3.2 实验状态说明

| 状态 | 含义 |
|------|------|
| `idle` | 当前实验未运行 |
| `running` | 正在执行步骤 |
| `paused` | 已暂停，可恢复 |
| `completed` | 全部步骤已完成 |
| `failed` | 某个步骤失败，实验中止 |
| `stopped` | 用户手动停止 |

### 3.3 单实验保护

系统同一时刻只允许一个实验处于：

- `running`
- `paused`

如果已有实验在运行或暂停，启动另一个实验会被拒绝。

---

## 串口稳定绑定补充

系统现在区分两个概念：

- 设备绑定身份：你希望 Heat 找到的是哪一台真实设备，例如 `SN=A6001234`、`VID:PID=1A86:7523 @ 1-3.2`
- 当前解析串口：这次启动时系统实际解析出的 `COMx`

控制页和仪表盘看到的 `connection_port` 只是本次解析结果，不再代表设备身份本身。

当你更换 USB 物理接口后：

- 如果设备绑定规则足够稳定，系统会在启动时自动把设备重新映射到新的 `COMx`
- 如果页面显示“未匹配”或“端口回退”，说明系统没有可靠找到目标设备，需要先检查绑定规则和现场接线，再尝试连接
- 如果设备是在后端启动后才被 Windows 枚举出来，控制页会在发现“未匹配”时自动请求后端重新扫描一次绑定；仍未匹配时再按下方清单排查。

优先检查：

- 设备 USB 转串口是否暴露了稳定 `serial_number`
- 是否改了 USB 集线器或物理口，导致 `location` 变化
- 多台同型号转串口设备是否同时在线，造成“多重匹配”
- `config/system_config.yaml` 中的 `connection.binding` 是否仍然对应目标设备

---

## 4. 行为语义

这部分非常重要，回答的是“按钮按下去以后系统到底会怎么做”。

### 4.1 停止 / 暂停 / 恢复的区别

#### 停止

- stop 会中断当前等待步骤
- 系统会停止本次实验曾尝试启动的加热器、泵通道和微波仪；全部停机确认成功后实验才结束为 `stopped`
- 任一设备停机返回 `False`、timeout 或异常时，stop 接口返回失败，实验终态为 `failed`；此时必须现场确认并按 SOP 使用设备面板或物理急停，不能把页面请求结束当作设备已停
- stop 是终止当前 run，不是临时挂起
- 全局急停只有在所有已注册设备都实际收到并确认停止命令时才返回成功；未连接、跳过或没有注册设备都会显示失败，需要现场确认或使用物理急停

#### 暂停

- pause 会让实验进入 `paused`
- 当前等待步骤会停止计时和轮询，不会在暂停期间偷偷完成
- 已经发出的同步设备命令不会被强行取消；命令返回后，引擎会停在步骤收尾处等待 resume
- 暂停后可以继续 `resume`
- 暂停不会自动把 run 改成完成或失败

#### 恢复

- resume 会从暂停状态继续执行
- 只对当前 paused 的实验有效

### 4.2 等待超时后会发生什么

如果等待条件超时，例如：

- 等温未达到目标
- 泵完成等待超时

系统会把该步骤视为失败，而不是静默继续往后执行。默认 `on_error: stop` 还会停止本实验曾尝试启动的设备；停机失败同样会保留为失败状态并要求现场处理。

### 4.3 浏览器刷新 / 关闭是否会影响设备

不会因为页面断开就自动停止设备。

浏览器刷新、关闭或 WebSocket 重连不会等同于“停止实验”或“停止泵”。  
如果你要真正停设备，请使用页面按钮或明确的控制接口。

这条规则同样适用于微波仪：WebSocket 断开不会自动停止微波输出。微波仪运行时必须由现场人员看护，并通过页面按钮、实验停止、设备 stop 或急停流程明确停机。

### 4.4 微波仪自动控制边界

按 2026-06-20 用户确认，微波仪 YAML 自动控制已开放，`microwave.configure_*`、`microwave.start` 和 `microwave.stop` 可以像加热器/蠕动泵动作一样由实验流程调用。

当前推荐把微波自动化写成“配置自动/PID 温控参数 -> 启动 -> 等待物料温度达到目标 -> Heat 外层计时保温 -> 显式停止”。不要把 `microwave_complete` 作为真实实验主流程的唯一结束条件，因为当前外控资料没有已实机确认的“程序完成”寄存器。

软件测试、页面二次确认和 YAML 结构校验不能替代实验室确认。真实运行前仍必须由实验室确认设备身份、接线、炉门联锁、非空载、探头、SOP、写入顺序和停机语义。实机验证清单见 [microwave_smoke_test.md](microwave_smoke_test.md)。

### 4.5 日志保存开关的影响

启动实验时可选择是否保存日志：

- 开启：实验日志会写入历史记录与原始日志文件
- 关闭：仍可实时看到日志，但不保存原始日志文件

### 4.6 `samples.csv`、历史记录、原始日志的关系

- `samples.csv`：面向样品追踪，记录 `sample_id`、batch、condition、状态等
- 历史记录：面向实验运行查看
- 原始日志：面向排查和还原 run 细节

它们相关，但不是同一个东西。

实验执行状态与追踪记录状态也相互独立：设备流程可以已经 `completed`，但日志文件或 `samples.csv` 仍可能因为磁盘、权限等问题写入失败。此时实验页面会显示“实验执行结束，但追踪记录失败”，历史页面会标记“记录失败”；该 run 不应被当成追踪完整的数据使用，必须先排查并补齐记录。

---

## 5. YAML 实验怎么用

如果你只是想会用，记住下面几点就够了：

- 实验文件放在 `experiments/`
- 文件后缀必须是 `.yaml` 或 `.yml`
- 每个实验至少要有 `steps`
- 每个步骤至少要有 `id` 和 `type`
- 微波仪 `configure`、`start` 和 `stop` 动作会直接调用已注册设备；失败时实验步骤失败，不会静默继续

最小示例：

```yaml
name: simple_heat_test
description: 简单加热测试
steps:
  - id: set_temp
    type: heater.set_temperature
    params:
      device_id: heater1
      temperature: 50.0
```

需要完整字段、动作表、等待表、metadata 说明时，请看：

- [experiment_yaml_spec.md](experiment_yaml_spec.md)

设备就位后的低风险 MVP 基线文件是：

- `experiments/mvp_water_loop_baseline.yaml`

运行它之前必须完成 [mvp_device_ready_runbook.md](mvp_device_ready_runbook.md) 中的设备确认、液路标定和微波人工确认。该 YAML 是水/替代液闭环验证，不是化学配方；任何 skipped、timeout 或 read_failed 都不算 MVP 通过。

---

## 6. 历史记录与日志

你可以在历史页面查看：

- 已保存的实验 run
- 运行状态
- 原始日志内容
- 单条记录详情、步骤状态与错误信息
- 实验报告曲线：加热器 PV/SV、微波仪物料温度、微波功率/电流、蠕动泵流量和累计体积
- 日志与 `samples.csv` 的追踪记录状态；失败时显示“记录失败”

历史页面支持：

- 勾选多条记录后批量导出为一个 JSON 文件。
- 勾选多条记录后批量删除；删除前会弹出确认。
- 在详情中导出或删除单条记录。
- 清空全部历史记录。

删除历史记录时，系统会同步删除 `samples.csv` 中对应 `run_id` 的样品行，避免留下指向已删除原始日志的孤立记录。没有对应历史日志的样品记录不会被“清空全部历史记录”误删。

历史记录更适合回顾实验过程；`samples.csv` 更适合做样品维度的追踪。

---

## 7. 最少可用 API 示例

如果你只是偶尔需要通过脚本触发系统，以下示例足够：

### 7.1 启动实验

```powershell
Invoke-RestMethod -Method Post -Uri 'http://localhost:8000/api/experiments/simple_heat_test.yaml/start' -ContentType 'application/json' -Body '{"save_log": true}'
```

### 7.2 暂停 / 恢复 / 停止实验

```powershell
Invoke-RestMethod -Method Post -Uri 'http://localhost:8000/api/experiments/simple_heat_test.yaml/pause'
Invoke-RestMethod -Method Post -Uri 'http://localhost:8000/api/experiments/simple_heat_test.yaml/resume'
Invoke-RestMethod -Method Post -Uri 'http://localhost:8000/api/experiments/simple_heat_test.yaml/stop'
```

### 7.3 查询实验进度

```powershell
Invoke-RestMethod -Method Get -Uri 'http://localhost:8000/api/experiments/simple_heat_test.yaml/progress'
```

---

## 8. 常见问题

### 8.1 实验为什么启动不了

常见原因：

- 已有其他实验处于运行或暂停状态
- YAML 文件名不合法
- YAML 缺少 `steps`
- 设备未连接，导致第一步立即失败

### 8.2 为什么实验一开始就失败

常见原因：

- 加热器或泵未连接
- YAML 参数不完整
- 设备命令返回失败

### 8.3 为什么页面上看不到实时数据

常见原因：

- 设备尚未连接
- WebSocket 未连上
- 页面未刷新到最新前端版本

### 8.4 为什么停止后很快就结束

这是当前设计的预期行为。  
stop 会尽快中断等待并结束实验，而不是等完整等待时间走完。

### 8.5 微波仪为什么配置或启动失败

常见原因：

- 微波仪未连接，或驱动返回失败。
- 前端读取状态失败，需要先刷新并确认设备正常。
- `fault_code` 非零，或当前功率/电流已经非零，前端会阻止重复启动。
- 设备自身门控联锁、HMI 状态或串口协议拒绝执行。
- YAML 自动控制中设备方法返回 `False`、timeout 或异常。

---

## 9. 去哪继续看

- YAML 规范： [experiment_yaml_spec.md](experiment_yaml_spec.md)
- 设备就位 MVP 运行手册： [mvp_device_ready_runbook.md](mvp_device_ready_runbook.md)
- Campaign 工作流： [campaign_workflow.md](campaign_workflow.md)
- 微波实机 smoke test： [microwave_smoke_test.md](microwave_smoke_test.md)
- 故障排查： [troubleshooting.md](troubleshooting.md)
- 开发维护： [developer_guide.md](developer_guide.md)
