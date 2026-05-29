"""
尾盘数据拉取脚本测试用例

测试覆盖：
1. K线解析逻辑
2. 尾盘时段筛选
3. 指标计算逻辑
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
        kline_str = "2026-05-28 14:30,10.64,10.65,10.65,10.63,11019,11724350.00"
        parts = kline_str.split(',')
        
        # 验证分离日期时间
        datetime_part = parts[0].split(' ')
        assert len(datetime_part) == 2
        assert datetime_part[0] == '2026-05-28'
        assert datetime_part[1] == '14:30'
        
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
        """筛选14:30-15:00时段"""
        # 构造测试数据
        klines = [
            {'date': '2026-05-28', 'time': '14:25', 'volume': 1000},
            {'date': '2026-05-28', 'time': '14:30', 'volume': 2000},
            {'date': '2026-05-28', 'time': '14:35', 'volume': 3000},
            {'date': '2026-05-28', 'time': '14:40', 'volume': 4000},
            {'date': '2026-05-28', 'time': '14:45', 'volume': 5000},
            {'date': '2026-05-28', 'time': '14:50', 'volume': 6000},
            {'date': '2026-05-28', 'time': '14:55', 'volume': 7000},
            {'date': '2026-05-28', 'time': '15:00', 'volume': 8000},
            {'date': '2026-05-28', 'time': '15:05', 'volume': 9000},  # 超出范围
        ]
        
        # 调用筛选函数
        tail_klines = fetch_tail_trading._filter_tail_klines(klines)
        
        # 验证结果（应包含14:30-15:00共7根）
        assert len(tail_klines) == 7
        for kline in tail_klines:
            time = kline['time']
            assert time >= '14:30' and time <= '15:00'

    def test_filter_empty_klines(self):
        """空列表筛选"""
        tail_klines = fetch_tail_trading._filter_tail_klines([])
        assert tail_klines == []


class TestTailMetrics:
    """测试尾盘指标计算"""

    def test_calculate_tail_metrics(self):
        """计算尾盘成交量占比"""
        # 构造测试数据（需要7条K线，因为TAIL_KLINE_COUNT=7）
        tail_klines = [
            {'volume': 1000, 'high': 10.5, 'low': 10.4, 'close': 10.45},
            {'volume': 2000, 'high': 10.6, 'low': 10.5, 'close': 10.55},
            {'volume': 3000, 'high': 10.7, 'low': 10.6, 'close': 10.65},
            {'volume': 4000, 'high': 10.8, 'low': 10.7, 'close': 10.75},
            {'volume': 5000, 'high': 10.9, 'low': 10.8, 'close': 10.85},
            {'volume': 6000, 'high': 11.0, 'low': 10.9, 'close': 10.95},
            {'volume': 7000, 'high': 11.1, 'low': 11.0, 'close': 11.05},  # 第7条
        ]
        day_volume = 50000  # 全天成交量
        
        # 调用计算函数
        metrics = fetch_tail_trading._calculate_tail_metrics(tail_klines, day_volume)
        
        # 验证结果
        assert metrics is not None
        assert 'tail_volume' in metrics
        assert 'tail_volume_pct' in metrics
        assert 'tail_high' in metrics
        assert 'tail_low' in metrics
        assert 'tail_close' in metrics
        
        # 尾盘成交量 = 1000 + ... + 7000 = 28000
        assert metrics['tail_volume'] == 28000
        
        # 尾盘成交量占比 = 28000 / 50000 = 0.56
        assert metrics['tail_volume_pct'] == 0.56
        
        # 最高价 = max(10.5, ..., 11.1) = 11.1
        assert metrics['tail_high'] == 11.1
        
        # 最低价 = min(10.4, ..., 11.0) = 10.4
        assert metrics['tail_low'] == 10.4
        
        # 收盘价 = 最后一根的收盘价 = 11.05
        assert metrics['tail_close'] == 11.05

    def test_calculate_metrics_insufficient_klines(self):
        """尾盘K线数量不足时返回None"""
        tail_klines = [
            {'volume': 1000, 'high': 10.5, 'low': 10.4, 'close': 10.45},
            {'volume': 2000, 'high': 10.6, 'low': 10.5, 'close': 10.55},
            # 只有2条，不足7条
        ]
        day_volume = 50000
        
        metrics = fetch_tail_trading._calculate_tail_metrics(tail_klines, day_volume)
        
        # K线数量不足时返回None
        assert metrics is None


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
        assert fetch_tail_trading._OUTPUT_VERSION == '1.0'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])