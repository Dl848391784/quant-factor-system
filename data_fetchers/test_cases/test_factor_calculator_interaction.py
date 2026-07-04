"""交互因子族（interaction_*__ret<N>d_<pos|neg|abs>）计算函数单元测试

v2.48 重构 (designs/feat_factor_definition_destigmatization_v1.md v1.2):
- 旧 9 个交互因子单边公式 `-z_cs(ret) × z_cs(X)` → 27 个 pos/neg/abs ReLU 变体
- pos = max(z_cs(ret_Nd), 0) × z_cs(X)
- neg = min(z_cs(ret_Nd), 0) × z_cs(X)
- abs = abs(z_cs(ret_Nd)) × z_cs(X)
- 数学恒等: pos + neg = z_cs(ret_Nd) × z_cs(X), abs = |z_cs(ret_Nd)| × z_cs(X)

测试覆盖:
1. _cross_section_zscore helper 行为（5 测试，保留 v2.36 既有）
2. ReLU 数学正交性: pos+neg ≡ ret_z × factor_z, abs ≡ |ret_z| × factor_z
3. 半轴互斥性: 任一行 pos × neg ≤ 0（除两者皆 0 外不同号）
4. 9 base × 3 direction = 27 计算函数: 列名 + required_cols 正确
5. 边界: 缺列 → ValueError, NaN 传播, std=0 防除零, 极端值 clip ±3σ
6. 输入 DataFrame 不被原地修改（MODULE.md 约束）
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from data_fetchers import factor_calculator as fc
from data_fetchers.factor_calculator._common import _cross_section_zscore


# ============================================================================
# 9 base × (return_window, factor_col) 映射 — F1 重构唯一权威清单
# ============================================================================

# (base_short_name, factor_column_in_df, return_column_in_df, return_window_for_naming)
# 注意 ret1d 用 past_return_1d (T-1 历史收益, 非 forward_return_1d 预测目标)
BASES = [
    ("amplitude", "amplitude", "return_3d", 3),
    ("turnover", "turnover_rate", "return_3d", 3),
    ("amp_compression", "amplitude_compression", "return_3d", 3),
    ("near_high", "near_high_ratio_5", "return_3d", 3),
    ("intraday", "intraday_intensity", "past_return_1d", 1),
    ("ma5_dev", "ma5_deviation", "return_3d", 3),
    ("price_pos", "price_position", "past_return_1d", 1),
    ("kdj", "kdj_j", "return_5d", 5),
    ("bollinger", "bollinger_pb", "return_5d", 5),
]

DIRECTIONS = ("pos", "neg", "abs")


def factor_name(base: str, window: int, direction: str) -> str:
    return f"interaction_{base}__ret{window}d_{direction}"


def func_for(base: str, window: int, direction: str):
    return getattr(fc, f"calculate_interaction_{base}__ret{window}d_{direction}")


# ============================================================================
# fixtures
# ============================================================================


@pytest.fixture
def full_df():
    """3 日 × 4 股，包含所有 9 base 所需的 factor 列 + 3 个 return 窗口"""
    np.random.seed(42)
    n_dates, n_assets = 3, 4
    n = n_dates * n_assets
    dates = pd.Series(["2026-01-01"] * n_assets + ["2026-01-02"] * n_assets + ["2026-01-03"] * n_assets)
    assets = pd.Series(["A", "B", "C", "D"] * n_dates)
    return pd.DataFrame(
        {
            "date": dates,
            "asset": assets,
            "return_1d": np.random.randn(n) * 0.02,
            "past_return_1d": np.random.randn(n) * 0.02,
            "return_3d": np.random.randn(n) * 0.05,
            "return_5d": np.random.randn(n) * 0.07,
            "amplitude": np.abs(np.random.randn(n)) * 0.03,
            "turnover_rate": np.abs(np.random.randn(n)) * 5,
            "amplitude_compression": np.random.randn(n) + 1.0,
            "near_high_ratio_5": np.clip(np.random.randn(n) * 0.3 + 0.6, 0.0, 1.0),
            "intraday_intensity": np.random.randn(n),
            "ma5_deviation": np.random.randn(n) * 0.05,
            "price_position": np.clip(np.random.randn(n) * 0.3 + 0.5, 0.0, 1.0),
            "kdj_j": np.random.randn(n) * 30 + 50,
            "bollinger_pb": np.random.randn(n) * 0.3 + 0.5,
        }
    )


# ============================================================================
# _cross_section_zscore（helper） — 行为不变, 保留 v2.36 既有 5 测试
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
        assert (z.abs() < 1e-5).all(), "截面 std=0 时 z-score 应接近 0"

    def test_clip(self):
        """极端值被 clip 到 ±3σ"""
        dates = pd.Series(["2026-01-01"] * 100)
        np.random.seed(1)
        value = pd.Series(np.concatenate([[1000.0], np.random.randn(99) * 0.1]))
        z = _cross_section_zscore(value, dates, clip_sigma=3.0)
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
# 全 27 计算函数：列名 + required_cols + 不修改输入
# ============================================================================


class TestAllVariantsBasic:
    """27 计算函数: 产出列在 DataFrame、required_cols 完整、不修改输入"""

    @pytest.mark.parametrize("base,factor_col,ret_col,window", BASES)
    @pytest.mark.parametrize("direction", DIRECTIONS)
    def test_output_column_exists(self, full_df, base, factor_col, ret_col, window, direction):
        f = func_for(base, window, direction)
        result = f(full_df)
        col = factor_name(base, window, direction)
        assert col in result.columns, f"{col} 应在输出 DataFrame 中"
        assert len(result) == len(full_df)

    @pytest.mark.parametrize("base,factor_col,ret_col,window", BASES)
    @pytest.mark.parametrize("direction", DIRECTIONS)
    def test_required_cols(self, base, factor_col, ret_col, window, direction):
        f = func_for(base, window, direction)
        assert f.required_cols == [
            "date",
            "asset",
            ret_col,
            factor_col,
        ]

    @pytest.mark.parametrize("base,factor_col,ret_col,window", BASES)
    @pytest.mark.parametrize("direction", DIRECTIONS)
    def test_does_not_mutate_input(self, full_df, base, factor_col, ret_col, window, direction):
        f = func_for(base, window, direction)
        original_cols = list(full_df.columns)
        _ = f(full_df)
        assert list(full_df.columns) == original_cols, "输入 DataFrame 列不应被修改"

    @pytest.mark.parametrize("base,factor_col,ret_col,window", BASES)
    @pytest.mark.parametrize("direction", DIRECTIONS)
    def test_missing_factor_column_raises(self, full_df, base, factor_col, ret_col, window, direction):
        f = func_for(base, window, direction)
        with pytest.raises(ValueError, match="缺失必需列"):
            f(full_df.drop(columns=[factor_col]))

    @pytest.mark.parametrize("base,factor_col,ret_col,window", BASES)
    @pytest.mark.parametrize("direction", DIRECTIONS)
    def test_missing_return_column_raises(self, full_df, base, factor_col, ret_col, window, direction):
        f = func_for(base, window, direction)
        with pytest.raises(ValueError, match="缺失必需列"):
            f(full_df.drop(columns=[ret_col]))


# ============================================================================
# ReLU 数学正交性（核心特性 — F1 重构关键不变量）
# ============================================================================


class TestRelueMathOrthogonality:
    """ReLU 切半轴数学恒等: pos+neg ≡ ret_z × factor_z, abs ≡ |ret_z| × factor_z"""

    @pytest.mark.parametrize("base,factor_col,ret_col,window", BASES)
    def test_pos_plus_neg_equals_signed_product(self, full_df, base, factor_col, ret_col, window):
        """pos + neg = z_cs(ret_Nd) × z_cs(factor)  (两 ReLU 半轴重组成全乘积)"""
        pos_col = factor_name(base, window, "pos")
        neg_col = factor_name(base, window, "neg")
        r_pos = func_for(base, window, "pos")(full_df)
        r_neg = func_for(base, window, "neg")(full_df)
        sum_half = r_pos[pos_col] + r_neg[neg_col]

        # 参考值: z(ret) × z(factor)
        ret_z = _cross_section_zscore(full_df[ret_col], full_df["date"])
        fac_z = _cross_section_zscore(full_df[factor_col], full_df["date"])
        expected = ret_z * fac_z

        np.testing.assert_allclose(
            sum_half.dropna().values,
            expected.dropna().values,
            atol=1e-9,
            err_msg=f"{base}__ret{window}d: pos+neg 应恒等 ret_z×factor_z",
        )

    @pytest.mark.parametrize("base,factor_col,ret_col,window", BASES)
    def test_abs_equals_abs_product(self, full_df, base, factor_col, ret_col, window):
        """abs = |z_cs(ret_Nd)| × z_cs(factor)"""
        abs_col = factor_name(base, window, "abs")
        r_abs = func_for(base, window, "abs")(full_df)

        ret_z = _cross_section_zscore(full_df[ret_col], full_df["date"])
        fac_z = _cross_section_zscore(full_df[factor_col], full_df["date"])
        expected = ret_z.abs() * fac_z

        np.testing.assert_allclose(
            r_abs[abs_col].dropna().values,
            expected.dropna().values,
            atol=1e-9,
            err_msg=f"{base}__ret{window}d_abs 应恒等 |ret_z|×factor_z",
        )

    @pytest.mark.parametrize("base,factor_col,ret_col,window", BASES)
    def test_pos_neg_half_axis_mutex(self, full_df, base, factor_col, ret_col, window):
        """任一行 pos × neg ≤ 0（半轴互斥, 不可能同正同负）

        因 pos = max(ret_z, 0) × factor_z, neg = min(ret_z, 0) × factor_z
        ret_z>0 时 neg=0;  ret_z<0 时 pos=0;  ret_z=0 时 pos=neg=0.
        所以 pos × neg = 0 严格成立.
        """
        pos_col = factor_name(base, window, "pos")
        neg_col = factor_name(base, window, "neg")
        r_pos = func_for(base, window, "pos")(full_df)
        r_neg = func_for(base, window, "neg")(full_df)
        product = r_pos[pos_col] * r_neg[neg_col]
        valid = product.dropna()
        assert (valid.abs() < 1e-12).all(), (
            f"{base}__ret{window}d: pos × neg 应严格为 0（半轴互斥）, max|product|={valid.abs().max():.2e}"
        )


# ============================================================================
# 边界: NaN 传播
# ============================================================================


class TestNanPropagation:
    """因子列 NaN → 输出 NaN（不污染其他行）"""

    def test_amplitude_pos_nan_propagates(self, full_df):
        df = full_df.copy()
        df.loc[0, "amplitude"] = np.nan
        result = func_for("amplitude", 3, "pos")(df)
        col = factor_name("amplitude", 3, "pos")
        assert pd.isna(result.loc[0, col]), "NaN 应传播"
        assert result.loc[1:, col].notna().sum() > 0, "其他行不应被污染"

    def test_kdj_abs_nan_propagates(self, full_df):
        df = full_df.copy()
        df.loc[5, "kdj_j"] = np.nan
        result = func_for("kdj", 5, "abs")(df)
        col = factor_name("kdj", 5, "abs")
        assert pd.isna(result.loc[5, col])


# ============================================================================
# ReLU 半轴零侧验证（结构特性）
# ============================================================================


class TestReluHalfAxisZeroSide:
    """构造 ret 全正/全负的截面, 验证另一侧严格为 0"""

    def test_all_positive_ret_means_neg_is_zero(self):
        """同日 ret 全正 → z_cs(ret) 有正有负? 实际 z_cs 中心化后必有正负 — 用极端构造"""
        # 用单股票截面 (n=1) 时 z_cs 退化, 改用 2 股极端不对称
        # 同日 ret = [+0.1, +0.1] → z 全 0 (std=0 防除零) → pos=neg=abs=0
        df = pd.DataFrame(
            {
                "date": ["2026-01-01"] * 2,
                "asset": ["A", "B"],
                "return_3d": [0.10, 0.10],  # 全相同 → z=0
                "amplitude": [0.05, 0.02],
            }
        )
        r_pos = func_for("amplitude", 3, "pos")(df)
        r_neg = func_for("amplitude", 3, "neg")(df)
        # ret_z=0 ⇒ max(0,0)=0 ⇒ pos=0; min(0,0)=0 ⇒ neg=0
        assert (r_pos[factor_name("amplitude", 3, "pos")].abs() < 1e-10).all()
        assert (r_neg[factor_name("amplitude", 3, "neg")].abs() < 1e-10).all()

    def test_asymmetric_ret_relu_cuts_correctly(self):
        """3 股：ret=[-1, 0, +1] z 后大致 [-1.22, 0, +1.22]
        → pos 只在 ret_z>0 的行非零, neg 只在 ret_z<0 的行非零
        """
        df = pd.DataFrame(
            {
                "date": ["2026-01-01"] * 3,
                "asset": ["A", "B", "C"],
                "return_3d": [-0.10, 0.0, 0.10],
                "amplitude": [0.03, 0.03, 0.03],  # 同 factor 排除干扰
            }
        )
        # amplitude 同值 → z_cs(amplitude) = 0 → pos = neg = 0 (退化)
        # 改用不同 amplitude 才看得见
        df["amplitude"] = [0.01, 0.03, 0.05]
        r_pos = func_for("amplitude", 3, "pos")(df)
        r_neg = func_for("amplitude", 3, "neg")(df)
        pos_col = factor_name("amplitude", 3, "pos")
        neg_col = factor_name("amplitude", 3, "neg")
        # ret_z=[-1.22, 0, +1.22] → pos 仅 C 非零, neg 仅 A 非零
        assert r_pos.loc[0, pos_col] == pytest.approx(0.0, abs=1e-9), "A (ret<0): pos 应=0"
        assert r_neg.loc[2, neg_col] == pytest.approx(0.0, abs=1e-9), "C (ret>0): neg 应=0"
        # 非零侧符号: factor_z[C] >0 (max amplitude); factor_z[A] <0
        assert r_pos.loc[2, pos_col] > 0, "C (ret_z>0, factor_z>0): pos 应 >0"
        assert r_neg.loc[0, neg_col] > 0, "A (ret_z<0, factor_z<0): neg 应 >0 (负×负)"
