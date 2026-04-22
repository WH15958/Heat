# Heat - 自动化控制系统

基于Python的实验室自动化控制系统，支持多设备协同控制、数据记录与报告生成。

## 项目进度

| 模块 | 状态 | 说明 |
|------|------|------|
| 加热器控制 | ✅ 完成 | AI-708 温控器 |
| 蠕动泵控制 | ✅ 完成 | LabSmart 多通道蠕动泵 |
| 程序控制 | ✅ 完成 | 温度+流量联动 |
| 数据记录 | ✅ 完成 | CSVDataLogger（纯同步，无后台线程） |
| 报告生成 | ✅ 完成 | HTML报告 + 温度曲线图 |
| 串口资源管理 | ✅ 完成 | 进程锁文件、强制释放、看门狗 |

## 核心架构

```
程序控制器（1个线程，顺序调度）
    ↓
加热器驱动（无线程）→ 串口A
泵驱动 LabSmartPumpDevice（无线程）→ 串口B
    ↓
串口（单线程访问 → 100% 稳定）
```

**关键约束：串口驱动必须是纯同步、无线程架构。** 串口是半双工通信，同一时间只能有一个指令。心跳、状态刷新、任务调度全部放在上层（脚本/GUI）实现。

## 功能特性

### 设备控制
- **加热器温度控制**：支持宇电AI系列温控仪表（AI-516/518/716/719等）
- **蠕动泵流量控制**：支持LabSmart系列多通道蠕动泵（1-4通道独立控制）
- **多设备并行**：不同串口上的设备可同时运行

### 通信协议
- **AIBUS协议**：宇电仪表通信协议（自主实现，不依赖厂商DLL）
- **MODBUS-RTU协议**：标准工业通信协议

### 安全机制
- **串口资源管理**：进程锁文件、强制释放、看门狗线程
- **紧急停止**：信号处理器 + atexit 回调确保资源释放
- **异常隔离**：单设备异常不影响其他设备

### 数据记录
- **CSVDataLogger**：纯同步数据记录，无后台线程
- **手动按需记录**：主线程直接调用，无串口竞争
- **双缓存保存**：同时写入 CSV 文件和内存，支持报告生成
- **多设备支持**：按 device_id 分组记录数据

### 运行模式（蠕动泵）
- 流量模式：设置流速持续运行
- 定时定量：设定时间后定量分装
- 定时定速：设定时间后定速运行
- 定量定速：设定总量后定速运行

### 程序控制
- 温度触发泵启动
- 多步骤程序执行
- 自动化实验流程

## 目录结构

```
Heat/
├── config/                     # 配置文件
│   └── system_config.yaml
├── context/                    # 项目上下文
│   └── PROJECT_CONTEXT.md      # AI记忆库+交接手册
├── src/                        # 源代码
│   ├── control/               # 程序控制
│   │   └── program_controller.py
│   ├── devices/               # 设备驱动（纯同步，无线程）
│   │   ├── base_device.py     # 设备基类
│   │   ├── heater.py          # 加热器驱动
│   │   └── peristaltic_pump.py # 蠕动泵驱动
│   ├── protocols/             # 通信协议
│   │   ├── aibus.py           # AIBUS协议
│   │   ├── modbus_rtu.py      # MODBUS-RTU协议
│   │   ├── parameters.py      # 加热器参数定义
│   │   └── pump_params.py     # 泵参数定义
│   ├── reports/               # 报告生成
│   │   └── report_generator.py
│   └── utils/                 # 工具函数
│       ├── config.py          # 配置管理
│       ├── serial_manager.py  # 串口资源管理
│       ├── csv_logger.py      # CSV数据记录
│       └── logger.py          # 日志工具
├── scripts/                   # 实验脚本
│   ├── chemical_synthesis_experiment.py  # 化学合成实验
│   ├── heater_only_experiment.py         # 纯加热实验
│   ├── temperature_experiment.py         # 温度控制实验
│   ├── test_connections.py               # 设备连接测试
│   └── cleanup_locks.py                  # 锁文件清理
├── tests/                     # 测试脚本
├── docs/                      # 文档
└── output/                    # 实验输出（报告/图表）
```

## 安装

### 方式一：Conda 环境（推荐）

```bash
git clone https://gitee.com/wh158958/heat.git
cd heat
conda env create -f environment.yml
conda activate heat
```

### 方式二：pip + venv

```bash
git clone https://gitee.com/wh158958/heat.git
cd heat
python -m venv venv
venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

### 可选依赖

```bash
pip install pywin32    # Windows 强制释放串口
pip install psutil     # 进程管理
```

## 快速开始

### 1. 测试设备连接

```bash
python scripts/test_connections.py
```

### 2. 运行化学合成实验

```bash
python scripts/chemical_synthesis_experiment.py --heater1-port COM7 --heater2-port COM9 --pump-port COM10 --force
```

### 3. 纯加热实验

```bash
python scripts/heater_only_experiment.py
```

## 使用示例

### 蠕动泵控制

```python
from devices.peristaltic_pump import LabSmartPumpDevice, PeristalticPumpConfig, PumpChannelConfig
from protocols.pump_params import PumpRunMode, PumpDirection

config = PeristalticPumpConfig(
    device_id="pump1",
    connection_params={"port": "COM10", "baudrate": 9600, "parity": "N"},
    channels=[PumpChannelConfig(channel=1, enabled=True)]
)

pump = LabSmartPumpDevice(config)
pump.connect()

pump.set_direction(1, PumpDirection.CLOCKWISE)
pump.set_run_mode(1, PumpRunMode.QUANTITY_SPEED)
pump.set_flow_rate(1, 20.0)
pump.set_dispense_volume(1, 10.0)
pump.start_channel(1)

pump.stop_all()
pump.disconnect()
```

### 加热器控制

```python
from devices.heater import AIHeaterDevice, HeaterConfig

config = HeaterConfig(device_id="heater1", connection_params={"port": "COM7"})
heater = AIHeaterDevice(config)
heater.connect()

heater.set_temperature(100.0)
heater.start()

pv, sv = heater.read_temperature()
print(f"当前温度: {pv}°C")

heater.stop()
heater.disconnect()
```

### 数据记录

```python
from utils import CSVDataLogger

logger = CSVDataLogger("output", "experiment")
logger.start()

logger.record(device_id="heater1", pv=25.3, sv=30.0)
logger.record(device_id="heater2", pv=28.1, sv=30.0)

logger.close()
```

### 串口资源管理

```python
from utils import get_serial_manager, cleanup_all_serial_ports

manager = get_serial_manager()
manager.acquire_port("COM10", force=True)

manager.release_port("COM10")
cleanup_all_serial_ports()
```

## 配置说明

编辑 `config/system_config.yaml`：

```yaml
heaters:
  - device_id: "heater1"
    name: "主加热器"
    connection:
      port: "COM7"
      baudrate: 9600
      address: 1
    decimal_places: 1
    safety_limit: 450.0

pumps:
  - device_id: "pump1"
    name: "蠕动泵"
    connection:
      port: "COM10"
      baudrate: 9600
      parity: "N"
    slave_address: 1
    channels:
      - channel: 1
        enabled: true
        pump_head: 5
        tube_model: 0
```

## 扩展新设备

1. 继承 `BaseDevice` 基类

```python
from devices.base_device import BaseDevice, DeviceConfig

class NewDeviceConfig(DeviceConfig):
    custom_param: str = "default"

class NewDevice(BaseDevice):
    def __init__(self, config: NewDeviceConfig):
        super().__init__(config)
        self._config = config
    
    def connect(self) -> bool:
        return self._do_connect()
    
    def disconnect(self) -> bool:
        return self._do_disconnect()
    
    def emergency_stop(self):
        self._do_stop()
```

2. 添加到配置文件
3. 在脚本中调用

**注意：驱动必须是纯同步、无线程架构。** 不要在驱动内部开线程。

## 技术栈

| 技术 | 用途 |
|------|------|
| Python 3.10+ | 主要开发语言 |
| pyserial | 串口通信 |
| pyyaml | 配置管理 |
| psutil | 进程管理 |
| matplotlib | 数据可视化 |
| struct | 二进制数据处理 |
| dataclass | 数据结构定义 |

## 通信协议

### AIBUS协议（宇电仪表）
- 读取PV（测量值）、SV（设定值）、MV（输出值）
- 设定目标温度
- 设备运行控制（启动/停止/保持）

### MODBUS-RTU协议（蠕动泵）
- 功能码：03(读)、06(写单寄存器)、16(写多寄存器)
- CRC-16校验
- 支持浮点数和整数数据类型

详见：[docs/presentation.md](docs/presentation.md)

## 项目上下文

新对话开始时，请先阅读项目上下文：

```
@context/PROJECT_CONTEXT.md
```

## 仓库地址

| 平台 | 地址 |
|------|------|
| Gitee (主) | https://gitee.com/wh158958/heat |
| GitHub (镜像) | https://github.com/WH15958/Heat |

## 许可证

MIT License
