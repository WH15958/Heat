#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LabSmart蠕动泵分步诊断脚本（Step1/2/3版）
------------------------------------
用法:
    python scripts/pump_diagnose_labsmart.py --port COM10

逐步测试:
    Step 1: 串口基本连通性
    Step 2: 写入测试（启动/停止）
    Step 3: 读取测试
"""

import sys
import os
import time
import argparse
from datetime import datetime
from typing import Optional

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, 'src'))

from devices.peristaltic_pump import (
    PeristalticPumpConfig,
    PumpChannelConfig,
    LabSmartPumpDevice
)
from protocols.pump_params import PumpRunMode, PumpDirection

from utils import get_serial_manager, cleanup_all_serial_ports

_pump = None
_serial_manager = get_serial_manager()
_auto_answer = False


def create_pump_config(port: str) -> PeristalticPumpConfig:
    channels = [
        PumpChannelConfig(channel=1, enabled=True, pump_head=5, tube_model=1),
        PumpChannelConfig(channel=4, enabled=True, pump_head=5, tube_model=1),
    ]
    return PeristalticPumpConfig(
        device_id="pump1",
        connection_params={'port': port, 'baudrate': 9600, 'parity': 'N'},
        slave_address=1,
        channels=channels
    )


def log(message: str):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}")


def step1_serial_basic(port: str, force: bool) -> bool:
    global _pump
    log("\n" + "=" * 60)
    log("Step 1: 串口基本连通性测试")
    log("=" * 60)

    log(f"[1.1] 尝试获取串口 {port} 锁...")
    try:
        if not _serial_manager.acquire_port(port, force=force):
            log(f"  ✗ 无法获取串口 {port}")
            return False
        log(f"  ✓ 成功获取串口 {port} 锁")
    except Exception as e:
        log(f"  ✗ 获取串口锁异常: {e}")
        return False

    log(f"[1.2] 连接蠕动泵端口: {port}...")
    try:
        config = create_pump_config(port)
        _pump = LabSmartPumpDevice(config)
        if _pump.connect():
            log(f"  ✓ 蠕动泵连接成功")
        else:
            log(f"  ✗ 蠕动泵连接失败")
            _serial_manager.release_port(port)
            return False
    except Exception as e:
        log(f"  ✗ 蠕动泵连接异常: {e}")
        _serial_manager.release_port(port)
        return False

    log("[1.3] 验证泵通信...")
    try:
        pump_status = _pump.read_pump_status()
        if pump_status:
            log(f"  ✓ 泵通信正常")
        else:
            log(f"  ⚠ 泵已连接，但未读到状态")
    except Exception as e:
        log(f"  ⚠ 读取状态异常，但连接成功")

    log("\n[Step1 完成] 串口连通性 ✅")
    return True


def step2_write_test():
    global _pump
    if not _pump:
        log("Step2 错误：泵未连接")
        return False

    log("\n" + "=" * 60)
    log("Step 2: 写入测试")
    log("=" * 60)

    try:
        _pump.set_direction(1, PumpDirection.CLOCKWISE)
        _pump.set_run_mode(1, PumpRunMode.FLOW_MODE)
        _pump.set_flow_rate(1, 5.0)
        log("  ✓ 通道1参数设置成功")
    except Exception as e:
        log(f"  ✗ 设置失败: {e}")
        return False

    try:
        _pump.start_channel(1)
        log("  ✓ 通道1已启动 → 请观察是否转动")
    except Exception as e:
        log(f"  ✗ 启动失败: {e}")

    log("  等待 5 秒...")
    for i in range(5):
        time.sleep(1)
        print(f"  {5-i}...", end="", flush=True)
    print()

    if _auto_answer:
        log("  [auto] 假设泵转动")
        moved = True
    else:
        ans = input("  泵是否转动？(y/n): ").strip().lower()
        moved = ans == "y"

    try:
        _pump.stop_channel(1)
        log("  ✓ 通道1已停止")
    except Exception as stop_e:
        log(f"  ✗ 停止失败: {stop_e}")

    log(f"\n[Step2 结果] {'转动正常 ✅' if moved else '未转动 ❌'}")
    return moved


def step3_read_test():
    global _pump
    if not _pump:
        log("Step3 错误：泵未连接")
        return False

    log("\n" + "=" * 60)
    log("Step 3: 读取测试")
    log("=" * 60)

    ok = True
    for ch in [1, 4]:
        try:
            st = _pump.read_channel_status(ch)
            if st:
                log(f"  ✓ 通道{ch} 读取成功")
            else:
                log(f"  ⚠ 通道{ch} 无数据")
        except:
            log(f"  ✗ 通道{ch} 读取失败")
            ok = False

    log(f"\n[Step3 结果] {'成功 ✅' if ok else '失败 ❌'}")
    return ok


def step4_probe_addresses():
    global _pump
    if not _pump:
        log("Step4 错误：泵未连接")
        return False

    log("\n" + "=" * 60)
    log("Step 4: 控制寄存器地址探测 (LabV协议地址)")
    log("=" * 60)

    labv_addresses = [
        (1000, "泵头型号"),
        (1001, "软管型号"),
        (1002, "电机转速"),
        (1003, "泵头型号(alt)"),
        (1004, "流量(单精度)"),
        (1007, "回吸角度"),
        (1008, "启停控制 ← LabV标准"),
        (1009, "方向控制 ← LabV标准"),
        (1010, "全速运行"),
        (1015, "分装量"),
        (1018, "工作时间"),
        (1020, "工作模式"),
        (1021, "暂停时间"),
        (1023, "循环次数"),
    ]

    log("\n[4.1] 探测写入 - 写0(停)到各地址...")
    for addr, name in labv_addresses:
        result = _pump._write_register(addr, 0)
        status = "✓" if result else "✗"
        log(f"  {status} addr={addr} ({name}): {'成功' if result else '失败'}")
        time.sleep(0.2)

    log("\n[4.2] 探测写入 - 写1(启动)到启停地址...")
    for addr, name in labv_addresses:
        result = _pump._write_register(addr, 1)
        status = "✓" if result else "✗"
        log(f"  {status} addr={addr} ({name}): {'成功' if result else '失败'}")
        time.sleep(0.2)

    log("\n[4.3] 探测当前代码使用的地址 (1001=启停, 1002=方向)...")
    current_addresses = [
        (1001, "当前: 启停控制"),
        (1002, "当前: 方向控制"),
        (1003, "当前: 泵头"),
        (1004, "当前: 软管"),
        (1005, "当前: 回吸"),
        (1006, "当前: 模式"),
    ]
    for addr, name in current_addresses:
        result = _pump._write_register(addr, 0)
        status = "✓" if result else "✗"
        log(f"  {status} addr={addr} ({name}): {'成功' if result else '失败'}")
        time.sleep(0.2)

    log("\n[4.4] 对比读取地址 1300/4300 是否可写...")
    read_addrs = [(1300, "CH1状态使能"), (4300, "CH4状态使能")]
    for addr, name in read_addrs:
        result = _pump._write_register(addr, 0)
        status = "✓" if result else "✗"
        log(f"  {status} addr={addr} ({name}): {'成功' if result else '失败'}")
        time.sleep(0.2)

    log("\n[4.5] 测试直接写入地址1008(启动)并观察...")
    log("  写0到1008 (停)...")
    _pump._write_register(1008, 0)
    time.sleep(0.5)
    log("  写1到1008 (启动)...")
    result = _pump._write_register(1008, 1)
    log(f"  结果: {'成功' if result else '失败'}")
    log("  等待5秒，请观察泵是否转动...")
    for i in range(5):
        time.sleep(1)
        print(f"  {5-i}...", end="", flush=True)
    print()
    if _auto_answer:
        log("  [auto] 跳过观察")
        moved = False
    else:
        ans = input("  泵是否转动？(y/n): ").strip().lower()
        moved = ans == "y"
    _pump._write_register(1008, 0)
    log(f"  写0到1008 (停)...")

    log(f"\n[Step4 结果] {'地址1008有效，泵转动 ✅' if moved else '地址1008无效 ❌'}")
    return moved


def step5_correct_sequence():
    global _pump
    if not _pump:
        log("Step5 错误：泵未连接")
        return False

    log("\n" + "=" * 60)
    log("Step 5: 按协议正确顺序操作（文档地址映射验证）")
    log("=" * 60)

    log("\n[5.1] 测试全局启停地址 0010(十六)=16(十进制)...")
    result = _pump._write_register(16, 0)
    log(f"  addr=16, value=0 (全局停): {'✓' if result else '✗ ' + str(result)}")
    time.sleep(1.0)
    result = _pump._write_register(16, 1)
    log(f"  addr=16, value=1 (全局启): {'✓' if result else '✗ ' + str(result)}")
    time.sleep(1.0)
    result = _pump._write_register(16, 0)
    log(f"  addr=16, value=0 (全局停): {'✓' if result else '✗ ' + str(result)}")
    time.sleep(1.0)

    log("\n[5.2] 按协议顺序设置 CH1 参数 (泵头→软管→模式→回吸→方向)...")
    params = [
        (1000, 5, "泵头型号=5 (n000)"),
        (1004, 1, "软管型号=1 (n004)"),
        (1006, 0, "运行模式=0 (n006)"),
        (1005, 0, "回吸角度=0 (n005)"),
        (1002, 0, "方向=0 (n002)"),
    ]
    for addr, val, name in params:
        result = _pump._write_register(addr, val)
        log(f"  {name}: {'✓' if result else '✗ ' + str(result)}")
        time.sleep(0.3)

    log("\n[5.3] 测试单通道启停地址 1001(n001)...")
    result = _pump._write_register(1001, 0)
    log(f"  1001=0 (单通道停): {'✓' if result else '✗ ' + str(result)}")
    time.sleep(0.5)
    result = _pump._write_register(1001, 1)
    log(f"  1001=1 (单通道启): {'✓' if result else '✗ ' + str(result)}")
    time.sleep(0.5)

    log("\n  等待5秒，请观察泵是否转动...")
    for i in range(5):
        time.sleep(1)
        print(f"  {5-i}...", end="", flush=True)
    print()
    if _auto_answer:
        log("  [auto] 假设泵转动")
        moved = True
    else:
        ans = input("  泵是否转动？(y/n): ").strip().lower()
        moved = ans == "y"

    log("\n[5.4] 停止 (写0到1001)...")
    _pump._write_register(1001, 0)
    time.sleep(0.5)
    _pump._write_register(16, 0)

    log("\n[5.5] 对比: 全局地址16启动 vs 单通道1001启动...")
    log("  方案A: 先 16=1 全局启动")
    _pump._write_register(16, 0)
    time.sleep(0.5)
    _pump._write_register(16, 1)
    log("  等待3秒...")
    time.sleep(3)
    if _auto_answer:
        log("  [auto] 假设泵转动")
        a_moved = True
    else:
        ans = input("  方案A (全局16) 泵是否转动？(y/n): ").strip().lower()
        a_moved = ans == "y"
    _pump._write_register(16, 0)
    time.sleep(0.5)

    log(f"\n[Step5 结果] 单通道1001: {'✅' if moved else '❌'}, 全局16: {'✅' if a_moved else '❌'}")
    return moved or a_moved


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default="COM10")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--yes", action="store_true", help="自动回答y")
    parser.add_argument("--step", type=int, choices=[1,2,3,4,5])
    args = parser.parse_args()
    global _auto_answer
    _auto_answer = args.yes

    log("=" * 60)
    log("LabSmart 蠕动泵诊断")
    log("=" * 60)

    s1 = s2 = s3 = s4 = s5 = False

    try:
        if args.step is None or args.step == 1:
            s1 = step1_serial_basic(args.port, args.force)
            if not s1:
                return 1

        if args.step is None or args.step == 2:
            s2 = step2_write_test()

        if args.step is None or args.step == 3:
            s3 = step3_read_test()

        if args.step is None or args.step == 4:
            s4 = step4_probe_addresses()

        if args.step is None or args.step == 5:
            s5 = step5_correct_sequence()

    finally:
        log("\n清理资源...")
        if _pump:
            try:
                _pump.stop_all()
                _pump.disconnect()
                log("  ✓ 泵已停止")
            except:
                pass
        try:
            _serial_manager.release_port(args.port)
        except:
            pass

    log("\n========== 诊断结果 ==========")
    log(f"Step1: {'✅ 通过' if s1 else '❌ 失败'}")
    if args.step is None or args.step >= 2:
        log(f"Step2: {'✅ 通过' if s2 else '❌ 失败'}")
    if args.step is None or args.step >= 3:
        log(f"Step3: {'✅ 通过' if s3 else '❌ 失败'}")
    if args.step is None or args.step >= 4:
        log(f"Step4: {'✅ 通过' if s4 else '❌ 失败'}")
    if args.step is None or args.step >= 5:
        log(f"Step5: {'✅ 通过' if s5 else '❌ 失败'}")
    return 0


if __name__ == "__main__":
    import atexit
    def cleanup():
        try:
            cleanup_all_serial_ports()
        except:
            pass
    atexit.register(cleanup)
    sys.exit(main())