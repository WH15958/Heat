# Heat - 自动化控制系统

基于Python的实验室自动化控制系统，支持多设备协同控制、数据监控与报告生成。

## 项目进度

| 模块 | 状态 | 说明 |
|------|------|------|
| 加热器控制 | ✅ 完成 | AI-516/518/716/719 温控仪表 |
| 蠕动泵控制 | ✅ 完成 | LabSmart 多通道蠕动泵 |
| 安全机制 | ✅ 完成 | 串口资源管理、紧急停止、通道隔离 |
| 程序控制 | ✅ 完成 | 温度+流量联动 |
| 报告生成 | ✅ 完成 | HTML报告 + 温度曲线 |

## 功能特性

### 设备控制
- **加热器温度控制**：支持宇电AI系列温控仪表（AI-516/518/716/719等）
- **蠕动泵流量控制**：支持LabSmart系列多通道蠕动泵（1-4通道独立控制）
- **多设备并行**：支持多设备同时运行

### 通信协议
- **AIBUS协议**：宇电仪表通信协议（自主实现，不依赖厂商DLL）
- **MODBUS-RTU协议**：标准工业通信协议

### 安全机制 ⭐新增
- **串口资源管理**：进程锁文件、强制释放、看门狗线程
- **设备安全基类**：状态监控、异常隔离、紧急停止
- **通道隔离**：单通道异常不影响其他通道
- **命令队列**：串行化串口操作，避免竞争

### 运行模式（蠕动泵）
- 流量模式：设置流速持续运行
- 定时定量：设定时间后定量分装
- 定时定速：设定时间后定速运行
- 定量定速：设定总量后定速运行

### 程序控制
- 温度触发泵启动
- 多步骤程序执行
- 自动化实验流程

### 其他功能
- 实时数据采集与存储
- HTML格式报告与温度曲线图
- 模块化设计，易于扩展新设备

## 目录结构

```
Heat/
├── config/                     # 配置文件
│   └── system_config.yaml      # 系统配置
├── context/                    # 项目上下文 ⭐新增
│   └── PROJECT_CONTEXT.md      # AI记忆库+交接手册
├── src/                        # 源代码
│   ├── control/               # 程序控制
│   │   └── program_controller.py
│   ├── devices/               # 设备驱动
│   │   ├── base_device.py     # 设备基类
│   │   ├── heater.py          # 加热器驱动
│   │   ├── peristaltic_pump.py # 蠕动泵驱动(基础)
│   │   └── safe_pump.py       # 蠕动泵驱动(安全增强) ⭐新增
│   ├── protocols/             # 通信协议
│   │   ├── aibus.py           # AIBUS协议
│   │   ├── modbus_rtu.py      # MODBUS-RTU协议
│   │   ├── parameters.py      # 加热器参数定义
│   │   └── pump_params.py     # 蠕动泵参数定义
│   ├── monitor/               # 数据监控
│   ├── reports/               # 报告生成
│   └── utils/                 # 工具函数
│       ├── config.py          # 配置管理
│       ├── serial_manager.py  # 串口资源管理 ⭐新增
│       └── device_safety.py   # 设备安全基类 ⭐新增
├── scripts/                   # 控制脚本
│   ├── simple_control.py      # 简单温度控制
│   ├── dual_heater_control.py # 双加热器控制
│   ├── heater_pump_integration.py  # 加热器+蠕动泵联动
│   ├── heater_pump_safe.py    # 安全联动脚本 ⭐新增
│   ├── test_pump_only.py      # 蠕动泵测试
│   └── test_pump_safe.py      # 安全蠕动泵测试 ⭐新增
├── tests/                     # 测试脚本
│   └── diagnose_pump.py       # 诊断工具
├── docs/                      # 文档
│   └── presentation.md        # 协议说明文档
└── reference paper/           # 参考文献
```

## 安装

### 方式一：Conda 环境（推荐）

```bash
# 克隆仓库
git clone https://gitee.com/wh158958/heat.git
cd heat

# 从 environment.yml 创建环境
conda env create -f environment.yml

# 激活环境
conda activate heat
```

### 方式二：pip + venv

```bash
# 克隆仓库
git clone https://gitee.com/wh158958/heat.git
cd heat

# 创建虚拟环境
python -m venv venv
venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt
```

### 可选依赖

```bash
# Windows 强制释放串口
pip install pywin32
```

## 快速开始

### 1. 测试蠕动泵连接

```bash
python scripts/test_pump_safe.py --port COM10 --force
```

### 2. 运行加热器+蠕动泵联动实验

```bash
python scripts/heater_pump_safe.py --heater-ports COM7 COM9 --pump-port COM10 --force
```

### 3. 简单温度控制

```bash
python scripts/simple_control.py
```

## 配置说明

编辑 `config/system_config.yaml`：

### 加热器配置

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
```

### 蠕动泵配置

```yaml
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

## 使用示例

### 安全蠕动泵控制（推荐）

```python
from devices.safe_pump import SafePumpDevice, ChannelTask
from devices.peristaltic_pump import PeristalticPumpConfig, PumpChannelConfig
from protocols.pump_params import PumpRunMode, PumpDirection

config = PeristalticPumpConfig(
    device_id="pump1",
    connection_params={"port": "COM10", "baudrate": 9600, "parity": "N"},
    channels=[PumpChannelConfig(channel=1, enabled=True)]
)

with SafePumpDevice(config) as pump:
    pump.connect(force=True)
    
    task = ChannelTask(
        channel=1,
        volume=10.0,
        flow_rate=20.0,
        mode=PumpRunMode.QUANTITY_SPEED
    )
    pump.run_channel_task(task)
    
    pump.stop_all_channels()
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

### 加热器+蠕动泵联动

```python
from scripts.heater_pump_safe import SafeExperiment

experiment = SafeExperiment(
    heater_ports=["COM7", "COM9"],
    pump_port="COM10",
    target_temp=35.0,
    pump_trigger_temp=30.0,
    heat_duration=300,
    hold_duration=300,
    pump_volume=10.0,
    pump_flow_rate=20.0,
    force=True
)

experiment.run()
```

## 安全机制

### 串口资源管理

```python
from utils.serial_manager import get_serial_manager, SerialPortForceRelease

manager = get_serial_manager()

# 获取串口（强制模式）
manager.acquire_port("COM10", force=True)

# 强制释放残留串口
SerialPortForceRelease.force_release("COM10")

# 清理所有串口
manager.cleanup()
```

### 紧急停止

```python
from utils.device_safety import get_safety_manager

manager = get_safety_manager()

# 注册紧急停止回调
manager.register_emergency_stop(my_device.emergency_stop)

# 触发全局紧急停止
manager.emergency_stop_all()
```

## 扩展新设备

1. 继承 `BaseDevice` 或 `SafeDevice` 基类

```python
from utils.device_safety import SafeDevice, DeviceState

class NewDevice(SafeDevice):
    def __init__(self, config):
        super().__init__(device_id=config.device_id)
        self._config = config
    
    def connect(self, force: bool = False) -> bool:
        self._set_state(DeviceState.INITIALIZING)
        # 实现连接逻辑
        self._set_state(DeviceState.RUNNING)
        return True
    
    def disconnect(self) -> bool:
        self._set_state(DeviceState.STOPPING)
        # 实现断开逻辑
        self._set_state(DeviceState.DISPOSED)
        return True
    
    def emergency_stop(self):
        # 实现紧急停止
        pass
```

2. 添加到配置文件

3. 在主程序中调用

## 技术栈

| 技术 | 用途 |
|------|------|
| Python 3.8+ | 主要开发语言 |
| pyserial | 串口通信 |
| pyyaml | 配置管理 |
| psutil | 进程管理 |
| matplotlib | 数据可视化 |
| struct | 二进制数据处理 |
| threading | 多线程控制 |
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

## 贡献

欢迎提交 Issue 和 Pull Request！

## 联系方式

- Gitee: https://gitee.com/wh158958
- GitHub: https://github.com/WH15958
