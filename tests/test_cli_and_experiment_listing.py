from types import SimpleNamespace
from unittest.mock import Mock
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_experiment_list_includes_yaml_and_yml(tmp_path, monkeypatch):
    experiments_dir = tmp_path / "experiments"
    experiments_dir.mkdir()
    (experiments_dir / "alpha.yaml").write_text(
        "name: alpha\ndescription: yaml file\nsteps: []\n",
        encoding="utf-8",
    )
    (experiments_dir / "beta.yml").write_text(
        "name: beta\ndescription: yml file\nsteps: []\n",
        encoding="utf-8",
    )
    (experiments_dir / "ignored.txt").write_text("name: ignored\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    from src.web.api import experiments as experiments_api

    app = FastAPI()
    app.include_router(experiments_api.router)
    response = TestClient(app).get("/experiments/")

    assert response.status_code == 200
    assert [item["filename"] for item in response.json()] == ["alpha.yaml", "beta.yml"]


def test_production_experiment_assets_are_reviewed_and_strict():
    from src.experiment.parser import list_experiments, parse_experiment

    expected = {
        "low_risk_all_devices_smoke_test.yaml",
        "mvp_water_loop_baseline.yaml",
        "pump_microwave_water_flow_test.yaml",
    }
    assert {item["filename"] for item in list_experiments()} == expected

    for filename in expected:
        parsed = parse_experiment(filename)
        assert parsed["metadata"].get("safety_notes")
        raw = yaml.safe_load((Path("experiments") / filename).read_text(encoding="utf-8"))
        assert all(step.get("on_error", "stop") != "skip" for step in raw["steps"])

    archived = Path("docs/archive/experiments")
    assert {
        "chemical_synthesis_A.yaml",
        "cspbbr3_baseline.yaml",
        "pump_four_channel_demo.yaml",
        "simple_heat_test.yaml",
    }.issubset({path.name for path in archived.glob("*.yaml")})


def test_main_returns_nonzero_when_experiment_fails(monkeypatch):
    import src.main as main_module

    controller = Mock()
    controller.initialize.return_value = True
    controller.run_experiment.return_value = False
    controller.shutdown.return_value = True

    monkeypatch.setattr(
        main_module,
        "AutomationController",
        lambda config_path: controller,
    )
    monkeypatch.setattr(main_module.signal, "signal", Mock())
    monkeypatch.setattr(
        main_module.argparse.ArgumentParser,
        "parse_args",
        lambda self: SimpleNamespace(
            config=None,
            interactive=False,
            device="heater1",
            temperature=100.0,
            duration=5.0,
        ),
    )

    assert main_module.main() == 1
    controller.run_experiment.assert_called_once_with("heater1", 100.0, 5.0)
    controller.generate_report.assert_not_called()
    controller.shutdown.assert_called_once_with()


@pytest.mark.parametrize(
    ("disconnect_name", "stop_name", "store_name"),
    [
        ("disconnect_device", "stop", "_heaters"),
        ("disconnect_pump", "stop_all", "_pumps"),
    ],
)
@pytest.mark.parametrize("stop_outcome", ["false", "exception"])
def test_cli_disconnect_retains_connection_when_stop_is_not_confirmed(
    disconnect_name, stop_name, store_name, stop_outcome
):
    from src.main import AutomationController

    controller = AutomationController.__new__(AutomationController)
    controller._logger = Mock()
    controller._heaters = {}
    controller._pumps = {}
    device = Mock()
    device.is_connected.return_value = True
    stop = getattr(device, stop_name)
    if stop_outcome == "false":
        stop.return_value = False
    else:
        stop.side_effect = RuntimeError("stop failed")
    getattr(controller, store_name)["device1"] = device

    assert getattr(controller, disconnect_name)("device1") is False
    device.disconnect.assert_not_called()


def test_cli_shutdown_continues_other_devices_and_reports_stop_failure():
    from src.main import AutomationController

    controller = AutomationController.__new__(AutomationController)
    controller._logger = Mock()
    controller._running = True
    controller.stop_recording = Mock()
    heater = Mock()
    heater.is_connected.return_value = True
    heater.stop.return_value = False
    pump = Mock()
    pump.is_connected.return_value = True
    pump.stop_all.return_value = True
    pump.disconnect.return_value = True
    controller._heaters = {"heater1": heater}
    controller._pumps = {"pump1": pump}

    assert controller.shutdown() is False
    heater.disconnect.assert_not_called()
    pump.stop_all.assert_called_once_with()
    pump.disconnect.assert_called_once_with()


def test_main_returns_nonzero_when_shutdown_fails_and_registers_sigterm(
    monkeypatch,
):
    import src.main as main_module

    controller = Mock()
    controller.initialize.return_value = True
    controller.run_experiment.return_value = True
    controller.generate_report.return_value = None
    controller.shutdown.return_value = False
    registered_signals = []

    monkeypatch.setattr(
        main_module,
        "AutomationController",
        lambda config_path: controller,
    )
    monkeypatch.setattr(
        main_module.signal,
        "signal",
        lambda sig, handler: registered_signals.append(sig),
    )
    monkeypatch.setattr(
        main_module.argparse.ArgumentParser,
        "parse_args",
        lambda self: SimpleNamespace(
            config=None,
            interactive=False,
            device="heater1",
            temperature=100.0,
            duration=5.0,
        ),
    )

    assert main_module.main() == 1
    assert registered_signals == [main_module.signal.SIGINT, main_module.signal.SIGTERM]
    controller.shutdown.assert_called_once_with()
