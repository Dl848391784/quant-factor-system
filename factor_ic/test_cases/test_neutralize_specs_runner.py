"""P3.1 neutralize_specs 决策与通用中性化 helper 测试。

覆盖：
    - 默认 specs: neutralize=True → ["industry", "log_market_cap"]
    - neutralize=False / 非 full mode 跳过
    - 因子按 control 独立排除：排除 industry 不影响 log_market_cap 继续跑
    - 通用 helper 可加载/预处理/按 join_keys 合并多个 provider 并计算 neutral IC

参考: designs/feat_neutralization_framework.md §10.2 P3.1
"""

from __future__ import annotations

from typing import Any, Literal

import pandas as pd

from factor_ic.common.factor_ic_runner import (
    NEUTRALIZE_SKIP_REASON_EXCLUDED,
    NEUTRALIZE_SKIP_REASON_INCREMENTAL,
    NEUTRALIZE_SKIP_REASON_USER_DISABLED,
    _compute_neutralized_ic,
    _resolve_neutralize_specs,
)


class _StaticProvider:
    name = "mock_group"
    column_type: Literal["categorical", "numerical"] = "categorical"
    join_keys = ["asset"]

    def __init__(self) -> None:
        self._meta: dict[str, Any] = {"loaded": False}

    def load(self, dates: list, assets: list, *, logger: Any = None) -> pd.DataFrame:
        self._meta["loaded"] = True
        return pd.DataFrame(
            {
                "asset": assets,
                "mock_group": ["A" if i < len(assets) / 2 else "B" for i, _ in enumerate(assets)],
            }
        )

    def preprocess(self, df: pd.DataFrame, *, logger: Any = None) -> pd.DataFrame:
        return df.copy()

    def filter_invalid_rows(self, day_df: pd.DataFrame, *, min_count: int, logger: Any = None) -> pd.DataFrame:
        filtered = day_df.groupby("mock_group").filter(lambda x: len(x) >= min_count)
        return pd.DataFrame(filtered)

    def to_design_columns(self, day_df: pd.DataFrame, *, drop_first: bool = False) -> pd.DataFrame:
        return pd.get_dummies(day_df["mock_group"], drop_first=drop_first)

    def get_meta(self) -> dict:
        return self._meta.copy()


class _NumericProvider:
    name = "mock_num"
    column_type: Literal["categorical", "numerical"] = "numerical"
    join_keys = ["date", "asset"]

    def __init__(self) -> None:
        self._meta: dict[str, Any] = {"loaded": False}

    def load(self, dates: list, assets: list, *, logger: Any = None) -> pd.DataFrame:
        self._meta["loaded"] = True
        rows = []
        for date in dates:
            for i, asset in enumerate(assets):
                rows.append({"date": date, "asset": asset, "mock_num": float(i + 1)})
        return pd.DataFrame(rows)

    def preprocess(self, df: pd.DataFrame, *, logger: Any = None) -> pd.DataFrame:
        return df.copy()

    def filter_invalid_rows(self, day_df: pd.DataFrame, *, min_count: int, logger: Any = None) -> pd.DataFrame:
        if len(day_df) < min_count:
            return day_df.iloc[0:0].copy()
        return day_df

    def to_design_columns(self, day_df: pd.DataFrame, *, drop_first: bool = False) -> pd.DataFrame:
        return day_df[["mock_num"]]

    def get_meta(self) -> dict:
        return self._meta.copy()


def _factor_return_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    ret_rows = []
    assets = ["000001", "000002", "000003", "000004", "000005", "000006"]
    for date_idx, date in enumerate(["2024-01-01", "2024-01-02", "2024-01-03"]):
        for i, asset in enumerate(assets):
            factor = 1.0 + 0.3 * i + date_idx * 0.05
            ret = 0.01 * (i - 2) + date_idx * 0.001
            rows.append({"date": date, "asset": asset, "factor": factor})
            ret_rows.append({"date": date, "asset": asset, "forward_return_1d": ret})
    return pd.DataFrame(rows), pd.DataFrame(ret_rows)


class TestResolveNeutralizeSpecs:
    def test_default_specs_when_enabled(self):
        effective, reason, excluded = _resolve_neutralize_specs(
            factor_name="rsi",
            neutralize=True,
            mode="full",
            neutralize_specs=None,
        )
        assert effective == ["industry", "log_market_cap"]
        assert reason is None
        assert excluded == []

    def test_user_disabled_returns_empty(self):
        effective, reason, excluded = _resolve_neutralize_specs(
            factor_name="rsi",
            neutralize=False,
            mode="full",
            neutralize_specs=["industry"],
        )
        assert effective == []
        assert reason == NEUTRALIZE_SKIP_REASON_USER_DISABLED
        assert excluded == []

    def test_incremental_returns_empty(self):
        effective, reason, excluded = _resolve_neutralize_specs(
            factor_name="rsi",
            neutralize=True,
            mode="incremental",
            neutralize_specs=["industry", "log_market_cap"],
        )
        assert effective == []
        assert reason == NEUTRALIZE_SKIP_REASON_INCREMENTAL
        assert excluded == []

    def test_excluded_control_is_popped_not_global_skip(self):
        effective, reason, excluded = _resolve_neutralize_specs(
            factor_name="industry_momentum_5d",
            neutralize=True,
            mode="full",
            neutralize_specs=["industry", "log_market_cap"],
        )
        assert effective == ["log_market_cap"]
        assert reason is None
        assert excluded == ["industry"]

    def test_all_controls_excluded_returns_excluded_reason(self):
        effective, reason, excluded = _resolve_neutralize_specs(
            factor_name="log_market_cap",
            neutralize=True,
            mode="full",
            neutralize_specs=["log_market_cap"],
        )
        assert effective == []
        assert reason == NEUTRALIZE_SKIP_REASON_EXCLUDED
        assert excluded == ["log_market_cap"]


class TestComputeNeutralizedIc:
    def test_compute_with_multiple_mock_providers(self):
        factor_df, return_df = _factor_return_frames()
        payload = _compute_neutralized_ic(
            factor_df=factor_df,
            return_df=return_df,
            factor_col="factor",
            return_col="forward_return_1d",
            providers=[_StaticProvider(), _NumericProvider()],
            min_stocks=3,
            control_min_count=3,
            raw_ic_mean=0.5,
            logger=None,
        )

        assert payload["controls_used"] == ["mock_group", "mock_num"]
        assert payload["enabled"] is True
        assert payload["n_days"] == 3
        assert payload["control_meta"]["mock_group"]["loaded"] is True
        assert payload["control_meta"]["mock_num"]["loaded"] is True
        assert len(payload["dates"]) == 3
        assert len(payload["ic_values"]) == 3
