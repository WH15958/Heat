import asyncio

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from src.experiment.parser import parse_experiment, list_experiments, _validate_filename
from src.experiment.engine import ExperimentEngine
from src.experiment.executor import StepExecutor
from src.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/experiments", tags=["experiments"])

_engines: dict = {}


class StartExperimentRequest(BaseModel):
    """启动实验请求"""
    filename: str


@router.get("/")
async def list_exp():
    """列出所有可用实验

    Returns:
        list: 实验摘要列表
    """
    return list_experiments()


@router.get("/{filename}")
async def get_experiment(filename: str):
    """获取实验详情

    Args:
        filename: 实验文件名

    Returns:
        dict: 实验详情
    """
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
    """启动实验

    Args:
        filename: 实验文件名

    Returns:
        dict: 启动结果
    """
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

    executor = StepExecutor(dm)
    engine = ExperimentEngine(executor)
    engine.load_steps(data["steps"])

    def on_progress(progress):
        try:
            loop = asyncio.get_event_loop()
            loop.create_task(_broadcast_progress(filename, progress))
        except Exception:
            pass

    engine.on_progress(on_progress)
    _engines[filename] = engine

    await engine.start()
    return {"success": True, "experiment": data["name"]}


@router.post("/{filename}/pause")
async def pause_experiment(filename: str):
    """暂停实验

    Args:
        filename: 实验文件名

    Returns:
        dict: 操作结果
    """
    engine = _engines.get(filename)
    if engine is None:
        raise HTTPException(status_code=404, detail="Experiment not running")
    await engine.pause()
    return {"success": True}


@router.post("/{filename}/resume")
async def resume_experiment(filename: str):
    """恢复实验

    Args:
        filename: 实验文件名

    Returns:
        dict: 操作结果
    """
    engine = _engines.get(filename)
    if engine is None:
        raise HTTPException(status_code=404, detail="Experiment not running")
    await engine.resume()
    return {"success": True}


@router.post("/{filename}/stop")
async def stop_experiment(filename: str):
    """停止实验

    Args:
        filename: 实验文件名

    Returns:
        dict: 操作结果
    """
    engine = _engines.get(filename)
    if engine is None:
        raise HTTPException(status_code=404, detail="Experiment not running")
    await engine.stop()
    return {"success": True}


@router.get("/{filename}/progress")
async def get_progress(filename: str):
    """查询实验进度

    Args:
        filename: 实验文件名

    Returns:
        dict: 进度信息
    """
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


async def _broadcast_progress(filename: str, progress):
    """通过WebSocket广播实验进度

    Args:
        filename: 实验文件名
        progress: 进度对象
    """
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
