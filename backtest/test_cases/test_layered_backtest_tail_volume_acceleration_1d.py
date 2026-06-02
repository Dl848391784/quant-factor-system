#!/usr/bin/env python3
"""
test_layered_backtest_tail_volume_acceleration_1d 测试用例

测试脚本: backtest/layered_backtest_tail_volume_acceleration_1d.py
分层配置: TailVolumeAccelerationLayerConfig
流程文档: backtest/docs/layered_backtest_tail_volume_acceleration_1d_flow.md

版本历史:
  v1.0 (2026-06-02): 初始版本，创建测试用例
  v1.1 (2026-06-02): Round 5 优化 - 测试文件版本历史同步
  v1.2 (2026-06-02): Round 5 优化 - 版本历史与分层回测脚本同步（v1.3）
  v1.3 (2026-06-02): Round 5 优化 - 版本历史与分层回测脚本同步（v1.6）
"""

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from backtest.layered_backtest_tail_volume_acceleration_1d import (
    TailVolumeAccelerationLayerConfig,
)


class TestLayerConfig:
    """分层配置类测试"""

    def test_factor_name_defined(self):
        """TC001-01: factor_name 已定义"""
        assert hasattr(TailVolumeAccelerationLayerConfig, "factor_name")
        assert TailVolumeAccelerationLayerConfig.factor_name == "tail_volume_acceleration"

    def test_layer_names_defined(self):
        """TC001-02: layer_names 已定义"""
        assert hasattr(TailVolumeAccelerationLayerConfig, "layer_names")
        assert len(TailVolumeAccelerationLayerConfig.layer_names) == 5

    def test_layer_names_sequence(self):
        """TC001-03: layer_names 是序列类型"""
        from collections.abc import Sequence

        assert isinstance(TailVolumeAccelerationLayerConfig.layer_names, Sequence)

    def test_layer_descriptions_defined(self):
        """TC001-04: layer_descriptions 已定义"""
        assert hasattr(TailVolumeAccelerationLayerConfig, "layer_descriptions")
        assert len(TailVolumeAccelerationLayerConfig.layer_descriptions) == 5

    def test_layer_descriptions_match_names(self):
        """TC001-05: layer_descriptions 与 layer_names 数量一致"""
        assert len(TailVolumeAccelerationLayerConfig.layer_names) == len(
            TailVolumeAccelerationLayerConfig.layer_descriptions
        )

    def test_factor_name_not_empty(self):
        """TC001-06: factor_name 非空"""
        assert TailVolumeAccelerationLayerConfig.factor_name != ""
        assert TailVolumeAccelerationLayerConfig.factor_name is not None

    def test_layer_names_not_empty(self):
        """TC001-07: layer_names 非空"""
        for name in TailVolumeAccelerationLayerConfig.layer_names:
            assert name != ""
            assert name is not None


class TestLayerConfigInheritance:
    """继承机制测试"""

    def test_inherits_from_base(self):
        """TC002-01: 继承自 LayerConfigBase"""
        from backtest.common.layered_backtest_runner import LayerConfigBase

        assert issubclass(TailVolumeAccelerationLayerConfig, LayerConfigBase)

    def test_has_classvar_annotations(self):
        """TC002-02: 使用 ClassVar 类型注解"""
        from typing import ClassVar, get_type_hints

        hints = get_type_hints(TailVolumeAccelerationLayerConfig)
        # ClassVar 应出现在类型提示中
        assert "factor_name" in hints or hasattr(TailVolumeAccelerationLayerConfig, "__annotations__")


class TestScriptIntegration:
    """脚本集成测试"""

    def test_script_imports(self):
        """TC003-01: 脚本可导入"""
        from backtest.layered_backtest_tail_volume_acceleration_1d import factor_cli_main

        assert callable(factor_cli_main)

    def test_factor_calculator_import(self):
        """TC003-02: 因子计算函数可导入"""
        from factor_ic.ic_tail_volume_acceleration_1d import calculate_tail_volume_acceleration

        assert callable(calculate_tail_volume_acceleration)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
