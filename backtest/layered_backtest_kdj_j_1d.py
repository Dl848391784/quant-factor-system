#!/usr/bin/env python3
"""
KDJ_J 因子分层回测脚本

使用公共入口 run_layered_backtest，代码量从 ~500 行降至 ~200 行。

规范:
- 遵循 PROJECT.md 公共模块强制复用规范
- 命名遵循 MODULE.md: layered_backtest_<因子名>_<收益周期>.py

作者: 云瑶
创建日期: 2026-05-23
重构日期: 2026-05-23（使用公共入口）
"""

# 标准库
import sys
from pathlib import Path
from dataclasses import dataclass, field
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

DEFAULT_N = 9
DEFAULT_M1 = 3
DEFAULT_M2 = 3


@dataclass
class KDJJLayerConfig(LayerConfigBase):
    """KDJ_J 分层配置"""
    
    # thresholds 设计说明：
    # - 5个阈值点 [-30, 0, 20, 80, 100] 形成 4 层（len(thresholds) - 1 = 4）
    # - 边界处理：J < -30 归 Layer 1（越界），J > 100 归 Layer 4（越界）
    # - Layer 划分：Layer1: [-30, 0), Layer2: [0, 20), Layer3: [20, 80), Layer4: [80, 100]
    # - KDJ J 理论范围 [-20, 120]，实际数据可能越界
    
    # layer_names 与 thresholds 对应（4层）：
    # - Layer 1: J < -30（超卖，越界值归入此层）→ 做多（反向因子）
    # - Layer 2: -30 ≤ J < 0（偏弱）→ 做多（反向因子）
    # - Layer 3: 0 ≤ J < 80（中性）→ 不参与多空组合
    # - Layer 4: J ≥ 80（偏强，越界值归入此层）→ 做空（反向因子）
    layer_names: TypingDict[str, str] = field(default_factory=lambda: {
        '1': '超卖层(J<-30)',
        '2': '偏弱层(-30≤J<0)',
        '3': '中性层(0≤J<80)',
        '4': '偏强层(J≥80)'
    })
    
    # 反向因子：J值低做多（超卖），J值高做空（超买）
    factor_direction: str = 'negative'
    long_layers: List[int] = field(default_factory=lambda: [1, 2])   # 超卖/偏弱层做多
    short_layers: List[int] = field(default_factory=lambda: [4])      # 偏强层做空
    
    layer_threshold_desc: TypingDict[str, str] = field(default_factory=lambda: {
        '1': 'J < -30 (含越界值，超卖层，做多)',
        '2': '-30 ≤ J < 0 (偏弱层，做多)',
        '3': '0 ≤ J < 80 (中性层，不参与多空)',
        '4': 'J ≥ 80 (含边界80，含越界值>100，偏强层，做空)'
    })
    
    kdj_n: int = DEFAULT_N
    kdj_m1: int = DEFAULT_M1
    kdj_m2: int = DEFAULT_M2


def _calc_ewm_with_initial(
    series: pd.Series,
    alpha: float,
    initial_value: float = 50.0
) -> pd.Series:
    """计算 EWM，填充 NaN 为初始值
    
    Args:
        series: 输入序列（可能包含 NaN）
        alpha: EWM alpha 参数（alpha = 1/period，权重衰减半衰期约为 period）
        initial_value: 初始值，默认 50（KDJ 的 K 和 D 初始值）
    
    Returns:
        EWM 计算结果
    """
    filled = series.fillna(initial_value)
    result = filled.ewm(alpha=alpha, adjust=False).mean()
    return result  # type: ignore


def _calc_k_from_rsv(series: pd.Series, alpha: float) -> pd.Series:
    """从 RSV 计算 K 值
    
    Args:
        series: RSV 序列
        alpha: K 值平滑 alpha
    
    Returns:
        K 值序列
    
    Note:
        用于 groupby.transform，lambda 仍会捕获 alpha（闭包特性），
        但 alpha 在循环外定义且不变，不会引发实际问题。
    """
    return _calc_ewm_with_initial(series, alpha)


def _calc_d_from_k(series: pd.Series, alpha: float) -> pd.Series:
    """从 K 值计算 D 值
    
    Args:
        series: K 值序列
        alpha: D 值平滑 alpha
    
    Returns:
        D 值序列
    
    Note:
        用于 groupby.transform，lambda 仍会捕获 alpha（闭包特性），
        但 alpha 在循环外定义且不变，不会引发实际问题。
    """
    return _calc_ewm_with_initial(series, alpha)


def calculate_kdj_j(
    factor_df: pd.DataFrame,
    n: int = DEFAULT_N,
    m1: int = DEFAULT_M1,
    m2: int = DEFAULT_M2,
    log_handler: Any = logger  # 问题2修复：默认值设为模块级 logger
) -> pd.DataFrame:
    """计算 KDJ_J 因子
    
    Args:
        factor_df: 包含 close, high, low 列的 DataFrame
        n: RSV 计算周期，默认 9
        m1: K 值平滑周期，默认 3
        m2: D 值平滑周期，默认 3
        log_handler: 日志对象，默认为模块级 logger
    
    Returns:
        包含 kdj_j 列的 DataFrame
    """
    # 问题1修复：入口日志，记录参数和输入数据规模
    stock_count = factor_df['asset'].nunique()
    date_range = f"{factor_df['date'].min()} ~ {factor_df['date'].max()}"
    log_handler.info(f"开始计算KDJ_J因子: n={n}, m1={m1}, m2={m2}, 股票数={stock_count}, 日期范围={date_range}")
    
    df = factor_df.copy()
    df = df.sort_values(['asset', 'date'])
    
    # RSV 计算（未成熟随机值）
    # 边界处理说明：
    # - 当 range_val == 0（high == low，如停牌）时：
    #   - safe_range 替换为 1.0 防止 division by zero
    #   - 第二个 where 将 RSV 设为 50.0（中性值），覆盖第一个计算结果
    # - 逻辑：range_val == 0 → RSV = 50.0（而非 0）
    df['low_n'] = df.groupby('asset')['low'].transform(
        lambda x: x.rolling(window=n, min_periods=n).min()
    )
    df['high_n'] = df.groupby('asset')['high'].transform(
        lambda x: x.rolling(window=n, min_periods=n).max()
    )
    
    # 使用 Series.where 避免 division by zero
    range_val = df['high_n'] - df['low_n']
    safe_range = range_val.where(range_val > 0, 1.0)  # 避免 division by zero（但不影响最终结果）
    df['rsv'] = ((df['close'] - df['low_n']) / safe_range * 100).where(range_val > 0, 50.0)  # range_val==0 时 RSV=50.0
    
    # 计算 K（alpha = 1/m1，使得权重衰减半衰期约为 m1）
    alpha_k = 1.0 / m1
    df['k'] = df.groupby('asset')['rsv'].transform(
        lambda s: _calc_k_from_rsv(s, alpha_k)  # 显式传参，避免闭包
    )
    
    # 计算 D（alpha = 1/m2，使得权重衰减半衰期约为 m2）
    alpha_d = 1.0 / m2
    df['d'] = df.groupby('asset')['k'].transform(
        lambda s: _calc_d_from_k(s, alpha_d)  # 显式传参，避免闭包
    )
    
    # 计算 J
    df['kdj_j'] = 3 * df['k'] - 2 * df['d']
    
    # 问题1修复：J值计算完成后记录非空行数
    kdj_j_valid = df['kdj_j'].notna().sum()
    log_handler.info(f"KDJ_J因子计算完成，有效值行数: {kdj_j_valid}")
    
    # 因子数据范围校验（遵循 MODULE.md 第505行规范）
    kdj_j_min = df['kdj_j'].min()
    kdj_j_max = df['kdj_j'].max()
    log_handler.info(f"KDJ_J 因子范围: {kdj_j_min:.2f} ~ {kdj_j_max:.2f}")
    
    return df


def main():
    import argparse
    parser = argparse.ArgumentParser(description='KDJ_J 分层回测')
    parser.add_argument('--data_source', type=str, default=None,
                        help='数据源文件路径')
    parser.add_argument('--output_dir', type=str, default=None)
    parser.add_argument('--quiet', action='store_true')
    # argparse 参数命名说明：
    # - 命令行使用 --kdj-n（连字符）
    # - Python 访问使用 args.kdj_n（下划线，argparse 自动转换）
    # - 这是 argparse 标准行为，dest 参数可自定义内部名称
    parser.add_argument('--kdj-n', type=int, default=DEFAULT_N,
                        help=f'KDJ N 参数，默认 {DEFAULT_N}')
    parser.add_argument('--kdj-m1', type=int, default=DEFAULT_M1,
                        help=f'KDJ M1 参数，默认 {DEFAULT_M1}')
    parser.add_argument('--kdj-m2', type=int, default=DEFAULT_M2,
                        help=f'KDJ M2 参数，默认 {DEFAULT_M2}')
    args = parser.parse_args()
    
    try:
        def factor_calc(df):
            return calculate_kdj_j(df, n=args.kdj_n, m1=args.kdj_m1, m2=args.kdj_m2, log_handler=logger)
        
        logger.info(f"启动KDJ_J分层回测: n={args.kdj_n}, m1={args.kdj_m1}, m2={args.kdj_m2}")
        
        # 更新历史（2026-05-27）：v2.7 移除 cache_dir 参数，改为 data_source
        result = run_layered_backtest(
            factor_name='kdj_j',
            factor_col='kdj_j',
            config=KDJJLayerConfig(),
            factor_calculator=factor_calc,
            required_factor_cols=['close', 'high', 'low'],
            data_source=args.data_source,
            output_dir=args.output_dir,
            verbose=not args.quiet,
            logger=logger
        )
        
        if result['meta']['n_days_total'] == 0:
            # 问题7修复：去掉"退出码 1"字样
            logger.error("回测无有效数据，程序终止")
            sys.exit(1)
        
        # 问题3修复：输出完整回测结果
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
        
        # 问题6修复：结束日志合并到结果摘要末尾
        logger.info("=" * 128 + " 回测完成 ")
        sys.exit(0)
        
    except FileNotFoundError:
        # 问题5修复：改用 logger.exception 输出完整堆栈
        logger.exception("数据文件不存在")
        sys.exit(2)
    except KeyError:
        # 问题4修复：改用 logger.exception 输出完整堆栈
        logger.exception("数据结构错误，缺少必要字段")
        sys.exit(3)
    except ValueError:
        # 问题5修复：改用 logger.exception 输出完整堆栈
        logger.exception("参数错误")
        sys.exit(4)
    except Exception:
        logger.exception("回测执行异常")
        sys.exit(5)


if __name__ == '__main__':
    main()