#!/usr/bin/env python3
"""
merge_factors.py 测试用例

测试内容：
1. setup_logger 初始化测试
2. load_main_data 输入验证测试
3. load_parquet_factor 输入验证测试
4. merge_factors 边界处理测试
5. 数据完整性验证测试

运行方式：
    pytest summary/test_cases/test_merge_factors.py -v
"""

import logging
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pandas as pd
import pytest

# 导入被测试模块
# R-fix (2026-07-19): NEW_FACTORS 已重命名为 DEFAULT_FACTORS (merge_factors v1.4), 同步接口漂移
from summary.merge_factors import (
    DEFAULT_FACTORS,
    __version__,
    load_main_data,
    load_parquet_factor,
    merge_factors,
    setup_logger,
)


# 向后兼容别名: 模块 NEW_FACTORS → DEFAULT_FACTORS (本测试文件内统一用别名, 最小改动)
NEW_FACTORS = DEFAULT_FACTORS


class TestSetupLogger:
    """setup_logger 函数测试"""

    def test_logger_initialization(self):
        """测试日志记录器初始化"""
        logger = setup_logger("test_merge_factors")
        assert logger is not None
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test_merge_factors"

    def test_logger_has_handlers(self):
        """测试日志处理器配置"""
        logger = setup_logger("test_merge_factors_2")
        assert len(logger.handlers) > 0
        # 应有文件处理器和控制台处理器
        handler_types = [type(h).__name__ for h in logger.handlers]
        assert "FileHandler" in handler_types or "StreamHandler" in handler_types

    def test_logger_level(self):
        """测试日志级别配置"""
        logger = setup_logger("test_merge_factors_3")
        assert logger.level == logging.DEBUG


class TestLoadMainData:
    """load_main_data 函数测试"""

    def test_load_main_data_file_not_exists(self):
        """测试主数据源文件不存在"""
        logger = Mock()
        result = load_main_data(logger)
        # 文件不存在时应返回 None 或抛出异常（取决于实现）
        assert result is None or isinstance(result, pd.DataFrame)
        # 应记录警告日志
        if result is None:
            logger.warning.assert_called()

    def test_load_main_data_success(self, tmp_path):
        """测试主数据源加载成功

        R-fix (2026-07-19): 弃用失效的 mock_project_root.__truediv__ + mock gzip/json,
        改为 tmp_path 下造真实 gzip JSON 文件 — load_main_data 读
        PROJECT_ROOT/DATA_PATHS['factor_data']/factor_data.json.gz, 用真文件端到端最可靠.
        """
        import gzip
        import json

        from summary.merge_factors import DATA_PATHS

        data_dir = tmp_path / DATA_PATHS["factor_data"]
        data_dir.mkdir(parents=True, exist_ok=True)
        payload = {"data": [{"date": "2024-01-01", "asset": "000001", "close": 10.0}]}
        with gzip.open(data_dir / "factor_data.json.gz", "wt", encoding="utf-8") as f:
            json.dump(payload, f)

        logger = Mock()
        with patch("summary.merge_factors.PROJECT_ROOT", tmp_path):
            result = load_main_data(logger)

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 1
        assert result.iloc[0]["asset"] == "000001"


class TestLoadParquetFactor:
    """load_parquet_factor 函数测试"""

    def test_load_parquet_factor_file_not_exists(self):
        """测试因子文件不存在"""
        logger = Mock()
        result = load_parquet_factor("nonexistent_factor", logger)
        assert result is None
        logger.warning.assert_called()

    def test_load_parquet_factor_success(self, tmp_path):
        """测试因子文件加载成功

        R-fix (2026-07-19): 弃用失效 mock, tmp_path 造真实 parquet —
        load_parquet_factor 读 PROJECT_ROOT/DATA_PATHS['factors']/<name>.parquet.
        """
        from summary.merge_factors import DATA_PATHS

        factors_dir = tmp_path / DATA_PATHS["factors"]
        factors_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"date": ["2024-01-01"], "asset": ["000001"], "factor_value": [0.5]}).to_parquet(
            factors_dir / "test_factor.parquet"
        )

        logger = Mock()
        with patch("summary.merge_factors.PROJECT_ROOT", tmp_path):
            result = load_parquet_factor("test_factor", logger)

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 1

    def test_load_parquet_factor_exception(self, tmp_path):
        """测试因子文件加载异常 (损坏的 parquet → 返回 None + error 日志)"""
        from summary.merge_factors import DATA_PATHS

        factors_dir = tmp_path / DATA_PATHS["factors"]
        factors_dir.mkdir(parents=True, exist_ok=True)
        # 写一个非 parquet 内容 → pd.read_parquet 抛异常
        (factors_dir / "test_factor.parquet").write_bytes(b"not a parquet")

        logger = Mock()
        with patch("summary.merge_factors.PROJECT_ROOT", tmp_path):
            result = load_parquet_factor("test_factor", logger)

        assert result is None
        logger.error.assert_called()


class TestMergeFactors:
    """merge_factors 函数测试"""

    @patch("summary.merge_factors.load_main_data")
    def test_merge_factors_main_data_none(self, mock_load_main):
        """测试主数据加载失败"""
        mock_load_main.return_value = None
        logger = Mock()
        result = merge_factors(logger)
        assert result is None
        logger.error.assert_called()

    @patch("summary.merge_factors.load_main_data")
    @patch("summary.merge_factors.load_parquet_factor")
    def test_merge_factors_no_factors_loaded(self, mock_load_factor, mock_load_main):
        """测试没有因子加载成功"""
        mock_load_main.return_value = pd.DataFrame({"date": ["2024-01-01"], "asset": ["000001"]})
        mock_load_factor.return_value = None

        logger = Mock()
        result = merge_factors(logger)

        # 应返回原始主数据
        assert isinstance(result, pd.DataFrame)

    @patch("summary.merge_factors.load_main_data")
    @patch("summary.merge_factors.load_parquet_factor")
    def test_merge_factors_success(self, mock_load_factor, mock_load_main, tmp_path):
        """测试合并成功

        R-fix (2026-07-19): 弃用 patch PROJECT_ROOT + 失效 __truediv__,
        改用 merge_factors 的 output_dir 参数传 tmp_path (生产代码 L452 支持),
        避免对 PROJECT_ROOT 的魔术方法 mock. 最小且可靠.
        """
        # 设置主数据
        mock_load_main.return_value = pd.DataFrame(
            {"date": ["2024-01-01", "2024-01-02"], "asset": ["000001", "000002"], "existing_factor": [0.1, 0.2]}
        )

        # 设置因子数据
        mock_load_factor.return_value = pd.DataFrame(
            {"date": ["2024-01-01", "2024-01-02"], "asset": ["000001", "000002"], "factor_value": [0.5, 0.6]}
        )

        logger = Mock()

        # 只测试一个因子 (patch 生产代码实际读取的 DEFAULT_FACTORS)
        with patch("summary.merge_factors.DEFAULT_FACTORS", ["test_factor"]):
            result = merge_factors(logger, output_dir=tmp_path)

        assert isinstance(result, pd.DataFrame)


class TestConstants:
    """常量测试"""

    def test_version_defined(self):
        """测试版本常量定义 (R-fix 2026-07-19: 模块已升级到 1.4, 同步断言)"""
        assert __version__ == "1.4"

    def test_new_factors_not_empty(self):
        """测试新因子列表非空"""
        assert len(NEW_FACTORS) > 0
        assert isinstance(NEW_FACTORS, list)

    def test_new_factors_format(self):
        """测试新因子名称格式"""
        for factor in NEW_FACTORS:
            assert isinstance(factor, str)
            assert len(factor) > 0


class TestDataIntegrity:
    """数据完整性验证测试"""

    def test_merge_preserves_main_data_columns(self):
        """测试合并保留主数据列"""
        main_df = pd.DataFrame({"date": ["2024-01-01"], "asset": ["000001"], "existing_col": [1.0]})

        factor_df = pd.DataFrame({"date": ["2024-01-01"], "asset": ["000001"], "factor_value": [0.5]})

        # 重命名并合并
        factor_df_renamed = factor_df[["date", "asset", "factor_value"]].copy()
        factor_df_renamed.columns = ["date", "asset", "new_factor"]

        merged = main_df.merge(factor_df_renamed, on=["date", "asset"], how="left")

        # 检查保留原有列
        assert "existing_col" in merged.columns
        assert "new_factor" in merged.columns

    def test_merge_handles_missing_data(self):
        """测试合并处理缺失数据"""
        main_df = pd.DataFrame(
            {
                "date": ["2024-01-01", "2024-01-02"],
                "asset": ["000001", "000002"],
            }
        )

        factor_df = pd.DataFrame(
            {
                "date": ["2024-01-01"],  # 只有第一天数据
                "asset": ["000001"],
                "factor_value": [0.5],
            }
        )

        factor_df_renamed = factor_df.copy()
        factor_df_renamed.columns = ["date", "asset", "new_factor"]

        merged = main_df.merge(factor_df_renamed, on=["date", "asset"], how="left")

        # 检查缺失值处理
        assert merged["new_factor"].isna().sum() == 1  # 第二天应为 NaN


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
