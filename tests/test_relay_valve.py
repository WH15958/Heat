"""Software checks only: never open a real serial port."""

import unittest
from unittest.mock import patch

from src.devices.base_device import DeviceConfig
from src.devices.relay_valve import RelayValveDevice
from src.utils.config import ValveDeviceConfig
from src.web.device_manager import DeviceManager


class FakeProtocol:
    def __init__(self, **kwargs):
        self.is_connected = False
        self.value = 0
        self.read_failed = False
        self.write_ok = True
        self.mismatch = False
        self.writes = []

    def connect(self):
        self.is_connected = True
        return True

    def disconnect(self):
        self.is_connected = False

    def read_holding_registers(self, address, start, count):
        assert (address, start, count) == (1, 0, 1)
        return None if self.read_failed else [self.value]

    def write_single_register(self, address, register, value):
        self.writes.append((address, register, value))
        if not self.mismatch:
            self.value = value
        return self.write_ok


class RelayValveTests(unittest.TestCase):
    def setUp(self):
        self.patch = patch('src.devices.relay_valve.ModbusRTUProtocol', FakeProtocol)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.valve = RelayValveDevice(DeviceConfig('valve1', {'port': 'FAKE'}))
        self.valve.connect()
        self.protocol = self.valve._protocol

    def test_connect_read_disconnect_never_write(self):
        self.valve.read_data()
        self.valve.disconnect()
        self.assertEqual(self.protocol.writes, [])
        self.assertIsNone(self.valve.relay_energized)

    def test_switch_requires_echo_and_readback(self):
        self.assertTrue(self.valve.set_energized(True))
        self.assertTrue(self.valve.relay_energized)
        self.protocol.mismatch = True
        with self.assertRaises(IOError):
            self.valve.set_energized(False)

    def test_timeout_is_unknown_and_not_retried(self):
        self.protocol.write_ok = False
        with self.assertRaises(IOError):
            self.valve.set_energized(True)
        self.assertEqual(len(self.protocol.writes), 1)
        self.assertIsNone(self.valve.relay_energized)
        self.assertFalse(self.valve.read_ok)

    def test_read_failure_clears_previous_value(self):
        self.protocol.read_failed = True
        with self.assertRaises(IOError):
            self.valve.read_data()
        self.assertFalse(self.valve.read_ok)
        self.assertIsNone(self.valve.relay_energized)

    def test_emergency_stop_does_not_claim_closed_route(self):
        self.assertFalse(self.valve.emergency_stop())
        self.assertEqual(self.protocol.writes, [])

    def test_manager_global_stop_blocks_switch_and_preserves_route(self):
        dm = DeviceManager()
        cfg = ValveDeviceConfig()
        dm.add_valve(cfg, dm._normalize_binding_info(None, 'FAKE'))
        dm.valve_operation('valve1', 'connect')
        dm._begin_global_stop()
        try:
            with self.assertRaises(RuntimeError):
                dm.valve_operation('valve1', 'switch', True)
        finally:
            dm._end_global_stop()
        self.assertFalse(dm.emergency_stop_all())
        self.assertEqual(dm.valves['valve1']._protocol.writes, [])
        self.assertTrue(dm.cleanup())

    def test_invalid_payload_never_writes(self):
        with self.assertRaises(ValueError):
            self.valve.set_energized('false')
        self.assertEqual(self.protocol.writes, [])

    def test_api_validation_and_failure_propagation(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from src.web.api.valves import router

        app = FastAPI()
        app.include_router(router, prefix='/api')
        dm = DeviceManager()
        dm.add_valve(ValveDeviceConfig(), dm._normalize_binding_info(None, 'FAKE'))
        app.state.device_manager = dm
        with TestClient(app) as client:
            self.assertEqual(client.get('/api/valve/missing/status').status_code, 404)
            self.assertEqual(client.post('/api/valve/valve1/switch', json={'energized': 'false'}).status_code, 422)
            self.assertEqual(client.post('/api/valve/valve1/connect').status_code, 200)
            self.assertEqual(client.get('/api/valve/valve1/status').status_code, 200)
            protocol = dm.valves['valve1']._protocol
            self.assertEqual(protocol.writes, [])
            protocol.write_ok = False
            self.assertEqual(client.post('/api/valve/valve1/switch', json={'energized': True}).status_code, 503)
            self.assertFalse(dm.get_all_status()['valves']['valve1']['read_ok'])
            self.assertEqual(len(protocol.writes), 1)
            self.assertEqual(client.post('/api/valve/valve1/disconnect').status_code, 200)


if __name__ == '__main__':
    unittest.main()
