#!/usr/bin/env python3
"""
测试扩展的条件解析器
测试命题: "3日涨幅 < 20% 且 非涨停"
"""

import sys
from pathlib import Path

# 添加模块路径
sys.path.insert(0, str(Path(__file__).parent))

from stock_selection_backtest import (
    ConditionParser, 
    LLMConditionParser, 
    SmartConditionParser,
    BacktestEngine
)

def test_rule_parser():
    """测试规则解析器"""
    print("=" * 60)
    print("测试规则解析器 (ConditionParser)")
    print("=" * 60)
    
    parser = ConditionParser()
    
    test_cases = [
        "RSI < 30",
        "量比 > 2",
        "RSI < 30 且 量比 > 1.5",
        "3日涨幅 < 20%",
        "非涨停",
        "3日涨幅 < 20% 且 非涨停",
        "非一字涨停",
    ]
    
    for condition in test_cases:
        print(f"\n条件: {condition}")
        result = parser.parse(condition)
        print(f"  有效: {result['valid']}")
        print(f"  逻辑: {result['logic']}")
        print(f"  规则: {result['rules']}")
        if result['error']:
            print(f"  错误: {result['error']}")


def test_smart_parser():
    """测试智能解析器"""
    print("\n" + "=" * 60)
    print("测试智能解析器 (SmartConditionParser)")
    print("=" * 60)
    
    parser = SmartConditionParser(use_llm=False)  # 不使用大模型
    
    test_cases = [
        "RSI < 30",
        "3日涨幅 < 20%",
        "非涨停",
        "3日涨幅 < 20% 且 非涨停",  # 测试命题
        "RSI < 30 且 非涨停",
        "非一字涨停 且 RSI > 50",
    ]
    
    for condition in test_cases:
        print(f"\n条件: {condition}")
        result = parser.parse(condition)
        print(f"  有效: {result['valid']}")
        print(f"  来源: {result.get('source', 'unknown')}")
        print(f"  逻辑: {result['logic']}")
        print(f"  规则: {result['rules']}")
        if result['error']:
            print(f"  错误: {result['error']}")


def test_load_data():
    """测试数据加载（包含计算型指标）"""
    print("\n" + "=" * 60)
    print("测试数据加载 - 计算型指标")
    print("=" * 60)
    
    engine = BacktestEngine(use_llm=False)
    
    try:
        factor_df, return_df, stock_list = engine.load_data()
        
        print(f"\n数据加载成功!")
        print(f"  数据条数: {len(factor_df)}")
        print(f"  字段: {list(factor_df.columns)}")
        
        # 检查计算型指标
        computed_fields = ['return_3d', 'is_limit_up', 'is_one_word', 'is_sealed']
        for field in computed_fields:
            if field in factor_df.columns:
                print(f"  {field}: ✓ 存在")
                # 显示一些统计
                if field.startswith('is_'):
                    true_count = factor_df[field].sum()
                    print(f"    - True 数量: {true_count} ({true_count/len(factor_df)*100:.2f}%)")
                else:
                    valid = factor_df[field].dropna()
                    if len(valid) > 0:
                        print(f"    - 范围: {valid.min():.4f} ~ {valid.max():.4f}")
                        print(f"    - 均值: {valid.mean():.4f}")
            else:
                print(f"  {field}: ✗ 缺失")
        
        # 显示几条样例数据
        print("\n样例数据（包含计算指标）:")
        sample = factor_df[factor_df['is_limit_up'] == True].head(3)
        for _, row in sample.iterrows():
            print(f"  {row['date']} {row['asset']}: close={row['close']}, "
                  f"return_3d={row.get('return_3d', 'N/A'):.4f if pd.notna(row.get('return_3d')) else 'N/A'}, "
                  f"is_limit_up={row['is_limit_up']}")
        
        return True
    except Exception as e:
        print(f"数据加载失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_backtest():
    """测试回测功能 - 测试命题: "3日涨幅 < 20% 且 非涨停" """
    print("\n" + "=" * 60)
    print("测试回测功能 - 测试命题")
    print("命题: 3日涨幅 < 20% 且 非涨停")
    print("=" * 60)
    
    engine = BacktestEngine(use_llm=False)
    
    # 测试命题
    condition = "3日涨幅 < 20% 且 非涨停"
    
    print(f"\n开始回测: {condition}")
    print("回测周期: 250个交易日")
    
    result = engine.run_backtest(condition, period_days=250)
    
    print(f"\n回测结果:")
    print(f"  状态: {result.status}")
    print(f"  任务ID: {result.task_id}")
    print(f"  日期范围: {result.start_date} ~ {result.end_date}")
    
    if result.parsed_condition:
        print(f"\n  解析后的条件:")
        print(f"    逻辑: {result.parsed_condition.get('logic')}")
        print(f"    规则: {result.parsed_condition.get('rules')}")
        print(f"    来源: {result.parsed_condition.get('source', 'unknown')}")
    
    if result.status == 'completed':
        print(f"\n  回测统计:")
        print(f"    总交易次数: {result.total_trades}")
        print(f"    选出股票数: {result.total_stocks_selected}")
        print(f"    平均T+1收益: {result.avg_forward_return}%")
        print(f"    平均开盘涨幅: {result.avg_open_return}%")
        print(f"    平均最高收益: {result.avg_high_return}%")
        print(f"    涨停概率: {result.limit_up_prob}%")
        print(f"    上涨概率: {result.positive_rate}%")
        print(f"    盈亏比: {result.profit_ratio}")
        print(f"    最终净值: {result.nav_final}")
        
        if result.trade_details:
            print(f"\n  前5笔交易明细:")
            for trade in result.trade_details[:5]:
                print(f"    {trade['date']} {trade['stock_code']}: "
                      f"收益={trade['forward_return']}%, "
                      f"RSI={trade.get('rsi_6', 'N/A')}")
    else:
        print(f"\n  错误: {result.error}")


if __name__ == '__main__':
    import pandas as pd
    
    # 运行测试
    test_rule_parser()
    test_smart_parser()
    test_load_data()
    test_backtest()
    
    print("\n" + "=" * 60)
    print("测试完成!")
    print("=" * 60)