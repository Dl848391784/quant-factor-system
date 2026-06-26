"""
数据加载路径定义

comprehensive_factor 模块专用数据路径配置。
遵循 PROJECT.md 跨模块数据路径规范，读取统一数据源。

更新历史（2026-05-27）：
- v2.7: 数据路径从 cache/factor_data/ 改为 data_fetchers/result/factor_ic_data.json.gz
- 统一数据源架构：factor_ic_data.json.gz 包含行情+因子+收益数据
"""

from pathlib import Path

# Pipeline 感知路径（从 paths.py 导入）
from paths import COMPREHENSIVE_FACTOR_RESULT, FACTOR_IC_DATA, FACTOR_IC_RESULT  # noqa: E402


# 统一数据源路径（pipeline 感知）
DEFAULT_DATA_SOURCE = FACTOR_IC_DATA

# IC 结果目录（pipeline 感知，comprehensive_factor 依赖）
DEFAULT_IC_RESULT_DIR = FACTOR_IC_RESULT

# comprehensive_factor 输出目录（pipeline 感知）
COMPREHENSIVE_OUTPUT_DIR = COMPREHENSIVE_FACTOR_RESULT

# 历史路径（已废弃，保留用于向后兼容检查）
_DEPRECATED_CACHE_DIR = Path(__file__).parent.parent.parent / "cache" / "factor_data"
