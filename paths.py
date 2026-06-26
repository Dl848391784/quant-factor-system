"""跨模块路径配置 - 单一来源

所有代码必须 import 此文件获取路径，禁止使用字符串字面量。
违反此规则会导致改一处忘另一处，必翻车。

Pipeline 感知（2026-06-26 新增）：
    所有 Stage 2-7 的产出路径根据 PIPELINE_ALIAS 环境变量动态解析。
    未设置时默认 "default"，与现有行为一致。

    PIPELINE_ALIAS=default  → factor_ic/result/default/ic_*.json
    PIPELINE_ALIAS=ob_pool  → factor_ic/result/ob_pool/ic_*.json

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

import os
from pathlib import Path


# 项目根目录
PROJECT_ROOT = Path(__file__).parent

# ============================================================================
# Pipeline 别名（环境变量注入，subprocess 级别隔离）
# ============================================================================
PIPELINE_ALIAS = os.environ.get("PIPELINE_ALIAS", "default")

# ============================================================================
# 共享区（Stage 0-1，不随 pipeline 变化）
# ============================================================================
DATA_FETCHERS_RESULT = PROJECT_ROOT / "data_fetchers" / "result"

# 主数据源（factor_generator 产出，所有 pipeline 的源头）
FACTOR_IC_DATA_MASTER = DATA_FETCHERS_RESULT / "factor_ic_data.parquet"

# 外部数据源（因子计算依赖，非统一数据源的一部分）
FINANCIAL_DATA = DATA_FETCHERS_RESULT / "financial_data.json.gz"  # 财务指标数据（方案B基本面动量因子）
FUND_FLOW_DATA = DATA_FETCHERS_RESULT / "fund_flow_data.json.gz"  # 资金流数据（方案C资金流因子，[experimental]）

# 备份文件（仅用于数据备份/历史追溯，禁止作为运行时数据源）
RETURN_DATA_BACKUP = DATA_FETCHERS_RESULT / "return_data.json.gz"
FACTOR_DATA_BACKUP = DATA_FETCHERS_RESULT / "factor_data.json.gz"

# 市值/估值面板（市值中性化数据源，[experimental] 2026-06-18）
MARKET_CAP_DATA = DATA_FETCHERS_RESULT / "market_cap_data.json.gz"

# 股票列表数据（code → name 映射来源，由 fetch_stock_list 维护）
STOCK_LIST_DATA = DATA_FETCHERS_RESULT / "stock_list.json"

# ============================================================================
# Pipeline 隔离区（Stage 2-7 产出，按别名隔离）
# ============================================================================

# 每个 pipeline 的数据源（slicer 产出：default=symlink, 其他=filtered parquet）
FACTOR_IC_DATA = DATA_FETCHERS_RESULT / PIPELINE_ALIAS / "factor_ic_data.parquet"

# 模块产出目录
FACTOR_IC_RESULT = PROJECT_ROOT / "factor_ic" / "result" / PIPELINE_ALIAS
BACKTEST_RESULT = PROJECT_ROOT / "backtest" / "result" / PIPELINE_ALIAS
COMPREHENSIVE_FACTOR_RESULT = PROJECT_ROOT / "comprehensive_factor" / "result" / PIPELINE_ALIAS
SUMMARY_RESULT = PROJECT_ROOT / "summary" / "result" / PIPELINE_ALIAS
REVERSE_DISCOVERY_RESULT = PROJECT_ROOT / "reverse_discovery" / "result" / PIPELINE_ALIAS

# LR 训练数据 (Hive 双分区 Parquet: weight_method × selection_date, v3.10)
# 来源: stock_selector 每次 pipeline 运行时保存 Bottom90 + 因子权重 + 因子值
# 用途: calibrate_lr_filter 训练样本 (训练分布 = 应用分布, 第一性原理)
LR_TRAINING_DATA_DIR = COMPREHENSIVE_FACTOR_RESULT / "lr_training_data"

# ============================================================================
# 日志目录（按别名隔离）
# ============================================================================
DATA_FETCHERS_LOGS = PROJECT_ROOT / "data_fetchers" / "logs"
FACTOR_IC_LOGS = PROJECT_ROOT / "factor_ic" / "logs" / PIPELINE_ALIAS
BACKTEST_LOGS = PROJECT_ROOT / "backtest" / "logs" / PIPELINE_ALIAS
COMPREHENSIVE_FACTOR_LOGS = PROJECT_ROOT / "comprehensive_factor" / "logs" / PIPELINE_ALIAS
SUMMARY_LOGS = PROJECT_ROOT / "summary" / "logs" / PIPELINE_ALIAS
REVERSE_DISCOVERY_LOGS = PROJECT_ROOT / "reverse_discovery" / "logs" / PIPELINE_ALIAS

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
        raise FileNotFoundError(f"路径不存在: {path}\n描述: {description}\n请检查路径配置或执行数据生成脚本")


# ============================================================================
# 所有路径定义（用于 import-linter 检查）
# ============================================================================

__all__ = [
    "PROJECT_ROOT",
    "PIPELINE_ALIAS",
    "DATA_FETCHERS_RESULT",
    "FACTOR_IC_DATA_MASTER",
    "FACTOR_IC_RESULT",
    "BACKTEST_RESULT",
    "COMPREHENSIVE_FACTOR_RESULT",
    "SUMMARY_RESULT",
    "REVERSE_DISCOVERY_RESULT",
    "LR_TRAINING_DATA_DIR",
    "FACTOR_IC_DATA",
    "FINANCIAL_DATA",
    "FUND_FLOW_DATA",
    "MARKET_CAP_DATA",
    "RETURN_DATA_BACKUP",
    "FACTOR_DATA_BACKUP",
    "STOCK_LIST_DATA",
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
