"""
股票选股脚本测试

测试用例:
1. 配置校验
2. 权重配置加载
3. 排序规则（正向/反向）
4. Top N 选股数量
5. 输出结构完整性
6. 边界情况处理

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
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.resolve()
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


@pytest.fixture
def mock_top_stocks():
    """Top 股票列表 fixture（v1.15: 修复 TestBuildResult 缺失 fixture）"""
    return [
        {
            "rank": 1,
            "code": "000006",
            "composite_value": -1.5,
            "factor_values": {"rsi": 10, "volume_ratio": 0.2},
            "factor_values_std": {"rsi": -2.0, "volume_ratio": -1.0},
            "weight_coverage": 1.0,
        }
    ]


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
        config_file = tmp_path / "weight_selection_result.json"
        with open(config_file, "w") as f:
            json.dump(mock_weight_config, f)

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
        result, excluded_amp, _, _ = sort_and_select(
            mock_composite_factor,
            mock_factor_df,
            top_n=3,
            factor_direction="negative",
            factor_cols=["rsi_6", "volume_ratio_5"],
        )

        # 反向因子：升序（值越小越好）
        assert len(result) == 3
        assert result[0]["code"] == "000006"  # 综合因子值最小
        assert result[0]["composite_value"] == pytest.approx(-1.5, abs=0.1)
        # 没有振幅列，excluded_amp 应为 0
        assert excluded_amp == 0

    def test_positive_direction_descending(self, mock_factor_df, mock_composite_factor):
        """测试正向因子降序排序"""
        # 正向因子：降序（值越大越好）
        result, excluded_amp, _, _ = sort_and_select(
            mock_composite_factor,
            mock_factor_df,
            top_n=3,
            factor_direction="positive",
            factor_cols=["rsi_6", "volume_ratio_5"],
        )

        assert len(result) == 3
        assert result[0]["code"] == "000005"  # 综合因子值最大

    def test_top_n_larger_than_total(self, mock_factor_df, mock_composite_factor):
        """测试 Top N 大于总股票数"""
        result, excluded_amp, _, _ = sort_and_select(
            mock_composite_factor,
            mock_factor_df,
            top_n=100,  # 大于实际数量 10
            factor_direction="negative",
            factor_cols=["rsi_6", "volume_ratio_5"],
        )

        assert len(result) == 10  # 返回所有有效股票

    def test_nan_values_excluded(self, mock_factor_df):
        """测试 NaN 值排除"""
        # 添加 NaN 值
        composite_with_nan = pd.Series([0.0, 0.5, np.nan, 1.0, np.nan, -1.0, -0.5, np.nan, 0.25, np.nan])

        result, excluded_amp, _, _ = sort_and_select(
            composite_with_nan,
            mock_factor_df,
            top_n=3,
            factor_direction="negative",
            factor_cols=["rsi_6", "volume_ratio_5"],
        )

        # NaN 排除后只剩 6 个有效值
        assert len(result) == 3
        # 第一个应该是最小值 -1.0（对应 000006）
        assert result[0]["code"] == "000006"

    def test_factor_values_included(self, mock_factor_df, mock_composite_factor):
        """测试因子值包含在结果中"""
        result, excluded_amp, _, _ = sort_and_select(
            mock_composite_factor,
            mock_factor_df,
            top_n=1,
            factor_direction="negative",
            factor_cols=["rsi_6", "volume_ratio_5"],
        )

        assert "factor_values" in result[0]
        assert "rsi" in result[0]["factor_values"]
        assert "volume_ratio" in result[0]["factor_values"]

    def test_amplitude_filter_removed(self, mock_factor_df):
        """测试振幅过滤已移除（v1.17: is_untradeable 在 load_full_data 阶段过滤）。

        sort_and_select 不再做 amplitude 过滤，excluded_by_amplitude 恒为 0。
        不可交易股票（涨停类）由 load_full_data → factor_loader 层过滤。
        """
        df_with_amplitude = mock_factor_df.copy()
        df_with_amplitude["amplitude"] = [0.005, 0.008, 0.03, 0.05, 0.02, 0.015, 0.04, 0.001, 0.06, 0.09]

        composite = pd.Series([-2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0, 2.5])

        result, excluded_amp, _, _ = sort_and_select(
            composite,
            df_with_amplitude,
            top_n=5,
            factor_direction="negative",
            factor_cols=["rsi_6", "volume_ratio_5"],
            min_amplitude=0.01,
        )

        # amplitude 过滤已移至 load_full_data 层，sort_and_select 不再排除
        assert excluded_amp == 0
        assert len(result) == 5


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

    def test_build_result_structure(self, mock_top_stocks, valid_config, mock_weight_config):
        """测试结果结构完整性"""
        result = build_result(
            mock_top_stocks,
            valid_config,
            mock_weight_config,
            stocks_on_date=10,
            factor_list=["rsi", "volume_ratio"],
            factor_cols=["rssi_6", "volume_ratio_5"],
            selection_date="2026-06-01",
            excluded_by_amplitude=3,  # v1.12: 振幅过滤排除数
            excluded_by_coverage=2,  # v1.15: 覆盖率过滤排除数
            min_weight_coverage=0.5,  # v1.15: 覆盖率阈值
        )

        # 检查 meta 字段
        assert "meta" in result
        assert result["meta"]["selection_date"] == "2026-06-01"
        assert result["meta"]["weight_method"] == "rolling_icir_weight"
        assert result["meta"]["composite_score"] == 0.8137
        assert result["meta"]["top_n"] == 10
        # v1.12: 振幅过滤信息
        assert result["meta"]["min_amplitude"] == 0.01
        assert result["meta"]["excluded_by_amplitude"] == 3
        # v1.15: 覆盖率过滤信息
        assert result["meta"]["excluded_by_coverage"] == 2
        assert result["meta"]["min_weight_coverage"] == 0.5

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
            sort_and_select(
                all_nan, mock_factor_df, top_n=3, factor_direction="negative", factor_cols=["rsi_6", "volume_ratio_5"]
            )

    def test_amplitude_zero_threshold(self, mock_factor_df, mock_composite_factor):
        """测试振幅阈值=0时不排除任何股票"""
        df_with_amplitude = mock_factor_df.copy()
        df_with_amplitude["amplitude"] = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

        result, excluded_amp, _, _ = sort_and_select(
            mock_composite_factor,
            df_with_amplitude,
            top_n=3,
            factor_direction="negative",
            factor_cols=["rsi_6", "volume_ratio_5"],
            min_amplitude=0,  # 阈值=0，不排除
        )

        assert excluded_amp == 0
        assert len(result) == 3


# ============================================================================
# 覆盖率计算测试 (v1.13)
# ============================================================================


class TestWeightCoverage:
    """权重覆盖率计算测试（v1.13: 修复因子名/列名不匹配导致覆盖率恒定）"""

    def test_coverage_varies_by_missing_factors(self, mock_factor_df, mock_composite_factor):
        """缺失因子的股票覆盖率应低于完整股票"""
        # v1.14: 覆盖率基于 _std 列判断（综合因子用 std 计算，std=NaN 则该因子不贡献）
        df = mock_factor_df.copy()
        df.loc[0, "rsi_6_std"] = np.nan  # 000001 缺失 rsi_6 标准化值

        # 权重键 = 列名（v1.13 修复后的正确格式）
        weights = {"rsi_6": 0.6, "volume_ratio_5": 0.4}

        result, _, _, _ = sort_and_select(
            mock_composite_factor,
            df,
            top_n=10,
            factor_direction="negative",
            factor_cols=["rsi_6", "volume_ratio_5"],
            weights=weights,
            min_weight_coverage=0,  # 禁用过滤，测试覆盖率计算本身
        )

        # 找到 000001（index=0，缺失 rsi_6）
        stock_000001 = next(s for s in result if s["code"] == "000001")
        # 找到 000002（index=1，无缺失）
        stock_000002 = next(s for s in result if s["code"] == "000002")

        # 000001 缺失 rsi_6(权重0.6) → coverage = 0.4/1.0 = 0.4
        assert stock_000001["weight_coverage"] == pytest.approx(0.4, abs=0.01)
        # 000002 无缺失 → coverage = 1.0
        assert stock_000002["weight_coverage"] == pytest.approx(1.0, abs=0.01)

    def test_coverage_all_present(self, mock_factor_df, mock_composite_factor):
        """所有因子都有值时覆盖率为 1.0"""
        weights = {"rsi_6": 0.5, "volume_ratio_5": 0.5}

        result, _, _, _ = sort_and_select(
            mock_composite_factor,
            mock_factor_df,
            top_n=3,
            factor_direction="negative",
            factor_cols=["rsi_6", "volume_ratio_5"],
            weights=weights,
        )

        for stock in result:
            assert stock["weight_coverage"] == pytest.approx(1.0, abs=0.01)

    def test_coverage_raw_present_std_nan(self, mock_factor_df, mock_composite_factor):
        """v1.14: raw 值非 NaN 但 std=NaN 时，覆盖率应反映 std 缺失（非 raw 可用）"""
        df = mock_factor_df.copy()
        # raw 值保留非 NaN，但 std 值设为 NaN（模拟生产环境短样本因子场景）
        df.loc[0, "rsi_6_std"] = np.nan
        # rsi_6 raw 值仍为 50（非 NaN），但 std 为 NaN → 综合因子不使用该因子

        weights = {"rsi_6": 0.6, "volume_ratio_5": 0.4}

        result, _, _, _ = sort_and_select(
            mock_composite_factor,
            df,
            top_n=10,
            factor_direction="negative",
            factor_cols=["rsi_6", "volume_ratio_5"],
            weights=weights,
            min_weight_coverage=0,  # 禁用过滤，测试覆盖率计算本身
        )

        stock_000001 = next(s for s in result if s["code"] == "000001")
        # rsi_6 std=NaN → 不计入 available_weight → coverage = 0.4/1.0 = 0.4
        assert stock_000001["weight_coverage"] == pytest.approx(0.4, abs=0.01)
