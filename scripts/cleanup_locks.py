"""
锁文件清理工具 - 使用通用的串口管理器逻辑

功能：
1. 列出所有锁文件
2. 清理过期锁文件（包括其他进程遗留的）
3. 清理损坏的锁文件
4. 可选：强制清理所有锁文件（包括当前进程的）
"""

import sys
import os

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)
sys.path.insert(0, os.path.join(_project_root, 'src'))

from utils.serial_manager import (
    list_all_serial_locks,
    cleanup_all_stale_serial_locks,
    is_process_alive,
)


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="锁文件清理工具")
    parser.add_argument(
        "-l", "--list",
        action="store_true",
        help="仅列出所有锁文件，不清理"
    )
    parser.add_argument(
        "-f", "--force",
        action="store_true",
        help="强制清理所有锁文件（包括当前进程的）"
    )
    
    args = parser.parse_args()
    
    # 列出锁文件
    print("="*60)
    print("锁文件清理工具")
    print("="*60)
    
    locks = list_all_serial_locks()
    
    if not locks:
        print("\n没有找到锁文件")
        print("="*60)
        return
    
    print(f"\n找到 {len(locks)} 个锁文件：")
    print("-"*60)
    
    for i, lock in enumerate(locks, 1):
        status = "正常"
        if lock.get('corrupted'):
            status = "损坏"
        elif lock.get('pid'):
            if not is_process_alive(lock['pid']):
                status = "过期"
        
        print(f"{i}. 端口: {lock.get('port', 'N/A')}")
        print(f"   进程ID: {lock.get('pid', 'N/A')}")
        print(f"   时间: {lock.get('datetime', 'N/A')}")
        print(f"   状态: {status}")
        print()
    
    if args.list:
        print("="*60)
        return
    
    # 清理锁文件
    print("-"*60)
    print("正在清理锁文件...")
    
    cleaned = cleanup_all_stale_serial_locks(include_current_process=args.force)
    
    if cleaned > 0:
        print(f"✓ 已清理 {cleaned} 个锁文件")
    else:
        print("没有需要清理的锁文件")
    
    # 再次列出剩余的锁文件
    locks = list_all_serial_locks()
    if locks:
        print(f"\n剩余 {len(locks)} 个锁文件：")
        for i, lock in enumerate(locks, 1):
            print(f"{i}. 端口: {lock.get('port', 'N/A')}, 进程ID: {lock.get('pid', 'N/A')}")
    
    print("\n" + "="*60)
    print("清理完成！")
    print("="*60)


if __name__ == "__main__":
    main()
