# Heat 开发者指南

面向人类开发者与维护者。  
如果你是 AI / 自动化协作者，请先读 [../context/PROJECT_CONTEXT.md](../context/PROJECT_CONTEXT.md)。

---

## 你现在应该看什么

- 想理解系统结构：看“架构总览”
- 想扩展实验能力：看“新增实验动作 / 等待条件标准流程”
- 想接入新设备：看“新增设备驱动标准流程”
- 想确认 merge 前要做什么：看 [testing_and_merge_flow.md](testing_and_merge_flow.md)
- 想排查线上/联调问题：看 [troubleshooting.md](troubleshooting.md)

---

## 1. 架构总览

当前主路径是 Web 架构：

```text
Vue 前端
  -> FastAPI Web 层
  -> Experiment 引擎
  -> Devices 同步驱动
  -> Protocols
  -> 串口资源管理
```

主线模块：

- `src/web/`：REST API、WebSocket、应用生命周期
- `src/experiment/`：YAML 解析、状态机、步骤执行、实验日志
- `src/devices/`：加热器和泵的同步设备驱动
- `src/protocols/`：AIBUS、MODBUS RTU、参数定义
- `src/utils/`：配置、日志、串口资源管理
- `src/science/`：`sample_id` 和 `samples.csv` 记录链路

前端主要页面：

- `/`
- `/control`
- `/experiment`
- `/history`

---

## 2. 核心开发约束

### 2.1 设备驱动必须保持同步

不要在 `src/devices/` 内做这些事情：

- 后台线程轮询
- 内部异步任务调度
- 命令队列线程
- 页面生命周期联动控制

原因：

- 串口是半双工，请求-响应强依赖顺序
- 驱动层并发会破坏稳定性

### 2.2 Web 层必须用桥接思维

FastAPI 是异步的，但设备是同步的。  
开发原则：

- 设备调用通过 `run_in_executor`
- 不在 Web 层伪造成功状态
- 不让 WebSocket 断开影响设备运行

### 2.3 语义一致性优先

以下三者必须一致：

- 引擎状态
- 日志状态
- 真实设备副作用

尤其注意：

- 设备方法返回 `False` 不能被忽略
- wait 超时不能静默继续
- stop 要尽快生效，但状态必须落到正确终态

---

## 3. 代码结构与职责

### 3.1 Web 层

- `src/web/app.py`：创建 FastAPI 应用、加载配置、挂载静态资源、启动推送循环
- `src/web/api/devices.py`：设备连接、控制、状态接口
- `src/web/api/experiments.py`：实验启动、暂停、恢复、停止、进度、历史
- `src/web/api/ws.py`：WebSocket 推送与连接管理

### 3.2 实验引擎

- `src/experiment/parser.py`：解析 YAML、校验实验文件名
- `src/experiment/actions.py`：动作和等待类型定义
- `src/experiment/executor.py`：逐步执行动作，处理等待、失败和返回值
- `src/experiment/engine.py`：状态机与 run 生命周期
- `src/experiment/experiment_logger.py`：run / step 日志与持久化

### 3.3 设备与协议

- `src/devices/heater.py`：加热器同步控制
- `src/devices/peristaltic_pump.py`：多通道泵同步控制
- `src/protocols/aibus.py`：加热器协议实现
- `src/protocols/modbus_rtu.py`：泵协议实现

### 3.4 样品与记录

- `src/science/sample_id.py`：`sample_id`、`batch_id`、`condition_id`
- `src/science/sample_record.py`：`samples.csv` 写入与去重

---

## 4. 新增设备驱动标准流程

### 4.1 目标

把“新设备”纳入现有体系，而不是单独起一套旁路实现。

### 4.2 标准步骤

1. 明确协议层边界
   - 协议编解码写在 `src/protocols/`
   - 协议层不要承载设备状态
2. 在 `src/devices/` 实现同步驱动
   - 保持同步阻塞
   - 使用现有锁与资源管理模式
3. 在配置层接入
   - 补 `config/system_config.yaml` 对应结构
   - 补 `utils/config.py` 的解析逻辑（若需要）
4. 在 `DeviceManager` 中注册并暴露控制入口
5. 如需 Web 控制，再补 `api/devices.py`
6. 如需实验引擎接入，再扩动作和执行器
7. 补软件测试与最小联调说明
8. 同步文档

### 4.3 禁止事项

- 直接在 Web 层拼协议帧
- 为新设备绕过 `DeviceManager`
- 在驱动内偷偷起线程

---

## 5. 新增实验动作 / 等待条件标准流程

### 5.1 新增动作

1. 在 `actions.py` 增加 `ActionType`
2. 在 `parser.py` 的 `ACTION_MAP` 注册字符串映射
3. 在 `executor.py` 增加执行逻辑
4. 如需要，补前端展示和用户文档
5. 补测试
6. 同步 [experiment_yaml_spec.md](experiment_yaml_spec.md)

### 5.2 新增等待条件

1. 在 `actions.py` 增加 `WaitType`
2. 在 `parser.py` 的 `WAIT_MAP` 注册
3. 在 `executor.py` 的 `_wait_condition()` 增加处理
4. 明确 timeout 和 stop 的语义
5. 补测试
6. 同步 YAML 规范文档

### 5.3 特别注意

新增等待逻辑时必须回答清楚：

- stop 是否可中断
- timeout 后是失败还是继续
- 需要读取哪个设备状态
- 失败时如何写日志

---

## 6. 测试分层策略

### 6.1 纯软件验证

适合日常开发和合并前检查：

- `python tests\test_metadata.py`
- 模块导入检查
- 前端构建

### 6.2 需要实机验证的改动

以下改动不应只靠软件测试：

- 串口时序调整
- 协议写寄存器顺序变化
- 泵模式参数写入策略变化
- 真实设备 stop / start 时序变化

### 6.3 本项目测试重点

当前最重要的非硬件测试点：

- YAML 解析
- metadata / `sample_id`
- `samples.csv`
- 单实验保护
- stop / wait 语义
- WebSocket 断开不影响设备

---

## 7. 调试与排错

优先使用这几个入口做定位：

- `src/web/api/experiments.py`：实验生命周期问题
- `src/experiment/executor.py`：动作失败、等待失败、返回值失败
- `src/web/api/ws.py`：实时推送、连接副作用
- `src/science/sample_record.py`：样品记录异常

常见问题请直接看：

- [troubleshooting.md](troubleshooting.md)

---

## 8. 文档同步规则（开发者视角）

以下改动后必须同步文档：

- 页面路由变化
- API 路径变化
- 实验动作 / wait 类型变化
- 行为语义变化，例如 stop、timeout、日志保存、样品记录
- 测试与 merge 流程变化

文档职责分工：

- `README.md`：入口与导航
- `PROJECT_CONTEXT.md`：AI 规则、历史问题、系统不变量
- `user_guide.md`：使用方式和行为语义
- `developer_guide.md`：开发维护方式
- `experiment_yaml_spec.md`：实验格式规范
- `testing_and_merge_flow.md`：测试、commit、push、双远程流程

---

## 9. 合并前检查清单

合并前至少确认：

- 代码改动与文档改动一致
- `tests/test_metadata.py` 通过
- Web 关键模块可导入
- 前端 `npm run build` 通过
- 临时产物未误入版本控制

更详细的流程见：

- [testing_and_merge_flow.md](testing_and_merge_flow.md)

---

## 10. 发布 / 推送流程（双远程）

本仓库当前常用双远程：

- `origin`：Gitee
- `github`：GitHub

标准流程：

1. 本地验证
2. 文档同步
3. `git add`
4. `git commit`
5. 推送到当前工作分支
6. 同步推送到两个远程

命令和规则细节统一见：

- [testing_and_merge_flow.md](testing_and_merge_flow.md)

---

## 11. Review Checklist

- 是否破坏了同步驱动模型
- 是否忽略了设备返回值
- 是否让 stop / timeout 语义变模糊
- 是否让页面连接状态影响设备状态
- 是否同步了 YAML 文档 / 用户文档 / AI 文档
- 是否把运行产物错误纳入版本控制
