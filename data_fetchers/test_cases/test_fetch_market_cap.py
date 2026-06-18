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
    main,
    merge_and_emit_final,
    save_batch_cache,
    validate_final_data,
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
    """TC-U-12 / U-F3-6: _normalize_fields 抛 ValueError 时不重试，直接上抛。

    数据契约错误（缺列）重试无意义，遵循 design.md §8.2 异常处理矩阵。
    """
    bad_df = fake_em_df.drop(columns=["流通市值"])
    with (
        mock_patch(
            "data_fetchers.fetch_market_cap.ak.stock_value_em",
            return_value=bad_df,
        ),
        mock_patch("data_fetchers.fetch_market_cap.time.sleep") as mock_sleep,
        pytest.raises(ValueError, match="缺少必要字段"),
    ):
        fetch_one_stock("000001", ("2024-03-18", "2024-03-20"), max_retries=3)

    # 不应该进入重试退避（time.sleep 不被调用，或仅 REQUEST_INTERVAL）
    # 重试退避 sleep(delay+jitter) 不应触发；放宽：调用次数 <= 1（仅 REQUEST_INTERVAL）
    assert mock_sleep.call_count <= 1


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


# ============================================================
# TC-U-19..21: merge_and_emit_final
# ============================================================


def _make_batch_cache(target_dir: Path, batch_idx: int, df: pd.DataFrame) -> None:
    """测试 helper：构造一个批次缓存文件。"""
    import gzip as _gzip

    cache = target_dir / f"market_cap_batch_{batch_idx:04d}.json.gz"
    payload = {
        "batch_idx": batch_idx,
        "n_rows": len(df),
        "n_assets": int(df["asset"].nunique()) if len(df) else 0,
        "data": df.to_dict(orient="records"),
    }
    with _gzip.open(cache, "wt", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


def test_merge_and_emit_final_full_flow(
    tmp_path: Path, fake_em_df: pd.DataFrame, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TC-U-19: 2 批次（5 + 4 行）合并去重，最终落盘 + meta 计算 + 清理。"""
    import gzip as _gzip

    # 构造 batch1: 5 行（000001 + 000002 各 part）
    df1 = _normalize_fields(fake_em_df, symbol="000001")  # 3 行
    df2 = _normalize_fields(fake_em_df, symbol="000002").iloc[:2]  # 2 行
    batch1 = pd.concat([df1, df2], ignore_index=True)
    _make_batch_cache(tmp_path, 1, batch1)

    # 构造 batch2: 包含 1 行重复（000001/2024-03-18）+ 3 行新数据
    df3 = _normalize_fields(fake_em_df, symbol="000001").iloc[:1]  # 重复
    df4 = _normalize_fields(fake_em_df, symbol="600000")  # 3 行新
    batch2 = pd.concat([df3, df4], ignore_index=True)
    _make_batch_cache(tmp_path, 2, batch2)

    # 把 OUTPUT_FILE 重定向到 tmp_path
    final_file = tmp_path / "market_cap_data.json.gz"
    monkeypatch.setattr("data_fetchers.fetch_market_cap.OUTPUT_FILE", final_file)

    n = merge_and_emit_final(
        total_batches=2,
        target_date_range=("2024-03-18", "2024-03-20"),
        total_success=3,
        total_fail=0,
        elapsed_seconds=12.5,
        result_dir=tmp_path,
    )

    # 5 + 4 = 9 raw → 去重 1 行 = 8 final
    assert n == 8
    assert final_file.exists()

    # 验证最终文件结构
    with _gzip.open(final_file, "rt", encoding="utf-8") as f:
        payload = json.load(f)

    assert "meta" in payload
    assert "data" in payload
    meta = payload["meta"]
    assert meta["n_records"] == 8
    assert meta["n_assets"] == 3
    assert meta["n_days"] == 3
    assert meta["date_range"]["start"] == "2024-03-18"
    assert meta["date_range"]["end"] == "2024-03-20"
    assert meta["fetch_stats"]["total_success"] == 3
    assert meta["fetch_stats"]["fail_rate"] == 0.0
    assert meta["circ_market_cap_non_null_rate"] == 1.0

    # 批次缓存被清理
    remaining = list(tmp_path.glob("market_cap_batch_*.json.gz"))
    assert remaining == []


def test_merge_and_emit_final_no_batches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """TC-U-20: 没有任何批次缓存返回 0，不写最终文件。"""
    final_file = tmp_path / "market_cap_data.json.gz"
    monkeypatch.setattr("data_fetchers.fetch_market_cap.OUTPUT_FILE", final_file)

    n = merge_and_emit_final(
        total_batches=0,
        target_date_range=("2024-03-18", "2024-03-20"),
        total_success=0,
        total_fail=0,
        elapsed_seconds=0.0,
        result_dir=tmp_path,
    )

    assert n == 0
    assert not final_file.exists()


def test_merge_and_emit_final_empty_batches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """TC-U-21: 批次缓存全空返回 0。"""
    empty = pd.DataFrame(columns=list(_OUTPUT_COLUMNS))
    _make_batch_cache(tmp_path, 1, empty)

    final_file = tmp_path / "market_cap_data.json.gz"
    monkeypatch.setattr("data_fetchers.fetch_market_cap.OUTPUT_FILE", final_file)

    n = merge_and_emit_final(
        total_batches=1,
        target_date_range=("2024-03-18", "2024-03-20"),
        total_success=0,
        total_fail=10,
        elapsed_seconds=5.0,
        result_dir=tmp_path,
    )

    assert n == 0
    assert not final_file.exists()


# ============================================================
# TC-U-22..25: validate_final_data
# ============================================================


def _write_final_payload(target: Path, df: pd.DataFrame, meta: dict) -> None:
    """测试 helper：写入最终格式 payload。"""
    import gzip as _gzip

    payload = {"meta": meta, "data": df.to_dict(orient="records")}
    with _gzip.open(target, "wt", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


def _make_full_df(n_assets: int = 100, n_days: int = 5) -> pd.DataFrame:
    """构造 N 只股票 × M 天的合法最终数据。"""
    rows = []
    for ai in range(n_assets):
        code = f"{ai:06d}"
        for di in range(n_days):
            rows.append(
                {
                    "date": f"2024-03-{18 + di:02d}",
                    "asset": code,
                    "total_market_cap": 1.0e10,
                    "circ_market_cap": 8.0e9,
                    "total_shares": 1_000_000_000,
                    "circ_shares": 800_000_000,
                    "pe_ttm": 12.5,
                    "pe_lyr": 13.0,
                    "pb": 1.5,
                    "peg": 0.8,
                    "pcf_ttm": 9.5,
                    "ps_ttm": 2.5,
                }
            )
    return pd.DataFrame(rows)


def test_validate_final_data_ok(tmp_path: Path, stock_list_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """TC-U-22: 合法 payload 通过全部 V1-V7。"""
    monkeypatch.setattr("data_fetchers.fetch_market_cap.STOCK_LIST_FILE", stock_list_file)

    df = pd.DataFrame(
        [
            {
                "date": "2024-03-18",
                "asset": code,
                "total_market_cap": 1.0e10,
                "circ_market_cap": 8.0e9,
                "total_shares": 1_000_000_000,
                "circ_shares": 800_000_000,
                "pe_ttm": 12.5,
                "pe_lyr": 13.0,
                "pb": 1.5,
                "peg": 0.8,
                "pcf_ttm": 9.5,
                "ps_ttm": 2.5,
            }
            for code in ["000001", "000002", "600000"]
        ]
    )
    meta = {"version": "1.0", "n_records": 3, "n_assets": 3, "n_days": 1}
    final = tmp_path / "market_cap_data.json.gz"
    _write_final_payload(final, df, meta)

    ok, n, na, nd = validate_final_data(output_file=final)
    assert ok is True
    assert n == 3
    assert na == 3
    assert nd == 1


def test_validate_final_data_missing_field(tmp_path: Path) -> None:
    """TC-U-23: 缺少 circ_market_cap 字段触发 V3 失败。"""
    df = pd.DataFrame(
        [
            {
                "date": "2024-03-18",
                "asset": "000001",
                "total_market_cap": 1.0e10,
                "total_shares": 1_000_000_000,
                "circ_shares": 800_000_000,
                "pe_ttm": 12.5,
                "pe_lyr": 13.0,
                "pb": 1.5,
                "peg": 0.8,
                "pcf_ttm": 9.5,
                "ps_ttm": 2.5,
            }
        ]
    )
    meta = {"version": "1.0", "n_records": 1, "n_assets": 1, "n_days": 1}
    final = tmp_path / "market_cap_data.json.gz"
    _write_final_payload(final, df, meta)

    ok, _, _, _ = validate_final_data(output_file=final)
    assert ok is False


def test_validate_final_data_low_circ_non_null(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """TC-U-24: circ_market_cap 非空率 < 99% 触发 V6 失败。"""
    monkeypatch.setattr(
        "data_fetchers.fetch_market_cap.STOCK_LIST_FILE",
        tmp_path / "no_stock_list.json",
    )

    df = _make_full_df(n_assets=100, n_days=1)
    df.loc[:4, "circ_market_cap"] = None  # 5% 缺失

    meta = {"version": "1.0", "n_records": len(df), "n_assets": 100, "n_days": 1}
    final = tmp_path / "market_cap_data.json.gz"
    _write_final_payload(final, df, meta)

    ok, _, _, _ = validate_final_data(output_file=final)
    assert ok is False


def test_validate_final_data_negative_market_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """TC-U-25: 市值字段出现 <= 0 值触发 V7 失败。"""
    monkeypatch.setattr(
        "data_fetchers.fetch_market_cap.STOCK_LIST_FILE",
        tmp_path / "no_stock_list.json",
    )

    df = _make_full_df(n_assets=100, n_days=1)
    df.loc[0, "circ_market_cap"] = -1.0

    meta = {"version": "1.0", "n_records": len(df), "n_assets": 100, "n_days": 1}
    final = tmp_path / "market_cap_data.json.gz"
    _write_final_payload(final, df, meta)

    ok, _, _, _ = validate_final_data(output_file=final)
    assert ok is False


def test_validate_final_data_missing_file(tmp_path: Path) -> None:
    """TC-U-25b: 文件不存在触发 V1 失败。"""
    ok, n, na, nd = validate_final_data(output_file=tmp_path / "missing.json.gz")
    assert ok is False
    assert n == 0
    assert na == 0
    assert nd == 0


# ============================================================
# TC-U-26..27: main 顶层编排（mock fetch_batch）
# ============================================================


def test_main_happy_path(
    tmp_path: Path,
    stock_list_file: Path,
    fake_em_df: pd.DataFrame,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-U-26: main happy path（mock 网络 + 临时目录），返回 0。"""
    # 重定向所有 IO 到 tmp_path
    final_file = tmp_path / "market_cap_data.json.gz"
    monkeypatch.setattr("data_fetchers.fetch_market_cap.STOCK_LIST_FILE", stock_list_file)
    monkeypatch.setattr("data_fetchers.fetch_market_cap.RESULT_DIR", tmp_path)
    monkeypatch.setattr("data_fetchers.fetch_market_cap.OUTPUT_FILE", final_file)

    # mock fetch_one_stock 返回 fake DataFrame（避免真实网络）
    def fake_fetch_one_stock(symbol: str, **kwargs: object) -> pd.DataFrame:
        df = fake_em_df.copy()
        # _normalize_fields 会被网络层调用前 / fetch_one_stock 内调用
        # 直接返回 raw em 格式，让 fetch_one_stock 自己 normalize
        return df

    # 按 fetch_one_stock 真实接口：返回 normalized 12 列 df
    from data_fetchers.fetch_market_cap import _clip_to_target_range, _normalize_fields

    def fake_fetch_one_normalized(
        symbol: str,
        target_date_range: tuple[str, str],
        max_retries: int = 3,
        logger_arg: object = None,
    ) -> pd.DataFrame:
        df = fake_em_df.copy()
        df = _normalize_fields(df, symbol=symbol)
        df = _clip_to_target_range(df, target_date_range)
        return df

    monkeypatch.setattr("data_fetchers.fetch_market_cap.fetch_one_stock", fake_fetch_one_normalized)

    rc = main(target_date_range=("2024-03-18", "2024-03-20"))
    assert rc == 0
    assert final_file.exists()

    import gzip as _gzip

    with _gzip.open(final_file, "rt", encoding="utf-8") as f:
        payload = json.load(f)

    # stock_list 含 5 stocks 过滤 ST 后 3 个 → 3 assets × 3 days = 9 records
    assert payload["meta"]["n_assets"] == 3
    assert payload["meta"]["n_records"] == 9
    assert payload["meta"]["fetch_stats"]["total_success"] == 3
    assert payload["meta"]["fetch_stats"]["total_fail"] == 0


def test_main_empty_stock_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """TC-U-27: stock_list 为空返回 1。"""
    empty_list = tmp_path / "empty_list.json"
    empty_list.write_text(json.dumps({"stocks": []}), encoding="utf-8")
    monkeypatch.setattr("data_fetchers.fetch_market_cap.STOCK_LIST_FILE", empty_list)
    monkeypatch.setattr("data_fetchers.fetch_market_cap.RESULT_DIR", tmp_path)

    rc = main(target_date_range=("2024-03-18", "2024-03-20"))
    assert rc == 1


# ============================================================
# TC-U-28..30: design.md §9 覆盖率补充
# ============================================================


def test_normalize_fields_raises_on_missing_columns(fake_em_df: pd.DataFrame) -> None:
    """U-F7-2: 输入缺 `流通市值` 列触发 ValueError（硬规则 #14 防御性）。"""
    bad = fake_em_df.drop(columns=["流通市值"])
    with pytest.raises(ValueError, match="缺少必要字段"):
        _normalize_fields(bad, symbol="000001")


def test_fetch_batch_concurrent_isolation(fake_em_df: pd.DataFrame) -> None:
    """U-F4-3: 并发 5 股，其中 1 股抛非 ValueError 异常，其他 4 股不受影响。"""
    call_log: list[str] = []

    def side_effect(symbol: str) -> pd.DataFrame:
        call_log.append(symbol)
        if symbol == "600000":
            raise ConnectionError(f"模拟网络异常: {symbol}")
        return fake_em_df.copy()

    with (
        mock_patch(
            "data_fetchers.fetch_market_cap.ak.stock_value_em",
            side_effect=lambda symbol: side_effect(symbol),
        ),
        mock_patch("data_fetchers.fetch_market_cap.time.sleep"),
    ):
        df, success, fail = fetch_batch(
            symbols=["000001", "000002", "600000", "300001", "688001"],
            batch_idx=1,
            total_batches=1,
            target_date_range=("2024-03-18", "2024-03-20"),
            max_workers=4,
        )

    # 1 股失败，4 股成功；其他股票数据完整（隔离正确）
    assert success == 4
    assert fail == 1
    assert df is not None
    assert sorted(df["asset"].unique()) == ["000001", "000002", "300001", "688001"]


def test_merge_emit_meta_has_all_required_fields(
    tmp_path: Path, fake_em_df: pd.DataFrame, monkeypatch: pytest.MonkeyPatch
) -> None:
    """U-F6-2: meta 包含 design.md §7.2 全部 11 个必填字段。"""
    df = _normalize_fields(fake_em_df, symbol="000001")
    _make_batch_cache(tmp_path, 1, df)

    final_file = tmp_path / "market_cap_data.json.gz"
    monkeypatch.setattr("data_fetchers.fetch_market_cap.OUTPUT_FILE", final_file)

    merge_and_emit_final(
        total_batches=1,
        target_date_range=("2024-03-18", "2024-03-20"),
        total_success=1,
        total_fail=0,
        elapsed_seconds=1.0,
        result_dir=tmp_path,
    )

    import gzip as _gzip

    with _gzip.open(final_file, "rt", encoding="utf-8") as f:
        meta = json.load(f)["meta"]

    # design.md §7.2 必填字段
    required_top = {
        "version",
        "source",
        "generated_at",
        "n_days",
        "n_assets",
        "n_records",
        "date_range",
        "fetch_stats",
        "field_units",
        "circ_market_cap_non_null_rate",
    }
    missing = required_top - set(meta.keys())
    assert not missing, f"meta 缺字段: {missing}"

    # date_range 子字段
    assert {"start", "end", "target_start", "target_end"} <= set(meta["date_range"].keys())

    # fetch_stats 子字段
    assert {"total_success", "total_fail", "fail_rate", "elapsed_seconds", "total_batches"} <= set(
        meta["fetch_stats"].keys()
    )
