"""
data_splitter 测试用例。

覆盖 design.md §7 的 6 个场景：
1. 日期切分边界
2. Purge 窗口隔离
3. 子集 schema 一致性
4. metadata 完整性
5. 三段无重叠
6. 空数据防护

使用构造的小数据（10 条记录），不依赖真实 2GB 文件。
"""

import gzip
import json
from pathlib import Path

import pytest
from reverse_discovery.data_splitter import compute_date_splits, split_data


# ============================================================================
# 测试数据构造
# ============================================================================

TEST_DATES = [
    "2024-01-01",
    "2024-01-02",
    "2024-01-03",
    "2024-01-04",
    "2024-01-05",
    "2024-01-06",
    "2024-01-07",
    "2024-01-08",
    "2024-01-09",
    "2024-01-10",
]

TEST_COLUMNS = [
    "date",
    "asset",
    "open",
    "close",
    "high",
    "low",
    "rsi_6",
    "volume",
    "forward_return_1d",
]


def _make_record(date: str, asset: str = "000001") -> dict:
    """构造一条测试记录。"""
    return {
        "date": date,
        "asset": asset,
        "open": 10.0,
        "close": 10.5,
        "high": 10.8,
        "low": 9.9,
        "rsi_6": 55.3,
        "volume": 1000000,
        "forward_return_1d": 0.012,
    }


@pytest.fixture
def fake_data_source(tmp_path: Path) -> Path:
    """构造一个 mini factor_ic_data.json.gz 文件。"""
    records = []
    for date in TEST_DATES:
        for asset in ["000001", "000002"]:
            records.append(_make_record(date, asset))

    data = {
        "dates": TEST_DATES,
        "data": records,
    }
    path = tmp_path / "factor_ic_data.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return path


# ============================================================================
# 1. 日期切分边界
# ============================================================================


class TestDateSplitBoundary:
    """测试 compute_date_splits 的日期边界正确性。"""

    def test_train_ends_before_purge(self):
        """train 段末尾应早于 train_end - purge_days。"""
        # train_end = TEST_DATES[6] = "2024-01-07" (idx=6)
        # purge_days = 2
        # train_cutoff_idx = 6 - 2 = 4
        # train = TEST_DATES[0:5] = 2024-01-01 ~ 2024-01-05
        splits = compute_date_splits(TEST_DATES, "2024-01-07", "2024-01-09", purge_days=2)

        assert splits["train"] == TEST_DATES[:5]
        assert splits["train"][-1] == "2024-01-05"

    def test_test_starts_after_train_end(self):
        """test 段应从 train_end 之后开始。"""
        splits = compute_date_splits(TEST_DATES, "2024-01-07", "2024-01-09", purge_days=2)

        assert splits["test"][0] == "2024-01-08"
        assert splits["test"][-1] == "2024-01-09"

    def test_holdout_starts_after_test_end(self):
        """holdout 段应从 test_end 之后开始。"""
        splits = compute_date_splits(TEST_DATES, "2024-01-07", "2024-01-09", purge_days=2)

        assert splits["holdout"][0] == "2024-01-10"


# ============================================================================
# 2. Purge 窗口隔离
# ============================================================================


class TestPurgeWindow:
    """测试 purge 窗口隔离正确性。"""

    def test_no_overlap_between_train_and_test(self):
        """train 与 test 无日期重叠。"""
        splits = compute_date_splits(TEST_DATES, "2024-01-07", "2024-01-09", purge_days=2)

        assert set(splits["train"]) & set(splits["test"]) == set()

    def test_gap_between_train_and_test(self):
        """train 末尾与 test 开头之间至少间隔 purge_days 个交易日。"""
        splits = compute_date_splits(TEST_DATES, "2024-01-07", "2024-01-09", purge_days=2)

        train_last_idx = TEST_DATES.index(splits["train"][-1])
        test_first_idx = TEST_DATES.index(splits["test"][0])
        # train 末尾是 idx=4, test 开头是 idx=7, 间隔 = 7-4-1 = 2 = purge_days
        assert test_first_idx - train_last_idx - 1 >= 2

    def test_purge_days_zero(self):
        """purge_days=0 时 train 包含到 train_end。"""
        splits = compute_date_splits(TEST_DATES, "2024-01-07", "2024-01-09", purge_days=0)

        assert splits["train"][-1] == "2024-01-07"


# ============================================================================
# 3. 三段无重叠
# ============================================================================


class TestNoOverlap:
    """测试 train / test / holdout 三段完全无重叠。"""

    def test_three_way_no_overlap(self):
        """三段日期集合的交集为空。"""
        splits = compute_date_splits(TEST_DATES, "2024-01-07", "2024-01-09", purge_days=2)

        train_set = set(splits["train"])
        test_set = set(splits["test"])
        holdout_set = set(splits["holdout"])

        assert train_set & test_set == set()
        assert train_set & holdout_set == set()
        assert test_set & holdout_set == set()


# ============================================================================
# 4. 空数据防护
# ============================================================================


class TestErrorHandling:
    """测试异常参数的防护。"""

    def test_empty_dates_raises(self):
        """dates 为空时抛 ValueError。"""
        with pytest.raises(ValueError, match="dates 列表为空"):
            compute_date_splits([], "2024-01-01", "2024-01-02")

    def test_train_end_after_test_end_raises(self):
        """train_end >= test_end 时抛 ValueError。"""
        with pytest.raises(ValueError, match="必须早于"):
            compute_date_splits(TEST_DATES, "2024-01-09", "2024-01-07")

    def test_train_end_before_data_start_raises(self):
        """train_end 早于数据起始日期时抛 ValueError。"""
        with pytest.raises(ValueError, match="早于数据起始日期"):
            compute_date_splits(TEST_DATES, "2023-01-01", "2024-01-05")

    def test_test_end_after_data_end_raises(self):
        """test_end 晚于数据结束日期时抛 ValueError。"""
        with pytest.raises(ValueError, match="晚于数据结束日期"):
            compute_date_splits(TEST_DATES, "2024-01-05", "2025-01-01")

    def test_train_end_not_in_dates_raises(self):
        """train_end 不在 dates 列表中（但在日期范围内）应抛 ValueError。"""
        # 从 TEST_DATES 中移除一天，让该日期在范围内但不在列表中
        dates_with_gap = [d for d in TEST_DATES if d != "2024-01-05"]
        with pytest.raises(ValueError, match="不在 dates 列表中"):
            compute_date_splits(dates_with_gap, "2024-01-05", "2024-01-09")

    def test_purge_too_large_raises(self):
        """purge_days 过大导致 train 段为空时抛 ValueError。"""
        with pytest.raises(ValueError, match="purge_days.*过大"):
            compute_date_splits(TEST_DATES, "2024-01-01", "2024-01-05", purge_days=5)


# ============================================================================
# 5. 子集 schema 一致性 + metadata 完整性
# ============================================================================


class TestSplitDataOutput:
    """测试 split_data 的输出文件正确性。"""

    def test_subset_schema_consistency(self, fake_data_source: Path, tmp_path: Path):
        """切分后 JSON 的 data 记录 keys 与源数据完全一致。"""
        output_dir = tmp_path / "output"
        result = split_data(
            train_end="2024-01-07",
            test_end="2024-01-09",
            purge_days=2,
            data_source=fake_data_source,
            output_dir=output_dir,
        )

        # 读取 train 子集的第一条记录
        with gzip.open(result["train"], "rt", encoding="utf-8") as f:
            subset_data = json.load(f)

        assert subset_data["data"], "train 子集 data 不应为空"
        record_keys = list(subset_data["data"][0].keys())
        assert record_keys == TEST_COLUMNS

    def test_metadata_completeness(self, fake_data_source: Path, tmp_path: Path):
        """metadata 中 split_type / split_train_end_date / split_purge_days 非空。"""
        output_dir = tmp_path / "output"
        result = split_data(
            train_end="2024-01-07",
            test_end="2024-01-09",
            purge_days=2,
            data_source=fake_data_source,
            output_dir=output_dir,
        )

        with gzip.open(result["train"], "rt", encoding="utf-8") as f:
            subset_data = json.load(f)

        meta = subset_data["metadata"]
        assert meta["split_type"] == "train"
        assert meta["split_train_end_date"] == "2024-01-07"
        assert meta["split_purge_days"] == 2
        assert meta["trading_days"] == 5  # train 段 5 天
        assert meta["date_range"]["start"] == "2024-01-01"
        assert meta["date_range"]["end"] == "2024-01-05"

    def test_subset_dates_correct(self, fake_data_source: Path, tmp_path: Path):
        """子集的 dates 字段与 compute_date_splits 结果一致。"""
        output_dir = tmp_path / "output"
        result = split_data(
            train_end="2024-01-07",
            test_end="2024-01-09",
            purge_days=2,
            data_source=fake_data_source,
            output_dir=output_dir,
        )

        splits = compute_date_splits(TEST_DATES, "2024-01-07", "2024-01-09", purge_days=2)

        with gzip.open(result["train"], "rt", encoding="utf-8") as f:
            train_data = json.load(f)
        with gzip.open(result["test"], "rt", encoding="utf-8") as f:
            test_data = json.load(f)
        with gzip.open(result["holdout"], "rt", encoding="utf-8") as f:
            holdout_data = json.load(f)

        assert train_data["dates"] == splits["train"]
        assert test_data["dates"] == splits["test"]
        assert holdout_data["dates"] == splits["holdout"]

    def test_record_count_matches(self, fake_data_source: Path, tmp_path: Path):
        """每条记录都属于正确的子集（按 date 过滤）。"""
        output_dir = tmp_path / "output"
        result = split_data(
            train_end="2024-01-07",
            test_end="2024-01-09",
            purge_days=2,
            data_source=fake_data_source,
            output_dir=output_dir,
        )

        with gzip.open(result["train"], "rt", encoding="utf-8") as f:
            train_data = json.load(f)
        # train 有 5 天 × 2 只股票 = 10 条记录
        assert len(train_data["data"]) == 10

        with gzip.open(result["test"], "rt", encoding="utf-8") as f:
            test_data = json.load(f)
        # test 有 2 天 × 2 只股票 = 4 条记录
        assert len(test_data["data"]) == 4

        with gzip.open(result["holdout"], "rt", encoding="utf-8") as f:
            holdout_data = json.load(f)
        # holdout 有 1 天 × 2 只股票 = 2 条记录
        assert len(holdout_data["data"]) == 2

    def test_output_filenames(self, fake_data_source: Path, tmp_path: Path):
        """输出文件名符合 MODULE.md 规范。"""
        output_dir = tmp_path / "output"
        result = split_data(
            train_end="2024-01-07",
            test_end="2024-01-09",
            purge_days=2,
            data_source=fake_data_source,
            output_dir=output_dir,
        )

        assert result["train"].name == "factor_ic_data_train_2024-01-07.json.gz"
        assert result["test"].name == "factor_ic_data_test_2024-01-07.json.gz"
        assert result["holdout"].name == "factor_ic_data_holdout.json.gz"

    def test_data_source_not_found_raises(self, tmp_path: Path):
        """主数据源不存在时抛 FileNotFoundError。"""
        output_dir = tmp_path / "output"
        with pytest.raises(FileNotFoundError, match="主数据源不存在"):
            split_data(
                train_end="2024-01-07",
                test_end="2024-01-09",
                data_source=tmp_path / "nonexistent.json.gz",
                output_dir=output_dir,
            )
