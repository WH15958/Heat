"""Durable ownership for Web-started ordinary YAML; never replay an interrupted run."""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
from datetime import datetime, timezone
from uuid import uuid4

from src.experiment.engine import ExperimentEngine, ExperimentState
from src.utils.runtime_paths import data_path

RECOVERY_DIR = data_path('output/yaml_runs', legacy=Path(__file__).resolve().parents[2] / 'output' / 'yaml_runs')
TERMINAL = {'completed', 'failed', 'stopped'}


def new_record(filename, source):
    return dict(recovery_id='yaml_' + uuid4().hex, filename=filename,
                source_sha256=hashlib.sha256(source.encode('utf-8')).hexdigest(),
                created_at=datetime.now(timezone.utc).isoformat(), state='starting',
                cleanup_required=True, recovery_required=False, persistence_status='ok',
                run_id=None, sample_id=None, current_step=0, error=None)


def write_record(record):
    RECOVERY_DIR.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=RECOVERY_DIR, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(record, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, RECOVERY_DIR / (record['recovery_id'] + '.json'))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def records(engines):
    # iterdir propagates permission/I/O failures instead of silently treating them as no locks.
    stored = {}
    try:
        paths = list(RECOVERY_DIR.iterdir())
    except FileNotFoundError:
        paths = []
    for path in paths:
        if path.suffix != '.json':
            continue
        record = json.loads(path.read_text(encoding='utf-8'))
        if (not isinstance(record, dict) or not re.fullmatch(r'yaml_[0-9a-f]{32}', path.stem)
                or record.get('recovery_id') != path.stem
                or record.get('state') not in TERMINAL | {'starting', 'running', 'paused'}
                or not isinstance(record.get('filename'), str)
                or type(record.get('cleanup_required')) is not bool
                or type(record.get('recovery_required')) is not bool
                or record.get('persistence_status') not in {'ok', 'error'}):
            raise ValueError('Invalid YAML recovery record: ' + path.name)
        if record['state'] not in TERMINAL or record['cleanup_required'] or record['persistence_status'] == 'error':
            record.update(state='interrupted', recovery_required=True)
        stored[path.stem] = record
    for engine in engines.values():
        if isinstance(engine, PersistentExperimentEngine) and engine.record:
            stored[engine.record['recovery_id']] = dict(engine.record)
    return list(stored.values())


class PersistentExperimentEngine(ExperimentEngine):
    """Keep the existing executor and stop semantics; persist before releasing ownership."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.record = None

    @property
    def cleanup_pending(self):
        return super().cleanup_pending or bool(self.record and (
            self.record['recovery_required'] or self.record['persistence_status'] == 'error'))

    def _save(self):
        try:
            write_record(self.record)
        except Exception as exc:
            self.record.update(persistence_status='error', recovery_required=True, error=str(exc))
            self.request_stop()
            raise

    async def start(self):
        self._save()  # Mandatory even when the user disables detailed run logs.
        try:
            await super().start()
        except Exception:
            self.record.update(recovery_required=True, state='failed')
            try:
                self._save()
            except Exception:
                pass  # Original intent and live record retain ownership.
            raise

    def _notify(self):
        run = self.exp_logger.active_run
        self.record.update(state='starting' if self.state == ExperimentState.IDLE else self.state.value,
                           current_step=self._current_step,
                           run_id=run.run_id if run else None,
                           sample_id=run.metadata.get('sample_id') if run else None)
        # Keep cleanup_required until _run has finished cleanup AND log persistence.
        self._save()
        super()._notify()

    def _notify_complete(self):
        # Base engine completion precedes durable finalization below.
        pass

    def _finalize_record(self):
        run = self.exp_logger.active_run
        failed = (self.state == ExperimentState.FAILED or self._cleanup_result is not True
                  or self.record['persistence_status'] == 'error'
                  or (run is not None and run.persistence_status == 'error'))
        self.record.update(state=self.state.value, cleanup_required=self._cleanup_result is not True,
                           recovery_required=bool(failed))
        if run and run.persistence_status == 'error':
            self.record['error'] = '运行记录保存失败'
        try:
            self._save()
        except Exception:
            return
        if not self.cleanup_pending:
            super()._notify_complete()

    async def _run(self):
        try:
            await super()._run()
        except Exception as exc:
            self.record.update(recovery_required=True, error=str(exc))
            self.request_stop()
            self._stop_result = await self._cleanup_active_devices()
            self._state = ExperimentState.FAILED
            if self._end_time is None:
                self._end_time = time.monotonic()
            try:
                self.exp_logger.finish_run('failed')
            except Exception:
                self.record['persistence_status'] = 'error'
        finally:
            self._finalize_record()

    async def _stop(self):
        try:
            success = await super()._stop()
        except Exception as exc:
            self.record.update(recovery_required=True, error=str(exc))
            return False
        # A previous record-write failure requires explicit acknowledgement, even after retry.
        if self.state == ExperimentState.IDLE:
            self._state = ExperimentState.STOPPED
        self._finalize_record()
        return success and self.record['persistence_status'] == 'ok'
