#!/usr/bin/env python3
"""
量比因子 IC 计算器（重构版） - 1日收益周期

使用公共模块实现 IC 计算部分，保留分层回测扩展功能。
代码量从 ~686行降至 ~200行（IC部分）。

功能：
1. 从缓存数据计算量比因子的正向 IC
2. 支持分层回测（LayeredBacktestEngine）
3. 五维度独立判断

作者: 云瑶
重构日期: 2026-05-22
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

# 导入分层回测引擎
from backtest.layered_backtest import LayeredBacktestEngine

# ============================================================================
# 参数统一管理
# ============================================================================
DEFAULT_MIN_STOCKS = 10
DEFAULT_NUM_LAYERS = 10
DEFAULT_TRADE_COST_RATE = 0.001


def run_volume_ratio_analysis(
    num_layers: int = DEFAULT_NUM_LAYERS,
    trade_cost_rate: float = DEFAULT_TRADE_COST_RATE,
    min_stocks_per_layer: int = DEFAULT_MIN_STOCKS
) -> dict:
    """
    执行量比因子完整分析（IC + 分层回测）
    
    参数:
        num_layers: 分层数
        trade_cost_rate: 交易成本率
        min_stocks_per_layer: 每层最小股票数
    
    返回:
        包含 IC 和分层回测结果的字典
    """
    print("=" * 80)
    print("量比因子完整分析（重构版）")
    print("=" * 80)
    
    # ========== Step 1: 加载数据 ==========
    print("\n[1/4] 从缓存加载因子和收益数据...")
    try:
        factor_df, return_df, raw_metadata = load_factor_return_data(
            factor_cols=['volume_ratio_5']
        )
        print(f"✓ 加载成功")
        print(f"  - 原始日期范围: {raw_metadata['period_start']} ~ {raw_metadata['period_end']}")
        print(f"  - 过滤后交易日数: {factor_df['date'].nunique()}")
        
    except FileNotFoundError as e:
        raise RuntimeError(f"缓存文件不存在: {e}") from e
    
    # ========== Step 2: 计算 IC ==========
    print("\n[2/4] 计算 IC...")
    ic_result = calculate_ic_with_direction_verification(
        factor_df=factor_df,
        return_df=return_df,
        factor_col='volume_ratio_5',
        return_col='forward_return',
        min_stocks=DEFAULT_MIN_STOCKS
    )
    
    print(f"  - IC 均值: {ic_result['ic_mean']:.4f}")
    print(f"  - ICIR: {ic_result['icir']:.2f}")
    print(f"  - 正比例: {ic_result['positive_ratio']:.1%}")
    
    # ========== Step 3: 分层回测 ==========
    print("\n[3/4] 执行分层回测...")
    print(f"  - 分层数: {num_layers}")
    print(f"  - 因子方向: positive（正向因子：低量比→Layer1，高量比→Layer10）")
    
    # 创建分层回测引擎（传入 DataFrame）
    layered_engine = LayeredBacktestEngine(
        factor_df=factor_df,
        return_df=return_df,
        factor_col='volume_ratio_5',
        return_col='forward_return',
        date_col='date',
        asset_col='asset'
    )
    
    # 执行回测（参数在 run() 中传入）
    layered_result = layered_engine.run(
        layer_method='percentile',
        n_layers=num_layers,
        factor_direction='positive',  # 量比是正向因子
        min_stocks_per_layer=min_stocks_per_layer,
        trade_cost_rate=trade_cost_rate
    )
    
    print(f"  ✓ 分层回测完成")
    print(f"    - 回测天数: {layered_result['meta']['n_days_total']}")
    ls_annual = layered_result.get('long_short', {}).get('long_short_return_annual', 0)
    print(f"    - 多空年化收益: {ls_annual:.2%}")
    
    # ========== Step 4: 构建输出 ==========
    print("\n[4/4] 构建输出结构...")
    
    # 使用公共模块构建 IC 结果
    ic_output = build_ic_result(
        ic_result=ic_result,
        raw_metadata=raw_metadata,
        factor_name='volume_ratio_1d',
        data_source='cache/factor_data/factor_data.json.gz',
        factor_col='volume_ratio_5'
    )
    
    # 扩展字段：分层回测
    result = ic_output.copy()
    result['layered_result'] = layered_result
    result['params'] = {
        'num_layers': num_layers,
        'factor_col': 'volume_ratio_5',
        'factor_direction': 'positive',
        'trade_cost_rate': trade_cost_rate,
        'min_stocks_per_layer': min_stocks_per_layer
    }
    
    # 转换类型
    result = convert_to_native_types(result)
    
    print(f"  ✓ 输出构建完成")
    
    return result


def main():
    """主函数"""
    output_file = get_ic_output_path('volume_ratio_1d')
    
    result = run_volume_ratio_analysis(num_layers=10)
    
    # 保存结果
    print(f"\n保存数据到: {output_file}")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print("\n" + "=" * 60)
    print(f"完成！共计算 {result['sample_stats']['valid_days']} 天有效 IC 数据")
    print("=" * 60)
    
    # 打印关键指标
    print("\n关键指标摘要:")
    print(f"  IC 均值: {result['ic_metrics']['ic_mean']:.4f}")
    print(f"  ICIR: {result['ic_metrics']['icir']:.2f}")
    if 'layered_result' in result and result['layered_result']:
        ls_annual = result['layered_result'].get('long_short', {}).get('long_short_return_annual', 0)
        print(f"  多空年化收益: {ls_annual:.2%}")


if __name__ == '__main__':
    try:
        main()
    except FileNotFoundError as e:
        print(f"\n[错误] 缓存文件不存在: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[错误] 分析失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)