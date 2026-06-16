# Heat 使用者指南

面向实验操作人员。本文只回答三类问题：怎么启动、怎么操作、出问题怎么看。  
如果你要修改代码，请转 [developer_guide.md](developer_guide.md)。

---

## 你现在应该看什么

- 想启动系统：看“系统启动”
- 想操作页面：看“页面与操作”
- 想编写实验：先看本文，再看 [experiment_yaml_spec.md](experiment_yaml_spec.md)
- 想排错：看 [troubleshooting.md](troubleshooting.md)

---

## 1. 系统启动

### 1.1 启动后端服务

```bash
conda activate heat
python run_server.py
```

默认访问地址：

- `http://localhost:8000`

### 1.2 前端更新后的处理

如果有人修改了前端代码，需要重新构建：

```bash
cd frontend
npm run build
```

构建产物会写入 `src/web/static/`。如果页面看起来没更新，先按 `Ctrl+Shift+R` 强制刷新浏览器。

---

## 2. 页面与操作

### 2.1 页面入口

系统包含 4 个主要页面：

| 页面 | 路径 | 作用 |
|------|------|------|
| 实时仪表盘 | `/` | 查看实时温度、泵状态与推送数据 |
| 设备控制 | `/control` | 连接设备、控制加热器与泵 |
| 实验页面 | `/experiment` | 选择 YAML 实验、启动、暂停、恢复、停止 |
| 历史记录 | `/history` | 查看实验历史记录和已保存日志 |

### 2.2 设备连接

在设备控制页面中：

1. 找到目标设备
2. 点击“连接”
3. 连接成功后状态会更新

如果连接失败，优先检查：

- 设备是否通电
- 串口号是否与 `config/system_config.yaml` 一致
- 是否有其他程序占用串口

### 2.3 加热器操作

可执行的核心操作：

- 设置目标温度
- 启动加热
- 停止加热

### 2.4 蠕动泵操作

每个泵可按通道独立控制。当前支持 4 种模式：

- `FLOW_MODE`
- `TIME_QUANTITY`
- `TIME_SPEED`
- `QUANTITY_SPEED`

如果你只需要会用，直接在页面里选模式、填参数即可。  
如果你需要理解 YAML 字段和单位，请看 [experiment_yaml_spec.md](experiment_yaml_spec.md)。
如果你要把蠕动泵接入前驱体管路、微波入口或长管路定量输运，请先按 [system_engineering_design.md](system_engineering_design.md) 做死体积、预灌和真实流量标定。

---

## 3. 实验执行

### 3.1 启动实验

1. 打开 `/experiment`
2. 在左侧选择 YAML 实验
3. 确认是否开启“保存日志”
4. 点击“启动”

### 3.2 实验状态说明

| 状态 | 含义 |
|------|------|
| `idle` | 当前实验未运行 |
| `running` | 正在执行步骤 |
| `paused` | 已暂停，可恢复 |
| `completed` | 全部步骤已完成 |
| `failed` | 某个步骤失败，实验中止 |
| `stopped` | 用户手动停止 |

### 3.3 单实验保护

系统同一时刻只允许一个实验处于：

- `running`
- `paused`

如果已有实验在运行或暂停，启动另一个实验会被拒绝。

---

## 4. 行为语义

这部分非常重要，回答的是“按钮按下去以后系统到底会怎么做”。

### 4.1 停止 / 暂停 / 恢复的区别

#### 停止

- stop 会中断当前等待步骤
- 实验会尽快结束为 `stopped`
- stop 是终止当前 run，不是临时挂起

#### 暂停

- pause 会让实验进入 `paused`
- 暂停后可以继续 `resume`
- 暂停不会自动把 run 改成完成或失败

#### 恢复

- resume 会从暂停状态继续执行
- 只对当前 paused 的实验有效

### 4.2 等待超时后会发生什么

如果等待条件超时，例如：

- 等温未达到目标
- 泵完成等待超时

系统会把该步骤视为失败，而不是静默继续往后执行。

### 4.3 浏览器刷新 / 关闭是否会影响设备

不会因为页面断开就自动停止设备。

浏览器刷新、关闭或 WebSocket 重连不会等同于“停止实验”或“停止泵”。  
如果你要真正停设备，请使用页面按钮或明确的控制接口。

### 4.4 日志保存开关的影响

启动实验时可选择是否保存日志：

- 开启：实验日志会写入历史记录与原始日志文件
- 关闭：仍可实时看到日志，但不保存原始日志文件

### 4.5 `samples.csv`、历史记录、原始日志的关系

- `samples.csv`：面向样品追踪，记录 `sample_id`、batch、condition、状态等
- 历史记录：面向实验运行查看
- 原始日志：面向排查和还原 run 细节

它们相关，但不是同一个东西。

---

## 5. YAML 实验怎么用

如果你只是想会用，记住下面几点就够了：

- 实验文件放在 `experiments/`
- 文件后缀必须是 `.yaml` 或 `.yml`
- 每个实验至少要有 `steps`
- 每个步骤至少要有 `id` 和 `type`

最小示例：

```yaml
name: simple_heat_test
description: 简单加热测试
steps:
  - id: set_temp
    type: heater.set_temperature
    params:
      device_id: heater1
      temperature: 50.0
```

需要完整字段、动作表、等待表、metadata 说明时，请看：

- [experiment_yaml_spec.md](experiment_yaml_spec.md)

---

## 6. 历史记录与日志

你可以在历史页面查看：

- 已保存的实验 run
- 运行状态
- 原始日志内容

历史记录更适合回顾实验过程；`samples.csv` 更适合做样品维度的追踪。

---

## 7. 最少可用 API 示例

如果你只是偶尔需要通过脚本触发系统，以下示例足够：

### 7.1 启动实验

```bash
curl -X POST http://localhost:8000/api/experiments/simple_heat_test.yaml/start ^
  -H "Content-Type: application/json" ^
  -d "{\"save_log\": true}"
```

### 7.2 暂停 / 恢复 / 停止实验

```bash
curl -X POST http://localhost:8000/api/experiments/simple_heat_test.yaml/pause
curl -X POST http://localhost:8000/api/experiments/simple_heat_test.yaml/resume
curl -X POST http://localhost:8000/api/experiments/simple_heat_test.yaml/stop
```

### 7.3 查询实验进度

```bash
curl http://localhost:8000/api/experiments/simple_heat_test.yaml/progress
```

---

## 8. 常见问题

### 8.1 实验为什么启动不了

常见原因：

- 已有其他实验处于运行或暂停状态
- YAML 文件名不合法
- YAML 缺少 `steps`
- 设备未连接，导致第一步立即失败

### 8.2 为什么实验一开始就失败

常见原因：

- 加热器或泵未连接
- YAML 参数不完整
- 设备命令返回失败

### 8.3 为什么页面上看不到实时数据

常见原因：

- 设备尚未连接
- WebSocket 未连上
- 页面未刷新到最新前端版本

### 8.4 为什么停止后很快就结束

这是当前设计的预期行为。  
stop 会尽快中断等待并结束实验，而不是等完整等待时间走完。

---

## 9. 去哪继续看

- YAML 规范： [experiment_yaml_spec.md](experiment_yaml_spec.md)
- 故障排查： [troubleshooting.md](troubleshooting.md)
- 开发维护： [developer_guide.md](developer_guide.md)
