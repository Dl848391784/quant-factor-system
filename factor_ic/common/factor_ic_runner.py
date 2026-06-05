#!/usr/bin/env python3
"""
因子IC计算主入口模板 - factor_ic 公共模块

功能：
1. 统一主入口逻辑（模式判断 → 分支调用 → 输出）
2. 封装全量/增量/跳过三种模式
3. 简化新增因子脚本的开发成本

模式判断流程（2026-05-23）：
1. 先调用 check_data_completeness 判断模式（不需要加载数据）
2. SKIP 模式：直接返回缓存数据（不加载全量数据，避免浪费）
3. FULL/INCREMENTAL 模式：再加载数据执行计算

增量模式职责划分（2026-05-23）：
- incremental_update_ic 负责保存结果（内部已调用 save_ic_result）
- factor_ic_runner 不再重复保存（避免双重写入）

作者: 云瑶
日期: 2026-05-22
最后修改: 2026-05-31（重构为单文件模式，删除双文件加载逻辑）
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

# 导入日志
from .logger_config import get_logger


logger = get_logger(__name__)

# 导入数据加载（单文件模式）
# 导入类型转换

# 导入数据完整性检查
from .data_completeness import check_data_completeness
from .data_loader import get_data_cache_path, load_factor_return_data

# 导入 IC 计算
from .ic_calculator import calculate_ic_with_direction_verification

# 导入结果构建
from .ic_result_builder import build_error_result, build_ic_result, get_ic_output_path, save_ic_result

# 导入增量引擎
from .incremental_engine import incremental_update_ic


def run_factor_ic_analysis(
    factor_name: str,
    factor_col: str,
    return_period: str = '1d',
    return_col: str = 'forward_return_1d',
    factor_cols: list[str] | None = None,
    min_stocks: int = 10,
    force_full: bool = False,
    output_path: Path | None = None,
    data_cache_path: Path | None = None,
    additional_factor_files: dict[str, Path] | None = None,
    custom_factor_calculation: Callable | None = None,
    custom_factor_calculation_params: dict[str, Any] | None = None,
    _logger=None
) -> dict[str, Any]:
    """
    因子 IC 分析统一主入口
    
    参数:
        factor_name: 因子名称（如 'rsi', 'volume_ratio'）
        factor_col: 主因子列名（如 'rsi_6', 'volume_ratio_5'）
        return_period: 收益周期（如 '1d'）
        return_col: 收益列名（缓存中）
        factor_cols: 需加载的因子列列表（默认 = [factor_col]）
        min_stocks: 最小股票数阈值
        force_full: 是否强制全量计算
        output_path: 输出文件路径（默认自动生成）
        data_cache_path: 数据缓存路径（默认使用 factor_ic_data.json.gz）
        additional_factor_files: 额外因子文件（如换手率数据）
        custom_factor_calculation: 自定义因子计算函数（可选）
            - 用于需要预处理因子值的场景（如 KDJ 计算）
            - 函数签名: (factor_df: pd.DataFrame) -> pd.DataFrame
        custom_factor_calculation_params: 自定义因子计算参数
        _logger: 日志记录器（由调用方传入，默认使用模块 logger）
            - 参数名使用下划线前缀避免遮蔽模块级 logger
    
    返回:
        IC 分析结果字典（符合 MODULE.md 输出结构统一性规范）
    
    流程:
        1. 判断模式（全量/增量/跳过）- 使用 check_data_completeness，不需要加载数据
        2. SKIP 模式：直接返回缓存数据
        3. 加载数据（仅在 FULL/INCREMENTAL 模式）
        4. 执行计算
        5. 构建输出
        6. 保存结果
    
    示例:
        # RSI 因子（直接用缓存列）
        result = run_factor_ic_analysis(
            factor_name='rsi',
            factor_col='rsi_6'
        )
        
        # KDJ 因子（需要自定义计算）
        def calculate_kdj_j(factor_df):
            # ... KDJ 计算逻辑 ...
            return factor_df
        
        result = run_factor_ic_analysis(
            factor_name='kdj_j',
            factor_col='kdj_j',
            factor_cols=['close', 'high', 'low'],
            custom_factor_calculation=calculate_kdj_j
        )
    """
    # _logger fallback 初始化（使用模块级已导入的 get_logger）
    # 参数重命名避免遮蔽模块级 logger
    if _logger is None:
        _logger = get_logger(__name__)

    _logger.info("=" * 60)
    _logger.info(f"因子 IC 分析: {factor_name}_{return_period}")
    _logger.info("=" * 60)

    # ========== 确定路径 ==========
    if output_path is None:
        output_path = get_ic_output_path(factor_name, return_period)

    if data_cache_path is None:
        data_cache_path = get_data_cache_path()

    if factor_cols is None:
        factor_cols = [factor_col]
    else:
        # 参数校验：factor_col 必须在 factor_cols 中
        # **重要修正**：复杂因子（有 custom_factor_calculation）跳过此校验
        # 原因：factor_col 是计算后的因子列名，不存在于原始缓存数据中
        # 只有简单因子才需要校验（直接从缓存读取 factor_col）
        if custom_factor_calculation is None and factor_col not in factor_cols:
            _logger.warning(
                f"factor_col '{factor_col}' 不在 factor_cols {factor_cols} 中，"
                f"自动添加以防止列缺失错误"
            )
            # 追加到末尾，保持原有顺序
            factor_cols = factor_cols + [factor_col]

    data_source = str(data_cache_path)

    # ========== 判断模式（不需要加载数据）==========
    # 使用 check_data_completeness 判断模式，避免 SKIP 模式也加载全量数据
    _logger.info("[模式判断] 判断更新模式...")

    # force_full 强制全量模式
    if force_full:
        mode = 'full'
        missing_dates = []
        info = {'cache_exists': False}
        _logger.info("模式判断: 强制全量计算")
    else:
        mode, missing_dates, info = check_data_completeness(factor_name, logger=_logger)
        _logger.info(f"模式判断: {mode}")

    # ========== SKIP 模式：直接返回缓存数据 ==========
    if mode == 'skip':
        _logger.info("[执行模式] 数据已最新，跳过计算")

        # 直接读取缓存数据返回
        if output_path.exists():
            with open(output_path, encoding='utf-8') as f:
                cached_result = json.load(f)
            cached_result['update_mode'] = 'skip'
            _logger.info(f"✓ 返回缓存数据: {len(cached_result.get('dates', []))} 天")
            return cached_result
        else:
            # 缓存文件不存在（理论上不应该发生，因为 mode='skip' 需要缓存存在）
            _logger.warning("缓存文件不存在，返回错误结构")
            return build_error_result(
                factor_name=f'{factor_name}_{return_period}',
                error_msg='缓存文件不存在（mode=skip 状态异常）',
                return_period=return_period,
                data_source=data_source
            )

    # ========== 加载数据（仅在 FULL/INCREMENTAL 模式）==========
    _logger.info("[数据加载] 加载因子和收益数据...")

    try:
        factor_df, return_df, raw_metadata = load_factor_return_data(
            factor_cols=factor_cols,
            return_col=return_col,
            data_cache_path=data_cache_path,
            additional_factor_files=additional_factor_files,
            logger=_logger
        )
    except FileNotFoundError as e:
        # 缓存不存在：返回错误结构
        _logger.error(f"数据加载失败: {e}")
        return build_error_result(
            factor_name=f'{factor_name}_{return_period}',
            error_msg=str(e),
            return_period=return_period,
            data_source=data_source
        )
    except Exception as e:
        # 其他异常：返回错误结构
        _logger.error(f"数据加载异常: {e}")
        return build_error_result(
            factor_name=f'{factor_name}_{return_period}',
            error_msg=str(e),
            return_period=return_period,
            data_source=data_source
        )

    # ========== 增量模式处理 ==========
    if mode == 'incremental':
        _logger.info("[执行模式] 增量更新...")

        # **重要修正**：复杂因子在增量模式也需要先执行自定义计算
        # 原因：factor_col 是计算后的因子列名，不存在于原始缓存数据中
        if custom_factor_calculation is not None:
            _logger.info("[因子预处理] 执行自定义因子计算...")
            params = custom_factor_calculation_params or {}
            factor_df = custom_factor_calculation(factor_df, **params)
            _logger.info(f"处理后数据: {len(factor_df)} 行")

        # 调用增量引擎（内部已保存结果）
        result = incremental_update_ic(
            output_path=output_path,
            factor_df_full=factor_df,
            return_df_full=return_df,
            raw_metadata=raw_metadata,
            factor_name=f'{factor_name}_{return_period}',
            factor_col=factor_col,
            return_col=return_col,
            min_stocks=min_stocks
        )

        # **注意**：incremental_update_ic 内部已保存结果
        # 职责划分：增量引擎负责保存，factor_ic_runner 不再重复保存
        # 避免双重写入问题

        # 检查增量引擎是否需要全量计算（缓存不存在或损坏）
        if result.get('update_mode') == 'need_full':
            _logger.warning("缓存不存在或损坏，转为全量计算")
            mode = 'full'
            # 继续执行下方的全量模式代码
        else:
            # 增量引擎已返回完整结果（包含五维度判断）
            # incremental_update_ic 内部已调用 calculate_ic_statistics 计算五维度
            # 数据来源一致性：ic_values 和 dates 来自增量引擎合并后的全量数据
            return result

    # ========== 全量模式 ==========
    # 注意：此分支也处理增量模式转全量模式的情况
    _logger.info("[执行模式] 全量计算...")

    # 自定义因子计算（如有）
    if custom_factor_calculation is not None:
        _logger.info("[因子预处理] 执行自定义因子计算...")
        params = custom_factor_calculation_params or {}
        factor_df = custom_factor_calculation(factor_df, **params)
        _logger.info(f"处理后数据: {len(factor_df)} 行")

    # 计算 IC（五维度判断）
    _logger.info("[IC 计算] 计算 IC（含五维度判断）...")

    try:
        ic_result = calculate_ic_with_direction_verification(
            factor_df=factor_df,
            return_df=return_df,
            factor_col=factor_col,
            return_col=return_col,
            date_col='date',
            asset_col='asset',
            min_stocks=min_stocks,
            logger=_logger
        )

        # 使用 .get() 防止 KeyError，保持与增量模式一致
        _logger.info(f"IC 均值: {ic_result.get('ic_mean', 0.0):.4f}")
        _logger.info(f"ICIR: {ic_result.get('icir', 0.0):.2f}")
        # 五维度字段嵌套访问需双重保护（get 默认 {}，或 None 时 fallback {}）
        stats_sig = ic_result.get('statistical_significance') or {}
        t_stat = stats_sig.get('t_stat', 0.0)
        _logger.info(f"t 统计量: {t_stat:.2f}")

    except Exception as e:
        _logger.error(f"IC 计算失败: {e}")
        return build_error_result(
            factor_name=f'{factor_name}_{return_period}',
            error_msg=f'IC 计算失败: {e}',
            return_period=return_period,
            data_source=data_source
        )

    # 构建完整结果
    _logger.info("[结果构建] 构建完整输出结构...")

    result = build_ic_result(
        ic_result=ic_result,
        raw_metadata=raw_metadata,
        factor_name=f'{factor_name}_{return_period}',
        return_period=return_period,
        data_source=data_source,
        factor_col=factor_col,
        update_mode='full'
    )

    # 保存
    save_ic_result(result, output_path)

    _logger.info("=" * 60)
    # 使用 .get() 双重保护防止 KeyError（与日志访问规范一致）
    valid_days = result.get('sample_stats', {}).get('valid_days', 0)
    _logger.info(f"完成！共计算 {valid_days} 天有效 IC")
    _logger.info("=" * 60)

    return result


# ========== 快捷函数 ==========

def run_simple_factor_ic(
    factor_name: str,
    factor_col: str,
    _logger=None,
    **kwargs
) -> dict[str, Any]:
    """
    快捷函数：简单因子 IC 分析
    
    适用于直接使用缓存列的因子（如 RSI、量比）
    
    参数:
        factor_name: 因子名称
        factor_col: 因子列名
        _logger: 日志记录器（由调用方传入，默认使用模块 logger）
            - 参数名使用下划线前缀避免遮蔽模块级 logger
        **kwargs: 其他参数（传递给 run_factor_ic_analysis）
    
    示例:
        result = run_simple_factor_ic('rsi', 'rsi_6')
        result = run_simple_factor_ic('volume_ratio', 'volume_ratio_5')
    """
    return run_factor_ic_analysis(
        factor_name=factor_name,
        factor_col=factor_col,
        factor_cols=[factor_col],
        _logger=_logger,
        **kwargs
    )


def run_complex_factor_ic(
    factor_name: str,
    factor_col: str,
    factor_cols: list[str],
    custom_factor_calculation: Callable,
    _logger=None,
    **kwargs
) -> dict[str, Any]:
    """
    快捷函数：复杂因子 IC 分析
    
    适用于需要预处理因子值的场景（如 KDJ、布林带）
    
    参数:
        factor_name: 因子名称
        factor_col: 最终因子列名
        factor_cols: 需加载的原始因子列
        custom_factor_calculation: 自定义因子计算函数（必须提供）
        _logger: 日志记录器（由调用方传入，默认使用模块 logger）
            - 参数名使用下划线前缀避免遮蔽模块级 logger
        **kwargs: 其他参数
    
    示例:
        def calculate_kdj_j(factor_df):
            # KDJ 计算逻辑
            ...
            return factor_df
        
        result = run_complex_factor_ic(
            factor_name='kdj_j',
            factor_col='kdj_j',
            factor_cols=['close', 'high', 'low'],
            custom_factor_calculation=calculate_kdj_j
        )
    """
    return run_factor_ic_analysis(
        factor_name=factor_name,
        factor_col=factor_col,
        factor_cols=factor_cols,
        custom_factor_calculation=custom_factor_calculation,
        _logger=_logger,
        **kwargs
    )


# ========== CLI 支持 ==========

def main():
    """
    CLI 主入口
    
    用法:
        python -m factor_ic.common.factor_ic_runner --factor rsi --col rsi_6
    """
    import argparse

    parser = argparse.ArgumentParser(description='因子 IC 分析')
    parser.add_argument('--factor', required=True, help='因子名称')
    parser.add_argument('--col', required=True, help='因子列名')
    parser.add_argument('--period', default='1d', help='收益周期')
    parser.add_argument('--min-stocks', type=int, default=10, help='最小股票数')
    parser.add_argument('--force-full', action='store_true', help='强制全量计算')

    args = parser.parse_args()

    # CLI 使用模块级 logger
    result = run_simple_factor_ic(
        factor_name=args.factor,
        factor_col=args.col,
        return_period=args.period,
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        _logger=logger  # 传入模块级 logger（参数名 _logger，值是模块级 logger）
    )

    # 使用模块级 logger（明确标识）
    logger.info(f"[CLI] 结果: {result.get('update_mode', 'unknown')}")


if __name__ == '__main__':
    main()
