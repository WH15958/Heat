"""Explicit guided batch start/control; preview and reads never write hardware."""
import asyncio
import json
import re

import yaml
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from src.experiment import guided
from src.web.api.experiments import _engines, _get_active_engine, _source_lock

router = APIRouter(prefix="/guided", tags=["guided"])
_batches = {}


class RecoveryConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    devices_stopped_confirmed: bool


def read_record(batch_id):
    if not re.fullmatch(r"guided_[0-9a-f]{32}", batch_id):
        raise HTTPException(404, "批次不存在")
    try:
        record = json.loads((guided.BATCH_DIR / (batch_id + ".json")).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise HTTPException(404, "批次不存在")
    except (ValueError, OSError) as exc:
        raise HTTPException(503, "批次记录读取失败，需检查持久化存储") from exc
    if (record["state"] not in guided.TERMINAL or record.get("cleanup_required")) and batch_id not in _batches:
        record["state"] = "interrupted"
        record["recovery_required"] = True
    return record


def records():
    return [read_record(path.stem) for path in guided.BATCH_DIR.glob("guided_*.json")]


def active_batch(batch_id):
    batch = _batches.get(batch_id)
    if batch is None:
        raise HTTPException(409, "批次未在当前服务中执行，不能自动恢复")
    return batch


@router.post("/preview")
async def preview(spec: guided.GuidedRequest):
    try:
        recipes = await asyncio.to_thread(guided.compile_plan, spec)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return dict(total_groups=len(recipes), rows=spec.rows(), recipes=recipes,
                yaml=[yaml.safe_dump(r, allow_unicode=True, sort_keys=False) for r in recipes])


@router.get("/current")
async def current():
    live = [b for b in _batches.values() if b.state.value in ("running", "paused") or b.cleanup_pending]
    if live:
        return live[-1].snapshot()
    stored = records()
    if not stored:
        return {"state": "idle"}
    actionable = [r for r in stored if r.get("recovery_required")]
    latest = max(actionable or stored, key=lambda r: r["created_at"])
    return _batches[latest["batch_id"]].snapshot() if latest["batch_id"] in _batches else latest


@router.get("/batches")
async def history():
    return sorted(records(), key=lambda r: r["created_at"], reverse=True)


@router.post("/start")
async def start(spec: guided.GuidedRequest, request: Request):
    async with _source_lock:
        if _get_active_engine()[1] is not None:
            raise HTTPException(409, "已有实验正在执行或停机尚未确认")
        if any(r.get("recovery_required") for r in records()):
            raise HTTPException(409, "存在服务中断批次，请先现场确认设备停止并解除中断锁定")
        try:
            batch = await asyncio.to_thread(guided.GuidedBatch, request.app.state.device_manager, spec)
            await guided.preflight(batch.dm, spec)
            _batches[batch.batch_id] = batch
            _engines[batch.batch_id] = batch
            await batch.start()
        except (ValueError, OSError, RuntimeError) as exc:
            if "batch" in locals():
                _engines.pop(batch.batch_id, None)
                _batches.pop(batch.batch_id, None)
            raise HTTPException(409, str(exc)) from exc
        return batch.snapshot()


@router.get("/{batch_id}")
async def status(batch_id: str):
    return _batches[batch_id].snapshot() if batch_id in _batches else read_record(batch_id)


@router.get("/{batch_id}/plan")
async def saved_plan(batch_id: str):
    read_record(batch_id)  # Validate identity and associated checkpoint first.
    try:
        return json.loads((guided.BATCH_DIR / "plans" / (batch_id + ".json")).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(503, "完整流程快照读取失败") from exc


@router.post("/{batch_id}/pause")
async def pause(batch_id: str):
    try:
        await active_batch(batch_id).pause()
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"success": True}


@router.post("/{batch_id}/resume")
async def resume(batch_id: str):
    try:
        await active_batch(batch_id).resume()
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"success": True}


@router.post("/{batch_id}/stop")
async def stop(batch_id: str):
    batch = active_batch(batch_id)
    success = await batch.stop()
    return {"success": success, **batch.snapshot()}


@router.post("/{batch_id}/acknowledge-interrupted")
async def acknowledge_interrupted(batch_id: str, body: RecoveryConfirmation):
    async with _source_lock:
        record = read_record(batch_id)
        if not record.get("recovery_required") or not body.devices_stopped_confirmed:
            raise HTTPException(409, "须现场确认所有设备已停止，且仅可解除中断批次锁定")
        record["recovery_required"] = False
        record["cleanup_required"] = False
        record["error"] = "服务中断；人工确认设备停止，未自动恢复执行"
        guided.atomic_record(record)
        return record
