"""factor_calculator 拆分前的行为基线指纹（design.md §9.2）。

用途：
    在 PR-2a/2b/2c/3/4 搬运前固化一次行为基线；每次搬运后用
    factor_calculator_verify_fingerprint.py 验证指纹未变。

放置目录：temporary/（遵循 AGENTS.md 规则 #3，PR-5 完成后随拆分项目一并删除）。

输出：
    temporary/factor_calculator_baseline_fingerprint.json
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from data_fetchers.factor_calculator import (
    calculate_amplitude,
    calculate_amplitude_delta,
    calculate_bollinger_pb,
    calculate_forward_return,
    calculate_kdj_j,
    calculate_ma5_deviation,
    calculate_momentum_strength,
    calculate_near_high_ratio_5,
    calculate_overnight_return,
    calculate_past_return_1d,
    calculate_positive_day_ratio_5,
    calculate_price_position,
    calculate_return_3d,
    calculate_return_5d,
    calculate_rsi,
    calculate_rsi_df,
    calculate_tail_price_position_delta,
    calculate_tail_volume_shrink_delta,
    calculate_turnover_surge,
    calculate_turnover_surge_delta,
    calculate_volume_price_strength,
    calculate_volume_ratio,
)

# 固定随机种子，保证基线可复现
SEED = 42
NUM_ASSETS = 20
NUM_DAYS = 60


def _build_panel() -> pd.DataFrame:
    """构造 20 个 asset × 60 日的固定面板数据（含 OHLCV + turnover_rate）。"""
    rng = np.random.default_rng(SEED)
    dates = pd.date_range("2024-01-02", periods=NUM_DAYS, freq="B")
    assets = [f"00000{i:02d}" for i in range(NUM_ASSETS)]

    rows = []
    for asset in assets:
        # 用几何随机游走构造 close
        rets = rng.normal(0.0005, 0.02, NUM_DAYS)
        close = 10.0 * np.cumprod(1 + rets)
        # OHLC 衍生
        high = close * (1 + np.abs(rng.normal(0, 0.01, NUM_DAYS)))
        low = close * (1 - np.abs(rng.normal(0, 0.01, NUM_DAYS)))
        open_ = close * (1 + rng.normal(0, 0.005, NUM_DAYS))
        volume = rng.integers(1_000_000, 5_000_000, NUM_DAYS).astype(float)
        turnover_rate = rng.uniform(0.5, 5.0, NUM_DAYS)

        for i, date in enumerate(dates):
            rows.append(
                {
                    "asset": asset,
                    "date": date,
                    "open": float(open_[i]),
                    "high": float(high[i]),
                    "low": float(low[i]),
                    "close": float(close[i]),
                    "volume": float(volume[i]),
                    "turnover_rate": float(turnover_rate[i]),
                }
            )

    return pd.DataFrame(rows).sort_values(["asset", "date"]).reset_index(drop=True)


def _hash_series(s: pd.Series) -> str:
    """对 Series 用 pandas.util.hash_pandas_object 取确定性 hash。"""
    return f"{int(pd.util.hash_pandas_object(s.fillna(-9999.999), index=False).sum()):x}"  # type: ignore[attr-defined]


def _hash_df_col(df: pd.DataFrame, col: str) -> str:
    return _hash_series(df[col])  # type: ignore[arg-type]


def _series_factor(df: pd.DataFrame, fn, group_col: str, src_col: str, **kwargs) -> pd.Series:
    """逐 asset 调用 Series-in / Series-out 的因子函数（如 calculate_rsi）。"""
    parts = []
    for _, group in df.groupby(group_col, sort=False):
        parts.append(fn(group[src_col].reset_index(drop=True), **kwargs))
    return pd.concat(parts, ignore_index=True)  # type: ignore[return-value]


def collect_fingerprints(panel: pd.DataFrame) -> dict[str, str]:
    """对每个公共因子函数生成指纹。"""
    fingerprints: dict[str, str] = {}

    # ----- Series-in / Series-out 因子（按 asset 分组调用） -----
    fingerprints["calculate_rsi"] = _hash_series(
        _series_factor(panel, calculate_rsi, "asset", "close")
    )
    fingerprints["calculate_volume_ratio"] = _hash_series(
        _series_factor(panel, calculate_volume_ratio, "asset", "volume")
    )
    fingerprints["calculate_forward_return"] = _hash_series(
        _series_factor(panel, calculate_forward_return, "asset", "close")
    )

    # ----- DataFrame-in / DataFrame-out 因子 -----
    df_factors = {
        "calculate_bollinger_pb": (calculate_bollinger_pb, "bollinger_pb"),
        "calculate_kdj_j": (calculate_kdj_j, "kdj_j"),
        "calculate_turnover_surge": (calculate_turnover_surge, "turnover_surge"),
        "calculate_price_position": (calculate_price_position, "price_position"),
        "calculate_amplitude": (calculate_amplitude, "amplitude"),
        "calculate_past_return_1d": (calculate_past_return_1d, "past_return_1d"),
        "calculate_return_3d": (calculate_return_3d, "return_3d"),
        "calculate_return_5d": (calculate_return_5d, "return_5d"),
        "calculate_momentum_strength": (calculate_momentum_strength, "momentum_strength"),
        "calculate_overnight_return": (calculate_overnight_return, "overnight_ret"),
        "calculate_rsi_df": (calculate_rsi_df, "rsi"),
        "calculate_amplitude_delta": (calculate_amplitude_delta, "amplitude_delta"),
        "calculate_turnover_surge_delta": (
            calculate_turnover_surge_delta,
            "turnover_surge_delta",
        ),
        "calculate_tail_price_position_delta": (
            calculate_tail_price_position_delta,
            "tail_price_position_delta",
        ),
        "calculate_tail_volume_shrink_delta": (
            calculate_tail_volume_shrink_delta,
            "tail_volume_shrink_delta",
        ),
        "calculate_volume_price_strength": (
            calculate_volume_price_strength,
            "volume_price_strength",
        ),
        "calculate_positive_day_ratio_5": (
            calculate_positive_day_ratio_5,
            "positive_day_ratio_5",
        ),
        "calculate_ma5_deviation": (calculate_ma5_deviation, "ma5_deviation"),
        "calculate_near_high_ratio_5": (calculate_near_high_ratio_5, "near_high_ratio_5"),
    }

    for name, (fn, out_col) in df_factors.items():
        try:
            out = fn(panel.copy())
            fingerprints[name] = _hash_df_col(out, out_col)
        except Exception as e:  # noqa: BLE001
            fingerprints[name] = f"ERROR:{type(e).__name__}:{e!s}"

    return fingerprints


def main() -> None:
    panel = _build_panel()

    fingerprints = collect_fingerprints(panel)

    out_path = Path(__file__).parent / "factor_calculator_baseline_fingerprint.json"
    payload = {
        "seed": SEED,
        "num_assets": NUM_ASSETS,
        "num_days": NUM_DAYS,
        "panel_hash": _hash_df_col(panel, "close"),
        "fingerprints": fingerprints,
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"baseline written → {out_path}")
    print(f"  panel_hash = {payload['panel_hash']}")
    print(f"  factor count = {len(fingerprints)}")
    errors = [k for k, v in fingerprints.items() if v.startswith("ERROR:")]
    if errors:
        print(f"  WARNING: {len(errors)} factor(s) errored:")
        for k in errors:
            print(f"    - {k}: {fingerprints[k]}")


if __name__ == "__main__":
    main()
