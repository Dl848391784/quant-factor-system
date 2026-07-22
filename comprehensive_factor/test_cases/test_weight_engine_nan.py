"""weight_engine.py _apply_weights 缺失因子中性填充测试

测试 v1.17 修复：缺失因子 z-score 用 0 填充（=全市场平均），不做动态归一化
- v1.11/v1.14: NaN 动态权重归一化 → 缺失因子后放大剩余因子权重 → 排名虚高
- v1.17: 缺失因子 z=0 填充 → 视为"无信号=平均水平" → 不放大不惩罚 → 天然趋中

遵循 MODULE.md M29 规范（行 998-1030）

作者: 云瑶
创建日期: 2026-06-10
更新日期: 2026-06-11 (v1.17 中性填充策略)
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


# sys.path 处理（与其他 test_cases 一致）
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from comprehensive_factor.common.logger_config import get_logger  # noqa: E402
from comprehensive_factor.common.weight_engine import (  # noqa: E402
    EqualWeightMethod,
    ICIRWeightMethod,
    ICWeightMethod,
    WeightEngine,
)


_logger = get_logger(__name__)


class TestApplyWeightsNaNPropagation:
    """_apply_weights 缺失因子中性填充测试（遵循 MODULE.md M29 规范）"""

    def _build_factor_df(self, values_dict: dict[str, list]) -> pd.DataFrame:
        """构建测试用 factor_df（含 _std 列）"""
        df = pd.DataFrame()
        for col, vals in values_dict.items():
            df[f"{col}_std"] = vals
        return df

    def test_one_factor_all_nan_others_valid(self):
        """关键场景：5 因子中 1 个全 NaN，其他 4 个有值 → 综合因子应有有效值

        这是 2026-06-10 stock_selector 选股失败的根因场景：
        icir_weight 选中 turnover_surge（2026-06-09 全 NaN）+ 4 个有值因子
        v1.17: 缺失因子 z=0 填充 → 4因子正常参与 + 1因子被视为平均 → 综合因子有效
        """
        factor_cols = [
            "tail_price_volume_intensity",
            "tail_price_position",
            "amplitude",
            "momentum_strength",
            "turnover_surge",
        ]

        n = 10
        factor_df = self._build_factor_df(
            {
                "tail_price_volume_intensity": list(np.random.randn(n)),
                "tail_price_position": list(np.random.randn(n)),
                "amplitude": list(np.random.randn(n)),
                "momentum_strength": list(np.random.randn(n)),
                "turnover_surge": list(np.full(n, np.nan)),  # 全 NaN
            }
        )

        engine = ICIRWeightMethod(logger=_logger)
        # ICIR 加权需要 ic_results（提供 mock 数据）
        ic_results = {
            "tail_price_volume_intensity": {"icir": 0.23},
            "tail_price_position": {"icir": 0.35},
            "amplitude": {"icir": 0.16},
            "momentum_strength": {"icir": 0.11},
            "turnover_surge": {"icir": 0.15},
        }
        composite = engine.calculate(factor_df, factor_cols, ic_results=ic_results)

        # 核心断言：综合因子不应全 NaN
        valid_count = composite.notna().sum()
        assert valid_count == n, f"1因子全NaN + 4因子有值 → 应有{n}条有效值，实际{valid_count}"

    def test_two_factors_partial_nan(self):
        """部分因子在某些行 NaN → 这些行综合因子仍有效（缺失因子 z=0 填充）"""
        factor_cols = ["factor_a", "factor_b", "factor_c"]
        weights = {"factor_a": 0.5, "factor_b": 0.3, "factor_c": 0.2}

        factor_df = self._build_factor_df(
            {
                "factor_a": [1.0, np.nan, 3.0],  # 第2行 NaN → z=0 填充
                "factor_b": [2.0, -1.0, np.nan],  # 第3行 NaN → z=0 填充
                "factor_c": [0.5, 0.5, 0.5],  # 全部有值
            }
        )

        engine = EqualWeightMethod(logger=_logger)
        # EqualWeightMethod 用等权，但 _apply_weights 是公共方法
        # 直接调用 _apply_weights 来测试 NaN 处理
        composite = engine._apply_weights(factor_df, factor_cols, weights, _logger, "测试加权")

        # 第1行：3因子都有值 → 有效
        assert composite.iloc[0] is not np.nan and not pd.isna(composite.iloc[0])
        # 第2行：factor_a NaN → z=0 填充 → 2因子有值 + 1因子 z=0 → 有效
        assert composite.iloc[1] is not np.nan and not pd.isna(composite.iloc[1])
        # 第3行：factor_b NaN → z=0 填充 → 2因子有值 + 1因子 z=0 → 有效
        assert composite.iloc[2] is not np.nan and not pd.isna(composite.iloc[2])

    def test_all_factors_nan(self):
        """所有因子全 NaN → 综合因子应全 NaN（遵循 M29 规范）

        v1.17: fillna(0) 将全 NaN 行变为 0，但 all_nan_mask 检查确保仍输出 NaN
        """
        factor_cols = ["factor_a", "factor_b"]
        weights = {"factor_a": 0.6, "factor_b": 0.4}

        factor_df = self._build_factor_df(
            {
                "factor_a": [np.nan, np.nan],
                "factor_b": [np.nan, np.nan],
            }
        )

        engine = EqualWeightMethod(logger=_logger)
        composite = engine._apply_weights(factor_df, factor_cols, weights, _logger, "测试加权")

        # 全 NaN → composite 全 NaN
        assert composite.isna().all(), "所有因子全NaN → 综合因子应全NaN"

    def test_neutral_fill_no_amplification(self):
        """v1.17 核心特性：缺失因子 z=0 填充，不做归一化 → 不放大剩余因子

        v1.14旧逻辑: factor_a NaN → factor_b(0.3)+factor_c(0.2) 归一化到 0.6+0.4
                     composite = 1.0 * 0.6 + 2.0 * 0.4 = 1.4 (放大了！)
        v1.17新逻辑: factor_a NaN → z=0 填充 → 0*0.6 + 1.0*0.3 + 2.0*0.2 = 0.7 (不放大)
        """
        factor_cols = ["factor_a", "factor_b", "factor_c"]
        weights = {"factor_a": 0.6, "factor_b": 0.3, "factor_c": 0.2}

        # factor_a 全 NaN，factor_b=1.0, factor_c=2.0
        factor_df = self._build_factor_df(
            {
                "factor_a": [np.nan],
                "factor_b": [1.0],
                "factor_c": [2.0],
            }
        )

        engine = EqualWeightMethod(logger=_logger)
        composite = engine._apply_weights(factor_df, factor_cols, weights, _logger, "测试加权")

        # v1.17 期望: 0*0.6 + 1.0*0.3 + 2.0*0.2 = 0.3 + 0.4 = 0.7 (不放大)
        # v1.14 旧期望: 1.0*0.6 + 2.0*0.4 = 1.4 (归一化放大了1.4/0.7=2倍!)
        expected = 0 * 0.6 + 1.0 * 0.3 + 2.0 * 0.2  # = 0.7
        assert abs(composite.iloc[0] - expected) < 1e-10, f"中性填充(不归一化): 期望{expected}, 实际{composite.iloc[0]}"

    def test_missing_factor_naturally_moderates(self):
        """v1.17 核心特性：缺失因子后综合因子值自然趋中（隐性惩罚）

        对比：有 tail_factor 时综合因子更极端，缺失时自然趋中
        """
        factor_cols = ["factor_a", "factor_b", "tail_factor"]
        weights = {"factor_a": 0.3, "factor_b": 0.3, "tail_factor": 0.4}

        # 场景1：tail_factor 有极端负值 → 综合因子很负
        factor_df_extreme = self._build_factor_df(
            {
                "factor_a": [0.0],
                "factor_b": [0.0],
                "tail_factor": [-3.0],  # 极端负值
            }
        )

        # 场景2：tail_factor 缺失 → z=0 填充 → 综合因子趋中
        factor_df_missing = self._build_factor_df(
            {
                "factor_a": [0.0],
                "factor_b": [0.0],
                "tail_factor": [np.nan],  # 缺失 → z=0
            }
        )

        engine = EqualWeightMethod(logger=_logger)

        composite_extreme = engine._apply_weights(factor_df_extreme, factor_cols, weights, _logger, "测试加权")
        composite_missing = engine._apply_weights(factor_df_missing, factor_cols, weights, _logger, "测试加权")

        # 有极端因子: 0*0.3 + 0*0.3 + (-3)*0.4 = -1.2
        assert abs(composite_extreme.iloc[0] - (-1.2)) < 1e-10
        # 缺失因子: 0*0.3 + 0*0.3 + 0*0.4 = 0.0 (趋中，隐性惩罚)
        assert abs(composite_missing.iloc[0] - 0.0) < 1e-10

        # 关键验证：缺失因子的综合因子绝对值 < 有极端因子的绝对值
        assert abs(composite_missing.iloc[0]) < abs(composite_extreme.iloc[0]), (
            "缺失因子后综合因子应自然趋中（绝对值更小），不应放大"
        )

    def test_weight_engine_ic_weight_with_nan_factor(self):
        """WeightEngine ic_weight 方法：含 NaN 因子时综合因子有效"""
        factor_cols = ["amplitude", "turnover_surge", "momentum_strength"]

        factor_df = self._build_factor_df(
            {
                "amplitude": [1.0, -1.0, 0.5],
                "turnover_surge": [np.nan, np.nan, np.nan],  # 全 NaN
                "momentum_strength": [2.0, -2.0, 1.0],
            }
        )

        engine = WeightEngine(weight_method="ic_weight", logger=_logger)
        # ic_weight 需要 ic_results，用 mock 数据
        ic_results = {
            "amplitude": {"ic_mean": 0.05},
            "turnover_surge": {"ic_mean": 0.03},
            "momentum_strength": {"ic_mean": 0.04},
        }
        composite = engine.calculate(factor_df, factor_cols, ic_results=ic_results)

        valid_count = composite.notna().sum()
        assert valid_count == 3, f"ic_weight + 1因子全NaN → 应有3条有效值，实际{valid_count}"

    def test_incremental_data_factor_participation(self):
        """增量采集因子场景：有数据的日期正常参与，无数据的日期被视为平均

        模拟尾盘因子：前4行 tail_factor 全 NaN（数据未开始采集），后4行有值
        v1.17: 缺失因子 z=0 填充 → 前半行综合因子由 3 因子决定 + 1 因子 z=0
        后半行 4 因子全参与，综合因子更可能有极端值
        """
        factor_cols = ["amplitude", "turnover_surge", "momentum_strength", "tail_factor"]
        weights = {
            "amplitude": 0.3,
            "turnover_surge": 0.2,
            "momentum_strength": 0.2,
            "tail_factor": 0.3,
        }

        # 8只股票，前4行 tail_factor 全 NaN（增量数据未覆盖）
        factor_df = self._build_factor_df(
            {
                "amplitude": list(np.random.randn(8)),
                "turnover_surge": list(np.random.randn(8)),
                "momentum_strength": list(np.random.randn(8)),
                "tail_factor": [np.nan, np.nan, np.nan, np.nan, 1.0, -1.0, 0.5, 2.0],
            }
        )

        engine = EqualWeightMethod(logger=_logger)
        composite = engine._apply_weights(factor_df, factor_cols, weights, _logger, "测试加权")

        # 全部行应有有效值（3因子始终有值 + 1因子 z=0 填充）
        valid_count = composite.notna().sum()
        assert valid_count == 8, f"3因子始终有值 + 1因子前半NaN(z=0填充) → 应有8条有效值，实际{valid_count}"
