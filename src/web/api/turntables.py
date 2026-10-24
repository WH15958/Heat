import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request

from src.devices.turntable_commands import TurntableCommand
from src.web.turntable_commands import BottleCommand
from src.web.api.devices import protect_guided_devices

router = APIRouter(prefix="/turntable", tags=["turntable"], dependencies=[Depends(protect_guided_devices)])


def controller(request, device_id):
    try:
        return request.app.state.device_manager.turntable(device_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


async def call(function, *args):
    try:
        worker = asyncio.create_task(asyncio.to_thread(function, *args))
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            # A cancelled HTTP request must retain the registration/STOP fence
            # until its synchronous worker has really finished touching hardware.
            while not worker.done():
                try:
                    await asyncio.shield(worker)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if not worker.cancelled():
                worker.exception()
            raise
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    except (OSError, TimeoutError) as exc:
        raise HTTPException(503, str(exc)) from exc


@router.post("/{device_id}/connect")
async def connect(device_id: str, request: Request):
    return {"success": True, **await call(controller(request, device_id).connect)}


@router.post("/{device_id}/disconnect")
async def disconnect(device_id: str, request: Request):
    return {"success": True, **await call(controller(request, device_id).disconnect)}


@router.get("/{device_id}/status")
async def status(device_id: str, request: Request):
    c = controller(request, device_id)
    coordinator = getattr(request.app.state, "device_read_coordinator", None)
    if coordinator:
        try:
            return await coordinator.read(("turntable", device_id), c.read, 5)
        except asyncio.TimeoutError as exc:
            raise HTTPException(503, "转盘状态读取超时") from exc
    return await call(c.read)


@router.post("/{device_id}/command")
async def command(device_id: str, body: TurntableCommand | BottleCommand, request: Request):
    c = controller(request, device_id)
    result = await call(request.app.state.device_manager.turntable_command,
                        device_id, body.model_dump(exclude_unset=True),
                        getattr(request.state, "turntable_generation", None))
    return {"success": True, "result": result, "state": await call(c.summary)}
