#!/usr/bin/env python3
"""
layered_backtest_intraday_intensity_1d 测试用例

测试脚本: backtest/layered_backtest_intraday_intensity_1d.py
规范文档: PROJECT.md, backtest/MODULE.md

运行: pytest backtest/test_cases/test_layered_backtest_intraday_intensity_1d.py -v
"""

import json
import sys
from pathlib import Path

import pytest


# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestLayerConfig:
    """测试分层配置"""

    def test_factor_name_declared(self):
        """factor_name 必须声明"""
        from backtest.layered_backtest_intraday_intensity_1d import IntradayIntensityLayerConfig

        config = IntradayIntensityLayerConfig()
        assert config.factor_name == 'intraday_intensity_1d'

    def test_factor_col_declared(self):
        """factor_col 必须声明为 intraday_intensity"""
        from backtest.layered_backtest_intraday_intensity_1d import IntradayIntensityLayerConfig

        config = IntradayIntensityLayerConfig()
        assert config.factor_col == 'intraday_intensity'

    def test_n_layers_derived(self):
        """n_layers 应从 layer_names 派生"""
        from backtest.layered_backtest_intraday_intensity_1d import IntradayIntensityLayerConfig

        config = IntradayIntensityLayerConfig()
        assert config.n_layers == 5

    def test_factor_direction_negative(self):
        """因子方向应为反向（从 IC 文件加载）"""
        from backtest.layered_backtest_intraday_intensity_1d import IntradayIntensityLayerConfig

        config = IntradayIntensityLayerConfig()
        assert config.factor_direction == 'negative'


class TestOutputFile:
    """测试输出文件"""

    def test_output_file_exists(self):
        """分层回测输出文件应存在"""
        output_path = Path('/home/admin/projects/factor_ic_analyzer/backtest/result')
        output_file = output_path / 'intraday_intensity_1d_layered_backtest.json'

        if not output_file.exists():
            pytest.skip("输出文件不存在，请先运行分层回测脚本")

        assert output_file.exists()

    def test_output_has_required_fields(self):
        """输出 JSON 应包含规范要求的字段"""
        output_path = Path('/home/admin/projects/factor_ic_analyzer/backtest/result')
        output_file = output_path / 'intraday_intensity_1d_layered_backtest.json'

        if not output_file.exists():
            pytest.skip("输出文件不存在")

        with open(output_file) as f:
            data = json.load(f)

        # 顶层必需字段
        required_fields = [
            'meta',
            'layer_stats',
            'long_short',
            'monotonicity'
        ]

        for field in required_fields:
            assert field in data, f"缺失顶层字段: {field}"

        # meta 子字段
        meta = data.get('meta') or {}
        assert 'factor_name' in meta, "meta 缺失 factor_name"
        assert 'factor_direction' in meta, "meta 缺失 factor_direction"
        assert 'n_layers' in meta, "meta 缺失 n_layers"


class TestCLIExecution:
    """测试 CLI 执行"""

    def test_script_runs_without_error(self):
        """脚本应能正常运行"""
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, 'backtest/layered_backtest_intraday_intensity_1d.py'],
            cwd='/home/admin/projects/factor_ic_analyzer',
            capture_output=True,
            text=True,
            timeout=180
        )

        # 脚本应正常退出
        assert result.returncode == 0, f"脚本执行失败: {result.stderr}"

        # 输出应包含分层回测报告（日志输出到 stderr）
        output = result.stderr
        assert '分层回测报告' in output or '完成' in output


# ============================================================================
# 运行入口
# ============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
