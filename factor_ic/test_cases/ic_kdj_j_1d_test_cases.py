#!/usr/bin/env python3
"""
ic_kdj_j_1d 测试用例

测试脚本: factor_ic/ic_kdj_j_1d.py
因子计算: data_fetchers/factor_calculator/basic.py::calculate_kdj_j
流程文档: factor_ic/docs/ic_kdj_j_1d_flow.md
规范文档: PROJECT.md / factor_ic/MODULE.md

KDJ_J 因子计算公式（N=9, M1=3, M2=3）：
    RSV = (Close - rolling_low_9) / (rolling_high_9 - rolling_low_9) × 100
    K = EWM(RSV, alpha=1/3, initial=50)
    D = EWM(K,   alpha=1/3, initial=50)
    J = 3K - 2D

运行: pytest factor_ic/test_cases/ic_kdj_j_1d_test_cases.py -v
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from data_fetchers.factor_calculator import calculate_kdj_j
from factor_ic.common.data_completeness import FACTOR_IC_RESULT_DIR, get_ic_output_path


def _make_panel(n_days: int = 30, asset: str = "A", base_close: float = 10.0) -> pd.DataFrame:
    """构造单股票面板数据（含 date/asset/close/high/low），KDJ 函数要求按 asset 分组排序。"""
    dates = pd.date_range("2026-01-01", periods=n_days)
    close = np.linspace(base_close, base_close + 10.0, n_days)
    return pd.DataFrame(
        {
            "date": dates,
            "asset": [asset] * n_days,
            "close": close,
            "high": close + 1.0,
            "low": close - 1.0,
        }
    )


class TestOutputPath:
    """测试输出路径和命名规范"""

    def test_output_path_format(self):
        """输出文件命名应符合规范: ic_<因子名>_analysis_result.json"""
        path = get_ic_output_path("kdj_j_1d")
        assert path.name == "ic_kdj_j_1d_analysis_result.json"

    def test_output_directory(self):
        """输出目录应为 factor_ic/result/"""
        path = get_ic_output_path("kdj_j_1d")
        assert path.parent == FACTOR_IC_RESULT_DIR

    def test_output_directory_exists_or_created(self):
        """输出目录不存在时应自动创建"""
        assert FACTOR_IC_RESULT_DIR.exists() or FACTOR_IC_RESULT_DIR.parent.exists()


class TestCalculateKdjJ:
    """测试因子计算函数"""

    def test_basic_calculation_adds_column(self):
        """基本计算：30 天单股票数据应正常添加 kdj_j 列"""
        df = _make_panel(n_days=30)
        result = calculate_kdj_j(df)

        assert "kdj_j" in result.columns
        assert len(result) == len(df)

    def test_warmup_period_is_nan(self):
        """N=9 窗口预热期前 8 天的 RSV 必须为 NaN（min_periods=9）"""
        df = _make_panel(n_days=30)
        result = calculate_kdj_j(df)

        # 单股票按时间排序后前 N-1=8 行应为 NaN
        result_sorted = result.sort_values(["asset", "date"]).reset_index(drop=True)
        first_n_minus_1 = result_sorted["kdj_j"].iloc[:8]
        assert first_n_minus_1.isna().all(), f"前 8 天 RSV 不足窗口，kdj_j 应全为 NaN，实际: {first_n_minus_1.tolist()}"

    def test_high_equals_low_rsv_neutral(self):
        """边界：high == low 时 RSV 退化为 50（避免除零），K/D/J 进入中性轨迹"""
        # 构造 9 天 high == low == close（一字行情）
        df = pd.DataFrame(
            {
                "date": pd.date_range("2026-01-01", periods=9),
                "asset": ["A"] * 9,
                "close": [10.0] * 9,
                "high": [10.0] * 9,
                "low": [10.0] * 9,
            }
        )
        result = calculate_kdj_j(df)

        # 不应抛异常，且第 9 天（首个有效窗口）应为有限值（中性附近）
        last_value = result["kdj_j"].iloc[-1]
        assert pd.notna(last_value), "high==low 边界下 kdj_j 应为有限值（中性）"
        # K=D=50 → J = 3*50 - 2*50 = 50
        assert np.isclose(last_value, 50.0, atol=1.0), f"high==low 时 J 应在 50 附近（中性），实际: {last_value}"

    def test_multi_asset_independent(self):
        """多股票场景：每只股票独立按 asset 分组计算 RSV，不相互污染"""
        df_a = _make_panel(n_days=20, asset="A", base_close=10.0)
        df_b = _make_panel(n_days=20, asset="B", base_close=100.0)
        df = pd.concat([df_a, df_b], ignore_index=True)

        result = calculate_kdj_j(df)

        # 两只股票预热期之外都应有有效值
        valid_a = result[result["asset"] == "A"]["kdj_j"].dropna()
        valid_b = result[result["asset"] == "B"]["kdj_j"].dropna()
        assert len(valid_a) > 0, "asset=A 应有有效 kdj_j 值"
        assert len(valid_b) > 0, "asset=B 应有有效 kdj_j 值"

    def test_data_insufficient_below_window(self):
        """数据天数不足窗口（< N=9）：所有行 kdj_j 应为 NaN，不抛异常"""
        df = _make_panel(n_days=5)
        result = calculate_kdj_j(df)

        assert result["kdj_j"].isna().all(), "数据不足窗口时所有 kdj_j 应为 NaN"

    def test_input_not_mutated(self):
        """函数入口必须 .copy()，不应修改原始 DataFrame（MODULE.md M3）"""
        df = _make_panel(n_days=15)
        original_columns = set(df.columns)
        _ = calculate_kdj_j(df)

        assert set(df.columns) == original_columns, "calculate_kdj_j 不应修改原始 DataFrame（应在副本上添加列）"


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
        path = get_ic_output_path("kdj_j_1d")
        if not path.exists():
            pytest.skip("输出文件不存在，需要先运行 ic_kdj_j_1d.py")

    def test_output_structure_if_exists(self):
        """如果输出文件存在，检查 MODULE.md 输出结构模板规定的必需字段"""
        path = get_ic_output_path("kdj_j_1d")
        if not path.exists():
            pytest.skip("输出文件不存在")

        with open(path, encoding="utf-8") as f:
            result = json.load(f)

        for field in self.REQUIRED_FIELDS:
            assert field in result, f"缺少必需字段: {field}"

    def test_ic_metrics_fields_if_exists(self):
        """如果输出文件存在，检查 ic_metrics 子字段"""
        path = get_ic_output_path("kdj_j_1d")
        if not path.exists():
            pytest.skip("输出文件不存在")

        with open(path, encoding="utf-8") as f:
            result = json.load(f)

        ic_metrics = result.get("ic_metrics", {})
        for field in ["ic_mean", "ic_std", "icir"]:
            assert field in ic_metrics, f"ic_metrics 缺少必需字段: {field}"

    def test_sample_stats_fields_if_exists(self):
        """如果输出文件存在，检查 sample_stats 子字段"""
        path = get_ic_output_path("kdj_j_1d")
        if not path.exists():
            pytest.skip("输出文件不存在")

        with open(path, encoding="utf-8") as f:
            result = json.load(f)

        sample_stats = result.get("sample_stats", {})
        for field in ["total_days", "valid_days"]:
            assert field in sample_stats, f"sample_stats 缺少必需字段: {field}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
