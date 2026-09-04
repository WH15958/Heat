# Heat

Heat 是一个面向实验室与小型工业场景的自动化控制系统，用于协调加热器、蠕动泵、实验流程、实时监控和样品记录。

## 你现在应该看什么

- 如果你是 AI / 自动化协作者：看 [context/PROJECT_CONTEXT.md](context/PROJECT_CONTEXT.md)
- 如果你是实验使用者：看 [docs/user_guide.md](docs/user_guide.md)
- 如果你是人类开发者：看 [docs/developer_guide.md](docs/developer_guide.md)

## 项目简介

- 后端：Python + FastAPI
- 前端：Vue 3 + Vite + Element Plus
- 设备：宇电 AI 系列温控器、LabSmart 多通道蠕动泵、MKM-AH1E 微波反应仪
- 协议：AIBUS、MODBUS RTU
- 实验定义：YAML
- 数据能力：实时 WebSocket 推送、实验日志、`samples.csv` 样品记录
- Web 页面：`/`、`/control`、`/experiment`、`/campaigns`、`/history`
- API 前缀：设备 `/api`、实验 `/api/experiments`、Campaign `/api/campaigns`

## 适用人群

- 实验操作人员：通过 Web 页面连接设备、运行实验、查看历史记录
- 开发者：扩展设备驱动、Web API、实验引擎和样品记录能力
- AI 协作者：在不破坏串口同步模型和项目约束的前提下辅助开发

## 快速开始

后端要求 Python 3.10 或更高版本。

### 1. 安装 Python 依赖

推荐使用 Conda：

```powershell
conda env create -f environment.yml
conda activate heat
```

也可以使用 `pip`：

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. 安装前端依赖

```bash
cd frontend
npm install
```

### 3. 构建前端

```bash
npm run build
```

构建产物会输出到 `src/web/static/`，由 FastAPI 直接托管。

### 4. 启动服务

```bash
cd ..
python run_server.py
```

浏览器访问 `http://localhost:8000`。

## 文档导航

### 面向 AI

- [context/PROJECT_CONTEXT.md](context/PROJECT_CONTEXT.md)：项目事实、硬约束、历史决策、AI 工作规则

### 面向使用者

- [docs/user_guide.md](docs/user_guide.md)：系统启动、页面使用、实验执行、行为语义、常见问题
- [docs/mvp_device_ready_runbook.md](docs/mvp_device_ready_runbook.md)：设备就位后的水/替代液闭环 MVP 操作顺序和材料入口
- [docs/mvp_system_acceptance_checklist.md](docs/mvp_system_acceptance_checklist.md)：MVP Gate 验收、证据和签字的唯一记录
- [docs/microwave_smoke_test.md](docs/microwave_smoke_test.md)：微波仪分级实机 smoke test
- [docs/campaign_workflow.md](docs/campaign_workflow.md)：批次式人工闭环优化、Trial 与离线表征录入流程
- [docs/system_engineering_design.md](docs/system_engineering_design.md)：当前水测试液路、死体积、预灌和三层标定的长期工程参考
- [docs/device_materials/](docs/device_materials/)：设备说明书、通信协议原始资料和转换版资料
- [docs/experiment_yaml_spec.md](docs/experiment_yaml_spec.md)：实验 YAML 规范与示例
- [docs/troubleshooting.md](docs/troubleshooting.md)：常见故障排查

### 面向开发者

- [docs/developer_guide.md](docs/developer_guide.md)：架构、扩展、调试、测试、提交流程
- [docs/testing_and_merge_flow.md](docs/testing_and_merge_flow.md)：验证、文档同步、commit、push、双远程流程
- [docs/experiment_yaml_spec.md](docs/experiment_yaml_spec.md)：实验定义格式与引擎输入契约

## 当前支持的能力概览

- 加热器连接、温度设定、启动和停止
- 蠕动泵 1-4 通道控制，支持四种运行模式
- 微波仪连接、状态读取、参数配置、启动和停止
- Web 实时仪表盘与控制面板
- Campaign、Trial、人工 recommendation 与离线表征记录
- 单实验运行保护、暂停、恢复、停止
- 实验日志保存开关、历史记录查询与删除
- metadata 到 `sample_id` 到 `samples.csv` 的样品追踪链路

实验页面只列出 `experiments/` 中经过当前审查的可执行 YAML。归档示例不会出现在实验列表中，也不代表已经通过当前硬件与安全验收；活动流程仍须按 Gate 清单完成实机放行。

## 最小开发 / 测试命令

```powershell
python tests\test_metadata.py
python tests\test_code_review_fixes.py
python -c "import src.web.app; import src.web.api.experiments; import src.web.api.ws"
npm --prefix frontend run build
```

## 重要约束

- 串口驱动必须保持纯同步、无线程
- Web 层只能桥接同步设备，不应改变设备语义
- `output/` 是运行产物，不应纳入版本控制
- 文档变更需要和代码行为保持同步
