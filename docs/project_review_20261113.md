# Heat 项目审查与资料整理（2026-11-13）

实施分支：`codex/project-review-20261113`。审查阶段修改工作区并进行离线软件验证；2026-11-13向用户说明现场验收未完成及合并规则后，用户再次明确授权“提交、推送和合并”，本轮按该明确授权进入Git收尾。现场验收项不据此关闭；未发布、重启服务或操作硬件。资料入口见[设备资料索引](device_materials/README.md)。

## 审查范围与结果

| 范围 | 本轮检查与结果 | 验证边界 |
| --- | --- | --- |
| 设备与协议 | 对照现有资料检查同步驱动、返回值、串口管理及异常路径；中盛手册确认通道控制含五种工作模式，修复未经模式确认直接写0/1的问题 | 模块型号已由用户确认；固件与现场接线仍待核对；未对全部协议逐寄存器签核 |
| 实验执行 | 检查预检、取消、暂停、清理和恢复保护；覆盖四圈双轴接样、YAML动作及双轴失败；补齐继电器模式读期间的停止检查 | 同步读取不可强制中断，真实停止延迟与运动安全须现场确认 |
| 数据完整性 | 检查历史、批次、样品CSV、快照、图表与恢复记录；修复历史删除绕过恢复保护、坏摘要缓存被采信的问题 | 软件临时目录验证，不迁移或删除真实实验记录 |
| 前端与桌面 | 回归状态、请求竞态、迟到响应、进度、错误、历史、退出及目录隔离；修复过期测试装配和接口断言 | 本轮未修改前端生产逻辑；构建通过不等于完整人工UI验收 |
| Campaign | 回归持久化、部分失败、恢复与旧记录兼容，保留人工决策边界 | 未启用自动参数注入或硬件执行 |
| 文档与资料 | 补2份官网原件，归档5份唯一历史资料；维护当前索引、历史事实来源和缺口，检查本地链接与哈希 | 保留原件和历史验收，未把历史助手推断升级为现场确认 |

本轮为重点路径审查与软件回归，不宣称所有代码无缺陷或全部仪器协议已完成实机适配。

## 已修复问题与复现

1. **继电器控制模式未确认。** 中盛V3.0第15页说明相同控制寄存器在不同模式下含义不同。`RelayValveDevice.set_energized`现先读`0x0096`，只接受普通模式`[0]`；失败清除可信状态并拒绝写入，不修改模式、不重发写命令。设备管理层在读模式前后检查停止代次，避免读取期间已取消的切换继续发出。回归覆盖非普通/未知模式和模式读取期间停止。新增可选关键字回调`before_write`仅为内部接口，API与YAML格式不变。
2. **总历史删除缺少恢复保护。** 单条删除现在检查引导式及微波/YAML恢复锁；清空全部补充微波/YAML恢复锁，保留既有批次恢复保护。回归验证待恢复时返回冲突且不删除。未改变Campaign记录的独立存储语义。
3. **摘要缓存结构损坏。** 即使源文件身份相同，也必须确认缓存摘要为对象、run_id匹配、metadata为对象，否则从原日志重建。回归覆盖4种坏缓存，不改写原日志。

另修复测试本身与当前实现不一致之处：冷却等待用例温度改为高于当前100°C门槛；前端测试补齐纯函数模块和路由装配，按当前batch_id摘要接口验证。未以修改生产行为迎合旧断言。

## 软件验证

全部后端测试排除真实硬件脚本`tests/test_hardware.py`，测试数据使用各用例隔离目录；构建输出至忽略目录`output/review-20261113/frontend-dist`。未向正在运行的服务发送控制请求。

| 检查 | 结果 |
| --- | --- |
| 初始后端基线（默认base Python） | 2258通过、7失败、1跳过、65子测试；6项由缺少uvicorn/Pillow导致，1项为过期冷却等待断言 |
| 环境核对 | 改用已有`C:/Users/Administrator/miniconda3/envs/heat/python.exe`，未安装依赖；桌面相关48项通过 |
| 新增缺陷回归 | 修复前失败、修复后通过，复现记录见本地`output/review-reproductions-20261113.log` |
| 最终后端软件回归 | 2273通过、1跳过、72子测试通过；1条依赖弃用警告 |
| metadata | 37项通过 |
| 后端导入 | app、experiments、ws、campaigns、campaigns.store、ml.planner通过 |
| 前端测试 | 基线221通过/16失败；修复测试装配与过期断言后237项全部通过 |
| 隔离生产构建 | 通过；保留构建工具弃用及chunk体积提示，不作为测试失败 |
| 资料与文档检查 | 56份Markdown中338个本地文件链接目标存在；24项文件哈希与5项迁移哈希一致；`git diff --check`通过 |

链接检查范围为本地文件目标，不代表远程网址持续可用或全部标题锚点均已校验。

完整结果保存在忽略目录`output/review-*-20261113.log`，不将运行产物纳入资料库。生成的前端声明文件无内容变更。跳过项不计为通过；Windows符号链接测试在当前账号不能创建链接时有显式跳过分支。

复验命令：

```powershell
& 'C:/Users/Administrator/miniconda3/envs/heat/python.exe' -m pytest tests --ignore=tests/test_hardware.py -q -o cache_dir=output/review-20261113/heat-cache
& 'C:/Users/Administrator/miniconda3/envs/heat/python.exe' tests/test_metadata.py
# 以下在frontend目录执行
node --import tsx --test tests/*.test.ts
npm run build -- --mode production --outDir ../output/review-20261113/frontend-dist
```

## 原件补齐与归档规则

新增中盛《数字量输入输出系列使用手册(RS485&RS232版)》V3.0（32页）及宇电AI-516/516P使用说明书V9.3（31页）。来源网址、下载日期、版本视觉核对及适用边界见[官网原件登记](device_materials/README.md)。宇电文本层残留旧版字样，保留原件，版本登记依据可见封面；不据此认定所有加热器均适配。

24项非Markdown文件（含目录属性文件）已计算哈希，10份PDF均可解析并尝试逐页文本提取；其中MSP1-CX为扫描件、文本为空，后续已对关键协议页渲染核对，不能视作全册文本检查通过；未发现完全相同的哈希副本，因此没有实施重复文件删除。2026-11-05审查所登记18份哈希仍可在当前资料库找到。旧Bürkert手册、被四圈方案替代的旧托盘设计及3份历史辅助EXE只移动归档；当前控制器RAR和四圈模型仍在主资料区。归档工具未运行或安装。

转换协议继续对应原始文件，并保留原始微波XLSX缺失、版本/固件未签核的说明；哈希证明副本身份，不证明设备适用性。历史资料的结论保留当时日期，当前导航明确其已被替代范围。

## 待补资料与现场验收

- 用户确认两台加热套整机为科瑞ZNBC-SCL-T/1000ML、K型传感器，提供编号KR202603302187；用户说明产品编号不重要，不再要求逐台对应。仍待确认heater1内部控制器型号和两台固件；Heat2历史读回AI-516P不外推到heater1。
- 用户确认继电器为中盛ZS-DIO-R-10A-4（4路10A，RS485/CAN，Modbus RTU）；仍需确认固件及通道1实际模式；核对通信参数、接线、`0x0030`通信检测关闭输出条件。软件不自动调整这些参数。
- 用户确认`26.6.10-单模modbus地址.xlsx`已整理为Markdown，保留现有转换稿，不再列为待用户找回任务；原表哈希仍不可核验。泵与运动控制器现有资料、配置及关键协议对应已核对，见[逐设备核对表](device_materials/protocol_correspondence_20261113.md)；该资料核对任务关闭，未登记固件号不单独作为阻塞项。现场验收仍独立保留。
- 最终阀门电源型号按用户要求不记录；ACC-007已于2026-11-13由用户确认选定PP（聚丙烯），材质选择事项关闭；额定工况与实物适配不据此视为验收通过。历史24V、上限10A电源对照正常及约0.65A启动峰值是观察结果，不证明所有1A电源不足或最终采购已完成。
- 继电器新增模式只读查询改变切换前通信时序；现场需验证普通模式下开关与读回、模式不匹配拒绝写入，以及查询超时/查询期间停止的延迟。不得仅凭软件测试解除硬件验收要求。
- 四圈72瓶逐点对准、双轴异常停止、限位/失联、跨圈避让及联动水测继续按[标定记录](collection_platform_calibration.md)与现场清单验收。历史局部对准不等于全盘验收。

资料缺口不阻断有充分证据的软件修复，以上项目保持未关闭。

## 资料迁移清单

路径相对仓库根目录；归档后逐字节哈希与迁移前一致。

| 原路径 | 当前路径 | SHA-256 |
| --- | --- | --- |
| `docs/device_materials/DS0127-Standard-CN-ZH0127(1).pdf` | [docs/device_materials/valve/archive/DS0127-Standard-CN-ZH0127(1).pdf](device_materials/valve/archive/DS0127-Standard-CN-ZH0127%281%29.pdf) | `e78fc05fcd4cc6bf563e8566e912b0974a1c5098ec10a345a2356f2d03ded29b` |
| `docs/device_materials/designs/turntable/自动换瓶托盘与支架设计草案.html` | [docs/device_materials/collection/archive/designs/自动换瓶托盘与支架设计草案.html](device_materials/collection/archive/designs/%E8%87%AA%E5%8A%A8%E6%8D%A2%E7%93%B6%E6%89%98%E7%9B%98%E4%B8%8E%E6%94%AF%E6%9E%B6%E8%AE%BE%E8%AE%A1%E8%8D%89%E6%A1%88.html) | `7e6dcad01db21454b25d7339eecd27e99b535e510e3ae0d0ed0635b7e2862979` |
| `docs/device_materials/tools/turntable/1_340芯片+USB转串口线+USB转RS232+USB9针串口+340芯片USB转串口线(2).EXE.exe` | [docs/device_materials/collection/archive/tools/1_340芯片+USB转串口线+USB转RS232+USB9针串口+340芯片USB转串口线(2).EXE.exe](device_materials/collection/archive/tools/1_340%E8%8A%AF%E7%89%87%2BUSB%E8%BD%AC%E4%B8%B2%E5%8F%A3%E7%BA%BF%2BUSB%E8%BD%ACRS232%2BUSB9%E9%92%88%E4%B8%B2%E5%8F%A3%2B340%E8%8A%AF%E7%89%87USB%E8%BD%AC%E4%B8%B2%E5%8F%A3%E7%BA%BF%282%29.EXE.exe) | `5c79a8c123d3fa03274fdccc8fad722aaf3b703df35c39b4b42f0b5bfbb26dfd` |
| `docs/device_materials/tools/turntable/CL-01A(串口控制_翼宣).exe` | [docs/device_materials/collection/archive/tools/CL-01A(串口控制_翼宣).exe](device_materials/collection/archive/tools/CL-01A%28%E4%B8%B2%E5%8F%A3%E6%8E%A7%E5%88%B6_%E7%BF%BC%E5%AE%A3%29.exe) | `becae88567d7237e16733c593ecc587fda8196b13c8119210a037d56d7638410` |
| `docs/device_materials/tools/turntable/CL-01A程序下载助手(翼宣).exe` | [docs/device_materials/collection/archive/tools/CL-01A程序下载助手(翼宣).exe](device_materials/collection/archive/tools/CL-01A%E7%A8%8B%E5%BA%8F%E4%B8%8B%E8%BD%BD%E5%8A%A9%E6%89%8B%28%E7%BF%BC%E5%AE%A3%29.exe) | `73ad2278cb024c83e2e85375ab91c1912a493d9972fddb34f6bb78ff6a351210` |

## 当前资料文件指纹

路径相对`docs/device_materials/`，Markdown说明文档单独检查链接与差异。

| 文件 | 字节数 | SHA-256 |
| --- | ---: | --- |
| [.gitattributes](device_materials/.gitattributes) | 227 | `dda6a4740929866773e7e977edd908c65964c6cf6d8cbf94fba6dcdf11974730` |
| [20260624-出厂检验报告(4).doc](device_materials/microwave/20260624-%E5%87%BA%E5%8E%82%E6%A3%80%E9%AA%8C%E6%8A%A5%E5%91%8A%284%29.doc) | 18458516 | `fe29b842d12871457402b788ae5d829fbff1ef4d5970a2680de9b08b2ee3543d` |
| [3758240252Henyon两位三通电磁阀使用说明书.pdf](device_materials/valve/3758240252Henyon%E4%B8%A4%E4%BD%8D%E4%B8%89%E9%80%9A%E7%94%B5%E7%A3%81%E9%98%80%E4%BD%BF%E7%94%A8%E8%AF%B4%E6%98%8E%E4%B9%A6.pdf) | 809442 | `caf67b04023629b4aa76adf782ad96aa06e411a9c9c53a31079034a47b0b0e31` |
| [accessories/images/ACC-002-supplier.png](device_materials/accessories/images/ACC-002-supplier.png) | 701934 | `ba6719601736cb61abba48df79633d9cf279592e76a4b574ee5e5294ff03ffd5` |
| [accessories/images/microwave-accessories-list-20261105.png](device_materials/microwave/images/microwave-accessories-list-20261105.png) | 4271 | `27999bbebfa0ff949c7a3c3cc96379787fa7ee36adc728440c0a74b747efbe43` |
| [accessories/images/microwave-ptfe-bottle-section.png](device_materials/microwave/images/microwave-ptfe-bottle-section.png) | 10316 | `7fc0cd061fc2756d664f5105c60d436313118f2003931f0e95a8d90e923eb767` |
| [accessories/images/microwave-ptfe-bottle-volume.png](device_materials/microwave/images/microwave-ptfe-bottle-volume.png) | 49018 | `043f5ad3d75b4293b9721241d524af27e7300b6a89555998c87784aef6bb1c97` |
| [archive/designs/turntable/自动换瓶托盘与支架设计草案.html](device_materials/collection/archive/designs/%E8%87%AA%E5%8A%A8%E6%8D%A2%E7%93%B6%E6%89%98%E7%9B%98%E4%B8%8E%E6%94%AF%E6%9E%B6%E8%AE%BE%E8%AE%A1%E8%8D%89%E6%A1%88.html) | 684698 | `7e6dcad01db21454b25d7339eecd27e99b535e510e3ae0d0ed0635b7e2862979` |
| [archive/DS0127-Standard-CN-ZH0127(1).pdf](device_materials/valve/archive/DS0127-Standard-CN-ZH0127%281%29.pdf) | 1958496 | `e78fc05fcd4cc6bf563e8566e912b0974a1c5098ec10a345a2356f2d03ded29b` |
| [archive/tools/turntable/1_340芯片+USB转串口线+USB转RS232+USB9针串口+340芯片USB转串口线(2).EXE.exe](device_materials/collection/archive/tools/1_340%E8%8A%AF%E7%89%87%2BUSB%E8%BD%AC%E4%B8%B2%E5%8F%A3%E7%BA%BF%2BUSB%E8%BD%ACRS232%2BUSB9%E9%92%88%E4%B8%B2%E5%8F%A3%2B340%E8%8A%AF%E7%89%87USB%E8%BD%AC%E4%B8%B2%E5%8F%A3%E7%BA%BF%282%29.EXE.exe) | 233018 | `5c79a8c123d3fa03274fdccc8fad722aaf3b703df35c39b4b42f0b5bfbb26dfd` |
| [archive/tools/turntable/CL-01A(串口控制_翼宣).exe](device_materials/collection/archive/tools/CL-01A%28%E4%B8%B2%E5%8F%A3%E6%8E%A7%E5%88%B6_%E7%BF%BC%E5%AE%A3%29.exe) | 2068480 | `becae88567d7237e16733c593ecc587fda8196b13c8119210a037d56d7638410` |
| [archive/tools/turntable/CL-01A程序下载助手(翼宣).exe](device_materials/collection/archive/tools/CL-01A%E7%A8%8B%E5%BA%8F%E4%B8%8B%E8%BD%BD%E5%8A%A9%E6%89%8B%28%E7%BF%BC%E5%AE%A3%29.exe) | 2113536 | `73ad2278cb024c83e2e85375ab91c1912a493d9972fddb34f6bb78ff6a351210` |
| [CL-01A运动控制器说明书.pdf](device_materials/collection/CL-01A%E8%BF%90%E5%8A%A8%E6%8E%A7%E5%88%B6%E5%99%A8%E8%AF%B4%E6%98%8E%E4%B9%A6.pdf) | 1810808 | `2355866bcfa51d4d02117604c3dd93f831b4a01f8aa185dd76ee7c8a8b05d1fb` |
| [designs/turntable/整体装配参考_R1_含购买件与模拟物.blend](device_materials/collection/designs/%E6%95%B4%E4%BD%93%E8%A3%85%E9%85%8D%E5%8F%82%E8%80%83_R1_%E5%90%AB%E8%B4%AD%E4%B9%B0%E4%BB%B6%E4%B8%8E%E6%A8%A1%E6%8B%9F%E7%89%A9.blend) | 6477405 | `5caaa40c76401feb73823855d8d1501898eceeb9201ff37176fe68d33b9ff32e` |
| [LabSmart说明书（中文）.pdf](device_materials/peristaltic_pump/LabSmart%E8%AF%B4%E6%98%8E%E4%B9%A6%EF%BC%88%E4%B8%AD%E6%96%87%EF%BC%89.pdf) | 3058282 | `4f49b79858dbd57f1935ad0dfdb85ed59666b91aebc53266261cc6cfd9cfc1c7` |
| [MKM-AH1E环形聚焦单模微波化学合成仪-说明书.doc](device_materials/microwave/MKM-AH1E%E7%8E%AF%E5%BD%A2%E8%81%9A%E7%84%A6%E5%8D%95%E6%A8%A1%E5%BE%AE%E6%B3%A2%E5%8C%96%E5%AD%A6%E5%90%88%E6%88%90%E4%BB%AA-%E8%AF%B4%E6%98%8E%E4%B9%A6.doc) | 962427 | `ef73b9e390cddda16263eef0f68db8b381f6c88f913ac4cd18b871e9be6c97a8` |
| [MSP1-CX用户手册 2025.6.4.pdf](device_materials/syringe_pump/MSP1-CX%E7%94%A8%E6%88%B7%E6%89%8B%E5%86%8C%202025.6.4.pdf) | 30549245 | `6bb9fe4189cd398ebbef695bc54360be96da1a9be599751eb33eda94b46faa5a` |
| [tools/turntable/YX_HA02C 调试终端.rar](device_materials/collection/tools/YX_HA02C%20%E8%B0%83%E8%AF%95%E7%BB%88%E7%AB%AF.rar) | 4317829 | `601c2bc1ed483aa4943bf875569de982beca0ce02737dec0f09590baaf819e93` |
| [YX-HA02C运动控制器使用说明书v1.2.pdf](device_materials/collection/YX-HA02C%E8%BF%90%E5%8A%A8%E6%8E%A7%E5%88%B6%E5%99%A8%E4%BD%BF%E7%94%A8%E8%AF%B4%E6%98%8E%E4%B9%A6v1.2.pdf) | 14313370 | `e4f80429cb307694c848ec834c483e74f752ce139fb82fd4b1d1a53635cc7e51` |
| [多通道蠕动泵MODBUS通信协议.doc](device_materials/peristaltic_pump/%E5%A4%9A%E9%80%9A%E9%81%93%E8%A0%95%E5%8A%A8%E6%B3%B5MODBUS%E9%80%9A%E4%BF%A1%E5%8D%8F%E8%AE%AE.doc) | 169472 | `997cef5a096dbfa839b3fc68dfd47e300f9d4de85b2ff7306cf408e67be89541` |
| [宇电AI-516_516P使用说明书V9.3.pdf](device_materials/heaters/%E5%AE%87%E7%94%B5AI-516_516P%E4%BD%BF%E7%94%A8%E8%AF%B4%E6%98%8E%E4%B9%A6V9.3.pdf) | 1845553 | `f88522b65a0b08e29f74bfe6b910d4fbac3319156e3bed7df5d2b6570d143ec4` |
| [宇电单回路测量控制仪表通讯协议说明(1).pdf](device_materials/heaters/%E5%AE%87%E7%94%B5%E5%8D%95%E5%9B%9E%E8%B7%AF%E6%B5%8B%E9%87%8F%E6%8E%A7%E5%88%B6%E4%BB%AA%E8%A1%A8%E9%80%9A%E8%AE%AF%E5%8D%8F%E8%AE%AE%E8%AF%B4%E6%98%8E%281%29.pdf) | 365553 | `3c2141652df4980f3f0042333c9561e5f714ad0f841500c945948594a6573172` |
| [数字量输入输出系列使用手册(RS485&RS232版).pdf](device_materials/relay/%E6%95%B0%E5%AD%97%E9%87%8F%E8%BE%93%E5%85%A5%E8%BE%93%E5%87%BA%E7%B3%BB%E5%88%97%E4%BD%BF%E7%94%A8%E6%89%8B%E5%86%8C%28RS485%26RS232%E7%89%88%29.pdf) | 3935827 | `9ef7571ad7f73869f3cf9ca29172c02aaec002e87f92f672cb04f62d9ec3547e` |
| [申辰多通道独立控制 LabSmart.pdf](device_materials/peristaltic_pump/%E7%94%B3%E8%BE%B0%E5%A4%9A%E9%80%9A%E9%81%93%E7%8B%AC%E7%AB%8B%E6%8E%A7%E5%88%B6%20LabSmart.pdf) | 1628762 | `103143dafb04fd1dcd3f866ad8704484042ecf08d0af05808b16a80e1f2fda5f` |

## 按仪器拆分目录（用户追加要求）

将资料归入加热器、蠕动泵、微波仪、注射泵、阀体、继电器、接样平台7个目录。历史资料置于对应仪器的archive子目录，共用配件清单单独保留。25个文件迁移（含协议转换稿及微波专用附件），厂家原件与二进制资料字节不变；Markdown中的路径随迁移更新。

| 迁移前 | 迁移后 |
| --- | --- |
| `docs/device_materials/20260624-出厂检验报告(4).doc` | `docs/device_materials/microwave/20260624-出厂检验报告(4).doc` |
| `docs/device_materials/3758240252Henyon两位三通电磁阀使用说明书.pdf` | `docs/device_materials/valve/3758240252Henyon两位三通电磁阀使用说明书.pdf` |
| `docs/device_materials/CL-01A运动控制器说明书.pdf` | `docs/device_materials/collection/CL-01A运动控制器说明书.pdf` |
| `docs/device_materials/LabSmart说明书（中文）.pdf` | `docs/device_materials/peristaltic_pump/LabSmart说明书（中文）.pdf` |
| `docs/device_materials/MKM-AH1E环形聚焦单模微波化学合成仪-说明书.doc` | `docs/device_materials/microwave/MKM-AH1E环形聚焦单模微波化学合成仪-说明书.doc` |
| `docs/device_materials/MSP1-CX用户手册 2025.6.4.pdf` | `docs/device_materials/syringe_pump/MSP1-CX用户手册 2025.6.4.pdf` |
| `docs/device_materials/YX-HA02C运动控制器使用说明书v1.2.pdf` | `docs/device_materials/collection/YX-HA02C运动控制器使用说明书v1.2.pdf` |
| `docs/device_materials/多通道蠕动泵MODBUS通信协议.doc` | `docs/device_materials/peristaltic_pump/多通道蠕动泵MODBUS通信协议.doc` |
| `docs/device_materials/多通道蠕动泵MODBUS通信协议.md` | `docs/device_materials/peristaltic_pump/多通道蠕动泵MODBUS通信协议.md` |
| `docs/device_materials/宇电AI-516_516P使用说明书V9.3.pdf` | `docs/device_materials/heaters/宇电AI-516_516P使用说明书V9.3.pdf` |
| `docs/device_materials/宇电单回路测量控制仪表通讯协议说明(1).pdf` | `docs/device_materials/heaters/宇电单回路测量控制仪表通讯协议说明(1).pdf` |
| `docs/device_materials/微波反应仪通信协议.md` | `docs/device_materials/microwave/微波反应仪通信协议.md` |
| `docs/device_materials/数字量输入输出系列使用手册(RS485&RS232版).pdf` | `docs/device_materials/relay/数字量输入输出系列使用手册(RS485&RS232版).pdf` |
| `docs/device_materials/申辰多通道独立控制 LabSmart.pdf` | `docs/device_materials/peristaltic_pump/申辰多通道独立控制 LabSmart.pdf` |
| `docs/device_materials/archive/DS0127-Standard-CN-ZH0127(1).pdf` | `docs/device_materials/valve/archive/DS0127-Standard-CN-ZH0127(1).pdf` |
| `docs/device_materials/archive/designs/turntable/自动换瓶托盘与支架设计草案.html` | `docs/device_materials/collection/archive/designs/自动换瓶托盘与支架设计草案.html` |
| `docs/device_materials/archive/tools/turntable/1_340芯片+USB转串口线+USB转RS232+USB9针串口+340芯片USB转串口线(2).EXE.exe` | `docs/device_materials/collection/archive/tools/1_340芯片+USB转串口线+USB转RS232+USB9针串口+340芯片USB转串口线(2).EXE.exe` |
| `docs/device_materials/archive/tools/turntable/CL-01A(串口控制_翼宣).exe` | `docs/device_materials/collection/archive/tools/CL-01A(串口控制_翼宣).exe` |
| `docs/device_materials/archive/tools/turntable/CL-01A程序下载助手(翼宣).exe` | `docs/device_materials/collection/archive/tools/CL-01A程序下载助手(翼宣).exe` |
| `docs/device_materials/designs/turntable/整体装配参考_R1_含购买件与模拟物.blend` | `docs/device_materials/collection/designs/整体装配参考_R1_含购买件与模拟物.blend` |
| `docs/device_materials/tools/turntable/YX_HA02C 调试终端.rar` | `docs/device_materials/collection/tools/YX_HA02C 调试终端.rar` |
| `docs/device_materials/accessories/microwave_bottle_fittings.md` | `docs/device_materials/microwave/microwave_bottle_fittings.md` |
| `docs/device_materials/accessories/images/microwave-accessories-list-20261105.png` | `docs/device_materials/microwave/images/microwave-accessories-list-20261105.png` |
| `docs/device_materials/accessories/images/microwave-ptfe-bottle-section.png` | `docs/device_materials/microwave/images/microwave-ptfe-bottle-section.png` |
| `docs/device_materials/accessories/images/microwave-ptfe-bottle-volume.png` | `docs/device_materials/microwave/images/microwave-ptfe-bottle-volume.png` |

拆分后复核：63份Markdown中380个本地文件链接目标存在；23项原有非Markdown资料文件（不含已更新的.gitattributes维护文件）哈希与拆分前一致；`git diff --check`通过。本次只更新资料与说明，不重复运行已通过的软件回归。
