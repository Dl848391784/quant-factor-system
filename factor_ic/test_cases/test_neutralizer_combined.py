"""联合中性化集成测试（P2.3）。

测试目标:
    - 单 numerical provider 路径跑通，残差均值约 0
    - IndustryProvider + LogMarketCapProvider 双 control 路径跑通
    - 含 numerical 时 categorical 自动 drop_first=True，共线性护栏生效
    - LogMarketCapProvider 小样本过滤可跳过部分日期

说明:
    P2 只引入 Provider 与 neutralizer 能力，不改变 runner 默认行为；
    因此本测试直接构造已合并控制列的 factor_df，手动传 providers。

参考: designs/feat_neutralization_framework.md §9.2（P2.3）
"""

from __future__ import annotations

import pandas as pd
import pytest

from factor_ic.common.control_providers import IndustryProvider, LogMarketCapProvider
from factor_ic.common.control_providers.base import ControlProvider
from factor_ic.common.neutralizer import _build_design_matrix, neutralize


def _combined_factor_df() -> pd.DataFrame:
    """两天、两行业、每行业 3 只股票的可回归样本。"""
    rows = []
    assets = ["000001", "000002", "000003", "000004", "000005", "000006"]
    industries = ["银行", "银行", "银行", "医药", "医药", "医药"]
    caps = [10.0, 11.0, 12.0, 20.0, 21.0, 22.0]
    for date_idx, date in enumerate(["2024-01-01", "2024-01-02"]):
        for i, (asset, industry, cap) in enumerate(zip(assets, industries, caps, strict=True)):
            # 因子由行业 + 市值 + 少量 idiosyncratic 组成；OLS 后残差应均值约 0
            factor = (1.5 if industry == "银行" else -0.5) + 0.2 * cap + (i - 2.5) * 0.01 + date_idx * 0.03
            rows.append(
                {
                    "date": date,
                    "asset": asset,
                    "factor": factor,
                    "industry": industry,
                    "log_market_cap": cap,
                }
            )
    return pd.DataFrame(rows)


class TestDesignMatrixCollinearityGuard:
    def test_combined_controls_drop_first_for_industry(self):
        df = _combined_factor_df()
        day_df = df.loc[df["date"] == "2024-01-01"].copy()
        providers: list[ControlProvider] = [IndustryProvider(), LogMarketCapProvider()]

        x = _build_design_matrix(day_df, providers, has_numerical=True)

        # 两个行业 + numerical 时，categorical drop_first=True → 1 个行业哑变量 + 1 个市值列
        assert x.shape == (6, 2)
        assert "log_market_cap" in x.columns
        assert len([c for c in x.columns if c != "log_market_cap"]) == 1

    def test_industry_only_keeps_all_dummies_for_p1_parity(self):
        df = _combined_factor_df()
        day_df = df.loc[df["date"] == "2024-01-01"].copy()
        providers: list[ControlProvider] = [IndustryProvider()]

        x = _build_design_matrix(day_df, providers, has_numerical=False)

        # P1 legacy parity: 纯 categorical 保留全部行业哑变量
        assert x.shape == (6, 2)
        assert set(x.columns) == {"银行", "医药"}


class TestCombinedNeutralization:
    def test_log_market_cap_only_residual_mean_zero_per_day(self):
        df = _combined_factor_df()
        provider = LogMarketCapProvider()

        residual = neutralize(df, [provider], factor_col="factor", min_count=3)

        assert len(residual) == len(df)
        merged = residual.merge(df[["date", "asset"]], on=["date", "asset"], how="inner")
        assert len(merged) == len(residual)
        for _, day in residual.groupby("date"):
            assert day["neutral_factor"].mean() == pytest.approx(0.0, abs=1e-6)

    def test_industry_and_log_market_cap_combined_residual_mean_zero(self):
        df = _combined_factor_df()
        providers = [IndustryProvider(), LogMarketCapProvider()]

        residual = neutralize(df, providers, factor_col="factor", min_count=3)

        assert len(residual) == len(df)
        assert set(residual.columns) == {"date", "asset", "neutral_factor"}
        for _, day in residual.groupby("date"):
            assert day["neutral_factor"].mean() == pytest.approx(0.0, abs=1e-6)

    def test_log_market_cap_small_day_skipped(self):
        df = _combined_factor_df()
        # 第二天只保留 2 行，小于 min_count=3；第一天仍完整保留
        mask = (df["date"] == "2024-01-01") | ((df["date"] == "2024-01-02") & (df["asset"].isin(["000001", "000002"])))
        small_df = df.loc[mask].copy()

        residual = neutralize(small_df, [LogMarketCapProvider()], factor_col="factor", min_count=3)

        assert set(residual["date"]) == {"2024-01-01"}
        assert len(residual) == 6

    def test_combined_controls_with_small_industry_filter(self):
        df = _combined_factor_df()
        # 第二天医药只剩 2 行；IndustryProvider(min_count=3) 会剔除医药，银行仍可回归
        mask = ~((df["date"] == "2024-01-02") & (df["asset"] == "000006"))
        filtered_df = df.loc[mask].copy()

        residual = neutralize(
            filtered_df, [IndustryProvider(), LogMarketCapProvider()], factor_col="factor", min_count=3
        )

        day2_assets = set(residual.loc[residual["date"] == "2024-01-02", "asset"])
        assert day2_assets == {"000001", "000002", "000003"}
        assert len(residual) == 9
