# Heat 开发者维护教程

面向项目开发者与AI辅助开发，介绍项目架构、开发规范、调试方法与维护流程。

---

## 目录

1. [项目架构总览](#1-项目架构总览)
2. [核心设计约束](#2-核心设计约束)
3. [开发环境搭建](#3-开发环境搭建)
4. [代码结构详解](#4-代码结构详解)
5. [添加新设备驱动](#5-添加新设备驱动)
6. [Web层开发](#6-web层开发)
7. [实验引擎扩展](#7-实验引擎扩展)
8. [线程安全规范](#8-线程安全规范)
9. [Git分支管理](#9-git分支管理)
10. [AI辅助开发指南](#10-ai辅助开发指南)
11. [调试与排错](#11-调试与排错)
12. [代码审查清单](#12-代码审查清单)

---

## 1. 项目架构总览

```
┌─────────────────────────────────────────────────────────────┐
│                 frontend/ (Web前端 - Vue 3)                   │
│   Dashboard.vue, ControlPanel.vue, ExperimentPage.vue       │
└─────────────────────────────────────────────────────────────┘
                              │ WebSocket + REST API
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                  web/ (Web服务层 - FastAPI)                    │
│   app.py, device_manager.py, api/devices.py, api/ws.py      │
│   关键：run_in_executor 桥接同步设备与异步框架                  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│               experiment/ (实验自动化引擎)                      │
│   parser.py → engine.py → executor.py → actions.py          │
│   关键：YAML解析 → 状态机调度 → 步骤执行                       │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    devices/ (设备驱动层)                      │
│   base_device.py, heater.py, peristaltic_pump.py            │
│   关键：纯同步、无线程，RLock保护串口访问                       │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    protocols/ (协议层)                        │
│   aibus.py, modbus_rtu.py, pump_params.py                   │
│   关键：协议编解码，不持有状态                                  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    utils/ (工具层)                            │
│   serial_manager.py, config.py, csv_logger.py               │
│   关键：串口单例管理，配置过滤，数据大小限制                     │
└─────────────────────────────────────────────────────────────┘
```

### 数据流

```
用户操作 → FastAPI → run_in_executor → 设备方法（同步）→ 协议层 → 串口
                                                              ↓
WebSocket推送 ← FastAPI ← 设备read_data ← 协议层 ← 串口响应
```

---

## 2. 核心设计约束

### 约束1：设备驱动必须是纯同步、无线程

**原因**：串口通信天然是请求-响应模式，多线程并发访问串口会导致数据混乱。

**规则**：
- 设备驱动（`devices/`）内部**禁止**创建线程
- 所有设备方法都是同步阻塞调用
- 使用 `threading.RLock` 保护串口访问，防止Web层并发调用
- 锁范围最小化：仅保护协议通信，计算逻辑在锁外

### 约束2：协议层不持有状态

**原因**：协议对象可能被多个设备共享（同一串口）。

**规则**：
- 协议类（`protocols/`）只负责编解码
- 不缓存数据，不维护设备状态
- 每次调用都是独立的请求-响应

### 约束3：Web层通过 run_in_executor 桥接

**原因**：FastAPI是异步框架，设备方法是同步阻塞的。

**规则**：
- 所有设备操作必须通过 `run_in_executor` 调用
- 禁止在 async 函数中直接调用设备方法
- WebSocket推送在独立的定时任务中执行

### 约束4：锁范围最小化

**原因**：锁范围过大会导致死锁和不必要的阻塞。

**规则**：
- 锁仅保护共享资源（串口协议调用、状态变量）
- I/O操作（协议通信）在锁内执行（串口必须互斥）
- 纯计算逻辑（数据解析、对象构造）在锁外执行
- connect方法：锁仅保护状态检查和设置，协议通信在锁外

---

## 3. 开发环境搭建

### Python后端

```bash
git clone https://gitee.com/wh158958/heat.git
cd heat
conda env create -f environment.yml
conda activate heat
```

### Vue前端

```bash
cd frontend
npm install
npm run dev      # 开发模式（热重载，端口5173）
npm run build    # 生产构建 → src/web/static/
```

> **注意**：`vite.config.ts` 已配置 `build.outDir` 指向 `src/web/static/`，构建产物直接输出到后端静态文件目录。构建后重启Web服务器，浏览器按 `Ctrl+Shift+R` 强制刷新。

### 验证环境

```bash
python -m py_compile src/devices/heater.py   # 编译检查
python -m py_compile src/web/app.py          # Web层检查
python scripts/test_connections.py           # 硬件连接测试
```

---

## 4. 代码结构详解

### 设备驱动层 (`src/devices/`)

| 文件 | 职责 |
|------|------|
| `base_device.py` | 基类：状态管理、回调、重试机制 |
| `heater.py` | 加热器：AI-BUS协议，温度控制 |
| `peristaltic_pump.py` | 蠕动泵：MODBUS-RTU协议，多通道控制 |

**BaseDevice 关键机制**：

```python
class BaseDevice:
    _lock: RLock              # 保护串口访问（可重入）
    _callback_lock: Lock      # 保护回调列表（在_callbacks之前初始化）
    _status: DeviceStatus     # 设备状态（通过property setter触发回调）
    
    def execute_with_retry()  # 重试机制（retry_count >= 1）
    def _notify_status_change()  # 状态变更通知（锁内复制回调列表，锁外执行）
```

**Heater 关键机制**：

```python
class AIHeaterDevice(BaseDevice):
    connect()    # 锁仅保护状态，协议通信在锁外
    read_data()  # 锁仅保护协议调用，数据解析在锁外
    _safe_run_status()  # 枚举越界保护
    wait_for_temperature()  # 连接检查 + 轮询
```

**Pump 关键机制**：

```python
class LabSmartPumpDevice(BaseDevice):
    _write_float_with_unit()  # 先写单位(0x06)，再写浮点数(0x10)
    _safe_enum()              # 枚举越界保护
    channel_data              # 返回deepcopy，防止外部修改
    _force_disconnect()       # 非阻塞锁获取（atexit安全）
    set_tube_model()          # 验证范围0-13，防止无效型号损坏寄存器
```

**Pump 运行模式参数规则（重要）**：

| 参数 | 可设置的模式 | 不可设置的模式 |
|------|-------------|---------------|
| 流速(n110) | 仅流量模式(0) | 定时定量/定时定速/定量定速 ❌ |
| 运行时间(n107) | 定时定量(1)/定时定速(2) | 流量模式 ❌ |
| 分装液量(n104) | 定时定量(1)/定量定速(3) | 流量模式 ❌ |

非流量模式启动流程：先切流量模式设流速 → 再切目标模式设其他参数 → 启动。

流速单位(n112)仅接受 1(mL/min) 和 3(RPM)，0 和 2 返回 ILLEGAL_DATA_VALUE。

### 协议层 (`src/protocols/`)

| 文件 | 职责 |
|------|------|
| `aibus.py` | AI-BUS协议：读写参数、CRC校验 |
| `modbus_rtu.py` | MODBUS-RTU：功能码03/06/16、CRC-16 |
| `parameters.py` | 加热器参数码定义 |
| `pump_params.py` | 泵寄存器地址映射 |

**协议层关键点**：
- `_receive_frame()` 不完整帧返回 `None`（不返回部分数据）
- `_send_and_receive()` 写入后调用 `flush()` 确保数据发出
- `close()` 异常时返回 `False`

### Web层 (`src/web/`)

| 文件 | 职责 |
|------|------|
| `app.py` | FastAPI入口、SPA路由、静态文件 |
| `device_manager.py` | 设备实例管理、桥接Web与设备 |
| `api/devices.py` | REST API：连接/控制/数据 |
| `api/ws.py` | WebSocket：1Hz实时数据推送 |
| `api/experiments.py` | 实验管理API（含路径遍历防护、日志保存开关、历史记录删除） |

**Web层关键点**：
- SPA路由：所有非 `/api/` 路径返回 `index.html`
- `run_in_executor`：所有设备操作通过线程池执行
- 路径遍历防护：`_validate_filename()` 校验文件名
- 实验启动：`StartExperimentRequest` 包含 `save_log` 字段控制日志保存
- 历史记录：支持 DELETE 单条/全部删除

### 实验引擎 (`src/experiment/`)

| 文件 | 职责 |
|------|------|
| `parser.py` | YAML解析 + 文件名校验 |
| `engine.py` | 状态机：IDLE/RUNNING/PAUSED/COMPLETED/FAILED/STOPPED |
| `executor.py` | 步骤执行器：调用DeviceManager |
| `actions.py` | 9种动作 + 4种等待条件定义 |

---

## 5. 添加新设备驱动

### 步骤1：创建配置类

```python
# src/devices/new_device.py
from dataclasses import dataclass, field
from devices.base_device import DeviceConfig

@dataclass
class NewDeviceConfig(DeviceConfig):
    custom_param: str = "default"
    channels: list = field(default_factory=list)
```

### 步骤2：实现设备类

```python
from devices.base_device import BaseDevice, DeviceStatus
from protocols.your_protocol import YourProtocol

class NewDevice(BaseDevice):
    def __init__(self, config: NewDeviceConfig):
        super().__init__(config)
        self._config = config
        self._protocol = None
    
    def connect(self) -> bool:
        with self._lock:
            if self.is_connected():
                return True
            self.status = DeviceStatus.CONNECTING
        
        try:
            protocol = YourProtocol(...)
            protocol.connect()
            
            with self._lock:
                self._protocol = protocol
                self.status = DeviceStatus.CONNECTED
            return True
        except Exception as e:
            with self._lock:
                self.status = DeviceStatus.ERROR
            self._logger.error(f"Connect failed: {e}")
            return False
    
    def disconnect(self) -> bool:
        with self._lock:
            if self._protocol is not None:
                self._protocol.disconnect()
                self._protocol = None
            self.status = DeviceStatus.DISCONNECTED
        return True
    
    def emergency_stop(self):
        with self._lock:
            if self._protocol is not None:
                self._protocol.emergency_stop()
    
    def read_data(self):
        def _read():
            with self._lock:
                return self._protocol.read_all()
        
        data = self.execute_with_retry(
            _read,
            operation_name="read_data"
        )
        return self._parse_data(data)
```

### 步骤3：注册到DeviceManager

```python
# src/web/device_manager.py
from devices.new_device import NewDevice, NewDeviceConfig

class DeviceManager:
    def add_new_device(self, device_id, port, **kwargs):
        config = NewDeviceConfig(
            device_id=device_id,
            connection_params={"port": port, ...},
            **kwargs
        )
        device = NewDevice(config)
        self._new_devices[device_id] = device
        return device
```

### 步骤4：添加Web API

```python
# src/web/api/devices.py - 添加新的路由
@router.post("/devices/{device_id}/custom-action")
async def custom_action(device_id: str, ...):
    device = manager.get_device(device_id)
    result = await asyncio.get_event_loop().run_in_executor(
        None, device.custom_action, ...
    )
    return {"success": result}
```

### 步骤5：添加实验动作

```python
# src/experiment/actions.py - 添加新动作类型
class ActionType(str, Enum):
    ...
    CUSTOM_ACTION = "custom_action"

# src/experiment/executor.py - 添加执行逻辑
async def _execute_custom_action(self, params):
    device = self._device_manager.get_device(params["device_id"])
    return await asyncio.get_event_loop().run_in_executor(
        None, device.custom_action, params["param"]
    )
```

---

## 6. Web层开发

### 前端开发流程

1. 启动前端开发服务器：`cd frontend && npm run dev`
2. 修改Vue组件（热重载自动刷新）
3. 构建生产版本：`npm run build`
4. 产物自动输出到 `src/web/static/`

### 添加新页面

1. 在 `frontend/src/views/` 创建 `.vue` 文件
2. 在 `frontend/src/router/index.ts` 添加路由
3. 在 `App.vue` 导航栏添加链接
4. 构建部署

### WebSocket数据格式

服务端每秒推送：

```json
{
    "type": "device_data",
    "timestamp": "2026-04-24T10:30:00",
    "heaters": {
        "heater1": {"pv": 85.3, "sv": 100.0, "mv": 65, "status": "connected"}
    },
    "pumps": {
        "pump1": {
            "channels": {
                "1": {"flow_rate": 5.0, "running": true, "dispensed_volume": 12.5}
            }
        }
    }
}
```

### 添加新API端点

```python
# src/web/api/devices.py
@router.get("/devices/{device_id}/custom")
async def get_custom_data(device_id: str):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, manager.get_custom_data, device_id
    )
    return result
```

**注意**：所有设备操作必须通过 `run_in_executor`，禁止直接调用。

---

## 7. 实验引擎扩展

### 添加新动作类型

1. 在 `actions.py` 的 `ActionType` 枚举中添加新类型
2. 在 `executor.py` 的 `_execute_step()` 中添加处理分支
3. 在前端 `ExperimentPage.vue` 中添加对应的步骤显示

### 添加新等待条件

1. 在 `actions.py` 的 `WaitConditionType` 中添加
2. 在 `executor.py` 的 `_wait_for_condition()` 中添加检查逻辑
3. 等待条件必须支持暂停检查

---

## 8. 线程安全规范

### 锁使用规则

| 场景 | 锁类型 | 范围 |
|------|--------|------|
| 串口协议调用 | `self._lock` (RLock) | 仅包裹协议读写 |
| 状态变量读写 | `self._lock` | 仅包裹赋值 |
| 回调列表操作 | `self._callback_lock` (Lock) | 仅包裹列表修改/复制 |
| 全局单例创建 | `threading.Lock` | 双重检查锁 |

### 锁初始化顺序

```python
def __init__(self):
    self._callback_lock = threading.Lock()  # 先于 _callbacks
    self._callbacks = []
    self._lock = threading.RLock()          # 保护串口
```

### connect方法锁模式

```python
def connect(self) -> bool:
    with self._lock:                    # 锁内：状态检查
        if self.is_connected():
            return True
        self.status = DeviceStatus.CONNECTING
    
    # 锁外：协议通信（可能耗时）
    protocol = create_protocol(...)
    protocol.connect()
    
    with self._lock:                    # 锁内：状态更新
        self._protocol = protocol
        self.status = DeviceStatus.CONNECTED
    return True
```

### read_data方法锁模式

```python
def read_data(self):
    def _read():
        with self._lock:                # 锁内：协议调用
            raw = self._protocol.read()
            current_status = self._status
        return raw, current_status
    
    raw, status = self.execute_with_retry(_read, ...)
    # 锁外：数据解析、对象构造
    return self._parse(raw, status)
```

### atexit回调锁模式

```python
def _force_disconnect(self):
    try:
        if self._lock.acquire(blocking=False):  # 非阻塞
            try:
                self._protocol.disconnect()
                self._protocol = None
                self._closed = True
            finally:
                self._lock.release()
        else:
            self._closed = True  # 获取不到锁，至少标记关闭
    except Exception:
        pass
```

### 常见陷阱

| 陷阱 | 正确做法 |
|------|----------|
| `x or default` | `x if x is not None else default` |
| `RunStatus(val)` | `_safe_enum(RunStatus, val, RunStatus.STOP)` |
| 返回内部可变对象 | `return copy.deepcopy(self._data)` |
| 锁内执行耗时I/O | 缩小锁范围，I/O在锁外 |
| `retry_count=0` 崩溃 | `retry_count = max(config.retry_count, 1)` |

---

## 9. Git分支管理

### 分支策略

```
master (主分支)
  │
  ├── develop-web (Web开发分支)
  │     │
  │     └── feature/xxx (功能分支)
  │
  └── hotfix/xxx (紧急修复分支)
```

### 日常开发流程

```bash
# 在功能分支开发
git checkout develop-web
git checkout -b feature/new-sensor

# 开发完成后合并
git add .
git commit -m "feat: add new sensor driver"
git checkout develop-web
git merge feature/new-sensor

# 测试通过后合并到master
git checkout master
git merge develop-web

# 推送到两个远程
git push gitee master
git push github master
```

### 双远程同步

```bash
# 查看远程
git remote -v

# 推送到两个远程
git push gitee --all
git push github --all
```

---

## 10. AI辅助开发指南

### 新对话启动

每次新开AI对话时，首先提供项目上下文：

```
@context/PROJECT_CONTEXT.md
```

这会让AI了解项目架构、设计约束和历史经验。

### 高效提问模式

| 场景 | 推荐提问方式 |
|------|-------------|
| 修复Bug | "验证问题的存在性并进行修复：标题:xxx 详情:xxx" |
| 代码审查 | "对整个项目进行审查" |
| 添加功能 | "实现xxx功能，参考现有xxx的模式" |
| 架构设计 | "xxx应该怎么设计，给出完整流程" |
| 更新文档 | "更新上下文md、README" |

### AI开发注意事项

1. **验证后再修复**：AI可能误判问题，要求"验证问题的存在性"
2. **编译检查**：修改后必须运行 `py_compile` 验证
3. **遵循约束**：提醒AI"设备驱动必须是纯同步无线程"
4. **锁规范**：提醒AI"锁范围最小化，I/O在锁外"
5. **不添加注释**：项目约定不添加代码注释

### 项目上下文维护

每次重大变更后更新 `context/PROJECT_CONTEXT.md`：

- 版本号递增
- 架构图更新
- 新增模块说明
- 关键经验记录
- Bug修复记录

---

## 11. 调试与排错

### 串口调试

```python
# 查看可用串口
import serial.tools.list_ports
for port in serial.tools.list_ports.comports():
    print(port.device, port.description)

# 直接发送MODBUS命令
import serial
ser = serial.Serial('COM10', 9600, timeout=1)
ser.write(bytes.fromhex('010300000002C40B'))
response = ser.read(20)
print(response.hex())
```

### 设备诊断

```bash
# 加热器诊断
python tests/diagnose.py

# 蠕动泵诊断
python tests/diagnose_pump.py

# TTL信号诊断
python tests/diagnose_ttl.py
```

### Web服务调试

```bash
# 启动带日志的Web服务
python -c "
import uvicorn
from src.web.app import create_app
app = create_app()
uvicorn.run(app, host='0.0.0.0', port=8000, log_level='debug')
"

# 测试API端点
curl -v http://localhost:8000/api/devices/status
curl -v http://localhost:8000/api/experiments/
```

### 前端调试

1. 浏览器F12打开开发者工具
2. Console查看错误
3. Network查看API请求
4. WebSocket查看实时数据帧

### 日志配置

设备驱动使用Python标准logging，日志级别：

```python
self._logger.debug("详细调试信息")    # 协议通信细节
self._logger.info("正常操作信息")     # 连接/断开
self._logger.warning("警告信息")      # 非致命错误
self._logger.error("错误信息")        # 操作失败
```

---

## 12. 代码审查清单

### 安全性

- [ ] 路径遍历：文件名参数是否校验
- [ ] 注入风险：用户输入是否过滤
- [ ] 资源泄露：串口是否正确关闭
- [ ] 紧急停止：是否能可靠停止所有设备

### 线程安全

- [ ] 共享资源是否加锁
- [ ] 锁范围是否最小化
- [ ] 锁初始化是否先于被保护数据
- [ ] atexit回调是否非阻塞
- [ ] `or` 是否误用（应为 `is not None`）
- [ ] 枚举转换是否有越界保护
- [ ] 可变对象是否返回深拷贝

### 协议层

- [ ] 不完整帧是否拒绝（返回None）
- [ ] 写入后是否flush
- [ ] CRC校验是否正确
- [ ] 超时处理是否合理

### 设备层

- [ ] connect/disconnect是否有锁保护
- [ ] connect锁范围是否最小化
- [ ] read_data锁范围是否最小化
- [ ] emergency_stop是否有null检查
- [ ] execute_with_retry的retry_count是否 >= 1

### Web层

- [ ] 设备操作是否通过run_in_executor
- [ ] SPA路由是否正确
- [ ] 静态文件路径是否正确
- [ ] API参数是否校验

### 编译验证

```bash
# 批量编译检查
python -m py_compile src/devices/base_device.py
python -m py_compile src/devices/heater.py
python -m py_compile src/devices/peristaltic_pump.py
python -m py_compile src/protocols/aibus.py
python -m py_compile src/protocols/modbus_rtu.py
python -m py_compile src/web/app.py
python -m py_compile src/experiment/engine.py
```

---

## 附录：关键文件速查

| 需求 | 文件 |
|------|------|
| 添加新设备 | `src/devices/` + `src/web/device_manager.py` |
| 修改协议 | `src/protocols/` |
| 添加Web API | `src/web/api/` |
| 添加实验动作 | `src/experiment/actions.py` + `executor.py` |
| 修改前端页面 | `frontend/src/views/` |
| 修改配置 | `config/system_config.yaml` |
| 查看项目历史 | `context/PROJECT_CONTEXT.md` |
| 用户教程 | `docs/user_guide.md` |
