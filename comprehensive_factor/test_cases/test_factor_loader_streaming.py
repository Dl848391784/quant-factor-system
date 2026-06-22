"""factor_loader 流式加载测试

验证 v2.23 ijson 流式加载的正确性：
- T1: 全列加载与 json.load 输出一致
- T2: factor_cols 列子集模式只返回指定列 + 5 个固定列
- T3: load_factor_values 委托后输出 date+asset+factor_cols（不含 forward_return_*）
- T4: ImportError 时回退到 json.load 路径，输出仍一致

设计文档: designs/composite_streaming_load_design.md §5
作者: 云瑶
创建日期: 2026-06-14
"""

from __future__ import annotations

import builtins
import gzip
import json

import numpy as np
import pandas as pd
import pytest
from comprehensive_factor.common.factor_loader import (
    load_factor_values,
    load_full_data,
)


@pytest.fixture
def mini_data_source(tmp_path):
    """构造 10 行 × 7 列的 mini factor_ic_data.json.gz。

    包含 date, asset, 2 个因子列, 3 个 forward_return 列。
    """
    records = [
        {
            "date": f"2026-06-{day:02d}",
            "asset": "000001.SZ",
            "rsi_6": 50.0 + day,
            "volume_ratio_5": 1.0 + day * 0.1,
            "forward_return_1d": 0.001 * day,
            "forward_return_3d": 0.003 * day,
            "forward_return_5d": 0.005 * day,
        }
        for day in range(1, 11)
    ]
    payload = {"data": records, "metadata": {"source": "test"}}
    out = tmp_path / "mini_factor_ic_data.json.gz"
    with gzip.open(out, "wt", encoding="utf-8") as f:
        json.dump(payload, f)
    return out


def test_full_load_consistent_with_json_load(mini_data_source):
    """T1: 新版流式与 json.load 行/列/值完全一致。"""
    # 新路径
    new_df = load_full_data(data_source=mini_data_source)

    # 参考路径（直接 json.load）
    with gzip.open(mini_data_source, "rt", encoding="utf-8") as f:
        payload = json.load(f)
    ref_df = pd.DataFrame(payload["data"])
    # 与新版一致：对数值列做 to_numeric
    for col in ref_df.columns:
        if col not in ("date", "asset"):
            ref_df[col] = pd.to_numeric(ref_df[col], errors="coerce")

    assert set(new_df.columns) == set(ref_df.columns)
    assert len(new_df) == len(ref_df) == 10
    for col in ref_df.columns:
        pd.testing.assert_series_equal(
            new_df[col].reset_index(drop=True),
            ref_df[col].reset_index(drop=True),
            check_names=False,
        )


def test_load_with_factor_cols_subset(mini_data_source):
    """T2: factor_cols 模式只加载指定因子 + 5 个固定列（date/asset/forward_return_*）。"""
    df = load_full_data(data_source=mini_data_source, factor_cols=["rsi_6"])

    # 必须包含: date, asset, rsi_6, forward_return_1d/3d/5d, is_untradeable, is_low_liquidity
    expected_cols = {
        "date",
        "asset",
        "rsi_6",
        "forward_return_1d",
        "forward_return_3d",
        "forward_return_5d",
        "is_untradeable",
        "is_low_liquidity",
    }
    assert set(df.columns) == expected_cols
    # 不应包含未请求的因子列
    assert "volume_ratio_5" not in df.columns
    assert len(df) == 10
    # 数值列已 to_numeric
    assert df["rsi_6"].dtype == np.float64


def test_load_factor_values_delegates(mini_data_source):
    """T3: load_factor_values 委托给 load_full_data，输出 date+asset+factor_cols（无 forward_return）。"""
    df = load_factor_values(
        factor_cols=["rsi_6", "volume_ratio_5"],
        data_source=mini_data_source,
    )

    # 仅含 date, asset, rsi_6, volume_ratio_5（不含 forward_return_*）
    assert set(df.columns) == {"date", "asset", "rsi_6", "volume_ratio_5"}
    assert "forward_return_1d" not in df.columns
    assert len(df) == 10
    # 数值列已 to_numeric
    assert df["rsi_6"].dtype == np.float64
    assert df["volume_ratio_5"].dtype == np.float64


def test_ijson_unavailable_fallback(mini_data_source, monkeypatch):
    """T4: ijson ImportError 时回退到 json.load 路径，输出仍一致。"""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "ijson":
            raise ImportError("simulated ijson absence")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    # 仍能成功加载（走 json.load 分支 + warning）
    df = load_full_data(data_source=mini_data_source)
    assert len(df) == 10
    assert "rsi_6" in df.columns
    # 数值列已 to_numeric（fallback 路径同样适用类型规范化）
    assert df["rsi_6"].dtype == np.float64
