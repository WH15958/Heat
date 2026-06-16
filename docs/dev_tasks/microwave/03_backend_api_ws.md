# 03 后端 API 与 WebSocket

## 目标

在 `02_backend_driver.md` 完成后，把微波仪驱动暴露到 Web 层：REST API、WebSocket 实时 payload、全局急停。此任务不做前端页面和 YAML 自动化。

## 输入资料

- `docs/dev_tasks/microwave/00_index.md`
- `docs/dev_tasks/microwave/01_protocol_register_map.md`
- `docs/dev_tasks/microwave/02_backend_driver.md`
- `src/web/api/devices.py`
- `src/web/api/ws.py`
- `src/web/app.py`
- `src/web/device_manager.py`

## 允许修改

- `src/web/api/devices.py`
- `src/web/api/ws.py`
- `src/web/app.py`
- `src/web/device_manager.py`，仅补 API 需要的薄包装
- 后端 API/WS 测试文件

## 不做

- 不改前端。
- 不改 YAML parser/executor。
- 不新增真实硬件 smoke test 脚本，除非只是 fake 测试。
- 不改变 heater/pump 现有接口语义。

## REST API

新增接口前缀保持当前设备 API 风格：

```text
POST /api/microwave/{device_id}/connect
POST /api/microwave/{device_id}/disconnect
GET  /api/microwave/{device_id}/data
POST /api/microwave/{device_id}/configure/manual
POST /api/microwave/{device_id}/configure/auto_power
POST /api/microwave/{device_id}/configure/constant_rate
POST /api/microwave/{device_id}/start
POST /api/microwave/{device_id}/stop
```

请求模型：

- `MicrowaveSegmentRequest`
  - `segment: int`
  - 温度字段按模式明确命名
  - 功率字段只在手动模式中允许
  - 时间字段使用 `hours`、`minutes`、`seconds`
- `MicrowaveConfigureRequest`
  - `segments: list[MicrowaveSegmentRequest]`
- `MicrowaveStartRequest`
  - `mode: "manual_power" | "auto_power" | "constant_rate"`

响应模型保持项目现状的简单 dict 风格：

```json
{
  "success": true,
  "device_id": "microwave1"
}
```

读取状态返回：

```json
{
  "device_id": "microwave1",
  "running": false,
  "mode": "unknown",
  "current_segment": 0,
  "material_temperature": 25.0,
  "temperature_source": "float",
  "power_percent": 0,
  "current": 0,
  "runtime_seconds": 0,
  "fault_code": 0,
  "faults": []
}
```

## WebSocket payload

把当前 payload 从：

```json
{
  "type": "realtime",
  "heaters": {},
  "pumps": {}
}
```

扩展为：

```json
{
  "type": "realtime",
  "heaters": {},
  "pumps": {},
  "microwaves": {}
}
```

微波设备在线时：

```json
{
  "microwaves": {
    "microwave1": {
      "device_id": "microwave1",
      "running": false,
      "mode": "manual_power",
      "current_segment": 1,
      "material_temperature": 25.0,
      "temperature_source": "float",
      "power_percent": 0,
      "current": 0,
      "runtime_seconds": 0,
      "fault_code": 0,
      "faults": []
    }
  }
}
```

读取失败时：

```json
{
  "error": "read_failed"
}
```

WebSocket 断开不能触发任何设备 stop。

## 急停接入

`/api/emergency_stop` 和 `DeviceManager.emergency_stop_all()` 必须调用微波仪 `emergency_stop()`。

要求：

- 单个微波 stop 失败要记录日志。
- 不因为一个设备失败跳过其他设备。
- 返回值不要伪造每台设备都成功；若当前 API 只返回全局 success，则至少日志要保留失败细节。

## 测试要求

使用 fake `DeviceManager` 或 fake microwave device。

必须覆盖：

- `/api/devices` 包含 `microwaves`。
- connect/disconnect 调用正确的 manager 方法。
- configure/start/stop 的失败返回不会变成成功。
- WebSocket payload 包含 `microwaves` key。
- 微波读取 timeout 或异常时 payload 写入 error。
- WebSocket connect/disconnect 不调用 stop。
- emergency stop 调用微波 stop。

## 验收

建议运行：

```powershell
python tests\test_metadata.py
python -c "import src.web.app; import src.web.api.devices; import src.web.api.ws"
python -m pytest <新增或相关API测试> -q
git diff --check -- src tests
```

如果 `pytest` 不可用，用等价 Python 验证并记录。

## 完成记录

- 状态：2026-06-16 已完成本任务范围内的后端 API、WebSocket payload、配置注册和全局急停接入。未改前端、未改 YAML parser/executor，未连接真实硬件。
- 已完成：
  - 在 `src/web/api/devices.py` 新增 `/api/microwave/{device_id}/...` 路由：connect、disconnect、data、configure/manual、configure/auto_power、configure/constant_rate、start、stop。
  - 新增 `MicrowaveSegmentRequest`、`MicrowaveConfigureRequest`、`MicrowaveStartRequest`，非手动模式拒绝功率字段；Web 层通过 `run_in_executor` 调用同步 `DeviceManager`/`MicrowaveDevice`。
  - 微波 API 对设备返回 `False` 显式返回 HTTP 400，不把失败包装成成功；读取异常按现有设备接口风格返回失败状态码。
  - `src/web/api/ws.py` 的实时 payload 增加 `microwaves` key，微波读取走 `run_in_executor`，timeout 或异常写入 `{"error": "read_failed"}`；WebSocket connect/disconnect 路径不启动、停止或改变硬件状态。
  - `src/web/app.py` 从配置注册 enabled microwave，保留 `allow_experiment_control=false` 和 `enable_control_writes=false` 安全默认。
  - `src/web/device_manager.py` 统一微波状态 payload，`/api/devices` 和数据 payload 展示微波安全开关；`emergency_stop_all()` 调用微波 `emergency_stop()`，单个设备返回 `False` 或异常时记录失败并继续停止其他设备。
  - 新增 `tests/test_microwave_api_ws.py`，使用 fake manager/device 覆盖 API、WS payload、失败传播、WS 断开无停机副作用和急停微波调用。
- 验证：
  - `python tests\test_metadata.py`：通过，36 passed, 0 failed。
  - `python -c "import src.web.app; import src.web.api.devices; import src.web.api.ws"`：通过，退出码 0。
  - `python -m pytest tests\test_microwave_api_ws.py -q`：未执行成功，当前环境缺少 `pytest`（`No module named pytest`）。
  - `python tests\test_microwave_api_ws.py`：通过，7 passed, 0 failed，作为 pytest 不可用时的等价 fallback。
  - `python tests\test_microwave.py`：通过，10 passed, 0 failed。
  - `git diff --check -- src tests`：通过，退出码 0；仅提示部分已编辑文本下次 Git 触碰时 LF/CRLF 转换，无 whitespace error。
- 遗留问题：
  - 真实硬件未连接、未写入、未 smoke test；`enable_control_writes` 仍必须默认关闭，直到实验室确认串口、接线、安全授权和真实写入时序。
  - 协议未提供明确运行状态、模式枚举和故障 bit 映射；当前 API/WS 保留 `mode="unknown"`、暴露 `current_mode_code` 和原始 `fault_code`，`faults` 暂为空列表。
  - `running` 仅由实时功率是否非零做保守展示，不能替代实机确认的运行状态寄存器。
  - `40151` stop 写 `0` 仍只在 fake protocol 中验证，真实设备 stop 语义需 smoke test 确认。
- 交接给 04：
  - 前端只调用本任务新增的 `/api/microwave/...` 接口和 WS `microwaves` payload，不直接假设微波仪已允许真实写入。
  - 前端应清楚展示 `enable_control_writes=false`、`allow_experiment_control=false`、`mode="unknown"`、`fault_code` 和读取失败状态，不把禁用或失败显示为成功。
  - 前端按钮可以接手动连接、读取、配置和 stop/emergency stop；真实 start 控件必须尊重后端失败返回和实验室 smoke-test 门槛。
  - 不要在 04 中加入 YAML 自动化；YAML 接入仍留给 `05_experiment_yaml_automation.md`。
