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
        with gzip.open(batch_path, 'wt', encoding='utf-8') as f:
            json.dump(test_data, f)

        stream = BatchStream(0, 'factor', result_dir=temp_dir)

        assert stream.batch_idx == 0
        assert stream.data_type == 'factor'
        assert len(stream.records) == 2
        assert not stream.exhausted

    def test_batch_stream_peek_key(self, temp_dir):
        """验证 peek_key 返回正确的 key"""
        batch_path = temp_dir / "batch_0_factor.json.gz"
        test_data = [{"date": "2026-05-27", "asset": "000001", "open": 10.0}]
        with gzip.open(batch_path, 'wt', encoding='utf-8') as f:
            json.dump(test_data, f)

        stream = BatchStream(0, 'factor', result_dir=temp_dir)
        key = stream.peek_key()

        assert key == ("2026-05-27", "000001")

    def test_batch_stream_pop_record(self, temp_dir):
        """验证 pop_record 返回正确记录"""
        batch_path = temp_dir / "batch_0_factor.json.gz"
        test_data = [
            {"date": "2026-05-27", "asset": "000001", "open": 10.0},
            {"date": "2026-05-27", "asset": "000002", "open": 20.0},
        ]
        with gzip.open(batch_path, 'wt', encoding='utf-8') as f:
            json.dump(test_data, f)

        stream = BatchStream(0, 'factor', result_dir=temp_dir)

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
            with gzip.open(path, 'wt', encoding='utf-8') as f:
                json.dump(test_data, f)

        stream0 = BatchStream(0, 'factor', result_dir=temp_dir)
        stream1 = BatchStream(1, 'factor', result_dir=temp_dir)

        assert stream0 < stream1

    def test_batch_stream_cleanup(self, temp_dir):
        """验证 cleanup 清理资源"""
        batch_path = temp_dir / "batch_0_factor.json.gz"
        test_data = [{"date": "2026-05-27", "asset": "000001", "open": 10.0}]
        with gzip.open(batch_path, 'wt', encoding='utf-8') as f:
            json.dump(test_data, f)

        stream = BatchStream(0, 'factor', result_dir=temp_dir)
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

        factor_df = pd.DataFrame({
            'date': ['2026-05-27', '2026-05-27'],
            'asset': ['000001', '000002'],
            'open': [10.0, 20.0],
            'close': [10.5, 20.5],
            'high': [11.0, 21.0],
            'low': [9.5, 19.5],
            'rsi_6': [50.0, 60.0],
                        'volume_ratio_5': [1.0, 1.5],
            'volume': [1000000.0, 2000000.0]
        })

        return_df = pd.DataFrame({
            'date': ['2026-05-27', '2026-05-27'],
            'asset': ['000001', '000002'],
            'forward_return_1d': [0.01, 0.02],
            'forward_return_3d': [0.03, 0.06],
            'forward_return_5d': [0.05, 0.10]
        })

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
        invalid_df = pd.DataFrame({
            'date': ['2026-05-27'],
            'asset': ['000001']
            # 缺少 open, close, high, low, rsi_6, volume_ratio_5
        })

        return_df = pd.DataFrame({
            'date': ['2026-05-27'],
            'asset': ['000001'],
            'forward_return_1d': [0.01],
            'forward_return_3d': [0.03],
            'forward_return_5d': [0.05]
        })

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
        for batch_idx, asset in [(0, '000001'), (1, '000002')]:
            factor_df = pd.DataFrame({
                'date': ['2026-05-27'],
                'asset': [asset],
                'open': [10.0 + batch_idx],
                'close': [10.5 + batch_idx],
                'high': [11.0 + batch_idx],
                'low': [9.5 + batch_idx],
                'rsi_6': [50.0],
                                'volume_ratio_5': [1.0],
                'volume': [1000000.0]
            })
            return_df = pd.DataFrame({
                'date': ['2026-05-27'],
                'asset': [asset],
                'forward_return_1d': [0.01],
                'forward_return_3d': [0.03],
                'forward_return_5d': [0.05]
            })
            save_batch_cache_sorted(batch_idx, factor_df, return_df, result_dir=temp_dir, logger_arg=test_logger)

        merged_path = n_way_merge_deduplicate(2, 'factor', result_dir=temp_dir, logger_arg=test_logger)

        assert merged_path is not None
        assert merged_path.name == "merged_factor.json.gz"

        # 验证合并结果
        with gzip.open(merged_path, 'rt', encoding='utf-8') as f:
            merged_data = json.load(f)
        assert len(merged_data) == 2

    def test_merge_deduplicate(self, temp_dir, test_logger):
        """TC005: 相同 key 选择最新 batch（去重）"""
        import pandas as pd

        # 两个批次包含相同 key，batch_1 是最新
        for batch_idx, close in [(0, 10.5), (1, 15.5)]:
            factor_df = pd.DataFrame({
                'date': ['2026-05-27'],
                'asset': ['000001'],  # 相同 key
                'open': [10.0],
                'close': [close],
                'high': [11.0],
                'low': [9.5],
                'rsi_6': [50.0],
                                'volume_ratio_5': [1.0],
                'volume': [1000000.0]
            })
            return_df = pd.DataFrame({
                'date': ['2026-05-27'],
                'asset': ['000001'],
                'forward_return_1d': [0.01],
                'forward_return_3d': [0.03],
                'forward_return_5d': [0.05]
            })
            save_batch_cache_sorted(batch_idx, factor_df, return_df, result_dir=temp_dir, logger_arg=test_logger)

        merged_path = n_way_merge_deduplicate(2, 'factor', result_dir=temp_dir, logger_arg=test_logger)

        # 验证选择最新 batch（batch_1 的 close=15.5）
        with gzip.open(merged_path, 'rt', encoding='utf-8') as f:
            merged_data = json.load(f)
        assert merged_data[0]['close'] == 15.5

    def test_merge_no_batches(self, temp_dir, test_logger):
        """TC006: 无有效批次返回 None"""
        merged_path = n_way_merge_deduplicate(0, 'factor', result_dir=temp_dir, logger_arg=test_logger)
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
        factor_df = pd.DataFrame({
            'date': ['2026-05-27'],
            'asset': ['000001'],
            'open': [10.0],
            'close': [10.5],
            'high': [11.0],
            'low': [9.5],
            'rsi_6': [50.0],
                            'volume_ratio_5': [1.0],
                'volume': [1000000.0]
        })
        return_df = pd.DataFrame({
            'date': ['2026-05-27'],
            'asset': ['000001'],
            'forward_return_1d': [0.01],
            'forward_return_3d': [0.03],
            'forward_return_5d': [0.05]
        })
        save_batch_cache_sorted(0, factor_df, return_df, result_dir=temp_dir, logger_arg=test_logger)

        factor_merged = n_way_merge_deduplicate(1, 'factor', result_dir=temp_dir, logger_arg=test_logger)
        return_merged = n_way_merge_deduplicate(1, 'return', result_dir=temp_dir, logger_arg=test_logger)

        format_final_output(factor_merged, return_merged, result_dir=temp_dir, logger_arg=test_logger)

        # 验证最终文件
        factor_final = temp_dir / "factor_data.json.gz"
        return_final = temp_dir / "return_data.json.gz"

        assert factor_final.exists()
        assert return_final.exists()

        # 验证 meta 结构
        with gzip.open(factor_final, 'rt', encoding='utf-8') as f:
            factor_data = json.load(f)
        assert 'meta' in factor_data
        assert 'data' in factor_data
        assert factor_data['meta']['n_days'] == 1
        assert factor_data['meta']['n_assets'] == 1

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
        factor_df = pd.DataFrame({
            'date': ['2026-05-27'],
            'asset': ['000001'],
            'open': [10.0],
            'close': [10.5],
            'high': [11.0],
            'low': [9.5],
            'rsi_6': [50.0],
                            'volume_ratio_5': [1.0],
                'volume': [1000000.0]
        })
        return_df = pd.DataFrame({
            'date': ['2026-05-27'],
            'asset': ['000001'],
            'forward_return_1d': [0.01],
            'forward_return_3d': [0.03],
            'forward_return_5d': [0.05]
        })
        save_batch_cache_sorted(0, factor_df, return_df, result_dir=temp_dir, logger_arg=test_logger)

        # 创建 merged 文件（手动创建）
        merged_factor = temp_dir / "merged_factor.json.gz"
        merged_return = temp_dir / "merged_return.json.gz"
        with gzip.open(merged_factor, 'wt', encoding='utf-8') as f:
            json.dump([{"date": "2026-05-27", "asset": "000001"}], f)
        with gzip.open(merged_return, 'wt', encoding='utf-8') as f:
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
# 集成测试
# ============================================================================

class TestIntegration:
    """TC011: 完整流程集成测试"""

    def test_full_workflow(self, temp_dir, test_logger):
        """验证完整批次处理流程"""
        import pandas as pd

        # Step 1: 批次保存
        for batch_idx in range(2):
            factor_df = pd.DataFrame({
                'date': ['2026-05-27'],
                'asset': [f'00000{batch_idx + 1}'],
                'open': [10.0 + batch_idx],
                'close': [10.5 + batch_idx],
                'high': [11.0 + batch_idx],
                'low': [9.5 + batch_idx],
                'rsi_6': [50.0],
                                'volume_ratio_5': [1.0],
                'volume': [1000000.0]
            })
            return_df = pd.DataFrame({
                'date': ['2026-05-27'],
                'asset': [f'00000{batch_idx + 1}'],
                'forward_return_1d': [0.01],
                'forward_return_3d': [0.03],
                'forward_return_5d': [0.05]
            })
            save_batch_cache_sorted(batch_idx, factor_df, return_df, result_dir=temp_dir, logger_arg=test_logger)

        # Step 2: N-way merge
        factor_merged = n_way_merge_deduplicate(2, 'factor', result_dir=temp_dir, logger_arg=test_logger)
        return_merged = n_way_merge_deduplicate(2, 'return', result_dir=temp_dir, logger_arg=test_logger)

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
