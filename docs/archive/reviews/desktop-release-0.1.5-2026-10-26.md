# Heat 0.1.5 构建与覆盖安装（2026-10-26）

用户在全项目审查完成后明确授权提交、推送、合并及更新安装。所有源码与文档修改在 `codex/project-review-fixes-20261026` 完成，随后按仓库流程同步双远程、合并并归档。

## 内容与验证

本版包含[全项目审查报告](project-review-2026-10-26.md)中的 7 类产品修复和 1 类测试修复：取消安全的手动设备桥接、严格恢复目录检查、CSV 历史保留与兼容、REST/WS 进度顺序、状态未确认提示、图形 YAML 节点创建，以及模板批次缺省 metadata。同步驱动和既有实验策略保持。

- 完整业务回归：后端 1992 passed、1 skipped、65 subtests passed；前端 200 passed；metadata 37 passed；模块导入、pip check 通过。
- 版本更新后的桌面 host/packaging 专项：65 passed。
- 重新执行生产前端构建，两个生成声明内容无变化；复用现有独立构建环境，不安装或升级依赖。
- PyInstaller、Inno Setup 和发行验证成功：657 个发行文件的集合、大小与 SHA-256 一致；两个 EXE 各 80 个源码模块及入口与源码一致；94 个前端资源一致；45 项锁定依赖匹配。未夹带实验室配置、数据、历史、恢复记录。
- 跳过项仍为 Windows 账户无法创建符号链接的迁移测试；干净机器、真实设备及物理停止验收未在本次执行。

## 安装与数据保留

安装前确认没有 Heat.exe、HeatBackend.exe 或 8000 端口监听；没有停止在用实验或强杀进程。先备份 `%LOCALAPPDATA%\Heat` 和旧安装目录并逐文件核对哈希。

0.1.5 安装器正常退出（exit 0），安装日志确认无需重启 Windows。注册表版本为 0.1.5；安装目录 656 个发行文件与清单匹配，原有 585 个用户资料文件的集合及 SHA-256 完全一致，未重新导入工作区。旧 0.1.4 安装器哈希保持不变。

对已安装 `HeatBackend.exe` 使用独立 LOCALAPPDATA、独立 HEAT_DATA_DIR 及六类设备均为空的配置进行启动检查：IPC 版本 0.1.5、进程身份及工作区匹配，首页和设备列表可读，设备列表为空；随后通过认证 shutdown/commit_exit 正常结束，exit 0。此检查不启动用户实际工作区，不连接真实设备，也不替代原生窗口、托盘及实验室验收。

## 产物与证据

| 内容 | 路径或结果 |
| --- | --- |
| 安装器 | `output/desktop/release/Heat-Setup-0.1.5-x64.exe` |
| 安装位置 | `%LOCALAPPDATA%\Programs\Heat` |
| 安装器大小 | 254725560 字节 |
| 安装器 SHA-256 | `46be5bf126e1d2c3a336cb427a0b4a3f699b877af4ea25e3a1a6af77890d2730` |
| 构建清单 | `output/desktop/release-manifest.json` |
| 日志及核验 | `output/desktop/release-0.1.5-evidence/` |
| 本机升级前备份 | `output/desktop/release-0.1.5-evidence/upgrade-backup/` |

证据目录包含构建日志、源码/资源核验、安装日志、安装后文件核验及空设备启动检查结果。备份含本机资料，仅作本机恢复使用，不提交或随安装包分发。安装成功不等于设备现场验收通过。
