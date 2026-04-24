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
    heater = dm._heaters.get(device_id)
    if heater is None:
        raise HTTPException(status_code=404, detail=f"Heater not found: {device_id}")
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, heater.set_temperature, body.temperature
        )
        return {"success": result, "temperature": body.temperature}
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
    heater = dm._heaters.get(device_id)
    if heater is None:
        raise HTTPException(status_code=404, detail=f"Heater not found: {device_id}")
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, heater.start)
    return {"success": result}


@router.post("/heater/{device_id}/stop")
async def stop_heater(device_id: str, request: Request):
    """停止加热器

    Args:
        device_id: 设备ID

    Returns:
        dict: 停止结果
    """
    dm = get_dm(request)
    heater = dm._heaters.get(device_id)
    if heater is None:
        raise HTTPException(status_code=404, detail=f"Heater not found: {device_id}")
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, heater.stop)
    return {"success": result}


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
    pump = dm._pumps.get(device_id)
    if pump is None:
        raise HTTPException(status_code=404, detail=f"Pump not found: {device_id}")
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
        await loop.run_in_executor(None, pump.set_direction, body.channel, direction)
        await loop.run_in_executor(None, pump.set_run_mode, body.channel, run_mode)
        await loop.run_in_executor(
            None, pump.set_flow_rate, body.channel, body.flow_rate
        )
        if body.run_time is not None and run_mode in (
            PumpRunMode.TIME_QUANTITY,
            PumpRunMode.TIME_SPEED,
        ):
            await loop.run_in_executor(
                None, pump.set_run_time, body.channel, body.run_time
            )
        if body.dispense_volume is not None and run_mode in (
            PumpRunMode.TIME_QUANTITY,
            PumpRunMode.QUANTITY_SPEED,
        ):
            await loop.run_in_executor(
                None, pump.set_dispense_volume, body.channel, body.dispense_volume
            )
        await loop.run_in_executor(None, pump.start_channel, body.channel)
        return {
            "success": True,
            "channel": body.channel,
            "flow_rate": body.flow_rate,
            "mode": body.mode,
        }
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
    pump = dm._pumps.get(device_id)
    if pump is None:
        raise HTTPException(status_code=404, detail=f"Pump not found: {device_id}")
    try:
        loop = asyncio.get_event_loop()
        if body.channel is not None:
            await loop.run_in_executor(None, pump.stop_channel, body.channel)
        else:
            await loop.run_in_executor(None, pump.stop_all)
        return {"success": True}
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
