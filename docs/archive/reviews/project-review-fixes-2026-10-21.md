# Heat 全项目审查修复记录（2026-10-21）

本记录对应 [原审查报告](project-review-2026-10-21.md) 的第二阶段。原报告保留为历史证据；当前操作规范以现行使用、开发和测试指南为准。

## 1. 范围与基线

- 用户已明确授权修复报告问题；沿用已批准的 `codex/desktop-app`，HEAD 为 `46f01d8da46e62eb14bd3ebc5d38d53608375540`。
- 修复 14 项代码／接口问题、8 项文档／规则问题和 1 项 Git 忽略问题。各项原问题均可追溯至原审查基线，详细归属见原报告。
- 保留原有未提交桌面开发及声明文件状态；本轮未提交、推送、新建分支、改写历史或删除清理候选。
- `127.0.0.1:8000` 的已安装后台受保护；未向它发送业务或退出请求。软件测试使用临时数据与假设备，串口禁止访问的保护传递给综合测试子进程。
- 条件性风险 R1 的 Web 网络信任边界未擅自调整；真实硬件、干净 Windows 离线安装和未知厂家协议仍需单独验收。

## 2. 代码问题与验收映射

| 编号 | 最终修复 | 回归证据 |
| --- | --- | --- |
| F1 | 共用待确认操作代号；卸载、相关停止／断连、急停、连接／必要参数变化使旧确认失效，重复确认受限。生命周期事件只撤销尚未提交的操作，不发送设备停止 | `frontend/tests/reviewRegressions.test.ts`：加热、微波、引导、阀、初始化／EEPROM；离页、断网、停止与确认交错 |
| F2 | 选择请求成功后成对提交文件名和详情；加载中禁启动，启动使用选择快照，失败或过期响应不能变更启动目标 | 同上：A→B 失败、读取及 progress 反序、确认中换实验 |
| F3 | Campaign 选择使用请求代号；切换先清旧表，丢弃过期成功／失败响应及卸载后的回应 | 同上：A/B 反序、晚到失败、卸载 |
| F4 | Run／Sample 只 PATCH 用户改变的字段，避免交错更新把另一字段写回旧值 | 同上：后端反序应用两个 PATCH，两个新关联均保留 |
| F5 | 编辑器文档代号隔离 load／import／save；旧保存回应不能绑定新文档，保存期间继续编辑的内容保持 dirty | 同上：保存 A→导入 B→A 返回，下一次保存仍指向 B；旧读取及继续编辑 |
| F6 | 实验页详情、preview、progress、start/pause/resume/stop 路径统一编码文件名 | 同上：中文空格、`#`、字面 `%20`；另有真实浏览器保存／读取验证 |
| F7 | localStorage 写入捕获 quota/security 异常，显示持续未保存提示；保留当前输入，后续保存成功可清除提示 | 同上：QuotaExceededError／SecurityError，无新增设备请求 |
| B1 | 串口关闭失败不丢句柄、占用及协议引用；失败如实返回并允许明确重试。连接初始化／登记后清理失败同样保留对象，禁止再次 connect 覆盖它 | `tests/test_serial_resource_recovery.py`：close 异常、仍 open、登记失败、连接失败、设备包装传播和重试 |
| B2 | 普通引擎、引导批次、微波托管各自持有停止任务，调用者以 shield 等待；清理任务自己记录结果和释放引用，避免取消后重复清理；停止未结束不能重启 | `tests/test_review_stop_cancellation.py`：取消 stop／wait_finished、并发调用、False 后明确重试、恢复锁与日志、两种编排最终保存 |
| B3 | Modbus 响应等待 deadline 使用单调时钟 | `tests/test_serial_resource_recovery.py`：公开读取接口墙钟前跳／回拨与有限超时 |
| B4 | 每端口持有 OS 非阻塞文件锁至 release；metadata 带 owner token，旧所有者及陈旧清理不能删除新占用 | 同上：真实 spawn 双进程争抢只有一个成功、进程退出接管、token 更换、active-owner 清理保护 |
| B5 | 仅 VID/PID 的合法指纹匹配补全；仍要求唯一匹配，零个和多个匹配继续拒绝 | 同上：0／1／2 个候选 |
| S1 | 参数和表征指标递归拒绝非有限数；HTTP 400 且写入前拒绝，store 直接调用及 JSON writer 也保护，不转换合法科学文本／bool/null | `tests/test_review_storage_integrity.py`：NaN、±Infinity、±1e309、嵌套值、原文件字节不变、后续读取可用 |
| S2 | 非对象列表、空白、坏 JSON／编码、非有限历史数值、坏恢复 journal 作为存储错误返回 503；原内容保留，不当空库覆盖 | 同上：根形状、非法行、非法编码、journal 部分恢复保护、合法空列表 |

实现位置分别为 `frontend/src/views/`、相关设备组件与 `composables/pendingConfirmation.ts`；`src/utils/serial_manager.py`、`serial_binding.py`、同步协议及设备包装；`src/experiment/engine.py` 和三种持久化／编排入口；`src/campaigns/models.py`、`store.py` 与 `src/web/api/campaigns.py`。

兼容边界：没有新增公共路由、YAML 动作／等待类型或设备协议命令。无效 Campaign 数值现在返回 400，损坏的已有存储返回 503；原先已被写入的坏数据保留，由维护者检查，不能宣称自动恢复。串口 `.guard` 文件永久保留，存在本身不表示占用；加热器／蠕动泵／微波／阀须明确 disconnect 成功后再连接，注射泵后续显式 connect 会先重试旧清理，失败不得覆盖旧对象。Modbus 改为单调响应 deadline，不承诺整个串行 I/O 的严格总时限。

## 3. 文档、规则及目录治理

| 编号 | 修复及验证 |
| --- | --- |
| D1 | Trae doc-sync 改为当前 AGENTS／测试指南入口，去掉失效章节、固定旧分支和每次修改 context 的规定 |
| D2 | Trae code-review 按设备／上层／前端风险检查，移除没有依据的全局锁、注释和线程禁令；编译不代替行为测试 |
| D3 | 测试、开发及 Campaign 指南统一按变更范围验证；docs-only 不要求产品构建，硬件行为仍须实验室确认 |
| D4 | YAML 示例使用 `position: "NO"`，真实 parser/editor 参数校验通过，避免 YAML bool 误解析 |
| D5 | 双泵说明以配置／启用／连接条件判断，未更改实际设备配置 |
| D6 | context 能力清单与 29 种合法 YAML 动作、10 种等待一致；13 种注射泵 YAML 动作与手动 pause 例外明确 |
| D7 | README／桌面构建说明补 Node `^20.19.0` 或 `>=22.12.0` 下限；构建机需要 Node，安装目标机不需要 |
| D8 | 使用指南覆盖 8 条路由与真实导航；模板工具按独立路径说明，不虚构跳转按钮 |
| G1 | 忽略根运行目录，移除全局 CSV/XLSX/XLS/log 及任意层 data 屏蔽；fixture／厂家资料可见，私有 env/local config 精确保护、example 与 heat.spec 保留，去重复规则 |

本轮最终行为已同步使用、开发和 Campaign 指南；OS 串口锁、停止所有权、科学存储错误及前端失效回应处理都有对应维护说明。文档验证涵盖枚举、路由、NO 示例、Node 条件、Trae 规则、89 个本地链接及标题锚点。Git ignore 测试 4 项、32 个虚构路径断言通过；不创建或读取私密配置。缩小忽略范围没有新增可见的未跟踪 CSV/XLSX/XLS/log。

原审查报告的清理清单仍供留存决策。本轮没有整目录清理 `output/`，没有删除安装包、离线运行时、环境、历史实验或验收记录；已安装程序和用户 workspace 不在删除范围。

## 4. 软件验证

证据目录为 `output/project-review-fixes-20261021/`；前端与文档分工证据仍位于 `output/project-review-20261021/frontend/` 和 `docs-deployment/`，原始审查 baseline 不覆盖。

- Python 3.10.21（Conda heat）；Node 24.21.0；未安装新依赖。
- 综合后端：**1641 passed、2 skipped、65 subtests passed**，177.32 秒；`pytest.log`、`backend-results.xml`。含新增 104 项后端／治理测试，其中停止与存储 41 项、串口与设备 59 项、ignore 4 项。分项结果与综合结果重叠，不累加冒充覆盖。
- 两项 skip：8000 已被既有后台占用的独立桌面后台子进程用例；当前 Windows 账户无法建立符号链接的 escape 用例。均保留阻塞条件，没有停止现有后台或更改系统权限。
- metadata **37 passed、0 failed**；Web／实验／WS／Campaign／store／planner 导入及 pip check 通过。综合测试仅有既有 Starlette TestClient 弃用提示。
- 前端全部 18 个测试文件：157 passed、0 failed、0 skipped，含新增 29 项真实 SFC setup 行为回归；`fixes-all-tests.log`。
- 隔离镜像生产构建及 vue-tsc 通过；`fixes-build.log`、`fixes-build-dist/`。未覆盖原 `src/web/static`，两份生成声明无内容差异；既有 `components.d.ts` 状态保留。
- 浏览器使用 18000、单独数据根、空设备配置及串口拒绝；所有硬件写入路径额外阻断。验证 Campaign A/B 切换和 Run／Sample 重进后保留；特殊文件名 `修复#%20 空间.yaml` 保存、preview、选中、progress 读取均成功；没有执行 start。
- 临时服务已通过测试专用退出入口正常关闭，标签页已关闭。IAB 使用独立来源，未证明独立 OS 浏览器资料；确认乱序由 SFC 假 API 确定性注入，未伪装成鼠标可同时点穿真实弹框。
- Git／文件核对：`git diff --check` 通过；原基线 286 个文件无删除，业务配置 SHA-256 不变，新增忽略规则没有误忽略已跟踪文件，两份前端声明的字节哈希与基线相同（`i/lf w/lf`）。完整事实见 `workspace-facts.json`。18000 已释放，8000 后台未被操作。

浏览器证据：

![隔离 Campaign 验证页面](../../../output/project-review-fixes-20261021/browser-campaign.png)

Run／Sample 重新进入后的具体值见同目录 `browser-campaign.txt`；页面截图受视口高度限制。

![特殊文件名选择验证](../../../output/project-review-fixes-20261021/browser-experiment.png)

## 5. 分发与实机验收边界

审查修复阶段结束时，旧 `output/desktop/release` 中 0.1.1 安装包对应修复前的历史构建，该阶段没有重打包或安装。后续 0.1.2 构建见第 6 节。源码检查通过不代表旧安装包已经包含修复；修复版分发须重新构建并核对清单，按 [桌面说明](../../desktop_app.md) 做安装／升级／卸载验收。

USB／串口实际故障、设备停止与断连、物理输出、托盘行为、中文 IME、下载及 WebView 资料持久化和 Windows 11 x64 无 Python／Node／WebView2 的离线安装仍需实验室或干净机验证。软件测试不能替代现场安全、设备身份及科学有效性确认。

## 6. 后续集中构建 0.1.2（2026-10-21）

用户已授权由 Codex 判断安装包构建时机：积累一批稳定修复后集中生成一个新版本，约定已写入 `context/PROJECT_CONTEXT.md` 第 6.1 节。本次依据已完成的软件验证，生成 `output/desktop/release/Heat-Setup-0.1.2-x64.exe`，将本报告的代码修复纳入桌面版；0.1.0／0.1.1 旧安装器原样保留。

- 真实前端生产构建与 vue-tsc 通过，重新生成 `src/web/static`；不再只使用修复阶段的镜像构建。
- 45 项固定构建／运行依赖匹配，发行脚本及离线运行时校验通过；metadata 37 项、打包边界 23 项和后端导入检查通过。
- 655 项发行文件集合、大小及 SHA-256 一致；两个 EXE 各 70 个源码模块及入口逐一匹配当前源码，92 项前端资源集合与哈希一致，无实验室配置或历史数据目录。
- 构建前 134 项文件基线中，仅 `src/desktop/common.py` 精确版本号从 0.1.1 改为 0.1.2；业务配置、两份声明、前端源码及两个旧安装器哈希不变。安装脚本默认版本同步为 0.1.2。
- 安装器 254642601 字节，SHA-256：`a9a97e4af8a6463eff0511282be1ea99fd6c87d97aa8e81da39b411cbc048ead`。证据位于 `output/desktop/release-0.1.2-evidence/`，包括构建、软件检查、`release-verification.json` 和文件基线；发行清单为 `output/desktop/release-manifest.json`。

此步骤未运行或覆盖安装桌面应用、未操作既有后台或硬件，也未提交、推送或清理文件。升级及待完成的干净机／实机验收按[桌面说明](../../desktop_app.md)执行。
