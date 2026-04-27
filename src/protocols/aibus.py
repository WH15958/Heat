"""
AIBUS协议通信模块

实现宇电AI系列仪表的AIBUS通信协议。
基于《宇电单回路测量控制仪表通讯协议说明》V9.3版本。

协议特点：
- 指令长度固定：发送8字节，接收10字节
- 支持读/写参数
- 写参数同时返回测量值，不破坏读周期
- 地址范围：0-80，最多连接81台仪表
"""

import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional, Tuple, Union
import logging
import time

import serial

logger = logging.getLogger(__name__)


class AIBUSCommand(IntEnum):
    """AIBUS命令代码"""
    READ = 0x52
    WRITE = 0x43


class AlarmStatus(IntEnum):
    """报警状态位定义"""
    HIAL = 0x01
    LOAL = 0x02
    DHAL = 0x04
    DLAL = 0x08
    ORAL = 0x10
    AL1_ACTION = 0x20
    AL2_ACTION = 0x40


@dataclass
class AIBUSResponse:
    """AIBUS响应数据结构"""
    pv: float
    sv: float
    mv: int
    alarm_status: int
    param_value: int
    checksum: int
    raw_data: bytes
    
    @property
    def is_alarm_hial(self) -> bool:
        """上限报警"""
        return bool(self.alarm_status & AlarmStatus.HIAL)
    
    @property
    def is_alarm_loal(self) -> bool:
        """下限报警"""
        return bool(self.alarm_status & AlarmStatus.LOAL)
    
    @property
    def is_alarm_dhal(self) -> bool:
        """正偏差报警"""
        return bool(self.alarm_status & AlarmStatus.DHAL)
    
    @property
    def is_alarm_dlal(self) -> bool:
        """负偏差报警"""
        return bool(self.alarm_status & AlarmStatus.DLAL)
    
    @property
    def is_alarm_oral(self) -> bool:
        """输入超量程报警"""
        return bool(self.alarm_status & AlarmStatus.ORAL)
    
    @property
    def alarm_description(self) -> list:
        """获取报警描述列表"""
        alarms = []
        if self.is_alarm_hial:
            alarms.append("上限报警(HIAL)")
        if self.is_alarm_loal:
            alarms.append("下限报警(LoAL)")
        if self.is_alarm_dhal:
            alarms.append("正偏差报警(dHAL)")
        if self.is_alarm_dlal:
            alarms.append("负偏差报警(dLAL)")
        if self.is_alarm_oral:
            alarms.append("输入超量程报警(orAL)")
        return alarms


class AIBUSProtocol:
    """
    AIBUS协议实现类
    
    实现宇电AI系列仪表的AIBUS通信协议，支持参数读写操作。
    
    协议帧格式：
    - 读指令：地址(2) + 命令(1) + 参数代号(1) + 固定值(2) + 校验和(2) = 8字节
    - 写指令：地址(2) + 命令(1) + 参数代号(1) + 写入值(2) + 校验和(2) = 8字节
    - 响应：测量值(2) + 设定值(2) + MV/状态(2) + 参数值(2) + 校验和(2) = 10字节
    
    Attributes:
        serial_port: pyserial串口对象
        address: 仪表地址(0-80)
        timeout: 通信超时时间(秒)
    """
    
    INVALID_PARAM_VALUE = 32767
    
    def __init__(self, port: str, address: int = 0, 
                 baudrate: int = 9600, 
                 timeout: float = 1.0,
                 bytesize: int = 8,
                 parity: str = 'N',
                 stopbits: int = 1):
        """
        初始化AIBUS协议实例
        
        Args:
            port: 串口号（如'COM3'或'/dev/ttyUSB0'）
            address: 仪表地址，范围0-80
            baudrate: 波特率，默认9600
            timeout: 通信超时时间(秒)
            bytesize: 数据位，默认8
            parity: 校验位，'N'无校验，'E'偶校验，'O'奇校验
            stopbits: 停止位，默认1
        """
        if not 0 <= address <= 80:
            raise ValueError(f"Address must be 0-80, got {address}")
        
        self._port = port
        self._address = address
        self._baudrate = baudrate
        self._timeout = timeout
        self._bytesize = bytesize
        self._parity = parity
        self._stopbits = stopbits
        self._serial: Optional[serial.Serial] = None
        self._logger = logging.getLogger(f"{__name__}.AIBUS[{address}]")
        
    @property
    def address(self) -> int:
        """获取仪表地址"""
        return self._address
    
    @address.setter
    def address(self, value: int):
        """设置仪表地址"""
        if not 0 <= value <= 80:
            raise ValueError(f"Address must be 0-80, got {value}")
        self._address = value
    
    @property
    def is_open(self) -> bool:
        """检查串口是否打开"""
        return self._serial is not None and self._serial.is_open
    
    def open(self) -> bool:
        """
        打开串口连接
        
        Returns:
            bool: 打开成功返回True
        
        Raises:
            serial.SerialException: 串口打开失败
        """
        if self.is_open:
            return True
            
        try:
            self._serial = serial.Serial(
                port=self._port,
                baudrate=self._baudrate,
                bytesize=self._bytesize,
                parity=self._parity,
                stopbits=self._stopbits,
                timeout=self._timeout
            )
            self._logger.info(f"Serial port opened: {self._port}")
            return True
        except serial.SerialException as e:
            self._logger.error(f"Failed to open serial port: {e}")
            raise
    
    def close(self) -> bool:
        """
        关闭串口连接
        
        Returns:
            bool: 关闭成功返回True
        """
        if self._serial is not None:
            try:
                if self._serial.is_open:
                    self._serial.close()
                self._logger.info("Serial port closed")
            except Exception as e:
                self._logger.error(f"Error closing serial port: {e}")
                return False
            finally:
                self._serial = None
        return True
    
    def _build_address_bytes(self) -> bytes:
        """
        构建地址字节
        
        地址指令为两个相同的字节，值为(仪表地址 + 0x80)
        
        Returns:
            bytes: 2字节地址
        """
        addr_byte = self._address + 0x80
        return bytes([addr_byte, addr_byte])
    
    def _calculate_read_checksum(self, param_code: int) -> int:
        """
        计算读指令校验和
        
        校验和 = 参数代号 * 256 + 82(0x52) + 仪表地址
        
        Args:
            param_code: 参数代号
        
        Returns:
            int: 16位校验和
        """
        return (param_code * 256 + AIBUSCommand.READ + self._address) & 0xFFFF
    
    def _calculate_write_checksum(self, param_code: int, value: int) -> int:
        """
        计算写指令校验和
        
        校验和 = 参数代号 * 256 + 67(0x43) + 写入值 + 仪表地址
        
        Args:
            param_code: 参数代号
            value: 写入值
        
        Returns:
            int: 16位校验和
        """
        return (param_code * 256 + AIBUSCommand.WRITE + value + self._address) & 0xFFFF
    
    def _calculate_response_checksum(self, pv: int, sv: int, 
                                     mv_status: int, param_value: int) -> int:
        """
        计算响应校验和
        
        校验和 = 测量值 + 设定值 + (报警状态*256 + MV) + 参数值 + 地址
        
        Args:
            pv: 测量值
            sv: 设定值
            mv_status: MV和状态字节组合
            param_value: 参数值
        
        Returns:
            int: 16位校验和
        """
        return (pv + sv + mv_status + param_value + self._address) & 0xFFFF
    
    def _build_read_command(self, param_code: int) -> bytes:
        """
        构建读参数指令
        
        帧格式：地址(2) + 命令(0x52) + 参数代号(1) + 0x0000(2) + 校验和(2)
        
        Args:
            param_code: 参数代号
        
        Returns:
            bytes: 8字节指令
        """
        checksum = self._calculate_read_checksum(param_code)
        
        frame = bytearray()
        frame.extend(self._build_address_bytes())
        frame.append(AIBUSCommand.READ)
        frame.append(param_code)
        frame.extend([0x00, 0x00])
        frame.extend(struct.pack('<H', checksum))
        
        return bytes(frame)
    
    def _build_write_command(self, param_code: int, value: int) -> bytes:
        """
        构建写参数指令
        
        帧格式：地址(2) + 命令(0x43) + 参数代号(1) + 写入值(2) + 校验和(2)
        
        Args:
            param_code: 参数代号
            value: 写入值（16位有符号整数）
        
        Returns:
            bytes: 8字节指令
        """
        if not -32768 <= value <= 32767:
            raise ValueError(f"Value must be in range [-32768, 32767], got {value}")
        
        value_unsigned = value if value >= 0 else (value + 65536)
        checksum = self._calculate_write_checksum(param_code, value_unsigned)
        
        frame = bytearray()
        frame.extend(self._build_address_bytes())
        frame.append(AIBUSCommand.WRITE)
        frame.append(param_code)
        frame.extend(struct.pack('<H', value_unsigned))
        frame.extend(struct.pack('<H', checksum))
        
        return bytes(frame)
    
    def _parse_response(self, data: bytes) -> AIBUSResponse:
        """
        解析响应数据
        
        响应格式：测量值(2) + 设定值(2) + MV(1) + 状态(1) + 参数值(2) + 校验和(2) = 10字节
        
        Args:
            data: 10字节响应数据
        
        Returns:
            AIBUSResponse: 解析后的响应对象
        
        Raises:
            ValueError: 数据长度错误或校验失败
        """
        if len(data) != 10:
            raise ValueError(f"Response length must be 10 bytes, got {len(data)}")
        
        pv_raw = struct.unpack('<H', data[0:2])[0]
        sv_raw = struct.unpack('<H', data[2:4])[0]
        mv = data[4]
        alarm_status = data[5]
        param_value_raw = struct.unpack('<H', data[6:8])[0]
        checksum_raw = struct.unpack('<H', data[8:10])[0]
        
        pv = pv_raw if pv_raw < 32768 else pv_raw - 65536
        sv = sv_raw if sv_raw < 32768 else sv_raw - 65536
        param_value = param_value_raw if param_value_raw < 32768 else param_value_raw - 65536
        
        calculated_checksum = self._calculate_response_checksum(
            pv_raw, sv_raw, 
            (alarm_status << 8) | mv, 
            param_value_raw
        )
        
        if calculated_checksum != checksum_raw:
            self._logger.warning(
                f"Checksum mismatch: calculated={calculated_checksum:04X}, "
                f"received={checksum_raw:04X}"
            )
            raise IOError(
                f"AIBUS checksum mismatch: calculated={calculated_checksum:04X}, "
                f"received={checksum_raw:04X}"
            )
        
        return AIBUSResponse(
            pv=pv,
            sv=sv,
            mv=mv,
            alarm_status=alarm_status,
            param_value=param_value,
            checksum=checksum_raw,
            raw_data=data
        )
    
    def _send_and_receive(self, command: bytes) -> AIBUSResponse:
        """
        发送指令并接收响应
        
        Args:
            command: 8字节指令
        
        Returns:
            AIBUSResponse: 解析后的响应
        
        Raises:
            IOError: 通信错误
        """
        if not self.is_open:
            raise IOError("Serial port is not open")
        
        self._serial.reset_input_buffer()
        self._serial.reset_output_buffer()
        
        self._serial.write(command)
        self._serial.flush()
        self._logger.debug(f"Sent: {command.hex().upper()}")
        
        response = self._serial.read(10)
        self._logger.debug(f"Received: {response.hex().upper()}")
        
        if len(response) != 10:
            raise IOError(
                f"Response timeout or incomplete: expected 10 bytes, got {len(response)}"
            )
        
        return self._parse_response(response)
    
    def read_parameter(self, param_code: int, 
                       decimal_places: int = 0) -> Tuple[float, AIBUSResponse]:
        """
        读取参数值
        
        Args:
            param_code: 参数代号（参见参数代号表）
            decimal_places: 小数位数（用于显示值转换）
        
        Returns:
            Tuple[float, AIBUSResponse]: (参数值, 完整响应对象)
        
        Raises:
            IOError: 通信错误
            ValueError: 参数无效（返回值为32767）
        """
        command = self._build_read_command(param_code)
        response = self._send_and_receive(command)
        
        if response.param_value == self.INVALID_PARAM_VALUE:
            raise ValueError(
                f"Invalid parameter code: {param_code} (device returned 32767)"
            )
        
        display_value = response.param_value / (10 ** decimal_places)
        return display_value, response
    
    def write_parameter(self, param_code: int, value: float,
                       decimal_places: int = 0) -> AIBUSResponse:
        """
        写入参数值
        
        Args:
            param_code: 参数代号（参见参数代号表）
            value: 要写入的值
            decimal_places: 小数位数（用于值转换）
        
        Returns:
            AIBUSResponse: 设备响应（包含当前测量值等信息）
        
        Raises:
            IOError: 通信错误
        """
        int_value = int(round(value * (10 ** decimal_places)))
        command = self._build_write_command(param_code, int_value)
        return self._send_and_receive(command)
    
    def read_pv_sv(self, decimal_places: int = 1) -> Tuple[float, float, int, int]:
        """
        快速读取测量值(PV)和设定值(SV)
        
        通过读取参数代号0（给定值），同时获取PV和SV。
        
        Args:
            decimal_places: 小数位数，默认1（对应dPt=1），可通过读取参数代号8(dPt)获取
        
        Returns:
            Tuple[float, float, int, int]: (测量值, 设定值, MV输出, 报警状态)
        """
        _, response = self.read_parameter(0)
        divisor = 10 ** decimal_places
        return response.pv / divisor, response.sv / divisor, response.mv, response.alarm_status
    
    def __enter__(self):
        """上下文管理器入口"""
        self.open()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器退出"""
        self.close()
        return False
