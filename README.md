# Heat - 自动化控制系统

基于Python的实验室自动化控制系统，支持多设备协同控制、数据监控与报告生成。

## 功能特性

- **设备控制**：加热器温度控制（支持多设备并行）
- **通信协议**：AIBUS协议自主实现（不依赖厂商DLL）
- **数据监控**：实时数据采集与存储
- **报告生成**：HTML格式报告与温度曲线图
- **模块化设计**：易于扩展新设备

## 目录结构

```
Heat/
├── config/                 # 配置文件
│   └── system_config.yaml
├── src/                    # 源代码
│   ├── devices/           # 设备驱动
│   │   ├── base_device.py # 设备基类
│   │   └── heater.py      # 加热器驱动
│   ├── protocols/         # 通信协议
│   │   ├── aibus.py       # AIBUS协议
│   │   └── parameters.py  # 参数定义
│   ├── monitor/           # 数据监控
│   ├── reports/           # 报告生成
│   └── utils/             # 工具函数
├── scripts/               # 控制脚本
│   ├── simple_control.py
│   ├── dual_heater_control.py
│   └── temperature_experiment.py
├── tests/                 # 测试脚本
├── docs/                  # 文档
└── reference paper/       # 参考文献
```

## 安装

```bash
# 克隆仓库
git clone https://gitee.com/wh158958/heat.git
cd heat

# 创建虚拟环境
python -m venv venv
venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt
```

## 快速开始

### 1. 测试硬件连接

```bash
python tests/test_hardware.py
```

### 2. 简单温度控制

```bash
python scripts/simple_control.py
```

### 3. 温度实验（带报告生成）

```bash
python scripts/temperature_experiment.py
```

## 配置说明

编辑 `config/system_config.yaml`：

```yaml
heaters:
  - device_id: "heater1"
    name: "主加热器"
    connection:
      port: "COM3"        # 串口号
      baudrate: 9600      # 波特率
      address: 1          # 设备地址
    decimal_places: 1     # 小数位数
    safety_limit: 450.0   # 安全限温
```

## 扩展新设备

1. 继承 `BaseDevice` 基类

```python
from src.devices.base_device import BaseDevice

class PumpDevice(BaseDevice):
    def connect(self):
        # 实现连接逻辑
        pass
    
    def read_data(self):
        # 实现数据读取
        pass
```

2. 添加到配置文件

3. 在主程序中调用

## 技术栈

- **Python 3.8+**
- **pyserial** - 串口通信
- **matplotlib** - 数据可视化
- **PyYAML** - 配置管理

## 通信协议

本项目实现了宇电AIBUS通信协议，支持：

- 读取PV（测量值）、SV（设定值）、MV（输出值）
- 设定目标温度
- 设备运行控制（启动/停止/保持）

详见：[docs/presentation.md](docs/presentation.md)

## 许可证

MIT License

## 贡献

欢迎提交 Issue 和 Pull Request！

## 联系方式

- Gitee: https://gitee.com/wh158958
- GitHub: https://github.com/WH15958
