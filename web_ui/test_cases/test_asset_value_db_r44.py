"""v0.4.8 R44 单元测试: load_asset_value_trend() 几何复合资产值.

§18.1f v1.5.12 实战锚点: 新组件必须真实 parquet 验证, 不允许只 mock.

测试场景:
1. 真实 ssd + master 跑通 → 返回非 None, 含 30 段 × (N+1) 资产值 + 起点 1.00
2. asset[0] = 1.00 (起点), 后续 = 几何复合
3. final_value = asset[-1], total_return_pct = (final - 1) * 100
4. 继承 R43 失败 → 返回 None (R43 None → R44 None)
"""

from __future__ import annotations

import logging

import pytest
from web_ui.common.asset_value_db import load_asset_value_trend
from web_ui.common.pl_ratio_db import (
    _MASTER_PARQUET_PATH,
    _SEGMENT_STOCK_DETAILS_PATH,
)


@pytest.mark.skipif(
    not _SEGMENT_STOCK_DETAILS_PATH.exists() or not _MASTER_PARQUET_PATH.exists(),
    reason="parquet 缺失, 跳过实测",
)
def test_load_asset_value_trend_runs_on_real_parquet():
    """R44 主路径: 真实 parquet 上能跑通, 几何复合结果合理."""
    logger = logging.getLogger(__name__)
    result = load_asset_value_trend(n_recent_dates=12, logger=logger)

    assert result is not None, "真实 parquet 都存在, 不应返回 None"
    assert set(result.keys()) >= {"dates", "start_date", "segments", "source"}
    assert result["source"] == "summary_segment_stock_details_plus_master"

    # dates 长度
    n_dates = len(result["dates"])
    assert n_dates > 0

    # start_date = dates[0] (Q2 用户决策)
    assert result["start_date"] == result["dates"][0]

    # 30 段
    assert len(result["segments"]) == 30
    labels = [s["label"] for s in result["segments"]]
    assert labels == [f"S{i}" for i in range(1, 31)]

    # 每段 asset_values 长度 = dates + 1 (含起点)
    for seg in result["segments"]:
        assert len(seg["asset_values"]) == n_dates + 1, (
            f"{seg['label']} asset_values 长度应为 {n_dates + 1}, 实际 {len(seg['asset_values'])}"
        )
        # asset[0] = 1.00
        assert seg["asset_values"][0] == 1.0, f"{seg['label']} 起点应为 1.00, 实际 {seg['asset_values'][0]}"

    # final_value = asset_values[-1]
    # total_return_pct = (final - 1) * 100
    for seg in result["segments"]:
        assert seg["final_value"] == seg["asset_values"][-1]
        expected_ret = round((seg["final_value"] - 1) * 100, 2)
        assert seg["total_return_pct"] == expected_ret

    # 资产值合理范围: 通常 0.5 ~ 2.0 (15 天不至于跌 50% 或翻倍)
    for seg in result["segments"]:
        assert 0.3 <= seg["final_value"] <= 2.0, f"{seg['label']} final_value={seg['final_value']} 异常"


def test_load_asset_value_trend_geom_compound_calculation():
    """R44 几何复合算法自检: 用 mock R43 数据, 验证链式乘法 + 起点 1.00."""
    from unittest.mock import patch

    # mock R43 返回固定 seg_return (3 天: +5%, -3%, +2%)
    # 预期: 1.00 → 1.05 → 1.05 * 0.97 = 1.0185 → 1.0185 * 1.02 = 1.0389
    mock_pl_trend = {
        "dates": ["07-01", "07-02", "07-03"],
        "avg_line": [1.5, -0.8, 2.0],
        "source": "test",
        "segments": [
            {"label": "S1", "pl_ratios": [5.0, -3.0, 2.0], "avg_pl_ratio": 1.33},
            {"label": "S2", "pl_ratios": [-1.0, -1.0, -1.0], "avg_pl_ratio": -1.0},
        ],
    }
    with patch("web_ui.common.asset_value_db.load_pl_ratio_trend", return_value=mock_pl_trend):
        result = load_asset_value_trend(logger=logging.getLogger(__name__))

    assert result is not None
    # S1: 1.00 → 1.05 → 1.0185 → 1.03887
    s1_assets = result["segments"][0]["asset_values"]
    assert s1_assets[0] == 1.00
    assert abs(s1_assets[1] - 1.05) < 1e-4  # 1.00 * (1 + 5/100)
    assert abs(s1_assets[2] - 1.0185) < 1e-4  # 1.05 * (1 - 3/100)
    assert abs(s1_assets[3] - 1.03887) < 1e-3  # 1.0185 * (1 + 2/100)

    # S2: 1.00 → 0.99 → 0.9801 → 0.970299 (连续 -1%)
    s2_assets = result["segments"][1]["asset_values"]
    assert s2_assets[0] == 1.00
    assert abs(s2_assets[1] - 0.99) < 1e-4
    assert abs(s2_assets[2] - 0.9801) < 1e-4
    assert abs(s2_assets[3] - 0.970299) < 1e-4

    # final_value + total_return_pct
    assert result["segments"][0]["final_value"] == s1_assets[-1]
    assert result["segments"][0]["total_return_pct"] == round((1.03887 - 1) * 100, 2)


def test_load_asset_value_trend_returns_none_when_r43_fails():
    """R44 继承 R43 失败: pl_ratio_trend None → asset_value_trend None."""
    from unittest.mock import patch

    with patch("web_ui.common.asset_value_db.load_pl_ratio_trend", return_value=None):
        result = load_asset_value_trend(logger=logging.getLogger(__name__))
    assert result is None, "R43 失败时 R44 应返回 None"
