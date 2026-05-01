# Heat - 自动化控制系统

基于Python的实验室自动化控制系统，支持多设备协同控制、数据记录、Web远程监控与实验自动化。

## 项目进度

| 模块 | 状态 | 说明 |
|------|------|------|
| 加热器控制 | ✅ 完成 | AI-708 温控器 |
| 蠕动泵控制 | ✅ 完成 | LabSmart 多通道蠕动泵 |
| 程序控制 | ✅ 完成 | 温度+流量联动（asyncio架构） |
| 数据记录 | ✅ 完成 | CSVDataLogger（纯同步，定时flush，支持温度+泵数据） |
| 报告生成 | ✅ 完成 | HTML报告 + 温度曲线图 + 泵流量曲线图 + XSS防护 |
| 串口资源管理 | ✅ 完成 | 进程锁文件、强制释放、看门狗心跳 |
| Web远程控制 | ✅ 完成 | FastAPI + Vue 3 + WebSocket 实时推送 + CORS安全 |
| 实验自动化 | ✅ 完成 | YAML实验定义 + 状态机引擎 + 日志追溯 |
| 实验日志 | ✅ 完成 | 实时日志推送 + JSON持久化 + 历史记录查询 |
| 代码质量审查 | ✅ 完成 | v2.5 全面审查修复（20+问题，含安全/竞态/封装） |
| 前端稳定性增强 | ✅ 完成 | v2.6 温度显示修复、日志保存开关、历史记录删除、浏览器缓存处理 |
| 蠕动泵模式修复 | ✅ 完成 | v2.7 运行模式参数规则、流速单位限制、软管型号验证、定时定量自动计算、前端参数持久化 |
| 主控制器 | ✅ 完成 | main.py 支持加热器+蠕动泵交互控制 |

## 核心架构

```
Vue 3 前端（仪表盘/控制面板/实验页面）
    │ WebSocket + REST API
    ▼
FastAPI 服务层（run_in_executor 桥接同步设备）
    │
    ▼
实验自动化引擎（YAML → 状态机 → 步骤执行器）
    │
    ▼
设备驱动层（heater.py / peristaltic_pump.py，纯同步无线程）
    │
    ▼
协议层（AIBUS / MODBUS-RTU）
    │
    ▼
串口（单线程访问 → 100% 稳定）
```

**关键约束：串口驱动必须是纯同步、无线程架构。**

## 功能特性

### 设备控制
- **加热器温度控制**：支持宇电AI系列温控仪表（AI-516/518/716/719等）
- **蠕动泵流量控制**：支持LabSmart系列多通道蠕动泵（1-4通道独立控制）
- **多设备并行**：不同串口上的设备可同时运行

### Web远程控制
- **实时仪表盘**：温度曲线 + 流量曲线实时显示（1Hz刷新）
- **设备控制面板**：4通道独立控制，4种泵模式选择
- **实验自动化页面**：YAML实验流程可视化，支持启动/暂停/恢复/停止
- **WebSocket推送**：实时数据无需刷新页面

### 实验自动化
- **YAML实验定义**：声明式定义实验步骤
- **9种动作类型**：set_temperature, start_heater, stop_heater, set_flow_rate, start_pump, stop_pump, wait, wait_temperature, wait_time
- **状态机引擎**：IDLE → RUNNING → PAUSED/COMPLETED/FAILED/STOPPED
- **暂停/恢复**：实验运行中可随时暂停恢复
- **日志保存开关**：启动实验时可选择是否保存日志到文件
- **历史记录管理**：查看、删除、导出实验历史记录

### 通信协议
- **AIBUS协议**：宇电仪表通信协议（自主实现，不依赖厂商DLL）
- **MODBUS-RTU协议**：标准工业通信协议

### 安全机制
- **串口资源管理**：进程锁文件、强制释放、看门狗线程
- **紧急停止**：信号处理器 + atexit 回调确保资源释放
- **异常隔离**：单设备异常不影响其他设备
- **路径遍历防护**：Web API参数校验
- **CORS安全**：限定允许的来源域名
- **XSS防护**：报告生成器HTML转义
- **设备操作安全**：连接状态检查 + 返回值校验，防止设备以错误参数运转

### 数据记录
- **CSVDataLogger**：纯同步数据记录，无后台线程
- **定时flush**：1秒间隔自动刷新，减少I/O开销
- **双缓存保存**：同时写入 CSV 文件和内存，支持报告生成
- **多设备支持**：按 device_id 分组记录数据
- **内存限制**：每设备最多10万数据点，防止内存溢出

### 运行模式（蠕动泵）
- 流量模式：设置流速持续运行
- 定时定量：设定时间和分装液量，流速自动计算
- 定时定速：设定时间和流速
- 定量定速：设定分装液量和流速

> **重要**：流速只能在流量模式下设置，非流量模式启动时会自动先切到流量模式设流速再切回目标模式。定时定量模式下流速由泵自动计算，前端显示为只读。流速单位仅支持 mL/min 和 RPM。

## 目录结构

```
Heat/
├── config/                     # 配置文件
│   └── system_config.yaml
├── context/                    # 项目上下文
│   └── PROJECT_CONTEXT.md      # AI记忆库+交接手册
├── docs/                       # 文档
│   ├── user_guide.md           # 用户使用教程
│   ├── developer_guide.md      # 开发者维护教程
│   ├── lock_cleanup_usage.md   # 锁文件清理说明
│   └── presentation.md         # 演示文档
├── experiments/                # 实验定义（YAML）
│   ├── chemical_synthesis_A.yaml
│   └── simple_heat_test.yaml
├── frontend/                   # Vue 3 前端
│   ├── src/
│   │   ├── api/devices.ts      # REST API封装
│   │   ├── composables/useWebSocket.ts
│   │   ├── views/
│   │   │   ├── Dashboard.vue   # 实时仪表盘
│   │   │   ├── ControlPanel.vue # 设备控制
│   │   │   ├── ExperimentPage.vue # 实验自动化
│   │   │   └── HistoryPage.vue   # 实验历史记录
│   │   └── router/index.ts
│   └── package.json
├── src/                        # 源代码
│   ├── control/               # 程序控制
│   │   └── program_controller.py
│   ├── devices/               # 设备驱动（纯同步，无线程）
│   │   ├── base_device.py
│   │   ├── heater.py
│   │   └── peristaltic_pump.py
│   ├── experiment/            # 实验自动化引擎
│   │   ├── actions.py         # 动作定义
│   │   ├── engine.py          # 状态机引擎
│   │   ├── executor.py        # 步骤执行器
│   │   ├── experiment_logger.py # 实验日志记录器
│   │   └── parser.py          # YAML解析器
│   ├── protocols/             # 通信协议
│   │   ├── aibus.py
│   │   ├── modbus_rtu.py
│   │   ├── parameters.py
│   │   └── pump_params.py
│   ├── reports/               # 报告生成
│   │   └── report_generator.py
│   ├── web/                   # Web服务层
│   │   ├── app.py             # FastAPI入口
│   │   ├── device_manager.py  # 设备管理器
│   │   └── api/
│   │       ├── devices.py     # 设备REST API
│   │       ├── ws.py          # WebSocket推送
│   │       └── experiments.py # 实验管理API
│   └── utils/                 # 工具函数
│       ├── config.py
│       ├── serial_manager.py
│       ├── csv_logger.py
│       └── logger.py
├── scripts/                   # 实验脚本
├── tests/                     # 测试脚本
├── run_server.py              # Web服务器启动入口
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

### Web 前端构建

```bash
cd frontend
npm install
npm run build
```

构建产物自动输出到 `src/web/static/`，Web服务器自动提供静态文件。

### 可选依赖

```bash
pip install pywin32    # Windows 强制释放串口
pip install psutil     # 进程管理
```

## 快速开始

### 1. 启动 Web 服务器

```bash
python run_server.py
```

浏览器访问 http://localhost:8000

### 2. 测试设备连接

```bash
python scripts/test_connections.py
```

### 3. 运行化学合成实验

```bash
python scripts/chemical_synthesis_experiment.py --heater1-port COM7 --heater2-port COM9 --pump-port COM10 --force
```

### 4. 纯加热实验

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
    connection_params={"port": "COM10", "baudrate": 19200, "parity": "E"},
    channels=[PumpChannelConfig(channel=1, enabled=True, tube_model=13)]
)

pump = LabSmartPumpDevice(config)
pump.connect()

# 流量模式
pump.set_direction(1, PumpDirection.CLOCKWISE)
pump.set_run_mode(1, PumpRunMode.FLOW_MODE)
pump.set_flow_rate(1, 5.0)
pump.start_channel(1)

# 定时定量模式（流速自动计算）
pump.set_run_mode(1, PumpRunMode.FLOW_MODE)
pump.set_flow_rate(1, 5.0)  # 先在流量模式设流速
pump.set_run_mode(1, PumpRunMode.TIME_QUANTITY)  # 切到定时定量
pump.set_run_time(1, 60.0)
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

pv, sv = heater.get_temperature()
print(f"当前温度: {pv}°C")

heater.stop()
heater.disconnect()
```

### 实验自动化（YAML定义）

```yaml
name: simple_heat_test
description: 简单加热测试
steps:
  - name: 设置温度
    action: set_temperature
    params:
      device_id: heater1
      temperature: 80.0

  - name: 启动加热
    action: start_heater
    params:
      device_id: heater1

  - name: 等待温度达标
    action: wait_temperature
    params:
      device_id: heater1
      target: 80.0
      tolerance: 2.0
      timeout: 600

  - name: 停止加热
    action: stop_heater
    params:
      device_id: heater1
```

通过Web界面或API启动实验：

```bash
curl -X POST http://localhost:8000/api/experiments/simple_heat_test.yaml/start
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
      baudrate: 19200
      parity: "E"
    slave_address: 1
    channels:
      - channel: 1
        enabled: true
        tube_model: 13
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
| FastAPI | Web服务框架 |
| uvicorn | ASGI服务器 |
| websockets | WebSocket支持 |
| Vue 3 + TypeScript | Web前端 |
| Element Plus | UI组件库 |
| ECharts | 数据可视化 |
| matplotlib | 报告图表 |
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

## 教程文档

| 文档 | 面向 | 说明 |
|------|------|------|
| [用户使用教程](docs/user_guide.md) | 实验操作人员 | 自动化实验操作指南 |
| [开发者维护教程](docs/developer_guide.md) | 开发者/AI | 项目开发与维护指南 |

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
