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

- 状态：未开始。
- 验证：未运行。
- 交接：下一任务可以执行 `05_experiment_yaml_automation.md`，但前端不依赖 YAML 自动化。
