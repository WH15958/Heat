# 04 前端控制与仪表盘

## 目标

在 `03_backend_api_ws.md` 完成后，为微波仪新增前端手动控制和仪表盘展示。此任务只做前端，不做 YAML 自动化。

## 输入资料

- `docs/dev_tasks/microwave/00_index.md`
- `docs/dev_tasks/microwave/03_backend_api_ws.md`
- `frontend/src/api/devices.ts`
- `frontend/src/composables/useWebSocket.ts`
- `frontend/src/views/ControlPanel.vue`
- `frontend/src/views/Dashboard.vue`
- `frontend/src/components/HeaterControl.vue`
- `frontend/src/components/PumpControl.vue`

## 允许修改

- `frontend/src/api/devices.ts`
- `frontend/src/composables/useWebSocket.ts`
- `frontend/src/components/MicrowaveControl.vue`
- `frontend/src/views/ControlPanel.vue`
- `frontend/src/views/Dashboard.vue`
- 必要的前端类型或小型 helper

## 不做

- 不改后端驱动。
- 不改 REST/WS 接口设计，除非发现接口无法使用并同步记录。
- 不改实验 YAML。
- 不改生成文件，除非构建确实更新且 diff 经确认需要提交。

## UI 范围

新增 `MicrowaveControl.vue`，与 `HeaterControl`、`PumpControl` 平级。

控件必须包含：

- 连接/断开。
- 当前连接状态。
- 模式选择：
  - 手动功率
  - 自动功率
  - 恒速率
- 参数编辑：
  - 段号 1-5
  - 温度输入，最大 300 C
  - 功率输入，仅手动功率模式显示，范围 0-100
  - 时/分/秒输入
- 配置按钮。
- 启动按钮。
- 停止按钮。
- 当前状态：
  - 物料温度
  - 当前功率
  - 电流
  - 运行时间
  - 当前段
  - 当前模式
  - 故障码/故障提示

## 启动确认

点击启动前必须弹出二次确认，确认文案至少包含：

- 炉门已关闭。
- 反应瓶非空载，光纤探头已没入物料。
- 温度和功率参数已核对。
- 设备运行期间有人看护。
- 确认后才调用 `/api/microwave/{device_id}/start`。

用户取消确认时不得调用 API。

## 前端状态与本地保存

- 在 `ControlPanel.vue` 中增加 `microwaves` state。
- 可参考已有泵参数保存方式，把微波参数保存到 localStorage。
- 不把微波仪伪装成 heater；它应有独立类型和独立组件。

## WebSocket 类型

`useWebSocket.ts` 增加：

- `MicrowaveRealtimeData`
- `RealtimeData.microwaves`

兼容后端暂时没有 `microwaves` key 的情况，避免页面报错。

## Dashboard 展示

新增微波设备卡：

- 标题：微波仪 `<id>`
- 状态 tag：运行中、停止、异常
- 温度、功率、电流、运行时间、当前段、当前模式
- 故障码非 0 时显示 warning/danger

曲线：

- 复用现有 ECharts 风格。
- 新增微波温度曲线或扩展温度曲线 legend。
- 若新增功率曲线，保持布局稳定，不大改页面结构。

## 验收

建议运行：

```powershell
cd frontend
npm run build -- --mode production
```

然后检查生成声明文件：

```powershell
git status --short -- frontend/auto-imports.d.ts frontend/components.d.ts
git diff -- frontend/auto-imports.d.ts frontend/components.d.ts
```

若生成文件只是构建噪声，不要盲目提交；按当前项目规则判断。

## 完成记录

- 状态：2026-06-17 已完成本任务范围内的微波仪前端手动控制和仪表盘展示。未改后端、未改 YAML parser/executor，未连接真实硬件。
- 已完成：
  - 新增 `frontend/src/components/MicrowaveControl.vue`，作为独立微波仪控制卡片接入连接/断开、刷新状态、模式选择、段号 1-5、温度、手动功率、时/分/秒、配置、启动、停止和实时状态展示。
  - `MicrowaveControl.vue` 明确展示 `enable_control_writes` 与 `allow_experiment_control` 安全状态；配置和真实启动在控制写入禁用时不可点击，页面加载和 WebSocket 连接不会自动控制设备。
  - 启动按钮增加二次确认，确认文案包含炉门已关闭、反应瓶非空载且光纤探头已没入物料、温度和功率已核对、运行期间有人看护；用户取消时不调用 `/api/microwave/{device_id}/start`。
  - `frontend/src/api/devices.ts` 增加微波仪 REST API 方法、模式枚举和配置 payload 类型，调用后端既有 `/api/microwave/...` 接口。
  - `frontend/src/composables/useWebSocket.ts` 增加 `MicrowaveRealtimeData` 和 `RealtimeData.microwaves`，并兼容后端暂时没有 `microwaves` key 的旧 payload。
  - `frontend/src/views/ControlPanel.vue` 增加 `microwaves` state、微波参数 localStorage 保存/恢复、REST 状态刷新缓存和微波控制事件处理。
  - `frontend/src/views/Dashboard.vue` 增加微波设备卡片，展示运行/停止/异常、物料温度、功率、电流、运行时间、当前段、当前模式和故障码；温度曲线增加微波温度 series。
  - `frontend/components.d.ts` 由构建生成并新增 `MicrowaveControl` 声明；`frontend/auto-imports.d.ts` 无变化。
- 验证：
  - `cd frontend; npm run build -- --mode production`：通过，`vue-tsc -b` 与 `vite build --mode production` 均完成。
  - `git diff -- frontend/auto-imports.d.ts frontend/components.d.ts`：确认仅 `components.d.ts` 增加 `MicrowaveControl` 组件声明，属于本次新增组件的有意义生成声明更新。
- 遗留问题：
  - 未做真实硬件 smoke test；微波仪真实写入仍受后端 `enable_control_writes=false` 默认安全门禁限制，实验室确认前前端不会绕过该限制。
  - 后端当前仍保留 `mode="unknown"`、原始 `current_mode_code` 和原始 `fault_code`，前端只展示原始状态，不解释协议未确认的模式枚举或故障 bit。
  - `running` 仍沿用后端“实时功率非零”的保守判断，不能替代真实设备运行状态寄存器或实机确认。
  - 停止/急停写入语义仍需后续真实设备 smoke test 复核；本任务只做前端调用与失败提示，不改变后端 stop 行为。
- 交接给 05：
  - 下一任务可以执行 `05_experiment_yaml_automation.md`，但必须继续保持 YAML 自动化默认禁用真实微波启动，只有显式配置和实验室 smoke-test 门槛通过后才能允许。
  - 05 可复用本任务中的 `MicrowaveMode` 文案和 `/api/microwave/...` 前端调用经验，但不要让 YAML 动作继承前端手动启动确认作为安全替代；自动化应有独立的后端安全门禁。
  - 前端已能展示 `allow_experiment_control=false` 和 `enable_control_writes=false`，05 若改变这些语义，需同步用户/开发/YAML 文档并重新验证前端展示。
