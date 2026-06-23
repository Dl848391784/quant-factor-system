"""test_role_weights_matrix: R2 角色固定权重矩阵版 (r2c) 单元测试.

测试目标:
- _apply_role_weights_matrix 与 _apply_role_weights_static 数值同构 (atol=1e-9)
- 矩阵版每行独立处理 (n_days 行互不影响)
- 边界场景: 无 confirmation / 无 primary / primary 行全 0 / 含 filter
- RollingICIRWeightMethod 端到端集成: enable_role_weights=True 时
  最终 _last_day_weights 满足 primary≈75% + confirmation≈25% + filter=0
- enable_role_weights=False 时向后兼容 (矩阵版不被调用)

设计依据: designs/feat_r2c_role_weights_for_rolling_icir.md
"""

import numpy as np
import pandas as pd
import pytest
from comprehensive_factor.common.weight_engine import (
    EqualWeightMethod,
    RollingICIRWeightMethod,
)
from factor_definitions import FACTOR_ROLES, PRIMARY_WEIGHT_TOTAL


# === 因子分桶 (与 factor_definitions.FACTOR_ROLES 一致) ===
# primary (3): 高 IC, 单独可形成多头收益
# 注: 使用 factor_name (FACTOR_CATEGORIES key), 而非数据列名.
#   RollingICIR._last_day_weights 的 key 是 factor_name (由 _get_factor_name_from_col 解析),
#   故测试此处直接用 factor_name 保持列名 == factor_name, 简化端到端断言.
PRIMARY_COLS = ["momentum_strength", "return_3d", "rsi"]
# confirmation (3): 低 IC 但低相关, 固定份额
CONFIRMATION_COLS = ["rsi_slope_3d", "ma5_slope", "lower_shadow_ratio"]
# filter (1): stock_selector 硬过滤, 不进 composite
FILTER_COLS = ["cum_return_5d_breakdown"]


@pytest.fixture
def method_enabled():
    """启用 role_weights 的 EqualWeightMethod (用于测矩阵版函数)."""
    return EqualWeightMethod(enable_role_weights=True)


@pytest.fixture
def method_disabled():
    """禁用 role_weights 的 EqualWeightMethod (默认)."""
    return EqualWeightMethod()


def _validate_factor_roles():
    """fixture 前置校验: 假定因子的角色映射与 factor_definitions 一致."""
    for c in PRIMARY_COLS:
        assert FACTOR_ROLES.get(c, "primary") == "primary", (
            f"测试假设 {c} 是 primary, 与 FACTOR_ROLES 不一致, 请同步更新"
        )
    for c in CONFIRMATION_COLS:
        assert FACTOR_ROLES.get(c) == "confirmation", (
            f"测试假设 {c} 是 confirmation, 与 FACTOR_ROLES 不一致, 请同步更新"
        )
    for c in FILTER_COLS:
        assert FACTOR_ROLES.get(c) == "filter", f"测试假设 {c} 是 filter, 与 FACTOR_ROLES 不一致, 请同步更新"


_validate_factor_roles()


class TestMatrixStaticEquivalence:
    """T1+T2: 矩阵版与静态 dict 版数值等价 (核心契约)."""

    def test_matrix_equals_static_single_row(self, method_enabled):
        """T1: 单行矩阵 vs 静态 dict 版, 应数值相等 (atol=1e-9)."""
        cols = PRIMARY_COLS + CONFIRMATION_COLS
        # 任意非平凡权重 (sum=1)
        W = np.array([[0.30, 0.20, 0.10, 0.15, 0.15, 0.10]])
        matrix_out = method_enabled._apply_role_weights_matrix(W, cols)

        static_in = {col: float(W[0, i]) for i, col in enumerate(cols)}
        static_out = method_enabled._apply_role_weights_static(static_in, cols)

        for i, col in enumerate(cols):
            assert abs(matrix_out[0, i] - static_out[col]) < 1e-9, (
                f"col={col}: matrix={matrix_out[0, i]:.10f} vs static={static_out[col]:.10f}"
            )

    def test_matrix_multi_day_independent(self, method_enabled):
        """T2: 多日矩阵每行独立处理, 每行 = 静态版独立处理结果."""
        cols = PRIMARY_COLS + CONFIRMATION_COLS
        # 5 日不同权重 (每行 sum=1)
        rng = np.random.default_rng(42)
        W = rng.dirichlet(np.ones(len(cols)), size=5)
        matrix_out = method_enabled._apply_role_weights_matrix(W, cols)

        for day in range(5):
            static_in = {col: float(W[day, i]) for i, col in enumerate(cols)}
            static_out = method_enabled._apply_role_weights_static(static_in, cols)
            for i, col in enumerate(cols):
                assert abs(matrix_out[day, i] - static_out[col]) < 1e-9, (
                    f"day={day} col={col}: matrix={matrix_out[day, i]:.10f} vs static={static_out[col]:.10f}"
                )


class TestMatrixEdgeCases:
    """T3-T6: 矩阵版边界场景."""

    def test_no_confirmation_primary_takes_all(self, method_enabled):
        """T3: 无 confirmation → primary 独占 100%, 按原比例分配."""
        cols = PRIMARY_COLS  # 全 primary
        W = np.array([[0.5, 0.3, 0.2], [0.1, 0.6, 0.3]])
        out = method_enabled._apply_role_weights_matrix(W, cols)

        # 每行 sum=1, 且按原比例 (因为 primary_pool=1.0, primary_sum=1.0)
        assert np.allclose(out.sum(axis=1), 1.0, atol=1e-9)
        assert np.allclose(out, W, atol=1e-9), "全 primary 且 sum=1 → 应等于原 W"

    def test_no_primary_confirmation_equal_split(self, method_enabled):
        """T4: 无 primary → confirmation 等权独占 100%."""
        cols = CONFIRMATION_COLS  # 全 confirmation, n=3
        W = np.array([[0.5, 0.3, 0.2], [0.1, 0.6, 0.3]])
        out = method_enabled._apply_role_weights_matrix(W, cols)

        # 每行 sum=1, 且每列 = 1/3 (均分)
        assert np.allclose(out.sum(axis=1), 1.0, atol=1e-9)
        assert np.allclose(out, 1.0 / 3.0, atol=1e-9), "全 confirmation → 每列应等于 1/n_conf=1/3"

    def test_filter_zeroed_others_renormalized(self, method_enabled):
        """T5: 含 filter → filter 列 = 0, 其他列重新归一化 sum=1."""
        cols = PRIMARY_COLS + CONFIRMATION_COLS + FILTER_COLS
        W = np.array([[0.20, 0.15, 0.15, 0.15, 0.15, 0.10, 0.10]])
        out = method_enabled._apply_role_weights_matrix(W, cols)

        # filter 列 (最后一列) = 0
        assert out[0, -1] == 0.0, f"filter 列应为 0, 实际 {out[0, -1]}"
        # 行 sum = 1
        assert abs(out[0].sum() - 1.0) < 1e-9
        # primary 桶合计 ≈ 0.75, confirmation 桶合计 ≈ 0.25
        primary_sum = out[0, :3].sum()
        conf_sum = out[0, 3:6].sum()
        assert abs(primary_sum - PRIMARY_WEIGHT_TOTAL) < 1e-9, f"primary 桶合计应 ≈ 0.75, 实际 {primary_sum:.6f}"
        assert abs(conf_sum - (1.0 - PRIMARY_WEIGHT_TOTAL)) < 1e-9, f"confirmation 桶合计应 ≈ 0.25, 实际 {conf_sum:.6f}"

    def test_primary_zero_row_degrades_to_equal(self, method_enabled):
        """T6: 某行 primary 原权重全 0 → primary 等权降级到 primary_pool/n_primary."""
        cols = PRIMARY_COLS + CONFIRMATION_COLS
        # 第 0 行 primary 全 0, 权重全在 confirmation 上 (n_primary=3, n_conf=3)
        W = np.array(
            [
                [0.0, 0.0, 0.0, 0.5, 0.3, 0.2],
                [0.3, 0.2, 0.1, 0.2, 0.1, 0.1],  # 正常行做参照
            ]
        )
        out = method_enabled._apply_role_weights_matrix(W, cols)

        # 行 0: primary 等权降级 = 0.75 / 3 = 0.25 / 列
        assert np.allclose(out[0, :3], PRIMARY_WEIGHT_TOTAL / 3, atol=1e-9), (
            f"primary 全 0 行应等权降级, 实际 {out[0, :3]}"
        )
        # 行 0 confirmation = 0.25 / 3
        assert np.allclose(out[0, 3:], (1.0 - PRIMARY_WEIGHT_TOTAL) / 3, atol=1e-9)
        # 行 sum=1
        assert np.allclose(out.sum(axis=1), 1.0, atol=1e-9)


class TestMatrixDisabled:
    """T8: enable_role_weights=False → 矩阵版直接返回 copy (向后兼容)."""

    def test_disabled_returns_copy_unchanged(self, method_disabled):
        cols = PRIMARY_COLS + CONFIRMATION_COLS
        W = np.array([[0.30, 0.20, 0.10, 0.15, 0.15, 0.10]])
        out = method_disabled._apply_role_weights_matrix(W, cols)

        assert np.allclose(out, W, atol=1e-12), "禁用时矩阵不应被修改"
        # 验证是 copy (修改 out 不影响 W)
        out[0, 0] = 999.0
        assert W[0, 0] == 0.30, "应返回 copy, 不应共享底层数组"


class TestRollingICIRRoleWeightsE2E:
    """T7: RollingICIRWeightMethod 端到端集成测试.

    构造小型 factor_df + ic_daily_data, 完整跑 calculate(),
    断言 _last_day_weights 满足 R2 契约:
        primary 桶合计 ≈ 0.75
        confirmation 桶合计 ≈ 0.25
        filter 桶 = 0
    """

    def _build_factor_df(self, factor_names, n_days=30, n_assets=20, seed=42):
        """构造合成 factor_df: date × asset × 因子标准化列 + ic_daily_data."""
        rng = np.random.default_rng(seed)
        dates = pd.date_range("2026-01-01", periods=n_days, freq="D")
        assets = [f"00{i:04d}" for i in range(n_assets)]

        rows = []
        for d in dates:
            for a in assets:
                row = {"date": d, "asset": a}
                for fname in factor_names:
                    # 因子原值 + 标准化列 (RollingICIR 用 _std 列)
                    val = rng.standard_normal()
                    row[fname] = val
                    row[f"{fname}_std"] = val
                rows.append(row)
        df = pd.DataFrame(rows)

        # 构造 ic_daily_data: 每个因子一条 IC 时间序列, 有非零 ICIR
        ic_daily = {}
        for fname in factor_names:
            ic_series = rng.uniform(-0.05, 0.05, size=n_days)
            # 注入趋势避免 std=0
            ic_series = ic_series + rng.standard_normal(n_days) * 0.02
            ic_daily[fname] = pd.DataFrame({"date": dates.astype(str), "ic": ic_series})

        return df, ic_daily

    def test_rolling_icir_role_weights_e2e(self):
        """端到端: enable_role_weights=True → _last_day_weights 满足 R2 契约."""
        # 用真实的 primary + confirmation 因子名 (不含 filter, filter 由 stock_selector 处理)
        factor_names = PRIMARY_COLS + CONFIRMATION_COLS
        df, ic_daily = self._build_factor_df(factor_names, n_days=30)

        method = RollingICIRWeightMethod(window=10, enable_role_weights=True)
        # window=10, n_days=30 → 充足滚动样本
        _ = method.calculate(df, factor_cols=factor_names, ic_daily_data=ic_daily)

        weights = method._last_day_weights
        assert weights, "_last_day_weights 应非空"

        # primary 合计 ≈ 0.75
        primary_sum = sum(weights.get(c, 0.0) for c in PRIMARY_COLS)
        assert abs(primary_sum - PRIMARY_WEIGHT_TOTAL) < 1e-6, (
            f"primary 桶合计应 ≈ 0.75, 实际 {primary_sum:.6f}, weights={ {k: round(v, 4) for k, v in weights.items()} }"
        )

        # confirmation 合计 ≈ 0.25, 且均分
        conf_sum = sum(weights.get(c, 0.0) for c in CONFIRMATION_COLS)
        assert abs(conf_sum - (1.0 - PRIMARY_WEIGHT_TOTAL)) < 1e-6, f"confirmation 桶合计应 ≈ 0.25, 实际 {conf_sum:.6f}"
        per_conf = (1.0 - PRIMARY_WEIGHT_TOTAL) / len(CONFIRMATION_COLS)
        for c in CONFIRMATION_COLS:
            assert abs(weights[c] - per_conf) < 1e-6, f"{c} 应均分 = {per_conf:.6f}, 实际 {weights[c]:.6f}"

        # 总和 ≈ 1.0
        assert abs(sum(weights.values()) - 1.0) < 1e-6

    def test_rolling_icir_disabled_no_role_weights(self):
        """enable_role_weights=False → 权重不被 R2 改写 (向后兼容)."""
        factor_names = PRIMARY_COLS + CONFIRMATION_COLS
        df, ic_daily = self._build_factor_df(factor_names, n_days=30, seed=99)

        method = RollingICIRWeightMethod(window=10, enable_role_weights=False)
        _ = method.calculate(df, factor_cols=factor_names, ic_daily_data=ic_daily)

        weights = method._last_day_weights
        assert weights, "_last_day_weights 应非空"

        # 关键断言: confirmation 不应被强制 25%/n_conf (否则 R2 错误启用)
        per_conf_if_r2 = (1.0 - PRIMARY_WEIGHT_TOTAL) / len(CONFIRMATION_COLS)
        # 任意一个 confirmation 因子权重应偏离 per_conf_if_r2 (因为是 |ICIR| 加权)
        conf_weights = [weights[c] for c in CONFIRMATION_COLS]
        # 至少有一个 confirmation 权重明显偏离 per_conf (R2 未应用)
        deviations = [abs(w - per_conf_if_r2) for w in conf_weights]
        assert max(deviations) > 1e-4, (
            f"enable_role_weights=False 时 R2 不应生效, "
            f"但 confirmation 权重恰好等于 R2 期望值 {per_conf_if_r2:.4f}: {conf_weights}"
        )
