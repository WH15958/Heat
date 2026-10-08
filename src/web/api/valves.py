import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, StrictBool

from src.web.api.devices import protect_guided_devices

router = APIRouter(prefix="/valve", tags=["valve"], dependencies=[Depends(protect_guided_devices)])


class ValveSwitchRequest(BaseModel):
    energized: StrictBool


async def operation(request, device_id, action, energized=None):
    dm = request.app.state.device_manager
    if device_id not in dm.valves:
        raise HTTPException(404, "阀门不存在")
    try:
        status = await asyncio.to_thread(dm.valve_operation, device_id, action, energized)
        return {"success": True, **status}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.post("/{device_id}/connect")
async def connect(device_id: str, request: Request):
    return await operation(request, device_id, "connect")


@router.post("/{device_id}/disconnect")
async def disconnect(device_id: str, request: Request):
    return await operation(request, device_id, "disconnect")


@router.get("/{device_id}/status")
async def status(device_id: str, request: Request):
    return await operation(request, device_id, "status")


@router.post("/{device_id}/switch")
async def switch(device_id: str, body: ValveSwitchRequest, request: Request):
    return await operation(request, device_id, "switch", body.energized)
