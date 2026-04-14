# Heat - 自动化控制系统

基于Python的实验室自动化控制系统，支持多设备协同控制、数据监控与报告生成。

## 功能特性

### 设备控制
- **加热器温度控制**：支持宇电AI系列温控仪表（AI-516/518/716/719等）
- **蠕动泵流量控制**：支持LabSmart系列多通道蠕动泵（1-4通道独立控制）
- **多设备并行**：支持多设备同时运行

### 通信协议
- **AIBUS协议**：宇电仪表通信协议（自主实现，不依赖厂商DLL）
- **MODBUS-RTU协议**：标准工业通信协议

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
├── src/                        # 源代码
│   ├── control/               # 程序控制
│   │   └── program_controller.py  # 程序控制器
│   ├── devices/               # 设备驱动
│   │   ├── base_device.py     # 设备基类
│   │   ├── heater.py          # 加热器驱动
│   │   └── peristaltic_pump.py # 蠕动泵驱动
│   ├── protocols/             # 通信协议
│   │   ├── aibus.py           # AIBUS协议
│   │   ├── modbus_rtu.py      # MODBUS-RTU协议
│   │   ├── parameters.py      # 加热器参数定义
│   │   └── pump_params.py     # 蠕动泵参数定义
│   ├── monitor/               # 数据监控
│   ├── reports/               # 报告生成
│   └── utils/                 # 工具函数
├── scripts/                   # 控制脚本
│   ├── simple_control.py      # 简单温度控制
│   ├── dual_heater_control.py # 双加热器控制
│   └── temperature_experiment.py # 温度实验
├── tests/                     # 测试脚本
├── docs/                      # 文档
│   └── presentation.md        # 协议说明文档
└── reference paper/           # 参考文献
```

## 安装

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

## 快速开始

### 1. 测试硬件连接

```bash
python tests/test_hardware.py
```

### 2. 简单温度控制

```bash
python scripts/simple_control.py
```

### 3. 温度实验（带报告生成）

```bash
python scripts/temperature_experiment.py
```

## 配置说明

编辑 `config/system_config.yaml`：

### 加热器配置

```yaml
heaters:
  - device_id: "heater1"
    name: "主加热器"
    connection:
      port: "COM3"        # 串口号
      baudrate: 9600      # 波特率
      address: 1          # 设备地址
    decimal_places: 1     # 小数位数
    safety_limit: 450.0   # 安全限温
```

### 蠕动泵配置

```yaml
pumps:
  - device_id: "pump1"
    name: "蠕动泵"
    connection:
      port: "COM4"        # 串口号
      baudrate: 9600      # 波特率
    slave_address: 1      # MODBUS从站地址
    channels:             # 通道配置
      - channel: 1
        enabled: true
        pump_head: 5      # 泵头型号
        tube_model: 0     # 软管型号
```

## 使用示例

### 加热器控制

```python
from devices import AIHeaterDevice, HeaterConfig

# 创建加热器
config = HeaterConfig(device_id="heater1", connection_params={"port": "COM3"})
heater = AIHeaterDevice(config)
heater.connect()

# 设置温度并启动
heater.set_temperature(100.0)
heater.start()

# 读取数据
data = heater.read_data()
print(f"当前温度: {data.pv}°C")

# 停止并断开
heater.stop()
heater.disconnect()
```

### 蠕动泵控制

```python
from devices import LabSmartPumpDevice, PeristalticPumpConfig, PumpChannelConfig
from protocols import PumpRunMode, PumpDirection

# 创建蠕动泵
config = PeristalticPumpConfig(
    device_id="pump1",
    connection_params={"port": "COM4"},
    channels=[PumpChannelConfig(channel=1, enabled=True)]
)
pump = LabSmartPumpDevice(config)
pump.connect()

# 设置流速并启动
pump.set_flow_rate(1, 50.0)  # 50 mL/min
pump.set_direction(1, PumpDirection.CLOCKWISE)
pump.start_channel(1)

# 停止
pump.stop_channel(1)
pump.disconnect()
```

### 程序控制（温度+流量联动）

```python
from control import ProgramController, ProgramStep, StepType

# 创建程序控制器
controller = ProgramController(heater, pump)

# 创建简单程序：加热到100°C，保持5分钟，期间泵以50mL/min运行
program = controller.create_simple_program(
    temperature=100.0,
    hold_time=300,
    pump_channel=1,
    pump_flow_rate=50.0
)

# 运行程序
controller.load_program(program)
controller.start()
```

## 扩展新设备

1. 继承 `BaseDevice` 基类

```python
from devices.base_device import BaseDevice, DeviceConfig, DeviceStatus

class NewDevice(BaseDevice):
    def connect(self) -> bool:
        # 实现连接逻辑
        self._status = DeviceStatus.CONNECTED
        return True
    
    def disconnect(self) -> bool:
        # 实现断开逻辑
        return True
    
    def read_data(self):
        # 实现数据读取
        return DeviceData(...)
```

2. 添加到配置文件

3. 在主程序中调用

## 技术栈

| 技术 | 用途 |
|------|------|
| Python 3.8+ | 主要开发语言 |
| pyserial | 串口通信 |
| matplotlib | 数据可视化 |
| PyYAML | 配置管理 |
| struct | 二进制数据处理 |

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

## 许可证

MIT License

## 贡献

欢迎提交 Issue 和 Pull Request！

## 联系方式

- Gitee: https://gitee.com/wh158958
- GitHub: https://github.com/WH15958
