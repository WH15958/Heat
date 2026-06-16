# 02 后端同步驱动

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

- 状态：未开始。
- 验证：未运行。
- 交接：下一任务 `03_backend_api_ws.md` 负责把驱动暴露给 Web 层。
