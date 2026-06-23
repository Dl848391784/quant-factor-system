"""weight_selector 测试用例

覆盖 4 类协作 API (v1.8 SRP 拆分后)：
- WeightSelectorConfig (配置值对象)
- MetricExtractor (业务层)
- Scorer (数学层)
- ReportFormatter (输出层)

并验证 P3 改动 (designs/strategy_systemic_overhaul.md §2.3)：
- 多空/空头指标删除
- L1指标新增 (layer_1_annual, layer_1_sharpe)
- 总指标数 = 7

历史: 原 test_weight_selector.py (v1.4-stale) 与 test_weight_selector_p3.py
合并到此文件 (2026-06-23)。stale 文件 import v1.7 顶层函数
(extract_metrics/normalize_minmax/...) 导致 ImportError，v1.8 已封装入 4 类。

遵循:
- AGENTS.md §0 (Execute / Review)
- AGENTS.md §2 规则 #7 (测试位置), #8 (配套测试)
"""

import pytest
from comprehensive_factor.weight_selector import (
    DEFAULT_CONFIG,
    EPSILON,
    MetricExtractor,
    ReportFormatter,
    Scorer,
    WeightSelectorConfig,
    __version__,
)


# =============================================================================
# Fixtures
# =============================================================================


def _make_config() -> WeightSelectorConfig:
    """从 DEFAULT_CONFIG 创建 WeightSelectorConfig（v1.8 标准入口）"""
    return WeightSelectorConfig.from_dict(
        metric_configs={k: dict(v) for k, v in DEFAULT_CONFIG["metrics"].items()},
        long_layers=list(DEFAULT_CONFIG["long_layers"]),
    )


def _make_backtest_result(
    method: str = "equal_weight",
    l1_annual: float = 0.15,
    l1_sharpe: float = 0.60,
    turnover: float = 0.30,
    correlation: float = -0.5,
) -> dict:
    """构造单 method 的 backtest_result 数据（覆盖 P3 7 个指标所需字段）"""
    return {
        method: {
            "backtest_result": {
                "long_short": {"turnover_long_avg": turnover},
                "monotonicity": {"correlation": correlation},
                "layer_stats": {
                    "layer_1": {
                        "annual_return": l1_annual,
                        "sharpe_ratio": l1_sharpe,
                        "max_drawdown": -0.10,
                    },
                    "layer_2": {
                        "annual_return": 0.08,
                        "sharpe_ratio": 0.40,
                        "max_drawdown": -0.12,
                    },
                },
            }
        }
    }


# =============================================================================
# 模块级常量验证
# =============================================================================


class TestModuleConstants:
    """模块常量基线验证"""

    def test_version_present(self):
        """__version__ 已定义且为字符串（不硬编码具体值，避免再次 stale）"""
        assert isinstance(__version__, str)
        assert len(__version__) > 0

    def test_epsilon_value(self):
        """EPSILON 精度容差 = 1e-10"""
        assert EPSILON == 1e-10

    def test_default_config_weight_methods(self):
        """权重方式 = 4 个固定方法"""
        expected = ["equal_weight", "ic_weight", "icir_weight", "rolling_icir_weight"]
        actual = DEFAULT_CONFIG["weight_methods"]  # type: ignore[index]
        assert list(actual) == expected


# =============================================================================
# P3: 只做多对齐 (designs/strategy_systemic_overhaul.md §2.3)
# =============================================================================


class TestMetricsConfig:
    """指标配置验证（P3 改动）"""

    def test_long_short_metrics_removed(self):
        """多空/空头指标已删除"""
        metrics = DEFAULT_CONFIG["metrics"]
        assert "long_short_return_annual" not in metrics
        assert "long_short_sharpe" not in metrics
        assert "long_short_net_daily" not in metrics
        assert "turnover_short_avg" not in metrics

    def test_layer_1_metrics_added(self):
        """L1指标已新增"""
        metrics = DEFAULT_CONFIG["metrics"]
        assert "layer_1_annual" in metrics
        assert "layer_1_sharpe" in metrics
        assert metrics["layer_1_annual"]["direction"] == "higher_better"
        assert metrics["layer_1_sharpe"]["direction"] == "higher_better"

    def test_total_metrics_count_is_seven(self):
        """总指标数 = 7（原9 - 4删除 + 2新增）"""
        assert len(DEFAULT_CONFIG["metrics"]) == 7

    def test_all_metrics_meaningful_for_long_only(self):
        """所有7个指标对只做多策略有意义"""
        for name in DEFAULT_CONFIG["metrics"]:
            assert "long_short" not in name, f"多空指标残留: {name}"
            assert "short" not in name, f"空头指标残留: {name}"


# =============================================================================
# MetricExtractor (业务层)
# =============================================================================


class TestMetricExtractor:
    """指标提取验证（含 P3 改动）"""

    def test_layer_1_extracted_correctly(self):
        """L1指标从 layer_stats 正确提取"""
        extractor = MetricExtractor(_make_config())
        metrics_data = extractor.extract(_make_backtest_result(l1_annual=0.22, l1_sharpe=0.80))
        assert pytest.approx(metrics_data["equal_weight"]["layer_1_annual"], abs=1e-6) == 0.22
        assert pytest.approx(metrics_data["equal_weight"]["layer_1_sharpe"], abs=1e-6) == 0.80

    def test_no_long_short_fields_in_extracted_data(self):
        """提取的指标数据中不含多空/空头字段（P3 契约）"""
        extractor = MetricExtractor(_make_config())
        metrics_data = extractor.extract(_make_backtest_result())
        for data in metrics_data.values():
            assert "long_short_return_annual" not in data
            assert "long_short_sharpe" not in data
            assert "long_short_net_daily" not in data
            assert "turnover_short_avg" not in data

    def test_monotonicity_abs_taken(self):
        """monotonicity_abs 取绝对值（方向无关）"""
        extractor = MetricExtractor(_make_config())
        positive = extractor.extract(_make_backtest_result(correlation=0.8))
        negative = extractor.extract(_make_backtest_result(correlation=-0.8))
        assert positive["equal_weight"]["monotonicity_abs"] == 0.8
        assert negative["equal_weight"]["monotonicity_abs"] == 0.8

    def test_missing_long_short_raises(self):
        """backtest_result 完全缺失时跳过失败方法；全部失败抛 ValueError"""
        extractor = MetricExtractor(_make_config())
        broken = {"equal_weight": {"backtest_result": {}}}
        with pytest.raises(ValueError, match="所有方法提取失败"):
            extractor.extract(broken)


# =============================================================================
# Scorer (数学层)
# =============================================================================


class TestScorer:
    """评分器：归一化 / 加权 / 选优"""

    def _build_two_method_metrics(self) -> dict[str, dict[str, float]]:
        """构造 2 方法的 metrics_data（覆盖 DEFAULT_CONFIG 7 个指标）"""
        return {
            "equal_weight": {
                "long_return_annual": 0.10,
                "long_sharpe": 0.50,
                "layer_1_annual": 0.12,
                "layer_1_sharpe": 0.55,
                "monotonicity_abs": 0.70,
                "turnover_long_avg": 0.40,
                "max_drawdown": 0.08,
            },
            "icir_weight": {
                "long_return_annual": 0.20,
                "long_sharpe": 0.80,
                "layer_1_annual": 0.22,
                "layer_1_sharpe": 0.85,
                "monotonicity_abs": 0.90,
                "turnover_long_avg": 0.30,
                "max_drawdown": 0.05,
            },
        }

    def test_normalize_range(self):
        """归一化值在 [0, 1] 区间"""
        scorer = Scorer(_make_config())
        normalized = scorer.normalize(self._build_two_method_metrics())
        for method_scores in normalized.values():
            for value in method_scores.values():
                assert 0 <= value <= 1

    def test_normalize_higher_better_direction(self):
        """higher_better 指标：最大值得 1.0，最小值得 0.0"""
        scorer = Scorer(_make_config())
        normalized = scorer.normalize(self._build_two_method_metrics())
        # layer_1_annual: icir(0.22) > equal(0.12)
        assert normalized["icir_weight"]["layer_1_annual"] == 1.0
        assert normalized["equal_weight"]["layer_1_annual"] == 0.0

    def test_normalize_lower_better_direction(self):
        """lower_better 指标（turnover_long_avg）：最小值得 1.0"""
        scorer = Scorer(_make_config())
        normalized = scorer.normalize(self._build_two_method_metrics())
        assert normalized["icir_weight"]["turnover_long_avg"] == 1.0
        assert normalized["equal_weight"]["turnover_long_avg"] == 0.0

    def test_normalize_single_method_all_ones(self):
        """单方法 diff=0 → EPSILON 容差 → 全给 1.0"""
        scorer = Scorer(_make_config())
        single = {
            "equal_weight": {
                "long_return_annual": 0.10,
                "long_sharpe": 0.50,
                "layer_1_annual": 0.12,
                "layer_1_sharpe": 0.55,
                "monotonicity_abs": 0.70,
                "turnover_long_avg": 0.40,
                "max_drawdown": 0.08,
            }
        }
        normalized = scorer.normalize(single)
        for value in normalized["equal_weight"].values():
            assert value == 1.0

    def test_calculate_weighted_range(self):
        """综合得分在 [0, 1] 区间"""
        scorer = Scorer(_make_config())
        normalized = scorer.normalize(self._build_two_method_metrics())
        scores = scorer.calculate_weighted(normalized)
        for score in scores.values():
            assert 0 <= score <= 1

    def test_calculate_weighted_zero_total_weight(self):
        """所有权重为 0 时返回 0.0（不除零）"""
        # 自建 metrics 全 0 权重的临时 config
        zero_metrics = {
            "m1": {"direction": "higher_better", "weight": 0.0, "short_name": "m1"},
            "m2": {"direction": "higher_better", "weight": 0.0, "short_name": "m2"},
        }
        config = WeightSelectorConfig.from_dict(
            metric_configs=zero_metrics, long_layers=["layer_1"]
        )
        scorer = Scorer(config)
        normalized_scores = {"method1": {"m1": 0.5, "m2": 0.5}}
        assert scorer.calculate_weighted(normalized_scores)["method1"] == 0.0

    def test_select_best_returns_top_score(self):
        """select_best 返回最高得分的 method"""
        scorer = Scorer(_make_config())
        normalized = scorer.normalize(self._build_two_method_metrics())
        scores = scorer.calculate_weighted(normalized)
        best_method, best_score, ranked = scorer.select_best(scores)
        assert best_score == max(scores.values())
        assert ranked[0] == (best_method, best_score)
        assert len(ranked) == len(scores)

    def test_select_best_empty_raises(self):
        """空字典抛 ValueError（v1.4 防御性边界）"""
        scorer = Scorer(_make_config())
        with pytest.raises(ValueError, match="final_scores 不能为空"):
            scorer.select_best({})


# =============================================================================
# ReportFormatter (输出层)
# =============================================================================


class TestReportFormatter:
    """输出结构验证"""

    def _build_full_pipeline(self):
        """走完 extract → normalize → score → select 拿到全部参数"""
        config = _make_config()
        extractor = MetricExtractor(config)
        scorer = Scorer(config)
        results = _make_backtest_result("equal_weight", l1_annual=0.10, l1_sharpe=0.50)
        results.update(_make_backtest_result("icir_weight", l1_annual=0.20, l1_sharpe=0.80))
        metrics_data = extractor.extract(results)
        normalized = scorer.normalize(metrics_data)
        scores = scorer.calculate_weighted(normalized)
        best_method, best_score, ranked = scorer.select_best(scores)
        formatter = ReportFormatter(config)
        return (
            formatter,
            metrics_data,
            normalized,
            scores,
            best_method,
            best_score,
            ranked,
        )

    def test_generate_output_meta_fields(self):
        """meta 字段含 created_at / normalization_method='min-max' / total_metrics=7"""
        formatter, metrics_data, normalized, scores, best, best_score, ranked = (
            self._build_full_pipeline()
        )
        output = formatter.generate_output(metrics_data, normalized, scores, best, best_score, ranked)
        assert "meta" in output
        assert "created_at" in output["meta"]
        assert output["meta"]["normalization_method"] == "min-max"
        assert output["meta"]["total_metrics"] == 7

    def test_generate_output_best_selection(self):
        """best_selection 含 method + composite_score"""
        formatter, metrics_data, normalized, scores, best, best_score, ranked = (
            self._build_full_pipeline()
        )
        output = formatter.generate_output(metrics_data, normalized, scores, best, best_score, ranked)
        assert output["best_selection"]["method"] == best
        assert output["best_selection"]["composite_score"] == round(best_score, 4)

    def test_generate_output_ranking_length(self):
        """ranking 长度 = 方法数"""
        formatter, metrics_data, normalized, scores, best, best_score, ranked = (
            self._build_full_pipeline()
        )
        output = formatter.generate_output(metrics_data, normalized, scores, best, best_score, ranked)
        assert len(output["ranking"]) == len(scores)
        # 排名从 1 开始
        assert output["ranking"][0]["rank"] == 1

