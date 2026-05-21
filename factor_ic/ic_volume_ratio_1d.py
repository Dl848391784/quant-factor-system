#!/usr/bin/env python3
"""
量比因子 IC 计算器（重构版） - 1日收益周期

使用公共模块实现 IC 计算，符合职责边界规范（禁止分层回测）。
代码量从 ~686行降至 ~150行。

功能：
1. 从缓存数据计算量比因子的正向 IC
2. 五维度独立判断

作者: 云瑶
重构日期: 2026-05-22
职责边界修订: 2026-05-22（删除分层回测逻辑）
原版作者: 云舟
原版日期: 2026-05-08
"""

import sys
from pathlib import Path
import json
from datetime import datetime

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from factor_ic.common.logger_config import get_logger
logger = get_logger(__name__)

# 导入公共模块
from factor_ic.common import (
    load_factor_return_data,
    calculate_ic_with_direction_verification,
    build_ic_result,
    incremental_update_ic,
    should_use_incremental
)
from factor_ic.common.data_completeness import get_ic_output_path
from factor_ic.common.convert_types import convert_to_native_types

# ============================================================================
# 参数统一管理
# ============================================================================
DEFAULT_MIN_STOCKS = 10


def run_volume_ratio_analysis(min_stocks: int = DEFAULT_MIN_STOCKS) -> dict:
    """
    执行量比因子 IC 分析
    
    参数:
        min_stocks: 每日最小股票数
    
    返回:
        IC 分析结果字典（不含分层回测）
    """
    logger.info("=" * 80)
    logger.info("量比因子 IC 分析（重构版）")
    logger.info("=" * 80)
    
    # ========== Step 1: 加载数据 ==========
    logger.info("[1/3] 从缓存加载因子和收益数据...")
    try:
        factor_df, return_df, raw_metadata = load_factor_return_data(
            factor_cols=['volume_ratio_5'],
            logger=logger
        )
        logger.info("✓ 加载成功")
        logger.info(f"- 原始日期范围: {raw_metadata['period_start']} ~ {raw_metadata['period_end']}")
        logger.info(f"- 过滤后交易日数: {factor_df['date'].nunique()}")
        
    except FileNotFoundError as e:
        raise RuntimeError(f"缓存文件不存在: {e}") from e
    
    # ========== Step 2: 计算 IC ==========
    logger.info("[2/3] 计算 IC...")
    ic_result = calculate_ic_with_direction_verification(
        factor_df=factor_df,
        return_df=return_df,
        factor_col='volume_ratio_5',
return_col='forward_return_1d',
        min_stocks=min_stocks,
        logger=logger
    )
    
    logger.info(f"- IC 均值: {ic_result['ic_mean']:.4f}")
    logger.info(f"- ICIR: {ic_result['icir']:.2f}")
    logger.info(f"- 正比例: {ic_result['positive_ratio']:.1%}")
    
    # ========== Step 3: 构建输出 ==========
    logger.info("[3/3] 构建输出结构...")
    
    # 使用公共模块构建 IC 结果
    result = build_ic_result(
        ic_result=ic_result,
        raw_metadata=raw_metadata,
        factor_name='volume_ratio_1d',
        data_source='cache/factor_data/factor_data.json.gz',
        factor_col='volume_ratio_5'
    )
    
    # 转换类型
    result = convert_to_native_types(result)
    
    logger.info("✓ 输出构建完成")
    
    return result


def main():
    """主函数"""
    output_file = get_ic_output_path('volume_ratio_1d')
    
    result = run_volume_ratio_analysis()
    
    # 保存结果
    logger.info(f"保存数据到: {output_file}")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    logger.info("=" * 60)
    logger.info(f"完成！共计算 {result['sample_stats']['valid_days']} 天有效 IC 数据")
    logger.info("=" * 60)
    
    # 打印关键指标
    logger.info("关键指标摘要:")
    logger.info(f"IC 均值: {result['ic_metrics']['ic_mean']:.4f}")
    logger.info(f"ICIR: {result['ic_metrics']['icir']:.2f}")
    logger.info(f"方向判断: {result['summary']['factor_direction']}")


if __name__ == '__main__':
    try:
        main()
    except FileNotFoundError as e:
        logger.error(f"缓存文件不存在: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"分析失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)