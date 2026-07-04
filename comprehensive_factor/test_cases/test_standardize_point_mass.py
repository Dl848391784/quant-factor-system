"""点质量检测测试：standardize_factors 中 z-score 置 NaN 逻辑。

测试场景：
1. 点质量检出：2.3% 重复值 → z-score 置 NaN
2. 正常分布无误触发：连续值 < 1% 重复 → z-score 正常
3. 多日期独立检测：每个日期截面独立判定
4. NaN 不干扰检测：原始 NaN 不影响点质量频率计算
5. v2.26: 离散型因子豁免（unique/N < 5% 或 unique < 20）
6. v2.27: 物理边界值豁免（高频值=截面 min/max 时不置 NaN）

v2.27 注意：点质量测试值必须用非边界值（如 0.5），不能用 0.0/1.0，
因为 0.0/1.0 会被物理边界豁免。正常值分布在 [0, 0.2] 和 [0.8, 1.0]
两段，0.5 在中间，z ≈ 2.07 > 1.0 触发点质量检测。
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
        """2.3% 重复值（0.5，非边界中间值）→ z-score 置 NaN。

        v2.27: 点质量值必须是非边界值（0.0/1.0 会被物理边界豁免）。
        正常值分布在 [0, 0.2] 和 [0.8, 1.0] 两段，0.5 在中间，
        z ≈ 2.07 > 1.0 触发点质量检测。
        """
        rng = np.random.RandomState(42)
        low_values = rng.uniform(0.0, 0.2, size=280).tolist()
        high_values = rng.uniform(0.8, 1.0, size=13).tolist()
        point_mass_values = [0.5] * 7
        all_values = low_values + high_values + point_mass_values

        df = self._build_df(all_values)
        result = standardize_factors(df, ["test_factor"])

        # 点质量股票的 z-score 应为 NaN
        point_mass_z = result.loc[result["test_factor"] == 0.5, "test_factor_std"]
        assert point_mass_z.isna().all(), f"点质量 z-score 应为 NaN, 实际: {point_mass_z.values}"

        # 非点质量股票的 z-score 不受影响（在 ±3σ 范围内）
        normal_z = result.loc[result["test_factor"] != 0.5, "test_factor_std"]
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
        # 日期 A：300 只，7 只为 0.5（2.3% > 1%，非边界中间值）
        values_a = rng.uniform(0.0, 0.2, size=280).tolist() + rng.uniform(0.8, 1.0, size=13).tolist() + [0.5] * 7
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

        # 日期 A 的 0.5 股票应被置 NaN（非边界点质量）
        mask_a = (result["date"] == "2026-06-18") & (result["test_factor"] == 0.5)
        z_a = result.loc[mask_a, "test_factor_std"]
        assert z_a.isna().all(), f"日期 A 点质量 z-score 应为 NaN, 实际: {z_a.values}"

        # 日期 B 应有 z-score > 2.0（未被误处理）
        mask_b = result["date"] == "2026-06-19"
        z_b = result.loc[mask_b, "test_factor_std"]
        assert z_b.abs().max() > 2.0, f"日期 B 应有 z-score > 2.0, 实际 max={z_b.abs().max()}"

    def test_nan_does_not_affect_frequency(self):
        """原始 NaN 不影响点质量频率计算。"""
        rng = np.random.RandomState(42)
        # 300 只股票：260 低值 + 13 高值 + 20 NaN + 7 个 0.5（非边界）
        # 有效非 NaN 数 = 280，7/280 = 2.5% > 1% → 触发
        low_values = rng.uniform(0.0, 0.2, size=260).tolist()
        high_values = rng.uniform(0.8, 1.0, size=13).tolist()
        nan_values = [np.nan] * 20
        point_mass_values = [0.5] * 7
        all_values = low_values + high_values + nan_values + point_mass_values

        df = self._build_df(all_values)
        result = standardize_factors(df, ["test_factor"])

        # 点质量股票的 z-score 应为 NaN
        point_mass_z = result.loc[result["test_factor"] == 0.5, "test_factor_std"]
        assert point_mass_z.isna().all()

        # 原始 NaN 股票的 z-score 应为 NaN
        nan_z = result.loc[result["test_factor"].isna(), "test_factor_std"]
        assert nan_z.isna().all()


class TestDiscreteFactorExemption:
    """v2.26: 离散型因子豁免点质量检测。"""

    @staticmethod
    def _build_df(values: list[float], date_str: str = "2026-06-18") -> pd.DataFrame:
        n = len(values)
        return pd.DataFrame(
            {
                "date": [date_str] * n,
                "asset": [f"stock_{i:04d}" for i in range(n)],
                "test_factor": values,
            }
        )

    def test_discrete_factor_no_point_mass(self):
        """离散型因子（unique < 20）即使高频聚集也不置 NaN。

        模拟 positive_day_ratio_5：6 个离散值，每个 >1% 频率，
        4 个值 |z|>1.0 ——若无豁免，80%+ 股票被置 NaN。
        """
        # 300 只股票，6 个离散值（模拟 5 日上涨比例）
        # 0.0:88, 0.2:588, 0.4:965, 0.6:904, 0.8:406, 1.0:70（≈真实分布）
        values = [0.0] * 9 + [0.2] * 59 + [0.4] * 96 + [0.6] * 90 + [0.8] * 41 + [1.0] * 5
        df = self._build_df(values)
        result = standardize_factors(df, ["test_factor"])

        # 离散因子：所有 z-score 都不应被置 NaN（豁免点质量检测）
        z_scores = result["test_factor_std"]
        nan_count = z_scores.isna().sum()
        assert nan_count == 0, f"离散因子不应有点质量 NaN, 实际 NaN 数: {nan_count}/{len(z_scores)}"

    def test_discrete_factor_by_ratio(self):
        """离散型因子（unique/N < 5%）豁免。

        300 只股票，15 个离散值（unique/N = 5%），每个值出现 20 次。
        """
        values = []
        for v in range(15):
            values.extend([float(v)] * 20)
        df = self._build_df(values)
        result = standardize_factors(df, ["test_factor"])

        z_scores = result["test_factor_std"]
        assert z_scores.isna().sum() == 0, "unique/N < 5% 的离散因子不应有点质量 NaN"

    def test_continuous_factor_still_detected(self):
        """连续型因子仍执行点质量检测（豁免不影响连续因子）。

        v2.27: 点质量值用 0.5（非边界），避免被物理边界豁免。
        """
        # 300 只股票：280 个 uniform(0,0.2) + 13 个 uniform(0.8,1.0) + 7 个 0.5
        # 0.5 不是 min/max，z ≈ 2.07 > 1.0 → 触发点质量检测
        rng = np.random.RandomState(42)
        low_values = rng.uniform(0.0, 0.2, size=280).tolist()
        high_values = rng.uniform(0.8, 1.0, size=13).tolist()
        point_mass_values = [0.5] * 7
        all_values = low_values + high_values + point_mass_values

        df = self._build_df(all_values)
        result = standardize_factors(df, ["test_factor"])

        # 连续因子：0.5 点质量应被检测到并置 NaN
        point_mass_z = result.loc[result["test_factor"] == 0.5, "test_factor_std"]
        assert point_mass_z.isna().all(), "连续因子的非边界点质量仍应被检测"

    def test_mixed_date_discrete_and_continuous(self):
        """多日期：离散日期豁免，连续日期正常检测。"""
        # 日期 A：离散因子（6 个值）
        values_a = [0.0] * 50 + [0.2] * 100 + [0.4] * 100 + [0.6] * 50
        # 日期 B：连续因子 + 非边界点质量（0.5）
        rng = np.random.RandomState(42)
        values_b = rng.uniform(0.0, 0.2, size=280).tolist() + rng.uniform(0.8, 1.0, size=13).tolist() + [0.5] * 7

        df = pd.DataFrame(
            {
                "date": ["2026-06-18"] * 300 + ["2026-06-19"] * 300,
                "asset": [f"s_{i:04d}" for i in range(600)],
                "test_factor": values_a + values_b,
            }
        )
        result = standardize_factors(df, ["test_factor"])

        # 日期 A（离散）：无 NaN
        z_a = result.loc[result["date"] == "2026-06-18", "test_factor_std"]
        assert z_a.isna().sum() == 0, "离散日期不应有点质量 NaN"

        # 日期 B（连续）：0.5 非边界点质量被置 NaN
        mask_b_pm = (result["date"] == "2026-06-19") & (result["test_factor"] == 0.5)
        z_b_pm = result.loc[mask_b_pm, "test_factor_std"]
        assert z_b_pm.isna().all(), "连续日期的非边界点质量仍应被检测"


class TestPhysicalBoundaryExemption:
    """v2.27: 物理边界值豁免——高频值=当日截面 min/max 时不置 NaN。

    有界分布(如 [0,1])的边界值是真实极端信号，不是数据噪声。
    tail_price_position=0.0 表示价格触底，11% 股票触底在下跌市中正常。
    点质量检测应只针对中间值的异常聚集。
    """

    @staticmethod
    def _build_df(values: list[float], date_str: str = "2026-06-18") -> pd.DataFrame:
        n = len(values)
        return pd.DataFrame(
            {
                "date": [date_str] * n,
                "asset": [f"stock_{i:04d}" for i in range(n)],
                "test_factor": values,
            }
        )

    def test_boundary_min_exempt(self):
        """高频值=截面 min 时不置 NaN。

        模拟 tail_price_position：0.0 是物理下界，11% 股票触底，
        z=-1.50 > 1.0 ——若无豁免，336 只被置 NaN。
        """
        # 300 只股票，0.0 出现 33 次(11%)，其余连续分布在 [0.01, 1.0]
        rng = np.random.RandomState(42)
        normal_values = rng.uniform(0.01, 1.0, size=267).tolist()
        boundary_values = [0.0] * 33
        all_values = normal_values + boundary_values

        df = self._build_df(all_values)
        result = standardize_factors(df, ["test_factor"])

        # 0.0 是截面 min → 豁免，不应被置 NaN
        boundary_z = result.loc[result["test_factor"] == 0.0, "test_factor_std"]
        assert boundary_z.notna().all(), f"物理边界 min=0.0 应豁免点质量检测, 实际 NaN 数: {boundary_z.isna().sum()}"

    def test_boundary_max_exempt(self):
        """高频值=截面 max 时不置 NaN。

        模拟 near_high_ratio_5：1.0 是物理上界，15% 股票创新高，
        z=1.77 > 1.0 ——若无豁免，467 只被置 NaN。
        """
        # 300 只股票，1.0 出现 45 次(15%)，其余连续分布在 [0.0, 0.99]
        rng = np.random.RandomState(42)
        normal_values = rng.uniform(0.0, 0.99, size=255).tolist()
        boundary_values = [1.0] * 45
        all_values = normal_values + boundary_values

        df = self._build_df(all_values)
        result = standardize_factors(df, ["test_factor"])

        # 1.0 是截面 max → 豁免，不应被置 NaN
        boundary_z = result.loc[result["test_factor"] == 1.0, "test_factor_std"]
        assert boundary_z.notna().all(), f"物理边界 max=1.0 应豁免点质量检测, 实际 NaN 数: {boundary_z.isna().sum()}"

    def test_interior_point_mass_still_detected(self):
        """非边界中间值的高频聚集仍被检测。

        模拟：0.5 出现 15 次(5%)，不是 min/max，
        z ≈ 2.4 > 1.0 → 异常聚集（可能是计算 bug），仍应被置 NaN。
        """
        # 300 只股票：280 个 uniform(0,0.2) + 5 个 uniform(0.8,1.0) + 15 个 0.5（5%，中间值）
        # 0.5 不是 min(0附近)/max(1附近)，z ≈ 2.4 > 1.0 → 触发点质量检测
        rng = np.random.RandomState(42)
        low_values = rng.uniform(0.0, 0.2, size=280).tolist()
        high_values = rng.uniform(0.8, 1.0, size=5).tolist()
        interior_mass_values = [0.5] * 15
        all_values = low_values + high_values + interior_mass_values

        df = self._build_df(all_values)
        result = standardize_factors(df, ["test_factor"])

        # 0.5 不是 min 也不是 max → 不豁免，应被置 NaN
        interior_z = result.loc[result["test_factor"] == 0.5, "test_factor_std"]
        assert interior_z.isna().all(), f"非边界中间值的高频聚集应被检测, 实际 NaN 数: {interior_z.isna().sum()}"

    def test_both_boundaries_exempt(self):
        """0.0 和 1.0 同时高频时都豁免。

        模拟 tail_price_position：0.0(11%) 和 1.0(7%) 同时高频。
        """
        rng = np.random.RandomState(42)
        normal_values = rng.uniform(0.01, 0.99, size=246).tolist()
        min_values = [0.0] * 30  # 10%
        max_values = [1.0] * 24  # 8%
        all_values = normal_values + min_values + max_values

        df = self._build_df(all_values)
        result = standardize_factors(df, ["test_factor"])

        # 0.0 = min → 豁免
        min_z = result.loc[result["test_factor"] == 0.0, "test_factor_std"]
        assert min_z.notna().all(), "物理边界 min=0.0 应豁免"

        # 1.0 = max → 豁免
        max_z = result.loc[result["test_factor"] == 1.0, "test_factor_std"]
        assert max_z.notna().all(), "物理边界 max=1.0 应豁免"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
