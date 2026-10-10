import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from typing import List

from src.devices.microwave import MicrowaveSegment
from src.protocols.microwave_params import MicrowaveMode
from src.protocols.pump_params import PumpDirection, PumpRunMode

from src.experiment.parameter_models import (
    SetTemperatureRequest, StartPumpRequest, StopPumpRequest,
    MicrowaveSegmentRequest, MicrowaveConfigureRequest, MicrowaveStartRequest,
)

async def protect_guided_devices(request: Request):
    # Serialize manual writes with batch registration. Reads never take this lock.
    if request.method not in ("POST", "PUT", "DELETE") or request.url.path.endswith("/emergency_stop"):
        yield
        return
    from src.web.api.experiments import _engines, _source_lock
    from src.experiment.guided import GuidedBatch
    from src.experiment.microwave_program import MicrowaveProgramRun
    async with _source_lock:
        is_stop = request.url.path.endswith("/stop")
        if request.url.path.endswith("/command"):
            is_stop = (await request.json()).get("action") == "stop"
        batches = [b for b in _engines.values() if isinstance(b, (GuidedBatch, MicrowaveProgramRun))
                   and (b.state.value in ("running", "paused") or b.cleanup_pending)]
        if batches:
            if is_stop:
                for batch in batches:
                    batch.request_stop()
            else:
                raise HTTPException(409, "批次或微波托管程序占用装置；请先停止再手动操作")
        if not is_stop and not request.url.path.endswith(("/connect", "/disconnect", "/refresh_bindings")):
            from src.web.api.microwave_program import require_recovered
            require_recovered()
        yield


router = APIRouter(tags=["devices"], dependencies=[Depends(protect_guided_devices)])


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
        if not result:
            detail = dm.get_last_command_error(device_id)
            raise HTTPException(
                status_code=400,
                detail=detail or "Heater stop or disconnect failed",
            )
        return {"success": True, "device_id": device_id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
        run_mode = mode_map[body.mode]
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
    from src.web.api.experiments import _engines, _source_lock

    # Block new experiment registration until existing runs and devices stop.
    async with _source_lock:
        engines = list(_engines.values())
        for engine in engines:
            engine.request_stop()
        try:
            result = await loop.run_in_executor(None, dm.emergency_stop_all)
        finally:
            stopped = await asyncio.gather(
                *(engine.stop() for engine in engines), return_exceptions=True
            )
        result = result and all(value is True for value in stopped)
    get_report = getattr(dm, "get_last_emergency_stop_report", None)
    return {
        "success": bool(result),
        "devices": get_report() if callable(get_report) else [],
    }


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
        from src.web.api.ws import DeviceReadCoordinator, PUMP_READ_TIMEOUT

        loop = asyncio.get_event_loop()
        read_coordinator = getattr(
            request.app.state, "device_read_coordinator", None
        ) or DeviceReadCoordinator()
        channel_tests = {}
        try:
            status = await read_coordinator.read(
                ("pump", device_id),
                lambda: dm.read_pump_status(device_id),
                timeout=PUMP_READ_TIMEOUT,
            )
            for ch in range(1, 5):
                channel = status["channels"][str(ch)]
                if channel.get("read_ok"):
                    channel_tests[f"CH{ch}"] = {
                        "success": True,
                        "running": channel["running"],
                        "flow_rate": channel["flow_rate"],
                    }
                else:
                    channel_tests[f"CH{ch}"] = {
                        "success": False,
                        "error": "read_failed",
                    }
        except (asyncio.TimeoutError, TimeoutError):
            channel_tests = {
                f"CH{ch}": {"success": False, "error": "timeout"}
                for ch in range(1, 5)
            }
        except Exception as e:
            channel_tests = {
                f"CH{ch}": {"success": False, "error": str(e)}
                for ch in range(1, 5)
            }
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
