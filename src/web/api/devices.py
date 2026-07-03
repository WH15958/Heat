import asyncio

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import List, Optional

from devices.microwave import MicrowaveSegment
from protocols.microwave_params import MicrowaveMode
from protocols.pump_params import PumpDirection, PumpRunMode

router = APIRouter(tags=["devices"])


class SetTemperatureRequest(BaseModel):
    """设置温度请求"""
    temperature: float


class StartPumpRequest(BaseModel):
    """启动泵请求"""
    channel: int = 1
    flow_rate: float = 10.0
    direction: str = "CW"
    mode: str = "FLOW_MODE"
    run_time: Optional[float] = None
    dispense_volume: Optional[float] = None
    tube_model: Optional[int] = None
    flow_unit: Optional[int] = None
    time_unit: Optional[int] = None
    volume_unit: Optional[int] = None
    repeat_count: Optional[int] = None
    interval_time: Optional[float] = None
    interval_time_unit: Optional[int] = None


class StopPumpRequest(BaseModel):
    """停止泵请求"""
    channel: Optional[int] = None


class MicrowaveSegmentRequest(BaseModel):
    """微波仪段参数请求"""
    segment: int
    heating_temperature: float = 0.0
    target_temperature: Optional[float] = None
    holding_temperature: float = 0.0
    heating_power_percent: Optional[int] = None
    holding_power_percent: Optional[int] = None
    holding_deviation: float = 0.0
    hours: int = 0
    minutes: int = 0
    seconds: int = 0
    ramp_hours: int = 0
    ramp_minutes: int = 0
    ramp_seconds: int = 0


class MicrowaveConfigureRequest(BaseModel):
    """微波仪配置请求"""
    segments: List[MicrowaveSegmentRequest]
    confirm_real_hardware_write: bool = False


class MicrowaveStartRequest(BaseModel):
    """微波仪启动请求"""
    mode: str


def get_dm(request: Request) -> "DeviceManager":
    """从应用状态获取设备管理器

    Args:
        request: FastAPI请求对象

    Returns:
        DeviceManager: 设备管理器
    """
    return request.app.state.device_manager


def _microwave_segments(
    body: MicrowaveConfigureRequest,
    allow_power_fields: bool,
) -> List[MicrowaveSegment]:
    """转换微波仪段请求，避免非手动模式携带功率字段"""
    segments = []
    for segment in body.segments:
        if not allow_power_fields and (
            segment.heating_power_percent is not None
            or segment.holding_power_percent is not None
        ):
            raise HTTPException(
                status_code=400,
                detail="power fields are only allowed for manual_power mode",
            )
        segments.append(MicrowaveSegment(
            segment=segment.segment,
            heating_temperature=segment.heating_temperature,
            heating_power_percent=segment.heating_power_percent or 0,
            holding_temperature=segment.holding_temperature,
            holding_power_percent=segment.holding_power_percent or 0,
            holding_deviation=segment.holding_deviation,
            hours=segment.hours,
            minutes=segment.minutes,
            seconds=segment.seconds,
            target_temperature=segment.target_temperature,
            ramp_hours=segment.ramp_hours,
            ramp_minutes=segment.ramp_minutes,
            ramp_seconds=segment.ramp_seconds,
        ))
    return segments


def _raise_if_false(result: bool, action: str):
    if not result:
        raise HTTPException(status_code=400, detail=f"Microwave {action} failed")


@router.get("/devices")
async def list_devices(request: Request):
    """列出所有设备及状态

    Returns:
        dict: 设备状态摘要
    """
    dm = get_dm(request)
    return dm.get_all_status()


@router.post("/devices/refresh_bindings")
async def refresh_device_bindings(request: Request):
    """重新扫描本机串口并刷新设备绑定解析结果。"""
    dm = get_dm(request)
    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, dm.refresh_bindings)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/heater/{device_id}/connect")
async def connect_heater(device_id: str, request: Request):
    """连接加热器

    Args:
        device_id: 设备ID

    Returns:
        dict: 连接结果
    """
    dm = get_dm(request)
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, dm.connect_heater, device_id)
        return {"success": result, "device_id": device_id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/heater/{device_id}/disconnect")
async def disconnect_heater(device_id: str, request: Request):
    """断开加热器

    Args:
        device_id: 设备ID

    Returns:
        dict: 断开结果
    """
    dm = get_dm(request)
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, dm.disconnect_heater, device_id)
        return {"success": result, "device_id": device_id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/heater/{device_id}/data")
async def read_heater_data(device_id: str, request: Request):
    """读取加热器数据

    Args:
        device_id: 设备ID

    Returns:
        dict: 加热器数据
    """
    dm = get_dm(request)
    try:
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, dm.read_heater_data, device_id)
        return data
    except IOError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/heater/{device_id}/set_temperature")
async def set_temperature(
    device_id: str, body: SetTemperatureRequest, request: Request
):
    """设置加热器目标温度

    Args:
        device_id: 设备ID
        body: 温度请求体

    Returns:
        dict: 设置结果
    """
    dm = get_dm(request)
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, dm.set_temperature, device_id, body.temperature)
        return {"success": result, "temperature": body.temperature}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/heater/{device_id}/start")
async def start_heater(device_id: str, request: Request):
    """启动加热器

    Args:
        device_id: 设备ID

    Returns:
        dict: 启动结果
    """
    dm = get_dm(request)
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, dm.start_heater, device_id)
        return {"success": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/heater/{device_id}/stop")
async def stop_heater(device_id: str, request: Request):
    """停止加热器

    Args:
        device_id: 设备ID

    Returns:
        dict: 停止结果
    """
    dm = get_dm(request)
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, dm.stop_heater, device_id)
        return {"success": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/microwave/{device_id}/connect")
async def connect_microwave(device_id: str, request: Request):
    """连接微波仪"""
    dm = get_dm(request)
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, dm.connect_microwave, device_id)
        _raise_if_false(result, "connect")
        return {"success": True, "device_id": device_id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/microwave/{device_id}/disconnect")
async def disconnect_microwave(device_id: str, request: Request):
    """断开微波仪"""
    dm = get_dm(request)
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, dm.disconnect_microwave, device_id)
        _raise_if_false(result, "disconnect")
        return {"success": True, "device_id": device_id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/microwave/{device_id}/data")
async def read_microwave_data(device_id: str, request: Request):
    """读取微波仪数据"""
    dm = get_dm(request)
    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, dm.read_microwave_data, device_id)
    except IOError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/microwave/{device_id}/configure/manual")
async def configure_microwave_manual(
    device_id: str, body: MicrowaveConfigureRequest, request: Request
):
    """配置微波仪手动功率模式"""
    dm = get_dm(request)
    try:
        segments = _microwave_segments(body, allow_power_fields=True)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, dm.configure_microwave_manual, device_id, segments
        )
        _raise_if_false(result, "configure manual")
        return {"success": True, "device_id": device_id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/microwave/{device_id}/configure/auto_power")
async def configure_microwave_auto_power(
    device_id: str, body: MicrowaveConfigureRequest, request: Request
):
    """配置微波仪自动功率模式"""
    dm = get_dm(request)
    try:
        segments = _microwave_segments(body, allow_power_fields=False)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, dm.configure_microwave_auto_power, device_id, segments
        )
        _raise_if_false(result, "configure auto_power")
        return {"success": True, "device_id": device_id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/microwave/{device_id}/configure/constant_rate")
async def configure_microwave_constant_rate(
    device_id: str, body: MicrowaveConfigureRequest, request: Request
):
    """配置微波仪恒速率模式"""
    dm = get_dm(request)
    try:
        segments = _microwave_segments(body, allow_power_fields=False)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, dm.configure_microwave_constant_rate, device_id, segments
        )
        _raise_if_false(result, "configure constant_rate")
        return {"success": True, "device_id": device_id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/microwave/{device_id}/start")
async def start_microwave(
    device_id: str, body: MicrowaveStartRequest, request: Request
):
    """启动微波仪输出"""
    dm = get_dm(request)
    try:
        mode = MicrowaveMode.from_value(body.mode)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unsupported microwave mode: {body.mode}")
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, dm.start_microwave, device_id, mode)
        _raise_if_false(result, "start")
        return {"success": True, "device_id": device_id, "mode": mode.value}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/microwave/{device_id}/stop")
async def stop_microwave(device_id: str, request: Request):
    """停止微波仪输出"""
    dm = get_dm(request)
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, dm.stop_microwave, device_id)
        _raise_if_false(result, "stop")
        return {"success": True, "device_id": device_id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/pump/{device_id}/connect")
async def connect_pump(device_id: str, request: Request):
    """连接蠕动泵

    Args:
        device_id: 设备ID

    Returns:
        dict: 连接结果
    """
    dm = get_dm(request)
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, dm.connect_pump, device_id)
        return {"success": result, "device_id": device_id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/pump/{device_id}/disconnect")
async def disconnect_pump(device_id: str, request: Request):
    """断开蠕动泵

    Args:
        device_id: 设备ID

    Returns:
        dict: 断开结果
    """
    dm = get_dm(request)
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, dm.disconnect_pump, device_id)
        return {"success": result, "device_id": device_id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/pump/{device_id}/status")
async def read_pump_status(device_id: str, request: Request):
    """读取蠕动泵状态

    Args:
        device_id: 设备ID

    Returns:
        dict: 泵状态数据
    """
    dm = get_dm(request)
    try:
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, dm.read_pump_status, device_id)
        return data
    except IOError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/pump/{device_id}/start")
async def start_pump(device_id: str, body: StartPumpRequest, request: Request):
    """启动蠕动泵通道

    Args:
        device_id: 设备ID
        body: 启动请求体

    Returns:
        dict: 启动结果
    """
    dm = get_dm(request)
    try:
        direction = (
            PumpDirection.CLOCKWISE
            if body.direction == "CW"
            else PumpDirection.COUNTER_CLOCKWISE
        )
        mode_map = {
            "FLOW_MODE": PumpRunMode.FLOW_MODE,
            "TIME_QUANTITY": PumpRunMode.TIME_QUANTITY,
            "TIME_SPEED": PumpRunMode.TIME_SPEED,
            "QUANTITY_SPEED": PumpRunMode.QUANTITY_SPEED,
        }
        run_mode = mode_map.get(body.mode, PumpRunMode.FLOW_MODE)
        loop = asyncio.get_event_loop()
        run_time = body.run_time if run_mode in (
            PumpRunMode.TIME_QUANTITY,
            PumpRunMode.TIME_SPEED,
        ) else None
        dispense_volume = body.dispense_volume if run_mode in (
            PumpRunMode.TIME_QUANTITY,
            PumpRunMode.QUANTITY_SPEED,
        ) else None
        result = await loop.run_in_executor(
            None, dm.start_pump_channel, device_id, body.channel,
            body.flow_rate, direction, run_mode, run_time, dispense_volume,
            body.tube_model, body.flow_unit, body.time_unit, body.volume_unit,
            body.repeat_count, body.interval_time, body.interval_time_unit,
        )
        return {
            "success": result,
            "channel": body.channel,
            "flow_rate": body.flow_rate,
            "mode": body.mode,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/pump/{device_id}/stop")
async def stop_pump(device_id: str, body: StopPumpRequest, request: Request):
    """停止蠕动泵

    Args:
        device_id: 设备ID
        body: 停止请求体

    Returns:
        dict: 停止结果
    """
    dm = get_dm(request)
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, dm.stop_pump_channel, device_id, body.channel)
        return {"success": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/emergency_stop")
async def emergency_stop(request: Request):
    """紧急停止所有设备

    Returns:
        dict: 停止结果
    """
    dm = get_dm(request)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, dm.emergency_stop_all)
    return {"success": bool(result)}


@router.get("/pump/{device_id}/diagnose")
async def pump_diagnose(device_id: str, request: Request):
    """蠕动泵MODBUS通信诊断

    Returns:
        dict: 诊断结果
    """
    dm = get_dm(request)
    pump = dm.get_pump(device_id)
    if pump is None:
        raise HTTPException(status_code=404, detail=f"Pump not found: {device_id}")

    result = {
        "device_id": device_id,
        "status": pump.status.name,
        "connected": pump.is_connected(),
    }

    if pump.is_connected():
        loop = asyncio.get_event_loop()
        channel_tests = {}
        for ch in range(1, 5):
            try:
                ch_data = await asyncio.wait_for(
                    loop.run_in_executor(None, pump.read_channel_status, ch),
                    timeout=5.0,
                )
                channel_tests[f"CH{ch}"] = {
                    "success": True,
                    "running": ch_data.running,
                    "flow_rate": ch_data.flow_rate,
                }
            except asyncio.TimeoutError:
                channel_tests[f"CH{ch}"] = {"success": False, "error": "timeout"}
            except Exception as e:
                channel_tests[f"CH{ch}"] = {"success": False, "error": str(e)}
        result["channel_tests"] = channel_tests

    return result


@router.get("/pump/{device_id}/settings")
async def get_pump_settings(device_id: str, request: Request):
    """获取蠕动泵当前设置参数

    Returns:
        dict: 各通道的设置参数
    """
    dm = get_dm(request)
    pump = dm.get_pump(device_id)
    if pump is None:
        raise HTTPException(status_code=404, detail=f"Pump not found: {device_id}")

    settings = {"device_id": device_id, "channels": {}}
    for ch in range(1, 5):
        ch_data = pump.channel_data.get(ch)
        if ch_data:
            settings["channels"][str(ch)] = {
                "enabled": ch_data.enabled,
                "running": ch_data.running,
                "flow_rate": ch_data.flow_rate,
                "direction": ch_data.direction.name if ch_data.direction else "CW",
                "run_mode": ch_data.run_mode.name if ch_data.run_mode else "FLOW_MODE",
            }
    return settings
