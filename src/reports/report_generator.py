"""
数据报告生成模块

提供实验数据报告的生成功能，支持HTML和PDF格式。
"""

import base64
import io
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
import logging
import statistics

logger = logging.getLogger(__name__)


@dataclass
class StatisticsResult:
    """统计结果"""
    count: int
    mean: float
    std: float
    min: float
    max: float
    median: float


def calculate_statistics(values: List[float]) -> StatisticsResult:
    """计算统计值"""
    if not values:
        return StatisticsResult(0, 0, 0, 0, 0, 0)
    
    return StatisticsResult(
        count=len(values),
        mean=statistics.mean(values),
        std=statistics.stdev(values) if len(values) > 1 else 0,
        min=min(values),
        max=max(values),
        median=statistics.median(values)
    )


class ChartGenerator:
    """
    图表生成器
    
    使用matplotlib生成数据图表。
    """
    
    @staticmethod
    def generate_temperature_chart(data_points: List[Any],
                                   title: str = "Temperature Monitor",
                                   output_path: Optional[str] = None) -> Optional[str]:
        """
        生成温度监控图表
        
        Args:
            data_points: 数据点列表
            title: 图表标题
            output_path: 输出路径，如果为None则返回base64编码
        
        Returns:
            str: 图片路径或base64编码字符串
        """
        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            import matplotlib.dates as mdates
        except ImportError:
            logger.warning("matplotlib not installed, skipping chart generation")
            return None
        
        if not data_points:
            return None
        
        timestamps = [dp.timestamp for dp in data_points]
        pv_values = [dp.pv for dp in data_points]
        sv_values = [dp.sv for dp in data_points]
        
        fig, ax = plt.subplots(figsize=(12, 6))
        
        ax.plot(timestamps, pv_values, 'b-', label='PV (Actual)', linewidth=1.5)
        ax.plot(timestamps, sv_values, 'r--', label='SV (Setpoint)', linewidth=1.5)
        
        ax.set_xlabel('Time')
        ax.set_ylabel('Temperature (°C)')
        ax.set_title(title)
        ax.legend()
        ax.grid(True, alpha=0.3)
        
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        plt.xticks(rotation=45)
        
        plt.tight_layout()
        
        if output_path:
            plt.savefig(output_path, dpi=150, bbox_inches='tight')
            plt.close()
            return output_path
        else:
            buffer = io.BytesIO()
            plt.savefig(buffer, format='png', dpi=150, bbox_inches='tight')
            plt.close()
            buffer.seek(0)
            return base64.b64encode(buffer.read()).decode()
    
    @staticmethod
    def generate_output_chart(data_points: List[Any],
                              title: str = "Output Monitor",
                              output_path: Optional[str] = None) -> Optional[str]:
        """生成输出百分比图表"""
        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            import matplotlib.dates as mdates
        except ImportError:
            return None
        
        if not data_points:
            return None
        
        timestamps = [dp.timestamp for dp in data_points]
        mv_values = [dp.mv for dp in data_points]
        
        fig, ax = plt.subplots(figsize=(12, 4))
        
        ax.fill_between(timestamps, mv_values, alpha=0.3, color='green')
        ax.plot(timestamps, mv_values, 'g-', label='MV (Output %)', linewidth=1.5)
        
        ax.set_xlabel('Time')
        ax.set_ylabel('Output (%)')
        ax.set_title(title)
        ax.legend()
        ax.grid(True, alpha=0.3)
        ax.set_ylim(0, 110)
        
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        plt.xticks(rotation=45)
        
        plt.tight_layout()
        
        if output_path:
            plt.savefig(output_path, dpi=150, bbox_inches='tight')
            plt.close()
            return output_path
        else:
            buffer = io.BytesIO()
            plt.savefig(buffer, format='png', dpi=150, bbox_inches='tight')
            plt.close()
            buffer.seek(0)
            return base64.b64encode(buffer.read()).decode()

    @staticmethod
    def generate_flow_chart(data_points: List[Any],
                            title: str = "Flow Rate Monitor",
                            output_path: Optional[str] = None) -> Optional[str]:
        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            import matplotlib.dates as mdates
        except ImportError:
            return None
        
        if not data_points:
            return None
        
        timestamps = [dp.timestamp for dp in data_points]
        flow_values = [dp.flow_rate for dp in data_points]
        
        fig, ax = plt.subplots(figsize=(12, 4))
        
        ax.fill_between(timestamps, flow_values, alpha=0.3, color='#2196F3')
        ax.plot(timestamps, flow_values, '-', color='#1565C0',
                label='Flow Rate (mL/min)', linewidth=1.5)
        
        ax.set_xlabel('Time')
        ax.set_ylabel('Flow Rate (mL/min)')
        ax.set_title(title)
        ax.legend()
        ax.grid(True, alpha=0.3)
        ax.set_ylim(bottom=0)
        
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        plt.xticks(rotation=45)
        
        plt.tight_layout()
        
        if output_path:
            plt.savefig(output_path, dpi=150, bbox_inches='tight')
            plt.close()
            return output_path
        else:
            buffer = io.BytesIO()
            plt.savefig(buffer, format='png', dpi=150, bbox_inches='tight')
            plt.close()
            buffer.seek(0)
            return base64.b64encode(buffer.read()).decode()


class ReportGenerator:
    """
    报告生成器
    
    生成实验数据报告，支持HTML和PDF格式。
    
    Example:
        >>> generator = ReportGenerator("reports")
        >>> report_path = generator.generate(
        ...     device_id="heater1",
        ...     data_points=data_points,
        ...     title="Heating Experiment Report"
        ... )
    """
    
    HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{title}}</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.6;
            color: #333;
            background-color: #f5f5f5;
            padding: 20px;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        h1 {
            color: #2c3e50;
            border-bottom: 3px solid #3498db;
            padding-bottom: 10px;
            margin-bottom: 20px;
        }
        h2 {
            color: #34495e;
            margin-top: 30px;
            margin-bottom: 15px;
            border-left: 4px solid #3498db;
            padding-left: 10px;
        }
        .meta-info {
            background: #ecf0f1;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
        }
        .meta-info p {
            margin: 5px 0;
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin: 20px 0;
        }
        .stat-card {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 8px;
            text-align: center;
        }
        .stat-card h3 {
            font-size: 14px;
            opacity: 0.9;
            margin-bottom: 5px;
        }
        .stat-card .value {
            font-size: 28px;
            font-weight: bold;
        }
        .stat-card .unit {
            font-size: 12px;
            opacity: 0.8;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }
        th, td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }
        th {
            background-color: #3498db;
            color: white;
        }
        tr:hover {
            background-color: #f5f5f5;
        }
        .chart-container {
            margin: 20px 0;
            text-align: center;
        }
        .chart-container img {
            max-width: 100%;
            height: auto;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }
        .alarm-list {
            background: #fff3cd;
            border-left: 4px solid #ffc107;
            padding: 15px;
            margin: 20px 0;
            border-radius: 0 5px 5px 0;
        }
        .alarm-list h3 {
            color: #856404;
            margin-bottom: 10px;
        }
        .alarm-list ul {
            margin-left: 20px;
        }
        .footer {
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid #ddd;
            text-align: center;
            color: #666;
            font-size: 12px;
        }
        @media print {
            body {
                background: white;
                padding: 0;
            }
            .container {
                box-shadow: none;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>{{title}}</h1>
        
        <div class="meta-info">
            <p><strong>设备ID:</strong> {{device_id}}</p>
            <p><strong>报告生成时间:</strong> {{generated_time}}</p>
            <p><strong>数据时间范围:</strong> {{time_range}}</p>
            <p><strong>数据点数量:</strong> {{data_count}}</p>
        </div>
        
        <h2>统计摘要</h2>
        <div class="stats-grid">
            <div class="stat-card">
                <h3>平均温度 (PV)</h3>
                <div class="value">{{pv_mean}}</div>
                <div class="unit">°C</div>
            </div>
            <div class="stat-card">
                <h3>温度标准差</h3>
                <div class="value">{{pv_std}}</div>
                <div class="unit">°C</div>
            </div>
            <div class="stat-card">
                <h3>最高温度</h3>
                <div class="value">{{pv_max}}</div>
                <div class="unit">°C</div>
            </div>
            <div class="stat-card">
                <h3>最低温度</h3>
                <div class="value">{{pv_min}}</div>
                <div class="unit">°C</div>
            </div>
        </div>
        
        <h2>温度曲线</h2>
        <div class="chart-container">
            {{temperature_chart}}
        </div>
        
        <h2>输出曲线</h2>
        <div class="chart-container">
            {{output_chart}}
        </div>
        
        {{alarm_section}}
        
        <h2>详细数据</h2>
        <table>
            <thead>
                <tr>
                    <th>时间</th>
                    <th>PV (°C)</th>
                    <th>SV (°C)</th>
                    <th>输出 (%)</th>
                    <th>报警状态</th>
                </tr>
            </thead>
            <tbody>
                {{data_rows}}
            </tbody>
        </table>
        
        <div class="footer">
            <p>自动化控制系统 - 数据报告</p>
            <p>Generated at {{generated_time}}</p>
        </div>
    </div>
</body>
</html>
"""
    
    def __init__(self, output_dir: str = "reports"):
        """
        初始化报告生成器
        
        Args:
            output_dir: 报告输出目录
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._logger = logging.getLogger(__name__)
    
    def generate(self,
                 device_id: str,
                 data_points: List[Any],
                 title: str = "Experiment Report",
                 include_charts: bool = True,
                 include_data_table: bool = True,
                 max_table_rows: int = 100) -> str:
        """
        生成HTML报告
        
        Args:
            device_id: 设备ID
            data_points: 数据点列表
            title: 报告标题
            include_charts: 是否包含图表
            include_data_table: 是否包含数据表格
            max_table_rows: 表格最大行数
        
        Returns:
            str: 报告文件路径
        """
        if not data_points:
            raise ValueError("No data points to generate report")
        
        pv_stats = calculate_statistics([dp.pv for dp in data_points])
        sv_stats = calculate_statistics([dp.sv for dp in data_points])
        
        start_time = data_points[0].timestamp
        end_time = data_points[-1].timestamp
        
        temp_chart_html = ""
        output_chart_html = ""
        
        if include_charts:
            temp_chart_b64 = ChartGenerator.generate_temperature_chart(
                data_points,
                title=f"{device_id} - Temperature"
            )
            if temp_chart_b64:
                temp_chart_html = f'<img src="data:image/png;base64,{temp_chart_b64}" alt="Temperature Chart">'
            
            output_chart_b64 = ChartGenerator.generate_output_chart(
                data_points,
                title=f"{device_id} - Output"
            )
            if output_chart_b64:
                output_chart_html = f'<img src="data:image/png;base64,{output_chart_b64}" alt="Output Chart">'
        
        alarm_events = []
        for dp in data_points:
            if dp.alarms:
                alarm_events.append({
                    'time': dp.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                    'alarms': dp.alarms
                })
        
        alarm_section = ""
        if alarm_events:
            alarm_items = "".join([
                f"<li>{e['time']}: {', '.join(e['alarms'])}</li>"
                for e in alarm_events[:20]
            ])
            alarm_section = f"""
            <div class="alarm-list">
                <h3>⚠️ 报警记录</h3>
                <ul>
                    {alarm_items}
                </ul>
            </div>
            """
        
        data_rows = ""
        if include_data_table:
            step = max(1, len(data_points) // max_table_rows)
            sampled_data = data_points[::step][:max_table_rows]
            
            data_rows = "\n".join([
                f"""<tr>
                    <td>{dp.timestamp.strftime('%Y-%m-%d %H:%M:%S')}</td>
                    <td>{dp.pv:.2f}</td>
                    <td>{dp.sv:.2f}</td>
                    <td>{dp.mv}</td>
                    <td>{', '.join(dp.alarms) if dp.alarms else '-'}</td>
                </tr>"""
                for dp in sampled_data
            ])
        
        html = self.HTML_TEMPLATE
        html = html.replace("{{title}}", title)
        html = html.replace("{{device_id}}", device_id)
        html = html.replace("{{generated_time}}", datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        html = html.replace("{{time_range}}", 
            f"{start_time.strftime('%Y-%m-%d %H:%M:%S')} ~ {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        html = html.replace("{{data_count}}", str(len(data_points)))
        html = html.replace("{{pv_mean}}", f"{pv_stats.mean:.2f}")
        html = html.replace("{{pv_std}}", f"{pv_stats.std:.2f}")
        html = html.replace("{{pv_max}}", f"{pv_stats.max:.2f}")
        html = html.replace("{{pv_min}}", f"{pv_stats.min:.2f}")
        html = html.replace("{{temperature_chart}}", temp_chart_html)
        html = html.replace("{{output_chart}}", output_chart_html)
        html = html.replace("{{alarm_section}}", alarm_section)
        html = html.replace("{{data_rows}}", data_rows)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"report_{device_id}_{timestamp}.html"
        report_path = self.output_dir / filename
        
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(html)
        
        self._logger.info(f"Report generated: {report_path}")
        return str(report_path)
    
    def generate_summary(self, 
                        device_id: str,
                        data_points: List[Any]) -> Dict[str, Any]:
        """
        生成数据摘要
        
        Args:
            device_id: 设备ID
            data_points: 数据点列表
        
        Returns:
            Dict: 摘要信息
        """
        if not data_points:
            return {}
        
        pv_stats = calculate_statistics([dp.pv for dp in data_points])
        sv_stats = calculate_statistics([dp.sv for dp in data_points])
        mv_stats = calculate_statistics([float(dp.mv) for dp in data_points])
        
        alarm_count = sum(1 for dp in data_points if dp.alarms)
        
        return {
            'device_id': device_id,
            'data_count': len(data_points),
            'start_time': data_points[0].timestamp.isoformat(),
            'end_time': data_points[-1].timestamp.isoformat(),
            'duration_seconds': (data_points[-1].timestamp - data_points[0].timestamp).total_seconds(),
            'pv_statistics': {
                'mean': pv_stats.mean,
                'std': pv_stats.std,
                'min': pv_stats.min,
                'max': pv_stats.max,
                'median': pv_stats.median,
            },
            'sv_statistics': {
                'mean': sv_stats.mean,
                'std': sv_stats.std,
                'min': sv_stats.min,
                'max': sv_stats.max,
            },
            'mv_statistics': {
                'mean': mv_stats.mean,
                'min': mv_stats.min,
                'max': mv_stats.max,
            },
            'alarm_count': alarm_count,
        }

    COMBINED_HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{title}}</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.6;
            color: #333;
            background-color: #f5f5f5;
            padding: 20px;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        h1 {
            color: #2c3e50;
            border-bottom: 3px solid #3498db;
            padding-bottom: 10px;
            margin-bottom: 20px;
        }
        h2 {
            color: #34495e;
            margin-top: 30px;
            margin-bottom: 15px;
            border-left: 4px solid #3498db;
            padding-left: 10px;
        }
        h3 {
            color: #2c3e50;
            margin-top: 20px;
            margin-bottom: 10px;
        }
        .meta-info {
            background: #ecf0f1;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
        }
        .meta-info p {
            margin: 5px 0;
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin: 20px 0;
        }
        .stat-card {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 8px;
            text-align: center;
        }
        .stat-card h3 {
            font-size: 14px;
            opacity: 0.9;
            margin-bottom: 5px;
            color: white;
        }
        .stat-card .value {
            font-size: 28px;
            font-weight: bold;
        }
        .stat-card .unit {
            font-size: 12px;
            opacity: 0.8;
        }
        .chart-container {
            margin: 20px 0;
            text-align: center;
        }
        .chart-container img {
            max-width: 100%;
            height: auto;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }
        .device-section {
            margin: 30px 0;
            padding: 20px;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            background: #fafafa;
        }
        .device-section h2 {
            margin-top: 0;
        }
        .footer {
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid #ddd;
            text-align: center;
            color: #666;
            font-size: 12px;
        }
        @media print {
            body {
                background: white;
                padding: 0;
            }
            .container {
                box-shadow: none;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>{{title}}</h1>
        
        <div class="meta-info">
            <p><strong>报告生成时间:</strong> {{generated_time}}</p>
            <p><strong>设备数量:</strong> {{device_count}}</p>
            <p><strong>实验时长:</strong> {{duration}}</p>
        </div>
        
        {{device_sections}}
        
        <div class="footer">
            <p>自动化控制系统 - 实验汇总报告</p>
            <p>Generated at {{generated_time}}</p>
        </div>
    </div>
</body>
</html>
"""

    def generate_combined_report(
        self,
        devices_data: Dict[str, List[Any]],
        pump_data: Optional[Dict[str, List[Any]]] = None,
        title: str = "Experiment Summary Report",
        experiment_duration: Optional[float] = None,
    ) -> str:
        if not devices_data and not pump_data:
            raise ValueError("No device data to generate report")

        device_sections_html = []

        for device_id, data_points in devices_data.items():
            if not data_points:
                continue

            pv_stats = calculate_statistics([dp.pv for dp in data_points])

            temp_chart_b64 = ChartGenerator.generate_temperature_chart(
                data_points,
                title=f"{device_id} - Temperature"
            )
            temp_chart_html = ""
            if temp_chart_b64:
                temp_chart_html = f'<div class="chart-container"><img src="data:image/png;base64,{temp_chart_b64}" alt="{device_id} Temperature Chart"></div>'

            output_chart_b64 = ChartGenerator.generate_output_chart(
                data_points,
                title=f"{device_id} - Output"
            )
            output_chart_html = ""
            if output_chart_b64:
                output_chart_html = f'<div class="chart-container"><img src="data:image/png;base64,{output_chart_b64}" alt="{device_id} Output Chart"></div>'

            start_time = data_points[0].timestamp
            end_time = data_points[-1].timestamp

            section = f"""
            <div class="device-section">
                <h2>{device_id}</h2>
                <div class="meta-info">
                    <p><strong>数据点数量:</strong> {len(data_points)}</p>
                    <p><strong>时间范围:</strong> {start_time.strftime('%Y-%m-%d %H:%M:%S')} ~ {end_time.strftime('%Y-%m-%d %H:%M:%S')}</p>
                </div>
                <div class="stats-grid">
                    <div class="stat-card">
                        <h3>平均温度</h3>
                        <div class="value">{pv_stats.mean:.2f}</div>
                        <div class="unit">°C</div>
                    </div>
                    <div class="stat-card">
                        <h3>温度标准差</h3>
                        <div class="value">{pv_stats.std:.2f}</div>
                        <div class="unit">°C</div>
                    </div>
                    <div class="stat-card">
                        <h3>最高温度</h3>
                        <div class="value">{pv_stats.max:.2f}</div>
                        <div class="unit">°C</div>
                    </div>
                    <div class="stat-card">
                        <h3>最低温度</h3>
                        <div class="value">{pv_stats.min:.2f}</div>
                        <div class="unit">°C</div>
                    </div>
                </div>
                <h3>温度曲线</h3>
                {temp_chart_html}
                <h3>输出曲线</h3>
                {output_chart_html}
            </div>
            """
            device_sections_html.append(section)

        if pump_data:
            for device_id, data_points in pump_data.items():
                if not data_points:
                    continue

                flow_stats = calculate_statistics([dp.flow_rate for dp in data_points])
                
                channels = sorted(set(dp.channel for dp in data_points))
                channel_info = ", ".join([f"通道{ch}" for ch in channels])
                
                running_count = sum(1 for dp in data_points if dp.running)
                total_count = len(data_points)

                flow_chart_b64 = ChartGenerator.generate_flow_chart(
                    data_points,
                    title=f"{device_id} - Flow Rate"
                )
                flow_chart_html = ""
                if flow_chart_b64:
                    flow_chart_html = f'<div class="chart-container"><img src="data:image/png;base64,{flow_chart_b64}" alt="{device_id} Flow Chart"></div>'

                start_time = data_points[0].timestamp
                end_time = data_points[-1].timestamp

                section = f"""
                <div class="device-section" style="border-left: 4px solid #2196F3;">
                    <h2>{device_id} (蠕动泵)</h2>
                    <div class="meta-info">
                        <p><strong>数据点数量:</strong> {len(data_points)}</p>
                        <p><strong>时间范围:</strong> {start_time.strftime('%Y-%m-%d %H:%M:%S')} ~ {end_time.strftime('%Y-%m-%d %H:%M:%S')}</p>
                        <p><strong>运行通道:</strong> {channel_info}</p>
                        <p><strong>运行比例:</strong> {running_count}/{total_count} ({running_count*100//max(total_count,1)}%)</p>
                    </div>
                    <div class="stats-grid">
                        <div class="stat-card">
                            <h3>平均流量</h3>
                            <div class="value">{flow_stats.mean:.2f}</div>
                            <div class="unit">mL/min</div>
                        </div>
                        <div class="stat-card">
                            <h3>流量标准差</h3>
                            <div class="value">{flow_stats.std:.2f}</div>
                            <div class="unit">mL/min</div>
                        </div>
                        <div class="stat-card">
                            <h3>最大流量</h3>
                            <div class="value">{flow_stats.max:.2f}</div>
                            <div class="unit">mL/min</div>
                        </div>
                        <div class="stat-card">
                            <h3>最小流量</h3>
                            <div class="value">{flow_stats.min:.2f}</div>
                            <div class="unit">mL/min</div>
                        </div>
                    </div>
                    <h3>流量曲线</h3>
                    {flow_chart_html}
                </div>
                """
                device_sections_html.append(section)

        duration_str = ""
        if experiment_duration is not None:
            mins, secs = divmod(int(experiment_duration), 60)
            duration_str = f"{mins}分{secs}秒"

        html = self.COMBINED_HTML_TEMPLATE
        html = html.replace("{{title}}", title)
        html = html.replace("{{generated_time}}", datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        html = html.replace("{{device_count}}", str(len(devices_data)))
        html = html.replace("{{duration}}", duration_str)
        html = html.replace("{{device_sections}}", "\n".join(device_sections_html))

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"report_summary_{timestamp}.html"
        report_path = self.output_dir / filename

        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(html)

        self._logger.info(f"Combined report generated: {report_path}")
        return str(report_path)
