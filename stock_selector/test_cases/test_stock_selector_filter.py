"""P6-Step2: stock_selector 企稳确认过滤器测试

验证 design.md P6（批次8）：
1. 有企稳信号的股票通过过滤
2. 无企稳信号的股票被排除
3. 确认信号因子不可用时跳过过滤（向后兼容）
4. 不足 top_n 时递补
5. rank 重新编号

遵循 designs/strategy_systemic_overhaul.md §2.6 + 公理4推论4。
"""

import numpy as np
import pandas as pd
import pytest
from stock_selector import apply_stabilization_filter


def _make_stock(code: str, rank: int) -> dict:
    """构造股票 dict"""
    return {
        "rank": rank,
        "code": code,
        "composite_value": -2.0 - rank * 0.1,
        "factor_values": {},
        "factor_values_std": {},
        "weight_coverage": 1.0,
    }


def _make_factor_df(stocks: list[dict], vol_shrink=None, pv_div=None, lower_shadow=None) -> pd.DataFrame:
    """构造单日因子 DataFrame"""
    rows = []
    for s in stocks:
        row = {"asset": s["code"]}
        if vol_shrink is not None:
            row["volume_shrink_rate"] = vol_shrink.get(s["code"], np.nan)
        if pv_div is not None:
            row["price_volume_divergence"] = pv_div.get(s["code"], np.nan)
        if lower_shadow is not None:
            row["lower_shadow_ratio"] = lower_shadow.get(s["code"], np.nan)
        rows.append(row)
    return pd.DataFrame(rows)


class TestStabilizationFilterPass:
    """有企稳信号的股票通过过滤"""

    def test_volume_shrink_passes(self):
        """缩量(vol_shrink<1.0) → 通过"""
        stocks = [_make_stock("001", 1), _make_stock("002", 2)]
        factor_df = _make_factor_df(stocks, vol_shrink={"001": 0.5, "002": 0.8})
        result, excluded = apply_stabilization_filter(stocks, factor_df, top_n=2)
        assert len(result) == 2
        assert excluded == 0

    def test_pv_divergence_passes(self):
        """价跌量缩背离(pv_div>0) → 通过"""
        stocks = [_make_stock("001", 1), _make_stock("002", 2)]
        factor_df = _make_factor_df(stocks, pv_div={"001": 0.05, "002": 0.02})
        result, excluded = apply_stabilization_filter(stocks, factor_df, top_n=2)
        assert len(result) == 2
        assert excluded == 0

    def test_lower_shadow_passes(self):
        """下影线承接(lower_shadow>0.3) → 通过"""
        stocks = [_make_stock("001", 1), _make_stock("002", 2)]
        factor_df = _make_factor_df(stocks, lower_shadow={"001": 0.5, "002": 0.4})
        result, excluded = apply_stabilization_filter(stocks, factor_df, top_n=2)
        assert len(result) == 2
        assert excluded == 0


class TestStabilizationFilterExclude:
    """无企稳信号的股票被排除"""

    def test_volume_amplified_excluded(self):
        """放量(vol_shrink>=1.0) + 无背离 + 无下影线 → 排除"""
        stocks = [_make_stock("001", 1), _make_stock("002", 2), _make_stock("003", 3)]
        factor_df = _make_factor_df(
            stocks,
            vol_shrink={"001": 1.5, "002": 1.2, "003": 0.8},
            pv_div={"001": 0.0, "002": -0.01, "003": 0.0},
            lower_shadow={"001": 0.1, "002": 0.2, "003": 0.1},
        )
        result, excluded = apply_stabilization_filter(stocks, factor_df, top_n=3)
        # 001 和 002 无企稳信号，003 缩量通过
        assert excluded == 2
        assert len(result) == 3  # 递补到 top_n
        # 003 应在结果中
        codes = [s["code"] for s in result]
        assert "003" in codes

    def test_negative_pv_divergence_excluded(self):
        """背离为负(pv_div<=0) + 放量 + 无下影线 → 排除"""
        stocks = [_make_stock("001", 1), _make_stock("002", 2)]
        factor_df = _make_factor_df(
            stocks,
            vol_shrink={"001": 1.5, "002": 1.5},
            pv_div={"001": -0.05, "002": 0.0},
            lower_shadow={"001": 0.1, "002": 0.1},
        )
        result, excluded = apply_stabilization_filter(stocks, factor_df, top_n=2)
        assert excluded == 2
        assert len(result) == 2  # 递补


class TestStabilizationFilterBackwardCompat:
    """向后兼容：数据不可用时跳过过滤"""

    def test_no_confirmation_columns_skips_filter(self):
        """确认信号因子列不存在 → 跳过过滤"""
        stocks = [_make_stock("001", 1), _make_stock("002", 2)]
        factor_df = pd.DataFrame({"asset": ["001", "002"]})
        result, excluded = apply_stabilization_filter(stocks, factor_df, top_n=2)
        assert len(result) == 2
        assert excluded == 0

    def test_all_nan_values_skips_filter(self):
        """确认信号因子值全 NaN → 跳过过滤"""
        stocks = [_make_stock("001", 1), _make_stock("002", 2)]
        factor_df = _make_factor_df(
            stocks,
            vol_shrink={"001": np.nan, "002": np.nan},
        )
        result, excluded = apply_stabilization_filter(stocks, factor_df, top_n=2)
        assert len(result) == 2
        assert excluded == 0


class TestStabilizationFilterRankAndBackfill:
    """rank 重新编号 + 递补"""

    def test_rank_renumbered_after_filter(self):
        """过滤后 rank 从1开始重新编号"""
        stocks = [_make_stock(f"00{i}", i) for i in range(1, 5)]
        factor_df = _make_factor_df(
            stocks,
            vol_shrink={"001": 1.5, "002": 0.5, "003": 1.5, "004": 0.8},
        )
        result, _ = apply_stabilization_filter(stocks, factor_df, top_n=2)
        assert result[0]["rank"] == 1
        assert result[1]["rank"] == 2

    def test_backfill_when_insufficient(self):
        """过滤后不足 top_n → 用被排除的股票递补"""
        stocks = [_make_stock(f"00{i}", i) for i in range(1, 5)]
        factor_df = _make_factor_df(
            stocks,
            vol_shrink={"001": 0.5, "002": 1.5, "003": 1.5, "004": 1.5},
        )
        # 只有 001 通过，需要 3 个 → 递补 002, 003
        result, excluded = apply_stabilization_filter(stocks, factor_df, top_n=3)
        assert len(result) == 3
        assert excluded == 3
        # 递补的股票有 stabilization_warning 标记
        warnings = [s for s in result if s.get("stabilization_warning")]
        assert len(warnings) == 2
