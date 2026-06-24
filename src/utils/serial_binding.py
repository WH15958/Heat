from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

from serial.tools import list_ports


@dataclass
class SerialPortInfo:
    port: str
    serial_number: Optional[str] = None
    vid: Optional[int] = None
    pid: Optional[int] = None
    location: Optional[str] = None
    description: Optional[str] = None
    manufacturer: Optional[str] = None
    hwid: Optional[str] = None

    def summary(self) -> str:
        parts = [self.port]
        if self.serial_number:
            parts.append(f"SN={self.serial_number}")
        if self.vid is not None and self.pid is not None:
            parts.append(f"VID:PID={self.vid:04X}:{self.pid:04X}")
        if self.location:
            parts.append(f"LOC={self.location}")
        return " ".join(parts)


@dataclass
class SerialBindingResolution:
    resolved_port: str
    connection_binding_mode: str
    binding_label: str
    binding_resolved: bool
    binding_match_count: int
    binding_error: Optional[str]
    binding_candidates: List[str]


def enumerate_serial_ports() -> List[SerialPortInfo]:
    ports: List[SerialPortInfo] = []
    for port in list_ports.comports():
        ports.append(
            SerialPortInfo(
                port=port.device,
                serial_number=getattr(port, "serial_number", None),
                vid=getattr(port, "vid", None),
                pid=getattr(port, "pid", None),
                location=getattr(port, "location", None),
                description=getattr(port, "description", None),
                manufacturer=getattr(port, "manufacturer", None),
                hwid=getattr(port, "hwid", None),
            )
        )
    return ports


def build_binding_label(binding, fallback_port: str = "") -> str:
    mode = getattr(binding, "mode", "fixed_port")
    if mode == "fixed_port":
        return f"固定串口 {fallback_port or '--'}"

    serial_number = getattr(binding, "serial_number", None)
    if serial_number:
        return f"SN={serial_number}"

    vid = getattr(binding, "vid", None)
    pid = getattr(binding, "pid", None)
    location = getattr(binding, "location", None)
    description_regex = getattr(binding, "description_regex", None)
    manufacturer_regex = getattr(binding, "manufacturer_regex", None)

    parts: List[str] = []
    if vid is not None and pid is not None:
        parts.append(f"VID:PID={vid:04X}:{pid:04X}")
    if location:
        parts.append(f"@ {location}")
    if description_regex:
        parts.append(f"DESC~/{description_regex}/")
    if manufacturer_regex:
        parts.append(f"MFG~/{manufacturer_regex}/")
    return " ".join(parts) if parts else "未配置指纹"


def resolve_connection(connection) -> SerialBindingResolution:
    binding = getattr(connection, "binding", None)
    port = getattr(connection, "port", "") or ""
    mode = getattr(binding, "mode", "fixed_port") if binding else "fixed_port"
    fallback_to_port = bool(getattr(binding, "fallback_to_port", False)) if binding else False
    label = build_binding_label(binding, fallback_port=port)
    ports = enumerate_serial_ports()

    if mode == "fixed_port":
        matched_ports = [item for item in ports if _normalize(item.port) == _normalize(port)]
        candidates = [item.summary() for item in matched_ports]
        if len(matched_ports) == 1:
            return SerialBindingResolution(
                resolved_port=matched_ports[0].port,
                connection_binding_mode=mode,
                binding_label=label,
                binding_resolved=True,
                binding_match_count=1,
                binding_error=None,
                binding_candidates=candidates,
            )
        return SerialBindingResolution(
            resolved_port="",
            connection_binding_mode=mode,
            binding_label=label,
            binding_resolved=False,
            binding_match_count=0,
            binding_error="missing_fixed_port" if not port else "no_match",
            binding_candidates=candidates,
        )

    binding_error = _validate_fingerprint_binding(binding)
    if binding_error:
        return _build_unresolved_result(mode, label, binding_error, [], port, fallback_to_port)

    matched_ports = _match_ports(binding, ports)
    candidates = [item.summary() for item in matched_ports]

    if len(matched_ports) == 1:
        return SerialBindingResolution(
            resolved_port=matched_ports[0].port,
            connection_binding_mode=mode,
            binding_label=label,
            binding_resolved=True,
            binding_match_count=1,
            binding_error=None,
            binding_candidates=candidates,
        )

    error = "no_match" if len(matched_ports) == 0 else "multiple_matches"
    return _build_unresolved_result(mode, label, error, candidates, port, fallback_to_port)


def _build_unresolved_result(
    mode: str,
    label: str,
    error: str,
    candidates: List[str],
    fallback_port: str,
    fallback_to_port: bool,
) -> SerialBindingResolution:
    if fallback_to_port and fallback_port:
        return SerialBindingResolution(
            resolved_port=fallback_port,
            connection_binding_mode=mode,
            binding_label=label,
            binding_resolved=True,
            binding_match_count=len(candidates),
            binding_error="fallback_to_port",
            binding_candidates=candidates,
        )

    return SerialBindingResolution(
        resolved_port="",
        connection_binding_mode=mode,
        binding_label=label,
        binding_resolved=False,
        binding_match_count=len(candidates),
        binding_error=error,
        binding_candidates=candidates,
    )


def _validate_fingerprint_binding(binding) -> Optional[str]:
    serial_number = getattr(binding, "serial_number", None)
    location = getattr(binding, "location", None)
    vid = getattr(binding, "vid", None)
    pid = getattr(binding, "pid", None)
    description_regex = getattr(binding, "description_regex", None)

    if serial_number:
        return None
    if location:
        return None
    if vid is not None and pid is not None:
        return None
    if description_regex:
        return None
    return "missing_fingerprint"


def _match_ports(binding, ports: List[SerialPortInfo]) -> List[SerialPortInfo]:
    serial_number = _normalize(getattr(binding, "serial_number", None))
    location = _normalize(getattr(binding, "location", None))
    vid = getattr(binding, "vid", None)
    pid = getattr(binding, "pid", None)
    description_regex = getattr(binding, "description_regex", None)
    manufacturer_regex = getattr(binding, "manufacturer_regex", None)

    if serial_number:
        return [item for item in ports if _normalize(item.serial_number) == serial_number]

    if vid is not None and pid is not None and location:
        return [
            item
            for item in ports
            if item.vid == vid and item.pid == pid and _normalize(item.location) == location
        ]

    if vid is not None and pid is not None and description_regex:
        return [
            item
            for item in ports
            if item.vid == vid and item.pid == pid and _regex_match(description_regex, item.description)
        ]

    if description_regex and manufacturer_regex:
        return [
            item
            for item in ports
            if _regex_match(description_regex, item.description)
            and _regex_match(manufacturer_regex, item.manufacturer)
        ]

    if description_regex:
        return [item for item in ports if _regex_match(description_regex, item.description)]

    if location:
        return [item for item in ports if _normalize(item.location) == location]

    return []


def _regex_match(pattern: str, value: Optional[str]) -> bool:
    if not pattern or not value:
        return False
    return re.search(pattern, value, flags=re.IGNORECASE) is not None


def _normalize(value: Optional[str]) -> str:
    return (value or "").strip().lower()
