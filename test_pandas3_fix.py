#!/usr/bin/env python3
"""
pandas 3.0 兼容性修复验证测试
测试修复后的代码是否能正确保留分组列（asset, date）
"""

import pandas as pd
import numpy as np
import sys

print("=" * 60)
print("pandas 3.0 兼容性修复验证测试")
print("=" * 60)
print(f"pandas 版本: {pd.__version__}")
print()

# 测试结果统计
test_results = {
    "passed": 0,
    "failed": 0,
    "errors": []
}

def test_cumcount_preserves_columns():
    """
    测试修复1: cumcount() 替代 groupby().apply(tail)
    验证 asset 列是否保留
    """
    print("测试 1: cumcount() 替代 groupby().apply(tail)")
    print("-" * 60)
    
    # 创建模拟数据
    np.random.seed(42)
    n_days = 10  # 每只股票最多保留10天
    
    data = {
        'asset': ['AAPL'] * 15 + ['GOOGL'] * 12 + ['MSFT'] * 8,
        'date': pd.date_range('2024-01-01', periods=35, freq='D'),
        'value': np.random.randn(35)
    }
    df = pd.DataFrame(data)
    
    print(f"原始数据: {len(df)} 条记录")
    print(f"资产列表: {df['asset'].unique()}")
    print()
    
    # 应用修复后的代码
    # pandas 3.0 兼容性修复：使用 cumcount 替代 groupby().apply(tail)
    df['row_num'] = df.groupby('asset').cumcount(ascending=False)
    filtered_df = df[df['row_num'] < n_days].drop('row_num', axis=1)
    
    print(f"过滤后数据: {len(filtered_df)} 条记录")
    print(f"每只股票记录数:")
    for asset in filtered_df['asset'].unique():
        count = len(filtered_df[filtered_df['asset'] == asset])
        print(f"  {asset}: {count} 条")
    print()
    
    # 验证
    checks = [
        ("asset 列存在", 'asset' in filtered_df.columns),
        ("date 列存在", 'date' in filtered_df.columns),
        ("value 列存在", 'value' in filtered_df.columns),
        ("AAPL 有10条", len(filtered_df[filtered_df['asset'] == 'AAPL']) == 10),
        ("GOOGL 有10条", len(filtered_df[filtered_df['asset'] == 'GOOGL']) == 10),
        ("MSFT 有8条", len(filtered_df[filtered_df['asset'] == 'MSFT']) == 8),  # 原本只有8条
    ]
    
    all_passed = True
    for name, result in checks:
        status = "✓" if result else "✗"
        print(f"  {status} {name}")
        if not result:
            all_passed = False
            test_results["errors"].append(f"测试1失败: {name}")
    
    if all_passed:
        test_results["passed"] += 1
        print("\n✅ 测试1通过")
    else:
        test_results["failed"] += 1
        print("\n❌ 测试1失败")
    
    print()
    return all_passed


def test_groupby_apply_with_group_keys():
    """
    测试修复2: group_keys=True + reset_index(level='date')
    验证 date 列是否保留
    """
    print("测试 2: group_keys=True + reset_index(level='date')")
    print("-" * 60)
    
    # 创建模拟数据
    np.random.seed(42)
    
    data = {
        'date': pd.to_datetime(['2024-01-01'] * 5 + ['2024-01-02'] * 5 + ['2024-01-03'] * 5),
        'asset': ['AAPL', 'GOOGL', 'MSFT', 'AMZN', 'TSLA'] * 3,
        'total_score': np.random.randn(15)
    }
    df = pd.DataFrame(data)
    
    print(f"原始数据: {len(df)} 条记录")
    print(f"日期列表: {df['date'].unique()}")
    print(f"资产列表: {df['asset'].unique()}")
    print()
    
    # 应用修复后的代码
    def get_top_n(group, n=3):
        top = group.nlargest(n, 'total_score')
        return top
    
    # pandas 3.0 兼容性修复：使用 reset_index(level='date') 恢复分组列
    selected_df = df.groupby('date', group_keys=True).apply(
        get_top_n, n=3, include_groups=False
    ).reset_index(level='date')
    
    print(f"筛选后数据: {len(selected_df)} 条记录")
    print(f"列名: {selected_df.columns.tolist()}")
    print(f"每日期选出资产数:")
    for date in selected_df['date'].unique():
        count = len(selected_df[selected_df['date'] == date])
        print(f"  {date}: {count} 条")
    print()
    
    # 验证
    checks = [
        ("date 列存在", 'date' in selected_df.columns),
        ("asset 列存在", 'asset' in selected_df.columns),
        ("total_score 列存在", 'total_score' in selected_df.columns),
        ("每个日期有3条记录", all(
            len(selected_df[selected_df['date'] == d]) == 3 
            for d in selected_df['date'].unique()
        )),
        ("总记录数为9", len(selected_df) == 9),  # 3天 * 3条
    ]
    
    all_passed = True
    for name, result in checks:
        status = "✓" if result else "✗"
        print(f"  {status} {name}")
        if not result:
            all_passed = False
            test_results["errors"].append(f"测试2失败: {name}")
    
    if all_passed:
        test_results["passed"] += 1
        print("\n✅ 测试2通过")
    else:
        test_results["failed"] += 1
        print("\n❌ 测试2失败")
    
    print()
    return all_passed


def test_industry_constraint_scenario():
    """
    测试修复3: 行业约束场景下的 group_keys=True
    模拟 scoring_engine.py 中的实际使用场景
    """
    print("测试 3: 行业约束场景 (scoring_engine.py)")
    print("-" * 60)
    
    # 创建模拟数据（模拟 scoring_engine 场景）
    np.random.seed(42)
    
    data = {
        'date': pd.to_datetime(['2024-01-01'] * 10 + ['2024-01-02'] * 10),
        'asset': ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J'] * 2,
        'industry': ['Tech', 'Tech', 'Finance', 'Finance', 'Health',
                     'Tech', 'Health', 'Finance', 'Tech', 'Health'] * 2,
        'total_score': np.random.randn(20)
    }
    df = pd.DataFrame(data)
    
    print(f"原始数据: {len(df)} 条记录")
    print(f"行业分布:")
    for industry in df['industry'].unique():
        count = len(df[df['industry'] == industry])
        print(f"  {industry}: {count} 条")
    print()
    
    # 应用修复后的代码（带行业约束）
    def get_top_n_with_industry_constraint(group, top_n=5, max_same_industry=2):
        # 先按得分排序
        sorted_group = group.sort_values('total_score', ascending=False)
        
        # 应用行业约束
        industry_count = {}
        selected = []
        
        for _, row in sorted_group.iterrows():
            ind = row['industry']
            if industry_count.get(ind, 0) < max_same_industry:
                selected.append(row)
                industry_count[ind] = industry_count.get(ind, 0) + 1
            
            if len(selected) >= top_n:
                break
        
        if selected:
            result_df = pd.DataFrame(selected)
            return result_df
        else:
            return pd.DataFrame(columns=group.columns)
    
    # pandas 3.0 兼容性修复：使用 reset_index(level='date') 恢复分组列
    selected_df = df.groupby('date', group_keys=True).apply(
        lambda g: get_top_n_with_industry_constraint(g, top_n=5, max_same_industry=2),
        include_groups=False
    ).reset_index(level='date')
    
    print(f"筛选后数据: {len(selected_df)} 条记录")
    print(f"列名: {selected_df.columns.tolist()}")
    
    if not selected_df.empty:
        print(f"每日期选出资产数:")
        for date in selected_df['date'].unique():
            date_data = selected_df[selected_df['date'] == date]
            print(f"  {date}: {len(date_data)} 条")
            print(f"    行业分布: {date_data['industry'].value_counts().to_dict()}")
        print()
        
        # 验证
        checks = [
            ("date 列存在", 'date' in selected_df.columns),
            ("asset 列存在", 'asset' in selected_df.columns),
            ("industry 列存在", 'industry' in selected_df.columns),
            ("total_score 列存在", 'total_score' in selected_df.columns),
            ("每个日期最多5条记录", all(
                len(selected_df[selected_df['date'] == d]) <= 5 
                for d in selected_df['date'].unique()
            )),
            ("每个日期每个行业最多2条", all(
                (selected_df[selected_df['date'] == d]['industry'].value_counts() <= 2).all()
                for d in selected_df['date'].unique()
            )),
        ]
    else:
        print("⚠️ 警告: 筛选结果为空")
        checks = [
            ("date 列存在", 'date' in selected_df.columns),
            ("结果非空（警告）", not selected_df.empty),
        ]
    
    all_passed = True
    for name, result in checks:
        status = "✓" if result else "✗"
        print(f"  {status} {name}")
        if not result:
            all_passed = False
            test_results["errors"].append(f"测试3失败: {name}")
    
    if all_passed:
        test_results["passed"] += 1
        print("\n✅ 测试3通过")
    else:
        test_results["failed"] += 1
        print("\n❌ 测试3失败")
    
    print()
    return all_passed


def test_pandas_version_compatibility():
    """
    测试 pandas 版本兼容性
    """
    print("测试 4: pandas 版本检查")
    print("-" * 60)
    
    version = pd.__version__
    major, minor, *_ = map(int, version.split('.'))
    
    print(f"当前 pandas 版本: {version}")
    print(f"主版本号: {major}, 次版本号: {minor}")
    
    if major >= 3:
        print("✓ 检测到 pandas 3.x - 修复代码应该生效")
        is_v3_or_later = True
    elif major == 2 and minor >= 0:
        print("✓ 检测到 pandas 2.x - 修复代码向后兼容")
        is_v3_or_later = False
    else:
        print("⚠️ 警告: pandas 版本较旧，建议升级")
        is_v3_or_later = False
    
    print()
    
    # 记录通过
    test_results["passed"] += 1
    return True


def main():
    """运行所有测试"""
    try:
        # 运行测试
        test_cumcount_preserves_columns()
        test_groupby_apply_with_group_keys()
        test_industry_constraint_scenario()
        test_pandas_version_compatibility()
        
        # 输出总结
        print("=" * 60)
        print("测试总结")
        print("=" * 60)
        print(f"✅ 通过: {test_results['passed']}")
        print(f"❌ 失败: {test_results['failed']}")
        
        if test_results['errors']:
            print("\n错误详情:")
            for error in test_results['errors']:
                print(f"  - {error}")
        
        print()
        
        if test_results['failed'] == 0:
            print("🎉 所有测试通过！pandas 3.0 兼容性修复验证成功！")
            return 0
        else:
            print("⚠️ 部分测试失败，请检查修复代码")
            return 1
            
    except Exception as e:
        print(f"\n❌ 测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())