#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
单通道蠕动泵流量模式测试

使用方法：
    python scripts/test_pump_flow.py --port COM10 --force
"""

import sys
import os
import time
import argparse

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, 'src'))

from devices.peristaltic_pump import LabSmartPumpDevice, PeristalticPumpConfig, PumpChannelConfig
from protocols.pump_params import PumpRunMode, PumpDirection
from utils import get_serial_manager, cleanup_all_serial_ports


def main():
    parser = argparse.ArgumentParser(description="单通道蠕动泵流量模式测试")
    parser.add_argument("--port", type=str, default="COM10", help="蠕动泵串口")
    parser.add_argument("--channel", type=int, default=1, help="通道号 (1-4)")
    parser.add_argument("--flow-rate", type=float, default=5.0, help="流量 mL/min")
    parser.add_argument("--duration", type=float, default=10.0, help="运行秒数")
    parser.add_argument("--force", action="store_true", help="强制获取串口")
    args = parser.parse_args()

    mgr = get_serial_manager()

    print(f"获取串口 {args.port} ...")
    if not mgr.acquire_port(args.port, force=args.force):
        print(f"[失败] 无法获取串口 {args.port}")
        return 1

    try:
        config = PeristalticPumpConfig(
            device_id="pump_test",
            connection_params={"port": args.port, "baudrate": 9600, "parity": "N"},
            slave_address=1,
            channels=[PumpChannelConfig(channel=args.channel, enabled=True)],
        )

        pump = LabSmartPumpDevice(config)

        print("连接蠕动泵 ...")
        if not pump.connect():
            print("[失败] 蠕动泵连接失败")
            return 1

        print("[成功] 蠕动泵已连接")

        print(f"设置通道{args.channel}: 流量模式, {args.flow_rate} mL/min, 顺时针 ...")
        pump.set_direction(args.channel, PumpDirection.CLOCKWISE)
        pump.set_run_mode(args.channel, PumpRunMode.FLOW_MODE)
        pump.set_flow_rate(args.channel, args.flow_rate)

        print(f"启动通道{args.channel} ...")
        pump.start_channel(args.channel)
        print(f"[运行中] 通道{args.channel} 以 {args.flow_rate} mL/min 运行 {args.duration} 秒")

        for i in range(int(args.duration)):
            time.sleep(1)
            print(f"  {i+1}s / {int(args.duration)}s")

        print("停止所有通道 ...")
        pump.stop_all()
        print("[成功] 已停止")

        pump.disconnect()
        print("蠕动泵已断开")

    except Exception as e:
        print(f"[错误] {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        mgr.release_port(args.port)
        cleanup_all_serial_ports()
        print("串口资源已释放")

    return 0


if __name__ == "__main__":
    sys.exit(main())
