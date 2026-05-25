"""
综合因子公共入口模块

功能:
1. 加载因子数据和IC结果
2. 标准化因子值
3. 计算综合因子（调用 weight_engine）
4. 调用 backtest 分层回测（复用 run_layered_backtest）
5. 保存结果

设计参考:
- factor_ic/common/factor_ic_runner.py
- backtest/common/layered_backtest_runner.py

作者: 云瑶
创建日期: 2026-05-24
"""

import os
import sys
import json
import gzip
import logging
import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, List, Callable, Union
from dataclasses import dataclass, field

# 导入公共模块
from comprehensive_factor.common.logger_config import get_logger
from comprehensive_factor.common.convert_types import convert_to_native_types
from comprehensive_factor.common.factor_loader import (
    load_factor_values,
    load_ic_results,
    load_ic_daily,
    standardize_factors,
    calc_factor_correlation
)
from comprehensive_factor.common.weight_engine import WeightEngine

# 导入 backtest 公共模块（跨模块调用，但通过函数接口）
# 修复：添加重复插入检查，避免多次 import 时路径重复污染
_project_root = str(Path(__file__).parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from backtest.common.layered_backtest import LayeredBacktestEngine
from backtest.common.layered_backtest_runner import LayerConfigBase, load_factor_return_data
from backtest.common.convert_types import convert_to_native_types as backtest_convert


# ============================================================================
# Config 基类
# ============================================================================

@dataclass
class CompositeLayerConfig(LayerConfigBase):
    """综合因子分层配置
    
    综合因子默认为反向因子（低值预期高收益），
    因为低相关性组合中流动性因子（缩量）+ 技术指标（超卖）都指向反向逻辑。
    
    扩展参数：
    - factor_list: 因子名称列表
    - factor_cols: 因子列名列表
    - rolling_window: 滚动ICIR窗口
    """
    
    # 因子组合参数
    factor_list: List[str] = field(default_factory=lambda: ['rsi', 'volume_ratio'])
    factor_cols: List[str] = field(default_factory=lambda: ['rsi_6', 'volume_ratio_5'])
    rolling_window: int = 60
    
    def validate(self) -> None:
        """校验配置完整性"""
        super().validate()  # 调用父类校验
        
        if not self.factor_list:
            raise ValueError("factor_list 不能为空")
        
        if not self.factor_cols:
            raise ValueError("factor_cols 不能为空")
        
        if len(self.factor_list) != len(self.factor_cols):
            raise ValueError(
                f"factor_list ({len(self.factor_list)}) 与 factor_cols ({len(self.factor_cols)}) 数量不一致"
            )


# ============================================================================
# 公共入口函数
# ============================================================================

def run_composite_backtest(
    weight_method: str = 'equal_weight',
    factor_list: Optional[List[str]] = None,      # 可选，如为None则自动筛选
    factor_cols: Optional[List[str]] = None,      # 可选，如为None则自动筛选
    config: Optional['CompositeLayerConfig'] = None,
    return_period: str = '1d',
    data_source: Optional[Union[str, Path]] = None,
    ic_result_dir: Optional[str] = None,
    backtest_result_dir: Optional[str] = None,
    output_dir: Union[str, Path, None] = None,    # 修复：支持 str 或 Path，入口统一转换
    auto_select: bool = False,                    # 是否自动筛选因子
    thresholds: Optional[Dict] = None,            # 筛选阈值配置
    verbose: bool = True,
    logger: Optional[logging.Logger] = None
) -> Dict:
    """综合因子分层回测公共入口
    
    Args:
        weight_method: 加权方式（equal_weight/icir_weight/ic_weight/rolling_icir_weight）
        factor_list: 因子名称列表（用于加载IC结果），如为None且auto_select=True则自动筛选
        factor_cols: 因子列名列表（用于加载因子值），如为None且auto_select=True则自动筛选
        config: 分层配置对象
        return_period: 收益周期
        data_source: 数据源文件路径（可选，默认使用 DEFAULT_DATA_SOURCE）
        ic_result_dir: IC结果目录
        backtest_result_dir: 回测结果目录
        output_dir: 输出目录（支持 str 或 Path，入口统一转换为 Path）
        auto_select: 是否自动筛选因子（Step 2自动化）
        thresholds: 筛选阈值配置（如未提供则使用默认值）
        verbose: 是否打印详细信息
        logger: 日志对象
    
    Returns:
        回测结果字典
    
    更新历史（2026-05-27）：
        - v2.7: 移除 cache_dir 参数，改为统一数据源 data_source
    """
    if logger is None:
        logger = get_logger(__name__)
    
    # 修复：入口统一转换类型，处理所有情况（包括 None）
    if output_dir is None:
        # 默认输出目录
        project_root = Path(__file__).parent.parent.parent
        output_dir = project_root / 'comprehensive_factor' / 'result'
    else:
        output_dir = Path(output_dir)
    
    # 创建默认配置（如果未传入）
    if config is None:
        config = CompositeLayerConfig()
    
    # 校验配置
    config.validate()
    
    logger.info("=" * 40)
    logger.info("综合因子分层回测 [%s]", weight_method)
    logger.info("=" * 40)
    
    # ====================================================================
    # Step 2: 自动筛选因子（如果启用）
    # ====================================================================
    selection_result = None
    if auto_select and factor_list is None:
        from comprehensive_factor.common.factor_selector import select_factors
        
        logger.info("启用自动因子筛选...")
        
        # 加载所有因子数据用于计算相关性
        # 注意：这需要 factor_data.json.gz 包含所有因子列
        # 如果缓存数据不完整，只能使用手动配置
        
        selection_result = select_factors(
            ic_result_dir=Path(ic_result_dir) if ic_result_dir else None,
            backtest_result_dir=Path(backtest_result_dir) if backtest_result_dir else None,
            thresholds=thresholds,
            logger=logger
        )
        
        # 根据筛选结果设置 factor_list
        factor_list = selection_result['selected']
        
        # 使用 select_factors 返回的 factor_cols 映射（已从 FACTOR_NAME_TO_COL_MAP 获取）
        # 修复：不再直接赋值 factor_cols = factor_list，避免列名不匹配
        factor_cols = selection_result.get('factor_cols', factor_list)
        
        # 检查未映射因子警告
        unmapped = selection_result.get('unmapped_factors', [])
        if unmapped:
            logger.warning(
                "以下因子未找到列名映射，可能导致数据加载失败: %s",
                unmapped
            )
        
        logger.info("自动筛选完成: %s → %s", factor_list, factor_cols)
    
    # 如果仍未指定，使用默认配置
    if factor_list is None:
        raise ValueError(
            "factor_list 未指定\n"
            "请设置 auto_select=True 启用自动筛选，或手动传入 factor_list"
        )
    
    if factor_cols is None:
        factor_cols = factor_list
    
    if verbose:
        logger.info("配置信息:")
        logger.info("  加权方式: %s", weight_method)
        logger.info("  因子列表: %s", factor_list)
        logger.info("  因子方向: %s", config.factor_direction)
        logger.info("  分层数量: %d (percentile)", config.n_layers)
        logger.info("  多头组合: Layer %s", config.long_layers)
        logger.info("  空头组合: Layer %s", config.short_layers)
        if auto_select:
            logger.info("  自动筛选: 启用")
    
    # 1. 加载因子数据
    logger.info("加载因子数据...")
    factor_df = load_factor_values(
        factor_cols=factor_cols,
        data_source=data_source,
        logger=logger
    )
    
    # 2. 加载 IC 结果
    logger.info("加载 IC 结果...")
    ic_results, missing_ic_factors = load_ic_results(
        factor_names=factor_list,
        ic_result_dir=ic_result_dir,
        return_period=return_period,
        logger=logger
    )
    
    # 修复：检查缺失因子，避免后续计算 KeyError
    if missing_ic_factors:
        logger.warning(
            "部分因子 IC 结果缺失，权重计算将回退等权: %s",
            missing_ic_factors
        )
    
    # 3. 加载 IC 每日数据（滚动ICIR需要）
    ic_daily_data = None
    if weight_method == 'rolling_icir_weight':
        logger.info("加载 IC 每日数据...")
        ic_daily_data = load_ic_daily(
            factor_names=factor_list,
            ic_result_dir=ic_result_dir,
            return_period=return_period,
            logger=logger
        )
    
    # 4. 标准化因子
    logger.info("标准化因子值...")
    factor_df = standardize_factors(factor_df, factor_cols, logger)
    
    # 修复：列校验前置，放在 standardize 之后、calculate 之前
    # 校验必需列存在性（防御性编程）
    required_cols = ['date', 'asset']
    for col in required_cols:
        if col not in factor_df.columns:
            raise ValueError(
                f"factor_df 缺少必需列 '{col}'，当前列: {list(factor_df.columns)}"
            )
    
    # 校验因子列存在性
    for col in factor_cols:
        if col not in factor_df.columns:
            raise ValueError(
                f"factor_df 缺少因子列 '{col}'，当前列: {list(factor_df.columns)}"
            )
    
    # 校验标准化因子列存在性（standardize_factors 生成 *_std 列）
    std_cols = [f'{col}_std' for col in factor_cols]
    for col in std_cols:
        if col not in factor_df.columns:
            raise ValueError(
                f"factor_df 缺少标准化因子列 '{col}'，当前列: {list(factor_df.columns)}\n"
                "可能原因：standardize_factors 未正确生成标准化列"
            )
    
    # 5. 计算因子相关性
    logger.info("计算因子相关性...")
    corr_matrix = calc_factor_correlation(factor_df, factor_cols, logger)
    
    # 检查高相关性因子
    high_corr_pairs = []
    nan_corr_pairs = []  # 新增：NaN相关性记录（缺失值过多导致的异常）
    
    for i in range(len(factor_cols)):
        for j in range(i + 1, len(factor_cols)):
            corr_val = corr_matrix.loc[factor_cols[i], factor_cols[j]]
            
            # 修复：显式处理 NaN（缺失值过多导致的异常相关性）
            if pd.isna(corr_val):
                nan_corr_pairs.append({
                    'factor_a': factor_cols[i],
                    'factor_b': factor_cols[j],
                    'reason': 'NaN（缺失值过多导致相关性无法计算）'
                })
                logger.warning(
                    "相关性 NaN 警告: %s vs %s，缺失值过多导致相关性无法计算",
                    factor_cols[i], factor_cols[j]
                )
                continue  # 跳过 NaN，不判断高相关性
            
            # 正常相关性判断
            if abs(corr_val) > 0.7:
                high_corr_pairs.append({
                    'factor_a': factor_cols[i],
                    'factor_b': factor_cols[j],
                    'corr': float(corr_val)  # 显式转为 float，避免 numpy 类型
                })
                logger.warning(
                    "高相关因子警告: %s vs %s, corr=%.2f，建议只选其一",
                    factor_cols[i], factor_cols[j], corr_val
                )
    
    # 6. 计算综合因子
    logger.info("计算综合因子 [%s]...", weight_method)
    weight_engine = WeightEngine(
        weight_method=weight_method,
        window=config.rolling_window,
        logger=logger
    )
    
    composite_factor = weight_engine.calculate(
        factor_df=factor_df,
        factor_cols=factor_cols,
        ic_results=ic_results,
        ic_daily_data=ic_daily_data
    )
    
    # 添加综合因子到 factor_df
    factor_df['composite_factor'] = composite_factor
    
    # 修复：检查 composite_factor 全为 NaN 的情况
    valid_composite_count = factor_df['composite_factor'].notna().sum()
    if valid_composite_count == 0:
        raise ValueError(
            "composite_factor 全为 NaN，无法进行分层回测\n"
            "可能原因：\n"
            "  1. 所有因子值缺失（检查 factor_cols 是否正确）\n"
            "  2. 标准化后全为 NaN（检查原始数据覆盖率）\n"
            "  3. 加权计算异常（检查 weight_engine.calculate()）"
        )
    
    # 7. 获取权重（修复：元信息与权重数据分离）
    # 区分静态权重和动态权重
    if weight_method == 'rolling_icir_weight':
        # 滚动ICIR权重是每日动态计算的，无法用固定字典表达
        # 修复：将元信息与权重数据分离，避免序列化风险
        weights = {}  # 权重字典为空（动态权重不保存静态值）
        weight_meta = {
            'is_dynamic': True,
            'method': 'rolling_icir_weight',
            'window': config.rolling_window,
            'note': '权重每日动态计算，不保存静态值'
        }
        logger.info("滚动ICIR加权: 权重每日动态计算（窗口 %d 日），不保存静态权重", config.rolling_window)
    else:
        # 静态权重方法（equal_weight、icir_weight、ic_weight）
        weights = weight_engine.get_weights(factor_cols, ic_results)
        weight_meta = {
            'is_dynamic': False,
            'method': weight_method
        }
        logger.info("静态权重获取完成: %s", weights)
    
    if verbose:
        logger.info("因子权重:")
        if weight_meta['is_dynamic']:
            logger.info("  %s（每日动态计算，窗口 %d 日）", weight_meta['method'], weight_meta['window'])
        else:
            for col, w in weights.items():
                logger.info("  %s: %.4f", col, w)
        
        logger.info("数据统计:")
        logger.info("  日期范围: %s ~ %s", factor_df['date'].min(), factor_df['date'].max())
        logger.info("  股票数量: %d", factor_df['asset'].nunique())
        valid_composite = factor_df['composite_factor'].dropna()
        if len(valid_composite) > 0:
            logger.info("  综合因子范围: %.2f ~ %.2f", valid_composite.min(), valid_composite.max())
    
    # 8. 调用 backtest 分层回测
    logger.info("调用 backtest 分层回测...")
    
    # 加载收益数据（防御性校验返回值）
    factor_return_result = load_factor_return_data(
        data_source=data_source,
        logger=logger
    )
    
    # 校验返回值数量和类型
    if factor_return_result is None:
        raise ValueError("load_factor_return_data 返回 None，期望 (factor_df, return_df)")
    
    if not isinstance(factor_return_result, tuple) or len(factor_return_result) != 2:
        raise ValueError(
            f"load_factor_return_data 返回值数量错误，期望 2 个，实际: "
            f"{len(factor_return_result) if isinstance(factor_return_result, tuple) else '非tuple'}"
        )
    
    _, return_df = factor_return_result
    
    if return_df is None:
        raise ValueError("return_df 为 None，收益数据加载失败")
    
    # 修复：检查空 DataFrame（有列名但无数据）
    if len(return_df) == 0:
        raise ValueError(
            "return_df 为空 DataFrame（有列名但无数据），无法进行分层回测\n"
            "可能原因：\n"
            "  1. 缓存数据文件为空（检查 return_data.json.gz）\n"
            "  2. 数据加载异常（检查 load_factor_return_data()）\n"
            f"  当前列: {list(return_df.columns)}"
        )
    
    if 'forward_return_1d' not in return_df.columns:
        raise ValueError(
            f"return_df 缺少 'forward_return_1d' 列，当前列: {list(return_df.columns)}"
        )
    
    # 创建回测引擎（直接传入已计算的综合因子）
    logger.info("创建回测引擎...")
    engine = LayeredBacktestEngine(
        factor_df=factor_df,
        return_df=return_df,
        factor_col='composite_factor',
        return_col='forward_return_1d',
        date_col='date',
        asset_col='asset'
    )
    
    # 执行分层回测
    logger.info("执行分层回测...")
    result = engine.run(
        layer_method='percentile',
        n_layers=config.n_layers,
        factor_direction=config.factor_direction,
        long_layers=config.long_layers,
        short_layers=config.short_layers,
        min_stocks_per_layer=config.min_stocks_per_layer,
        trade_cost_rate=config.trade_cost_rate
    )
    
    # 添加元信息
    result['meta']['factor_name'] = f'{weight_method}_composite'
    
    # 生成报告
    report = engine.generate_report(result)
    logger.info(report)
    
    # 9. 保存综合因子结果
    # output_dir 已在入口统一转换（包括 None 默认值），无需再次处理
    output_dir.mkdir(parents=True, exist_ok=True)
    
    output_file = output_dir / f'composite_{weight_method}_{return_period}.json'
    
    # 构建输出数据
    output_data = {
        'meta': {
            'weight_method': weight_method,
            'return_period': return_period,
            'factor_list': factor_list,
            'factor_cols': factor_cols,
            'weights': weights,           # 权重数据（动态权重时为空字典）
            'weight_meta': weight_meta,   # 新增：权重元信息（与权重数据分离）
            'ic_results': {
                name: {
                    'ic_mean': ic_results.get(name, {}).get('ic_mean'),
                    'icir': ic_results.get(name, {}).get('icir'),
                    'ic_std': ic_results.get(name, {}).get('ic_std')
                }
                for name in factor_list
            },
            'correlation_matrix': backtest_convert(corr_matrix.to_dict()),
            'high_corr_pairs': high_corr_pairs,  # 已改为字典列表格式
            'nan_corr_pairs': nan_corr_pairs,  # 新增：NaN相关性记录
            'n_factors': len(factor_cols),
            'n_days': result.get('meta', {}).get('n_days_total', 0)
        },
        'backtest_result': {
            'meta': result.get('meta', {}),
            'layer_stats': result.get('layer_stats', []),
            'long_short': result.get('long_short', {}),
            'monotonicity': result.get('monotonicity', {}),
            'trading_cost_analysis': result.get('trading_cost_analysis', {})
        },
        'config': {
            'n_layers': config.n_layers,
            'factor_direction': config.factor_direction,
            'long_layers': config.long_layers,
            'short_layers': config.short_layers,
            'trade_cost_rate': config.trade_cost_rate,
            'min_stocks_per_layer': config.min_stocks_per_layer,
            'rolling_window': config.rolling_window
        },
        'created_at': datetime.now().isoformat()
    }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(backtest_convert(output_data), f, indent=2, ensure_ascii=False)
    
    logger.info("综合因子结果已保存: %s", output_file)
    
    # 10. 保存综合因子每日明细
    # 校验输出必需列（防御性编程）
    output_cols = ['date', 'asset', 'composite_factor'] + factor_cols
    missing_cols = [col for col in output_cols if col not in factor_df.columns]
    if missing_cols:
        raise ValueError(
            f"factor_df 缺少输出必需列: {missing_cols}, 当前列: {list(factor_df.columns)}"
        )
    
    daily_output = {
        'meta': {
            'weight_method': weight_method,
            'columns': output_cols
        },
        'data': backtest_convert(
            factor_df[output_cols].to_dict('records')
        )
    }
    
    daily_file = output_dir / f'composite_{weight_method}_{return_period}_daily.json.gz'
    
    with gzip.open(daily_file, 'wt', encoding='utf-8') as f:
        json.dump(daily_output, f, indent=2, ensure_ascii=False)
    
    logger.info("综合因子每日明细已保存: %s", daily_file)
    
    return output_data


# ============================================================================
# CLI 入口工厂函数
# ============================================================================

def create_cli_entrypoint(
    weight_method: str,
    factor_list: List[str],
    factor_cols: List[str],
    config_class: type,
    return_period: str = '1d',
    data_source: Optional[Union[str, Path]] = None,
    ic_result_dir: Optional[str] = None
) -> Callable[[], None]:
    """创建 CLI 入口函数
    
    Args:
        weight_method: 加权方式
        factor_list: 因子名称列表
        factor_cols: 因子列名列表
        config_class: Config 类
        return_period: 收益周期
        data_source: 数据源文件路径
        ic_result_dir: IC结果目录
    
    Returns:
        CLI 入口函数
    
    更新历史（2026-05-27）：
        - v2.7: 移除 cache_dir 参数，改为统一数据源 data_source
    """
    def main():
        import argparse
        
        parser = argparse.ArgumentParser(description=f'综合因子分层回测 [{weight_method}]')
        parser.add_argument('--data_source', type=str, default=data_source,
                            help='数据源文件路径')
        parser.add_argument('--ic_result_dir', type=str, default=ic_result_dir,
                            help='IC结果目录路径')
        parser.add_argument('--output_dir', type=str, default=None)
        parser.add_argument('--quiet', action='store_true')
        
        args = parser.parse_args()
        
        logger = get_logger(__name__)
        
        try:
            result = run_composite_backtest(
                weight_method=weight_method,
                factor_list=factor_list,
                factor_cols=factor_cols,
                config=config_class(),
                return_period=return_period,
                data_source=args.data_source,
                ic_result_dir=args.ic_result_dir,
                output_dir=args.output_dir,
                verbose=not args.quiet,
                logger=logger
            )
            
            # 打印关键结果
            ls_stats = result.get('backtest_result', {}).get('long_short', {})
            logger.info("=" * 40)
            logger.info("综合因子回测结果")
            logger.info("=" * 40)
            logger.info("多空年化收益: %.2f%%", ls_stats.get('long_short_return_annual', 0) * 100)
            logger.info("多空夏普比率: %.2f", ls_stats.get('long_short_sharpe', 0))
            logger.info("回测完成，退出码 0")
            sys.exit(0)  # 显式设置成功退出码
            
        except Exception as e:
            # 修复：保留异常堆栈信息，便于排查
            import traceback
            logger.error("回测执行异常: %s", e)
            logger.error("异常堆栈:\n%s", traceback.format_exc())
            logger.error("退出码 1（异常终止）")
            sys.exit(1)  # 显式设置失败退出码
    
    return main