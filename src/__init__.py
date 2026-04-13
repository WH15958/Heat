"""
自动化控制系统

提供设备控制、数据监控和报告生成的完整解决方案。
"""

__version__ = "1.0.0"
__author__ = "Automation System"

from .devices import (
    BaseDevice,
    DeviceConfig,
    DeviceData,
    DeviceInfo,
    DeviceStatus,
    DeviceType,
    AIHeaterDevice,
    HeaterConfig,
    HeaterData,
)

from .protocols import (
    AIBUSProtocol,
    AIBUSResponse,
    ParameterCode,
    ControlMode,
    RunStatus,
)

from .monitor import (
    DataMonitor,
    DataPoint,
    AlarmRule,
)

from .reports import (
    ReportGenerator,
)

from .utils import (
    ConfigManager,
    SystemConfig,
    setup_logging,
    get_logger,
)

__all__ = [
    '__version__',
    '__author__',
    'BaseDevice',
    'DeviceConfig',
    'DeviceData',
    'DeviceInfo',
    'DeviceStatus',
    'DeviceType',
    'AIHeaterDevice',
    'HeaterConfig',
    'HeaterData',
    'AIBUSProtocol',
    'AIBUSResponse',
    'ParameterCode',
    'ControlMode',
    'RunStatus',
    'DataMonitor',
    'DataPoint',
    'AlarmRule',
    'ReportGenerator',
    'ConfigManager',
    'SystemConfig',
    'setup_logging',
    'get_logger',
]
