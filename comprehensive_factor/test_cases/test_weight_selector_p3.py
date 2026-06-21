"""P3: weight_selector 评分对齐只做多测试

验证 design.md P3 改动：
1. 多空/空头指标已删除
2. L1指标已新增
3. 总指标数 = 7
4. MetricExtractor 提取数据不含多空字段

遵循 designs/strategy_systemic_overhaul.md §2.3 决策。
"""

import pytest
from comprehensive_factor.weight_selector import (
    DEFAULT_CONFIG,
    MetricExtractor,
    WeightSelectorConfig,
)


def _make_config() -> WeightSelectorConfig:
    """从 DEFAULT_CONFIG 创建 WeightSelectorConfig"""
    return WeightSelectorConfig.from_dict(
        metric_configs={k: dict(v) for k, v in DEFAULT_CONFIG["metrics"].items()},
        long_layers=list(DEFAULT_CONFIG["long_layers"]),
    )


class TestMetricsConfig:
    """指标配置验证"""

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


class TestMetricsExtraction:
    """指标提取验证"""

    def _make_result(self, l1_annual=0.15, l1_sharpe=0.60) -> dict:
        return {
            "equal_weight": {
                "backtest_result": {
                    "long_short": {"turnover_long_avg": 0.30},
                    "monotonicity": {"correlation": -0.5},
                    "layer_stats": {
                        "layer_1": {"annual_return": l1_annual, "sharpe_ratio": l1_sharpe, "max_drawdown": -0.10},
                        "layer_2": {"annual_return": 0.08, "sharpe_ratio": 0.40, "max_drawdown": -0.12},
                    },
                }
            }
        }

    def test_layer_1_extracted_correctly(self):
        """L1指标从 layer_stats 正确提取"""
        extractor = MetricExtractor(_make_config())
        metrics_data = extractor.extract(self._make_result(l1_annual=0.22, l1_sharpe=0.80))
        assert pytest.approx(metrics_data["equal_weight"]["layer_1_annual"], abs=1e-6) == 0.22
        assert pytest.approx(metrics_data["equal_weight"]["layer_1_sharpe"], abs=1e-6) == 0.80

    def test_no_long_short_fields_in_extracted_data(self):
        """提取的指标数据中不含多空/空头字段"""
        extractor = MetricExtractor(_make_config())
        metrics_data = extractor.extract(self._make_result())
        for data in metrics_data.values():
            assert "long_short_return_annual" not in data
            assert "long_short_sharpe" not in data
            assert "long_short_net_daily" not in data
            assert "turnover_short_avg" not in data
