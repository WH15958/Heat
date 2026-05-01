import asyncio

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

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


class StopPumpRequest(BaseModel):
    """停止泵请求"""
    channel: Optional[int] = None


def get_dm(request: Request) -> "DeviceManager":
    """从应用状态获取设备管理器

    Args:
        request: FastAPI请求对象

    Returns:
        DeviceManager: 设备管理器
    """
    return request.app.state.device_manager


@router.get("/devices")
async def list_devices(request: Request):
    """列出所有设备及状态

    Returns:
        dict: 设备状态摘要
    """
    dm = get_dm(request)
    return dm.get_all_status()


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
            body.tube_model, body.flow_unit,
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
    await loop.run_in_executor(None, dm.emergency_stop_all)
    return {"success": True}


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
