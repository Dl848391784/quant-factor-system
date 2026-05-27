#!/usr/bin/env python3
"""
fetch_turnover.py 测试用例

测试覆盖：
1. 核心流程（TC001）
2. 主板股票过滤（TC002）
3. 数据合并（TC003）
4. 缓存操作（TC004）
5. 约束合规（TC005）

版本历史:
- v1.0 (2026-05-27): 初始测试文件

作者: 云舟
日期: 2026-05-27
"""

import gzip
import json
import logging
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from data_fetchers.fetch_turnover import (
    _OUTPUT_VERSION,
    ST_PREFIXES,
    is_main_board_stock,
    load_cache,
    save_cache,
    get_cached_turnover_codes,
    merge_records,
    get_existing_stocks,
)


# ============================================================
# 测试配置
# ============================================================

@pytest.fixture
def test_logger():
    """测试 logger"""
    return logging.getLogger('test_fetch_turnover')


@pytest.fixture
def temp_cache_file():
    """临时缓存文件"""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = Path(tmpdir) / 'test_turnover.json.gz'
        yield cache_path


# ============================================================
# TC001: 核心流程测试
# ============================================================

class TestCoreFlow:
    """核心流程测试"""
    
    def test_load_cache_not_exists(self, test_logger, monkeypatch):
        """TC001-1: 缓存文件不存在时返回 None"""
        # Mock CACHE_FILE
        monkeypatch.setattr(
            'data_fetchers.fetch_turnover.CACHE_FILE',
            Path('/nonexistent/path/file.json.gz')
        )
        result = load_cache(logger_arg=test_logger)
        assert result is None
    
    def test_load_cache_valid_json(self, test_logger, temp_cache_file, monkeypatch):
        """TC001-2: 加载有效缓存"""
        # 准备测试数据
        test_data = {
            'meta': {
                'generated_at': '2026-05-27T19:00:00',
                'source': 'eastmoney',
                'n_days': 1,
                'n_assets': 100,
                'date_range': {'start': '2026-05-26', 'end': '2026-05-27'},
                'last_updated': '2026-05-27 19:00:00',
                'version': '2.11'
            },
            'data': [
                {'date': '2026-05-27', 'asset': '600000', 'turnover_rate': 2.5}
            ]
        }
        
        # 写入测试缓存
        with gzip.open(temp_cache_file, 'wt', encoding='utf-8') as f:
            json.dump(test_data, f)
        
        # Mock CACHE_FILE
        monkeypatch.setattr(
            'data_fetchers.fetch_turnover.CACHE_FILE',
            temp_cache_file
        )
        
        result = load_cache(logger_arg=test_logger)
        assert result is not None
        assert isinstance(result, dict)
        assert 'meta' in result
        assert 'data' in result
    
    def test_load_cache_type_check(self, test_logger, temp_cache_file, monkeypatch):
        """TC001-3: 缓存 JSON 类型校验（非 dict 返回 None）"""
        # 准备非 dict 类型数据
        test_data = ['invalid', 'list', 'data']
        
        # 写入测试缓存
        with gzip.open(temp_cache_file, 'wt', encoding='utf-8') as f:
            json.dump(test_data, f)
        
        # Mock CACHE_FILE
        monkeypatch.setattr(
            'data_fetchers.fetch_turnover.CACHE_FILE',
            temp_cache_file
        )
        
        result = load_cache(logger_arg=test_logger)
        assert result is None  # 非 dict 类型应返回 None
    
    def test_save_cache_atomic_write(self, test_logger, temp_cache_file, monkeypatch):
        """TC001-4: 保存缓存原子写入"""
        test_data = {
            'meta': {
                'generated_at': '2026-05-27T19:00:00',
                'source': 'eastmoney',
                'n_days': 1,
                'n_assets': 100,
                'date_range': {'start': '2026-05-26', 'end': '2026-05-27'},
                'last_updated': '2026-05-27 19:00:00',
                'version': '2.11'
            },
            'data': []
        }
        
        # Mock FACTOR_DATA_DIR
        monkeypatch.setattr(
            'data_fetchers.fetch_turnover.FACTOR_DATA_DIR',
            temp_cache_file.parent
        )
        monkeypatch.setattr(
            'data_fetchers.fetch_turnover.CACHE_FILE',
            temp_cache_file
        )
        
        save_cache(test_data, logger_arg=test_logger)
        
        # 验证文件存在且内容正确
        assert temp_cache_file.exists()
        with gzip.open(temp_cache_file, 'rt', encoding='utf-8') as f:
            loaded = json.load(f)
        assert loaded['meta']['version'] == '2.11'


# ============================================================
# TC002: 主板股票过滤测试
# ============================================================

class TestStockFilter:
    """主板股票过滤测试"""
    
    def test_main_board_sh(self):
        """TC002-1: 上海主板股票通过"""
        assert is_main_board_stock('600000', '浦发银行') is True
        assert is_main_board_stock('601318', '中国平安') is True
    
    def test_main_board_sz(self):
        """TC002-2: 深圳主板股票通过"""
        assert is_main_board_stock('000001', '平安银行') is True
        assert is_main_board_stock('000002', '万科A') is True
    
    def test_gem_excluded(self):
        """TC002-3: 创业板股票剔除"""
        assert is_main_board_stock('300001', '特锐德') is False
        assert is_main_board_stock('300999', '稳健医疗') is False
    
    def test_star_excluded(self):
        """TC002-4: 科创板股票剔除"""
        assert is_main_board_stock('688001', '华兴源创') is False
    
    def test_bse_excluded(self):
        """TC002-5: 北交所股票剔除"""
        assert is_main_board_stock('830001', '速腾聚创') is False
        assert is_main_board_stock('430001', '某股票') is False
    
    def test_st_excluded(self):
        """TC002-6: ST 股票剔除（前缀匹配）"""
        # *ST 股票
        assert is_main_board_stock('600000', '*ST某某') is False
        # ST 股票
        assert is_main_board_stock('600000', 'ST某某') is False
        # SST 股票
        assert is_main_board_stock('600000', 'SST某某') is False
        # S*ST 股票
        assert is_main_board_stock('600000', 'S*ST某某') is False
    
    def test_delisted_excluded(self):
        """TC002-7: 退市股票剔除"""
        assert is_main_board_stock('600000', '某某退市') is False
        assert is_main_board_stock('600000', '退市某某') is False
    
    def test_normal_stock_with_st_in_name(self):
        """TC002-8: 正常股票名称含 'ST' 字符串（不误判）"""
        # 前缀匹配不会误判 "东ST" 这种情况
        assert is_main_board_stock('600000', '东ST科技') is True


# ============================================================
# TC003: 数据合并测试
# ============================================================

class TestDataMerge:
    """数据合并测试"""
    
    def test_merge_new_records(self, test_logger):
        """TC003-1: 合并新数据"""
        existing = None
        new_records = [
            {'date': '2026-05-27', 'asset': '600000', 'turnover_rate': 2.5}
        ]
        
        result = merge_records(existing, new_records, source='eastmoney', logger_arg=test_logger)
        
        assert result['meta']['source'] == 'eastmoney'
        assert result['meta']['n_assets'] == 1
        assert len(result['data']) == 1
    
    def test_merge_with_existing(self, test_logger):
        """TC003-2: 合并到现有数据"""
        existing = {
            'meta': {
                'generated_at': '2026-05-26T19:00:00',
                'source': 'eastmoney',
                'n_days': 1,
                'n_assets': 100,
                'date_range': {'start': '2026-05-26', 'end': '2026-05-26'},
                'last_updated': '2026-05-26 19:00:00',
                'version': '2.10'
            },
            'data': [
                {'date': '2026-05-26', 'asset': '600000', 'turnover_rate': 1.5}
            ]
        }
        new_records = [
            {'date': '2026-05-27', 'asset': '600000', 'turnover_rate': 2.5}
        ]
        
        result = merge_records(existing, new_records, source='eastmoney', logger_arg=test_logger)
        
        assert result['meta']['n_days'] == 2
        assert result['meta']['n_assets'] == 1
        assert len(result['data']) == 2
    
    def test_merge_dedup(self, test_logger):
        """TC003-3: 合并去重（同一 date+asset）"""
        existing = {
            'meta': {
                'generated_at': '2026-05-26T19:00:00',
                'source': 'eastmoney',
                'n_days': 1,
                'n_assets': 100,
                'date_range': {'start': '2026-05-26', 'end': '2026-05-26'},
                'last_updated': '2026-05-26 19:00:00',
                'version': '2.10'
            },
            'data': [
                {'date': '2026-05-27', 'asset': '600000', 'turnover_rate': 1.5}
            ]
        }
        new_records = [
            {'date': '2026-05-27', 'asset': '600000', 'turnover_rate': 2.5}  # 相同 key
        ]
        
        result = merge_records(existing, new_records, source='eastmoney', logger_arg=test_logger)
        
        # 去重后应只有 1 条
        assert len(result['data']) == 1
        # 新数据覆盖旧数据
        assert result['data'][0]['turnover_rate'] == 2.5
    
    def test_merge_empty_new_records(self, test_logger):
        """TC003-4: 新数据为空时保留现有数据（遵循 MODULE.md 约束 88）"""
        existing = {
            'meta': {
                'generated_at': '2026-05-26T19:00:00',
                'source': 'eastmoney',
                'n_days': 1,
                'n_assets': 100,
                'date_range': {'start': '2026-05-26', 'end': '2026-05-26'},
                'last_updated': '2026-05-26 19:00:00',
                'version': '2.10'
            },
            'data': [
                {'date': '2026-05-26', 'asset': '600000', 'turnover_rate': 1.5}
            ]
        }
        new_records = []
        
        result = merge_records(existing, new_records, source='eastmoney', logger_arg=test_logger)
        
        # 应返回 existing，不做更新
        assert result == existing
    
    def test_merge_mixed_source(self, test_logger):
        """TC003-5: 数据源合并逻辑（遵循 MODULE.md 约束 93）"""
        existing = {
            'meta': {
                'generated_at': '2026-05-26T19:00:00',
                'source': 'eastmoney',
                'n_days': 1,
                'n_assets': 100,
                'date_range': {'start': '2026-05-26', 'end': '2026-05-26'},
                'last_updated': '2026-05-26 19:00:00',
                'version': '2.10'
            },
            'data': []
        }
        new_records = [
            {'date': '2026-05-27', 'asset': '600000', 'turnover_rate': 2.5}
        ]
        
        # 不同数据源 → mixed
        result = merge_records(existing, new_records, source='baostock', logger_arg=test_logger)
        assert result['meta']['source'] == 'mixed'
        
        # 相同数据源 → 保持原数据源
        result2 = merge_records(existing, new_records, source='eastmoney', logger_arg=test_logger)
        assert result2['meta']['source'] == 'eastmoney'


# ============================================================
# TC004: 缓存操作测试
# ============================================================

class TestCacheOperations:
    """缓存操作测试"""
    
    def test_get_existing_stocks_empty(self):
        """TC004-1: 空缓存返回空集合"""
        result = get_existing_stocks(None)
        assert result == set()
    
    def test_get_existing_stocks_valid(self):
        """TC004-2: 获取已有股票代码"""
        cache_data = {
            'meta': {},
            'data': [
                {'date': '2026-05-27', 'asset': '600000', 'turnover_rate': 2.5},
                {'date': '2026-05-27', 'asset': '601318', 'turnover_rate': 1.5}
            ]
        }
        
        result = get_existing_stocks(cache_data)
        assert result == {'600000', '601318'}
    
    def test_get_cached_turnover_codes_empty(self, test_logger, monkeypatch):
        """TC004-3: 缓存不存在返回空集合"""
        monkeypatch.setattr(
            'data_fetchers.fetch_turnover.CACHE_FILE',
            Path('/nonexistent/path/file.json.gz')
        )
        
        result = get_cached_turnover_codes(logger_arg=test_logger)
        assert result == set()
        assert isinstance(result, set)


# ============================================================
# TC005: 约束合规测试
# ============================================================

class TestConstraintCompliance:
    """约束合规测试"""
    
    def test_version_constant_exists(self):
        """TC005-1: 版本号提取为常量（MODULE.md 约束 #16）"""
        assert _OUTPUT_VERSION == '2.11'
    
    def test_st_prefixes_constant_exists(self):
        """TC005-2: ST前缀常量提取（MODULE.md 约束 #16）"""
        assert ST_PREFIXES is not None
        assert isinstance(ST_PREFIXES, tuple)
        assert '*ST' in ST_PREFIXES
        assert 'ST' in ST_PREFIXES
    
    def test_st_prefixes_is_tuple(self):
        """TC005-3: ST_PREFIXES 使用元组（MODULE.md 约束 #89）"""
        # 元组可直接传给 startswith
        assert isinstance(ST_PREFIXES, tuple)
    
    def test_public_module_import(self):
        """TC005-4: 公共模块导入测试"""
        # 验证所有 __all__ 导出函数可导入
        from data_fetchers.fetch_turnover import (
            load_cache,
            save_cache,
            get_cached_turnover_codes,
            fetch_turnover_rate_eastmoney,
            fetch_turnover_rate_baostock,
            main,
        )
        assert callable(load_cache)
        assert callable(save_cache)
        assert callable(get_cached_turnover_codes)


# ============================================================
# 运行测试
# ============================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v'])