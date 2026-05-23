"""
换手率突增因子分层回测入口脚本

功能:
1. 从缓存加载 turnover_rate, close 价格数据
2. 实时计算 turnover_surge 因子
3. 配置分层参数（反向因子）
4. 调用通用分层回测引擎
5. 输出结果到 backtest/result/

规范:
- 命名遵循 MODULE.md: layered_backtest_<因子名>_<收益周期>.py
- 输出遵循 PROJECT.md: 结果输出到 backtest/result/
- 日志遵循 PROJECT.md: 使用 logging 模块
- 数据加载使用缓存，不截断

因子说明:
- turnover_surge = 当日换手率 / 过去 N 日平均换手率（不含当日）
- surge = 1: 当日换手率等于历史均值
- surge > 1: 换手率突增
- surge < 1: 换手率低于均值
- 反向因子：高 surge 值预期低收益（短期过度交易）

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


# 换手率突增参数
DEFAULT_SURGE_WINDOW = 5  # 换手率均值计算窗口
EPSILON = 1e-10  # 除零防护阈值


@dataclass
class TurnoverSurgeLayerConfig:
    """换手率突增分层配置"""
    
    # 固定阈值分层（基于 turnover_surge 实测数据范围）
    # surge = 当日换手率 / 过去 N 日均值
    # 实测范围: 0.01 ~ 470.28
    # 5层划分：极低、偏低、正常、偏高、突增
    # 使用 log 尺度划分更合理
    layer_thresholds: List[float] = field(default_factory=lambda: [0, 0.5, 1.0, 2.0, 5.0, 500.0])
    
    # 分层命名
    layer_names: TypingDict[str, str] = field(default_factory=lambda: {
        '1': '极低层(surge<0.5)',
        '2': '偏低层(0.5≤surge<1)',
        '3': '正常层(1≤surge<1.5)',
        '4': '偏高层(1.5≤surge<2)',
        '5': '突增层(surge≥2)'
    })
    
    # 因子方向（反向因子）
    factor_direction: str = 'negative'
    
    # 多空组合（反向因子：买极低偏低、卖偏高突增）
    long_layers: List[int] = field(default_factory=lambda: [1, 2])
    short_layers: List[int] = field(default_factory=lambda: [4, 5])
    
    # 阈值说明
    layer_threshold_desc: TypingDict[str, str] = field(default_factory=lambda: {
        '1': 'surge < 0.5 (换手率远低于均值)',
        '2': '0.5 ≤ surge < 1 (换手率偏低)',
        '3': '1 ≤ surge < 2 (换手率接近均值)',
        '4': '2 ≤ surge < 5 (换手率偏高)',
        '5': 'surge ≥ 5 (换手率突增)'
    })
    
    # 交易成本
    trade_cost_rate: float = 0.003
    
    # 最小股票数
    min_stocks_per_layer: int = 10
    
    # 换手率突增参数
    surge_window: int = DEFAULT_SURGE_WINDOW
    
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
    def SURGE_WINDOW(self) -> int:
        return self.surge_window


def calculate_turnover_surge(
    factor_df: pd.DataFrame,
    surge_window: int = DEFAULT_SURGE_WINDOW
) -> pd.DataFrame:
    """
    计算换手率突增因子
    
    参数:
        factor_df: 包含 turnover_rate, close, date, asset 列的 DataFrame
        surge_window: 换手率均值计算窗口（默认5）
    
    返回:
        包含 turnover_surge 列的 DataFrame
    
    计算公式:
        avg_turnover = 过去 surge_window 日换手率均值（不含当日）
        turnover_surge = 当日换手率 / avg_turnover
    
    注意:
        1. 函数入口先 .copy()
        2. avg_turnover 不含当日，否则因子值被稀释
        3. 除零防护：avg_turnover 接近零时标记为 NaN
        4. 需要至少 surge_window + 1 天历史数据才能得到第一个有效值
    """
    df = factor_df.copy()
    
    # 按 asset+date 排序
    df = df.sort_values(['asset', 'date'])
    
    # 计算过去 N 日换手率均值（不含当日）
    # shift(1) 确保不含当日
    avg_turnover = df.groupby('asset')['turnover_rate'].transform(
        lambda x: x.shift(1).rolling(surge_window, min_periods=surge_window).mean()
    )
    
    # 除零防护：avg_turnover 接近零时标记为 NaN
    zero_avg_mask = (avg_turnover.notna()) & (avg_turnover.abs() < EPSILON)
    if zero_avg_mask.sum() > 0:
        logger.warning(
            "avg_turnover 接近零的记录数: %d (%.2f%%)，标记为 NaN",
            zero_avg_mask.sum(),
            zero_avg_mask.sum() / len(df) * 100
        )
    
    # 计算 turnover_surge
    # 当 avg_turnover 接近零或为 NaN 时，turnover_surge 设为 NaN
    safe_avg = avg_turnover.where(~zero_avg_mask, np.nan)
    df['turnover_surge'] = df['turnover_rate'] / safe_avg
    
    # 检测异常负值
    negative_mask = df['turnover_surge'] < 0
    if negative_mask.sum() > 0:
        logger.warning(
            "turnover_surge 负值记录数: %d (%.2f%%)，数据质量问题",
            negative_mask.sum(),
            negative_mask.sum() / len(df) * 100
        )
        df.loc[negative_mask, 'turnover_surge'] = np.nan
    
    return df


def load_data_from_cache(
    cache_dir: Optional[str] = None
) -> tuple:
    """从缓存加载因子和收益数据
    
    注意：换手率突增因子需要额外的 turnover_rate 数据
    """
    if cache_dir is None:
        project_root = Path(__file__).parent.parent
        cache_dir = project_root / 'cache' / 'factor_data'
    
    # 加载主因子数据
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
    
    # 加载换手率数据（额外数据源）
    turnover_path = Path(cache_dir) / 'turnover_rate_data.json.gz'
    logger.info("加载换手率数据: %s", turnover_path)
    
    if not turnover_path.exists():
        raise FileNotFoundError(
            f"换手率数据文件不存在: {turnover_path}，"
            f"换手率突增因子需要 turnover_rate 数据"
        )
    
    try:
        with gzip.open(turnover_path, 'rt', encoding='utf-8') as f:
            turnover_data = json.load(f)
    except json.JSONDecodeError as e:
        raise json.JSONDecodeError(
            f"换手率数据 JSON 解析失败: {turnover_path}, 错误: {e.msg}",
            e.doc, e.pos
        )
    
    if 'data' not in turnover_data:
        raise KeyError(
            f"换手率数据 JSON 结构缺失 'data' 字段: {turnover_path}, "
            f"顶层字段: {list(turnover_data.keys())}"
        )
    
    turnover_df = pd.DataFrame(turnover_data['data'])
    logger.info("换手率数据: %d 条记录", len(turnover_df))
    
    # 合并换手率数据到因子数据
    # 按 date + asset 合并
    if 'turnover_rate' not in turnover_df.columns:
        raise ValueError("换手率数据中缺少 turnover_rate 列")
    
    # 确保 merge key 存在
    for col in ['date', 'asset']:
        if col not in turnover_df.columns:
            raise ValueError(f"换手率数据中缺少 {col} 列")
    
    factor_df = factor_df.merge(
        turnover_df[['date', 'asset', 'turnover_rate']],
        on=['date', 'asset'],
        how='left'
    )
    logger.info("合并换手率数据后: %d 条记录", len(factor_df))
    
    # 检查必需列
    required_cols = ['turnover_rate', 'close']
    for col in required_cols:
        if col not in factor_df.columns:
            raise ValueError(f"因子数据中缺少 {col} 列")
    
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
    
    if 'forward_return_1d' not in return_df.columns:
        raise ValueError("收益数据中缺少 forward_return_1d 列")
    
    return factor_df, return_df


def run_turnover_surge_layered_backtest(
    output_dir: str = None,
    verbose: bool = True
) -> Dict:
    """换手率突增分层回测入口函数"""
    logger.info("=" * 40)
    logger.info("换手率突增分层回测")
    logger.info("=" * 40)
    
    config = TurnoverSurgeLayerConfig()
    
    if verbose:
        logger.info("配置信息:")
        logger.info("  分层阈值: %s", config.LAYER_THRESHOLDS)
        logger.info("  因子方向: %s", config.FACTOR_DIRECTION)
        logger.info("  多头组合: Layer %s", config.LONG_LAYERS)
        logger.info("  空头组合: Layer %s", config.SHORT_LAYERS)
        logger.info("  换手率突增窗口: %d", config.SURGE_WINDOW)
        logger.info("  最小股票数: %d", config.MIN_STOCKS_PER_LAYER)
        logger.info("  交易成本率: %.2f%%", config.TRADE_COST_RATE * 100)
    
    factor_df, return_df = load_data_from_cache()
    
    # 计算 turnover_surge 因子
    logger.info("计算换手率突增因子...")
    factor_df = calculate_turnover_surge(
        factor_df,
        surge_window=config.SURGE_WINDOW
    )
    
    if verbose:
        logger.info("数据统计:")
        logger.info("  日期范围: %s ~ %s", factor_df['date'].min(), factor_df['date'].max())
        logger.info("  股票数量: %d", factor_df['asset'].nunique())
        valid_surge = factor_df['turnover_surge'].dropna()
        if len(valid_surge) > 0:
            logger.info("  turnover_surge 范围: %.2f ~ %.2f", 
                        valid_surge.min(), valid_surge.max())
            logger.info("  turnover_surge 均值: %.2f", valid_surge.mean())
    
    # 验证因子范围
    surge_min = factor_df['turnover_surge'].min()
    surge_max = factor_df['turnover_surge'].max()
    thresholds = config.LAYER_THRESHOLDS
    
    if pd.notna(surge_min) and surge_min < thresholds[0]:
        logger.warning(
            "因子最小值 %.2f 低于阈值下限 %s，建议调整 thresholds",
            surge_min, thresholds[0]
        )
    
    if pd.notna(surge_max) and surge_max > thresholds[-1]:
        logger.warning(
            "因子最大值 %.2f 超出阈值上限 %s，将归入 Layer5",
            surge_max, thresholds[-1]
        )
    
    # 创建回测引擎
    logger.info("创建回测引擎...")
    engine = LayeredBacktestEngine(
        factor_df=factor_df,
        return_df=return_df,
        factor_col='turnover_surge',
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
    result['meta']['factor_name'] = 'turnover_surge'
    result['meta']['layer_names'] = config.LAYER_NAMES
    result['meta']['layer_thresholds_desc'] = config.LAYER_THRESHOLD_DESC
    result['meta']['surge_params'] = {
        'surge_window': config.SURGE_WINDOW
    }
    
    report = engine.generate_report(result)
    logger.info(report)
    
    logger.info("=" * 40)
    logger.info("换手率突增分层说明")
    logger.info("=" * 40)
    for layer_id in range(1, n_layers + 1):
        layer_key = str(layer_id)
        name = config.LAYER_NAMES.get(layer_key, f'Layer{layer_id}')
        desc = config.LAYER_THRESHOLD_DESC.get(layer_key, '')
        logger.info("  Layer%d (%s): %s", layer_id, name, desc)
    
    # 保存结果（遵循 PROJECT.md 输出目录规范）
    if output_dir is None:
        project_root = Path(__file__).parent.parent
        output_dir = project_root / 'backtest' / 'result'
    
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    output_file = Path(output_dir) / 'turnover_surge_layered_backtest.json'
    
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
            'surge_window': config.SURGE_WINDOW
        },
        'created_at': datetime.now().isoformat()
    }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(convert_to_native_types(output_data), f, indent=2, ensure_ascii=False)
    
    logger.info("结果已保存: %s", output_file)
    
    # 保存每日明细
    daily_file = Path(output_dir) / 'turnover_surge_layered_backtest_daily.json.gz'
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
    
    parser = argparse.ArgumentParser(description='换手率突增分层回测')
    parser.add_argument('--output_dir', type=str, default=None)
    parser.add_argument('--quiet', action='store_true')
    
    args = parser.parse_args()
    
    try:
        result = run_turnover_surge_layered_backtest(
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