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

- 状态：未开始。
- 验证：未运行。
- 交接：下一任务 `04_frontend_control_dashboard.md` 负责前端接入。
