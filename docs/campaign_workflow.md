# Heat 智能实验 Campaign 工作流

适用对象：需要使用或继续开发 human-in-the-loop batch optimization 的实验人员和开发者。

本功能的目标是让 Heat 先具备“批次式闭环优化”的数据与界面骨架，而不是直接接入机器学习算法。当前版本使用 `ManualPlanner`：人工输入下一批实验参数，系统记录为 recommendation 和 trial，实验人员离线表征后再把结果录入系统。

---

## 1. 核心边界

当前实现不改变现有设备控制链路：

- 不修改 `ExperimentEngine`
- 不修改 `StepExecutor`
- 不让 planner 直接控制硬件
- 不自动生成或启动 YAML 实验
- 不自动解析光谱或仪器文件

新增能力位于外围层：

- `src/campaigns/`：Campaign、Trial、Recommendation、CharacterizationResult 的文件存储
- `src/ml/planner.py`：planner 抽象和 `ManualPlanner`
- `src/web/api/campaigns.py`：Campaign REST API
- `/campaigns`：前端“智能实验”页面

---

## 2. 数据文件

Campaign 数据默认写入：

```text
data/campaigns/campaigns.json
data/campaigns/trials.json
data/campaigns/recommendations.json
data/campaigns/characterizations.json
```

这些文件会在首次访问 Campaign API 时自动创建。已有的 `data/datasets/samples.csv` 不迁移、不替代，仍用于现有实验样品记录链路。

---

## 3. 推荐使用流程

1. 打开 `/campaigns`
2. 创建 Campaign
   - 设置材料体系，例如 `CsPbBr3`
   - 设置主目标指标，例如 `pl_intensity`
   - 设置参数名，例如 `temperature_c, flow_a, flow_b`
3. 在 `ManualPlanner` 中输入一批参数 JSON
4. 点击生成 Trial
5. 根据 Trial 参数在现有 `/experiment` 页面选择或准备 YAML，并手动执行实验
6. 回到 `/campaigns`，为 Trial 填写 `run_id` 和 `sample_id`
7. 离线完成 PL、UV-Vis、XRD 等表征
8. 在 `/campaigns` 录入表征类型、主目标值、额外指标和原始文件路径
9. 将可靠结果标记为 `accepted_for_planner`，供后续 ML planner 使用

参数批次示例：

```json
[
  { "temperature_c": 120, "flow_a": 0.4, "flow_b": 0.2 },
  { "temperature_c": 140, "flow_a": 0.5, "flow_b": 0.2 }
]
```

额外指标示例：

```json
{
  "peak_nm": 516.4,
  "fwhm_nm": 21.5
}
```

---

## 4. Trial 状态

Trial 支持以下状态：

| 状态 | 含义 |
|---|---|
| `planned` | 已由 planner 生成，还未准备执行 |
| `ready_to_run` | 参数已确认，准备执行 |
| `running` | 对应实验正在执行 |
| `synthesized` | 样品已合成 |
| `waiting_characterization` | 等待离线表征 |
| `characterized` | 已录入表征结果 |
| `accepted_for_planner` | 结果可用于后续 planner |
| `excluded` | 结果不参与后续 planner |
| `failed` | 合成、表征或记录失败 |

---

## 5. API 概览

当前提供以下接口：

```text
GET  /api/campaigns
POST /api/campaigns
GET  /api/campaigns/{campaign_id}
POST /api/campaigns/{campaign_id}/recommendations/manual
GET  /api/campaigns/{campaign_id}/trials
PATCH /api/campaigns/{campaign_id}/trials/{trial_id}
POST /api/campaigns/{campaign_id}/characterizations
GET  /api/campaigns/{campaign_id}/history
GET  /api/campaigns/{campaign_id}/characterizations
```

`/history` 返回的是后续 ML planner 最需要的数据形状：

```json
{
  "trial_id": "trial_xxx",
  "sample_id": "CSPB_S001",
  "parameters": { "temperature_c": 120 },
  "metrics": { "pl_intensity": 8200 },
  "characterization_type": "PL",
  "accepted_for_planner": true,
  "trial_status": "accepted_for_planner"
}
```

---

## 6. 后续接入 ML Planner

后续接入 ATLAS、Bayesian optimization 或其他 ML planner 时，不应修改设备层。推荐做法：

1. 新增一个 planner 类，例如 `AtlasPlanner`
2. 实现与 `ManualPlanner` 相同的 `recommend(...)` 接口
3. 从 Campaign history 中读取 `parameters` 和 `metrics`
4. 输出下一批参数对象
5. 继续复用 Trial、CharacterizationResult 和 `/campaigns` 页面

planner 可以建议实验参数，但最终执行仍由 Heat 的实验页面、YAML 和人工确认完成。

---

## 7. 验证命令

修改 Campaign 相关功能后，至少执行：

```powershell
python tests\test_metadata.py
python -c "import src.web.app; import src.web.api.experiments; import src.web.api.ws; import src.web.api.campaigns"
cd frontend
npm run build -- --mode production
```

如果安装了 `pytest`，再执行：

```powershell
python -m pytest tests\test_campaigns.py -q
```
