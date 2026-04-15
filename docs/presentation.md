---
theme: default
title: 组会汇报：自动化控制系统
layout: cover
class: text-center
---

# 组会汇报：自动化控制系统

## 从通信协议到项目实现

---
layout: default
---

# 目录

<div class="grid grid-cols-2 gap-4 mt-6">
<div>

**基础与原理**
- 一、串口通信原理 ⬅️ 基础知识
- 二、电平标准与接口

**编程与协议**
- 三、Python串口编程
- 四、AIBUS协议详解
- 五、MODBUS-RTU协议详解 ⭐新增

</div>
<div>

**项目实现**
- 六、项目架构设计
- 七、核心代码实现
- 八、安全机制设计 ⭐新增

**演示与展望**
- 九、演示与总结

</div>
</div>

---

# 一、串口通信原理

---

## 1.1 什么是串口通信？

### 生活类比：两个人聊天 💬

| 对比项 | 生活场景 | 串口通讯 |
|--------|----------|----------|
| 通讯双方 | 两个人 | 两台设备（电脑 ↔ 单片机） |
| 通讯通道 | 空气/电话线 | 串口线（USB线/RS-232线） |
| 通讯规则 | 语言/语速/停顿 | 波特率/数据位/校验位 |

> **核心本质**：数据以"位（bit）"为单位，一位一位地**串行传输**

<img src="./images/人与机交流.png" style="max-height: 200px; margin-top: 8px; display: block; margin-left: auto; margin-right: auto;">

---

## 1.2 串行 vs 并行传输

<div style="display: flex; gap: 24px; align-items: flex-start; margin-top: 8px;">
<div style="flex: 1;">

**并行传输的缺点**：
- ❌ 线路多（8根以上）
- ❌ 距离短（通常<1米）
- ❌ 成本高 / 抗干扰差

<img src="./images/并行通讯接口：开始的做法.png" style="max-height: 160px; width: 100%; object-fit: contain;">

</div>
<div style="flex: 1;">

**串口通讯的优势**：
- ✅ 线路少（最少仅需3根）
- ✅ 距离远（RS-485可达1200米）
- ✅ 成本低 / 抗干扰强

<img src="./images/串口通讯接口：后来因为并行缺点产生.png" style="max-height: 160px; width: 100%; object-fit: contain;">

</div>
</div>

---

## 1.3 串口通讯的应用场景

### 串口通讯无处不在

| 领域 | 典型应用 |
|------|----------|
| 🖥️ 嵌入式开发 | 单片机程序下载、调试输出 |
| 🏭 工业控制 | PLC、变频器、传感器互联 |
| 🏠 智能家居 | 门禁、网关、温湿度传感器 |
| 🚗 汽车电子 | OBD车载诊断系统 |
| 🖨️ 办公设备 | 老式打印机、扫描仪 |

<img src="./images/后续丰富的应用.png" style="max-height: 120px; display: block; margin: 8px auto 0;">

---

## 1.4 数据帧结构

### 串口传输的基本单元

一帧完整的串口数据包含：

```
┌────────┬──────────┬────────┬────────┐
│ 起始位 │  数据位  │ 停止位 │ 校验位 │
│ 1 bit  │ 5-8 bit  │ 1-2bit │0/1 bit │
└────────┴──────────┴────────┴────────┘
   ↓        ↓         ↓        ↓
  开始标志  有效数据   结束标志  纠错用
```

<img src="./images/实现方法.png" style="max-height: 160px; display: block; margin: 8px auto 0;">

---

## 1.5 数据帧示例

### 发送字符 'A'（8N1配置）

**ASCII码**: `0x41` = 二进制 `01000001`

```
空闲   起始   D0  D1  D2  D3  D4  D5  D6  D7   停止   空闲
  1      0     1   0   0   0   0   0   1   0     1      1
        └──────────────────────────────┘
                  一个完整数据帧
```

> 📝 **时序说明**：先传低位(D0)，后传高位(D7)

---

## 1.6 串口四件套

### 确保双方能正常通讯的核心参数

| 参数 | 类比 | 说明 | 常见值 |
|------|------|------|--------|
| **波特率** | 聊天语速 | 每秒传输位数(bps) | 9600, 115200 |
| **数据位** | 每个词字数 | 每帧数据位数 | 7, 8 (常用8) |
| **停止位** | 说完停顿 | 帧结束标志 | 1, 2 (常用1) |
| **校验位** | 确认听懂 | 检错机制 | N/O/E (常用N) |

> ⚠️ **关键**：发送方和接收方的参数必须**完全一致**！

<img src="./images/波特率引出3.png" style="max-height: 180px; display: block; margin: 8px auto 0;">

---

## 1.7 波特率选择

### 波特率与传输速度对照

| 波特率 | 字节/秒 | 典型应用 |
|--------|---------|----------|
| 9600 | ~960 | 工业仪表、传感器 |
| 19200 | ~1920 | PLC通信 |
| 115200 | ~11520 | 调试下载、高速通信 |

> 💡 **经典配置**：`9600 N 8 1`（9600波特率，无校验，8数据位，1停止位）

<div style="display: flex; gap: 16px; justify-content: center; margin-top: 8px;">
<img src="./images/波特率引出.png" style="max-height: 160px; object-fit: contain;">
<img src="./images/波特率引出2.png" style="max-height: 160px; object-fit: contain;">
</div>

---

## 1.8 通讯方向

### 三种通讯模式

| 类型 | 类比 | 特点 | 典型应用 |
|------|------|------|----------|
| **全双工** | 打电话 | 双方可同时说/听 | UART（TX+RX双线） |
| **半双工** | 对讲机 | 同一时间只能一方传输 | RS-485总线 |
| **单工** | 广播 | 只能单向传输 | 传感器→控制器 |

<img src="./images/机与机交流.png" style="max-height: 180px; display: block; margin: 8px auto 0;">

---

## 1.9 接线方式

### 全双工接线规则：TX接RX

```
┌─────────────┐                    ┌─────────────┐
│    设备A    │                    │   设备B    │
│             │                    │             │
│  TX ──────────►───────────────────►── RX      │
│  RX ◄───────────────────────────────◄── TX    │
│  GND ────────────────────────────────── GND   │
└─────────────┘                    └─────────────┘

✅ 规则：TX → RX，RX → TX（交叉连接）
❌ 错误：TX → TX，RX → RX
```

> 💡 **最小系统只需3根线**：TXD、RXD、GND

<img src="./images/如何实现单片机与单片机的通信.png" style="max-height: 160px; display: block; margin: 8px auto 0;">

---

## 1.10 电脑如何连接单片机？

### USB转串口方案

**为什么需要转换？**
- 电脑USB口 → USB信号
- 单片机串口 → TTL电平（0~5V）
- 需要 **USB转TTL模块**（如CH340）

<div style="display: flex; gap: 16px; justify-content: center; margin-top: 8px;">
<img src="./images/如何实现单片机与电脑.png" style="max-height: 160px; object-fit: contain;">
<img src="./images/实现电脑和单片机交流.png" style="max-height: 160px; object-fit: contain;">
</div>

---

## 1.11 电平标准对比

### 物理层的三种接口

| 标准 | 信号类型 | 逻辑1 | 逻辑0 | 特点 | 距离 |
|------|----------|-------|-------|------|------|
| **TTL** | 单端 | 2.4~5V | 0~0.4V | 芯片直连 | <1米 |
| **RS-232** | 单端(负电平) | -15~-3V | +3~+15V | 抗干扰差 | <15米 |
| **RS-485** | 差分信号 | A-B>+200mV | A-B<-200mV | 抗干扰强 | 1200米 |

<img src="./images/物理层.png" style="max-height: 160px; display: block; margin: 8px auto 0;">

---

## 1.12 RS-232 接口

| 逻辑 | 电压范围 | 说明 |
|------|----------|------|
| 逻辑1 (高) | **-15V ~ -3V** | 负电压！ |
| 逻辑0 (低) | **+3V ~ +15V** | 正电压！ |

> 🔴 **警告**：RS-232电平**绝对不能**直接连接TTL设备！
> 必须使用 MAX232 等电平转换芯片。

<img src="./images/RS232.png" style="max-height: 160px; display: block; margin: 8px auto 0;">

---

## 1.13 RS-485 接口

RS-485采用**差分信号**传输：

| 特性 | 说明 |
|------|------|
| 传输方式 | 差分信号 (A线 - B线) |
| 逻辑1 | A - B > **+200mV** |
| 逻辑0 | A - B < **-200mV** |
| 最大距离 | **1200米** |
| 最大节点 | **32个设备** |

> ✅ **优点**：一根总线可连接最多32个设备，最远1200米

<img src="./images/RS485.png" style="max-height: 80px; display: block; margin: 8px auto 0;">

---

## 1.14 RS-485 总线拓扑

### 一主多从连接方式

```
                    ┌──────┐
                    │ 主站 │
                    └──┬───┘
                       │
    ┌───────────────────┼───────────────────┐
    │                   │                   │
┌───┴───┐          ┌───┴───┐          ┌───┴───┐
│ 从站1 │          │ 从站2 │          │ 从站3 │
└───────┘          └───────┘          └───────┘
    A+──────────────A+──────────────A+
    B-──────────────B-──────────────B-
    GND─────────────GND─────────────GND
```

---

## 1.15 工作流程总结

### 以发送字符 'A' 为例（9600 N 8 1）

```
┌──────────────────────────────────────────────────────┐
│                      通讯流程                          │
├──────────────────────────────────────────────────────┤
│  1️⃣ 参数约定  │ 双方设置 9600波特率、无校验、8数据位    │
│  2️⃣ 数据转换  │ 'A' → ASCII 65 → 二进制 01000001       │
│  3️⃣ 串行发送  │ TX线按波特率逐位发送（先低位后高位）     │
│  4️⃣ 数据接收  │ RX线按相同波特率接收8位+1位停止位       │
│  5️⃣ 数据还原  │ 二进制 01000001 → ASCII 65 → 'A'       │
└──────────────────────────────────────────────────────┘
```

<img src="./images/二进制容易实现单片机互相交流.png" style="max-height: 160px; display: block; margin: 8px auto 0;">

---

# 二、电平标准与接口

---

## 2.1 TTL电平详解

TTL (Transistor-Transistor Logic) 是芯片级数字电平标准：

| 逻辑 | 电压范围 | 典型值 |
|------|----------|--------|
| 逻辑1 (高) | 2.4V ~ 5V | 3.3V / 5V |
| 逻辑0 (低) | 0V ~ 0.4V | 0V |

> ⚠️ **注意**：3.3V设备不能直接接5V设备，需电平转换！

---

## 2.2 串口引脚定义：DB9接口

| 引脚 | 名称 | 方向 | 功能 |
|------|------|------|------|
| 2 | **RXD** | 输入 | 接收数据 |
| 3 | **TXD** | 输出 | 发送数据 |
| 5 | **GND** | - | 信号地 |
| 7 | RTS | 输出 | 请求发送 |
| 8 | CTS | 输入 | 清除发送 |

---

# 三、Python串口编程

---

## 3.1 pyserial库简介

Python最常用的串口库：

```bash
pip install pyserial
```

**核心功能**：
- ✅ 串口打开/关闭
- ✅ 数据发送/接收
- ✅ 参数配置
- ✅ 超时控制

---

## 3.2 串口基本操作

```python
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

## 3.3 推荐写法：上下文管理器

```python
# ✅ 推荐方式：自动关闭串口，防止资源泄漏
with serial.Serial('COM3', 9600, timeout=1) as ser:
    # 发送指令
    ser.write(command)
    
    # 读取响应
    response = ser.read(10)
    
# 退出with块时自动关闭
```

---

## 3.4 串口配置参数详解

```python
ser = serial.Serial(
    port='COM3',           # 端口号
    baudrate=9600,          # 波特率
    bytesize=8,             # 数据位 (5,6,7,8)
    parity='N',             # 校验位 (N无/O奇/E偶)
    stopbits=1,             # 停止位 (1, 1.5, 2)
    timeout=1.0,            # 读超时(秒)
    write_timeout=1.0,      # 写超时(秒)
)
```

---

## 3.5 数据打包与解包

使用 `struct` 模块处理二进制数据：

```python
import struct

# 打包：数值 → 字节 (小端序 uint16)
data = struct.pack('<H', 1000)  # → b'\xe8\x03'

# 解包：字节 → 数值
value = struct.unpack('<H', b'\xe8\x03')[0]  # → 1000

# 多字段打包
frame = struct.pack('<HHB', 0x8080, 0x52, 0x00)
```

---

## 3.6 串口通信流程图

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

## 3.7 Python自动化控制原理

### 整体架构

从用户操作到硬件控制，采用分层设计：

```
┌─────────────────────────────────────────────────────────────┐
│                    Python 应用层                             │
│  (控制脚本、业务逻辑、数据处理)                               │
├─────────────────────────────────────────────────────────────┤
│                    设备抽象层                                │
│  (BaseDevice, HeaterDevice, PumpDevice - 统一接口)          │
├─────────────────────────────────────────────────────────────┤
│                    协议层                                    │
│  (AIBUS/MODBUS协议 - 数据打包/解包、校验计算)                │
├─────────────────────────────────────────────────────────────┤
│                    通信层                                    │
│  (pyserial - 串口打开/关闭、数据发送/接收)                   │
├─────────────────────────────────────────────────────────────┤
│                    硬件层                                    │
│  (USB转串口、RS485/TTL、加热器/蠕动泵设备)                   │
└─────────────────────────────────────────────────────────────┘
```

---

## 3.8 各层职责

| 层次 | 职责 | 关键技术 |
|------|------|----------|
| 应用层 | 用户交互、业务逻辑 | Python脚本、配置文件 |
| 设备层 | 设备操作封装 | 面向对象、继承 |
| 协议层 | 数据格式转换 | struct、校验和/CRC |
| 通信层 | 数据传输 | pyserial |
| 硬件层 | 物理连接 | 串口、电平转换 |

---

## 3.9 通信层原理

```python
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

> **核心概念**：串口、字节流、同步通信

---

## 3.10 协议层原理

协议 = 数据格式 + 通信规则

```python
# 1. 构建指令（按协议格式打包数据）
def build_read_command(address, param_code):
    frame = bytearray()
    frame.extend(address.to_bytes(2, 'little'))  # 地址(小端)
    frame.append(0x52)                            # 读命令
    frame.append(param_code)                      # 参数代号
    checksum = (address + 0x52 + param_code) & 0xFFFF
    frame.extend(checksum.to_bytes(2, 'little')) # 校验和
    return bytes(frame)

# 2. 解析响应（按协议格式解包数据）
def parse_response(data):
    pv = int.from_bytes(data[0:2], 'little')    # 测量值
    sv = int.from_bytes(data[2:4], 'little')    # 设定值
    mv = data[4]                                  # 输出值
    return {'pv': pv, 'sv': sv, 'mv': mv}
```

---

## 3.11 设备抽象层原理

```python
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

class PumpDevice(BaseDevice):
    def connect(self):
        self._protocol = ModbusRTUProtocol(self.config)
        self._protocol.open()

    def set_flow_rate(self, channel, rate):
        self._protocol.write_float(channel, rate)
```

> **核心概念**：抽象、封装、继承

---

## 3.12 控制层原理

控制循环 = 持续监控 + 动态调整

```python
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

## 3.13 数据流示意图

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

## 3.14 关键技术栈

| 技术 | 作用 | 本项目应用 |
|------|------|------------|
| **pyserial** | 串口通信 | 与加热器/蠕动泵通信 |
| **struct** | 二进制数据处理 | 打包/解包协议帧 |
| **threading** | 多线程 | 多设备并行控制 |
| **dataclass** | 数据结构 | 设备数据、配置 |
| **ABC** | 抽象基类 | 设备统一接口 |
| **YAML** | 配置文件 | 系统参数配置 |
| **matplotlib** | 数据可视化 | 温度曲线图 |

---

## 3.15 为什么选择Python？

| 优势 | 说明 |
|------|------|
| **开发效率高** | 简洁语法，快速原型开发 |
| **生态丰富** | pyserial, matplotlib, numpy等 |
| **跨平台** | Windows/Linux/Mac |
| **易于扩展** | 添加新设备只需继承基类 |
| **调试方便** | 交互式环境，实时测试 |

---

# 四、AIBUS协议详解

---

## 4.1 AIBUS协议概述

AIBUS是宇电仪表专用的通信协议：

| 特点 | 说明 |
|------|------|
| 简单高效 | 固定帧格式，易于实现 |
| 可靠性强 | 校验和验证，数据可靠 |
| 功能完整 | 支持读写参数 |

---

## 4.2 AIBUS帧格式：读参数指令（8字节）

```
┌──────────┬──────────┬──────────┬──────────┬──────────┐
│ 地址(2B) │ 命令(1B) │ 参数(1B) │ 固定(2B) │ 校验(2B) │
│  80 80   │   52     │   00     │  00 00   │  52 00   │
└──────────┴──────────┴──────────┴──────────┴──────────┘
```

---

## 4.3 AIBUS帧格式：写参数指令（8字节）

```
┌──────────┬──────────┬──────────┬──────────┬──────────┐
│ 地址(2B) │ 命令(1B) │ 参数(1B) │ 值(2B)   │ 校验(2B) │
│  80 80   │   43     │   00     │  E8 03   │  2B 04   │
└──────────┴──────────┴──────────┴──────────┴──────────┘
```

---

## 4.4 AIBUS响应数据格式（10字节）

```
┌──────────┬──────────┬──────────┬──────────┬──────────┬──────────┐
│ PV(2B)   │ SV(2B)   │ MV(1B)   │ 状态(1B) │ 值(2B)   │ 校验(2B) │
│  E8 03   │  00 00   │   00     │   60     │  E8 03   │  XX XX   │
└──────────┴──────────┴──────────┴──────────┴──────────┴──────────┘
```

**数据解析示例**：
- PV（测量值）= 0x03E8 = 1000 → **100.0°C**
- SV（设定值）= 0x0000 = 0 → **0.0°C**
- MV（输出值）= 0x00 = 0% → **0%**

---

## 4.5 校验和计算

```python
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

## 4.6 AIBUS常用参数代号

| 代号 | 参数 | 说明 | 范围 |
|------|------|------|------|
| 0 | SV | 给定值(设定温度) | -999~9999 |
| 8 | D_P | 小数位数 | 0~3 |
| 26 | MV | 输出值 | 0~100 |
| 74 | PV | 测量值 | 只读 |
| 100 | MODEL | 型号特征字 | 只读 |

---

# 五、MODBUS-RTU协议详解

---

## 5.1 MODBUS协议概述

MODBUS是一种工业通信协议标准，广泛应用于工业设备之间的通信。

| 特性 | 说明 |
|------|------|
| **协议类型** | 主从式（Master-Slave） |
| **传输模式** | RTU（Remote Terminal Unit） |
| **物理层** | RS-232 / RS-485 |
| **数据格式** | 二进制 |
| **校验方式** | CRC-16 |

---

## 5.2 MODBUS帧结构

### RTU帧格式

```
┌────────────┬────────────┬─────────────┬──────────┬──────────┐
│ 从站地址   │  功能码    │   数据区    │ CRC校验  │ 帧间隔   │
│  1字节     │  1字节     │   N字节     │  2字节   │ 3.5字符  │
└────────────┴────────────┴─────────────┴──────────┴──────────┘
```

### 帧间隔要求

- 帧内字符间隔：< 1.5 个字符时间
- 帧间间隔：≥ 3.5 个字符时间

---

## 5.3 功能码定义

| 功能码 | 名称 | 说明 |
|--------|------|------|
| **0x03** | 读保持寄存器 | 读取一个或多个寄存器 |
| **0x06** | 写单个寄存器 | 写入单个寄存器值 |
| **0x10** | 写多个寄存器 | 写入多个寄存器值 |
| 0x04 | 读输入寄存器 | 读取只读寄存器 |
| 0x01 | 读线圈 | 读取开关量输出 |
| 0x05 | 写单个线圈 | 写入单个开关量 |

---

## 5.4 读保持寄存器（0x03）

### 请求帧格式

```
┌──────────┬──────────┬───────────────┬───────────────┬──────────┐
│ 从站地址 │ 功能码   │ 起始地址      │ 寄存器数量    │ CRC校验  │
│  1字节   │  1字节   │   2字节       │   2字节       │  2字节   │
└──────────┴──────────┴───────────────┴───────────────┴──────────┘
```

### 示例：读取地址0开始的10个寄存器

```
请求: 01 03 00 00 00 0A C5 CD
      │  │  └──┬──┘ └──┬──┘ └──┬──┘
      │  │     │       │       └─ CRC
      │  │     │       └─ 数量: 10
      │  │     └─ 起始地址: 0
      │  └─ 功能码: 03
      └─ 从站地址: 1
```

### 响应帧格式

```
┌──────────┬──────────┬──────────┬─────────────┬──────────┐
│ 从站地址 │ 功能码   │ 字节数   │ 寄存器数据  │ CRC校验  │
│  1字节   │  1字节   │  1字节   │   N字节     │  2字节   │
└──────────┴──────────┴──────────┴─────────────┴──────────┘
```

---

## 5.5 写单个寄存器（0x06）

### 请求帧格式

```
┌──────────┬──────────┬───────────────┬───────────────┬──────────┐
│ 从站地址 │ 功能码   │ 寄存器地址    │ 写入值       │ CRC校验  │
│  1字节   │  1字节   │   2字节       │   2字节      │  2字节   │
└──────────┴──────────┴───────────────┴───────────────┴──────────┘
```

### 示例：向地址100写入值50

```
请求: 01 06 00 64 00 32 99 E9
      │  │  └──┬──┘ └──┬──┘ └──┬──┘
      │  │     │       │       └─ CRC
      │  │     │       └─ 值: 50 (0x0032)
      │  │     └─ 地址: 100 (0x0064)
      │  └─ 功能码: 06
      └─ 从站地址: 1
```

---

## 5.6 CRC-16校验算法

### 算法步骤

```
1. 初始化CRC寄存器为0xFFFF
2. 将数据第一个字节与CRC低字节异或
3. CRC右移1位
4. 如果最低位为1，与多项式0xA001异或
5. 重复步骤3-4共8次
6. 处理下一个字节，重复步骤2-5
7. 最终CRC值低字节在前发送
```

### Python实现

```python
def calculate_crc(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc
```

---

## 5.7 异常响应

当从站无法执行请求时，返回异常响应：

```
┌──────────┬──────────────┬──────────┬──────────┐
│ 从站地址 │ 功能码+0x80  │ 异常码   │ CRC校验  │
│  1字节   │    1字节     │  1字节   │  2字节   │
└──────────┴──────────────┴──────────┴──────────┘
```

### 异常码定义

| 代码 | 名称 | 说明 |
|------|------|------|
| 0x01 | 非法功能码 | 设备不支持该功能码 |
| 0x02 | 非法数据地址 | 寄存器地址无效 |
| 0x03 | 非法数据值 | 数据值超出范围 |
| 0x06 | 从站设备忙 | 设备正在处理其他请求 |

---

## 5.8 蠕动泵寄存器映射

### LabSmart蠕动泵寄存器地址

| 地址 | 名称 | 数据类型 | 说明 |
|------|------|----------|------|
| 10 | 全部启停 | uint16 | 1:启动 0:停止 |
| n001 | 启停控制 | uint16 | 0:停止 1:启动 2:暂停 3:全速 |
| n002 | 方向控制 | uint16 | 0:顺时针 1:逆时针 |
| n006 | 运行模式 | uint16 | 0-3 四种模式 |
| n110 | 流速设置 | float | 流速值(mL/min) |
| n104 | 分装液量 | float | 液量(mL) |

> 注：n为通道号(1-4)，如1001表示通道1的启停控制

---

## 5.9 数据类型处理

### 整数（2字节）

```
数据: 高字节 低字节
发送: 高字节 低字节
示例: 1234H 发送 12H 34H
```

### 浮点数（4字节）

```python
import struct

# 浮点数转字节（大端序）
bytes_data = struct.pack('>f', 50.0)  # → b'BH\x00\x00'

# 字节转浮点数
value = struct.unpack('>f', b'BH\x00\x00')[0]  # → 50.0
```

---

## 5.10 AIBUS vs MODBUS对比

| 特性 | AIBUS | MODBUS-RTU |
|------|-------|------------|
| **帧长度** | 固定8/10字节 | 可变长度 |
| **校验方式** | 校验和 | CRC-16 |
| **功能码** | 2个(读/写) | 多个功能码 |
| **数据类型** | 厂商专有 | 工业标准 |
| **设备数量** | 最多81台 | 最多247台 |
| **适用设备** | 宇电仪表 | 通用工业设备 |

---

# 六、项目架构设计

---

## 6.1 设计目标

| 目标 | 说明 |
|------|------|
| 模块化 | 设备独立，易于扩展 |
| 可配置 | 参数可调，无需改代码 |
| 可监控 | 实时数据采集与报警 |
| 可追溯 | 完整日志与报告 |
| 联动控制 | 温度+流量协同 |

---

## 6.2 系统架构图

```
┌─────────────────────────────────────────────────────────┐
│                     主程序 (main.py)                     │
│              统一调度、设备管理、流程控制                  │
├─────────────────────────────────────────────────────────┤
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐      │
│  │ devices │ │protocols│ │ control │ │ reports │      │
│  │ 设备驱动 │ │通信协议  │ │程序控制  │ │报告生成  │      │
│  └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘      │
├───────┴───────────┴───────────┴───────────┴────────────┤
│                     utils (工具层)                       │
│              配置管理、日志记录、通用工具                  │
├─────────────────────────────────────────────────────────┤
│                     硬件设备层                           │
│     ┌─────────┐ ┌─────────┐ ┌─────────┐               │
│     │ 加热器1 │ │ 加热器2 │ │ 蠕动泵  │  ...          │
│     └─────────┘ └─────────┘ └─────────┘               │
└─────────────────────────────────────────────────────────┘
```

---

## 6.3 目录结构

```
d:\AI\Heat\
├── config/
│   └── system_config.yaml    # 系统配置
├── context/                  # 项目上下文 ⭐新增
│   └── PROJECT_CONTEXT.md    # AI记忆库+交接手册
├── src/
│   ├── control/              # 程序控制
│   │   └── program_controller.py
│   ├── devices/              # 设备驱动
│   │   ├── base_device.py    # 设备基类
│   │   ├── heater.py         # 加热器驱动
│   │   ├── peristaltic_pump.py # 蠕动泵驱动
│   │   └── safe_pump.py      # 安全蠕动泵驱动 ⭐新增
│   ├── protocols/            # 通信协议
│   │   ├── aibus.py          # AIBUS协议
│   │   ├── modbus_rtu.py     # MODBUS协议
│   │   ├── parameters.py     # 加热器参数
│   │   └── pump_params.py    # 泵参数
│   ├── monitor/              # 数据监控
│   ├── reports/              # 报告生成
│   └── utils/                # 工具函数 ⭐新增
│       ├── config.py         # 配置管理
│       ├── serial_manager.py # 串口资源管理 ⭐新增
│       └── device_safety.py  # 设备安全基类 ⭐新增
├── scripts/                  # 控制脚本
│   ├── heater_pump_safe.py   # 安全联动脚本 ⭐新增
│   └── test_pump_safe.py     # 安全测试脚本 ⭐新增
└── tests/                    # 测试脚本
```

---

# 七、核心代码实现

---

## 7.1 设备抽象基类

设计模式：**模板方法模式**

```python
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

## 7.2 设备基类 - 核心方法

```python
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

## 7.3 AIBUS协议实现 - 指令构建

```python
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

## 7.4 AIBUS协议实现 - 响应解析

```python
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

## 7.5 加热器设备驱动

```python
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

## 7.6 MODBUS协议实现

```python
class ModbusRTUProtocol:
    """MODBUS-RTU协议实现"""
    
    def calculate_crc(self, data: bytes) -> int:
        """计算CRC-16校验"""
        crc = 0xFFFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 0x0001:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return crc
    
    def read_holding_registers(self, slave: int, address: int, count: int):
        """读保持寄存器 (功能码0x03)"""
        frame = bytes([slave, 0x03, 
                      (address >> 8) & 0xFF, address & 0xFF,
                      (count >> 8) & 0xFF, count & 0xFF])
        crc = self.calculate_crc(frame)
        self._serial.write(frame + bytes([crc & 0xFF, (crc >> 8) & 0xFF]))
        return self._parse_read_response(count)
```

---

## 7.7 蠕动泵设备驱动

```python
class LabSmartPumpDevice(BaseDevice):
    """LabSmart蠕动泵设备驱动"""
    
    SUPPORTED_COMMANDS = [
        "start_channel", "stop_channel", "pause_channel",
        "set_direction", "set_flow_rate", "set_run_mode",
        "calibrate_flow", "get_channel_status"
    ]
    
    def start_channel(self, channel: int) -> bool:
        """启动指定通道"""
        address = get_channel_address(channel, 1)  # 启停控制寄存器
        return self._write_register(address, PumpRunStatus.START)
    
    def set_flow_rate(self, channel: int, flow_rate: float) -> bool:
        """设置流速 (mL/min)"""
        address = get_channel_address(channel, 110)  # 流速寄存器
        return self._write_float(address, flow_rate)
    
    def set_run_mode(self, channel: int, mode: PumpRunMode) -> bool:
        """设置运行模式"""
        address = get_channel_address(channel, 6)  # 模式寄存器
        return self._write_register(address, mode)
```

---

## 7.8 程序控制器

```python
class ProgramController:
    """程序控制器 - 温度流量联动"""
    
    def __init__(self, heater=None, pump=None):
        self._heater = heater
        self._pump = pump
        self._program = None
        self._running = False
    
    def _execute_step(self, step: ProgramStep) -> bool:
        """执行单个步骤"""
        if step.step_type == StepType.HEAT:
            return self._heater.set_temperature(step.temperature)
        elif step.step_type == StepType.PUMP_START:
            self._pump.set_flow_rate(step.pump_channel, step.pump_flow_rate)
            return self._pump.start_channel(step.pump_channel)
        elif step.step_type == StepType.HOLD:
            time.sleep(step.hold_time)
            return True
        elif step.step_type == StepType.PUMP_STOP:
            return self._pump.stop_channel(step.pump_channel)
```

---

## 7.9 配置管理

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

pumps:
  - device_id: "pump1"
    name: "蠕动泵"
    connection:
      port: "COM4"
      baudrate: 9600
    slave_address: 1
    channels:
      - channel: 1
        enabled: true
        pump_head: 5
        max_flow_rate: 100.0
```

---

## 7.10 控制脚本示例

### 加热器控制

```python
config = HeaterConfig(device_id="heater1", connection_params={'port': 'COM3'})
with AIHeaterDevice(config) as heater:
    heater.set_temperature(100.0)
    heater.start()
    data = heater.read_data()
    print(f"当前温度: {data.pv}°C")
```

### 蠕动泵控制

```python
config = PeristalticPumpConfig(device_id="pump1", connection_params={'port': 'COM4'})
with LabSmartPumpDevice(config) as pump:
    pump.set_flow_rate(1, 50.0)  # 50 mL/min
    pump.start_channel(1)
    time.sleep(60)
    pump.stop_channel(1)
```

### 联动控制

```python
controller = ProgramController(heater, pump)
program = controller.create_simple_program(
    temperature=100.0,
    hold_time=300,
    pump_channel=1,
    pump_flow_rate=50.0
)
controller.load_program(program)
controller.start()
```

---

# 八、安全机制设计

---

## 8.1 安全机制概述

### 为什么需要安全机制？

| 问题 | 后果 | 解决方案 |
|------|------|----------|
| 线程无安全关闭 | 串口被占用 | 全局停止事件 |
| 串口未正确关闭 | 端口残留占用 | try...finally + 强制释放 |
| 多线程并发访问 | 内核死锁 | 串口锁 + 命令队列 |
| 异常崩溃 | 设备失控 | 异常隔离 + 紧急停止 |

---

## 8.2 系统架构图（安全增强版）

```
┌─────────────────────────────────────────────────────────────┐
│                     主程序 (main.py)                         │
│              统一调度、设备管理、流程控制                      │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌───────┐ │
│  │ devices │ │protocols│ │ control │ │ reports │ │utils  │ │
│  │ 设备驱动 │ │通信协议  │ │程序控制  │ │报告生成  │ │安全层 │ │
│  └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘ └───┬───┘ │
│       │          │          │          │           │      │
│       └──────────┴──────────┴──────────┴───────────┘      │
│                           │                                 │
│                    ┌──────┴──────┐                         │
│                    │ SafetyMgr   │                         │
│                    │ 安全管理器   │                         │
│                    │ - 紧急停止   │                         │
│                    │ - 状态监控   │                         │
│                    │ - 资源清理   │                         │
│                    └─────────────┘                         │
├─────────────────────────────────────────────────────────────┤
│                     硬件设备层                               │
│     ┌─────────┐ ┌─────────┐ ┌─────────┐                   │
│     │ 加热器1 │ │ 加热器2 │ │ 蠕动泵  │  ...              │
│     └─────────┘ └─────────┘ └─────────┘                   │
└─────────────────────────────────────────────────────────────┘
```

---

## 8.3 设备安全基类

```python
class SafeDevice(ABC):
    """安全设备基类 - 提供线程安全、异常隔离、紧急停止"""
    
    def __init__(self, device_id: str):
        self._device_id = device_id
        self._state = DeviceState.DISCONNECTED
        self._lock = threading.RLock()  # 线程锁
        self._stop_event = threading.Event()  # 停止事件
    
    def _set_state(self, state: DeviceState):
        """线程安全的状态切换"""
        with self._lock:
            self._state = state
    
    @abstractmethod
    def emergency_stop(self):
        """紧急停止 - 必须实现"""
        pass
    
    def is_running(self) -> bool:
        return self._state == DeviceState.RUNNING
```

---

## 8.4 串口资源管理器

```python
class SerialPortManager:
    """串口资源管理器 - 防止端口冲突"""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def acquire_port(self, port: str, force: bool = False):
        """获取串口（支持强制释放）"""
        if force:
            self._force_release_port(port)
        # 检查并锁定端口
        self._create_lock_file(port)
    
    def _force_release_port(self, port: str):
        """强制释放被占用的端口"""
        # 查找占用进程并终止
        for proc in psutil.process_iter(['pid', 'name']):
            if self._is_port_in_use_by(port, proc):
                proc.terminate()
```

---

## 8.5 安全蠕动泵驱动

```python
class SafePumpDevice(SafeDevice):
    """安全蠕动泵驱动 - 通道隔离 + 命令队列"""
    
    def __init__(self, config: PeristalticPumpConfig):
        super().__init__(config.device_id)
        self._config = config
        self._command_queue = queue.Queue()  # 命令队列
        self._channel_tasks = {}  # 通道任务
    
    def connect(self, force: bool = False) -> bool:
        """安全连接"""
        self._set_state(DeviceState.INITIALIZING)
        try:
            manager = get_serial_manager()
            manager.acquire_port(self._port, force=force)
            self._serial = serial.Serial(...)
            self._set_state(DeviceState.CONNECTED)
            return True
        except Exception as e:
            self._set_state(DeviceState.ERROR)
            raise
    
    def emergency_stop(self):
        """紧急停止所有通道"""
        self._stop_event.set()
        for channel in self._config.channels:
            self._stop_channel_internal(channel.channel)
        self._serial.close()
```

---

## 8.6 全局安全管理器

```python
class DeviceSafetyManager:
    """全局安全管理器"""
    
    _instance = None
    _emergency_callbacks = []
    
    def register_emergency_stop(self, callback: Callable):
        """注册紧急停止回调"""
        self._emergency_callbacks.append(callback)
    
    def emergency_stop_all(self, timeout: float = 3.0):
        """触发全局紧急停止（带超时保护）"""
        # 并行停止所有设备，每个设备最多等待 timeout 秒
        for callback in self._emergency_callbacks:
            try:
                callback()
            except Exception:
                pass
    
    def cleanup_all(self):
        """清理所有资源"""
        self.emergency_stop_all()
        get_serial_manager().cleanup()

# 全局实例
def get_safety_manager() -> DeviceSafetyManager:
    if DeviceSafetyManager._instance is None:
        DeviceSafetyManager._instance = DeviceSafetyManager()
    return DeviceSafetyManager._instance
```

---

## 8.7 信号处理与清理

```python
import signal
import atexit

def setup_signal_handlers():
    """设置信号处理器"""
    safety = get_safety_manager()
    
    def handle_sigint(signum, frame):
        print("\n接收到中断信号，正在安全停止...")
        safety.emergency_stop_all()
        safety.cleanup_all()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, handle_sigint)
    atexit.register(safety.cleanup_all)

# 在程序入口调用
setup_signal_handlers()
```

---

## 8.8 安全机制总结

| 机制 | 实现 | 效果 |
|------|------|------|
| 线程安全 | RLock + Event | 无竞争访问 |
| 资源管理 | 单例管理器 | 无端口冲突 |
| 异常隔离 | try...finally | 崩溃不影响其他设备 |
| 紧急停止 | 全局回调 | 3秒内停止所有设备 |
| 强制释放 | 进程检测 | 解决僵尸占用 |
| 通道隔离 | 独立任务队列 | 单通道异常不影响其他 |

---

# 九、演示与总结

---

## 9.1 已实现功能

| 功能 | 状态 | 说明 |
|------|------|------|
| 温度读取 | ✅ | PV/SV/MV实时读取 |
| 温度设定 | ✅ | 支持安全限温 |
| 运行控制 | ✅ | 启动/停止/保持 |
| 蠕动泵控制 | ✅ | 四通道独立控制 |
| 流量设定 | ✅ | 流速/定量/定时模式 |
| 多设备控制 | ✅ | 多线程并行 |
| 程序联动 | ✅ | 温度+流量协同 |
| 数据监控 | ✅ | 实时采集存储 |
| 报告生成 | ✅ | HTML格式报告 |
| **串口资源管理** | ✅ ⭐新增 | 强制释放、进程锁 |
| **设备安全基类** | ✅ ⭐新增 | 状态监控、异常隔离 |
| **紧急停止** | ✅ ⭐新增 | 全局回调、3秒停止 |
| **通道隔离** | ✅ ⭐新增 | 单通道异常不影响其他 |

---

## 9.2 蠕动泵运行模式

| 模式 | 说明 | 应用场景 |
|------|------|----------|
| 流量模式 | 设置流速持续运行 | 连续输送 |
| 定时定量 | 设定时间后定量分装 | 自动分装 |
| 定时定速 | 设定时间后定速运行 | 定时实验 |
| 定量定速 | 设定总量后定速运行 | 精确计量 |

---

## 9.3 演示：双加热器控制

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

## 9.4 扩展性设计

添加新设备只需3步：

```python
# 1. 继承BaseDevice
class NewDevice(BaseDevice):
    pass

# 2. 实现抽象方法
    def connect(self): ...
    def read_data(self): ...

# 3. 添加到配置文件
new_devices:
  - device_id: "device1"
    connection: {port: "COM5", ...}
```

---

## 8.5 未来规划

- [ ] Web界面远程控制
- [ ] 数据可视化仪表盘
- [ ] 自动化实验流程编排
- [ ] 更多设备支持（阀门、传感器）
- [ ] AI辅助实验优化

---

## 8.6 项目亮点

1. **模块化架构** - 设备独立，易于扩展
2. **多协议支持** - AIBUS + MODBUS-RTU
3. **协议自主实现** - 不依赖厂商DLL
4. **配置驱动** - 无需修改代码
5. **联动控制** - 温度+流量协同
6. **完整日志** - 可追溯、可调试
7. **并行控制** - 多设备同时运行

---

# Q&A

感谢聆听！

项目地址：`d:\AI\Heat\`

---

# 附录：关键文件说明

| 文件 | 功能 | 代码行数 |
|------|------|----------|
| `protocols/aibus.py` | AIBUS协议实现 | ~500 |
| `protocols/modbus_rtu.py` | MODBUS协议实现 | ~400 |
| `devices/heater.py` | 加热器驱动 | ~600 |
| `devices/peristaltic_pump.py` | 蠕动泵驱动 | ~500 |
| `devices/safe_pump.py` | 安全蠕动泵驱动 ⭐新增 | ~400 |
| `devices/base_device.py` | 设备基类 | ~300 |
| `utils/serial_manager.py` | 串口资源管理 ⭐新增 | ~300 |
| `utils/device_safety.py` | 设备安全基类 ⭐新增 | ~250 |
| `control/program_controller.py` | 程序控制器 | ~400 |
| `monitor/data_monitor.py` | 数据监控 | ~400 |
| `reports/report_generator.py` | 报告生成 | ~350 |
| `context/PROJECT_CONTEXT.md` | 项目上下文 ⭐新增 | ~500 |

---

# 📚 参考资料

| 资源 | 说明 |
|------|------|
| pyserial文档 | pythonhosted.org/pyserial |
| MAX232芯片 | RS-232电平转换 |
| MAX485芯片 | RS-485差分收发 |
| CH340驱动 | USB转串口驱动 |
| MODBUS协议 | modbus.org |
| 宇电AIBUS | 宇电仪表通信协议 |
| LabSmart | 蠕动泵通信协议 |
| psutil文档 | 进程管理库 |
| Python threading | 多线程编程 |
| Python signal | 信号处理 |
