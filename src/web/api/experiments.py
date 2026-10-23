import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field, ConfigDict

from src.experiment.parser import parse_experiment, parse_experiment_content, list_experiments, _validate_filename
from src.experiment import parser as experiment_parser
from src.experiment.yaml_recovery import PersistentExperimentEngine as ExperimentEngine
from src.experiment import yaml_recovery
from src.experiment.editor import read_source, write_source, validate_source, source_path, SourceConflict
from src.experiment.executor import StepExecutor
from src.experiment.experiment_logger import ExperimentLogger, list_experiment_runs, get_experiment_run, delete_experiment_run, delete_all_experiment_runs
from src.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/experiments", tags=["experiments"])

_engines: dict = {}
# Serialize source replacement with loading/registering a run, including initial awaits.
_source_lock = asyncio.Lock()
_stop_generation = 0
_stopping = 0
_desktop_exiting = False


def control_generation(*, allow_stop=False):
    if _stopping or (_desktop_exiting and not allow_stop):
        raise HTTPException(409, "全局停止或服务关闭处理中")
    return _stop_generation


def check_control_generation(generation, *, allow_stop=False):
    if _stopping or (_desktop_exiting and not allow_stop) or generation != _stop_generation:
        raise HTTPException(409, "停止请求已取消待执行操作，请重新确认")


def begin_stop():
    global _stop_generation, _stopping
    _stop_generation += 1
    _stopping += 1
    for engine in list(_engines.values()):
        engine.request_stop()


def end_stop():
    global _stopping
    _stopping -= 1


async def shutdown() -> bool:
    begin_stop()
    try:
        async with _source_lock:
            engines = list(_engines.values())
            for engine in engines:
                engine.request_stop()
            results = await asyncio.gather(*(e.stop() for e in engines), return_exceptions=True)
            if any(result is not True for result in results):
                logger.error("One or more experiments failed to stop during shutdown")
            return all(result is True for result in results)
    finally:
        end_stop()


def _get_active_engine():
    for fname, engine in _engines.items():
        if engine.state.value in ("running", "paused") or getattr(
            engine, "cleanup_pending", False
        ):
            return fname, engine
    return None, None


def _cleanup_engine(filename: str, expected_engine=None):
    engine = _engines.get(filename)
    if engine is not None and (expected_engine is None or engine is expected_engine):
        del _engines[filename]
        logger.info(f"Cleaned up engine for: {filename}")


class StartExperimentRequest(BaseModel):
    save_log: bool = True


class SourceRequest(BaseModel):
    content: str = Field(max_length=1_000_000)
    revision: str | None = None


def recovery_records():
    try:
        return yaml_recovery.records(_engines)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(503, '普通实验恢复记录不可读，请检查存储，禁止启动') from exc


def require_yaml_recovered():
    if any(r['recovery_required'] or r['cleanup_required'] for r in recovery_records()):
        raise HTTPException(409, '普通实验占用或中断锁定，请在实验页面确认设备停止并解除锁定')


def require_turntables_idle(dm):
    # This is a memory-only guard, called while holding the shared start lock.
    check = getattr(dm, "require_turntables_idle", None)
    if callable(check):
        try:
            check()
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc


class YamlRecoveryConfirmation(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    devices_stopped_confirmed: bool


@router.get('/recovery/pending')
async def pending_recovery():
    return [r for r in recovery_records() if r['recovery_required']]


@router.post('/recovery/{recovery_id}/acknowledge')
async def acknowledge_recovery(recovery_id: str, body: YamlRecoveryConfirmation):
    async with _source_lock:
        record = next((r for r in recovery_records() if r['recovery_id'] == recovery_id), None)
        if not record or not record['recovery_required'] or not body.devices_stopped_confirmed:
            raise HTTPException(409, '仅在现场确认设备已停止后解除中断锁定')
        live = next((e for e in _engines.values() if isinstance(e, ExperimentEngine)
                     and e.record and e.record['recovery_id'] == recovery_id), None)
        if live:
            if live._task and not live._task.done():
                raise HTTPException(409, '请先停止仍在执行的实验')
            if not await live.stop() and live._cleanup_result is not True:
                raise HTTPException(409, '设备停止未确认，不能解除锁定')
            record = dict(live.record)
        record.update(recovery_required=False, cleanup_required=False, persistence_status='ok',
                      state='stopped', acknowledged_at=datetime.now(timezone.utc).isoformat(),
                      error='人工确认停止，未恢复或重放实验')
        try:
            yaml_recovery.write_record(record)
        except (OSError, ValueError) as exc:
            raise HTTPException(503, '恢复确认无法保存，保留锁定') from exc
        if live:
            live.record.update(record)
            _cleanup_engine(record['filename'], live)
        return {'success': True}


@router.post('/validate')
async def validate_experiment(body: SourceRequest):
    return validate_source(body.content)


@router.get('/{filename}/source')
async def get_experiment_source(filename: str):
    try:
        return read_source(filename)
    except FileNotFoundError:
        raise HTTPException(404, 'Experiment not found')
    except (ValueError, UnicodeError) as exc:
        raise HTTPException(400, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(500, '实验文件读取失败') from exc


@router.put('/{filename}/source')
async def save_experiment_source(filename: str, body: SourceRequest):
    async with _source_lock:
        try:
            target = source_path(filename).resolve()
            for active_name, engine in _engines.items():
                if not active_name.endswith(('.yaml', '.yml')):
                    continue  # Guided registry keys identify batches, not YAML files.
                if source_path(active_name).resolve() == target and (
                    engine.state.value in ('running', 'paused') or engine.cleanup_pending
                ):
                    raise SourceConflict('运行中或停机清理未完成的实验不能覆盖，请另存为。')
            result = validate_source(body.content, filename)
            if not result['valid']:
                raise HTTPException(422, result)
            return write_source(filename, body.content, body.revision)
        except SourceConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(500, '保存失败，原文件未被覆盖') from exc


@router.get("/")
async def list_exp():
    return list_experiments()


@router.get("/{filename}")
async def get_experiment(filename: str):
    try:
        data = parse_experiment(f"experiments/{filename}")
        return {
            "name": data["name"],
            "description": data["description"],
            "metadata": data.get("metadata", {}),
            "steps": [
                {
                    "id": s.id,
                    "type": s.type.value,
                    "params": s.params,
                    "wait_type": s.wait.type.value,
                    "enabled": s.enabled,
                }
                for s in data["steps"]
            ],
        }
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Experiment not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{filename}/start")
async def start_experiment(filename: str, body: StartExperimentRequest, request: Request):
    generation = control_generation()
    async with _source_lock:
        check_control_generation(generation)
        return await _start_experiment_locked(filename, body, request)


async def _start_experiment_locked(filename: str, body: StartExperimentRequest, request: Request):
    require_yaml_recovered()
    from src.web.api.microwave_program import require_recovered
    require_recovered()
    from src.web.api.guided import records
    if any(r.get("recovery_required") for r in records()):
        raise HTTPException(409, "存在中断的引导式批次，须先现场确认设备停止")

    active_fname, active_engine = _get_active_engine()
    if active_engine is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot start new experiment: '{active_fname}' is still {active_engine.state.value}. "
                   f"Please stop or wait for it to complete before starting another.",
        )
    dm = request.app.state.device_manager
    require_turntables_idle(dm)
    try:
        _validate_filename(filename)
        source_content = (experiment_parser.EXPERIMENTS_DIR / filename).read_text(encoding="utf-8")
        validation = validate_source(source_content, filename)
        if not validation["valid"]:
            raise ValueError("; ".join(error["message"] for error in validation["errors"]))
        data = parse_experiment_content(source_content, filename)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Experiment not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    for fname in list(_engines.keys()):
        engine = _engines[fname]
        if (
            engine.state.value in ("completed", "failed", "stopped")
            and not getattr(engine, "cleanup_pending", False)
        ):
            _cleanup_engine(fname)

    for step in data["steps"]:
        if not step.enabled:
            continue
        if step.type.value == "syringe_pair.dispense":
            for feed in step.params["feeds"]:
                try:
                    if not dm.syringe(feed["device_id"]).device.is_connected():
                        raise ValueError(f"{feed['device_id']} 未连接")
                except ValueError as exc:
                    raise HTTPException(409, str(exc)) from exc
        if step.type.value == "valve.switch":
            device_id = step.params["device_id"]
            valve = getattr(dm, "valves", {}).get(device_id)
            if valve is None or not valve.is_connected():
                raise HTTPException(409, f"阀门 {device_id} 未配置或未连接")
        if step.type.value.startswith("syringe_pump.") or step.wait.type.value == "syringe_pump_complete":
            ids = set()
            if step.type.value.startswith("syringe_pump."):
                ids.add(step.params["device_id"])
            if step.wait.type.value == "syringe_pump_complete":
                ids.add(step.wait.device_id)
            for device_id in ids:
                try:
                    c = dm.syringe(device_id)
                    if not c.device.is_connected():
                        raise ValueError(f"{device_id} 未配置或未连接")
                except ValueError as exc:
                    raise HTTPException(409, str(exc)) from exc
    executor = StepExecutor(dm)
    exp_logger = ExperimentLogger(save_log=body.save_log)

    loop = asyncio.get_running_loop()

    def on_log_event(event_type: str, event_data: dict):
        try:
            asyncio.create_task(
                _broadcast_log(filename, event_type, event_data)
            )
        except RuntimeError:
            try:
                asyncio.run_coroutine_threadsafe(
                    _broadcast_log(filename, event_type, event_data), loop
                )
            except Exception as e:
                logger.error(f"Failed to broadcast log event ({event_type}): {e}")
        except Exception as e:
            logger.error(f"Failed to broadcast log event ({event_type}): {e}")

    exp_logger.on_log(on_log_event)

    engine = ExperimentEngine(executor, exp_logger=exp_logger)
    engine.record = yaml_recovery.new_record(filename, source_content)
    engine.load_steps(data["steps"], name=data["name"], filename=filename, metadata=data.get("metadata", {}))

    def on_progress(progress):
        try:
            asyncio.create_task(
                _broadcast_progress(filename, progress)
            )
        except RuntimeError:
            try:
                asyncio.run_coroutine_threadsafe(
                    _broadcast_progress(filename, progress), loop
                )
            except Exception:
                pass
        except Exception:
            pass

    def on_complete():
        _cleanup_engine(filename, engine)

    engine.on_progress(on_progress)
    engine.on_complete(on_complete)
    _engines[filename] = engine

    try:
        await engine.start()
    except Exception as e:
        logger.error(f"Failed to start experiment {filename}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start experiment: {e}")
    return {
        "success": True,
        "experiment": data["name"],
        "run_id": exp_logger.active_run.run_id if exp_logger.active_run else None,
        "sample_id": exp_logger.active_run.metadata.get("sample_id") if exp_logger.active_run else None,
        "metadata": exp_logger.active_run.metadata if exp_logger.active_run else {},
    }


@router.post("/{filename}/pause")
async def pause_experiment(filename: str):
    engine = _engines.get(filename)
    if engine is None:
        raise HTTPException(status_code=404, detail="Experiment not running")
    if not hasattr(engine, "pause"):
        raise HTTPException(409, "微波托管程序不支持暂停，请使用停止")
    await engine.pause()
    return {"success": True}


@router.post("/{filename}/resume")
async def resume_experiment(filename: str):
    engine = _engines.get(filename)
    if engine is None:
        raise HTTPException(status_code=404, detail="Experiment not running")
    if not hasattr(engine, "resume"):
        raise HTTPException(409, "微波托管程序不支持恢复，请重新检查程序")
    await engine.resume()
    return {"success": True}


@router.post("/{filename}/stop")
async def stop_experiment(filename: str):
    engine = _engines.get(filename)
    if engine is None:
        raise HTTPException(status_code=404, detail="Experiment not running")
    success = await engine.stop()
    return {"success": success}


@router.get("/{filename}/progress")
async def get_progress(filename: str):
    engine = _engines.get(filename)
    if engine is None:
        return {"state": "idle", "pause_pending": False}
    p = engine.progress
    return {
        "state": p.state.value,
        "current_step": p.current_step,
        "total_steps": p.total_steps,
        "step_id": p.step_id,
        "elapsed": round(p.elapsed, 1),
        "pause_pending": p.pause_pending,
        "cleanup_pending": engine.cleanup_pending,
    }


@router.get("/{filename}/logs")
async def get_current_logs(filename: str):
    engine = _engines.get(filename)
    if engine is None or engine.exp_logger.active_run is None:
        return {"steps": [], "run_id": None}
    run = engine.exp_logger.active_run
    return run.to_dict()


@router.get("/history/runs")
async def get_history_runs():
    return list_experiment_runs()


@router.get("/history/runs/{run_id}")
async def get_history_run(run_id: str):
    data = get_experiment_run(run_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return data


@router.delete("/history/runs/{run_id}")
async def delete_history_run(run_id: str):
    try:
        success = delete_experiment_run(run_id)
    except OSError as exc:
        raise HTTPException(503, "历史及样品记录删除未完成，请解除文件占用后重试") from exc
    if not success:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"success": True, "deleted": run_id}


@router.delete("/history/runs")
async def delete_all_history_runs():
    try:
        count = delete_all_experiment_runs()
    except OSError as exc:
        raise HTTPException(503, "历史及样品记录删除未完成，请解除文件占用后重试") from exc
    return {"success": True, "deleted_count": count}


async def _broadcast_progress(filename: str, progress):
    from src.web.api.ws import manager

    await manager.broadcast(
        {
            "type": "experiment_progress",
            "filename": filename,
            "state": progress.state.value,
            "current_step": progress.current_step,
            "total_steps": progress.total_steps,
            "step_id": progress.step_id,
            "elapsed": round(progress.elapsed, 1),
            "pause_pending": progress.pause_pending,
            "cleanup_pending": progress.cleanup_pending,
        }
    )


async def _broadcast_log(filename: str, event_type: str, event_data: dict):
    from src.web.api.ws import manager

    await manager.broadcast(
        {
            "type": "experiment_log",
            "filename": filename,
            "event": event_type,
            "data": event_data,
        }
    )
