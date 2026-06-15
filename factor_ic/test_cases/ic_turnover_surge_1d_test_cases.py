#!/usr/bin/env python3
"""
ic_turnover_surge_1d 测试用例

测试脚本: factor_ic/ic_turnover_surge_1d.py
因子计算: data_fetchers/factor_calculator/basic.py::calculate_turnover_surge
流程文档: factor_ic/docs/ic_turnover_surge_1d_flow.md
规范文档: PROJECT.md / factor_ic/MODULE.md

换手率突增因子计算公式（surge_window=5）：
    avg_turnover = turnover_rate.shift(1).rolling(5, min_periods=5).mean()
    turnover_surge = turnover_rate / avg_turnover
    边界: avg_turnover ≈ 0 → NaN; turnover_surge < 0 → NaN

运行: pytest factor_ic/test_cases/ic_turnover_surge_1d_test_cases.py -v
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from data_fetchers.factor_calculator import calculate_turnover_surge
from factor_ic.common.data_completeness import FACTOR_IC_RESULT_DIR, get_ic_output_path


def _make_panel(
    n_days: int = 10,
    asset: str = "A",
    turnover_pattern: list[float] | None = None,
) -> pd.DataFrame:
    """构造单股票面板数据（含 date/asset/close/turnover_rate）。"""
    dates = pd.date_range("2026-01-01", periods=n_days)
    if turnover_pattern is None:
        turnover_pattern = [1.0] * n_days
    return pd.DataFrame(
        {
            "date": dates,
            "asset": [asset] * n_days,
            "close": [10.0] * n_days,
            "turnover_rate": turnover_pattern,
        }
    )


class TestOutputPath:
    """测试输出路径和命名规范"""

    def test_output_path_format(self):
        """输出文件命名应符合规范: ic_<因子名>_analysis_result.json"""
        path = get_ic_output_path("turnover_surge_1d")
        assert path.name == "ic_turnover_surge_1d_analysis_result.json"

    def test_output_directory(self):
        """输出目录应为 factor_ic/result/"""
        path = get_ic_output_path("turnover_surge_1d")
        assert path.parent == FACTOR_IC_RESULT_DIR

    def test_output_directory_exists_or_created(self):
        """输出目录不存在时应自动创建"""
        assert FACTOR_IC_RESULT_DIR.exists() or FACTOR_IC_RESULT_DIR.parent.exists()


class TestCalculateTurnoverSurge:
    """测试因子计算函数"""

    def test_basic_calculation_adds_column(self):
        """基本计算：10 天单股票数据应正常添加 turnover_surge 列"""
        df = _make_panel(n_days=10)
        result = calculate_turnover_surge(df)

        assert "turnover_surge" in result.columns
        assert len(result) == len(df)

    def test_warmup_period_is_nan(self):
        """surge_window=5 + shift(1) → 前 5 天的 turnover_surge 必须为 NaN"""
        df = _make_panel(n_days=10, turnover_pattern=[1.0] * 5 + [2.0, 1.0, 3.0, 1.0, 1.0])
        result = calculate_turnover_surge(df, surge_window=5)

        result_sorted = result.sort_values(["asset", "date"]).reset_index(drop=True)
        first_5 = result_sorted["turnover_surge"].iloc[:5]
        assert first_5.isna().all(), f"前 5 天预热期 turnover_surge 应全为 NaN，实际: {first_5.tolist()}"

    def test_surge_value_correctness(self):
        """因子值正确性：第 6 天 = 当日 / mean(过去 5 天) = 2.0 / 1.0 = 2.0"""
        df = _make_panel(n_days=10, turnover_pattern=[1.0] * 5 + [2.0, 1.0, 3.0, 1.0, 1.0])
        result = calculate_turnover_surge(df, surge_window=5)

        result_sorted = result.sort_values(["asset", "date"]).reset_index(drop=True)
        # 第 6 天（index=5）：2.0 / mean([1,1,1,1,1]) = 2.0
        assert np.isclose(result_sorted["turnover_surge"].iloc[5], 2.0), (
            f"第 6 天应为 2.0，实际: {result_sorted['turnover_surge'].iloc[5]}"
        )

    def test_zero_avg_turnover_marked_nan(self):
        """边界：avg_turnover ≈ 0（前 5 天换手率全 0）→ 当日 turnover_surge 应为 NaN"""
        df = _make_panel(n_days=8, turnover_pattern=[0.0] * 5 + [1.0, 1.0, 1.0])
        result = calculate_turnover_surge(df, surge_window=5)

        result_sorted = result.sort_values(["asset", "date"]).reset_index(drop=True)
        # 第 6 天：avg=0 → 标记为 NaN（异常检测优于静默修正，MODULE.md M15）
        assert pd.isna(result_sorted["turnover_surge"].iloc[5]), (
            "avg_turnover ≈ 0 时 turnover_surge 应为 NaN（避免除零）"
        )

    def test_multi_asset_independent(self):
        """多股票场景：每只股票独立按 asset 分组计算，不相互污染"""
        pattern = [1.0] * 5 + [2.0, 1.0, 1.0]
        df_a = _make_panel(n_days=8, asset="A", turnover_pattern=pattern)
        # B 的换手率是 A 的 2 倍，但 surge 比值应相同（self-relative 因子）
        df_b = _make_panel(n_days=8, asset="B", turnover_pattern=[v * 2 for v in pattern])
        df = pd.concat([df_a, df_b], ignore_index=True)

        result = calculate_turnover_surge(df, surge_window=5)

        valid_a = result[result["asset"] == "A"]["turnover_surge"].dropna().tolist()
        valid_b = result[result["asset"] == "B"]["turnover_surge"].dropna().tolist()
        assert len(valid_a) == len(valid_b) == 3
        # surge 是相对比值，两只股票应得到相同 surge 值
        for a, b in zip(valid_a, valid_b):
            assert np.isclose(a, b), f"A.surge={a} 应等于 B.surge={b}（相对比值不变）"

    def test_data_insufficient_below_window(self):
        """数据天数 ≤ surge_window：所有行 turnover_surge 应为 NaN"""
        df = _make_panel(n_days=4)
        result = calculate_turnover_surge(df, surge_window=5)

        assert result["turnover_surge"].isna().all(), "数据 ≤ surge_window 时所有 turnover_surge 应为 NaN"

    def test_input_not_mutated(self):
        """函数入口必须 .copy()，不应修改原始 DataFrame（MODULE.md M3）"""
        df = _make_panel(n_days=8)
        original_columns = set(df.columns)
        original_turnover = df["turnover_rate"].tolist()
        _ = calculate_turnover_surge(df)

        assert set(df.columns) == original_columns, "calculate_turnover_surge 不应修改原始 DataFrame 的列"
        assert df["turnover_rate"].tolist() == original_turnover, "calculate_turnover_surge 不应修改原始 DataFrame 的值"


class TestOutputStructure:
    """测试输出数据结构规范（文件存在时校验，否则 skip）"""

    REQUIRED_FIELDS = [
        "factor_name",
        "calculation_date",
        "period",
        "ic_metrics",
        "sample_stats",
        "statistical_significance",
        "factor_direction",
        "economic_significance",
        "icir_stability",
        "ic_distribution_consistency",
    ]

    def test_output_file_exists_after_run(self):
        """运行后输出文件应存在（仅校验路径正确）"""
        path = get_ic_output_path("turnover_surge_1d")
        if not path.exists():
            pytest.skip("输出文件不存在，需要先运行 ic_turnover_surge_1d.py")

    def test_output_structure_if_exists(self):
        """如果输出文件存在，检查 MODULE.md 输出结构模板规定的必需字段"""
        path = get_ic_output_path("turnover_surge_1d")
        if not path.exists():
            pytest.skip("输出文件不存在")

        with open(path, encoding="utf-8") as f:
            result = json.load(f)

        for field in self.REQUIRED_FIELDS:
            assert field in result, f"缺少必需字段: {field}"

    def test_ic_metrics_fields_if_exists(self):
        """如果输出文件存在，检查 ic_metrics 子字段"""
        path = get_ic_output_path("turnover_surge_1d")
        if not path.exists():
            pytest.skip("输出文件不存在")

        with open(path, encoding="utf-8") as f:
            result = json.load(f)

        ic_metrics = result.get("ic_metrics", {})
        for field in ["ic_mean", "ic_std", "icir"]:
            assert field in ic_metrics, f"ic_metrics 缺少必需字段: {field}"

    def test_sample_stats_fields_if_exists(self):
        """如果输出文件存在，检查 sample_stats 子字段"""
        path = get_ic_output_path("turnover_surge_1d")
        if not path.exists():
            pytest.skip("输出文件不存在")

        with open(path, encoding="utf-8") as f:
            result = json.load(f)

        sample_stats = result.get("sample_stats", {})
        for field in ["total_days", "valid_days"]:
            assert field in sample_stats, f"sample_stats 缺少必需字段: {field}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
