# Heat 设备就位版 MVP 运行手册

本文只规定执行顺序和材料入口。所有实测值、证据、问题编号、Gate 结论和签字统一填写在 [mvp_system_acceptance_checklist.md](mvp_system_acceptance_checklist.md)，不要在本文维护第二套记录。

## MVP 边界

- 自动控制：`heater1`、`heater2`、`pump1`、`microwave1`。
- 人工负责：管路切换、收集、安全确认、SOP 执行和样品有效性判断。
- 首轮介质：实验室批准的水或低风险替代液。
- 成功链路：设备连接 -> 液路预灌/标定 -> YAML -> 日志/历史 -> `run_id`/`sample_id`/`samples.csv` -> 人工验收记录。
- 文件出现在实验页面中只表示通过仓库审查，不表示已通过实机或实验室安全放行。

## 材料阅读顺序

1. [user_guide.md](user_guide.md)：启动系统、页面操作和停止语义。
2. [mvp_system_acceptance_checklist.md](mvp_system_acceptance_checklist.md)：唯一 Gate 清单和现场记录。
3. [system_engineering_design.md](system_engineering_design.md)：液路、死体积和三层标定方法。
4. [microwave_smoke_test.md](microwave_smoke_test.md)：微波仪分级实机验证。
5. [experiment_yaml_spec.md](experiment_yaml_spec.md)：需要审查或修改 YAML 时使用。
6. [device_materials/README.md](device_materials/README.md)：找到对应厂家资料、协议转换稿和实机观察记录。

## 三个活动流程

| YAML | 用途 | 进入条件 |
| --- | --- | --- |
| `low_risk_all_devices_smoke_test.yaml` | 低温、低流量、低功率、短时长验证四类设备动作 | Gate 0 通过；每项参数和安全负载已由实验室批准 |
| `mvp_water_loop_baseline.yaml` | 验证水/替代液、日志、历史和样品追踪链路 | Gate 0-3 通过；参与液路已标定；根据现场拓扑复核步骤 |
| `pump_microwave_water_flow_test.yaml` | CH4/CW 进水、60 C 保温、CH3/CCW 出水的集成流程 | Gate 0-4 全部通过；`2 mL/min`、`315 s`、`60 C`、5 分钟均已实测和批准 |

任何流程出现 `False`、timeout、`read_failed`、非零故障码或状态未知，都不算通过。活动 YAML 使用 `on_error: stop`；失败后的软件清理仍不能替代现场确认。

## Gate 0-6 执行顺序

### Gate 0：身份与基础安全

记录设备型号、序列号、固件、HMI、配置 commit 和操作者。逐台核对 COM 口、站号、串口参数、VID/PID/USB 位置，并通过断开单台设备证明不会误连。检查接地、漏保、急停、通风、散热、门控和断电手段。

通过条件：验收清单 Gate 0 无空白安全项，设备身份唯一且现场授权有效。

### Gate 1：单设备低风险测试

1. 加热器：环境温度读取、低温 SV 写回、RUN/STOP，记录 `Srun`、MV、HMI、输出端口和物理输出。
2. 泵：四通道逐一核对软管实物、`11 -> 13` HMI 映射、CW/CCW 方向、启动/停止读回和重新上电默认状态。
3. 微波仪：只读连接和参数读回，不进行未批准的真实输出。

通过条件：命令结果、寄存器读回、HMI 和物理行为一致；不存在状态未知。

### Gate 2：液路与流量标定

对 CH4 入口和 CH3 出口分别完成：

1. 标记泵头、通道、软管、入口和出口。
2. 测量有效内径、长度、接头/反应器附加体积，计算理论死体积。
3. 排气后做泵出口、2 m 长管末端、系统端三层标定，每层至少三次。
4. 用称重和液体密度换算体积，记录实际流量、重复性、到达延迟、残留、气泡、泄漏和背压影响。
5. 验证停泵时出口仍保持常压连通，不会夹闭反应器唯一出口。

通过条件：验收清单中得到两条液路的实测流量、死体积、预灌量、运行时间和废液策略。理论值不能替代系统端实测值。

### Gate 3：微波最小启停

按 [microwave_smoke_test.md](microwave_smoke_test.md) 执行。先确认非空载、探头浸没、常压出口、门控和现场看护，再用批准的最低风险参数验证配置读回、40151 启动位、故障码、功率/电流、stop 写零和物理停机。

通过条件：软件状态、HMI 和物理行为一致，`stop_confirmed=true`，实机未知项均有结论。

### Gate 4：双泵冷态干跑

保持微波关闭，先单独验证 CH4/CW 进水和 CH3/CCW 出水。按 Gate 2 的标定结果运行，测量实际进入容器和到达收集端的体积，不要只按理论 `315 s` 推定。

通过条件：方向、体积、液位、停止、残留和常压路径全部通过。

### Gate 5：60 C 热水集成运行

1. 复核容器、液位、探头、开放出口、收集容器、停止手段和现场人员。
2. 在实验页面选择 `pump_microwave_water_flow_test.yaml`，再次核对 YAML 与 Gate 标定值。
3. 现场观察 CH4 进水、达温、保温、微波停止、CH3 出水和最终状态。
4. 核对历史曲线、步骤日志、具体失败原因、`run_id`、`sample_id` 和 `samples.csv`。

通过条件：验收清单 Gate 5 全部通过；任何人工 stop 或异常都必须按失败/中止记录，不得补写为成功。

### Gate 6：放行决定

分别给出“软件通过”“单设备实机通过”“液路通过”“集成水测试通过”的结论。只有问题关闭并获得实验室批准后，才能进入重复实验；水测试通过不自动授权化学体系。

## 立即停止条件

- 串口身份不确定，或写回、读回、HMI、物理行为不一致。
- 泄漏、堵塞、蒸汽、异常气泡、回流、虹吸或探头暴露。
- 微波空载、出口不通、门控/接地/通风未确认。
- 非零故障码、状态未知、温度超过批准上限。
- stop 后泵仍转动、微波启动位未清除或功率/电流未归零。

先按实验室 SOP 使设备安全，再在验收清单中记录证据和问题编号。
