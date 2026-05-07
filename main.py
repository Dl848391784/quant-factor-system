#!/usr/bin/env python3
"""
因子池 IC 分析系统 - 主程序
作者: 云舟
功能: 计算因子 Rank IC 并生成可视化报告

使用方法:
    python main.py
"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from data_loader import DataLoader
from ic_calculator import ICCalculator
from visualizer import ICVisualizer


def main():
    """主函数"""
    print("="*60)
    print("因子池 IC 分析系统")
    print("="*60)
    
    # 1. 初始化数据加载器
    print("\n[步骤1] 加载数据")
    loader = DataLoader(use_real_data=False)
    
    # 使用模拟数据（如有真实数据接口，可替换）
    factor_data, return_data = loader.load_simulated_data(
        num_stocks=100,     # 100只股票
        num_days=750,       # 约3年交易日
        start_date='2021-04-01'
    )
    
    # 2. 初始化IC计算器
    print("\n[步骤2] 计算因子IC")
    calculator = ICCalculator(factor_data, return_data)
    
    # 分析两个布尔因子
    factor_names = ['rsi_oversold', 'volume_ratio_high']
    
    for factor_name in factor_names:
        ic_series, stats = calculator.analyze_factor(factor_name)
    
    # 3. 输出统计报告
    calculator.print_report()
    
    # 4. 生成可视化图表
    print("\n[步骤3] 生成可视化图表")
    output_dir = Path(__file__).parent / 'output'
    visualizer = ICVisualizer(output_dir=str(output_dir))
    
    saved_paths = visualizer.generate_report(calculator.ic_results, show=False)
    
    # 5. 输出总结
    print("\n" + "="*60)
    print("分析完成！")
    print("="*60)
    print(f"\n生成的图表:")
    for path in saved_paths:
        print(f"  - {path}")
    
    # 返回结果供外部调用
    return calculator.ic_results


if __name__ == '__main__':
    results = main()