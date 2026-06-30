"""S6 段日内操作建议功能测试.

核心 invariant:
  1. real_gap_pct = (open - prev_close) / prev_close * 100 (不用 forward_return_1d 反推)
  2. gap > +0.5% → sell_at_open
  3. gap < -0.5% → wait_bounce
  4. |gap| > 10% → monitor (复权异常标记)
  5. -0.5% ≤ gap ≤ 0.5% → monitor
  6. stop_loss_price = prev_close * 0.98 (仅 wait_bounce)
  7. parquet round-trip 一致
  8. T+1 OHLC 缺失 → 返回 None 不崩
"""

import logging
from pathlib import Path

import pandas as pd
import pytest
from summary.report.segment_win_db import (
    INTRADAY_STRATEGY_COLUMNS,
    compute_intraday_strategy,
    load_intraday_strategy_recommendation,
    save_intraday_strategy_recommendation,
)


@pytest.fixture
def fixture_logger():
    return logging.getLogger("test_intraday")


@pytest.fixture
def fixture_details_path(tmp_path: Path) -> Path:
    """构造一个 8 只 S6 段的 stock_details (含 1 高开, 1 低开, 1 平开, 1 异常)."""
    p = tmp_path / "segment_stock_details.parquet"
    df = pd.DataFrame(
        {
            "pipeline": ["ob_quality"] * 8,
            "weight_method": ["rolling_icir_weight"] * 8,
            "selection_date": ["2026-06-15"] * 8,
            "segment_label": ["S6"] * 8,
            "asset": ["000001", "000002", "000003", "000004",
                      "000005", "000006", "000007", "000008"],
            "composite_value": [0.5, 0.4, 0.3, 0.2, 0.1, 0.0, -0.1, -0.2],
            "rank": [21, 22, 23, 24, 25, 26, 27, 28],
            "created_at": ["2026-06-15T00:00:00"] * 8,
        }
    )
    df.to_parquet(p, index=False)
    return p


@pytest.fixture
def fixture_master_with_t1(tmp_path: Path) -> Path:
    """构造一个最小 master parquet (含 T 日 close + T+1 日 OHLC)."""
    p = tmp_path / "factor_ic_data.parquet"
    date_t = pd.Timestamp("2026-06-15")
    date_t1 = pd.Timestamp("2026-06-16")

    rows = []
    for asset, t_close, t1_open, t1_high, t1_low, t1_close, fwd_ret in [
        ("000001", 10.00, 10.50, 11.00, 10.20, 10.80, 0.08),   # 高开 +5%
        ("000002", 20.00, 19.50, 20.50, 19.00, 19.80, -0.01),  # 低开 -2.5%
        ("000003", 30.00, 30.05, 30.50, 29.80, 30.10, 0.003),   # 平开 +0.17%
        ("000004", 40.00, 39.00, 39.50, 36.50, 37.00, -0.075),  # 低开 -2.5% (深)
        ("000005", 50.00, 50.50, 51.00, 50.20, 50.80, 0.016),   # 平开 +1% (其实算高)
        ("000006", 60.00, 60.10, 60.30, 59.95, 60.20, 0.003),   # 平开 +0.17%
        ("000007", 70.00, 71.00, 72.00, 70.50, 71.50, 0.021),   # 高开 +1.4%
        ("000008", 80.00, 90.00, 92.00, 88.00, 91.00, 0.14),    # 异常 +12.5%
    ]:
        # T 日 close
        rows.append(
            {
                "date": date_t,
                "asset": asset,
                "open": t_close,
                "high": t_close,
                "low": t_close,
                "close": t_close,
                "forward_return_1d": 0.0,
                "turnover_rate": 5.0,
                "rsi_6": 80,
            }
        )
        # T+1 日 OHLC
        rows.append(
            {
                "date": date_t1,
                "asset": asset,
                "open": t1_open,
                "high": t1_high,
                "low": t1_low,
                "close": t1_close,
                "forward_return_1d": fwd_ret,
                "turnover_rate": 5.0,
                "rsi_6": 80,
            }
        )

    pd.DataFrame(rows).to_parquet(p, index=False)
    return p


# ── T1: 8 只分桶边界正确 ────────────────────────────────────────────────


def test_5_segment_buckets_correct(
    fixture_logger, fixture_master_with_t1, fixture_details_path
):
    df = compute_intraday_strategy(
        pipeline="ob_quality",
        weight_method="rolling_icir_weight",
        selection_date="2026-06-15",
        logger=fixture_logger,
        factor_data_path=fixture_master_with_t1,
        stock_details_path=fixture_details_path,
    )
    assert df is not None
    assert len(df) == 8

    # 逐只验证
    by_asset = {row["asset"]: row for _, row in df.iterrows()}
    # 000001: 高开 +5% → sell_at_open
    assert by_asset["000001"]["open_signal"] == "high"
    assert by_asset["000001"]["recommended_action"] == "sell_at_open"
    assert by_asset["000001"]["stop_loss_price"] == 0.0
    # 000002: 低开 -2.5% → wait_bounce, stop_loss = 19.6
    assert by_asset["000002"]["open_signal"] == "low"
    assert by_asset["000002"]["recommended_action"] == "wait_bounce"
    assert by_asset["000002"]["stop_loss_price"] == pytest.approx(19.6, abs=0.01)
    # 000003: 平开 +0.17% → monitor, stop_loss=0
    assert by_asset["000003"]["open_signal"] == "flat"
    assert by_asset["000003"]["recommended_action"] == "monitor"
    # 000008: 异常 +12.5% → abnormal
    assert by_asset["000008"]["open_signal"] == "abnormal"
    assert bool(by_asset["000008"]["adjustment_abnormal"])  # noqa: E501
    assert by_asset["000008"]["recommended_action"] == "monitor"


# ── T2: 复权异常股被识别 ────────────────────────────────────────────────


def test_adjustment_abnormal_marked(
    fixture_logger, fixture_master_with_t1, fixture_details_path
):
    df = compute_intraday_strategy(
        pipeline="ob_quality",
        weight_method="rolling_icir_weight",
        selection_date="2026-06-15",
        logger=fixture_logger,
        factor_data_path=fixture_master_with_t1,
        stock_details_path=fixture_details_path,
    )
    abnormal = df[df["open_signal"] == "abnormal"]
    assert len(abnormal) == 1
    assert abnormal.iloc[0]["asset"] == "000008"
    assert bool(abnormal.iloc[0]["adjustment_abnormal"]) is True


# ── T3: real_gap_pct 用真前收, 不用 forward_return_1d 反推 ─────────────


def test_real_gap_uses_actual_close_not_inferred(
    fixture_logger, fixture_master_with_t1, fixture_details_path
):
    """关键 invariant: gap = (open - prev_close)/prev_close, 不是 (open - close/(1+fwd))/..."""
    df = compute_intraday_strategy(
        pipeline="ob_quality",
        weight_method="rolling_icir_weight",
        selection_date="2026-06-15",
        logger=fixture_logger,
        factor_data_path=fixture_master_with_t1,
        stock_details_path=fixture_details_path,
    )
    # 000008: prev_close=80, open=90, fwd_ret=0.14
    # 真前收算法: (90-80)/80*100 = +12.5%
    # 反推前收算法: (90 - 91/1.14) / (91/1.14) * 100 = (90 - 79.82)/79.82*100 ≈ +12.74%
    # 测试用真前收, 确认值是 +12.5
    asset_08 = df[df["asset"] == "000008"].iloc[0]
    assert asset_08["real_gap_pct"] == pytest.approx(12.5, abs=0.01)
    # 异常阈值是 10%, 所以归到 abnormal
    assert asset_08["open_signal"] == "abnormal"


# ── T4: gap > +0.5% → sell_at_open ────────────────────────────────────


def test_gap_above_threshold_sell_at_open(
    fixture_logger, fixture_master_with_t1, fixture_details_path
):
    df = compute_intraday_strategy(
        pipeline="ob_quality",
        weight_method="rolling_icir_weight",
        selection_date="2026-06-15",
        logger=fixture_logger,
        factor_data_path=fixture_master_with_t1,
        stock_details_path=fixture_details_path,
    )
    high = df[df["open_signal"] == "high"]
    assert len(high) >= 1
    for _, row in high.iterrows():
        assert row["recommended_action"] == "sell_at_open"
        assert row["stop_loss_price"] == 0.0
        # 期望收益 = (open - prev_close) / prev_close * 100
        assert row["expected_return_pct"] > 0


# ── T5: gap < -0.5% → wait_bounce + stop_loss = prev_close * 0.98 ──────


def test_gap_below_threshold_wait_bounce_with_stop_loss(
    fixture_logger, fixture_master_with_t1, fixture_details_path
):
    df = compute_intraday_strategy(
        pipeline="ob_quality",
        weight_method="rolling_icir_weight",
        selection_date="2026-06-15",
        logger=fixture_logger,
        factor_data_path=fixture_master_with_t1,
        stock_details_path=fixture_details_path,
    )
    low = df[df["open_signal"] == "low"]
    assert len(low) >= 1
    for _, row in low.iterrows():
        assert row["recommended_action"] == "wait_bounce"
        # 止损价 = prev_close * 0.98
        expected_stop = round(row["prev_close"] * 0.98, 4)
        assert row["stop_loss_price"] == pytest.approx(expected_stop, abs=0.001)
        assert row["expected_return_pct"] > 0  # 历史期望均收正值


# ── T6: parquet round-trip 一致 ────────────────────────────────────────


def test_parquet_round_trip(
    fixture_logger, fixture_master_with_t1, fixture_details_path, tmp_path
):
    fp = tmp_path / "intraday.parquet"
    out = compute_intraday_strategy(
        pipeline="ob_quality",
        weight_method="rolling_icir_weight",
        selection_date="2026-06-15",
        logger=fixture_logger,
        factor_data_path=fixture_master_with_t1,
        stock_details_path=fixture_details_path,
    )
    # write 用的是 _INTRADAY_STRATEGY_PATH 默认值; 直接调用 save_*
    save_intraday_strategy_recommendation(
        pipeline="ob_quality",
        weight_method="rolling_icir_weight",
        selection_date="2026-06-15",
        df=out,
        file_path=fp,
    )
    loaded = load_intraday_strategy_recommendation(
        pipeline="ob_quality",
        weight_method="rolling_icir_weight",
        selection_date="2026-06-15",
        file_path=fp,
    )
    assert len(loaded) == len(out)
    # 关键字段 round-trip 一致
    for orig, back in zip(out.to_dict("records"), loaded):
        assert orig["asset"] == back["asset"]
        assert orig["real_gap_pct"] == pytest.approx(back["real_gap_pct"], abs=0.001)
        assert orig["open_signal"] == back["open_signal"]
        assert orig["recommended_action"] == back["recommended_action"]


# ── T7: T+1 OHLC 缺失 → None 不崩 ────────────────────────────────────


def test_missing_t1_returns_none(fixture_logger, fixture_details_path, tmp_path):
    """T+1 数据未到位时返回 None, 不写文件, 不崩."""
    # master 只有 T 日数据, 没有 T+1
    p = tmp_path / "factor_ic_data.parquet"
    rows = []
    for asset in ["000001", "000002", "000003", "000004",
                  "000005", "000006", "000007", "000008"]:
        rows.append(
            {
                "date": pd.Timestamp("2026-06-15"),
                "asset": asset,
                "open": 50.0,
                "high": 50.0,
                "low": 50.0,
                "close": 50.0,
                "forward_return_1d": 0.0,
                "turnover_rate": 5.0,
                "rsi_6": 80,
            }
        )
    pd.DataFrame(rows).to_parquet(p, index=False)

    df = compute_intraday_strategy(
        pipeline="ob_quality",
        weight_method="rolling_icir_weight",
        selection_date="2026-06-15",
        logger=fixture_logger,
        factor_data_path=p,
        stock_details_path=fixture_details_path,
    )
    assert df is None


# ── T8: 报告渲染函数存在 + 入口可调用 ──────────────────────────────────


def test_render_section_importable():
    from summary.report.data_loaders import load_intraday_strategy
    from summary.report.sections import _render_intraday_strategy_section
    assert callable(_render_intraday_strategy_section)
    assert callable(load_intraday_strategy)


# ── T9: S6 段无明细 → 返回 None ────────────────────────────────────────


def test_missing_s6_segment(
    fixture_logger, fixture_master_with_t1, tmp_path
):
    """stock_details 没有 S6 段 → 返回 None."""
    p = tmp_path / "segment_stock_details.parquet"
    df = pd.DataFrame(
        {
            "pipeline": ["ob_quality"] * 2,
            "weight_method": ["rolling_icir_weight"] * 2,
            "selection_date": ["2026-06-15"] * 2,
            "segment_label": ["S1", "S30"],  # 不是 S6
            "asset": ["000001", "000008"],
            "composite_value": [0.5, -0.2],
            "rank": [1, 86],
            "created_at": ["2026-06-15T00:00:00"] * 2,
        }
    )
    df.to_parquet(p, index=False)

    result = compute_intraday_strategy(
        pipeline="ob_quality",
        weight_method="rolling_icir_weight",
        selection_date="2026-06-15",
        logger=fixture_logger,
        factor_data_path=fixture_master_with_t1,
        stock_details_path=p,
    )
    assert result is None


# ── T10: COLUMNS schema 完整性 ────────────────────────────────────────


def test_columns_schema_complete():
    """INTRADAY_STRATEGY_COLUMNS 必须覆盖所有段渲染字段."""
    required = {
        "pipeline", "weight_method", "selection_date", "trade_date",
        "segment_label", "asset", "rank", "composite_value",
        "prev_close", "open", "high", "low", "close",
        "forward_return_1d", "real_gap_pct", "open_signal",
        "recommended_action", "expected_return_pct", "stop_loss_price",
        "adjustment_abnormal", "created_at",
    }
    actual = set(INTRADAY_STRATEGY_COLUMNS)
    assert required.issubset(actual), (
        f"missing columns: {required - actual}"
    )
