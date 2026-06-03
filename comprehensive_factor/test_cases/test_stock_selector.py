"""
股票选股脚本测试

测试用例：
1. 配置校验
2. 权重配置加载
3. 滚动ICIR选股
4. 排序规则（正向/反向）
5. Top N选股数量
6. 输出结构完整性
7. 边界情况处理

作者: 云瑶
创建日期: 2026-06-03
"""

import json
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
import pytest


# sys.path 处理
PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
import sys  # noqa: E402


if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from comprehensive_factor.stock_selector import (  # noqa: E402
    StockSelectorConfig,
    build_result,
    get_latest_date,
    load_weight_config,
    select_stocks,
    sort_and_select,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def valid_config():
    """有效配置 fixture"""
    return StockSelectorConfig(
        top_n=10,
        selection_date="2026-06-01",
        factor_direction="negative",
    )


@pytest.fixture
def mock_weight_config():
    """权重配置 fixture"""
    return {
        "best_selection": {
            "method": "rolling_icir_weight",
            "composite_score": 0.8137,
        },
        "ranking": [],
    }


@pytest.fixture
def mock_factor_df():
    """因子 DataFrame fixture"""
    return pd.DataFrame(
        {
            "date": ["2026-06-01"] * 10,
            "asset": [
                "000001",
                "000002",
                "000003",
                "000004",
                "000005",
                "000006",
                "000007",
                "000008",
                "000009",
                "000010",
            ],
            "rsi_6": [50, 60, 70, 80, 90, 10, 20, 30, 40, 55],
            "volume_ratio_5": [1.0, 1.5, 2.0, 0.5, 0.8, 0.2, 0.3, 0.4, 0.6, 1.2],
            "rsi_6_std": [0.0, 0.5, 1.0, 1.5, 2.0, -2.0, -1.5, -1.0, -0.5, 0.25],
            "volume_ratio_5_std": [0.0, 0.3, 0.6, -0.4, -0.2, -1.0, -0.8, -0.6, -0.1, 0.15],
        }
    )


@pytest.fixture
def mock_composite_factor(mock_factor_df):
    """综合因子 Series fixture"""
    # 反向因子：低值预期高收益
    # RSI_6_std 越低越好，volume_ratio_5_std 越低越好
    return mock_factor_df["rsi_6_std"] * 0.5 + mock_factor_df["volume_ratio_5_std"] * 0.5


# ============================================================================
# 配置校验测试
# ============================================================================


class TestConfigValidation:
    """配置校验测试"""

    def test_valid_config(self, valid_config):
        """测试有效配置"""
        valid_config.validate()
        assert valid_config.top_n == 10
        assert valid_config.factor_direction == "negative"

    def test_empty_factor_list(self):
        """测试空因子列表"""
        config = StockSelectorConfig(factor_list=[], factor_cols=[])
        with pytest.raises(ValueError, match="factor_list 不能为空"):
            config.validate()

    def test_top_n_zero(self):
        """测试 top_n 为 0"""
        config = StockSelectorConfig(top_n=0)
        with pytest.raises(ValueError, match="top_n 必须大于 0"):
            config.validate()

    def test_invalid_factor_direction(self):
        """测试无效因子方向"""
        config = StockSelectorConfig(factor_direction="invalid")
        with pytest.raises(ValueError, match="factor_direction 必须为"):
            config.validate()


# ============================================================================
# 权重配置加载测试
# ============================================================================


class TestLoadWeightConfig:
    """权重配置加载测试"""

    def test_load_valid_config(self, tmp_path, mock_weight_config):
        """测试加载有效配置"""
        # 创建临时文件
        config_file = tmp_path / "weight_selection_result.json"
        with open(config_file, "w") as f:
            json.dump(mock_weight_config, f)

        # 加载
        result = load_weight_config(config_file)
        assert result["best_selection"]["method"] == "rolling_icir_weight"

    def test_missing_file(self, tmp_path):
        """测试缺失文件"""
        config_file = tmp_path / "nonexistent.json"
        with pytest.raises(FileNotFoundError, match="权重选择结果文件不存在"):
            load_weight_config(config_file)

    def test_missing_best_selection(self, tmp_path):
        """测试缺失 best_selection 字段"""
        config_file = tmp_path / "weight_selection_result.json"
        with open(config_file, "w") as f:
            json.dump({"ranking": []}, f)

        with pytest.raises(ValueError, match="缺失必需字段 'best_selection'"):
            load_weight_config(config_file)


# ============================================================================
# 排序选股测试
# ============================================================================


class TestSortAndSelect:
    """排序选股测试"""

    def test_negative_direction_ascending(self, mock_factor_df, mock_composite_factor):
        """测试反向因子升序排序"""
        result = sort_and_select(
            mock_composite_factor,
            mock_factor_df,
            top_n=3,
            factor_direction="negative",
        )

        # 反向因子：升序（值越小越好）
        assert len(result) == 3
        assert result[0]["code"] == "000006"  # 综合因子值最小
        assert result[0]["composite_value"] == pytest.approx(-1.5, abs=0.1)

    def test_positive_direction_descending(self, mock_factor_df, mock_composite_factor):
        """测试正向因子降序排序"""
        # 正向因子：降序（值越大越好）
        result = sort_and_select(
            mock_composite_factor,
            mock_factor_df,
            top_n=3,
            factor_direction="positive",
        )

        assert len(result) == 3
        assert result[0]["code"] == "000005"  # 综合因子值最大

    def test_top_n_larger_than_total(self, mock_factor_df, mock_composite_factor):
        """测试 Top N 大于总股票数"""
        result = sort_and_select(
            mock_composite_factor,
            mock_factor_df,
            top_n=100,  # 大于实际数量 10
            factor_direction="negative",
        )

        assert len(result) == 10  # 返回所有有效股票

    def test_nan_values_excluded(self, mock_factor_df):
        """测试 NaN 值排除"""
        # 添加 NaN 值
        composite_with_nan = pd.Series([0.0, 0.5, np.nan, 1.0, np.nan, -1.0, -0.5, np.nan, 0.25, np.nan])

        result = sort_and_select(
            composite_with_nan,
            mock_factor_df,
            top_n=3,
            factor_direction="negative",
        )

        # NaN 排除后只剩 6 个有效值
        assert len(result) == 3
        # 第一个应该是最小值 -1.0（对应 000006）
        assert result[0]["code"] == "000006"

    def test_factor_values_included(self, mock_factor_df, mock_composite_factor):
        """测试因子值包含在结果中"""
        result = sort_and_select(
            mock_composite_factor,
            mock_factor_df,
            top_n=1,
            factor_direction="negative",
        )

        assert "factor_values" in result[0]
        assert "rsi_6" in result[0]["factor_values"]
        assert "volume_ratio_5" in result[0]["factor_values"]


# ============================================================================
# 获取最新日期测试
# ============================================================================


class TestGetLatestDate:
    """获取最新日期测试"""

    def test_get_latest_date(self, mock_factor_df):
        """测试获取最新日期"""
        latest = get_latest_date(mock_factor_df)
        assert latest == "2026-06-01"

    def test_empty_df(self):
        """测试空 DataFrame"""
        empty_df = pd.DataFrame()
        with pytest.raises(ValueError, match="factor_df 为空"):
            get_latest_date(empty_df)

    def test_missing_date_column(self):
        """测试缺失 date 列"""
        df = pd.DataFrame({"asset": ["000001"], "value": [1.0]})
        with pytest.raises(ValueError, match="缺少 'date' 列"):
            get_latest_date(df)


# ============================================================================
# 结果构建测试
# ============================================================================


class TestBuildResult:
    """结果构建测试"""

    def test_build_result_structure(self, mock_weight_config, valid_config):
        """测试结果结构完整性"""
        top_stocks = [{"rank": 1, "code": "000001", "composite_value": -1.5, "factor_values": {}}]

        result = build_result(
            top_stocks,
            valid_config,
            mock_weight_config,
            total_stocks=100,
        )

        # 检查 meta 字段
        assert "meta" in result
        assert result["meta"]["selection_date"] == "2026-06-01"
        assert result["meta"]["weight_method"] == "rolling_icir_weight"
        assert result["meta"]["composite_score"] == 0.8137
        assert result["meta"]["top_n"] == 10

        # 检查 top_stocks 字段
        assert "top_stocks" in result
        assert len(result["top_stocks"]) == 1

        # 检查 weight_config 字段
        assert "weight_config" in result


# ============================================================================
# 边界情况测试
# ============================================================================


class TestEdgeCases:
    """边界情况测试"""

    def test_all_nan_composite(self, mock_factor_df):
        """测试全 NaN 综合因子"""
        all_nan = pd.Series([np.nan] * 10)

        with pytest.raises(ValueError, match="综合因子值全部为 NaN"):
            sort_and_select(all_nan, mock_factor_df, top_n=3, factor_direction="negative")


# ============================================================================
# 集成测试
# ============================================================================


class TestIntegration:
    """集成测试（需要实际数据）"""

    @pytest.mark.skipif(
        not Path("/home/admin/projects/factor_ic_analyzer/data_fetchers/result/factor_ic_data.json.gz").exists(),
        reason="数据源文件不存在",
    )
    def test_full_workflow(self):
        """测试完整流程"""
        config = StockSelectorConfig(top_n=3, selection_date="2026-06-01")

        try:
            result, output_file = select_stocks(config)

            # 验证结果
            assert "meta" in result
            assert "top_stocks" in result
            assert len(result["top_stocks"]) == 3
            assert output_file.exists()

        except FileNotFoundError as e:
            pytest.skip(f"数据文件缺失: {e}")
