# Heat 自动化实验使用教程

面向实验操作人员，介绍如何使用 Heat 系统进行自动化实验。

---

## 目录

1. [系统启动](#1-系统启动)
2. [Web界面概览](#2-web界面概览)
3. [设备连接与管理](#3-设备连接与管理)
4. [实时仪表盘](#4-实时仪表盘)
5. [设备控制面板](#5-设备控制面板)
6. [实验自动化](#6-实验自动化)
7. [编写实验流程（YAML）](#7-编写实验流程yaml)
8. [命令行实验脚本](#8-命令行实验脚本)
9. [数据记录与报告](#9-数据记录与报告)
10. [紧急停止](#10-紧急停止)
11. [常见问题](#11-常见问题)

---

## 1. 系统启动

### 启动 Web 服务器

```bash
conda activate heat
python run_server.py
```

启动成功后会显示：

```
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     Application startup complete.
```

在浏览器中访问 **http://localhost:8000** 即可打开控制界面。

### 修改端口

如需修改端口，编辑 `run_server.py` 中的端口号：

```python
uvicorn.run(app, host="0.0.0.0", port=8000)
```

---

## 2. Web界面概览

Web界面包含三个主要页面，通过顶部导航栏切换：

| 页面 | 路径 | 功能 |
|------|------|------|
| 实时仪表盘 | `/` | 温度曲线、流量曲线实时显示 |
| 设备控制面板 | `/control` | 加热器/蠕动泵操作控制 |
| 实验自动化 | `/experiments` | YAML实验流程管理 |

---

## 3. 设备连接与管理

### 通过Web界面连接

1. 打开 **设备控制面板** 页面
2. 在左侧设备列表中点击 **连接** 按钮
3. 连接成功后设备状态变为绿色"已连接"

### 通过API连接

```bash
# 连接加热器
curl -X POST http://localhost:8000/api/devices/heater1/connect

# 连接蠕动泵
curl -X POST http://localhost:8000/api/devices/pump1/connect
```

### 查看设备状态

```bash
# 查看所有设备状态
curl http://localhost:8000/api/devices/status

# 查看加热器数据
curl http://localhost:8000/api/devices/heater1/data

# 查看蠕动泵数据
curl http://localhost:8000/api/devices/pump1/data
```

---

## 4. 实时仪表盘

仪表盘页面提供两个实时图表：

### 温度曲线
- 显示所有已连接加热器的实时温度（PV）
- 1秒刷新一次
- 不同加热器用不同颜色区分
- 自动滚动显示最近数据

### 流量曲线
- 显示蠕动泵各通道的实时流量
- 4个通道用4种颜色区分（通道1-蓝，通道2-绿，通道3-橙，通道4-红）
- 与温度曲线同步刷新

> **提示**：数据通过 WebSocket 实时推送，无需手动刷新页面。

---

## 5. 设备控制面板

### 加热器控制

| 操作 | 说明 |
|------|------|
| 设置温度 | 输入目标温度（°C），点击"设置" |
| 启动加热 | 点击"启动"按钮 |
| 停止加热 | 点击"停止"按钮 |
| 紧急停止 | 点击红色"紧急停止"按钮 |

### 蠕动泵控制

蠕动泵支持4个通道独立控制，每个通道可设置：

| 参数 | 说明 |
|------|------|
| 流量 | 设置流速（mL/min） |
| 方向 | 顺时针/逆时针 |
| 模式 | 4种运行模式（见下文） |
| 启动/停止 | 独立控制每个通道 |

### 泵运行模式

| 模式 | 说明 | 需设置参数 |
|------|------|------------|
| 流量模式 | 设置流速持续运行 | 流量 |
| 定时定量 | 设定时间内完成定量分装 | 流量 + 时间 + 总量 |
| 定时定速 | 设定时间内定速运行 | 流量 + 时间 |
| 定量定速 | 设定总量后定速运行 | 流量 + 总量 |

---

## 6. 实验自动化

实验自动化功能允许你通过 YAML 文件定义实验流程，系统自动按步骤执行。

### 界面操作

1. 打开 **实验自动化** 页面
2. 左侧显示可用实验列表
3. 点击实验名称查看步骤详情
4. 点击 **启动** 开始执行实验
5. 实验运行中可 **暂停** / **恢复** / **停止**

### 实验状态

| 状态 | 颜色 | 说明 |
|------|------|------|
| 空闲 | 灰色 | 实验未启动 |
| 运行中 | 绿色 | 正在执行步骤 |
| 已暂停 | 黄色 | 实验已暂停，可恢复 |
| 已完成 | 蓝色 | 所有步骤执行完毕 |
| 失败 | 红色 | 某步骤执行出错 |
| 已停止 | 灰色 | 用户手动停止 |

### 通过API操作

```bash
# 列出可用实验
curl http://localhost:8000/api/experiments/

# 获取实验详情
curl http://localhost:8000/api/experiments/simple_heat_test.yaml

# 启动实验
curl -X POST http://localhost:8000/api/experiments/simple_heat_test.yaml/start

# 暂停实验
curl -X POST http://localhost:8000/api/experiments/simple_heat_test.yaml/pause

# 恢复实验
curl -X POST http://localhost:8000/api/experiments/simple_heat_test.yaml/resume

# 停止实验
curl -X POST http://localhost:8000/api/experiments/simple_heat_test.yaml/stop

# 查询实验状态
curl http://localhost:8000/api/experiments/simple_heat_test.yaml/status
```

---

## 7. 编写实验流程（YAML）

### 基本结构

```yaml
name: 实验名称
description: 实验描述
steps:
  - name: 步骤1名称
    action: 动作类型
    params:
      参数1: 值1
      参数2: 值2
```

### 可用动作类型

#### 设备控制动作

| 动作 | 说明 | 必需参数 |
|------|------|----------|
| `set_temperature` | 设置加热器目标温度 | `device_id`, `temperature` |
| `start_heater` | 启动加热器 | `device_id` |
| `stop_heater` | 停止加热器 | `device_id` |
| `set_flow_rate` | 设置泵通道流速 | `device_id`, `channel`, `flow_rate` |
| `start_pump` | 启动泵通道 | `device_id`, `channel` |
| `stop_pump` | 停止泵通道 | `device_id`, `channel` |

#### 等待条件动作

| 动作 | 说明 | 必需参数 |
|------|------|----------|
| `wait` | 等待指定秒数 | `duration` |
| `wait_temperature` | 等待温度达到目标 | `device_id`, `target`, `tolerance`, `timeout` |
| `wait_time` | 等待指定秒数（同wait） | `duration` |

### 示例1：简单加热测试

```yaml
name: simple_heat_test
description: 简单加热测试 - 升温到80度后保持10分钟
steps:
  - name: 设置温度80度
    action: set_temperature
    params:
      device_id: heater1
      temperature: 80.0

  - name: 启动加热器
    action: start_heater
    params:
      device_id: heater1

  - name: 等待温度达到80度
    action: wait_temperature
    params:
      device_id: heater1
      target: 80.0
      tolerance: 2.0
      timeout: 600

  - name: 保持10分钟
    action: wait
    params:
      duration: 600

  - name: 停止加热器
    action: stop_heater
    params:
      device_id: heater1
```

### 示例2：化学合成实验

```yaml
name: chemical_synthesis_A
description: 化学合成实验A - 双加热器+蠕动泵协同
steps:
  - name: 设置反应温度
    action: set_temperature
    params:
      device_id: heater1
      temperature: 120.0

  - name: 设置冷凝温度
    action: set_temperature
    params:
      device_id: heater2
      temperature: 60.0

  - name: 启动两个加热器
    action: start_heater
    params:
      device_id: heater1

  - name: 启动冷凝器
    action: start_heater
    params:
      device_id: heater2

  - name: 等待反应温度
    action: wait_temperature
    params:
      device_id: heater1
      target: 120.0
      tolerance: 3.0
      timeout: 900

  - name: 启动进料泵
    action: set_flow_rate
    params:
      device_id: pump1
      channel: 1
      flow_rate: 5.0

  - name: 开始进料
    action: start_pump
    params:
      device_id: pump1
      channel: 1

  - name: 进料30分钟
    action: wait
    params:
      duration: 1800

  - name: 停止进料
    action: stop_pump
    params:
      device_id: pump1
      channel: 1

  - name: 继续反应1小时
    action: wait
    params:
      duration: 3600

  - name: 停止所有设备
    action: stop_heater
    params:
      device_id: heater1

  - name: 停止冷凝器
    action: stop_heater
    params:
      device_id: heater2
```

### 保存实验文件

将 YAML 文件保存到 `experiments/` 目录下，文件名以 `.yaml` 或 `.yml` 结尾：

```
experiments/
├── chemical_synthesis_A.yaml
├── simple_heat_test.yaml
└── my_experiment.yaml        ← 你的实验文件
```

保存后在Web界面的实验列表中即可看到新实验。

---

## 8. 命令行实验脚本

除了Web界面的实验自动化，也可以使用Python脚本直接运行实验。

### 化学合成实验

```bash
python scripts/chemical_synthesis_experiment.py \
    --heater1-port COM7 \
    --heater2-port COM9 \
    --pump-port COM10 \
    --force
```

参数说明：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--heater1-port` | 主加热器串口 | COM7 |
| `--heater2-port` | 冷凝器串口 | COM9 |
| `--pump-port` | 蠕动泵串口 | COM10 |
| `--force` | 强制释放被占用的串口 | - |

### 纯加热实验

```bash
python scripts/heater_only_experiment.py
```

### 设备连接测试

```bash
python scripts/test_connections.py
```

---

## 9. 数据记录与报告

### 自动数据记录

Web服务器运行期间，所有已连接设备的数据会自动记录到CSV文件：

- 保存位置：`output/` 目录
- 文件格式：`{prefix}_{device_id}_{timestamp}.csv`
- 记录频率：约1Hz（与WebSocket推送同步）

### CSV数据格式

加热器数据：

| 列名 | 说明 |
|------|------|
| timestamp | 时间戳 |
| pv | 测量温度 |
| sv | 设定温度 |
| mv | 输出百分比 |
| alarm_status | 报警状态 |

蠕动泵数据：

| 列名 | 说明 |
|------|------|
| timestamp | 时间戳 |
| channel | 通道号 |
| flow_rate | 当前流量 |
| current_speed | 当前转速 |
| dispensed_volume | 已分配体积 |

### 生成实验报告

通过Python脚本运行的实验会自动生成HTML报告，包含：

- 温度曲线图
- 泵流量曲线图
- 实验参数摘要
- 数据统计

---

## 10. 紧急停止

### Web界面紧急停止

在设备控制面板中点击红色 **紧急停止** 按钮。

### API紧急停止

```bash
# 停止所有设备
curl -X POST http://localhost:8000/api/devices/emergency-stop

# 停止指定设备
curl -X POST "http://localhost:8000/api/devices/emergency-stop?device_id=heater1"
```

### 命令行紧急停止

在运行脚本的终端按 **Ctrl+C**，系统会自动：
1. 停止所有加热器
2. 停止所有蠕动泵
3. 关闭串口连接
4. 保存数据记录

---

## 11. 常见问题

### Q: Web页面打不开？

1. 确认 `run_server.py` 正在运行
2. 确认浏览器访问 `http://localhost:8000`（注意不是 https）
3. 检查防火墙是否阻止了8000端口

### Q: 设备连接失败？

1. 确认设备已通电并连接到正确的串口
2. 在Windows设备管理器中查看COM口号
3. 确认串口没有被其他程序占用
4. 使用 `--force` 参数强制释放串口

### Q: 串口被占用？

```bash
# 查看串口占用
python scripts/test_connections.py

# 强制释放
python scripts/cleanup_locks.py --force --port COM7
```

### Q: 实验执行失败？

1. 确认所有需要的设备已连接
2. 确认YAML文件中的 `device_id` 与配置文件一致
3. 检查 `wait_temperature` 的 `timeout` 是否足够
4. 查看Web界面的实验状态和错误信息

### Q: 温度数据不更新？

1. 确认加热器已连接
2. 刷新Web页面
3. 检查浏览器控制台是否有WebSocket连接错误
4. 重启Web服务器

### Q: 泵通道无法启动？

1. 确认通道已启用（`enabled: true`）
2. 确认已设置流量或模式参数
3. 检查泵的运行模式是否正确
4. 确认泵头和管路型号配置正确

---

## 快速参考卡

```
启动服务器:     python run_server.py
Web地址:        http://localhost:8000
设备连接:       控制面板 → 连接按钮
查看数据:       仪表盘页面（自动刷新）
运行实验:       实验页面 → 选择实验 → 启动
紧急停止:       控制面板 → 紧急停止按钮
实验文件目录:   experiments/
数据输出目录:   output/
配置文件:       config/system_config.yaml
```
