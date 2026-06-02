#!/usr/bin/env python3
"""
尾盘价格位置因子分层回测测试用例

测试覆盖：
- 配置类属性验证
- 因子名称正确性
- 分层命名正确性
"""

import pytest
from pathlib import Path
import sys

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backtest.layered_backtest_tail_price_position_1d import TailPricePositionLayerConfig


class TestTailPricePositionLayerConfig:
    """分层配置类测试"""

    def test_factor_name(self):
        """因子名称正确"""
        assert TailPricePositionLayerConfig.factor_name == "tail_price_position"

    def test_layer_names_count(self):
        """分层数量为5"""
        assert len(TailPricePositionLayerConfig.layer_names) == 5

    def test_layer_names_values(self):
        """分层命名正确"""
        expected = ("lowest", "lower", "normal", "higher", "highest")
        assert TailPricePositionLayerConfig.layer_names == expected

    def test_layer_descriptions_count(self):
        """分层描述数量与分层数量一致"""
        assert len(TailPricePositionLayerConfig.layer_descriptions) == 5

    def test_layer_descriptions_content(self):
        """分层描述包含关键信息"""
        descriptions = TailPricePositionLayerConfig.layer_descriptions
        # 第一层应包含"底部"关键词
        assert "底部" in descriptions[0]
        # 第五层应包含"顶部"关键词
        assert "顶部" in descriptions[4]


class TestInheritedAttributes:
    """基类派生属性测试"""

    def test_n_layers_derived(self):
        """n_layers 由 layer_names 派生"""
        config = TailPricePositionLayerConfig()
        assert config.n_layers == 5

    def test_factor_direction_from_ic(self):
        """factor_direction 从 IC 文件派生"""
        config = TailPricePositionLayerConfig()
        # IC 文件显示 ic_mean = -0.0613，应为 negative
        assert config.factor_direction == "negative"

    def test_long_short_layers_derived(self):
        """long_layers/short_layers 由方向派生"""
        config = TailPricePositionLayerConfig()
        # negative 因子：做空高层，做多低层
        # 基类派生逻辑：long_layers=[1,2]，short_layers=[4,5]
        assert config.short_layers == [4, 5]
        assert config.long_layers == [1, 2]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])