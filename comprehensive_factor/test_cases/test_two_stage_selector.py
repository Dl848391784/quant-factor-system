"""Test apply_stage2_resort and two-stage selection in stock_selector (v2.44).

设计依据: designs/feat_two_stage_stock_selector_v244.md

覆盖:
1. apply_stage2_resort 基本逻辑 (升序/降序/缺列/NaN/asset 缺失)
2. StockSelectorConfig.validate() 两阶段校验 (stage1_pool_size > top_n*2)
3. 集成验证: enable_two_stage=True/False 行为差异
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("PYTHONHASHSEED", "0")

from comprehensive_factor.stock_selector import (  # noqa: E402
    StockSelectorConfig,
    apply_stage2_resort,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def silent_logger() -> logging.Logger:
    """安静的 logger, 避免 pytest 输出污染."""
    log = logging.getLogger("test_two_stage_selector")
    log.addHandler(logging.NullHandler())
    log.setLevel(logging.CRITICAL)
    return log


@pytest.fixture
def mock_stage1_stocks() -> list[dict]:
    """Stage 1 候选: 10 只股票, rank 已编号 1..10."""
    return [
        {"code": f"00000{i}" if i < 10 else f"0000{i}", "rank": i, "composite_score": -float(i)} for i in range(1, 11)
    ]


@pytest.fixture
def mock_factor_df_with_turnover() -> pd.DataFrame:
    """单日 factor DataFrame, 含 turnover_rate."""
    return pd.DataFrame(
        {
            "asset": [f"00000{i}" if i < 10 else f"0000{i}" for i in range(1, 11)],
            # turnover_rate: 倒序 (asset 1 高, asset 10 低)
            # 升序后 asset 10 排第一, asset 1 排末尾
            "turnover_rate": [10.0, 9.0, 8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0],
        }
    )


# ============================================================================
# 1. apply_stage2_resort 基本逻辑
# ============================================================================


class TestApplyStage2ResortBasic:
    """apply_stage2_resort 基本逻辑测试."""

    def test_ascending_sort_picks_lowest_turnover_first(
        self, mock_stage1_stocks, mock_factor_df_with_turnover, silent_logger
    ):
        """升序排序: turnover 最低的 asset 10 应该排第一."""
        result = apply_stage2_resort(
            mock_stage1_stocks,
            mock_factor_df_with_turnover,
            target_n=5,
            sort_col="turnover_rate",
            ascending=True,
            logger=silent_logger,
        )
        assert len(result) == 5
        # asset 10 turnover=1.0 最低, 升序第一
        assert result[0]["code"] == "000010"
        # 之后 asset 9, 8, 7, 6 (turnover 2..6)
        assert [s["code"] for s in result] == ["000010", "000009", "000008", "000007", "000006"]

    def test_descending_sort_picks_highest_turnover_first(
        self, mock_stage1_stocks, mock_factor_df_with_turnover, silent_logger
    ):
        """降序排序: turnover 最高的 asset 1 应该排第一."""
        result = apply_stage2_resort(
            mock_stage1_stocks,
            mock_factor_df_with_turnover,
            target_n=3,
            sort_col="turnover_rate",
            ascending=False,
            logger=silent_logger,
        )
        assert len(result) == 3
        assert [s["code"] for s in result] == ["000001", "000002", "000003"]

    def test_stage1_rank_preserved(self, mock_stage1_stocks, mock_factor_df_with_turnover, silent_logger):
        """重排后 stage1_rank 保留 Stage 1 名次, rank 重新编号 Stage 2."""
        result = apply_stage2_resort(
            mock_stage1_stocks,
            mock_factor_df_with_turnover,
            target_n=3,
            sort_col="turnover_rate",
            ascending=True,
            logger=silent_logger,
        )
        # asset 10 在 Stage 1 排第 10, Stage 2 排第 1
        assert result[0]["code"] == "000010"
        assert result[0]["stage1_rank"] == 10
        assert result[0]["rank"] == 1
        # asset 9 Stage 1 第 9, Stage 2 第 2
        assert result[1]["stage1_rank"] == 9
        assert result[1]["rank"] == 2

    def test_target_n_larger_than_stage1_returns_all(
        self, mock_stage1_stocks, mock_factor_df_with_turnover, silent_logger
    ):
        """target_n > stage1 长度时返回所有股票, 不报错."""
        result = apply_stage2_resort(
            mock_stage1_stocks,
            mock_factor_df_with_turnover,
            target_n=100,
            sort_col="turnover_rate",
            ascending=True,
            logger=silent_logger,
        )
        assert len(result) == 10  # 只有 10 只 Stage 1


# ============================================================================
# 2. 边界情况: 缺列 / NaN / asset 缺失
# ============================================================================


class TestApplyStage2ResortEdgeCases:
    """边界情况测试."""

    def test_missing_sort_col_falls_back_to_truncate(self, mock_stage1_stocks, silent_logger):
        """sort_col 不在 factor_df 时跳过重排, 直接截取 Stage 1 前 N 只."""
        factor_df = pd.DataFrame({"asset": ["000001"], "other_col": [1.0]})
        result = apply_stage2_resort(
            mock_stage1_stocks,
            factor_df,
            target_n=5,
            sort_col="turnover_rate",  # 不存在
            ascending=True,
            logger=silent_logger,
        )
        # 应直接返回 Stage 1 前 5 只, 不报错
        assert len(result) == 5
        assert [s["code"] for s in result] == [f"00000{i}" for i in range(1, 6)]

    def test_empty_stage1_returns_empty(self, silent_logger):
        """空 Stage 1 返回空列表, 不报错."""
        factor_df = pd.DataFrame({"asset": [], "turnover_rate": []})
        result = apply_stage2_resort(
            [],
            factor_df,
            target_n=10,
            sort_col="turnover_rate",
            ascending=True,
            logger=silent_logger,
        )
        assert result == []

    def test_nan_values_sink_to_bottom_ascending(self, silent_logger):
        """升序时 NaN 值排到末尾, 不会污染前列."""
        stage1 = [
            {"code": "A", "rank": 1},
            {"code": "B", "rank": 2},
            {"code": "C", "rank": 3},
            {"code": "D", "rank": 4},
        ]
        factor_df = pd.DataFrame(
            {
                "asset": ["A", "B", "C", "D"],
                "turnover_rate": [5.0, np.nan, 1.0, 3.0],
            }
        )
        result = apply_stage2_resort(
            stage1,
            factor_df,
            target_n=3,
            sort_col="turnover_rate",
            ascending=True,
            logger=silent_logger,
        )
        # 升序: C(1.0), D(3.0), A(5.0), B(NaN→末尾)
        assert [s["code"] for s in result] == ["C", "D", "A"]
        assert "B" not in [s["code"] for s in result]

    def test_asset_not_in_factor_df_sinks_to_bottom(self, silent_logger):
        """stage1 stock 不在 factor_df 时按 sentinel 处理, 排末尾."""
        stage1 = [
            {"code": "A", "rank": 1},
            {"code": "B", "rank": 2},
            {"code": "UNKNOWN", "rank": 3},  # 不在 factor_df
        ]
        factor_df = pd.DataFrame(
            {
                "asset": ["A", "B"],
                "turnover_rate": [5.0, 1.0],
            }
        )
        result = apply_stage2_resort(
            stage1,
            factor_df,
            target_n=3,
            sort_col="turnover_rate",
            ascending=True,
            logger=silent_logger,
        )
        # 升序: B(1.0), A(5.0), UNKNOWN(sentinel→末尾)
        assert [s["code"] for s in result] == ["B", "A", "UNKNOWN"]


# ============================================================================
# 3. StockSelectorConfig 校验
# ============================================================================


class TestStockSelectorConfigTwoStageValidation:
    """StockSelectorConfig.validate() 两阶段配置校验."""

    def test_default_config_passes(self):
        """默认配置 (top_n=30, stage1_pool_size=200) 应通过校验."""
        config = StockSelectorConfig(top_n=30)
        config.validate()  # 不抛异常
        assert config.enable_two_stage is True
        assert config.stage1_pool_size == 200
        assert config.stage2_sort_col == "turnover_rate"
        assert config.stage2_ascending is True

    def test_stage1_too_small_raises(self):
        """stage1_pool_size <= top_n*2 时校验失败 (两阶段退化)."""
        config = StockSelectorConfig(top_n=30, stage1_pool_size=60)
        with pytest.raises(ValueError, match="stage1_pool_size .* 必须 > top_n.2"):
            config.validate()

    def test_disabled_two_stage_skips_check(self):
        """enable_two_stage=False 时跳过两阶段校验, 不抛异常."""
        config = StockSelectorConfig(top_n=30, enable_two_stage=False, stage1_pool_size=10)
        config.validate()  # 不应抛异常

    def test_overheat_filter_defaults(self):
        """v3.9.1: 过热过滤参数默认值校验 (彻底数据驱动)."""
        config = StockSelectorConfig()
        assert config.enable_overheat_filter is True
        assert config.overheat_calibrate_min_pvalue == 0.05
        assert config.overheat_calibrate_grid == (0.5, 0.6, 0.7, 0.8, 0.9)


# ============================================================================
# 4. OOS 实证守门 (回归测试): 防止默认参数被静默改坏
# ============================================================================


class TestTwoStageDefaults:
    """默认参数回归守门 (designs/feat_two_stage_stock_selector_v244.md §3.2)."""

    def test_default_stage1_pool_size_is_200(self):
        """OOS 测试得到的最优 stage1_pool_size=200, 不可静默改动."""
        config = StockSelectorConfig()
        assert config.stage1_pool_size == 200, (
            "stage1_pool_size 默认值改动需更新 design 并重做 OOS 验证 "
            "(designs/feat_two_stage_stock_selector_v244.md §2.2)"
        )

    def test_default_stage2_sort_is_turnover_ascending(self):
        """OOS 测试 5 候选, turnover_rate 升序最稳健 (IS→OOS 衰减仅 4pp)."""
        config = StockSelectorConfig()
        assert config.stage2_sort_col == "turnover_rate"
        assert config.stage2_ascending is True
