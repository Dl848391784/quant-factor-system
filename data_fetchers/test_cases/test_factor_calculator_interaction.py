"""交互因子族（interaction_*）计算函数单元测试

测试目标:
- calculate_interaction_amplitude
- calculate_interaction_turnover
- calculate_interaction_amp_compression
- _cross_section_zscore（截面 z-score helper）

测试覆盖:
1. 正常计算: z-score 截面属性 + 乘法叠加
2. 信号方向（第一性原理验证）:
   - 弱势×高因子 = 正向 (反弹型)
   - 弱势×低因子 = 负向 (阴跌型)
   - 强势×高因子 = 负向 (高位风险)
   - 强势×低因子 = 正向 (平稳型)
3. 边界:
   - 缺失必需列 → ValueError
   - NaN 传播（不污染其他行）
   - 截面 std=0 → 防除零（结果接近 0）
   - 极端值 → clip ±3σ

设计依据: designs/feat_interaction_factors.md §4-6 + skill ref conditional-ic-analysis.md
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from data_fetchers.factor_calculator import (
    calculate_interaction_amp_compression,
    calculate_interaction_amplitude,
    calculate_interaction_turnover,
)
from data_fetchers.factor_calculator._common import _cross_section_zscore


# ============================================================================
# fixtures
# ============================================================================


@pytest.fixture
def sample_df():
    """3 日 × 4 股 的截面数据，包含所有交互因子所需输入列"""
    np.random.seed(42)
    n_dates = 3
    n_assets = 4
    dates = pd.Series(["2026-01-01"] * n_assets + ["2026-01-02"] * n_assets + ["2026-01-03"] * n_assets)
    assets = pd.Series(["A", "B", "C", "D"] * n_dates)
    return pd.DataFrame(
        {
            "date": dates,
            "asset": assets,
            "return_3d": np.random.randn(n_dates * n_assets) * 0.05,
            "amplitude": np.abs(np.random.randn(n_dates * n_assets)) * 0.03,
            "turnover_rate": np.abs(np.random.randn(n_dates * n_assets)) * 5,
            "amplitude_compression": np.random.randn(n_dates * n_assets) + 1.0,
        }
    )


@pytest.fixture
def signal_df():
    """信号方向测试：4 种组合（弱势/强势 × 高/低因子）"""
    return pd.DataFrame(
        {
            "date": ["2026-01-01"] * 4,
            "asset": ["weak_high", "weak_low", "strong_high", "strong_low"],
            "return_3d": [-0.10, -0.10, 0.10, 0.10],  # 前2弱势 / 后2强势
            "amplitude": [0.05, 0.01, 0.05, 0.01],  # 1/3 高 / 2/4 低
            "turnover_rate": [5.0, 1.0, 5.0, 1.0],
            "amplitude_compression": [1.5, 0.5, 1.5, 0.5],
        }
    )


# ============================================================================
# _cross_section_zscore（helper）
# ============================================================================


class TestCrossSectionZScore:
    """截面 z-score helper 行为"""

    def test_basic_zscore(self):
        """正常情况：截面 z-score 均值≈0，标准差≈1"""
        n_per_day = 100
        dates = pd.Series(["2026-01-01"] * n_per_day + ["2026-01-02"] * n_per_day)
        np.random.seed(0)
        value = pd.Series(np.random.randn(n_per_day * 2))
        z = _cross_section_zscore(value, dates)
        # 按日期检查
        for d in dates.unique():
            mask = dates == d
            assert abs(z[mask].mean()) < 0.01, f"截面 {d} 均值应接近 0"
            # std 不严格=1 是因为 clip ±3σ 会略微缩小尾部
            assert 0.95 <= z[mask].std() <= 1.05, f"截面 {d} std 应接近 1"

    def test_zero_std_handling(self):
        """截面 std=0（同日所有值相等）→ 防除零，结果接近 0"""
        dates = pd.Series(["2026-01-01"] * 5)
        value = pd.Series([3.0] * 5)
        z = _cross_section_zscore(value, dates)
        # std=0 + std_min=1e-10 → 分母极小 → 但分子也是 0，结果 NaN 或 0
        # 实际 (x - mean)/(std+eps) = 0/eps = 0
        assert (z.abs() < 1e-5).all(), "截面 std=0 时 z-score 应接近 0"

    def test_clip(self):
        """极端值被 clip 到 ±3σ"""
        dates = pd.Series(["2026-01-01"] * 100)
        np.random.seed(1)
        # 1 个极端值 + 99 个正常值
        value = pd.Series(np.concatenate([[1000.0], np.random.randn(99) * 0.1]))
        z = _cross_section_zscore(value, dates, clip_sigma=3.0)
        # 极端值应被 clip 到 ±3.0
        assert z.iloc[0] == 3.0, "极端正值应被 clip 到 +3σ"
        assert (z.abs() <= 3.0).all(), "所有 z-score 应在 ±3σ 范围内"

    def test_nan_propagation(self):
        """NaN 输入直接传播，不影响其他行"""
        dates = pd.Series(["2026-01-01"] * 5)
        value = pd.Series([1.0, 2.0, np.nan, 4.0, 5.0])
        z = _cross_section_zscore(value, dates)
        assert pd.isna(z.iloc[2]), "NaN 输入应传播为 NaN"
        assert z.iloc[[0, 1, 3, 4]].notna().all(), "其他行不应受影响"

    def test_length_mismatch_raises(self):
        """value 和 dates 长度不一致 → ValueError"""
        with pytest.raises(ValueError, match="长度不一致"):
            _cross_section_zscore(
                pd.Series([1.0, 2.0]),
                pd.Series(["2026-01-01"]),
            )


# ============================================================================
# 计算函数：interaction_amplitude
# ============================================================================


class TestCalculateInteractionAmplitude:
    """interaction_amplitude = -z_cs(return_3d) × z_cs(amplitude)"""

    def test_basic_calculation(self, sample_df):
        """正常计算路径不报错，且产出列在 DataFrame 中"""
        result = calculate_interaction_amplitude(sample_df)
        assert "interaction_amplitude" in result.columns
        assert len(result) == len(sample_df)

    def test_signal_direction_first_principles(self, signal_df):
        """第一性原理验证（design.md §2.1）:
        - 弱势(return_3d 低) × 高振幅 → 正值 (反弹型)
        - 弱势 × 低振幅 → 负值 (阴跌型)
        - 强势(return_3d 高) × 高振幅 → 负值 (高位风险)
        - 强势 × 低振幅 → 正值 (平稳型)
        """
        result = calculate_interaction_amplitude(signal_df)
        vals = dict(zip(result["asset"], result["interaction_amplitude"]))
        assert vals["weak_high"] > 0, "弱势×高振幅 应为正 (反弹型)"
        assert vals["weak_low"] < 0, "弱势×低振幅 应为负 (阴跌型)"
        assert vals["strong_high"] < 0, "强势×高振幅 应为负 (高位风险)"
        assert vals["strong_low"] > 0, "强势×低振幅 应为正 (平稳型)"

    def test_missing_column_raises(self, sample_df):
        """缺失必需列 → ValueError"""
        with pytest.raises(ValueError, match="缺失必需列"):
            calculate_interaction_amplitude(sample_df.drop(columns=["amplitude"]))

    def test_nan_propagation(self, sample_df):
        """amplitude NaN → interaction_amplitude NaN"""
        df = sample_df.copy()
        df.loc[0, "amplitude"] = np.nan
        result = calculate_interaction_amplitude(df)
        assert pd.isna(result.loc[0, "interaction_amplitude"]), "NaN 应传播"
        # 其他行不受影响（除非同日 std 计算被波及）
        assert result.loc[1:, "interaction_amplitude"].notna().sum() > 0

    def test_does_not_mutate_input(self, sample_df):
        """输入 DataFrame 不被原地修改（MODULE.md 约束）"""
        original_cols = list(sample_df.columns)
        _ = calculate_interaction_amplitude(sample_df)
        assert list(sample_df.columns) == original_cols, "输入 DataFrame 列不应被修改"


# ============================================================================
# 计算函数：interaction_turnover
# ============================================================================


class TestCalculateInteractionTurnover:
    """interaction_turnover = -z_cs(return_3d) × z_cs(turnover_rate)"""

    def test_basic_calculation(self, sample_df):
        result = calculate_interaction_turnover(sample_df)
        assert "interaction_turnover" in result.columns

    def test_signal_direction(self, signal_df):
        result = calculate_interaction_turnover(signal_df)
        vals = dict(zip(result["asset"], result["interaction_turnover"]))
        assert vals["weak_high"] > 0
        assert vals["weak_low"] < 0
        assert vals["strong_high"] < 0
        assert vals["strong_low"] > 0

    def test_missing_column_raises(self, sample_df):
        with pytest.raises(ValueError, match="缺失必需列"):
            calculate_interaction_turnover(sample_df.drop(columns=["turnover_rate"]))


# ============================================================================
# 计算函数：interaction_amp_compression
# ============================================================================


class TestCalculateInteractionAmpCompression:
    """interaction_amp_compression = -z_cs(return_3d) × z_cs(amplitude_compression)"""

    def test_basic_calculation(self, sample_df):
        result = calculate_interaction_amp_compression(sample_df)
        assert "interaction_amp_compression" in result.columns

    def test_signal_direction(self, signal_df):
        result = calculate_interaction_amp_compression(signal_df)
        vals = dict(zip(result["asset"], result["interaction_amp_compression"]))
        assert vals["weak_high"] > 0
        assert vals["weak_low"] < 0
        assert vals["strong_high"] < 0
        assert vals["strong_low"] > 0

    def test_missing_column_raises(self, sample_df):
        with pytest.raises(ValueError, match="缺失必需列"):
            calculate_interaction_amp_compression(sample_df.drop(columns=["amplitude_compression"]))


# ============================================================================
# required_cols 属性验证（与 FactorSpec 派生联动）
# ============================================================================


class TestRequiredColsAttribute:
    """3 个计算函数的 required_cols 属性正确暴露（被 FactorSpec 自动派生使用）"""

    def test_interaction_amplitude_required_cols(self):
        assert calculate_interaction_amplitude.required_cols == [
            "date",
            "asset",
            "return_3d",
            "amplitude",
        ]

    def test_interaction_turnover_required_cols(self):
        assert calculate_interaction_turnover.required_cols == [
            "date",
            "asset",
            "return_3d",
            "turnover_rate",
        ]

    def test_interaction_amp_compression_required_cols(self):
        assert calculate_interaction_amp_compression.required_cols == [
            "date",
            "asset",
            "return_3d",
            "amplitude_compression",
        ]
