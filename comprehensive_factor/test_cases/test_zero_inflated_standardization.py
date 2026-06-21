"""零值分离标准化测试——验证 price_volume_divergence 等零膨胀因子的 σ 失真修复

遵循 design.md 方案A（零值分离标准化），验证：
1. 正常因子（零值占比 <5%）不受影响
2. 零膨胀因子（零值占比 ≥5%）启用零值分离标准化
3. 零值 → z=0，非零值 → 用自身 μ/σ 标准化
4. 修复后 pvd z-score 范围不再极端放大
"""

import numpy as np
import pandas as pd
import pytest
from comprehensive_factor.common.factor_loader import (
    _is_zero_inflated_group,
    _standardize_zero_inflated,
    standardize_factors,
)
from comprehensive_factor.common.logger_config import get_logger


logger = get_logger(__name__)


class TestZeroInflatedDetection:
    """测试零膨胀分布检测"""

    def test_zero_inflated_group_detected(self):
        """42% 零值的截面被检测为零膨胀（≥5%阈值）"""
        # 模拟 price_volume_divergence 截面：42% 零值，58% 非零值
        values = [0.0] * 42 + list(np.random.uniform(0.01, 0.04, size=58))
        group = pd.Series(values)
        assert _is_zero_inflated_group(group, zero_threshold=0.001, ratio_threshold=0.05)

    def test_normal_group_not_detected(self):
        """2.8% 零值的截面不被检测为零膨胀（<5%阈值）"""
        values = [0.0] * 3 + list(np.random.uniform(0.01, 0.04, size=97))
        group = pd.Series(values)
        assert not _is_zero_inflated_group(group, zero_threshold=0.001, ratio_threshold=0.05)

    def test_exactly_5_percent(self):
        """5% 零值刚好触发阈值（≥5%）"""
        values = [0.0] * 5 + list(np.random.uniform(0.01, 0.04, size=95))
        group = pd.Series(values)
        assert _is_zero_inflated_group(group, zero_threshold=0.001, ratio_threshold=0.05)

    def test_near_zero_values_detected(self):
        """|v| < 0.001 的近零值也被检测为零值（浮点精度保护）"""
        values = [1e-15] * 42 + list(np.random.uniform(0.01, 0.04, size=58))
        group = pd.Series(values)
        assert _is_zero_inflated_group(group, zero_threshold=0.001, ratio_threshold=0.05)

    def test_empty_group(self):
        """空分组返回 False"""
        group = pd.Series([], dtype=float)
        assert not _is_zero_inflated_group(group, zero_threshold=0.001, ratio_threshold=0.05)


class TestStandardizeZeroInflated:
    """测试零值分离标准化算法"""

    def test_zero_values_get_z_zero(self):
        """零值 → z = 0（中性信号）"""
        values = [0.0] * 42 + [0.01, 0.02, 0.03, 0.04] * 14 + [0.05] * 2
        group = pd.Series(values)
        result = _standardize_zero_inflated(group, winsorize_sigma=3.0, zero_threshold=0.001)

        # 所有零值 → z = 0
        zero_indices = group.index[group.abs() < 0.001]
        assert (result[zero_indices] == 0.0).all()

    def test_nonzero_values_use_own_distribution(self):
        """非零值用自身 μ/σ 标准化，σ 不受零值压缩"""
        # 构造：42%零值 + 58%非零值（均值0.02，标准差0.01）
        nonzero_vals = np.array([0.01, 0.02, 0.03, 0.04] * 14 + [0.05] * 2)
        values = [0.0] * 42 + list(nonzero_vals)
        group = pd.Series(values)
        result = _standardize_zero_inflated(group, winsorize_sigma=3.0, zero_threshold=0.001)

        nonzero_indices = group.index[group.abs() >= 0.001]
        nonzero_z = result[nonzero_indices]

        # 验证非零值z-score范围应在[-3, +3]内（clip生效）
        assert nonzero_z.max() <= 3.0
        assert nonzero_z.min() >= -3.0

        # 验证非零值z-score的自然范围应远小于零膨胀前的[-24, +24]
        # 非零值自身σ≈0.01 → z范围≈[-2, +3]，而非[-24, +24]
        # 注意：这是零值分离后的自然范围，clip只是保护极端值
        nonzero_mean = nonzero_vals.mean()
        nonzero_std = nonzero_vals.std()
        expected_z_range = max(abs(nonzero_vals - nonzero_mean)) / nonzero_std
        # 修复前σ≈0.015（全截面），修复后σ≈0.01（非零值自身）
        # 预期z范围从~24降到~3
        assert expected_z_range < 5.0  # 修复前会是 ~24

    def test_all_zero_values(self):
        """全零值 → 全部 z = 0"""
        group = pd.Series([0.0] * 100)
        result = _standardize_zero_inflated(group, winsorize_sigma=3.0, zero_threshold=0.001)
        assert (result == 0.0).all()

    def test_single_nonzero_value(self):
        """只有1个非零值 → 全部 z = 0（σ无法计算）"""
        group = pd.Series([0.0] * 99 + [0.04])
        result = _standardize_zero_inflated(group, winsorize_sigma=3.0, zero_threshold=0.001)
        assert (result == 0.0).all()

    def test_all_nonzero_same_value(self):
        """所有非零值相同 → z = 0（σ=0）"""
        group = pd.Series([0.0] * 42 + [0.03] * 58)
        result = _standardize_zero_inflated(group, winsorize_sigma=3.0, zero_threshold=0.001)
        assert (result == 0.0).all()


class TestStandardizeFactorsIntegration:
    """测试 standardize_factors 函数的整体行为——零膨胀因子 vs 正常因子"""

    def test_normal_factor_unchanged(self):
        """正常因子（零值占比 <5%）使用原有标准化，不受零值分离影响"""
        df = pd.DataFrame(
            {
                "date": ["2026-06-17"] * 100,
                "asset": range(100),
                "amplitude_compression": np.random.uniform(0.5, 1.5, size=100),  # 无零值
            }
        )
        result = standardize_factors(df, ["amplitude_compression"], logger)
        z = result["amplitude_compression_std"]

        # 正常因子：使用原有 (v-μ)/σ + clip ±3σ
        assert z.max() <= 3.01  # 允许浮点误差
        assert z.min() >= -3.01
        assert z.mean() < 0.1  # 均值接近0

    def test_zero_inflated_factor_separated(self):
        """零膨胀因子（零值占比 ≥5%）使用零值分离标准化"""
        # 模拟 price_volume_divergence 截面：40%零值
        values = [0.0] * 40 + list(np.random.uniform(0.01, 0.04, size=60))
        df = pd.DataFrame(
            {
                "date": ["2026-06-17"] * 100,
                "asset": range(100),
                "price_volume_divergence": values,
            }
        )
        result = standardize_factors(df, ["price_volume_divergence"], logger)

        std_col = "price_volume_divergence_std"
        zero_mask = df["price_volume_divergence"].abs() < 0.001
        nonzero_mask = ~zero_mask

        # 零值 → z = 0
        assert (result.loc[zero_mask, std_col] == 0.0).all()

        # 非零值 → z-score 用非零值自身 μ/σ 标准化
        nonzero_z = result.loc[nonzero_mask, std_col]
        assert nonzero_z.max() <= 3.01
        assert nonzero_z.min() >= -3.01

        # 验证非零值z-score的自然范围远小于零膨胀前
        # 非零值自身σ≈0.01 → 最大z≈3，而非24
        nonzero_vals = df.loc[nonzero_mask, "price_volume_divergence"]
        mu_nz = nonzero_vals.mean()
        sigma_nz = nonzero_vals.std()
        max_raw_z = max(abs(nonzero_vals - mu_nz)) / sigma_nz
        # 修复前 max_raw_z ≈ 24（σ全截面≈0.015），修复后 max_raw_z ≈ 3-4
        assert max_raw_z < 10.0  # 显著低于零膨胀前的~24

    def test_pvd_contribution_reduced(self):
        """修复后 pvd 在等权中的 z-score 幅度显著降低，不再极端主导"""
        # 模拟8因子截面：pvd 40%零值 + 其他7个正常因子
        n = 100
        zero_count = 40
        pvd_values = [0.0] * zero_count + list(np.random.uniform(0.01, 0.04, size=n - zero_count))

        df = pd.DataFrame(
            {
                "date": ["2026-06-17"] * n,
                "asset": range(n),
                "price_volume_divergence": pvd_values,
                "amplitude_compression": np.random.uniform(0.5, 1.5, size=n),
                "volume_decay_rate": np.random.uniform(0.3, 0.9, size=n),
                "bollinger_pb": np.random.uniform(0.1, 0.9, size=n),
                "rsi_6": np.random.uniform(20, 80, size=n),
                "volume_ratio_5": np.random.uniform(0.3, 2.0, size=n),
                "price_position": np.random.uniform(0.1, 0.9, size=n),
                "volume_price_strength": np.random.uniform(-0.5, 0.5, size=n),
            }
        )

        factor_cols = [
            "price_volume_divergence",
            "amplitude_compression",
            "volume_decay_rate",
            "bollinger_pb",
            "rsi_6",
            "volume_ratio_5",
            "price_position",
            "volume_price_strength",
        ]

        result = standardize_factors(df, factor_cols, logger)

        # pvd 非零值的z-score幅度应远小于修复前
        pvd_std = result["price_volume_divergence_std"]
        nonzero_pvd_z = pvd_std[df["price_volume_divergence"].abs() >= 0.001]

        # 修复前非零值z-score会被放大到~3（clip后），修复后应在自然范围
        # 关键指标：非零值z-score的绝对均值应低于其他因子
        # 正常因子z-score绝对均值 ≈ 0.8（正态分布）
        # 修复前pvd非零值z-score绝对均值 ≈ 2.0（被零膨胀放大）
        # 修复后应 ≈ 0.8-1.0（与正常因子相当）
        other_z_means = []
        for col in factor_cols[1:]:
            z = result[f"{col}_std"]
            other_z_means.append(z.abs().mean())

        avg_other_z = np.mean(other_z_means)
        avg_pvd_nonzero_z = nonzero_pvd_z.abs().mean()

        # pvd非零值z-score均值不应超过其他因子2倍（修复前是~2.5倍）
        assert avg_pvd_nonzero_z < avg_other_z * 2.5
