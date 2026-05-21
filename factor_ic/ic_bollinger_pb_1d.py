#!/usr/bin/env python3
"""
布林带%B 因子 IC 计算器（重构版） - 1日收益周期

使用公共模块实现数据加载和输出构建，保留布林带计算逻辑。
代码量从 ~1129行降至 ~200行（布林带计算保留）。

因子定义：
- Middle Band = SMA(Close, N)
- Upper Band = Middle Band + K × StdDev(Close, N)
- Lower Band = Middle Band - K × StdDev(Close, N)
- %B = (Close - Lower Band) / (Upper Band - Lower Band)

参数：
- N = 20（移动平均周期）
- K = 2.0（标准差倍数）

作者: 云瑶
重构日期: 2026-05-22
原版作者: 云舟
原版日期: 2026-04-07
"""

import sys
from pathlib import Path
import json

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np

# 导入公共模块
from factor_ic.common import (
    load_factor_return_data,
    calculate_ic_with_direction_verification,
    build_ic_result,
    incremental_update_ic
)
from factor_ic.common.incremental_engine import UpdateMode, should_use_incremental
from factor_ic.common.data_completeness import get_ic_output_path, check_data_completeness
from factor_ic.common.logger_config import get_logger
from factor_ic.common.ic_result_builder import save_ic_result

logger = get_logger(__name__)

# ============================================================================
# 参数统一管理
# ============================================================================
DEFAULT_MIN_STOCKS = 10

# 布林带默认参数
DEFAULT_N = 20     # 移动平均周期
DEFAULT_K = 2.0    # 标差倍数


# ============================================================================
# 布林带计算函数
# ============================================================================

def calculate_bollinger_pb(
    factor_df: pd.DataFrame,
    n: int = DEFAULT_N,
    k: float = DEFAULT_K
) -> pd.DataFrame:
    """
    计算布林带 %B 因子
    
    参数:
        factor_df: 包含 close 列的 DataFrame
        n: 移动平均周期
        k: 标差倍数
    
    返回:
        添加了 bollinger_pb 列的 DataFrame
    
    规范:
        - 函数入口必须先 .copy()，避免修改原始数据（MODULE.md DataFrame参数副本规范）
        - 使用 pandas 语义，避免 np.where 混用
    """
    # 函数入口必须先 copy，避免副作用
    factor_df = factor_df.copy()
    
    # 计算 Middle Band（SMA）
    middle = factor_df.groupby('asset')['close'].transform(
        lambda x: x.rolling(n, min_periods=n).mean()
    )
    
    # 计算标准差
    std_dev = factor_df.groupby('asset')['close'].transform(
        lambda x: x.rolling(n, min_periods=n).std()
    )
    
    # 计算上下轨
    upper = middle + k * std_dev
    lower = middle - k * std_dev
    
    # 计算 %B
    # 边界处理：价格在上轨外 %B > 1，在下轨外 %B < 0
    band_width = upper - lower
    
    # 避免除零（使用 EPSILON）
    EPSILON = 1e-10
    
    # 使用 pandas Series.clip 避免 np.where 混用问题
    # 当 band_width 接近 0 时，%B 设为 0.5（中性值）
    safe_band_width = band_width.clip(lower=EPSILON)
    bollinger_pb = (factor_df['close'] - lower) / safe_band_width
    
    # band_width < EPSILON 的位置设为 0.5
    narrow_band_mask = band_width.abs() < EPSILON
    bollinger_pb = bollinger_pb.where(~narrow_band_mask, 0.5)
    
    factor_df['bollinger_pb'] = bollinger_pb
    factor_df['middle_band'] = middle
    factor_df['upper_band'] = upper
    factor_df['lower_band'] = lower
    
    return factor_df


# ============================================================================
# 主函数
# ============================================================================

def generate_bollinger_pb_ic_data(
    output_file: Path | str | None = None,
    force_full: bool = False,
    n: int = DEFAULT_N,
    k: float = DEFAULT_K,
    min_stocks: int = DEFAULT_MIN_STOCKS
) -> dict:
    """
    从缓存数据计算布林带 %B IC
    
    参数:
        output_file: 输出文件路径
        force_full: 强制全量计算
        n: 移动平均周期
        k: 标差倍数
        min_stocks: 最小股票数阈值
    
    返回:
        IC 数据字典
    """
    # 统一转换为 Path 对象
    if output_file is None:
        output_file = get_ic_output_path('bollinger_pb_1d')
    else:
        output_file = Path(output_file)
    
    logger.info("=" * 60)
    logger.info(f"布林带%B IC 计算器（重构版） - 1日收益周期")
    logger.info(f"参数: N={n}, K={k}")
    logger.info("=" * 60)
    
    # ========== Step 1: 加载原始数据 ==========
    logger.info("[1/3] 从缓存加载因子和收益数据...")
    try:
        factor_df, return_df, raw_metadata = load_factor_return_data(
            factor_cols=['close'],
            logger=logger
        )
        logger.info("✓ 加载成功")
        logger.info(f"原始日期范围: {raw_metadata['period_start']} ~ {raw_metadata['period_end']}")
        
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
            # 缓存文件被删除（并发情况），fallback 到全量计算
            logger.info("[诊断] 缓存文件不存在（可能被并发删除），执行全量计算")
            mode = UpdateMode.FULL  # 重置模式，继续执行全量逻辑
        except json.JSONDecodeError as e:
            raise RuntimeError(f"缓存文件损坏: {output_file}\n{e}") from e
    
    elif mode == UpdateMode.INCREMENTAL:
        # ========== 增量更新（缓存滞后） ==========
        logger.info("[模式] 增量更新")
        logger.info("[2/3] 计算布林带 %B 因子（需要全量历史数据）...")
        
        # 注意：布林带计算需要完整的历史 close 数据才能正确计算 rolling mean/std
        factor_df = calculate_bollinger_pb(factor_df, n=n, k=k)
        logger.info("✓ 布林带 %B 计算完成")
        
        logger.info("[3/3] 执行增量 IC 计算...")
        result = incremental_update_ic(
            output_path=output_file,
            factor_df_full=factor_df,
            return_df_full=return_df,
            raw_metadata=raw_metadata,
            factor_name='bollinger_pb_1d',
            factor_col='bollinger_pb',
            return_col='forward_return_1d',
            min_stocks=min_stocks
        )
        
        # 添加布林带参数信息
        result['params'] = {
            'n': n,
            'k': k,
            'factor_col': 'bollinger_pb'
        }
        
        logger.info(f"IC 均值: {result.get('ic_mean', 0):.4f}")
        logger.info(f"ICIR: {result.get('icir', 0):.2f}")
        logger.info(f"更新模式: {result['update_mode']}")
        
        return result
    
    # ========== 全量计算 ==========
    logger.info("[模式] 全量计算")
    logger.info("[2/3] 计算布林带 %B 因子...")
    factor_df = calculate_bollinger_pb(factor_df, n=n, k=k)
    logger.info("✓ 布林带 %B 计算完成")
    
    # ========== Step 3: 计算 IC ==========
    logger.info("[3/3] 计算 IC...")
    ic_result = calculate_ic_with_direction_verification(
        factor_df=factor_df,
        return_df=return_df,
        factor_col='bollinger_pb',
return_col='forward_return_1d',
        min_stocks=min_stocks,
        logger=logger
    )
    
    logger.info(f"IC 均值: {ic_result['ic_mean']:.4f}")
    logger.info(f"ICIR: {ic_result['icir']:.2f}")
    logger.info(f"正比例: {ic_result['positive_ratio']:.1%}")
    
    # ========== Step 4: 构建输出 ==========
    result = build_ic_result(
        ic_result=ic_result,
        raw_metadata=raw_metadata,
        factor_name='bollinger_pb_1d',
        data_source='cache/factor_data/factor_data.json.gz',
        factor_col='bollinger_pb'
    )
    
    # 添加布林带参数信息
    result['params'] = {
        'n': n,
        'k': k,
        'factor_col': 'bollinger_pb'
    }
    
    # 保存结果
    logger.info(f"保存数据到: {output_file}")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    logger.info("=" * 60)
    logger.info(f"完成！共计算 {result['sample_stats']['valid_days']} 天有效 IC 数据")
    logger.info("=" * 60)
    
    return result


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='布林带%B IC 计算器（重构版）')
    parser.add_argument('--force-full', action='store_true', help='强制全量计算')
    parser.add_argument('--output', type=str, help='输出文件路径')
    parser.add_argument('--n', type=int, default=DEFAULT_N, help='移动平均周期')
    parser.add_argument('--k', type=float, default=DEFAULT_K, help='标差倍数')
    
    args = parser.parse_args()
    
    result = generate_bollinger_pb_ic_data(
        output_file=args.output,
        force_full=args.force_full,
        n=args.n,
        k=args.k
    )
    
    logger.info("结果摘要:")
    logger.info(f"因子名称: {result['factor_name']}")
    logger.info(f"IC 均值: {result['ic_metrics']['ic_mean']:.4f}")
    logger.info(f"ICIR: {result['ic_metrics']['icir']:.2f}")