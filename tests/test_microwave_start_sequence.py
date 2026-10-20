"""Guarded, finite microwave startup sequences using an in-memory PLC model."""
from collections import Counter

import pytest

from src.devices.microwave import MicrowaveConfig, MicrowaveDevice
from src.protocols.microwave_params import (
    CONTROL_AUTO_POWER,
    CONTROL_MANUAL_POWER,
    CONTROL_MICROWAVE_START,
    CONTROL_WORD,
    MODE_CONTROL_MASKS,
    STATUS_BLOCK_COUNT,
    STATUS_BLOCK_START,
    STATUS_CURRENT,
    STATUS_FAULT_CODE,
    STATUS_POWER_PERCENT,
    MicrowaveMode,
    auto_power_segment_start,
)
from test_microwave_atomic_config import RecordingProtocol


class EdgeLatchProtocol(RecordingProtocol):
    """START uses the mode selected before this write, without mode-code guesses."""

    def __init__(self):
        super().__init__()
        self.registers[CONTROL_WORD] = CONTROL_MANUAL_POWER
        self.running_mode_bit = None
        self.reads = []
        self.after_write = None
        self.after_read = None

    def write_single_register(self, slave, address, value):
        previous = self.registers.get(address, 0)
        if address == CONTROL_WORD and value & CONTROL_MICROWAVE_START:
            if not previous & CONTROL_MICROWAVE_START:
                mode_mask = sum(MODE_CONTROL_MASKS.values())
                self.running_mode_bit = previous & mode_mask
        success = super().write_single_register(slave, address, value)
        if self.after_write:
            self.after_write(address, value)
        return success

    def read_holding_registers(self, slave, address, count):
        self.reads.append((address, count))
        values = super().read_holding_registers(slave, address, count)
        if self.after_read:
            self.after_read(address, count)
        if address == CONTROL_WORD:
            # Mode selection bits are write-only; only expose the known START readback.
            return [value & CONTROL_MICROWAVE_START for value in values]
        return values


def make_device():
    protocol = EdgeLatchProtocol()
    device = MicrowaveDevice(MicrowaveConfig(device_id="mw1",
        connection_params={"port": "FAKE"}), protocol=protocol)
    device.READBACK_DELAY = 0
    return device, protocol


def configure(device, mode, segments=2):
    method = "configure_manual" if mode == "manual_power" else "configure_" + mode
    assert getattr(device, method)([
        dict(segment=index, target_temperature=60, holding_temperature=60, minutes=31)
        for index in range(1, segments + 1)
    ])


def start_writes(protocol):
    return [write for write in protocol.single_writes
            if write[1] == CONTROL_WORD and write[2] & CONTROL_MICROWAVE_START]


def test_separate_selection_avoids_latching_previous_manual_mode():
    old = EdgeLatchProtocol()
    assert old.write_single_register(1, CONTROL_WORD,
        CONTROL_AUTO_POWER | CONTROL_MICROWAVE_START)
    assert old.running_mode_bit == CONTROL_MANUAL_POWER

    device, protocol = make_device()
    assert device.start("auto_power")
    assert protocol.running_mode_bit == CONTROL_AUTO_POWER
    assert protocol.single_writes == [
        (1, CONTROL_WORD, CONTROL_AUTO_POWER),
        (1, CONTROL_WORD, CONTROL_AUTO_POWER | CONTROL_MICROWAVE_START),
    ]


@pytest.mark.parametrize("mode", list(MicrowaveMode))
@pytest.mark.parametrize("configured", [False, True])
def test_all_modes_keep_direct_start_and_bound_configuration_reads(mode, configured):
    device, protocol = make_device()
    expected_addresses = []
    if configured:
        configure(device, mode.value)
        expected_addresses = [address for _, address, _ in protocol.multi_writes]
    writes_before = list(protocol.multi_writes)
    protocol.reads.clear()

    assert device.start(mode)
    assert protocol.running_mode_bit == MODE_CONTROL_MASKS[mode]
    assert len(start_writes(protocol)) == 1
    assert protocol.multi_writes == writes_before
    assert device.last_command_result["before"]["control_active"] is False
    assert device.last_command_result["after_mode_selection"]["control_active"] is False
    assert device.last_command_result["before_start"]["control_active"] is False
    counts = Counter(address for address, _ in protocol.reads)
    status_reads = 5 if configured else 4
    expected_counts = Counter({STATUS_BLOCK_START: status_reads, CONTROL_WORD: status_reads})
    expected_counts.update({address: 2 for address in expected_addresses})
    assert counts == expected_counts
    assert device.last_command_result["configuration_verified"] is configured
    assert device.last_command_result["pre_start_configuration_verified"] is configured


@pytest.mark.parametrize("problem", ["active", "power", "current", "fault",
                                   "unknown", "read_failure", "read_exception"])
def test_fresh_idle_guard_rejects_unsafe_or_unknown_state_without_writes(problem):
    device, protocol = make_device()
    # A cached idle sample must not qualify a later, unsafe fresh observation.
    device.read_data()
    if problem == "active":
        protocol.registers[CONTROL_WORD] |= CONTROL_MICROWAVE_START
    elif problem in ("power", "current", "fault"):
        address = {"power": STATUS_POWER_PERCENT, "current": STATUS_CURRENT,
                   "fault": STATUS_FAULT_CODE}[problem]
        protocol.registers[address] = 1
    read = protocol.read_holding_registers

    def fail_read(slave, address, count):
        if problem == "unknown" and address == CONTROL_WORD:
            return None
        if problem.startswith("read_") and address == STATUS_BLOCK_START:
            if problem == "read_exception":
                raise IOError("status connection lost")
            return None
        return read(slave, address, count)

    protocol.read_holding_registers = fail_read
    assert not device.start("auto_power")
    assert protocol.single_writes == []
    assert not device.last_command_result["start_write_attempted"]


@pytest.mark.parametrize("problem", ["write_failure", "read_failure", "read_exception",
                                   "active", "output", "unknown", "fault"])
def test_mode_selection_failure_cannot_send_start(problem):
    device, protocol = make_device()
    write = protocol.write_single_register
    read = protocol.read_holding_registers

    def select(slave, address, value):
        if problem == "write_failure":
            protocol.single_writes.append((slave, address, value))
            return False
        success = write(slave, address, value)
        if problem == "active":
            protocol.registers[CONTROL_WORD] |= CONTROL_MICROWAVE_START
        elif problem == "output":
            protocol.registers[STATUS_POWER_PERCENT] = 11
        elif problem == "fault":
            protocol.registers[STATUS_FAULT_CODE] = 1
        return success

    def observe(slave, address, count):
        if protocol.single_writes:
            if problem in ("read_failure", "read_exception") and address == STATUS_BLOCK_START:
                if problem == "read_exception":
                    raise IOError("mode-selection status lost")
                return None
            if problem == "unknown" and address == CONTROL_WORD:
                return None
        return read(slave, address, count)

    protocol.write_single_register = select
    protocol.read_holding_registers = observe
    assert not device.start("auto_power")
    assert len(protocol.single_writes) == 1
    assert start_writes(protocol) == []
    assert not device.last_command_result["start_write_attempted"]


def test_mode_selection_parameter_reload_invalidates_configuration_without_rewriting():
    device, protocol = make_device()
    configure(device, "auto_power")
    writes_before = list(protocol.multi_writes)
    address = auto_power_segment_start(1)

    def reload(selected_address, value):
        if selected_address == CONTROL_WORD and not value & CONTROL_MICROWAVE_START:
            protocol.registers[address + 3] = 5

    protocol.after_write = reload
    assert not device.start("auto_power")
    assert "pre-start configuration mismatch" in device.last_command_error
    assert protocol.multi_writes == writes_before
    assert start_writes(protocol) == []
    assert device._expected_configuration is None
    assert device.last_command_result["pre_start_blocks"][0]["actual"] == [60, 60, 0, 5, 0]

    reads_before = list(protocol.reads)
    assert not device.start("auto_power")
    assert "configure the selected mode again" in device.last_command_error
    assert protocol.reads == reads_before
    assert len(protocol.single_writes) == 1

    protocol.after_write = None
    configure(device, "auto_power")
    assert device.start("auto_power")


@pytest.mark.parametrize("problem", ["active", "power", "current", "fault", "unknown"])
def test_state_changed_during_parameter_verification_blocks_final_start(problem):
    device, protocol = make_device()
    configure(device, "auto_power")
    last_address = auto_power_segment_start(2)
    read = protocol.read_holding_registers
    changed = False

    def observe(slave, address, count):
        nonlocal changed
        if changed and problem == "unknown" and address == CONTROL_WORD:
            return None
        values = read(slave, address, count)
        if address == last_address:
            changed = True
            target = {"active": CONTROL_WORD, "power": STATUS_POWER_PERCENT,
                      "current": STATUS_CURRENT, "fault": STATUS_FAULT_CODE}.get(problem)
            if target is not None:
                protocol.registers[target] = (CONTROL_AUTO_POWER | CONTROL_MICROWAVE_START
                    if problem == "active" else 1)
        return values

    protocol.read_holding_registers = observe
    assert not device.start("auto_power")
    assert "before_start" in device.last_command_error
    assert start_writes(protocol) == []
    assert len(protocol.single_writes) == 1
    assert device.last_command_result["pre_start_configuration_verified"]


@pytest.mark.parametrize("phase", ["pre-start", "post-start"])
@pytest.mark.parametrize("problem", ["read_failure", "read_exception", "changed"])
def test_unverifiable_configuration_invalidates_session_and_preserves_evidence(phase, problem):
    device, protocol = make_device()
    configure(device, "auto_power")
    read = protocol.read_holding_registers
    address = auto_power_segment_start(1)

    def observe(slave, selected_address, count):
        reached_phase = bool(start_writes(protocol)) == (phase == "post-start")
        if protocol.single_writes and reached_phase and selected_address == address:
            if problem == "read_exception":
                raise IOError("configuration connection lost")
            if problem == "read_failure":
                return None
            protocol.registers[address + 3] = 5
        return read(slave, selected_address, count)

    protocol.read_holding_registers = observe
    assert not device.start("auto_power")
    assert phase in device.last_command_error
    assert device._expected_configuration is None
    assert len(start_writes(protocol)) == (1 if phase == "post-start" else 0)
    blocks = device.last_command_result["blocks" if phase == "post-start" else "pre_start_blocks"]
    assert len(blocks) == 1
    assert blocks[0]["address"] == address
    if problem == "read_exception":
        assert blocks[0]["error"] == "configuration connection lost"
    else:
        assert blocks[0]["actual"] != blocks[0]["expected"]


@pytest.mark.parametrize("phase", ["before", "before_read", "selection_write",
    "selection_read", "pre-start", "before_start_read", "start_write", "post-start", "final_read"])
def test_stop_preempts_remaining_startup_operations(phase):
    device, protocol = make_device()
    configure(device, "auto_power")
    protocol.reads.clear()
    stopped = phase == "before"
    address = auto_power_segment_start(1)
    status_reads = 0

    def after_read(selected_address, count):
        nonlocal stopped, status_reads
        if selected_address == CONTROL_WORD:
            status_reads += 1
            if (phase, status_reads) in (("before_read", 1), ("selection_read", 2),
                                        ("before_start_read", 3), ("final_read", 5)):
                stopped = True
        if selected_address == address:
            if phase == ("post-start" if start_writes(protocol) else "pre-start"):
                stopped = True

    def after_write(selected_address, value):
        nonlocal stopped
        if selected_address == CONTROL_WORD:
            if phase == ("start_write" if value & CONTROL_MICROWAVE_START else "selection_write"):
                stopped = True

    protocol.after_read = after_read
    protocol.after_write = after_write
    assert not device.start("auto_power", should_stop=lambda: stopped)
    assert "stop request" in device.last_command_error
    expected_starts = 1 if phase in ("start_write", "post-start", "final_read") else 0
    assert len(start_writes(protocol)) == expected_starts
    if phase == "before":
        assert protocol.reads == [] and protocol.single_writes == []
    elif phase == "before_read":
        assert protocol.single_writes == []
    elif phase == "selection_write":
        assert protocol.reads == [(STATUS_BLOCK_START, STATUS_BLOCK_COUNT), (CONTROL_WORD, 1)]
    elif phase in ("pre-start", "post-start"):
        blocks = device.last_command_result["blocks" if phase == "post-start" else "pre_start_blocks"]
        assert len(blocks) == 1
    elif phase == "start_write":
        assert status_reads == 3
    assert not device.last_command_result["success"]


def test_unconfirmed_start_has_bounded_readback_and_one_start_write():
    device, protocol = make_device()

    def refuse_start(address, value):
        if address == CONTROL_WORD and value & CONTROL_MICROWAVE_START:
            protocol.registers[CONTROL_WORD] = value & ~CONTROL_MICROWAVE_START

    protocol.after_write = refuse_start
    assert not device.start("auto_power")
    assert len(start_writes(protocol)) == 1
    assert Counter(address for address, _ in protocol.reads) == Counter({
        STATUS_BLOCK_START: 3 + device.READBACK_ATTEMPTS,
        CONTROL_WORD: 3 + device.READBACK_ATTEMPTS,
    })
