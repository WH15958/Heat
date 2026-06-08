# Heat 项目代码审查报告

> 审查日期：2026-05-15（第三次审查，项目已趋于稳定）

---

## 总体评价

项目质量 **中上**。架构清晰、分层合理，协议层和设备驱动层实现扎实。经多轮重构，依赖管理、配置加载、前端组件、CLI 泵支持等问题已全部解决。

| 维度 | 评分 | 备注 |
|------|:----:|------|
| 架构设计 | ★★★★ | 分层合理，单向依赖清晰 |
| 代码质量 | ★★★★ | 协议层优秀，驱动层组织良好 |
| 安全性 | ★★★★★ | 考虑周全 |
| 依赖管理 | ★★★★★ | 三份文件完全统一 |
| 文档 | ★★★★★ | 过期引用已全部清理 |
| 测试覆盖 | ★★ | 唯一短板，无单元测试 |
| 前端质量 | ★★★★ | 组件化良好，HeaterControl/PumpControl 独立 |

---

## 1. 架构

### 1.1 分层架构（严格的单向依赖）

```
前端 (Vue 3) → WebSocket + REST API →
  Web 服务 (FastAPI) →
    实验引擎 (asyncio) →
      设备管理器 (DeviceManager) →
        设备驱动 (纯同步，无线程) →
          协议 (AIBUS / MODBUS-RTU) →
            串口 (串行访问)
```

### 1.2 关键架构模式

- **`run_in_executor` 桥接**：异步 FastAPI/实验引擎通过 `loop.run_in_executor(None, sync_func)` 调用同步设备驱动
- **每设备一个锁**：`DeviceManager` 为每台泵维护一个 `threading.Lock()`，将多通道操作串行化到同一串口
- **WebSocket 实时推送**：后台任务每秒轮询所有已连接设备，通过 WebSocket 广播 JSON 负载
- **YAML 驱动实验**：实验由 YAML 文件定义，解析为 `ExperimentStep` 列表，由状态机逐步执行
- **无后台线程数据记录**：`CSVDataLogger` 完全在主线程运行，手动调用 `record()`，定时刷新
- **进程级串口锁**：`SerialPortLock` 在临时目录使用原子文件创建操作，防止多进程串口冲突
- **看门狗守护**：如果主进程无响应超过 120 秒，看门狗线程会自动触发清理

### 1.3 安全机制

| 机制 | 位置 |
|------|------|
| 温度安全硬限制 450°C | `devices/heater.py` |
| `atexit` 注册紧急停止 | `DeviceManager` |
| WebSocket 看门狗（120s 超时） | `utils/serial_manager.py` |
| 串口进程锁文件 | `utils/serial_manager.py` |
| XSS 防护（html.escape） | `reports/report_generator.py` |
| CORS 白名单 | `web/app.py` |
| 路径遍历防护（Path.resolve()） | `experiment/parser.py` |
| 泵参数范围验证 | `device_manager.py` |

---

## 2. 目录结构

```
D:\AI\Heat/
├── pyproject.toml                    # 项目配置（完整）
├── requirements.txt                  # pip 依赖（完备）
├── environment.yml                   # Conda 环境（完备）
├── run_server.py                     # uvicorn 启动入口
├── .gitignore
├── README.md                         # 文档（已清理过期引用）
│
├── config/
│   └── system_config.yaml
│
├── src/                              # Python 主源代码
│   ├── main.py                       # CLI 入口（泵支持已完善）
│   ├── devices/                      # 设备驱动层（纯同步）
│   │   ├── base_device.py            # 抽象基类
│   │   ├── heater.py                 # AI 加热器驱动（697 行）
│   │   └── peristaltic_pump.py       # LabSmart 蠕动泵驱动（1240 行）
│   ├── protocols/                    # 通信协议层
│   │   ├── aibus.py                  # AIBUS 协议
│   │   ├── modbus_rtu.py             # MODBUS-RTU 协议
│   │   ├── parameters.py             # 加热器参数代号
│   │   └── pump_params.py            # 蠕动泵寄存器映射
│   ├── experiment/                   # 实验自动化引擎
│   │   ├── actions.py
│   │   ├── engine.py                 # 状态机引擎
│   │   ├── executor.py               # 步骤执行器
│   │   ├── experiment_logger.py
│   │   └── parser.py                 # YAML 解析器
│   ├── control/
│   │   └── program_controller.py
│   ├── web/                          # Web 服务层
│   │   ├── app.py                    # FastAPI 入口（统一 ConfigManager）
│   │   ├── device_manager.py         # 设备管理器（泵逻辑已重构）
│   │   ├── static/                   # 前端构建产物
│   │   └── api/
│   │       ├── devices.py
│   │       ├── ws.py
│   │       └── experiments.py
│   ├── reports/
│   │   └── report_generator.py
│   ├── utils/
│   │   ├── config.py                 # 配置管理（from_dict 过滤修复）
│   │   ├── serial_manager.py
│   │   ├── csv_logger.py
│   │   └── logger.py
│   └── monitor/                      # 已废弃
│
├── frontend/                         # Vue 3 + TypeScript
│   └── src/
│       ├── main.ts
│       ├── App.vue
│       ├── api/devices.ts
│       ├── composables/useWebSocket.ts
│       ├── router/index.ts
│       ├── components/
│       │   ├── HeaterControl.vue      # 加热器控制
│       │   └── PumpControl.vue        # 蠕动泵控制
│       └── views/
│           ├── Dashboard.vue         # 301 行
│           ├── ControlPanel.vue       # 402 行（已拆分）
│           ├── ExperimentPage.vue     # 523 行
│           └── HistoryPage.vue       # 559 行
│
├── experiments/                      # YAML 实验定义
│   ├── simple_heat_test.yaml
│   ├── chemical_synthesis_A.yaml
│   └── pump_four_channel_demo.yaml
│
├── scripts/
│   └── cleanup_locks.py
│
└── tests/                            # 测试（唯一短板）
    ├── test_heater.py
    └── test_hardware.py
```

---

## 3. 依赖管理（已完全统一）

三份依赖文件内容完全一致，无冗余、无遗漏：

| 依赖 | pyproject.toml | requirements.txt | environment.yml | 实际使用 |
|------|:---:|:---:|:---:|:---:|
| pyserial | ✅ | ✅ | ✅ | ✅ 串口通信 |
| fastapi | ✅ | ✅ | ✅ | ✅ Web 框架 |
| uvicorn | ✅ | ✅ | ✅ | ✅ ASGI 服务器 |
| websockets | ✅ | ✅ | ✅ | ✅ WebSocket |
| matplotlib | ✅ | ✅ | ✅ | ✅ 图表生成 |
| PyYAML | ✅ | ✅ | ✅ | ✅ 配置/实验解析 |
| pydantic | ✅ | ✅ | ✅ | ✅ FastAPI 数据验证 |
| pywin32 | 可选 | 注释 | — | Windows 串口 |
| psutil | 可选 | 注释 | — | Windows 串口 |

---

## 4. 配置加载（已修复）

- Web 服务器统一使用 `ConfigManager` 进行 dataclass 验证加载
- `_convert_dict_to_config` 使用 `from_dict()` 过滤 YAML 中多余的 `stopbits`/`bytesize` 键，不再抛 `TypeError`
- 服务器启动正常，`heater1`、`heater2`、`pump1` 正确注册

---

## 5. 代码质量

### 5.1 优秀部分

| 模块 | 说明 |
|------|------|
| `protocols/aibus.py` | AIBUS 协议实现完整，8字节命令/10字节响应，自定义校验和 |
| `protocols/modbus_rtu.py` | MODBUS-RTU 实现规范，03/06/10 功能码，CRC-16，大端浮点 |
| `devices/peristaltic_pump.py` | 1240 行，4通道、4种运行模式、校准、自动重连 |
| `experiment/engine.py` | 状态机：IDLE→RUNNING→PAUSED/COMPLETED/FAILED/STOPPED |
| `frontend/` | TypeScript 类型完善，`useWebSocket.ts` 引用计数 + 自动重连 |

### 5.2 全部已修复的问题

| 原问题 | 修复方式 |
|--------|----------|
| 依赖管理三份文件不一致 | 统一为 7 个核心依赖，删除 `PyPDF2`/`pefile`，补充 `fastapi`/`uvicorn`/`websockets`/`pydantic` |
| 配置加载双路径 | `web/app.py` 改用 `ConfigManager` |
| `config.py` `ConfigManager` 解析 `stopbits` 报错 | `_convert_dict_to_config` 改用 `from_dict()` |
| `src/main.py` 泵支持不完整 | `get_device_status()`、`get_all_status()`、`record_device_data()` 增加泵遍历 |
| `ControlPanel.vue` 过重（598 行） | 拆分为 `HeaterControl.vue` + `PumpControl.vue`，父组件降至 402 行 |
| `device_manager.py` 泵启动逻辑过长（197 行） | 提取 `_validate_pump_units`、`_set_pump_flow_and_mode`、`_set_pump_mode_params` |
| 两套实验执行范式 | 删除 `scripts/chemical_synthesis_experiment.py` |
| `environment.yml` 重复依赖 | 已清理 |
| `README.md` 过期脚本引用 | 已更新 |
| `context/PROJECT_CONTEXT.md` 过期引用 | 已更新 |
| `scripts/__pycache__/` .pyc 残留 | 已清理 |

---

## 6. 建议事项

### 当前唯一短板：测试覆盖

```
tests/
├── test_heater.py       # 硬件集成测试
└── test_hardware.py     # 硬件集成测试
```

2 个文件均依赖真实硬件，无单元测试。

### 建议（优先级）

| # | 事项 | 说明 |
|---|------|------|
| 1 | 协议层单元测试 | AIBUS 报文编解码、MODBUS CRC-16 校验 |
| 2 | 实验引擎状态机测试 | 模拟步骤执行，验证状态转换 |
| 3 | 设备驱动 mock 测试 | 使用 mock 串口隔离测试逻辑 |
| 4 | 前端组件测试 | Vue Test Utils + vitest |

---

## 变更记录

| 日期 | 变更 |
|------|------|
| 2026-05-15 | 初版审查：发现依赖不一致、配置双路径、两套实验范式等 9 个问题 |
| 2026-05-15 | 二次审查：依赖已统一、配置加载已修复、main.py 泵支持已补充、ControlPanel 已拆分、重复脚本已删除 |
| 2026-05-15 | 三次审查：environment.yml 重复已清理、pydantic 已补充、README 过期引用已删除、config.py from_dict 已修复、__pycache__ 已清理——所有已知问题已解决，项目趋于稳定 |
