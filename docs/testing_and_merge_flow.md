# Heat 测试与合并流程

适用人群：人类开发者、负责合并的人、需要判断“现在能不能 merge”的协作者。

---

## 你现在应该看什么

- 想知道最少要跑什么：看“最小验证清单”
- 想知道哪些改动需要实机：看“软件验证与实机验证边界”
- 想知道文档何时必须同步：看“文档同步要求”
- 想知道如何 commit / push 双远程：看“提交与推送流程”

---

## 1. 最小验证清单

任何准备合并的改动，至少完成以下软件层检查：

```powershell
python tests\test_metadata.py
python -c "import src.web.app; import src.web.api.experiments; import src.web.api.ws"
npm --prefix frontend run build
```

检查目标：

- 核心实验逻辑不回归
- Web 关键模块可导入
- 前端能构建出生产产物

---

## 2. 软件验证与实机验证边界

### 2.1 纯软件验证通常足够的改动

- 文档改动
- YAML 解析与 metadata 逻辑
- 样品记录逻辑
- 引擎状态机的纯逻辑改动
- 前端展示层改动

### 2.2 建议补实机 smoke test 的改动

- 串口访问时序变化
- 协议写入顺序变化
- 泵模式参数写入变化
- 设备 start / stop / emergency_stop 语义变化
- 真实等待条件依赖设备读数的改动

最低实机 smoke test 建议：

- 加热器连接、设温、停止
- 泵连接、单通道启动、停止
- 一个最小 YAML 实验启动与停止

`tests/test_hardware.py` 是实验室手工脚本，不参与 pytest 收集。它会写入温度设定值并执行真实启动/停止，只有现场条件已确认时才可显式运行：

```powershell
python tests\test_hardware.py --port COMx --confirm-hardware-write
```

未提供 `--confirm-hardware-write` 时脚本会拒绝执行；任一检查失败时退出码为 1。

---

## 3. 文档同步要求

以下改动必须同步文档：

- 页面路径变化
- API 路径变化
- 实验动作 / wait 类型变化
- stop / pause / resume / timeout 行为变化
- metadata / `sample_id` / `samples.csv` 逻辑变化
- merge / push / 构建 / 产物处理流程变化

文档更新目标：

- 项目入口：`README.md`
- AI 规则：`context/PROJECT_CONTEXT.md`
- 用户行为：`docs/user_guide.md`
- 开发维护：`docs/developer_guide.md`
- YAML 规范：`docs/experiment_yaml_spec.md`
- 故障排查：`docs/troubleshooting.md`

---

## 4. 产物与工作区规则

### 4.1 运行产物

当前约定：

- `output/` 是运行和测试产物
- 不应纳入版本控制

### 4.2 前端构建产物

- `src/web/static/` 是被 Git 忽略的前端构建目录
- 构建时会被覆盖，不进入提交

### 4.3 提交前检查

至少执行一次：

```bash
git status --short
```

确认：

- 没有临时脚本误入提交
- 没有测试日志误入提交
- 没有无关文档或产物混入

---

## 5. 推荐 commit message 风格

推荐简洁、行为导向的前缀：

- `fix:` 修复问题
- `docs:` 文档更新
- `feat:` 新能力
- `refactor:` 重构
- `test:` 测试更新

示例：

```text
fix: harden experiment stop flow and sync docs
docs: reorganize documentation by audience
feat: add pump wait timeout handling
```

---

## 6. 提交与推送流程

### 6.1 本地提交

```bash
git add <files>
git commit -m "fix: your message"
```

### 6.2 推送当前分支

当前仓库常用双远程：

- `origin`：Gitee
- `github`：GitHub

推送示例：

```bash
git push origin <branch>
git push github <branch>
```

---

## 7. 合并前最终检查

合并前最后确认：

- 测试通过
- 前端构建通过
- 文档已同步
- `git status --short` 干净或只包含本次改动
- 未跟踪文件不是临时脚本或运行产物
- 如果触及设备时序，已完成至少一轮实机 smoke test

---

## 8. 什么时候不该 merge

以下情况不建议直接合并：

- 设备返回值失败仍被当作成功
- stop / timeout 语义不明确
- 文档与真实行为冲突
- 工作区混入无关产物
- 仅做了“页面层面验证”，但改动实际触及硬件控制语义

---

## 9. 分支管理规则

当前仓库正式采用任务分支制：

- `master` 是唯一长期保留的稳定主线
- 日常开发不直接在 `master` 上进行
- 每个独立项目或功能从最新 `master` 切出新分支
- 一个分支只承载一个明确主题
- 合并进 `master` 后，任务分支默认删除本地和远程引用

推荐命名：

- `feature/<topic>`
- `fix/<topic>`
- `docs/<topic>`

示例：

- `feature/automation-valve-microwave`
- `fix/experiment-stop-flow`
- `docs/branch-policy`

只有在以下情况，才允许保留阶段性集成分支：

- 大项目拆成多个子功能并行推进
- 短期内不适合频繁直接合入 `master`
- 分支创建时已经写明用途、生命周期和删除条件

### 9.1 标准生命周期

```bash
git checkout master
git pull <remote> master
git checkout -b feature/<topic>
git push origin feature/<topic>
git push github feature/<topic>
```

合并回 `master` 后默认执行：

```bash
git branch -d feature/<topic>
git push origin --delete feature/<topic>
git push github --delete feature/<topic>
```

### 9.2 当前仓库的收尾判定

如果一个阶段分支满足以下条件，通常应删除：

- `master` 已包含该分支关键提交
- 工作区干净
- 两个远程的 `master` 已同步
- 该分支不再承担长期集成职责

## 10. Codex `/git` 判断式流程

Codex 收到 `/git` 时，按以下含义执行：

```text
按需验证 -> 按需更新文档 -> 提交 -> 等待用户确认后推送
```

### 10.1 按变更类型选择验证

完整 pytest 收集需要先安装测试依赖：

```powershell
python -m pip install -e ".[test]"
python -m pytest -q
```

直接运行 `tests\test_campaigns.py` 不会执行 pytest fixture 测试，不能把其退出码 0 当作测试通过。

不是所有提交都需要完整编译验证：

| 变更类型 | 默认验证 |
| --- | --- |
| 仅文档、规则、Skill | `git diff --check -- <paths>` + 内容一致性检查 |
| Python 后端 | `python tests\test_metadata.py` + `python tests\test_code_review_fixes.py` + 相关 import 检查 |
| Campaign / planner | 后端检查 + `import src.web.api.campaigns; import src.campaigns.store; import src.ml.planner` |
| 前端源码 | `cd frontend; npm run build -- --mode production` |
| YAML parser / ExperimentEngine | metadata 测试 + 定向行为或 import 检查 |
| 硬件控制语义 | 软件检查 + 用户/实验室实机 smoke test 确认 |

### 10.2 文档同步对应关系

| 变更场景 | 应同步文档 |
| --- | --- |
| 新页面、新按钮、新用户操作流程 | `docs/user_guide.md` |
| API、请求/响应字段、后端架构或开发流程 | `docs/developer_guide.md` |
| YAML action、wait type、metadata 字段或实验文件格式 | `docs/experiment_yaml_spec.md` |
| `sample_id`、`samples.csv`、campaign、trial、recommendation、characterization | `docs/campaign_workflow.md`；用户可见时也更新 `docs/user_guide.md` |
| 验证、分支、提交、合并、推送或 `/git` 流程 | `docs/testing_and_merge_flow.md` |
| 项目定位、主要能力、启动方式 | `README.md` |
| AI 长期需要知道的项目事实、硬件边界、agent 规则 | `context/PROJECT_CONTEXT.md` 和/或 `AGENTS.md` |

### 10.3 PowerShell 性能约定

当前 Windows 工作区中，宽泛 PowerShell 输出可能明显变慢。默认优先使用：

- `rg` / `rg --files`
- `git status --short -- <paths>`
- `git diff -- <paths>`
- Node `spawnSync` 或定向文件读取处理大输出

避免把递归目录扫描、大 diff、无路径限定的 `git status`、大 `Format-Table` 输出作为默认路径。

### 10.4 推送与清理

- `/git` 不自动推送；必须等待用户明确确认。
- `frontend/auto-imports.d.ts` 和 `frontend/components.d.ts` 是生成声明文件，提交前先看内容 diff 和 EOL 状态。
- Git 提示 unreachable loose objects 通常是对象积累，不是代码错误；不放入 `/git` 默认流程。需要维护时单独执行 `git count-objects -v` 和 `git gc`，更激进的 `git gc --prune=now` 需用户确认。
