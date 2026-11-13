# Heat 全项目文档资料审查与更新（2026-11-05）

## 1. 范围与结论

沿用已批准分支 `codex/accessories-register`，基线提交 `bfd9682fedcfa21faeb86f9e9cbbeacba5d7afc5`。审查开始时已有本任务的配件登记、出厂报告和Henyon说明书归档改动，全部保留。覆盖既有 **52份Markdown**，另核对 **18份资料文件**（7 PDF、3 DOC、4 PNG、1 HTML草案、3 EXE副本）及目录`.gitattributes`；新增本报告后为53份Markdown。

本次按文档用途核对当前事实、来源、引用和历史边界，并对差异关联代码/配置或原件。未修改厂家原件、历史运行记录、控制阈值、动作顺序、驱动、串口配置或API字段；审查交付阶段没有提交、推送、发布、安装、重启服务或操作硬件。软件检查与资料完整性检查不等于全装置实机验收，也不是对所有厂家条款逐条认证。

当前主要入口：[用户指南](user_guide.md)、[开发指南](developer_guide.md)、[YAML规范](experiment_yaml_spec.md)、[设备原件索引](device_materials/README.md)、[连接件与配件登记](device_materials/accessories/README.md)。

## 2. 已修正的问题与依据

| 问题 | 修正与依据 |
| --- | --- |
| README仍称45℃、设备和路由清单不全 | 按`src/experiment/guided.py`及`frontend/src/router/index.ts`写明当前新流程≤55℃、双注射泵、阀、转盘与模板路由；旧计划保留原参数 |
| 详细进度写死45℃、±3℃/30秒、额外10分钟 | `src/experiment/progress.py`读取本步骤温度、容差、时长与总超时；缺少目标时不编造数字；不保证双泵同时物理运动 |
| 简短步骤标题仍写死55℃/稳定时长 | `GuidedBatch.snapshot()`读取匹配当前步骤的等待参数；无活动步骤使用无数字说明；脱气时长也取步骤，不从新请求反推旧步骤 |
| 模板页称阀/转盘/跨组调度尚未接入 | 只改`TemplateBatchPage.vue`两处说明，明确模板工具负责单组生成/校验/另存，完整固定装置执行使用引导式 |
| 早期水测被写成全项目当前拓扑 | 工程参考、MVP手册及清单限定CH4进水/CH3出水的历史范围；当前引导式为双注射泵进料、CH3清洗进液、CH4排液、NO产物/NC废液；不改历史YAML |
| 旧装液量与新报告容易混用 | 旧约2/3液位保留为早期方案；出厂报告3–5 mL为报告条件，二者须结合容器和现场SOP核对，不自动替换 |
| YAML流量示例把读回管型13当待写值 | 示例改为当前pump1配置的11，并解释设备级11→13映射；新软管登记不修改配置/标定 |
| 源码、安装版、旧任务状态混杂 | 更新上下文日期及小节编号，日常开发改为任务分支规则；桌面0.1.5、Python包0.1.0、前端包0.0.0分别说明；历史0.1.4/0.1.5记录不覆盖 |
| 资料索引转盘超时仍为1秒 | 按当前配置改为2秒，注明模型默认1秒；已有有限定位/回零记录与完整待验项分别说明 |
| 宇电协议版次被列为未登记 | 第1页原页和提取文字均为V9.3，已登记；实物型号及固件对应仍待核验 |
| 新旧阀资料关系与USB编号易误读 | 用户指南、YAML及资料索引明确Henyon为后续更换，Bürkert资料保留；USB指纹不等于仪器出厂编号 |
| 故障排查遗漏工作区/恢复锁且清锁表述过强 | 按runtime_paths、serial_manager和恢复机制修订；区分源码静态刷新与后端/安装版更新，补6秒控制与15秒监控边界 |
| 长文专题追加及引用位置不清 | 补局部导航和主来源链接，修正“下文转盘”等方向引用；保留章节主体和既有历史证据 |
| 验证规则末尾要求所有任务构建前端 | 最终清单与AGENTS验证矩阵一致；heat-git补必要依赖缺失确认规则 |

## 3. Markdown逐文件覆盖清单

“已核对”表示未发现需要本次修订的事实差异；“已修订”为本轮审查改动；“历史保留”为按当时范围核对并保留；“待现场确认”不代表文件未审查。硬件文件的核对不自动改变验收状态。所有下列文件均纳入本地链接检查。

| 文件（仓库相对路径） | 状态 | 核对内容 / 依据 |
| --- | --- | --- |
| [README.md](../README.md) | 已修订 | 路由、设备能力、55℃生成流程；依据 router/index.ts、guided.py 与设备配置，补资料导航。 |
| [AGENTS.md](../AGENTS.md) | 已核对 | 分支授权、同步驱动、必要依赖确认和验证矩阵；作为规则主来源保留。 |
| [context/PROJECT_CONTEXT.md](../context/PROJECT_CONTEXT.md) | 已修订 | 更新日期、历史小节编号、源码/发行口径及后续阀门边界；依据配置、专题验收及包版本。 |
| [docs/water_test_microwave_20261019.md](water_test_microwave_20261019.md) | 历史保留 | 历史保温提前退出证据及未确认原因保留，不用新提示或厂家报告覆盖运行事实。 |
| [docs/water_test_acceptance_20261016.md](water_test_acceptance_20261016.md) | 历史保留 | 历史水测后软件审查；原件差异、测试数量和现场证据缺口按当时记录保留。 |
| [docs/user_guide.md](user_guide.md) | 已修订 | 核对8个页面入口、启停及恢复语义；补导航、动态提示、新旧阀资料关系与源码/安装边界。 |
| [docs/turntable_integration.md](turntable_integration.md) | 已核对；待现场确认 | 对照配置2秒超时、12瓶及协议查询间隔；保留10-24/10-28有限核验与10-29待验收范围。 |
| [docs/troubleshooting.md](troubleshooting.md) | 已修订 | 核对 serial_manager.py、恢复锁和采样机制；补工作区、存储错误及6秒/15秒边界，纠正强制清锁及重启说明。 |
| [docs/testing_and_merge_flow.md](testing_and_merge_flow.md) | 已修订 | 与 AGENTS.md 验证矩阵、任务分支及双远程授权核对；最终清单明确前端构建的适用范围。 |
| [docs/system_engineering_design.md](system_engineering_design.md) | 已修订 | 对照早期水测试 YAML、当前 guided.py 与出厂报告；标明拓扑、装液量及阀温度边界，不登记泵软管长度。 |
| [docs/syringe_pump_integration.md](syringe_pump_integration.md) | 已核对 | 对照 syringe_pump 驱动/协议与配置；OEM固定序号、两台RS232、理论排量边界保留。 |
| [docs/syringe_pump_acceptance.md](syringe_pump_acceptance.md) | 已核对；待现场确认 | 保留2026-10-01初始化故障/用户反馈与尚未完成的验收清单；不把拆管后恢复写成完整验收。 |
| [docs/mvp_system_acceptance_checklist.md](mvp_system_acceptance_checklist.md) | 已修订；待现场确认 | 保留空白Gate与2026-10-01观察；增加适用范围，原2 m方案不移入新配件登记。 |
| [docs/mvp_device_ready_runbook.md](mvp_device_ready_runbook.md) | 已修订 | 对照三个活动水测 YAML、Gate清单及当前引导流程；限定早期拓扑，不要求补登泵软管长度。 |
| [docs/microwave_smoke_test.md](microwave_smoke_test.md) | 已核对；待现场确认 | 对照微波控制及监督等待、既有水测记录；±5℃/15秒和五段覆盖为待现场复验，不补写通过。 |
| [docs/experiment_yaml_spec.md](experiment_yaml_spec.md) | 已修订 | 核对 parser.ACTION_MAP/WAIT_MAP 与动作约束；修正 pump1 示例写入管型为11及“下文”引用；示例离线解析。 |
| [docs/daily_development.md](daily_development.md) | 已修订 | 核对 run_server.py、runtime_paths.py、桌面工作区；历史分支不再作为固定当前入口。 |
| [docs/campaign_workflow.md](campaign_workflow.md) | 已修订 | 核对 store.py、planner.py、Campaign API与模板路由；明确数据根目录及模板工具名称。 |
| [docs/desktop_app.md](desktop_app.md) | 已修订 | 核对桌面 common.py、构建脚本及0.1.5发行记录；分别说明源码、安装包和包版本。 |
| [docs/developer_guide.md](developer_guide.md) | 已修订 | 核对协议/驱动/路由、只读快照、模板与引导批次职责；补遗漏模块及参数来源。 |
| [docs/archive/reviews/system-review-2026-10-12.md](archive/reviews/system-review-2026-10-12.md) | 历史保留 | 与其10-13修复说明核对；原7项发现及测试数字保留。 |
| [docs/archive/reviews/project-review-fixes-2026-10-21.md](archive/reviews/project-review-fixes-2026-10-21.md) | 历史保留 | 阶段二修复及0.1.2历史构建范围保留。 |
| [docs/archive/reviews/project-review-2026-10-26.md](archive/reviews/project-review-2026-10-26.md) | 历史保留 | 原审查/修复与后续0.1.5发布引用一致；测试数量仅属当时。 |
| [docs/archive/reviews/project-review-2026-10-21.md](archive/reviews/project-review-2026-10-21.md) | 历史保留 | 阶段一审查和证据保留；后续修复见同目录fixes记录。 |
| [docs/archive/reviews/desktop-release-0.1.5-2026-10-26.md](archive/reviews/desktop-release-0.1.5-2026-10-26.md) | 历史保留 | 保留发行、覆盖安装、空设备验证及原资料哈希记录，不推断后续源码已安装。 |
| [docs/archive/reviews/desktop-exit-followup-2026-10-21.md](archive/reviews/desktop-exit-followup-2026-10-21.md) | 历史保留 | 退出偶发问题、正常退出观察及0.1.3范围保留，不宣称证实根因。 |
| [docs/archive/README.md](archive/README.md) | 已修订 | 历史资料总边界明确，增加本次审查入口。 |
| [docs/archive/learning_path.md](archive/learning_path.md) | 历史保留 | 历史学习路线保留；依赖安装与运行以活动README和开发指南为准。 |
| [.codex/skills/heat-git/SKILL.md](../.codex/skills/heat-git/SKILL.md) | 已修订 | 与AGENTS.md核对提交/推送、分支和归档规则；补必要测试依赖确认规则，本任务不执行/git。 |
| [docs/archive/code_review.md](archive/code_review.md) | 历史保留 | 2026-05-15审查已有历史提示；原评价、目录和测试记录保留。 |
| [docs/archive/experiments/README.md](archive/experiments/README.md) | 历史保留 | 归档配方不得直接作为当前已放行实验；活动入口只列experiments目录，历史示例保留。 |
| [.trae/skills/word-reader/SKILL.md](../.trae/skills/word-reader/SKILL.md) | 已核对 | 通用Word提取示例与依赖说明保留；本次DOC采用只读复合文档提取，未启动Word或宏。 |
| [.trae/skills/dll-analyzer/SKILL.md](../.trae/skills/dll-analyzer/SKILL.md) | 已核对 | 通用DLL诊断示例保留；并非Heat运行依赖，不执行附带EXE或加载厂家组件。 |
| [.trae/skills/pdf-reader/SKILL.md](../.trae/skills/pdf-reader/SKILL.md) | 已核对 | 通用PDF读取示例保留；本次用已提供运行时pypdf及Poppler，不把扫描件空文本当内容缺失。 |
| [docs/device_materials/microwave/微波反应仪通信协议.md](device_materials/microwave/%E5%BE%AE%E6%B3%A2%E5%8F%8D%E5%BA%94%E4%BB%AA%E9%80%9A%E4%BF%A1%E5%8D%8F%E8%AE%AE.md) | 已核对 | 核对转换稿性质与关键地址入口；原XLSX缺失，保留原转换表，不由代码反造厂家依据。 |
| [docs/device_materials/peristaltic_pump/多通道蠕动泵MODBUS通信协议.md](device_materials/peristaltic_pump/%E5%A4%9A%E9%80%9A%E9%81%93%E8%A0%95%E5%8A%A8%E6%B3%B5MODBUS%E9%80%9A%E4%BF%A1%E5%8D%8F%E8%AE%AE.md) | 已核对 | 对照原DOC和既有差异记录；19200/n003与原件不同，正文保留，在索引显式说明。 |
| [.trae/skills/convert-to-md/SKILL.md](../.trae/skills/convert-to-md/SKILL.md) | 已核对 | 通用转换规则保留，非厂家资料权威来源；本次不覆盖原件或批量生成转换稿。 |
| [.trae/skills/find-skill/SKILL.md](../.trae/skills/find-skill/SKILL.md) | 已核对 | 通用技能检索/安装说明保留；本次无安装或更新技能需求，外部排行数值不作为本次核验事实。 |
| [docs/archive/dev_tasks/microwave/06_docs_and_smoke_test.md](archive/dev_tasks/microwave/06_docs_and_smoke_test.md) | 历史保留 | 历史微波接入任务；检查归档声明、输入/完成记录与引用，旧控制闸、阶段性范围及测试数字保留；当前操作以活动指南为准。 |
| [docs/archive/dev_tasks/microwave/05_experiment_yaml_automation.md](archive/dev_tasks/microwave/05_experiment_yaml_automation.md) | 历史保留 | 历史微波接入任务；检查归档声明、输入/完成记录与引用，旧控制闸、阶段性范围及测试数字保留；当前操作以活动指南为准。 |
| [docs/archive/dev_tasks/microwave/04_frontend_control_dashboard.md](archive/dev_tasks/microwave/04_frontend_control_dashboard.md) | 历史保留 | 历史微波接入任务；检查归档声明、输入/完成记录与引用，旧控制闸、阶段性范围及测试数字保留；当前操作以活动指南为准。 |
| [docs/archive/dev_tasks/microwave/03_backend_api_ws.md](archive/dev_tasks/microwave/03_backend_api_ws.md) | 历史保留 | 历史微波接入任务；检查归档声明、输入/完成记录与引用，旧控制闸、阶段性范围及测试数字保留；当前操作以活动指南为准。 |
| [docs/archive/dev_tasks/microwave/02_backend_driver.md](archive/dev_tasks/microwave/02_backend_driver.md) | 历史保留 | 历史微波接入任务；检查归档声明、输入/完成记录与引用，旧控制闸、阶段性范围及测试数字保留；当前操作以活动指南为准。 |
| [docs/archive/dev_tasks/microwave/01_protocol_register_map.md](archive/dev_tasks/microwave/01_protocol_register_map.md) | 历史保留 | 历史微波接入任务；检查归档声明、输入/完成记录与引用，旧控制闸、阶段性范围及测试数字保留；当前操作以活动指南为准。 |
| [docs/archive/dev_tasks/microwave/00_index.md](archive/dev_tasks/microwave/00_index.md) | 历史保留 | 历史微波接入任务；检查归档声明、输入/完成记录与引用，旧控制闸、阶段性范围及测试数字保留；当前操作以活动指南为准。 |
| [.trae/skills/code-review/SKILL.md](../.trae/skills/code-review/SKILL.md) | 已核对 | 同步驱动、上层桥接、实机证据和缺依赖规则一致。 |
| [.trae/skills/doc-sync/SKILL.md](../.trae/skills/doc-sync/SKILL.md) | 已核对 | 文档映射与授权边界一致；本次仅审查其文本，未据此提交或推送。 |
| [docs/device_materials/README.md](device_materials/README.md) | 已修订 | 全部厂家原件哈希与型号/来源索引；修正转盘超时、登记宇电V9.3，区分USB与仪器编号，补新原件和协议差异入口。 |
| [.trae/rules/heat.md](../.trae/rules/heat.md) | 已核对 | 兼容入口仍指向AGENTS.md与项目上下文，无第二套硬件/提交规则。 |
| [frontend/README.md](../frontend/README.md) | 已核对 | 前端指南入口存在；构建契约以 package.json、vite.config.ts 和开发指南为准。 |
| [docs/device_materials/accessories/README.md](device_materials/accessories/README.md) | 已核对 | 逐条核对用户要求及截图：9个有效编号；ACC-008排除；ACC-006长度不登记；材料、单位、数量层级与适配未知保持。 |
| [docs/device_materials/microwave/microwave_bottle_fittings.md](device_materials/microwave/microwave_bottle_fittings.md) | 已核对；待现场确认 | 复看瓶体图及配件图；M28×2/M44×1.5不是管接头螺纹，M6候选与φ2.6清单不得合并推定。 |

## 4. 原件与资料文件核对

14份已有哈希登记的非图片资料均与索引一致；4份配件/瓶体PNG在本表固定哈希。18份资料文件和`.gitattributes`与审查开始的基线完全一致。新归档DOC及Henyon PDF另与用户提供的`D:/share`原文件复核，SHA-256一致。哈希仅证明副本身份，不证明厂家签章、适用固件或现场安装状态。

7份PDF均可解析且未加密；所有页尝试文字提取，扫描页没有文本不视为缺页。渲染查看各PDF封面，并核对Henyon第1–3页、Bürkert第3–4页及本任务已有关键原图。读取时有一次非零起始xref索引提示，解析器在内存纠正后完成读取，原件未保存或修复。3份DOC以只读复合文档正文提取检查（报告2058、微波说明书10108、泵协议4954字符），不运行Word/宏；不宣称全部版面或签章已经逐页验证。

| 文件（相对device_materials） | 可读性 / 用途 | SHA-256 |
| --- | --- | --- |
| [20260624-出厂检验报告(4).doc](device_materials/microwave/20260624-%E5%87%BA%E5%8E%82%E6%A3%80%E9%AA%8C%E6%8A%A5%E5%91%8A%284%29.doc) | DOC，复合文档及正文可读取；原图结论以查看原图为准 | `FE29B842D12871457402B788AE5D829FBFF1EF4D5970A2680DE9B08B2EE3543D` |
| [3758240252Henyon两位三通电磁阀使用说明书.pdf](device_materials/valve/3758240252Henyon%E4%B8%A4%E4%BD%8D%E4%B8%89%E9%80%9A%E7%94%B5%E7%A3%81%E9%98%80%E4%BD%BF%E7%94%A8%E8%AF%B4%E6%98%8E%E4%B9%A6.pdf) | PDF，3页；可解析/封面渲染，第3页空白 | `CAF67B04023629B4AA76ADF782AD96AA06E411A9C9C53A31079034A47B0B0E31` |
| [accessories/images/ACC-002-supplier.png](device_materials/accessories/images/ACC-002-supplier.png) | PNG，可解码，1176×2400 | `BA6719601736CB61ABBA48DF79633D9CF279592E76A4B574EE5E5294FF03FFD5` |
| [accessories/images/microwave-accessories-list-20261105.png](device_materials/microwave/images/microwave-accessories-list-20261105.png) | PNG，可解码，484×98 | `27999BBEBFA0FF949C7A3C3CC96379787FA7EE36ADC728440C0A74B747EFBE43` |
| [accessories/images/microwave-ptfe-bottle-section.png](device_materials/microwave/images/microwave-ptfe-bottle-section.png) | PNG，可解码，707×519 | `7FC0CD061FC2756D664F5105C60D436313118F2003931F0E95A8D90E923EB767` |
| [accessories/images/microwave-ptfe-bottle-volume.png](device_materials/microwave/images/microwave-ptfe-bottle-volume.png) | PNG，可解码，798×448 | `043F5AD3D75B4293B9721241D524AF27E7300B6A89555998C87784AEF6BB1C97` |
| [CL-01A运动控制器说明书.pdf](device_materials/collection/CL-01A%E8%BF%90%E5%8A%A8%E6%8E%A7%E5%88%B6%E5%99%A8%E8%AF%B4%E6%98%8E%E4%B9%A6.pdf) | PDF，18页；可解析/封面渲染 | `2355866BCFA51D4D02117604C3DD93F831B4A01F8AA185DD76EE7C8A8B05D1FB` |
| [designs/turntable/自动换瓶托盘与支架设计草案.html](device_materials/collection/archive/designs/%E8%87%AA%E5%8A%A8%E6%8D%A2%E7%93%B6%E6%89%98%E7%9B%98%E4%B8%8E%E6%94%AF%E6%9E%B6%E8%AE%BE%E8%AE%A1%E8%8D%89%E6%A1%88.html) | 设计草案，8瓶示例不替代当前12瓶配置或加工图 | `7E6DCAD01DB21454B25D7339EECD27E99B535E510E3AE0D0ED0635B7E2862979` |
| [DS0127-Standard-CN-ZH0127(1).pdf](device_materials/valve/archive/DS0127-Standard-CN-ZH0127%281%29.pdf) | PDF，20页；可解析/封面渲染 | `E78FC05FCD4CC6BF563E8566E912B0974A1C5098EC10A345A2356F2D03DED29B` |
| [LabSmart说明书（中文）.pdf](device_materials/peristaltic_pump/LabSmart%E8%AF%B4%E6%98%8E%E4%B9%A6%EF%BC%88%E4%B8%AD%E6%96%87%EF%BC%89.pdf) | PDF，32页；可解析/封面渲染 | `4F49B79858DBD57F1935AD0DFDB85ED59666B91AEBC53266261CC6CFD9CFC1C7` |
| [MKM-AH1E环形聚焦单模微波化学合成仪-说明书.doc](device_materials/microwave/MKM-AH1E%E7%8E%AF%E5%BD%A2%E8%81%9A%E7%84%A6%E5%8D%95%E6%A8%A1%E5%BE%AE%E6%B3%A2%E5%8C%96%E5%AD%A6%E5%90%88%E6%88%90%E4%BB%AA-%E8%AF%B4%E6%98%8E%E4%B9%A6.doc) | DOC，复合文档及正文可读取；原图结论以查看原图为准 | `EF73B9E390CDDDA16263EEF0F68DB8B381F6C88F913AC4CD18B871E9BE6C97A8` |
| [MSP1-CX用户手册 2025.6.4.pdf](device_materials/syringe_pump/MSP1-CX%E7%94%A8%E6%88%B7%E6%89%8B%E5%86%8C%202025.6.4.pdf) | PDF，42页；可解析/封面渲染 | `6BB9FE4189CD398EBBEF695BC54360BE96DA1A9BE599751EB33EDA94B46FAA5A` |
| [tools/turntable/1_340芯片+USB转串口线+USB转RS232+USB9针串口+340芯片USB转串口线(2).EXE.exe](device_materials/collection/archive/tools/1_340%E8%8A%AF%E7%89%87%2BUSB%E8%BD%AC%E4%B8%B2%E5%8F%A3%E7%BA%BF%2BUSB%E8%BD%ACRS232%2BUSB9%E9%92%88%E4%B8%B2%E5%8F%A3%2B340%E8%8A%AF%E7%89%87USB%E8%BD%AC%E4%B8%B2%E5%8F%A3%E7%BA%BF%282%29.EXE.exe) | EXE，副本哈希与MZ头核对；未运行/安装，版本签名未验 | `5C79A8C123D3FA03274FDCCC8FAD722AAF3B703DF35C39B4B42F0B5BFBB26DFD` |
| [tools/turntable/CL-01A(串口控制_翼宣).exe](device_materials/collection/archive/tools/CL-01A%28%E4%B8%B2%E5%8F%A3%E6%8E%A7%E5%88%B6_%E7%BF%BC%E5%AE%A3%29.exe) | EXE，副本哈希与MZ头核对；未运行/安装，版本签名未验 | `BECAE88567D7237E16733C593ECC587FDA8196B13C8119210A037D56D7638410` |
| [tools/turntable/CL-01A程序下载助手(翼宣).exe](device_materials/collection/archive/tools/CL-01A%E7%A8%8B%E5%BA%8F%E4%B8%8B%E8%BD%BD%E5%8A%A9%E6%89%8B%28%E7%BF%BC%E5%AE%A3%29.exe) | EXE，副本哈希与MZ头核对；未运行/安装，版本签名未验 | `73AD2278CB024C83E2E85375AB91C1912A493D9972FDDB34F6BB78FF6A351210` |
| [多通道蠕动泵MODBUS通信协议.doc](device_materials/peristaltic_pump/%E5%A4%9A%E9%80%9A%E9%81%93%E8%A0%95%E5%8A%A8%E6%B3%B5MODBUS%E9%80%9A%E4%BF%A1%E5%8D%8F%E8%AE%AE.doc) | DOC，复合文档及正文可读取；原图结论以查看原图为准 | `997CEF5A096DBFA839B3FC68DFD47E300F9D4DE85B2FF7306CF408E67BE89541` |
| [宇电单回路测量控制仪表通讯协议说明(1).pdf](device_materials/heaters/%E5%AE%87%E7%94%B5%E5%8D%95%E5%9B%9E%E8%B7%AF%E6%B5%8B%E9%87%8F%E6%8E%A7%E5%88%B6%E4%BB%AA%E8%A1%A8%E9%80%9A%E8%AE%AF%E5%8D%8F%E8%AE%AE%E8%AF%B4%E6%98%8E%281%29.pdf) | PDF，13页；可解析/封面渲染 | `3C2141652DF4980F3F0042333C9561E5F714AD0F841500C945948594A6573172` |
| [申辰多通道独立控制 LabSmart.pdf](device_materials/peristaltic_pump/%E7%94%B3%E8%BE%B0%E5%A4%9A%E9%80%9A%E9%81%93%E7%8B%AC%E7%AB%8B%E6%8E%A7%E5%88%B6%20LabSmart.pdf) | PDF，2页；可解析/封面渲染 | `103143DAFB04FD1DCD3F866AD8704484042ECF08D0AF05808B16A80E1F2FDA5F` |

图表结论：瓶体M28×2、M44×1.5为瓶体端部螺纹，不是顶部/底部接头规格；图中未给管路接口密封座及瓶体温度—压力额定曲线。商品M6/2.0 mm候选与另一截图φ2.6接头分别登记，不能认定互配。原始三行配件截图保留作来源，第一项继续排除，不恢复ACC-008。用户提供的1 m PTFE管、1个ETFE锁紧锥、1个PEEK接头作为本次需求登记，不推定每台用量；截图3个/3套不是已购或待购数量。蠕动泵氟橡胶软管长度不登记。

## 5. 验证结果

| 检查 | 结果与限制 |
| --- | --- |
| `python -m pytest tests/test_guided_progress.py tests/test_guided_preparation.py tests/test_microwave_cooling.py -q -o cache_dir=output/documentation-review-20261105/pytest-cache` | 111 passed，18 subtests passed；包含新旧45/55℃、无目标、容差/时长/总超时、步骤/观测不变、无设备调用及简短标题回归。仅既有Starlette/httpx弃用提示 |
| `python tests/test_metadata.py` | 37 passed，0 failed；脚本使用既有隔离机制 |
| Web app/experiments/ws及guided/progress导入 | 通过；已有win32file缺失提示只关闭强制释放功能，不影响本次只读展示验证；未安装额外依赖 |
| `node --import tsx --test tests/batch.test.ts`（frontend） | 6 passed，0 failed；没有为静态文案添加镜像测试 |
| `npm run build -- --mode production --outDir ../output/documentation-review-20261105/frontend-build`（frontend） | TypeScript及生产构建通过，输出隔离；107份原有静态资源/生成声明文件哈希未改变。构建有插件耗时提示，无编译失败 |
| YAML文档示例 | 24个YAML代码块可解析；其中19个完整流程或补steps外壳后的动作片段经当前parser及配置校验通过，另5个配置/错误示例片段仅检查YAML语法，未冒充可运行完整流程；没有执行任何步骤 |
| 本地链接、图片及标题锚点 | 使用Markdown解析器检查53份文件中的实际Markdown链接（含引用式链接/图片）及目标标题，忽略代码围栏中的示例；数量与结果见下方最终记录。外部网页可用性、代码中的历史路径和本机忽略目录不计作已验证链接 |
| 原件哈希 | 18份资料及`.gitattributes`均与审查基线一致；索引中原有14个资料哈希全部匹配 |
| 差异检查 | `git diff --check`及新增Markdown尾空白检查；无整篇改写或原件变更，配置、历史YAML、驱动及在用静态页面不修改 |

本机复核脚本、基线、PDF文本/页面图、构建日志和检查JSON在忽略目录 `output/documentation-review-20261105/`。这些是复核辅助产物，不作为仓库运行依赖；本报告保存可审查的范围和结论。

## 6. 剩余资料缺口与现场事项

| 项目 | 缺口 / 后续确认 |
| --- | --- |
| 微波协议 | 原始`26.6.10-单模modbus地址.xlsx`缺失；模式位、有效方案、固件与字序等原有问题仍须厂家/实机证据，转换稿不能补造原件 |
| 继电器与加热器 | 缺中盛《数字量输入输出系列使用手册（RS485/RS232版）》V3.0原件及具体模块接线资料；两台宇电完整型号、操作接线手册及固件对应待补 |
| 蠕动泵 | 原DOC与转换稿19200/n003差异待厂家/固件确认；新氟橡胶规格不等于已确认的HMI管型，也不证明流量标定；不要求补登记长度 |
| 既有Bürkert与55℃流程 | 0127系列常规介质上限50℃，扩展55℃仅部分条件适用；须按实物订货号、DN、密封和安装方式核对。软件55℃门槛不是阀额定许可 |
| 后续Henyon | HY100T3MP12-62说明书为拟更换资料；实物铭牌、安装完成、电源/继电器负载、通断关系及密封座尚未现场确认。PP/PVDF接头材质未定，整阀150℃不代表接头许可 |
| 瓶体和接头 | 需厂家完整接口图、螺距/公差、有效旋合深度、密封结构和额定工况；M6候选、1/4-28接头、φ2.6清单不混为已适配套件 |
| 配件数量 | ACC-001/002/007数量及安装位置、ACC-009/010截图数量含义和缺失单位/标准、各项已有/待购数量待用户/厂家确认；不补猜 |
| 实机验收 | 瓶体装液量/常压泄放、材料与介质相容性、实际输液量、55℃切阀、微波运行方案、完整批次/5–12瓶对齐、暂停/停止/失联均按专项记录继续验收；既有有限测试不扩大结论 |
| 转盘与发行 | 控制器原件已有，机械本体、电机/驱动器规格及正式加工图待补；桌面干净机和真实装置完整验收仍未完成。源码与现场安装版本分开核对 |

## 7. 超出展示修订范围的跟进

已有证据表明整轮采样等待慢设备，可能超过前端6秒控制有效期；只读监控为15秒。此次只补故障定位说明，不调整采样架构或超时。若实际复发，先记录全设备连接时的逐设备读取耗时、推送间隔、运行程序路径和启动时间，再作为独立程序修复评估。

微波提前退出、转盘偶发通信问题及厂家协议差异沿用各专题的待确认结论；本次未通过操作硬件复现，不把新增文案、软件测试或资料归档写成实机故障已解决。没有发现需要在本次展示改动中扩展API或控制逻辑的理由。

## 8. 最终检查记录

53份Markdown共290处本地链接/图片引用核对通过，目标文件和Markdown标题锚点无失效项。18份资料文件及目录属性文件哈希未变；在用静态资源与前端生成声明文件共107份哈希未变。差异检查通过；审查交付时新增资料与报告为未提交文件，位于`codex/accessories-register`。用户随后以`/git`授权本地提交；具体提交以Git记录为准，推送仍须另行明确确认。
