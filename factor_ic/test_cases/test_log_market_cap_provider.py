"""LogMarketCapProvider 单元测试（P2.1）。

覆盖：
    - gzip JSON `{meta, data}` 结构读取与 dates/assets 切片
    - `circ_market_cap` 缺失 / <=0 剔除
    - `ln(circ_market_cap)` + 每日截面 winsorize(1%, 99%)
    - numerical design column / 小样本过滤 / meta copy

参考: designs/feat_neutralization_framework.md §9.2（P2.1）
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factor_ic.common.control_providers.base import ControlProvider
from factor_ic.common.control_providers.log_market_cap import LogMarketCapProvider


def _write_market_cap_fixture(path: Path, records: list[dict]) -> Path:
    payload = {
        "meta": {"source": "unit-test", "version": "1.0"},
        "data": records,
    }
    with gzip.open(path, "wt", encoding="utf-8") as fp:
        json.dump(payload, fp)
    return path


@pytest.fixture
def market_cap_path(tmp_path: Path) -> Path:
    records = [
        {"date": "2024-01-01", "asset": "000001", "circ_market_cap": 100.0, "total_market_cap": 200.0},
        {"date": "2024-01-01", "asset": "000002", "circ_market_cap": 200.0, "total_market_cap": 300.0},
        {"date": "2024-01-01", "asset": "000003", "circ_market_cap": 300.0, "total_market_cap": 400.0},
        {"date": "2024-01-02", "asset": "000001", "circ_market_cap": 400.0, "total_market_cap": 500.0},
        {"date": "2024-01-02", "asset": "000002", "circ_market_cap": 0.0, "total_market_cap": 600.0},
        {"date": "2024-01-02", "asset": "000003", "circ_market_cap": None, "total_market_cap": 700.0},
        {"date": "2024-01-03", "asset": "999999", "circ_market_cap": 999.0, "total_market_cap": 999.0},
    ]
    return _write_market_cap_fixture(tmp_path / "market_cap_data.json.gz", records)


class TestLogMarketCapProviderContract:
    def test_satisfies_protocol(self, market_cap_path: Path):
        provider = LogMarketCapProvider(source_path=market_cap_path)
        assert isinstance(provider, ControlProvider)
        assert provider.name == "log_market_cap"
        assert provider.column_type == "numerical"
        assert provider.join_keys == ["date", "asset"]

    def test_meta_initial_values(self, market_cap_path: Path):
        provider = LogMarketCapProvider(source_path=market_cap_path)
        meta = provider.get_meta()
        assert meta["source_field"] == "circ_market_cap"
        assert meta["winsorize_quantiles"] == [0.01, 0.99]
        assert meta["n_loaded"] == 0


class TestLogMarketCapProviderLoad:
    def test_load_reads_gzip_json_data_field_and_slices(self, market_cap_path: Path):
        provider = LogMarketCapProvider(source_path=market_cap_path)
        result = provider.load(
            dates=["2024-01-01", "2024-01-02"],
            assets=["000001", "000003"],
        )

        assert list(result.columns) == ["date", "asset", "circ_market_cap"]
        assert len(result) == 4
        assert set(result["date"]) == {"2024-01-01", "2024-01-02"}
        assert set(result["asset"]) == {"000001", "000003"}
        assert provider.get_meta()["n_loaded"] == 7
        assert provider.get_meta()["n_after_slice"] == 4

    def test_load_missing_file_raises(self, tmp_path: Path):
        provider = LogMarketCapProvider(source_path=tmp_path / "missing.json.gz")
        with pytest.raises(FileNotFoundError, match="市值数据文件不存在"):
            provider.load(dates=["2024-01-01"], assets=["000001"])

    def test_load_missing_required_column_raises(self, tmp_path: Path):
        path = _write_market_cap_fixture(tmp_path / "bad.json.gz", [{"date": "2024-01-01", "asset": "000001"}])
        provider = LogMarketCapProvider(source_path=path)
        with pytest.raises(ValueError, match="缺少必需列"):
            provider.load(dates=["2024-01-01"], assets=["000001"])


class TestLogMarketCapProviderPreprocess:
    def test_preprocess_ln_and_drop_invalid(self, market_cap_path: Path):
        provider = LogMarketCapProvider(source_path=market_cap_path)
        raw = provider.load(
            dates=["2024-01-02"],
            assets=["000001", "000002", "000003"],
        )
        result = provider.preprocess(raw)

        assert list(result.columns) == ["date", "asset", "log_market_cap"]
        assert len(result) == 1
        assert result.iloc[0]["asset"] == "000001"
        assert result.iloc[0]["log_market_cap"] == pytest.approx(np.log(400.0))
        assert provider.get_meta()["n_missing_or_non_positive_dropped"] == 2

    def test_preprocess_winsorizes_per_date(self, tmp_path: Path):
        records = []
        for i, cap in enumerate([1.0, 2.0, 3.0, 4.0, 1000.0], start=1):
            records.append(
                {
                    "date": "2024-02-01",
                    "asset": f"{i:06d}",
                    "circ_market_cap": cap,
                    "total_market_cap": cap,
                }
            )
        path = _write_market_cap_fixture(tmp_path / "winsor.json.gz", records)
        provider = LogMarketCapProvider(source_path=path)
        raw = provider.load(dates=["2024-02-01"], assets=[f"{i:06d}" for i in range(1, 6)])
        result = provider.preprocess(raw)

        logs = pd.Series(np.log([1.0, 2.0, 3.0, 4.0, 1000.0]))
        expected_lo = logs.quantile(0.01)
        expected_hi = logs.quantile(0.99)
        assert result["log_market_cap"].min() == pytest.approx(expected_lo)
        assert result["log_market_cap"].max() == pytest.approx(expected_hi)
        assert provider.get_meta()["n_winsorized_low"] == 1
        assert provider.get_meta()["n_winsorized_high"] == 1

    def test_preprocess_empty_returns_contract_columns(self, market_cap_path: Path):
        provider = LogMarketCapProvider(source_path=market_cap_path)
        empty = pd.DataFrame(columns=["date", "asset", "circ_market_cap"])
        result = provider.preprocess(empty)
        assert list(result.columns) == ["date", "asset", "log_market_cap"]
        assert result.empty


class TestLogMarketCapProviderFilterAndDesign:
    def test_filter_invalid_rows_skips_small_day(self, market_cap_path: Path):
        provider = LogMarketCapProvider(source_path=market_cap_path)
        df = pd.DataFrame(
            {
                "date": ["2024-01-01"] * 2,
                "asset": ["000001", "000002"],
                "factor": [1.0, 2.0],
                "log_market_cap": [10.0, 11.0],
            }
        )
        result = provider.filter_invalid_rows(df, min_count=3)
        assert result.empty

    def test_filter_invalid_rows_keeps_large_day(self, market_cap_path: Path):
        provider = LogMarketCapProvider(source_path=market_cap_path)
        df = pd.DataFrame(
            {
                "date": ["2024-01-01"] * 3,
                "asset": ["000001", "000002", "000003"],
                "factor": [1.0, 2.0, 3.0],
                "log_market_cap": [10.0, 11.0, 12.0],
            }
        )
        result = provider.filter_invalid_rows(df, min_count=3)
        assert len(result) == 3

    def test_to_design_columns_single_numeric_column(self, market_cap_path: Path):
        provider = LogMarketCapProvider(source_path=market_cap_path)
        df = pd.DataFrame({"log_market_cap": [10.0, 11.0, 12.0], "factor": [1.0, 2.0, 3.0]})
        result = provider.to_design_columns(df, drop_first=True)
        assert list(result.columns) == ["log_market_cap"]
        assert result.shape == (3, 1)

    def test_get_meta_returns_copy(self, market_cap_path: Path):
        provider = LogMarketCapProvider(source_path=market_cap_path)
        meta = provider.get_meta()
        meta["n_loaded"] = 999
        assert provider.get_meta()["n_loaded"] == 0
