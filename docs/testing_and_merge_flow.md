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

```bash
python tests\test_metadata.py
python -c "import src.web.app; import src.web.api.experiments; import src.web.api.ws"
cd frontend && npm run build
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

- `src/web/static/` 是前端构建目录
- 构建时会被覆盖
- 提交前要确认是否真的需要提交该目录内容

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

如果当前分支是 `develop-web`：

```bash
git push origin develop-web
git push github develop-web
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

当前仓库中的 `develop-web` 就属于这种情况：它是已完成并已合入主线的阶段性开发分支，不应继续承载下一轮硬件集成开发。
