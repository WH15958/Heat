"""Experiment authoring validation and atomic file storage. No device access."""
import hashlib
import os
import tempfile
from pathlib import Path

import yaml
from pydantic import ValidationError

from src.experiment.parser import _validate_filename, parse_experiment_data
from src.experiment.parameter_models import (
    SetTemperatureRequest, StartPumpRequest, StopPumpRequest,
    MicrowaveConfigureRequest, MicrowaveStartRequest,
)


class UniqueKeyLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        keys = set()
        for key, _ in node.value:
            if key.tag == 'tag:yaml.org,2002:merge':
                continue
            value = self.construct_object(key, deep=deep)
            if not isinstance(value, (str, int, float, bool, type(None))):
                raise ValueError('Mapping keys must be scalar values')
            if value in keys:
                raise yaml.constructor.ConstructorError(
                    None, None, f'Duplicate key: {value}', key.start_mark
                )
            keys.add(value)
        return super().construct_mapping(node, deep)


def _locations(node, path=(), seen=None):
    seen = set() if seen is None else seen
    if node is None or id(node) in seen:
        return {}
    seen.add(id(node))
    result = {path: (node.start_mark.line + 1, node.start_mark.column + 1)}
    if isinstance(node, yaml.MappingNode):
        for key, value in node.value:
            result.update(_locations(value, (*path, key.value), seen))
    elif isinstance(node, yaml.SequenceNode):
        for index, value in enumerate(node.value):
            result.update(_locations(value, (*path, index), seen))
    return result


def _check_params(step):
    action, params = step['type'], step.get('params', {})
    if action.startswith(('heater.', 'pump.', 'microwave.')):
        if not isinstance(params.get('device_id'), str) or not params['device_id'].strip():
            raise ValueError('params.device_id is required')
    if action == 'heater.set_temperature':
        SetTemperatureRequest.model_validate(params)
    elif action == 'pump.start':
        if 'channel' not in params:
            raise ValueError('params.channel is required')
        StartPumpRequest.model_validate(params)
    elif action == 'pump.stop_channel':
        if params.get('channel') is None:
            raise ValueError('params.channel is required')
        StopPumpRequest.model_validate(params)
    elif action == 'microwave.start':
        MicrowaveStartRequest.model_validate(params)
    elif action.startswith('microwave.configure_'):
        # Keep the aliases accepted by the executor; canonical names take precedence.
        aliases = {
            'heating_temperature': ('heat_temperature', 'ramp_target_temperature', 'target_temperature'),
            'heating_power_percent': ('heat_power',),
            'holding_temperature': ('hold_temperature', 'hold_target_temperature'),
            'holding_power_percent': ('hold_power',), 'holding_deviation': ('hold_deviation',),
            'hours': ('hold_hours',), 'minutes': ('hold_minutes',), 'seconds': ('hold_seconds',),
            'target_temperature': ('ramp_target_temperature',),
        }
        raw = params.get('segments')
        if not isinstance(raw, list) or any(not isinstance(s, dict) for s in raw):
            raise ValueError('params.segments must be a list of objects')
        segments = []
        for item in raw:
            item = dict(item)
            for target, sources in aliases.items():
                for source in sources:
                    if target not in item and source in item:
                        item[target] = item[source]
            segments.append(item)
        checked = MicrowaveConfigureRequest.model_validate({'segments': segments})
        ids = [s.segment for s in checked.segments]
        if len(ids) != len(set(ids)):
            raise ValueError('Duplicate microwave segment number')
        if action != 'microwave.configure_manual' and any(
            s.heating_power_percent is not None or s.holding_power_percent is not None
            for s in checked.segments
        ):
            raise ValueError('Power fields are only allowed for manual_power')
    wait = step.get('wait', {})
    if wait.get('type', 'none') not in ('none', 'duration'):
        if not isinstance(wait.get('device_id'), str) or not wait['device_id'].strip():
            raise ValueError('wait.device_id is required')
    if wait.get('type') == 'pump_complete':
        if wait.get('channel') is None:
            raise ValueError('wait.channel is required')
        StopPumpRequest.model_validate({'channel': wait['channel']})


def validate_source(content: str, filename: str = 'untitled.yaml') -> dict:
    errors, warnings, locations = [], [], {}
    data = None

    def issue(message, path=(), step_id=None):
        probe = path
        while probe and probe not in locations:
            probe = probe[:-1]
        line, column = locations.get(probe, (1, 1))
        return dict(message=message, path=list(path), step_id=step_id, line=line, column=column)

    try:
        node = yaml.compose(content, Loader=yaml.SafeLoader)
        locations = _locations(node)
        data = yaml.load(content, Loader=UniqueKeyLoader)
        parse_experiment_data(data, filename, validate_devices=False)
    except yaml.YAMLError as exc:
        mark = getattr(exc, 'problem_mark', None)
        problem = issue(getattr(exc, 'problem', None) or str(exc))
        if mark:
            problem.update(line=mark.line + 1, column=mark.column + 1)
        errors.append(problem)
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError) as exc:
        path, step_id = (), None
        if isinstance(data, dict) and isinstance(data.get('steps'), list):
            seen_ids = set()
            for index, step in enumerate(data['steps']):
                try:
                    parse_experiment_data({**data, 'steps': [step]}, filename, validate_devices=False)
                    current_id = step['id']
                    if current_id in seen_ids:
                        raise ValueError('Duplicate step id')
                    seen_ids.add(current_id)
                except (ValueError, TypeError, KeyError, RecursionError, OverflowError):
                    path = ('steps', index)
                    step_id = step.get('id') if isinstance(step, dict) else None
                    break
        errors.append(issue(str(exc), path, step_id))
    else:
        if data.get('metadata') is not None and not isinstance(data['metadata'], dict):
            errors.append(issue('metadata must be an object', ('metadata',)))
        for key in ('name', 'description'):
            if key in data and not isinstance(data[key], str):
                errors.append(issue(f'{key} must be a string', (key,)))
        for index, step in enumerate(data['steps']):
            try:
                _check_params(step)
            except ValidationError as exc:
                for error in exc.errors():
                    errors.append(issue(error['msg'], ('steps', index, 'params', *error['loc']), step['id']))
            except (ValueError, TypeError) as exc:
                errors.append(issue(str(exc), ('steps', index), step['id']))
            if step.get('wait', {}).get('type') == 'microwave_complete':
                warnings.append(issue('微波完成信号尚需实机确认，建议使用有界等待后显式停止。', ('steps', index, 'wait'), step['id']))
        if not any(s.get('enabled', True) for s in data['steps']):
            warnings.append(issue('没有启用的步骤。', ('steps',)))
        from src.utils.config import ConfigManager
        try:
            config = ConfigManager().load()
            device_groups = {
                'heater': {d.device_id for d in config.heaters if d.enabled},
                'pump': {d.device_id for d in config.pumps if d.enabled},
                'microwave': {d.device_id for d in config.microwaves if d.enabled},
                'syringe_pump': {d.device_id for d in config.syringe_pumps if d.enabled},
                'valve': {d.device_id for d in config.valves if d.enabled},
            }
            for index, step in enumerate(data['steps']):
                group = step['type'].split('.')[0]
                device_id = step.get('params', {}).get('device_id')
                if group in device_groups and device_id and device_id not in device_groups[group]:
                    warnings.append(issue(f'未知或未启用的设备：{device_id}', ('steps', index, 'params', 'device_id'), step['id']))
                wait = step.get('wait', {})
                wait_group = {
                    'temperature_reached': 'heater', 'pump_complete': 'pump',
                    'microwave_temperature_reached': 'microwave',
                    'microwave_complete': 'microwave',
                    'microwave_temperature_below': 'microwave',
                    'microwave_monitored_hold': 'microwave',
                    'syringe_pump_complete': 'syringe_pump',
                }.get(wait.get('type'))
                if wait_group and wait.get('device_id') not in device_groups[wait_group]:
                    warnings.append(issue(f'等待引用未知或未启用的设备：{wait.get("device_id")}', ('steps', index, 'wait', 'device_id'), step['id']))
        except (ValueError, OSError):
            warnings.append(issue('设备配置暂不可读，请运行前重新核对设备。'))
    return dict(valid=not errors, errors=errors, warnings=warnings)


def source_path(filename: str) -> Path:
    path = _validate_filename(filename)
    # Disallow symlink aliases and Windows alternate/device names for writable files.
    if path.is_symlink() or filename.endswith((' ', '.')) or filename.split('.')[0].upper() in {
        'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))
    }:
        raise ValueError('Invalid experiment filename')
    return path


def revision(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def read_source(filename: str) -> dict:
    raw = source_path(filename).read_bytes()
    return dict(filename=filename, content=raw.decode('utf-8'), revision=revision(raw))


class SourceConflict(ValueError):
    pass


def write_source(filename: str, content: str, expected_revision: str | None) -> dict:
    path = source_path(filename)
    raw = content.encode('utf-8')

    def check_revision():
        current = revision(path.read_bytes()) if path.exists() else None
        if current != expected_revision:
            raise SourceConflict('文件已存在或已被修改，请重新读取或另存为。')

    check_revision()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix='.tmp', delete=False) as f:
            temporary = f.name
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        check_revision()
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
    return dict(filename=filename, content=content, revision=revision(raw))
