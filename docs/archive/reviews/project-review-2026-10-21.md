# Heat 全项目深度审查报告（2026-10-21）

> 阶段一：先报告，再修复。本报告是该日期工作区的审查证据，不是新的操作规范或设备验收结论。

## 1. 结论与基线

确认 **14 项代码／接口契约问题、8 项文档／协作规则问题、1 项 Git 忽略治理问题**。其中两项 P1 应先修：失效的设备确认仍可提交物理操作，以及实验选择失败后确认名称与实际启动文件不一致。其余发现、条件性部署风险、未确认线索和实机待验项目分别列在下文。

这些确认项都能追溯到 HEAD 已有代码或文本；本轮未复现出桌面未提交改动新增的缺陷。这个结论只适用于已检查的路径，不代表桌面版本已经通过全部安装或硬件验收。软件测试通过也没有覆盖本轮发现的全部故障交错。

| 项目 | 审查基线 |
| --- | --- |
| 工作区／分支 | `D:/AI/Heat`；已批准的 `codex/desktop-app`，没有新建分支或工作树 |
| HEAD | `46f01d8da46e62eb14bd3ebc5d38d53608375540` |
| 工作区范围 | 263 个跟踪文件，加非忽略未跟踪文件，共 286 个已有文件的 SHA-256 基线；另盘点 ignored 文件 |
| 既有未提交内容 | 桌面源码、打包与测试；业务路径／生命周期修改；README、context、用户／开发／Campaign／测试指南；`.gitignore`；既有 `frontend/components.d.ts` 脏状态 |
| 软件环境 | Windows；Conda `heat` 的 Python 3.10.21；Node 24.21.0；使用现有依赖，未安装新工具 |
| 受保护后台 | `127.0.0.1:8000` 为已安装的 `HeatBackend.exe`，PID 12708；未向它发送业务或退出请求，未结束该进程 |
| 本轮变更 | 仅新增本报告；验证脚本、镜像构建和日志写入 ignored 的 `output/project-review-20261021/`。浏览器另外产生一份无设备 YAML 下载件，见 §8 |
| 禁止动作执行情况 | 未修复产品、修改现行文档／规则、删除原文件、提交、推送或改写 Git 历史 |

原始基线及文件哈希在 `output/project-review-20261021/baseline.json`。收尾 SHA-256 比对：已有286个文件无内容变化或删除，唯一新增的非忽略文件是本报告；既有未提交状态保留。文中行号指本轮工作区；未来修复会改变行号。归属判断使用 scoped diff 和 HEAD 同段文本核对，不依据文件修改时间猜测。

优先级含义：P1 为应先阻断的控制／确认目标错误；P2 为需分批修复的失败传播、追溯、兼容或维护问题；P3 为较低优先级的文档入口问题。

## 2. 工作包覆盖与结论

| 工作包 | 实际检查与结论 | 未覆盖或限制 |
| --- | --- | --- |
| 协议、驱动与串口 | AIBUS／Modbus 收发与校验、同步驱动返回值、serial manager、文件锁与指纹绑定；确认 B1、B3、B4、B5。短写公开接口假成功线索未成立 | 未在 USB 故障、真实串口驱动或厂家仪器上注入超时／短写；未知协议语义不凭代码推定 |
| 实验与控制流程 | 普通 YAML、PersistentExperimentEngine、StepExecutor、引导批次、微波托管、ProgramController／旧控制台入口；启动互斥、暂停计时、停止清理、恢复锁及持久化重试；确认 B2，前端确认边界另见 F1/F2 | 未运行旧控制台硬件入口，不证明仪器物理停止；普通断网不等于请求协程一定取消 |
| API、存储与科学记录 | 路由、参数模型、路径/revision、run/sample 删除重试、Campaign/Trial/表征、两种 pending 事务及批次快照；确认 S1/S2，关联竞争见 F4 | 没有对真实实验数据做写入或修复；没有替实验室判断原始表征文件及结果的科学有效性 |
| 前端与接口契约 | 全部 8 路由、相关设备组件、共享／独立 WS、编辑器、模板、监控、历史、Campaign、单位换算；128 项现有测试及 12 个新增隔离复现场景；确认 F1–F7 | SFC 复现是实际 setup + 假依赖，并非全部等价于鼠标操作；未声称浏览器覆盖所有按钮及异常分支 |
| 网页、桌面与部署 | Web/bat/旧 console 入口；桌面 IPC、双单实例、身份校验、端口占用、导入暂存、退出重试、数据路径、发行资源／安装器；当前软件回归通过，见 §5/§9 | 固定 8000 的独立后台子进程用例因现有后台占用跳过；未运行安装器、托盘或干净离线机器验收 |
| 文档、上下文与规则 | 42 份 Markdown、8 个技能文件、AGENTS／Trae入口、枚举/parser/API AST、108 个本地链接与锚点、29 个 YAML 围栏；确认 D1–D8 | 标题 slug 采用 GitHub 近似算法；1 个外链未联网核验；设备原件只核身份/哈希，未重新逐页签核 |
| Git 与目录治理 | 当前索引／未跟踪／ignored、本地 exclude、142 个可达提交、大对象、有限密钥模式、目录用途与大小；确认 G1；清理分级见 §7/§8 | 8 个无权限目录未读；没有遍历不可达对象、二进制内部或证明不存在任意格式的秘密 |

## 3. 优先修复的 P1

### F1：页面失效后，待确认的硬件操作仍会提交

- **位置**：`frontend/src/views/ControlPanel.vue:762`（加热）、`:1092`（微波托管）、`:611`（卸载）；`frontend/src/views/BatchExperimentPage.vue:388`／`:490`（引导及卸载）；`frontend/src/components/ValveControl.vue:75`；`frontend/src/components/SyringePumpControl.vue:183`。温度写入和 EEPROM 确认存在同类等待边界。
- **触发**：设备启动／运动确认 Promise 尚未完成，页面先卸载；随后旧确认成功。确认后的 handler 没有页面存活／操作代号校验，原参数签名也未因卸载失效。
- **复现结果**：heater 仍调用 `startHeater('heater1')`；微波仍提交 `hardware_confirmed:true`；引导仍 POST `/api/guided/start`；阀位仍 `switch(true)`；注射泵仍发 `initialize, confirm:true`。另在 handler 级复现了旧确认与停止交错：`['emergencyStop', 'start:heater1']`。
- **影响**：已经离开的控制上下文仍能发出新的物理动作。后端正常校验参数不能判断 UI 确认已过期。
- **证据边界**：是真实 SFC setup、可控确认 Promise 与假 API 的确定性复现。同一页面的 MessageBox 会遮挡底层急停按钮，**未把上述交错描述成真实单窗口鼠标烟测**；离页后的真实确认框交互仍需隔离浏览器补验。
- **最小修复**：确认前建立局部操作代号／single-flight；卸载及相关停止／断连使其失效；确认后检查代号、页面存活、连接和必要参数快照。普通实验已有 `wsClosed`、泵已有令牌保护可参考。**不要以卸载／WS 断开事件停止已经运行的硬件。**
- **验收**：每条待确认写入路径在离页／撤销／相关停止后，即使原确认成功也不新增命令；已经提交的后台实验继续使用原有明确停止流程。
- **归属**：基线已有；相关前端源码相对 HEAD 无内容差异。

### F2：选择 B 失败后，确认框显示 A，实际却启动 B

- **位置**：`frontend/src/views/ExperimentPage.vue:550`、`:579`。
- **触发**：A 已选中；选择 B 的详情请求失败。请求前 `selectedFilename` 已改为 B，失败时 `selectedExp` 仍是 A，开始入口仍可用。
- **复现结果**：确认文案为 `确定要启动实验 "Experiment A" 吗？`，实际 POST `/api/experiments/B.yaml/start`。
- **影响**：确认目标与将执行的配方不一致；后端对 B 的正常配方校验无法识别这个选择错误。
- **最小修复**：文件、详情、运行展示作为一份选择状态提交；加载期间禁启动；只有当前请求成功才更新整套状态。启动捕获选择快照，并在确认后核对选择未变，同时丢弃迟到响应。
- **验收**：A→B 失败、A/B 反序返回、加载中点开始均不得出现显示名称与启动路径不一致。
- **归属／证据**：基线已有；`frontend/reproductions.json` 中 `Experiment failed selection keeps old details but starts new filename`，真实 setup + 假 axios。

## 4. 其余代码与接口发现

以下 12 项均为 P2，均能在 HEAD 找到对应既有逻辑；部分文件本轮只有数据根路径或退出门禁修改，未改变所列触发段。

### B1：串口 close 失败后丢失句柄及所有权，重试可错误成功

- **位置**：`src/utils/serial_manager.py:491`（尤其 `:500`／`:502`）；传播到 `src/protocols/modbus_rtu.py:181`、`src/protocols/aibus.py:221`、`src/devices/heater.py:215`。
- **触发／实证**：fake handle 首次 `close()` 抛错且保持 open，第二次本可成功。manager 仍删除 handle、释放跨进程锁；协议清空引用。heater 两次 disconnect 都 True，但 handle.close 总共只调用一次，handle 仍 open。首次断开后直接 Modbus reconnect 被残留 reservation 拒绝；另行再次调用 manager.release 又可 True 并清除 reservation，但实际 handle 仍 open。
- **影响**：资源真实状态、所有权与返回值不一致，正常重试失效。没有据此声称 OS 会允许两个独占串口同时打开，也没有把断开当作物理停机。
- **最小修复／验收**：close 未确认时保留 handle、reservation、文件锁与上层引用，并向上传播 False；第二次明确重试应实际重试 close，成功后才释放。须同时覆盖 manager、协议及设备封装。
- **证据**：`backend/protocol_probe_results.json.failed_close`；`reproduce_protocol_findings.py.probe_failed_close`。涉及文件相对 HEAD 无差异。

### B2：取消停止调用者会连带取消 owned 清理，后续设备未收到停止命令

- **位置**：`src/experiment/engine.py:312`、`:317`、`:396`；生产普通实验入口 `src/web/api/experiments.py:372`。
- **触发／实证**：真实 PersistentExperimentEngine + StepExecutor + 临时 logger，fake heater/pump 均启动。stop 正在停 pump 时，只取消等待 `engine.stop()` 的 caller。取消传播到 owned `_task` 和 `_cleanup_task`；pump 线程完成，后面的 heater.stop 没有调用。
- **结果**：`heater_stop_calls=0`，heater 仍 running，引擎仍 running，恢复记录 `cleanup_required=true, recovery_required=true`；第二次明确 stop 才成功清理。
- **影响边界**：恢复锁仍保留，不是静默实验成功。普通浏览器断开不必然取消 FastAPI handler；不能把该复现解释成关网页必然触发。
- **最小修复／验收**：发布 stop 意图后，由引擎所有的单一停止／清理任务独立存活，调用者通过 shield 等待；取消外部等待不应取消清理。覆盖所有直接 await owned task 的路径，验证去重及失败重试；不在驱动内增加线程。
- **证据**：`backend/reproduce_engine_cancellation.py`、`engine_cancellation_results.json`。engine/executor 无 HEAD 差异；yaml_recovery 本轮只改数据路径。

### B3：Modbus 墙钟 deadline 在系统回拨时延长交易

- **位置**：`src/protocols/modbus_rtu.py:274`。
- **触发／实证**：公开 read 路径无响应，配置 timeout=1s；只替换模块时钟，模拟一次回拨 60s。对照持续 1.18s，回拨后持续 61.12s，均为模拟时间，无真实一分钟等待。
- **影响**：同步交易与设备锁占用延长，后续控制／stop 可等待更久；泵、阀、微波共用该协议。
- **最小修复／验收**：deadline 改用 `time.monotonic()`，保留同步驱动和锁；回拨／前跳均不改变既定等待上限。
- **证据**：`backend/protocol_probe_results.json.clock_rollback`。协议文件无 HEAD 差异。

### B4：陈旧串口锁的并发接管不互斥，旧 owner 可删除新锁

- **位置**：`src/utils/serial_manager.py:104`（`:123` 无条件 replace）、`:162`（释放不核 owner）。
- **触发／实证**：两个独立 SerialPortLock 对象均先读到同一已退出 pid；Barrier/Event 固定接管顺序。A 替换旧锁，B 按旧判断再替换 A；两者 acquire 都 True，最终文件属于 B，A.release 又删掉 B 的锁。
- **影响边界**：证实 Heat 文件协调失效；Windows 串口独占仍可能阻止第二个真实 handle，未证明真实命令并发写入。占用诊断、清理和后续锁归属已不可靠。
- **最小修复／验收**：接管检查／替换用真实跨进程互斥或完整原子所有权协议；每次占用带独立 owner token，release 只释放自身持有记录。简单“替换前再读一次”仍存在 TOCTOU。增加双进程争抢和 owner 释放测试。
- **证据**：`backend/protocol_probe_results.json.stale_lock_race`；只在临时目录操作锁。serial_manager 无 HEAD 差异。

### B5：合法的仅 VID/PID 指纹配置永远 no_match

- **位置**：`src/utils/serial_binding.py:189` 至匹配函数末尾 `:228`；接受条件见 `src/utils/config.py:132`、resolver `serial_binding.py:182`。
- **触发／实证**：mode=fingerprint，仅配置 vid/pid；枚举假设备为唯一匹配的 COM_REVIEW。配置 validate errors=[]，resolver 却返回 `binding_resolved=false, binding_error=no_match, match_count=0`。
- **影响**：合法且文档支持的绑定方式不能连接；该路径失败关闭，没有连接错设备的实证。
- **最小修复／验收**：补 VID+PID 匹配分支；保留唯一性检查，多台同型号仍须 multiple_matches，不猜串口。
- **证据**：`backend/protocol_probe_results.json.vid_pid_binding`。binding 无 HEAD 差异，config 仅有数据路径改动。

### S1：非有限科学数值先保存，响应才 500，后续读取持续失败

- **位置**：`src/web/api/campaigns.py:36`／`:39`、`:113`；`src/campaigns/store.py:78`、`:245`。
- **触发／实证**：向临时 Campaign/Trial 的 characterization 提交 metrics。既测试 `NaN`，也测试符合 JSON 数字语法但溢出的 `1e309`；请求均被接受为 Python 非有限数。store 保存后响应 JSON 序列化失败。
- **结果**：两种输入都是 POST 500、磁盘已有 1 条记录；后续 GET characterizations 500。`persisted_nan=true`／`persisted_infinity=true`。这不是保存失败回滚，而是失败响应掩盖已提交的数据。
- **影响**：污染该 Campaign 的表征读取和 planner history，也可能因用户重试重复写入。代码中其他任意字典数值入口应一并核查。
- **最小修复／验收**：写入前递归校验有限数值；JSON 写出采用 `allow_nan=False` 兜底且不能提交半份事务；对旧异常记录给明确诊断，保留原数据，不能静默清空。非法值被 4xx 拒绝且文件不变，合法值和事务回滚行为不退化。
- **证据**：根目录 `repro_api_boundaries.py`／`.json`／`.log`（均在审查 output 下）；内存 ASGI + 临时真实 store，无端口。campaign API 无 HEAD 差异，store 只有 data_path 改动。

### S2：Campaign JSON 根形状错误被当空库，下一次创建覆写原内容

- **位置**：`src/campaigns/store.py:52`（`:61` 至 `:63`）、`:139`。
- **触发／实证**：临时 campaigns.json 是可解析对象 `{"campaigns":[{"campaign_id":"camp_prior"}]}`；list 只 warning 后返回 []；create_campaign 成功写成只有新记录的列表。
- **结果**：`list_result=[]`，`creation_returned_success=true`，`prior_payload_retained=false`，`current_rows=1`。
- **影响**：结构损坏／错误格式的原始记录被进一步覆盖，而无失败关闭保护。未声称当前真实 Campaign 文件已出现此损坏。
- **最小修复／验收**：非列表根、必要行形状错误应明确报损坏并拒绝写入；文件字节保留。空库初始化、损坏诊断和恢复事务分别测试，不自动猜格式迁移。
- **证据**：`repro_store_root_shape.py`／`.log`；TemporaryDirectory 内执行，store 触发逻辑为 HEAD 已有。

### F3：Campaign A 的迟到响应覆盖已选 B 的记录

- **位置**：`frontend/src/views/CampaignPage.vue:296`，尤其 `:304`／`:305`。
- **触发／实证**：A 请求先发，选择 B 后 B 先回，A 后回。最终 selected=B，但 trials 与 characterizations 的 campaign_id 都为 A。
- **影响**：B 标题下出现 A 的科学记录，后续操作又使用 B 的 ID，造成误读、错误目标或 404。
- **最小修复／验收**：选择代号与 ID 双重校验，切换时清旧记录／关联输入并显示加载；反序、部分失败、离页后的响应均不得污染当前 Campaign。

### F4：Campaign 关联字段并发保存可静默回退新 sample_id

- **位置**：`frontend/src/views/CampaignPage.vue:391`；run_id/sample_id 的 change 入口；后端字段更新见 `src/web/api/campaigns.py:101`。
- **触发／实证**：先改 run，发 `{run_id:new, sample_id:old}`；再改 sample，发 `{run_id:new, sample_id:new}`；第二写先提交，第一写后提交。假持久化端最终 sample=old，UI 仍 sample=new，两次均成功且无错误反馈。
- **影响**：科学记录的 run/sample 关联与用户看到的状态不同。
- **最小修复／验收**：每次仅 PATCH 实际改变的字段，或按 Trial 串行/版本校验保存；任意提交／响应顺序下最后编辑的两个字段都保留，失败明确标未保存。

### F5：保存 A 的迟到响应把新导入 B 重新绑定到 A

- **位置**：`frontend/src/views/ExperimentEditor.vue:208`、`:214`、`:242`；导入／重读未在 saving 期间禁用。
- **触发／实证**：保存 A pending→导入 B→A 保存返回。source=B，但 filename/loadedFilename=A.yaml，revision=rev-A2；下一次保存用有效 A revision 将 B 写向 A。
- **影响**：导入文档身份和保存目标错误；后端 revision 并不能阻止这次覆盖。
- **最小修复／验收**：保存期间阻止更换文档并在 handler 守卫，或给文档代号使旧响应只更新原文档；保留用户在同一文档保存期间继续编辑时的未保存内容。

### F6：允许保存的 `#`／字面 `%20` 文件名在执行页未编码

- **位置**：`frontend/src/views/ExperimentPage.vue:535`、`:557`、`:579`、`:600`、`:612`、`:630`、`:647`；允许范围 `src/experiment/parser.py:33`；正确对照 `frontend/src/api/experimentEditor.ts:7`。
- **实证**：真实 parser 接受 `test#1.yaml` 和 `batch%20a.yaml`。真实 setup + 假 axios 捕获执行页直接拼接的请求，Node URL／decodeURIComponent 断言前者传输 path 为 `/api/experiments/test`（其后为 fragment），后者解码为 `batch a.yaml`，不是原字面文件名。本项未将这些请求实际发送至 HTTP 服务。
- **影响边界**：合法文件无法正确预览／控制；若解码目标另有同名文件可能指错目标，此重名启动场景未做 HTTP 硬件实证。
- **最小修复／验收**：所有 filename 路径段统一 `encodeURIComponent`；中文、空格、`#`、字面 `%20` 的预览、选择、启动、暂停、恢复、停止和进度始终指向同一文件。

### F7：控制参数 localStorage 写失败无可见反馈（P2，低优先）

- **位置**：`frontend/src/views/ControlPanel.vue:417`、`:478` deep watcher。
- **触发／实证**：存储配额耗尽或写入被禁止，setItem 抛异常；watcher 没捕获且无消息。开发版 Vue 还记录未处理调度 Promise 拒绝。
- **影响边界**：偏好未保存而用户不知，重开恢复旧值。**没有证实生产页面因此崩溃**，生产默认错误处理可能仅写控制台。
- **最小修复／验收**：保留当前表单，捕获 QuotaExceededError/SecurityError，显示一次明确未保存状态，恢复可写后可重试。继续依靠既有后端校验物理参数。

F3–F7 的完整输入／输出在 `frontend/reproductions.json`，驱动脚本为 `frontend/reproduce-findings.mjs`。F1–F7 共 12 个场景均断言通过；前端产品源码相对 HEAD 无差异。

## 5. 条件性风险、已排除线索与桌面结论

### R1：Web 模式的网络信任边界需要使用方明确

**事实**：`run_server.py:11` 默认监听 `0.0.0.0`；`src/web/app.py` 未设置认证门禁；设备 router 的 Depends 为运行互斥，不是用户认证。在内存 ASGI 中伪设 client 为 `192.0.2.10`，无凭证 POST `/api/heater/heater1/start` 返回 200 且调用 fake manager 一次。CORS 限制不能阻止直接 HTTP 客户端。

**风险条件**：如果主机防火墙和网络让不受信任者访问该端口，就能提交硬件控制请求。没有扫描用户网络或证明该电脑对外网可达；LAN 远程控制本来就是 Web 模式的既有能力，因此此项单列为部署风险，不自动定义为桌面缺陷或替用户新增认证 API。

**建议**：本机使用优先桌面/loopback；如保留 Web LAN 控制，单独确认可信网络、主机访问限制和是否需要应用身份认证。默认监听或认证若变更，须明确远程使用兼容影响。桌面仍只监听 `127.0.0.1:8000`。

### 已检查但不能据此认定缺陷

| 线索 | 证据与处理 |
| --- | --- |
| 串口短写会公开假成功 | 内部确实未检查 write 字节计数，但假串口只写 7/8 字节、无合法完整回包时，公开 `write_single_register=False`。没有伪造不可能回包来制造“实机成功”结论；作为后续健壮性改进线索 |
| write_timeout／flush 上限 | 构造未设置 write_timeout 是代码事实；USB／内核阻塞与仪器实际时序未验证，不把任意 fake 阻塞当实机缺陷 |
| ProgramController safety_temperature 无消费点 | 孤立字段确无当前消费点，但生产 Web 未使用 ProgramController；旧 console 实际使用 AutomationController。不能当成当前 Web 保护被绕过的证据 |
| 所有版本号必须统一 | 桌面 0.1.1 用于 IPC、安装器与清单且一致；API 2.2、Python 包元数据／导出版本、private npm 包用途不同，未发现实际不兼容，不直接统一数字 |
| Python 依赖清单不同 | 三份基础清单的 7 个包及下限一致；桌面 38 项运行依赖＋7 项构建依赖与发行清单匹配。重复维护成本存在，未发现当前缺包证据 |
| 新旧液路说明互相冲突 | 工程/MVP 的 CH4 进水、CH3 出水是特定水测基线；双注射泵／阀流程另有适用范围。历史条件保留，宜补适用范围导航，不能批量改旧实测事实 |
| 批次与 Campaign 必须自动关联 | 当前约定为人参与的独立流程，Trial 参数不自动注入 YAML。没有因未实现自动串联而提出新 API/执行功能 |

### 桌面与部署当前证据

- 源码检查与现有测试覆盖：shell/backend 两类单实例，身份／instance_id 校验，未知端口冲突拒绝，导入前不创建设备后台，暂存＋源稳定性＋哈希核验，业务数据根与 WebView 资料隔离。
- 显式退出覆盖普通实验、引导和微波托管；失败／超时保留后台、连接和读取／stop／急停／恢复入口；终态持久化可明确重试，不重放动作。源码中退出等待不强杀后台，窗口隐藏／WS 事件不控制硬件。
- 已修复的旧桌面清理失败重试问题与保存重试问题，当前测试通过，本报告不重复当作现存发现。
- 现有 0.1.1 发行清单 **655 项** size/hash/member 集合一致；Heat.exe 与 HeatBackend.exe 各 **70 个 src 模块＋入口代码对象**与当前源码一致；**92 项**静态资源一致。未重建或安装该发行。
- WebView2／ISCC 的哈希与清单一致，当前只读签名状态 Valid；源码构建明确收集依赖、静态资源及图标。安装器无用户数据删除项，要求 Heat 正常退出，内置官方离线 WebView2 安装失败会报错。
- 这些是软件／文件证据。**Windows 11 x64 无 Python/Node/WebView2 的离线安装、升级、卸载保留数据，及真实托盘/窗口/设备停机仍未在本轮验收。**跨用户权限隔离、真实系统关机和异常进程退出也未作系统级故障注入。

## 6. 文档、上下文与协作规则纠正表

下表是修复建议，**本轮没有修改这些文件**。8 项触发文本均已在 HEAD 找到；D7 的前提缺失也延续到新增桌面说明。

| ID／优先级 | 位置与已确认问题 | 最小纠正与验收 |
| --- | --- | --- |
| D1／P2 | `.trae/skills/doc-sync/SKILL.md:8`、`:42`、`:116`、`:122` 仍引用不存在的 heat.md §8.2，强制每次改 context，并硬编码推送 develop-web；与 AGENTS 及 heat-git 冲突 | 改成当前 AGENTS／测试指南的薄入口；按范围更新文档，获明确确认后才推当前分支。任意批准任务分支及 docs-only 案例都得到一致流程 |
| D2／P2 | `.trae/skills/code-review/SKILL.md:8`、`:32`、`:36`、`:42`、`:97` 引用失效章节，要求全部 RLock、全局禁 daemon／注释，并将编译称为唯一客观检查 | 删掉无当前依据的全局禁令，按驱动／Web／桌面职责和行为风险检查。驱动仍同步，上层桥接不因线程本身误判，不能编译代替行为测试 |
| D3／P2 | `docs/testing_and_merge_flow.md:19`／`:24` 要求所有改动跑 metadata/imports/前端构建，而 `:325`／`:329`、AGENTS 与 heat-git 按范围；`docs/developer_guide.md:402`／`:407` 仍有旧统一合并清单 | 以按范围验证矩阵为主来源，其他入口引用或一致摘要；docs-only、backend、frontend、hardware 四例一致，保留实验室验收要求 |
| D4／P2 | `docs/experiment_yaml_spec.md:805` 的 `position: NO` 被 PyYAML SafeLoader 转成 bool False，真实 parser 报 `valve position must be NO or NC` | 改为 `position: "NO"`，并检查同类面向用户片段；完整示例 parse＋editor 参数校验通过且类型为字符串，无需改变协议或全局 YAML 语义 |
| D5／P2 | `docs/experiment_yaml_spec.md:771` 称泵2默认未配置，但 `config/system_config.yaml:136`／`:141` 及接入指南已启用两台；只读配置验证通过 | 改成“被引用泵未配置／禁用／未连接则启动前失败”的条件表述；适用于当前双泵及新工作区，不替实验室确认身份 |
| D6／P2 | `context/PROJECT_CONTEXT.md:59` 的当前完整能力清单漏 syringe_pump 系列及 `syringe_pump_complete`、`microwave_monitored_hold`；后部零散追加 | 集中当前清单或链接主规范；枚举含14个 syringe 动作，但 YAML 仅13类可用，`syringe_pump.pause` 被 parser 明确拒绝、仅手动使用，不能直接复制全部枚举 |
| D7／P2 | `README.md:53` 与 `docs/desktop_app.md:68` 没写 Node 下限；`frontend/package-lock.json:2720`／`:2737` 的 Vite 8/Rolldown 要求 `^20.19.0 \|\| >=22.12.0` | 开发／桌面构建准备写明 lockfile 约束及已验证版本；区分构建机和安装目标，桌面用户不需要 Node |
| D8／P3 | `docs/user_guide.md:62` 称5页，后表已有6项，实际 `frontend/src/router/index.ts:6` 起为8路由；批次／模板入口分散 | 去掉易漂移固定数量，说明主要导航与子页关系；总览可定位全部8路由，链接／锚点有效 |

其它文档结论：

- 109 个显式 Markdown 链接中，108 个本地目标及标题锚点有效，1 个外链未联网验证；不意味着纯文字旧章节引用正确（D1/D2 已另检出）。
- 29 个 YAML 围栏：16 个实验／步骤片段通过真实 parser 与参数模型；12 个配置／局部字段或故意错误片段不作为完整实验；1 个错误为 D4。只解析，未执行配方。
- 81 个 API/WS 声明（含尾斜杠别名）通过 AST 和 include_router 核对；未发现文档所列完整接口不存在。WS 是 `/ws`，不加 `/api`。
- 六份厂家 PDF/DOC 共 36,733,741 B，SHA-256 与设备资料索引一致。厂家版次／固件匹配、缺失的继电器厂家原件与微波原始 XLSX 仍待补证；微波协议 Markdown 现为保留依据，不能因是转换稿就删除。
- `docs/archive/` 的旧 COM、旧默认、旧测试数是历史证据。保留日期、基线、运行号；不批量改成当前事实。现行 0.1.0/0.1.1 桌面说明区分旧 GUI 冒烟与当前软件／发行核验，没有将它们宣称为干净机完整验收。
- AGENTS 与 Codex heat-git 的分支许可、分范围验证、确认推送、归档次序相互一致；应纠正旧入口，避免复制出第三套规则。

证据：`docs-deployment/documents_inventory.json`、`navigation_audit.json`、`capabilities.json`、`api_routes.json`、`yaml_examples_validation.json`、`findings.json`。

## 7. Git 忽略规则调整方案

### G1／P2：按扩展名及未锚定 data 目录的全局忽略会误屏蔽资料和测试样本

**事实与复现**：`.gitignore:42` 的 `data/`、`:43` 的 `*.csv`、`:44` 的 `*.xlsx`、`:45` 的 `*.xls` 在任意层级生效。`git check-ignore --no-index -v` 验证下列候选路径被屏蔽：

| 探针路径 | 当前匹配 | 建议目标 |
| --- | --- | --- |
| `data/datasets/samples.csv` | `data/` | 继续忽略真实业务数据 |
| `tests/fixtures/data/case.json` | `data/` | 测试样本可提交，根运行目录规则宜为 `/data/` |
| `tests/fixtures/run.csv` | `*.csv` | 经过审查的合成测试样本可提交 |
| `docs/device_materials/vendor.xlsx` | `*.xlsx` | 厂家原件按资料用途决定跟踪，不被全局扩展名静默屏蔽 |
| `docs/examples/recommendation.csv` | `*.csv` | 明确的脱敏示例可提交 |
| `output/desktop/release/HeatSetup.exe` | `output/` | 继续忽略，不把发行和环境上传源码仓库 |
| `packaging/desktop/heat.spec` | 显式 `!packaging/desktop/heat.spec` 例外 | 保留该源码入口，不能删除例外 |
| `src/desktop/app.manifest`（假设将来新增） | `*.manifest` | 需要源 manifest 时应精确放行；目前不据此臆造缺文件 |
| `frontend/package-lock.json`、`requirements-desktop.txt` | 未忽略 | 保持锁／依赖清单可提交 |

这是**规则探针**，不是声称这些假设文件已经丢失。当前 `git ls-files -ci --exclude-standard` 为 0：没有已跟踪文件被现行 ignore 匹配。G1 为 HEAD 已有规则；此次新增 `/output/desktop/` 只是与 `output/` 重复。

建议下一阶段以用途定规则，先做匹配矩阵，再修改：

1. 运行数据、日志、导出采用根锚定 `/data/`、`/logs/`、`/output/` 及明确 reports 导出范围；确认没有其他实际运行写入目录遗漏。
2. 移除全局 CSV/XLSX/XLS 规则，或给受控 fixtures/资料/示例精确例外。放开后重新盘点未跟踪项，不能直接 `git add .`；实验数据继续受运行目录规则保护。
3. 保留 node_modules、venv、bytecode、pytest/cache、前端静态输出与桌面产物的忽略；删除冗余 `/output/desktop/` 只属规则简化，不影响功能。
4. 保留 `heat.spec` 例外；manifest 在确有源码需求时放行指定文件。不要一刀切取消所有生成文件保护。
5. `.env` 与 `config/local_config.yaml` 目前没有匹配规则，但本轮有限模式未发现泄露。可为实际私有配置增加精确保护并保留 `.env.example`／合成 fixtures。当前受跟踪 `config/system_config.yaml` 是既有配置来源，不能未经迁移设计直接 untrack。
6. `.git/info/exclude` 另有 `/tmp/imagegen/`，全局 excludesfile 未配置。团队需要依赖的约定应进入仓库规则；个人临时文件可继续本地排除，不能误以为其他机器自动继承。
7. 新规则不会取消已有跟踪；未来如有真实数据误跟踪，须另列迁移与历史处理。**本轮没有执行 `git rm --cached`、历史重写或 gc。**

### 当前／历史敏感与体积检查

- 当前跟踪文本、142 个可达提交的 diff，以及补充扫描的 1608 份可读本地文本，均未命中限定的私钥头、OpenAI-like、GitHub、AWS access-ID 高精度模式。只输出命中位置，不输出内容。
- 这不是完整 secret audit：依赖/构建副本、WebView profile、二进制、较大文本、无权限目录、不可达对象、任意格式凭证及人为敏感实验内容没有全覆盖。
- 历史 ≥1 MiB blob 只有3个，均为厂家 PDF（约29.13、2.92、1.55 MiB）。应保留资料来源，不建议为这些文件改写历史。
- 158 个 ignored 源码／Markdown 候选主要含冻结依赖副本、浏览器生成脚本、独立复现和实测记录。应逐项决定哪些有长期价值需要整理到 tests/scripts/archive；不能全部作为垃圾，也不能全部加进 Git。
- 证据：`inventory.json`、`hygiene-addendum.json`。后续验收应同时证明“运行数据仍忽略”与“源码／受控样本／设备资料可见”。

## 8. 分类清理清单

**本轮没有清理。**大小为只读盘点时的文件字节总和，MiB=1,048,576 B；不是实际磁盘簇占用，也不包括无权限内容。原 inventory 按深度归入互斥分类桶，不是每行的递归目录总量，尤其 `output` 行只是残余桶；可读旧快照合计 2,022,528,287 B，其中 output 各桶合计 1,723,311,522 B，均不是可释放容量。本轮审查新产物与运行中的日志会变化，不能将下表简单相加当作承诺可回收空间。已安装程序与 `%LOCALAPPDATA%/Heat` 用户工作区不在清理范围。

### 8.1 可再生成候选（删除前仍应确认用途）

| 路径 | 大小／跟踪 | 用途、引用与再生成方式 | 建议 |
| --- | --- | --- | --- |
| `tests/__pycache__/` | 约3.18 MiB；未跟踪 | Python 测试字节码；import/pytest 再生成，无业务记录引用 | 可清缓存，不能混入原测试源码 |
| 源码各层 `__pycache__/` | 各模块混合目录另计；未跟踪 | Python import 再生成；需限定具体缓存目录 | 不按 `src/` 整删 |
| `frontend/node_modules/` | 234,105,239 B；223.26 MiB；未跟踪 | 前端构建／tsx 测试依赖；按 package-lock 用 `npm ci` 重建 | 频繁开发建议保留；离线重建需事先保留依赖来源 |
| `src/web/static/` | 单独复核92文件，2,368,246 B，约2.26 MiB；未跟踪 | 当前源码 Web 启动直接服务的生产前端；`cd frontend; npm run build -- --mode production` 再生成 | 会影响未安装 Web 使用，保留至确认可重建，不作为随手缓存删除 |
| `output/desktop/build/` | 60,282,552 B；57.49 MiB；未跟踪 | PyInstaller 中间产物；`scripts/build_desktop.ps1` 重建 | 可在停止构建后清理指定目录 |
| `output/desktop/dist/` | 105,286,744 B；100.41 MiB；未跟踪 | 冻结发行目录，安装器从这里取文件；同构建脚本重建 | 保留当前发布核验清单后再决定；开发直接运行者需要它 |
| `output/desktop/assets/heat.ico` | 7,220 B；未跟踪 | 由跟踪的 `frontend/public/favicon.svg` 经 `packaging/desktop/make_icon.py` 生成，spec/安装器使用；`src/desktop/main.py:303` 的源码托盘回退也直接引用它 | 可重建，源码桌面运行前须保留或先重建，不能只因 ignored 就删除 |
| `heat.egg-info/` | 8,012 B；未跟踪 | 本地 Python 包安装元数据，依源码重新安装生成 | 可再生成，但现有 editable 安装使用期间保留 |
| `output/project-review-20261021/frontend/build-mirror/`、`build-dist/` | 本轮新增，未计入旧盘点；未跟踪 | 隔离生产构建，prepare_build.py 与现有依赖可重建；镜像含 node_modules 目录联接 | 报告确认前保留；清理不得沿目录联接删除真实依赖 |

### 8.2 需要留存决策

| 路径 | 大小／跟踪 | 用途、再生成／引用 | 建议保留方式 |
| --- | --- | --- | --- |
| `output/desktop/release/` | 509,269,764 B；485.68 MiB；2个 EXE；未跟踪 | 0.1.0／0.1.1 安装器，实际交付和回退依据；重建需相应源码/工具链 | 按发布版本存安装器、清单、哈希、验收范围；旧版非自动删除项 |
| `output/desktop/downloads/` | 224,748,256 B；214.34 MiB；未跟踪 | 官方离线运行时／工具下载件，构建或离线恢复依赖 | 核官方签名/hash后保留一份受控离线来源；不随源码提交 |
| `output/desktop/runtime/` | 214,156,024 B；204.24 MiB；未跟踪 | WebView2 离线安装资源，构建安装包使用 | 与 downloads 比对后可去重，但需保留构建预期路径或明确恢复步骤 |
| `output/desktop/venv/` | 180,803,220 B；172.43 MiB；未跟踪 | Python3.10 x64 固定构建环境，脚本和维护核验使用 | 可以依固定清单重建；离线构建前不删唯一可用环境／包源 |
| `output/desktop/tools/` | 34,131,862 B；32.55 MiB；未跟踪 | Inno Setup 等构建工具 | 根据签名/hash及离线重装能力决定保留，不假定外网一直可用 |
| `output/desktop/full-smoke/` | 83,177,892 B；79.32 MiB；未跟踪 | 隔离桌面 profile/数据及验证产物，不能当正式工作区 | 摘录验证结果与必要截图后，仅对确定可重做的 profile 清理 |
| `output/desktop/bridge-smoke/` | 80,769,885 B；77.03 MiB；未跟踪 | 桥接测试 profile/产物 | 同上，先与独立验证脚本和旧报告对应 |
| `output/desktop/ui-smoke/` | 73,933,412 B；70.51 MiB；未跟踪 | UI 冒烟 profile/产物 | 同上 |
| `output/desktop/冻结 冒烟/` | 73,511,905 B；70.11 MiB；未跟踪 | 冻结 GUI 冒烟 profile/产物 | 同上；保留该次发行证据 |
| `tmp/imagegen/` | 约1.52 MiB，7文件；本地 exclude | 图像来源／参考件，未证明每个均可由受跟踪资源重建 | 逐图检查唯一素材及引用后决定，不能因临时目录直接删除 |
| `output/` 下独立 `.py/.js/.md`、预览与导出件 | 分散，详见 inventory；未跟踪 | 有些是一次性调试，有些是唯一故障复现／测量材料；通常不被生产程序 import | 有长期价值的整理到受控脚本/归档，其余按文件清单决定 |
| 本轮 `output/project-review-20261021/` | 本轮新增；未跟踪 | 基线、复现、JSON、测试日志与截图，是报告底层证据 | 至少保留至对应修复完成；先把必要复现转成正式回归，再归档/清理冗余镜像 |

### 8.3 保留追溯依据

| 路径 | 大小／跟踪 | 保留理由及引用 |
| --- | --- | --- |
| `output/experiment_logs/` | 31,831,857 B；30.36 MiB；21文件；未跟踪 | 实际实验运行记录，历史读取与 run/sample 关联依据，不是构建缓存 |
| `data/datasets/samples.csv` | 11,778 B；未跟踪 | 真实样品索引及 run/batch 关联；不可因 CSV 被忽略就删除 |
| `data/campaigns/` | 4文件，共16 B；未跟踪 | 当前为空列表也仍是业务存储位置；未来含 Campaign/Trial/表征与事务日志 |
| `output/guided_batches/` | 283,149 B；0.27 MiB；16文件；未跟踪 | 引导批次、方案快照及关联，不能从源码重建历史，保留 |
| `output/microwave_programs/` | 43,813 B；0.04 MiB；7文件；未跟踪 | 托管程序与中断/恢复状态，保留 |
| `output/yaml_runs/`、`data/syringe_programs/` | 旧盘点未形成独立桶，不能据此认定不存在；未跟踪 | YAML恢复、注射泵程序登记；实际业务根中的 `.pending`/`.lock` 不能仅按扩展名清理 |
| `logs/` | 主组 16,004,531 B＋`logs/devices/` 784 B；未跟踪 | 设备通信、故障和实测时间线；可做归档/轮转方案，不能全称垃圾 |
| `output/water-acceptance-materials/` | 13,334,156 B；12.72 MiB；未跟踪 | 水测准备、实测与验收材料，含追溯依据 |
| `output/monitor-water-test-*`、`monitor-microwave-*` 及故障报告 | 具体文件及大小见 inventory；未跟踪 | 真实监测、失败与验收证据，应按日期/运行归档 |
| `docs/device_materials/` | 9文件，约35.08 MiB；跟踪 | 厂家原件、索引和协议转换稿；六份原件hash已核对，微波原XLSX缺失时现有稿更应保留 |
| `docs/water_test_*`、验收文档、`docs/archive/` | 跟踪 | 已确认现场条件、Gate/SOP和历史证据；历史效力不等于无用 |
| `output/git-ref-recovery/` | 82 B；未跟踪 | Git 引用恢复线索，用途需与既有维护记录核对 |

其它需要逐项留存决策的目录如下；均为未跟踪。测试副本内可能含合成数据与缓存，也可能含唯一截图／复现，未核验为纯缓存，不能自动删除。

| 路径 | 精确字节 | 用途、重建性、引用及建议 |
| --- | ---: | --- |
| `output/desktop/installer-smoke/` | 2,055,134 | 隔离安装验证 EXE/ICO，非生产入口；按旧报告核对来源与残留后再决定 |
| `output/water-acceptance-baseline/` | 1,188,983 | 隔离验收副本；源码可能重做测试，不能重建原次证据；先核对关联并归档 |
| `output/water-acceptance-final/` | 1,188,815 | 最终验收副本，同上 |
| `output/water-acceptance-targeted/` | 440,829 | 定向验收资料，同上 |
| `output/yaml-recovery-final/` | 1,194,033 | 恢复测试资料，含JSON/CSV/YAML及锁；保留结果，合成数据确认后再清 |
| `output/yaml-recovery-suite/` | 1,192,124 | 恢复测试资料，同上 |
| `output/ui-review/` | 1,254,358 | 截图及人工 mock 脚本，无生产引用，保留关键审阅证据再清冗余预览 |
| `output/monitor-ui-20261020/` | 923,112 | UI监测截图，不能由当前重跑恢复原次状态，先归档 |
| `output/guided-timed-hold-20261020/` | 551,335 | 计时/保温截图及JSON，先按验收证据归档 |
| `output/manual-review/` | 360,101 | 人工复核截图，先归档 |
| `output/test-isolation-audit-20261016/` | 97,318 | 测试隔离审查记录，保留整改依据 |
| `output/autotune/` | 17,959 | 整定JSONL，属于参数/决策历史，不能源码重建 |
| `output/monitor-water-test-2026-10-19T09-08-43-749Z/` | 4,682,341 | 实机水测监控报告/JSONL/日志，保留 |
| `output/monitor-microwave-50c-2026-10-19T10-06-36-753Z/` | 1,153,135 | 实机微波监测证据，保留 |
| `output/imagegen/` | 4,266,893 | 6个生成/处理/对比素材，部分同hash但高分辨率主图不能由正式180px资产恢复；无直接运行引用，见下文 |
| `tmp/imagegen/` | 1,594,728 | 6参考图＋prompt，未发现程序引用，也未在本轮素材比对范围找到同hash副本；保留生成来源 |
| `src/__pycache__/` | 62,762 | 字节码，Python import可重建，限定缓存路径才是候选 |
| `scripts/__pycache__/` | 17,913 | 同上 |
| `output/` 残余分类桶 | 17,148,849 | 125个浅层文件，含人工脚本、截图、报告、锁；**不是整个output**，用途混合，不给整桶删除建议 |

未跟踪源码必须保留：`src/desktop/` 是源码/字节码混合桶（91,378 B），`packaging/desktop/` 也是混合桶（12,649 B）；`.py`、`.spec`、`.iss`、新依赖清单和构建脚本均是本次待提交实现，不能把“未跟踪”解释为可清理。

已确认的重复及生成链：

- WebView2 在 `output/desktop/downloads/` 与 `runtime/` 下的两份 EXE 各 214,156,024 B（204.235100 MiB），SHA-256 同为 `0625fb5c1e75be58a164e14f95aa58a3e5badb859b3d17c952385f3e4a9ff3e8`，与发布清单一致。仅能列为**保留一个已验证输入后**的去重候选，不能两处全删。
- `output/imagegen/syringe-pump-msp1cx-v2.png` 与 `syringe-pump-msp1cx-v2-chroma.png` 各945,104 B且同hash，均为1254×1254 RGBA、有透明度；名称不能作为是否抠图的判断依据。
- `output/imagegen/syringe-pump-msp1cx-v2.webp` 与跟踪的 `frontend/src/assets/theme/syringe-pump.webp` 各23,384 B且同hash；正式资源被Vue/catalog导入，应保留。输出副本可以在决定留存后列候选。
- `tmp/imagegen/msp1cx/` 的手册页、几何裁切、风格拼图与prompt在所查素材范围没有同hash副本；精确渲染/裁切配方未核实，AI重生成也不保证同图。
- ICO可由已有构建环境执行 `output/desktop/venv/Scripts/python.exe packaging/desktop/make_icon.py output/desktop/assets/heat.ico` 重建。完整构建脚本接受 `-Python`、`-ISCC`、`-WebView2Installer`；需要解释器、固定依赖及官方输入，不保证安装器位级重现。本轮没有执行重建/安装。

49个主要分类桶、逐素材哈希及引用证据另存 `docs-deployment/cleanup-addendum.md` 与 `cleanup-evidence.json`，均在本轮审查output下。正文已保留决定清理所需的主要数据，不能仅依据补充表的总量推定可释放空间。

### 8.4 未读目录与禁止的整目录清理

以下 8 个目录读取遇 PermissionError：`output/msp1cx-regression-1/`、`output/msp1cx-pytest-7/`、`-6/`、`-5/`、`-3/`、`-2/`、`output/msp1cx-final/`、`.pytest_cache/`。**大小和内容未知**，不提权、不视为空、不判定可删除；需先解释权限和用途。

只读 `git clean -ndX` 预览会把 output、logs、生产 static 等整体列为可删除。这只说明它们被忽略，不说明可以清理。禁止据此运行 blanket `git clean -fdX` 或整删 `output/`。

浏览器本轮下载件为 `C:/Users/Administrator/Downloads/审查 空间.yaml`，与隔离工作区中同名文件字节相同，SHA-256 `87d7b39e3919da0925d5fd5290f97967db204f3aac2e7f6f343db2088d5dfaff`。这是本轮新建的纯日志示例，不是实验室数据；本轮未删除它。

## 9. 实际验证、复现入口与未验证项目

### 9.1 先验隔离检查

- 阅读 `tests/conftest.py` 和 `tests/runtime_isolation.py`：autouse fixture 将实验副本、运行日志、samples、Campaign、引导批次、微波托管和 YAML 恢复记录重定向临时目录，持久化本身不被简单禁用。
- `tests/test_hardware.py` 为 `__test__=False` 的实机脚本，直接执行还要求 `--confirm-hardware-write`；本轮未运行。其它硬件脚本和文档 recipe 也未执行。
- 统一 runner 通过 `guard/sitecustomize.py` 令真实 `serial.Serial.open` 抛 AssertionError，并让测试子进程继承 guard 环境；新增复现显式使用假串口／假设备。固定端口用例先检测占用，不退出原服务。
- 没有把生产页面 `?demo=1` 当隔离：Dashboard 的 demo 仅 DEV 生效，生产会照常请求真实后台。

### 9.2 执行结果

| 检查 | 结果／证据 |
| --- | --- |
| 全后端 `pytest tests -q -p no:cacheprovider` | **1537 passed，2 skipped，33 subtests passed**，175.84s；`pytest.log`、`backend-results.xml`。仅现有依赖 deprecation warning |
| skip 1 | `test_empty_device_backend_lives_independently_and_commits_confirmed_exit`：8000 已被其他服务占用，保留原后台 |
| skip 2 | `test_symlink_escape_is_rejected`：当前 Windows 账户不能创建符号链接；其余路径/重解析点检查不等于该实测已通过 |
| standalone metadata | **37 passed，0 failed**；`metadata.log`。与 pytest 范围可能重叠，不相加冒充新增覆盖 |
| 后端 imports | app、experiments、ws、campaigns、CampaignStore、planner 通过；`imports.log` |
| `pip check` | 通过；`pip-check.log`。只验证当前环境依赖关系，不是漏洞审计 |
| 前端 Node/tsx | 17 文件，**128 passed，0 failed，0 skipped**；`frontend/node-tests.log` |
| 前端生产构建 | 隔离镜像运行 `npm run build -- --mode production --outDir .../build-dist` 通过，含 vue-tsc；`frontend/build.log` |
| 构建声明检查 | 原 `auto-imports.d.ts`／`components.d.ts` 均无内容 diff；`git ls-files --eol` 为 i/lf w/lf。components 的既有 stat/换行脏状态保留，未 restore/update-index |
| 前端故障复现 | 12 个真实 SFC setup + 假 API/设备/存储/可控 Promise 场景通过；不是已提交正式测试 |
| 后端新增复现 | 协议4类＋VID/PID、停止取消、Campaign根形状、NaN及1e309、无凭证控制边界均有断言／结构化输出 |
| 文档／YAML／发行 | 42文档、108本地链接/锚点；29 YAML分类；6原件hash；655发行成员、双EXE代码、92静态资源核对，见 §5/§6 |
| 目录／历史 | 142可达提交，大对象及有限secret模式；目录大小、ignored探针与本地exclude，见 §7/§8 |

### 9.3 独立浏览器实际操作

临时 harness 为 `output/project-review-20261021/browser_smoke.py`：仅 `127.0.0.1:18000`；在业务 import 前设置独立 `HEAT_DATA_DIR=.../browser-workspace`，五类设备配置全部空列表，禁止真实 serial.open，并阻止非实验编辑／Campaign测试范围的硬件 mutation。使用现有只读生产 static，没有修改产品 app。

IAB 临时标签页使用独立端口 origin，未读生产 8000 的浏览器存储；Chrome 独立会话不可用，**没有新建独立 OS 浏览器 profile**，因此不能将本轮扩大为全新 WebView profile/兼容验收。

实际通过：

- 全部8路由直接加载与刷新：`/`、`/control`、`/experiment`、`/experiment/editor`、`/experiment/batch`、`/experiment/batch/template`、`/campaigns`、`/history`。
- 中文 YAML 编辑、校验、保存；`审查 空间.yaml` 的列表、详情、编辑重新读取；下载内容与隔离磁盘文件字节相同。只保存纯 log 步骤，没有启动实验。
- 空设备、空 Campaign/历史状态；编辑器及模板从隔离目录读取。最终正常退出临时后台后，仪表盘明确显示“服务器通信中断 · 设备状态未知”，没有宣称设备已经停机。
- 检查时 console error/warn 为空；这不替代全部异常操作覆盖。

证据为 `browser-states.json`、`browser-requests.json`、`browser-editor.png`、`browser-disconnected.png`。临时后台 PID 3428 正常结束，18000 监听消失；8000 仍为原 PID 12708。

### 9.4 可复验命令

以下命令从仓库根运行，使用本机已存在的 Python3.10 环境；脚本位于 ignored 目录，报告已保留关键输入／输出，后续应将必要场景转为正式回归。

```powershell
& 'C:/Users/Administrator/miniconda3/envs/heat/python.exe' output/project-review-20261021/run_checks.py metadata
& 'C:/Users/Administrator/miniconda3/envs/heat/python.exe' output/project-review-20261021/run_checks.py imports
& 'C:/Users/Administrator/miniconda3/envs/heat/python.exe' output/project-review-20261021/run_checks.py pytest
& 'C:/Users/Administrator/miniconda3/envs/heat/python.exe' -X utf8 output/project-review-20261021/backend/reproduce_protocol_findings.py
& 'C:/Users/Administrator/miniconda3/envs/heat/python.exe' -X utf8 output/project-review-20261021/backend/reproduce_engine_cancellation.py
& 'C:/Users/Administrator/miniconda3/envs/heat/python.exe' -X utf8 output/project-review-20261021/repro_store_root_shape.py
& 'C:/Users/Administrator/miniconda3/envs/heat/python.exe' -X utf8 output/project-review-20261021/repro_api_boundaries.py
```

前端现有测试从 `frontend/` 执行 `node --import tsx --test tests/*.test.ts`；故障复现脚本也从该目录执行 `node --import tsx ../output/project-review-20261021/frontend/reproduce-findings.mjs`。镜像构建准备与命令见 `frontend/prepare_build.py` 和 `frontend/review-fragment.md`，不要直接重建原 static 后盲目还原声明。

### 9.5 明确未验证

- 真实仪器身份／固件、串口断连与短写、流量温度精度、物理停止、收起窗口时的实际运行、SOP/试剂/压力和液路安全，仍需实验室验收。
- 厂家未知协议语义、缺原件的寄存器依据，本轮不猜测补齐。
- 干净 Windows11 x64 离线安装／首次导入／重启／升级／卸载保留数据未执行；当前发行文件相同不等于这些验收通过。
- 托盘恢复、真实 WebView2 下载对话框、中文 IME、CodeMirror 光标/撤销、带数据长时间图表与实际系统关机交互未完整验证。中文文本填入不是 IME 验收。
- 本地草稿完整生命周期、存储禁用的真实浏览器策略、F1 的实际确认框／离页交互、F5 的实际导入文件选择交互尚需隔离浏览器补验；本轮没有将一次 reload 的可见文本等同于完整草稿持久化验证。
- 没有获取行覆盖率；coverage/ruff/bandit/pip_audit 未安装且未自动安装。本轮必要 tests/imports/build 已可执行，这些额外工具不被作为虚构完成项；未来如要求对应审计再单独列最小依赖。

## 10. 后续分批修复顺序与验收

须先由用户确认本报告范围，再进入修复／删除阶段；本报告不自动授权推送、历史重写或清理。继续使用获批准任务分支；若需要新分支，遵守 AGENTS 的明确批准规则。

| 批次 | 范围 | 进入下一批前的验收 |
| --- | --- | --- |
| 1 控制确认与目标一致性 | F1、F2；同区顺带处理 F6 的路径编码，变更限于必要契约 | 增加失效确认、反序选择、读失败及特殊文件名的故障回归；不新增硬件动作；128前端测试＋生产构建，隔离浏览器实交互；后端相关接口检查 |
| 2 停止与资源所有权 | B1–B5，优先 close失败和取消stop | 假设备 False/异常/超时/取消及双进程锁竞争测试；metadata、imports及受影响回归；仍保持同步驱动，无 WS 控制硬件；实际 stop 与串口由实验室确认 |
| 3 科学数据及编辑状态 | S1、S2、F3、F4、F5、F7 | 非有限/坏结构写入前拒绝且原字节不变；事务/删除重试保持；Campaign乱序、关联并发、保存导入交错及存储异常回归；不得自动“修复”现有真实数据 |
| 4 文档与协作规则 | D1–D8；修复行为对应的用户/开发/上下文文档 | 枚举/参数/命令/路由/链接检查；四种验证选择一致；YAML示例只解析；历史档案保留旧事实；docs-only不强制无关构建 |
| 5 Git 与目录治理 | G1、精确私有配置保护、清理候选逐项决策 | ignore矩阵双向通过；已跟踪文件单检；保留当前未提交源码、依赖锁和设备资料；先审大小/来源/重建/引用清单，再由用户明确批准具体删除路径 |
| 6 发行与实验室验收 | 软件修复后新发行；R1网络边界单独决策 | 新构建清单与源码/资源一致；干净离线Windows安装升级卸载及WebView/托盘验收；真实设备停机与记录签核后才宣称相应硬件能力通过 |

本轮未提出新的公共 API、YAML 类型或设备协议。上述最小修复主要保持既有契约；若选择 R1 的认证/默认监听变更、数值约束收紧或损坏文件恢复迁移，应分别记录旧客户端、特殊输入和历史数据的兼容影响。
