#!/usr/bin/env python3
"""
fetch_stock_list.py pytest 测试文件

测试覆盖：
- TC001: 正常流程 - fetch_stocks_from_sina mock测试
- TC002: 增量更新 - save_cache mock测试
- TC003: 缓存验证 - validate_cache测试
- TC004: 股票筛选 - is_valid_main_board_stock测试
- TC005: 市场判断 - determine_market测试
- TC006: 约束合规 - 版本号常量、公共模块导入验证
- TC007: 异常处理 - API失败、缓存失败测试

作者: 云舟
日期: 2026-05-27
"""

import json
import logging

# 导入测试目标
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest


sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from data_fetchers.fetch_stock_list import (
    _OUTPUT_VERSION,
    ST_PREFIX_S,
    ST_PREFIX_ST,
    ST_PREFIX_STAR,
    determine_market,
    get_cached_stock_codes,
    is_valid_main_board_stock,
    load_cache,
    refresh_stock_cache,
    validate_cache,
)


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def temp_dir(tmp_path):
    """临时目录fixture"""
    return tmp_path


@pytest.fixture
def test_logger():
    """测试logger fixture"""
    logger = logging.getLogger("test_fetch_stock_list")
    logger.setLevel(logging.DEBUG)
    # 添加处理器避免日志丢失
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    return logger


@pytest.fixture
def mock_stock_data():
    """模拟股票数据fixture（确保超过MIN_TOTAL_STOCKS阈值）"""
    # 创建足够多的股票数据（2600只）用于验证测试
    stocks = []
    for i in range(2600):
        if i < 1600:
            code = f"60{i:04d}"
            market = "sh"
        else:
            code = f"00{i:04d}"
            market = "sz"
        stocks.append({"code": code, "name": f"测试股票{i}", "market": market})
    return stocks


@pytest.fixture
def mock_cache_data(mock_stock_data):
    """模拟缓存数据fixture"""
    return {
        "meta": {
            "last_updated": datetime.now().isoformat(),
            "source": "sina_api",
            "total_count": len(mock_stock_data),
            "version": "2.9",
        },
        "stocks": mock_stock_data,
        "codes": [s["code"] for s in mock_stock_data],
    }


# ============================================================
# TC004: 股票筛选测试
# ============================================================


class TestStockFilter:
    """TC004: 股票筛选逻辑测试"""

    def test_valid_sh_main_board(self):
        """TC004-1: 沪市主板股票通过"""
        assert is_valid_main_board_stock("600000", "浦发银行") is True

    def test_valid_sz_main_board(self):
        """TC004-2: 深市主板股票通过"""
        assert is_valid_main_board_stock("000001", "平安银行") is True
        assert is_valid_main_board_stock("000002", "万科A") is True

    def test_gem_excluded(self):
        """TC004-3: 创业板股票剔除"""
        assert is_valid_main_board_stock("300001", "特锐德") is False

    def test_star_market_excluded(self):
        """TC004-4: 科创板股票剔除"""
        assert is_valid_main_board_stock("688001", "华兴源创") is False

    def test_bse_excluded(self):
        """TC004-5: 北交所股票剔除"""
        assert is_valid_main_board_stock("830001", "生物谷") is False
        assert is_valid_main_board_stock("430001", "新三板") is False

    def test_st_prefix_s_excluded(self):
        """TC004-6: S开头股票剔除"""
        assert is_valid_main_board_stock("600000", "SST股票") is False

    def test_st_prefix_star_st_excluded(self):
        """TC004-7: *ST股票剔除"""
        assert is_valid_main_board_stock("600000", "*ST股票") is False

    def test_st_prefix_st_excluded(self):
        """TC004-8: ST股票剔除"""
        assert is_valid_main_board_stock("600000", "ST股票") is False

    def test_delisted_excluded(self):
        """TC004-9: 退市股票剔除"""
        assert is_valid_main_board_stock("600000", "退市股票") is False

    def test_other_codes_excluded(self):
        """TC004-10: 其他代码剔除（如002001属于深市主板00开头，实际保留）"""
        # 注意：002开头属于深市主板（00开头），符合is_valid_main_board_stock保留规则
        assert is_valid_main_board_stock("002001", "中小板") is True


# ============================================================
# TC005: 市场判断测试
# ============================================================


class TestMarketDetermination:
    """TC005: 市场判断逻辑测试"""

    def test_sh_market(self):
        """TC005-1: 沪市主板判断"""
        assert determine_market("600000") == "sh"

    def test_sz_market(self):
        """TC005-2: 深市主板判断"""
        assert determine_market("000001") == "sz"

    def test_unknown_market(self):
        """TC005-3: 未知市场判断"""
        assert determine_market("300001") == "unknown"
        assert determine_market("688001") == "unknown"


# ============================================================
# TC003: 缓存验证测试
# ============================================================


class TestCacheValidation:
    """TC003: 缓存数据完整性验证测试"""

    def test_valid_cache_passes(self, mock_cache_data):
        """TC003-1: 有效缓存数据通过验证"""
        result = validate_cache(mock_cache_data)
        assert result["passed"] is True
        assert result["stats"]["total"] == 2600

    def test_low_total_count_warning(self):
        """TC003-2: 股票总数偏低警告"""
        # 创建低于警告阈值的缓存数据（2700只，WARN_TOTAL_STOCKS=2800）
        stocks = [{"code": f"60{i:04d}", "name": f"测试{i}", "market": "sh"} for i in range(2700)]
        cache_data = {
            "stocks": stocks,
        }

        result = validate_cache(cache_data)
        assert result["passed"] is True
        assert len(result["warnings"]) > 0
        assert "股票总数偏低" in result["warnings"][0]

    def test_st_stock_detection(self):
        """TC003-3: ST股票混入检测"""
        # 创建超过阈值的缓存数据
        stocks = [{"code": f"60{i:04d}", "name": f"测试{i}", "market": "sh"} for i in range(2600)]
        # 添加ST股票
        stocks.append({"code": "600000", "name": "ST股票", "market": "sh"})
        cache_data = {"stocks": stocks}

        result = validate_cache(cache_data)
        assert result["passed"] is False
        assert "发现ST股票混入" in result["errors"][0]

    def test_gem_stock_detection(self):
        """TC003-4: 创业板股票混入检测"""
        # 创建超过阈值的缓存数据
        stocks = [{"code": f"60{i:04d}", "name": f"测试{i}", "market": "sh"} for i in range(2600)]
        # 添加创业板股票
        stocks.append({"code": "300001", "name": "特锐德", "market": "sz"})
        cache_data = {"stocks": stocks}

        result = validate_cache(cache_data)
        assert result["passed"] is False
        assert "发现创业板股票混入" in result["errors"][0]


# ============================================================
# TC006: 约束合规测试
# ============================================================


class TestConstraintCompliance:
    """TC006: MODULE.md 约束合规测试"""

    def test_version_constant_exists(self):
        """TC006-1: 版本号提取为常量（MODULE.md 约束 #16）"""
        assert _OUTPUT_VERSION == "2.13"

    def test_st_prefixes_constant_exists(self):
        """TC006-2: ST前缀常量提取（MODULE.md 约束 #16）"""
        # 使用具名常量而非 dict
        assert ST_PREFIX_STAR == "*ST"
        assert ST_PREFIX_ST == "ST"
        assert ST_PREFIX_S == "S"

    def test_public_module_import(self):
        """TC006-3: 公共模块导入验证"""
        # 验证公共模块可导入
        from data_fetchers.common import setup_logger, write_json_cache

        assert callable(write_json_cache)
        assert callable(setup_logger)


# ============================================================
# TC002: 增量更新测试
# ============================================================


class TestIncrementalUpdate:
    """TC002: 增量更新逻辑测试（使用mock）"""

    @patch("data_fetchers.fetch_stock_list.fetch_stocks_from_sina")
    @patch("data_fetchers.fetch_stock_list.save_cache")
    def test_incremental_update_success(self, mock_save, mock_fetch, test_logger):
        """TC002-1: 增量更新成功"""
        # Mock API返回
        mock_fetch.return_value = ([{"code": "600000", "name": "浦发银行", "market": "sh"}], 1)

        # Mock保存缓存
        mock_save.return_value = {
            "meta": {
                "total_count": 1,
                "added_count": 1,
                "removed_count": 0,
                "updated_count": 0,
            },
            "stocks": mock_fetch.return_value[0],
        }

        # Mock验证通过
        with patch("data_fetchers.fetch_stock_list.validate_cache") as mock_validate:
            mock_validate.return_value = {
                "passed": True,
                "warnings": [],
                "errors": [],
                "stats": {"total": 1, "sh_count": 1, "sz_count": 0},
            }

            result = refresh_stock_cache(test_logger)

            assert result["success"] is True
            assert result["total_count"] == 1

    @patch("data_fetchers.fetch_stock_list.fetch_stocks_from_sina")
    def test_api_failure_returns_error_dict(self, mock_fetch, test_logger):
        """TC002-2: API失败返回错误字典（而非抛出异常）"""
        mock_fetch.side_effect = RuntimeError("API请求失败")

        # refresh_stock_cache 现在总是返回字典，而非抛出异常（v2.11）
        result = refresh_stock_cache(test_logger)

        assert result["success"] is False
        assert "增量更新股票列表失败" in result["message"]


# ============================================================
# TC007: 异常处理测试
# ============================================================


class TestExceptionHandling:
    """TC007: 异常处理测试"""

    @patch("data_fetchers.fetch_stock_list.CACHE_FILE")
    def test_load_cache_file_not_exists(self, mock_path, test_logger):
        """TC007-1: 缓存文件不存在返回None"""
        mock_path.exists.return_value = False

        result = load_cache(test_logger)
        assert result is None

    @patch("data_fetchers.fetch_stock_list.CACHE_FILE")
    def test_load_cache_json_error(self, mock_path, test_logger):
        """TC007-2: JSON解析失败返回None"""
        mock_path.exists.return_value = True

        # Mock文件读取抛出JSONDecodeError
        with patch("builtins.open", side_effect=json.JSONDecodeError("test", "test", 0)):
            result = load_cache(test_logger)
            assert result is None

    @patch("data_fetchers.fetch_stock_list.load_cache")
    def test_get_cached_stock_codes_empty_cache(self, mock_load):
        """TC007-3: 空缓存返回空列表"""
        mock_load.return_value = None

        result = get_cached_stock_codes()
        assert result == []


# ============================================================
# TC001: 正常流程测试（集成测试）
# ============================================================


class TestNormalFlow:
    """TC001: 正常流程测试（使用mock模拟API）"""

    @patch("data_fetchers.fetch_stock_list.write_json_cache")
    @patch("data_fetchers.fetch_stock_list.load_cache")
    def test_save_cache_incremental_update(self, mock_load, mock_write, test_logger, mock_stock_data):
        """TC001-1: 增量更新保存缓存"""
        # Mock现有缓存
        mock_load.return_value = {
            "stocks": [{"code": "600000", "name": "旧名称", "market": "sh"}],
        }

        # 调用save_cache
        from data_fetchers.fetch_stock_list import save_cache

        result = save_cache(mock_stock_data, 1, test_logger)

        # 验证调用write_json_cache
        assert mock_write.call_count == 2  # cache文件 + result文件

        # 验证返回数据结构
        assert "meta" in result
        assert "stocks" in result
        assert "codes" in result
        assert result["meta"]["version"] == "2.13"


# ============================================================
# 运行测试
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
