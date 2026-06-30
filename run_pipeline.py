#!/usr/bin/env python3
"""
因子分析完整流程串行执行脚本

执行顺序：
Stage 0: 基础数据拉取
  1. fetch_stock_list.py        → data_fetchers/result/stock_list.json
  2. fetch_factor_cache.py      → cache/factor_data/factor_data.json.gz（收益数据已内置于 factor_ic_data.json.gz）
  3. fetch_market_cap.py        → data_fetchers/result/market_cap_data.json.gz（市值/估值面板，中性化依赖）
  4. fetch_turnover.py          → data_fetchers/result/turnover_rate_data.json.gz
  5. fetch_industry.py          → result/stock_industry.json
  6. fetch_tail_trading.py      → data_fetchers/result/tail_trading_data.json.gz（尾盘5分钟K线数据）

Stage 1: 数据整合
  7. factor_generator.py        → data_fetchers/result/factor_ic_data.json.gz

Stage 2: IC计算
  8. ic_rsi_1d.py
  9. ic_volume_ratio_1d.py
  10. ic_kdj_j_1d.py
  11. ic_bollinger_pb_1d.py
  12. ic_turnover_surge_1d.py
  13. ic_amplitude_1d.py
  14. ic_price_position_1d.py
  15. ic_return_3d_1d.py
  16. ic_return_5d_1d.py
  17. ic_overnight_ret_1d.py
  18. ic_past_return_1d_1d.py (新增 2026-06-04)
  19. ic_momentum_strength_1d.py (新增 2026-06-05)
  20. ic_tail_price_position.py (新增 2026-06-02)
  21. ic_tail_price_slope_1d.py (新增 2026-06-02)
  22. ic_tail_price_volume_intensity.py (新增 2026-06-02)
  23. ic_tail_volume_acceleration_1d.py (新增 2026-06-02)
  24. ic_tail_volume_shrink_1d.py (新增 2026-06-06)
  25. ic_volume_price_strength_1d.py (新增 2026-06-11)
  26. ic_positive_day_ratio_5_1d.py (新增 2026-06-11)
  27. ic_ma5_deviation_1d.py (新增 2026-06-11)
  28. ic_near_high_ratio_5_1d.py (新增 2026-06-11)
  29. ic_intraday_intensity_1d.py (补注册 2026-06-13)
  30. ic_capital_flow_intensity_1d.py (补注册 2026-06-13)
  31. ic_capital_flow_ratio_trend_1d.py (补注册 2026-06-13)
  32. ic_industry_pe_trend_1d.py (补注册 2026-06-13)
  33. ic_industry_earnings_growth_1d.py (补注册 2026-06-13)
  34. ic_industry_roe_trend_1d.py (补注册 2026-06-13)
  35. ic_industry_turnover_trend_1d.py (补注册 2026-06-13)
  36. ic_industry_momentum_5d_1d.py (补注册 2026-06-13)
  37. ic_industry_amplitude_trend_1d.py (补注册 2026-06-13)
  38. ic_tail_price_position_delta_1d.py (新增 2026-06-11)
  39. ic_tail_volume_shrink_delta_1d.py (新增 2026-06-11)
  40. ic_turnover_surge_delta_1d.py (补注册 2026-06-13)
  41. ic_amplitude_delta_1d.py (补注册 2026-06-13)
  42. ic_rsi_slope_3d_1d.py (v2.35 P5 新增)
  43. ic_ma5_slope_1d.py (v2.35 P5 新增)
  44. ic_lower_shadow_ratio_1d.py (v2.35 P5 新增)
  45. ic_volume_shrink_rate_1d.py (v2.35 P5 新增)
  46. ic_price_volume_divergence_1d.py (v2.35 P5 新增)
  47. ic_return_acceleration_5d_1d.py (v2.35 P5-补充 新增)
  48. ic_downside_deceleration_1d.py (v2.35 P5-补充 新增)
  49. ic_amplitude_compression_1d.py (v2.35 P5-补充 新增)
  50. ic_range_compression_1d.py (v2.35 P5-补充 新增)
  51. ic_volume_decay_rate_1d.py (v2.35 P5-补充 新增)
  52. ic_turnover_decay_rate_1d.py (v2.35 P5-补充 新增)

Stage 3: 分层回测
  53. layered_backtest_rsi_1d.py
  43. layered_backtest_volume_ratio_1d.py
  44. layered_backtest_kdj_j_1d.py
  45. layered_backtest_bollinger_pb_1d.py
  46. layered_backtest_turnover_surge_1d.py
  47. layered_backtest_amplitude_1d.py
  48. layered_backtest_price_position_1d.py
  49. layered_backtest_return_3d_1d.py
  50. layered_backtest_return_5d_1d.py
  51. layered_backtest_overnight_ret_1d.py
  52. layered_backtest_past_return_1d_1d.py (新增 2026-06-04)
  53. layered_backtest_momentum_strength_1d.py (新增 2026-06-05)
  54. layered_backtest_tail_price_position_1d.py (新增 2026-06-02)
  55. layered_backtest_tail_price_slope_1d.py (新增 2026-06-02)
  56. layered_backtest_tail_price_volume_intensity_1d.py (新增 2026-06-02)
  57. layered_backtest_tail_volume_acceleration_1d.py (新增 2026-06-02)
  58. layered_backtest_tail_volume_shrink_1d.py (新增 2026-06-06)
  59. layered_backtest_volume_price_strength_1d.py (补注册 2026-06-13)
  60. layered_backtest_positive_day_ratio_5_1d.py (补注册 2026-06-13)
  61. layered_backtest_ma5_deviation_1d.py (补注册 2026-06-13)
  62. layered_backtest_near_high_ratio_5_1d.py (补注册 2026-06-13)
  63. layered_backtest_intraday_intensity_1d.py (补注册 2026-06-13)
  64. layered_backtest_capital_flow_intensity_1d.py (补注册 2026-06-13)
  65. layered_backtest_capital_flow_ratio_trend_1d.py (补注册 2026-06-13)
  66. layered_backtest_industry_pe_trend_1d.py (补注册 2026-06-13)
  67. layered_backtest_industry_earnings_growth_1d.py (补注册 2026-06-13)
  68. layered_backtest_industry_roe_trend_1d.py (补注册 2026-06-13)
  69. layered_backtest_industry_turnover_trend_1d.py (补注册 2026-06-13)
  70. layered_backtest_industry_momentum_5d_1d.py (补注册 2026-06-13)
  71. layered_backtest_industry_amplitude_trend_1d.py (补注册 2026-06-13)
  72. layered_backtest_tail_price_position_delta_1d.py (新增 2026-06-11)
  73. layered_backtest_tail_volume_shrink_delta_1d.py (新增 2026-06-11)
  74. layered_backtest_turnover_surge_delta_1d.py (补注册 2026-06-13)
  75. layered_backtest_amplitude_delta_1d.py (补注册 2026-06-13)
  76. layered_backtest_rsi_slope_3d_1d.py (v2.35 P5 新增)
  77. layered_backtest_ma5_slope_1d.py (v2.35 P5 新增)
  78. layered_backtest_lower_shadow_ratio_1d.py (v2.35 P5 新增)
  79. layered_backtest_volume_shrink_rate_1d.py (v2.35 P5 新增)
  80. layered_backtest_price_volume_divergence_1d.py (v2.35 P5 新增)
  81. layered_backtest_return_acceleration_5d_1d.py (v2.35 P5-补充 新增)
  82. layered_backtest_downside_deceleration_1d.py (v2.35 P5-补充 新增)
  83. layered_backtest_amplitude_compression_1d.py (v2.35 P5-补充 新增)
  84. layered_backtest_range_compression_1d.py (v2.35 P5-补充 新增)
  85. layered_backtest_volume_decay_rate_1d.py (v2.35 P5-补充 新增)
  86. layered_backtest_turnover_decay_rate_1d.py (v2.35 P5-补充 新增)

Stage 4: 综合因子
  87. composite_equal_weight_1d.py
  88. composite_icir_weight_1d.py
  89. composite_ic_weight_1d.py
  90. composite_rolling_icir_weight_1d.py

Stage 5: 权重选择（新增 2026-06-03; 2026-06-26 重命名为 composite_weight_selector.py）
  80. composite_weight_selector.py → comprehensive_factor/result/weight_selection_result.json

Stage 6: 股票选股（新增 2026-06-03; 2026-06-26 迁移至 stock_selector/）
  81. stock_selector.py          → comprehensive_factor/result/stock_selection_history/selection_date=YYYY-MM-DD/part-0.parquet (v3.7: Parquet 分区数据集, 含 Stage 1/2/3 三段)

Stage 7: 汇总报告
  82. generate_factor_summary_report.py

版本历史：
- v1.0 (2026-05-27): 初始版本，完全串行执行，退出码检查，脚本级别重试
- v1.1 (2026-05-27): fetch_turnover 添加 --baostock 参数，获取历史换手率数据
- v1.2 (2026-06-02): 新增 4 个尾盘因子（tail_price_position, tail_price_slope, tail_price_volume_intensity, tail_volume_acceleration）
- v1.3 (2026-06-03): 新增 Stage 5 权重选择和 Stage 6 股票选股
- v1.4 (2026-06-04): 新增 past_return_1d 因子（IC + 分层回测）
- v1.5 (2026-06-05): 新增 momentum_strength 因子（IC + 分层回测）
- v1.6 (2026-06-06): 新增 tail_volume_shrink 因子（IC + 分层回测）
- v1.7 (2026-06-13): 补注册 4 个方向性因子（volume_price_strength / positive_day_ratio_5 / ma5_deviation / near_high_ratio_5）的分层回测；补注册 intraday_intensity、capital_flow_intensity / capital_flow_ratio_trend、6 个 industry_* 因子、turnover_surge_delta / amplitude_delta 的 IC + 分层回测（脚本均已存在但漏注册到 pipeline）
- v1.8 (2026-06-17): fetch_turnover 设置 5 小时独立超时，避免 baostock 慢速拉取被默认 30 分钟超时反复重启
- v1.9 (2026-06-18): Stage 0 新增 fetch_market_cap（市值/估值面板数据），为 P3 联合中性化提供数据基础

作者: 云瑶
"""

import gc
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import NamedTuple


# ============================================================================
# 配置常量
# ============================================================================

# 项目根目录（脚本所在位置即为项目根）
PROJECT_ROOT = Path(__file__).parent.resolve()

# 脚本执行配置
MAX_RETRIES = 3  # 脚本级别最大重试次数
RETRY_DELAY = 30  # 重试间隔（秒）
SCRIPT_TIMEOUT = 1800  # 单个脚本最大执行时间（秒）= 30分钟
FETCH_TURNOVER_TIMEOUT = 18000  # fetch_turnover 独立超时（秒）= 5小时

# 并行执行配置（2026-06-23 新增，遵循 designs/run_pipeline_parallel_design.md）
# 默认 N=1（串行）：实测 N=2 在 7.3GB 机器上触发 OOM Killed
#   - 单脚本峰值实测：ic_rsi_1d ~2.46GB / ic_amplitude_1d >4GB（含中性化 OLS）
#   - N=2 总占用 ~5-8GB + 系统 3.6GB > 7.3GB 内存，全局 OOM Killer 触发
#   - 用户显式 --parallel 2 时承担 OOM 风险（高配机器 >16GB 可用）
DEFAULT_PARALLEL = 1  # 默认串行；--parallel N 可覆盖
# 可并行的 stage 集合：仅 IC 计算 (2) 和分层回测 (3)，每脚本独立读 Parquet 写各自 result/，无写竞争。
# Stage 0（数据拉取）有顺序依赖；Stage 1/5/6/7 单脚本；Stage 4 单脚本峰值 ~2.6GB（用户决策保持串行）。
PARALLELIZABLE_STAGES: frozenset[int] = frozenset({2, 3})

# ============================================================================
# 脚本定义
# ============================================================================


class ScriptTask(NamedTuple):
    """脚本任务定义"""

    name: str  # 任务名称（用于日志）
    script: str  # 脚本相对路径
    stage: int | float  # 所属阶段（int 为主，1.5 为 Stage 1.5 数据切割）
    args: list[str]  # 命令行参数（可选）
    timeout: int | None = None  # 独立超时时间（秒），None 则使用默认 SCRIPT_TIMEOUT


# 完整执行流程（按顺序）
PIPELINE_SCRIPTS: list[ScriptTask] = [
    # Stage 0: 基础数据拉取
    ScriptTask("fetch_stock_list", "data_fetchers/fetch_stock_list.py", 0, []),
    ScriptTask("fetch_factor_cache", "data_fetchers/fetch_factor_cache.py", 0, []),
    # 市值/估值面板数据（P3 市值中性化依赖，2026-06-18 新增）
    ScriptTask("fetch_market_cap", "data_fetchers/fetch_market_cap.py", 0, []),
    ScriptTask("fetch_turnover", "data_fetchers/fetch_turnover.py", 0, ["--baostock"], timeout=FETCH_TURNOVER_TIMEOUT),
    ScriptTask("fetch_industry", "data_fetchers/fetch_industry.py", 0, []),  # 行业分类数据
    ScriptTask(
        "fetch_tail_trading", "data_fetchers/fetch_tail_trading.py", 0, [], timeout=10800
    ),  # 尾盘5分钟K线数据（3小时超时，因每批停顿80秒）
    ScriptTask("fetch_market_cap", "data_fetchers/fetch_market_cap.py", 0, []),  # 市值数据（用于市值中性化）
    # Stage 1: 数据整合
    ScriptTask("factor_generator", "data_fetchers/factor_generator.py", 1, []),
    # Stage 1.5: Pipeline 数据切割（共享，为所有 pipeline 生成子集数据）
    ScriptTask("pipeline_data_slicer", "pipelines/pipeline_data_slicer.py", 1.5, []),
    # Stage 2: IC计算（pipeline 隔离，需 PIPELINE_ALIAS 环境变量）
    ScriptTask("ic_rsi", "factor_ic/ic_rsi_1d.py", 2, []),
    ScriptTask("ic_volume_ratio", "factor_ic/ic_volume_ratio_1d.py", 2, []),
    ScriptTask("ic_kdj_j", "factor_ic/ic_kdj_j_1d.py", 2, []),
    ScriptTask("ic_bollinger_pb", "factor_ic/ic_bollinger_pb_1d.py", 2, []),
    ScriptTask("ic_turnover_surge", "factor_ic/ic_turnover_surge_1d.py", 2, []),
    ScriptTask("ic_amplitude", "factor_ic/ic_amplitude_1d.py", 2, []),
    ScriptTask("ic_price_position", "factor_ic/ic_price_position_1d.py", 2, []),
    ScriptTask("ic_return_3d", "factor_ic/ic_return_3d_1d.py", 2, []),
    ScriptTask("ic_return_5d", "factor_ic/ic_return_5d_1d.py", 2, []),
    ScriptTask("ic_overnight_ret", "factor_ic/ic_overnight_ret_1d.py", 2, []),
    # past_return_1d 因子 IC 计算（2026-06-04 新增）
    ScriptTask("ic_past_return_1d", "factor_ic/ic_past_return_1d_1d.py", 2, []),
    # momentum_strength 因子 IC 计算（2026-06-05 新增）
    ScriptTask("ic_momentum_strength", "factor_ic/ic_momentum_strength_1d.py", 2, []),
    # 尾盘因子 IC 计算（2026-06-02 新增）
    ScriptTask("ic_tail_price_position", "factor_ic/ic_tail_price_position.py", 2, []),
    ScriptTask("ic_tail_price_slope", "factor_ic/ic_tail_price_slope_1d.py", 2, []),
    ScriptTask("ic_tail_price_volume_intensity", "factor_ic/ic_tail_price_volume_intensity.py", 2, []),
    ScriptTask("ic_tail_volume_acceleration", "factor_ic/ic_tail_volume_acceleration_1d.py", 2, []),
    # tail_volume_shrink 因子 IC 计算（2026-06-06 新增）
    ScriptTask("ic_tail_volume_shrink", "factor_ic/ic_tail_volume_shrink_1d.py", 2, []),
    # 方向性因子 IC（2026-06-11 新增，趋势维度补充）
    ScriptTask("ic_volume_price_strength", "factor_ic/ic_volume_price_strength_1d.py", 2, []),
    ScriptTask("ic_positive_day_ratio_5", "factor_ic/ic_positive_day_ratio_5_1d.py", 2, []),
    ScriptTask("ic_ma5_deviation", "factor_ic/ic_ma5_deviation_1d.py", 2, []),
    ScriptTask("ic_near_high_ratio_5", "factor_ic/ic_near_high_ratio_5_1d.py", 2, []),
    # 日内强度因子 IC（2026-06-13 补注册）
    ScriptTask("ic_intraday_intensity", "factor_ic/ic_intraday_intensity_1d.py", 2, []),
    # 资金流因子 IC（2026-06-13 补注册）
    ScriptTask("ic_capital_flow_intensity", "factor_ic/ic_capital_flow_intensity_1d.py", 2, []),
    ScriptTask("ic_capital_flow_ratio_trend", "factor_ic/ic_capital_flow_ratio_trend_1d.py", 2, []),
    # 行业因子 IC（2026-06-13 补注册）
    ScriptTask("ic_industry_pe_trend", "factor_ic/ic_industry_pe_trend_1d.py", 2, []),
    ScriptTask("ic_industry_earnings_growth", "factor_ic/ic_industry_earnings_growth_1d.py", 2, []),
    ScriptTask("ic_industry_roe_trend", "factor_ic/ic_industry_roe_trend_1d.py", 2, []),
    ScriptTask("ic_industry_turnover_trend", "factor_ic/ic_industry_turnover_trend_1d.py", 2, []),
    ScriptTask("ic_industry_momentum_5d", "factor_ic/ic_industry_momentum_5d_1d.py", 2, []),
    ScriptTask("ic_industry_amplitude_trend", "factor_ic/ic_industry_amplitude_trend_1d.py", 2, []),
    # 差分因子 IC（2026-06-11 新增止跌信号维度，2026-06-13 补 turnover/amplitude delta）
    ScriptTask("ic_tail_price_position_delta", "factor_ic/ic_tail_price_position_delta_1d.py", 2, []),
    ScriptTask("ic_tail_volume_shrink_delta", "factor_ic/ic_tail_volume_shrink_delta_1d.py", 2, []),
    ScriptTask("ic_turnover_surge_delta", "factor_ic/ic_turnover_surge_delta_1d.py", 2, []),
    ScriptTask("ic_amplitude_delta", "factor_ic/ic_amplitude_delta_1d.py", 2, []),
    # v2.35: P5 新增5个趋势变化/量价背离因子 IC（design.md §2.5）
    ScriptTask("ic_rsi_slope_3d", "factor_ic/ic_rsi_slope_3d_1d.py", 2, []),
    ScriptTask("ic_ma5_slope", "factor_ic/ic_ma5_slope_1d.py", 2, []),
    ScriptTask("ic_lower_shadow_ratio", "factor_ic/ic_lower_shadow_ratio_1d.py", 2, []),
    ScriptTask("ic_volume_shrink_rate", "factor_ic/ic_volume_shrink_rate_1d.py", 2, []),
    ScriptTask("ic_price_volume_divergence", "factor_ic/ic_price_volume_divergence_1d.py", 2, []),
    # v2.35: P5-补充 6个二阶导数企稳信号因子 IC（design.md §4, §1）
    ScriptTask("ic_return_acceleration_5d", "factor_ic/ic_return_acceleration_5d_1d.py", 2, []),
    ScriptTask("ic_downside_deceleration", "factor_ic/ic_downside_deceleration_1d.py", 2, []),
    ScriptTask("ic_amplitude_compression", "factor_ic/ic_amplitude_compression_1d.py", 2, []),
    ScriptTask("ic_range_compression", "factor_ic/ic_range_compression_1d.py", 2, []),
    ScriptTask("ic_volume_decay_rate", "factor_ic/ic_volume_decay_rate_1d.py", 2, []),
    ScriptTask("ic_turnover_decay_rate", "factor_ic/ic_turnover_decay_rate_1d.py", 2, []),
    # v2.48: 交互因子族 27 个 pos/neg/abs ReLU 变体 IC 脚本 (F2 阶段注册)
    # 设计依据: designs/feat_factor_definition_destigmatization_v1.md v1.2
    # 9 base × {pos, neg, abs} = 27, 方向由 IC 闸口数据驱动 (无叙事预设)
    ScriptTask("ic_interaction_amplitude__ret3d_pos", "factor_ic/ic_interaction_amplitude__ret3d_pos_1d.py", 2, []),
    ScriptTask("ic_interaction_amplitude__ret3d_neg", "factor_ic/ic_interaction_amplitude__ret3d_neg_1d.py", 2, []),
    ScriptTask("ic_interaction_amplitude__ret3d_abs", "factor_ic/ic_interaction_amplitude__ret3d_abs_1d.py", 2, []),
    ScriptTask("ic_interaction_turnover__ret3d_pos", "factor_ic/ic_interaction_turnover__ret3d_pos_1d.py", 2, []),
    ScriptTask("ic_interaction_turnover__ret3d_neg", "factor_ic/ic_interaction_turnover__ret3d_neg_1d.py", 2, []),
    ScriptTask("ic_interaction_turnover__ret3d_abs", "factor_ic/ic_interaction_turnover__ret3d_abs_1d.py", 2, []),
    ScriptTask(
        "ic_interaction_amp_compression__ret3d_pos", "factor_ic/ic_interaction_amp_compression__ret3d_pos_1d.py", 2, []
    ),
    ScriptTask(
        "ic_interaction_amp_compression__ret3d_neg", "factor_ic/ic_interaction_amp_compression__ret3d_neg_1d.py", 2, []
    ),
    ScriptTask(
        "ic_interaction_amp_compression__ret3d_abs", "factor_ic/ic_interaction_amp_compression__ret3d_abs_1d.py", 2, []
    ),
    ScriptTask("ic_interaction_near_high__ret3d_pos", "factor_ic/ic_interaction_near_high__ret3d_pos_1d.py", 2, []),
    ScriptTask("ic_interaction_near_high__ret3d_neg", "factor_ic/ic_interaction_near_high__ret3d_neg_1d.py", 2, []),
    ScriptTask("ic_interaction_near_high__ret3d_abs", "factor_ic/ic_interaction_near_high__ret3d_abs_1d.py", 2, []),
    ScriptTask("ic_interaction_intraday__ret1d_pos", "factor_ic/ic_interaction_intraday__ret1d_pos_1d.py", 2, []),
    ScriptTask("ic_interaction_intraday__ret1d_neg", "factor_ic/ic_interaction_intraday__ret1d_neg_1d.py", 2, []),
    ScriptTask("ic_interaction_intraday__ret1d_abs", "factor_ic/ic_interaction_intraday__ret1d_abs_1d.py", 2, []),
    ScriptTask("ic_interaction_ma5_dev__ret3d_pos", "factor_ic/ic_interaction_ma5_dev__ret3d_pos_1d.py", 2, []),
    ScriptTask("ic_interaction_ma5_dev__ret3d_neg", "factor_ic/ic_interaction_ma5_dev__ret3d_neg_1d.py", 2, []),
    ScriptTask("ic_interaction_ma5_dev__ret3d_abs", "factor_ic/ic_interaction_ma5_dev__ret3d_abs_1d.py", 2, []),
    ScriptTask("ic_interaction_price_pos__ret1d_pos", "factor_ic/ic_interaction_price_pos__ret1d_pos_1d.py", 2, []),
    ScriptTask("ic_interaction_price_pos__ret1d_neg", "factor_ic/ic_interaction_price_pos__ret1d_neg_1d.py", 2, []),
    ScriptTask("ic_interaction_price_pos__ret1d_abs", "factor_ic/ic_interaction_price_pos__ret1d_abs_1d.py", 2, []),
    ScriptTask("ic_interaction_kdj__ret5d_pos", "factor_ic/ic_interaction_kdj__ret5d_pos_1d.py", 2, []),
    ScriptTask("ic_interaction_kdj__ret5d_neg", "factor_ic/ic_interaction_kdj__ret5d_neg_1d.py", 2, []),
    ScriptTask("ic_interaction_kdj__ret5d_abs", "factor_ic/ic_interaction_kdj__ret5d_abs_1d.py", 2, []),
    ScriptTask("ic_interaction_bollinger__ret5d_pos", "factor_ic/ic_interaction_bollinger__ret5d_pos_1d.py", 2, []),
    ScriptTask("ic_interaction_bollinger__ret5d_neg", "factor_ic/ic_interaction_bollinger__ret5d_neg_1d.py", 2, []),
    ScriptTask("ic_interaction_bollinger__ret5d_abs", "factor_ic/ic_interaction_bollinger__ret5d_abs_1d.py", 2, []),
    # Stage 3: 分层回测
    ScriptTask("backtest_rsi", "backtest/layered_backtest_rsi_1d.py", 3, []),
    ScriptTask("backtest_volume_ratio", "backtest/layered_backtest_volume_ratio_1d.py", 3, []),
    ScriptTask("backtest_kdj_j", "backtest/layered_backtest_kdj_j_1d.py", 3, []),
    ScriptTask("backtest_bollinger_pb", "backtest/layered_backtest_bollinger_pb_1d.py", 3, []),
    ScriptTask("backtest_turnover_surge", "backtest/layered_backtest_turnover_surge_1d.py", 3, []),
    ScriptTask("backtest_amplitude", "backtest/layered_backtest_amplitude_1d.py", 3, []),
    ScriptTask("backtest_price_position", "backtest/layered_backtest_price_position_1d.py", 3, []),
    ScriptTask("backtest_return_3d", "backtest/layered_backtest_return_3d_1d.py", 3, []),
    ScriptTask("backtest_return_5d", "backtest/layered_backtest_return_5d_1d.py", 3, []),
    ScriptTask("backtest_overnight_ret", "backtest/layered_backtest_overnight_ret_1d.py", 3, []),
    # past_return_1d 因子分层回测（2026-06-04 新增）
    ScriptTask("backtest_past_return_1d", "backtest/layered_backtest_past_return_1d_1d.py", 3, []),
    # momentum_strength 因子分层回测（2026-06-05 新增）
    ScriptTask("backtest_momentum_strength", "backtest/layered_backtest_momentum_strength_1d.py", 3, []),
    # 尾盘因子分层回测（2026-06-02 新增）
    ScriptTask("backtest_tail_price_position", "backtest/layered_backtest_tail_price_position_1d.py", 3, []),
    ScriptTask("backtest_tail_price_slope", "backtest/layered_backtest_tail_price_slope_1d.py", 3, []),
    ScriptTask(
        "backtest_tail_price_volume_intensity", "backtest/layered_backtest_tail_price_volume_intensity_1d.py", 3, []
    ),
    ScriptTask("backtest_tail_volume_acceleration", "backtest/layered_backtest_tail_volume_acceleration_1d.py", 3, []),
    # tail_volume_shrink 因子分层回测（2026-06-06 新增）
    ScriptTask("backtest_tail_volume_shrink", "backtest/layered_backtest_tail_volume_shrink_1d.py", 3, []),
    # 方向性因子分层回测（2026-06-13 补注册，对应 2026-06-11 新增 IC）
    ScriptTask("backtest_volume_price_strength", "backtest/layered_backtest_volume_price_strength_1d.py", 3, []),
    ScriptTask("backtest_positive_day_ratio_5", "backtest/layered_backtest_positive_day_ratio_5_1d.py", 3, []),
    ScriptTask("backtest_ma5_deviation", "backtest/layered_backtest_ma5_deviation_1d.py", 3, []),
    ScriptTask("backtest_near_high_ratio_5", "backtest/layered_backtest_near_high_ratio_5_1d.py", 3, []),
    # 日内强度因子分层回测（2026-06-13 补注册）
    ScriptTask("backtest_intraday_intensity", "backtest/layered_backtest_intraday_intensity_1d.py", 3, []),
    # 资金流因子分层回测（2026-06-13 补注册）
    ScriptTask("backtest_capital_flow_intensity", "backtest/layered_backtest_capital_flow_intensity_1d.py", 3, []),
    ScriptTask("backtest_capital_flow_ratio_trend", "backtest/layered_backtest_capital_flow_ratio_trend_1d.py", 3, []),
    # 行业因子分层回测（2026-06-13 补注册）
    ScriptTask("backtest_industry_pe_trend", "backtest/layered_backtest_industry_pe_trend_1d.py", 3, []),
    ScriptTask("backtest_industry_earnings_growth", "backtest/layered_backtest_industry_earnings_growth_1d.py", 3, []),
    ScriptTask("backtest_industry_roe_trend", "backtest/layered_backtest_industry_roe_trend_1d.py", 3, []),
    ScriptTask("backtest_industry_turnover_trend", "backtest/layered_backtest_industry_turnover_trend_1d.py", 3, []),
    ScriptTask("backtest_industry_momentum_5d", "backtest/layered_backtest_industry_momentum_5d_1d.py", 3, []),
    ScriptTask("backtest_industry_amplitude_trend", "backtest/layered_backtest_industry_amplitude_trend_1d.py", 3, []),
    # 差分因子分层回测（2026-06-11 新增止跌信号维度，2026-06-13 补 turnover/amplitude delta）
    ScriptTask(
        "backtest_tail_price_position_delta", "backtest/layered_backtest_tail_price_position_delta_1d.py", 3, []
    ),
    ScriptTask("backtest_tail_volume_shrink_delta", "backtest/layered_backtest_tail_volume_shrink_delta_1d.py", 3, []),
    ScriptTask("backtest_turnover_surge_delta", "backtest/layered_backtest_turnover_surge_delta_1d.py", 3, []),
    ScriptTask("backtest_amplitude_delta", "backtest/layered_backtest_amplitude_delta_1d.py", 3, []),
    # v2.35: P5 新增5个趋势变化/量价背离因子分层回测（design.md §2.5）
    ScriptTask("backtest_rsi_slope_3d", "backtest/layered_backtest_rsi_slope_3d_1d.py", 3, []),
    ScriptTask("backtest_ma5_slope", "backtest/layered_backtest_ma5_slope_1d.py", 3, []),
    ScriptTask("backtest_lower_shadow_ratio", "backtest/layered_backtest_lower_shadow_ratio_1d.py", 3, []),
    ScriptTask("backtest_volume_shrink_rate", "backtest/layered_backtest_volume_shrink_rate_1d.py", 3, []),
    ScriptTask("backtest_price_volume_divergence", "backtest/layered_backtest_price_volume_divergence_1d.py", 3, []),
    # v2.35: P5-补充 6个二阶导数企稳信号因子分层回测（design.md §5, §1）
    ScriptTask("backtest_return_acceleration_5d", "backtest/layered_backtest_return_acceleration_5d_1d.py", 3, []),
    ScriptTask("backtest_downside_deceleration", "backtest/layered_backtest_downside_deceleration_1d.py", 3, []),
    ScriptTask("backtest_amplitude_compression", "backtest/layered_backtest_amplitude_compression_1d.py", 3, []),
    ScriptTask("backtest_range_compression", "backtest/layered_backtest_range_compression_1d.py", 3, []),
    ScriptTask("backtest_volume_decay_rate", "backtest/layered_backtest_volume_decay_rate_1d.py", 3, []),
    ScriptTask("backtest_turnover_decay_rate", "backtest/layered_backtest_turnover_decay_rate_1d.py", 3, []),
    # v2.48: 交互因子族 27 个 pos/neg/abs ReLU 变体分层回测脚本 (F2 阶段注册)
    # 设计依据: designs/feat_factor_definition_destigmatization_v1.md v1.2
    # 9 base × {pos, neg, abs} = 27, factor_direction 由 _load_ic_meta 派生 (无叙事预设)
    ScriptTask(
        "backtest_interaction_amplitude__ret3d_pos",
        "backtest/layered_backtest_interaction_amplitude__ret3d_pos_1d.py",
        3,
        [],
    ),
    ScriptTask(
        "backtest_interaction_amplitude__ret3d_neg",
        "backtest/layered_backtest_interaction_amplitude__ret3d_neg_1d.py",
        3,
        [],
    ),
    ScriptTask(
        "backtest_interaction_amplitude__ret3d_abs",
        "backtest/layered_backtest_interaction_amplitude__ret3d_abs_1d.py",
        3,
        [],
    ),
    ScriptTask(
        "backtest_interaction_turnover__ret3d_pos",
        "backtest/layered_backtest_interaction_turnover__ret3d_pos_1d.py",
        3,
        [],
    ),
    ScriptTask(
        "backtest_interaction_turnover__ret3d_neg",
        "backtest/layered_backtest_interaction_turnover__ret3d_neg_1d.py",
        3,
        [],
    ),
    ScriptTask(
        "backtest_interaction_turnover__ret3d_abs",
        "backtest/layered_backtest_interaction_turnover__ret3d_abs_1d.py",
        3,
        [],
    ),
    ScriptTask(
        "backtest_interaction_amp_compression__ret3d_pos",
        "backtest/layered_backtest_interaction_amp_compression__ret3d_pos_1d.py",
        3,
        [],
    ),
    ScriptTask(
        "backtest_interaction_amp_compression__ret3d_neg",
        "backtest/layered_backtest_interaction_amp_compression__ret3d_neg_1d.py",
        3,
        [],
    ),
    ScriptTask(
        "backtest_interaction_amp_compression__ret3d_abs",
        "backtest/layered_backtest_interaction_amp_compression__ret3d_abs_1d.py",
        3,
        [],
    ),
    ScriptTask(
        "backtest_interaction_near_high__ret3d_pos",
        "backtest/layered_backtest_interaction_near_high__ret3d_pos_1d.py",
        3,
        [],
    ),
    ScriptTask(
        "backtest_interaction_near_high__ret3d_neg",
        "backtest/layered_backtest_interaction_near_high__ret3d_neg_1d.py",
        3,
        [],
    ),
    ScriptTask(
        "backtest_interaction_near_high__ret3d_abs",
        "backtest/layered_backtest_interaction_near_high__ret3d_abs_1d.py",
        3,
        [],
    ),
    ScriptTask(
        "backtest_interaction_intraday__ret1d_pos",
        "backtest/layered_backtest_interaction_intraday__ret1d_pos_1d.py",
        3,
        [],
    ),
    ScriptTask(
        "backtest_interaction_intraday__ret1d_neg",
        "backtest/layered_backtest_interaction_intraday__ret1d_neg_1d.py",
        3,
        [],
    ),
    ScriptTask(
        "backtest_interaction_intraday__ret1d_abs",
        "backtest/layered_backtest_interaction_intraday__ret1d_abs_1d.py",
        3,
        [],
    ),
    ScriptTask(
        "backtest_interaction_ma5_dev__ret3d_pos",
        "backtest/layered_backtest_interaction_ma5_dev__ret3d_pos_1d.py",
        3,
        [],
    ),
    ScriptTask(
        "backtest_interaction_ma5_dev__ret3d_neg",
        "backtest/layered_backtest_interaction_ma5_dev__ret3d_neg_1d.py",
        3,
        [],
    ),
    ScriptTask(
        "backtest_interaction_ma5_dev__ret3d_abs",
        "backtest/layered_backtest_interaction_ma5_dev__ret3d_abs_1d.py",
        3,
        [],
    ),
    ScriptTask(
        "backtest_interaction_price_pos__ret1d_pos",
        "backtest/layered_backtest_interaction_price_pos__ret1d_pos_1d.py",
        3,
        [],
    ),
    ScriptTask(
        "backtest_interaction_price_pos__ret1d_neg",
        "backtest/layered_backtest_interaction_price_pos__ret1d_neg_1d.py",
        3,
        [],
    ),
    ScriptTask(
        "backtest_interaction_price_pos__ret1d_abs",
        "backtest/layered_backtest_interaction_price_pos__ret1d_abs_1d.py",
        3,
        [],
    ),
    ScriptTask(
        "backtest_interaction_kdj__ret5d_pos", "backtest/layered_backtest_interaction_kdj__ret5d_pos_1d.py", 3, []
    ),
    ScriptTask(
        "backtest_interaction_kdj__ret5d_neg", "backtest/layered_backtest_interaction_kdj__ret5d_neg_1d.py", 3, []
    ),
    ScriptTask(
        "backtest_interaction_kdj__ret5d_abs", "backtest/layered_backtest_interaction_kdj__ret5d_abs_1d.py", 3, []
    ),
    ScriptTask(
        "backtest_interaction_bollinger__ret5d_pos",
        "backtest/layered_backtest_interaction_bollinger__ret5d_pos_1d.py",
        3,
        [],
    ),
    ScriptTask(
        "backtest_interaction_bollinger__ret5d_neg",
        "backtest/layered_backtest_interaction_bollinger__ret5d_neg_1d.py",
        3,
        [],
    ),
    ScriptTask(
        "backtest_interaction_bollinger__ret5d_abs",
        "backtest/layered_backtest_interaction_bollinger__ret5d_abs_1d.py",
        3,
        [],
    ),
    # Stage 4: 综合因子（auto_select 默认启用，无需传参；传 --auto_select 会触发 argparse unrecognized arguments 错误）
    # v2.35: P2 维度权重全方法支持——4种方法统一配置 --dimension_weight icir
    # 消除 rolling_icir 独享维度权重的不公平对比（design.md §2.2 决策点3）
    ScriptTask(
        "composite_equal", "comprehensive_factor/composite_equal_weight_1d.py", 4, ["--dimension_weight", "icir"]
    ),
    ScriptTask("composite_icir", "comprehensive_factor/composite_icir_weight_1d.py", 4, ["--dimension_weight", "icir"]),
    ScriptTask("composite_ic", "comprehensive_factor/composite_ic_weight_1d.py", 4, ["--dimension_weight", "icir"]),
    ScriptTask(
        "composite_rolling_icir",
        "comprehensive_factor/composite_rolling_icir_weight_1d.py",
        4,
        ["--dimension_weight", "icir"],
    ),
    # Stage 5: 权重选择（新增 2026-06-03; 2026-06-26 重命名为 composite_weight_selector.py）
    ScriptTask("weight_selector", "comprehensive_factor/composite_weight_selector.py", 5, []),
    # Stage 6: 股票选股（新增 2026-06-03; 2026-06-26 迁移至 stock_selector/）
    ScriptTask("stock_selector", "stock_selector/stock_selector.py", 6, []),
    # Stage 7: 汇总报告
    ScriptTask("summary_report", "summary/generate_factor_summary_report.py", 7, []),
]

# ============================================================================
# 执行函数
# ============================================================================


def run_script(task: ScriptTask, retry_count: int = 0, pipeline_alias: str | None = None) -> bool | None:
    """
    执行单个脚本

    Args:
        task: 脚本任务定义
        retry_count: 当前重试次数（用于日志）
        pipeline_alias: pipeline 别名（None 表示共享 stage，不注入环境变量）

    Returns:
        True: 执行成功
        False: 执行失败（可重试）
        None: 不可重试失败（如 SIGKILL/OOM，重试只会再次 OOM）
    """
    script_path = PROJECT_ROOT / task.script

    # 检查脚本是否存在
    if not script_path.exists():
        print(f"[错误] 脚本不存在: {script_path}")
        return False

    # 构建命令
    cmd = [sys.executable, str(script_path)] + task.args

    # 日志前缀（含 pipeline 别名）
    alias_prefix = f"[{pipeline_alias}]" if pipeline_alias else ""
    prefix = f"{alias_prefix}[{task.name}]" + (f"(重试#{retry_count})" if retry_count > 0 else "")

    print(f"{prefix} 开始执行...")
    print(f"{prefix} 脚本路径: {script_path}")

    # 计算实际超时时间（优先使用任务独立超时，否则使用默认值）
    actual_timeout = task.timeout if task.timeout is not None else SCRIPT_TIMEOUT

    start_time = time.time()

    # 构建子进程环境变量
    child_env = {
        **dict(os.environ),
        "PYTHONPATH": str(PROJECT_ROOT),
        "MALLOC_TRIM_THRESHOLD_": "-1",
        "MALLOC_MMAP_THRESHOLD_": "131072",
    }
    if pipeline_alias:
        child_env["PIPELINE_ALIAS"] = pipeline_alias

    try:
        # 执行脚本（流式输出，避免 capture_output 在内存中累积全量日志导致 OOM）
        result = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            text=True,
            timeout=actual_timeout,
            env=child_env,
        )

        elapsed = time.time() - start_time

        # 检查退出码
        if result.returncode == 0:
            print(f"{prefix} ✓ 执行成功 (耗时 {elapsed:.1f}s, 退出码 0)")
            return True
        elif result.returncode == -9:
            # SIGKILL (OOM Killer 或手动 kill -9): 确定性失败，重试不会成功
            # 第一性原理：OOM 是稳态失败（内存不变，结果不变），重试只会再次 OOM
            print(f"{prefix} ✗ 被 SIGKILL 终止 (耗时 {elapsed:.1f}s, 退出码 -9)")
            print(f"{prefix}   可能是 OOM Killer 或手动 kill -9，不重试")
            return None
        else:
            print(f"{prefix} ✗ 执行失败 (耗时 {elapsed:.1f}s, 退出码 {result.returncode})")
            return False

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        print(f"{prefix} ✗ 执行超时 (耗时 {elapsed:.1f}s > {actual_timeout}s)")
        return False

    except Exception as e:
        elapsed = time.time() - start_time
        print(f"{prefix} ✗ 执行异常: {type(e).__name__}: {e}")
        return False


# ============================================================================
# 并行执行辅助函数（2026-06-23 新增）
# ============================================================================


def run_script_with_retry(task: ScriptTask, pipeline_alias: str | None = None) -> tuple[ScriptTask, bool]:
    """
    单脚本 + 重试循环（封装供线程池调用）。

    与原 run_pipeline() 内联的重试循环行为完全一致：最多 MAX_RETRIES 次重试，
    每次重试间隔 RETRY_DELAY 秒。重试时序在并行模式下会阻塞当前 worker 线程，
    但不影响同批其他 worker（接受这一折衷，见 design §6 风险表）。

    Returns:
        (task, True): 至少一次执行成功
        (task, False): 重试次数用尽全部失败
    """
    for retry in range(MAX_RETRIES + 1):
        result = run_script(task, retry, pipeline_alias=pipeline_alias)
        if result is True:
            return task, True
        if result is None:
            # SIGKILL/OOM: 确定性失败，不重试
            print(f"[{task.name}] SIGKILL 不可重试，标记为失败")
            return task, False
        if retry < MAX_RETRIES:
            print(f"[{task.name}] 等待 %ds 后重试..." % RETRY_DELAY)
            time.sleep(RETRY_DELAY)
    print(f"[{task.name}] 重试次数用尽，标记为失败")
    return task, False


def _plan_batches(
    scripts: list[ScriptTask],
    parallel: int,
    parallelizable_stages: frozenset[int] = PARALLELIZABLE_STAGES,
) -> list[list[ScriptTask]]:
    """
    将脚本列表切分为执行批次（纯函数，可独立单元测试）。

    规则：
    - 不跨 stage 边界（用户决策 Q3=A）
    - stage ∈ parallelizable_stages 且 parallel > 1：按 batch_size=parallel 切分
    - 其他情况：每脚本一个单元素批

    Args:
        scripts: 已过滤的待执行脚本列表（按原 PIPELINE_SCRIPTS 顺序）
        parallel: 并行度，N=1 等同于全串行
        parallelizable_stages: 允许并行的 stage 集合

    Returns:
        批次列表，每批是若干同 stage 的 ScriptTask。串行情况下每批长度 1。

    Examples:
        # parallel=1 → 每脚本一批
        _plan_batches([t1, t2, t3], 1) == [[t1], [t2], [t3]]

        # parallel=2 且全部在 stage 2 → 按 2 切分
        _plan_batches([t1, t2, t3, t4, t5], 2) where all stage=2
            == [[t1, t2], [t3, t4], [t5]]

        # 混合 stage → stage 边界处自然切断
        _plan_batches([s0a, s2a, s2b, s2c, s3a], 2)
            == [[s0a], [s2a, s2b], [s2c], [s3a]]
    """
    batches: list[list[ScriptTask]] = []
    i = 0
    n = len(scripts)
    while i < n:
        task = scripts[i]
        if task.stage in parallelizable_stages and parallel > 1:
            # 收集同 stage 的连续段
            j = i
            while j < n and scripts[j].stage == task.stage:
                j += 1
            stage_tasks = scripts[i:j]
            # 按 batch_size=parallel 切分
            for k in range(0, len(stage_tasks), parallel):
                batches.append(stage_tasks[k : k + parallel])
            i = j
        else:
            # 串行 stage 或 parallel=1：单元素批
            batches.append([task])
            i += 1
    return batches


def _run_batch_parallel(
    tasks: list[ScriptTask], parallel: int, pipeline_alias: str | None = None
) -> list[tuple[ScriptTask, bool]]:
    """
    并行执行一批 tasks，全部完成才返回（批间严格屏障）。

    使用 ThreadPoolExecutor：subprocess.run 是阻塞 IO，线程池调度无 GIL 问题。
    as_completed 等所有 future 完成，单个失败不取消同批其他 future。

    Args:
        tasks: 同 stage 的脚本列表（长度 <= parallel）
        parallel: 线程池大小
        pipeline_alias: pipeline 别名（传递给子进程）

    Returns:
        每个 task 的 (task, success) 二元组列表（顺序按完成时间，非提交顺序）
    """
    results: list[tuple[ScriptTask, bool]] = []
    with ThreadPoolExecutor(max_workers=parallel) as pool:
        futures = {pool.submit(run_script_with_retry, t, pipeline_alias): t for t in tasks}
        for fut in as_completed(futures):
            results.append(fut.result())
    return results


def run_pipeline(
    start_stage: int | float = 0,
    start_script: str | None = None,
    skip_stages: list[int] | None = None,
    parallel: int = 1,
    pipeline_aliases: list[str] | None = None,
) -> bool:
    """
    执行完整流程

    Args:
        start_stage: 从哪个阶段开始（0-7，1.5=数据切割）
        start_script: 从哪个脚本开始（脚本名称，如 'fetch_turnover'）
        skip_stages: 跳过的阶段列表
        parallel: 并行度（默认 1=串行）。N>1 时仅 PARALLELIZABLE_STAGES 内的脚本并行，
                  批内 N 个 future 全部完成才进下一批（批间严格屏障）。
        pipeline_aliases: 要执行的 pipeline 别名列表。
            None 或 ["all"] 表示执行配置文件中的全部 pipeline。
            Stage < 2 的脚本（共享区）只跑一次，不注入 PIPELINE_ALIAS。
            Stage >= 2 的脚本为每个 alias 各跑一遍。

    Returns:
        True: 全部成功
        False: 有脚本失败
    """
    skip_stages = skip_stages or []

    # 解析 pipeline 别名列表
    if pipeline_aliases is None or pipeline_aliases == ["all"]:
        from pipelines.pipeline_context import load_pipeline_config

        aliases = list(load_pipeline_config().keys())
    else:
        aliases = pipeline_aliases

    # 过滤要执行的脚本
    all_scripts = []
    started = False

    for task in PIPELINE_SCRIPTS:
        # 跳过指定阶段
        if task.stage in skip_stages:
            continue

        # 从指定阶段开始
        if task.stage < start_stage:
            continue

        # 从指定脚本开始
        if start_script and not started:
            if task.name == start_script:
                started = True
            else:
                continue

        all_scripts.append(task)

    if not all_scripts:
        print("[信息] 无脚本需要执行")
        return True

    # 分离共享脚本（stage < 2）和 pipeline 隔离脚本（stage >= 2）
    shared_scripts = [t for t in all_scripts if t.stage < 2]
    pipeline_scripts = [t for t in all_scripts if t.stage >= 2]

    # 打印执行计划
    print("=" * 70)
    print("因子分析流程执行计划")
    print("=" * 70)
    print(f"项目根目录: {PROJECT_ROOT}")
    print(f"Pipelines: {aliases}")
    print(f"共享脚本数: {len(shared_scripts)} (Stage 0-1.5)")
    print(
        f"Pipeline 脚本数: {len(pipeline_scripts)} × {len(aliases)} pipelines = {len(pipeline_scripts) * len(aliases)}"
    )
    print(f"并行度: {parallel} ({'并行' if parallel > 1 else '串行'}模式)")
    if parallel > 1:
        print(f"可并行 stages: {sorted(PARALLELIZABLE_STAGES)}")
    print(f"重试配置: 最大{MAX_RETRIES}次, 间隔{RETRY_DELAY}s")
    print("-" * 70)
    print("=" * 70)
    print()

    failed_scripts: list[tuple[ScriptTask, int]] = []  # (task, exit_code)
    success_count = 0

    # ========== Phase 1: 共享脚本（Stage 0-1.5，只跑一次）==========
    if shared_scripts:
        print(">>> Phase 1: 共享阶段 (Stage 0-1.5)")
        shared_batches = _plan_batches(shared_scripts, parallel)

        for batch_idx, batch in enumerate(shared_batches, 1):
            is_parallel_batch = len(batch) > 1
            batch_stage = batch[0].stage

            # v2.48: Stage 4 (composite) 前杀 LSP 进程释放内存 (~200MB)
            if batch_stage >= 4 and not any(s.stage >= 4 for s in shared_scripts[: shared_scripts.index(batch[0])]):
                import signal as _signal

                for _line in subprocess.check_output(["ps", "aux"], text=True).splitlines():
                    if "pyright-langserver" in _line and "grep" not in _line:
                        _pid = int(_line.split()[1])
                        try:
                            os.kill(_pid, _signal.SIGTERM)
                            print(f"[内存] 杀死 LSP 进程 PID={_pid} (释放 ~200MB)")
                        except ProcessLookupError:
                            pass
                        except PermissionError:
                            print(f"[内存] 无权限杀 LSP PID={_pid}")

            print()
            if is_parallel_batch:
                print(
                    f">>> Batch {batch_idx}/{len(shared_batches)} [Stage {batch_stage}] "
                    f"并行启动 ({len(batch)} tasks): {', '.join(t.name for t in batch)}"
                )
                t0 = time.time()
                batch_results = _run_batch_parallel(batch, parallel)
                batch_elapsed = time.time() - t0
                ok_count = sum(1 for _, s in batch_results if s)
                print(
                    f"<<< Batch {batch_idx}/{len(shared_batches)} [Stage {batch_stage}] "
                    f"完成 (耗时 %.1fs, 成功 %d/%d)" % (batch_elapsed, ok_count, len(batch))
                )
                for tk, success in batch_results:
                    if success:
                        success_count += 1
                    else:
                        failed_scripts.append((tk, -1))
            else:
                task = batch[0]
                print(f"[阶段 {task.stage}] 执行: {task.name}")
                print("-" * 50)
                _, success = run_script_with_retry(task)
                if success:
                    success_count += 1
                else:
                    failed_scripts.append((task, -1))

            gc.collect()
            time.sleep(3)

        # 共享阶段失败则不继续 pipeline 阶段
        if failed_scripts:
            print("\n[警告] 共享阶段有脚本失败，跳过 pipeline 阶段")
        print()

    # ========== Phase 2: Pipeline 隔离脚本（Stage 2-7，每个 alias 各跑一遍）==========
    if pipeline_scripts and not failed_scripts:
        for alias in aliases:
            print(f">>> Phase 2: Pipeline [{alias}] (Stage 2-7)")
            print("=" * 50)

            pipeline_batches = _plan_batches(pipeline_scripts, parallel)

            for batch_idx, batch in enumerate(pipeline_batches, 1):
                is_parallel_batch = len(batch) > 1
                batch_stage = batch[0].stage

                # v2.48: Stage 4 (composite) 前杀 LSP 进程释放内存 (~200MB)
                if batch_stage >= 4 and not any(
                    s.stage >= 4 for s in pipeline_scripts[: pipeline_scripts.index(batch[0])]
                ):
                    import signal as _signal

                    for _line in subprocess.check_output(["ps", "aux"], text=True).splitlines():
                        if "pyright-langserver" in _line and "grep" not in _line:
                            _pid = int(_line.split()[1])
                            try:
                                os.kill(_pid, _signal.SIGTERM)
                                print(f"[内存] 杀死 LSP 进程 PID={_pid} (释放 ~200MB)")
                            except ProcessLookupError:
                                pass
                            except PermissionError:
                                print(f"[内存] 无权限杀 LSP PID={_pid}")

                print()
                if is_parallel_batch:
                    print(
                        f"[{alias}] Batch {batch_idx}/{len(pipeline_batches)} [Stage {batch_stage}] "
                        f"并行启动 ({len(batch)} tasks): {', '.join(t.name for t in batch)}"
                    )
                    t0 = time.time()
                    batch_results = _run_batch_parallel(batch, parallel, pipeline_alias=alias)
                    batch_elapsed = time.time() - t0
                    ok_count = sum(1 for _, s in batch_results if s)
                    print(
                        f"[{alias}] Batch {batch_idx}/{len(pipeline_batches)} [Stage {batch_stage}] "
                        f"完成 (耗时 %.1fs, 成功 %d/%d)" % (batch_elapsed, ok_count, len(batch))
                    )
                    for tk, success in batch_results:
                        if success:
                            success_count += 1
                        else:
                            failed_scripts.append((tk, -1))
                else:
                    task = batch[0]
                    print(f"[{alias}][阶段 {task.stage}] 执行: {task.name}")
                    print("-" * 50)
                    _, success = run_script_with_retry(task, pipeline_alias=alias)
                    if success:
                        success_count += 1
                    else:
                        failed_scripts.append((task, -1))

                gc.collect()
                time.sleep(3)

            print()

    # 打印执行结果
    print()
    print("=" * 70)
    print("执行结果汇总")
    print("=" * 70)
    total_scripts = len(shared_scripts) + len(pipeline_scripts) * len(aliases)
    print(f"成功: {success_count}/{total_scripts}")

    if failed_scripts:
        print(f"失败: {len(failed_scripts)}")
        print("-" * 50)
        for task, _ in failed_scripts:
            print(f"  ✗ [{task.stage}] {task.name}: {task.script}")
        print("=" * 70)
        return False
    else:
        print("全部成功 ✓")
        print("=" * 70)
        return True


# ============================================================================
# CLI 入口
# ============================================================================


def main() -> int:
    """CLI 入口"""
    global MAX_RETRIES, RETRY_DELAY  # 必须在函数开头声明
    import argparse

    parser = argparse.ArgumentParser(
        description="因子分析完整流程串行执行脚本", formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__
    )

    parser.add_argument(
        "--start-stage",
        type=float,
        default=0,
        choices=[0, 1, 1.5, 2, 3, 4, 5, 6, 7],
        help="从哪个阶段开始执行（0=数据拉取, 1=数据整合, 1.5=数据切割, 2=IC计算, 3=回测, 4=综合因子, 5=权重选择, 6=股票选股, 7=汇总报告）",
    )

    parser.add_argument(
        "--start-script", type=str, default=None, help="从哪个脚本开始执行（脚本名称，如 fetch_turnover）"
    )

    parser.add_argument(
        "--skip-stages", type=int, nargs="*", default=[], help="跳过的阶段（如 --skip-stages 0 1 跳过数据拉取和整合）"
    )

    parser.add_argument(
        "--pipeline",
        type=str,
        default=None,
        help="只运行指定 pipeline（如 --pipeline ob_quality）。未指定时运行 pipelines.yaml 中的全部 pipeline。",
    )

    parser.add_argument(
        "--pipelines",
        type=str,
        default=None,
        help="运行多个指定 pipeline，逗号分隔（如 --pipelines default,ob_quality）。",
    )

    parser.add_argument(
        "--parallel",
        type=int,
        default=DEFAULT_PARALLEL,
        help=(
            f"并行度 N（默认 {DEFAULT_PARALLEL}）。N=1 等同于串行；N>1 时仅 Stage 2 (IC) 和 "
            "Stage 3 (Backtest) 内的脚本按批并行（批间严格屏障，N 个完成才进下一批）。"
            "其他 stage 始终串行。"
        ),
    )

    parser.add_argument(
        "--max-retries", type=int, default=MAX_RETRIES, help=f"脚本级别最大重试次数（默认 {MAX_RETRIES}）"
    )

    parser.add_argument("--retry-delay", type=int, default=RETRY_DELAY, help=f"重试间隔秒数（默认 {RETRY_DELAY}）")

    args = parser.parse_args()

    # 参数验证
    if args.parallel < 1:
        parser.error(f"--parallel 必须 >= 1，当前 {args.parallel}")

    # 更新全局配置
    MAX_RETRIES = args.max_retries
    RETRY_DELAY = args.retry_delay

    # 解析 pipeline 别名
    pipeline_aliases: list[str] | None = None
    if args.pipeline:
        pipeline_aliases = [args.pipeline]
    elif args.pipelines:
        pipeline_aliases = args.pipelines.split(",")

    # 执行流程
    success = run_pipeline(
        start_stage=args.start_stage,
        start_script=args.start_script,
        skip_stages=args.skip_stages,
        parallel=args.parallel,
        pipeline_aliases=pipeline_aliases,
    )

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
