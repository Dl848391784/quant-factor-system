#!/usr/bin/env python3
"""
RSI 因子分层回测脚本

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

DEFAULT_N = 6
# EPSILON 用于判断 avg_loss 是否接近零（避免 division by zero 或极小值）
# RSI 理论范围 [0, 100]，avg_loss 为价格变动绝对值，量级约价格*0.01~0.05
# 1e-10 作为零值阈值，相对 avg_loss 量级极小（约 1e-8 倍），判断合理
EPSILON = 1e-10


def _calc_delta(series: pd.Series) -> pd.Series:
    """计算价格变化（groupby transform 专用，显式传参避免闭包）
    
    Args:
        series: 单资产的收盘价序列
    
    Returns:
        价格变化序列（第一天为 NaN）
    
    Note:
        - diff() 计算与前一天的差值
        - 第一天无前值，结果为 NaN
    """
    return series.diff()


def _wilder_smoothing(series: pd.Series, n: int) -> pd.Series:
    """Wilder 平滑：前 n-1 天 NaN，第 n 天 SMA 种子，第 n+1 天起 EWM 递推
    
    Args:
        series: 单资产的序列（gain 或 loss）
        n: 窗口期
    
    Returns:
        Wilder 平滑均值序列
    
    Note:
        Wilder (1978) 标准实现：
        1. 前 n-1 天为 NaN（数据不足以计算 SMA）
        2. 第 n 天（索引 n-1）使用 SMA 值作为 EWM 种子
           - SMA = series.iloc[:n].mean()
        3. 第 n+1 天及之后使用 EWM 递推
           - 公式：avg_t = alpha * val_t + (1-alpha) * avg_{t-1}
           - alpha = 1/n
           - NaN 传播：若当天输入为 NaN，结果也为 NaN
        
        与 pandas ewm(adjust=False) 的差异：
        - pandas ewm(adjust=False) 从第 1 个观测值就开始计算
        - Wilder 标准要求前 n-1 天为 NaN，第 n 天用 SMA
    """
    alpha = 1.0 / n
    
    # 防御性检查：序列长度不足
    if len(series) < n:
        return pd.Series(float('nan'), index=series.index, dtype=float)
    
    # 第 n 天（索引 n-1）：SMA 种子
    seed = series.iloc[:n].mean()
    if pd.isna(seed):  # 防御：前 n 天全为 NaN 时无法计算种子
        return pd.Series(float('nan'), index=series.index, dtype=float)
    
    # 向量化 EWM 递推（替代显式循环）
    # 使用 ignore_na=True：NaN 不参与 ewm 计算，但仍需手动传播
    ewm_result = series.ewm(alpha=alpha, adjust=False, ignore_na=True).mean()
    
    # 构建结果：前 n-1 天 NaN，第 n 天 SMA 种子，第 n+1 天起 ewm 结果
    result = pd.Series(float('nan'), index=series.index, dtype=float)
    result.iloc[n - 1] = seed  # 手动设置 SMA 种子（ewm 计算起点不同）
    result.iloc[n:] = ewm_result.iloc[n:]  # 第 n+1 天起使用 ewm 递推结果
    
    # NaN 传播：ewm(ignore_na=True) 会跳过 NaN，需手动强制传播
    # 使用 .where() 避免 ChainedAssignmentError（Copy-on-Write）
    result.iloc[n:] = ewm_result.iloc[n:].where(series.iloc[n:].notna(), float('nan'))
    
    return result


@dataclass
class RSILayerConfig(LayerConfigBase):
    """RSI 分层配置"""
    
    
    layer_names: TypingDict[str, str] = field(default_factory=lambda: {
        '1': '超卖层(RSI<30)',
        '2': '偏弱层(30≤RSI<50)',
        '3': '偏强层(50≤RSI<70)',
        '4': '超买层(RSI≥70)'
    })
    
    factor_direction: str = 'negative'
    long_layers: List[int] = field(default_factory=lambda: [1, 2])
    short_layers: List[int] = field(default_factory=lambda: [3, 4])
    
    # ========== 策略说明（均值回归）==========
    # RSI 经典均值回归策略：
    # - RSI < 30（超卖）→ 价格可能反弹，做多（Layer1）
    # - RSI > 70（超买）→ 价格可能回落，做空（Layer4）
    # 
    # Layer2/Layer3 扩展说明：
    # - Layer2（30≤RSI<50，偏弱）→ 偏离中性偏弱，可能反弹，做多
    # - Layer3（50≤RSI<70，偏强）→ 偏离中性偏强，可能回落，做空
    # 
    # factor_direction='negative' 意味着：
    # - 低 RSI（超卖/偏弱）→ 做多（long_layers=[1,2]）
    # - 高 RSI（超买/偏强）→ 做空（short_layers=[3,4]）
    # 
    # 注意：这是均值回归策略，而非趋势跟随策略。
    # 趋势跟随策略会在 RSI 50~70（上涨趋势延续）时做多，
    # 但均值回归策略认为偏离中性后可能回归，故做空。
    # 若需趋势跟随策略，请调整 factor_direction='positive'。
    
    # 格式遵循 MODULE.md 第451行规范：完整区间 [lower, upper)，必须包含下界
    # 最大边界使用 ≥，说明越界值处理
    #
    # runner 分层逻辑说明（fixed_threshold 模式）：
    # - 低于最小阈值（RSI<0）→ 归入 Layer1（边界处理）
    # - 边界内循环归层：
    #   - Layer1: [0, 30) 区间（0 ≤ RSI < 30）
    #   - Layer2: [30, 50) 区间（30 ≤ RSI < 50）
    #   - Layer3: [50, 70) 区间（50 ≤ RSI < 70）
    #   - Layer4: [70, 100] 区间（最后一层右闭：70 ≤ RSI ≤ 100）
    # - 高于最大阈值（RSI>100）→ 归入 Layer4（边界处理）
    #
    # 关键边界点说明：
    # - RSI=30 → 归入 Layer2（runner 使用 [30,50) 区间，左闭右开）
    # - RSI=70 → 归入 Layer4（runner 最后一层右闭：[70,100]）
    # - 与 layer_names 描述一致，不存在"碰巧正确"问题
    layer_threshold_desc: TypingDict[str, str] = field(default_factory=lambda: {
        '1': 'RSI < 30 (含越界值<0，超卖层，做多)',   # 含越界值 RSI < 0
        '2': '30 ≤ RSI < 50 (偏弱层，做多)',
        '3': '50 ≤ RSI < 70 (偏强层，做空)',
        '4': 'RSI ≥ 70 (含边界70，含越界值>100，超买层，做空)'  # 含越界值 RSI > 100
    })
    
    # 配置元数据：记录默认 RSI 窗口（CLI 可通过 --rsi-n 覆盖）
    rsi_n: int = DEFAULT_N


def calculate_rsi(
    factor_df: pd.DataFrame,
    n: int = DEFAULT_N,
    log_handler: Any = None
) -> pd.DataFrame:
    """计算 RSI 因子
    
    Args:
        factor_df: 包含 close 列的 DataFrame
        n: 滚动窗口期，默认 6
        log_handler: 日志对象（可选，避免遮蔽模块级 logger）
    
    Returns:
        包含 rsi 列的 DataFrame
    
    Note:
        Wilder (1978) RSI 计算方法：
        1. 前 n-1 天为 NaN（数据不足以计算 SMA）
        2. 第 n 天（索引 n-1）使用 SMA 值作为 EWM 种子
           - SMA = rolling(n).mean() 的第一个有效值
        3. 第 n+1 天及之后使用 EWM 递推
           - 公式：avg_t = alpha * val_t + (1-alpha) * avg_{t-1}
           - alpha = 1/n
        
        与 pandas ewm(adjust=False) 的差异：
        - pandas ewm(adjust=False) 从第 1 个观测值就开始计算
        - Wilder 标准要求前 n-1 天为 NaN，第 n 天用 SMA
        
        RSI 公式：
        - RSI = 100 - 100 / (1 + RS)，RS = avg_gain / avg_loss
        - RSI 理论范围 [0, 100]，实际数据可能因计算误差越界
        - avg_loss 接近零时，RS → ∞，RSI → 100
    """
    df = factor_df.copy()
    df = df.sort_values(['asset', 'date'])
    
    # 计算价格变化
    df['delta'] = df.groupby('asset')['close'].transform(_calc_delta)
    
    # 分离上涨和下跌
    df['gain'] = df['delta'].where(df['delta'] > 0, 0)
    df['loss'] = df['delta'].where(df['delta'] < 0, 0).abs()
    
    # Wilder 标准 RSI 计算（前 n 天 SMA 种子，之后 EWM 递推）
    # 使用 rolling 计算 SMA，之后用 EWM 递推（alpha=1/n）
    # 注意：pandas ewm(adjust=False) 从第一个观测值就开始计算，
    # 但 Wilder 标准要求前 n 天用 SMA 种子，之后才 EWM 递推
    # 
    # 实现方式：
    # 1. 前 n 天使用 rolling(n).mean() 计算 SMA
    #    - 前 n-1 天：NaN（数据不足）
    #    - 第 n-1 天：SMA 值作为 EWM 种子
    # 2. 第 n 天及之后：手动 EWM 递推
    #    - 公式：avg_t = alpha * val_t + (1-alpha) * avg_{t-1}
    #    - alpha = 1/n
    
    # 使用独立函数替代 lambda 闭包（遵循 MODULE.md 规范）
    calc_avg = partial(_wilder_smoothing, n=n)
    
    # 计算平均上涨和下跌
    df['avg_gain'] = df.groupby('asset')['gain'].transform(calc_avg)
    df['avg_loss'] = df.groupby('asset')['loss'].transform(calc_avg)
    
    # ========== 边界处理：avg_loss 接近零时 ==========
    # avg_loss 接近零时的 RSI 计算（遵循 Wilder 1978 标准）
    # 
    # 边界情况分类：
    # 1. avg_loss > EPSILON 且 avg_gain > 0: 正常计算 RS，RSI ∈ [0, 100]
    # 2. avg_loss > EPSILON 且 avg_gain = 0: RS = 0，RSI = 0（超卖）
    # 3. avg_loss = 0 且 avg_gain > 0: RS → ∞，RSI = 100（超买）
    # 4. avg_loss = 0 且 avg_gain = 0: 无涨无跌，RSI = 50（中性）
    #    - 场景：连续多天价格不变（delta=0），或停牌/价格冻结
    #    - gain=0 且 loss=0，导致 avg_gain=0 且 avg_loss=0
    #    - 此时 RSI 应为 50（无涨无跌），而非 100（超买）
    #
    # delta=0 归属说明：
    # - delta=0（价格不变）时，gain=0 且 loss=0
    # - 这是正确的处理：既不是上涨也不是下跌
    # - 但连续多天 delta=0 会累积导致 avg_gain=0 且 avg_loss=0
    
    # 防御性代码说明：
    # avg_loss 和 avg_gain 理论上非负（delta.abs() 后 EWM）
    # 使用 .abs() 是防御性代码，防止数值误差或异常数据产生负值
    
    # 边界判断：使用 .abs() 防御负值（理论上不应出现）
    zero_loss_mask = (df['avg_loss'].notna()) & (df['avg_loss'].abs() < EPSILON)
    zero_gain_mask = (df['avg_gain'].notna()) & (df['avg_gain'].abs() < EPSILON)
    
    # 同时接近零：avg_gain=0 且 avg_loss=0 → RSI=50
    both_zero_mask = zero_loss_mask & zero_gain_mask
    if both_zero_mask.sum() > 0 and log_handler:
        # 数据质量问题：可能表示停牌或价格冻结
        log_handler.warning(
            "avg_gain=avg_loss=0 的记录数: %d (%.2f%%)，RSI 设为 50（无涨无跌）。"
            "可能原因：停牌、价格冻结、数据质量问题，建议检查。",
            both_zero_mask.sum(), both_zero_mask.sum() / len(df) * 100
        )
    
    # 只有 avg_loss 接近零（avg_gain > 0）: RSI=100（超买）
    only_zero_loss_mask = zero_loss_mask & ~zero_gain_mask
    if only_zero_loss_mask.sum() > 0 and log_handler:
        log_handler.warning(
            "avg_loss 接近零但 avg_gain>0 的记录数: %d (%.2f%%)，RSI 设为 100（超买）",
            only_zero_loss_mask.sum(), only_zero_loss_mask.sum() / len(df) * 100
        )
    
    # 计算 RS 和 RSI（避免中间污染值）
    # 使用 safe_avg_loss 避免 EPSILON 替换导致的数值污染
    # 边界判断统一使用 >= EPSILON（对齐 zero_loss_mask 的 < EPSILON）
    safe_avg_loss = df['avg_loss'].where(df['avg_loss'] >= EPSILON)
    df['rs'] = df['avg_gain'] / safe_avg_loss
    
    # RSI 计算：直接赋值，无需 .where 冗余（rs 为 NaN 时，计算结果自动为 NaN）
    df['rsi'] = 100 - (100 / (1 + df['rs']))
    
    # 边界处理覆盖（逻辑清晰，无中间污染值）
    # avg_loss=0 且 avg_gain>0 → RSI=100（超买）
    df.loc[only_zero_loss_mask, 'rsi'] = 100
    # avg_loss=0 且 avg_gain=0 → RSI=50（中性）
    df.loc[both_zero_mask, 'rsi'] = 50
    
    # ========== 因子值统计（正常业务场景记录）==========
    # RSI < 0: 计算误差导致越界，归入 Layer 1（runner 边界处理）
    # RSI > 100: 计算误差导致越界，归入 Layer 4（runner 边界处理）
    below_min_mask = (df['rsi'].notna()) & (df['rsi'] < 0)
    if below_min_mask.sum() > 0 and log_handler:
        log_handler.info(
            "RSI 越界统计: RSI<0 的记录数: %d (%.2f%%)，将归入 Layer1（超卖层）",
            below_min_mask.sum(), below_min_mask.sum() / len(df) * 100
        )
    
    above_max_mask = (df['rsi'].notna()) & (df['rsi'] > 100)
    if above_max_mask.sum() > 0 and log_handler:
        log_handler.info(
            "RSI 越界统计: RSI>100 的记录数: %d (%.2f%%)，将归入 Layer4（超买层）",
            above_max_mask.sum(), above_max_mask.sum() / len(df) * 100
        )
    
    # 因子数据范围校验（遵循 MODULE.md 第505行规范）
    # 全 NaN 防御：检查是否有有效数据
    rsi_values = df['rsi'].dropna()
    if len(rsi_values) == 0:
        if log_handler:
            log_handler.warning("RSI 全部为 NaN，无法计算范围")
        # 全 NaN 时提前返回，避免输出误导性的 "0.00 ~ 0.00" 日志
        return df
    
    rsi_min = rsi_values.min()
    rsi_max = rsi_values.max()
    
    if log_handler:
        log_handler.info("RSI 因子范围: %.2f ~ %.2f", rsi_min, rsi_max)
    
    return df


def main():
    import argparse
    parser = argparse.ArgumentParser(description='RSI 分层回测')
    parser.add_argument('--data_source', type=str, default=None,
                        help='数据源文件路径')
    parser.add_argument('--output_dir', type=str, default=None,
                        help='输出目录路径')
    parser.add_argument('--quiet', action='store_true',
                        help='静默模式')
    parser.add_argument('--rsi-n', type=int, default=DEFAULT_N,
                        help=f'RSI 计算窗口，默认 {DEFAULT_N}')
    args = parser.parse_args()
    
    try:
        # 使用 functools.partial 替代闭包，显式传参避免隐式捕获
        # 透传 log_handler 参数（遵循 bollinger_pb 模式）
        factor_calc = partial(
            calculate_rsi,
            n=args.rsi_n,
            log_handler=logger
        )
        
        # 更新历史（2026-05-27）：v2.7 移除 cache_dir 参数，改为 data_source
        result = run_layered_backtest(
            factor_name='rsi',
            factor_col='rsi',
            config=RSILayerConfig(),
            factor_calculator=factor_calc,
            required_factor_cols=['close'],
            data_source=args.data_source,
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
        logger.error("数据字段缺失: %s", e)
        sys.exit(3)
    except ValueError as e:
        logger.error("数据值异常: %s", e)
        sys.exit(4)
    except Exception as e:
        logger.exception("回测执行异常: %s", e)
        sys.exit(5)


if __name__ == '__main__':
    main()