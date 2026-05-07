#!/usr/bin/env python3
"""
导出IC分析结果为JSON格式
供Web界面使用

使用方式:
    python export_results.py
"""

import json
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from main import main


def export_to_json(results):
    """将IC结果导出为JSON格式"""
    output_file = Path(__file__).parent / 'ic_results.json'
    
    json_data = {}
    
    for factor_name, result in results.items():
        stats = result['statistics']
        ic_series = result['ic_series']
        
        # 因子描述
        descriptions = {
            'rsi_oversold': 'RSI超卖因子 - 当RSI<30时为True',
            'volume_ratio_high': '成交量比率因子 - 当成交量>5日均量*1.5时为True'
        }
        
        # 计算评级
        icir = abs(stats['icir']) if stats['icir'] and not str(stats['icir']) == 'nan' else 0
        if icir > 1.0:
            grade = "A级 (优秀)"
        elif icir > 0.5:
            grade = "B级 (良好)"
        elif icir > 0.3:
            grade = "C级 (一般)"
        else:
            grade = "D级 (较弱)"
        
        json_data[factor_name] = {
            'statistics': {
                'ic_mean': float(stats['ic_mean']),
                'ic_std': float(stats['ic_std']),
                'icir': float(stats['icir']),
                't_stat': float(stats['t_stat']),
                'ic_positive_ratio': float(stats['ic_positive_ratio']),
                'sample_count': int(stats['sample_count'])
            },
            'description': descriptions.get(factor_name, f'{factor_name} 因子'),
            'grade': grade
        }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, indent=2, ensure_ascii=False)
    
    print(f"\n✓ IC结果已导出到: {output_file}")
    return output_file


if __name__ == '__main__':
    print("="*60)
    print("运行IC分析并导出结果")
    print("="*60)
    
    # 运行主程序获取结果
    results = main()
    
    # 导出为JSON
    export_to_json(results)
    
    print("\n" + "="*60)
    print("导出完成！可以运行 web_app.py 启动Web界面")
    print("="*60)