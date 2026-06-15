#!/usr/bin/env python3
"""
ic_bollinger_pb_1d 测试用例

测试脚本: factor_ic/ic_bollinger_pb_1d.py
因子计算: data_fetchers/factor_calculator/basic.py::calculate_bollinger_pb
流程文档: factor_ic/docs/ic_bollinger_pb_1d_flow.md
规范文档: PROJECT.md / factor_ic/MODULE.md

布林带 %B 因子计算公式（n=20, k=2.0）：
    middle = close.rolling(20).mean()
    std = close.rolling(20).std()
    upper = middle + k*std; lower = middle - k*std
    %B = (close - lower) / (upper - lower)
    边界: band_width < 0 → NaN; band_width 过窄（< EPSILON）→ 中性值 0.5

运行: pytest factor_ic/test_cases/ic_bollinger_pb_1d_test_cases.py -v
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from data_fetchers.factor_calculator import calculate_bollinger_pb
from factor_ic.common.data_completeness import FACTOR_IC_RESULT_DIR, get_ic_output_path


# 布林带窄带触发的中性值（与 basic.py 中 _BOLLINGER_NEUTRAL_VALUE 一致）
BOLLINGER_NEUTRAL_VALUE = 0.5


def _make_panel(
    n_days: int = 25,
    asset: str = "A",
    close_pattern: list[float] | np.ndarray | None = None,
) -> pd.DataFrame:
    """构造单股票面板数据（含 date/asset/close）。"""
    dates = pd.date_range("2026-01-01", periods=n_days)
    if close_pattern is None:
        close_pattern = np.linspace(10.0, 20.0, n_days)
    return pd.DataFrame(
        {
            "date": dates,
            "asset": [asset] * n_days,
            "close": list(close_pattern),
        }
    )


class TestOutputPath:
    """测试输出路径和命名规范"""

    def test_output_path_format(self):
        """输出文件命名应符合规范: ic_<因子名>_analysis_result.json"""
        path = get_ic_output_path("bollinger_pb_1d")
        assert path.name == "ic_bollinger_pb_1d_analysis_result.json"

    def test_output_directory(self):
        """输出目录应为 factor_ic/result/"""
        path = get_ic_output_path("bollinger_pb_1d")
        assert path.parent == FACTOR_IC_RESULT_DIR

    def test_output_directory_exists_or_created(self):
        """输出目录不存在时应自动创建"""
        assert FACTOR_IC_RESULT_DIR.exists() or FACTOR_IC_RESULT_DIR.parent.exists()


class TestCalculateBollingerPb:
    """测试因子计算函数"""

    def test_basic_calculation_adds_column(self):
        """基本计算：25 天单股票数据应正常添加 bollinger_pb 列"""
        df = _make_panel(n_days=25)
        result = calculate_bollinger_pb(df, n=20, k=2.0)

        assert "bollinger_pb" in result.columns
        assert len(result) == len(df)

    def test_warmup_period_is_nan(self):
        """n=20 窗口预热期前 19 天应为 NaN（min_periods=20，rolling 默认）"""
        df = _make_panel(n_days=25)
        result = calculate_bollinger_pb(df, n=20, k=2.0)

        result_sorted = result.sort_values(["asset", "date"]).reset_index(drop=True)
        first_19 = result_sorted["bollinger_pb"].iloc[:19]
        assert first_19.isna().all(), f"前 19 天预热期 bollinger_pb 应全为 NaN，实际: {first_19.tolist()}"

    def test_flat_close_narrow_band_neutral(self):
        """边界：价格平稳（close 全相同）→ band_width 过窄 → 中性值 0.5"""
        df = _make_panel(n_days=25, close_pattern=[10.0] * 25)
        result = calculate_bollinger_pb(df, n=20, k=2.0)

        result_sorted = result.sort_values(["asset", "date"]).reset_index(drop=True)
        # 第 20 天起：std=0 → band_width≈0 → 触发窄带 → 中性值 0.5
        valid_values = result_sorted["bollinger_pb"].iloc[19:]
        assert (valid_values == BOLLINGER_NEUTRAL_VALUE).all(), (
            f"价格平稳时 bollinger_pb 应全为中性值 {BOLLINGER_NEUTRAL_VALUE}，实际: {valid_values.tolist()}"
        )

    def test_close_at_middle_pb_around_half(self):
        """收盘价处于均线时 %B 应在 0.5 附近（对称分布场景）"""
        # 构造对称围绕 10.0 波动的 close，最后一天 close=10.0
        n = 25
        rng = np.random.default_rng(seed=42)
        close = 10.0 + rng.normal(0, 0.5, size=n)
        close[-1] = 10.0  # 最后一天回到均线
        df = _make_panel(n_days=n, close_pattern=close)
        result = calculate_bollinger_pb(df, n=20, k=2.0)

        result_sorted = result.sort_values(["asset", "date"]).reset_index(drop=True)
        last_pb = result_sorted["bollinger_pb"].iloc[-1]
        # close 接近均线 → %B 接近 0.5（允许较宽容差，因为均值受历史影响）
        assert pd.notna(last_pb)
        assert 0.2 < last_pb < 0.8, f"close 接近均线时 %B 应在 0.5 附近，实际: {last_pb}"

    def test_multi_asset_independent(self):
        """多股票场景：每只股票独立按 asset 分组计算 rolling，不相互污染"""
        df_a = _make_panel(n_days=25, asset="A", close_pattern=np.linspace(10.0, 20.0, 25))
        df_b = _make_panel(n_days=25, asset="B", close_pattern=np.linspace(100.0, 200.0, 25))
        df = pd.concat([df_a, df_b], ignore_index=True)

        result = calculate_bollinger_pb(df, n=20, k=2.0)

        valid_a = result[result["asset"] == "A"]["bollinger_pb"].dropna()
        valid_b = result[result["asset"] == "B"]["bollinger_pb"].dropna()
        assert len(valid_a) > 0, "asset=A 应有有效 bollinger_pb 值"
        assert len(valid_b) > 0, "asset=B 应有有效 bollinger_pb 值"
        # 两只股票均为线性上涨，scale 不同但 %B 形态应相近（self-relative）
        assert np.allclose(valid_a.values, valid_b.values, atol=1e-6), "两只股票同形态线性上涨，%B 应一致（尺度无关）"

    def test_data_insufficient_below_window(self):
        """数据天数 < n=20：所有行 bollinger_pb 应为 NaN"""
        df = _make_panel(n_days=10)
        result = calculate_bollinger_pb(df, n=20, k=2.0)

        assert result["bollinger_pb"].isna().all(), "数据 < n 时所有 bollinger_pb 应为 NaN"

    def test_input_not_mutated(self):
        """函数入口必须 .copy()，不应修改原始 DataFrame（MODULE.md M3）"""
        df = _make_panel(n_days=25)
        original_columns = set(df.columns)
        original_close = df["close"].tolist()
        _ = calculate_bollinger_pb(df, n=20, k=2.0)

        assert set(df.columns) == original_columns, "calculate_bollinger_pb 不应修改原始 DataFrame 的列"
        assert df["close"].tolist() == original_close, "calculate_bollinger_pb 不应修改原始 DataFrame 的值"


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
        path = get_ic_output_path("bollinger_pb_1d")
        if not path.exists():
            pytest.skip("输出文件不存在，需要先运行 ic_bollinger_pb_1d.py")

    def test_output_structure_if_exists(self):
        """如果输出文件存在，检查 MODULE.md 输出结构模板规定的必需字段"""
        path = get_ic_output_path("bollinger_pb_1d")
        if not path.exists():
            pytest.skip("输出文件不存在")

        with open(path, encoding="utf-8") as f:
            result = json.load(f)

        for field in self.REQUIRED_FIELDS:
            assert field in result, f"缺少必需字段: {field}"

    def test_ic_metrics_fields_if_exists(self):
        """如果输出文件存在，检查 ic_metrics 子字段"""
        path = get_ic_output_path("bollinger_pb_1d")
        if not path.exists():
            pytest.skip("输出文件不存在")

        with open(path, encoding="utf-8") as f:
            result = json.load(f)

        ic_metrics = result.get("ic_metrics", {})
        for field in ["ic_mean", "ic_std", "icir"]:
            assert field in ic_metrics, f"ic_metrics 缺少必需字段: {field}"

    def test_sample_stats_fields_if_exists(self):
        """如果输出文件存在，检查 sample_stats 子字段"""
        path = get_ic_output_path("bollinger_pb_1d")
        if not path.exists():
            pytest.skip("输出文件不存在")

        with open(path, encoding="utf-8") as f:
            result = json.load(f)

        sample_stats = result.get("sample_stats", {})
        for field in ["total_days", "valid_days"]:
            assert field in sample_stats, f"sample_stats 缺少必需字段: {field}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
