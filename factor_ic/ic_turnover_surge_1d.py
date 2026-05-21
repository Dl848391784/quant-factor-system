#!/usr/bin/env python3
"""
换手率突增因子 IC 计算器（重构版） - 1日收益周期

使用公共模块实现数据加载和输出构建，保留换手率突增计算逻辑。
代码量从 ~798行降至 ~200行（换手率计算保留）。

因子定义：
- 换手率突增 = 当日换手率 / 过去5日换手率均值

筛选条件：
- 换手率突增 > 1（当日换手率高于近期均值）
- 当日涨跌幅 > 0（上涨）
- 不满足条件的股票因子值设为 None

作者: 云瑶
重构日期: 2026-05-22
增量模式补充: 2026-05-22
原版作者: 云舟
原版日期: 2026-05-08
"""

import sys
from pathlib import Path
import json
import warnings
warnings.filterwarnings('ignore')

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np

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
from factor_ic.common.data_loader import DEFAULT_CACHE_DIR
from factor_ic.common.logger_config import get_logger

logger = get_logger(__name__)

# ============================================================================
# 参数统一管理
# ============================================================================
DEFAULT_MIN_STOCKS = 10
DEFAULT_SURGE_WINDOW = 5  # 换手率均值计算窗口


# ============================================================================
# 换手率突增计算函数
# ============================================================================

def calculate_turnover_surge(
    factor_df: pd.DataFrame,
    surge_window: int = DEFAULT_SURGE_WINDOW
) -> pd.DataFrame:
    """
    计算换手率突增因子
    
    参数:
        factor_df: 包含 turnover_rate, close 列的 DataFrame
        surge_window: 换手率均值计算窗口
    
    返回:
        添加了 turnover_surge 列的 DataFrame
    
    规范:
        - 函数入口必须先 .copy()，避免修改原始数据（MODULE.md DataFrame参数副本规范）
    """
    # 函数入口必须先 copy，避免副作用
    factor_df = factor_df.copy()
    
    # 计算过去 surge_window 日换手率均值
    avg_turnover = factor_df.groupby('asset')['turnover_rate'].transform(
        lambda x: x.rolling(surge_window, min_periods=surge_window).mean()
    )
    
    # 计算换手率突增
    factor_df['turnover_surge'] = factor_df['turnover_rate'] / avg_turnover
    
    # 筛选条件：
    # 1. 换手率突增 > 1
    # 2. 当日涨跌幅 > 0（close 上涨）
    # 计算涨跌幅（当日 close vs 前一日 close）
    
    # 获取前一日收盘价
    prev_close = factor_df.groupby('asset')['close'].transform(
        lambda x: x.shift(1)
    )
    factor_df['daily_return'] = (factor_df['close'] - prev_close) / prev_close
    
    # 应用筛选条件
    condition = (
        (factor_df['turnover_surge'] > 1) &
        (factor_df['daily_return'] > 0)
    )
    
    # 不满足条件的股票因子值设为 NaN
    factor_df.loc[~condition, 'turnover_surge'] = np.nan
    
    return factor_df


def load_turnover_data(factor_df: pd.DataFrame) -> pd.DataFrame:
    """
    加载并合并换手率数据
    
    参数:
        factor_df: 基础因子数据
    
    返回:
        合并了换手率数据的 DataFrame
    """
    import gzip
    
    turnover_path = DEFAULT_CACHE_DIR / 'turnover_rate_data.json.gz'
    with gzip.open(turnover_path, 'rt', encoding='utf-8') as f:
        turnover_data = json.load(f)
    
    turnover_df = pd.DataFrame(turnover_data['data'])
    turnover_df['turnover_rate'] = pd.to_numeric(turnover_df['turnover_rate'], errors='coerce')
    turnover_df = turnover_df.dropna(subset=['turnover_rate'])
    
    # 处理日期格式（转换为 YYYY-MM-DD）
    turnover_df['date'] = pd.to_datetime(turnover_df['date'], errors='coerce').dt.strftime('%Y-%m-%d')
    
    # 合并换手率数据
    factor_df = pd.merge(
        factor_df,
        turnover_df[['date', 'asset', 'turnover_rate']],
        on=['date', 'asset'],
        how='inner'
    )
    
    return factor_df


# ============================================================================
# 主函数
# ============================================================================

def generate_turnover_surge_ic_data(
    output_file: Path | str | None = None,
    force_full: bool = False,
    surge_window: int = DEFAULT_SURGE_WINDOW,
    min_stocks: int = DEFAULT_MIN_STOCKS
) -> dict:
    """
    从缓存数据计算换手率突增 IC（支持三模式）
    
    参数:
        output_file: 输出文件路径
        force_full: 强制全量计算
        surge_window: 换手率均值计算窗口
        min_stocks: 最小股票数阈值
    
    返回:
        IC 数据字典
    
    规范:
        - 支持 skip/incremental/full 三种模式
        - 输出结构符合 MODULE.md 规范
    """
    # 统一转换为 Path 对象
    if output_file is None:
        output_file = get_ic_output_path('turnover_surge_1d')
    else:
        output_file = Path(output_file)
    
    logger.info("=" * 60)
    logger.info(f"换手率突增 IC 计算器（重构版） - 1日收益周期")
    logger.info(f"参数: surge_window={surge_window}")
    logger.info("=" * 60)
    
    # ========== [1/4] 加载原始数据（前置步骤，所有模式共享） ==========
    logger.info("[1/4] 从缓存加载因子和收益数据...")
    try:
        # 加载基本数据
        factor_df, return_df, raw_metadata = load_factor_return_data(
            factor_cols=['close'],
            logger=logger
        )
        logger.info("✓ 基本数据加载成功")
        
        # 加载并合并换手率数据
        factor_df = load_turnover_data(factor_df)
        logger.info(f"合并换手率后: {len(factor_df)} 行")
        logger.info(f"原始日期范围: {raw_metadata['period_start']} ~ {raw_metadata['period_end']}")
        
    except FileNotFoundError as e:
        # 缓存文件不存在：严重错误，不降级（数据源缺失）
        raise RuntimeError(f"缓存文件不存在，请先运行数据采集: {e}") from e
    except json.JSONDecodeError as e:
        # 缓存文件损坏：严重错误，不降级
        raise RuntimeError(f"缓存文件损坏，请检查数据源: {e}") from e
    except PermissionError as e:
        # 权限错误：严重错误，不降级
        raise RuntimeError(f"缓存文件权限错误: {e}") from e
    except KeyError as e:
        # 数据结构错误：严重错误，不降级（缺失必需字段）
        raise ValueError(f"缓存数据结构错误，缺少必需字段: {e}") from e
    except Exception as e:
        # 其他未预期异常：保留完整堆栈信息，便于诊断
        raise RuntimeError(f"数据加载失败（未预期错误）: {type(e).__name__}: {e}") from e
    
    # ========== Step 2: 判断模式 ==========
    mode = should_use_incremental(output_file, factor_df, force_full)
    
    # 定义内部函数：全量计算（用于 FULL 模式和 SKIP fallback）
    def do_full_recalculate() -> dict:
        """执行全量计算（用于正常 FULL 模式和 SKIP fallback）"""
        logger.info("[模式] 全量计算")
        
        # ========== [2/4] 计算换手率突增因子 ==========
        logger.info("[2/4] 计算换手率突增因子...")
        
        factor_df_local = calculate_turnover_surge(factor_df, surge_window=surge_window)
        
        surge_count = factor_df_local['turnover_surge'].notna().sum()
        total_count = len(factor_df_local)
        logger.info("✓ 换手率突增计算完成")
        logger.info(f"满足条件股票数: {surge_count} / {total_count} ({surge_count/total_count:.1%})")
        
        # ========== [3/4] 计算 IC ==========
        logger.info("[3/4] 计算 IC...")
        ic_result = calculate_ic_with_direction_verification(
            factor_df=factor_df_local,
            return_df=return_df,
            factor_col='turnover_surge',
            return_col='forward_return_1d',
            min_stocks=min_stocks,
            logger=logger
        )
        
        # ========== Step 4: 构建输出 ==========
        result = build_ic_result(
            ic_result=ic_result,
            raw_metadata=raw_metadata,
            factor_name='turnover_surge_1d',
            data_source='cache/factor_data/factor_data.json.gz + turnover_rate_data.json.gz',
            factor_col='turnover_surge'
        )
        
        # 使用 result['ic_metrics'] 统一取值（遵循 MODULE.md 增量更新返回结构统一规范）
        logger.info(f"IC 均值: {result['ic_metrics']['ic_mean']:.4f}")
        logger.info(f"ICIR: {result['ic_metrics']['icir']:.2f}")
        logger.info(f"正比例: {result['positive_ratio']:.1%}")
        
        # 添加参数信息
        result['params'] = {
            'surge_window': surge_window,
            'factor_col': 'turnover_surge',
            'filter_conditions': [
                'turnover_surge > 1',
                'daily_return > 0'
            ]
        }
        result['update_mode'] = 'full'
        
        # ========== [4/4] 保存结果 ==========
        logger.info("[4/4] 保存数据到: {output_file}")
        save_ic_result(result, output_file)
        
        logger.info("=" * 60)
        logger.info(f"完成！共计算 {result['sample_stats']['valid_days']} 天有效 IC 数据")
        logger.info(f"更新模式: {result['update_mode']}")
        logger.info("=" * 60)
        
        return result
    
    if mode == UpdateMode.SKIP:
        # ========== 跳过更新（缓存已最新） ==========
        # 规范：SKIP 模式不修改缓存对象，直接返回（update_mode 在缓存中已是正确值）
        logger.info("[模式] 缓存已最新，跳过更新")
        try:
            with open(output_file, 'r', encoding='utf-8') as f:
                cached_data = json.load(f)
                # 不修改 cached_data，直接返回（避免内存与文件不一致）
                return cached_data
        except FileNotFoundError:
            logger.warning("[诊断] 缓存文件不存在，执行全量计算")
            return do_full_recalculate()  # 显式调用，逻辑清晰
        except json.JSONDecodeError as e:
            raise RuntimeError(f"缓存文件损坏: {output_file}\n{e}") from e
    
    elif mode == UpdateMode.INCREMENTAL:
        # ========== 增量更新（缓存滞后） ==========
        logger.info("[模式] 增量更新")
        
        # ========== [2/4] 计算换手率突增因子 ==========
        # 注意：换手率突增计算需要完整的历史换手率数据才能正确计算 rolling mean
        logger.info("[2/4] 计算换手率突增因子（需要全量历史数据）...")
        
        factor_df_local = calculate_turnover_surge(factor_df, surge_window=surge_window)
        
        surge_count = factor_df_local['turnover_surge'].notna().sum()
        total_count = len(factor_df_local)
        logger.info("✓ 换手率突增计算完成")
        logger.info(f"满足条件股票数: {surge_count} / {total_count} ({surge_count/total_count:.1%})")
        
        # ========== [3/4] 执行增量 IC 计算 ==========
        logger.info("[3/4] 执行增量 IC 计算...")
        result = incremental_update_ic(
            output_path=output_file,
            factor_df_full=factor_df_local,
            return_df_full=return_df,
            raw_metadata=raw_metadata,
            factor_name='turnover_surge_1d',
            factor_col='turnover_surge',
            return_col='forward_return_1d',
            min_stocks=min_stocks
        )
        
        # 增量结果已在 incremental_update_ic 内部保存（[4/4] 已完成）
        
        # 添加参数信息
        result['params'] = {
            'surge_window': surge_window,
            'factor_col': 'turnover_surge',
            'filter_conditions': [
                'turnover_surge > 1',
                'daily_return > 0'
            ]
        }
        
        # 使用 result['ic_metrics'] 统一取值（遵循 MODULE.md 增量更新返回结构统一规范）
        logger.info(f"IC 均值: {result['ic_metrics']['ic_mean']:.4f}")
        logger.info(f"ICIR: {result['ic_metrics']['icir']:.2f}")
        logger.info(f"更新模式: {result['update_mode']}")
        
        return result
    
    # ========== 全量计算 ==========
    return do_full_recalculate()  # 复用同一函数


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='换手率突增 IC 计算器（重构版）')
    parser.add_argument('--force-full', action='store_true', help='强制全量计算')
    parser.add_argument('--output', type=str, help='输出文件路径')
    parser.add_argument('--surge-window', type=int, default=DEFAULT_SURGE_WINDOW, help='换手率均值计算窗口')
    
    args = parser.parse_args()
    
    try:
        result = generate_turnover_surge_ic_data(
            output_file=args.output,
            force_full=args.force_full,
            surge_window=args.surge_window
        )
        
        # 使用防御性访问（遵循 MODULE.md __main__ 防御性访问规范）
        ic_metrics = result.get('ic_metrics', {})
        logger.info("=" * 60)
        logger.info("结果摘要:")
        logger.info(f"因子名称: {result.get('factor_name', 'unknown')}")
        logger.info(f"IC 均值: {ic_metrics.get('ic_mean', 0):.4f}")
        logger.info(f"ICIR: {ic_metrics.get('icir', 0):.2f}")
        logger.info("=" * 60)
        
    except FileNotFoundError as e:
        # 缓存文件不存在：严重错误，不降级
        logger.error(f"缓存文件不存在，请先运行数据采集: {e}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        # 缓存文件损坏：严重错误，不降级
        logger.error(f"缓存文件损坏，请检查数据源: {e}")
        sys.exit(1)
    except PermissionError as e:
        # 权限错误：严重错误，不降级
        logger.error(f"缓存文件权限错误: {e}")
        sys.exit(1)
    except Exception as e:
        # 其他未预期异常：保留完整堆栈信息
        logger.exception(f"计算失败（未预期错误）: {type(e).__name__}")
        sys.exit(1)