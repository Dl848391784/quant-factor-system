#!/usr/bin/env python3
"""
统一因子生成模块

职责：生成所有因子数据到缓存，提供单一数据源

Requires: Python >= 3.8 (gzip.BadGzipFile 异常类)

使用前提：
- 运行前需将 project_root 加入 PYTHONPATH，或以项目根目录为工作目录执行
- 否则 else 分支的 factor_ic 绝对导入会触发 ModuleNotFoundError

遵循 PROJECT.md 规范：
- 输出到 data_fetchers/result/
- 复用公共模块计算函数（遵循强制复用规范）
- 公共模块接收 logger 参数（遵循 PROJECT.md 公共模块日志规范）

版本历史：
- v1.0 (2026-05-24): 初始版本，支持 bollinger_pb、kdj_j、turnover_surge 因子
- v1.1 (2026-05-25): logger 参数化 + __all__ 导出 + 类型注解精确化 + 异常处理补全
- v1.2 (2026-05-25): 清理冗余导入/常量 + os 导入规范化 + 数据验证补全 + CLI 参数补全 + 运行耗时统计
- v1.3 (2026-05-25): 常量命名私有化（DEFAULT_CACHE_DIR → _DEFAULT_CACHE_DIR）+ 导入顺序 PEP 8 合规化（argparse 为 CLI 入口特有导入，保留函数内导入）
- v1.4 (2026-05-25): 流程文档创建 + 测试用例创建 + output_cols 注释补全（索引含义）+ valid_records_percent 字段补全
- v1.5 (2026-05-25): 条件导入合并简化（移除 __main__ 重复 sys.path.insert）+ 异常处理精确化（OSError 涵盖 PermissionError）+ metadata 字段注释补全
- v1.6 (2026-05-25): JSONDecodeError 内存优化（提取 lineno/colno/msg）+ CLI 入口返回退出码 + __main__ 测试补全 valid_records_percent + 条件导入合并简化（CLI 入口块）
- v1.7 (2026-05-25): docstring RuntimeError 补全 + main() 返回类型注解（-> int）
- v1.8 (2026-05-25): gzip.BadGzipFile 异常处理补全（gzip 文件损坏）
- v1.9 (2026-05-25): 冗余导入清理（移除条件导入块的 _Path）
- v1.10 (2026-05-25): 导入冗余清理（合并 gzip 导入、移除 main() 函数内冗余 logging 导入）
- v1.11 (2026-05-25): Bug修复（条件导入合并到顶部、__main__循环导入修复、PermissionError重复捕获简化、temp_path后缀处理修复）
- v1.12 (2026-05-25): Bug修复（output_cols注释修正OHLCV顺序、dates排序补充注释、total_records除零保护、版本历史移除硬编码行号、argparse版本描述修正）+ MODULE.md日志换行符规范补充（错误日志允许多行格式化）
- v1.13 (2026-05-25): Bug修复（缩进错误修正Step8注释、numpy.int64类型转换JSON兼容、__main__块改为CLI入口调用main()、测试代码移至test_cases/test_factor_generator.py）
- v1.14 (2026-05-25): Bug修复（除零保护统一使用_calc_pct模块级函数、_EXTENDED_FACTOR_COLS常量替代硬编码切片、docstring补充空数据异常声明、turnover_missing显式int转换）
- v1.15 (2026-05-25): Bug修复（docstring移除JSONDecodeError声明、temp_path.unlink改用missing_ok=True消除TOCTOU竞争窗口）
- v1.16 (2026-05-25): 代码结构优化（_BASE_COLS+_OUTPUT_COLS常量统一output_cols引用关系、__main__块移除sys重复导入、_calc_pct函数语义修正为通用百分比计算）
- v1.17 (2026-05-25): Bug修复（output_path父目录不存在时创建、dates字段从output_df取数据来源更清晰、docstring示例值改为范围说明）
- v1.18 (2026-05-25): Bug修复（版本历史描述修正v1.12日志换行符为规范补充而非修复、_EXTENDED_FACTOR_COLS返回副本防止外部修改）
- v1.19 (2026-05-25): 代码结构优化（常量改为元组防止意外修改、docstring示例补充注释说明返回列表副本、factor_df显式释放内存）
- v1.20 (2026-05-25): 代码结构优化（mkdir移入try块统一异常处理、_OUTPUT_COLS注释移到常量定义处、_calc_pct docstring补充示例、main()异常日志增加类型名）
- v1.21 (2026-05-25): Bug修复（docstring Example格式修正：注释放在>>>行、返回值行无注释、增加isinstance示例）
- v1.22 (2026-05-25): 代码结构优化（清理output_cols冗余别名、mkdir和temp_path职责分离、base_data/turnover_data内存释放、missing_cols错误信息改进）
- v1.23 (2026-05-26): 代码结构优化（tuple类型注解改为tuple[str, ...]更精确表达字符串元组）
- v1.24 (2026-05-26): Bug修复+代码结构优化（turnover_df内存释放、docstring Example标记非运行示例、元组转列表pandas兼容）
- v1.25 (2026-05-26): Bug修复+文档修正（_calc_pct类型注解补充兼容类型说明、docstring Raises删除输入数据为空场景、兜底块错误信息补充异常详情）
- v1.26 (2026-05-26): 规范合规修复（输出路径改为result目录，遵循MODULE.md约束#2：与factor_ic等模块保持一致）
- v1.27 (2026-05-27): 4项修复——1) 条件导入else分支注释补充（说明factor_ic跨包必须用绝对导入）；2) Step编号修正（7→6、8→7、9→8）；3) sys移至顶层导入（PEP 8合规）；4) _DEFAULT_CACHE_DIR注释补充路径层级说明
- v1.28 (2026-05-27): 4项修复——1) 模块docstring声明Python>=3.8（gzip.BadGzipFile）；2) output_df显式释放内存（与既有风格一致）；3) json.dump设置ensure_ascii=False（中文不转义）；4) argparse移至顶层导入（PEP 8合规）
- v1.29 (2026-05-27): 5项修复——1) Step编号重排（2b→3，后续顺延4-9）；2) 使用前提说明补充（PYTHONPATH要求）；3) output_df提前释放（output_data构建后立即del）；4) gzip.open显式encoding='utf-8'（跨平台一致性）；5) JSONDecodeError捕获移除logger.error（行列信息合并到ValueError）
- v1.30 (2026-05-27): 4项日志精确化修复：
    1. Step 1/2/3 gzip.BadGzipFile 捕获块补充 logger.error（文件路径+异常原因）
    2. Step 8 OSError/Exception 捕获块补充 logger.error（输出路径+异常类型+原因）
    3. Step 8 mkdir OSError 捕获块补充 logger.error（目录路径+异常类型+原因）
    4. main() 成功分支补充执行摘要日志（total_records、elapsed_seconds、output_path）
- v1.31 (2026-05-27): 4项修复：
    1. Step 1/2/3 gzip.open 读取补充 encoding='utf-8'（跨平台一致性，与写入对称）
    2. 删除 main() finally 块（logger 共享风险，Python 进程退出自动清理）
    3. Step 4/5/6 因子计算函数补充 logger_arg=logger（日志统一输出到调用方 logger）
    4. 合并 _DEFAULT_CACHE_DIR/_DEFAULT_RESULT_DIR 为单一常量（消除虚假语义差异）
- v1.32 (2026-05-27): 2项文档修复：
    1. 模块 docstring 输出路径修正：cache/factor_data/ → data_fetchers/result/
    2. generate_all_factors Note 修正：factor_ic → factor_calculator（与实际导入一致）
- v1.33 (2026-06-02): 尾盘因子整合到统一数据源：
    1. 新增 _EXTENDED_FACTOR_COLS: tail_price_position, tail_price_slope, tail_price_volume_intensity
    2. 新增 _load_tail_trading_data() 函数加载尾盘5分钟K线数据
    3. 新增 _calculate_tail_factors() 函数合并计算尾盘因子
    4. 新增 Step 9 计算尾盘因子，Step 编号顺延至 10-12
    5. 更新 metadata valid_records 包含所有因子统计
    6. 遵循 PROJECT.md H1 规则：迁移函数而非跨模块导入
- v1.34 (2026-06-03): 新增隔夜收益率因子（跳空幅度）：
    1. 新增 overnight_ret 到 _EXTENDED_FACTOR_COLS
    2. 新增 Step 9 计算 overnight_ret（调用 calculate_overnight_return）
    3. Step 编号顺延：尾盘因子 Step 10，格式化 Step 11，保存 Step 12
    4. 公式：(今日Open - 昨日Close) / 昨日Close（即跳空幅度）
- v1.35 (2026-06-03): 新增尾盘量能加速度因子：
    1. 新增 tail_volume_acceleration 到 _EXTENDED_FACTOR_COLS
    2. 新增 _calc_tail_volume_acceleration() 函数（后半段/前半段成交量比）
    3. 在 _calculate_tail_factors() 中添加 tail_volume_acceleration 计算
    4. 公式：sum(volumes[7:13]) / sum(volumes[0:6])（后半段/前半段）
    5. 遵循数据层架构原则：因子数据预计算存储到统一数据源
- v1.36 (2026-06-03): 新增两个缺失因子：
    1. 新增 intraday_intensity 到 _EXTENDED_FACTOR_COLS（日内价格强度）
    2. 新增 tail_volume_shrink 到 _EXTENDED_FACTOR_COLS（尾盘缩量程度）
    3. 新增 _calc_intraday_intensity() 函数（(close-open)/(high-low)）
    4. 新增 _calc_tail_volume_shrink() 函数（尾盘成交量总和/全天成交量）
    5. 在 generate_all_factors 中添加 Step 10 计算 intraday_intensity
    6. 在 _calculate_tail_factors 中添加 tail_volume_shrink 计算
    7. 更新 metadata valid_records 包含 intraday_intensity/tail_volume_acceleration/tail_volume_shrink
    8. 遵循数据层架构原则：因子数据预计算存储到统一数据源
- v1.37 (2026-06-04): 新增当日涨跌幅因子（遵循 PROJECT.md 因子开发规范）：
    1. 新增 past_return_1d 到 _EXTENDED_FACTOR_COLS（当日涨跌幅）
    2. 新增 Step 3.5 计算 past_return_1d（调用 calculate_past_return_1d）
    3. 导入 calculate_past_return_1d 函数
    4. 公式：close[t] / close[t-1] - 1（当日涨跌幅）
    5. 遵循 PROJECT.md 规范：因子计算在 data_fetchers 完成，存储到统一数据源
- v1.38 (2026-06-05): 新增动量强度因子（遵循 PROJECT.md 因子开发规范）：
    1. 新增 return_5d 到 _EXTENDED_FACTOR_COLS（5日累计涨幅，momentum_strength 前置依赖）
    2. 新增 momentum_strength 到 _EXTENDED_FACTOR_COLS（动量强度因子）
    3. 导入 calculate_return_5d 和 calculate_momentum_strength 函数
    4. 新增 Step 8.5 计算 return_5d（调用 calculate_return_5d）
    5. 新增 Step 8.6 计算 momentum_strength（调用 calculate_momentum_strength）
    6. 公式：momentum_strength = return_5d / std(return_1d, 5日)
    7. 遵循 PROJECT.md 规范：因子计算在 data_fetchers 完成，存储到统一数据源
- v1.39 (2026-06-11): 涨跌停零波动处理（tail_price_position 公式分母为零不再是 NaN）：
    1. _calc_price_position 新增 daily_close/high/low 参数，涨跌停时 position=1.0/0.0
    2. 涨停：尾盘价格锁定涨停板 → 收盘价=区间最高点 → position=1.0（最强信号）
    3. 跌停：尾盘价格锁定跌停板 → 收盘价=区间最低点 → position=0.0（最弱信号）
    4. 极端罕见无交易非涨跌停 → position=0.5（中性）
    5. 日线数据缺失无法判断方向 → 仍返回 NaN
- v1.40 (2026-06-11): 新增止跌信号差分因子（4个，遵循 H5 因子方向不预判）：
    1. 新增 amplitude_delta 到 _EXTENDED_FACTOR_COLS（振幅差分因子）
    2. 新增 turnover_surge_delta 到 _EXTENDED_FACTOR_COLS（换手突增差分因子）
    3. 新增 tail_price_position_delta 到 _EXTENDED_FACTOR_COLS（尾盘位置差分因子）
    4. 新增 tail_volume_shrink_delta 到 _EXTENDED_FACTOR_COLS（尾盘缩量差分因子）
    5. 新增 Step 11.5 计算4个差分因子（依赖原始因子已计算）
    6. 公式：delta = factor(T) - factor(T-1)，按asset分组shift(1)
    7. metadata valid_records/valid_records_percent 同步更新
- v1.42 (2026-06-12): 新增行业级别方向性因子（Pattern 14）：
    1. 新增 industry_momentum_5d 到 _EXTENDED_FACTOR_COLS（行业5日动量）
    2. 新增 industry_turnover_trend 到 _EXTENDED_FACTOR_COLS（行业换手率趋势）
    3. 新增 industry_amplitude_trend 到 _EXTENDED_FACTOR_COLS（行业振幅趋势）
    4. 新增 Step 11.7 计算行业级别方向性因子
    5. 公式：按(行业,日期)分组聚合→赋给同行业每只个股
    6. 实测结论：个股方向性IC全负，行业层面IC=+0.026（方向性信号存在于行业而非个股）
    7. 遵循 H5：IC方向不预判，行业因子作为行业配置维度补充

作者: 云瑶
"""

import argparse
import gzip
import json
import logging
import math
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


# ============================================================================
# 条件导入：__main__ 时添加 sys.path + 绝对导入，其他时候使用相对导入
# 注意：sys.path.insert 是必要的，因为脚本需要能够直接运行
# 遵循 stock_utils.py 的条件导入模式
if __name__ == "__main__":
    project_root = Path(__file__).parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    # 重构后统一从 factor_calculator 导入因子计算函数（遵循 MODULE.md 约束 #3）
    from data_fetchers.common.logger_config import setup_logger
    from data_fetchers.factor_calculator import (
        calculate_amplitude,
        calculate_amplitude_delta,  # v1.40 新增：振幅差分因子
        calculate_bollinger_pb,
        calculate_industry_amplitude_trend,  # v1.42 新增：行业振幅趋势因子
        calculate_industry_earnings_growth,  # v1.43 新增：行业盈利增长因子
        calculate_industry_momentum_5d,  # v1.42 新增：行业5日动量因子
        calculate_industry_pe_trend,  # v1.43 新增：行业PE趋势因子
        calculate_industry_roe_trend,  # v1.43 新增：行业ROE趋势因子
        calculate_industry_turnover_trend,  # v1.42 新增：行业换手率趋势因子
        calculate_capital_flow_ratio_trend,  # v1.44 新增：资金流占比趋势因子（方案C）
        calculate_capital_flow_intensity,  # v1.44 新增：资金流强度因子（方案C）
        calculate_kdj_j,
        calculate_ma5_deviation,  # v1.41 新增：5日均线偏离度因子
        calculate_momentum_strength,  # v1.37 新增
        calculate_near_high_ratio_5,  # v1.41 新增：近5日高低位置因子
        calculate_overnight_return,
        calculate_past_return_1d,  # 当日涨跌幅
        calculate_positive_day_ratio_5,  # v1.41 新增：5日阳线比例因子
        calculate_price_position,
        calculate_return_5d,  # v1.37 新增：5日累计涨幅
        calculate_tail_price_position_delta,  # v1.40 新增：尾盘位置差分因子
        calculate_tail_volume_shrink_delta,  # v1.40 新增：尾盘缩量差分因子
        calculate_turnover_surge,
        calculate_turnover_surge_delta,  # v1.40 新增：换手突增差分因子
        calculate_volume_price_strength,  # v1.41 新增：量价齐升因子
    )
else:
    # 重构后统一从 factor_calculator 导入因子计算函数（遵循 MODULE.md 约束 #3）
    from .common.logger_config import setup_logger
    from .factor_calculator import (
        calculate_amplitude,
        calculate_amplitude_delta,  # v1.40 新增：振幅差分因子
        calculate_bollinger_pb,
        calculate_industry_amplitude_trend,  # v1.42 新增：行业振幅趋势因子
        calculate_industry_earnings_growth,  # v1.43 新增：行业盈利增长因子
        calculate_industry_momentum_5d,  # v1.42 新增：行业5日动量因子
        calculate_industry_pe_trend,  # v1.43 新增：行业PE趋势因子
        calculate_industry_roe_trend,  # v1.43 新增：行业ROE趋势因子
        calculate_industry_turnover_trend,  # v1.42 新增：行业换手率趋势因子
        calculate_capital_flow_ratio_trend,  # v1.44 新增：资金流占比趋势因子（方案C）
        calculate_capital_flow_intensity,  # v1.44 新增：资金流强度因子（方案C）
        calculate_kdj_j,
        calculate_ma5_deviation,  # v1.41 新增：5日均线偏离度因子
        calculate_momentum_strength,  # v1.37 新增
        calculate_near_high_ratio_5,  # v1.41 新增：近5日高低位置因子
        calculate_overnight_return,
        calculate_past_return_1d,  # 当日涨跌幅
        calculate_positive_day_ratio_5,  # v1.41 新增：5日阳线比例因子
        calculate_price_position,
        calculate_return_5d,  # v1.37 新增：5日累计涨幅
        calculate_tail_price_position_delta,  # v1.40 新增：尾盘位置差分因子
        calculate_tail_volume_shrink_delta,  # v1.40 新增：尾盘缩量差分因子
        calculate_turnover_surge,
        calculate_turnover_surge_delta,  # v1.40 新增：换手突增差分因子
        calculate_volume_price_strength,  # v1.41 新增：量价齐升因子
    )

# ============================================================================
# 模块级 fallback logger（遵循 PROJECT.md 公共模块日志规范）
# ============================================================================
_MODULE_LOGGER = logging.getLogger("data_fetchers.factor_generator")

# ============================================================================
# 公共 API 导出
# ============================================================================
__all__ = [
    "generate_all_factors",
    "get_module_logger",
]

# ============================================================================
# 默认路径配置（私有常量）
# ============================================================================

# 输入输出数据路径（result 目录：统一数据源，遵循 PROJECT.md 跨模块数据路径规范）
# 数据由 fetch_factor_cache.py 和 fetch_turnover.py 输出到 result 目录，本模块从该目录读取并输出
# parent=data_fetchers/, 路径为 data_fetchers/result/
# 注：输入输出路径相同，若未来需分离可再拆分常量
_DEFAULT_RESULT_DIR = Path(__file__).parent / "result"

# 扩展因子列名（元组防止意外修改）
# v1.33 新增尾盘因子：tail_price_position, tail_price_slope, tail_price_volume_intensity
# v1.34 新增隔夜收益率因子：overnight_ret（跳空幅度）
# v1.35 新增尾盘量能加速度因子：tail_volume_acceleration（后半段/前半段成交量比）
# v1.37 新增动量强度因子：momentum_strength（5日涨幅/5日波动率）
_EXTENDED_FACTOR_COLS: tuple[str, ...] = (
    "past_return_1d",  # 当日涨跌幅（遵循 PROJECT.md 规则：因子计算在 data_fetchers 完成）
    "bollinger_pb",
    "kdj_j",
    "turnover_surge",
    "amplitude",
    "price_position",
    "return_5d",  # v1.37 新增：5日累计涨幅（momentum_strength 的前置依赖）
    "momentum_strength",  # v1.37 新增：动量强度因子
    "overnight_ret",
    "intraday_intensity",
    "tail_price_position",
    "tail_price_slope",
    "tail_price_volume_intensity",
    "tail_volume_acceleration",
    "tail_volume_shrink",
    "amplitude_delta",  # v1.40 新增：振幅差分因子
    "turnover_surge_delta",  # v1.40 新增：换手突增差分因子
    "tail_price_position_delta",  # v1.40 新增：尾盘位置差分因子
    "tail_volume_shrink_delta",  # v1.40 新增：尾盘缩量差分因子
    "volume_price_strength",  # v1.41 新增：量价齐升因子
    "positive_day_ratio_5",  # v1.41 新增：5日阳线比例因子
    "ma5_deviation",  # v1.41 新增：5日均线偏离度因子
    "near_high_ratio_5",  # v1.41 新增：近5日高低位置因子
    "industry_momentum_5d",  # v1.42 新增：行业5日动量因子
    "industry_turnover_trend",  # v1.42 新增：行业换手率趋势因子
    "industry_amplitude_trend",  # v1.42 新增：行业振幅趋势因子
    "industry_roe_trend",  # v1.43 新增：行业ROE趋势因子（方案B）
    "industry_earnings_growth",  # v1.43 新增：行业盈利增长因子（方案B）
    "industry_pe_trend",  # v1.43 新增：行业PE趋势因子（方案B）
    "capital_flow_ratio_trend",  # v1.44 新增：资金流占比趋势因子（方案C）
    "capital_flow_intensity",  # v1.44 新增：资金流强度因子（方案C）
)

# 收益数据列名（元组防止意外修改）
_RETURN_COLS: tuple[str, ...] = ("forward_return_1d", "forward_return_3d", "forward_return_5d")

# 基础列名（元组防止意外修改）
# 包含：索引字段 + 行情数据 + 基础因子 + 换手率（从换手率数据合并）+ 成交量（尾盘量比计算需要）
_BASE_COLS: tuple[str, ...] = (
    "date",
    "asset",
    "open",
    "close",
    "high",
    "low",
    "rsi_6",
    "volume_ratio_5",
    "turnover_rate",
    "volume",
)

# 输出列名：基础列 + 扩展因子 + 收益数据（元组防止意外修改）
# 组成：_BASE_COLS(10) + _EXTENDED_FACTOR_COLS(15) + _RETURN_COLS(3)
_OUTPUT_COLS: tuple[str, ...] = _BASE_COLS + _EXTENDED_FACTOR_COLS + _RETURN_COLS


# ============================================================================
# 尾盘因子计算常量
# ============================================================================

# 尾盘数据路径（遵循 PROJECT.md H7 规则：使用 paths.py 单一来源）
_TAIL_TRADING_DATA_PATH = _DEFAULT_RESULT_DIR / "tail_trading_data.json.gz"

# 尾盘因子计算参数
EPSILON = 1e-10  # 避免除零阈值
_TAIL_KLINE_COUNT = 13  # 尾盘5分钟K线数量（14:00-15:00共13根K线）

# ============================================================================
# 日内因子计算函数（基于 OHLC 数据）
# ============================================================================


def _calc_intraday_intensity(
    open_price: float | None, close_price: float | None, high: float | None, low: float | None
) -> float:
    """
    计算日内价格强度（收盘价在振幅中的相对位置）

    公式:
    - 日内价格强度 = (close - open) / (high - low)

    Args:
        open_price: 开盘价
        close_price: 收盘价
        high: 最高价
        low: 最低价

    Returns:
        日内价格强度值，理论范围 [-1, 1]，或 NaN（数据不完整/除零）

    Note:
        - 正值表示收盘价高于开盘价（上涨），负值表示下跌
        - 数值越大表示上涨强度越强，数值越小表示下跌强度越强
        - 遵循 MODULE.md 约束 #5：类型守卫先用 isinstance 再用 pd.isna
    """
    # 类型守卫：检查 None
    if open_price is None or close_price is None or high is None or low is None:
        return np.nan
    # 类型守卫：参数必须是数值
    if not all(isinstance(p, (int, float)) for p in [open_price, close_price, high, low]):
        return np.nan

    price_range = high - low
    if abs(price_range) < EPSILON:
        return np.nan

    return (close_price - open_price) / price_range


# ============================================================================
# 尾盘因子计算函数（从 factor_ic/ic_tail_price_*.py 迁移）
# ============================================================================


def _load_tail_trading_data(logger: logging.Logger) -> pd.DataFrame:
    """
    加载尾盘5分钟K线数据

    Args:
        logger: 日志记录器

    Returns:
        pd.DataFrame: 尾盘数据，包含 date, asset, prices, volumes, tail_high, tail_low 列

    Note:
        - 文件不存在时返回空 DataFrame（而非抛异常）
        - 日志记录加载状态
        - 遵循 MODULE.md 约束 #4：函数入口先 copy()
    """
    if not _TAIL_TRADING_DATA_PATH.exists():
        logger.warning("尾盘数据文件不存在: %s，尾盘因子将为 NaN", _TAIL_TRADING_DATA_PATH)
        return pd.DataFrame()

    try:
        with gzip.open(_TAIL_TRADING_DATA_PATH, "rt", encoding="utf-8") as f:
            data = json.load(f)
    except gzip.BadGzipFile as e:
        logger.error("尾盘数据 gzip 文件损坏: %s, 原因: %s", _TAIL_TRADING_DATA_PATH, str(e))
        return pd.DataFrame()
    except json.JSONDecodeError as e:
        logger.error("尾盘数据 JSON 解析失败: %s, 行 %d, 列 %d", _TAIL_TRADING_DATA_PATH, e.lineno, e.colno)
        return pd.DataFrame()

    if "data" not in data:
        logger.error("尾盘数据缺少 'data' 字段: %s", _TAIL_TRADING_DATA_PATH)
        return pd.DataFrame()

    df = pd.DataFrame(data["data"])
    logger.info("尾盘数据加载完成: %d 条记录", len(df))
    return df


def _get_close_price(prices: list | None) -> float:
    """
    获取尾盘收盘价（prices[-1])

    Args:
        prices: 尾盘价格列表（13根5分钟K线收盘价）

    Returns:
        尾盘收盘价，或 NaN（数据不完整时）
    """
    if not isinstance(prices, list):
        return np.nan
    if len(prices) < _TAIL_KLINE_COUNT:
        return np.nan
    return prices[-1]


def _calc_price_position(
    close_price: float,
    tail_high: float,
    tail_low: float,
    daily_close: float | None = None,
    daily_high: float | None = None,
    daily_low: float | None = None,
) -> float:
    """
    计算尾盘价格位置

    公式:
    - 尾盘价格位置 = (收盘价 - 尾盘最低价) / (尾盘最高价 - 尾盘最低价)
    - 理论范围 [0, 1]

    涨跌停处理（v1.39）:
    - 当 tail_high == tail_low（零波动）时，公式分母为零 → 0/0 无定义
    - 涨停：尾盘价格锁定在涨停板，收盘价=区间最高点 → position = 1.0（最强信号）
    - 跌停：尾盘价格锁定在跌停板，收盘价=区间最低点 → position = 0.0（最弱信号）
    - 判断方法：close == daily_high → 涨停方向 → 1.0；close == daily_low → 跌停方向 → 0.0
    - 极端罕见无交易且非涨跌停 → 0.5（中性，无信号）

    Args:
        close_price: 尾盘收盘价
        tail_high: 尾盘最高价
        tail_low: 尾盘最低价
        daily_close: 日线收盘价（涨跌停判断需要，可选）
        daily_high: 日线最高价（涨跌停判断需要，可选）
        daily_low: 日线最低价（涨跌停判断需要，可选）

    Returns:
        尾盘价格位置，理论范围 [0, 1]，或 NaN（输入缺失）
    """
    if pd.isna(close_price) or pd.isna(tail_high) or pd.isna(tail_low):
        return np.nan
    price_range = tail_high - tail_low
    if abs(price_range) < EPSILON:
        # v1.39: 零波动不是缺失数据——涨跌停是极端明确的信号
        # 涨停：收盘价在区间最高点 → position = 1.0
        # 跌停：收盘价在区间最低点 → position = 0.0
        # 判断依据：日线 close 与 high/low 的关系
        if (
            daily_close is not None
            and not pd.isna(daily_close)
            and daily_high is not None
            and not pd.isna(daily_high)
            and daily_low is not None
            and not pd.isna(daily_low)
        ):
            if daily_close == daily_high:
                # 涨停（含一字涨停）：收盘价=日线最高 → 尾盘位置=1.0
                return 1.0
            if daily_close == daily_low:
                # 跌停（含一字跌停）：收盘价=日线最低 → 尾盘位置=0.0
                return 0.0
            # 极端罕见：零波动但非涨跌停（如尾盘无成交但日内有波动）
            # 中性填充：position = 0.5
            return 0.5
        # 日线数据缺失时无法判断方向，仍返回 NaN
        return np.nan
    return (close_price - tail_low) / price_range


def _calc_tail_price_slope(prices: list | None) -> float:
    """
    计算尾盘趋势斜率（百分比形式）

    公式:
    - 线性回归：对 prices 数组做回归，得到 slope
    - 百分比斜率：factor_value = slope / mean_price

    Args:
        prices: 13根5分钟K线收盘价列表

    Returns:
        百分比斜率，或 NaN（数据不完整/除零）
    """
    if not isinstance(prices, list):
        return np.nan
    if len(prices) < _TAIL_KLINE_COUNT:
        return np.nan

    Y = np.array(prices)
    if np.any(np.isnan(Y)):
        return np.nan

    X = np.arange(_TAIL_KLINE_COUNT)
    try:
        slope, _ = np.polyfit(X, Y, 1)
    except np.linalg.LinAlgError:
        return np.nan

    mean_price = np.mean(Y)
    if abs(mean_price) < EPSILON:
        return np.nan

    return slope / mean_price


def _calc_tail_price_volume_intensity(prices: list | None, volumes: list | None, total_volume: float | None) -> float:
    """
    计算尾盘量价强度

    公式:
    - 尾盘涨跌幅 = (prices[-1] - prices[0]) / prices[0]
    - 尾盘量比 = sum(volumes) / volume
    - 尾盘量价强度 = 尾盘涨跌幅 × 尾盘量比

    Args:
        prices: 13根5分钟K线收盘价列表
        volumes: 13根5分钟K线成交量列表
        total_volume: 全天成交量

    Returns:
        尾盘量价强度，或 NaN（数据不完整/除零）
    """
    # 类型守卫：检查 None
    if prices is None or volumes is None or total_volume is None:
        return np.nan
    if not isinstance(prices, list) or not isinstance(volumes, list):
        return np.nan
    if len(prices) < _TAIL_KLINE_COUNT or len(volumes) < _TAIL_KLINE_COUNT:
        return np.nan
    # 类型守卫：total_volume 必须是数值
    if not isinstance(total_volume, (int, float)):
        return np.nan
    if abs(float(total_volume)) < EPSILON:
        return np.nan

    first_price = prices[0]
    last_price = prices[-1]
    if abs(first_price) < EPSILON:
        return np.nan

    price_change = (last_price - first_price) / first_price
    tail_volume = sum(volumes)
    volume_ratio = tail_volume / float(total_volume)

    return price_change * volume_ratio


def _calc_tail_volume_acceleration(volumes: list | None) -> float:
    """
    计算尾盘量能加速度（后半段/前半段成交量比）

    公式:
    - 前半段成交量总和 = sum(volumes[0:6])  # 14:00-14:25
    - 后半段成交量总和 = sum(volumes[7:13])  # 14:35-15:00
    - 量能加速度 = 后半段 / 前半段

    Args:
        volumes: 13根5分钟K线成交量列表

    Returns:
        量能加速度值，或 NaN（数据不完整/除零）

    Note:
        - 14:30（索引6）不属于任何一段
        - 遵循 MODULE.md 约束 #5：类型守卫先用 isinstance 再用 pd.isna
    """
    # 类型守卫：检查 None/非列表类型
    if volumes is None:
        return np.nan
    if not isinstance(volumes, list):
        return np.nan
    if len(volumes) < 13:
        return np.nan
    # 检查是否包含 NaN/None
    if any(v is None or (isinstance(v, float) and np.isnan(v)) for v in volumes):
        return np.nan

    # 前半段成交量总和（索引 0-5）
    front_volume = sum(volumes[0:6])
    # 后半段成交量总和（索引 7-12）
    back_volume = sum(volumes[7:13])

    # 除零防护
    if front_volume < EPSILON:
        return np.nan

    return back_volume / front_volume


def _calc_tail_volume_shrink(volumes: list | None, total_volume: float | None) -> float:
    """
    计算尾盘缩量程度（尾盘成交量总和/全天成交量）

    公式:
    - 尾盘缩量程度 = sum(volumes) / total_volume

    Args:
        volumes: 13根5分钟K线成交量列表（14:00-15:00）
        total_volume: 全天成交量

    Returns:
        尾盘缩量程度值，理论范围 [0, 1]，或 NaN（数据不完整/除零）

    Note:
        - 数值越小表示尾盘缩量越明显
        - 遵循 MODULE.md 约束 #5：类型守卫先用 isinstance 再用 pd.isna
    """
    # 类型守卫：检查 None
    if volumes is None or total_volume is None:
        return np.nan
    if not isinstance(volumes, list):
        return np.nan
    if len(volumes) < _TAIL_KLINE_COUNT:
        return np.nan
    # 类型守卫：total_volume 必须是数值
    if not isinstance(total_volume, (int, float)):
        return np.nan
    if abs(float(total_volume)) < EPSILON:
        return np.nan

    # 检查 volumes 是否包含 NaN/None
    if any(v is None or (isinstance(v, float) and np.isnan(v)) for v in volumes):
        return np.nan

    tail_volume = sum(volumes)
    return tail_volume / float(total_volume)


def _calculate_tail_factors(factor_df: pd.DataFrame, logger: logging.Logger) -> pd.DataFrame:
    """
    计算所有尾盘因子（合并计算，避免重复加载尾盘数据）

    Args:
        factor_df: 包含 date, asset, volume 列的 DataFrame
        logger: 日志记录器

    Returns:
        DataFrame，新增 tail_price_position, tail_price_slope, tail_price_volume_intensity, tail_volume_acceleration, tail_volume_shrink 列

    Note:
        - 遵循 MODULE.md 约束 #4：函数入口先 copy()
        - 尾盘数据不存在时返回全 NaN
        - 合并计算减少内存占用和数据加载次数
    """
    factor_df = factor_df.copy()

    # 加载尾盘数据
    tail_df = _load_tail_trading_data(logger)
    if tail_df.empty:
        factor_df["tail_price_position"] = np.nan
        factor_df["tail_price_slope"] = np.nan
        factor_df["tail_price_volume_intensity"] = np.nan
        factor_df["tail_volume_acceleration"] = np.nan
        factor_df["tail_volume_shrink"] = np.nan
        return factor_df

    # 确保日期格式一致
    factor_df["date"] = pd.to_datetime(factor_df["date"]).dt.strftime("%Y-%m-%d")
    tail_df["date"] = pd.to_datetime(tail_df["date"]).dt.strftime("%Y-%m-%d")

    # 合并尾盘数据
    merge_cols = ["date", "asset", "prices", "tail_high", "tail_low"]
    if "volumes" in tail_df.columns:
        merge_cols.append("volumes")

    merged_df = factor_df.merge(tail_df[merge_cols], on=["date", "asset"], how="left")

    logger.info("尾盘数据合并完成: %d / %d 条匹配", merged_df["prices"].notna().sum(), len(factor_df))

    # 计算尾盘收盘价
    merged_df["tail_close"] = merged_df["prices"].apply(_get_close_price)

    # 计算尾盘价格位置（v1.39: 传入日线 close/high/low 用于涨跌停判断）
    merged_df["tail_price_position"] = merged_df.apply(
        lambda row: _calc_price_position(
            row["tail_close"],
            row["tail_high"],
            row["tail_low"],
            daily_close=row.get("close"),
            daily_high=row.get("high"),
            daily_low=row.get("low"),
        ),
        axis=1,
    )

    # 计算尾盘趋势斜率
    merged_df["tail_price_slope"] = merged_df["prices"].apply(_calc_tail_price_slope)

    # 计算尾盘量价强度
    if "volumes" in merged_df.columns:
        merged_df["tail_price_volume_intensity"] = merged_df.apply(
            lambda row: _calc_tail_price_volume_intensity(row["prices"], row["volumes"], row["volume"]), axis=1
        )
        # 计算尾盘量能加速度（后半段/前半段成交量比）
        merged_df["tail_volume_acceleration"] = merged_df["volumes"].apply(_calc_tail_volume_acceleration)
        # 计算尾盘缩量程度（尾盘成交量总和/全天成交量）
        merged_df["tail_volume_shrink"] = merged_df.apply(
            lambda row: _calc_tail_volume_shrink(row["volumes"], row["volume"]), axis=1
        )
    else:
        merged_df["tail_price_volume_intensity"] = np.nan
        merged_df["tail_volume_acceleration"] = np.nan
        merged_df["tail_volume_shrink"] = np.nan
        logger.warning(
            "尾盘数据缺少 'volumes' 列，tail_price_volume_intensity/tail_volume_acceleration/tail_volume_shrink 将为 NaN"
        )

    # 统计有效因子数量
    for col in [
        "tail_price_position",
        "tail_price_slope",
        "tail_price_volume_intensity",
        "tail_volume_acceleration",
        "tail_volume_shrink",
    ]:
        valid_count = merged_df[col].notna().sum()
        total_count = len(merged_df)
        logger.info(
            "%s 因子计算完成: %d / %d 有效 (%.1f%%)",
            col,
            valid_count,
            total_count,
            100 * valid_count / total_count if total_count > 0 else 0,
        )

    # 返回只包含原列 + 因子列的 DataFrame
    result_cols = list(factor_df.columns) + [
        "tail_price_position",
        "tail_price_slope",
        "tail_price_volume_intensity",
        "tail_volume_acceleration",
        "tail_volume_shrink",
    ]
    return merged_df[result_cols]


# ============================================================================
# 模块级私有辅助函数
# ============================================================================


def _calc_pct(count: int, total: int) -> float:
    """
    计算百分比（除零保护）

    Args:
        count: 记录数（分子，如有效记录数、缺失记录数等），支持 int 或兼容类型
        total: 总记录数（分母），支持 int 或兼容类型

    Returns:
        float: 百分比（0.0-100.0），空数据时返回 0.0

    Example:
        >>> _calc_pct(80, 100)  # 有效记录百分比
        80.0
        >>> _calc_pct(20, 100)  # 缺失记录百分比
        20.0
        >>> _calc_pct(50, 0)  # 空数据，返回 0.0
        0.0

    Note:
        - 通用百分比计算函数，可用于有效记录、缺失记录等场景
        - 参数语义由调用方决定（count 是分子，total 是分母）
        - 类型注解为 int，但实际接受 int、numpy.int64、float 等兼容类型
        - Python 运行时不强制类型检查，注解仅为静态分析提供参考
    """
    if total <= 0:
        return 0.0
    return round(count / total * 100, 2)


# ============================================================================
# logger 获取函数（遵循 PROJECT.md 公共模块日志规范）
# ============================================================================


def get_module_logger(logger: logging.Logger | None = None) -> logging.Logger:
    """
    获取模块 logger

    Args:
        logger: 调用方传入的 logger（可选）

    Returns:
        logging.Logger: 模块 logger

    Raises:
        TypeError: logger 参数不是 logging.Logger 类型

    Note:
        - 如果 logger 为 None，返回模块级 fallback logger
        - 公共模块接收 logger 参数，日志可追溯调用方

    Example:
        >>> logger = get_module_logger()
        >>> logger.name
        'data_fetchers.factor_generator'
        >>> custom_logger = get_module_logger(logging.getLogger("my_app"))
        >>> custom_logger.name
        'my_app'
    """
    if logger is None:
        return _MODULE_LOGGER
    if not isinstance(logger, logging.Logger):
        raise TypeError(f"logger 必须是 logging.Logger 类型，实际类型: {type(logger).__name__}")
    return logger


# ============================================================================
# 统一因子生成入口
# ============================================================================


def generate_all_factors(
    factor_data_path: Path | str | None = None,
    turnover_data_path: Path | str | None = None,
    return_data_path: Path | str | None = None,
    output_path: Path | str | None = None,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    """
    生成所有因子数据（含收益数据）

    Args:
        factor_data_path: 基础因子数据路径（默认 factor_data.json.gz）
        turnover_data_path: 换手率数据路径（默认 turnover_rate_data.json.gz）
        return_data_path: 收益数据路径（默认 return_data.json.gz）
        output_path: 输出路径（默认 factor_ic_data.json.gz）
        logger: 调用方传入的 logger（可选）

    Returns:
        Dict[str, Any]: 元数据字典（包含生成时间、因子列表、运行耗时等）

    Raises:
        FileNotFoundError: 输入数据文件不存在
        ValueError: 数据格式不正确（缺少 'data' 字段）、JSON 解析失败、gzip 文件损坏
        KeyError: 必需字段不存在（输出列不存在）
        RuntimeError: 文件系统错误（磁盘/权限/IO）或未知保存错误

    Note:
        - 输出到 data_fetchers/result/factor_ic_data.json.gz
        - 复用 factor_calculator 计算函数（遵循强制复用规范）
        - 公共模块接收 logger 参数，日志可追溯调用方
        - 运行耗时统计方便性能分析
        - 空数据场景：所有百分比计算均有除零保护，返回 0.0
        - JSONDecodeError 已内部捕获并转换为 ValueError，调用方不会收到 JSONDecodeError

    Example:
        # 以下为示例用法，非实际运行（generate_all_factors 需要输入数据文件）
        >>> from data_fetchers.factor_generator import generate_all_factors
        >>> metadata = generate_all_factors()  # 需要 data_fetchers/result/*.json.gz
        >>> metadata["factor_columns"]  # 返回列表副本，防止外部修改
        ['bollinger_pb', 'kdj_j', 'turnover_surge']
        >>> isinstance(metadata["elapsed_seconds"], float)
        True
    """
    start_time = datetime.now()
    logger = get_module_logger(logger)

    # 默认路径
    factor_data_path = Path(factor_data_path) if factor_data_path else _DEFAULT_RESULT_DIR / "factor_data.json.gz"
    turnover_data_path = (
        Path(turnover_data_path) if turnover_data_path else _DEFAULT_RESULT_DIR / "turnover_rate_data.json.gz"
    )
    return_data_path = Path(return_data_path) if return_data_path else _DEFAULT_RESULT_DIR / "return_data.json.gz"
    output_path = Path(output_path) if output_path else _DEFAULT_RESULT_DIR / "factor_ic_data.json.gz"

    logger.info("=" * 40)
    logger.info("统一因子生成模块")
    logger.info("=" * 40)

    # ========== Step 1: 加载基础因子数据 ==========
    logger.info("Step 1: 加载基础因子数据...")

    try:
        with gzip.open(factor_data_path, "rt", encoding="utf-8") as f:
            base_data = json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"基础因子数据文件不存在: {factor_data_path}") from None
    except gzip.BadGzipFile as e:
        logger.error("gzip 文件损坏: %s, 原因: %s", factor_data_path, str(e))
        raise ValueError(f"gzip 文件损坏: {factor_data_path}") from e
    except json.JSONDecodeError as e:
        # JSONDecodeError 内存优化：提取关键信息，避免 e.doc 内存翻倍
        # 将行列信息合并到异常消息，由调用方统一决定是否记录日志
        raise ValueError(f"JSON解析失败: {factor_data_path}, 行 {e.lineno}, 列 {e.colno}, 信息: {e.msg}") from e

    # 数据验证：检查 'data' 字段存在
    if "data" not in base_data:
        raise ValueError(f"基础因子数据缺少 'data' 字段: {factor_data_path}")

    factor_df = pd.DataFrame(base_data["data"])
    factor_df["date"] = pd.to_datetime(factor_df["date"])

    # 显式释放 base_data 内存（JSON 加载的大对象）
    del base_data

    logger.info("  基础数据记录数: %d", len(factor_df))
    logger.info("  基础因子列: rsi_6, volume_ratio_5")

    # ========== Step 2: 加载换手率数据 ==========
    logger.info("Step 2: 加载换手率数据...")

    try:
        with gzip.open(turnover_data_path, "rt", encoding="utf-8") as f:
            turnover_data = json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"换手率数据文件不存在: {turnover_data_path}") from None
    except gzip.BadGzipFile as e:
        logger.error("gzip 文件损坏: %s, 原因: %s", turnover_data_path, str(e))
        raise ValueError(f"gzip 文件损坏: {turnover_data_path}") from e
    except json.JSONDecodeError as e:
        # JSONDecodeError 内存优化：提取关键信息，避免 e.doc 内存翻倍
        # 将行列信息合并到异常消息，由调用方统一决定是否记录日志
        raise ValueError(f"JSON解析失败: {turnover_data_path}, 行 {e.lineno}, 列 {e.colno}, 信息: {e.msg}") from e

    # 数据验证：检查 'data' 字段存在
    if "data" not in turnover_data:
        raise ValueError(f"换手率数据缺少 'data' 字段: {turnover_data_path}")

    turnover_df = pd.DataFrame(turnover_data["data"])
    # 使用 format='mixed' 处理不同日期格式（有的带时间，有的不带）
    turnover_df["date"] = pd.to_datetime(turnover_df["date"], format="mixed")

    # 显式释放 turnover_data 内存（JSON 加载的大对象）
    del turnover_data

    logger.info("  换手率数据记录数: %d", len(turnover_df))

    # 合并换手率
    factor_df = factor_df.merge(turnover_df[["date", "asset", "turnover_rate"]], on=["date", "asset"], how="left")

    # 显式释放 turnover_df 内存（merge 完成后不再需要）
    del turnover_df

    # 检查换手率缺失情况
    turnover_missing = int(factor_df["turnover_rate"].isna().sum())
    if turnover_missing > 0:
        logger.warning("  换手率缺失记录数: %d (%.2f%%)", turnover_missing, _calc_pct(turnover_missing, len(factor_df)))

    logger.info("  合并后记录数: %d", len(factor_df))

    # ========== Step 3: 加载收益数据 ==========
    logger.info("Step 3: 加载收益数据...")

    try:
        with gzip.open(return_data_path, "rt", encoding="utf-8") as f:
            return_data = json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"收益数据文件不存在: {return_data_path}") from None
    except gzip.BadGzipFile as e:
        logger.error("gzip 文件损坏: %s, 原因: %s", return_data_path, str(e))
        raise ValueError(f"gzip 文件损坏: {return_data_path}") from e
    except json.JSONDecodeError as e:
        # JSONDecodeError 内存优化：提取关键信息，避免 e.doc 内存翻倍
        # 将行列信息合并到异常消息，由调用方统一决定是否记录日志
        raise ValueError(f"JSON解析失败: {return_data_path}, 行 {e.lineno}, 列 {e.colno}, 信息: {e.msg}") from e

    # 数据验证：检查 'data' 字段存在
    if "data" not in return_data:
        raise ValueError(f"收益数据缺少 'data' 字段: {return_data_path}")

    return_df = pd.DataFrame(return_data["data"])
    return_df["date"] = pd.to_datetime(return_df["date"], format="mixed")

    # 显式释放 return_data 内存（JSON 加载的大对象）
    del return_data

    logger.info("  收益数据记录数: %d", len(return_df))

    # 合并收益数据
    factor_df = factor_df.merge(return_df[["date", "asset"] + list(_RETURN_COLS)], on=["date", "asset"], how="left")

    # 显式释放 return_df 内存（merge 完成后不再需要）
    del return_df

    # 检查收益数据缺失情况
    for col in _RETURN_COLS:
        return_missing = int(factor_df[col].isna().sum())
        if return_missing > 0:
            logger.warning(
                "  %s 缺失记录数: %d (%.2f%%)", col, return_missing, _calc_pct(return_missing, len(factor_df))
            )

    logger.info("  合并收益后记录数: %d", len(factor_df))

    # ========== Step 3.5: 计算 past_return_1d（当日涨跌幅） ==========
    logger.info("Step 3.5: 计算当日涨跌幅因子...")

    factor_df = calculate_past_return_1d(factor_df, logger_arg=logger)

    past_return_valid = int(factor_df["past_return_1d"].notna().sum())
    logger.info("  有效 past_return_1d: %d (%.2f%%)", past_return_valid, _calc_pct(past_return_valid, len(factor_df)))

    # ========== Step 4: 计算 bollinger_pb ==========
    logger.info("Step 4: 计算布林带 %B 因子...")

    factor_df = calculate_bollinger_pb(factor_df, logger_arg=logger)

    bollinger_valid = int(factor_df["bollinger_pb"].notna().sum())
    logger.info("  有效 bollinger_pb: %d (%.2f%%)", bollinger_valid, _calc_pct(bollinger_valid, len(factor_df)))

    # ========== Step 5: 计算 kdj_j ==========
    logger.info("Step 5: 计算 KDJ_J 因子...")

    factor_df = calculate_kdj_j(factor_df, logger_arg=logger)

    kdj_valid = int(factor_df["kdj_j"].notna().sum())
    logger.info("  有效 kdj_j: %d (%.2f%%)", kdj_valid, _calc_pct(kdj_valid, len(factor_df)))

    # ========== Step 6: 计算 turnover_surge ==========
    logger.info("Step 6: 计算换手率突增因子...")

    factor_df = calculate_turnover_surge(factor_df, logger_arg=logger)

    surge_valid = int(factor_df["turnover_surge"].notna().sum())
    logger.info("  有效 turnover_surge: %d (%.2f%%)", surge_valid, _calc_pct(surge_valid, len(factor_df)))

    # ========== Step 7: 计算 amplitude ==========
    logger.info("Step 7: 计算振幅因子...")

    factor_df = calculate_amplitude(factor_df, logger_arg=logger)

    amplitude_valid = int(factor_df["amplitude"].notna().sum())
    logger.info("  有效 amplitude: %d (%.2f%%)", amplitude_valid, _calc_pct(amplitude_valid, len(factor_df)))

    # ========== Step 8: 计算 price_position ==========
    logger.info("Step 8: 计算价格位置因子...")

    factor_df = calculate_price_position(factor_df, logger_arg=logger)

    position_valid = int(factor_df["price_position"].notna().sum())
    logger.info("  有效 price_position: %d (%.2f%%)", position_valid, _calc_pct(position_valid, len(factor_df)))

    # ========== Step 8.5: 计算 return_5d（5日累计涨幅） ==========
    logger.info("Step 8.5: 计算5日累计涨幅因子...")

    factor_df = calculate_return_5d(factor_df, logger_arg=logger)

    return_5d_valid = int(factor_df["return_5d"].notna().sum())
    logger.info("  有效 return_5d: %d (%.2f%%)", return_5d_valid, _calc_pct(return_5d_valid, len(factor_df)))

    # ========== Step 8.6: 计算 momentum_strength（动量强度） ==========
    logger.info("Step 8.6: 计算动量强度因子...")

    factor_df = calculate_momentum_strength(factor_df, logger_arg=logger)

    momentum_valid = int(factor_df["momentum_strength"].notna().sum())
    logger.info("  有效 momentum_strength: %d (%.2f%%)", momentum_valid, _calc_pct(momentum_valid, len(factor_df)))

    # ========== Step 9: 计算 overnight_ret（隔夜收益率/跳空幅度） ==========
    logger.info("Step 9: 计算隔夜收益率因子（跳空幅度）...")

    factor_df = calculate_overnight_return(factor_df, logger_arg=logger)

    overnight_valid = int(factor_df["overnight_ret"].notna().sum())
    logger.info("  有效 overnight_ret: %d (%.2f%%)", overnight_valid, _calc_pct(overnight_valid, len(factor_df)))

    # ========== Step 10: 计算 intraday_intensity（日内价格强度） ==========
    logger.info("Step 10: 计算日内价格强度因子...")

    factor_df["intraday_intensity"] = factor_df.apply(
        lambda row: _calc_intraday_intensity(row["open"], row["close"], row["high"], row["low"]), axis=1
    )

    intraday_valid = int(factor_df["intraday_intensity"].notna().sum())
    logger.info("  有效 intraday_intensity: %d (%.2f%%)", intraday_valid, _calc_pct(intraday_valid, len(factor_df)))

    # ========== Step 11: 计算尾盘因子 ==========
    logger.info("Step 11: 计算尾盘因子...")

    factor_df = _calculate_tail_factors(factor_df, logger)

    tail_position_valid = int(factor_df["tail_price_position"].notna().sum())
    tail_slope_valid = int(factor_df["tail_price_slope"].notna().sum())
    tail_intensity_valid = int(factor_df["tail_price_volume_intensity"].notna().sum())
    tail_acceleration_valid = int(factor_df["tail_volume_acceleration"].notna().sum())
    tail_shrink_valid = int(factor_df["tail_volume_shrink"].notna().sum())
    logger.info(
        "  有效 tail_price_position: %d (%.2f%%)", tail_position_valid, _calc_pct(tail_position_valid, len(factor_df))
    )
    logger.info("  有效 tail_price_slope: %d (%.2f%%)", tail_slope_valid, _calc_pct(tail_slope_valid, len(factor_df)))
    logger.info(
        "  有效 tail_price_volume_intensity: %d (%.2f%%)",
        tail_intensity_valid,
        _calc_pct(tail_intensity_valid, len(factor_df)),
    )
    logger.info(
        "  有效 tail_volume_acceleration: %d (%.2f%%)",
        tail_acceleration_valid,
        _calc_pct(tail_acceleration_valid, len(factor_df)),
    )
    logger.info(
        "  有效 tail_volume_shrink: %d (%.2f%%)", tail_shrink_valid, _calc_pct(tail_shrink_valid, len(factor_df))
    )

    # ========== Step 11.5: 计算止跌信号差分因子（Reversal Delta Factors） ==========
    # v1.40 新增：差分因子依赖原始因子（必须在原始因子计算之后）
    # 遵循 H5: 因子方向不预判，IC方向由数据决定
    logger.info("Step 11.5: 计算止跌信号差分因子...")

    # 振幅差分因子：amplitude(T) - amplitude(T-1)
    factor_df = calculate_amplitude_delta(factor_df, logger_arg=logger)
    amplitude_delta_valid = int(factor_df["amplitude_delta"].notna().sum())
    logger.info(
        "  有效 amplitude_delta: %d (%.2f%%)",
        amplitude_delta_valid,
        _calc_pct(amplitude_delta_valid, len(factor_df)),
    )

    # 换手突增差分因子：turnover_surge(T) - turnover_surge(T-1)
    factor_df = calculate_turnover_surge_delta(factor_df, logger_arg=logger)
    turnover_surge_delta_valid = int(factor_df["turnover_surge_delta"].notna().sum())
    logger.info(
        "  有效 turnover_surge_delta: %d (%.2f%%)",
        turnover_surge_delta_valid,
        _calc_pct(turnover_surge_delta_valid, len(factor_df)),
    )

    # 尾盘位置差分因子：tail_price_position(T) - tail_price_position(T-1)
    factor_df = calculate_tail_price_position_delta(factor_df, logger_arg=logger)
    tail_position_delta_valid = int(factor_df["tail_price_position_delta"].notna().sum())
    logger.info(
        "  有效 tail_price_position_delta: %d (%.2f%%)",
        tail_position_delta_valid,
        _calc_pct(tail_position_delta_valid, len(factor_df)),
    )

    # 尾盘缩量差分因子：tail_volume_shrink(T) - tail_volume_shrink(T-1)
    factor_df = calculate_tail_volume_shrink_delta(factor_df, logger_arg=logger)
    tail_shrink_delta_valid = int(factor_df["tail_volume_shrink_delta"].notna().sum())
    logger.info(
        "  有效 tail_volume_shrink_delta: %d (%.2f%%)",
        tail_shrink_delta_valid,
        _calc_pct(tail_shrink_delta_valid, len(factor_df)),
    )

    # ========== Step 11.6: 计算方向性因子（Directional Factors） ==========
    logger.info("Step 11.6: 计算方向性因子...")

    # 量价齐升强度因子
    factor_df = calculate_volume_price_strength(factor_df, logger_arg=logger)
    volume_price_strength_valid = int(factor_df["volume_price_strength"].notna().sum())

    # 近5日阳线比例因子
    factor_df = calculate_positive_day_ratio_5(factor_df, logger_arg=logger)
    positive_day_ratio_5_valid = int(factor_df["positive_day_ratio_5"].notna().sum())

    # 5日均线偏离度因子
    factor_df = calculate_ma5_deviation(factor_df, logger_arg=logger)
    ma5_deviation_valid = int(factor_df["ma5_deviation"].notna().sum())

    # 近5日高低位置因子
    factor_df = calculate_near_high_ratio_5(factor_df, logger_arg=logger)
    near_high_ratio_5_valid = int(factor_df["near_high_ratio_5"].notna().sum())

    # ========== Step 11.7: 计算行业级别方向性因子（Industry-Level Directional Factors） ==========
    logger.info("Step 11.7: 计算行业级别方向性因子...")
    # Note: 行业因子需要 industry 列做分组聚合。统一添加一次 industry 列，3个因子函数共用。
    # industry 列不属于 _OUTPUT_COLS，Step 12 输出时自动排除。

    # 行业5日动量因子
    factor_df = calculate_industry_momentum_5d(factor_df, logger_arg=logger)
    industry_momentum_5d_valid = int(factor_df["industry_momentum_5d"].notna().sum())

    # 行业换手率趋势因子
    factor_df = calculate_industry_turnover_trend(factor_df, logger_arg=logger)
    industry_turnover_trend_valid = int(factor_df["industry_turnover_trend"].notna().sum())

    # 行业振幅趋势因子
    factor_df = calculate_industry_amplitude_trend(factor_df, logger_arg=logger)
    industry_amplitude_trend_valid = int(factor_df["industry_amplitude_trend"].notna().sum())

    # ========== Step 11.8: 计算行业基本面动量因子（方案B：Industry-Level Fundamental Momentum） ==========
    logger.info("Step 11.8: 计算行业基本面动量因子...")
    # Note: 基本面因子函数内部会添加 industry 列（与方案A相同逻辑），用于行业聚合赋个股。
    # 数据来源: financial_data.json.gz（季度财务数据，merge_asof 前推填充对齐日频）

    # 行业ROE趋势因子（行业ΔROE赋个股）
    factor_df = calculate_industry_roe_trend(factor_df, logger_arg=logger)
    industry_roe_trend_valid = int(factor_df["industry_roe_trend"].notna().sum())

    # 行业盈利增长因子（行业净利润增长率赋个股）
    factor_df = calculate_industry_earnings_growth(factor_df, logger_arg=logger)
    industry_earnings_growth_valid = int(factor_df["industry_earnings_growth"].notna().sum())

    # 行业PE趋势因子（行业ΔPE赋个股）
    factor_df = calculate_industry_pe_trend(factor_df, logger_arg=logger)
    industry_pe_trend_valid = int(factor_df["industry_pe_trend"].notna().sum())

    # ========== Step 11.9: 计算资金流因子（方案C：Capital Flow Factors） ==========
    logger.info("Step 11.9: 计算资金流因子...")
    # Note: 资金流因子函数内部会添加 industry 列（与方案A/B相同逻辑）
    # 数据来源: fund_flow_data.json.gz（约120交易日日频数据，精确匹配无需前推填充）
    # ⚠️ 数据覆盖限制: 每只股票约120交易日（API限制），超过此范围的日期 → NaN

    # 资金流占比趋势因子（行业Δ主力净流入占比赋个股）
    factor_df = calculate_capital_flow_ratio_trend(factor_df, logger_arg=logger)
    capital_flow_ratio_trend_valid = int(factor_df["capital_flow_ratio_trend"].notna().sum())

    # 资金流强度因子（行业主力流入绝对额占比赋个股）
    factor_df = calculate_capital_flow_intensity(factor_df, logger_arg=logger)
    capital_flow_intensity_valid = int(factor_df["capital_flow_intensity"].notna().sum())

    # 删除 industry 临时列（不属于 _OUTPUT_COLS，不应出现在最终输出中）
    # Note: 方案A/B/C的因子函数都会添加 industry 列，统一在此删除
    if "industry" in factor_df.columns:
        factor_df = factor_df.drop(columns=["industry"])

    # ========== Step 12: 格式化输出 ==========
    logger.info("Step 12: 格式化输出...")

    # date 列可能在 Step 11 已转换为字符串，需检查类型
    if pd.api.types.is_datetime64_any_dtype(factor_df["date"]):
        factor_df["date"] = factor_df["date"].dt.strftime("%Y-%m-%d")

    # 检查列是否存在（直接使用模块级常量 _OUTPUT_COLS）
    missing_cols = [col for col in _OUTPUT_COLS if col not in factor_df.columns]
    if missing_cols:
        raise KeyError(f"输出列不存在: {missing_cols}，请检查因子计算函数的输出列名是否与 _EXTENDED_FACTOR_COLS 一致")

    output_df = factor_df[list(_OUTPUT_COLS)].copy()  # 元组转列表，pandas 列选择需要列表

    # 显式释放 factor_df 内存（可能包含中间列，比 output_df 更多）
    del factor_df

    # ========== Step 13: 保存输出 ==========
    logger.info("Step 13: 保存输出...")

    # dates 字段：字符串排序对 YYYY-MM-DD 格式正确（字典序与日期序一致）
    # 从 output_df 取 dates，数据来源更清晰
    dates_list = sorted(output_df["date"].unique().tolist())

    total_records = len(output_df)

    # 确保父目录存在（职责分离：mkdir 单独处理，异常信息更精确）
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.error("创建输出目录失败: %s, 原因: %s (%s)", output_path.parent, type(e).__name__, str(e))
        raise RuntimeError(f"创建输出目录失败: {output_path.parent}, {type(e).__name__}: {e}") from e

    # 使用临时文件 + os.replace 原子写入（遵循 PROJECT.md 文件写入规范）
    # ⚠️ 内存优化: 流式写入 JSON，避免 output_df.to_dict("records") 一次性创建4GB+字典
    # 旧方法: json.dump({"dates": ..., "data": output_df.to_dict("records")}, f) → OOM
    # 新方法: 分批写入 {"dates": ..., "data": [row1, row2, ...]} → 内存峰值仅每批行数
    _BATCH_WRITE_SIZE = 50000  # 每批写入5万行，峰值约 50000 × 44列 × 100B ≈ 200MB
    temp_path = output_path.parent / (output_path.name + ".tmp")
    try:
        with gzip.open(temp_path, "wt", encoding="utf-8") as f:
            # 写入 JSON 头部
            f.write("{\"dates\": ")
            json.dump(dates_list, f, ensure_ascii=False)
            f.write(", \"data\": [")

            # ⚠️ NaN→null 处理：json.dump 默认把 float NaN 输出为 "NaN"（非法JSON值）
            # Python json 模块的 JSONEncoder/iterencode 对嵌套 dict 中的 NaN 无法拦截
            # pandas to_dict('records') 把 NaN 输出为 float('nan')，不是 None
            # 唯一可靠方案: 在 to_dict 后遍历每条记录，NaN → None → json 输出为 null
            def _nan_to_null(obj):
                if isinstance(obj, float) and obj != obj:  # NaN (NaN != NaN)
                    return None
                if isinstance(obj, float) and (obj == float('inf') or obj == float('-inf')):
                    return None
                if isinstance(obj, dict):
                    return {k: _nan_to_null(v) for k, v in obj.items()}
                if isinstance(obj, list):
                    return [_nan_to_null(item) for item in obj]
                return obj

            # 分批写入数据行（避免一次性 to_dict("records") 导致 OOM）
            # ⚠️ 关键: 逐条输出每个记录，而不是 json.dump(batch_records)（输出整个数组）
            # 因为 json.dump(batch_records) 会把每批输出为 [...]，逗号连接后变成 [[batch1], [batch2], ...]
            # 正确格式应该是 [record1, record2, ...]，不能嵌套
            total_rows = len(output_df)
            first_record = True
            for batch_start in range(0, total_rows, _BATCH_WRITE_SIZE):
                batch_end = min(batch_start + _BATCH_WRITE_SIZE, total_rows)
                batch_df = output_df.iloc[batch_start:batch_end]
                batch_records = batch_df.to_dict("records")
                # NaN→null 转换（确保 JSON 严格合规）
                batch_records = _nan_to_null(batch_records)
                # 逐条输出每个记录，逗号 + 换行分隔
                for record in batch_records:
                    if not first_record:
                        f.write(",\n")
                    json.dump(record, f, ensure_ascii=False)
                    first_record = False
                # 显式释放批次数据
                del batch_df, batch_records

            # 写入 JSON 尾部
            f.write("]}")

        os.replace(temp_path, output_path)
    except OSError as e:
        # 文件系统错误（磁盘/权限/IO，PermissionError 是 OSError 子类）
        logger.error("文件系统错误保存失败: %s, 原因: %s (%s)", output_path, type(e).__name__, str(e))
        temp_path.unlink(missing_ok=True)  # 原子操作，消除 TOCTOU 竞争窗口
        raise RuntimeError(f"文件系统错误: {output_path}, {type(e).__name__}: {e}") from e
    except Exception as e:
        # 未知错误（兜底）
        logger.error("未知错误保存失败: %s, 原因: %s (%s)", output_path, type(e).__name__, str(e))
        temp_path.unlink(missing_ok=True)  # 原子操作，消除 TOCTOU 竞争窗口
        raise RuntimeError(f"未知错误保存失败: {output_path}, {type(e).__name__}: {e}") from e

    logger.info("  输出路径: %s", output_path)
    logger.info("  输出记录数: %d", total_records)

    # 计算运行耗时
    end_time = datetime.now()
    elapsed_seconds = (end_time - start_time).total_seconds()

    # ========== Step 14: 返回元数据 ==========
    # metadata 字段说明：
    # - generated_at: 生成时间（格式 YYYY-MM-DD HH:MM:SS）
    # - elapsed_seconds: 运行耗时（秒，精度 .2f）
    # - total_records: 输出总记录数
    # - valid_records: 各因子有效记录数（绝对值）
    # - valid_records_percent: 各因子有效记录百分比（与日志输出一致，便于质量评估）
    # - factor_columns: 扩展因子列名（不含基础列和基础因子）
    # - return_columns: 收益数据列名
    # - input_sources: 输入数据源路径
    # - output_path: 输出文件路径

    metadata = {
        "generated_at": end_time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_seconds": round(elapsed_seconds, 2),
        "total_records": total_records,
        "valid_records": {
            "bollinger_pb": bollinger_valid,
            "kdj_j": kdj_valid,
            "turnover_surge": surge_valid,
            "amplitude": amplitude_valid,
            "price_position": position_valid,
            "past_return_1d": past_return_valid,
            "overnight_ret": overnight_valid,
            "return_5d": return_5d_valid,
            "momentum_strength": momentum_valid,
            "intraday_intensity": intraday_valid,
            "tail_price_position": tail_position_valid,
            "tail_price_slope": tail_slope_valid,
            "tail_price_volume_intensity": tail_intensity_valid,
            "tail_volume_acceleration": tail_acceleration_valid,
            "tail_volume_shrink": tail_shrink_valid,
            "amplitude_delta": amplitude_delta_valid,  # v1.40 新增
            "turnover_surge_delta": turnover_surge_delta_valid,  # v1.40 新增
            "tail_price_position_delta": tail_position_delta_valid,  # v1.40 新增
            "tail_volume_shrink_delta": tail_shrink_delta_valid,  # v1.40 新增
            "volume_price_strength": volume_price_strength_valid,  # v1.41 新增
            "positive_day_ratio_5": positive_day_ratio_5_valid,  # v1.41 新增
            "ma5_deviation": ma5_deviation_valid,  # v1.41 新增
            "near_high_ratio_5": near_high_ratio_5_valid,  # v1.41 新增
            "industry_momentum_5d": industry_momentum_5d_valid,  # v1.42 新增
            "industry_turnover_trend": industry_turnover_trend_valid,  # v1.42 新增
            "industry_amplitude_trend": industry_amplitude_trend_valid,  # v1.42 新增
            "industry_roe_trend": industry_roe_trend_valid,  # v1.43 新增（方案B）
            "industry_earnings_growth": industry_earnings_growth_valid,  # v1.43 新增（方案B）
            "industry_pe_trend": industry_pe_trend_valid,  # v1.43 新增（方案B）
            "capital_flow_ratio_trend": capital_flow_ratio_trend_valid,  # v1.44 新增（方案C）
            "capital_flow_intensity": capital_flow_intensity_valid,  # v1.44 新增（方案C）
        },
        "valid_records_percent": {
            "bollinger_pb": _calc_pct(bollinger_valid, total_records),
            "kdj_j": _calc_pct(kdj_valid, total_records),
            "turnover_surge": _calc_pct(surge_valid, total_records),
            "amplitude": _calc_pct(amplitude_valid, total_records),
            "price_position": _calc_pct(position_valid, total_records),
            "past_return_1d": _calc_pct(past_return_valid, total_records),
            "overnight_ret": _calc_pct(overnight_valid, total_records),
            "return_5d": _calc_pct(return_5d_valid, total_records),
            "momentum_strength": _calc_pct(momentum_valid, total_records),
            "intraday_intensity": _calc_pct(intraday_valid, total_records),
            "tail_price_position": _calc_pct(tail_position_valid, total_records),
            "tail_price_slope": _calc_pct(tail_slope_valid, total_records),
            "tail_price_volume_intensity": _calc_pct(tail_intensity_valid, total_records),
            "tail_volume_acceleration": _calc_pct(tail_acceleration_valid, total_records),
            "tail_volume_shrink": _calc_pct(tail_shrink_valid, total_records),
            "amplitude_delta": _calc_pct(amplitude_delta_valid, total_records),  # v1.40 新增
            "turnover_surge_delta": _calc_pct(turnover_surge_delta_valid, total_records),  # v1.40 新增
            "tail_price_position_delta": _calc_pct(tail_position_delta_valid, total_records),  # v1.40 新增
            "tail_volume_shrink_delta": _calc_pct(tail_shrink_delta_valid, total_records),  # v1.40 新增
            "volume_price_strength": _calc_pct(volume_price_strength_valid, total_records),  # v1.41 新增
            "positive_day_ratio_5": _calc_pct(positive_day_ratio_5_valid, total_records),  # v1.41 新增
            "ma5_deviation": _calc_pct(ma5_deviation_valid, total_records),  # v1.41 新增
            "near_high_ratio_5": _calc_pct(near_high_ratio_5_valid, total_records),  # v1.41 新增
            "industry_momentum_5d": _calc_pct(industry_momentum_5d_valid, total_records),  # v1.42 新增
            "industry_turnover_trend": _calc_pct(industry_turnover_trend_valid, total_records),  # v1.42 新增
            "industry_amplitude_trend": _calc_pct(industry_amplitude_trend_valid, total_records),  # v1.42 新增
            "industry_roe_trend": _calc_pct(industry_roe_trend_valid, total_records),  # v1.43 新增（方案B）
            "industry_earnings_growth": _calc_pct(industry_earnings_growth_valid, total_records),  # v1.43 新增（方案B）
            "industry_pe_trend": _calc_pct(industry_pe_trend_valid, total_records),  # v1.43 新增（方案B）
            "capital_flow_ratio_trend": _calc_pct(capital_flow_ratio_trend_valid, total_records),  # v1.44 新增（方案C）
            "capital_flow_intensity": _calc_pct(capital_flow_intensity_valid, total_records),  # v1.44 新增（方案C）
        },
        "factor_columns": list(_EXTENDED_FACTOR_COLS),  # 扩展因子列（返回副本，防止外部修改）
        "return_columns": list(_RETURN_COLS),  # 收益数据列（返回副本，防止外部修改）
        "input_sources": {
            "factor_data": str(factor_data_path),
            "turnover_data": str(turnover_data_path),
            "return_data": str(return_data_path),
        },
        "output_path": str(output_path),
    }

    logger.info("=" * 40)
    logger.info("因子生成完成")
    logger.info("生成时间: %s", metadata["generated_at"])
    logger.info("运行耗时: %.2f 秒", metadata["elapsed_seconds"])
    logger.info("因子列: %s", metadata["factor_columns"])
    logger.info("=" * 40)

    return metadata


# ============================================================================
# CLI 入口
# ============================================================================


def main() -> int:
    """CLI 主入口"""
    parser = argparse.ArgumentParser(description="统一因子生成模块（含收益数据）")
    parser.add_argument("--factor_data", type=str, default=None, help="基础因子数据路径")
    parser.add_argument("--turnover_data", type=str, default=None, help="换手率数据路径")
    parser.add_argument("--return_data", type=str, default=None, help="收益数据路径")
    parser.add_argument("--output", type=str, default=None, help="输出路径")
    parser.add_argument("--quiet", action="store_true", help="静默模式（只输出 ERROR 级别日志）")

    args = parser.parse_args()

    # 设置日志级别
    log_level = logging.ERROR if args.quiet else logging.INFO
    logger = setup_logger("factor_generator", level=log_level)

    # 参数路径转换
    factor_data_path = Path(args.factor_data) if args.factor_data else None
    turnover_data_path = Path(args.turnover_data) if args.turnover_data else None
    return_data_path = Path(args.return_data) if args.return_data else None
    output_path = Path(args.output) if args.output else None

    try:
        metadata = generate_all_factors(
            factor_data_path=factor_data_path,
            turnover_data_path=turnover_data_path,
            return_data_path=return_data_path,
            output_path=output_path,
            logger=logger,
        )
        # CLI 入口执行摘要（关键元数据）
        logger.info(
            "执行摘要: 总记录数=%d, 耗时=%.2f秒, 输出路径=%s",
            metadata["total_records"],
            metadata["elapsed_seconds"],
            metadata["output_path"],
        )
        logger.info("执行成功，退出码: 0")
        return 0
    except Exception as e:
        logger.error("执行失败 [%s]: %s", type(e).__name__, str(e))
        return 1


# ============================================================================
# __main__ CLI 入口
# ============================================================================

if __name__ == "__main__":
    # CLI 入口：调用 main() 函数，测试代码已移至 test_cases/test_factor_generator.py
    # 注意：sys 已在顶部条件块导入，无需重复导入
    sys.exit(main())
