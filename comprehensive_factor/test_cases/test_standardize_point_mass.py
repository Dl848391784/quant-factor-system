"""点质量检测测试：standardize_factors 中 z-score 置 NaN 逻辑。

测试场景：
1. 点质量检出：2.3% 重复值 → z-score 置 NaN
2. 正常分布无误触发：连续值 < 1% 重复 → z-score 正常
3. 多日期独立检测：每个日期截面独立判定
4. NaN 不干扰检测：原始 NaN 不影响点质量频率计算
"""

import numpy as np
import pandas as pd
import pytest
from comprehensive_factor.common.factor_loader import standardize_factors


class TestPointMassDetection:
    """点质量检测测试。"""

    @staticmethod
    def _build_df(
        values: list[float],
        n_dates: int = 1,
        date_col: str = "2026-06-18",
    ) -> pd.DataFrame:
        """构造单因子 DataFrame。"""
        n = len(values)
        dates = (
            [date_col] * n
            if n_dates == 1
            else [f"2026-06-{18 + i:02d}" for i in range(n_dates) for _ in range(n // n_dates)]
        )
        return pd.DataFrame(
            {
                "date": dates[:n],
                "asset": [f"stock_{i:04d}" for i in range(n)],
                "test_factor": values,
            }
        )

    def test_point_mass_set_to_nan(self):
        """2.3% 重复值（0.0）→ z-score 置 NaN。"""
        # 构造 300 只股票，7 只 (2.3%) 的值为 0.0
        # uniform(0.2, 1.0) 使 0.0 的 z-score < -2.0，触发点质量检测
        rng = np.random.RandomState(42)
        normal_values = rng.uniform(0.2, 1.0, size=293).tolist()
        point_mass_values = [0.0] * 7
        all_values = normal_values + point_mass_values

        df = self._build_df(all_values)
        result = standardize_factors(df, ["test_factor"])

        # 点质量股票的 z-score 应为 NaN
        point_mass_z = result.loc[result["test_factor"] == 0.0, "test_factor_std"]
        assert point_mass_z.isna().all(), f"点质量 z-score 应为 NaN, 实际: {point_mass_z.values}"

        # 非点质量股票的 z-score 不受影响（在 ±3σ 范围内）
        normal_z = result.loc[result["test_factor"] != 0.0, "test_factor_std"]
        assert normal_z.abs().max() <= 3.0

    def test_no_nan_for_normal_distribution(self):
        """连续值 < 1% 重复 → z-score 正常，不触发置 NaN。"""
        rng = np.random.RandomState(42)
        # 300 只股票，每个值唯一（0% 重复）
        values = rng.randn(300).tolist()

        df = self._build_df(values)
        result = standardize_factors(df, ["test_factor"])

        # 所有 z-score 应在 ±3σ 范围内（Winsorize），但不被置 NaN
        z_scores = result["test_factor_std"]
        # 至少有一些 z-score 绝对值 > 2.0（证明没有被误处理）
        assert z_scores.abs().max() > 2.0, f"正常分布应有 z-score > 2.0, 实际 max={z_scores.abs().max()}"
        # 不应有非预期 NaN
        assert z_scores.notna().all(), f"正常分布不应有 NaN, 实际 NaN 数: {z_scores.isna().sum()}"

    def test_multi_date_independent(self):
        """多日期截面独立检测：日期 A 有点质量，日期 B 无。"""
        rng = np.random.RandomState(42)
        # 日期 A：300 只，7 只为 0.0（2.3% > 1%）
        values_a = rng.uniform(0.2, 1.0, size=293).tolist() + [0.0] * 7
        # 日期 B：300 只，全部唯一（0% 重复）
        values_b = rng.randn(300).tolist()

        df_a = pd.DataFrame(
            {"date": ["2026-06-18"] * 300, "asset": [f"s_{i:04d}" for i in range(300)], "test_factor": values_a}
        )
        df_b = pd.DataFrame(
            {"date": ["2026-06-19"] * 300, "asset": [f"s_{i:04d}" for i in range(300)], "test_factor": values_b}
        )
        df = pd.concat([df_a, df_b], ignore_index=True)

        result = standardize_factors(df, ["test_factor"])

        # 日期 A 的 0.0 股票应被置 NaN
        mask_a = (result["date"] == "2026-06-18") & (result["test_factor"] == 0.0)
        z_a = result.loc[mask_a, "test_factor_std"]
        assert z_a.isna().all(), f"日期 A 点质量 z-score 应为 NaN, 实际: {z_a.values}"

        # 日期 B 应有 z-score > 2.0（未被误处理）
        mask_b = result["date"] == "2026-06-19"
        z_b = result.loc[mask_b, "test_factor_std"]
        assert z_b.abs().max() > 2.0, f"日期 B 应有 z-score > 2.0, 实际 max={z_b.abs().max()}"

    def test_nan_does_not_affect_frequency(self):
        """原始 NaN 不影响点质量频率计算。"""
        rng = np.random.RandomState(42)
        # 300 只股票：280 有效值 + 20 NaN + 7 个 0.0
        # 有效非 NaN 数 = 287，7/287 = 2.4% > 1% → 触发
        normal_values = rng.uniform(0.2, 1.0, size=280).tolist()
        nan_values = [np.nan] * 20
        point_mass_values = [0.0] * 7
        all_values = normal_values + nan_values + point_mass_values

        df = self._build_df(all_values)
        result = standardize_factors(df, ["test_factor"])

        # 点质量股票的 z-score 应为 NaN
        point_mass_z = result.loc[result["test_factor"] == 0.0, "test_factor_std"]
        assert point_mass_z.isna().all()

        # 原始 NaN 股票的 z-score 应为 NaN
        nan_z = result.loc[result["test_factor"].isna(), "test_factor_std"]
        assert nan_z.isna().all()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
