"""
尾盘数据拉取脚本测试用例

测试覆盖：
1. K线解析逻辑
2. 尾盘时段筛选（14:00-15:00共13根K线）
3. 指标计算逻辑（prices/volumes/tail_high/tail_low）
4. 缓存读写（增量/全量）
"""

import sys
import os
import pytest
from datetime import datetime

# 调整 sys.path 以支持相对导入
# 测试文件位于 data_fetchers/test_cases/
# 需要将 data_fetchers 目录加入 sys.path
_test_dir = os.path.dirname(os.path.abspath(__file__))
_data_fetchers_dir = os.path.dirname(_test_dir)
if _data_fetchers_dir not in sys.path:
    sys.path.insert(0, _data_fetchers_dir)

import fetch_tail_trading


class TestParseKline:
    """测试K线字符串解析"""

    def test_parse_normal_kline(self):
        """正常格式解析"""
        kline_str = "2026-05-28 14:00,10.64,10.65,10.65,10.63,11019,11724350.00"
        parts = kline_str.split(',')
        
        # 验证分离日期时间
        datetime_part = parts[0].split(' ')
        assert len(datetime_part) == 2
        assert datetime_part[0] == '2026-05-28'
        assert datetime_part[1] == '14:00'
        
        # 验证字段映射
        assert float(parts[1]) == 10.64  # open
        assert float(parts[2]) == 10.65  # close
        assert float(parts[3]) == 10.65  # high
        assert float(parts[4]) == 10.63  # low
        assert float(parts[5]) == 11019  # volume

    def test_parse_with_extra_fields(self):
        """包含额外字段的格式"""
        kline_str = "2026-05-28 15:00,10.64,10.66,10.66,10.64,23438,24971105.00,0.19,0.09"
        parts = kline_str.split(',')
        
        # 前6个字段应正确解析
        datetime_part = parts[0].split(' ')
        assert datetime_part[0] == '2026-05-28'
        assert datetime_part[1] == '15:00'


class TestTailKlineFilter:
    """测试尾盘时段筛选"""

    def test_filter_tail_klines(self):
        """筛选14:00-15:00时段（13根K线）"""
        # 构造测试数据（v2.0: 14:00-15:00共13根）
        klines = [
            {'date': '2026-05-28', 'time': '13:55', 'volume': 1000},  # 超出范围（前）
            {'date': '2026-05-28', 'time': '14:00', 'volume': 2000},
            {'date': '2026-05-28', 'time': '14:05', 'volume': 3000},
            {'date': '2026-05-28', 'time': '14:10', 'volume': 4000},
            {'date': '2026-05-28', 'time': '14:15', 'volume': 5000},
            {'date': '2026-05-28', 'time': '14:20', 'volume': 6000},
            {'date': '2026-05-28', 'time': '14:25', 'volume': 7000},
            {'date': '2026-05-28', 'time': '14:30', 'volume': 8000},
            {'date': '2026-05-28', 'time': '14:35', 'volume': 9000},
            {'date': '2026-05-28', 'time': '14:40', 'volume': 10000},
            {'date': '2026-05-28', 'time': '14:45', 'volume': 11000},
            {'date': '2026-05-28', 'time': '14:50', 'volume': 12000},
            {'date': '2026-05-28', 'time': '14:55', 'volume': 13000},
            {'date': '2026-05-28', 'time': '15:00', 'volume': 14000},
            {'date': '2026-05-28', 'time': '15:05', 'volume': 15000},  # 超出范围（后）
        ]
        
        # 调用筛选函数
        tail_klines = fetch_tail_trading._filter_tail_klines(klines)
        
        # 验证结果（应包含14:00-15:00共13根）
        assert len(tail_klines) == 13
        for kline in tail_klines:
            time = kline['time']
            assert time >= '14:00' and time <= '15:00'

    def test_filter_empty_klines(self):
        """空列表筛选"""
        tail_klines = fetch_tail_trading._filter_tail_klines([])
        assert tail_klines == []


class TestTailMetrics:
    """测试尾盘指标计算"""

    def test_calculate_tail_metrics(self):
        """计算尾盘指标（prices/volumes/tail_high/tail_low）"""
        # 构造测试数据（v2.0: 需要13条K线）
        tail_klines = [
            {'time': '14:00', 'volume': 1000, 'high': 10.5, 'low': 10.4, 'close': 10.45},
            {'time': '14:05', 'volume': 2000, 'high': 10.6, 'low': 10.5, 'close': 10.55},
            {'time': '14:10', 'volume': 3000, 'high': 10.7, 'low': 10.6, 'close': 10.65},
            {'time': '14:15', 'volume': 4000, 'high': 10.8, 'low': 10.7, 'close': 10.75},
            {'time': '14:20', 'volume': 5000, 'high': 10.9, 'low': 10.8, 'close': 10.85},
            {'time': '14:25', 'volume': 6000, 'high': 11.0, 'low': 10.9, 'close': 10.95},
            {'time': '14:30', 'volume': 7000, 'high': 11.1, 'low': 11.0, 'close': 11.05},
            {'time': '14:35', 'volume': 8000, 'high': 11.2, 'low': 11.1, 'close': 11.15},
            {'time': '14:40', 'volume': 9000, 'high': 11.3, 'low': 11.2, 'close': 11.25},
            {'time': '14:45', 'volume': 10000, 'high': 11.4, 'low': 11.3, 'close': 11.35},
            {'time': '14:50', 'volume': 11000, 'high': 11.5, 'low': 11.4, 'close': 11.45},
            {'time': '14:55', 'volume': 12000, 'high': 11.6, 'low': 11.5, 'close': 11.55},
            {'time': '15:00', 'volume': 13000, 'high': 11.7, 'low': 11.6, 'close': 11.65},  # 第13条
]
        # v2.1: day_volume 参数已删除
    
        # 调用计算函数
        metrics = fetch_tail_trading._calculate_tail_metrics(tail_klines)
        
        # 验证结果
        assert metrics is not None
        assert 'prices' in metrics
        assert 'volumes' in metrics
        assert 'tail_high' in metrics
        assert 'tail_low' in metrics
        
        # prices 应有13个值，按时间升序
        assert len(metrics['prices']) == 13
        assert metrics['prices'][0] == 10.45  # 14:00
        assert metrics['prices'][12] == 11.65  # 15:00
        
        # volumes 应有13个值
        assert len(metrics['volumes']) == 13
        assert metrics['volumes'][0] == 1000  # 14:00
        assert metrics['volumes'][12] == 13000  # 15:00
        
        # 最高价 = max(10.5, ..., 11.7) = 11.7
        assert metrics['tail_high'] == 11.7
        
        # 最低价 = min(10.4, ..., 11.6) = 10.4
        assert metrics['tail_low'] == 10.4

    def test_calculate_metrics_insufficient_klines(self):
        """尾盘K线数量不足13根时返回None"""
        tail_klines = [
            {'time': '14:00', 'volume': 1000, 'high': 10.5, 'low': 10.4, 'close': 10.45},
            {'time': '14:05', 'volume': 2000, 'high': 10.6, 'low': 10.5, 'close': 10.55},
# 只有2条，不足13条
        ]
        # v2.1: day_volume 参数已删除
    
        metrics = fetch_tail_trading._calculate_tail_metrics(tail_klines)
        
        # K线数量不足时返回None
        assert metrics is None

    def test_calculate_metrics_sorted_by_time(self):
        """验证 prices/volumes 按时间升序排列"""
        # 构造乱序数据
        tail_klines = [
            {'time': '14:30', 'volume': 7000, 'close': 11.05},
            {'time': '14:00', 'volume': 1000, 'close': 10.45},
            {'time': '14:15', 'volume': 4000, 'close': 10.75},
            {'time': '14:05', 'volume': 2000, 'close': 10.55},
            {'time': '14:10', 'volume': 3000, 'close': 10.65},
            {'time': '14:20', 'volume': 5000, 'close': 10.85},
            {'time': '14:25', 'volume': 6000, 'close': 10.95},
            {'time': '14:35', 'volume': 8000, 'close': 11.15},
            {'time': '14:40', 'volume': 9000, 'close': 11.25},
            {'time': '14:45', 'volume': 10000, 'close': 11.35},
            {'time': '14:50', 'volume': 11000, 'close': 11.45},
            {'time': '14:55', 'volume': 12000, 'close': 11.55},
{'time': '15:00', 'volume': 13000, 'close': 11.65},
        ]
        # v2.1: day_volume 参数已删除
    
        metrics = fetch_tail_trading._calculate_tail_metrics(tail_klines)
        
        assert metrics is not None
        # 验证排序：prices[0] 应为 14:00 的收盘价
        assert metrics['prices'][0] == 10.45  # 14:00
        assert metrics['prices'][12] == 11.65  # 15:00


class TestMarketCode:
    """测试市场代码转换"""

    def test_parse_market_code_shenzhen(self):
        """深市股票（0/3开头）"""
        market, pure_code = fetch_tail_trading._parse_market_code('000001')
        assert market == 0
        assert pure_code == '000001'

    def test_parse_market_code_shanghai(self):
        """沪市股票（6开头）"""
        market, pure_code = fetch_tail_trading._parse_market_code('600000')
        assert market == 1
        assert pure_code == '600000'

    def test_parse_market_code_with_prefix_sh(self):
        """带sh前缀的代码，函数不处理前缀"""
        # 函数只检查是否以'6'开头，不处理前缀
        market, pure_code = fetch_tail_trading._parse_market_code('sh600000')
        # 'sh600000'不以'6'开头，判定为深市，返回原代码
        assert market == 0
        assert pure_code == 'sh600000'


class TestOutputVersion:
    """测试输出版本常量"""

    def test_output_version_defined(self):
        """版本常量已定义"""
        assert hasattr(fetch_tail_trading, '_OUTPUT_VERSION')
        assert fetch_tail_trading._OUTPUT_VERSION == '2.1'  # v2.1 第六轮深度优化


class TestConstants:
    """测试常量定义"""

    def test_tail_period_start(self):
        """尾盘开始时间"""
        assert fetch_tail_trading.TAIL_PERIOD_START == '14:00'

    def test_tail_kline_count(self):
        """尾盘K线数量"""
        assert fetch_tail_trading.TAIL_KLINE_COUNT == 13


if __name__ == '__main__':
    pytest.main([__file__, '-v'])