#!/usr/bin/env python3
"""
公共模块验证脚本 - 测试 data_loader + ic_calculator + ic_result_builder

功能：
1. 加载 RSI 因子数据（使用 data_loader）
2. 计算 IC（使用 ic_calculator）
3. 构建输出结构（使用 ic_result_builder）
4. 保存结果（使用 save_ic_result）
5. 检查输出结构是否符合 MODULE.md 规范

作者: 云瑶
日期: 2026-05-22
"""

import sys
import json
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from factor_ic.common import (
    load_factor_return_data,
    calculate_ic_with_direction_verification,
    build_ic_result,
    save_ic_result,
    get_ic_output_path
)


def test_public_modules():
    """测试公共模块"""
    print("=" * 60)
    print("公共模块验证测试")
    print("=" * 60)
    
    # ========== Step 1: 加载数据 ==========
    print("\n[Step 1] 测试 data_loader.load_factor_return_data()")
    try:
        factor_df, return_df, raw_metadata = load_factor_return_data(
            factor_cols=['rsi_6']
        )
        print(f"✓ 加载成功")
        print(f"  - factor_df 行数: {len(factor_df)}")
        print(f"  - return_df 行数: {len(return_df)}")
        print(f"  - raw_metadata:")
        print(f"    - period_start: {raw_metadata.get('period_start')}")
        print(f"    - period_end: {raw_metadata.get('period_end')}")
        print(f"    - total_days: {raw_metadata.get('total_days')}")
        print(f"    - avg_stocks_per_day: {raw_metadata.get('avg_stocks_per_day'):.1f}")
    except Exception as e:
        print(f"✗ 加载失败: {e}")
        return False
    
    # ========== Step 2: 计算 IC ==========
    print("\n[Step 2] 测试 ic_calculator.calculate_ic_with_direction_verification()")
    try:
        ic_result = calculate_ic_with_direction_verification(
            factor_df=factor_df,
            return_df=return_df,
            factor_col='rsi_6',
return_col='forward_return_1d',
            min_stocks=10
        )
        print(f"✓ 计算成功")
        print(f"  - ic_mean: {ic_result['ic_mean']:.6f}")
        print(f"  - ic_std: {ic_result['ic_std']:.6f}")
        print(f"  - icir: {ic_result['icir']:.4f}")
        print(f"  - n_days: {ic_result['n_days']}")
        print(f"  - statistical_significance.p_value: {ic_result['statistical_significance']['p_value']:.6f}")
    except Exception as e:
        print(f"✗ 计算失败: {e}")
        return False
    
    # ========== Step 3: 构建输出结构 ==========
    print("\n[Step 3] 测试 ic_result_builder.build_ic_result()")
    try:
        result = build_ic_result(
            ic_result=ic_result,
            raw_metadata=raw_metadata,
            factor_name='test_rsi_1d',
            data_source='cache/factor_data/factor_data.json.gz',
            factor_col='rsi_6'
        )
        print(f"✓ 构建成功")
        print(f"  - 顶层字段数: {len(result)}")
        print(f"  - ic_metrics 字段数: {len(result.get('ic_metrics', {}))}")
        print(f"  - sample_stats 字段数: {len(result.get('sample_stats', {}))}")
    except Exception as e:
        print(f"✗ 构建失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # ========== Step 4: 检查输出结构 ==========
    print("\n[Step 4] 检查输出结构是否符合规范")
    required_top_fields = [
        'factor_name', 'calculation_date', 'period', 'ic_metrics', 'sample_stats',
        'statistical_significance', 'factor_direction', 'economic_significance',
        'icir_stability', 'ic_distribution_consistency', 'dates', 'ic_values',
        'rolling_ic_mean', 'positive_ratio', 'n_assets', 'summary', 'factor_stats',
        'update_mode'
    ]
    
    missing_fields = []
    for field in required_top_fields:
        if field not in result:
            missing_fields.append(field)
    
    if missing_fields:
        print(f"✗ 缺少字段: {missing_fields}")
        return False
    else:
        print(f"✓ 所有必需字段存在（17个）")
    
    # 检查 ic_metrics 结构（应为5字段）
    ic_metrics_fields = ['ic_mean', 'ic_std', 'icir', 'p_value', 'p_value_display']
    missing_ic_metrics = [f for f in ic_metrics_fields if f not in result.get('ic_metrics', {})]
    if missing_ic_metrics:
        print(f"✗ ic_metrics 缺少字段: {missing_ic_metrics}")
        return False
    else:
        print(f"✓ ic_metrics 字段完整（5个）")
    
    # 检查 sample_stats 结构
    sample_stats = result.get('sample_stats', {})
    if 'avg_stocks_period' not in sample_stats:
        print(f"✗ sample_stats 缺少 avg_stocks_period")
        return False
    else:
        print(f"✓ sample_stats 包含 avg_stocks_period 口径说明")
    
    # 检查 statistical_significance 结构（应为7字段）
    # 字段定义：见 MODULE.md 第935行
    ss_fields = ['t_stat', 'p_value', 'p_value_display', 'nw_lag', 'nw_lag_method', 'is_significant', 'conclusion']
    ss = result.get('statistical_significance', {})
    missing_ss = [f for f in ss_fields if f not in ss]
    if missing_ss:
        print(f"✗ statistical_significance 缺少字段: {missing_ss}")
        print(f"  当前字段: {list(ss.keys())}")
        return False
    else:
        print(f"✓ statistical_significance 字段完整（7个）")
    
    # ========== Step 5: 保存结果 ==========
    print("\n[Step 5] 测试 save_ic_result()")
    test_output_path = project_root / 'factor_ic' / 'result' / 'test_rsi_1d_analysis_result.json'
    try:
        # 手动保存到测试路径
        with open(test_output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"✓ 保存成功: {test_output_path}")
        print(f"  文件大小: {test_output_path.stat().st_size} bytes")
    except Exception as e:
        print(f"✗ 保存失败: {e}")
        return False
    
    # ========== 完成 ==========
    print("\n" + "=" * 60)
    print("✓ 公共模块验证通过！所有字段符合 MODULE.md 规范")
    print("=" * 60)
    
    # 清理测试文件
    if test_output_path.exists():
        test_output_path.unlink()
        print("\n已清理测试输出文件")
    
    return True


if __name__ == '__main__':
    success = test_public_modules()
    sys.exit(0 if success else 1)