# 设备资料

本目录保留 Heat 当前设备的厂家原始资料、便于检索的转换稿和项目实机观察。三类内容的权威边界不同，不能互相替代。

## 厂家原始资料

原始资料用于确认额定条件、接线、寄存器、联锁和安全要求。下表固定仓库文件的 SHA-256，并记录目前能从仓库确认的代码对应关系。文件校验和仅识别当前副本，不能证明厂家版本、适用型号或现场设备身份。

| 原始文件 | SHA-256 | 代码/协议对应 | 当前配置中的设备身份与串口参数 | 版本/适配核验状态 |
|---|---|---|---|---|
| `宇电单回路测量控制仪表通讯协议说明(1).pdf` | `3C2141652DF4980F3F0042333C9561E5F714AD0F841500C945948594A6573172` | `src/protocols/aibus.py`、`parameters.py`；`src/devices/heater.py` | `heater1`: fallback `COM4`，VID/PID `6790/29987`，USB location `1-3.3`，9600/N/站号1；`heater2`: fallback `COM5`，同 VID/PID，location `1-3.4`，9600/N/站号1 | 协议标题指向宇电单回路仪表；具体 AI 型号、手册版次和两台仪表的序列号/固件未登记。COM 是绑定回退值，实际端口以指纹解析结果为准 |
| `LabSmart说明书（中文）.pdf` | `4F49B79858DBD57F1935AD0DFDB85ED59666B91AEBC53266261CC6CFD9CFC1C7` | `src/devices/peristaltic_pump.py`、`src/protocols/pump_params.py`；映射文档见下方转换协议 | `pump1`: fallback `COM3`，序列号 `CNDIB148313`，19200/8E1/站号1；泵头5，四通道软管配置11，最大流量18.75 mL/min | 文件名指向 LabSmart；具体型号、手册版次、实物固件/HMI 版本未登记 |
| `申辰多通道独立控制 LabSmart.pdf` | `103143DAFB04FD1DCD3F866AD8704484042ECF08D0AF05808B16A80E1F2FDA5F` | 同上；`pump1` 设备级软管覆盖为写入 `11`、读回 `13` | 同 `pump1` 配置；该映射由 HMI 显示 `1.52 x 0.86` 确认，仅适用于配置中的 `pump1` | 文件名指向申辰 LabSmart 多通道系列；具体型号/版次及该手册与 `pump1` 实物的对应关系未登记 |
| `多通道蠕动泵MODBUS通信协议.doc` | `997CEF5A096DBFA839B3FC68DFD47E300F9D4DE85B2FF7306CF408E67BE89541` | 转换稿 `多通道蠕动泵MODBUS通信协议.md`；寄存器实现 `src/protocols/modbus_rtu.py`、`pump_params.py` | 与 `pump1` 配置相同：序列号 `CNDIB148313`，19200/8E1/站号1 | 原件标题指向多通道蠕动泵；协议版次、适用型号/固件未登记，转换稿没有逐项签核记录 |
| `MKM-AH1E环形聚焦单模微波化学合成仪-说明书.doc` | `EF73B9E390CDDDA16263EEF0F68DB8B381F6C88F913AC4CD18B871E9BE6C97A8` | `src/devices/microwave.py`、`src/protocols/microwave_params.py`；寄存器转换稿见下方 | `microwave1`: 型号配置名 `MKM-AH1E`，fallback `COM6`，序列号 `DU0ENS4UA`，9600/8N1/站号1 | 原件标题与配置型号相符；说明书版次及该序列号设备的固件/HMI 版本未登记 |

串口 fallback 和指纹身份来自 [`config/system_config.yaml`](../../config/system_config.yaml)。设备配置与验收清单中的旧 COM 号曾不一致；当前配置身份以该 YAML 为准，fingerprint 模式下实际 COM 号可能变化。

**待核验状态：** 配置已经登记设备指纹/序列号、通信参数和部分型号；验收记录也记载 `pump1` 的管型读回例外。仍缺厂家完整型号（两台加热器及泵）、各原件版次/日期/关键页表号、各实物固件/HMI 版本，以及原件逐项对照签核。原始文件哈希只能识别仓库副本，不能证明手册适用于当前固件。对未确认项保持“未核验”，不要由代码常量反推厂家版本。

## 转换版协议

- `多通道蠕动泵MODBUS通信协议.md`：由原始协议整理为可检索 Markdown。
- `微波反应仪通信协议.md`：由原 `26.6.10-单模modbus地址.xlsx` 的可见表格 `B2:G143` 转换并校验；原 xlsx 不再保留，无法对原始表格文件计算哈希。配置型号 `MKM-AH1E` 与转换稿所指设备类型相符；原件版次、实物固件对应和逐项签核仍待核验。

转换稿便于代码审查，但若与厂家原件或实际固件冲突，应记录差异并停止推定，不能静默修改为“看起来合理”的协议。

## Heat 实机观察

代码、日志或验收清单中的现场观察只对记录的设备序列号、固件和配置 commit 有效。例如 `pump1` 的软管型号 `写入 11 -> 读回 13` 已由 HMI 显示 `1.52 x 0.86` 确认，因此仅作为该设备的配置级覆盖；完整扫描表只是诊断记录，不是通用可执行映射。

实机结论统一填写在 [MVP 系统验收清单](../mvp_system_acceptance_checklist.md)，微波仪专项步骤见 [微波 smoke test](../microwave_smoke_test.md)。
