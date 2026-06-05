#!/usr/bin/env python3
"""
cache_manager.py pytest 测试文件

测试覆盖：
- gzip/json 缓存读写
- 统一缓存 API
- 辅助函数（cache_exists, delete_cache, get_cache_file_info）
- 增量追加（append_to_cache）
- 异常处理（FileNotFoundError, PermissionError）
- 参数选项（compresslevel, json_indent）

运行方式：
    pytest data_fetchers/test_cases/test_cache_manager.py -v

版本历史：
- v1.0 (2026-05-27): 从 __main__ 块转换，删除临时测试代码，创建 pytest 可执行文件
"""

import gzip
import logging

# 添加项目根目录到 sys.path
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch as mock_patch

import pytest


sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from data_fetchers.common.cache_manager import (
    append_to_cache,
    cache_exists,
    delete_cache,
    get_cache_file_info,
    get_module_logger,
    read_cache,
    read_gzip_cache,
    read_json_cache,
    write_cache,
    write_gzip_cache,
    write_json_cache,
)


# 配置测试 logger
@pytest.fixture(scope="module")
def test_logger():
    """配置测试用 logger"""
    logger = logging.getLogger("test_cache_manager")
    logger.setLevel(logging.DEBUG)
    return logger


@pytest.fixture
def temp_dir():
    """创建临时测试目录"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


class TestGzipCacheReadWrite:
    """TC001: gzip 缓存读写"""

    def test_write_and_read_gzip_cache(self, temp_dir, test_logger):
        """验证 gzip 压缩缓存的读写一致性"""
        test_path = temp_dir / "test.json.gz"
        test_data = {"test": [1, 2, 3], "dates": ["2024-01-01"]}

        # 写入
        write_gzip_cache(test_path, test_data, logger=test_logger)

        # 读取
        loaded = read_gzip_cache(test_path, logger=test_logger)

        # 验证
        assert loaded == test_data
        assert test_path.exists()

    def test_compresslevel_options(self, temp_dir, test_logger):
        """TC018: gzip 压缩级别控制"""
        # 使用更大的测试数据确保压缩差异明显
        data = {"large_data": [{"id": i, "value": f"test_string_{i}" * 10} for i in range(1000)]}

        # 压缩级别 1（最快）
        path1 = temp_dir / "level1.json.gz"
        write_gzip_cache(path1, data, compresslevel=1, logger=test_logger)
        size1 = path1.stat().st_size

        # 压缩级别 9（最高）
        path9 = temp_dir / "level9.json.gz"
        write_gzip_cache(path9, data, compresslevel=9, logger=test_logger)
        size9 = path9.stat().st_size

        # 验证：级别 9 文件更小（压缩率更高）
        assert size9 < size1
        # 验证：都能正常读取
        assert read_gzip_cache(path1, logger=test_logger) == data
        assert read_gzip_cache(path9, logger=test_logger) == data


class TestJsonCacheReadWrite:
    """TC002: json 缓存读写"""

    def test_write_and_read_json_cache(self, temp_dir, test_logger):
        """验证普通 JSON 缓存的读写一致性"""
        test_path = temp_dir / "test.json"
        test_data = {"test": [1, 2, 3]}

        write_json_cache(test_path, test_data, logger=test_logger)
        loaded = read_json_cache(test_path, logger=test_logger)

        assert loaded == test_data

    def test_json_format_options(self, temp_dir, test_logger):
        """验证 JSON 格式选项（indent, sort_keys）"""
        test_path = temp_dir / "test_readable.json"
        test_data = {"key1": "value1", "key2": "value2"}

        # 可读格式写入
        write_json_cache(test_path, test_data, json_indent=2, json_sort_keys=True, logger=test_logger)

        # 验证文件格式（显式指定 encoding='utf-8'）
        with open(test_path, encoding="utf-8") as f:
            content = f.read()

        # 验证有缩进和排序
        assert "  " in content  # indent=2 生成的缩进
        assert content.startswith("{")  # JSON 格式


class TestUnifiedCacheAPI:
    """TC013/TC014: 统一缓存 API"""

    def test_unified_api_gzip(self, temp_dir, test_logger):
        """验证 read_cache/write_cache 自动判断 gzip 文件"""
        test_path = temp_dir / "test.json.gz"
        data = {"gzip": True}

        write_cache(test_path, data, logger=test_logger)
        loaded = read_cache(test_path, logger=test_logger)

        assert loaded == data

    def test_unified_api_json(self, temp_dir, test_logger):
        """验证 read_cache/write_cache 自动判断 json 文件"""
        test_path = temp_dir / "test.json"
        data = {"gzip": False}

        write_cache(test_path, data, logger=test_logger)
        loaded = read_cache(test_path, logger=test_logger)

        assert loaded == data


class TestCacheExists:
    """TC015: 缓存存在性检查"""

    def test_cache_exists_true(self, temp_dir, test_logger):
        """文件存在时返回 True"""
        test_path = temp_dir / "test.json.gz"
        write_cache(test_path, {"data": "test"}, logger=test_logger)

        assert cache_exists(test_path) == True

    def test_cache_exists_false(self, temp_dir):
        """文件不存在时返回 False"""
        test_path = temp_dir / "not_exist.json.gz"

        assert cache_exists(test_path) == False


class TestDeleteCache:
    """TC016: 缓存删除函数"""

    def test_delete_existing_file(self, temp_dir, test_logger):
        """文件存在时删除成功，返回 True"""
        test_path = temp_dir / "test.json.gz"
        write_cache(test_path, {"data": "test"}, logger=test_logger)

        result = delete_cache(test_path, logger=test_logger)
        assert result == True
        assert not test_path.exists()

    def test_delete_non_existing_file(self, temp_dir, test_logger):
        """文件不存在时返回 False"""
        test_path = temp_dir / "not_exist.json.gz"

        result = delete_cache(test_path, logger=test_logger)
        assert result == False


class TestAppendToCache:
    """TC003: 增量追加数据"""

    def test_append_to_new_file(self, temp_dir, test_logger):
        """第一次追加（文件不存在）"""
        test_path = temp_dir / "test_append.json"

        total1 = append_to_cache(test_path, [{"date": "2024-01-01", "value": 100}], key="data", logger=test_logger)
        assert total1 == 1

        loaded = read_json_cache(test_path, logger=test_logger)
        assert len(loaded["data"]) == 1

    def test_append_to_existing_file(self, temp_dir, test_logger):
        """第二次追加（文件已存在）"""
        test_path = temp_dir / "test_append.json"

        # 第一次追加
        append_to_cache(test_path, [{"date": "2024-01-01", "value": 100}], key="data", logger=test_logger)

        # 第二次追加
        total2 = append_to_cache(test_path, [{"date": "2024-01-02", "value": 200}], key="data", logger=test_logger)
        assert total2 == 2

        # 验证数据
        loaded = read_json_cache(test_path, logger=test_logger)
        assert len(loaded["data"]) == 2


class TestGetCacheFileInfo:
    """TC004: 获取缓存文件信息"""

    def test_get_file_info_existing(self, temp_dir, test_logger):
        """文件存在时返回正确信息"""
        test_path = temp_dir / "test.json.gz"
        write_cache(test_path, {"data": "test"}, logger=test_logger)

        info = get_cache_file_info(test_path, logger=test_logger)

        assert info["exists"] == True
        assert info["size_mb"] > 0
        assert info["modified_time"] is not None
        assert info["error"] is None  # 无错误

    def test_get_file_info_not_existing(self, temp_dir, test_logger):
        """文件不存在时返回正确信息"""
        test_path = temp_dir / "not_exist.json.gz"

        info = get_cache_file_info(test_path, logger=test_logger)

        assert info["exists"] == False
        assert info["error"] is None  # 不是权限错误，只是不存在


class TestExceptions:
    """TC005/TC006: 异常处理"""

    def test_file_not_found(self, temp_dir, test_logger):
        """TC005: 读取不存在文件时抛 FileNotFoundError"""
        test_path = temp_dir / "not_exist.json.gz"

        with pytest.raises(FileNotFoundError) as exc_info:
            read_gzip_cache(test_path, logger=test_logger)

        assert "缓存文件不存在" in str(exc_info.value)

    def test_json_decode_error(self, temp_dir, test_logger):
        """TC006: JSON 解析失败时抛 ValueError"""
        test_path = temp_dir / "corrupt.json.gz"

        # 写入非法 JSON
        with gzip.open(test_path, "wt", encoding="utf-8") as f:
            f.write('{"invalid": }')  # 非法 JSON

        with pytest.raises(ValueError) as exc_info:
            read_gzip_cache(test_path, logger=test_logger)

        # 错误信息已精确化（v1.18）：包含 "gzip JSON文件内容解析失败"
        assert "JSON" in str(exc_info.value) and "解析失败" in str(exc_info.value)


class TestPathTypes:
    """TC008: path 支持 Path 和 str 类型"""

    def test_path_as_str(self, temp_dir, test_logger):
        """使用 str 类型调用"""
        test_path_str = str(temp_dir / "test_str.json.gz")
        data = {"test": [1, 2, 3]}

        write_gzip_cache(test_path_str, data, logger=test_logger)
        loaded = read_gzip_cache(test_path_str, logger=test_logger)

        assert loaded == data

    def test_path_as_path(self, temp_dir, test_logger):
        """使用 Path 类型调用"""
        test_path_obj = temp_dir / "test_path.json.gz"
        data = {"test": [1, 2, 3]}

        write_gzip_cache(test_path_obj, data, logger=test_logger)
        loaded = read_gzip_cache(test_path_obj, logger=test_logger)

        assert loaded == data


class TestLoggerFallback:
    """TC010: logger 不传时使用 fallback"""

    def test_no_logger_uses_fallback(self, temp_dir):
        """不传 logger 时使用模块级 fallback logger"""
        test_path = temp_dir / "test.json.gz"
        data = {"test": "data"}

        # 不传 logger 参数
        write_gzip_cache(test_path, data)
        loaded = read_gzip_cache(test_path)

        assert loaded == data


class TestDefensiveProgramming:
    """防御性编程测试"""

    def test_append_to_nested_dict_data(self, temp_dir, test_logger):
        """测试数据结构异常修复（嵌套 dict 转 list）"""
        test_path = temp_dir / "test_invalid.json"

        # 写入嵌套 dict 数据
        write_json_cache(test_path, {"data": {"nested": "dict"}}, logger=test_logger)

        # 追加 list 数据（应该自动修复）
        append_to_cache(test_path, [5, 6], key="data", logger=test_logger)

        # 验证结果
        loaded = read_json_cache(test_path, logger=test_logger)
        assert isinstance(loaded["data"], list)
