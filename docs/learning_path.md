# Heat 项目技术栈学习路径

> 基于 Heat 项目实际使用的技术，从前端到后端到硬件通信的完整学习路线。

---

## 学习路线总览

```
前端基础 → 前端框架 → 通信协议 → 后端框架 → 硬件通信 → 工程化
   ①          ②          ③          ④          ⑤         ⑥
```

每个阶段标注学习时长参考（零基础估算），有编程基础可大幅缩短。

---

## 第一阶段：前端基础

### 1.1 HTML + CSS

| 内容 | 说明 | 项目对应 |
|------|------|----------|
| HTML 标签 | div/span/input/select/button | ControlPanel.vue 模板结构 |
| CSS 布局 | flex/grid、margin/padding | 仪表盘布局、控制面板排列 |
| CSS 选择器 | class/id/伪类 | Element Plus 样式覆盖 |

**学习资源**：
- MDN Web Docs（https://developer.mozilla.org/zh-CN/）
- 菜鸟教程 HTML/CSS 部分

**练习**：写一个静态的泵控制面板页面（纯 HTML+CSS，不含交互）

### 1.2 JavaScript

| 内容 | 说明 | 项目对应 |
|------|------|----------|
| 变量与类型 | let/const、string/number/boolean/array/object | 全部前端代码 |
| 函数 | 箭头函数、默认参数、解构赋值 | `calcFlowRate(ch)` 等 |
| 异步 | Promise、async/await、fetch | API 调用 `await devicesApi.startPump()` |
| DOM 操作 | 事件监听、元素操作 | Vue 底层原理 |
| 模块化 | import/export | 所有 .ts/.vue 文件 |

**学习资源**：
- MDN JavaScript 教程
- 《JavaScript 高级程序设计》（红宝书）第1-10章

**练习**：用原生 JS 写一个按钮，点击后 fetch 一个 API 并显示结果

### 1.3 TypeScript

| 内容 | 说明 | 项目对应 |
|------|------|----------|
| 类型注解 | `: string`、`: number`、`: boolean` | 所有函数参数和返回值 |
| 接口 interface | 定义对象结构 | `ChannelConfig`、`PumpStatus` |
| 类型别名 type | 联合类型、字面量类型 | `PumpMode = 'FLOW_MODE' \| 'TIME_QUANTITY' \| ...` |
| 泛型 | `<T>` | API 响应类型 |
| 枚举 enum | 有限集合 | 项目中用字面量联合类型替代 |

**学习资源**：
- TypeScript 官方 Handbook（https://www.typescriptlang.org/docs/handbook/）
- 《TypeScript 编程》

**练习**：给 1.2 的 JS 代码加上 TypeScript 类型

---

## 第二阶段：前端框架

### 2.1 Vue 3

| 内容 | 说明 | 项目对应 |
|------|------|----------|
| 组合式 API | `setup()`、`ref()`、`reactive()` | 所有 .vue 文件 |
| 模板语法 | `v-model`、`v-if`、`v-for`、`@click` | ControlPanel.vue |
| 计算属性 | `computed()` | 流速自动计算 |
| 生命周期 | `onMounted()`、`onUnmounted()` | WebSocket 连接/断开 |
| 组件通信 | props/emit、provide/inject | 父子组件数据传递 |
| 路由 | Vue Router | 页面切换（仪表盘/控制/实验） |

**项目中的关键模式**：

```typescript
// 响应式状态
const devices = reactive({ pumps: {}, heaters: {} })

// 条件渲染
<template v-if="pump.channels[ch].mode === 'TIME_QUANTITY'">
  <!-- 定时定量模式：流速只读 -->
</template>

// 双向绑定
<el-input-number v-model="pump.channels[ch].flowRate" />
```

**学习资源**：
- Vue 3 官方文档（https://cn.vuejs.org/）— 重点看「组合式 API」章节
- 《Vue.js 设计与实现》

**练习**：用 Vue 3 写一个 TODO 应用（增删改查）

### 2.2 Element Plus

| 内容 | 项目对应组件 |
|------|-------------|
| ElButton | 启动/停止/连接按钮 |
| ElInputNumber | 流速/时间/液量输入 |
| ElSelect + ElOption | 模式/软管/单位选择 |
| ElTag | 运行状态标签 |
| ElRadioButton | 方向选择（顺时针/逆时针） |
| ElMessage | 操作成功/失败提示 |

**学习资源**：Element Plus 官方文档（https://element-plus.org/zh-CN/）

**练习**：给 TODO 应用加上 Element Plus 组件

### 2.3 ECharts

| 内容 | 项目对应 |
|------|----------|
| 折线图 | 温度曲线、流量曲线 |
| 实时数据更新 | `setOption()` 追加数据 |
| 多系列 | 多加热器/多通道颜色区分 |
| 自动滚动 | 时间轴滚动显示 |

**学习资源**：ECharts 官方示例（https://echarts.apache.org/examples/zh/）

### 2.4 Vite

| 命令 | 用途 |
|------|------|
| `npm run dev` | 开发模式，热重载 |
| `npm run build` | 生产构建 → `src/web/static/` |

了解即可，不需要深入学习。

---

## 第三阶段：通信协议

### 3.1 HTTP / REST API

| 方法 | 用途 | 项目示例 |
|------|------|----------|
| GET | 获取数据 | `GET /api/devices/status` |
| POST | 执行操作 | `POST /api/pump/pump1/start` |
| DELETE | 删除资源 | `DELETE /api/experiments/history/runs/{id}` |

**关键概念**：
- 请求体（Request Body）：JSON 格式传参
- 响应体（Response Body）：JSON 格式返回
- 状态码：200 成功、404 不存在、500 服务器错误
- Content-Type：`application/json`

### 3.2 WebSocket

| 概念 | 说明 | 项目对应 |
|------|------|----------|
| 连接 | `new WebSocket(url)` | useWebSocket.ts |
| 接收消息 | `ws.onmessage` | 实时数据推送 |
| 断线重连 | 定时检测 + 重新连接 | useWebSocket.ts |
| 心跳 | 定时发送 ping | 保持连接活跃 |

**项目中的数据流**：

```
服务端每秒推送 → WebSocket → 前端 onmessage → 更新 reactive 状态 → 页面自动刷新
```

### 3.3 JSON

所有前后端数据交换的格式，必须熟练掌握：
- 对象：`{"key": "value"}`
- 数组：`[1, 2, 3]`
- 嵌套：`{"pump1": {"channels": {"1": {"flow_rate": 5.0}}}}`

### 3.4 CORS

前后端分离时的跨域问题：
- 前端跑在 `localhost:5173`（开发模式）
- 后端跑在 `localhost:8000`
- 浏览器阻止跨域请求 → 后端配置 CORS 允许

---

## 第四阶段：后端框架

### 4.1 Python 3.10+

| 内容 | 说明 | 项目对应 |
|------|------|----------|
| 类型注解 | `def func(x: int) -> bool:` | 全部代码 |
| dataclass | `@dataclass` 数据类 | 配置类、状态类 |
| 枚举 | `Enum`/`IntEnum` | PumpRunMode、FlowUnit |
| 上下文管理器 | `with` 语句 | 锁管理、串口操作 |
| f-string | `f"CH{channel}"` | 日志和错误消息 |
| 结构体 | `struct.pack`/`unpack` | 浮点数↔寄存器转换 |

### 4.2 FastAPI

| 内容 | 说明 | 项目对应 |
|------|------|----------|
| 路由 | `@router.get()`/`@router.post()` | api/devices.py |
| 请求模型 | Pydantic BaseModel | 请求体验证 |
| 依赖注入 | `Depends()` | 获取 DeviceManager 实例 |
| 异步处理 | `async def` + `await` | 所有 API 端点 |
| 静态文件 | `StaticFiles` | 托管前端构建产物 |
| SPA 路由 | 捕获所有非 API 路径返回 index.html | app.py |

**项目中的关键模式**：

```python
# 同步设备操作桥接到异步框架
@router.post("/pump/{device_id}/start")
async def start_pump(device_id: str, request: StartPumpRequest):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, manager.start_pump_channel, device_id, ...
    )
    return {"success": result}
```

**学习资源**：
- FastAPI 官方教程（https://fastapi.tiangolo.com/zh/）
- 重点看：路径操作、请求体、依赖注入、异步

### 4.3 asyncio

| 内容 | 说明 | 项目对应 |
|------|------|----------|
| event loop | 事件循环 | FastAPI 底层 |
| run_in_executor | 同步→异步桥接 | 所有设备操作 |
| asyncio.sleep | 非阻塞等待 | 等待条件轮询 |
| async/await | 协程语法 | 全部 API 端点 |

**核心理解**：设备操作是同步阻塞的（串口通信），FastAPI 是异步的，`run_in_executor` 是两者之间的桥梁。

### 4.4 Pydantic

FastAPI 内置的数据验证库：
- 定义请求/响应的数据结构
- 自动类型转换和验证
- 生成 OpenAPI 文档

```python
class StartPumpRequest(BaseModel):
    channel: int
    flow_rate: float
    mode: str = "FLOW_MODE"
```

---

## 第五阶段：硬件通信

### 5.1 串口通信（pyserial）

| 内容 | 说明 | 项目对应 |
|------|------|----------|
| 打开串口 | `serial.Serial(port, baudrate, ...)` | modbus_rtu.py |
| 读写数据 | `ser.write()`/`ser.read()` | 协议层全部 |
| 超时设置 | `timeout=1.0` | 防止永久阻塞 |
| 校验位 | parity='E'（偶校验） | 蠕动泵必须 E |
| 端口管理 | 锁文件、强制释放 | serial_manager.py |

**学习资源**：
- pyserial 官方文档（https://pyserial.readthedocs.io/）
- Windows 设备管理器查看 COM 口

### 5.2 MODBUS RTU 协议

| 内容 | 说明 | 项目对应 |
|------|------|----------|
| 帧结构 | 从站地址 + 功能码 + 数据 + CRC | modbus_rtu.py |
| 功能码 03 | 读保持寄存器 | 读取泵状态 |
| 功能码 06 | 写单个寄存器 | 写单位/控制字 |
| 功能码 16(0x10) | 写多个寄存器 | 写浮点数（2个寄存器） |
| CRC-16 | 循环冗余校验 | modbus_rtu.py `_crc16()` |
| 大端序 | 高字节在前 | 浮点数 ABCD 字序 |

**项目中的关键经验**：

```
浮点数写入：struct.pack('>f', value) → 拆为2个16位寄存器 → 0x10写入
单位写入：0x06 写单个寄存器
顺序：先写单位，再写浮点数（泵需要先知道单位才能验证值范围）
```

**学习资源**：
- 《MODBUS 协议中文版》（网上可搜到）
- 本项目 `多通道蠕动泵MODBUS通信协议.md`

### 5.3 struct 模块

Python 二进制数据处理，MODBUS 通信核心：

```python
import struct

# 浮点数 → 2个寄存器（大端序）
value = 5.0
fb = struct.pack('>f', value)        # b'\x40\xa0\x00\x00'
reg_high = (fb[0] << 8) | fb[1]     # 16544 (0x40A0)
reg_low = (fb[2] << 8) | fb[3]      # 0     (0x0000)

# 2个寄存器 → 浮点数
b = struct.pack('>HH', 16544, 0)
value = struct.unpack('>f', b)[0]   # 5.0
```

| 格式 | 说明 |
|------|------|
| `'>f'` | 大端序 32位浮点 |
| `'>H'` | 大端序 16位无符号整数 |
| `'>HH'` | 2个大端序 16位整数 |

### 5.4 线程安全

| 内容 | 说明 | 项目对应 |
|------|------|----------|
| RLock | 可重入锁，保护串口访问 | BaseDevice._lock |
| 泵级锁 | 序列化多通道操作 | device_manager.py |
| 非阻塞获取 | `lock.acquire(blocking=False)` | atexit 安全清理 |
| 停止标志 | `threading.Event` | 看门狗线程 |

**核心原则**：串口是半双工，同一时间只能有一个指令，必须用锁保护。

---

## 第六阶段：工程化

### 6.1 Git

| 命令 | 用途 |
|------|------|
| `git add -A` | 暂存所有修改 |
| `git commit -m "msg"` | 提交 |
| `git push origin develop-web` | 推送到 Gitee |
| `git push github develop-web` | 推送到 GitHub |
| `git log --oneline -10` | 查看最近提交 |

### 6.2 Conda

```bash
conda env create -f environment.yml   # 创建环境
conda activate heat                    # 激活环境
conda env remove -n heat              # 删除环境
```

### 6.3 npm

```bash
cd frontend
npm install          # 安装依赖
npm run dev          # 开发模式（热重载）
npm run build        # 生产构建
```

### 6.4 日志与调试

| 技术 | 用途 |
|------|------|
| Python logging | 设备操作日志 |
| 浏览器 F12 | 前端调试（Console/Network/WebSocket） |
| `python -m py_compile` | Python 编译检查 |

---

## 项目代码阅读顺序

按依赖关系从底层到上层：

```
1. src/protocols/pump_params.py     → 理解泵参数定义
2. src/protocols/modbus_rtu.py      → 理解 MODBUS 通信
3. src/devices/base_device.py       → 理解设备基类
4. src/devices/peristaltic_pump.py  → 理解泵驱动
5. src/web/device_manager.py        → 理解设备管理
6. src/web/api/devices.py           → 理解 REST API
7. src/web/api/ws.py                → 理解 WebSocket
8. src/experiment/executor.py       → 理解实验执行
9. frontend/src/api/devices.ts      → 理解前端 API 封装
10. frontend/src/views/ControlPanel.vue → 理解控制面板
```

---

## 推荐学习资源汇总

| 技术 | 资源 | 类型 |
|------|------|------|
| HTML/CSS/JS | MDN Web Docs | 文档 |
| TypeScript | TypeScript Handbook | 文档 |
| Vue 3 | vuejs.org 官方文档 | 文档 |
| Element Plus | element-plus.org | 文档 |
| ECharts | echarts.apache.org/examples | 示例 |
| Python | 《Python Crash Course》 | 书籍 |
| FastAPI | fastapi.tiangolo.com | 文档 |
| pyserial | pyserial.readthedocs.io | 文档 |
| MODBUS | 《MODBUS 协议中文版》 | 文档 |
| Git | progit.bootcss.com | 书籍 |
