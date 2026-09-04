import warnings
import signal
from datetime import datetime
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient


def test_serial_manager_leaves_process_signal_handling_to_the_application(
    monkeypatch,
):
    from src.utils import serial_manager as serial_mod

    atexit_register = Mock()
    signal_register = Mock()
    monkeypatch.setattr(serial_mod.atexit, "register", atexit_register)
    monkeypatch.setattr(signal, "signal", signal_register)
    monkeypatch.setattr(serial_mod.SerialPortManager, "_instance", None)

    manager = serial_mod.SerialPortManager()

    atexit_register.assert_called_once_with(manager.cleanup)
    signal_register.assert_not_called()
    assert not hasattr(serial_mod.SerialPortManager, "_signal_handler")


@pytest.mark.parametrize(
    "path",
    [
        "/%2e%2e/app.py",
        "/..%2Fapp.py",
        "/%2e%2e%5capp.py",
    ],
)
def test_spa_fallback_rejects_static_directory_traversal(path):
    from src.web.app import app

    response = TestClient(app).get(path)

    assert response.status_code == 404
    assert "import asyncio" not in response.text


@pytest.mark.parametrize("path", ["/api/not-a-route", "/ws/not-a-route"])
def test_spa_fallback_does_not_hide_unknown_backend_routes(path):
    from src.web.app import app

    response = TestClient(app).get(path)

    assert response.status_code == 404


def test_experiment_logger_records_pump_read_quality_without_false_flow():
    from src.experiment.experiment_logger import ExperimentLogger, ExperimentRun

    experiment_logger = ExperimentLogger(save_log=False)
    experiment_logger._active_run = ExperimentRun(
        run_id="pump_read_quality",
        experiment_name="pump_read_quality",
        experiment_file="pump_read_quality.yaml",
        started_at=datetime.now().isoformat(),
    )

    experiment_logger.record_sensor_data(
        {
            "pumps": {
                "pump1": {
                    "channels": {
                        "1": {
                            "read_ok": False,
                            "flow_rate": 999.0,
                            "volume": 999.0,
                            "flow_unit": "ML_MIN",
                        },
                        "2": {
                            "read_ok": True,
                            "flow_rate": 1.5,
                            "volume": 2.5,
                            "flow_unit": "ML_MIN",
                        },
                    }
                }
            }
        }
    )

    pump_data = experiment_logger.active_run.sensor_data["pumps"]["pump1"]
    assert pump_data["1"]["read_ok"][0]["v"] is False
    assert pump_data["1"]["running"][0]["v"] is None
    assert pump_data["1"]["flow_rate"][0]["v"] is None
    assert pump_data["2"]["flow_rate"][0]["v"] == 1.5
    assert pump_data["2"]["volume"][0]["v"] == 2.5


def test_heater_output_status_read_failure_is_unknown():
    from src.devices.heater import AIHeaterDevice, HeaterConfig
    from src.protocols.parameters import ParameterCode, RunStatus

    class OutputStatusReadFailureProtocol:
        is_open = True

        def read_pv_sv(self, decimal_places):
            return 25.0, 30.0, 0, 0

        def read_parameter(self, parameter):
            assert parameter == ParameterCode.OUTPUT_STATUS
            raise IOError("status unavailable")

    heater = AIHeaterDevice(
        HeaterConfig(
            device_id="heater_status_quality",
            connection_params={"port": "FAKE"},
            retry_count=1,
            retry_delay=0.0,
        )
    )
    heater._protocol = OutputStatusReadFailureProtocol()

    data = heater.read_data()

    assert data.run_status is RunStatus.UNKNOWN
    assert data.run_status.name == "UNKNOWN"


def test_campaign_timestamp_is_utc_without_utcnow_deprecation():
    from src.campaigns.models import utc_now_iso

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        timestamp = utc_now_iso()

    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    assert timestamp.endswith("Z")
    assert parsed.utcoffset().total_seconds() == 0
    assert parsed.microsecond == 0
