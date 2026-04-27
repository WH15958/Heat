import asyncio

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from src.experiment.parser import parse_experiment, list_experiments, _validate_filename
from src.experiment.engine import ExperimentEngine
from src.experiment.executor import StepExecutor
from src.experiment.experiment_logger import ExperimentLogger, list_experiment_runs, get_experiment_run
from src.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/experiments", tags=["experiments"])

_engines: dict = {}


def _cleanup_engine(filename: str):
    if filename in _engines:
        del _engines[filename]
        logger.info(f"Cleaned up engine for: {filename}")


class StartExperimentRequest(BaseModel):
    filename: str


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
async def start_experiment(filename: str, request: Request):
    dm = request.app.state.device_manager
    try:
        _validate_filename(filename)
        data = parse_experiment(f"experiments/{filename}")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Experiment not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if filename in _engines and _engines[filename].state.value == "running":
        raise HTTPException(status_code=409, detail="Experiment already running")

    if filename in _engines:
        _cleanup_engine(filename)

    executor = StepExecutor(dm)
    exp_logger = ExperimentLogger()

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
    engine.load_steps(data["steps"], name=data["name"], filename=filename)

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
        _cleanup_engine(filename)

    engine.on_progress(on_progress)
    engine.on_complete(on_complete)
    _engines[filename] = engine

    await engine.start()
    return {"success": True, "experiment": data["name"], "run_id": exp_logger.active_run.run_id if exp_logger.active_run else None}


@router.post("/{filename}/pause")
async def pause_experiment(filename: str):
    engine = _engines.get(filename)
    if engine is None:
        raise HTTPException(status_code=404, detail="Experiment not running")
    await engine.pause()
    return {"success": True}


@router.post("/{filename}/resume")
async def resume_experiment(filename: str):
    engine = _engines.get(filename)
    if engine is None:
        raise HTTPException(status_code=404, detail="Experiment not running")
    await engine.resume()
    return {"success": True}


@router.post("/{filename}/stop")
async def stop_experiment(filename: str):
    engine = _engines.get(filename)
    if engine is None:
        raise HTTPException(status_code=404, detail="Experiment not running")
    await engine.stop()
    _cleanup_engine(filename)
    return {"success": True}


@router.get("/{filename}/progress")
async def get_progress(filename: str):
    engine = _engines.get(filename)
    if engine is None:
        return {"state": "idle"}
    p = engine.progress
    return {
        "state": p.state.value,
        "current_step": p.current_step,
        "total_steps": p.total_steps,
        "step_id": p.step_id,
        "elapsed": round(p.elapsed, 1),
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
