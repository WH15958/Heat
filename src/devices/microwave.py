"""
Synchronous MKM-AH1E microwave device driver.

This driver only performs direct, blocking Modbus calls. It does not create
background polling, heartbeats, command queues, or worker threads.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional
import logging

from src.devices.base_device import (
    BaseDevice,
    DeviceConfig,
    DeviceData,
    DeviceInfo,
    DeviceStatus,
    DeviceType,
)
from src.protocols.modbus_rtu import ModbusRTUProtocol
from src.protocols.microwave_params import (
    CONTROL_MICROWAVE_START,
    CONTROL_STOP,
    CONTROL_WORD,
    MAX_SEGMENTS,
    MODE_CONTROL_MASKS,
    STATUS_BLOCK_COUNT,
    STATUS_BLOCK_START,
    STATUS_CURRENT,
    STATUS_CURRENT_MODE_CODE,
    STATUS_CURRENT_SEGMENT,
    STATUS_FAULT_CODE,
    STATUS_FLOAT_TEMPERATURE,
    STATUS_MATERIAL_TEMPERATURE_RAW,
    STATUS_POWER_PERCENT,
    STATUS_RUNTIME_HOURS,
    STATUS_RUNTIME_MINUTES,
    STATUS_RUNTIME_SECONDS_PART,
    MicrowaveMode,
    auto_power_segment_start,
    constant_rate_segment_start,
    manual_hold_time_start,
    manual_segment_start,
)

logger = logging.getLogger(__name__)


@dataclass
class MicrowaveSegment:
    """One program segment worth of raw register values."""

    segment: int
    heating_temperature: float = 0.0
    heating_power_percent: int = 0
    holding_temperature: float = 0.0
    holding_power_percent: int = 0
    holding_deviation: float = 0.0
    hours: int = 0
    minutes: int = 0
    seconds: int = 0
    target_temperature: Optional[float] = None
    ramp_hours: int = 0
    ramp_minutes: int = 0
    ramp_seconds: int = 0


@dataclass
class MicrowaveStatus:
    """Raw microwave status values exposed by the protocol table."""

    current: int = 0
    material_temperature_raw: int = 0
    power_percent: int = 0
    runtime_hours: int = 0
    runtime_minutes: int = 0
    runtime_seconds_part: int = 0
    runtime_seconds: int = 0
    fault_code: int = 0
    current_segment: int = 0
    current_mode_code: int = 0
    material_temperature: Optional[float] = None
    material_temperature_source: str = "raw"


@dataclass
class MicrowaveConfig(DeviceConfig):
    """Microwave device configuration."""

    slave_address: int = 1
    baudrate: int = 9600
    parity: str = "N"
    stopbits: int = 1
    bytesize: int = 8
    timeout: float = 2.0
    poll_interval: float = 1.0
    max_temperature: float = 300.0
    max_power_percent: int = 100
    allow_experiment_control: bool = True
    allow_real_hardware_writes: bool = True
    enable_control_writes: bool = True


@dataclass
class MicrowaveData(DeviceData):
    """Microwave data snapshot."""

    microwave_status: MicrowaveStatus = field(default_factory=MicrowaveStatus)


class MicrowaveDevice(BaseDevice):
    """Synchronous microwave driver using Modbus RTU."""

    SUPPORTED_COMMANDS = [
        "read_data",
        "configure_manual",
        "configure_auto_power",
        "configure_constant_rate",
        "start",
        "stop",
        "emergency_stop",
    ]

    def __init__(
        self,
        config: MicrowaveConfig,
        info: Optional[DeviceInfo] = None,
        protocol: Optional[ModbusRTUProtocol] = None,
    ):
        if info is None:
            info = DeviceInfo(
                name=config.device_id,
                device_type=DeviceType.MICROWAVE,
                model="MKM-AH1E",
                description="MKM-AH1E microwave synthesis device",
            )
        super().__init__(config, info)
        self._microwave_config = config
        self._protocol = protocol

    @property
    def protocol(self):
        return self._protocol

    def connect(self) -> bool:
        """Connect the Modbus protocol synchronously."""
        with self._lock:
            if self.is_connected():
                self.status = DeviceStatus.CONNECTED
                return True
            if self._status == DeviceStatus.CONNECTING:
                self._logger.error("Connection already in progress")
                return False
            self.status = DeviceStatus.CONNECTING

        protocol = self._protocol
        created_protocol = False
        try:
            if protocol is None:
                protocol = ModbusRTUProtocol(
                    port=self.config.connection_params.get("port", "COM1"),
                    baudrate=self.config.connection_params.get(
                        "baudrate", self._microwave_config.baudrate
                    ),
                    parity=self.config.connection_params.get("parity", self._microwave_config.parity),
                    stopbits=self.config.connection_params.get(
                        "stopbits", self._microwave_config.stopbits
                    ),
                    bytesize=self.config.connection_params.get(
                        "bytesize", self._microwave_config.bytesize
                    ),
                    timeout=self.config.timeout,
                )
                created_protocol = True

            if not self._connect_protocol(protocol):
                with self._lock:
                    self.status = DeviceStatus.ERROR
                return False

            with self._lock:
                self._protocol = protocol
                self.status = DeviceStatus.CONNECTED
            return True
        except Exception as e:
            self._logger.error(f"Failed to connect microwave: {e}")
            if created_protocol and protocol is not None:
                self._disconnect_protocol(protocol)
            with self._lock:
                self.status = DeviceStatus.ERROR
            return False

    def disconnect(self) -> bool:
        """Disconnect the protocol synchronously."""
        with self._lock:
            if self._protocol is not None:
                self._disconnect_protocol(self._protocol)
                self._protocol = None
            self.status = DeviceStatus.DISCONNECTED
            return True

    def is_connected(self) -> bool:
        """Return True when the protocol object reports an open connection."""
        return self._protocol is not None and self._protocol_connected(self._protocol)

    def read_data(self) -> MicrowaveData:
        """Read raw microwave status data."""
        if not self.is_connected():
            raise IOError("Device not connected")

        with self._lock:
            values = self._read_registers(STATUS_BLOCK_START, STATUS_BLOCK_COUNT)
            if values is None or len(values) < STATUS_BLOCK_COUNT:
                raise IOError("Failed to read microwave status")

            def value_at(address: int) -> int:
                return int(values[address - STATUS_BLOCK_START])

            status = MicrowaveStatus(
                current=value_at(STATUS_CURRENT),
                material_temperature_raw=value_at(STATUS_MATERIAL_TEMPERATURE_RAW),
                power_percent=value_at(STATUS_POWER_PERCENT),
                runtime_hours=value_at(STATUS_RUNTIME_HOURS),
                runtime_minutes=value_at(STATUS_RUNTIME_MINUTES),
                runtime_seconds_part=value_at(STATUS_RUNTIME_SECONDS_PART),
                fault_code=value_at(STATUS_FAULT_CODE),
                current_segment=value_at(STATUS_CURRENT_SEGMENT),
                current_mode_code=value_at(STATUS_CURRENT_MODE_CODE),
            )
            status.runtime_seconds = (
                status.runtime_hours * 3600
                + status.runtime_minutes * 60
                + status.runtime_seconds_part
            )

            # 40118/40119 byte and word order still needs real-device confirmation.
            float_temperature = self._read_float(STATUS_FLOAT_TEMPERATURE)
            if float_temperature is not None:
                status.material_temperature = float_temperature
                status.material_temperature_source = "float"
            else:
                status.material_temperature = float(status.material_temperature_raw)
                status.material_temperature_source = "raw"

            data = MicrowaveData(
                device_id=self.config.device_id,
                timestamp=datetime.now(),
                data={
                    "current": status.current,
                    "material_temperature": status.material_temperature,
                    "material_temperature_raw": status.material_temperature_raw,
                    "material_temperature_source": status.material_temperature_source,
                    "power_percent": status.power_percent,
                    "runtime_seconds": status.runtime_seconds,
                    "fault_code": status.fault_code,
                    "current_segment": status.current_segment,
                    "current_mode_code": status.current_mode_code,
                },
                status=self.status,
                microwave_status=status,
            )
            self._last_data = data
            return data

    def configure_manual(self, segments: Iterable[MicrowaveSegment]) -> bool:
        """Write manual-power segment parameters."""
        for segment in self._coerce_segments(segments):
            if not self._validate_segment(segment, include_manual_power=True):
                return False
            params = [
                self._register_value(segment.heating_temperature),
                self._register_value(segment.heating_power_percent),
                self._register_value(segment.holding_temperature),
                self._register_value(segment.holding_power_percent),
                self._register_value(segment.holding_deviation),
            ]
            hold_time = [int(segment.hours), int(segment.minutes), int(segment.seconds)]
            if not self._write_registers(manual_segment_start(segment.segment), params):
                return False
            if not self._write_registers(manual_hold_time_start(segment.segment), hold_time):
                return False
        return True

    def configure_auto_power(self, segments: Iterable[MicrowaveSegment]) -> bool:
        """Write auto-power segment parameters."""
        for segment in self._coerce_segments(segments):
            if not self._validate_segment(segment):
                return False
            target_temperature = self._temperature_value(
                segment.target_temperature, segment.heating_temperature
            )
            params = [
                self._register_value(target_temperature),
                self._register_value(segment.holding_temperature),
                int(segment.hours),
                int(segment.minutes),
                int(segment.seconds),
            ]
            if not self._write_registers(auto_power_segment_start(segment.segment), params):
                return False
        return True

    def configure_constant_rate(self, segments: Iterable[MicrowaveSegment]) -> bool:
        """Write constant-rate segment parameters."""
        for segment in self._coerce_segments(segments):
            if not self._validate_segment(segment, include_ramp_time=True):
                return False
            target_temperature = self._temperature_value(
                segment.target_temperature, segment.heating_temperature
            )
            params = [
                int(segment.ramp_hours),
                int(segment.ramp_minutes),
                int(segment.ramp_seconds),
                self._register_value(target_temperature),
                int(segment.hours),
                int(segment.minutes),
                int(segment.seconds),
                self._register_value(segment.holding_temperature),
            ]
            if not self._write_registers(constant_rate_segment_start(segment.segment), params):
                return False
        return True

    def start(self, mode: MicrowaveMode | str) -> bool:
        """Write the explicit mode bit and start bit to the control word."""
        try:
            selected_mode = MicrowaveMode.from_value(mode)
        except ValueError:
            self._logger.error(f"Unsupported microwave mode: {mode}")
            return False
        control_word = MODE_CONTROL_MASKS[selected_mode] | CONTROL_MICROWAVE_START
        return self._write_register(CONTROL_WORD, control_word)

    def stop(self) -> bool:
        """Write this implementation's conservative stop control word."""
        return self._write_register(CONTROL_WORD, CONTROL_STOP)

    def emergency_stop(self) -> bool:
        """Use the same guarded stop path until real-device stop semantics are verified."""
        self._logger.warning("Microwave emergency_stop requested")
        return self.stop()

    def write_command(self, command: str, value: Any) -> bool:
        """Execute a supported microwave command."""
        if command not in self.SUPPORTED_COMMANDS:
            raise ValueError(f"Unsupported command: {command}")
        if command == "read_data":
            self.read_data()
            return True
        if command == "configure_manual":
            return self.configure_manual(value)
        if command == "configure_auto_power":
            return self.configure_auto_power(value)
        if command == "configure_constant_rate":
            return self.configure_constant_rate(value)
        if command == "start":
            return self.start(value)
        if command == "stop":
            return self.stop()
        if command == "emergency_stop":
            return self.emergency_stop()
        raise ValueError(f"Command not implemented: {command}")

    def get_available_commands(self) -> List[str]:
        return self.SUPPORTED_COMMANDS.copy()

    def _get_slave_address(self) -> int:
        return int(getattr(self.config, "slave_address", 1))

    def _write_register(self, address: int, value: int) -> bool:
        with self._lock:
            if not self.is_connected():
                return False
            return bool(
                self._protocol.write_single_register(
                    self._get_slave_address(),
                    int(address),
                    self._register_value(value),
                )
            )

    def _write_registers(self, start_address: int, values: List[int]) -> bool:
        end_address = int(start_address) + len(values)
        if int(start_address) <= CONTROL_WORD < end_address:
            self._logger.error("Microwave configuration write attempted to include control word")
            return False
        with self._lock:
            if not self.is_connected():
                return False
            clean_values = [self._register_value(value) for value in values]
            return bool(
                self._protocol.write_multiple_registers(
                    self._get_slave_address(),
                    int(start_address),
                    clean_values,
                )
            )

    def _read_registers(self, start_address: int, count: int) -> Optional[List[int]]:
        if not self.is_connected():
            return None
        return self._protocol.read_holding_registers(
            self._get_slave_address(),
            int(start_address),
            int(count),
        )

    def _read_float(self, address: int) -> Optional[float]:
        if not self.is_connected():
            return None
        return self._protocol.read_float_register(self._get_slave_address(), int(address))

    def _coerce_segments(self, segments: Iterable[MicrowaveSegment]) -> List[MicrowaveSegment]:
        coerced = []
        for segment in segments:
            if isinstance(segment, MicrowaveSegment):
                coerced.append(segment)
            elif isinstance(segment, dict):
                coerced.append(MicrowaveSegment(**segment))
            else:
                raise TypeError(f"Unsupported microwave segment: {type(segment).__name__}")
        return coerced

    def _validate_segment(
        self,
        segment: MicrowaveSegment,
        include_manual_power: bool = False,
        include_ramp_time: bool = False,
    ) -> bool:
        if not 1 <= int(segment.segment) <= MAX_SEGMENTS:
            self._logger.error(f"Invalid microwave segment: {segment.segment}")
            return False

        temperatures = [
            segment.heating_temperature,
            segment.holding_temperature,
            segment.target_temperature,
        ]
        if include_manual_power:
            temperatures.append(segment.holding_deviation)
        for temperature in temperatures:
            if temperature is not None and not self._valid_temperature(float(temperature)):
                return False

        if include_manual_power:
            powers = [segment.heating_power_percent, segment.holding_power_percent]
            for power in powers:
                if not self._valid_power(int(power)):
                    return False

        times = [segment.hours, segment.minutes, segment.seconds]
        if include_ramp_time:
            times.extend([segment.ramp_hours, segment.ramp_minutes, segment.ramp_seconds])
        for value in times:
            if int(value) < 0:
                self._logger.error(f"Microwave time value must be >= 0: {value}")
                return False
        return True

    def _valid_temperature(self, temperature: float) -> bool:
        if not 0 <= temperature <= self._microwave_config.max_temperature:
            self._logger.error(
                f"Microwave temperature {temperature} outside "
                f"0-{self._microwave_config.max_temperature}"
            )
            return False
        return True

    def _valid_power(self, power_percent: int) -> bool:
        if not 0 <= power_percent <= self._microwave_config.max_power_percent:
            self._logger.error(
                f"Microwave power {power_percent} outside "
                f"0-{self._microwave_config.max_power_percent}"
            )
            return False
        return True

    @staticmethod
    def _temperature_value(preferred: Optional[float], fallback: float) -> float:
        return float(fallback if preferred is None else preferred)

    @staticmethod
    def _register_value(value: Any) -> int:
        register_value = int(value)
        if not 0 <= register_value <= 0xFFFF:
            raise ValueError(f"Register value out of range: {value}")
        return register_value

    @staticmethod
    def _protocol_connected(protocol: Any) -> bool:
        connected = getattr(protocol, "is_connected", False)
        if callable(connected):
            return bool(connected())
        return bool(connected)

    @staticmethod
    def _connect_protocol(protocol: Any) -> bool:
        connect = getattr(protocol, "connect", None)
        if callable(connect):
            return bool(connect())
        return MicrowaveDevice._protocol_connected(protocol)

    @staticmethod
    def _disconnect_protocol(protocol: Any) -> None:
        disconnect = getattr(protocol, "disconnect", None)
        if callable(disconnect):
            disconnect()
