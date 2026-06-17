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

- 状态：2026-06-17 已完成本任务范围内的实验 YAML 自动化接入。未改前端，未新增 REST API，未连接真实硬件，未做用户/开发文档收口。
- 已完成：
  - 在 `src/experiment/actions.py` 新增微波仪动作：`microwave.configure_manual`、`microwave.configure_auto_power`、`microwave.configure_constant_rate`、`microwave.start`、`microwave.stop`。
  - 在 `src/experiment/actions.py` 新增等待类型：`microwave_temperature_reached`、`microwave_complete`，并为等待条件补 `target_temperature` 字段。
  - 在 `src/experiment/parser.py` 新增动作和等待类型映射，`microwave_temperature_reached` 支持 `target_temperature`，兼容 `temperature` 别名。
  - 在 `src/experiment/executor.py` 接入微波仪 configure/start/stop。`microwave.configure_*` 和 `microwave.start` 执行前检查 `allow_experiment_control`，禁用时返回 `False`、记录明确日志，并且不调用设备方法。
  - `microwave.stop` 不受 `allow_experiment_control=false` 限制，仍允许通过 `DeviceManager.stop_microwave()` 做安全停机。
  - `microwave_temperature_reached` 通过 `DeviceManager.read_microwave_data()` 读取 `material_temperature` 并比较目标温度，timeout 返回失败，stop 请求可中断。
  - `microwave_complete` 通过微波仪 payload 的 `running` 判断完成，timeout 返回失败，stop 请求可中断。
  - 在 `src/web/device_manager.py` 新增只读薄方法 `is_microwave_experiment_control_allowed(device_id)`，供 executor 查询安全闸。
  - 新增 `tests/test_microwave_experiment.py`，覆盖 parser 识别、成功配置/启动、禁用拒绝、stop 放行、设备返回 `False`、两个等待条件的成功/timeout/stop 中断。
  - 对 `docs/experiment_yaml_spec.md` 做最小同步，记录微波仪动作、等待类型和默认禁用安全闸；正式示例、用户/开发说明和 smoke test 清单留给 06。
- 验证：
  - `python tests\test_microwave_experiment.py`：通过，12 passed, 0 failed。
  - `python tests\test_metadata.py`：通过，36 passed, 0 failed。
  - `python -m pytest tests\test_microwave_experiment.py -q`：未执行成功，当前环境缺少 `pytest`（`No module named pytest`）。
  - `python -c "import src.experiment.actions; import src.experiment.parser; import src.experiment.executor"`：通过，退出码 0。
  - `python tests\test_microwave.py`：通过，10 passed, 0 failed。
  - `python tests\test_microwave_api_ws.py`：通过，7 passed, 0 failed。
  - `python -c "import src.web.device_manager; import src.web.api.devices; import src.web.api.ws"`：通过，退出码 0。
- 遗留问题：
  - 真实硬件未连接、未写入、未 smoke test；微波仪真实 start/stop 和自动实验控制仍不能视为实验室确认可用。
  - `allow_experiment_control` 和 `enable_control_writes` 必须继续默认关闭，直到实验室确认串口、接线、安全授权、协议写入顺序和真实停机语义。
  - `microwave_complete` 当前依赖 API/WS 任务留下的保守 `running` payload；该字段仍不是实机确认的运行状态寄存器。
  - `docs/experiment_yaml_spec.md` 只是最小事实同步，尚未形成正式用户示例或 smoke-test 操作文档。
  - `context/PROJECT_CONTEXT.md` 中的“当前实验动作与等待类型”仍需在 06 文档收口时统一更新，避免本窗口扩大范围。
- 交接给 06：
  - `06_docs_and_smoke_test.md` 需要正式同步用户/开发/YAML 文档，补微波仪动作和等待类型的审核说明，但不要提供可直接照抄的真实化学配方。
  - smoke test 清单必须继续强调：真实微波 start/自动实验控制只有在实验室确认设备身份、接线、安全授权、协议写入顺序和停机语义后才能启用。
  - 06 应检查 `context/PROJECT_CONTEXT.md`、`docs/user_guide.md`、`docs/developer_guide.md` 和 `docs/experiment_yaml_spec.md` 的事实一致性，尤其是动作/等待类型清单和 `allow_experiment_control=false` 默认拒绝语义。
  - 前端相关改动属于 04 的范围，本任务未修改；06 如需收口，应先区分已有 04 工作树改动与本任务后端/YAML 改动。
