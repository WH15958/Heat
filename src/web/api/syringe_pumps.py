import asyncio
from fastapi import APIRouter, HTTPException, Request
from src.devices.syringe_commands import SyringeCommand

router = APIRouter(prefix="/syringe_pump", tags=["syringe_pump"])


def controller(request, device_id):
    try:
        return request.app.state.device_manager.syringe(device_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


async def call(function, *args):
    try:
        return await asyncio.to_thread(function, *args)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    except (OSError, TimeoutError) as exc:
        raise HTTPException(503, str(exc)) from exc


@router.post("/{device_id}/connect")
async def connect(device_id: str, request: Request):
    return {"success": await call(controller(request, device_id).connect)}


@router.post("/{device_id}/disconnect")
async def disconnect(device_id: str, request: Request):
    return {"success": await call(controller(request, device_id).disconnect)}


@router.get("/{device_id}/status")
async def status(device_id: str, request: Request):
    c = controller(request, device_id)
    coordinator = getattr(request.app.state, "device_read_coordinator", None)
    if coordinator:
        try:
            return await coordinator.read(("syringe_pump", device_id), c.read, 10)
        except asyncio.TimeoutError:
            raise HTTPException(503, "状态读取超时")
    return await call(c.read)


@router.get("/{device_id}/diagnostics")
async def diagnostics(device_id: str, request: Request):
    return await call(controller(request, device_id).read, True)


@router.get("/{device_id}/programs")
async def programs(device_id: str, request: Request):
    return await call(controller(request, device_id).programs)


@router.post("/{device_id}/command")
async def command(device_id: str, body: SyringeCommand, request: Request):
    controller(request, device_id)
    return await call(request.app.state.device_manager.syringe_command,
                      device_id, body.model_dump(exclude_unset=True))
