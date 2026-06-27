"""测试 _merge_data 的 T-1 对齐（消除前视偏差）

验证 factor[D] 与 forward_return_1d[D+1] 配对，而非 forward_return_1d[D]
"""

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import numpy as np
import pandas as pd
import pytest

from backtest.common.layered_backtest import LayeredBacktestEngine


class TestT1Alignment:
    """T-1 对齐消除前视偏差"""

    def _make_test_data(self):
        """构造 3 天 × 2 只股票的测试数据

        factor[D] 用 D 日收盘价算出，forward_return_1d[D] = (close[D+1] - close[D]) / close[D]

        正确配对：factor[D-1] → forward_return_1d[D]
        = D-1 日的因子 → D→D+1 收益
        = T-1 因子 → T 买入 → T+1 卖出
        """
        dates = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"])
        assets = ["000001", "000002"]

        # 因子值：D1=1.0, D2=2.0, D3=3.0（递增，方便追踪）
        factor_df = pd.DataFrame(
            {
                "date": np.repeat(dates, len(assets)),
                "asset": assets * len(dates),
                "factor_value": [1.0, 1.1, 2.0, 2.1, 3.0, 3.1],
            }
        )

        # forward_return_1d[D] = D→D+1 收益
        # D1: stock1 +10%, stock2 +5%
        # D2: stock1 -5%, stock2 +8%
        # D3: NaN（无 D4 数据）
        return_df = pd.DataFrame(
            {
                "date": np.repeat(dates, len(assets)),
                "asset": assets * len(dates),
                "forward_return_1d": [0.10, 0.05, -0.05, 0.08, np.nan, np.nan],
            }
        )

        return factor_df, return_df, dates

    def test_factor_d1_pairs_with_return_d2(self):
        """factor[D1] 应与 forward_return_1d[D2] 配对，而非 forward_return_1d[D1]"""
        factor_df, return_df, dates = self._make_test_data()

        engine = LayeredBacktestEngine(
            factor_df=factor_df,
            return_df=return_df,
            factor_col="factor_value",
            return_col="forward_return_1d",
        )

        # D1 的因子值 1.0 应配对 D2 的收益 -0.05（而非 D1 的 0.10）
        d2_row = engine.merged_df[(engine.merged_df["date"] == dates[1]) & (engine.merged_df["asset"] == "000001")]
        assert len(d2_row) == 1
        assert d2_row["factor_value"].iloc[0] == 1.0  # D1 的因子
        assert d2_row["forward_return_1d"].iloc[0] == pytest.approx(-0.05)  # D2 的收益

    def test_factor_d2_pairs_with_return_d3(self):
        """factor[D2] 应与 forward_return_1d[D3] 配对"""
        factor_df, return_df, dates = self._make_test_data()

        engine = LayeredBacktestEngine(
            factor_df=factor_df,
            return_df=return_df,
            factor_col="factor_value",
            return_col="forward_return_1d",
        )

        d3_row = engine.merged_df[(engine.merged_df["date"] == dates[2]) & (engine.merged_df["asset"] == "000002")]
        assert len(d3_row) == 1
        assert d3_row["factor_value"].iloc[0] == 2.1  # D2 的因子
        # D3 收益是 NaN，merge 后应无有效收益
        assert pd.isna(d3_row["forward_return_1d"].iloc[0])

    def test_no_lookahead_bias(self):
        """前视偏差消除：merge 后的行数应少于 factor 和 return 的交集

        修复前：factor[D1]→return[D1], factor[D2]→return[D2], factor[D3]→return[D3]
        修复后：factor[D1]→return[D2], factor[D2]→return[D3], factor[D3]→无（丢弃）
        """
        factor_df, return_df, dates = self._make_test_data()

        engine = LayeredBacktestEngine(
            factor_df=factor_df,
            return_df=return_df,
            factor_col="factor_value",
            return_col="forward_return_1d",
        )

        # 修复后：D1→D2(2行), D2→D3(2行), D3→无(丢弃)
        # merged_df 应有 4 行（2 天 × 2 股票），而非 6 行
        assert len(engine.merged_df) == 4

        # 日期应为 D2 和 D3（因子 D1→D2, D2→D3）
        merged_dates = sorted(engine.merged_df["date"].unique())
        assert len(merged_dates) == 2
        assert merged_dates[0] == dates[1]
        assert merged_dates[1] == dates[2]

    def test_last_day_factor_dropped(self):
        """最后一个交易日的因子无次日收益，应被丢弃"""
        factor_df, return_df, dates = self._make_test_data()

        engine = LayeredBacktestEngine(
            factor_df=factor_df,
            return_df=return_df,
            factor_col="factor_value",
            return_col="forward_return_1d",
        )

        # D3 的因子值 3.0/3.1 不应出现在 merged_df 中
        assert 3.0 not in engine.merged_df["factor_value"].values
        assert 3.1 not in engine.merged_df["factor_value"].values
