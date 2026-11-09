"""Persistent, derived chart data. Never accesses devices or changes source logs."""
import json
import math
import os
import tempfile
from datetime import datetime, timezone

from src.experiment.experiment_logger import get_experiment_run

VERSION = 1


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def phase_index(sid):
    if sid.startswith("clean_"):
        return 5
    if sid == "collect_product":
        return 4
    if sid in ("microwave_stop", "cool_before_collection", "recheck_temperature", "product_route"):
        return 3
    if sid == "hold":
        return 2
    if sid == "microwave_start":
        return 1
    if sid.startswith(("heat_", "aspirate_", "feed_")) or sid == "microwave_config":
        return 0
    return 6


def chart_run(run, index):
    phases = [0.0] * 7
    intervals = []
    for step in run.get("steps", []):
        try:
            start = datetime.fromisoformat(run["started_at"])
            a = (datetime.fromisoformat(step["started_at"]) - start).total_seconds()
            b = (datetime.fromisoformat(step["finished_at"]) - start).total_seconds()
        except (KeyError, TypeError, ValueError):
            continue
        if a < 0 or b < a:
            continue
        phase = phase_index(step.get("step_id", ""))
        phases[phase] += b - a
        intervals.append(dict(phase=phase, start=a / 60, end=b / 60))
    total = run.get("total_duration")
    if not finite(total) or total < 0:
        total = None
    if total is not None:
        phases[6] += max(0, total - sum(phases))
    parameters = (run.get("metadata") or {}).get("guided_parameters") or []
    target = parameters[4] if len(parameters) > 4 else None
    temperature = []
    for device_id, data in (run.get("sensor_data") or {}).get("microwaves", {}).items():
        points, previous = [], None
        for point in data.get("material_temperature", []):
            t, value = point.get("t"), point.get("v")
            if not finite(t) or t < 0:
                continue
            if previous is not None and t - previous > 15:
                points.append([(previous + .01) / 60, None])
            points.append([t / 60, value if finite(value) else None])
            previous = t
        temperature.append(dict(id=device_id, points=points))
    return dict(index=index, runId=run["run_id"], start=run.get("started_at"),
                end=run.get("finished_at"), total=total, phases=phases, intervals=intervals,
                target=target if finite(target) else None, temperature=temperature)


def saved_charts(record, directory):
    """Reuse a complete terminal snapshot; unfinished/partial data is never cached."""
    groups = [g for g in record.get("groups", []) if g.get("run_id")]
    identity = [[g["index"], g["run_id"], g.get("state")] for g in groups]
    path = directory / "charts" / (record["batch_id"] + ".json")
    terminal = record.get("state") in {"completed", "failed", "stopped", "interrupted"}
    if terminal and path.exists():
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if (cached.get("version") == VERSION and cached.get("identity") == identity
                    and cached.get("batch_id") == record["batch_id"]
                    and cached.get("state") == record.get("state")):
                return cached
        except (ValueError, OSError):
            pass  # Derived cache can be regenerated; source logs are never overwritten.
    models, missing = [], []
    for group in groups:
        run = get_experiment_run(group["run_id"])
        if (not run or run.get("run_id") != group["run_id"]
                or (run.get("metadata", {}).get("batch_id") not in (None, record["batch_id"]))):
            missing.append(group["index"])
            continue
        models.append(chart_run(run, group["index"]))
    result = dict(version=VERSION, batch_id=record["batch_id"], identity=identity,
                  state=record.get("state"), generated_at=datetime.now(timezone.utc).isoformat(),
                  models=models, missing=missing, saved=False)
    if terminal and not missing:
        path.parent.mkdir(parents=True, exist_ok=True)
        result["saved"] = True
        fd, name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(result, stream, ensure_ascii=False, allow_nan=False)
            os.replace(name, path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
    return result
