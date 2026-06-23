"""
数据加载路径定义

comprehensive_factor 模块专用数据路径配置。
遵循 PROJECT.md 跨模块数据路径规范，读取统一数据源。

更新历史（2026-05-27）：
- v2.7: 数据路径从 cache/factor_data/ 改为 data_fetchers/result/factor_ic_data.json.gz
- 统一数据源架构：factor_ic_data.json.gz 包含行情+因子+收益数据
"""

from pathlib import Path


# 统一数据源路径（遵循 PROJECT.md 跨模块数据路径规范）
DEFAULT_DATA_SOURCE = Path(__file__).parent.parent.parent / "data_fetchers" / "result" / "factor_ic_data.parquet"

# IC 结果目录（comprehensive_factor 依赖）
DEFAULT_IC_RESULT_DIR = Path(__file__).parent.parent.parent / "factor_ic" / "result"

# 历史路径（已废弃，保留用于向后兼容检查）
_DEPRECATED_CACHE_DIR = Path(__file__).parent.parent.parent / "cache" / "factor_data"
