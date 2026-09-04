# 02 后端同步驱动

> 归档提示：本文件是已完成任务记录，不代表当前实现或实机验收结论。

## 目标

基于 `01_protocol_register_map.md` 实现微波仪同步驱动、协议常量、配置模型和 `DeviceManager` 基础注册。此任务结束后，后端应能在 fake Modbus 下完成参数写入、状态读取、start/stop 控制字写入和失败传播。

## 输入资料

- `docs/dev_tasks/microwave/00_index.md`
- `docs/dev_tasks/microwave/01_protocol_register_map.md`
- `src/protocols/modbus_rtu.py`
- `src/devices/base_device.py`
- `src/devices/peristaltic_pump.py`
- `src/web/device_manager.py`
- `src/utils/config.py`
- `config/system_config.yaml`

## 允许修改

- `src/protocols/microwave_params.py`
- `src/protocols/__init__.py`
- `src/devices/microwave.py`
- `src/devices/__init__.py`
- `src/utils/config.py`
- `src/web/device_manager.py`
- `config/system_config.yaml`
- `tests/test_microwave.py` 或等价后端测试文件

## 不做

- 不新增 REST API。
- 不改 WebSocket。
- 不改前端。
- 不改实验 YAML parser/executor。
- 不真实连接或启动微波仪。

## 实现要求

- 新增协议常量：
  - `MicrowaveMode`: `manual_power`、`auto_power`、`constant_rate`
  - 地址转换 helper：`holding_address(40001) == 0`
  - 手动、自动功率、恒速率、状态、控制字寄存器常量
  - 控制字 mask：bit15、bit14、bit13、bit12
- 新增数据结构：
  - `MicrowaveSegment`
  - `MicrowaveStatus`
  - `MicrowaveConfig`
  - `MicrowaveData`
- 新增同步驱动 `MicrowaveDevice(BaseDevice)`：
  - `connect()`
  - `disconnect()`
  - `is_connected()`
  - `read_data()`
  - `configure_manual(segments)`
  - `configure_auto_power(segments)`
  - `configure_constant_rate(segments)`
  - `start(mode)`
  - `stop()`
  - `emergency_stop()`
  - `write_command(command, value)`
  - `get_available_commands()`

## 安全默认

- 配置中新增 `allow_experiment_control: false`，即使设备启用，也默认不允许实验 YAML 自动启动。
- `max_temperature` 默认 300。
- `max_power_percent` 默认 100。
- 参数写入前校验：
  - 温度 `0 <= temperature <= max_temperature`
  - 功率 `0 <= power_percent <= max_power_percent`
  - 时、分、秒不能为负
  - 段号只能 1-5
- 任何寄存器写入失败返回 `False`。
- 多寄存器配置中任一步失败，整体返回 `False`。

## DeviceManager 接入

新增内部集合和方法：

- `_microwaves`
- `add_microwave(...)`
- `connect_microwave(device_id)`
- `disconnect_microwave(device_id)`
- `read_microwave_data(device_id)`
- `configure_microwave_manual(device_id, segments)`
- `configure_microwave_auto_power(device_id, segments)`
- `configure_microwave_constant_rate(device_id, segments)`
- `start_microwave(device_id, mode)`
- `stop_microwave(device_id)`
- `get_microwave(device_id)`
- `get_all_microwaves()`

`get_all_status()` 返回值增加：

```json
{
  "heaters": {},
  "pumps": {},
  "microwaves": {}
}
```

## 配置接入

在 `config/system_config.yaml` 添加默认禁用配置：

```yaml
microwaves:
  - device_id: "microwave1"
    name: "MKM-AH1E微波合成仪"
    connection:
      port: "COM1"
      baudrate: 9600
      address: 1
      parity: "N"
      timeout: 2.0
    slave_address: 1
    max_temperature: 300.0
    max_power_percent: 100
    poll_interval: 1.0
    retry_count: 3
    retry_delay: 0.5
    enabled: false
    allow_experiment_control: false
```

## 测试要求

使用 fake protocol，不访问真实串口。

必须覆盖：

- 地址转换：
  - `40001 -> 0`
  - `40151 -> 150`
- 控制字：
  - 手动功率 start 写入 `(1 << 13) | (1 << 12)`
  - 自动功率 start 写入 `(1 << 14) | (1 << 12)`
  - 恒速率 start 写入 `(1 << 15) | (1 << 12)`
  - stop 写入当前实现定义的停止值
- 参数校验：
  - 超过 300 C 拒绝
  - 负时间拒绝
  - 非 1-5 段拒绝
- 状态读取：
  - 40118/40119 浮点温度成功路径
  - 浮点温度失败后回退 40107
  - runtime 合并为秒
- 失败传播：
  - 任一写寄存器失败时配置返回 `False`
  - `read_data()` 未连接时抛出或返回当前项目一致的错误语义

## 验收

建议运行：

```powershell
python tests\test_metadata.py
python -m pytest tests\test_microwave.py -q
python -c "import src.web.app; import src.web.api.experiments; import src.web.api.ws"
git diff --check -- src tests config
```

如果 `pytest` 不可用，用等价 Python 命令运行新增测试，并在完成记录中说明。

## 完成记录

- 状态：2026-06-16 已完成本任务范围内的同步后端驱动、协议常量、配置模型、`DeviceManager` 注册和 fake Modbus 单元测试。真实寄存器写入由 `MicrowaveConfig.enable_control_writes=false` 默认阻断，实验自动控制入口字段 `allow_experiment_control=false` 已保留但未接入 YAML。
- 已完成：
  - 新增 `src/protocols/microwave_params.py`，统一使用 PDU 地址，覆盖 `MicrowaveMode`、`holding_address()`、模式/状态/控制字寄存器和 bit mask。
  - 新增 `src/devices/microwave.py`，实现同步 `MicrowaveDevice`、`MicrowaveSegment`、`MicrowaveStatus`、`MicrowaveConfig`、`MicrowaveData`，不添加线程、轮询、心跳或命令队列。
  - 更新 `src/utils/config.py` 和 `config/system_config.yaml`，默认微波仪禁用，真实写入禁用，实验自动控制禁用。
  - 更新 `src/web/device_manager.py`，增加微波仪集合、注册、连接、读取、配置、start/stop、状态汇总和清理方法；未新增 REST API、WebSocket、前端或 YAML 自动化。
  - 新增 `tests/test_microwave.py`，使用 fake Modbus 覆盖地址转换、控制字、参数校验、状态读取、失败传播和默认写入保护。
- 验证：
  - `python tests\test_metadata.py`：通过，36 passed, 0 failed。
  - `python -m pytest tests\test_microwave.py -q`：未执行成功，当前环境缺少 `pytest`（`No module named pytest`）。
  - `python tests\test_microwave.py`：通过，10 passed, 0 failed，作为 pytest 不可用时的等价 fallback。
  - `python -c "import src.web.app; import src.web.api.experiments; import src.web.api.ws"`：通过，退出码 0。
  - `git diff --check -- src tests config`：通过，退出码 0；仅提示部分已编辑文本下次 Git 触碰时 LF/CRLF 转换，无 whitespace error。
- 遗留问题：
  - 真实硬件未连接、未写入、未 smoke test；`enable_control_writes` 必须保持默认关闭，直到实验室确认串口、接线、安全授权和真实写入时序。
  - `40118`/`40119` 浮点温度字节序/字序仍为软件假设，fake 测试仅覆盖成功和回退路径，不能当作实机确认。
  - `40151` stop 当前实现写入 `0`，只在 fake protocol 中验证；真实设备 stop 语义需 smoke test 确认。
  - 温度、功率、电流寄存器比例系数仍未确认，驱动先按原始寄存器值读写。
  - API、WebSocket、前端和 YAML 自动化均未实现，按任务拆分留给后续窗口。
- 交接给 03：
  - `03_backend_api_ws.md` 可以从 `DeviceManager` 的 `read_microwave_data()`、`configure_microwave_*()`、`start_microwave()`、`stop_microwave()` 暴露 Web 层接口。
  - Web 层只做同步驱动的桥接，异步入口使用既有 `run_in_executor` 风格；不要让 WebSocket connect/disconnect 控制硬件生命周期。
  - API/WS 必须保留并展示 `enable_control_writes=false` 和 `allow_experiment_control=false` 的安全默认，不得默认开放真实 start/stop 或 YAML 自动启动。
  - 任何驱动返回 `False`、读取异常或通信失败都必须向调用方传播为失败，不得记录成成功。
