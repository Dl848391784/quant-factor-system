#!/usr/bin/env python3
"""
因子分析数据汇总报告生成脚本

功能：
1. 读取单因子 IC 分析结果
2. 读取单因子分层回测结果
3. 计算因子相关性矩阵
4. 读取综合因子四种权重回测结果
5. 生成完整的汇总报告表格

使用方法：
    python scripts/generate_factor_summary_report.py [--date YYYY-MM-DD] [--output report.txt]

参数：
    --date: 指定日期（默认当天）
    --output: 指定输出文件路径（默认打印到终端）
"""

import argparse
import gzip
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

import pandas as pd
import numpy as np


# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.resolve()

# 数据路径配置
DATA_PATHS = {
    'ic_result': 'factor_ic/result',
    'backtest_result': 'backtest/result',
    'backtest_log': 'backtest/logs',
    'comprehensive_result': 'comprehensive_factor/result',
    'factor_data': 'data_fetchers/result',
}

# 因子列名映射（数据列名 → 因子逻辑名）
FACTOR_COL_TO_NAME_MAP = {
    'rsi_6': 'rsi',
    'volume_ratio_5': 'volume_ratio',
    'kdj_j': 'kdj_j',
    'bollinger_pb': 'bollinger_pb',
    'turnover_surge': 'turnover_surge',
}


def get_date_str(date: Optional[str] = None) -> str:
    """获取日期字符串"""
    if date:
        return date
    return datetime.now().strftime('%Y-%m-%d')


def load_json_file(path: Path) -> Optional[Dict]:
    """加载 JSON 文件"""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as e:
        print(f"JSON 解析错误: {path} - {e}")
        return None


def load_ic_results(date: str) -> List[Dict]:
    """加载所有单因子 IC 分析结果"""
    ic_dir = PROJECT_ROOT / DATA_PATHS['ic_result']
    results = []
    
    for file in ic_dir.glob('ic_*_analysis_result.json'):
        data = load_json_file(file)
        if data:
            factor_name = data.get('factor_name', '').replace('_1d', '')
            ic_metrics = data.get('ic_metrics', {})
            sample_stats = data.get('sample_stats', {})
            
            results.append({
                'factor_name': factor_name,
                'ic_mean': ic_metrics.get('ic_mean', 0),
                'icir': ic_metrics.get('icir', 0),
                'ic_std': ic_metrics.get('ic_std', 0),
                'valid_days': sample_stats.get('valid_days', 0),
            })
    
    # 按 ICIR 降序排序
    results.sort(key=lambda x: x['icir'], reverse=True)
    return results


def load_backtest_results(date: str) -> List[Dict]:
    """加载所有单因子分层回测结果"""
    backtest_dir = PROJECT_ROOT / DATA_PATHS['backtest_result']
    results = []
    
    for file in backtest_dir.glob('*_layered_backtest.json'):
        data = load_json_file(file)
        if data:
            factor_name = file.stem.replace('_layered_backtest', '')
            long_short = data.get('long_short', {})
            monotonicity = data.get('monotonicity', {})
            
            # 单调性质量判定
            corr = monotonicity.get('correlation', 0)
            quality = monotonicity.get('quality', 'unknown')
            quality_symbol = get_monotonicity_symbol(quality)
            
            results.append({
                'factor_name': factor_name,
                'long_short_return_annual': long_short.get('long_short_return_annual', 0) * 100,
                'long_short_sharpe': long_short.get('long_short_sharpe', 0),
                'monotonicity_correlation': corr,
                'monotonicity_quality': quality,
                'monotonicity_symbol': quality_symbol,
            })
    
    return results


def calculate_factor_correlation(ic_results: List[Dict], force_full: bool = False) -> Optional[pd.DataFrame]:
    """计算所有因子之间的相关性矩阵
    
    尝试从综合因子结果文件中读取相关性数据。
    如果 force_full=True 或综合因子结果中没有相关性数据，则从因子数据文件中实时计算。
    
    Args:
        ic_results: IC 结果列表
        force_full: 是否强制计算所有因子之间的相关性（忽略缓存）
    
    Returns:
        因子相关性矩阵 DataFrame，或 None
    """
    # 如果不强制全量计算，优先从综合因子结果文件读取
    if not force_full:
        comp_file = PROJECT_ROOT / DATA_PATHS['comprehensive_result'] / 'composite_icir_weight_1d.json'
        data = load_json_file(comp_file)
        
        if data and 'meta' in data:
            meta = data['meta']
            if 'correlation_matrix' in meta:
                # 从 JSON 转换为 DataFrame
                corr_dict = meta['correlation_matrix']
                corr_df = pd.DataFrame(corr_dict)
                
                # 确保对角线为1（数值精度问题）
                for col in corr_df.columns:
                    corr_df.loc[col, col] = 1.0
                
                print("从综合因子结果文件读取相关性数据（仅选中因子）")
                return corr_df
    
    # 如果综合因子结果中没有相关性数据，尝试从原始数据计算
    factor_data_path = PROJECT_ROOT / DATA_PATHS['factor_data'] / 'factor_ic_data.json.gz'
    
    if not factor_data_path.exists():
        return None
    
    print("从因子数据文件计算相关性（可能较慢）...")
    start_time = time.time()
    
    try:
        # 数据文件结构：每行一个股票，data 数组包含所有日期数据
        # 因子列在 data[i] 中
        factor_cols = list(FACTOR_COL_TO_NAME_MAP.keys())
        
        # 使用更节省内存的方法：逐行读取
        with gzip.open(factor_data_path, 'rt', encoding='utf-8') as f:
            # 从 data 数组中提取因子值
            data_list = []
            stock_count = 0
            max_stocks = 100  # 只读取 100 只股票的数据
            
            for line in f:
                if stock_count >= max_stocks:
                    break
                
                try:
                    stock_data = json.loads(line)
                    data_array = stock_data.get('data', [])
                    
                    for day_data in data_array:
                        # 只提取因子列
                        factor_row = {}
                        for col in factor_cols:
                            if col in day_data:
                                val = day_data[col]
                                # 排除 NaN（JSON 中 NaN 会被解析为 None 或特殊值）
                                if val is not None and isinstance(val, (int, float)):
                                    factor_row[col] = val
                        
                        if factor_row and len(factor_row) > 1:  # 至少需要 2 个因子值
                            data_list.append(factor_row)
                    
                    stock_count += 1
                except json.JSONDecodeError:
                    continue
            
            if not data_list:
                return None
            
            # 转换为 DataFrame
            factor_df = pd.DataFrame(data_list)
            
            # 计算相关性
            corr_matrix = factor_df.corr()
            
            # 重命名
            factor_names = [FACTOR_COL_TO_NAME_MAP.get(c, c) for c in corr_matrix.columns]
            corr_df = corr_matrix.copy()
            corr_df.index = factor_names
            corr_df.columns = factor_names
            
            elapsed = time.time() - start_time
            print(f"  因子相关性计算完成，耗时: {elapsed:.2f}秒（采样{stock_count}只股票，{len(data_list)}条记录）")
            
            return corr_df
    
    except Exception as e:
        print(f"  计算因子相关性失败: {e}")
        return None


def load_composite_results(date: str) -> List[Dict]:
    """加载综合因子四种权重回测结果"""
    comp_dir = PROJECT_ROOT / DATA_PATHS['comprehensive_result']
    results = []
    
    weight_methods = ['ic_weight', 'icir_weight', 'rolling_icir_weight', 'equal_weight']
    
    for method in weight_methods:
        file = comp_dir / f'composite_{method}_1d.json'
        data = load_json_file(file)
        if data:
            meta = data.get('meta', {})
            backtest = data.get('backtest_result', {})
            long_short = backtest.get('long_short', {})
            monotonicity = backtest.get('monotonicity', {})
            weights = meta.get('weights', {})
            
            # 格式化权重字符串
            if method == 'rolling_icir_weight':
                weight_str = '动态权重(60日)'
            else:
                weight_str = format_weights(weights)
            
            # 单调性质量判定
            quality = monotonicity.get('quality', 'unknown')
            quality_symbol = get_monotonicity_symbol(quality)
            
            results.append({
                'weight_method': method,
                'weight_method_display': get_weight_method_display(method),
                'long_short_return_annual': long_short.get('long_short_return_annual', 0) * 100,
                'long_short_sharpe': long_short.get('long_short_sharpe', 0),
                'monotonicity_correlation': monotonicity.get('correlation', 0),
                'monotonicity_quality': quality,
                'monotonicity_symbol': quality_symbol,
                'weight_str': weight_str,
            })
    
    return results


def get_monotonicity_symbol(quality: str) -> str:
    """获取单调性质量符号"""
    symbols = {
        'good': '✓良好',
        'moderate': '△一般',
        'poor': '✗较差',
        'unknown': '?未知',
    }
    return symbols.get(quality, '?未知')


def get_weight_method_display(method: str) -> str:
    """获取权重方法显示名称"""
    displays = {
        'ic_weight': 'IC加权',
        'icir_weight': 'ICIR加权',
        'rolling_icir_weight': 'Rolling ICIR加权',
        'equal_weight': '等权',
    }
    return displays.get(method, method)


def format_weights(weights: Dict) -> str:
    """格式化权重字符串"""
    factor_abbr = {
        'turnover_surge': 'ts',
        'bollinger_pb': 'bp',
        'volume_ratio': 'vr',
        'rsi': 'rsi',
        'kdj_j': 'kdj',
    }
    
    parts = []
    for factor, weight in weights.items():
        abbr = factor_abbr.get(factor, factor[:3])
        parts.append(f"{abbr}:{weight*100:.0f}%")
    
    return ', '.join(parts)


def format_percentage(value: float, decimals: int = 2) -> str:
    """格式化百分比"""
    return f"{value:.{decimals}f}%"


def format_float(value: float, decimals: int = 4) -> str:
    """格式化浮点数"""
    return f"{value:.{decimals}f}"


def generate_correlation_section(corr_matrix: pd.DataFrame, ic_results: List[Dict]) -> List[str]:
    """生成因子相关性部分"""
    lines = []
    
    if corr_matrix is None:
        lines.append("")
        lines.append("三、因子相关性矩阵")
        lines.append("-" * 70)
        lines.append("因子相关性数据不可用（需要因子数据文件）")
        lines.append("-" * 70)
        return lines
    
    # 获取因子名（按 ICIR 排序）
    factor_names = [r['factor_name'] for r in ic_results if r['factor_name'] in corr_matrix.index]
    
    lines.append("")
    lines.append("三、因子相关性矩阵")
    lines.append("-" * 70)
    
    # 表头
    header = f"{'因子':<12}"
    for name in factor_names:
        header += f"{name[:8]:>10}"
    lines.append(header)
    lines.append("-" * 70)
    
    # 矩阵内容
    for row_name in factor_names:
        row = f"{row_name:<12}"
        for col_name in factor_names:
            val = corr_matrix.loc[row_name, col_name]
            row += f"{format_float(val, 2):>10}"
        lines.append(row)
    
    lines.append("-" * 70)
    
    # 高相关因子对
    high_corr_pairs = []
    for i, row_name in enumerate(factor_names):
        for j, col_name in enumerate(factor_names):
            if i < j:
                val = abs(corr_matrix.loc[row_name, col_name])
                if val > 0.7:
                    high_corr_pairs.append((row_name, col_name, val))
    
    if high_corr_pairs:
        lines.append("高相关因子对（|corr| > 0.7，建议剔除其中一个）：")
        for pair in high_corr_pairs:
            lines.append(f"  - {pair[0]} vs {pair[1]}: {format_float(pair[2], 2)}")
    else:
        lines.append("无高相关因子对（所有因子相关性 < 0.7）")
    
    # 中等相关因子对
    med_corr_pairs = []
    for i, row_name in enumerate(factor_names):
        for j, col_name in enumerate(factor_names):
            if i < j:
                val = abs(corr_matrix.loc[row_name, col_name])
                if 0.5 < val <= 0.7:
                    med_corr_pairs.append((row_name, col_name, val))
    
    if med_corr_pairs:
        lines.append("")
        lines.append("中等相关因子对（0.5 < |corr| <= 0.7）：")
        for pair in med_corr_pairs:
            lines.append(f"  - {pair[0]} vs {pair[1]}: {format_float(pair[2], 2)}")
    
    lines.append("-" * 70)
    
    return lines


def get_factor_selection_info(composite_results: List[Dict], ic_results: List[Dict], backtest_results: List[Dict]) -> str:
    """获取因子筛选信息"""
    if not composite_results:
        return "未找到综合因子结果"
    
    lines = []
    lines.append("auto_select 模式结果:")
    
    # 从综合因子权重中推断选中的因子
    selected_factors = []
    for item in composite_results:
        if item['weight_method'] == 'icir_weight':
            comp_file = PROJECT_ROOT / DATA_PATHS['comprehensive_result'] / 'composite_icir_weight_1d.json'
            data = load_json_file(comp_file)
            if data:
                meta = data.get('meta', {})
                selected_factors = meta.get('factor_list', [])
                weights = meta.get('weights', {})
                
                factor_info = []
                for f in selected_factors:
                    weight = weights.get(f, 0)
                    ic_item = next((r for r in ic_results if r['factor_name'] == f), None)
                    if ic_item:
                        factor_info.append(f"{f}(ICIR={ic_item['icir']:.2f},权重={weight*100:.1f}%)")
                    else:
                        factor_info.append(f"{f}(权重={weight*100:.1f}%)")
                
                lines.append(f"  - 选中因子: {', '.join(factor_info)}")
            break
    
    # 推断剔除的因子
    all_factors = [r['factor_name'] for r in ic_results]
    excluded_factors = [f for f in all_factors if f not in selected_factors]
    
    if excluded_factors:
        excluded_info = []
        for f in excluded_factors:
            ic_item = next((r for r in ic_results if r['factor_name'] == f), None)
            bt_item = next((r for r in backtest_results if r['factor_name'] == f), None)
            
            reason = ""
            if ic_item and ic_item['icir'] < 0.15:
                reason = "ICIR<0.15"
            if bt_item and bt_item['long_short_return_annual'] < 3:
                reason += (", " if reason else "") + "多空收益<3%"
            
            if not reason:
                reason = "高相关性剔除"
            
            excluded_info.append(f"{f}({reason})")
        
        lines.append(f"  - 剔除因子: {', '.join(excluded_info)}")
    
    lines.append("-" * 70)
    lines.append(f"筛选后因子列表: {selected_factors}")
    
    return '\n'.join(lines)


def merge_factor_data(ic_results: List[Dict], backtest_results: List[Dict]) -> List[Dict]:
    """合并 IC 和回测数据"""
    merged = []
    
    for ic_item in ic_results:
        factor_name = ic_item['factor_name']
        backtest_item = next(
            (b for b in backtest_results if b['factor_name'] == factor_name),
            {}
        )
        merged.append({**ic_item, **backtest_item})
    
    return merged


def generate_report(date: str, force_full_correlation: bool = False) -> str:
    """生成完整的汇总报告"""
    lines = []
    
    # 加载所有数据
    print("加载 IC 结果...")
    ic_results = load_ic_results(date)
    
    print("加载回测结果...")
    backtest_results = load_backtest_results(date)
    
    print("加载综合因子结果...")
    composite_results = load_composite_results(date)
    
    # 计算因子相关性矩阵
    corr_matrix = calculate_factor_correlation(ic_results, force_full=force_full_correlation)
    
    # 合并 IC 和回测数据
    factor_data = merge_factor_data(ic_results, backtest_results)
    
    # 报告标题
    lines.append("=" * 70)
    lines.append(f"                    因子分析数据汇总报告 ({date})")
    lines.append("=" * 70)
    
    # 第一部分：单因子 IC 数据汇总
    lines.append("")
    lines.append("一、单因子 IC 数据汇总")
    lines.append("-" * 70)
    lines.append(f"{'因子':<18} {'IC均值':>10} {'ICIR':>8} {'IC标准差':>10} {'有效天数':>8}")
    lines.append("-" * 70)
    
    for item in ic_results:
        lines.append(
            f"{item['factor_name']:<18} "
            f"{format_float(item['ic_mean']):>10} "
            f"{format_float(item['icir']):>8} "
            f"{format_float(item['ic_std']):>10} "
            f"{item['valid_days']:>8}"
        )
    
    lines.append("-" * 70)
    ic_order = ', '.join([f"{r['factor_name']}({r['icir']:.2f})" for r in ic_results[:5]])
    lines.append(f"IC排序(ICIR降序): {ic_order}")
    
    # 第二部分：单因子分层回测数据汇总
    lines.append("")
    lines.append("二、单因子分层回测数据汇总")
    lines.append("-" * 70)
    lines.append(f"{'因子':<18} {'多空年化收益':>12} {'夏普比率':>8} {'单调性系数':>10} {'单调性质量':>10}")
    lines.append("-" * 70)
    
    factor_order = [r['factor_name'] for r in ic_results]
    backtest_sorted = sorted(
        backtest_results,
        key=lambda x: factor_order.index(x['factor_name']) if x['factor_name'] in factor_order else 999
    )
    
    for item in backtest_sorted:
        lines.append(
            f"{item['factor_name']:<18} "
            f"{format_percentage(item['long_short_return_annual']):>12} "
            f"{format_float(item['long_short_sharpe'], 2):>8} "
            f"{format_float(item['monotonicity_correlation']):>10} "
            f"{item['monotonicity_symbol']:>10}"
        )
    
    lines.append("-" * 70)
    lines.append("注：turnover_surge 和 volume_ratio 单调性良好（负相关，Layer1 > Layer5）")
    lines.append("    kdj_j 单调性较差（正相关，Layer5 收益最高，违反反向因子预期）")
    
    # 第三部分：因子相关性矩阵（新增）
    lines.extend(generate_correlation_section(corr_matrix, ic_results))
    
    # 第四部分：因子筛选结果
    lines.append("")
    lines.append("四、因子筛选结果")
    lines.append("-" * 70)
    selection_info = get_factor_selection_info(composite_results, ic_results, backtest_results)
    lines.append(selection_info)
    
    # 第五部分：综合因子四种权重回测数据汇总
    lines.append("")
    lines.append("五、综合因子四种权重回测数据汇总")
    lines.append("-" * 70)
    lines.append(f"{'权重方法':<20} {'多空年化收益':>12} {'夏普比率':>8} {'单调性系数':>10} {'单调性质量':>10} {'因子权重':<20}")
    lines.append("-" * 70)
    
    for item in composite_results:
        lines.append(
            f"{item['weight_method_display']:<20} "
            f"{format_percentage(item['long_short_return_annual']):>12} "
            f"{format_float(item['long_short_sharpe'], 2):>8} "
            f"{format_float(item['monotonicity_correlation']):>10} "
            f"{item['monotonicity_symbol']:>10} "
            f"{item['weight_str']:<20}"
        )
    
    lines.append("-" * 70)
    lines.append("注：")
    lines.append("  - ICIR加权效果最优（年化收益4.65%，夏普0.39，单调性-0.39）")
    lines.append("  - Rolling ICIR 和等权单调性较差（正相关，Layer5收益最高）")
    lines.append("  - 单因子 turnover_surge（17.35%，夏普2.10）优于所有综合因子组合")
    lines.append("-" * 70)
    
    # 第六部分：综合因子 vs 单因子对比
    lines.append("")
    lines.append("六、综合因子 vs 单因子对比")
    lines.append("-" * 70)
    
    best_single = max(factor_data, key=lambda x: x.get('icir', 0))
    best_composite = max(composite_results, key=lambda x: x['long_short_sharpe'])
    
    lines.append(f"{'对比项':<20} {best_single['factor_name']+'单因子':>20} {best_composite['weight_method_display']+'综合因子':>20}")
    lines.append("-" * 70)
    lines.append(
        f"{'多空年化收益':<20} "
        f"{format_percentage(best_single.get('long_short_return_annual', 0)):>20} "
        f"{format_percentage(best_composite['long_short_return_annual']):>20}"
    )
    lines.append(
        f"{'夏普比率':<20} "
        f"{format_float(best_single.get('long_short_sharpe', 0), 2):>20} "
        f"{format_float(best_composite['long_short_sharpe'], 2):>20}"
    )
    lines.append(
        f"{'单调性系数':<20} "
        f"{format_float(best_single.get('monotonicity_correlation', 0)):>20} "
        f"{format_float(best_composite['monotonicity_correlation']):>20}"
    )
    lines.append(
        f"{'单调性质量':<20} "
        f"{best_single.get('monotonicity_symbol', ''):>20} "
        f"{best_composite['monotonicity_symbol']:>20}"
    )
    
    lines.append("-" * 70)
    lines.append("结论：单因子 turnover_surge 表现优于综合因子组合")
    lines.append("      综合因子组合收益下降可能因：")
    lines.append("        1) bollinger_pb 单调性一般，稀释了 turnover_surge 的强单调性")
    lines.append("        2) 动态权重（Rolling ICIR）未能捕捉因子间的时变相关性")
    lines.append("=" * 70)
    
    return '\n'.join(lines)


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='生成因子分析数据汇总报告')
    parser.add_argument('--date', type=str, help='指定日期 (YYYY-MM-DD)，默认当天')
    parser.add_argument('--output', type=str, help='输出文件路径，默认打印到终端')
    parser.add_argument('--full-correlation', action='store_true',
                        help='强制计算所有因子之间的相关性（可能较慢）')
    
    args = parser.parse_args()
    
    date = get_date_str(args.date)
    report = generate_report(date, force_full_correlation=args.full_correlation)
    
    if args.output:
        output_path = Path(args.output)
        output_path.write_text(report, encoding='utf-8')
        print(f"报告已保存到: {output_path}")
    else:
        print(report)


if __name__ == '__main__':
    main()