#!/usr/bin/env python3
"""
fetch_tail_trading.py 单元测试

测试 v3.1 Bug修复后的核心功能
"""

import pytest
from datetime import time as datetime_time


class TestFormatSinaCode:
    """测试 _format_sina_code 函数（问题10：北交所处理）"""
    
    def test_sh_market(self):
        """沪市股票代码格式化"""
        from data_fetchers.fetch_tail_trading import _format_sina_code
        assert _format_sina_code('600000') == 'sh600000'
        assert _format_sina_code('600001') == 'sh600001'
    
    def test_sz_market(self):
        """深市股票代码格式化"""
        from data_fetchers.fetch_tail_trading import _format_sina_code
        assert _format_sina_code('000001') == 'sz000001'
        assert _format_sina_code('300001') == 'sz300001'
    
    def test_bj_market(self):
        """北交所股票代码格式化（v3.1新增）"""
        from data_fetchers.fetch_tail_trading import _format_sina_code
        assert _format_sina_code('430001') == 'bj430001'
        assert _format_sina_code('830001') == 'bj830001'


class TestFilterTailKlines:
    """测试 _filter_tail_klines 函数（问题1：时间比较逻辑）"""
    
    def test_normal_tail_period(self):
        """正常尾盘时段过滤"""
        from data_fetchers.fetch_tail_trading import _filter_tail_klines
        klines = [
            {'time': '09:30:00', 'close': 10.0},
            {'time': '14:00:00', 'close': 11.0},
            {'time': '14:30:00', 'close': 12.0},
            {'time': '15:00:00', 'close': 13.0},
            {'time': '15:05:00', 'close': 14.0},
        ]
        result = _filter_tail_klines(klines)
        assert len(result) == 3
        assert result[0]['time'] == '14:00:00'
        assert result[2]['time'] == '15:00:00'
    
    def test_single_digit_hour_bug(self):
        """单字符小时不应被错误包含（v3.1修复的核心bug）"""
        from data_fetchers.fetch_tail_trading import _filter_tail_klines
        klines = [
            {'time': '9:30:00', 'close': 10.0},  # 单字符小时，应被排除
            {'time': '14:00:00', 'close': 11.0},
        ]
        result = _filter_tail_klines(klines)
        assert len(result) == 1
        assert result[0]['time'] == '14:00:00'
    
    def test_no_seconds_format(self):
        """无秒的时间格式支持"""
        from data_fetchers.fetch_tail_trading import _filter_tail_klines
        klines = [
            {'time': '14:00', 'close': 11.0},
            {'time': '15:00', 'close': 13.0},
        ]
        result = _filter_tail_klines(klines)
        assert len(result) == 2
    
    def test_empty_time(self):
        """空时间字符串跳过"""
        from data_fetchers.fetch_tail_trading import _filter_tail_klines
        klines = [
            {'time': '', 'close': 10.0},
            {'time': '14:00:00', 'close': 11.0},
        ]
        result = _filter_tail_klines(klines)
        assert len(result) == 1


class TestCalculateTailMetrics:
    """测试 _calculate_tail_metrics 函数（问题6、7：日志增强）"""
    
    def test_sufficient_klines(self):
        """足够K线时正常计算"""
        from data_fetchers.fetch_tail_trading import _calculate_tail_metrics
        klines = [{'time': f'14:{i*5:02d}:00', 'close': 10.0 + i, 'high': 11.0 + i, 'low': 9.0 + i, 'volume': 1000 + i} for i in range(13)]
        result = _calculate_tail_metrics(klines, date='2026-05-30', code='000001')
        assert result is not None
        assert len(result['prices']) == 13
        assert len(result['volumes']) == 13
    
    def test_insufficient_klines_returns_none(self):
        """K线不足时返回None"""
        from data_fetchers.fetch_tail_trading import _calculate_tail_metrics
        klines = [{'time': '14:00:00', 'close': 10.0, 'high': 11.0, 'low': 9.0, 'volume': 1000} for i in range(5)]
        result = _calculate_tail_metrics(klines, date='2026-05-30', code='000001')
        assert result is None


class TestFetchTailTradingBatch:
    """测试 fetch_tail_trading_batch 函数（问题5、8：返回格式和统计）"""
    
    def test_returns_dict_format(self):
        """v3.1: 返回字典格式（包含 records 和 failed_stocks）"""
        from data_fetchers.fetch_tail_trading import fetch_tail_trading_batch
        # 注意：此测试需要mock网络请求，此处仅验证返回结构
        # 实际网络测试应在集成测试中进行
        pass  # 需要mock，此处仅占位


class TestMergeRecords:
    """测试 merge_records 函数（问题2、4：默认参数和断点续传）"""
    
    def test_default_source_is_sina(self):
        """默认数据源应为 sina_5min（v3.1修复）"""
        from data_fetchers.fetch_tail_trading import merge_records
        result = merge_records(None, [{'date': '2026-05-30', 'asset': '000001', 'prices': [], 'volumes': [], 'tail_high': 10.0, 'tail_low': 9.0}])
        assert result['meta']['source'] == 'sina_5min'
    
    def test_failed_stocks_merge(self):
        """失败股票列表合并（v3.1新增）"""
        from data_fetchers.fetch_tail_trading import merge_records
        
        # 第一次拉取：部分失败
        result1 = merge_records(
            None,
            [{'date': '2026-05-30', 'asset': '000001', 'prices': [], 'volumes': [], 'tail_high': 10.0, 'tail_low': 9.0}],
            failed_stocks=['000002', '000003']
        )
        assert 'failed_stocks' in result1['meta']
        assert '000002' in result1['meta']['failed_stocks']
        assert '000003' in result1['meta']['failed_stocks']
        
        # 第二次拉取：成功拉取000002，000003仍然失败
        result2 = merge_records(
            result1,
            [{'date': '2026-05-30', 'asset': '000002', 'prices': [], 'volumes': [], 'tail_high': 10.0, 'tail_low': 9.0}],
            failed_stocks=['000003']
        )
        # 000002 应从失败列表移除
        assert '000002' not in result2['meta']['failed_stocks']
        # 000003 应保留在失败列表
        assert '000003' in result2['meta']['failed_stocks']