# PROJECT_CONTEXT.md

> **项目级 AI 记忆库 + 开发者交接手册**
> 
> 最后更新：2026-04-15
> 版本：v1.5

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
│                    scripts/ (实验脚本层)                      │
│         heater_pump_safe.py, test_pump_safe.py              │
│         职责：实验流程编排，不涉及设备细节                        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    devices/ (设备驱动层)                      │
│         heater.py, safe_pump.py, peristaltic_pump.py        │
│         职责：设备控制逻辑，封装通信细节                          │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    protocols/ (协议层)                        │
│         modbus_rtu.py, pump_params.py                       │
│         职责：通信协议实现，寄存器映射                           │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    utils/ (工具层)                            │
│         serial_manager.py, device_safety.py, config.py      │
│         职责：资源管理、安全机制、配置解析                        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    config/ (配置层)                           │
│         system_config.yaml                                   │
│         职责：设备参数、串口配置、实验参数                        │
└─────────────────────────────────────────────────────────────┘
```

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
│   ├── README.md               # 项目说明
│   └── presentation.md         # 演示文档
├── scripts/
│   ├── heater_pump_integration.py  # 原集成脚本
│   ├── heater_pump_safe.py         # 安全集成脚本
│   ├── test_pump_only.py           # 原测试脚本
│   └── test_pump_safe.py           # 安全测试脚本
├── src/
│   ├── devices/
│   │   ├── base_device.py      # 设备基类
│   │   ├── heater.py           # 加热器驱动
│   │   ├── peristaltic_pump.py # 蠕动泵驱动(基础)
│   │   └── safe_pump.py        # 蠕动泵驱动(安全增强)
│   ├── protocols/
│   │   ├── modbus_rtu.py       # MODBUS协议
│   │   └── pump_params.py      # 泵参数定义
│   └── utils/
│       ├── config.py           # 配置管理
│       ├── serial_manager.py   # 串口资源管理
│       └── device_safety.py    # 设备安全基类
├── tests/
│   └── diagnose_pump.py        # 诊断工具
├── environment.yml             # Conda环境配置
└── requirements.txt            # pip依赖列表
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

### 5.2 蠕动泵 (LabSmartPumpDevice / SafePumpDevice)

| 属性 | 值 |
|------|-----|
| 设备类型 | LabSmart 多通道蠕动泵 |
| 通信协议 | MODBUS RTU |
| 默认串口 | COM10 |
| 波特率 | 9600 |
| 校验位 | N |
| 通道数 | 4 |

**核心功能：**
- 四通道独立控制
- 四种运行模式：流量、定时定量、定时定速、定量定速
- 启停、换向、速度控制
- 流量校准

**关键类：**

| 类 | 用途 |
|---|------|
| `LabSmartPumpDevice` | 基础驱动，直接操作串口 |
| `SafePumpDevice` | 安全增强版，命令队列 + 通道隔离 |
| `ChannelTask` | 通道任务定义 |

**开发经验：**

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| 串口被占用 | 进程被强制终止，串口未释放 | 使用 `SerialPortManager` + 锁文件 |
| 通道互相影响 | 共享串口，无隔离 | `SafePumpDevice` 命令队列 |
| 程序无法退出 | `daemon=True` 线程卡死 | `daemon=False` + 停止标志 |
| 读取超时 | 串口阻塞 | 设置 `timeout` + 超时重试 |
| 校验位错误 | 设备默认偶校验 | 确认设备配置，使用 N |

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
[日期] [问题/功能]
- 问题现象：
- 根本原因：
- 解决方案：
- 经验教训：
```

---

## 附录

### A. 快速启动命令

```bash
# 测试蠕动泵
python scripts/test_pump_safe.py --port COM10 --force

# 运行集成实验
python scripts/heater_pump_safe.py --heater-ports COM7 COM9 --pump-port COM10 --force

# 诊断串口
python tests/diagnose_pump.py
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

**或使用 pip + venv：**

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

**可选依赖：**

```bash
pip install pywin32  # Windows 强制释放串口
```

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
