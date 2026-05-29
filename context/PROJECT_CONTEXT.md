# PROJECT_CONTEXT.md

> **项目级 AI 记忆库 + 开发者交接手册**
>
> 最后更新：2026-05-28
版本：v2.13

---

## 目录

1. [项目定位](#1-项目定位)
2. [整体架构原则](#2-整体架构原则)
3. [通用编码规范](#3-通用编码规范)
4. [硬件开发统一规则](#4-硬件开发统一规则)
5. [已开发设备](#5-已开发设备)
6. [历史重大问题与解决方案](#6-历史重大问题与解决方案)
7. [AI 开发指南](#7-ai-开发指南)
8. [待开发与待确认](#8-待开发与待确认)

---

## 1. 项目定位

### 1.1 项目概述

| 项目名称 | Heat - 温度控制与流体输送实验系统 |
|---------|--------------------------------|
| 项目类型 | 工业自动化 + Python 硬件控制 |
| 核心功能 | 多设备联动控制、温度监控、流体分装 |
| 开发环境 | Windows + Python 3.10 + Trae IDE |
| Conda 环境 | `heat` |
| 通信协议 | MODBUS RTU (RS232/RS485) |

### 1.2 核心目标

- **实验自动化**：加热器 + 蠕动泵联动控制
- **安全可靠**：工业级异常处理、紧急停止保障
- **可扩展**：新设备接入只需配置 + 协议实现
- **可维护**：配置与逻辑分离、模块化设计

### 1.3 项目仓库

| 平台 | 地址 |
|------|------|
| Gitee (主) | `https://gitee.com/wh158958/heat` |
| GitHub (镜像) | `https://github.com/WH15958/Heat` |

---

## 2. 整体架构原则

### 2.1 分层架构

```
┌─────────────────────────────────────────────────────────────┐
│                 frontend/ (Web前端 - Vue 3)                   │
│   Dashboard.vue, ControlPanel.vue, ExperimentPage.vue       │
│   HistoryPage.vue                                            │
│   职责：数据可视化仪表盘、设备控制面板、实验自动化界面、历史记录 │
└─────────────────────────────────────────────────────────────┘
                              │ WebSocket + REST API
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                  web/ (Web服务层 - FastAPI)                    │
│   app.py, device_manager.py, api/devices.py, api/ws.py      │
│   职责：HTTP/WebSocket接口，桥接同步设备与异步框架             │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│               experiment/ (实验自动化引擎)                      │
│   parser.py, engine.py, executor.py, actions.py             │
│   experiment_logger.py                                      │
│   职责：YAML实验定义解析、状态机调度、步骤执行、日志记录        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    scripts/ (实验脚本层)                      │
│   chemical_synthesis_experiment.py, heater_only_experiment  │
│   职责：实验流程编排，不涉及设备细节                        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                  control/ (程序控制层)                        │
│         program_controller.py                                │
│         职责：实验步骤调度（单线程顺序执行）                    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    devices/ (设备驱动层)                      │
│         heater.py, peristaltic_pump.py                       │
│         职责：设备控制逻辑，封装通信细节（纯同步，无线程）       │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    protocols/ (协议层)                        │
│         aibus.py, modbus_rtu.py, pump_params.py             │
│         职责：通信协议实现，寄存器映射                           │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    utils/ (工具层)                            │
│         serial_manager.py, config.py, csv_logger.py         │
│         职责：资源管理、配置解析、数据记录                        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    config/ (配置层)                           │
│         system_config.yaml                                   │
│         职责：设备参数、串口配置、实验参数                        │
└─────────────────────────────────────────────────────────────┘
```

**关键架构约束：串口驱动必须是纯同步、无线程架构**

串口是半双工通信，同一时间只能有一个指令在执行。正确的访问模式：

```
程序控制器（1个线程，顺序调度）
    ↓
加热器驱动（无线程）→ 串口A
泵驱动 LabSmartPumpDevice（无线程）→ 串口B
    ↓
串口（单线程访问 → 100% 稳定）
```

**严禁在串口驱动内部开线程！** 心跳、状态刷新、任务调度全部放在上层（脚本/GUI）实现。

### 2.2 核心设计原则

| 原则 | 说明 |
|------|------|
| **配置与逻辑分离** | 实验脚本改动不触及设备配置，新设备只需改配置和协议 |
| **设备抽象** | 所有设备继承 `BaseDevice`，统一接口 |
| **安全优先** | 所有设备必须实现 `emergency_stop()` |
| **资源管理** | 串口必须通过 `SerialPortManager` 管理 |
| **异常隔离** | 单设备/通道异常不影响其他设备/通道 |

### 2.3 目录结构

```
Heat/
├── config/
│   └── system_config.yaml      # 系统配置
├── context/
│   └── PROJECT_CONTEXT.md      # AI记忆库+交接手册
├── docs/
│   ├── images/                 # 文档图片
│   ├── user_guide.md           # 用户使用教程
│   ├── developer_guide.md      # 开发者维护教程
│   ├── lock_cleanup_usage.md   # 锁文件清理说明
│   └── presentation.md         # 演示文档
├── experiments/
│   ├── chemical_synthesis_A.yaml  # 化学合成实验定义
│   ├── simple_heat_test.yaml      # 简单加热测试定义
│   ├── cspbbr3_baseline.yaml      # CsPbBr3基线实验（metadata示例）
│   └── pump_four_channel_demo.yaml # 蠕动泵四通道四模式演示
├── frontend/
│   ├── src/
│   │   ├── api/devices.ts        # REST API封装
│   │   ├── composables/useWebSocket.ts  # WebSocket封装
│   │   ├── router/index.ts       # Vue Router
│   │   └── views/
│   │       ├── Dashboard.vue     # 实时仪表盘
│   │       ├── ControlPanel.vue  # 设备控制面板
│   │       ├── ExperimentPage.vue # 实验自动化页面+实时日志
│   │       └── HistoryPage.vue   # 实验历史记录
│   └── package.json
├── scripts/
│   └── cleanup_locks.py                  # 锁文件清理
├── src/
│   ├── control/
│   │   └── program_controller.py  # 程序控制器（单线程调度）
│   ├── devices/
│   │   ├── base_device.py          # 设备基类
│   │   ├── heater.py               # 加热器驱动（纯同步）
│   │   └── peristaltic_pump.py     # 蠕动泵驱动（纯同步）
│   ├── experiment/
│   │   ├── actions.py              # 实验动作定义
│   │   ├── engine.py               # 实验状态机引擎
│   │   ├── executor.py             # 步骤执行器
│   │   ├── experiment_logger.py    # 实验日志记录器
│   │   └── parser.py               # YAML实验解析器
│   ├── monitor/
│   │   └── __init__.py             # 已废弃DataMonitor
│   ├── protocols/
│   │   ├── aibus.py                # AI-BUS协议
│   │   ├── modbus_rtu.py           # MODBUS RTU协议
│   │   ├── parameters.py           # 加热器参数定义
│   │   └── pump_params.py          # 泵参数定义
│   ├── reports/
│   │   └── report_generator.py     # 报告生成器
│   ├── science/
│   │   ├── sample_id.py            # sample_id/batch_id/condition_id 生成
│   │   └── sample_record.py        # samples.csv 写入（目录创建、header、去重、UTF-8）
│   ├── web/
│   │   ├── app.py                  # FastAPI应用入口
│   │   ├── device_manager.py       # 设备管理器
│   │   └── api/
│   │   ├── api/devices.py          # 设备REST API
│   │       ├── ws.py               # WebSocket实时推送
│   │       └── experiments.py      # 实验管理API + 日志API
│   └── utils/
│       ├── config.py               # 配置管理
│       ├── serial_manager.py       # 串口资源管理
│       ├── csv_logger.py           # CSV数据记录
│       └── logger.py               # 日志工具
├── tests/
│   ├── test_heater.py              # 加热器测试
│   ├── test_hardware.py            # 硬件测试
│   └── test_metadata.py            # metadata/sample_id/samples.csv 测试（17项）
├── output/                         # 实验输出（报告/图表）
├── run_server.py                   # Web服务器启动入口
├── environment.yml                 # Conda环境配置
├── requirements.txt                # pip依赖列表
├── pyproject.toml                  # Python项目配置
└── README.md                       # 项目说明
```

---

## 3. 通用编码规范

### 3.1 必须遵守

| 规则 | 说明 |
|------|------|
| **禁止 `daemon=True` 线程** | 必须使用 `daemon=False`，手动管理线程生命周期 |
| **禁止裸 `while True`** | 必须检查停止标志：`while not stop_event.is_set()` |
| **禁止长 `sleep()`** | 使用短间隔循环：`for _ in range(100): time.sleep(0.1)` |
| **禁止无锁串口操作** | 所有串口读写必须通过 `RLock` 保护 |
| **禁止无 `finally` 清理** | 设备操作必须有 `try...finally` 确保资源释放 |
| **禁止注释** | 代码必须自解释，除非用户明确要求 |
| **禁止串口驱动内部开线程** | 心跳、轮询、命令队列等线程严禁在驱动层实现 |

### 3.2 推荐做法

| 规则 | 说明 |
|------|------|
| **使用 `with` 语句** | 锁、文件、设备连接优先使用上下文管理器 |
| **注册 `atexit` 回调** | 确保进程退出时清理资源 |
| **注册信号处理器** | `SIGINT`/`SIGTERM` 触发优雅关闭 |
| **使用数据类** | 配置、状态使用 `@dataclass` |
| **类型注解** | 函数参数和返回值添加类型注解 |

### 3.3 异常处理规范

```python
# 正确示例
def safe_operation(device):
    try:
        result = device.read_status()
        return result
    except TimeoutError:
        logger.warning(f"Device {device.device_id} timeout")
        return None
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise
    finally:
        device.cleanup()

# 错误示例 - 禁止
def unsafe_operation(device):
    result = device.read_status()  # 无异常处理
    return result
```

### 3.4 线程安全规范

```python
# 正确示例
class SafeDevice:
    def __init__(self):
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
    
    def read_status(self):
        if self._stop_event.is_set():
            return None
        
        with self._lock:
            return self._do_read()
    
    def stop(self):
        self._stop_event.set()

# 错误示例 - 禁止
class UnsafeDevice:
    def read_status(self):
        return self._do_read()  # 无锁、无停止检查
```

---

## 4. 硬件开发统一规则

### 4.1 串口通信

| 规则 | 说明 |
|------|------|
| **必须通过 `SerialPortManager` 获取串口** | 防止多进程冲突 |
| **必须设置超时** | `timeout=1.0` 防止永久阻塞 |
| **必须使用锁** | `threading.RLock()` 保护读写 |
| **断开必须幂等** | 重复调用 `disconnect()` 不报错 |

**串口配置模板：**

```python
connection_params = {
    "port": "COM10",
    "baudrate": 9600,
    "parity": "N",      # N/E/O
    "stopbits": 1,
    "bytesize": 8,
    "timeout": 1.0,
}
```

### 4.2 线程管理

| 规则 | 说明 |
|------|------|
| **必须存储线程引用** | 退出时 `join()` 等待 |
| **必须检查停止标志** | 循环内检查 `stop_event.is_set()` |
| **必须短间隔轮询** | `time.sleep(0.1)` 而非 `time.sleep(5)` |
| **必须捕获线程异常** | 异常放入队列，不静默忽略 |

**线程模板：**

```python
def worker_thread(stop_event, result_queue):
    while not stop_event.is_set():
        try:
            result = do_work()
            result_queue.put(result)
        except Exception as e:
            result_queue.put(e)
        
        for _ in range(10):  # 1秒，可快速响应停止
            if stop_event.is_set():
                return
            time.sleep(0.1)
```

### 4.3 资源释放

| 规则 | 说明 |
|------|------|
| **必须 `atexit` 注册** | 进程退出时强制清理 |
| **必须 `finally` 清理** | 异常路径也要释放 |
| **必须关闭串口** | `serial.close()` 在 `finally` 中 |
| **必须释放锁文件** | 删除锁文件，允许后续进程获取 |

**清理模板：**

```python
import atexit
import signal

_device = None
_stop_event = threading.Event()

def cleanup():
    global _device
    if _device is not None:
        try:
            _device.emergency_stop()
            _device.disconnect()
        except Exception as e:
            logger.error(f"Cleanup error: {e}")
        finally:
            _device = None

def signal_handler(signum, frame):
    _stop_event.set()
    cleanup()

atexit.register(cleanup)
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)
```

### 4.4 紧急停止

| 规则 | 说明 |
|------|------|
| **必须实现 `emergency_stop()`** | 所有设备必须有此方法 |
| **必须在 3 秒内完成** | 停止输出 + 关闭串口 |
| **必须全局协调** | `DeviceSafetyManager` 管理所有设备 |
| **必须硬件级保障** | 软件失效时硬件急停可用 |

### 4.5 MODBUS RTU 协议

| 参数 | 默认值 |
|------|--------|
| 从站地址 | 1 |
| 波特率 | 9600 |
| 校验位 | N (无校验) / E (偶校验) |
| 停止位 | 1 |
| 数据位 | 8 |

**⚠️ 蠕动泵必须使用 parity='E'（偶校验），波特率 19200**

**关键经验：**
- **校验位必须与设备一致**：不同设备可能不同，必须确认
- **超时时间**：建议 1.0 秒，过短易误判
- **重试机制**：失败重试 3 次，间隔 0.5 秒

---

## 5. 已开发设备

### 5.1 加热器 (AIHeaterDevice)

| 属性 | 值 |
|------|-----|
| 设备类型 | AI-708 温控器 |
| 通信协议 | MODBUS RTU |
| 默认串口 | COM7, COM9 |
| 波特率 | 9600 |
| 校验位 | N |

**核心功能：**
- 温度读取：`read_temperature()` → `(pv, sv)`
- 温度设置：`set_temperature(temp)`
- 启动/停止：`start()`, `stop()`

**开发经验：**
- 温度读取可能返回 `None`，必须处理
- 设置温度后需等待设备响应
- 多加热器同时运行需独立线程监控

### 5.2 蠕动泵 (LabSmartPumpDevice)

| 属性 | 值 |
|------|-----|
| 设备类型 | LabSmart 多通道蠕动泵 |
| 通信协议 | MODBUS RTU |
| 默认串口 | COM10 |
| 波特率 | 19200 |
| 校验位 | E (偶校验) |
| 停止位 | 1 |
| 数据位 | 8 |
| 通道数 | 4 |

**核心功能：**
- 四通道独立控制
- 四种运行模式：流量、定时定量、定时定速、定量定速
- 启停、换向、速度控制
- 流量校准
- 重复模式：repeat_count(0=无限,1-9999) + interval_time(最小0.1s) + interval_time_unit
- 单位参数：time_unit(sec/min/hour)、volume_unit(uL/mL/L)、flow_unit(mL/min/RPM)

**运行模式参数设置规则（实测验证，非常重要）：**

协议要求"相关参数必须在对应模式下才可以设置"，实测验证：

| 参数 | 可设置的模式 | 不可设置的模式 |
|------|-------------|---------------|
| 流速(n110) | **仅流量模式(0)** | 定时定量/定时定速/定量定速 ❌ |
| 运行时间(n107) | 定时定量(1)/定时定速(2) | 流量模式 ❌ |
| 分装液量(n104) | 定时定量(1)/定量定速(3) | 流量模式 ❌ |

**启动流程（非流量模式）：**
1. 使能 + 停止
2. 设软管型号
3. 设方向
4. **先切到流量模式 → 设流速**
5. **再切到目标模式 → 设运行时间/分装液量**
6. 启动

**定时定量模式流速自动计算：**
- 流速 = 分装液量(mL) / 运行时间(min)，由泵自动计算
- 切换到定时定量模式后，泵会覆盖之前设置的流速值
- 前端：定时定量模式下流速输入框为只读，显示计算值

**流速单位(n112)限制（实测验证）：**

| 单位值 | 含义 | 泵是否接受 |
|--------|------|-----------|
| 0 | uL/min | ❌ ILLEGAL_DATA_VALUE |
| 1 | mL/min | ✅ |
| 2 | L/min | ❌ ILLEGAL_DATA_VALUE |
| 3 | RPM | ✅（读回=0） |

泵只接受 1(mL/min) 和 3(RPM)，0 和 2 均返回 ILLEGAL_DATA_VALUE。

**软管型号(n004)验证：**
- 有效范围：0-13，超出范围返回 False
- 写入值与读回值可能不一致（如写11读回13），泵内部会映射到最近的合法型号

**关键类：**

| 类 | 用途 |
|---|------|
| `LabSmartPumpDevice` | 基础驱动，纯同步操作串口 |

**MODBUS 字序经验（实测验证，非常重要）：**

协议文档的数据传输格式表格描述有歧义（"第X个字节"编号从低位到高位，反直觉），
但示例是明确的：`1234H` 发送 `12H 34H`，即大端序（MSB first）。

**浮点数寄存器字序：ABCD（大端序，高字在前）**

```
IEEE754 float 10.0 = 0x41200000
拆为两个16位寄存器：高字=0x4120(16672), 低字=0x0000(0)
MODBUS 0x10写入顺序：[0x4120, 0x0000]  ← ABCD，高字在前
```

实测验证结果：

| 操作 | 字序 | 结果 |
|------|------|------|
| 0.1 mL/min 写入 | ABCD `[0x3DCC, 0xCCCD]` | ✅ 成功，读回一致 |
| 0.1 mL/min 写入 | CDAB `[0xCCCD, 0x3DCC]` | ❌ ILLEGAL_DATA_VALUE |
| 50.0 RPM 写入 | ABCD `[0x4248, 0x0000]` | ✅ 成功，读回一致 |
| 50.0 RPM 写入 | CDAB `[0x0000, 0x4248]` | ❌ ILLEGAL_DATA_VALUE |
| 10.0 mL/min 写入 | ABCD `[0x4120, 0x0000]` | ❌ ILLEGAL_DATA_VALUE（软管型号未设置，流速范围受限） |

**⚠️ n003(泵头型号) 不可写，流速适配通过软管型号(n004)实现**

- n003 写操作返回 ILLEGAL_DATA_ADDRESS，该寄存器不可通过MODBUS写入
- 泵头型号在泵出厂时已固定，无需也不可设置
- 流速与转速的适配关系由软管型号(n004)决定，初始化时必须设置软管型号
- 软管型号未设置(n004=0)时，mL/min流速范围极小（约0.01~5.0），超出范围返回ILLEGAL_DATA_VALUE

**LabSmart 流量参数（申辰产品说明 6.3节）：**

| 软管规格 | 软管型号(n004) | 流量范围 (mL/min) |
|----------|---------------|-------------------|
| 0.13×0.86 | 4 | 0.0002 ~ 0.29 |
| 0.19×0.86 | 5 | 0.0003 ~ 0.44 |
| 0.25×0.86 | 6 | 0.0005 ~ 0.76 |
| 0.51×0.86 | 7 | 0.0013 ~ 2.00 |
| 0.89×0.86 | 8 | 0.0030 ~ 4.47 |
| 1×1 | 0 | 0.0050 ~ 7.55 |
| 1.14×0.86 | 9 | 0.0061 ~ 9.16 |
| 1.42×0.86 | 10 | 0.0125 ~ 18.75 |
| 1.52×0.86 | 11 | 说明书未给出，需厂家确认 |
| 2×1 | 1 | 0.0183 ~ 27.52 |
| 2.06×0.86 | 12 | 0.0197 ~ 29.60 |
| 2.4×0.86 | 2 | 0.0254 ~ 38.13 |
| 2.79×0.86 | 13 | 0.0286 ~ 42.86 |
| 3×1 | 3 | 0.0323 ~ 48.38 |

泵头型号：AMC_(10)（n003=5，不可写）。转速范围：0.1~150 rpm，4通道，10滚轮，软管承压 0.1 MPa

**开发经验：**

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| 串口被占用 | 进程被强制终止，串口未释放 | 使用 `SerialPortManager` + 锁文件 |
| 通道互相影响 | 共享串口，无隔离 | 上层顺序调度，不要并发 |
| 程序无法退出 | `daemon=True` 线程卡死 | `daemon=False` + 停止标志 |
| 读取超时 | 串口阻塞 | 设置 `timeout` + 超时重试 |
| 校验位错误 | 设备默认偶校验 | 确认设备配置，使用 E (偶校验) |
| 流速写入ILLEGAL_DATA_VALUE | 软管型号未设置导致流速范围受限 | 初始化时设置正确的软管型号(n004) |
| n003泵头型号写入失败 | n003不可写，返回ILLEGAL_DATA_ADDRESS | 不写n003，泵头出厂固定，流速适配通过n004实现 |
| 浮点字序错误 | 误用CDAB低字在前 | 必须用ABCD大端序（高字在前） |
| 控制寄存器批量读取失败 | 泵不支持连续读n000-n006 | 逐个寄存器单独读取 |
| 浮点数0x06单写失败 | 低字寄存器不可独立写 | 必须用0x10批量写2个寄存器 |
| 浮点数+单位0x10写3个寄存器失败 | 泵不支持0x10写3个 | 单位0x06单写，浮点数0x10写2个 |
| 非流量模式下流速写入失败 | 流速(n110)只能在流量模式下设置 | 先切流量模式设流速，再切目标模式 |
| 流量模式下运行时间/分装液量写入失败 | 运行时间/分装液量只能在对应模式下设置 | 先切到目标模式再设参数 |
| 流速单位n112写入0/2失败 | 泵只接受1(mL/min)和3(RPM) | 只使用1和3两个单位值 |
| 软管型号写入与读回不一致 | 泵内部映射到最近合法型号 | 写入前验证0-13范围，读回验证一致性 |
| CH1 n110寄存器锁定 | 写入无效tube_model导致寄存器状态损坏 | 给泵断电重启恢复；添加tube_model范围验证 |

**⚠️ 已废弃：SafePumpDevice**

`SafePumpDevice` 因架构错误已移除。它在驱动内部开线程（命令队列线程、心跳线程、通道任务线程），导致多线程抢占串口，产生通信冲突、Timeout、锁文件无法释放等问题。串口是半双工通信，驱动必须是纯同步、无线程架构。

**寄存器映射：**

| 功能 | 地址 | 说明 |
|------|------|------|
| 启停控制 | 40001 | 0=停止, 1=启动 |
| 运行方向 | 40002 | 0=正转, 1=反转 |
| 运行模式 | 40003 | 1-4 对应四种模式 |
| 流速设置 | 40004 | 单位 mL/min |
| 分装量 | 40005 | 单位 mL |
| 运行状态 | 40009 | 读取状态 |

---

## 6. 历史重大问题与解决方案

### 6.1 串口被占用找不到进程

**问题现象：**
- 运行脚本报错 `PermissionError: [Errno 13] Permission denied: 'COM10'`
- 设备管理器显示端口正常
- 任务管理器找不到占用进程

**根本原因：**
1. 程序使用 `daemon=True` 线程
2. 进程被强制终止时，后台线程仍在运行
3. 线程持有串口句柄，进程已死但句柄未释放

**最终解决方案：**

```python
# 1. 使用 SerialPortManager 管理串口
from utils import get_serial_manager
manager = get_serial_manager()
manager.acquire_port("COM10", force=True)

# 2. 使用 SafePumpDevice 替代 LabSmartPumpDevice
from devices import SafePumpDevice
pump = SafePumpDevice(config)
pump.connect(force=True)

# 3. 启动时强制释放
SerialPortForceRelease.force_release("COM10")
```

### 6.2 程序无法正常退出

**问题现象：**
- Ctrl+C 无响应
- IDE 停止按钮无效
- 必须重启电脑才能释放串口

**根本原因：**
1. `while True:` 死循环无退出条件
2. 串口 `read()` 阻塞
3. 无全局停止标志
4. 无信号处理器

**最终解决方案：**

```python
# 1. 全局停止事件
_stop_event = threading.Event()

# 2. 循环检查停止标志
while not _stop_event.is_set():
    # ...

# 3. 短间隔轮询
for _ in range(10):
    if _stop_event.is_set():
        return
    time.sleep(0.1)

# 4. 信号处理器
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)
```

### 6.3 多通道同时运行死锁

**问题现象：**
- 通道 1 和通道 4 同时启动
- 读取状态时卡死
- Windows 串口驱动死锁

**根本原因：**
- 多线程同时读写同一串口
- 无互斥锁保护

**最终解决方案：**

```python
# SafePumpDevice 使用命令队列
self._command_queue = queue.Queue()

def _execute_command(self, func, *args, timeout=5.0, **kwargs):
    result_event = threading.Event()
    result_container = {}
    self._command_queue.put((func, args, kwargs, result_event, result_container))
    result_event.wait(timeout=timeout)
    return result_container.get('result')
```

### 6.4 异常崩溃后设备失控

**问题现象：**
- 程序崩溃后蠕动泵继续运行
- 液体过冲
- 设备无法停止

**根本原因：**
- 异常未捕获
- `finally` 未执行
- 无紧急停止机制

**最终解决方案：**

```python
# 1. 全局异常捕获
try:
    run_experiment()
except Exception as e:
    logger.error(f"Experiment error: {e}")
finally:
    emergency_stop_all()

# 2. atexit 注册
atexit.register(emergency_stop_all)

# 3. DeviceSafetyManager 协调
manager = get_safety_manager()
manager.register_emergency_stop(pump.emergency_stop)
```

### 6.5 Trae IDE 停止按钮问题

**问题现象：**
- 点击 IDE 停止按钮后串口仍被占用
- 后台线程继续运行

**根本原因：**
- Trae 可能使用 `TerminateProcess()` 强制终止
- 不触发 `atexit` 和信号处理器

**缓解方案：**
- 使用锁文件检测残留进程
- 下次启动时强制释放
- **无法完全解决**：这是操作系统层面限制

### 6.6 2026-04-22 代码审查与修复

**问题现象：**
- 多处使用 `daemon=True` 线程
- `requirements.txt` 缺少可选依赖说明
- 多处使用空 `except:` 捕获所有异常
- `src/` 下文件重复定义 `_project_root` 并插入 `sys.path`
- 缺少配置验证机制

**根本原因：**
1. 开发过程中逐步引入的问题，未进行统一审查
2. 缺少项目级打包配置，导致路径处理混乱
3. 异常处理不规范，可能掩盖真实错误
4. 配置加载时未进行有效性验证

**最终解决方案：**

```python
# 1. 创建 pyproject.toml，实现可编辑模式安装
# pyproject.toml
[project]
name = "heat"
version = "0.1.0"
dependencies = [
    "pyserial>=3.5",
    "PyYAML>=6.0",
]
[project.optional-dependencies]
windows = ["pywin32>=306", "psutil>=5.9.0"]
[tool.setuptools.packages.find]
where = ["src"]

# 2. 安装项目
pip install -e .

# 3. 移除 src/ 下文件的重复路径处理代码
# 之前：
_project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_project_root))
# 之后：直接使用包导入

# 4. 完善异常处理，避免空 except
try:
    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)
except (OSError, ValueError):  # 明确捕获具体异常
    pass

# 5. 为配置类添加 validate() 方法
class BaseConfig:
    def validate(self) -> List[str]:
        return []

class DeviceConnectionConfig(BaseConfig):
    def validate(self) -> List[str]:
        errors = []
        if self.baudrate not in [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200]:
            errors.append(f"波特率无效: {self.baudrate}")
        return errors
```

**经验教训：**
- **定期代码审查**：即使是小问题，积累起来也会影响项目质量
- **使用标准 Python 打包**：`pyproject.toml` + `pip install -e .` 是解决路径问题的标准方案
- **明确异常捕获**：捕获具体异常类型，避免掩盖错误
- **配置验证**：加载配置时立即验证，提前发现问题

### 6.7 2026-04-23 彻底移除 DataMonitor 解决串口资源竞争

**问题现象：**
- DataMonitor 后台独立线程持续轮询读取串口
- 与主线程的加热控制指令产生严重串口资源竞争
- 导致串口被占用、通信超时、指令错乱、数据丢包
- 甚至程序崩溃，完全破坏加热实验的稳定性与安全性

**根本原因：**
1. 串口是硬件独占资源，不支持多线程共享读写
2. DataMonitor 使用后台线程轮询，与主线程同时访问串口
3. 该设计更适合网口/TCP/OPC UA 等非独占通信场景，不适合 RS485/串口

**最终解决方案：**

```python
# 1. 创建 CSVDataLogger 替代 DataMonitor
# src/utils/csv_logger.py
class CSVDataLogger:
    def __init__(self, output_dir: str, filename_prefix: str = "data"):
        self._data_points: Dict[str, List[Dict]] = {}
        # 完全在主线程运行，无后台线程
    
    def record(self, device_id: str, pv: float = None, sv: float = None, 
               mv: float = None, alarm_status: int = 0, alarms: list = None):
        # 手动调用记录数据
```

### 6.8 2026-04-23 移除 SafePumpDevice 解决多线程串口冲突

**问题现象：**
- SafePumpDevice 内部包含心跳线程、命令队列线程、通道任务线程
- 多线程同时访问串口，产生大量通信冲突、Timeout
- 锁文件无法释放，程序无法正常退出
- 无论脚本还是GUI都无法稳定使用

**根本原因：**
1. 串口是半双工通信，同一时间只能有一个指令
2. SafePumpDevice 在驱动内部开线程，从架构上就是错误的
3. 命令队列看似解决了并发问题，实际上只是把冲突延迟和复杂化
4. 心跳线程定期发送心跳包，与业务指令抢占串口
5. 通道任务线程同时操作不同通道，共享同一串口

**正确架构：**
```
程序控制器（1个线程，顺序调度）
    ↓
加热器驱动（无线程）→ 串口A
泵驱动 LabSmartPumpDevice（无线程）→ 串口B
    ↓
串口（单线程访问 → 100% 稳定）
```

**最终解决方案：**
1. 删除 `src/devices/safe_pump.py`（SafePumpDevice）
2. 删除 `src/monitor/data_monitor.py`（DataMonitor，同样有后台线程问题）
3. 删除 `src/utils/device_safety.py`（SafeDevice/ChannelManager/ThreadSafeExecutor，仅被SafePumpDevice使用）
4. 所有泵操作改用 `LabSmartPumpDevice`（纯同步、无线程）
5. 心跳、状态刷新、任务调度全部放在上层（脚本/GUI）实现

**经验教训：**
- **串口驱动必须是纯同步、无线程架构**，这是不可违反的铁律
- 心跳、轮询、状态刷新等"便利功能"不应在驱动层实现
- 上层（脚本/GUI）负责调度，驱动层只负责执行
- ProgramController 的设计是正确的：虽然使用线程，但全程单线程顺序访问设备

# 2. 在实验引擎中自动记录数据
# src/experiment/executor.py 通过 CSVDataLogger 自动记录设备数据
def _record_temperature(self):
    try:
        if self.heater1:
            pv1, sv1 = self.heater1.get_temperature()
            self._csv_logger.record("heater1", pv1, sv1)
    except Exception as e:
        self.logger.log(f"警告: 读取加热器1温度失败: {e}")

# 3. 更新所有相关文件移除 DataMonitor
# src/main.py
# src/__init__.py
```

**关键变更：**
- 新增 `src/utils/csv_logger.py` 实现单线程 CSV 数据记录
- 移除 `src/monitor/` 下 DataMonitor 相关代码的所有引用
- 更新 `src/utils/__init__.py` 导出 CSVDataLogger
- 更新 `src/__init__.py` 移除 DataMonitor 导出，添加 CSVDataLogger
- 修改所有实验脚本使用 CSVDataLogger

**经验教训：**
- **独占资源绝对禁止多线程访问**：串口硬件同一时刻只允许一个线程操作
- **设计选择必须匹配通信方式**：DataMonitor 适合网络通信，不适合独占串口
- **宁愿手动记录也不要多线程冲突**：安全性 > 便利性
- **问题暴露不一定立即明显**：竞争条件可能在长时间运行后才触发

---

## 7. AI 开发指南

### 7.1 与 AI 协作最佳实践

| 规则 | 说明 |
|------|------|
| **明确需求** | 描述具体功能，避免模糊表述 |
| **提供文档** | 新设备提供说明书/协议文档 |
| **确认配置** | 串口、波特率、校验位必须确认 |
| **逐步验证** | 先测试单个设备，再集成 |
| **Git 推送前确认** | 每次推送前询问用户 |

### 7.2 AI 必须遵守

| 规则 | 说明 |
|------|------|
| **禁止自动推送 Git** | 必须询问用户确认 |
| **禁止创建不必要的文件** | 优先编辑现有文件 |
| **禁止添加注释** | 除非用户明确要求 |
| **禁止假设库可用** | 先检查 `requirements.txt` |
| **必须运行 lint/typecheck** | 修改代码后验证 |

### 7.3 代码修改流程

```
1. 理解需求
   ↓
2. 搜索现有代码
   ↓
3. 设计方案
   ↓
4. 实现修改
   ↓
5. 运行测试
   ↓
6. 运行 lint/typecheck
   ↓
7. 询问用户确认 Git 推送
```

### 7.4 常见问题快速定位

| 问题 | 检查项 |
|------|--------|
| 串口无法打开 | 1. 锁文件是否存在 2. 进程是否残留 3. 设备管理器状态 |
| 通信超时 | 1. 波特率 2. 校验位 3. 接线 4. 从站地址 |
| 程序卡死 | 1. 是否有 `while True` 2. 是否有长 `sleep` 3. 是否有阻塞读取 |
| 设备不响应 | 1. 电源 2. 通信模式(RS232/RS485) 3. 设备界面状态 |

### 7.5 文档更新提醒

**AI 必须在完成以下任务后主动询问是否更新相关文档：**

| 任务类型 | 需更新文档 | 示例 |
|----------|------------|------|
| 新增设备驱动 | PROJECT_CONTEXT.md + README.md | 添加第3个设备 |
| 解决重大 bug | PROJECT_CONTEXT.md | 串口占用、线程死锁 |
| 修改核心架构 | PROJECT_CONTEXT.md + README.md | 新增工具层、重构协议层 |
| 发现新经验 | PROJECT_CONTEXT.md | 新的踩坑教训 |

**提醒格式：**

```
此任务涉及重要变更，是否需要更新以下文档？
1. context/PROJECT_CONTEXT.md
2. README.md

如需更新，请告知更新内容。
```

**更新位置：**

| 变更类型 | 更新位置 |
|----------|----------|
| 新增设备 | PROJECT_CONTEXT.md 第5章 + 第8.3节；README.md 设备列表 |
| 解决问题 | PROJECT_CONTEXT.md 第6章 |
| 架构变更 | PROJECT_CONTEXT.md 第2章；README.md 架构说明 |
| 新经验 | PROJECT_CONTEXT.md 第8.3节 |
| 任何更新 | 文件头部"最后更新"日期 |

### 7.6 Git 分支管理策略

**新设备开发必须遵循分支管理流程：**

```
main (主分支 - 稳定版本)
  │
  ├── feature/device-xxx (新设备分支)
  │     │
  │     ├── 开发设备驱动
  │     ├── 实现通信协议
  │     ├── 编写测试脚本
  │     ├── 本地测试验证
  │     │
  │     └── 测试稳定后 → 合并到 main
  │
  └── feature/device-yyy (另一个新设备)
        └── ...
```

**分支命名规范：**

| 分支类型 | 命名格式 | 示例 |
|----------|----------|------|
| 新设备 | `feature/device-{设备名}` | `feature/device-valve` |
| 功能增强 | `feature/{功能名}` | `feature/auto-report` |
| Bug修复 | `fix/{问题描述}` | `fix/serial-timeout` |
| 重构 | `refactor/{模块名}` | `refactor/protocol-layer` |

**开发流程：**

```
1. 从 main 创建新分支
   git checkout main
   git pull
   git checkout -b feature/device-xxx

2. 开发与测试
   git add .
   git commit -m "feat: 添加 xxx 设备驱动"
   # 本地测试验证

3. 测试稳定后合并
   git checkout main
   git merge feature/device-xxx
   git push origin main

4. 删除已合并分支（可选）
   git branch -d feature/device-xxx
```

**AI 必须遵守：**

| 规则 | 说明 |
|------|------|
| **新设备必须开分支** | 不直接在 main 上开发 |
| **测试稳定后合并** | 本地验证通过再合并 |
| **推送前询问用户** | 每次推送/合并前确认 |
| **保持 main 稳定** | main 分支始终可运行 |

---

## 8. 待开发与待确认

### 8.1 待开发设备

| 设备 | 状态 | 备注 |
|------|------|------|
| 第3个设备 | 待定 | 预留接口 |
| 第4个设备 | 待定 | 预留接口 |
| 第5个设备 | 待定 | 预留接口 |

### 8.1.1 新设备开发文件清单

**必须新增：**

| 目录 | 文件 | 职责 |
|------|------|------|
| `src/protocols/` | `xxx_protocol.py` | 通信协议（帧构建、解析、校验） |
| `src/protocols/` | `xxx_params.py` | 参数定义（寄存器地址、枚举） |
| `src/devices/` | `xxx_device.py` | 设备驱动（继承 `SafeDevice`） |

**必须修改：**

| 文件 | 修改内容 |
|------|----------|
| `config/system_config.yaml` | 添加设备配置 |
| `context/PROJECT_CONTEXT.md` | 第5章 + 第8.3节 |
| `README.md` | 设备列表、示例 |

**可选新增：**

| 目录 | 文件 | 说明 |
|------|------|------|
| `scripts/` | `test_xxx.py` | 测试脚本 |
| `tests/` | `diagnose_xxx.py` | 诊断工具 |

### 8.1.2 开发流程

```
1. 创建分支 (见 7.6 Git分支管理策略)
   git checkout -b feature/device-xxx

2. 实现协议层
   ├── 分析设备通信协议文档
   ├── 实现 protocols/xxx_protocol.py
   └── 定义 protocols/xxx_params.py

3. 实现设备驱动
   ├── 继承 SafeDevice
   ├── 实现 connect/disconnect/emergency_stop
   └── 实现设备特有方法

4. 添加配置 → system_config.yaml

5. 编写测试脚本 → scripts/test_xxx.py

6. 本地测试验证

7. 更新文档 → PROJECT_CONTEXT.md + README.md

8. 合并主分支
   git checkout main && git merge feature/device-xxx
```

### 8.1.3 设备驱动模板

```python
from utils import SafeDevice, DeviceState

class XxxDevice(SafeDevice):
    def __init__(self, config):
        super().__init__(device_id=config.device_id)
        self._config = config
        self._protocol = None
    
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

### 8.2 待确认问题

| 问题 | 状态 | 备注 |
|------|------|------|
| Trae IDE 停止按钮行为 | 待确认 | 是否触发 atexit |
| 硬件急停接口 | 待开发 | 外部触发机制 |
| 多进程并发保护 | 待增强 | 跨机器锁 |

### 8.3 新增经验记录

> **使用方法**：每完成一个重要功能或解决一个重要问题，在此追加记录

```
[2026-04-29] 蠕动泵 Modbus 控制关键配置要求
- 问题现象：
  - 写入 1001（启停控制）返回 SLAVE_DEVICE_BUSY (0x06)
  - 写入 1002（方向控制）返回 SLAVE_DEVICE_BUSY (0x06)
  - 协议文档说这些寄存器可读写，但实际无法写入
- 根本原因：
  - 泵的外控模式和通信设置不正确
  - 必须在正确的模式下才能进行 Modbus 通信控制
- 解决方案：
  - **外控设置**：外控模式必须设置为"脉冲模式"（不是电平模式）
  - **外控开关**：外控信号中的"独立启停/全部启停/脚踏启停"必须关闭
  - **界面要求**：泵必须处于主运行界面（非菜单、非设置界面）
  - **泵头型号**：不需要设置，由硬件自动识别
- 关键配置步骤：
  1. 进入泵的"外控设置"菜单
  2. 外控模式选择：**脉冲模式**（不是电平模式）
  3. 外控信号中的"独立启停"等选项：**必须关闭**
  4. 确保泵显示在**主运行界面**
  5. 此时 Modbus 写入才能正常工作
- 经验教训：
  - **脉冲模式**：通信控制必须使用脉冲模式
  - **外控关闭**：外控信号中的启停控制必须关闭，否则与 Modbus 冲突
  - **主界面**：泵必须在主界面才能响应 Modbus 指令
  - **泵头型号**：不需要通过 Modbus 或面板设置，由硬件自动识别
  - 与厂家技术沟通后确认：这是该型号泵的正确配置要求

[2026-04-23] MODBUS RTU 通信稳定性修复
- 问题现象：
  - 控制台刷屏报错：ILLEGAL_DATA_ADDRESS、SLAVE_DEVICE_BUSY、Timeout
  - 蠕动泵有时能启动，有时不能
- 根本原因：
  - 指令发送太快，蠕动泵从机处理不过来
  - CRC 校验失败处理不当（返回 True 掩盖错误）
  - 写寄存器异常时阻断主流程
- 解决方案：
  - _send_frame 发送后增加 time.sleep(0.05) 延时
  - _receive_frame 开头增加 time.sleep(0.1) 延时
  - 改为宽松读取模式，不严格卡死响应帧长度
  - CRC 校验失败：记录 warning，返回 False
  - 02/06 异常：记录 info，返回 True（蠕动泵特殊处理）
  - 写寄存器即使异常也返回 True，不阻断主流程
- 经验教训：
  - 工业设备从机处理能力有限，必须留足响应时间
  - CRC 校验失败表示数据完整性受损，必须返回失败
  - 蠕动泵 02/06 异常属于正常现象（地址特殊、处理忙），忽略即可

[2026-04-23] 删除 conda heat 虚拟环境
- 问题现象：
  - 项目同时存在 conda heat 环境和 base 环境
  - 依赖管理混乱
- 根本原因：
  - 开发过程中创建了多个环境
- 解决方案：
  - 删除 conda env remove -n heat
  - 统一使用 base 环境（或按需创建专用环境）
- 经验教训：
  - 保持环境简洁，避免重复
```
[2026-05-01] 蠕动泵运行模式参数设置规则与流速单位限制
- 问题现象：
  - 定时定量模式启动失败，set_flow_rate 返回 ILLEGAL_DATA_VALUE
  - 流速单位切换到 uL/min 或 L/min 失败
  - 软管型号写入 11 但读回 13
  - CH1 流速寄存器锁定无法写入
- 根本原因：
  - 泵协议要求"相关参数必须在对应模式下才可以设置"
  - 流速(n110)只能在流量模式(0)下设置，非流量模式下写入返回 ILLEGAL_DATA_VALUE
  - 运行时间(n107)和分装液量(n104)只能在对应模式下设置，流量模式下写入返回 ILLEGAL_DATA_VALUE
  - 流速单位(n112)只接受 1(mL/min) 和 3(RPM)，0 和 2 均返回 ILLEGAL_DATA_VALUE
  - 软管型号写入值与读回值不一致，泵内部映射到最近合法型号
  - 写入无效 tube_model 值（如 11）导致 CH1 寄存器状态损坏
- 解决方案：
  - 启动流程：先切到流量模式设流速，再切到目标模式设其他参数
  - 前端流速单位只提供 mL/min 和 RPM 两个选项
  - set_tube_model 添加 0-13 范围验证
  - 定时定量模式流速由泵自动计算，前端显示为只读
  - CH1 寄存器锁定需给泵断电重启恢复
- 经验教训：
  - **参数设置必须匹配运行模式**：流速在流量模式设，时间/液量在目标模式设
  - **流速单位有限制**：不是协议文档中所有枚举值都能用
  - **软管型号有映射**：泵可能不接受某些型号值，写入后必须验证读回
  - **无效参数可能损坏寄存器**：必须验证参数范围再写入

[2026-05-01] 前端参数持久化与多通道并发修复
- 问题现象：
  - 前端参数刷新后丢失
  - 多通道同时启动导致通信冲突
  - 仪表盘流速显示 0
- 根本原因：
  - 前端参数仅存在 reactive state，未持久化
  - 多通道并发操作共享串口，无序列化
  - 参数寄存器索引错误
- 解决方案：
  - 使用 localStorage 持久化泵参数
  - 添加泵级锁序列化多通道操作
  - 修正参数寄存器索引映射
- 经验教训：
  - 前端关键参数必须持久化
  - 共享串口设备必须序列化操作
  - 寄存器映射必须与协议文档严格对照

[2026-05-01] 服务器终止与端口释放修复
- 问题现象：
  - Ctrl+C 无法终止服务器
  - 端口 8000 被残留进程占用
- 根本原因：
  - uvicorn reload=True 创建多进程
  - sys.exit(0) 被 uvicorn 捕获
- 解决方案：
  - 设置 reload=False
  - 使用 os._exit(0) 确保退出
  - 添加进程清理和端口释放逻辑
- 经验教训：
  - 生产环境禁用 uvicorn reload
  - 信号处理器中避免使用 sys.exit

---

## 附录

### A. 快速启动命令

```bash
# 测试蠕动泵
python scripts/test_pump_flow.py --port COM10 --force

# 运行集成实验
python scripts/heater_pump_safe.py --heater-ports COM7 COM9 --pump-port COM10 --force
```

### B. 环境管理

**推荐使用 Conda 管理环境：**

```bash
# 创建环境
conda env create -f environment.yml

# 激活环境
conda activate heat

# 导出环境（新增依赖后）
conda env export > environment.yml

# 删除环境
conda env remove -n heat
```

**或使用 pip + venv + pyproject.toml：**

```bash
# 创建虚拟环境
python -m venv venv
venv\Scripts\activate

# 安装项目（推荐：可编辑模式）
pip install -e .

# 安装项目 + Windows 可选依赖
pip install -e ".[windows]"

# 仅安装依赖（不安装项目）
pip install -r requirements.txt
```

**可选依赖：**

```bash
# Windows 可选依赖（用于串口强制释放）
pip install pywin32 psutil
```

**项目结构说明：**
- `pyproject.toml` 定义了项目元数据、依赖和包发现配置
- `pip install -e .` 将 `src/` 目录安装到 Python 路径中
- 安装后可以直接使用 `from devices import ...`、`from utils import ...`，无需处理路径

### C. 配置文件模板

```yaml
# config/system_config.yaml
heaters:
  - device_id: "heater1"
    port: "COM7"
    baudrate: 9600

pumps:
  - device_id: "pump1"
    port: "COM10"
    baudrate: 9600
    parity: "N"
    slave_address: 1
```

---

**文档结束**

> 此文档是项目的核心记忆库，任何新对话开始时，请先阅读此文档。
> 
> 每次重要更新后，请更新"最后更新"日期。

---

### 6.7 2026-04-23 全面代码审查与修复

**审查范围：** 项目全部17个源代码文件，按优先级分4级共发现17个问题。

**P0 严重问题（3项）：**

| 问题 | 文件 | 修复 |
|------|------|------|
| Modbus写操作所有异常都返回True | modbus_rtu.py | 仅SLAVE_DEVICE_BUSY返回True，其他异常返回False |
| AIBUS校验和失败静默通过 | aibus.py | 校验失败时抛出IOError |
| 蠕动泵绕过BaseDevice的status属性setter | peristaltic_pump.py | `self._status=` 全部改为 `self.status=` |

**P1 中等问题（3项）：**

| 问题 | 文件 | 修复 |
|------|------|------|
| _receive_frame空数据返回空bytes而非None | modbus_rtu.py | 统一返回None |
| read_channel_status返回内部数据引用 | peristaltic_pump.py | 使用copy.deepcopy返回深拷贝 |
| heater_only_experiment.py cleanup无try/except | heater_only_experiment.py（已移除） | 文件已删除，功能由实验引擎替代 |

**P2 改进项（3项）：**

| 问题 | 文件 | 修复 |
|------|------|------|
| temperature_experiment.py自定义DataPoint | temperature_experiment.py（已移除） | 文件已删除，功能由实验引擎替代 |
| main.py不支持蠕动泵 | main.py | 添加_init_pumps/connect_pump/start_pump/stop_pump等方法和交互命令 |
| 多处裸except | 3个实验脚本 | 全部改为except Exception |

**P3 规范项（4项）：**

| 问题 | 文件 | 修复 |
|------|------|------|
| 多处方法缺少docstring | heater.py, program_controller.py, csv_logger.py | 补充文档字符串 |
| PumpChannelConfig重复定义 | config.py | 重命名为PumpChannelConfigYaml |
| heater.py read_data锁范围过大 | heater.py | 锁从外层移入_read()内部，仅保护协议调用 |

**关键经验：**

1. **Modbus异常处理策略**：`SLAVE_DEVICE_BUSY` 是可恢复异常（设备忙稍后重试），返回True不中断主流程；`ILLEGAL_DATA_ADDRESS`、`SLAVE_DEVICE_FAILURE` 等是真实错误，必须返回False通知调用方
2. **AIBUS校验失败必须抛异常**：校验和错误意味着数据已损坏，静默通过会导致加热器温度被错误解析，可能造成误控
3. **BaseDevice.status属性setter**：直接赋值 `self._status` 绕过了属性setter，状态变更回调永远不会触发，外部无法感知状态变化
4. **锁范围最小化**：锁应仅保护共享资源（串口协议调用），纯计算逻辑（数据解析、对象构造）应在锁外执行，避免重试时长时间阻塞其他线程

### 6.9 2026-04-24 Web远程控制与实验自动化（v2.3）

**新增模块：**

| 模块 | 路径 | 说明 |
|------|------|------|
| Web服务层 | `src/web/` | FastAPI + WebSocket，桥接同步设备与异步框架 |
| 实验自动化引擎 | `src/experiment/` | YAML实验定义 + 状态机调度 + 步骤执行 |
| Vue前端 | `frontend/` | 仪表盘 + 控制面板 + 实验页面 |
| 实验定义 | `experiments/` | YAML格式实验流程定义 |

**Web架构关键设计：**
- FastAPI通过 `run_in_executor` 桥接同步设备操作与异步Web框架
- WebSocket 1Hz推送实时温度和流量数据
- SPA路由：FastAPI catch-all路由返回index.html，支持Vue Router history模式
- 路径遍历防护：实验API的filename参数校验，禁止`../`等路径穿越

**实验自动化引擎架构：**
- YAML定义实验步骤（9种动作 + 4种等待条件）
- 状态机：IDLE → RUNNING → PAUSED/COMPLETED/FAILED/STOPPED
- 通过DeviceManager调用设备，支持暂停/恢复/停止

**全面代码审查修复（~70项）：**

P0严重（3项）：
- program_controller pause/resume逻辑反转（Event.set/clear语义）
- chemical_synthesis heat_ramp_time硬编码300.0覆盖构造参数
- heater_only_experiment pv1/pv2 None格式化崩溃

P1重要（6项）：
- Web实验API路径遍历漏洞
- heater emergency_stop null protocol检查
- base_device execute_with_retry retry_count=0崩溃
- pump read_channel_status enum越界保护
- pump set_flow_rate非原子操作
- pump channel_data返回可变引用

P2改进（16项）：
- heater/pump connect/disconnect加锁保护
- base_device callbacks锁保护
- modbus_rtu _receive_frame不完整帧拒绝
- aibus _send_and_receive写入后flush
- config.py from_dict多余键过滤
- csv_logger _data_points大小限制
- serial_manager get_serial_manager线程安全
- main.py emergency_stop停止CSV记录器
- chemical_synthesis泵失败时清理加热器
- pump _force_disconnect非阻塞锁获取
- pump _read_float or语义修复（区分0.0和None）
- heater read_data status锁保护
- heater wait_for_temperature连接检查
- heater write_command添加get_temperature分支
- heater RunStatus枚举越界保护
- connect方法锁范围缩小（协议通信在锁外）

P3规范（3项）：
- aibus close异常返回值修复
- pump_params get_channel_address通道校验
- base_device __exit__异常处理

**关键经验：**

1. **锁范围最小化**：connect方法中锁仅保护状态检查和设置，协议通信（串口I/O）在锁外执行，避免死锁
2. **`or` vs `is not None`**：`_read_float() or 0.0` 无法区分0.0和None，必须用 `is not None` 判断
3. **atexit回调非阻塞**：`_force_disconnect` 使用 `acquire(blocking=False)` 避免程序退出时阻塞
4. **回调锁先于数据**：`_callback_lock` 必须在 `_callbacks` 之前初始化
5. **Web层线程安全**：FastAPI通过 `run_in_executor` 调用同步设备方法，设备层RLock保证线程安全

### 6.10 2026-04-24 实验日志可追溯系统 + 竞态条件修复（v2.4）

**实验日志系统（新增）：**

| 模块 | 路径 | 说明 |
|------|------|------|
| 实验日志记录器 | `src/experiment/experiment_logger.py` | 记录每个步骤的执行状态、耗时、错误信息 |
| 实时日志推送 | WebSocket `experiment_log` 事件 | 前端实时显示实验运行日志 |
| 历史记录页面 | `frontend/src/views/HistoryPage.vue` | 查看/导出历史实验记录 |
| 日志持久化 | `output/experiment_logs/*.json` | 每次运行自动保存JSON格式日志 |

**日志系统架构：**

```
实验运行 → ExperimentLogger → 双通道输出
                ├── WebSocket 实时推送 → 前端日志面板（终端风格）
                └── JSON 文件持久化   → 历史记录查询/导出
```

**日志记录内容：**
- Run ID：时间戳+随机码，唯一标识每次运行
- 每个步骤：step_id、动作类型、参数、状态(pending/running/completed/failed/skipped)、耗时、错误信息
- 运行级别：实验名称、开始/结束时间、总耗时、完成/失败步骤数

**新增API端点：**

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/experiments/{filename}/logs` | GET | 获取当前运行日志 |
| `/api/experiments/history/runs` | GET | 列出所有历史运行 |
| `/api/experiments/history/runs/{run_id}` | GET | 获取指定运行详情 |

**前端功能：**
- 实验页面：终端风格实时日志面板 + 步骤状态标签 + 日志导出为.txt
- 历史页面：历史运行列表 + 详情弹窗（步骤表格）+ 单条记录导出
- WebSocket断线自动重连（5s间隔）+ onerror处理

**竞态条件修复：**

heater.py / peristaltic_pump.py connect方法3层防护：

| 防护层 | 位置 | 作用 |
|--------|------|------|
| CONNECTING状态拒绝 | 第一个锁块 | 检测到CONNECTING时拒绝新的连接请求 |
| 临时变量+二次检查 | 第二个锁块 | 赋值前再次检查is_connected()，已被其他线程连接则清理临时protocol |
| protocol=None标记+异常清理 | 赋值后+except | 成功赋值后置None防止误清理；异常时清理未移交的protocol |

**其他修复：**
- 协议关闭异常日志：`except Exception: pass` → `except Exception as close_err: self._logger.warning(...)`
- 异步日志广播异常日志：`except Exception: pass` → `except Exception as e: logger.error(...)`

**关键经验：**

1. **实验可追溯性**：化学合成实验必须记录完整执行日志，包括每步的参数、耗时、成功/失败状态，用于事后分析和复现
2. **connect竞态条件**：协议对象在锁外创建但状态在锁内更新，多线程并发connect可能导致protocol泄漏。解决方案：临时变量+二次状态检查+异常清理
3. **WebSocket健壮性**：前端必须处理onerror和onclose，自动重连；后端广播异常必须记录日志

### 6.11 2026-04-27 全面代码质量审查与修复（v2.5）

**审查范围：** 项目全部源代码文件，按优先级发现20个问题，全部修复。

**P0 高优先级（5项）：**

| 问题 | 文件 | 修复 |
|------|------|------|
| data_push_loop竞态条件 | app.py / run_server.py | 将data_push_loop启动移入lifespan上下文管理器，确保device_manager先初始化 |
| DeviceManager私有属性直接访问 | device_manager.py + api/ | 添加get_heater/get_pump/get_all_heaters/get_all_pumps公共方法，API层改用公共方法 |
| ProgramController使用threading | program_controller.py | 从threading重构为asyncio架构，使用asyncio.Event和run_in_executor |
| test_connections.py裸except | test_connections.py（已移除） | 文件已删除 |
| parameters.py枚举值冲突 | parameters.py | 移除重复的MV_EXT=80（与SP1=80冲突） |

**P1 中优先级（7项）：**

| 问题 | 文件 | 修复 |
|------|------|------|
| SLAVE_DEVICE_BUSY静默忽略 | modbus_rtu.py | 读操作改为warning日志+返回None；写操作返回False（不再静默返回True） |
| csv_logger频繁flush | csv_logger.py | 添加_maybe_flush()定时刷新（1秒间隔），stop()时强制flush |
| csv_logger channel类型不一致 | csv_logger.py | heater行channel字段从空字符串改为0 |
| _engines资源泄漏 | experiments.py | 添加_cleanup_engine() + on_complete回调，实验结束/停止时自动清理 |
| on_log_event线程安全 | experiments.py | 从loop.create_task改为asyncio.run_coroutine_threadsafe |
| CORS安全配置 | app.py | allow_origins从["*"]改为限定4个已知来源 |
| parser.py路径验证绕过 | parser.py | 移除startswith("experiments/")的绕过条件，强制所有路径走验证 |

**P2 低优先级（6项）：**

| 问题 | 文件 | 修复 |
|------|------|------|
| aibus.py小数位转换 | aibus.py | read_pv_sv添加decimal_places参数，PV/SV按小数位转换 |
| report_generator.py XSS | report_generator.py | 对device_id、title、alarms等用户可控数据使用html_escape() |
| serial_manager.py看门狗误触发 | serial_manager.py | 在data_push_loop中调用feed_watchdog()，防止120秒超时误触发cleanup |
| device_manager.py add_pump硬编码 | device_manager.py | 添加channels参数，支持dict/PumpChannelConfig/int三种格式 |
| ExperimentPage.vue WebSocket泄漏 | ExperimentPage.vue | 添加wsClosed标志位，onUnmounted时阻止自动重连 |
| HistoryPage.vue onUnmounted缺失 | HistoryPage.vue | 添加onUnmounted关闭残留弹窗 |

**后续增量修复：**

| 问题 | 文件 | 修复 |
|------|------|------|
| stop_pump_channel缺少参数验证 | device_manager.py | 添加channel范围验证(1-4)，start_pump_channel同步添加 |
| _get_event_loop竞态条件 | experiments.py | 移除全局_event_loop缓存，改用asyncio.get_running_loop()；回调优先create_task，RuntimeError时降级run_coroutine_threadsafe |
| start()缺少task清理 | program_controller.py | start()启动前取消残留task；_run_program() finally中置_task=None |
| start_pump_channel缺少返回值检查 | device_manager.py | 每个配置步骤(set_direction/set_run_mode等)检查返回值，任一失败返回False |
| 写操作缺少连接检查 | device_manager.py | set_temperature/start_heater/stop_heater/start_pump_channel/stop_pump_channel添加is_connected()检查 |
| peristaltic_pump atexit无锁 | peristaltic_pump.py | 添加_atexit_lock保护_atexit_refs列表 |
| csv_logger import time位置 | csv_logger.py | import time从方法内部移到文件顶部 |

**关键经验：**

1. **DeviceManager封装原则**：API层不应直接访问_device_manager._heaters等私有属性，必须通过公共方法。公共方法内部用锁保护，返回快照副本
2. **asyncio协作式调度无数据竞争**：所有async方法运行在同一个事件循环线程，协程间不会在属性赋值中间被抢占，不需要asyncio.Lock保护_status等状态
3. **CORS安全**：allow_origins=["*"] + allow_credentials=True违反规范；改为限定来源 + allow_credentials=False
4. **设备操作返回值必须检查**：底层方法(如set_direction)在通信失败时返回False而非抛异常，上层必须检查返回值，否则设备可能以错误参数运转
5. **连接检查分层设计**：读操作检查连接抛IOError（明确告知调用方），写操作检查连接返回False+warning日志（不中断紧急停止等场景）
6. **两级降级回调策略**：create_task（同线程快路径）→ RuntimeError降级 → run_coroutine_threadsafe（跨线程慢路径），是有意的防御性设计而非冗余

### 6.12 2026-04-28 前端稳定性与实验日志管理增强（v2.6）

**温度显示修复：**

| 问题 | 原因 | 修复 |
|------|------|------|
| 30℃显示为3.0℃ | heater.py read_data()对PV/SV做了重复除法 | 移除heater.py中的重复除法，确认aibus.py read_pv_sv()内部已通过decimal_places参数完成转换 |

数据流确认：AIBUS原始值300 → read_pv_sv(decimal_places=1) → 300/10=30.0 → heater.py直接使用 → 30.0

**实验日志保存开关：**

| 模块 | 变更 |
|------|------|
| experiment_logger.py | ExperimentLogger构造函数添加save_log: bool=True参数，_save_to_file()检查该开关 |
| experiments.py | StartExperimentRequest添加save_log字段，start_experiment传递给ExperimentLogger |
| ExperimentPage.vue | 启动按钮旁添加"保存日志"开关（el-switch），启动实验时传递save_log参数 |

**实验自动化加载修复：**

| 问题 | 原因 | 修复 |
|------|------|------|
| Invalid filename: experiments/chemical_synthesis_A.yaml | _validate_filename拒绝含/的路径 | parse_experiment用Path(filepath).name提取纯文件名再验证 |
| 启动失败: [object Object] | StartExperimentRequest含多余filename必填字段，FastAPI返回422验证错误；前端错误处理未JSON.stringify | 移除StartExperimentRequest.filename字段；前端错误处理改为JSON.stringify |

**实验日志删除功能：**

| 模块 | 变更 |
|------|------|
| experiment_logger.py | 新增delete_experiment_run()和delete_all_experiment_runs()，使用missing_ok=True防止竞态异常 |
| experiments.py | 新增DELETE /history/runs/{run_id}和DELETE /history/runs端点 |
| HistoryPage.vue | 表格操作列添加删除按钮、详情弹窗添加删除按钮、顶部添加清空全部按钮，均带确认对话框和deleting loading状态 |

**前端稳定性增强：**

| 模块 | 变更 |
|------|------|
| Dashboard.vue | initCharts()添加try-catch错误处理，防止echarts.init()异常导致页面崩溃 |
| Dashboard.vue | ECharts setOption使用replaceMerge避免series残留；ResizeObserver监听容器变化 |
| index.html | 添加Cache-Control/Pragma/Expires禁用缓存meta标签，防止浏览器缓存旧版本 |
| vite.config.ts | 添加build.outDir配置，构建产物直接输出到src/web/static/ |

**前端错误处理改进：**

| 位置 | 变更 |
|------|------|
| ExperimentPage.vue | 启动实验错误处理从`${detail}`改为JSON.stringify，避免[object Object] |
| HistoryPage.vue | 删除操作添加deleting ref防重复点击，所有删除按钮绑定:loading="deleting" |

**关键经验：**

1. **AIBUS小数位转换在协议层完成**：read_pv_sv(decimal_places=1)内部已执行pv/(10**decimal_places)，heater.py不需要再除。在_read()内部加try-except会吞掉异常导致execute_with_retry无法重试
2. **FastAPI body参数与路径参数不要重复**：StartExperimentRequest中的filename字段与URL路径参数filename冲突，前端只传{save_log:true}导致422验证错误
3. **前端错误对象必须JSON.stringify**：FastAPI验证错误返回的detail是数组/对象，直接模板字符串拼接显示为[object Object]
4. **浏览器缓存问题**：Vite构建后JS文件名含hash（如index-CnyeLZ9u.js），但index.html可能被缓存导致加载旧JS。添加no-cache meta标签解决
5. **删除操作防重复点击**：deleting ref + if(deleting.value)return + finally重置，按钮绑定:loading

### 6.13 2026-05-07 蠕动泵四种模式功能完善与参数验证增强（v2.8）

**蠕动泵四种模式功能完善：**

| 模式 | 可设置参数 | 说明 |
|------|-----------|------|
| 流量模式 | 流速 + 流速单位 | 持续运行，精确到小数点后3位 |
| 定时定量 | 运行时间 + 时间单位 + 分装液量 + 体积单位 + 重复次数 + 间隔时间 + 间隔时间单位 | 流速由泵自动计算（只读） |
| 定时定速 | 流速 + 流速单位 + 运行时间 + 时间单位 + 重复次数 + 间隔时间 + 间隔时间单位 | - |
| 定量定速 | 流速 + 流速单位 + 分装液量 + 体积单位 + 重复次数 + 间隔时间 + 间隔时间单位 | - |

**新增参数：**

| 参数 | 范围 | 说明 |
|------|------|------|
| time_unit | 0=sec, 1=min, 2=hour | 运行时间单位 |
| volume_unit | 0=uL, 1=mL, 2=L | 分装液量单位 |
| repeat_count | 0=无限, 1-9999 | 重复次数 |
| interval_time | ≥0.1s | 重复间隔时间 |
| interval_time_unit | 0=sec, 1=min, 2=hour | 间隔时间单位 |

**参数验证规则（双重防护）：**

| 验证项 | executor.py（前置校验） | device_manager.py（防御性校验） |
|--------|------------------------|-------------------------------|
| repeat_count类型 | - | 必须为int/float，非数值类型拒绝 |
| repeat_count范围 | - | [0, 9999]，float需为整数值 |
| 重复模式间隔 | repeat_count!=1时interval_time>0 | repeat_count!=1时interval_time>0 |
| 单位默认值 | time_unit=None→0, volume_unit=None→1, interval_time_unit=None→0 | 同左 |

**关键设计决策：**

1. **`repeat_count != 1` 而非 `> 1`**：repeat_count=0表示无限重复，也需要间隔时间。如果用`>1`，无限重复模式会漏掉间隔校验
2. **单位参数提前归一化**：警告后立即设置默认值（time_unit=0, volume_unit=1, interval_time_unit=0），防止后续代码误用None
3. **流速精度3位小数**：前端step=0.001, precision=3，符合说明书"精确到小数点后三位"

**前端变更：**

| 文件 | 变更 |
|------|------|
| ControlPanel.vue | 添加时间/体积单位切换、重复次数/间隔时间输入、流速step=0.001/precision=3、前端参数校验 |
| devices.ts | 新增TIME_UNITS/VOLUME_UNITS常量，startPump添加5个新参数 |

**后端变更：**

| 文件 | 变更 |
|------|------|
| devices.py | StartPumpRequest添加time_unit/volume_unit/repeat_count/interval_time/interval_time_unit |
| device_manager.py | 传递单位参数到泵驱动，添加repeat_count类型/范围校验，重复模式间隔校验，单位默认值归一化 |
| executor.py | 传递新参数，单位默认值处理，重复模式前置校验 |

**实验YAML更新：**

| 文件 | 变更 |
|------|------|
| chemical_synthesis_A.yaml | 补全time_unit/volume_unit/repeat_count/interval_time/interval_time_unit |
| pump_four_channel_demo.yaml | 同上 |

**关键经验：**

1. **参数验证双重防护**：executor前置校验给出清晰步骤级错误日志，device_manager防御性校验确保无论调用来源如何非法参数不写入泵寄存器
2. **`!= 1` vs `> 1`**：repeat_count=0（无限重复）同样需要间隔时间，使用`!= 1`而非`> 1`避免漏校验
3. **单位参数必须归一化**：仅记录警告不设默认值会导致原始参数仍为None，后续代码误用会出错
4. **前端精度与步长必须匹配**：precision=3配合step=0.1导致无法精确输入3位小数，改为step=0.001

### 6.14 2026-05-11 项目规则重构与开发工具链完善（v2.9）

**规则文件重构：**

`heat.md` 从 265 行精简至 75 行，核心变更：

| 变更 | 说明 |
|------|------|
| 删除与 PROJECT_CONTEXT.md 重复内容 | 项目概述、架构约束、代码风格、线程安全规范均以上下文md为准 |
| 删除设备特定规则 | 蠕动泵参数、ECharts/Element Plus 规范移至上下文md |
| 提炼为通用行为准则 | 上下文优先、安全优先、稳定优先三大原则 |
| 简化开发流程 | 从4阶段流水线简化为5步：分析→开发→验证→自检→文档 |

**新增 Skill：**

| Skill | 路径 | 用途 |
|-------|------|------|
| `code-review` | `.trae/skills/code-review/SKILL.md` | 按项目规则执行代码质检，输出通过/不通过报告 |
| `doc-sync` | `.trae/skills/doc-sync/SKILL.md` | 分析变更后按需更新4份文档，提交并等用户确认推送 |

**命令触发：**

| 命令 | 行为 |
|------|------|
| `/review` | 使用 `code-review` Skill 审查代码 |
| `/git` | 编译验证 → `doc-sync` 更新文档 → 提交 → 用户确认后推送 |
| `/finish` | 自检 → 更新文档 → 归档变更记录 |

**关键经验：**

1. **规则文件与上下文文件职责分离**：heat.md 定义"怎么做"（行为准则），PROJECT_CONTEXT.md 定义"是什么"（项目知识），避免重复维护
2. **规则应通用而非具体**：设备参数、框架细节属于上下文，不属于规则；规则应跨设备、跨框架通用
3. **Skill 优于角色扮演**：单AI架构下，结构化 Skill（清单+模板）比"多智能体角色扮演"更可执行、可验证

### 6.15 2026-05-15 代码审查问题修复与依赖清理（v2.10）

**变更内容：**

| 类别 | 变更 | 涉及文件 |
|------|------|----------|
| 依赖管理 | 删除 `environment.yml` 中 3 行重复依赖（旧版本号 fastapi/uvicorn/websockets） | `environment.yml` |
| 依赖管理 | 补充 `pydantic>=2.0.0` 到 `pyproject.toml` 和 `requirements.txt` | `pyproject.toml`, `requirements.txt` |
| 配置加载 | `app.py` 改用 `ConfigManager` 加载配置，利用 dataclass 进行类型验证 | `src/web/app.py`, `src/utils/config.py` |
| CLI 泵支持 | `get_device_status`/`get_all_status`/`record_device_data` 增加泵设备遍历 | `src/main.py` |
| 代码重构 | `_start_pump_channel_inner` 拆分为 `_validate_pump_units`/`_validate_pump_repeat_params`/`_set_pump_flow_and_mode`/`_set_pump_mode_params` 4 个子函数 | `src/web/device_manager.py` |
| 前端拆分 | `ControlPanel.vue`（598行）拆分为 `HeaterControl.vue` + `PumpControl.vue` 子组件，父组件降至 402 行 | `frontend/src/views/ControlPanel.vue`, `frontend/src/components/HeaterControl.vue`, `frontend/src/components/PumpControl.vue` |
| 脚本清理 | 删除重复的 `chemical_synthesis_experiment.py`（690行），功能已由实验引擎替代 | `scripts/chemical_synthesis_experiment.py` |
| 文档更新 | 清理 `PROJECT_CONTEXT.md` 和 `README.md` 中引用已删除文件的过期路径 | `context/PROJECT_CONTEXT.md`, `README.md` |
| 缓存清理 | 删除 `scripts/__pycache__/` 中 13 个已删除脚本的 `.pyc` 残留（含 cpython-310/313 双版本） | `scripts/__pycache__/` |
| 审查报告 | 新增 `docs/code_review.md` 代码审查报告 | `docs/code_review.md` |

**经验教训：**

1. **依赖文件三份必须同步**：`pyproject.toml`/`requirements.txt`/`environment.yml` 任何一份变更后必须检查另外两份，避免版本号不一致和缺失依赖
2. **删除脚本后清理缓存**：`.pyc` 文件不会被 Git 跟踪（在 `.gitignore` 中），但残留会误导开发者以为脚本仍存在，删除 `.py` 源文件后应同步清理 `__pycache__/`
3. **前端组件拆分阈值**：单文件超过 400 行且包含两种以上独立功能时，应考虑拆分为子组件

### 6.16 2026-05-28 实验YAML metadata支持与samples.csv样品记录（v2.11）

**新增模块：`src/science/`**

| 文件 | 用途 |
|------|------|
| `sample_id.py` | `generate_sample_id()` / `generate_batch_id()` / `generate_condition_id()` |
| `sample_record.py` | `write_sample_record()`：自动创建目录、写 header、UTF-8 编码、防重复 run_id |

**metadata 从 YAML 到 samples.csv 的完整链路：**

```
YAML metadata → parser.py → web/api/experiments.py → engine.load_steps()
    → engine.start() → exp_logger.start_run()
        → generate_sample_id() → ExperimentRun.metadata
    → ... 状态机执行步骤 ...
    → exp_logger.finish_run()
        → _save_to_file() (JSON 日志)
        → _write_sample_record() → write_sample_record() → data/datasets/samples.csv
```

**YAML metadata 字段示例（`cspbbr3_baseline.yaml`）：**

```yaml
metadata:
  material_system: CsPbBr3
  batch_id: CsPbBr3_20260528_B01
  condition_id: T140_t180_R2
  sample_index: 3
  operator: WH
  recipe_version: v0.1
```

**samples.csv 格式：**

| 字段 | 说明 |
|------|------|
| sample_id | 样品编号（`{batch_id}_S{sample_index:03d}`） |
| batch_id | 批次编号（`{material_system}_{date}_B{number:02d}`） |
| condition_id | 条件编号 |
| run_id | 实验运行ID |
| recipe_file | YAML 文件名 |
| material_system | 材料体系 |
| operator | 操作员 |
| started_at / finished_at | 起止时间 |
| status | completed / failed / stopped |
| raw_log_path | JSON 日志路径 |
| notes | 备注 |
| error_flag | 失败实验为 true |

**关键设计决策：**

| 决策 | 原因 |
|------|------|
| sample_id 在 start_run 时生成，不在 finish_run | 保证样品编号在实验开始时就有，可随时引用 |
| sample_id 生成与 CSV 写入职责分离 | `sample_id.py` 只做编号逻辑，`sample_record.py` 只做 CSV I/O |
| 失败实验也写入 samples.csv 且 error_flag=true | 完整追踪所有实验，含失败案例 |
| `engine.load_steps(metadata=None)` 默认 None | 向后兼容，老 YAML 无 metadata 仍正常运行 |
| 无 metadata 时自动生成 sample_id | 老 YAML 运行后同样有样品记录 |

**涉及文件：**

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/science/__init__.py` | 新增 | 包声明 |
| `src/science/sample_id.py` | 新增 | ID 生成逻辑 |
| `src/science/sample_record.py` | 新增 | CSV 写入逻辑（含异常处理） |
| `src/experiment/parser.py` | 修改 | 解析 YAML metadata 字段，无则返回 `{}` |
| `src/experiment/engine.py` | 修改 | `load_steps()` 增加 `metadata=None` 参数 |
| `src/experiment/experiment_logger.py` | 修改 | `start_run()` 生成 sample_id；`finish_run()` 写入 samples.csv |
| `src/web/api/experiments.py` | 修改 | 传递 metadata 到 engine |
| `experiments/cspbbr3_baseline.yaml` | 新增 | 带 metadata 的示例 YAML |
| `tests/test_metadata.py` | 新增 | 17 个测试覆盖所有场景 |

**经验教训：**

1. **职责分离优于单体模块**：将 ID 生成与 CSV 写入分离，使两个模块各司其职、独立可测
2. **向后兼容靠默认值**：`metadata=None` 配合 `or {}` 确保老代码无需修改
3. **防御性异常处理**：`_ensure_dir()` 的 `mkdir` 需 try/except，否则权限不足等场景会静默崩溃（已在 review 中修复）
4. **冗余代码清理**：`merged_metadata.get("sample_index", merged_metadata.get("sample_index", 1))` 内层 get 多余，简化为 `merged_metadata.get("sample_index", 1)`（已在 review 中修复）


### 6.17 2026-05-28 sample_id唯一性修复、API metadata增强、raw_log_path修复（v2.12）

**问题修复：**

| 问题 | 修复方案 |
|------|---------|
| sample_id 可能重复（写死 batch_id+sample_index） | 新增 `generate_unique_sample_id()`，自动递增至不重复 |
| GET /experiments/{filename} 不返回 metadata | 增加 `metadata: data.get("metadata", {})` |
| POST start 不返回 sample_id | 增加 `sample_id` 和 `metadata` 字段 |
| save_log=False 时写入假路径 | 条件判断：save_log=True 才写真实路径，否则空字符串 |
| cspbbr3_baseline.yaml 描述不清 | 改为 `metadata demo / heating-only placeholder, not full synthesis recipe` |
| CSV 写入失败会中断实验 | `finish_run()` 中 `_write_sample_record()` 包裹 try/except |

**新增函数：**

| 函数 | 位置 | 说明 |
|------|------|------|
| `existing_sample_ids()` | `src/science/sample_record.py` | 从 samples.csv 读取已存在的所有 sample_id |
| `generate_unique_sample_id(metadata: dict) -> str` | `src/science/sample_id.py` | 唯一 sample_id 生成，策略见下 |

**sample_id 唯一性生成规则：**

| 场景 | 策略 |
|------|------|
| 显式提供 sample_id，未重复 | 直接使用 |
| 显式提供 sample_id，已重复 | 日志警告 + 基于 batch_id/sample_index 递增 |
| 无 sample_id，有 batch_id+sample_index | 生成基础 ID，自动递增至不重复 |
| 无 batch_id | `UNKNOWN_{日期}_B01` 前缀，同样保证唯一 |

**API 接口变更：**

| 接口 | 新增字段 |
|------|---------|
| `GET /experiments/{filename}` | `metadata` |
| `POST /experiments/{filename}/start` | `sample_id`, `metadata` |

**涉及文件：**

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/science/sample_id.py` | 修改 | 新增 `generate_unique_sample_id()` + logger |
| `src/science/sample_record.py` | 修改 | 新增 `existing_sample_ids()` |
| `src/experiment/experiment_logger.py` | 修改 | 使用 `generate_unique_sample_id()`；raw_log_path 条件设置；CSV 写入 try/except |
| `src/web/api/experiments.py` | 修改 | GET 返回 metadata；POST 返回 sample_id+metadata |
| `experiments/cspbbr3_baseline.yaml` | 修改 | description 注明为 placeholder |
| `tests/test_metadata.py` | 修改 | 25 个测试（+8 个新测试） |

**经验教训：**

1. **ID 唯一性必须对 CSV 已有记录做去重**：仅靠 run_id 去重不够，sample_id 也必须独立保证唯一
2. **显式 sample_id 重复时不应报错，应自动处理并警告**：避免中断实验流程
3. **API 返回 sample_id 和 metadata**：让前端和操作者可以在启动前/后看到样品信息
4. **save_log 与 raw_log_path 必须一致**：避免写入不存在的日志路径

### 6.18 2026-05-29 全局单实验保护、metadata边界修复、类型规范化（v2.13）

**问题修复：**

| 问题 | 修复方案 |
|------|---------|
| 只阻止同一 filename 重复启动，不同 filename 可并行运行（争用硬件） | 新增 `_get_active_engine()`，任何 running/paused 引擎都阻止新实验 → HTTP 409 |
| 旧引擎 completed/failed/stopped 后不清理，累积占用内存 | 启动新实验前自动清理已结束的引擎 |
| `start_run()` 中 `metadata or {}` 可能原地修改 parser 返回的原始 dict | 改为 `dict(metadata or {})` 浅拷贝 |
| `sample_index` 来自 YAML 或前端时可能是字符串，导致格式化失败 | 新增 `_normalize_sample_index()`，统一 int 转换 + fallback 到 1 |
| `existing_sample_ids()` / `_existing_run_ids()` 读取异常时静默 pass | 改为 `logger.warning()` 记录异常信息 |
| `write_sample_record()` 写入重复 sample_id 时无提示 | 新增 `existing_sample_ids()` 检查，重复时记录 warning |

**新增函数：**

| 函数 | 位置 | 说明 |
|------|------|------|
| `_get_active_engine()` | `src/web/api/experiments.py` | 遍历 `_engines` 查找 running/paused 状态的引擎，返回 `(filename, engine)` |
| `_normalize_sample_index(sample_index) -> int` | `src/science/sample_id.py` | 将 sample_index 统一转为 int；None/""/非数字/≤0 → 1 |

**全局单实验保护逻辑：**

```
启动新实验
  ├── 清理 completed/failed/stopped 的旧引擎
  ├── _get_active_engine() 检查是否有 running/paused 引擎
  │   ├── 有 → HTTP 409，返回活动引擎 filename + state
  │   └── 无 → 继续
  └── 创建新引擎并启动
```

**API 行为变更：**

| 场景 | 旧行为 | 新行为 |
|------|--------|--------|
| 实验A running，启动实验B | 允许并行运行 | HTTP 409: `'expA.yaml' is still running` |
| 实验A paused，启动实验B | 允许并行运行 | HTTP 409: `'expA.yaml' is still paused` |
| 实验A completed，启动实验B | 旧引擎残留 | 自动清理旧引擎，允许启动 |

**涉及文件：**

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/web/api/experiments.py` | 修改 | 新增 `_get_active_engine()`；启动前清理旧引擎 + 全局活动检查 |
| `src/experiment/experiment_logger.py` | 修改 | `metadata or {}` → `dict(metadata or {})` |
| `src/science/sample_id.py` | 修改 | 新增 `_normalize_sample_index()`；`generate_sample_id` / `generate_unique_sample_id` 使用 |
| `src/science/sample_record.py` | 修改 | 异常时记录 warning；`write_sample_record()` 重复 sample_id 警告 |
| `tests/test_metadata.py` | 修改 | 32 个测试（+7 个新测试，覆盖引擎保护、metadata 不修改、类型规范化等） |

**经验教训：**

1. **单套硬件必须全局单实验保护**：不同 YAML 文件可能争用同一套泵、温控器、串口，必须阻止并行运行
2. **metadata 必须防御性拷贝**：`dict(metadata or {})` 避免修改 parser 返回的共享对象
3. **YAML/前端传来的数值类型不可信**：必须做类型规范化，sample_index 可能是 str/int/None
4. **静默吞异常是隐患**：数据读取异常必须记录日志，否则可能误判"无已有数据"导致重复编号
