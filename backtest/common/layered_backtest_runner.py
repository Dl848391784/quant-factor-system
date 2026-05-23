"""
分层回测公共入口模块

功能:
1. 提供统一的分层回测入口函数 run_layered_backtest
2. 抽象 Config 基类 LayerConfigBase
3. 抽象数据加载、回测执行、结果保存逻辑

设计参考:
- factor_ic/common/factor_ic_runner.py (run_simple_factor_ic)
- PROJECT.md 公共模块强制复用规范

使用方式:
```python
from backtest.common.layered_backtest_runner import run_layered_backtest, LayerConfigBase

# 定义因子特有 Config（继承基类）
class MyFactorLayerConfig(LayerConfigBase):
    n_layers = 5  # percentile 分层（每层20%）
    factor_direction = 'negative'
    layer_names = {
        '1': '极低层',
        '2': '偏低层',
        '3': '正常层',
        '4': '偏高层',
        '5': '极高层'
    }
    # ...

# 调用公共入口
result = run_layered_backtest(
    factor_name='my_factor',
    factor_col='my_factor_value',
    config=MyFactorLayerConfig(),
    factor_calculator=my_calculate_func,  # 可选
    additional_data_files={'turnover_rate': 'path/to/data.json.gz'},  # 可选
    logger=logger
)
```

作者: 云瑶
创建日期: 2026-05-23
"""

import os
import sys
import json
import gzip
import logging
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, Optional, Callable, List, Union, Tuple
from pathlib import Path
from dataclasses import dataclass, field
from abc import ABC, abstractmethod

# 导入公共模块
from backtest.common.logger_config import get_logger
from backtest.common.convert_types import convert_to_native_types
from backtest.common.layered_backtest import LayeredBacktestEngine


# ============================================================================
# Config 基类
# ============================================================================

@dataclass
class LayerConfigBase:
    """分层配置基类
    
    子类只需定义因子特有参数：
    - n_layers: 分层数量（默认5层，每层20%）
    - layer_names: 分层命名（业务描述）
    - factor_direction: 因子方向 ('positive' / 'negative')
    - long_layers: 多头组合
    - short_layers: 空头组合
    
    设计变更（v1.5，2026-05-23）：
    - 删除 layer_thresholds（固定阈值已废弃）
    - 新增 n_layers（percentile 分层强制参数）
    - 原因：fixed_threshold 在极端行情时分层不稳定
    """
    
    # percentile 分层参数（强制）
    n_layers: int = 5  # 默认5层，每层20%
    
    # 分层命名（业务描述，不含阈值）
    layer_names: Dict[str, str] = field(default_factory=dict)
    
    # 因子方向和多空组合
    factor_direction: str = 'negative'
    long_layers: List[int] = field(default_factory=lambda: [1, 2])
    short_layers: List[int] = field(default_factory=lambda: [4, 5])
    
    # 通用参数
    trade_cost_rate: float = 0.003
    min_stocks_per_layer: int = 10
    
    def validate(self) -> None:
        """校验配置完整性"""
        if self.n_layers < 2:
            raise ValueError(f"n_layers 至少需要 2 层，当前: {self.n_layers}")
        
        if self.factor_direction not in ['positive', 'negative']:
            raise ValueError(f"factor_direction 必须是 'positive' 或 'negative', 当前: {self.factor_direction}")
        
        if not self.long_layers or not self.short_layers:
            raise ValueError("long_layers 和 short_layers 不能为空")
        
        # 校验层编号上界（前置校验，避免错误延迟到 engine.run）
        for layer_id in self.long_layers:
            if layer_id > self.n_layers or layer_id < 1:
                raise ValueError(
                    f"long_layers 层编号 {layer_id} 越界，有效范围 [1, {self.n_layers}]"
                )
        
        for layer_id in self.short_layers:
            if layer_id > self.n_layers or layer_id < 1:
                raise ValueError(
                    f"short_layers 层编号 {layer_id} 越界，有效范围 [1, {self.n_layers}]"
                )


# ============================================================================
# 数据加载
# ============================================================================

def load_factor_return_data(
    cache_dir: Optional[str] = None,
    additional_data_files: Optional[Dict[str, str]] = None,
    required_factor_cols: Optional[List[str]] = None,
    logger: Optional[logging.Logger] = None
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """从缓存加载因子和收益数据
    
    参数:
        cache_dir: 缓存目录路径
        additional_data_files: 额外数据文件映射 {字段名: 文件路径}
        required_factor_cols: 因子数据必需字段列表
        logger: 日志对象
    
    返回:
        (factor_df, return_df)
    
    注意:
        - 遵循 PROJECT.md 数据完整性校验规范
        - 支持额外数据源合并（如 turnover_rate）
    """
    if logger is None:
        logger = get_logger(__name__)
    
    if cache_dir is None:
        # 默认缓存目录
        cache_dir = Path(__file__).parent.parent.parent / 'cache' / 'factor_data'
    
    cache_dir = Path(cache_dir)
    
    # 加载主因子数据
    factor_path = cache_dir / 'factor_data.json.gz'
    logger.info("加载因子数据: %s", factor_path)
    
    if not factor_path.exists():
        raise FileNotFoundError(f"因子数据缓存文件不存在: {factor_path}")
    
    try:
        with gzip.open(factor_path, 'rt', encoding='utf-8') as f:
            factor_data = json.load(f)
    except json.JSONDecodeError as e:
        # 不传递 e.doc（完整文档字符串），避免内存翻倍
        raise ValueError(
            f"因子数据 JSON 解析失败: {factor_path}, 位置 {e.pos}: {e.msg}"
        ) from e
    
    if 'data' not in factor_data:
        raise KeyError(
            f"因子数据 JSON 结构缺失 'data' 字段: {factor_path}, "
            f"顶层字段: {list(factor_data.keys())}"
        )
    
    factor_df = pd.DataFrame(factor_data['data'])
    logger.info("因子数据: %d 条记录", len(factor_df))
    
    # 加载额外数据源（如 turnover_rate）
    if additional_data_files:
        for col_name, file_path in additional_data_files.items():
            extra_path = Path(file_path)
            logger.info("加载额外数据 (%s): %s", col_name, extra_path)
            
            if not extra_path.exists():
                raise FileNotFoundError(f"额外数据文件不存在: {extra_path}")
            
            try:
                with gzip.open(extra_path, 'rt', encoding='utf-8') as f:
                    extra_data = json.load(f)
            except json.JSONDecodeError as e:
                # 不传递 e.doc（完整文档字符串），避免内存翻倍
                raise ValueError(
                    f"额外数据 JSON 解析失败: {extra_path}, 位置 {e.pos}: {e.msg}"
                ) from e
            
            if 'data' not in extra_data:
                raise KeyError(
                    f"额外数据 JSON 结构缺失 'data' 字段: {extra_path}, "
                    f"顶层字段: {list(extra_data.keys())}"
                )
            
            extra_df = pd.DataFrame(extra_data['data'])
            
            # 校验必需字段
            for req_col in ['date', 'asset', col_name]:
                if req_col not in extra_df.columns:
                    raise ValueError(f"额外数据中缺少 {req_col} 列")
            
            # 合并到主因子数据
            factor_df = factor_df.merge(
                extra_df[['date', 'asset', col_name]],
                on=['date', 'asset'],
                how='left'
            )
            logger.info("合并 %s 数据后: %d 条记录", col_name, len(factor_df))
    
    # 校验必需字段
    if required_factor_cols:
        for col in required_factor_cols:
            if col not in factor_df.columns:
                raise ValueError(f"因子数据中缺少 {col} 列")
    
    # 加载收益数据
    return_path = cache_dir / 'return_data.json.gz'
    logger.info("加载收益数据: %s", return_path)
    
    if not return_path.exists():
        raise FileNotFoundError(f"收益数据缓存文件不存在: {return_path}")
    
    try:
        with gzip.open(return_path, 'rt', encoding='utf-8') as f:
            return_data = json.load(f)
    except json.JSONDecodeError as e:
        # 不传递 e.doc（完整文档字符串），避免内存翻倍
        raise ValueError(
            f"收益数据 JSON 解析失败: {return_path}, 位置 {e.pos}: {e.msg}"
        ) from e
    
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


# ============================================================================
# 公共入口函数
# ============================================================================

def run_layered_backtest(
    factor_name: str,
    factor_col: str,
    config: LayerConfigBase,
    factor_calculator: Optional[Callable] = None,
    additional_data_files: Optional[Dict[str, str]] = None,
    required_factor_cols: Optional[List[str]] = None,
    cache_dir: Optional[str] = None,
    output_dir: Optional[str] = None,
    verbose: bool = True,
    logger: Optional[logging.Logger] = None
) -> Dict:
    """分层回测公共入口
    
    参数:
        factor_name: 因子名称（用于输出文件命名）
        factor_col: 因子列名（在 factor_df 中）
        config: 分层配置对象（继承 LayerConfigBase）
        factor_calculator: 因子计算函数（可选，若因子已在缓存中则不需要）
        additional_data_files: 额外数据文件映射（可选）
        required_factor_cols: 因子数据必需字段列表（可选）
        cache_dir: 缓存目录（可选，默认 cache/factor_data/）
        output_dir: 输出目录（默认 backtest/result/）
        verbose: 是否打印详细信息
        logger: 日志对象
    
    返回:
        回测结果字典
    
    使用示例:
        # 简单因子（已在缓存中）
        result = run_layered_backtest(
            factor_name='volume_ratio',
            factor_col='volume_ratio_5',
            config=VolumeRatioLayerConfig()
        )
        
        # 需要计算的因子
        result = run_layered_backtest(
            factor_name='turnover_surge',
            factor_col='turnover_surge',
            config=TurnoverSurgeLayerConfig(),
            factor_calculator=calculate_turnover_surge,
            additional_data_files={'turnover_rate': 'path/to/turnover_rate.json.gz'},
            required_factor_cols=['turnover_rate', 'close']
        )
    """
    if logger is None:
        logger = get_logger(__name__)
    
    # 校验配置
    config.validate()
    
    logger.info("=" * 40)
    logger.info("%s 分层回测", factor_name)
    logger.info("=" * 40)
    
    if verbose:
        logger.info("配置信息:")
        logger.info("  分层数量: %d (percentile)", config.n_layers)
        logger.info("  因子方向: %s", config.factor_direction)
        logger.info("  多头组合: Layer %s", config.long_layers)
        logger.info("  空头组合: Layer %s", config.short_layers)
        logger.info("  最小股票数: %d", config.min_stocks_per_layer)
        logger.info("  交易成本率: %.2f%%", config.trade_cost_rate * 100)
    
    # 加载数据（透传 cache_dir）
    factor_df, return_df = load_factor_return_data(
        cache_dir=cache_dir,
        additional_data_files=additional_data_files,
        required_factor_cols=required_factor_cols,
        logger=logger
    )
    
    # 因子计算（如果需要）
    if factor_calculator:
        logger.info("计算 %s 因子...", factor_name)
        factor_df = factor_calculator(factor_df)
    
    # 校验因子列存在
    if factor_col not in factor_df.columns:
        available_cols = [c for c in factor_df.columns if c not in ['date', 'asset']]
        raise ValueError(
            f"因子列 '{factor_col}' 不存在于 factor_df 中，"
            f"可用因子列: {available_cols}"
        )
    
    # 数据统计
    if verbose:
        logger.info("数据统计:")
        logger.info("  日期范围: %s ~ %s", factor_df['date'].min(), factor_df['date'].max())
        logger.info("  股票数量: %d", factor_df['asset'].nunique())
        valid_factor = factor_df[factor_col].dropna()
        if len(valid_factor) > 0:
            logger.info("  %s 范围: %.2f ~ %.2f", factor_col, valid_factor.min(), valid_factor.max())
            logger.info("  %s 均值: %.2f", factor_col, valid_factor.mean())
    
    # percentile 分层无需阈值验证（自适应数据范围）
    
    # 创建回测引擎
    logger.info("创建回测引擎...")
    engine = LayeredBacktestEngine(
        factor_df=factor_df,
        return_df=return_df,
        factor_col=factor_col,
        return_col='forward_return_1d',
        date_col='date',
        asset_col='asset'
    )
    
# 执行分层回测
    logger.info("执行分层回测...")
    # percentile 模式：强制使用（v1.5 规范），每层固定比例
    
    result = engine.run(
        layer_method='percentile',
        n_layers=config.n_layers,
        factor_direction=config.factor_direction,
        long_layers=config.long_layers,
        short_layers=config.short_layers,
        min_stocks_per_layer=config.min_stocks_per_layer,
        trade_cost_rate=config.trade_cost_rate
    )
    
    # 添加因子特定信息
    result['meta']['factor_name'] = factor_name
    result['meta']['layer_names'] = config.layer_names
    
    # 生成报告
    report = engine.generate_report(result)
    logger.info(report)
    
    # 分层说明
    logger.info("=" * 40)
    logger.info("%s 分层说明", factor_name)
    logger.info("=" * 40)
    for layer_id in range(1, config.n_layers + 1):
        layer_key = str(layer_id)
        name = config.layer_names.get(layer_key, f'Layer{layer_id}')
        logger.info("  Layer%d (%s): percentile %d-%d%%", 
            layer_id, name, 
            (layer_id-1)*100//config.n_layers, 
            layer_id*100//config.n_layers)
    
    # 保存结果
    if output_dir is None:
        project_root = Path(__file__).parent.parent.parent
        output_dir = project_root / 'backtest' / 'result'
    
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    output_file = Path(output_dir) / f'{factor_name}_layered_backtest.json'
    
    output_data = {
        'meta': result['meta'],
        'layer_stats': result['layer_stats'],
        'long_short': result['long_short'],
        'monotonicity': result['monotonicity'],
        'trading_cost_analysis': result['trading_cost_analysis'],
        'config': {
            'n_layers': config.n_layers,
            'layer_names': config.layer_names,
            'factor_direction': config.factor_direction,
            'long_layers': config.long_layers,
            'short_layers': config.short_layers,
            'trade_cost_rate': config.trade_cost_rate,
            'min_stocks_per_layer': config.min_stocks_per_layer
        },
        'created_at': datetime.now().isoformat()
    }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(convert_to_native_types(output_data), f, indent=2, ensure_ascii=False)
    
    logger.info("结果已保存: %s", output_file)
    
    # 保存每日明细
    daily_file = Path(output_dir) / f'{factor_name}_layered_backtest_daily.json.gz'
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


# ============================================================================
# CLI 入口
# ============================================================================

def create_cli_entrypoint(
    factor_name: str,
    factor_col: str,
    config_class: type,
    factor_calculator: Optional[Callable] = None,
    additional_data_files: Optional[Dict[str, str]] = None,
    required_factor_cols: Optional[List[str]] = None,
    cache_dir: Optional[str] = None
) -> Callable[[], None]:
    """创建 CLI 入口函数
    
    使用方式:
        main = create_cli_entrypoint(
            factor_name='volume_ratio',
            factor_col='volume_ratio_5',
            config_class=VolumeRatioLayerConfig
        )
        
        if __name__ == '__main__':
            main()
    """
    def main():
        import argparse
        
        parser = argparse.ArgumentParser(description=f'{factor_name} 分层回测')
        parser.add_argument('--cache_dir', type=str, default=cache_dir,
                            help='缓存目录路径')
        parser.add_argument('--output_dir', type=str, default=None)
        parser.add_argument('--quiet', action='store_true')
        
        args = parser.parse_args()
        
        logger = get_logger(__name__)
        
        try:
            result = run_layered_backtest(
                factor_name=factor_name,
                factor_col=factor_col,
                config=config_class(),
                factor_calculator=factor_calculator,
                additional_data_files=additional_data_files,
                required_factor_cols=required_factor_cols,
                cache_dir=args.cache_dir,
                output_dir=args.output_dir,
                verbose=not args.quiet,
                logger=logger
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
    
    return main