import os
import sys

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)
sys.path.insert(0, os.path.join(_project_root, "src"))

from src.devices.heater import AIHeaterDevice, HeaterConfig


class _ClosedProtocol:
    is_open = False


def test_heater_disconnect_guard():
    config = HeaterConfig(
        device_id="heater_guard",
        connection_params={
            "port": "COM7",
            "baudrate": 9600,
            "address": 1,
            "parity": "N",
        },
        retry_count=1,
        retry_delay=0.0,
    )
    heater = AIHeaterDevice(config)
    heater._protocol = _ClosedProtocol()

    try:
        heater.read_data()
    except IOError as exc:
        assert str(exc) == "Device not connected"
    else:
        raise AssertionError("Expected IOError when protocol is unavailable")

    print("heater disconnect guard test: passed")


if __name__ == "__main__":
    test_heater_disconnect_guard()
