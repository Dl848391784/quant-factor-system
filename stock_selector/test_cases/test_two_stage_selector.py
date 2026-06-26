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

from stock_selector import (  # noqa: E402
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
        """v3.11: LR 数据驱动过滤参数默认值校验 (已启用, 548 天训练数据, AUC=0.573)."""
        config = StockSelectorConfig()
        assert config.enable_overheat_filter is True  # v3.13: LR 打分排序, 不截断, 全部输出
        assert config.lr_min_training_days == 90  # v3.10: 最小训练天数
        assert config.lr_top_features == 10
        assert config.lr_train_window == 120
        assert config.lr_min_oos_auc == 0.55
        assert config.lr_filter_quantile == 0.3
        assert config.lr_bottom_pool_size == 90  # v3.10: Bottom90


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


# ============================================================================
# 5. v3.10: LR 训练数据持久化测试 (designs/feat_lr_training_data.md)
# ============================================================================


class TestSaveLrTrainingData:
    """save_lr_training_data + backfill_forward_return_1d 测试."""

    @pytest.fixture
    def mock_bottom90(self) -> list[dict]:
        """模拟 Bottom90 股票列表."""
        return [{"rank": i + 1, "code": f"{i:06d}", "composite_value": -2.0 + i * 0.01} for i in range(90)]

    @pytest.fixture
    def mock_factor_df(self) -> pd.DataFrame:
        """模拟当日全特征数据."""
        rng = np.random.RandomState(42)
        return pd.DataFrame(
            {
                "asset": [f"{i:06d}" for i in range(90)],
                "amplitude": rng.uniform(0.01, 0.15, 90),
                "rsi_6": rng.uniform(10, 90, 90),
                "turnover_rate": rng.uniform(0.001, 0.1, 90),
                "volume_ratio_5": rng.uniform(0.5, 3.0, 90),
                "close": rng.uniform(5, 50, 90),
                "volume": rng.uniform(1e6, 1e8, 90),
            }
        )

    @pytest.fixture
    def mock_weight_config(self) -> dict:
        """模拟权重配置."""
        return {
            "best_selection": {
                "method": "equal_weight",
                "composite_score": 0.75,
            },
            "meta": {
                "weight_meta": {
                    "last_day_weights": {
                        "amplitude": 0.15,
                        "rsi_6": 0.10,
                        "turnover_rate": 0.08,
                        "volume_ratio_5": 0.05,
                    },
                },
            },
        }

    def test_save_basic(
        self,
        mock_bottom90: list[dict],
        mock_factor_df: pd.DataFrame,
        mock_weight_config: dict,
        silent_logger: logging.Logger,
        tmp_path: Path,
    ) -> None:
        """保存 90 行, 验证分区路径和行数."""
        # Monkey-patch LR_TRAINING_DATA_DIR to tmp_path
        import paths
        import pyarrow.parquet as pq

        original = paths.LR_TRAINING_DATA_DIR
        paths.LR_TRAINING_DATA_DIR = tmp_path / "lr_training_data"
        try:
            from stock_selector import save_lr_training_data

            config = StockSelectorConfig()
            partition_dir = save_lr_training_data(
                mock_bottom90,
                mock_factor_df,
                mock_weight_config,
                config,
                "2026-06-25",
                logger=silent_logger,
            )
            assert partition_dir is not None
            assert partition_dir.exists()
            assert "weight_method=equal_weight" in str(partition_dir)
            assert "selection_date=2026-06-25" in str(partition_dir)

            # 验证行数
            df = pq.read_table(partition_dir / "part-0.parquet").to_pandas()
            assert len(df) == 90
            assert "forward_return_1d" in df.columns
            assert df["forward_return_1d"].isna().all()  # 当天为 null
        finally:
            paths.LR_TRAINING_DATA_DIR = original

    def test_save_overwrite(
        self,
        mock_bottom90: list[dict],
        mock_factor_df: pd.DataFrame,
        mock_weight_config: dict,
        silent_logger: logging.Logger,
        tmp_path: Path,
    ) -> None:
        """同日重跑覆盖, 不产生重复."""
        import paths
        import pyarrow.parquet as pq

        original = paths.LR_TRAINING_DATA_DIR
        paths.LR_TRAINING_DATA_DIR = tmp_path / "lr_training_data"
        try:
            from stock_selector import save_lr_training_data

            config = StockSelectorConfig()
            save_lr_training_data(
                mock_bottom90,
                mock_factor_df,
                mock_weight_config,
                config,
                "2026-06-25",
                logger=silent_logger,
            )
            # 重跑
            save_lr_training_data(
                mock_bottom90,
                mock_factor_df,
                mock_weight_config,
                config,
                "2026-06-25",
                logger=silent_logger,
            )
            # 只有一个分区
            partition_dir = tmp_path / "lr_training_data" / "weight_method=equal_weight" / "selection_date=2026-06-25"
            df = pq.read_table(partition_dir / "part-0.parquet").to_pandas()
            assert len(df) == 90  # 不是 180
        finally:
            paths.LR_TRAINING_DATA_DIR = original

    def test_backfill_null(
        self,
        mock_bottom90: list[dict],
        mock_factor_df: pd.DataFrame,
        mock_weight_config: dict,
        silent_logger: logging.Logger,
        tmp_path: Path,
    ) -> None:
        """补写 forward_return_1d, null 被填充."""
        import paths
        import pyarrow.parquet as pq

        original = paths.LR_TRAINING_DATA_DIR
        paths.LR_TRAINING_DATA_DIR = tmp_path / "lr_training_data"
        try:
            from stock_selector import (
                backfill_forward_return_1d,
                save_lr_training_data,
            )

            config = StockSelectorConfig()
            save_lr_training_data(
                mock_bottom90,
                mock_factor_df,
                mock_weight_config,
                config,
                "2026-06-25",
                logger=silent_logger,
            )

            # 模拟 data_source (次日数据)
            data_source = tmp_path / "factor_ic_data.parquet"
            src_df = pd.DataFrame(
                {
                    "date": ["2026-06-25"] * 90,
                    "asset": [f"{i:06d}" for i in range(90)],
                    "forward_return_1d": np.random.uniform(-0.05, 0.05, 90),
                }
            )
            src_df.to_parquet(data_source, index=False)

            n = backfill_forward_return_1d(data_source, logger=silent_logger)
            assert n > 0

            partition_dir = tmp_path / "lr_training_data" / "weight_method=equal_weight" / "selection_date=2026-06-25"
            df = pq.read_table(partition_dir / "part-0.parquet").to_pandas()
            assert df["forward_return_1d"].notna().all()
        finally:
            paths.LR_TRAINING_DATA_DIR = original

    def test_backfill_no_null_skipped(
        self,
        mock_bottom90: list[dict],
        mock_factor_df: pd.DataFrame,
        mock_weight_config: dict,
        silent_logger: logging.Logger,
        tmp_path: Path,
    ) -> None:
        """已补写的分区不重复处理."""
        import paths

        original = paths.LR_TRAINING_DATA_DIR
        paths.LR_TRAINING_DATA_DIR = tmp_path / "lr_training_data"
        try:
            from stock_selector import (
                backfill_forward_return_1d,
                save_lr_training_data,
            )

            config = StockSelectorConfig()
            save_lr_training_data(
                mock_bottom90,
                mock_factor_df,
                mock_weight_config,
                config,
                "2026-06-25",
                logger=silent_logger,
            )

            data_source = tmp_path / "factor_ic_data.parquet"
            src_df = pd.DataFrame(
                {
                    "date": ["2026-06-25"] * 90,
                    "asset": [f"{i:06d}" for i in range(90)],
                    "forward_return_1d": np.random.uniform(-0.05, 0.05, 90),
                }
            )
            src_df.to_parquet(data_source, index=False)

            backfill_forward_return_1d(data_source, logger=silent_logger)
            # 第二次应返回 0 (已无 null)
            n = backfill_forward_return_1d(data_source, logger=silent_logger)
            assert n == 0
        finally:
            paths.LR_TRAINING_DATA_DIR = original
