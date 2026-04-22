# 锁文件清理功能使用说明

## 概述

锁文件清理功能已集成到 `serial_manager.py` 中，提供通用的锁文件管理能力。

## API 接口

### 1. 便捷函数（推荐使用）

```python
from utils.serial_manager import (
    list_all_serial_locks,
    cleanup_all_stale_serial_locks
)

# 列出所有锁文件
locks = list_all_serial_locks()
for lock in locks:
    print(f"端口: {lock['port']}, 进程: {lock['pid']}")

# 清理过期锁文件（其他进程遗留的）
cleaned = cleanup_all_stale_serial_locks()
print(f"清理了 {cleaned} 个锁文件")

# 强制清理所有锁文件（包括当前进程的）
cleaned = cleanup_all_stale_serial_locks(include_current_process=True)
```

### 2. 通过 SerialPortManager 使用

```python
from utils.serial_manager import get_serial_manager

manager = get_serial_manager()

# 列出所有锁文件
locks = manager.list_all_locks()

# 清理过期锁文件
cleaned = manager.cleanup_all_stale_locks()

# 强制清理所有锁文件
cleaned = manager.cleanup_all_stale_locks(include_current_process=True)
```

### 3. 通过 SerialPortLock 类使用

```python
from utils.serial_manager import SerialPortLock

locker = SerialPortLock()

# 列出所有锁文件
locks = locker.list_all_locks()

# 清理过期锁文件
cleaned = locker.cleanup_all_stale_locks()
```

## 命令行工具

### 基本使用

```bash
# 列出所有锁文件
python scripts/cleanup_locks.py --list

# 清理过期锁文件
python scripts/cleanup_locks.py

# 强制清理所有锁文件
python scripts/cleanup_locks.py --force
```

### 命令行选项

| 选项 | 说明 |
|------|------|
| `-h, --help` | 显示帮助信息 |
| `-l, --list` | 仅列出所有锁文件，不清理 |
| `-f, --force` | 强制清理所有锁文件（包括当前进程的） |

## 功能特性

### 1. 智能锁文件检测

- 自动检测已死亡进程的锁文件
- 自动检测损坏的锁文件
- 自动清理空的锁目录

### 2. 安全的清理策略

- 默认只清理过期锁文件（其他进程遗留的）
- 可选：清理当前进程的锁文件
- 单文件删除失败不影响整体操作

### 3. 详细的锁信息

每个锁文件包含：
- 端口名称
- 进程 ID
- 创建时间
- 进程存活状态（检测时）

## 使用场景

### 场景 1：程序异常退出后清理

```python
from utils.serial_manager import cleanup_all_stale_serial_locks

# 程序启动前清理可能的遗留锁文件
cleaned = cleanup_all_stale_serial_locks()
if cleaned > 0:
    print(f"清理了 {cleaned} 个遗留锁文件")
```

### 场景 2：调试时查看锁状态

```python
from utils.serial_manager import list_all_serial_locks

locks = list_all_serial_locks()
print(f"当前有 {len(locks)} 个锁文件：")
for lock in locks:
    status = "活动" if lock.get('pid') else "损坏"
    print(f"  - {lock['port']}: {status}")
```

### 场景 3：完全重置（开发调试用）

```python
from utils.serial_manager import cleanup_all_stale_serial_locks

# 强制清理所有锁文件，包括当前进程的
cleaned = cleanup_all_stale_serial_locks(include_current_process=True)
print(f"已重置所有锁文件，共清理 {cleaned} 个")
```

## 注意事项

1. **生产环境慎用 `--force` 选项**：这会清理所有锁文件，包括其他正在运行程序的锁

2. **锁文件自动管理**：正常情况下，程序退出时会自动清理锁文件，无需手动调用

3. **多进程协调**：锁文件机制用于防止多个进程同时访问同一串口，使用时注意协调

4. **异常处理**：清理操作已包含异常处理，单个锁文件删除失败不会影响整体操作
