#!/usr/bin/env python3
"""
ic_intraday_intensity_1d 测试用例

测试脚本: factor_ic/ic_intraday_intensity_1d.py
流程文档: factor_ic/docs/ic_intraday_intensity_1d_flow.md
规范文档: PROJECT.md, factor_ic/MODULE.md

运行: pytest factor_ic/test_cases/ic_intraday_intensity_1d_test_cases.py -v
"""

import pytest
import sys
import json
import numpy as np
import pandas as pd
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from factor_ic.common.data_completeness import (
    get_ic_output_path,
    FACTOR_IC_RESULT_DIR
)


class TestOutputPath:
    """测试输出路径和命名规范"""
    
    def test_output_path_format(self):
        """输出文件命名应符合规范: ic_<因子名>_analysis_result.json"""
        path = get_ic_output_path('intraday_intensity_1d')
        assert path.name == 'ic_intraday_intensity_1d_analysis_result.json'
    
    def test_output_directory(self):
        """输出目录应为 factor_ic/result/"""
        path = get_ic_output_path('intraday_intensity_1d')
        assert path.parent == FACTOR_IC_RESULT_DIR


class TestOutputStructure:
    """测试输出数据结构规范"""
    
    REQUIRED_FIELDS = [
        'factor_name',
        'calculation_date',
        'period',
        'ic_metrics',
        'sample_stats',
        'statistical_significance',
        'factor_direction',
        'economic_significance',
        'icir_stability',
        'ic_distribution_consistency'
    ]
    
    def test_output_has_required_fields(self):
        """输出 JSON 应包含规范要求的字段"""
        output_path = get_ic_output_path('intraday_intensity_1d')
        
        if not output_path.exists():
            pytest.skip("输出文件不存在，请先运行 ic_intraday_intensity_1d.py")
        
        with open(output_path) as f:
            data = json.load(f)
        
        for field in self.REQUIRED_FIELDS:
            assert field in data, f"缺失字段: {field}"
    
    def test_ic_metrics_fields(self):
        """ic_metrics 应包含 ic_mean, ic_std, icir"""
        output_path = get_ic_output_path('intraday_intensity_1d')
        
        if not output_path.exists():
            pytest.skip("输出文件不存在")
        
        with open(output_path) as f:
            data = json.load(f)
        
        ic_metrics = data.get('ic_metrics') or {}
        required = ['ic_mean', 'ic_std', 'icir']
        
        for field in required:
            assert field in ic_metrics, f"ic_metrics 缺失字段: {field}"
    
    def test_factor_direction_negative(self):
        """日内强度因子应为反向因子（ic_mean < 0）"""
        output_path = get_ic_output_path('intraday_intensity_1d')
        
        if not output_path.exists():
            pytest.skip("输出文件不存在")
        
        with open(output_path) as f:
            data = json.load(f)
        
        factor_direction = data.get('factor_direction') or {}
        ic_mean_sign = factor_direction.get('ic_mean_sign')
        
        # 实测结果 ic_mean = -0.0218
        assert ic_mean_sign == 'negative', "日内强度因子应为反向因子"


class TestFactorCalculation:
    """测试因子计算函数"""
    
    def test_calculate_intraday_intensity_basic(self):
        """测试基本计算：阳线日内强度应为正值"""
        # 导入因子计算函数
        from factor_ic.ic_intraday_intensity_1d import calculate_intraday_intensity
        
        # 测试数据：阳线（收 > 开）
        df = pd.DataFrame({
            'date': ['2026-01-01'],
            'asset': ['000001'],
            'open': [10.0],
            'close': [10.5],  # 收盘 > 开盘
            'high': [11.0],
            'low': [9.5]
        })
        
        result = calculate_intraday_intensity(df, skip_validation=True)
        
        # (10.5 - 10.0) / (11.0 - 9.5) = 0.5 / 1.5 = 0.333
        expected = (10.5 - 10.0) / (11.0 - 9.5)
        actual = result['intraday_intensity'].iloc[0]
        
        assert np.isclose(actual, expected, rtol=1e-4)
        assert actual > 0, "阳线日内强度应为正值"
    
    def test_calculate_intraday_intensity_negative(self):
        """测试阴线计算：阴线日内强度应为负值"""
        from factor_ic.ic_intraday_intensity_1d import calculate_intraday_intensity
        
        # 测试数据：阴线（收 < 开）
        df = pd.DataFrame({
            'date': ['2026-01-01'],
            'asset': ['000001'],
            'open': [10.0],
            'close': [9.5],  # 收盘 < 开盘
            'high': [11.0],
            'low': [9.0]
        })
        
        result = calculate_intraday_intensity(df, skip_validation=True)
        
        # (9.5 - 10.0) / (11.0 - 9.0) = -0.5 / 2.0 = -0.25
        expected = (9.5 - 10.0) / (11.0 - 9.0)
        actual = result['intraday_intensity'].iloc[0]
        
        assert np.isclose(actual, expected, rtol=1e-4)
        assert actual < 0, "阴线日内强度应为负值"
    
    def test_calculate_intraday_intensity_zero_amplitude(self):
        """测试振幅为零：High=Low 时应设为 NaN"""
        from factor_ic.ic_intraday_intensity_1d import calculate_intraday_intensity
        
        # 测试数据：振幅为零（涨跌停）
        df = pd.DataFrame({
            'date': ['2026-01-01'],
            'asset': ['000001'],
            'open': [10.0],
            'close': [10.0],
            'high': [10.0],  # High = Low
            'low': [10.0]
        })
        
        result = calculate_intraday_intensity(df, skip_validation=True)
        
        assert pd.isna(result['intraday_intensity'].iloc[0]), "振幅为零时应设为 NaN"
    
    def test_calculate_intraday_intensity_doji(self):
        """测试十字星：开=收时日内强度应为 0"""
        from factor_ic.ic_intraday_intensity_1d import calculate_intraday_intensity
        
        # 测试数据：十字星（开 = 收）
        df = pd.DataFrame({
            'date': ['2026-01-01'],
            'asset': ['000001'],
            'open': [10.0],
            'close': [10.0],  # 开盘 = 收盘
            'high': [11.0],
            'low': [9.0]
        })
        
        result = calculate_intraday_intensity(df, skip_validation=True)
        
        # (10.0 - 10.0) / (11.0 - 9.0) = 0 / 2.0 = 0
        assert result['intraday_intensity'].iloc[0] == 0, "十字星日内强度应为 0"
    
    def test_missing_columns_raises_error(self):
        """测试缺失列时抛出 ValueError"""
        from factor_ic.ic_intraday_intensity_1d import calculate_intraday_intensity
        
        # 缺失 high 列
        df = pd.DataFrame({
            'date': ['2026-01-01'] * 150,  # 需要 ≥100 行才能触发数据量校验
            'asset': ['000001'] * 150,
            'open': [10.0] * 150,
            'close': [10.5] * 150,
            'low': [9.5] * 150
            # 缺失 high
        })
        
        with pytest.raises(ValueError, match="缺失必需列"):
            calculate_intraday_intensity(df)
    
    def test_insufficient_data_raises_error(self):
        """测试数据量不足时抛出 ValueError"""
        from factor_ic.ic_intraday_intensity_1d import calculate_intraday_intensity
        
        # 只有 50 行数据
        df = pd.DataFrame({
            'date': ['2026-01-01'] * 50,
            'asset': ['000001'] * 50,
            'open': [10.0] * 50,
            'close': [10.5] * 50,
            'high': [11.0] * 50,
            'low': [9.5] * 50
        })
        
        with pytest.raises(ValueError, match="有效数据量不足"):
            calculate_intraday_intensity(df)


class TestCLIExecution:
    """测试 CLI 执行"""
    
    def test_script_runs_without_error(self):
        """脚本应能正常运行"""
        import subprocess
        
        result = subprocess.run(
            ['python', 'factor_ic/ic_intraday_intensity_1d.py'],
            cwd='/home/admin/projects/factor_ic_analyzer',
            capture_output=True,
            text=True
        )
        
        # 脚本应正常退出
        assert result.returncode == 0, f"脚本执行失败: {result.stderr}"
        
        # 输出应包含结果摘要（日志输出到 stderr）
        output = result.stderr
        assert '结果摘要' in output or '完成' in output


# ============================================================================
# 运行入口
# ============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v'])