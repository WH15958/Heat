# Heat 故障排查

适用人群：实验使用者、开发者、联调人员。

---

## 你现在应该看什么

- 设备连不上：看“设备连接失败”
- 页面没数据：看“前端无实时数据”
- 实验跑不起来：看“实验无法启动”
- 实验卡住或 stop 慢：看“实验卡在等待”与“stop 不生效”
- 日志或历史记录不对：看“历史记录 / 日志缺失”

---

## 1. 串口占用 / 锁文件问题

### 现象

- 设备无法连接
- 串口打开失败
- 重启程序后仍提示资源占用

### 优先检查

- 是否还有其他串口工具正在占用设备
- 是否有旧进程未退出
- 是否需要使用仓库内的锁清理脚本

### 建议处理

1. 关闭其他串口软件
2. 确认旧的 Python 进程已退出
3. 必要时使用锁文件清理工具：

```bash
# 列出所有锁文件
python scripts/cleanup_locks.py --list

# 清理过期锁文件
python scripts/cleanup_locks.py

# 强制清理所有锁文件，仅限确认没有其他 Heat/串口进程时使用
python scripts/cleanup_locks.py --force
```

锁文件清理能力也集成在 `src/utils/serial_manager.py`：

- `list_all_serial_locks()`：列出当前锁文件
- `cleanup_all_stale_serial_locks()`：清理过期锁文件
- `cleanup_all_stale_serial_locks(include_current_process=True)`：强制清理所有锁文件

生产或真实联调环境中慎用 `--force`，它可能清理其他仍在运行进程持有的锁。

---

## 2. 设备连接失败

### 加热器 / 泵通用排查

检查：

- 设备是否通电
- 串口线是否正常
- `config/system_config.yaml` 里的端口是否正确
- 波特率、地址、奇偶校验是否匹配

### 软件侧定位

- Web 层：`src/web/api/devices.py`
- 设备注册：`src/web/app.py`
- 配置解析：`src/utils/config.py`

---

## 3. 前端无实时数据

### 现象

- 页面能打开，但图表不更新
- 设备已连接，仪表盘仍为空

### 优先检查

- 浏览器是否能访问 `http://localhost:8000`
- WebSocket 是否成功连接 `/ws`
- 设备是否真的处于已连接状态
- 页面是否是最新前端版本

### 建议处理

1. 刷新页面，必要时 `Ctrl+Shift+R`
2. 检查浏览器控制台是否有 WebSocket 错误
3. 检查后端日志中 `data_push_loop` 是否异常
4. 检查 `src/web/api/ws.py`

---

## 4. 实验无法启动

### 现象

- 点击启动无效
- API 返回 400 / 404 / 409

### 常见原因

- YAML 文件不存在
- 文件名非法
- YAML 缺少 `steps`
- 已有实验处于 `running` 或 `paused`

### 建议处理

1. 检查实验文件是否在 `experiments/`
2. 检查文件后缀是否为 `.yaml` / `.yml`
3. 检查 YAML 顶层是否包含 `steps`
4. 检查当前是否已有实验在运行

---

## 5. 实验卡在等待

### 现象

- 实验长时间停在某一步
- 页面一直显示同一个 step

### 可能原因

- 等温条件一直达不到
- 泵通道状态没有变为完成
- 设备读数异常

### 建议处理

1. 查看当前步骤的 `wait` 类型
2. 检查加热器当前温度与设定温度
3. 检查泵状态是否真的在运行
4. 查看实验日志是否有读数失败或 timeout 提示

---

## 6. stop 不生效或停止慢

### 当前预期

- stop 会尽快中断等待步骤
- 不需要等完整的等待时长结束

### 如果停止仍然慢

检查：

- 当前是否在等待步骤中
- 是否是旧版本前端或旧版本后端
- 是否存在未更新的部署产物

开发者定位入口：

- `src/experiment/engine.py`
- `src/experiment/executor.py`

---

## 7. 历史记录 / 日志缺失

### 现象

- 实验跑过，但历史页面没有记录
- 有 run，但看不到原始日志

### 常见原因

- 启动实验时关闭了“保存日志”
- 日志文件未写入成功
- 运行中断时只保留了样品记录，未保留原始日志

### 说明

- 历史记录依赖实验日志文件
- `samples.csv` 是样品追踪记录，不等同于历史日志

---

## 8. 前端更新后页面不生效

### 现象

- 代码改了，页面看起来还是旧版

### 建议处理

1. 在 `frontend/` 执行 `npm run build`
2. 确认构建产物已写入 `src/web/static/`
3. 重启后端服务
4. 浏览器执行强制刷新

---

## 9. 需要继续看哪里

- 使用方式： [user_guide.md](user_guide.md)
- YAML 规范： [experiment_yaml_spec.md](experiment_yaml_spec.md)
- 开发维护： [developer_guide.md](developer_guide.md)
- AI / 系统约束： [../context/PROJECT_CONTEXT.md](../context/PROJECT_CONTEXT.md)
