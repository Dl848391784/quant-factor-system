#!/usr/bin/env python3
"""
RSI_1D IC 计算器（重构版） - 1日收益周期

使用公共模块 run_simple_factor_ic() 实现，代码量从 ~774行降至 ~100行。

功能：
1. 从缓存数据计算 RSI(6) 因子的 IC
2. 支持全量计算和增量更新
3. 五维度独立判断（统计显著性、因子方向、经济显著性、ICIR稳定性、IC分布一致性）

作者: 云瑶
重构日期: 2026-05-22
原版作者: 云舟
原版日期: 2026-05-07
"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from factor_ic.common import (
    load_factor_return_data,
    calculate_ic_with_direction_verification,
    build_ic_result,
    incremental_update_ic
)
from factor_ic.common.incremental_engine import UpdateMode, should_use_incremental
# 使用 data_completeness 版本的 get_ic_output_path（输出 ic_<因子名>_analysis_result.json）
from factor_ic.common.data_completeness import get_ic_output_path
from factor_ic.common.logger_config import get_logger

import json

logger = get_logger(__name__)

# ============================================================================
# 参数统一管理（遵循 PROJECT.md 参数传递规范）
# ============================================================================
DEFAULT_MIN_STOCKS = 10


def generate_rsi_ic_data(
    output_file: Path | str | None = None,
    force_full: bool = False,
    min_stocks: int = DEFAULT_MIN_STOCKS
) -> dict:
    """
    从缓存数据计算 RSI IC
    
    参数:
        output_file: 输出文件路径（Path 或 str，内部统一转为 Path）
        force_full: 强制全量计算
        min_stocks: 最小股票数阈值
    
    返回:
        IC 数据字典
    
    规范:
        - 使用公共模块 run_simple_factor_ic()
        - 支持全量/增量/跳过三种模式
        - 输出结构符合 MODULE.md 规范
    """
    # 统一转换为 Path 对象
    if output_file is None:
        output_file = get_ic_output_path('rsi_1d')
    else:
        output_file = Path(output_file)
    
    logger.info("=" * 60)
    logger.info("RSI_1D IC 计算器（重构版） - 1日收益周期")
    logger.info("=" * 60)
    
    # ========== 加载全量数据 ==========
    logger.info("[1/3] 从缓存加载因子和收益数据...")
    try:
        factor_df, return_df, raw_metadata = load_factor_return_data(
            factor_cols=['rsi_6'],
            logger=logger
        )
        logger.info("✓ 加载成功")
        logger.info(f"原始日期范围: {raw_metadata['period_start']} ~ {raw_metadata['period_end']}")
        logger.info(f"原始交易日数: {raw_metadata['total_days']}")
        logger.info(f"过滤后交易日数: {factor_df['date'].nunique()}")
        
    except FileNotFoundError as e:
        raise RuntimeError(f"缓存文件不存在: {e}") from e
    except Exception as e:
        raise RuntimeError(f"数据加载失败: {e}") from e
    
    # ========== 判断模式 ==========
    mode = should_use_incremental(output_file, factor_df, force_full)
    
    # 定义内部函数：全量计算（用于 FULL 模式和 SKIP fallback）
    def do_full_recalculate() -> dict:
        """执行全量计算（用于正常 FULL 模式和 SKIP fallback）"""
        logger.info("[模式] 全量计算")
        logger.info("[2/3] 计算每日 IC...")
        
        # 使用公共模块计算 IC
        ic_result = calculate_ic_with_direction_verification(
            factor_df=factor_df,
            return_df=return_df,
            factor_col='rsi_6',
            return_col='forward_return_1d',
            min_stocks=min_stocks,
            logger=logger
        )
        
        logger.info(f"IC 均值: {ic_result['ic_mean']:.4f}")
        logger.info(f"ICIR: {ic_result['icir']:.2f}")
        logger.info(f"正比例: {ic_result['positive_ratio']:.1%}")
        
        # 使用公共模块构建输出
        result = build_ic_result(
            ic_result=ic_result,
            raw_metadata=raw_metadata,
            factor_name='rsi_1d',
            data_source='cache/factor_data/factor_data.json.gz',
            factor_col='rsi_6'
        )
        
        # ========== 保存结果 ==========
        logger.info(f"[3/3] 保存数据到: {output_file}")
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        logger.info("=" * 60)
        logger.info(f"完成！共计算 {result['sample_stats']['valid_days']} 天有效 IC 数据")
        logger.info(f"更新模式: {result['update_mode']}")
        logger.info("=" * 60)
        
        return result
    
    if mode == UpdateMode.SKIP:
        # ========== 跳过更新（缓存已最新） ==========
        logger.info("[模式] 缓存已最新，跳过更新")
        try:
            with open(output_file, 'r', encoding='utf-8') as f:
                cached_data = json.load(f)
                cached_data['update_mode'] = 'skip'
                return cached_data
        except FileNotFoundError:
            logger.warning("[诊断] 缓存文件不存在，执行全量计算")
            return do_full_recalculate()  # 显式调用，逻辑清晰
        except json.JSONDecodeError as e:
            raise RuntimeError(f"缓存文件损坏: {output_file}\n{e}") from e
    
    elif mode == UpdateMode.INCREMENTAL:
        # ========== 增量更新 ==========
        logger.info("[模式] 增量更新")
        logger.info("[2/3] 执行增量计算...")
        
        result = incremental_update_ic(
            output_path=output_file,
            factor_df_full=factor_df,
            return_df_full=return_df,
            raw_metadata=raw_metadata,
            factor_name='rsi_1d',
            factor_col='rsi_6',
            return_col='forward_return_1d',
            min_stocks=min_stocks
        )
        
        logger.info(f"IC 均值: {result['ic_metrics']['ic_mean']:.4f}")
        logger.info(f"ICIR: {result['icir']:.2f}")
        logger.info(f"更新模式: {result['update_mode']}")
        
        return result
    
    # ========== 全量计算 ==========
    return do_full_recalculate()  # 复用同一函数


# ============================================================================
# 主入口
# ============================================================================

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='RSI_1D IC 计算器（重构版）')
    parser.add_argument('--force-full', action='store_true', help='强制全量计算')
    parser.add_argument('--output', type=str, help='输出文件路径')
    parser.add_argument('--min-stocks', type=int, default=DEFAULT_MIN_STOCKS, help='最小股票数阈值')
    
    args = parser.parse_args()
    
    try:
        result = generate_rsi_ic_data(
            output_file=args.output,
            force_full=args.force_full,
            min_stocks=args.min_stocks
        )
        
        # 使用防御性访问（遵循 MODULE.md __main__ 防御性访问规范）
        ic_metrics = result.get('ic_metrics', {})
        logger.info("=" * 60)
        logger.info("结果摘要:")
        logger.info(f"因子名称: {result.get('factor_name', 'unknown')}")
        logger.info(f"IC 均值: {ic_metrics.get('ic_mean', 0):.4f}")
        logger.info(f"ICIR: {ic_metrics.get('icir', 0):.2f}")
        logger.info(f"更新模式: {result.get('update_mode', 'unknown')}")
        logger.info("=" * 60)
        
    except RuntimeError as e:
        logger.exception("计算失败")  # 使用 .exception() 保留完整堆栈
        sys.exit(1)
    except Exception as e:
        logger.exception("未预期的错误")  # 使用 .exception() 保留完整堆栈
        sys.exit(1)