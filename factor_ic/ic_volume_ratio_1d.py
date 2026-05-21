#!/usr/bin/env python3
"""
量比因子 IC 计算器（重构版） - 1日收益周期

使用公共模块实现 IC 计算，符合职责边界规范（禁止分层回测）。
代码量从 ~686行降至 ~240行。

功能：
1. 从缓存数据计算量比因子的 IC
2. 五维度独立判断
3. 支持 skip/incremental/full 三种更新模式
4. 支持 CLI 参数：--force-full、--output、--min-stocks

实现方式：
- 使用 calculate_ic_with_direction_verification 计算 IC
- 使用 build_ic_result 构建输出结构
- 使用 incremental_update_ic 执行增量更新

作者: 云瑶
重构日期: 2026-05-22
增量模式补充: 2026-05-22
SKIP模式修复: 2026-05-23（不修改缓存对象+内部函数封装）
CLI参数添加: 2026-05-23（与 ic_rsi_1d.py 保持一致）
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
    
    # ========== [1/4] 加载全量数据（前置步骤，所有模式共享） ==========
    logger.info("[1/4] 从缓存加载因子和收益数据...")
    try:
        factor_df, return_df, raw_metadata = load_factor_return_data(
            factor_cols=['volume_ratio_5'],
            logger=logger
        )
        logger.info("✓ 加载成功")
        logger.info(f"原始日期范围: {raw_metadata['period_start']} ~ {raw_metadata['period_end']}")
        logger.info(f"原始交易日数: {raw_metadata['total_days']}")
        logger.info(f"过滤后交易日数: {factor_df['date'].nunique()}")
        
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
    
    # ========== 判断模式 ==========
    mode = should_use_incremental(output_file, factor_df, force_full)
    
    # 定义内部函数：全量计算（用于 FULL 模式和 SKIP fallback）
    def do_full_recalculate() -> dict:
        """执行全量计算（用于正常 FULL 模式和 SKIP fallback）"""
        logger.info("[模式] 全量计算")
        
        # ========== [2/4] 计算因子 ==========
        # 量比因子已在缓存中，无需计算（跳过此步骤）
        logger.info("[2/4] 因子已在缓存中，跳过因子计算")
        
        # ========== [3/4] 计算每日 IC ==========
        logger.info("[3/4] 计算每日 IC...")
        
        ic_result = calculate_ic_with_direction_verification(
            factor_df=factor_df,
            return_df=return_df,
            factor_col='volume_ratio_5',
            return_col='forward_return_1d',
            min_stocks=min_stocks,
            logger=logger
        )
        
        # ========== [4/4] 构建输出并保存 ==========
        logger.info("[4/4] 构建输出结构...")
        
        result = build_ic_result(
            ic_result=ic_result,
            raw_metadata=raw_metadata,
            factor_name='volume_ratio_1d',
            data_source='cache/factor_data/factor_data.json.gz',
            factor_col='volume_ratio_5'
        )
        
        # update_mode 在保存前设置（save_ic_result 内部会调用 convert_to_native_types）
        result['update_mode'] = 'full'
        
        # 使用 result['ic_metrics'] 统一取值（遵循 MODULE.md 增量更新返回结构统一规范）
        logger.info(f"IC 均值: {result['ic_metrics']['ic_mean']:.4f}")
        logger.info(f"ICIR: {result['ic_metrics']['icir']:.2f}")
        logger.info(f"正比例: {result['positive_ratio']:.1%}")
        
        # ========== 保存结果 ==========
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
        
        # ========== [2/4] 因子已在缓存中，跳过因子计算 ==========
        logger.info("[2/4] 因子已在缓存中，跳过因子计算")
        
        # ========== [3/4] 执行增量 IC 计算 ==========
        logger.info("[3/4] 执行增量 IC 计算...")
        
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
        
        # 使用 result['ic_metrics'] 统一取值（遵循 MODULE.md 增量更新返回结构统一规范）
        logger.info(f"IC 均值: {result['ic_metrics']['ic_mean']:.4f}")
        logger.info(f"ICIR: {result['ic_metrics']['icir']:.2f}")
        logger.info(f"更新模式: {result['update_mode']}")
        
        return result
    
    # ========== 全量计算 ==========
    return do_full_recalculate()


def main():
    """主函数（支持 CLI 参数）"""
    import argparse
    
    parser = argparse.ArgumentParser(description='量比因子 IC 计算器（重构版） - 1日收益周期')
    parser.add_argument('--force-full', action='store_true', help='强制全量计算')
    parser.add_argument('--output', type=str, help='输出文件路径')
    parser.add_argument('--min-stocks', type=int, default=DEFAULT_MIN_STOCKS, help='最小股票数阈值')
    
    args = parser.parse_args()
    
    try:
        result = generate_volume_ratio_ic_data(
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


if __name__ == '__main__':
    main()