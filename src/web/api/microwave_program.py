"""Explicit host-owned microwave runs, independent of browser lifecycle."""
import asyncio

from fastapi import APIRouter, HTTPException, Request

from src.experiment import microwave_program as program
from src.web.api.experiments import _engines, _get_active_engine, _source_lock
from src.web.api.guided import RecoveryConfirmation

router = APIRouter(prefix="/microwave-program", tags=["microwave-program"])
_runs = {}


def records():
    try:
        stored = {r["program_id"]: r for r in program.stored_records(_runs)}
        # A failed initial disk write still owns a live recovery lock.
        stored.update({pid: run.snapshot() for pid, run in _runs.items()})
        return list(stored.values())
    except (OSError, ValueError, KeyError) as exc:
        raise HTTPException(503, "托管程序记录不可读，请检查存储，禁止启动") from exc


def require_recovered():
    if any(r.get("recovery_required") for r in records()):
        raise HTTPException(409, "存在中断或失败的微波托管程序，请先现场确认停止并解除锁定")


@router.post("/{device_id}/preview")
async def preview(device_id: str, spec: program.ProgramRequest):
    try:
        steps = await asyncio.to_thread(program.compile_steps, device_id, spec)
        return {"success": True, "total_stages": len(spec.stages),
                "hardware_hold_seconds": [s.params["segments"][0]["hours"] * 3600
                    + s.params["segments"][0]["minutes"] * 60 + s.params["segments"][0]["seconds"]
                    for s in steps if s.id.endswith("_configure")]}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/{device_id}/current")
async def current(device_id: str):
    stored = [r for r in records() if r["device_id"] == device_id]
    if not stored:
        return {"state": "idle"}
    pending = [r for r in stored if r.get("recovery_required") or r["state"] not in program.TERMINAL]
    latest = max(pending or stored, key=lambda r: r["created_at"])
    live = _runs.get(latest["program_id"])
    return live.snapshot() if live else latest


@router.post("/{device_id}/start")
async def start(device_id: str, spec: program.ProgramRequest, request: Request):
    async with _source_lock:
        program_id = "mwprogram_" + spec.request_id
        existing = next((r for r in records() if r["program_id"] == program_id), None)
        if existing:
            if existing["device_id"] != device_id or existing["request"] != spec.model_dump():
                raise HTTPException(409, "请求标识已被不同参数使用")
            live = _runs.get(program_id)
            return live.snapshot() if live else existing  # Never replay a request.
        require_recovered()
        from src.web.api.guided import records as batch_records
        if _get_active_engine()[1] is not None or any(r.get("recovery_required") for r in batch_records()):
            raise HTTPException(409, "已有实验占用或中断锁定，不能启动托管程序")
        if not spec.hardware_confirmed:
            raise HTTPException(409, "请确认负载、探头、炉门和现场看护条件")
        try:
            run = program.MicrowaveProgramRun(request.app.state.device_manager, device_id, spec)
            await program.preflight(request.app.state.device_manager, device_id)
        except (ValueError, RuntimeError, OSError) as exc:
            raise HTTPException(409, str(exc)) from exc
        _runs[program_id] = run
        _engines[program_id] = run
        try:
            await run.start()
        except Exception as exc:
            run.record.update(recovery_required=True, error=str(exc))
            await run.stop()
            raise HTTPException(503, "托管程序启动或持久化失败，请确认设备停止") from exc
        return run.snapshot()


@router.post("/{device_id}/stop")
async def stop(device_id: str):
    async with _source_lock:
        live = [r for r in _runs.values() if r.record["device_id"] == device_id
                and (r.state.value not in program.TERMINAL or r.cleanup_pending)]
        if not live:
            raise HTTPException(409, "当前服务没有待停止的托管程序；中断后须现场确认设备停止")
        results = [await run.stop() for run in live]
        return dict(live[-1].snapshot(), success=all(results))


@router.post("/{device_id}/acknowledge-interrupted")
async def acknowledge(device_id: str, body: RecoveryConfirmation):
    async with _source_lock:
        pending = [r for r in records() if r["device_id"] == device_id and r.get("recovery_required")]
        if not pending or not body.devices_stopped_confirmed:
            raise HTTPException(409, "仅在现场确认设备已停止后解除中断或失败锁定")
        for record in pending:
            live = _runs.get(record["program_id"])
            if live:
                if live.task and not live.task.done():
                    raise HTTPException(409, "请先停止仍在执行的托管程序")
                if not await live.stop():
                    raise HTTPException(409, "停止或存储未确认，不能解除锁定")
                record = dict(live.record)
            record.update(recovery_required=False, cleanup_required=False, state="stopped",
                          phase="acknowledged", error="人工确认停止，未恢复或重放程序")
            try:
                program.write_record(record)
            except OSError as exc:
                raise HTTPException(503, "恢复确认无法保存，保留锁定") from exc
            if live:
                live.record.update(record)
                _runs.pop(record["program_id"], None)
                if _engines.get(record["program_id"]) is live:
                    _engines.pop(record["program_id"])
        return {"success": True}


async def shutdown():
    runs = [r for r in _runs.values() if r.state.value not in program.TERMINAL or r.cleanup_pending]
    for run in runs:
        run.request_stop()
    await asyncio.gather(*(r.stop() for r in runs), return_exceptions=True)
