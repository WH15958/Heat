# Heat

Heat 是一个面向实验室与小型工业场景的自动化控制系统，用于协调加热器、蠕动泵、实验流程、实时监控和样品记录。

## 你现在应该看什么

- 如果你是 AI / 自动化协作者：看 [context/PROJECT_CONTEXT.md](context/PROJECT_CONTEXT.md)
- 如果你是实验使用者：看 [docs/user_guide.md](docs/user_guide.md)
- 如果你要安装或使用 Windows 桌面版：看 [docs/desktop_app.md](docs/desktop_app.md)
- 如果你是人类开发者：看 [docs/developer_guide.md](docs/developer_guide.md)

## 项目简介

- 后端：Python + FastAPI
- 前端：Vue 3 + Vite + Element Plus
- 设备：宇电 AI 系列温控器、LabSmart 多通道蠕动泵、MKM-AH1E 微波反应仪
- 协议：AIBUS、MODBUS RTU
- 实验定义：YAML，支持图形编排与 YAML 双模式编辑
- 数据能力：实时 WebSocket 推送、实验日志、`samples.csv` 样品记录
- Web 页面：`/`、`/control`、`/experiment`、`/experiment/editor`、`/experiment/batch`、`/campaigns`、`/history`
- API 前缀：设备 `/api`、实验 `/api/experiments`、引导式批次 `/api/guided`、Campaign `/api/campaigns`
- 引导式批次：固定装置条件组合、双泵协调、45℃降温后自动从产物出口收取、收取清洗和逐组记录；复用真实设备接口，软件验证不替代设备验收。操作见 [用户指南](docs/user_guide.md#引导式批次实验)。

## 适用人群

- 实验操作人员：通过 Web 页面连接设备、运行实验、查看历史记录
- 开发者：扩展设备驱动、Web API、实验引擎和样品记录能力
- AI 协作者：在不破坏串口同步模型和项目约束的前提下辅助开发

## 快速开始

Windows 桌面版面向 Windows 11 x64，安装包内置 Python 并随附 WebView2 离线安装程序；首次导入现有工作区，关闭窗口收至托盘，明确退出才执行停机与保存。安装、数据位置、构建和待完成的虚拟机/实机验收见 [桌面版说明](docs/desktop_app.md)。以下保留原浏览器运行方式。

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

构建机需要 Node.js `^20.19.0 || >=22.12.0`（与当前锁文件中的 Vite/Rolldown 要求一致）；本轮验证环境为 Node.js 24.21.0。桌面安装目标机不需要 Node.js 或 npm。

```bash
cd frontend
npm ci
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

Windows 完成上述依赖安装和前端构建后，也可双击根目录的 `start_heat.bat`。启动器会检查环境和页面文件，确认 Heat 就绪后打开浏览器；保留服务窗口，用 `Ctrl+C` 正常退出。环境选择、失败日志和端口冲突处理见 [用户指南](docs/user_guide.md#11-启动后端服务)。

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
- CL-01A 接样转盘手动控制与停止监督；定位编码及机械回零待现场核验，见 [转盘接入说明](docs/turntable_integration.md)
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


### MSP1-CX 注射泵

支持两台独立注射泵的手动控制、OEM/DT通信、有限程序、YAML自动化与历史记录；两台均已登记设备身份和通信配置，实际端口由串口指纹解析确定。软件验证通过，实机验收待进行。见 [接入说明与功能覆盖](docs/syringe_pump_integration.md)、[现场验收清单](docs/syringe_pump_acceptance.md)。
