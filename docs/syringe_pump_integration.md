# MSP1-CX 注射泵接入说明与功能覆盖

本实现面向两台 MSP1-CX、三口 Y 型阀、独立 USB 串口。**软件验证通过，实机验收待进行。** 本轮没有打开真实 COM 口或运行硬件。原始依据为 [厂家用户手册](device_materials/MSP1-CX用户手册%202025.6.4.pdf)，下文页码均为手册印刷页码（PDF 一页包含两个印刷页）。

## 配置与操作

`config/system_config.yaml` 的 `syringe_pumps` 独立于蠕动泵列表，不使用通道或蠕动泵模式。

| ID | 名称 | 串口绑定 | 拨盘地址 | 初始规格 |
| --- | --- | --- | --- | --- |
| syringe_pump1 | 注射泵1 | COM9，优先唯一匹配 USB 序列号 DSCCG146B12；禁止指纹失配后回退 | 1 | 2.5 mL、Y3 |
| syringe_pump2 | 注射泵2 | 串口/指纹空，待配置 | 0（待现场复核） | 2.5 mL、Y3 |

默认 OEM、9600/8N1。`protocol` 可显式改为 `DT`；波特率支持 9600/38400，必须与断电设置的设备拨码一致。拨盘 0..14 映射协议地址 ASCII 0x31..0x3F；拨盘1发送地址字符 `2`，不应把协议字符当作拨盘值。连接复用 SerialPortManager，不支持 CAN 或共用串口总线。

1. 在控制页查看两台卡片及绑定状态。新转换器/泵2接好后，显式修改 YAML 的 port、binding、address，重启服务并刷新绑定；启动、页面加载和刷新不会连接或初始化注射泵。
2. 手动连接，只发送查询。连接成功并不表示已初始化或位置可信；本连接未确认的模式、方向不用于体积计算。
3. 完成安装/液路检查后，显式确认初始化。Z 为面对泵正面左吸右排，Y 为右吸左排；初始化会移动活塞及阀。驱动力通过初始化代码选择，按注射器规格限制。
4. 基础控制可按 µL/mL/步数吸排，显示取整行程和目标。绝对定位按目标相对当前位置选择进液/排液通路。每次基本吸排下发 `v50c50V<速度>`，因此基本操作以该次表单速度为准；参数页速度用于独立设置及程序，不会因编辑输入框自动运动。
5. 参数、程序/I/O、诊断分别操作。程序先校验、装载，再明确执行。EEPROM 存储会覆盖指定槽位，须二次确认，存储本身不等于执行。
6. 单泵停止与全局急停始终独立可用；停止返回未确认时保留故障提示和实验占用，不报告安全停机。T 不能立即打断阀切换，停止后位置失信，检查原因后才能重新初始化。

容量可在 YAML 显式修改为 0.05/0.1/0.25/0.5/1/2.5/5 mL；当前只实现所购 Y3 阀，其他阀型号拒绝配置，不能只修改名称套用流向。步进模式 N0/N1/N2 分别为 3000/48000/24000 步，只在零位修改；初始化恢复 N0。无可靠模式查询，模式设置标为已发送/待验证，必须通过实机验收确认换算。

体积字段是注射器容量及位置推算的**理论排量/理论筒内体积**，不是实测输液量。软件没有漏液、水到位、液位或压力传感能力。长管路、气泡、回差、死体积须现场校准。

## 命令、参数、返回与入口对应

所有命令都通过帧层处理状态字；只使用 Q 的 busy/ready 位判定忙闲。OEM 为 STX、地址、序列号、命令、ETX、XOR；返回地址为主机 `0`，不要求回显泵地址。DT 为 `/地址命令\r`，返回 `/0<状态><数据>\x03\r\n`。读写有界超时、分包接收、错误地址/校验/状态拒绝，不自动重发运动。

下列测试位于 `tests/test_syringe_pump.py`。查询数据保持厂家原值；Q 错误低四位及说明同时保留，未识别码显示未知错误。

| 手册命令 / 页 | 范围与返回 | 功能入口 | 对应测试 |
| --- | --- | --- | --- |
| OEM / DT，串口协议章 | 拨盘0..14；OEM序列1..7及XOR；DT帧尾 | 配置 protocol，帧层 | framing_and_fragmented_reply、bad_responses_never_retry、oem_sequence_rotates_without_repeat_bit |
| Z/Y，31–32 | 代码0/1/2或10..40；状态应答后等待Q、零位及阀位 | initialize，基础控制；YAML同名 | unknown_mode_blocks_motion_and_init_establishes_it、faults_block_motion |
| A/P/D，32–33 | 额定行程0..3000/48000/24000；正数步；应答≠完成 | move / aspirate / dispense；程序A/P/D | aspirate_and_dispense_verify_target、stroke_and_resolution_limits、actual_position_mismatch_fails |
| I/O/B，33–34 | Y3不带参数；Z下阀位4/0/8，Y下0/4/8 | valve；程序编辑 | bounded_nested_program、invalid_programs |
| T/h/r，29 | 停止/硬件暂停/继续；T后不信任位置 | stop / pause / resume | stop_does_not_wait_for_motion_completion、experiment_stop_failure_keeps_ownership |
| v/V/c，38–40 | 50..1000 / 5..5000 / 50..2700 Hz；?1/?2/?3读回 | configure；参数页/程序 | configure_waits_for_q_and_checks_readback、bad_api_parameters |
| L/S，37–39 | L1..20，S0..40；L用?5核验，S标未完整验证 | configure；参数页/程序 | configure_waits_for_q_and_checks_readback、invalid_programs |
| N，38 | 0/1/2；无可靠查询，已发送/待验证 | configure，参数页，仅零位 | microstep_change_at_zero_and_rounding |
| K/k，36、40 | 回差0..31、死区0..80；?12/?24读回 | configure；参数页/程序 | bad_api_parameters、invalid_programs |
| Q，42–44 | busy/ready、错误1/2/3/7/9/10/11/15，未知码不当成功 | status、所有动作前检查 | overload_invalidates_position_and_no_automatic_initialize、unknown_fault_is_not_success |
| ?、?4、?6，40–41 | 目标、当前步数、阀位；仅可信位置换算体积 | status / diagnostics | actual_position_mismatch_fails、read_failure_returns_unknown |
| ?5/?8/?10/?12/?13/?14/?15/?16/?23/?24，41–42 | 斜率、驱动力0/1/2、缓冲96/64、回差、输入0/1、地址、扩展错误0..255、固件字符串、死区 | diagnostics；缓冲参与完成判断 | q_ready_does_not_complete_pending_buffer、get_and_ws_do_not_control_hardware |
| J/H，28–29 | J0..7三输出掩码，1断开/0闭合；H0/1/2等待R或TTL高电平 | io；程序H；resume释放当前H等待 | external_input_program_timeout_stops、invalid_programs |
| R/X，27 | R执行当前缓冲；重复重新校验并上传，**不盲发X** | program_run / repeat | lost_movement_reply_is_not_replayed、duplicate_submit_is_rejected_while_busy |
| g/G/M，27–28 | 最多4层；G1..30000有限循环；M5..30000毫秒 | 程序校验/编辑 | bounded_nested_program、invalid_programs |
| s/e，30–31 | 槽位0..14；程序登记名称、摘要SHA256、时间 | program_store / program_run(slot) | program_registry_and_unknown_slot、modified_registry_cannot_execute、failed_overwrite_revokes_previously_stored_slot |

范围采用所购硬件的额定行程，不开放手册中的额外机械行程。初始化表与正文对3..9存在范围差异，因此不开放3..9；有明确正文支持的10..40可用。驱动力不作为独立无运动参数暴露：它由初始化代码设置，?8可查询。

程序正文限制120 ASCII字节，为存储命令及槽号留空间；嵌套展开最多10000操作；拒绝未知命令、无限G0、递归/嵌套EEPROM调用、程序中的初始化及模式切换。初始化、模式设置与存储是单独类型化操作。程序可修改速度/L/K/k及I/O，但不允许旁路状态下移动活塞。装载、存储、执行前均按当前位置及模式校验行程；执行后核验终点与阀位。

EEPROM不能可靠读回全文。本地 `data/syringe_programs/<设备ID哈希>.json` 仅记录已发送内容，不声称设备程序已验证；只允许执行本连接成功登记且摘要未改变的槽位，重连须重新存储。写入或登记失败撤销该槽位运行资格。软件不修改上电自动运行配置；存储前现场确认设备没有启用不合要求的上电程序。

## API 与状态

设备列表：`GET /api/devices` 中的 `syringe_pumps`。

| 方法 | 路径（前缀 `/api/syringe_pump/{device_id}`） | 语义 |
| --- | --- | --- |
| POST | `/connect`、`/disconnect` | 手动连接；断开先确认停止，失败保留连接 |
| GET | `/status`、`/diagnostics`、`/programs` | 状态、手册查询、程序登记；均不运行/初始化/停止 |
| POST | `/command` | `SyringeCommand`共享类型化请求；额外字段/无关字段拒绝 |

`command` 示例：`{"action":"aspirate","volume":100,"unit":"uL","speed":100,"timeout":120}`。初始化加 `confirm:true`；存储加 `program/name/slot/confirm:true`；运行槽位加 `slot`，省略则运行缓冲。`timeout`为0到3600秒之间的正数，普通默认120秒。未找到设备404、参数错误422、占用/状态冲突409、传输失败503。`stop_unconfirmed`即使HTTP成功也不是停机成功。

状态包括 connected、configured、binding_*、connection_port、read_at/read_ok/read_error、busy、initialized、position/position_trusted、target_position、valve_position、fault_code/fault_description、theoretical_volume_ul、microstep/orientation、owner、stop_confirmed、action 和最近 events。未知读数为 null；read_ok=false 时不能展示旧成功值。`initialized`描述Q报告，不等于本连接已确认机械位置。

动作结果区分 accepted、running、completed、failed、unknown、paused、stopped、sent_unverified。只有Q空闲、缓冲空闲、适用目标读回一致才确认运动完成。运动应答丢失后结果保持unknown，禁止重试/继续叠加；诊断查明并现场检查后显式恢复。

## 自动化与记录

同步驱动不含轮询线程。REST、WebSocket及实验通过同一 `SyringeController` 串行访问；DeviceReadCoordinator合并状态读，锁只保护单次调用，不跨运动等待。停止世代号取消排队及检查期间尚未发送的控制；停止可抢在下一动作前进入。Web层独立监督已明确下发动作的超时，超时停止不依赖浏览器是否在线。

实验开始前检查所有启用步骤引用的注射泵连接，泵2未配置/未连接即失败；实际执行再检查Q、故障、模式和剩余行程。运动/配置自动等待本动作完成。实验开始前一次预留全部引用注射泵；预留失败释放已预留设备且不发送运动。实验持有设备所有权，阻止手动动作插入，停止除外。暂停让当前动作/有限程序继续，不发下一步，不重放；暂停期间继续检查故障，停止仍可中断。硬件h暂停只用于手动控制；实验暂停不发送h。

步骤保存 `device_result`，即使短动作在两次采样之间完成也保留最终结果；采样保存位置、理论体积、故障及事件。历史页曲线遇未知值断开，导出包含注射泵步骤结果及采样。数据复用原 run_id/sample_id 和持久化失败报告，未修改Campaign或planner控制权限。手动页最近事件是内存诊断信息；需长期追踪的操作使用启用日志的实验运行。

示例：[单泵](../experiments/syringe_single_water.yaml)、[双泵顺序协作](../experiments/syringe_dual_water.yaml)。文件存在不代表允许自动启动，实验仍由用户明确启动；双泵示例按顺序完成每步，不承诺同步启动。

## 验证边界

模拟测试禁止真实 `serial.Serial.open`。覆盖OEM/DT帧、分包、错误、超时不重试、忙/故障/失信、步数换算、程序边界、存储失败、双泵隔离、急停竞争、暂停监督、短动作历史及未配置泵2预检。项目metadata、实验/并发/资源协调/Campaign回归、后端导入、前端生产构建一并验证。

这些检查不能确认硬件接线、厂商固件时序、真实液量、阀方向或实际停止。后续按 [实机验收清单](syringe_pump_acceptance.md) 单独确认。


### 本轮软件检查记录（2026-09-28）

- 注射泵专项90项及相关回归214项：共304 passed。
- 项目metadata：37 passed，0 failed。
- 后端app/experiments/ws/parser/engine导入通过。
- 前端vue-tsc及Vite生产构建通过；未进行浏览器端到端交互或实机测试。
- 差异空白检查通过；生成声明仅增加实际使用组件。测试出现2项现有Starlette/httpx弃用警告，不影响通过。
- 分支 `codex/msp1cx-integration`，保留用户原始手册；本轮不提交、推送或合并。
