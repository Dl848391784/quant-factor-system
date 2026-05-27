#!/usr/bin/env python3
"""
BOLLINGER_PB 因子分层回测脚本

使用公共入口 run_layered_backtest。

规范:
- 遵循 PROJECT.md 公共模块强制复用规范
- 命名遵循 MODULE.md: layered_backtest_<因子名>_<收益周期>.py

作者: 云瑶
重构日期: 2026-05-23（使用公共入口）
"""

# 标准库
import sys
from pathlib import Path
from dataclasses import dataclass, field
from functools import partial
from typing import List, Dict as TypingDict, Any

# 第三方库
import pandas as pd

# 本地模块
sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.common.layered_backtest_runner import (
    run_layered_backtest,
    LayerConfigBase
)
from backtest.common.logger_config import get_logger

logger = get_logger(__name__)

DEFAULT_N = 20
# EPSILON 用于判断 band_width 是否接近零（避免 division by zero 或极小值）
# %B 典型范围 0.0 ~ 2.0，band_width 为价格标准差*2，量级约价格*0.02~0.1
# 1e-10 作为零值阈值，相对 band_width 量级极小（约 1e-8 倍），判断合理
EPSILON = 1e-10


def _calc_rolling(series: pd.Series, window: int, method: str = 'mean') -> pd.Series:
    """计算滚动统计量（groupby transform 专用，显式传参避免闭包）
    
    Args:
        series: 单资产的收盘价序列
        window: 滚动窗口期
        method: 统计方法，'mean' 或 'std'
    
    Returns:
        滚动统计量序列（前 window-1 天为 NaN）
    
    Note:
        - min_periods=window 确保只有足够历史数据时才计算
        - 前 window-1 天为 NaN，无法计算有效统计量
        - 例如 window=20，需要至少 20 天数据才能产生第一个有效结果
        - std 默认使用样本标准差（ddof=1，除以 n-1），布林带标准定义使用总体标准差（ddof=0）
        - 对于 window=20，两者差异约 sqrt(20/19) ≈ 2.6%，不影响分层方向
    """
    rolling_obj = series.rolling(window=window, min_periods=window)
    if method == 'mean':
        return rolling_obj.mean()
    elif method == 'std':
        return rolling_obj.std()  # 默认 ddof=1（样本标准差）
    else:
        raise ValueError(f"method 必须是 'mean' 或 'std', 当前值: '{method}'")


@dataclass
class BollingerPBLayerConfig(LayerConfigBase):
    """BOLLINGER_PB 分层配置"""
    
    # thresholds 设计说明：
    # - 5个阈值点 [0.5, 0.8, 1.0, 1.2] 形成 5 层（len(thresholds) = 4，默认生成 5 层）
    # - 边界处理：%B < 0 归 Layer 1（越界），%B > 2 归 Layer 5（越界）
    # - Layer 划分：
    #   - Layer1: %B < 0.5（含越界值<0，价格远低于下轨，超卖层）
    #   - Layer2: 0.5 ≤ %B < 0.8（接近下轨，偏弱层）
    #   - Layer3: 0.8 ≤ %B < 1.0（中轨偏下，中性层）
    #   - Layer4: 1.0 ≤ %B < 1.2（中轨偏上，偏强层）
    #   - Layer5: %B ≥ 1.2（含边界1.2，含越界值>2，价格远高于上轨，超买层）
    # - %B 理论范围无上下限（取决于价格偏离布林带程度），典型范围 [-0.5, 2.5]
    
    # layer_names 与 thresholds 对应（5层）：
    # - Layer 1: %B < 0.5（超卖，越界值<0归入此层）→ 做多（反向因子）
    # - Layer 2: 0.5 ≤ %B < 0.8（偏弱）→ 做多（反向因子）
    # - Layer 3: 0.8 ≤ %B < 1.0（中性）→ 不参与多空组合
    # - Layer 4: 1.0 ≤ %B < 1.2（偏强）→ 做空（反向因子）
    # - Layer 5: %B ≥ 1.2（超买，越界值>2归入此层）→ 做空（反向因子）
    
    layer_names: TypingDict[str, str] = field(default_factory=lambda: {
        '1': '超卖层(PB<0.5)',
        '2': '偏弱层(0.5≤PB<0.8)',
        '3': '中性层(0.8≤PB<1.0)',
        '4': '偏强层(1.0≤PB<1.2)',
        '5': '超买层(PB≥1.2)'
    })
    
    factor_direction: str = 'negative'
    long_layers: List[int] = field(default_factory=lambda: [1, 2])
    short_layers: List[int] = field(default_factory=lambda: [4, 5])
    
    # 格式遵循 MODULE.md 第451行规范：完整区间 [lower, upper)，必须包含下界
    # 最大边界使用 ≥，说明越界值处理
    layer_threshold_desc: TypingDict[str, str] = field(default_factory=lambda: {
        '1': 'PB < 0.5 (含越界值<0，价格远低于下轨，超卖层，做多)',   # 含越界值 PB < 0
        '2': '0.5 ≤ PB < 0.8 (接近下轨，偏弱层，做多)',
        '3': '0.8 ≤ PB < 1.0 (中轨偏下，中性层，不参与多空)',
        '4': '1.0 ≤ PB < 1.2 (中轨偏上，偏强层，做空)',
        '5': 'PB ≥ 1.2 (含边界1.2，含越界值>2，价格远高于上轨，超买层，做空)'  # 含越界值 PB > 2
    })
    
    # 配置元数据：记录默认布林带窗口（CLI 可通过 --bollinger-n 覆盖）
    bollinger_n: int = DEFAULT_N


def calculate_bollinger_pb(
    factor_df: pd.DataFrame,
    n: int = DEFAULT_N,
    log_handler: Any = logger  # 问题2修复：默认值设为模块级 logger
) -> pd.DataFrame:
    """计算 BOLLINGER_PB 因子
    
    Args:
        factor_df: 包含 close 列的 DataFrame
        n: 滚动窗口期，默认 20
        log_handler: 日志对象，默认为模块级 logger
    
    Returns:
        包含 bollinger_pb 列的 DataFrame
    
    Note:
        - 前 n-1 天 bollinger_pb 为 NaN（rolling 计算 NaN）
        - %B = (Close - Lower) / (Upper - Lower)
        - %B < 0: 价格低于下轨
        - %B = 0.5: 价格在中轨
        - %B > 1: 价格高于上轨
    """
    # 问题1修复：入口日志，记录参数和输入数据规模
    stock_count = factor_df['asset'].nunique()
    date_range = f"{factor_df['date'].min()} ~ {factor_df['date'].max()}"
    log_handler.info(f"开始计算布林带%B因子: n={n}, 股票数={stock_count}, 日期范围={date_range}")
    
    df = factor_df.copy()
    df = df.sort_values(['asset', 'date'])
    
    # 使用独立函数替代 lambda 闭包（遵循 MODULE.md 第789行规范）
    calc_mean = partial(_calc_rolling, window=n, method='mean')
    calc_std = partial(_calc_rolling, window=n, method='std')
    
    # 计算均线和标准差
    df['ma_n'] = df.groupby('asset')['close'].transform(calc_mean)
    df['std_n'] = df.groupby('asset')['close'].transform(calc_std)
    
    # 计算布林带上下轨
    df['upper'] = df['ma_n'] + 2 * df['std_n']
    df['lower'] = df['ma_n'] - 2 * df['std_n']
    
    # 计算 %B (Position in Band)
    # %B = (Close - Lower) / (Upper - Lower)
    band_width = df['upper'] - df['lower']
    
    # 边界处理：band_width 接近零时使用默认值 0.5（价格在中轨）
    # 使用 EPSILON 判断避免浮点精度问题（如 1e-15 导致 %B 极端值）
    zero_band_mask = (band_width.notna()) & (band_width.abs() < EPSILON)
    # 问题2修复：去掉 and log_handler 短路条件
    if zero_band_mask.sum() > 0:
        log_handler.warning(
            "band_width 接近零的记录数: %d (%.2f%%)，使用默认值 0.5",
            zero_band_mask.sum(), zero_band_mask.sum() / len(df) * 100
        )
    
    # 使用 Series.where 替代 np.where（避免 ndarray 丢失 index）
    # band_width > EPSILON: 正常计算 %B
    # band_width <= EPSILON: 使用默认值 0.5（价格在中轨）
    df['bollinger_pb'] = ((df['close'] - df['lower']) / band_width).where(
        band_width > EPSILON,
        0.5  # 带宽接近零时的默认值（价格在中轨）
    )
    
    # ========== 因子值统计（正常业务场景记录）==========
    # %B < 0: 价格低于下轨（超卖），归入 Layer 1（runner 边界处理）
    # %B > 2: 价格远高于上轨（超买），归入 Layer 5（runner 边界处理）
    # 这些是正常业务场景，不需要过滤，但记录统计信息供分析
    negative_mask = (df['bollinger_pb'].notna()) & (df['bollinger_pb'] < 0)
    # 问题2修复：去掉 and log_handler 短路条件
    if negative_mask.sum() > 0:
        log_handler.info(
            "bollinger_pb 越界统计: %%B<0 的记录数: %d (%.2f%%)，将归入 Layer1（超卖层）",
            negative_mask.sum(), negative_mask.sum() / len(df) * 100
        )
    
    above_max_mask = (df['bollinger_pb'].notna()) & (df['bollinger_pb'] > 2)
    # 问题2修复：去掉 and log_handler 短路条件
    if above_max_mask.sum() > 0:
        log_handler.info(
            "bollinger_pb 越界统计: %%B>2 的记录数: %d (%.2f%%)，将归入 Layer5（超买层）",
            above_max_mask.sum(), above_max_mask.sum() / len(df) * 100
        )
    
    # 因子数据范围校验（遵循 MODULE.md 第505行规范）
    # 全 NaN 防御：检查是否有有效数据
    pb_values = df['bollinger_pb'].dropna()
    if len(pb_values) == 0:
        # 问题3修复：改为 error 并抛出 ValueError，阻断无效数据进入回测
        log_handler.error("bollinger_pb 全部为 NaN，无法进行回测")
        raise ValueError("bollinger_pb 因子计算结果全为 NaN，无法进行有效回测")
    
    # 计算完成日志
    pb_valid = df['bollinger_pb'].notna().sum()
    log_handler.info(f"布林带%B因子计算完成，有效值行数: {pb_valid}")
    
    pb_min = pb_values.min()
    pb_max = pb_values.max()
    log_handler.info(f"bollinger_pb 因子范围: {pb_min:.2f} ~ {pb_max:.2f}")
    
    return df


def main():
    import argparse
    parser = argparse.ArgumentParser(description='BOLLINGER_PB 分层回测')
    parser.add_argument('--data_source', type=str, default=None,
                        help='数据源文件路径')
    parser.add_argument('--output_dir', type=str, default=None,
                        help='输出目录路径')
    parser.add_argument('--quiet', action='store_true',
                        help='静默模式')
    parser.add_argument('--bollinger-n', type=int, default=DEFAULT_N,
                        help=f'布林带计算窗口，默认 {DEFAULT_N}')
    args = parser.parse_args()
    
    try:
        # 使用 functools.partial 替代闭包，显式传参避免隐式捕获
        # 透传 log_handler 参数（遵循 turnover_surge 模式）
        factor_calc = partial(
            calculate_bollinger_pb,
            n=args.bollinger_n,
            log_handler=logger
        )
        
        logger.info(f"启动布林带%B分层回测: n={args.bollinger_n}")
        
        # 更新历史（2026-05-27）：v2.7 移除 cache_dir 参数，改为 data_source
        result = run_layered_backtest(
            factor_name='bollinger_pb',
            factor_col='bollinger_pb',
            config=BollingerPBLayerConfig(),
            factor_calculator=factor_calc,
            required_factor_cols=['close'],
            data_source=args.data_source,
            output_dir=args.output_dir,
            verbose=not args.quiet,
            logger=logger
        )
        
        if result['meta']['n_days_total'] == 0:
            # 问题8修复：去掉"退出码 1"字样
            logger.error("回测无有效数据，程序终止")
            sys.exit(1)
        
        # 问题5修复：输出完整回测结果
        logger.info("=" * 60 + " 回测结果摘要 " + "=" * 60)
        
        # 元信息
        meta = result.get('meta', {})
        logger.info(f"因子名称: {meta.get('factor_name', 'unknown')}")
        logger.info(f"回测天数: {meta.get('n_days_total', 0)}")
        logger.info(f"分层数量: {meta.get('n_layers', 0)}")
        
        # 分层收益
        layer_returns = result.get('layer_returns', {})
        if layer_returns:
            logger.info("--- 分层累计收益 ---")
            for layer_name, ret in layer_returns.items():
                logger.info(f"{layer_name}: {ret:.2%}")
        
        # 多空组合收益
        long_short = result.get('long_short_return', {})
        if long_short:
            logger.info("--- 多空组合 ---")
            logger.info(f"多头收益: {long_short.get('long_return', 0):.2%}")
            logger.info(f"空头收益: {long_short.get('short_return', 0):.2%}")
            logger.info(f"多空收益: {long_short.get('ls_return', 0):.2%}")
        
        # 风险指标
        risk_metrics = result.get('risk_metrics', {})
        if risk_metrics:
            logger.info("--- 风险指标 ---")
            logger.info(f"夏普比率: {risk_metrics.get('sharpe_ratio', 0):.2f}")
            logger.info(f"最大回撤: {risk_metrics.get('max_drawdown', 0):.2%}")
            logger.info(f"年化收益: {risk_metrics.get('annual_return', 0):.2%}")
            logger.info(f"年化波动: {risk_metrics.get('annual_volatility', 0):.2%}")
        
        # 问题7修复：结束日志合并到结果摘要末尾
        logger.info("=" * 128 + " 回测完成 ")
        sys.exit(0)
        
    except FileNotFoundError:
        # 问题6修复：改用 logger.exception 输出完整堆栈
        logger.exception("数据文件不存在")
        sys.exit(2)
    except KeyError:
        # 问题6修复：改用 logger.exception 输出完整堆栈
        logger.exception("数据字段缺失，缺少必要列")
        sys.exit(3)
    except ValueError:
        # 问题6修复：改用 logger.exception 输出完整堆栈
        logger.exception("数据值异常")
        sys.exit(4)
    except Exception:
        logger.exception("回测执行异常")
        sys.exit(5)


if __name__ == '__main__':
    main()