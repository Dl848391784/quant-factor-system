#!/usr/bin/env python3
"""
weight_selector.py 测试用例

测试覆盖：
- 配置类属性验证
- 加载函数验证
- 归一化函数验证
- 综合得分计算验证
- 输出结构验证

版本历史：
- v1.0 (2026-06-03): 初始测试用例
"""

# 标准库导入
import json
import sys
from pathlib import Path

# 根目录模块导入 sys.path 处理
PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 本地模块导入
from comprehensive_factor.weight_selector import (
    DEFAULT_CONFIG,
    EPSILON,
    extract_metrics,
    load_composite_results,
    normalize_minmax,
    calculate_weighted_score,
    select_best_method,
    generate_output,
    __version__,
)


# =============================================================================
# 测试数据
# =============================================================================

MOCK_RESULTS = {
    "equal_weight": {
        "backtest_result": {
            "long_short": {
                "long_short_return_annual": 0.10,
                "long_short_sharpe": 1.5,
                "turnover_long_avg": 0.3,
                "turnover_short_avg": 0.4,
            },
            "monotonicity": {"correlation": 0.8},
            "trading_cost_analysis": {"long_short_net_daily": 0.001},
            "layer_stats": {
                "layer_1": {"annual_return": 0.15, "sharpe_ratio": 2.0, "max_drawdown": -0.05},
                "layer_2": {"annual_return": 0.12, "sharpe_ratio": 1.8, "max_drawdown": -0.04},
            },
        }
    },
    "icir_weight": {
        "backtest_result": {
            "long_short": {
                "long_short_return_annual": 0.15,
                "long_short_sharpe": 2.0,
                "turnover_long_avg": 0.25,
                "turnover_short_avg": 0.35,
            },
            "monotonicity": {"correlation": 0.9},
            "trading_cost_analysis": {"long_short_net_daily": 0.002},
            "layer_stats": {
                "layer_1": {"annual_return": 0.18, "sharpe_ratio": 2.5, "max_drawdown": -0.03},
                "layer_2": {"annual_return": 0.16, "sharpe_ratio": 2.2, "max_drawdown": -0.02},
            },
        }
    },
}


# =============================================================================
# 测试类
# =============================================================================


class TestConfigAttributes:
    """配置类属性验证"""

    def test_default_config_metrics_count(self):
        """验证评价指标数量为9"""
        assert len(DEFAULT_CONFIG["metrics"]) == 9

    def test_default_config_weight_methods_count(self):
        """验证权重方式数量为4"""
        assert len(DEFAULT_CONFIG["weight_methods"]) == 4

    def test_default_config_weight_methods_names(self):
        """验证权重方式命名正确"""
        expected = ["equal_weight", "ic_weight", "icir_weight", "rolling_icir_weight"]
        assert DEFAULT_CONFIG["weight_methods"] == expected

    def test_epsilon_value(self):
        """验证EPSILON精度容差值正确"""
        assert EPSILON == 1e-10

    def test_version_format(self):
        """验证版本号格式正确"""
        assert __version__ == "1.3"


class TestMetricExtraction:
    """指标提取验证"""

    def test_extract_metrics_returns_dict(self):
        """验证extract_metrics返回字典"""
        metrics_data = extract_metrics(MOCK_RESULTS)
        assert isinstance(metrics_data, dict)

    def test_extract_metrics_method_count(self):
        """验证提取的方法数量正确"""
        metrics_data = extract_metrics(MOCK_RESULTS)
        assert len(metrics_data) == 2

    def test_extract_metrics_contains_all_metrics(self):
        """验证每个方法包含9个指标"""
        metrics_data = extract_metrics(MOCK_RESULTS)
        for method, metrics in metrics_data.items():
            assert len(metrics) == 9

    def test_extract_metrics_monotonicity_abs(self):
        """验证单调性取绝对值"""
        metrics_data = extract_metrics(MOCK_RESULTS)
        # 原始值为0.8和0.9，绝对值应相同
        assert metrics_data["equal_weight"]["monotonicity_abs"] == 0.8
        assert metrics_data["icir_weight"]["monotonicity_abs"] == 0.9


class TestNormalization:
    """归一化验证"""

    def test_normalize_minmax_returns_dict(self):
        """验证normalize_minmax返回字典"""
        metrics_data = extract_metrics(MOCK_RESULTS)
        normalized = normalize_minmax(metrics_data, DEFAULT_CONFIG["metrics"])
        assert isinstance(normalized, dict)

    def test_normalize_minmax_range(self):
        """验证归一化值在[0, 1]区间"""
        metrics_data = extract_metrics(MOCK_RESULTS)
        normalized = normalize_minmax(metrics_data, DEFAULT_CONFIG["metrics"])
        for method, scores in normalized.items():
            for metric, value in scores.items():
                assert 0 <= value <= 1

    def test_normalize_minmax_higher_better_direction(self):
        """验证higher_better方向归一化正确"""
        metrics_data = extract_metrics(MOCK_RESULTS)
        normalized = normalize_minmax(metrics_data, DEFAULT_CONFIG["metrics"])
        # icir_weight收益更高，应得更高分
        assert normalized["icir_weight"]["long_short_return_annual"] == 1.0
        assert normalized["equal_weight"]["long_short_return_annual"] == 0.0

    def test_normalize_minmax_lower_better_direction(self):
        """验证lower_better方向归一化正确"""
        metrics_data = extract_metrics(MOCK_RESULTS)
        normalized = normalize_minmax(metrics_data, DEFAULT_CONFIG["metrics"])
        # icir_weight换手率更低，应得更高分
        assert normalized["icir_weight"]["turnover_long_avg"] == 1.0
        assert normalized["equal_weight"]["turnover_long_avg"] == 0.0


class TestWeightedScore:
    """综合得分验证"""

    def test_calculate_weighted_score_returns_dict(self):
        """验证calculate_weighted_score返回字典"""
        metrics_data = extract_metrics(MOCK_RESULTS)
        normalized = normalize_minmax(metrics_data, DEFAULT_CONFIG["metrics"])
        scores = calculate_weighted_score(normalized, DEFAULT_CONFIG["metrics"])
        assert isinstance(scores, dict)

    def test_calculate_weighted_score_range(self):
        """验证综合得分在[0, 1]区间"""
        metrics_data = extract_metrics(MOCK_RESULTS)
        normalized = normalize_minmax(metrics_data, DEFAULT_CONFIG["metrics"])
        scores = calculate_weighted_score(normalized, DEFAULT_CONFIG["metrics"])
        for method, score in scores.items():
            assert 0 <= score <= 1


class TestSelection:
    """最优方法选择验证"""

    def test_select_best_method_returns_tuple(self):
        """验证select_best_method返回tuple"""
        metrics_data = extract_metrics(MOCK_RESULTS)
        normalized = normalize_minmax(metrics_data, DEFAULT_CONFIG["metrics"])
        scores = calculate_weighted_score(normalized, DEFAULT_CONFIG["metrics"])
        result = select_best_method(scores)
        assert isinstance(result, tuple)
        assert len(result) == 3

    def test_select_best_method_best_score(self):
        """验证最优方法得分最高"""
        metrics_data = extract_metrics(MOCK_RESULTS)
        normalized = normalize_minmax(metrics_data, DEFAULT_CONFIG["metrics"])
        scores = calculate_weighted_score(normalized, DEFAULT_CONFIG["metrics"])
        best_method, best_score, ranked = select_best_method(scores)
        # 验证最优得分等于最高得分
        assert best_score == max(scores.values())


class TestOutputStructure:
    """输出结构验证"""

    def test_generate_output_returns_dict(self):
        """验证generate_output返回字典"""
        metrics_data = extract_metrics(MOCK_RESULTS)
        normalized = normalize_minmax(metrics_data, DEFAULT_CONFIG["metrics"])
        scores = calculate_weighted_score(normalized, DEFAULT_CONFIG["metrics"])
        best_method, best_score, ranked = select_best_method(scores)
        output = generate_output(
            metrics_data, normalized, scores, best_method, best_score, ranked, DEFAULT_CONFIG["metrics"]
        )
        assert isinstance(output, dict)

    def test_generate_output_meta_fields(self):
        """验证meta字段存在"""
        metrics_data = extract_metrics(MOCK_RESULTS)
        normalized = normalize_minmax(metrics_data, DEFAULT_CONFIG["metrics"])
        scores = calculate_weighted_score(normalized, DEFAULT_CONFIG["metrics"])
        best_method, best_score, ranked = select_best_method(scores)
        output = generate_output(
            metrics_data, normalized, scores, best_method, best_score, ranked, DEFAULT_CONFIG["metrics"]
        )
        assert "meta" in output
        assert "created_at" in output["meta"]
        assert "normalization_method" in output["meta"]
        assert output["meta"]["normalization_method"] == "min-max"

    def test_generate_output_best_selection_fields(self):
        """验证best_selection字段存在"""
        metrics_data = extract_metrics(MOCK_RESULTS)
        normalized = normalize_minmax(metrics_data, DEFAULT_CONFIG["metrics"])
        scores = calculate_weighted_score(normalized, DEFAULT_CONFIG["metrics"])
        best_method, best_score, ranked = select_best_method(scores)
        output = generate_output(
            metrics_data, normalized, scores, best_method, best_score, ranked, DEFAULT_CONFIG["metrics"]
        )
        assert "best_selection" in output
        assert "method" in output["best_selection"]
        assert "composite_score" in output["best_selection"]

    def test_generate_output_ranking_fields(self):
        """验证ranking字段存在"""
        metrics_data = extract_metrics(MOCK_RESULTS)
        normalized = normalize_minmax(metrics_data, DEFAULT_CONFIG["metrics"])
        scores = calculate_weighted_score(normalized, DEFAULT_CONFIG["metrics"])
        best_method, best_score, ranked = select_best_method(scores)
        output = generate_output(
            metrics_data, normalized, scores, best_method, best_score, ranked, DEFAULT_CONFIG["metrics"]
        )
        assert "ranking" in output
        assert len(output["ranking"]) == len(scores)