# Heat 实验 YAML 规范

适用人群：需要编写、审核或扩展实验 YAML 的使用者与开发者。

---

## 你现在应该看什么

- 只想会写一个简单实验：看“最小示例”
- 想知道所有字段：看“顶层字段”和“steps 结构”
- 想知道所有动作和等待类型：看“动作表”和“等待表”
- 想排查 YAML 为什么跑不起来：看“常见错误”

---

## 1. 文件级规则

### 1.1 文件位置与后缀

- 实验文件放在 `experiments/`
- 只接受 `.yaml` 或 `.yml`
- 文件名必须是普通文件名，不能包含路径穿越

不允许：

- `../test.yaml`
- `subdir/test.yaml`
- 非 YAML 后缀

### 1.2 顶层字段

| 字段 | 必填 | 类型 | 说明 |
|------|------|------|------|
| `name` | 否 | string | 实验名；缺省时使用文件名 |
| `description` | 否 | string | 实验描述 |
| `metadata` | 否 | object | 样品与实验元数据 |
| `steps` | 是 | list | 实验步骤列表 |

---

## 2. metadata 推荐字段

`metadata` 当前不是强制字段，但推荐使用以下键：

| 字段 | 类型 | 说明 |
|------|------|------|
| `material_system` | string | 材料体系 |
| `batch_id` | string | 批次编号 |
| `condition_id` | string | 条件编号 |
| `sample_index` | int 或可转为 int 的值 | 样品序号 |
| `operator` | string | 操作员 |
| `recipe_version` | string | 配方版本 |

补充说明：

- `sample_index` 允许来自 YAML 的字符串值，但建议直接写整数
- `sample_id` 可由系统自动生成，不必手工提供
- `recipe_file`、`started_at`、`finished_at` 等运行态字段由系统补充

---

## 3. steps 结构

每个步骤的标准结构：

```yaml
- id: unique_step_id
  type: heater.set_temperature
  params:
    device_id: heater1
    temperature: 80.0
  wait:
    type: temperature_reached
    device_id: heater1
    tolerance: 1.0
    timeout: 600
  enabled: true
  on_error: stop
```

### 3.1 步骤字段

| 字段 | 必填 | 类型 | 说明 |
|------|------|------|------|
| `id` | 是 | string | 步骤唯一标识 |
| `type` | 是 | string | 动作类型 |
| `params` | 否 | object | 动作参数，默认空对象 |
| `wait` | 否 | object | 等待条件，默认 `none` |
| `enabled` | 否 | bool | 是否启用，默认 `true` |
| `on_error` | 否 | string | 错误策略，默认 `stop` |

### 3.2 `enabled` 语义

- `true`：步骤会被执行
- `false`：步骤会被加载时跳过，不进入实际执行列表

### 3.3 `on_error` 语义

当前推荐使用：

- `stop`：步骤失败后终止实验
- `skip`：步骤失败后跳过该步骤并继续

说明：

- 当前代码默认值是 `stop`
- 非标准值不应依赖，文档与 YAML 建议仅使用 `stop` 和 `skip`

---

## 4. 动作类型

### 4.1 `heater.set_temperature`

用途：设置加热器目标温度。

参数：

| 参数 | 必填 | 说明 |
|------|------|------|
| `device_id` | 是 | 加热器 ID |
| `temperature` | 是 | 目标温度 |

示例：

```yaml
- id: set_temp
  type: heater.set_temperature
  params:
    device_id: heater1
    temperature: 80.0
```

### 4.2 `heater.start`

参数：

| 参数 | 必填 | 说明 |
|------|------|------|
| `device_id` | 是 | 加热器 ID |

### 4.3 `heater.stop`

参数：

| 参数 | 必填 | 说明 |
|------|------|------|
| `device_id` | 是 | 加热器 ID |

### 4.4 `pump.start`

用途：启动指定泵通道。

基础参数：

| 参数 | 必填 | 说明 |
|------|------|------|
| `device_id` | 是 | 泵 ID |
| `channel` | 是 | 通道号，通常为 1-4 |
| `flow_rate` | 否 | 流速 |
| `direction` | 否 | `CW` 或 `CCW`，默认 `CW` |
| `mode` | 否 | 运行模式，默认 `FLOW_MODE` |
| `tube_model` | 否 | 软管型号 |
| `flow_unit` | 否 | 流速单位，常用 `1`(mL/min) |

按模式扩展参数：

| 模式 | 额外参数 |
|------|----------|
| `FLOW_MODE` | 无 |
| `TIME_QUANTITY` | `run_time` `time_unit` `dispense_volume` `volume_unit` |
| `TIME_SPEED` | `run_time` `time_unit` |
| `QUANTITY_SPEED` | `dispense_volume` `volume_unit` |

重复模式参数：

| 参数 | 说明 |
|------|------|
| `repeat_count` | 0 表示无限重复，1 表示单次 |
| `interval_time` | 重复间隔 |
| `interval_time_unit` | 间隔单位 |

规则：

- `repeat_count != 1` 时，`interval_time` 必须大于 0
- 缺失单位时系统会补默认值，但建议显式写出

### 4.5 `pump.stop`

用途：停止整个泵设备。

参数：

| 参数 | 必填 | 说明 |
|------|------|------|
| `device_id` | 是 | 泵 ID |

### 4.6 `pump.stop_channel`

用途：停止指定通道。

参数：

| 参数 | 必填 | 说明 |
|------|------|------|
| `device_id` | 是 | 泵 ID |
| `channel` | 是 | 通道号 |

### 4.7 微波仪动作

微波仪动作用于实验流程中配置、启动或停止已注册的 MKM-AH1E 微波仪。按 2026-06-20 用户确认，该能力已像加热器/蠕动泵动作一样开放；实验流程会直接调用目标设备，设备返回失败时步骤失败。

当前动作表：

| 动作 | 说明 |
|------|------|
| `microwave.configure_manual` | 配置手动功率模式段参数 |
| `microwave.configure_auto_power` | 配置自动功率模式段参数 |
| `microwave.configure_constant_rate` | 配置恒速率模式段参数 |
| `microwave.start` | 按指定模式启动微波输出 |
| `microwave.stop` | 停止微波输出 |

规则：

- `microwave.configure_*`、`microwave.start` 和 `microwave.stop` 会直接调用 `DeviceManager`；返回 `False`、timeout 或异常会使步骤失败。
- `allow_experiment_control`、`allow_real_hardware_writes` 和 `enable_control_writes` 字段仍可出现在配置或状态中，但当前不作为 YAML 自动控制的阻断门。
- 普通配置批量写入仍不得覆盖控制字 `40151`。
- 真实自动启动前，仍必须完成 [microwave_smoke_test.md](microwave_smoke_test.md) 中的实验室人工确认。
- 以下示例只说明 YAML 结构，不是化学工艺建议，也不能作为真实实验参数直接照抄。

`microwave.configure_manual` 参数：

| 参数 | 必填 | 说明 |
|------|------|------|
| `device_id` | 是 | 微波仪 ID |
| `segments` | 是 | 段参数列表，段号范围 1-5 |

手动功率段字段：

| 字段 | 必填 | 说明 |
|------|------|------|
| `segment` | 是 | 段号，1-5 |
| `heating_temperature` | 是 | 加热目标温度 |
| `heating_power_percent` | 是 | 加热功率百分数 |
| `holding_temperature` | 是 | 保温温度 |
| `holding_power_percent` | 是 | 保温功率百分数 |
| `holding_deviation` | 否 | 保温偏差，默认 `0` |
| `hours` / `minutes` / `seconds` | 是 | 保温时间 |

结构示例：

```yaml
- id: mw_manual_config_structure_only
  type: microwave.configure_manual
  params:
    device_id: microwave1
    segments:
      - segment: 1
        heating_temperature: 40
        heating_power_percent: 5
        holding_temperature: 40
        holding_power_percent: 5
        holding_deviation: 1
        hours: 0
        minutes: 0
        seconds: 5
```

`microwave.configure_auto_power` 参数：

| 字段 | 必填 | 说明 |
|------|------|------|
| `segment` | 是 | 段号，1-5 |
| `target_temperature` | 是 | 升温目标值 |
| `holding_temperature` | 是 | 保温目标值 |
| `hours` / `minutes` / `seconds` | 是 | 保温时间 |

结构示例：

```yaml
- id: mw_auto_power_config_structure_only
  type: microwave.configure_auto_power
  params:
    device_id: microwave1
    segments:
      - segment: 1
        target_temperature: 40
        holding_temperature: 40
        hours: 0
        minutes: 0
        seconds: 5
```

`microwave.configure_constant_rate` 参数：

| 字段 | 必填 | 说明 |
|------|------|------|
| `segment` | 是 | 段号，1-5 |
| `ramp_hours` / `ramp_minutes` / `ramp_seconds` | 是 | 升温时长 |
| `target_temperature` | 是 | 升温目标温度 |
| `hours` / `minutes` / `seconds` | 是 | 保温时长 |
| `holding_temperature` | 是 | 保温温度 |

结构示例：

```yaml
- id: mw_constant_rate_config_structure_only
  type: microwave.configure_constant_rate
  params:
    device_id: microwave1
    segments:
      - segment: 1
        ramp_hours: 0
        ramp_minutes: 0
        ramp_seconds: 5
        target_temperature: 40
        hours: 0
        minutes: 0
        seconds: 5
        holding_temperature: 40
```

`microwave.start` 参数：

| 参数 | 必填 | 说明 |
|------|------|------|
| `device_id` | 是 | 微波仪 ID |
| `mode` | 是 | `manual_power`、`auto_power` 或 `constant_rate` |

`microwave.stop` 参数：

| 参数 | 必填 | 说明 |
|------|------|------|
| `device_id` | 是 | 微波仪 ID |

最小结构示例：

```yaml
- id: mw_start_structure_only
  type: microwave.start
  params:
    device_id: microwave1
    mode: manual_power
  wait:
    type: microwave_complete
    device_id: microwave1
    timeout: 30

- id: mw_stop
  type: microwave.stop
  params:
    device_id: microwave1
```

### 4.8 `wait`

用途：不执行设备动作，仅依赖 `wait` 字段实现等待。

通常写法：

```yaml
- id: hold
  type: wait
  params: {}
  wait:
    type: duration
    seconds: 60
```

### 4.9 `emergency_stop`

用途：执行全局紧急停止。

参数：无强制参数。

### 4.10 `log`

用途：在实验日志中写入一条消息。

参数：

| 参数 | 必填 | 说明 |
|------|------|------|
| `message` | 否 | 日志文本 |

---

## 5. 等待类型

### 5.1 `none`

默认值，不等待。

### 5.2 `duration`

按秒等待。

字段：

| 字段 | 必填 | 说明 |
|------|------|------|
| `seconds` | 是 | 等待秒数 |

说明：

- 当前系统 stop 会中断该等待，不必等完整时长

### 5.3 `temperature_reached`

等待加热器达到目标条件。

字段：

| 字段 | 必填 | 说明 |
|------|------|------|
| `device_id` | 是 | 加热器 ID |
| `tolerance` | 否 | 容差，默认 `1.0` |
| `timeout` | 否 | 超时秒数，默认 `3600` |

说明：

- 判断逻辑基于当前温度和设定温度差值
- 超时会导致该步骤失败，不会静默继续

### 5.4 `pump_complete`

等待指定泵通道运行结束。

字段：

| 字段 | 必填 | 说明 |
|------|------|------|
| `device_id` | 是 | 泵 ID |
| `channel` | 是 | 通道号 |
| `timeout` | 否 | 超时秒数，默认 `3600` |

说明：

- 超时会导致步骤失败
- stop 会中断该等待

### 5.5 `microwave_temperature_reached`

等待微波仪物料温度达到目标温度。

字段：

| 字段 | 必填 | 说明 |
|------|------|------|
| `device_id` | 是 | 微波仪 ID |
| `target_temperature` | 是 | 目标温度 |
| `tolerance` | 否 | 容差，默认 `1.0` |
| `timeout` | 否 | 超时秒数，默认 `3600` |

说明：

- 判断逻辑基于 `DeviceManager.read_microwave_data()` 返回的 `material_temperature`
- 超时会导致步骤失败
- stop 会中断该等待

### 5.6 `microwave_complete`

等待微波仪运行完成。

字段：

| 字段 | 必填 | 说明 |
|------|------|------|
| `device_id` | 是 | 微波仪 ID |
| `timeout` | 否 | 超时秒数，默认 `3600` |

说明：

- 如果微波仪状态 payload 中有明确完成信号，例如 `completed: true`，则立即判定完成
- 如果没有明确完成信号，则等待过程会先观察到一次“运行中”，之后当 `running` 变为 `false` 时判定完成
- 这样可以避免设备尚未真正启动时，因为初始 `running=false` 而被误判为“已完成”
- `running` 仍是当前软件层的保守运行态，不等同于实验室已确认的真实完成寄存器语义
- 超时会导致步骤失败
- stop 会中断该等待

---

## 6. 最小示例

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

---

## 7. 带 metadata 的完整示例

```yaml
name: cspbbr3_baseline
description: metadata demo
metadata:
  material_system: CsPbBr3
  batch_id: CsPbBr3_20260528_B01
  condition_id: T140_t180_R2
  sample_index: 3
  operator: WH
  recipe_version: v0.1
steps:
  - id: heat_up
    type: heater.set_temperature
    params:
      device_id: heater1
      temperature: 140.0
    wait:
      type: temperature_reached
      device_id: heater1
      tolerance: 1.0
      timeout: 600
```

---

## 8. 泵模式示例

### 8.1 流量模式

```yaml
- id: ch1_flow
  type: pump.start
  params:
    device_id: pump1
    channel: 1
    flow_rate: 5.0
    mode: FLOW_MODE
    tube_model: 13
    flow_unit: 1
```

### 8.2 定时定量模式

```yaml
- id: ch2_time_quantity
  type: pump.start
  params:
    device_id: pump1
    channel: 2
    flow_rate: 10.0
    mode: TIME_QUANTITY
    run_time: 1
    time_unit: 1
    dispense_volume: 10.0
    volume_unit: 1
    repeat_count: 3
    interval_time: 2.0
    interval_time_unit: 0
```

---

## 9. 常见错误

### 9.1 文件名错误

错误：

```yaml
../bad.yaml
```

原因：

- 当前系统会拒绝路径穿越形式的文件名

### 9.2 动作名错误

错误：

```yaml
type: set_temperature
```

正确：

```yaml
type: heater.set_temperature
```

### 9.3 缺少 `steps`

错误：

```yaml
name: bad
description: no steps
```

原因：

- `steps` 是必填顶层字段

### 9.4 重复模式缺少间隔

错误：

```yaml
repeat_count: 3
interval_time: 0
```

原因：

- `repeat_count != 1` 时必须有大于 0 的 `interval_time`

### 9.5 单位省略太多

虽然系统会为部分单位补默认值，但建议显式写出：

- `time_unit`
- `volume_unit`
- `interval_time_unit`
- `flow_unit`

这样更容易调试和复现实验。

### 9.6 微波仪自动控制失败

现象：

- `microwave.configure_*` 或 `microwave.start` 步骤失败。

原因：

- 目标微波仪未连接，或驱动返回 `False`。
- 真实设备、门控联锁、HMI 状态或串口协议拒绝执行。
- 等待条件 timeout，或读取状态失败。

处理：

- 先确认 `/control` 页面能连接并读取目标微波仪，串口号与现场设备一致。
- 检查设备面板、炉门联锁、fault code、功率/电流和实验日志。
- 按 [microwave_smoke_test.md](microwave_smoke_test.md) 记录真实设备行为。
