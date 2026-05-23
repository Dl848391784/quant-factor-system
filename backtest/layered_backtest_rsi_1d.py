"""
RSI 因子分层回测入口脚本

功能:
1. 加载 RSI 因子数据
2. 配置 RSI 分层参数
3. 调用通用分层回测引擎
4. 输出结果到 cache/backtest/

规范:
- 命名遵循 MODULE.md: layered_backtest_<因子名>.py
- 日志遵循 PROJECT.md: 使用 logging 模块
- 数据加载使用缓存，不截断

作者: 云瑶
创建日期: 2026-05-11
修订日期: 2026-05-23（修复6个代码bug + 补充MODULE.md规范）
"""

import os
import sys
import json
import gzip
import pandas as pd
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


@dataclass
class RSILayerConfig:
    """RSI分层配置（使用 dataclass 提供类型约束和不可变性保护）"""
    
    # 固定阈值分层（推荐）
    layer_thresholds: List[float] = field(default_factory=lambda: [0, 20, 40, 60, 80, 100])
    
    # 分层命名（使用 str key，避免 JSON 序列化后 int→str 转换问题）
    # 保存和加载时 key 类型一致，下游使用 layer_names.get('1') 返回正确值
    layer_names: TypingDict[str, str] = field(default_factory=lambda: {
        '1': '超卖层',
        '2': '弱势层', 
        '3': '中性层',
        '4': '强势层',
        '5': '超买层'
    })
    
    # 因子方向（重要：RSI是反向因子）
    factor_direction: str = 'negative'  # 反向因子
    
    # 多空组合（反向因子：买超卖、卖超买）
    long_layers: List[int] = field(default_factory=lambda: [1, 2])   # 多头：超卖+弱势（预期收益高）
    short_layers: List[int] = field(default_factory=lambda: [4, 5])  # 空头：强势+超买（预期收益低）
    
    # RSI阈值说明（边界值明确归属规则）
    # 边界值归属原则：边界值归入下一层（向上进位）
    # 格式遵循 MODULE.md "阈值描述规范": 完整区间 [lower, upper)
    # 第5层特殊处理：RSI ≥ 80 归入 Layer5（含 RSI >= 100 的越界值）
    # 使用 str key，与 layer_names 保持一致
    layer_threshold_desc: TypingDict[str, str] = field(default_factory=lambda: {
        '1': '0 ≤ RSI < 20 (超卖)',
        '2': '20 ≤ RSI < 40 (含边界20)',
        '3': '40 ≤ RSI < 60 (含边界40)',
        '4': '60 ≤ RSI < 80 (含边界60)',
        '5': 'RSI ≥ 80 (含边界80，含越界值)'
    })
    
    # 交易成本
    trade_cost_rate: float = 0.003  # 单边千分之三
    
    # 最小股票数
    min_stocks_per_layer: int = 10
    
    # 允许类属性访问（兼容旧代码）
    # 使用 property 或 __getattr__ 提供类属性风格的访问
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
        # 使用 Path 解析项目根目录（语义清晰，不依赖文件层级假设）
        # Path(__file__).parent = backtest/，.parent.parent = 项目根目录
        project_root = Path(__file__).parent.parent
        cache_dir = project_root / 'cache' / 'factor_data'
    
    # 加载因子数据
    factor_path = Path(cache_dir) / 'factor_data.json.gz'
    logger.info("加载因子数据: %s", factor_path)
    
    # 校验文件存在
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
    
    # 校验 JSON 结构完整性（遵循 MODULE.md 数据完整性校验规范）
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
    
    # 校验文件存在
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
    
    # 校验 JSON 结构完整性
    if 'data' not in return_data:
        raise KeyError(
            f"收益数据 JSON 结构缺失 'data' 字段: {return_path}, "
            f"顶层字段: {list(return_data.keys())}"
        )
    
    return_df = pd.DataFrame(return_data['data'])
    logger.info("收益数据: %d 条记录", len(return_df))
    logger.debug("收益列: %s", list(return_df.columns))
    
    # 使用缓存全部日期（不截断）
    
    return factor_df, return_df


def run_rsi_layered_backtest(
    output_dir: str = None,
    verbose: bool = True
) -> Dict:
    """
    RSI分层回测入口函数
    
    参数:
        output_dir: 输出目录，默认 cache/backtest/
        verbose: 是否打印详细日志
    
    返回:
        回测结果字典
    
    规范:
        使用缓存全部日期数据，不截断
    """
    logger.info("=" * 40)
    logger.info("RSI 分层回测")
    logger.info("=" * 40)
    
    # 配置
    config = RSILayerConfig()
    
    if verbose:
        logger.info("配置信息:")
        logger.info("  分层阈值: %s", config.LAYER_THRESHOLDS)
        logger.info("  因子方向: %s", config.FACTOR_DIRECTION)
        logger.info("  多头组合: Layer %s", config.LONG_LAYERS)
        logger.info("  空头组合: Layer %s", config.SHORT_LAYERS)
        logger.info("  最小股票数: %d", config.MIN_STOCKS_PER_LAYER)
        logger.info("  交易成本率: %.2f%%", config.TRADE_COST_RATE * 100)
    
    # 加载数据
    factor_df, return_df = load_data_from_cache()
    
    # 检查数据
    if 'rsi_6' not in factor_df.columns:
        raise ValueError("因子数据中缺少 rsi_6 列")
    
    if 'forward_return_1d' not in return_df.columns:
        raise ValueError("收益数据中缺少 forward_return_1d 列")
    
    # 打印数据统计
    if verbose:
        logger.info("数据统计:")
        logger.info("  日期范围: %s ~ %s", factor_df['date'].min(), factor_df['date'].max())
        logger.info("  股票数量: %d", factor_df['asset'].nunique())
        logger.info("  RSI 范围: %.2f ~ %.2f", factor_df['rsi_6'].min(), factor_df['rsi_6'].max())
        logger.info("  RSI 均值: %.2f", factor_df['rsi_6'].mean())
        logger.info("  收益范围: %.4f ~ %.4f", return_df['forward_return_1d'].min(), return_df['forward_return_1d'].max())
    
    # 创建回测引擎
    logger.info("创建回测引擎...")
    engine = LayeredBacktestEngine(
        factor_df=factor_df,
        return_df=return_df,
        factor_col='rsi_6',
        return_col='forward_return_1d',
        date_col='date',
        asset_col='asset'
    )
    
    # 执行回测（显式传入 n_layers，遵循 MODULE.md 参数显式规范）
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
    
    # 添加RSI特定信息
    # 使用 str key，与 config.layer_names 保持一致（避免 JSON 序列化 int→str 转换问题）
    result['meta']['factor_name'] = 'rsi_6'
    result['meta']['layer_names'] = config.LAYER_NAMES  # str key
    result['meta']['layer_thresholds_desc'] = config.LAYER_THRESHOLD_DESC  # str key
    
    # 生成报告
    report = engine.generate_report(result)
    logger.info(report)
    
    # 输出RSI特有信息
    logger.info("=" * 40)
    logger.info("RSI 分层说明")
    logger.info("=" * 40)
    # 使用 str key 访问（与 dataclass 定义一致）
    for layer_id in range(1, n_layers + 1):
        layer_key = str(layer_id)
        name = config.LAYER_NAMES.get(layer_key, f'Layer{layer_id}')
        desc = config.LAYER_THRESHOLD_DESC.get(layer_key, '')
        logger.info("  Layer%d (%s): %s", layer_id, name, desc)
    
    # 保存结果
    if output_dir is None:
        # 使用 Path 解析项目根目录（语义清晰）
        project_root = Path(__file__).parent.parent
        output_dir = project_root / 'cache' / 'backtest'
    
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    # 保存完整结果
    output_file = Path(output_dir) / 'rsi_layered_backtest.json'
    
    # 准备输出数据（不包含daily_records以减少文件大小）
    # 使用 str key 的 layer_names，避免 JSON 序列化后 int→str 转换问题
    output_data = {
        'meta': result['meta'],
        'layer_stats': result['layer_stats'],
        'long_short': result['long_short'],
        'monotonicity': result['monotonicity'],
        'trading_cost_analysis': result['trading_cost_analysis'],
        'config': {
            'layer_thresholds': config.LAYER_THRESHOLDS,
            'layer_names': config.LAYER_NAMES,  # str key
            'factor_direction': config.FACTOR_DIRECTION,
            'long_layers': config.LONG_LAYERS,
            'short_layers': config.SHORT_LAYERS,
            'trade_cost_rate': config.TRADE_COST_RATE,
            'min_stocks_per_layer': config.MIN_STOCKS_PER_LAYER
        },
        'created_at': datetime.now().isoformat()
    }
    
    # 使用公共模块转换 numpy/pandas 类型（遵循 PROJECT.md 强制复用规范）
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(convert_to_native_types(output_data), f, indent=2, ensure_ascii=False)
    
    logger.info("结果已保存: %s", output_file)
    
    # 保存每日明细（压缩）
    # 使用引擎返回的 n_days_total，避免低效 set 计算
    daily_file = Path(output_dir) / 'rsi_layered_backtest_daily.json.gz'
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
    
    parser = argparse.ArgumentParser(description='RSI分层回测')
    parser.add_argument('--output_dir', type=str, default=None, help='输出目录')
    parser.add_argument('--quiet', action='store_true', help='安静模式')
    
    args = parser.parse_args()
    
    try:
        result = run_rsi_layered_backtest(
            output_dir=args.output_dir,
            verbose=not args.quiet
        )
        
        # 检查结果有效性
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