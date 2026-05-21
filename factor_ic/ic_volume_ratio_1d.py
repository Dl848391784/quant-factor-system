#!/usr/bin/env python3
"""
量比因子 IC 计算器（重构版） - 1日收益周期

使用公共模块实现 IC 计算，符合职责边界规范（禁止分层回测）。
代码量从 ~686行降至 ~150行。

功能：
1. 从缓存数据计算量比因子的正向 IC
2. 五维度独立判断
3. 支持 skip/incremental/full 三种更新模式

作者: 云瑶
重构日期: 2026-05-22
增量模式补充: 2026-05-22
职责边界修订: 2026-05-22（删除分层回测逻辑）
原版作者: 云舟
原版日期: 2026-05-08
"""

import sys
from pathlib import Path
import json

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
    save_ic_result
)
from factor_ic.common.incremental_engine import UpdateMode, should_use_incremental
from factor_ic.common.data_completeness import get_ic_output_path
from factor_ic.common.convert_types import convert_to_native_types

# ============================================================================
# 参数统一管理
# ============================================================================
DEFAULT_MIN_STOCKS = 10


def generate_volume_ratio_ic_data(
    output_file: Path | str | None = None,
    force_full: bool = False,
    min_stocks: int = DEFAULT_MIN_STOCKS
) -> dict:
    """
    量比因子 IC 计算主函数（支持三模式）
    
    参数:
        output_file: 输出文件路径
        force_full: 强制全量计算
        min_stocks: 每日最小股票数
    
    返回:
        IC 数据字典
    
    规范:
        - 使用公共模块 run_simple_factor_ic() 模式
        - 支持 skip/incremental/full 三种模式
        - 输出结构符合 MODULE.md 规范
    """
    # 统一转换为 Path 对象
    if output_file is None:
        output_file = get_ic_output_path('volume_ratio_1d')
    else:
        output_file = Path(output_file)
    
    logger.info("=" * 60)
    logger.info("量比因子 IC 计算器（重构版） - 1日收益周期")
    logger.info("=" * 60)
    
    # ========== Step 1: 加载原始数据 ==========
    logger.info("[1/3] 从缓存加载因子和收益数据...")
    try:
        factor_df, return_df, raw_metadata = load_factor_return_data(
            factor_cols=['volume_ratio_5'],
            logger=logger
        )
        logger.info("✓ 加载成功")
        logger.info(f"原始日期范围: {raw_metadata['period_start']} ~ {raw_metadata['period_end']}")
        logger.info(f"过滤后交易日数: {factor_df['date'].nunique()}")
        
    except FileNotFoundError as e:
        raise RuntimeError(f"缓存文件不存在: {e}") from e
    
    # ========== Step 2: 判断模式 ==========
    mode = should_use_incremental(output_file, factor_df, force_full)
    
    if mode == UpdateMode.SKIP:
        # ========== 跳过更新（缓存已最新） ==========
        logger.info("[模式] 缓存已最新，跳过更新")
        try:
            with open(output_file, 'r', encoding='utf-8') as f:
                cached_data = json.load(f)
                cached_data['update_mode'] = 'skip'
                return cached_data
        except FileNotFoundError:
            logger.info("[诊断] 缓存文件不存在，执行全量计算")
        except json.JSONDecodeError as e:
            raise RuntimeError(f"缓存文件损坏: {output_file}\n{e}") from e
    
    elif mode == UpdateMode.INCREMENTAL:
        # ========== 增量更新（缓存滞后） ==========
        logger.info("[模式] 增量更新")
        logger.info("[2/3] 执行增量 IC 计算...")
        
        result = incremental_update_ic(
            output_path=output_file,
            factor_df_full=factor_df,
            return_df_full=return_df,
            raw_metadata=raw_metadata,
            factor_name='volume_ratio_1d',
            factor_col='volume_ratio_5',
            return_col='forward_return_1d',
            min_stocks=min_stocks
        )
        
        logger.info(f"IC 均值: {result.get('ic_mean', 0):.4f}")
        logger.info(f"ICIR: {result.get('icir', 0):.2f}")
        logger.info(f"更新模式: {result['update_mode']}")
        
        return result
    
    # ========== 全量计算 ==========
    logger.info("[模式] 全量计算")
    logger.info("[2/3] 计算 IC...")
    
    ic_result = calculate_ic_with_direction_verification(
        factor_df=factor_df,
        return_df=return_df,
        factor_col='volume_ratio_5',
        return_col='forward_return_1d',
        min_stocks=min_stocks,
        logger=logger
    )
    
    logger.info(f"IC 均值: {ic_result['ic_mean']:.4f}")
    logger.info(f"ICIR: {ic_result['icir']:.2f}")
    logger.info(f"正比例: {ic_result['positive_ratio']:.1%}")
    
    # ========== Step 3: 构建输出 ==========
    logger.info("[3/3] 构建输出结构...")
    
    result = build_ic_result(
        ic_result=ic_result,
        raw_metadata=raw_metadata,
        factor_name='volume_ratio_1d',
        data_source='cache/factor_data/factor_data.json.gz',
        factor_col='volume_ratio_5'
    )
    
    # 转换类型
    result = convert_to_native_types(result)
    result['update_mode'] = 'full'
    
    logger.info("✓ 输出构建完成")
    
    # ========== 保存结果 ==========
    save_ic_result(result, output_file)
    
    logger.info("=" * 60)
    logger.info(f"完成！共计算 {result['sample_stats']['valid_days']} 天有效 IC 数据")
    logger.info(f"更新模式: {result['update_mode']}")
    logger.info("=" * 60)
    
    return result


def main():
    """主函数"""
    try:
        result = generate_volume_ratio_ic_data()
        
        # 使用防御性访问（遵循 MODULE.md __main__ 防御性访问规范）
        ic_metrics = result.get('ic_metrics', {})
        summary = result.get('summary', {})
        logger.info("=" * 60)
        logger.info("关键指标摘要:")
        logger.info(f"IC 均值: {ic_metrics.get('ic_mean', 0):.4f}")
        logger.info(f"ICIR: {ic_metrics.get('icir', 0):.2f}")
        logger.info(f"方向判断: {summary.get('factor_direction', 'unknown')}")
        logger.info("=" * 60)
        
    except FileNotFoundError as e:
        logger.exception("缓存文件不存在")  # 使用 .exception() 保留完整堆栈
        sys.exit(1)
    except Exception as e:
        logger.exception("分析失败")  # 使用 .exception() 保留完整堆栈
        sys.exit(1)


if __name__ == '__main__':
    main()