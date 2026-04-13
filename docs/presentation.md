---
# 组会汇报：自动化控制系统

# 从通信协议到项目实现

---

# 目录

- 串口通信原理
- RS232与RS485对比
- Python串口编程
- Python自动化控制原理
- AIBUS协议详解
- 项目架构设计
- 核心代码实现
- 演示与总结

---

# 一、串口通信原理

## 什么是串口通信？

串口通信是一种**逐位传输**数据的通信方式：

- 数据按**位(bit)**顺序依次传输
- 只需**少量线路**即可实现
- 适合**远距离**通信

<!-- 图片位置：串口通信示意图 -->
<!--
![串口通信示意图](./images/serial_communication.png)
-->

---

# 串口通信 vs 并口通信

| 特性 | 串口通信 | 并口通信 |
|------|----------|----------|
| 传输方式 | 逐位传输 | 多位同时传输 |
| 线路数量 | 少(2-4根) | 多(8根以上) |
| 传输距离 | 远(可达千米) | 近(通常<1米) |
| 抗干扰能力 | 强 | 弱 |
| 应用场景 | 工业控制、传感器 | 打印机、内部总线 |

<!-- 图片位置：串口与并口对比图 -->
<!--
![串口与并口对比](./images/serial_vs_parallel.png)
-->

---

# 串口数据帧结构

一个完整的串口数据帧包含：

```
┌────────┬────────┬──────────┬────────┬────────┐
│ 起始位 │ 数据位 │ 校验位   │ 停止位 │ 空闲位 │
│  1 bit │ 5-8bit │ 0/1 bit  │ 1-2bit │ 不定   │
└────────┴────────┴──────────┴────────┴────────┘
```

**示例**：发送字符 'A' (ASCII: 0x41 = 01000001)

```
空闲  起始  D0 D1 D2 D3 D4 D5 D6 D7  停止  空闲
 1     0    1  0  0  0  0  0  1  0    1     1
       └────────────────────────────┘
              一个完整帧
```

---

# 串口通信参数详解

| 参数 | 说明 | 常见值 | 作用 |
|------|------|--------|------|
| 波特率 | 每秒传输位数 | 9600, 19200, 115200 | 决定传输速度 |
| 数据位 | 每帧数据位数 | 7, 8 | 决定数据范围 |
| 校验位 | 数据校验方式 | 无(N), 奇(O), 偶(E) | 检测传输错误 |
| 停止位 | 帧结束标志 | 1, 2 | 同步时序 |

**常见配置**：`9600,8,N,1`（9600波特率，8数据位，无校验，1停止位）

---

# 波特率与传输速度

```
波特率 9600 bps:
- 每秒传输 9600 位
- 每帧约 10 位 (1起始 + 8数据 + 1停止)
- 每秒传输约 960 字节
- 每字节传输时间 ≈ 1.04 ms
```

| 波特率 | 字节/秒 | 典型应用 |
|--------|---------|----------|
| 9600 | ~960 | 工业仪表、传感器 |
| 19200 | ~1920 | PLC通信 |
| 115200 | ~11520 | 调试下载、高速通信 |

---

# 二、电平标准与接口

## TTL电平

TTL (Transistor-Transistor Logic) 是最常见的数字电平：

| 逻辑 | 电压范围 | 典型值 |
|------|----------|--------|
| 逻辑1 (高) | 2.4V ~ 5V | 3.3V / 5V |
| 逻辑0 (低) | 0V ~ 0.4V | 0V |

<!-- 图片位置：TTL电平示意图 -->
<!--
![TTL电平](./images/ttl_level.png)
-->

---

# RS232电平

RS232是计算机串口标准，电平与TTL相反：

| 逻辑 | 电压范围 | 说明 |
|------|----------|------|
| 逻辑1 (高) | -15V ~ -3V | 负电压 |
| 逻辑0 (低) | +3V ~ +15V | 正电压 |

**注意**：RS232电平不能直接连接TTL设备，需要电平转换！

<!-- 图片位置：RS232电平示意图 -->
<!--
![RS232电平](./images/rs232_level.png)
-->

---

# RS485电平

RS485采用**差分信号**传输，抗干扰能力强：

| 特性 | 说明 |
|------|------|
| 传输方式 | 差分信号 (A-B) |
| 逻辑1 | A - B > +200mV |
| 逻辑0 | A - B < -200mV |
| 最大距离 | 1200米 |
| 最大设备数 | 32个节点 |

<!-- 图片位置：RS485差分信号图 -->
<!--
![RS485差分信号](./images/rs485_differential.png)
-->

---

# RS232 vs RS485 对比

| 特性 | RS232 | RS485 |
|------|-------|-------|
| 传输模式 | 单端信号 | 差分信号 |
| 传输距离 | <15米 | <1200米 |
| 通信方式 | 点对点 | 多点总线 |
| 抗干扰能力 | 弱 | 强 |
| 典型应用 | 短距离调试 | 工业现场 |

<!-- 图片位置：RS232与RS485对比图 -->
<!--
![RS232 vs RS485](./images/rs232_vs_rs485.png)
-->

---

# 串口引脚定义

## RS232 (DB9接口)

| 引脚 | 名称 | 方向 | 功能 |
|------|------|------|------|
| 2 | RXD | 输入 | 接收数据 |
| 3 | TXD | 输出 | 发送数据 |
| 5 | GND | - | 信号地 |
| 7 | RTS | 输出 | 请求发送 |
| 8 | CTS | 输入 | 清除发送 |

<!-- 图片位置：DB9接口引脚图 -->
<!--
![DB9引脚定义](./images/db9_pinout.png)
-->

---

# TTL/RS485 接线方式

## TTL串口 (3线制)

```
设备A              设备B
TXD  ────────────  RXD
RXD  ────────────  TXD
GND  ────────────  GND
```

## RS485 (2线制)

```
设备A              设备B
 A+  ────────────  A+
 B-  ────────────  B-
GND  ────────────  GND (可选)
```

<!-- 图片位置：TTL和RS485接线图 -->
<!--
![接线方式](./images/wiring_diagram.png)
-->

---

# 三、数据类型与编码

## 常见数据类型

| 类型 | 字节数 | 范围 | 用途 |
|------|--------|------|------|
| uint8 | 1 | 0 ~ 255 | 状态、命令 |
| int16 | 2 | -32768 ~ 32767 | 温度、压力 |
| uint16 | 2 | 0 ~ 65535 | 计数器 |
| float | 4 | ±3.4E38 | 精确测量值 |

---

# 字节序 (Endianness)

**大端序 (Big-Endian)**：高位在前
```
数值 0x1234 存储为: [0x12, 0x34]
```

**小端序 (Little-Endian)**：低位在前
```
数值 0x1234 存储为: [0x34, 0x12]
```

**AIBUS协议使用小端序**：
```python
# 解析温度值 (小端序)
pv_raw = struct.unpack('<H', data[0:2])[0]  # < 表示小端
```

---

# 四、Python串口编程

## pyserial库简介

`pyserial` 是Python最常用的串口库：

```bash
pip install pyserial
```

**核心功能**：
- 串口打开/关闭
- 数据发送/接收
- 参数配置
- 超时控制

---

# 串口基本操作

```python {all|1-3|4-6|7-9|10-12}
import serial

# 打开串口
ser = serial.Serial('COM3', 9600, timeout=1)

# 发送数据
ser.write(b'\x80\x80\x52\x00\x00\x00\x52\x00')

# 接收数据
data = ser.read(10)  # 读取10字节

# 关闭串口
ser.close()
```

---

# 使用上下文管理器

```python {all|1-2|3-4|5-6}
# 推荐方式：自动关闭串口
with serial.Serial('COM3', 9600, timeout=1) as ser:
    # 发送指令
    ser.write(command)
    
    # 读取响应
    response = ser.read(10)
    
# 退出with块时自动关闭
```

---

# 串口配置参数

```python
ser = serial.Serial(
    port='COM3',           # 端口号
    baudrate=9600,         # 波特率
    bytesize=8,            # 数据位 (5,6,7,8)
    parity='N',            # 校验位 (N,O,E,M,S)
    stopbits=1,            # 停止位 (1, 1.5, 2)
    timeout=1.0,           # 读超时(秒)
    write_timeout=1.0,     # 写超时(秒)
)
```

---

# 数据打包与解包

使用 `struct` 模块处理二进制数据：

```python {all|1-2|3-4|5-6}
import struct

# 打包：数值 → 字节
data = struct.pack('<H', 1000)  # 小端uint16 → b'\xe8\x03'

# 解包：字节 → 数值
value = struct.unpack('<H', b'\xe8\x03')[0]  # → 1000

# 多字段打包
frame = struct.pack('<HHB', 0x8080, 0x52, 0x00)
```

---

# 串口通信流程

```
┌──────────┐                    ┌──────────┐
│   主机   │                    │   从机   │
│ (电脑)   │                    │ (仪表)   │
└────┬─────┘                    └────┬─────┘
     │                               │
     │  ──── 发送指令 ──────────────>│
     │       (8字节)                 │
     │                               │
     │  <─── 返回响应 ───────────────│
     │       (10字节)                │
     │                               │
```

---

# 五、Python自动化控制原理

## 整体架构

从用户操作到硬件控制，采用分层设计：

```
┌─────────────────────────────────────────────────────────────┐
│                    Python 应用层                             │
│  (控制脚本、业务逻辑、数据处理)                               │
├─────────────────────────────────────────────────────────────┤
│                    设备抽象层                                │
│  (BaseDevice, AIHeaterDevice - 统一接口)                     │
├─────────────────────────────────────────────────────────────┤
│                    协议层                                    │
│  (AIBUS协议 - 数据打包/解包、校验和计算)                      │
├─────────────────────────────────────────────────────────────┤
│                    通信层                                    │
│  (pyserial - 串口打开/关闭、数据发送/接收)                    │
├─────────────────────────────────────────────────────────────┤
│                    硬件层                                    │
│  (USB转串口、RS485/TTL、加热器设备)                          │
└─────────────────────────────────────────────────────────────┘
```

---

# 各层职责

| 层次 | 职责 | 关键技术 |
|------|------|----------|
| 应用层 | 用户交互、业务逻辑 | Python脚本、配置文件 |
| 设备层 | 设备操作封装 | 面向对象、继承 |
| 协议层 | 数据格式转换 | struct、校验和 |
| 通信层 | 数据传输 | pyserial |
| 硬件层 | 物理连接 | 串口、电平转换 |

---

# 通信层原理

```python {all|1-2|3-4|5-6|7-8}
import serial

# 打开串口 - 建立物理连接
ser = serial.Serial('COM3', 9600, timeout=1)

# 发送数据 - 将字节流发送到设备
ser.write(b'\x80\x80\x52\x00\x00\x00\x52\x00')

# 接收数据 - 从设备读取响应
response = ser.read(10)

# 关闭串口 - 释放资源
ser.close()
```

**核心概念**：串口、字节流、同步/异步

---

# 协议层原理

协议 = 数据格式 + 通信规则

```python {all|1-6|7-12}
# 1. 构建指令（按协议格式打包数据）
def build_read_command(address, param_code):
    frame = bytearray()
    frame.extend(address.to_bytes(2, 'little'))  # 地址(小端)
    frame.append(0x52)                            # 读命令
    frame.append(param_code)                      # 参数代号
    checksum = (address + 0x52 + param_code) & 0xFFFF
    frame.extend(checksum.to_bytes(2, 'little'))  # 校验和
    return bytes(frame)

# 2. 解析响应（按协议格式解包数据）
def parse_response(data):
    pv = int.from_bytes(data[0:2], 'little')      # 测量值
    sv = int.from_bytes(data[2:4], 'little')      # 设定值
    mv = data[4]                                   # 输出值
    return {'pv': pv, 'sv': sv, 'mv': mv}
```

---

# 设备抽象层原理

```python {all|1-6|7-12}
from abc import ABC, abstractmethod

# 抽象基类 - 定义统一接口
class BaseDevice(ABC):
    @abstractmethod
    def connect(self): pass
    
    @abstractmethod
    def read_data(self): pass

# 具体设备 - 实现具体逻辑
class HeaterDevice(BaseDevice):
    def connect(self):
        self._protocol = AIBUSProtocol(self.config)
        self._protocol.open()
    
    def set_temperature(self, temp):
        self._protocol.write_parameter('SV', temp)
```

**核心概念**：抽象、封装、继承

---

# 控制层原理

控制循环 = 持续监控 + 动态调整

```python {all|1-4|5-8|9-12|13-16}
def control_loop(heater, target_temp, duration):
    start_time = time.time()
    
    while (time.time() - start_time) < duration:
        # 1. 读取当前状态
        data = heater.read_data()
        current_temp = data.pv
        
        # 2. 计算控制量
        error = target_temp - current_temp
        
        # 3. 执行控制动作
        heater.set_temperature(target_temp)
        
        # 4. 记录数据
        record_data(data)
        
        # 5. 等待下一个周期
        time.sleep(1.0)
```

---

# 数据流示意图

```
用户操作: "设置温度30°C"
    ↓
应用层: heater.set_temperature(30.0)
    ↓
设备层: 调用协议层
    ↓
协议层: 构建指令帧 [80 80 43 00 E8 03 2B 04]
    ↓
通信层: ser.write(b'\x80\x80\x43\x00\xE8\x03\x2B\x04')
    ↓
硬件层: USB→串口→RS485→加热器
    ↓
设备响应: [E8 03 E8 03 00 60 E8 03 XX XX]
    ↓
通信层: ser.read(10)
    ↓
协议层: 解析 → PV=100.0, SV=100.0, MV=0
    ↓
设备层: 返回 HeaterData(pv=100.0, sv=100.0)
    ↓
应用层: 显示 "温度已设定"
```

---

# 关键技术栈

| 技术 | 作用 | 本项目应用 |
|------|------|------------|
| **pyserial** | 串口通信 | 与加热器通信 |
| **struct** | 二进制数据处理 | 打包/解包协议帧 |
| **threading** | 多线程 | 多设备并行控制 |
| **dataclass** | 数据结构 | 设备数据、配置 |
| **ABC** | 抽象基类 | 设备统一接口 |
| **YAML** | 配置文件 | 系统参数配置 |
| **matplotlib** | 数据可视化 | 温度曲线图 |

---

# 为什么选择Python？

| 优势 | 说明 |
|------|------|
| **开发效率高** | 简洁语法，快速原型开发 |
| **生态丰富** | pyserial, matplotlib, numpy等 |
| **跨平台** | Windows/Linux/Mac |
| **易于扩展** | 添加新设备只需继承基类 |
| **调试方便** | 交互式环境，实时测试 |

---

# 六、AIBUS协议详解

## 协议概述

AIBUS是宇电仪表专用的通信协议，特点：

- **简单高效**：固定帧格式
- **可靠性强**：校验和验证
- **功能完整**：支持读写参数

---

# AIBUS帧格式

## 读参数指令（8字节）

```
┌──────────┬──────────┬──────────┬──────────┬──────────┐
│ 地址(2B) │ 命令(1B) │ 参数(1B) │ 固定(2B) │ 校验(2B) │
│  80 80   │   52     │   00     │  00 00   │  52 00   │
└──────────┴──────────┴──────────┴──────────┴──────────┘
```

## 写参数指令（8字节）

```
┌──────────┬──────────┬──────────┬──────────┬──────────┐
│ 地址(2B) │ 命令(1B) │ 参数(1B) │ 值(2B)   │ 校验(2B) │
│  80 80   │   43     │   00     │  E8 03   │  2B 04   │
└──────────┴──────────┴──────────┴──────────┴──────────┘
```

---

# 响应数据格式（10字节）

```
┌──────────┬──────────┬──────────┬──────────┬──────────┐
│ PV(2B)   │ SV(2B)   │ MV(1B)   │ 状态(1B) │ 值(2B)   │
│  E8 03   │  00 00   │   00     │   60     │  E8 03   │
└──────────┴──────────┴──────────┴──────────┴──────────┘
│                                          │ 校验(2B) │
│                                          │  XX XX   │
└──────────────────────────────────────────┴──────────┘
```

**数据解析**：
- PV（测量值）= 0x03E8 = 1000 → 100.0°C
- SV（设定值）= 0x0000 = 0 → 0.0°C
- MV（输出值）= 0x00 = 0%

---

# 校验和计算

```python {all|1-3|4-6|7-9}
# 读指令校验和
def calc_read_checksum(addr, param):
    return (addr + 0x52 + param) & 0xFFFF

# 写指令校验和
def calc_write_checksum(addr, param, value):
    return (addr + 0x43 + param + value) & 0xFFFF

# 响应校验和
def calc_response_checksum(pv, sv, status_mv, param_val):
    return (pv + sv + status_mv + param_val) & 0xFFFF
```

---

# 参数代号表

| 代号 | 参数 | 说明 | 范围 |
|------|------|------|------|
| 0 | SV | 给定值(设定温度) | -999~9999 |
| 8 | D_P | 小数位数 | 0~3 |
| 26 | MV | 输出值 | 0~100 |
| 74 | PV | 测量值 | 只读 |
| 100 | MODEL | 型号特征字 | 只读 |

---

# 七、项目架构设计

## 设计目标

- **模块化**：设备独立，易于扩展
- **可配置**：参数可调，无需改代码
- **可监控**：实时数据采集与报警
- **可追溯**：完整日志与报告

---

# 系统架构图

```
┌─────────────────────────────────────────────────────────┐
│                     主程序 (main.py)                     │
│              统一调度、设备管理、流程控制                  │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐      │
│  │ devices │ │protocols│ │ monitor │ │ reports │      │
│  │ 设备驱动 │ │通信协议  │ │数据监控  │ │报告生成  │      │
│  └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘      │
│       │           │           │           │            │
├───────┴───────────┴───────────┴───────────┴────────────┤
│                     utils (工具层)                       │
│              配置管理、日志记录、通用工具                  │
├─────────────────────────────────────────────────────────┤
│                     硬件设备层                           │
│     ┌─────────┐ ┌─────────┐ ┌─────────┐               │
│     │ 加热器1 │ │ 加热器2 │ │  泵/阀  │  ...          │
│     └─────────┘ └─────────┘ └─────────┘               │
└─────────────────────────────────────────────────────────┘
```

---

# 目录结构

```
d:\AI\Heat\
├── config/
│   └── system_config.yaml    # 系统配置
├── src/
│   ├── devices/              # 设备驱动
│   │   ├── base_device.py    # 设备基类
│   │   └── heater.py         # 加热器驱动
│   ├── protocols/            # 通信协议
│   │   ├── aibus.py          # AIBUS协议
│   │   └── parameters.py     # 参数定义
│   ├── monitor/              # 数据监控
│   ├── reports/              # 报告生成
│   └── main.py               # 主程序
├── scripts/                  # 控制脚本
└── tests/                    # 测试脚本
```

---

# 八、核心代码实现

## 8.1 设备抽象基类

设计模式：**模板方法模式**

```python {all|1-5|6-10|11-14}
class BaseDevice(ABC):
    """设备抽象基类 - 所有设备必须继承此类"""
    
    @abstractmethod
    def connect(self) -> bool:
        """连接设备"""
        pass
    
    @abstractmethod
    def disconnect(self) -> bool:
        """断开连接"""
        pass
    
    @abstractmethod
    def read_data(self) -> DeviceData:
        """读取数据"""
        pass
```

---

# 设备基类 - 核心方法

```python {all|1-4|5-12|13-20}
@abstractmethod
def write_command(self, command: str, value: Any) -> bool:
    """执行设备命令"""
    pass

def execute_with_retry(self, operation: Callable, name: str):
    """带重试机制执行操作"""
    for attempt in range(self.config.retry_count):
        try:
            return operation()
        except Exception as e:
            if attempt < self.config.retry_count - 1:
                time.sleep(self.config.retry_delay)
    raise last_error

def __enter__(self):
    self.connect()
    return self

def __exit__(self, *args):
    self.disconnect()
```

---

# 8.2 AIBUS协议实现

## 指令构建

```python {all|1-5|6-10|11-14}
def _build_read_command(self, param_code: int) -> bytes:
    """构建读参数指令"""
    checksum = self._calculate_read_checksum(param_code)
    
    frame = bytearray()
    frame.extend(self._build_address_bytes())  # 地址(2字节)
    frame.append(0x52)                          # 读命令
    frame.append(param_code)                    # 参数代号
    frame.extend([0x00, 0x00])                  # 固定值
    frame.extend(struct.pack('<H', checksum))   # 校验和
    return bytes(frame)
```

---

# 响应解析

```python {all|1-4|5-8|9-12}
def _parse_response(self, data: bytes) -> AIBUSResponse:
    """解析响应数据 - 10字节"""
    pv_raw = struct.unpack('<H', data[0:2])[0]   # 测量值
    sv_raw = struct.unpack('<H', data[2:4])[0]   # 设定值
    mv = data[4]                                  # 输出值
    alarm_status = data[5]                        # 报警状态
    param_value = struct.unpack('<H', data[6:8])[0]
    
    # 处理负数
    pv = pv_raw if pv_raw < 32768 else pv_raw - 65536
    sv = sv_raw if sv_raw < 32768 else sv_raw - 65536
    
    return AIBUSResponse(pv=pv, sv=sv, mv=mv, ...)
```

---

# 8.3 加热器设备驱动

```python {all|1-5|6-10|11-15}
class AIHeaterDevice(BaseDevice):
    """宇电AI系列加热器设备驱动"""
    
    def connect(self) -> bool:
        """连接加热器"""
        self._protocol = AIBUSProtocol(port, address, baudrate)
        self._protocol.open()
        self._model_code = self._read_model_code()
        return True
    
    def set_temperature(self, temperature: float) -> bool:
        """设定目标温度"""
        self._protocol.write_parameter(
            ParameterCode.SV, temperature, 
            decimal_places=self._decimal_places
        )
        return True
```

---

# 加热器 - 数据读取

```python {all|1-4|5-8|9-12}
def read_data(self) -> HeaterData:
    """读取加热器数据"""
    pv, sv, mv, alarm_status = self._protocol.read_pv_sv()
    
    # 解析报警状态
    alarms = self._parse_alarms(alarm_status)
    
    return HeaterData(
        device_id=self.config.device_id,
        timestamp=datetime.now(),
        pv=pv / (10 ** self._decimal_places),
        sv=sv / (10 ** self._decimal_places),
        mv=mv, alarms=alarms
    )
```

---

# 8.4 配置管理

```yaml
# config/system_config.yaml
name: "自动化控制系统"
version: "1.0.0"

heaters:
  - device_id: "heater1"
    name: "主加热器"
    connection:
      port: "COM3"
      baudrate: 9600
      address: 1
    decimal_places: 1
    safety_limit: 450.0
```

---

# 8.5 控制脚本示例

```python {all|1-4|5-8|9-12}
# 创建加热器
config = HeaterConfig(
    device_id="heater1",
    connection_params={'port': 'COM3', 'baudrate': 9600, 'address': 1}
)

with AIHeaterDevice(config) as heater:
    # 设定温度并启动
    heater.set_temperature(100.0)
    heater.start()
    
    # 读取数据
    data = heater.read_data()
    print(f"当前温度: {data.pv}°C")
```

---

# 九、演示与总结

## 已实现功能

| 功能 | 状态 | 说明 |
|------|------|------|
| 温度读取 | ✅ | PV/SV/MV实时读取 |
| 温度设定 | ✅ | 支持安全限温 |
| 运行控制 | ✅ | 启动/停止/保持 |
| 多设备控制 | ✅ | 多线程并行 |
| 数据监控 | ✅ | 实时采集存储 |
| 报告生成 | ✅ | HTML格式报告 |

---

# 演示：双加热器控制

```
============================================================
双加热器温度控制脚本
============================================================
目标温度: 30.0°C
加热时间: 5.0 分钟

[21:16:59][Heater1] 目标: 30.0°C | 当前: 30.0°C
[21:16:59][Heater2] 目标: 23.5°C | 当前: 23.5°C
...
[Heater1] 成功 - 最终温度: PV=29.9°C
[Heater2] 成功 - 最终温度: PV=33.8°C
```

---

# 扩展性设计

添加新设备只需3步：

```python {all|1-2|3-4|5-6}
# 1. 继承BaseDevice
class PumpDevice(BaseDevice):
    pass

# 2. 实现抽象方法
    def connect(self): ...
    def read_data(self): ...

# 3. 添加到配置文件
pumps:
  - device_id: "pump1"
    connection: {port: "COM5", ...}
```

---

# 未来规划

- [ ] Web界面远程控制
- [ ] 数据可视化仪表盘
- [ ] 自动化实验流程编排
- [ ] 更多设备支持（泵、阀门、传感器）
- [ ] AI辅助实验优化

---

# 项目亮点

1. **模块化架构** - 设备独立，易于扩展
2. **协议自主实现** - 不依赖厂商DLL
3. **配置驱动** - 无需修改代码
4. **完整日志** - 可追溯、可调试
5. **并行控制** - 多设备同时运行

---

# Q&A

感谢聆听！

项目地址：`d:\AI\Heat\`

---

# 附录：关键文件说明

| 文件 | 功能 | 代码行数 |
|------|------|----------|
| `protocols/aibus.py` | AIBUS协议实现 | ~500 |
| `devices/heater.py` | 加热器驱动 | ~600 |
| `devices/base_device.py` | 设备基类 | ~300 |
| `monitor/data_monitor.py` | 数据监控 | ~400 |
| `reports/report_generator.py` | 报告生成 | ~350 |
