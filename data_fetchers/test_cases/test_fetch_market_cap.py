#!/usr/bin/env python3
"""
fetch_market_cap.py 测试（C2b + C2c）

测试覆盖（详见 design.md §9）：
- TC-U-01..03 load_target_assets：正常 / 缺 codes / 过滤 ST
- TC-U-04..06 _normalize_fields：13 列 → 12 列 / 空 df / 缺必要字段
- TC-U-07     _clip_to_target_range：闭区间裁剪
- TC-U-08..12 fetch_one_stock：成功 / 重试成功 / 全失败 / 空区间裁剪
- TC-U-13..15 fetch_batch：成功 / 失败率>50% / 空 symbols

运行方式：
    pytest data_fetchers/test_cases/test_fetch_market_cap.py -v

版本历史：
- v1.0 (2026-06-18): C2b 三个纯函数单测
- v1.1 (2026-06-18): C2c fetch_one_stock + fetch_batch 单测
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch as mock_patch

import pandas as pd
import pytest


sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from data_fetchers.fetch_market_cap import (  # noqa: E402
    _OUTPUT_COLUMNS,
    _clip_to_target_range,
    _normalize_fields,
    _read_factor_data_date_range,
    fetch_batch,
    fetch_one_stock,
    load_target_assets,
    save_batch_cache,
)


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def stock_list_payload() -> dict:
    """构造合法 stock_list.json payload。"""
    return {
        "meta": {"last_updated": "2026-06-18", "source": "akshare", "total_count": 5},
        "stocks": [
            {"code": "000001", "name": "平安银行", "market": "SZ", "added_at": "2024-03-18"},
            {"code": "000002", "name": "万科A", "market": "SZ", "added_at": "2024-03-18"},
            {"code": "000003", "name": "*ST国华", "market": "SZ", "added_at": "2024-03-18"},
            {"code": "000004", "name": "ST中绒", "market": "SZ", "added_at": "2024-03-18"},
            {"code": "600000", "name": "浦发银行", "market": "SH", "added_at": "2024-03-18"},
        ],
        "codes": ["000001", "000002", "000003", "000004", "600000"],
    }


@pytest.fixture
def stock_list_file(tmp_path: Path, stock_list_payload: dict) -> Path:
    """落盘 stock_list.json 到临时目录。"""
    f = tmp_path / "stock_list.json"
    f.write_text(json.dumps(stock_list_payload, ensure_ascii=False), encoding="utf-8")
    return f


@pytest.fixture
def fake_em_df() -> pd.DataFrame:
    """构造 ak.stock_value_em 返回结果（13 列）。"""
    return pd.DataFrame(
        {
            "数据日期": ["2024-03-18", "2024-03-19", "2024-03-20"],
            "当日收盘价": [10.5, 10.6, 10.7],
            "当日涨跌幅": [0.5, 0.95, 0.94],
            "总市值": [1.0e10, 1.01e10, 1.02e10],
            "流通市值": [8.0e9, 8.1e9, 8.2e9],
            "总股本": [1_000_000_000, 1_000_000_000, 1_000_000_000],
            "流通股本": [800_000_000, 800_000_000, 800_000_000],
            "PE(TTM)": [12.5, 12.6, 12.7],
            "PE(静)": [13.0, 13.1, 13.2],
            "市净率": [1.5, 1.51, 1.52],
            "PEG值": [0.8, 0.81, 0.82],
            "市现率": [9.5, 9.6, 9.7],
            "市销率": [2.5, 2.51, 2.52],
        }
    )


# ============================================================
# TC-U-01..03: load_target_assets
# ============================================================


def test_load_target_assets_normal(stock_list_file: Path) -> None:
    """TC-U-01: 正常加载，过滤 ST 股票。"""
    codes = load_target_assets(stock_list_file=stock_list_file)
    # 5 总数，2 个 ST（*ST国华 / ST中绒）被过滤 → 3
    assert codes == ["000001", "000002", "600000"]


def test_load_target_assets_missing_file(tmp_path: Path) -> None:
    """TC-U-02: 文件不存在抛 FileNotFoundError。"""
    nonexistent = tmp_path / "missing.json"
    with pytest.raises(FileNotFoundError, match="stock_list 文件不存在"):
        load_target_assets(stock_list_file=nonexistent)


def test_load_target_assets_missing_codes_field(tmp_path: Path) -> None:
    """TC-U-03: codes 字段缺失抛 KeyError。"""
    f = tmp_path / "bad.json"
    f.write_text(json.dumps({"meta": {}, "stocks": []}), encoding="utf-8")
    with pytest.raises(KeyError, match="缺少 'codes' 字段"):
        load_target_assets(stock_list_file=f)


# ============================================================
# TC-U-04..06: _normalize_fields
# ============================================================


def test_normalize_fields_full_mapping(fake_em_df: pd.DataFrame) -> None:
    """TC-U-04: 13 列 → 12 列，drop 当日收盘价/当日涨跌幅，列顺序对齐 _OUTPUT_COLUMNS。"""
    result = _normalize_fields(fake_em_df, symbol="000001")

    assert list(result.columns) == list(_OUTPUT_COLUMNS)
    assert len(result) == 3
    assert (result["asset"] == "000001").all()
    assert result["date"].iloc[0] == "2024-03-18"
    # drop 列不应出现
    assert "当日收盘价" not in result.columns
    assert "当日涨跌幅" not in result.columns
    # 字段值正确映射
    assert result["circ_market_cap"].iloc[0] == pytest.approx(8.0e9)
    assert result["pe_ttm"].iloc[0] == pytest.approx(12.5)
    assert result["pb"].iloc[0] == pytest.approx(1.5)


def test_normalize_fields_empty_df() -> None:
    """TC-U-05: 空 df 返回 12 列空结构（避免下游 concat 报错）。"""
    empty = pd.DataFrame()
    result = _normalize_fields(empty, symbol="000001")

    assert list(result.columns) == list(_OUTPUT_COLUMNS)
    assert len(result) == 0


def test_normalize_fields_missing_required_field(fake_em_df: pd.DataFrame) -> None:
    """TC-U-06: 缺少必要字段（流通市值）抛 ValueError。"""
    bad_df = fake_em_df.drop(columns=["流通市值"])
    with pytest.raises(ValueError, match="缺少必要字段"):
        _normalize_fields(bad_df, symbol="000001")


# ============================================================
# TC-U-07: _clip_to_target_range
# ============================================================


def test_clip_to_target_range_inclusive(fake_em_df: pd.DataFrame) -> None:
    """TC-U-07: 闭区间裁剪，边界日期保留。"""
    df = _normalize_fields(fake_em_df, symbol="000001")
    # 数据 2024-03-18 ~ 2024-03-20
    clipped = _clip_to_target_range(df, ("2024-03-19", "2024-03-20"))

    assert len(clipped) == 2
    assert clipped["date"].tolist() == ["2024-03-19", "2024-03-20"]


def test_clip_to_target_range_empty_df() -> None:
    """TC-U-07b: 空 df 直接返回（边界保护）。"""
    empty = pd.DataFrame(columns=list(_OUTPUT_COLUMNS))
    clipped = _clip_to_target_range(empty, ("2024-03-18", "2024-03-20"))

    assert len(clipped) == 0
    assert list(clipped.columns) == list(_OUTPUT_COLUMNS)


def test_clip_to_target_range_reversed_range(fake_em_df: pd.DataFrame) -> None:
    """TC-U-07c: 起止日期逆序抛 ValueError。"""
    df = _normalize_fields(fake_em_df, symbol="000001")
    with pytest.raises(ValueError, match="起止逆序"):
        _clip_to_target_range(df, ("2024-03-20", "2024-03-18"))


# ============================================================
# TC-U-08..12: fetch_one_stock
# ============================================================


def test_fetch_one_stock_success(fake_em_df: pd.DataFrame) -> None:
    """TC-U-08: 一次成功调用，返回归一化裁剪后的 12 列 DataFrame。"""
    with (
        mock_patch(
            "data_fetchers.fetch_market_cap.ak.stock_value_em",
            return_value=fake_em_df,
        ),
        mock_patch("data_fetchers.fetch_market_cap.time.sleep"),
    ):
        result = fetch_one_stock("000001", ("2024-03-18", "2024-03-20"))

    assert result is not None
    assert list(result.columns) == list(_OUTPUT_COLUMNS)
    assert len(result) == 3
    assert (result["asset"] == "000001").all()


def test_fetch_one_stock_retry_then_success(fake_em_df: pd.DataFrame) -> None:
    """TC-U-09: 第一次失败，第二次成功，最终返回 DataFrame。"""
    call_log = {"calls": 0}

    def _flaky(symbol: str) -> pd.DataFrame:
        call_log["calls"] += 1
        if call_log["calls"] == 1:
            raise ConnectionError("simulated network failure")
        return fake_em_df

    with (
        mock_patch(
            "data_fetchers.fetch_market_cap.ak.stock_value_em",
            side_effect=_flaky,
        ),
        mock_patch("data_fetchers.fetch_market_cap.time.sleep"),
    ):
        result = fetch_one_stock("000001", ("2024-03-18", "2024-03-20"), max_retries=3)

    assert result is not None
    assert len(result) == 3
    assert call_log["calls"] == 2


def test_fetch_one_stock_all_retries_fail() -> None:
    """TC-U-10: 全部重试失败，返回 None（决策 E1：skip + warning）。"""
    with (
        mock_patch(
            "data_fetchers.fetch_market_cap.ak.stock_value_em",
            side_effect=ConnectionError("persistent failure"),
        ),
        mock_patch("data_fetchers.fetch_market_cap.time.sleep"),
    ):
        result = fetch_one_stock("000001", ("2024-03-18", "2024-03-20"), max_retries=3)

    assert result is None


def test_fetch_one_stock_clip_drops_out_of_range(fake_em_df: pd.DataFrame) -> None:
    """TC-U-11: target_date_range 之外的日期被裁掉，返回空 DataFrame。"""
    with (
        mock_patch(
            "data_fetchers.fetch_market_cap.ak.stock_value_em",
            return_value=fake_em_df,
        ),
        mock_patch("data_fetchers.fetch_market_cap.time.sleep"),
    ):
        result = fetch_one_stock("000001", ("2025-01-01", "2025-12-31"))

    assert result is not None
    assert len(result) == 0
    assert list(result.columns) == list(_OUTPUT_COLUMNS)


def test_fetch_one_stock_value_error_no_retry(fake_em_df: pd.DataFrame) -> None:
    """TC-U-12: _normalize_fields 抛 ValueError 也走重试逻辑（不区分错误类型）。"""
    bad_df = fake_em_df.drop(columns=["流通市值"])
    with (
        mock_patch(
            "data_fetchers.fetch_market_cap.ak.stock_value_em",
            return_value=bad_df,
        ),
        mock_patch("data_fetchers.fetch_market_cap.time.sleep"),
    ):
        result = fetch_one_stock("000001", ("2024-03-18", "2024-03-20"), max_retries=2)

    # 字段缺失是结构问题，重试无效，最终返回 None
    assert result is None


# ============================================================
# TC-U-13..15: fetch_batch
# ============================================================


def test_fetch_batch_all_success(fake_em_df: pd.DataFrame) -> None:
    """TC-U-13: 一批 3 只全成功，merged DataFrame 行数 = 3 × 3 = 9。"""
    with (
        mock_patch(
            "data_fetchers.fetch_market_cap.ak.stock_value_em",
            return_value=fake_em_df,
        ),
        mock_patch("data_fetchers.fetch_market_cap.time.sleep"),
    ):
        df, success, fail = fetch_batch(
            ["000001", "000002", "600000"],
            batch_idx=1,
            total_batches=1,
            target_date_range=("2024-03-18", "2024-03-20"),
            max_workers=2,
        )

    assert df is not None
    assert success == 3
    assert fail == 0
    assert len(df) == 9
    assert set(df["asset"].unique()) == {"000001", "000002", "600000"}


def test_fetch_batch_high_failure_rate() -> None:
    """TC-U-14: 单批失败率 > 50%（4 中 3 失败）触发批次失败信号（df=None）。"""
    fake_df = pd.DataFrame(
        {
            "数据日期": ["2024-03-18"],
            "当日收盘价": [10.0],
            "当日涨跌幅": [0.0],
            "总市值": [1.0e10],
            "流通市值": [8.0e9],
            "总股本": [1_000_000_000],
            "流通股本": [800_000_000],
            "PE(TTM)": [12.0],
            "PE(静)": [12.0],
            "市净率": [1.5],
            "PEG值": [0.8],
            "市现率": [9.0],
            "市销率": [2.5],
        }
    )

    call_log = {"calls": 0}

    def _mostly_fail(symbol: str) -> pd.DataFrame:
        call_log["calls"] += 1
        # 只有 000001 成功，其他全失败
        if symbol == "000001":
            return fake_df
        raise ConnectionError(f"sim fail {symbol}")

    with (
        mock_patch(
            "data_fetchers.fetch_market_cap.ak.stock_value_em",
            side_effect=_mostly_fail,
        ),
        mock_patch("data_fetchers.fetch_market_cap.time.sleep"),
    ):
        df, success, fail = fetch_batch(
            ["000001", "000002", "000003", "000004"],
            batch_idx=1,
            total_batches=1,
            target_date_range=("2024-03-18", "2024-03-20"),
            max_workers=2,
        )

    # 失败率 75% > 50% → df 应为 None
    assert df is None
    assert success == 1
    assert fail == 3


def test_fetch_batch_empty_symbols() -> None:
    """TC-U-15: 空 symbols 列表直接返回空 DataFrame。"""
    df, success, fail = fetch_batch(
        [],
        batch_idx=1,
        total_batches=1,
        target_date_range=("2024-03-18", "2024-03-20"),
    )

    assert df is not None
    assert len(df) == 0
    assert success == 0
    assert fail == 0
    assert list(df.columns) == list(_OUTPUT_COLUMNS)


# ============================================================
# TC-U-16..18: save_batch_cache + _read_factor_data_date_range
# ============================================================


def test_save_batch_cache_atomic_write(tmp_path: Path, fake_em_df: pd.DataFrame) -> None:
    """TC-U-16: 落盘后文件存在，结构含 batch_idx/n_rows/n_assets/data。"""
    df = _normalize_fields(fake_em_df, symbol="000001")
    cache_path = save_batch_cache(batch_idx=7, df=df, result_dir=tmp_path)

    assert cache_path.exists()
    assert cache_path.name == "market_cap_batch_0007.json.gz"

    import gzip as _gzip

    with _gzip.open(cache_path, "rt", encoding="utf-8") as f:
        payload = json.load(f)

    assert payload["batch_idx"] == 7
    assert payload["n_rows"] == 3
    assert payload["n_assets"] == 1
    assert len(payload["data"]) == 3
    assert payload["data"][0]["asset"] == "000001"
    # 落盘列顺序保留
    assert list(payload["data"][0].keys()) == list(_OUTPUT_COLUMNS)


def test_save_batch_cache_empty_df_skipped(tmp_path: Path) -> None:
    """TC-U-17: 空 df 不落盘，返回 Path('')。"""
    empty = pd.DataFrame(columns=list(_OUTPUT_COLUMNS))
    result = save_batch_cache(batch_idx=1, df=empty, result_dir=tmp_path)

    assert result == Path("")
    # 临时目录应该为空（不写半文件）
    assert list(tmp_path.iterdir()) == []


def test_read_factor_data_date_range(tmp_path: Path) -> None:
    """TC-U-18: 读取 factor_data.json.gz meta.date_range，返回 (start, end)。"""
    import gzip as _gzip

    fake_payload = {
        "meta": {
            "date_range": {"start": "2024-03-18", "end": "2026-06-17"},
            "n_days": 545,
            "n_assets": 3026,
        },
        "data": [],
    }
    fake_file = tmp_path / "factor_data.json.gz"
    with _gzip.open(fake_file, "wt", encoding="utf-8") as f:
        json.dump(fake_payload, f)

    start, end = _read_factor_data_date_range(factor_data_file=fake_file)
    assert start == "2024-03-18"
    assert end == "2026-06-17"


def test_read_factor_data_date_range_missing_file(tmp_path: Path) -> None:
    """TC-U-18b: 文件不存在抛 FileNotFoundError。"""
    nonexistent = tmp_path / "missing.json.gz"
    with pytest.raises(FileNotFoundError, match="factor_data 文件不存在"):
        _read_factor_data_date_range(factor_data_file=nonexistent)
