#!/usr/bin/env python3
"""_per_asset_transform 等价性单测（关键回归保护）

测试目标: data_fetchers/factor_calculator.py::_per_asset_transform
覆盖范围:
- TC01: 空输入处理
- TC02: 单 asset
- TC03: 多 asset，含 rolling/ewm/diff 等典型场景
- TC04: 与 pandas groupby.transform 位级等价（Bollinger / KDJ / Turnover / Momentum 各一例）
- TC05: 长度不一致抛 ValueError
- TC06: 验证下游 5 个因子在大随机数据上 helper 实现 == 旧 transform 实现

设计动机:
    v1.x (2026-06-13) 5 处 groupby.transform 重构为 _per_asset_transform 调用，
    必须保证位级等价性（不引入数值偏差），否则会污染下游 IC/分层回测/综合因子结果。
"""

import numpy as np
import pandas as pd
import pytest

from data_fetchers.factor_calculator import _calculate_ewm_with_initial, _per_asset_transform


@pytest.fixture
def sorted_panel():
    """构造已按 asset 排序的面板数据"""
    rng = np.random.default_rng(42)
    n_assets = 8
    n_days = 50
    rows = []
    base_date = pd.Timestamp("2026-01-01")
    for i in range(n_assets):
        asset = f"A{i:03d}"
        close = 100.0 + rng.standard_normal(n_days).cumsum()
        for d in range(n_days):
            rows.append(
                {
                    "asset": asset,
                    "date": (base_date + pd.Timedelta(days=d)).strftime("%Y-%m-%d"),
                    "close": float(close[d]),
                    "high": float(close[d]) + abs(rng.standard_normal()) * 0.5,
                    "low": float(close[d]) - abs(rng.standard_normal()) * 0.5,
                    "turnover_rate": abs(rng.standard_normal() * 0.01),
                }
            )
    return pd.DataFrame(rows).sort_values(["asset", "date"]).reset_index(drop=True)


# ============================================================================
# TC01-TC05 helper 单元测试
# ============================================================================


class TestHelperUnit:
    def test_empty_input(self):
        result = _per_asset_transform(np.array([]), np.array([]), lambda s: s.cumsum())
        assert result.shape == (0,)
        assert result.dtype == np.float64

    def test_single_asset(self):
        assets = np.array(["A"] * 5)
        values = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        result = _per_asset_transform(assets, values, lambda s: s.cumsum())
        np.testing.assert_array_equal(result, [1.0, 3.0, 6.0, 10.0, 15.0])

    def test_multi_asset_independent(self):
        """每个 asset 内部独立 cumsum，不跨 asset"""
        assets = np.array(["A", "A", "A", "B", "B", "C"])
        values = np.array([1.0, 2.0, 3.0, 10.0, 20.0, 100.0])
        result = _per_asset_transform(assets, values, lambda s: s.cumsum())
        np.testing.assert_array_equal(result, [1.0, 3.0, 6.0, 10.0, 30.0, 100.0])

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError, match="长度不一致"):
            _per_asset_transform(np.array(["A", "A"]), np.array([1.0]), lambda s: s)

    def test_rolling_independence(self):
        """rolling 在 asset 边界处应正确产生 NaN（独立窗口）"""
        assets = np.array(["A", "A", "A", "B", "B", "B"])
        values = np.array([1.0, 2.0, 3.0, 10.0, 20.0, 30.0])
        result = _per_asset_transform(assets, values, lambda s: s.rolling(window=2, min_periods=2).mean())
        # A 第一个 NaN，B 第一个也是 NaN（不能用 A 末尾延续）
        assert np.isnan(result[0])
        assert np.isnan(result[3])
        np.testing.assert_allclose(result[1:3], [1.5, 2.5])
        np.testing.assert_allclose(result[4:6], [15.0, 25.0])


# ============================================================================
# TC06: 5 个因子在随机面板上 helper 与 transform 位级等价
# ============================================================================


class TestEquivalenceWithGroupbyTransform:
    """对每个被重构的 transform 调用，验证 helper 实现位级一致"""

    def test_bollinger_rolling_mean(self, sorted_panel):
        """Bollinger %B 用 rolling mean"""
        df = sorted_panel
        n = 20
        # 旧实现
        legacy = df.groupby("asset", group_keys=False)["close"].transform(lambda x: x.rolling(window=n).mean())
        # 新实现
        new_arr = _per_asset_transform(
            df["asset"].to_numpy(), df["close"].to_numpy(), lambda s: s.rolling(window=n).mean()
        )
        legacy_arr = legacy.to_numpy()
        np.testing.assert_array_equal(np.isnan(new_arr), np.isnan(legacy_arr))
        mask = ~np.isnan(new_arr)
        np.testing.assert_allclose(new_arr[mask], legacy_arr[mask], rtol=1e-12)

    def test_bollinger_rolling_std(self, sorted_panel):
        df = sorted_panel
        n = 20
        legacy = df.groupby("asset", group_keys=False)["close"].transform(lambda x: x.rolling(window=n).std())
        new_arr = _per_asset_transform(
            df["asset"].to_numpy(), df["close"].to_numpy(), lambda s: s.rolling(window=n).std()
        )
        legacy_arr = legacy.to_numpy()
        np.testing.assert_array_equal(np.isnan(new_arr), np.isnan(legacy_arr))
        mask = ~np.isnan(new_arr)
        np.testing.assert_allclose(new_arr[mask], legacy_arr[mask], rtol=1e-12)

    def test_kdj_rolling_min_max(self, sorted_panel):
        """KDJ low_min / high_max"""
        df = sorted_panel
        n = 9
        for col, fn_name in [("low", "min"), ("high", "max")]:
            legacy = df.groupby("asset", group_keys=False)[col].transform(
                lambda x, _name=fn_name: getattr(x.rolling(n, min_periods=n), _name)()
            )
            new_arr = _per_asset_transform(
                df["asset"].to_numpy(),
                df[col].to_numpy(),
                lambda s, _name=fn_name: getattr(s.rolling(n, min_periods=n), _name)(),
            )
            legacy_arr = legacy.to_numpy()
            np.testing.assert_array_equal(np.isnan(new_arr), np.isnan(legacy_arr), err_msg=f"{col} NaN 不一致")
            mask = ~np.isnan(new_arr)
            np.testing.assert_allclose(new_arr[mask], legacy_arr[mask], rtol=1e-12, err_msg=f"{col} 数值不一致")

    def test_kdj_ewm_initial(self, sorted_panel):
        """KDJ K/D 计算用 _calculate_ewm_with_initial"""
        df = sorted_panel
        # 用 close 模拟 rsv 序列
        rsv_series = df["close"]
        alpha = 1 / 3
        initial = 50.0
        legacy = rsv_series.groupby(df["asset"]).transform(lambda x: _calculate_ewm_with_initial(x, alpha, initial))
        new_arr = _per_asset_transform(
            df["asset"].to_numpy(),
            rsv_series.to_numpy(),
            lambda s: _calculate_ewm_with_initial(s, alpha, initial),
        )
        legacy_arr = legacy.to_numpy()
        np.testing.assert_array_equal(np.isnan(new_arr), np.isnan(legacy_arr))
        mask = ~np.isnan(new_arr)
        np.testing.assert_allclose(new_arr[mask], legacy_arr[mask], rtol=1e-10)

    def test_turnover_surge_shift_rolling(self, sorted_panel):
        """Turnover surge: shift(1) + rolling(5).mean()"""
        df = sorted_panel
        window = 5
        legacy = df.groupby("asset")["turnover_rate"].transform(
            lambda x: x.shift(1).rolling(window, min_periods=window).mean()
        )
        new_arr = _per_asset_transform(
            df["asset"].to_numpy(),
            df["turnover_rate"].to_numpy(),
            lambda s: s.shift(1).rolling(window, min_periods=window).mean(),
        )
        legacy_arr = legacy.to_numpy()
        np.testing.assert_array_equal(np.isnan(new_arr), np.isnan(legacy_arr))
        mask = ~np.isnan(new_arr)
        np.testing.assert_allclose(new_arr[mask], legacy_arr[mask], rtol=1e-12)

    def test_momentum_rolling_std(self, sorted_panel):
        """Momentum strength: rolling(5).std()"""
        df = sorted_panel.copy()
        # 模拟 _return_1d_temp 列
        df["ret"] = df.groupby("asset", group_keys=False)["close"].pct_change()
        window = 5
        legacy = df.groupby("asset", group_keys=False)["ret"].transform(
            lambda x: x.rolling(window=window, min_periods=window).std()
        )
        new_arr = _per_asset_transform(
            df["asset"].to_numpy(),
            df["ret"].to_numpy(),
            lambda s: s.rolling(window=window, min_periods=window).std(),
        )
        legacy_arr = legacy.to_numpy()
        np.testing.assert_array_equal(np.isnan(new_arr), np.isnan(legacy_arr))
        mask = ~np.isnan(new_arr)
        np.testing.assert_allclose(new_arr[mask], legacy_arr[mask], rtol=1e-12)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
