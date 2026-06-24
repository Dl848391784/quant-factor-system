"""
方向统一化测试用例

遵循 MODULE.md M56 规则 (v2.47)：
- 反向因子 (ic_mean<0) 标准化值取反，对齐到正向语义
- direction_map 记录因子原始 IC 方向
- flipped_factors 记录被取反的反向因子列表（v2.47 含义反转）

测试范围：
1. 反向因子取反验证
2. 正向因子保持不变验证
3. ic_mean 缺失 (unknown) 处理
4. ic_mean = 0 按正向处理（保持不变）
5. 全正向因子场景
6. 全反向因子场景
7. JSON 输出 direction_map/flipped_fields 存在性
8. stock_selector 方向统一化一致性

创建日期: 2026-06-10
v2.47 更新: 2026-06-23 方向语义对齐到 positive (designs/direction_align_to_positive_v247.md)
"""

import numpy as np
import pandas as pd
import pytest


# ============================================================================
# 辅助函数：模拟方向统一化逻辑 (v2.47)
# ============================================================================


def apply_direction_unification(
    factor_df: pd.DataFrame,
    factor_cols: list[str],
    factor_list: list[str],
    ic_results: dict[str, dict],
) -> tuple[pd.DataFrame, dict[str, str], list[str]]:
    """模拟 composite_runner.py Step 5 方向统一化逻辑 (v2.47)

    Args:
        factor_df: 含 *_std 列的 DataFrame
        factor_cols: 因子列名列表
        factor_list: 因子逻辑名列表
        ic_results: IC 结果字典 {factor_name: {ic_mean: float}}

    Returns:
        (factor_df, direction_map, flipped_factors)
    """
    direction_map = {}
    flipped_factors = []

    for i, col in enumerate(factor_cols):
        factor_name = factor_list[i] if i < len(factor_list) else col
        ic_info = ic_results.get(factor_name, {})
        ic_mean_val = ic_info.get("ic_mean", None)

        std_col = f"{col}_std"

        if ic_mean_val is None:
            direction_map[factor_name] = "unknown"
            continue

        # v2.47: 反向因子（ic_mean<0）取反，对齐到正向语义
        if ic_mean_val < 0:
            direction_map[factor_name] = "negative"
            factor_df[std_col] = -factor_df[std_col]
            flipped_factors.append(factor_name)
        else:
            direction_map[factor_name] = "positive"

    return factor_df, direction_map, flipped_factors


# ============================================================================
# 测试用例
# ============================================================================


class TestDirectionUnification:
    """方向统一化核心逻辑测试 (v2.47)"""

    def _make_factor_df(self, n_stocks: int = 5) -> pd.DataFrame:
        """构造含 *_std 列的测试 DataFrame"""
        dates = pd.date_range("2024-01-01", periods=3, freq="D")
        assets = [f"SH{i:06d}" for i in range(n_stocks)]
        rows = []
        for date in dates:
            for asset in assets:
                rows.append(
                    {
                        "date": date,
                        "asset": asset,
                        "neg_factor_std": np.random.randn(),  # 反向因子标准化值
                        "pos_factor_std": np.random.randn(),  # 正向因子标准化值
                    }
                )
        return pd.DataFrame(rows)

    def test_negative_factor_flipped(self):
        """v2.47 M56 核心测试: 反向因子标准化值取反对齐到正向"""
        df = self._make_factor_df()
        original_neg_values = df["neg_factor_std"].copy()

        ic_results = {
            "neg_factor": {"ic_mean": -0.05},
            "pos_factor": {"ic_mean": 0.03},
        }

        df, direction_map, flipped_factors = apply_direction_unification(
            df,
            ["neg_factor", "pos_factor"],
            ["neg_factor", "pos_factor"],
            ic_results,
        )

        # v2.47: 反向因子取反
        assert "neg_factor" in flipped_factors
        pd.testing.assert_series_equal(
            df["neg_factor_std"],
            -original_neg_values,
            check_names=False,
        )
        assert direction_map["neg_factor"] == "negative"

    def test_positive_factor_unchanged(self):
        """v2.47 M56: 正向因子标准化值保持不变"""
        df = self._make_factor_df()
        original_pos_values = df["pos_factor_std"].copy()

        ic_results = {
            "neg_factor": {"ic_mean": -0.05},
            "pos_factor": {"ic_mean": 0.03},
        }

        df, direction_map, flipped_factors = apply_direction_unification(
            df,
            ["neg_factor", "pos_factor"],
            ["neg_factor", "pos_factor"],
            ic_results,
        )

        # v2.47: 正向因子不变
        assert "pos_factor" not in flipped_factors
        pd.testing.assert_series_equal(
            df["pos_factor_std"],
            original_pos_values,
            check_names=False,
        )
        assert direction_map["pos_factor"] == "positive"

    def test_ic_mean_missing_unknown(self):
        """M56: ic_mean 缺失 → direction='unknown'，保持原值"""
        df = self._make_factor_df()
        original_values = df["pos_factor_std"].copy()

        ic_results = {
            "neg_factor": {"ic_mean": -0.05},
            "pos_factor": {},  # ic_mean 缺失
        }

        df, direction_map, flipped_factors = apply_direction_unification(
            df,
            ["neg_factor", "pos_factor"],
            ["neg_factor", "pos_factor"],
            ic_results,
        )

        # 缺失因子保持原值
        assert direction_map["pos_factor"] == "unknown"
        assert "pos_factor" not in flipped_factors
        pd.testing.assert_series_equal(
            df["pos_factor_std"],
            original_values,
            check_names=False,
        )

    def test_ic_mean_zero_positive(self):
        """v2.47 M56: ic_mean=0 按正向处理（保持不变）"""
        df = self._make_factor_df()
        original_values = df["pos_factor_std"].copy()

        ic_results = {
            "pos_factor": {"ic_mean": 0.0},
        }

        df, direction_map, flipped_factors = apply_direction_unification(
            df,
            ["pos_factor"],
            ["pos_factor"],
            ic_results,
        )

        # v2.47: ic_mean=0 不触发取反（归正向）
        assert direction_map["pos_factor"] == "positive"
        assert "pos_factor" not in flipped_factors
        pd.testing.assert_series_equal(
            df["pos_factor_std"],
            original_values,
            check_names=False,
        )

    def test_all_positive_factors(self):
        """v2.47 M56: 全正向因子 → 无取反操作"""
        df = pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=3, freq="D").repeat(5),
                "asset": [f"SH{i:06d}" for i in range(5)] * 3,
                "factor_a_std": [1.0, 2.0, 0.5, -1.0, 0.3, 0.8, 1.5, 0.2, -0.5, 0.4, 0.6, 1.2, 0.1, -0.8, 0.5],
                "factor_b_std": [-0.5, 1.0, 0.3, 2.0, -1.5, 0.4, 0.7, 1.2, 0.1, -0.8, 0.5, 0.6, 1.2, 0.1, -0.8],
            }
        )

        ic_results = {
            "factor_a": {"ic_mean": 0.04},
            "factor_b": {"ic_mean": 0.06},
        }

        df, direction_map, flipped_factors = apply_direction_unification(
            df,
            ["factor_a", "factor_b"],
            ["factor_a", "factor_b"],
            ic_results,
        )

        # v2.47: 全部正向 → 不取反
        assert len(flipped_factors) == 0
        assert direction_map["factor_a"] == "positive"
        assert direction_map["factor_b"] == "positive"

    def test_all_negative_factors(self):
        """v2.47 M56: 全反向因子 → 全部取反对齐到正向"""
        df = pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=3, freq="D").repeat(5),
                "asset": [f"SH{i:06d}" for i in range(5)] * 3,
                "factor_a_std": [1.0, 2.0, 0.5, -1.0, 0.3] * 3,
                "factor_b_std": [-0.5, 1.0, 0.3, 2.0, -1.5] * 3,
            }
        )

        ic_results = {
            "factor_a": {"ic_mean": -0.04},
            "factor_b": {"ic_mean": -0.06},
        }

        df, direction_map, flipped_factors = apply_direction_unification(
            df,
            ["factor_a", "factor_b"],
            ["factor_a", "factor_b"],
            ic_results,
        )

        # v2.47: 全部反向 → 全部取反
        assert len(flipped_factors) == 2
        assert direction_map["factor_a"] == "negative"
        assert direction_map["factor_b"] == "negative"


class TestDirectionUnificationJSONOutput:
    """M56 Verify: JSON 输出 direction_map/flipped_factors 存在性"""

    def test_composite_json_has_direction_fields(self):
        """检查 composite JSON 输出含 direction_map 和 flipped_factors（兼容旧数据）"""
        import json
        from pathlib import Path

        result_dir = Path(__file__).parent.parent / "result"
        composite_files = list(result_dir.glob("composite_*_1d.json"))
        if not composite_files:
            pytest.skip("无 composite 结果文件，跳过 JSON 输出测试")
        for composite_file in composite_files:
            with open(composite_file, encoding="utf-8") as f:
                data = json.load(f)
            config = data.get("config", {})
            # equal_weight 不依赖 IC 数据，旧版输出可能缺少 direction_map
            # 新版输出（icir/ic/rolling_icir）必须包含这两个字段
            weight_method = data.get("meta", {}).get("weight_method", "")
            if weight_method == "equal_weight":
                # 等权方法兼容旧数据：允许缺少 direction_map
                continue
            assert "direction_map" in config, f"{composite_file.name}: config 缺少 direction_map 字段"
            assert "flipped_factors" in config, f"{composite_file.name}: config 缺少 flipped_factors 字段"
            assert isinstance(config["direction_map"], dict), f"{composite_file.name}: direction_map 应为 dict"
            assert isinstance(config["flipped_factors"], list), f"{composite_file.name}: flipped_factors 应为 list"

    def test_direction_map_values_valid(self):
        """direction_map 中每个值应为 negative/positive/unknown"""
        import json
        from pathlib import Path

        result_dir = Path(__file__).parent.parent / "result"
        composite_files = list(result_dir.glob("composite_*_1d.json"))
        if not composite_files:
            pytest.skip("无 composite 结果文件")

        valid_directions = {"negative", "positive", "unknown"}
        for composite_file in composite_files:
            with open(composite_file, encoding="utf-8") as f:
                data = json.load(f)

            direction_map = data.get("config", {}).get("direction_map", {})
            for factor_name, direction in direction_map.items():
                assert direction in valid_directions, (
                    f"{composite_file.name}: factor {factor_name} 方向值 '{direction}' 不合法"
                )


class TestStockSelectorDirectionConsistency:
    """stock_selector 方向统一化一致性测试"""

    def test_stock_selector_parquet_has_direction_info(self):
        """stock_selector Parquet 数据集含方向统一化信息 (v3.7).

        v3.7 起 stock_selection_result.json 被 Parquet 分区数据集替代,
        见 designs/feat_stock_selection_history_parquet.md.
        """
        from pathlib import Path

        import pyarrow.compute as pc
        import pyarrow.dataset as pads

        result_dir = Path(__file__).parent.parent / "result"
        history_root = result_dir / "stock_selection_history"

        if not history_root.exists() or not any(history_root.iterdir()):
            pytest.skip("无 stock_selection_history Parquet 数据集，跳过")

        dataset = pads.dataset(str(history_root), partitioning="hive")
        # 最新分区
        partitions = sorted(
            p for p in history_root.iterdir() if p.is_dir() and p.name.startswith("selection_date=")
        )
        latest = partitions[-1].name.split("=", 1)[1]
        df = dataset.to_table(filter=pc.field("selection_date") == latest).to_pandas()

        assert "factor_direction" in df.columns, "Parquet 数据集缺少 factor_direction 列"
        assert df["factor_direction"].notna().all(), "factor_direction 列含 null"
        valid_directions = {"positive", "negative"}
        assert set(df["factor_direction"].unique()).issubset(valid_directions), (
            f"factor_direction 值不合法: {df['factor_direction'].unique()}"
        )
