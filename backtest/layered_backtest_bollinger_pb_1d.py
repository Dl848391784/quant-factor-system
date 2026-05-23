"""
Bollinger PB 因子分层回测入口脚本

功能:
1. 从缓存加载 close 价格数据
2. 实时计算 bollinger_pb（布林带 %B）因子
3. 配置分层参数（反向因子）
4. 调用通用分层回测引擎
5. 输出结果到 cache/backtest/

规范:
- 命名遵循 MODULE.md: layered_backtest_<因子名>_<收益周期>.py
- 日志遵循 PROJECT.md: 使用 logging 模块
- 数据加载使用缓存，不截断

因子说明:
- Bollinger %B = (Price - Lower) / (Upper - Lower)
- %B < 0: 价格在下轨之下（超卖）
- %B > 1: 价格在上轨之上（超买）
- 反向因子：低 %B 预期高收益，高 %B 预期低收益

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

# 导入公共日志模块（遵循 PROJECT.md 日志规范）
from factor_ic.common.logger_config import get_logger

logger = get_logger(__name__)

# 导入公共类型转换模块（遵循 PROJECT.md 强制复用规范）
from factor_ic.common.convert_types import convert_to_native_types

from backtest.common.layered_backtest import LayeredBacktestEngine


# 布林带参数
DEFAULT_N = 20  # 移动平均周期
DEFAULT_K = 2.0  # 标差倍数


@dataclass
class BollingerPBLayerConfig:
    """Bollinger PB分层配置（使用 dataclass 提供类型约束和不可变性保护）"""
    
    # 固定阈值分层（基于 %B 理论范围）
    # %B 理论范围: -0.5 ~ 1.5（实际可能更宽）
    # 6层划分：超卖、偏下、中性、偏上、接近上轨、超买
    layer_thresholds: List[float] = field(default_factory=lambda: [-0.5, 0, 0.25, 0.5, 0.75, 1, 1.5])
    
    # 分层命名（使用 str key，避免 JSON 序列化后 int→str 转换问题）
    layer_names: TypingDict[str, str] = field(default_factory=lambda: {
        '1': '超卖层(%B<0)',
        '2': '偏下层(0≤%B<0.25)',
        '3': '中性层(0.25≤%B<0.5)',
        '4': '偏上层(0.5≤%B<0.75)',
        '5': '近上轨层(0.75≤%B<1)',
        '6': '超买层(%B≥1)'
    })
    
    # 因子方向（重要：Bollinger PB是反向因子）
    # IC结果: ic_mean = -0.04，反向因子有效
    factor_direction: str = 'negative'  # 反向因子
    
    # 多空组合（反向因子：买超卖、卖超买）
    long_layers: List[int] = field(default_factory=lambda: [1, 2])   # 多头：超卖+偏下（预期收益高）
    short_layers: List[int] = field(default_factory=lambda: [5, 6])  # 空头：近上轨+超买（预期收益低）
    
    # 阈值说明（边界值明确归属规则）
    # 边界值归属原则：边界值归入下一层（向上进位）
    # 第6层特殊处理：%B ≥ 1 归入 Layer6
    layer_threshold_desc: TypingDict[str, str] = field(default_factory=lambda: {
        '1': '%B < 0 (超卖，价格在下轨之下)',
        '2': '0 ≤ %B < 0.25 (偏下轨)',
        '3': '0.25 ≤ %B < 0.5 (中性偏下)',
        '4': '0.5 ≤ %B < 0.75 (中性偏上)',
        '5': '0.75 ≤ %B < 1 (接近上轨)',
        '6': '%B ≥ 1 (超买，价格在上轨之上，含越界值)'
    })
    
    # 交易成本
    trade_cost_rate: float = 0.003  # 单边千分之三
    
    # 最小股票数
    min_stocks_per_layer: int = 10
    
    # 布林带参数
    bollinger_n: int = DEFAULT_N
    bollinger_k: float = DEFAULT_K
    
    # 允许类属性访问（兼容旧代码）
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
    def BOLLINGER_N(self) -> int:
        return self.bollinger_n
    
    @property
    def BOLLINGER_K(self) -> float:
        return self.bollinger_k


def calculate_bollinger_pb(
    factor_df: pd.DataFrame,
    n: int = DEFAULT_N,
    k: float = DEFAULT_K
) -> pd.DataFrame:
    """
    计算布林带 %B 因子
    
    参数:
        factor_df: 包含 close、date、asset 列的 DataFrame
        n: 移动平均周期（默认20）
        k: 标差倍数（默认2）
    
    返回:
        包含 bollinger_pb 列的 DataFrame
    
    计算公式:
        Upper = MA(n) + k * Std(n)
        Lower = MA(n) - k * Std(n)
        %B = (Close - Lower) / (Upper - Lower)
    
    注意:
        1. 函数入口先 .copy()，避免修改原始数据
        2. 布林带是单只股票的时序指标，必须按 asset 分组后再做 rolling
        3. min_periods=n 确保前 n-1 天为 NaN（符合标准布林带定义）
    """
    # 入口必须 .copy()（遵循 MODULE.md 规范）
    df = factor_df.copy()
    
    # 按 asset 分组计算（布林带是单股票时序指标）
    # 使用 transform 保持原 DataFrame 结构
    df['middle_band'] = df.groupby('asset')['close'].transform(
        lambda x: x.rolling(window=n, min_periods=n).mean()
    )
    
    df['std'] = df.groupby('asset')['close'].transform(
        lambda x: x.rolling(window=n, min_periods=n).std()
    )
    
    # 计算上轨和下轨
    df['upper_band'] = df['middle_band'] + k * df['std']
    df['lower_band'] = df['middle_band'] - k * df['std']
    
    # 计算 %B = (Close - Lower) / (Upper - Lower)
    # 注意：Upper - Lower = 2 * k * Std，当 Std=0 时可能除零
    band_width = df['upper_band'] - df['lower_band']
    
    # 防止除零（band_width=0 时，价格等于中轨，%B=0.5）
    # 使用 np.where 处理，避免除零警告
    df['bollinger_pb'] = np.where(
        band_width > 0,
        (df['close'] - df['lower_band']) / band_width,
        0.5  # 中轨位置
    )
    
    # 清理中间列
    df.drop(columns=['middle_band', 'std', 'upper_band', 'lower_band', 'band_width'], 
            inplace=True, errors='ignore')
    
    return df


def load_data_from_cache(
    cache_dir: Optional[str] = None
) -> tuple:
    """
    从缓存加载因子和收益数据
    
    参数:
        cache_dir: 缓存目录，默认 cache/factor_data/
    
    返回:
        (factor_df, return_df)
    
    规范:
        加载缓存全部日期数据，不截断
        路径构造遵循 MODULE.md: 使用 Path 解析项目根目录
        数据完整性校验遵循 MODULE.md: 必须校验 JSON 结构
    
    异常:
        FileNotFoundError: 缓存文件不存在
        KeyError: JSON 结构缺失必需字段（data）
        json.JSONDecodeError: JSON 解析失败
    """
    if cache_dir is None:
        project_root = Path(__file__).parent.parent
        cache_dir = project_root / 'cache' / 'factor_data'
    
    # 加载因子数据
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
    logger.debug("因子列: %s", list(factor_df.columns))
    
    # 加载收益数据
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
    logger.debug("收益列: %s", list(return_df.columns))
    
    return factor_df, return_df


def run_bollinger_pb_layered_backtest(
    output_dir: str = None,
    verbose: bool = True
) -> Dict:
    """
    Bollinger PB分层回测入口函数
    
    参数:
        output_dir: 输出目录，默认 cache/backtest/
        verbose: 是否打印详细日志
    
    返回:
        回测结果字典
    
    规范:
        使用缓存全部日期数据，不截断
    """
    logger.info("=" * 40)
    logger.info("Bollinger PB 分层回测")
    logger.info("=" * 40)
    
    # 配置
    config = BollingerPBLayerConfig()
    
    if verbose:
        logger.info("配置信息:")
        logger.info("  分层阈值: %s", config.LAYER_THRESHOLDS)
        logger.info("  因子方向: %s", config.FACTOR_DIRECTION)
        logger.info("  多头组合: Layer %s", config.LONG_LAYERS)
        logger.info("  空头组合: Layer %s", config.SHORT_LAYERS)
        logger.info("  布林带参数: N=%d, K=%.1f", config.BOLLINGER_N, config.BOLLINGER_K)
        logger.info("  最小股票数: %d", config.MIN_STOCKS_PER_LAYER)
        logger.info("  交易成本率: %.2f%%", config.TRADE_COST_RATE * 100)
    
    # 加载基础数据（只需要 close）
    factor_df, return_df = load_data_from_cache()
    
    # 检查数据
    if 'close' not in factor_df.columns:
        raise ValueError("因子数据中缺少 close 列")
    
    if 'forward_return_1d' not in return_df.columns:
        raise ValueError("收益数据中缺少 forward_return_1d 列")
    
    # 计算 bollinger_pb 因子（实时计算）
    logger.info("计算 Bollinger PB 因子...")
    factor_df = calculate_bollinger_pb(
        factor_df,
        n=config.BOLLINGER_N,
        k=config.BOLLINGER_K
    )
    
    # 打印数据统计
    if verbose:
        logger.info("数据统计:")
        logger.info("  日期范围: %s ~ %s", factor_df['date'].min(), factor_df['date'].max())
        logger.info("  股票数量: %d", factor_df['asset'].nunique())
        logger.info("  Bollinger PB 范围: %.3f ~ %.3f", 
                    factor_df['bollinger_pb'].min(), factor_df['bollinger_pb'].max())
        logger.info("  Bollinger PB 均值: %.3f", factor_df['bollinger_pb'].mean())
        logger.info("  收益范围: %.4f ~ %.4f", 
                    return_df['forward_return_1d'].min(), return_df['forward_return_1d'].max())
    
    # 验证因子范围是否在阈值范围内
    pb_min = factor_df['bollinger_pb'].min()
    pb_max = factor_df['bollinger_pb'].max()
    thresholds = config.LAYER_THRESHOLDS
    
    if pb_min < thresholds[0] or pb_max > thresholds[-1]:
        logger.warning(
            "因子值超出 thresholds 范围: %.3f ~ %.3f, thresholds: %s, "
            "建议检查因子计算或调整 thresholds",
            pb_min, pb_max, thresholds
        )
    
    # 创建回测引擎
    logger.info("创建回测引擎...")
    engine = LayeredBacktestEngine(
        factor_df=factor_df,
        return_df=return_df,
        factor_col='bollinger_pb',
        return_col='forward_return_1d',
        date_col='date',
        asset_col='asset'
    )
    
    # 执行回测
    logger.info("执行分层回测...")
    
    n_layers = len(config.LAYER_THRESHOLDS) - 1  # fixed_threshold 模式
    
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
    result['meta']['factor_name'] = 'bollinger_pb'
    result['meta']['layer_names'] = config.LAYER_NAMES
    result['meta']['layer_thresholds_desc'] = config.LAYER_THRESHOLD_DESC
    result['meta']['bollinger_params'] = {
        'n': config.BOLLINGER_N,
        'k': config.BOLLINGER_K
    }
    
    # 生成报告
    report = engine.generate_report(result)
    logger.info(report)
    
    # 输出分层说明
    logger.info("=" * 40)
    logger.info("Bollinger PB 分层说明")
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
    
    output_file = Path(output_dir) / 'bollinger_pb_layered_backtest.json'
    
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
            'bollinger_n': config.BOLLINGER_N,
            'bollinger_k': config.BOLLINGER_K
        },
        'created_at': datetime.now().isoformat()
    }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(convert_to_native_types(output_data), f, indent=2, ensure_ascii=False)
    
    logger.info("结果已保存: %s", output_file)
    
    # 保存每日明细（压缩）
    daily_file = Path(output_dir) / 'bollinger_pb_layered_backtest_daily.json.gz'
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
    """命令行入口（遵循 MODULE.md: 捕获异常返回退出码）"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Bollinger PB分层回测')
    parser.add_argument('--output_dir', type=str, default=None, help='输出目录')
    parser.add_argument('--quiet', action='store_true', help='安静模式')
    
    args = parser.parse_args()
    
    try:
        result = run_bollinger_pb_layered_backtest(
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