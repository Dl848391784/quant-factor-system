"""
跨模块路径配置 - 单一来源

所有代码必须 import 此文件获取路径，禁止使用字符串字面量。
违反此规则会导致改一处忘另一处，必翻车。

正确导入方式：
    # 方式 1：通过 pip install -e . 安装项目后使用包导入
    from factor_ic_analyzer.paths import FACTOR_IC_DATA
    
    # 方式 2：通过 PYTHONPATH 环境变量
    # export PYTHONPATH=/path/to/factor_ic_analyzer
    from paths import FACTOR_IC_DATA
    
    # 方式 3：项目根目录下的脚本可直接导入
    from paths import FACTOR_IC_DATA  # paths.py 在根目录

注意：绝对路径示例（如 /home/admin/projects/...）仅供本地开发参考，
正式代码禁止硬编码，应使用包安装或 PYTHONPATH 方式。

稳定性：[experimental] 2026-06-01（待实战验证）
"""

from pathlib import Path


# 项目根目录
PROJECT_ROOT = Path(__file__).parent

# ============================================================================
# 模块输出目录
# ============================================================================

DATA_FETCHERS_RESULT = PROJECT_ROOT / "data_fetchers" / "result"
FACTOR_IC_RESULT = PROJECT_ROOT / "factor_ic" / "result"
BACKTEST_RESULT = PROJECT_ROOT / "backtest" / "result"
COMPREHENSIVE_FACTOR_RESULT = PROJECT_ROOT / "comprehensive_factor" / "result"
SUMMARY_RESULT = PROJECT_ROOT / "summary" / "result"
REVERSE_DISCOVERY_RESULT = PROJECT_ROOT / "reverse_discovery" / "result"

# ============================================================================
# 统一数据源（单一来源原则）
# ============================================================================

# factor_ic_data.json.gz = 行情 + 因子 + 收益数据
# 所有下游模块必须从此文件读取，禁止从其他文件读取收益数据
FACTOR_IC_DATA = DATA_FETCHERS_RESULT / "factor_ic_data.json.gz"

# 外部数据源（因子计算依赖，非统一数据源的一部分）
FINANCIAL_DATA = DATA_FETCHERS_RESULT / "financial_data.json.gz"  # 财务指标数据（方案B基本面动量因子）
FUND_FLOW_DATA = DATA_FETCHERS_RESULT / "fund_flow_data.json.gz"  # 资金流数据（方案C资金流因子，[experimental]）

# 备份文件（仅用于数据备份/历史追溯，禁止作为运行时数据源）
RETURN_DATA_BACKUP = DATA_FETCHERS_RESULT / "return_data.json.gz"
FACTOR_DATA_BACKUP = DATA_FETCHERS_RESULT / "factor_data.json.gz"

# 市值/估值面板（市值中性化数据源，[experimental] 2026-06-18）
# 来源：akshare ak.stock_value_em；字段含 total/circ_market_cap、total/circ_shares、PE/PB/PEG/PCF/PS
# 详见 designs/feat_market_cap_data_fetcher.md §6, §7
MARKET_CAP_DATA = DATA_FETCHERS_RESULT / "market_cap_data.json.gz"

# ============================================================================
# 日志目录
# ============================================================================

DATA_FETCHERS_LOGS = PROJECT_ROOT / "data_fetchers" / "logs"
FACTOR_IC_LOGS = PROJECT_ROOT / "factor_ic" / "logs"
BACKTEST_LOGS = PROJECT_ROOT / "backtest" / "logs"
COMPREHENSIVE_FACTOR_LOGS = PROJECT_ROOT / "comprehensive_factor" / "logs"
SUMMARY_LOGS = PROJECT_ROOT / "summary" / "logs"
REVERSE_DISCOVERY_LOGS = PROJECT_ROOT / "reverse_discovery" / "logs"

# ============================================================================
# 临时文件目录
# ============================================================================

TEMPORARY_DIR = PROJECT_ROOT / "temporary"

# ============================================================================
# design.md 目录
# ============================================================================

DESIGNS_DIR = PROJECT_ROOT / "designs"

# ============================================================================
# 路径变更检查（机器强制）
# ============================================================================


def validate_path_exists(path: Path, description: str) -> None:
    """
    验证路径存在，不存在则抛错

    用于 CI 强制检查：修改路径配置后必须验证新路径存在
    """
    if not path.exists():
        raise FileNotFoundError(
            f"路径不存在: {path}\n"
            f"描述: {description}\n"
            f"请检查路径配置或执行数据生成脚本"
        )


# ============================================================================
# 所有路径定义（用于 import-linter 检查）
# ============================================================================

__all__ = [
    "PROJECT_ROOT",
    "DATA_FETCHERS_RESULT",
    "FACTOR_IC_RESULT",
    "BACKTEST_RESULT",
    "COMPREHENSIVE_FACTOR_RESULT",
    "SUMMARY_RESULT",
    "REVERSE_DISCOVERY_RESULT",
    "FACTOR_IC_DATA",
    "MARKET_CAP_DATA",
    "RETURN_DATA_BACKUP",
    "FACTOR_DATA_BACKUP",
    "DATA_FETCHERS_LOGS",
    "FACTOR_IC_LOGS",
    "BACKTEST_LOGS",
    "COMPREHENSIVE_FACTOR_LOGS",
    "SUMMARY_LOGS",
    "REVERSE_DISCOVERY_LOGS",
    "TEMPORARY_DIR",
    "DESIGNS_DIR",
    "validate_path_exists",
]
