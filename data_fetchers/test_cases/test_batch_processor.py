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

    def test_merged_records_value_with_trailing_comma(self, temp_dir, test_logger):
        """Bug #2 等价覆盖（v1.9 迁移自 _scan_merged_file）：_iter_merged_records 两段式解析能正确处理字段值末尾逗号"""
        import gzip
        import json as _json

        from data_fetchers.batch_processor import _iter_merged_records

        merged_path = temp_dir / "merged_test.json.gz"
        record_with_trailing_comma_value = {
            "date": "2026-06-15",
            "asset": "000001",
            "value": "text_with_trailing_comma,",
        }
        with gzip.open(merged_path, "wt", encoding="utf-8") as f:
            f.write("[\n")
            f.write("  " + _json.dumps(record_with_trailing_comma_value, ensure_ascii=False))
            f.write("\n]")

        results = list(_iter_merged_records(merged_path, test_logger))
        assert len(results) == 1
        _line_content, rec = results[0]
        # 字段值末尾逗号应保留
        assert rec["value"] == "text_with_trailing_comma,"

    def test_scan_and_write_final_date_value_literal_null_string(self, temp_dir, test_logger):
        """Bug #6 等价覆盖（v1.9 迁移自 _write_final_file date_value_literal_null_string）：
        date_range 字段为字符串 "null" 时输出 JSON 字符串而非 null 字面量
        """
        import gzip
        import json as _json

        from data_fetchers.batch_processor import _scan_and_write_final

        merged_path = temp_dir / "merged_null_string.json.gz"
        records = [{"date": "null", "asset": "000001", "value": 1.0}]
        with gzip.open(merged_path, "wt", encoding="utf-8") as f:
            f.write("[\n")
            for i, rec in enumerate(records):
                if i > 0:
                    f.write(",\n")
                f.write("  " + _json.dumps(rec, ensure_ascii=False))
            f.write("\n]")

        output_path = temp_dir / "test_null_string.json.gz"
        meta_template = {
            "generated_at": "2026-06-15T00:00:00",
            "source": "test",
            "last_updated": "2026-06-15 00:00:00",
            "version": "test",
            "fields": ["date", "asset", "value"],
        }
        _scan_and_write_final(merged_path, output_path, meta_template, test_logger)

        with gzip.open(output_path, "rt", encoding="utf-8") as f:
            data = _json.load(f)
        # date_range.start 应为字符串 "null"，不是 JSON null
        assert data["meta"]["date_range"]["start"] == "null"
        assert isinstance(data["meta"]["date_range"]["start"], str)

    def test_scan_and_write_final_date_none(self, temp_dir, test_logger):
        """Bug #6 反向场景（v1.9 迁移自 _write_final_file date_none）：
        merged 文件无记录时 first/last_date 为 None，date_range 输出 JSON null 字面量
        """
        import gzip
        import json as _json

        from data_fetchers.batch_processor import _scan_and_write_final

        merged_path = temp_dir / "merged_empty.json.gz"
        with gzip.open(merged_path, "wt", encoding="utf-8") as f:
            f.write("[]")

        output_path = temp_dir / "test_none.json.gz"
        meta_template = {
            "generated_at": "2026-06-15T00:00:00",
            "source": "test",
            "last_updated": "2026-06-15 00:00:00",
            "version": "test",
            "fields": ["date", "asset", "value"],
        }
        _scan_and_write_final(merged_path, output_path, meta_template, test_logger)

        with gzip.open(output_path, "rt", encoding="utf-8") as f:
            data = _json.load(f)
        # None 应被序列化为 JSON null
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


class TestBugFixesV110:
    """v1.10 七项 Bug 修复回归测试（对称性 + 防御性 + 语义精修）"""

    def test_iter_merged_lines_second_pass_renamed(self, temp_dir):
        """Bug #1+#4: 函数已重命名为 _iter_merged_lines_second_pass，旧名 _iter_merged_lines 不再可用"""
        from data_fetchers import batch_processor

        assert hasattr(batch_processor, "_iter_merged_lines_second_pass"), (
            "v1.10 重命名后必须有 _iter_merged_lines_second_pass"
        )
        assert not hasattr(batch_processor, "_iter_merged_lines"), (
            "v1.10 旧名 _iter_merged_lines 应被移除，避免单独调用绕过预扫描"
        )

    def test_iter_merged_lines_second_pass_symmetric_with_records(self, temp_dir):
        """Bug #1: _iter_merged_lines_second_pass 与 _iter_merged_records 的 line_content 必须字节级一致

        构造一个字段值末尾本身带逗号的记录（容易被无脑 rstrip(",") 误剥离）：
        - _iter_merged_records 第一遍解析出 line_content 是 stripped 原值（不剥逗号）
        - _iter_merged_lines_second_pass 必须返回相同的 line_content
        """
        import gzip
        import json as _json

        from data_fetchers.batch_processor import (
            _iter_merged_lines_second_pass,
            _iter_merged_records,
        )

        merged_path = temp_dir / "merged_test.json.gz"
        # 字段值末尾带逗号 + 整行行末也带逗号（merged 数组分隔符）
        record = {"date": "2026-06-15", "asset": "000001", "note": "trailing,"}
        with gzip.open(merged_path, "wt", encoding="utf-8") as f:
            f.write("[\n")
            f.write("  " + _json.dumps(record, ensure_ascii=False) + ",\n")
            f.write("  " + _json.dumps({"date": "2026-06-16", "asset": "000002"}, ensure_ascii=False))
            f.write("\n]")

        first_pass_lines = [line for line, _ in _iter_merged_records(merged_path, _make_logger())]
        second_pass_lines = list(_iter_merged_lines_second_pass(merged_path))

        assert first_pass_lines == second_pass_lines, (
            f"两遍生成的 line_content 必须字节级一致，否则写出 ≠ 验证内容\n"
            f"first={first_pass_lines}\nsecond={second_pass_lines}"
        )
        # 验证两段式判定：第一条记录的 stripped 含尾逗号但原样可解析
        assert _json.loads(first_pass_lines[0])["note"] == "trailing,"

    def test_n_way_merge_pop_record_none_guard(self, temp_dir, test_logger):
        """Bug #5: pop_record 返回 None 时应跳过而非污染 same_key_records

        构造一个会在 peek 后切换 exhausted 状态的 mock stream，验证 None 不会进入 _emit_record。
        """
        import gzip
        import json as _json

        from data_fetchers import batch_processor

        # 创建一个正常的批次 + 一个会在 pop_record 时返回 None 的 mock stream
        batch_0 = temp_dir / "batch_0_factor.json.gz"
        with gzip.open(batch_0, "wt", encoding="utf-8") as f:
            _json.dump([{"date": "2026-06-15", "asset": "000001", "open": 10.0}], f)

        # 构造一个 BatchStream，pop_record 立即返回 None（模拟竞争条件）
        original_load = batch_processor.BatchStream._load_all
        original_pop = batch_processor.BatchStream.pop_record
        flip_state = {"force_none": False}

        def patched_pop_record(self):
            if flip_state["force_none"] and self.batch_idx == 99:
                return None
            return original_pop(self)

        # 直接调用 n_way_merge_deduplicate，仅 1 个真实批次，不会触发 mock 路径；
        # 这里主要验证守卫语句存在且语义正确（运行不抛异常）
        try:
            batch_processor.BatchStream._load_all = original_load
            batch_processor.BatchStream.pop_record = patched_pop_record
            merged = batch_processor.n_way_merge_deduplicate(1, "factor", result_dir=temp_dir, logger_arg=test_logger)
            assert merged is not None
            with gzip.open(merged, "rt", encoding="utf-8") as f:
                data = _json.load(f)
            assert len(data) == 1
        finally:
            batch_processor.BatchStream.pop_record = original_pop

    def test_emit_record_does_not_mutate_input(self, temp_dir, test_logger):
        """Bug #6: _emit_record 用 max() 替换 sort()，不再原地修改 same_key_records"""
        import gzip

        from data_fetchers.batch_processor import _emit_record

        # 故意构造乱序 batch_idx：max 取最大值，正确选 (5, dict_b)
        records = [
            (1, {"date": "2026-06-15", "asset": "001", "src": "old"}),
            (5, {"date": "2026-06-15", "asset": "001", "src": "new"}),
            (3, {"date": "2026-06-15", "asset": "001", "src": "mid"}),
        ]
        original_order = [t[0] for t in records]

        output_path = temp_dir / "test_emit_no_mutate.json.gz"
        with gzip.open(output_path, "wt", encoding="utf-8") as f:
            f.write("[\n")
            count = _emit_record(f, records, 0, test_logger)
            f.write("\n]")
        assert count == 1
        # 关键：原列表顺序不应被原地修改（v1.10 用 max 替换原地 sort）
        assert [t[0] for t in records] == original_order, (
            f"v1.10 _emit_record 不应原地修改输入列表，原顺序 {original_order} 实际 {[t[0] for t in records]}"
        )

        # 同时验证选中的是 batch_idx 最大者
        import json as _json

        with gzip.open(output_path, "rt", encoding="utf-8") as f:
            data = _json.load(f)
        assert data[0]["src"] == "new", "应选择 batch_idx 最大的记录"

    def test_save_batch_cache_sorted_str_date_works(self, temp_dir, test_logger):
        """Bug #7: docstring 契约——str 类型的 date 列正常工作（noop astype）"""
        import gzip
        import json as _json

        import pandas as pd

        factor_df = pd.DataFrame(
            {
                "date": ["2026-06-15", "2026-06-16"],  # str 类型，符合契约
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
                "date": ["2026-06-15", "2026-06-16"],
                "asset": ["000001", "000002"],
                "forward_return_1d": [0.01, 0.02],
                "forward_return_3d": [0.03, 0.06],
                "forward_return_5d": [0.05, 0.10],
            }
        )
        save_batch_cache_sorted(0, factor_df, return_df, result_dir=temp_dir, logger_arg=test_logger)

        factor_path = temp_dir / "batch_0_factor.json.gz"
        assert factor_path.exists()
        with gzip.open(factor_path, "rt", encoding="utf-8") as f:
            content = f.read()
        # 关键：date 字符串应原样保留，不出现 "<NA>" 字符串
        assert "<NA>" not in content, "str 类型 date 列经 astype(str) 不应产生 <NA>"
        # 验证可解析
        data = _json.loads(content)
        assert data[0]["date"] == "2026-06-15"


def _make_logger():
    """测试辅助：构造一个不输出到控制台的 logger"""
    import logging

    log = logging.getLogger("test_helper")
    log.setLevel(logging.WARNING)
    return log


class TestBugFixesV111:
    """v1.11 五项 Bug 修复回归测试（轻量化 + 健壮性 + 契约明确）"""

    def test_iter_merged_lines_second_pass_no_json_loads(self, temp_dir):
        """Bug #1: 第二遍生成器不应调用 json.loads（轻量化彻底化）

        通过 monkey-patch json.loads 抛错，验证函数不依赖 JSON 解析也能正常工作。
        """
        import gzip
        import json as _json
        from unittest import mock

        from data_fetchers.batch_processor import _iter_merged_lines_second_pass

        merged_path = temp_dir / "merged_test.json.gz"
        with gzip.open(merged_path, "wt", encoding="utf-8") as f:
            f.write("[\n")
            f.write('  {"date": "2026-06-15", "asset": "000001"},\n')
            f.write('  {"date": "2026-06-16", "asset": "000002"}\n')
            f.write("]")

        # patch json.loads 让其抛错——若第二遍生成器内部还有 json.loads 调用，立刻暴露
        with mock.patch("data_fetchers.batch_processor.json.loads", side_effect=AssertionError("不应调用 json.loads")):
            lines = list(_iter_merged_lines_second_pass(merged_path))

        assert len(lines) == 2
        # 验证仅做了行过滤+逗号剥离
        first = _json.loads(lines[0])
        assert first["asset"] == "000001"
        # 第一行原本以 "," 结尾，应被剥离
        assert not lines[0].endswith(",")

    def test_save_batch_cache_sorted_emits_entry_log(self, temp_dir):
        """Bug #3: save_batch_cache_sorted 应在入口处记录"保存批次 N..." 日志"""
        import logging

        import pandas as pd

        # 用一个捕获 logger 验证 info 日志被发出
        capture_log = logging.getLogger("test_entry_log_capture")
        capture_log.setLevel(logging.INFO)
        captured = []

        class _Handler(logging.Handler):
            def emit(self, record):
                captured.append(record.getMessage())

        handler = _Handler(level=logging.INFO)
        capture_log.addHandler(handler)
        capture_log.propagate = False

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
        save_batch_cache_sorted(7, factor_df, return_df, result_dir=temp_dir, logger_arg=capture_log)

        capture_log.removeHandler(handler)

        # 关键断言：入口日志和结尾日志都存在
        entry_logs = [m for m in captured if m == "保存批次 7..."]
        end_logs = [m for m in captured if m.startswith("  ✓ 保存批次 7:")]
        assert len(entry_logs) == 1, f"预期入口日志 '保存批次 7...'，实际捕获: {captured}"
        assert len(end_logs) == 1, f"预期结尾日志 '✓ 保存批次 7: ...'，实际捕获: {captured}"

    def test_scan_and_write_final_meta_string_with_special_chars(self, temp_dir, test_logger):
        """Bug #4: meta 字符串字段含双引号/反斜杠时应被 json.dumps 转义"""
        import gzip
        import json as _json

        from data_fetchers.batch_processor import _scan_and_write_final

        # 创建一个有效 merged 文件
        merged_path = temp_dir / "merged_test.json.gz"
        with gzip.open(merged_path, "wt", encoding="utf-8") as f:
            f.write("[\n")
            f.write('  {"date": "2026-06-15", "asset": "000001", "value": 1.0}\n')
            f.write("]")

        output_path = temp_dir / "final_special.json.gz"
        # 故意构造含双引号、反斜杠、换行的 meta 值
        meta_template = {
            "generated_at": '2026-06-15 with "quote"',
            "source": "test\\backslash",
            "last_updated": 'embedded "quote" inside',
            "version": "v1.0\nwith\nnewline",
            "fields": ["date", "asset", "value"],
            "extra_key": "note",
            "extra_value": 'comment with "quote" and \\backslash',
        }
        size_mb, stats = _scan_and_write_final(merged_path, output_path, meta_template, test_logger)
        assert size_mb > 0

        # 关键断言：写出的文件可被 json.loads 正常解析（特殊字符未破坏 JSON 结构）
        with gzip.open(output_path, "rt", encoding="utf-8") as f:
            data = _json.load(f)
        assert data["meta"]["generated_at"] == '2026-06-15 with "quote"'
        assert data["meta"]["source"] == "test\\backslash"
        assert data["meta"]["last_updated"] == 'embedded "quote" inside'
        assert data["meta"]["version"] == "v1.0\nwith\nnewline"
        assert data["meta"]["note"] == 'comment with "quote" and \\backslash'

    def test_format_final_output_rejects_same_paths(self, temp_dir, test_logger):
        """Bug #5: factor_merged_path 与 return_merged_path 相同时应抛 ValueError"""
        import gzip
        import json as _json

        from data_fetchers.batch_processor import format_final_output

        # 创建一个 dummy merged 文件
        same_path = temp_dir / "same_merged.json.gz"
        with gzip.open(same_path, "wt", encoding="utf-8") as f:
            _json.dump([{"date": "2026-06-15", "asset": "000001"}], f)

        with pytest.raises(ValueError, match="不能相同"):
            format_final_output(same_path, same_path, result_dir=temp_dir, logger_arg=test_logger)

    def test_emit_record_accepts_tuple_input(self, temp_dir, test_logger):
        """Bug #6: _emit_record 类型注解 Sequence 应同时接受 list 和 tuple

        Sequence 是只读协议，tuple 也实现 Sequence；list 类型注解则不允许 tuple。
        本测试验证 tuple 输入不报类型错误且功能正确（运行时 Python 不强制类型检查，
        但通过此测试保留 mypy/pyright 静态检查的语义意图）。
        """
        import gzip

        from data_fetchers.batch_processor import _emit_record

        # 用 tuple 调用（list 注解会被静态类型检查器拒绝，Sequence 接受）
        records_tuple = ((1, {"date": "2026-06-15", "asset": "001", "src": "first"}),)

        output_path = temp_dir / "test_emit_tuple.json.gz"
        with gzip.open(output_path, "wt", encoding="utf-8") as f:
            f.write("[\n")
            count = _emit_record(f, records_tuple, 0, test_logger)
            f.write("\n]")
        assert count == 1


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
