"""
MODBUS RTU协议通信模块

实现标准的MODBUS RTU通信协议，用于蠕动泵等设备的通信。

协议特点：
- RTU模式（Remote Terminal Unit）
- 支持功能码：03(读保持寄存器)、06(写单个寄存器)、16/0x10(写多个寄存器)
- CRC-16校验
- 支持浮点数和整数数据类型
"""

import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import List, Optional, Tuple, Union
import logging
import time

import serial

logger = logging.getLogger(__name__)


class ModbusFunction(IntEnum):
    """MODBUS功能码"""
    READ_HOLDING_REGISTERS = 0x03
    WRITE_SINGLE_REGISTER = 0x06
    WRITE_MULTIPLE_REGISTERS = 0x10
    READ_INPUT_REGISTERS = 0x04
    READ_COILS = 0x01
    WRITE_SINGLE_COIL = 0x05
    WRITE_MULTIPLE_COILS = 0x0F


class ModbusException(IntEnum):
    """MODBUS异常码"""
    ILLEGAL_FUNCTION = 0x01
    ILLEGAL_DATA_ADDRESS = 0x02
    ILLEGAL_DATA_VALUE = 0x03
    SLAVE_DEVICE_FAILURE = 0x04
    ACKNOWLEDGE = 0x05
    SLAVE_DEVICE_BUSY = 0x06
    MEMORY_PARITY_ERROR = 0x08
    GATEWAY_PATH_UNAVAILABLE = 0x0A
    GATEWAY_TARGET_DEVICE_FAILED = 0x0B


@dataclass
class ModbusResponse:
    """MODBUS响应数据结构"""
    slave_address: int
    function_code: int
    data: bytes
    exception_code: Optional[int] = None
    raw_data: bytes = b''
    
    @property
    def is_exception(self) -> bool:
        """是否为异常响应"""
        return self.function_code >= 0x80
    
    @property
    def exception_description(self) -> str:
        """获取异常描述"""
        if not self.is_exception or self.exception_code is None:
            return ""
        descriptions = {
            ModbusException.ILLEGAL_FUNCTION: "非法功能码",
            ModbusException.ILLEGAL_DATA_ADDRESS: "非法数据地址",
            ModbusException.ILLEGAL_DATA_VALUE: "非法数据值",
            ModbusException.SLAVE_DEVICE_FAILURE: "从站设备故障",
            ModbusException.ACKNOWLEDGE: "确认",
            ModbusException.SLAVE_DEVICE_BUSY: "从站设备忙",
            ModbusException.MEMORY_PARITY_ERROR: "内存奇偶校验错误",
        }
        return descriptions.get(self.exception_code, f"未知异常({self.exception_code})")


class ModbusRTUProtocol:
    """
    MODBUS RTU协议实现类
    
    实现标准的MODBUS RTU通信协议，支持读写保持寄存器操作。
    
    Example:
        >>> protocol = ModbusRTUProtocol(port="COM3", baudrate=9600)
        >>> protocol.connect()
        >>> values = protocol.read_holding_registers(slave_address=1, start_address=0, count=10)
        >>> protocol.write_single_register(slave_address=1, address=0, value=100)
        >>> protocol.disconnect()
    """
    
    FRAME_GAP = 0.0035
    
    def __init__(
        self,
        port: str,
        baudrate: int = 9600,
        parity: str = 'E',
        stopbits: int = 1,
        bytesize: int = 8,
        timeout: float = 2.0,
    ):
        """
        初始化MODBUS RTU协议
        
        Args:
            port: 串口名称
            baudrate: 波特率
            parity: 校验位 ('E'=偶校验, 'O'=奇校验, 'N'=无校验)
            stopbits: 停止位
            bytesize: 数据位
            timeout: 读取超时时间(秒)
        """
        self.port = port
        self.baudrate = baudrate
        self.parity = parity
        self.stopbits = stopbits
        self.bytesize = bytesize
        self.timeout = timeout
        self._serial: Optional[serial.Serial] = None
        self._connected = False
    
    @property
    def is_connected(self) -> bool:
        """检查是否已连接"""
        return self._connected and self._serial is not None and self._serial.is_open
    
    def connect(self) -> bool:
        """
        连接串口
        
        Returns:
            bool: 连接成功返回True
        """
        try:
            self._serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                parity=self.parity,
                stopbits=self.stopbits,
                bytesize=self.bytesize,
                timeout=self.timeout,
            )
            self._connected = True
            logger.info(f"MODBUS RTU connected to {self.port} at {self.baudrate}bps")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to {self.port}: {e}")
            self._connected = False
            return False
    
    def disconnect(self):
        """断开串口连接"""
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None
        self._connected = False
        logger.info("MODBUS RTU disconnected")
    
    @staticmethod
    def calculate_crc(data: bytes) -> int:
        """
        计算CRC-16校验码
        
        多项式: 0xA001 (MODBUS标准)
        
        Args:
            data: 需要计算CRC的数据
        
        Returns:
            int: 16位CRC值
        """
        crc = 0xFFFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 0x0001:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return crc
    
    @staticmethod
    def crc_to_bytes(crc: int) -> bytes:
        """
        将CRC值转换为字节（低字节在前）
        
        Args:
            crc: CRC值
        
        Returns:
            bytes: CRC字节序列
        """
        return bytes([crc & 0xFF, (crc >> 8) & 0xFF])
    
    def _send_frame(self, frame: bytes) -> bool:
        """
        发送数据帧
        
        Args:
            frame: 完整的数据帧（不含CRC）
        
        Returns:
            bool: 发送成功返回True
        """
        if not self.is_connected:
            logger.error("Serial port not connected")
            return False
        
        crc = self.calculate_crc(frame)
        full_frame = frame + self.crc_to_bytes(crc)
        
        try:
            self._serial.reset_input_buffer()
            self._serial.reset_output_buffer()
            self._serial.write(full_frame)
            self._serial.flush()
            return True
        except Exception as e:
            logger.error(f"Failed to send frame: {e}")
            return False
    
    def _receive_frame(self, expected_length: int) -> Optional[bytes]:
        """
        接收数据帧
        
        Args:
            expected_length: 期望接收的字节数
        
        Returns:
            Optional[bytes]: 接收到的数据帧，失败返回None
        """
        if not self.is_connected:
            return None
        
        try:
            response = self._serial.read(expected_length)
            if len(response) < expected_length:
                logger.warning(f"Timeout: expected {expected_length} bytes, got {len(response)}")
                return None
            return response
        except Exception as e:
            logger.error(f"Failed to receive frame: {e}")
            return None
    
    def _validate_response(self, response: bytes) -> bool:
        """
        验证响应帧的CRC
        
        Args:
            response: 响应数据帧
        
        Returns:
            bool: CRC正确返回True
        """
        if len(response) < 4:
            return False
        
        data = response[:-2]
        received_crc = response[-2] | (response[-1] << 8)
        calculated_crc = self.calculate_crc(data)
        
        return received_crc == calculated_crc
    
    def read_holding_registers(
        self,
        slave_address: int,
        start_address: int,
        count: int,
    ) -> Optional[List[int]]:
        """
        读保持寄存器（功能码0x03）
        
        Args:
            slave_address: 从站地址
            start_address: 起始地址
            count: 寄存器数量
        
        Returns:
            Optional[List[int]]: 寄存器值列表，失败返回None
        """
        frame = bytes([
            slave_address,
            ModbusFunction.READ_HOLDING_REGISTERS,
            (start_address >> 8) & 0xFF,
            start_address & 0xFF,
            (count >> 8) & 0xFF,
            count & 0xFF,
        ])
        
        if not self._send_frame(frame):
            return None
        
        expected_length = 3 + count * 2 + 2
        response = self._receive_frame(expected_length)
        
        if response is None:
            return None
        
        if not self._validate_response(response):
            logger.error("CRC validation failed")
            return None
        
        func_code = response[1]
        if func_code >= 0x80:
            exception_code = response[2]
            logger.error(f"MODBUS exception: {ModbusException(exception_code).name}")
            return None
        
        byte_count = response[2]
        data = response[3:3 + byte_count]
        
        values = []
        for i in range(0, len(data), 2):
            value = (data[i] << 8) | data[i + 1]
            values.append(value)
        
        return values
    
    def write_single_register(
        self,
        slave_address: int,
        address: int,
        value: int,
    ) -> bool:
        """
        写单个寄存器（功能码0x06）
        
        Args:
            slave_address: 从站地址
            address: 寄存器地址
            value: 写入值
        
        Returns:
            bool: 写入成功返回True
        """
        frame = bytes([
            slave_address,
            ModbusFunction.WRITE_SINGLE_REGISTER,
            (address >> 8) & 0xFF,
            address & 0xFF,
            (value >> 8) & 0xFF,
            value & 0xFF,
        ])
        
        if not self._send_frame(frame):
            return False
        
        response = self._receive_frame(8)
        
        if response is None:
            return False
        
        if not self._validate_response(response):
            logger.error("CRC validation failed")
            return False
        
        func_code = response[1]
        if func_code >= 0x80:
            exception_code = response[2]
            logger.error(f"MODBUS exception: {ModbusException(exception_code).name}")
            return False
        
        return True
    
    def write_multiple_registers(
        self,
        slave_address: int,
        start_address: int,
        values: List[int],
    ) -> bool:
        """
        写多个寄存器（功能码0x10）
        
        Args:
            slave_address: 从站地址
            start_address: 起始地址
            values: 写入值列表
        
        Returns:
            bool: 写入成功返回True
        """
        count = len(values)
        byte_count = count * 2
        
        frame = bytes([
            slave_address,
            ModbusFunction.WRITE_MULTIPLE_REGISTERS,
            (start_address >> 8) & 0xFF,
            start_address & 0xFF,
            (count >> 8) & 0xFF,
            count & 0xFF,
            byte_count,
        ])
        
        for value in values:
            frame += bytes([(value >> 8) & 0xFF, value & 0xFF])
        
        if not self._send_frame(frame):
            return False
        
        response = self._receive_frame(8)
        
        if response is None:
            return False
        
        if not self._validate_response(response):
            logger.error("CRC validation failed")
            return False
        
        func_code = response[1]
        if func_code >= 0x80:
            exception_code = response[2]
            logger.error(f"MODBUS exception: {ModbusException(exception_code).name}")
            return False
        
        return True
    
    def write_float_register(
        self,
        slave_address: int,
        start_address: int,
        value: float,
    ) -> bool:
        """
        写浮点数到寄存器（占用2个寄存器，4字节）
        
        Args:
            slave_address: 从站地址
            start_address: 起始地址
            value: 浮点数值
        
        Returns:
            bool: 写入成功返回True
        """
        float_bytes = struct.pack('>f', value)
        values = [
            (float_bytes[0] << 8) | float_bytes[1],
            (float_bytes[2] << 8) | float_bytes[3],
        ]
        return self.write_multiple_registers(slave_address, start_address, values)
    
    def read_float_register(
        self,
        slave_address: int,
        start_address: int,
    ) -> Optional[float]:
        """
        读浮点数寄存器（占用2个寄存器，4字节）
        
        Args:
            slave_address: 从站地址
            start_address: 起始地址
        
        Returns:
            Optional[float]: 浮点数值，失败返回None
        """
        values = self.read_holding_registers(slave_address, start_address, 2)
        if values is None or len(values) < 2:
            return None
        
        float_bytes = bytes([
            (values[0] >> 8) & 0xFF,
            values[0] & 0xFF,
            (values[1] >> 8) & 0xFF,
            values[1] & 0xFF,
        ])
        
        return struct.unpack('>f', float_bytes)[0]
