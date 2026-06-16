# 05 实验 YAML 自动化

## 目标

把微波仪接入实验流程，新增 YAML 动作和等待条件。此任务必须保持自动控制默认禁用，只有设备配置显式允许时才执行真实 start/configure。

## 输入资料

- `docs/dev_tasks/microwave/00_index.md`
- `docs/dev_tasks/microwave/01_protocol_register_map.md`
- `docs/dev_tasks/microwave/02_backend_driver.md`
- `docs/dev_tasks/microwave/03_backend_api_ws.md`
- `src/experiment/actions.py`
- `src/experiment/parser.py`
- `src/experiment/executor.py`
- `src/experiment/engine.py`
- `docs/experiment_yaml_spec.md`

## 允许修改

- `src/experiment/actions.py`
- `src/experiment/parser.py`
- `src/experiment/executor.py`
- `src/web/device_manager.py`，仅补 executor 所需方法
- 相关 parser/executor 测试
- `docs/experiment_yaml_spec.md` 可只加临时 TODO；正式文档收口在 `06_docs_and_smoke_test.md`

## 不做

- 不改前端。
- 不新增 REST API。
- 不绕过 `DeviceManager` 直接操作设备。
- 不提供化学配方、推荐工艺或可直接照抄的真实实验方案。

## 新增动作

新增 `ActionType`：

```text
microwave.configure_manual
microwave.configure_auto_power
microwave.configure_constant_rate
microwave.start
microwave.stop
```

新增 `ACTION_MAP` 字符串映射。

## 动作参数

`microwave.configure_manual`：

```yaml
type: microwave.configure_manual
params:
  device_id: microwave1
  segments:
    - segment: 1
      heat_temperature: 80
      heat_power: 20
      hold_temperature: 80
      hold_power: 20
      hold_deviation: 2
      hold_hours: 0
      hold_minutes: 5
      hold_seconds: 0
```

`microwave.configure_auto_power`：

```yaml
type: microwave.configure_auto_power
params:
  device_id: microwave1
  segments:
    - segment: 1
      ramp_target_temperature: 80
      hold_target_temperature: 80
      hours: 0
      minutes: 5
      seconds: 0
```

`microwave.configure_constant_rate`：

```yaml
type: microwave.configure_constant_rate
params:
  device_id: microwave1
  segments:
    - segment: 1
      ramp_hours: 0
      ramp_minutes: 2
      ramp_seconds: 0
      target_temperature: 80
      hold_hours: 0
      hold_minutes: 5
      hold_seconds: 0
      hold_temperature: 80
```

`microwave.start`：

```yaml
type: microwave.start
params:
  device_id: microwave1
  mode: manual_power
```

`microwave.stop`：

```yaml
type: microwave.stop
params:
  device_id: microwave1
```

## 新增等待类型

新增 `WaitType`：

```text
microwave_temperature_reached
microwave_complete
```

`microwave_temperature_reached`：

- 读取 `DeviceManager.read_microwave_data(device_id)`。
- 使用 `material_temperature` 和目标温度比较。
- 支持 `tolerance` 和 `timeout`。
- stop 请求必须尽快中断。
- timeout 返回失败。

`microwave_complete`：

- 读取 `running` 或当前模式/运行状态。
- 当设备不再运行时完成。
- 支持 `timeout`。
- stop 请求必须尽快中断。

## 自动控制安全闸

执行以下动作前必须检查配置或设备状态中的 `allow_experiment_control`：

- `microwave.configure_manual`
- `microwave.configure_auto_power`
- `microwave.configure_constant_rate`
- `microwave.start`

默认值为 `false` 时：

- executor 返回 `False`。
- 日志写明 `microwave experiment control is disabled` 或等价明确原因。
- 不调用真实设备方法。

`microwave.stop` 和全局 `emergency_stop` 可以在禁用自动控制时仍允许执行，用于安全停机；若实现者选择限制，也必须在文档中说明理由。

## 测试要求

必须覆盖：

- parser 识别新增动作。
- parser 识别新增等待类型。
- `allow_experiment_control=false` 时 configure/start 被拒绝。
- `microwave.stop` 调用 manager stop。
- 设备方法返回 `False` 时步骤失败。
- `microwave_temperature_reached` 成功路径。
- `microwave_temperature_reached` timeout 失败。
- `microwave_temperature_reached` 被 stop 中断。
- `microwave_complete` 成功、timeout、中断。

## 验收

建议运行：

```powershell
python tests\test_metadata.py
python -m pytest <新增或相关实验测试> -q
python -c "import src.experiment.actions; import src.experiment.parser; import src.experiment.executor"
git diff --check -- src tests docs/experiment_yaml_spec.md
```

## 完成记录

- 状态：未开始。
- 验证：未运行。
- 交接：下一任务 `06_docs_and_smoke_test.md` 负责正式用户/开发/YAML 文档同步和实机验证清单。
