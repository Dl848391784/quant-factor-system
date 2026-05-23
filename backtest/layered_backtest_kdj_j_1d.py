"""
KDJ_J 因子分层回测入口脚本

功能:
1. 从缓存加载 close, high, low 价格数据
2. 实时计算 kdj_j 因子
3. 配置分层参数（反向因子）
4. 调用通用分层回测引擎
5. 输出结果到 cache/backtest/

规范:
- 命名遵循 MODULE.md: layered_backtest_<因子名>_<收益周期>.py
- 日志遵循 PROJECT.md: 使用 logging 模块
- 数据加载使用缓存，不截断

因子说明:
- KDJ_J = 3K - 2D
- J < 0: 超卖（K 和 D 都很低）
- J > 100: 超买（K 和 D 都很高）
- 反向因子：低 J 值预期高收益，高 J 值预期低收益

作者: 云瑶
创建日期: 2026-05-23
"""

import os
import sys
import json
import gzip
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, Optional
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict as TypingDict

# 导入公共日志模块
from factor_ic.common.logger_config import get_logger

logger = get_logger(__name__)

# 导入公共类型转换模块
from factor_ic.common.convert_types import convert_to_native_types

from backtest.common.layered_backtest import LayeredBacktestEngine


# KDJ 参数
DEFAULT_N = 9   # RSV 计算周期
DEFAULT_M1 = 3  # K值平滑周期
DEFAULT_M2 = 3  # D值平滑周期


@dataclass
class KDJJLayerConfig:
    """KDJ_J分层配置"""
    
    # 固定阈值分层（基于 J 值实际数据范围）
    # J = 3K - 2D，范围 -30 ~ 130（实测数据）
    # 5层划分：超卖、偏下、中性、偏上、超买
    layer_thresholds: List[float] = field(default_factory=lambda: [-30, 0, 20, 80, 100, 130])
    
    # 分层命名
    layer_names: TypingDict[str, str] = field(default_factory=lambda: {
        '1': '超卖层(J<0)',
        '2': '偏下层(0≤J<20)',
        '3': '中性层(20≤J<80)',
        '4': '偏上层(80≤J<100)',
        '5': '超买层(J≥100)'
    })
    
    # 因子方向（反向因子）
    factor_direction: str = 'negative'
    
    # 多空组合（反向因子：买超卖、卖超买）
    long_layers: List[int] = field(default_factory=lambda: [1, 2])
    short_layers: List[int] = field(default_factory=lambda: [4, 5])
    
    # 阈值说明
    layer_threshold_desc: TypingDict[str, str] = field(default_factory=lambda: {
        '1': 'J < 0 (超卖，含越界值)',
        '2': '0 ≤ J < 20 (偏下)',
        '3': '20 ≤ J < 80 (中性区间)',
        '4': '80 ≤ J < 100 (偏上)',
        '5': 'J ≥ 100 (超买，含越界值)'
    })
    
    # 交易成本
    trade_cost_rate: float = 0.003
    
    # 最小股票数
    min_stocks_per_layer: int = 10
    
    # KDJ 参数
    kdj_n: int = DEFAULT_N
    kdj_m1: int = DEFAULT_M1
    kdj_m2: int = DEFAULT_M2
    
    @property
    def LAYER_THRESHOLDS(self) -> List[float]:
        return self.layer_thresholds
    
    @property
    def LAYER_NAMES(self) -> TypingDict[str, str]:
        return self.layer_names
    
    @property
    def FACTOR_DIRECTION(self) -> str:
        return self.factor_direction
    
    @property
    def LONG_LAYERS(self) -> List[int]:
        return self.long_layers
    
    @property
    def SHORT_LAYERS(self) -> List[int]:
        return self.short_layers
    
    @property
    def LAYER_THRESHOLD_DESC(self) -> TypingDict[str, str]:
        return self.layer_threshold_desc
    
    @property
    def TRADE_COST_RATE(self) -> float:
        return self.trade_cost_rate
    
    @property
    def MIN_STOCKS_PER_LAYER(self) -> int:
        return self.min_stocks_per_layer
    
    @property
    def KDJ_N(self) -> int:
        return self.kdj_n
    
    @property
    def KDJ_M1(self) -> int:
        return self.kdj_m1
    
    @property
    def KDJ_M2(self) -> int:
        return self.kdj_m2


def calculate_kdj_j(
    factor_df: pd.DataFrame,
    n: int = DEFAULT_N,
    m1: int = DEFAULT_M1,
    m2: int = DEFAULT_M2
) -> pd.DataFrame:
    """
    计算 KDJ_J 因子
    
    参数:
        factor_df: 包含 close, high, low, date, asset 列的 DataFrame
        n: RSV 计算周期（默认9）
        m1: K值平滑周期（默认3）
        m2: D值平滑周期（默认3）
    
    返回:
        包含 kdj_j 列的 DataFrame
    
    计算公式:
        RSV = (Close - LowN) / (HighN - LowN) * 100
        K = EMA(RSV, m1)  （首次用50）
        D = EMA(K, m2)    （首次用50）
        J = 3K - 2D
    
    注意:
        1. 函数入口先 .copy()
        2. KDJ 是单股票时序指标，必须按 asset 分组
        3. rolling/ewm 计算前必须排序
        4. min_periods=n，前 n-1 天为 NaN
    """
    df = factor_df.copy()
    
    # 按 asset+date 排序，确保时序正确
    df = df.sort_values(['asset', 'date'])
    
    # 计算 RSV（未成熟随机值）
    # LowN = n日最低价，HighN = n日最高价
    df['low_n'] = df.groupby('asset')['low'].transform(
        lambda x: x.rolling(window=n, min_periods=n).min()
    )
    df['high_n'] = df.groupby('asset')['high'].transform(
        lambda x: x.rolling(window=n, min_periods=n).max()
    )
    
    # RSV = (Close - LowN) / (HighN - LowN) * 100
    # 防止除零
    range_val = df['high_n'] - df['low_n']
    df['rsv'] = np.where(
        range_val > 0,
        (df['close'] - df['low_n']) / range_val * 100,
        50.0  # 默认值（价格区间为0时）
    )
    
    # 计算 K（使用 EWM，alpha = 1/m1）
    # K = K(t-1) * (1 - alpha) + RSV(t) * alpha
    # 初始值：第一个有效 RSV 之前，K=50（虚拟初始值）
    alpha_k = 1.0 / m1
    
    def calc_k_with_initial(rsv_series):
        """计算 K，使用虚拟初始值 50"""
        # 使用 ewm 计算，adjust=False
        k = rsv_series.ewm(alpha=alpha_k, adjust=False).mean()
        # ewm 默认用第一个值作为初始值，不符合 KDJ 定义
        # 需要在第一个有效 RSV 前插入虚拟初始值 50
        # 使用修正：第一个有效值开始计算
        first_valid_idx = rsv_series.first_valid_index()
        if first_valid_idx is not None:
            # 创建扩展序列，在第一个有效值前插入 50
            rsv_expanded = rsv_series.copy()
            rsv_expanded.loc[:first_valid_idx] = rsv_expanded.loc[:first_valid_idx].fillna(50)
            k = rsv_expanded.ewm(alpha=alpha_k, adjust=False).mean()
        return k
    
    df['k'] = df.groupby('asset')['rsv'].transform(calc_k_with_initial)
    
    # 计算 D（使用 EWM，alpha = 1/m2）
    alpha_d = 1.0 / m2
    
    def calc_d_with_initial(k_series):
        """计算 D，使用虚拟初始值 50"""
        first_valid_idx = k_series.first_valid_index()
        if first_valid_idx is not None:
            k_expanded = k_series.copy()
            k_expanded.loc[:first_valid_idx] = k_expanded.loc[:first_valid_idx].fillna(50)
            d = k_expanded.ewm(alpha=alpha_d, adjust=False).mean()
            return d
        return k_series.ewm(alpha=alpha_d, adjust=False).mean()
    
    df['d'] = df.groupby('asset')['k'].transform(calc_d_with_initial)
    
    # 计算 J = 3K - 2D
    df['kdj_j'] = 3 * df['k'] - 2 * df['d']
    
    # 清理中间列
    df.drop(columns=['low_n', 'high_n', 'rsv', 'k', 'd'], inplace=True, errors='ignore')
    
    return df


def load_data_from_cache(
    cache_dir: Optional[str] = None
) -> tuple:
    """从缓存加载因子和收益数据"""
    if cache_dir is None:
        project_root = Path(__file__).parent.parent
        cache_dir = project_root / 'cache' / 'factor_data'
    
    factor_path = Path(cache_dir) / 'factor_data.json.gz'
    logger.info("加载因子数据: %s", factor_path)
    
    if not factor_path.exists():
        raise FileNotFoundError(f"因子数据缓存文件不存在: {factor_path}")
    
    try:
        with gzip.open(factor_path, 'rt', encoding='utf-8') as f:
            factor_data = json.load(f)
    except json.JSONDecodeError as e:
        raise json.JSONDecodeError(
            f"因子数据 JSON 解析失败: {factor_path}, 错误: {e.msg}",
            e.doc, e.pos
        )
    
    if 'data' not in factor_data:
        raise KeyError(
            f"因子数据 JSON 结构缺失 'data' 字段: {factor_path}, "
            f"顶层字段: {list(factor_data.keys())}"
        )
    
    factor_df = pd.DataFrame(factor_data['data'])
    logger.info("因子数据: %d 条记录", len(factor_df))
    
    return_path = Path(cache_dir) / 'return_data.json.gz'
    logger.info("加载收益数据: %s", return_path)
    
    if not return_path.exists():
        raise FileNotFoundError(f"收益数据缓存文件不存在: {return_path}")
    
    try:
        with gzip.open(return_path, 'rt', encoding='utf-8') as f:
            return_data = json.load(f)
    except json.JSONDecodeError as e:
        raise json.JSONDecodeError(
            f"收益数据 JSON 解析失败: {return_path}, 错误: {e.msg}",
            e.doc, e.pos
        )
    
    if 'data' not in return_data:
        raise KeyError(
            f"收益数据 JSON 结构缺失 'data' 字段: {return_path}, "
            f"顶层字段: {list(return_data.keys())}"
        )
    
    return_df = pd.DataFrame(return_data['data'])
    logger.info("收益数据: %d 条记录", len(return_df))
    
    return factor_df, return_df


def run_kdj_j_layered_backtest(
    output_dir: str = None,
    verbose: bool = True
) -> Dict:
    """KDJ_J分层回测入口函数"""
    logger.info("=" * 40)
    logger.info("KDJ_J 分层回测")
    logger.info("=" * 40)
    
    config = KDJJLayerConfig()
    
    if verbose:
        logger.info("配置信息:")
        logger.info("  分层阈值: %s", config.LAYER_THRESHOLDS)
        logger.info("  因子方向: %s", config.FACTOR_DIRECTION)
        logger.info("  多头组合: Layer %s", config.LONG_LAYERS)
        logger.info("  空头组合: Layer %s", config.SHORT_LAYERS)
        logger.info("  KDJ参数: N=%d, M1=%d, M2=%d", config.KDJ_N, config.KDJ_M1, config.KDJ_M2)
        logger.info("  最小股票数: %d", config.MIN_STOCKS_PER_LAYER)
        logger.info("  交易成本率: %.2f%%", config.TRADE_COST_RATE * 100)
    
    factor_df, return_df = load_data_from_cache()
    
    # 检查数据
    required_cols = ['close', 'high', 'low']
    for col in required_cols:
        if col not in factor_df.columns:
            raise ValueError(f"因子数据中缺少 {col} 列")
    
    if 'forward_return_1d' not in return_df.columns:
        raise ValueError("收益数据中缺少 forward_return_1d 列")
    
    # 计算 KDJ_J 因子
    logger.info("计算 KDJ_J 因子...")
    factor_df = calculate_kdj_j(
        factor_df,
        n=config.KDJ_N,
        m1=config.KDJ_M1,
        m2=config.KDJ_M2
    )
    
    if verbose:
        logger.info("数据统计:")
        logger.info("  日期范围: %s ~ %s", factor_df['date'].min(), factor_df['date'].max())
        logger.info("  股票数量: %d", factor_df['asset'].nunique())
        logger.info("  KDJ_J 范围: %.2f ~ %.2f", 
                    factor_df['kdj_j'].min(), factor_df['kdj_j'].max())
        logger.info("  KDJ_J 均值: %.2f", factor_df['kdj_j'].mean())
    
    # 验证因子范围
    j_min = factor_df['kdj_j'].min()
    j_max = factor_df['kdj_j'].max()
    thresholds = config.LAYER_THRESHOLDS
    
    if j_min < thresholds[0] or j_max > thresholds[-1]:
        logger.warning(
            "因子值超出 thresholds 范围: %.2f ~ %.2f, thresholds: %s",
            j_min, j_max, thresholds
        )
    
    # 创建回测引擎
    logger.info("创建回测引擎...")
    engine = LayeredBacktestEngine(
        factor_df=factor_df,
        return_df=return_df,
        factor_col='kdj_j',
        return_col='forward_return_1d',
        date_col='date',
        asset_col='asset'
    )
    
    logger.info("执行分层回测...")
    n_layers = len(config.LAYER_THRESHOLDS) - 1
    
    result = engine.run(
        layer_method='fixed_threshold',
        thresholds=config.LAYER_THRESHOLDS,
        n_layers=n_layers,
        factor_direction=config.FACTOR_DIRECTION,
        long_layers=config.LONG_LAYERS,
        short_layers=config.SHORT_LAYERS,
        min_stocks_per_layer=config.MIN_STOCKS_PER_LAYER,
        trade_cost_rate=config.TRADE_COST_RATE
    )
    
    # 添加因子特定信息
    result['meta']['factor_name'] = 'kdj_j'
    result['meta']['layer_names'] = config.LAYER_NAMES
    result['meta']['layer_thresholds_desc'] = config.LAYER_THRESHOLD_DESC
    result['meta']['kdj_params'] = {
        'n': config.KDJ_N,
        'm1': config.KDJ_M1,
        'm2': config.KDJ_M2
    }
    
    report = engine.generate_report(result)
    logger.info(report)
    
    logger.info("=" * 40)
    logger.info("KDJ_J 分层说明")
    logger.info("=" * 40)
    for layer_id in range(1, n_layers + 1):
        layer_key = str(layer_id)
        name = config.LAYER_NAMES.get(layer_key, f'Layer{layer_id}')
        desc = config.LAYER_THRESHOLD_DESC.get(layer_key, '')
        logger.info("  Layer%d (%s): %s", layer_id, name, desc)
    
    # 保存结果
    if output_dir is None:
        project_root = Path(__file__).parent.parent
        output_dir = project_root / 'cache' / 'backtest'
    
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    output_file = Path(output_dir) / 'kdj_j_layered_backtest.json'
    
    output_data = {
        'meta': result['meta'],
        'layer_stats': result['layer_stats'],
        'long_short': result['long_short'],
        'monotonicity': result['monotonicity'],
        'trading_cost_analysis': result['trading_cost_analysis'],
        'config': {
            'layer_thresholds': config.LAYER_THRESHOLDS,
            'layer_names': config.LAYER_NAMES,
            'factor_direction': config.FACTOR_DIRECTION,
            'long_layers': config.LONG_LAYERS,
            'short_layers': config.SHORT_LAYERS,
            'trade_cost_rate': config.TRADE_COST_RATE,
            'min_stocks_per_layer': config.MIN_STOCKS_PER_LAYER,
            'kdj_n': config.KDJ_N,
            'kdj_m1': config.KDJ_M1,
            'kdj_m2': config.KDJ_M2
        },
        'created_at': datetime.now().isoformat()
    }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(convert_to_native_types(output_data), f, indent=2, ensure_ascii=False)
    
    logger.info("结果已保存: %s", output_file)
    
    # 保存每日明细
    daily_file = Path(output_dir) / 'kdj_j_layered_backtest_daily.json.gz'
    daily_data = {
        'meta': {
            'n_days': result['meta']['n_days_total'],
            'columns': ['date', 'layer', 'n_stocks', 'return', 'turnover']
        },
        'data': result['daily_records']
    }
    
    with gzip.open(daily_file, 'wt', encoding='utf-8') as f:
        json.dump(convert_to_native_types(daily_data), f, indent=2, ensure_ascii=False)
    
    logger.info("每日明细已保存: %s", daily_file)
    
    return result


def main():
    """命令行入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description='KDJ_J分层回测')
    parser.add_argument('--output_dir', type=str, default=None)
    parser.add_argument('--quiet', action='store_true')
    
    args = parser.parse_args()
    
    try:
        result = run_kdj_j_layered_backtest(
            output_dir=args.output_dir,
            verbose=not args.quiet
        )
        
        if result['meta']['n_days_total'] == 0:
            logger.error("回测无有效数据，退出码 1")
            sys.exit(1)
        
        logger.info("回测完成，退出码 0")
        sys.exit(0)
        
    except FileNotFoundError as e:
        logger.error("数据文件不存在: %s", e)
        sys.exit(2)
    except KeyError as e:
        logger.error("数据结构错误: %s", e)
        sys.exit(3)
    except ValueError as e:
        logger.error("参数错误: %s", e)
        sys.exit(4)
    except Exception as e:
        logger.exception("回测执行异常: %s", e)
        sys.exit(5)


if __name__ == '__main__':
    main()