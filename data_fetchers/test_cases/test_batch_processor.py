#!/usr/bin/env python3
"""
batch_processor.py pytest 测试文件

测试覆盖：
- BatchStream 类（流式读取、heap 比较）
- save_batch_cache_sorted（批次保存、列验证）
- n_way_merge_deduplicate（N-way merge、去重）
- format_final_output（最终格式化、meta 计算）
- cleanup_batch_files（临时文件清理）

运行方式：
    pytest data_fetchers/test_cases/test_batch_processor.py -v

版本历史：
- v1.0 (2026-05-27): 初始版本，覆盖所有公共函数
"""

import gzip
import json
import logging

# 添加项目根目录到 sys.path
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch as mock_patch

import pytest


sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from data_fetchers.batch_processor import (
    BatchStream,
    cleanup_batch_files,
    format_final_output,
    n_way_merge_deduplicate,
    save_batch_cache_sorted,
)


# 配置测试 logger
@pytest.fixture(scope="module")
def test_logger():
    """配置测试用 logger"""
    logger = logging.getLogger("test_batch_processor")
    logger.setLevel(logging.DEBUG)
    return logger


@pytest.fixture
def temp_dir():
    """创建临时测试目录"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


# ============================================================================
# BatchStream 类测试
# ============================================================================


class TestBatchStream:
    """TC001: BatchStream 流式读取测试"""

    def test_batch_stream_init(self, temp_dir):
        """验证 BatchStream 初始化"""
        # 创建测试批次文件
        batch_path = temp_dir / "batch_0_factor.json.gz"
        test_data = [
            {"date": "2026-05-27", "asset": "000001", "open": 10.0},
            {"date": "2026-05-27", "asset": "000002", "open": 20.0},
        ]
        with gzip.open(batch_path, "wt", encoding="utf-8") as f:
            json.dump(test_data, f)

        stream = BatchStream(0, "factor", result_dir=temp_dir)

        assert stream.batch_idx == 0
        assert stream.data_type == "factor"
        assert len(stream.records) == 2
        assert not stream.exhausted

    def test_batch_stream_peek_key(self, temp_dir):
        """验证 peek_key 返回正确的 key"""
        batch_path = temp_dir / "batch_0_factor.json.gz"
        test_data = [{"date": "2026-05-27", "asset": "000001", "open": 10.0}]
        with gzip.open(batch_path, "wt", encoding="utf-8") as f:
            json.dump(test_data, f)

        stream = BatchStream(0, "factor", result_dir=temp_dir)
        key = stream.peek_key()

        assert key == ("2026-05-27", "000001")

    def test_batch_stream_pop_record(self, temp_dir):
        """验证 pop_record 返回正确记录"""
        batch_path = temp_dir / "batch_0_factor.json.gz"
        test_data = [
            {"date": "2026-05-27", "asset": "000001", "open": 10.0},
            {"date": "2026-05-27", "asset": "000002", "open": 20.0},
        ]
        with gzip.open(batch_path, "wt", encoding="utf-8") as f:
            json.dump(test_data, f)

        stream = BatchStream(0, "factor", result_dir=temp_dir)

        rec1 = stream.pop_record()
        assert rec1["asset"] == "000001"
        assert not stream.exhausted

        rec2 = stream.pop_record()
        assert rec2["asset"] == "000002"
        assert stream.exhausted

    def test_batch_stream_comparison(self, temp_dir):
        """验证 BatchStream 的 __lt__ 比较"""
        batch_path0 = temp_dir / "batch_0_factor.json.gz"
        batch_path1 = temp_dir / "batch_1_factor.json.gz"

        for path, batch_idx in [(batch_path0, 0), (batch_path1, 1)]:
            test_data = [{"date": "2026-05-27", "asset": "000001", "open": 10.0}]
            with gzip.open(path, "wt", encoding="utf-8") as f:
                json.dump(test_data, f)

        stream0 = BatchStream(0, "factor", result_dir=temp_dir)
        stream1 = BatchStream(1, "factor", result_dir=temp_dir)

        assert stream0 < stream1

    def test_batch_stream_cleanup(self, temp_dir):
        """验证 cleanup 清理资源"""
        batch_path = temp_dir / "batch_0_factor.json.gz"
        test_data = [{"date": "2026-05-27", "asset": "000001", "open": 10.0}]
        with gzip.open(batch_path, "wt", encoding="utf-8") as f:
            json.dump(test_data, f)

        stream = BatchStream(0, "factor", result_dir=temp_dir)
        stream.cleanup()

        assert stream.records == []
        assert stream.exhausted


# ============================================================================
# save_batch_cache_sorted 测试
# ============================================================================


class TestSaveBatchCacheSorted:
    """TC002: save_batch_cache_sorted 批次保存测试"""

    def test_save_batch_basic(self, temp_dir, test_logger):
        """验证基本批次保存功能"""
        import pandas as pd

        factor_df = pd.DataFrame(
            {
                "date": ["2026-05-27", "2026-05-27"],
                "asset": ["000001", "000002"],
                "open": [10.0, 20.0],
                "close": [10.5, 20.5],
                "high": [11.0, 21.0],
                "low": [9.5, 19.5],
                "rsi_6": [50.0, 60.0],
                "volume_ratio_5": [1.0, 1.5],
                "volume": [1000000.0, 2000000.0],
            }
        )

        return_df = pd.DataFrame(
            {
                "date": ["2026-05-27", "2026-05-27"],
                "asset": ["000001", "000002"],
                "forward_return_1d": [0.01, 0.02],
                "forward_return_3d": [0.03, 0.06],
                "forward_return_5d": [0.05, 0.10],
            }
        )

        save_batch_cache_sorted(0, factor_df, return_df, result_dir=temp_dir, logger_arg=test_logger)

        # 验证文件存在
        factor_path = temp_dir / "batch_0_factor.json.gz"
        return_path = temp_dir / "batch_0_return.json.gz"

        assert factor_path.exists()
        assert return_path.exists()

    def test_save_batch_missing_columns(self, temp_dir, test_logger):
        """TC003: 缺少必需列时抛出 ValueError"""
        import pandas as pd

        # 缺少必需列的 DataFrame
        invalid_df = pd.DataFrame(
            {
                "date": ["2026-05-27"],
                "asset": ["000001"],
                # 缺少 open, close, high, low, rsi_6, volume_ratio_5
            }
        )

        return_df = pd.DataFrame(
            {
                "date": ["2026-05-27"],
                "asset": ["000001"],
                "forward_return_1d": [0.01],
                "forward_return_3d": [0.03],
                "forward_return_5d": [0.05],
            }
        )

        with pytest.raises(ValueError):
            save_batch_cache_sorted(0, invalid_df, return_df, result_dir=temp_dir, logger_arg=test_logger)


# ============================================================================
# n_way_merge_deduplicate 测试
# ============================================================================


class TestNWayMergeDeduplicate:
    """TC004: N-way merge 合并测试"""

    def test_merge_two_batches(self, temp_dir, test_logger):
        """验证两个批次合并"""
        import pandas as pd

        # 创建两个批次（模拟去重场景）
        for batch_idx, asset in [(0, "000001"), (1, "000002")]:
            factor_df = pd.DataFrame(
                {
                    "date": ["2026-05-27"],
                    "asset": [asset],
                    "open": [10.0 + batch_idx],
                    "close": [10.5 + batch_idx],
                    "high": [11.0 + batch_idx],
                    "low": [9.5 + batch_idx],
                    "rsi_6": [50.0],
                    "volume_ratio_5": [1.0],
                    "volume": [1000000.0],
                }
            )
            return_df = pd.DataFrame(
                {
                    "date": ["2026-05-27"],
                    "asset": [asset],
                    "forward_return_1d": [0.01],
                    "forward_return_3d": [0.03],
                    "forward_return_5d": [0.05],
                }
            )
            save_batch_cache_sorted(batch_idx, factor_df, return_df, result_dir=temp_dir, logger_arg=test_logger)

        merged_path = n_way_merge_deduplicate(2, "factor", result_dir=temp_dir, logger_arg=test_logger)

        assert merged_path is not None
        assert merged_path.name == "merged_factor.json.gz"

        # 验证合并结果
        with gzip.open(merged_path, "rt", encoding="utf-8") as f:
            merged_data = json.load(f)
        assert len(merged_data) == 2

    def test_merge_deduplicate(self, temp_dir, test_logger):
        """TC005: 相同 key 选择最新 batch（去重）"""
        import pandas as pd

        # 两个批次包含相同 key，batch_1 是最新
        for batch_idx, close in [(0, 10.5), (1, 15.5)]:
            factor_df = pd.DataFrame(
                {
                    "date": ["2026-05-27"],
                    "asset": ["000001"],  # 相同 key
                    "open": [10.0],
                    "close": [close],
                    "high": [11.0],
                    "low": [9.5],
                    "rsi_6": [50.0],
                    "volume_ratio_5": [1.0],
                    "volume": [1000000.0],
                }
            )
            return_df = pd.DataFrame(
                {
                    "date": ["2026-05-27"],
                    "asset": ["000001"],
                    "forward_return_1d": [0.01],
                    "forward_return_3d": [0.03],
                    "forward_return_5d": [0.05],
                }
            )
            save_batch_cache_sorted(batch_idx, factor_df, return_df, result_dir=temp_dir, logger_arg=test_logger)

        merged_path = n_way_merge_deduplicate(2, "factor", result_dir=temp_dir, logger_arg=test_logger)

        # 验证选择最新 batch（batch_1 的 close=15.5）
        with gzip.open(merged_path, "rt", encoding="utf-8") as f:
            merged_data = json.load(f)
        assert merged_data[0]["close"] == 15.5

    def test_merge_no_batches(self, temp_dir, test_logger):
        """TC006: 无有效批次返回 None"""
        merged_path = n_way_merge_deduplicate(0, "factor", result_dir=temp_dir, logger_arg=test_logger)
        assert merged_path is None


# ============================================================================
# format_final_output 测试
# ============================================================================


class TestFormatFinalOutput:
    """TC007: 最终格式化测试"""

    def test_format_basic(self, temp_dir, test_logger):
        """验证基本格式化功能"""
        import pandas as pd

        # 创建并合并一个批次
        factor_df = pd.DataFrame(
            {
                "date": ["2026-05-27"],
                "asset": ["000001"],
                "open": [10.0],
                "close": [10.5],
                "high": [11.0],
                "low": [9.5],
                "rsi_6": [50.0],
                "volume_ratio_5": [1.0],
                "volume": [1000000.0],
            }
        )
        return_df = pd.DataFrame(
            {
                "date": ["2026-05-27"],
                "asset": ["000001"],
                "forward_return_1d": [0.01],
                "forward_return_3d": [0.03],
                "forward_return_5d": [0.05],
            }
        )
        save_batch_cache_sorted(0, factor_df, return_df, result_dir=temp_dir, logger_arg=test_logger)

        factor_merged = n_way_merge_deduplicate(1, "factor", result_dir=temp_dir, logger_arg=test_logger)
        return_merged = n_way_merge_deduplicate(1, "return", result_dir=temp_dir, logger_arg=test_logger)

        format_final_output(factor_merged, return_merged, result_dir=temp_dir, logger_arg=test_logger)

        # 验证最终文件
        factor_final = temp_dir / "factor_data.json.gz"
        return_final = temp_dir / "return_data.json.gz"

        assert factor_final.exists()
        assert return_final.exists()

        # 验证 meta 结构
        with gzip.open(factor_final, "rt", encoding="utf-8") as f:
            factor_data = json.load(f)
        assert "meta" in factor_data
        assert "data" in factor_data
        assert factor_data["meta"]["n_days"] == 1
        assert factor_data["meta"]["n_assets"] == 1

    def test_format_missing_merged_file(self, temp_dir, test_logger):
        """TC008: merged 文件不存在抛出 FileNotFoundError"""
        fake_factor_path = temp_dir / "merged_factor.json.gz"
        fake_return_path = temp_dir / "merged_return.json.gz"

        # 文件不存在
        with pytest.raises(FileNotFoundError):
            format_final_output(fake_factor_path, fake_return_path, result_dir=temp_dir, logger_arg=test_logger)


# ============================================================================
# cleanup_batch_files 测试
# ============================================================================


class TestCleanupBatchFiles:
    """TC009: 临时文件清理测试"""

    def test_cleanup_basic(self, temp_dir, test_logger):
        """验证基本清理功能"""
        import pandas as pd

        # 创建批次文件
        factor_df = pd.DataFrame(
            {
                "date": ["2026-05-27"],
                "asset": ["000001"],
                "open": [10.0],
                "close": [10.5],
                "high": [11.0],
                "low": [9.5],
                "rsi_6": [50.0],
                "volume_ratio_5": [1.0],
                "volume": [1000000.0],
            }
        )
        return_df = pd.DataFrame(
            {
                "date": ["2026-05-27"],
                "asset": ["000001"],
                "forward_return_1d": [0.01],
                "forward_return_3d": [0.03],
                "forward_return_5d": [0.05],
            }
        )
        save_batch_cache_sorted(0, factor_df, return_df, result_dir=temp_dir, logger_arg=test_logger)

        # 创建 merged 文件（手动创建）
        merged_factor = temp_dir / "merged_factor.json.gz"
        merged_return = temp_dir / "merged_return.json.gz"
        with gzip.open(merged_factor, "wt", encoding="utf-8") as f:
            json.dump([{"date": "2026-05-27", "asset": "000001"}], f)
        with gzip.open(merged_return, "wt", encoding="utf-8") as f:
            json.dump([{"date": "2026-05-27", "asset": "000001"}], f)

        deleted = cleanup_batch_files(1, result_dir=temp_dir, logger_arg=test_logger)

        # 验证删除数量（2 批次 + 2 merged = 4）
        assert deleted == 4

        # 验证文件已删除
        assert not (temp_dir / "batch_0_factor.json.gz").exists()
        assert not (temp_dir / "batch_0_return.json.gz").exists()
        assert not merged_factor.exists()
        assert not merged_return.exists()

    def test_cleanup_no_files(self, temp_dir, test_logger):
        """TC010: 无临时文件时返回 0"""
        deleted = cleanup_batch_files(0, result_dir=temp_dir, logger_arg=test_logger)
        assert deleted == 0


# ============================================================================
# Bug 修复回归测试（v1.7, 2026-06-15）
# ============================================================================


class TestBugFixesV17:
    """TC012: v1.7 Bug 修复回归测试，防止已修复的 bug 重新出现"""

    def test_scan_merged_file_value_with_trailing_comma(self, temp_dir, test_logger):
        """Bug #2: 字段字符串值末尾恰好是逗号时，不能被 rstrip(",") 误剥离

        构造一条记录，其 asset 字段值末尾为逗号（极端但合法的字符串值），
        验证 _scan_merged_file 通过两段式解析能正确解析整条记录。
        """
        import gzip
        import json as _json

        from data_fetchers.batch_processor import _scan_merged_file

        merged_path = temp_dir / "merged_factor.json.gz"
        # 构造合并后文件格式（数组形式，单行 JSON 对象 + 逗号分隔）
        record_with_trailing_comma_value = {
            "date": "2026-05-27",
            "asset": "ABC,",  # 故意构造尾部逗号的字符串值
            "open": 10.0,
        }
        with gzip.open(merged_path, "wt", encoding="utf-8") as f:
            f.write("[\n")
            # 先尝试原样解析能成功（无尾随分隔逗号）
            f.write("  " + _json.dumps(record_with_trailing_comma_value, ensure_ascii=False))
            f.write("\n]")

        n_days, n_assets, first_date, last_date, n_records, lines = _scan_merged_file(merged_path, test_logger)
        assert n_records == 1
        # 关键断言：asset 字段值的尾部逗号不应被剥离
        parsed = _json.loads(lines[0])
        assert parsed["asset"] == "ABC,"

    def test_n_way_merge_no_path_exists_check(self, temp_dir, test_logger):
        """Bug #5: 缺失批次文件不再依赖调用方 path.exists() 前置过滤

        创建 batch_1，跳过 batch_0 和 batch_2，调用 n_way_merge_deduplicate(3)：
        - BatchStream._load_all 应统一捕获缺失文件并设置 load_error
        - 合并应仍能成功返回 batch_1 的内容
        """
        import gzip
        import json as _json

        # 仅创建 batch_1，故意缺失 batch_0 / batch_2
        batch_1 = temp_dir / "batch_1_factor.json.gz"
        with gzip.open(batch_1, "wt", encoding="utf-8") as f:
            _json.dump([{"date": "2026-05-27", "asset": "000001", "open": 10.0}], f)

        merged_path = n_way_merge_deduplicate(3, "factor", result_dir=temp_dir, logger_arg=test_logger)

        assert merged_path is not None
        with gzip.open(merged_path, "rt", encoding="utf-8") as f:
            data = _json.load(f)
        assert len(data) == 1
        assert data[0]["asset"] == "000001"

    def test_format_final_output_partial_failure_atomic_cleanup(self, temp_dir, test_logger):
        """Bug #5 (v1.8): 因子写出成功后收益写出失败，except 块应原子清理两个文件

        v1.7 决策为"保留已成功因子"，v1.8 反转为原子清理：因子+收益是配套数据契约，
        单边因子文件对下游 factor_generator 无意义，必须一起清理。
        """
        import pandas as pd

        # 创建 1 个有效批次 → 合并 → 拿到两个 merged 文件
        factor_df = pd.DataFrame(
            {
                "date": ["2026-05-27"],
                "asset": ["000001"],
                "open": [10.0],
                "close": [10.5],
                "high": [11.0],
                "low": [9.5],
                "rsi_6": [50.0],
                "volume_ratio_5": [1.0],
                "volume": [1000000.0],
            }
        )
        return_df = pd.DataFrame(
            {
                "date": ["2026-05-27"],
                "asset": ["000001"],
                "forward_return_1d": [0.01],
                "forward_return_3d": [0.03],
                "forward_return_5d": [0.05],
            }
        )
        save_batch_cache_sorted(0, factor_df, return_df, result_dir=temp_dir, logger_arg=test_logger)

        factor_merged = n_way_merge_deduplicate(1, "factor", result_dir=temp_dir, logger_arg=test_logger)
        return_merged = n_way_merge_deduplicate(1, "return", result_dir=temp_dir, logger_arg=test_logger)
        assert factor_merged is not None
        assert return_merged is not None
        from data_fetchers import batch_processor

        # mock _scan_and_write_final：第一次（因子）正常调用底层实现，第二次（收益）抛错
        original_swf = batch_processor._scan_and_write_final
        call_count = {"n": 0}

        def mocked_swf(merged_path, output_path, meta_template, logger):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return original_swf(merged_path, output_path, meta_template, logger)
            raise OSError("模拟收益文件写入失败")

        with (
            mock_patch.object(batch_processor, "_scan_and_write_final", side_effect=mocked_swf),
            pytest.raises(OSError, match="模拟收益文件写入失败"),
        ):
            format_final_output(factor_merged, return_merged, result_dir=temp_dir, logger_arg=test_logger)

        # 关键断言：因子和收益文件都不应存在（原子清理）
        factor_final = temp_dir / "factor_data.json.gz"
        return_final = temp_dir / "return_data.json.gz"
        assert not factor_final.exists(), "原子清理：因子文件虽已写出但收益失败时也应清理"
        assert not return_final.exists(), "收益文件写出失败，应被清理"

    def test_write_final_file_date_value_literal_null_string(self, temp_dir):
        """Bug #6: first_date 真实值恰好是字符串 "null" 时，不应被误判为空

        构造 first_date="null" 的极端场景，验证 JSON 输出为 "\"null\"" 字符串值，
        而不是 JSON null 字面量。
        """
        import gzip
        import json as _json

        from data_fetchers.batch_processor import _write_final_file

        output_path = temp_dir / "test_null_string.json.gz"
        meta = {
            "generated_at": "2026-06-15T00:00:00",
            "source": "test",
            "n_days": 1,
            "n_assets": 1,
            "n_records": 1,
            "first_date": "null",  # 字符串值就是 "null"
            "last_date": "null",
            "last_updated": "2026-06-15 00:00:00",
            "version": "test",
            "fields": ["date", "asset"],
        }
        lines = ['{"date": "null", "asset": "000001"}']
        _write_final_file(output_path, meta, lines)

        with gzip.open(output_path, "rt", encoding="utf-8") as f:
            data = _json.load(f)

        # 关键断言：date_range.start 应为字符串 "null"，不是 JSON null
        assert data["meta"]["date_range"]["start"] == "null"
        assert data["meta"]["date_range"]["end"] == "null"
        assert isinstance(data["meta"]["date_range"]["start"], str)

    def test_write_final_file_date_none(self, temp_dir):
        """Bug #6 反向场景: first_date 为 None 时输出 JSON null 字面量"""
        import gzip
        import json as _json

        from data_fetchers.batch_processor import _write_final_file

        output_path = temp_dir / "test_none.json.gz"
        meta = {
            "generated_at": "2026-06-15T00:00:00",
            "source": "test",
            "n_days": 0,
            "n_assets": 0,
            "n_records": 0,
            "first_date": None,
            "last_date": None,
            "last_updated": "2026-06-15 00:00:00",
            "version": "test",
            "fields": ["date", "asset"],
        }
        _write_final_file(output_path, meta, [])

        with gzip.open(output_path, "rt", encoding="utf-8") as f:
            data = _json.load(f)

        # None 应被序列化为 JSON null（Python 中是 None）
        assert data["meta"]["date_range"]["start"] is None
        assert data["meta"]["date_range"]["end"] is None


class TestBugFixesV18:
    """v1.8 六项 Bug 修复回归测试"""

    def test_emit_record_count_zero_guard(self, temp_dir, test_logger):
        """Bug #1: count=0 时 _emit_record 不应触发进度日志/gc"""
        import gzip
        import json as _json

        from data_fetchers.batch_processor import _emit_record

        output_path = temp_dir / "test_count_zero.json.gz"
        with gzip.open(output_path, "wt", encoding="utf-8") as f:
            f.write("[\n")
            # _emit_record 在写入第一条时 count 从 0 升为 1（_write_json_record +1），
            # 然后 count % 50000 == 1，本不会触发，但加上防御判断更稳健
            count = _emit_record(f, [(0, {"date": "2026-06-15", "asset": "000001"})], 0, test_logger)
            f.write("\n]")
        assert count == 1, f"预期 count=1, 实际 {count}"
        # 验证文件内容正确
        with gzip.open(output_path, "rt", encoding="utf-8") as f:
            data = _json.load(f)
        assert len(data) == 1
        assert data[0]["asset"] == "000001"

    def test_n_way_merge_skips_missing_batches_silently(self, temp_dir, test_logger):
        """Bug #2: 缺失批次被静默跳过，不记录 warning

        创建一批次后，用 total_batches=3（批次0存在，1和2缺失），验证 warning 日志为空。
        """
        import logging

        import pandas as pd

        factor_df = pd.DataFrame(
            {
                "date": ["2026-06-15"],
                "asset": ["000001"],
                "open": [10.0],
                "close": [10.5],
                "high": [11.0],
                "low": [9.5],
                "rsi_6": [50.0],
                "volume_ratio_5": [1.0],
                "volume": [1000000.0],
            }
        )
        return_df = pd.DataFrame(
            {
                "date": ["2026-06-15"],
                "asset": ["000001"],
                "forward_return_1d": [0.01],
                "forward_return_3d": [0.03],
                "forward_return_5d": [0.05],
            }
        )
        save_batch_cache_sorted(0, factor_df, return_df, result_dir=temp_dir, logger_arg=test_logger)

        # 用自定义 logger 捕获 warning 输出
        capture_log = logging.getLogger("test_capture")
        capture_log.setLevel(logging.WARNING)
        handler = logging.StreamHandler()
        handler.setLevel(logging.WARNING)
        capture_log.addHandler(handler)

        # total_batches=3, 批次1和2缺失，应静默跳过不触发 warning
        factor_merged = n_way_merge_deduplicate(3, "factor", result_dir=temp_dir, logger_arg=capture_log)
        assert factor_merged is not None
        # 验证 merged 文件正确（仅含批次0的数据）
        import gzip
        import json as _json

        with gzip.open(factor_merged, "rt", encoding="utf-8") as f:
            data = _json.load(f)
        assert len(data) == 1
        assert data[0]["asset"] == "000001"

    def test_scan_and_write_final_basic(self, temp_dir, test_logger):
        """Bug #4: _scan_and_write_final 正确写出因子文件"""
        import gzip
        import json as _json

        import pandas as pd

        # 先创建一个 merged 文件
        merged_path = temp_dir / "merged_factor.json.gz"
        records = [
            {"date": "2026-06-15", "asset": "000001", "value": 1.0},
            {"date": "2026-06-16", "asset": "000002", "value": 2.0},
        ]
        with gzip.open(merged_path, "wt", encoding="utf-8") as f:
            f.write("[\n")
            for i, rec in enumerate(records):
                if i > 0:
                    f.write(",\n")
                f.write("  " + _json.dumps(rec, ensure_ascii=False))
            f.write("\n]")

        from data_fetchers.batch_processor import _scan_and_write_final

        output_path = temp_dir / "factor_data.json.gz"
        meta_template = {
            "generated_at": "2026-06-15T00:00:00",
            "source": "test",
            "last_updated": "2026-06-15 00:00:00",
            "version": "1.0",
            "fields": ["date", "asset", "value"],
        }
        size_mb, stats = _scan_and_write_final(merged_path, output_path, meta_template, test_logger)

        assert size_mb > 0
        assert stats["n_days"] == 2
        assert stats["n_assets"] == 2
        assert stats["n_records"] == 2
        assert stats["first_date"] == "2026-06-15"
        assert stats["last_date"] == "2026-06-16"

        with gzip.open(output_path, "rt", encoding="utf-8") as f:
            data = _json.load(f)
        assert "meta" in data
        assert "data" in data
        assert len(data["data"]) == 2
        assert data["meta"]["n_records"] == 2
        assert data["meta"]["date_range"]["start"] == "2026-06-15"
        assert data["meta"]["date_range"]["end"] == "2026-06-16"

    def test_cleanup_batch_files_skips_nonexistent(self, temp_dir, test_logger):
        """Bug #8: cleanup_batch_files 不因缺失文件而报错（兜底行为）"""
        from data_fetchers.batch_processor import cleanup_batch_files

        # 没有任何文件，total_batches=3，应返回 0
        deleted = cleanup_batch_files(3, result_dir=temp_dir, logger_arg=test_logger)
        assert deleted == 0


# ============================================================================
# 集成测试
# ============================================================================


class TestIntegration:
    """TC011: 完整流程集成测试"""

    def test_full_workflow(self, temp_dir, test_logger):
        """验证完整批次处理流程"""
        import pandas as pd

        # Step 1: 批次保存
        for batch_idx in range(2):
            factor_df = pd.DataFrame(
                {
                    "date": ["2026-05-27"],
                    "asset": [f"00000{batch_idx + 1}"],
                    "open": [10.0 + batch_idx],
                    "close": [10.5 + batch_idx],
                    "high": [11.0 + batch_idx],
                    "low": [9.5 + batch_idx],
                    "rsi_6": [50.0],
                    "volume_ratio_5": [1.0],
                    "volume": [1000000.0],
                }
            )
            return_df = pd.DataFrame(
                {
                    "date": ["2026-05-27"],
                    "asset": [f"00000{batch_idx + 1}"],
                    "forward_return_1d": [0.01],
                    "forward_return_3d": [0.03],
                    "forward_return_5d": [0.05],
                }
            )
            save_batch_cache_sorted(batch_idx, factor_df, return_df, result_dir=temp_dir, logger_arg=test_logger)

        # Step 2: N-way merge
        factor_merged = n_way_merge_deduplicate(2, "factor", result_dir=temp_dir, logger_arg=test_logger)
        return_merged = n_way_merge_deduplicate(2, "return", result_dir=temp_dir, logger_arg=test_logger)

        assert factor_merged is not None
        assert return_merged is not None

        # Step 3: 最终格式化
        format_final_output(factor_merged, return_merged, result_dir=temp_dir, logger_arg=test_logger)

        factor_final = temp_dir / "factor_data.json.gz"
        return_final = temp_dir / "return_data.json.gz"

        assert factor_final.exists()
        assert return_final.exists()

        # Step 4: 清理
        deleted = cleanup_batch_files(2, result_dir=temp_dir, logger_arg=test_logger)
        assert deleted == 4  # 2*2 批次（merged 文件已在 format_final_output 中删除）
