"""
报告模块
"""

from .report_generator import (
    ReportGenerator,
    ChartGenerator,
    StatisticsResult,
    calculate_statistics,
)

__all__ = [
    'ReportGenerator',
    'ChartGenerator',
    'StatisticsResult',
    'calculate_statistics',
]
