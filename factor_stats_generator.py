#!/usr/bin/env python3
"""
因子分析统计文案生成器
作者: 云舟
功能: 将单个因子的预计算分析结果整合为结构化文案，支持多因子汇总
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple


# 因子名称映射
FACTOR_NAME_MAP = {
    'rsi': {
        'cn_name': 'RSI(6)',
        'full_name': 'RSI(6)（相对强弱指数）',
        'file': 'factor_analysis_result.json'
    },
    'kdj_j': {
        'cn_name': 'KDJ_J',
        'full_name': 'KDJ_J（随机指标J值）',
        'file': 'kdj_j_analysis_result.json'
    },
    'bollinger_pb': {
        'cn_name': '布林带%B',
        'full_name': '布林带%B（布林带百分比）',
        'file': 'bollinger_pb_analysis_result.json'
    },
    'volume_ratio': {
        'cn_name': '量比',
        'full_name': '量比（成交量比率）',
        'file': 'volume_ratio_analysis_result.json'
    },
    'return_3d': {
        'cn_name': '3日涨幅',
        'full_name': '3日涨幅（三日收益率）',
        'file': 'return_3d_analysis_result.json'
    },
    'turnover_surge': {
        'cn_name': '换手率突增',
        'full_name': '换手率突增（换手率异常）',
        'file': 'turnover_surge_analysis_result.json'
    }
}

# 因子顺序（用于汇总）
FACTOR_ORDER = ['rsi', 'kdj_j', 'bollinger_pb', 'volume_ratio', 'return_3d', 'turnover_surge']


def load_factor_data(factor_name: str, base_dir: Path = None) -> Optional[Dict[str, Any]]:
    """
    加载因子分析结果数据
    
    Args:
        factor_name: 因子标识符（如 'rsi', 'kdj_j'）
        base_dir: 基础目录，默认为当前文件所在目录
        
    Returns:
        dict: 因子分析结果，若不存在返回 None
    """
    if base_dir is None:
        base_dir = Path(__file__).parent
    
    if factor_name not in FACTOR_NAME_MAP:
        return None
    
    file_path = base_dir / FACTOR_NAME_MAP[factor_name]['file']
    
    if not file_path.exists():
        return None
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"Error loading factor data for {factor_name}: {e}")
        return None


def generate_summary_text(icir: float, long_short_sharpe: float, 
                          monotonicity_passed: bool) -> str:
    """
    根据因子数据生成综合评价文案
    
    Args:
        icir: ICIR 值
        long_short_sharpe: 多空组合夏普比率
        monotonicity_passed: 单调性检验是否通过
        
    Returns:
        str: 综合评价文案
    """
    # ICIR 预测能力评价
    if icir > 0.3:
        icir_desc = "ICIR较高，预测能力强"
    elif icir >= 0.1:
        icir_desc = "ICIR中等，预测能力中等"
    else:
        icir_desc = "IC预测能力较弱"
    
    # 多空收益能力评价
    if long_short_sharpe > 0.5:
        sharpe_desc = "多空收益能力强"
    elif long_short_sharpe > 0.3:
        sharpe_desc = "多空收益能力中等"
    elif long_short_sharpe > 0:
        sharpe_desc = "多空收益能力较弱"
    else:
        sharpe_desc = "多空收益为负"
    
    # 单调性描述
    mono_desc = "分层收益呈现单调性" if monotonicity_passed else "分层收益单调性不显著"
    
    # 综合评价
    if monotonicity_passed and long_short_sharpe > 0.3 and icir >= 0.05:
        overall = "因子有效性较强"
    elif monotonicity_passed or long_short_sharpe > 0.3:
        overall = "因子有效性中等"
    elif icir < 0.05 and long_short_sharpe < 0.1:
        overall = "因子有效性较弱"
    else:
        overall = "因子有效性一般"
    
    return f"{icir_desc}，{mono_desc}，多空组合夏普{long_short_sharpe:.2f}，{overall}。"


def generate_single_factor_stats(factor_name: str, base_dir: Path = None) -> Tuple[str, bool]:
    """
    生成单个因子的统计文案
    
    Args:
        factor_name: 因子标识符
        base_dir: 基础目录
        
    Returns:
        tuple: (文案文本, 是否成功)
    """
    if factor_name not in FACTOR_NAME_MAP:
        return f"错误：因子 '{factor_name}' 不存在。可用因子: {', '.join(FACTOR_ORDER)}", False
    
    data = load_factor_data(factor_name, base_dir)
    if data is None:
        return f"错误：因子 '{factor_name}' 的分析数据不存在或无法读取。", False
    
    factor_info = FACTOR_NAME_MAP[factor_name]
    full_name = factor_info['full_name']
    
    # 提取 IC 指标
    ic_metrics = data.get('ic_metrics', {})
    ic_mean = ic_metrics.get('ic_mean', 0)
    ic_std = ic_metrics.get('ic_std', 0)
    icir = ic_metrics.get('icir', 0)
    t_stat = ic_metrics.get('t_stat', 0)
    positive_ratio = ic_metrics.get('positive_ratio', 0)
    n_days = ic_metrics.get('n_days', 0)
    n_assets = ic_metrics.get('n_assets', 0)
    
    # 提取分层回测数据
    layered_result = data.get('layered_result', {})
    statistics = layered_result.get('statistics', [])
    summary = layered_result.get('summary', {})
    
    long_short_sharpe = summary.get('long_short_sharpe', 0)
    long_short_return = summary.get('long_short_annual_return', 0)
    monotonicity_passed = summary.get('monotonicity_passed', False)
    
    # 构建文案
    lines = []
    lines.append(f"【因子分析统计】{full_name}")
    lines.append("")
    
    # IC 分析部分
    lines.append("━━━ IC 分析 ━━━")
    lines.append(f"• IC均值：{ic_mean:.4f}")
    lines.append(f"• IC标准差：{ic_std:.4f}")
    lines.append(f"• ICIR：{icir:.2f}")
    lines.append(f"• t统计量：{t_stat:.2f}")
    lines.append(f"• 正IC比例：{positive_ratio * 100:.1f}%")
    lines.append(f"• 样本：{n_days}天 × {n_assets}只股票")
    lines.append("")
    
    # 分层回测部分
    lines.append("━━━ 分层回测 ━━━")
    lines.append("| 层级 | 年化收益 | 夏普比率 |")
    lines.append("|------|----------|----------|")
    
    # 层级名称映射
    layer_name_map = {
        'layer_1': 'L1(低)',
        'layer_2': 'L2',
        'layer_3': 'L3',
        'layer_4': 'L4',
        'layer_5': 'L5(高)',
        'long_short': '多空'
    }
    
    for stat in statistics:
        layer = stat.get('layer', '')
        layer_display = layer_name_map.get(layer, layer)
        annual_return = stat.get('annual_return', 0)
        sharpe = stat.get('sharpe', 0)
        
        # 年化收益转换为百分比
        return_pct = annual_return * 100
        lines.append(f"| {layer_display} | {return_pct:+.2f}% | {sharpe:.2f} |")
    
    lines.append("")
    
    # 单调性检验
    lines.append("━━━ 单调性检验 ━━━")
    mono_symbol = "✓" if monotonicity_passed else "✗"
    lines.append(f"• 结果：{'通过' if monotonicity_passed else '未通过'} {mono_symbol}")
    lines.append("")
    
    # 综合评价
    lines.append("━━━ 综合评价 ━━━")
    summary_text = generate_summary_text(icir, long_short_sharpe, monotonicity_passed)
    lines.append(summary_text)
    
    return "\n".join(lines), True


def generate_all_factors_summary(base_dir: Path = None) -> str:
    """
    生成所有因子的汇总文案
    
    Args:
        base_dir: 基础目录
        
    Returns:
        str: 汇总文案
    """
    lines = []
    today = datetime.now().strftime('%Y-%m-%d')
    lines.append(f"【因子分析汇总】{today}")
    lines.append("")
    
    # 统计有效因子数
    valid_factors = []
    
    for factor_name in FACTOR_ORDER:
        data = load_factor_data(factor_name, base_dir)
        if data is None:
            continue
        
        factor_info = FACTOR_NAME_MAP[factor_name]
        cn_name = factor_info['cn_name']
        
        ic_metrics = data.get('ic_metrics', {})
        layered_result = data.get('layered_result', {})
        summary = layered_result.get('summary', {})
        
        icir = ic_metrics.get('icir', 0)
        long_short_sharpe = summary.get('long_short_sharpe', 0)
        monotonicity_passed = summary.get('monotonicity_passed', False)
        
        mono_symbol = "✓" if monotonicity_passed else "✗"
        
        valid_factors.append({
            'name': factor_name,
            'cn_name': cn_name,
            'icir': icir,
            'sharpe': long_short_sharpe,
            'mono_passed': monotonicity_passed,
            'display': f"{cn_name}: ICIR={icir:.2f}, 多空夏普={long_short_sharpe:.2f}, 单调性{mono_symbol}"
        })
    
    lines.append(f"共分析 {len(valid_factors)} 个因子：")
    lines.append("")
    
    # 按顺序输出每个因子
    for i, factor in enumerate(valid_factors, 1):
        lines.append(f"{i}. {factor['display']}")
    
    lines.append("")
    
    # 推荐因子
    if valid_factors:
        # 按 ICIR 排序
        sorted_by_icir = sorted(valid_factors, key=lambda x: x['icir'], reverse=True)
        best_icir = sorted_by_icir[0]
        
        # 按多空夏普排序
        sorted_by_sharpe = sorted(valid_factors, key=lambda x: x['sharpe'], reverse=True)
        best_sharpe = sorted_by_sharpe[0]
        
        # 综合推荐（优先 ICIR，其次夏普）
        if best_icir['icir'] >= 0.1 and best_icir['mono_passed']:
            lines.append(f"推荐因子：{best_icir['cn_name']}（ICIR最高，单调性通过）")
        elif best_sharpe['sharpe'] > 0.3:
            lines.append(f"推荐因子：{best_sharpe['cn_name']}（多空收益最强）")
        elif best_icir['icir'] > 0:
            lines.append(f"相对较优：{best_icir['cn_name']}（ICIR={best_icir['icir']:.2f}）")
        else:
            lines.append("注意：所有因子表现较弱，建议进一步优化或筛选。")
    
    return "\n".join(lines)


def get_factor_list() -> List[Dict[str, str]]:
    """
    获取所有可用因子列表
    
    Returns:
        list: 因子信息列表
    """
    return [
        {
            'id': factor_name,
            'cn_name': info['cn_name'],
            'full_name': info['full_name']
        }
        for factor_name, info in FACTOR_NAME_MAP.items()
    ]


# 测试入口
if __name__ == '__main__':
    print("=" * 60)
    print("因子分析统计文案生成器 - 测试")
    print("=" * 60)
    
    # 测试单个因子
    for factor_name in FACTOR_ORDER:
        print(f"\n{'=' * 60}")
        print(f"测试因子: {factor_name}")
        print("=" * 60)
        text, success = generate_single_factor_stats(factor_name)
        if success:
            print(text)
        else:
            print(f"错误: {text}")
    
    # 测试汇总
    print(f"\n{'=' * 60}")
    print("因子汇总")
    print("=" * 60)
    print(generate_all_factors_summary())