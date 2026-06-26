"""
write_selection_history Parquet 数据集写入测试 (v3.7).

设计依据: designs/feat_stock_selection_history_parquet.md §8.1.

测试覆盖:
- test_write_three_stages_basic: 三阶段各 30 行
- test_partition_key_correct: Hive 分区目录结构
- test_file_level_metadata_roundtrip: excluded_by_* 元数据 roundtrip
- test_rerun_same_date_overwrites_partition: 同日重跑覆盖
- test_single_stage_mode_only_stage3: enable_two_stage=False 只写 stage3
- test_excluded_at_stage3_field: Stage 2 有 Stage 3 没有的股票标记淘汰原因
- test_stage2_sort_value_populated: Stage 2 行带 stage2_sort_value
- test_no_json_file_written: 写入后不产生 stock_selection_result.json
- test_empty_input_raises: 三段全空抛 ValueError
"""

import json
from pathlib import Path

import pyarrow.compute as pc
import pyarrow.dataset as pads
import pyarrow.parquet as pq
import pytest
from stock_selector import StockSelectorConfig, write_selection_history


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def base_config(tmp_path: Path) -> StockSelectorConfig:
    """构造一个最小可用的 StockSelectorConfig (两阶段模式)."""
    return StockSelectorConfig(
        top_n=30,
        selection_date="2026-06-23",
        factor_direction="positive",
        rolling_window=60,
        return_period="1d",
        data_source=tmp_path / "fake_data.parquet",
        ic_result_dir=tmp_path,
        weight_result_path=tmp_path / "fake_weight.json",
        output_dir=tmp_path / "out",
        min_amplitude=0.01,
        enable_two_stage=True,
        stage1_pool_size=200,
        stage2_sort_col="turnover_rate",
        stage2_ascending=True,
    )


@pytest.fixture
def weight_config() -> dict:
    return {
        "best_selection": {
            "method": "rolling_icir_weight",
            "composite_score": 0.8137,
        },
    }


def _make_stock(rank: int, code: str, composite: float, **extra) -> dict:
    """构造一只测试股票 dict."""
    return {
        "rank": rank,
        "code": code,
        "composite_value": composite,
        "weight_coverage": 0.85,
        **extra,
    }


@pytest.fixture
def stage1_top() -> list[dict]:
    """30 只 Stage 1 候选, composite 降序."""
    return [_make_stock(i + 1, f"S1{i:04d}", 3.0 - i * 0.01) for i in range(30)]


@pytest.fixture
def stage2_top(stage1_top) -> list[dict]:
    """30 只 Stage 2 候选, 含 stage1_rank/stage2_sort_value."""
    # 模拟从 Stage 1 (200 只) 按 turnover_rate 升序取 30
    out = []
    for i in range(30):
        out.append(
            _make_stock(
                rank=i + 1,
                code=f"S2{i:04d}",
                composite=3.0 - i * 0.015,  # 不一定单调
                stage1_rank=140 - i,  # 模拟 Stage 1 中间名次
                stage2_sort_value=0.01 + i * 0.001,
            )
        )
    return out


@pytest.fixture
def stage3_top(stage2_top) -> list[dict]:
    """30 只 Stage 3 最终, 其中 20 只与 stage2 重合, 含 factor_values/decision_card."""
    out = []
    for i in range(30):
        # 前 20 只复用 stage2 的 code (模拟通过企稳过滤)
        # 后 10 只用新 code (模拟递补)
        if i < 20:
            code = f"S2{i:04d}"
            stage1_rank = 140 - i
        else:
            code = f"S3{i:04d}"
            stage1_rank = 50 + i
        out.append(
            _make_stock(
                rank=i + 1,
                code=code,
                composite=3.0 - i * 0.02,
                stage1_rank=stage1_rank,
                stage2_sort_value=0.01 + i * 0.001,
                factor_values={"rsi_6": 30.0, "volume_ratio_5": 1.2},
                factor_values_std={"rsi_6": -1.5, "volume_ratio_5": 0.3},
                decision_card={
                    "ret_5d": -0.03,
                    "vol_5d": 0.02,
                    "support_level": 10.5,
                },
            )
        )
    return out


# ============================================================================
# Tests
# ============================================================================


class TestWriteSelectionHistory:
    def test_write_three_stages_basic(self, base_config, weight_config, stage1_top, stage2_top, stage3_top):
        """写入后三阶段各 30 行, 总 90 行."""
        partition_dir = write_selection_history(
            stage1_top=stage1_top,
            stage2_top=stage2_top,
            stage3_top=stage3_top,
            config=base_config,
            weight_config=weight_config,
            selection_date="2026-06-23",
            stocks_on_date=2790,
            factor_list=["rsi", "volume_ratio"],
            factor_cols=["rsi_6", "volume_ratio_5"],
            direction_map={"rsi": "positive", "volume_ratio": "positive"},
            flipped_factors=[],
            exclusion_stats={
                "excluded_by_amplitude": 0,
                "excluded_by_coverage": 0,
                "excluded_by_liquidity": 0,
                "excluded_by_confirmation": 33,
                "excluded_by_filter": {"cum_return_5d_breakdown": 0},
                "min_weight_coverage": 0.5,
            },
            output_dir=base_config.output_dir,
        )

        # 分区目录存在
        assert partition_dir.is_dir()
        target = partition_dir / "part-0.parquet"
        assert target.exists()

        # 通过 dataset 读取 (Hive 分区会自动注入 selection_date 虚拟列)
        history_root = base_config.output_dir / "stock_selection_history"
        ds = pads.dataset(str(history_root), partitioning="hive")
        df = ds.to_table().to_pandas()
        assert len(df) == 90, f"期望 90 行 (3 stage × 30), 实际 {len(df)}"
        assert df.groupby("stage").size().to_dict() == {1: 30, 2: 30, 3: 30}
        # 分区键虚拟列存在
        assert (df["selection_date"] == "2026-06-23").all()

    def test_partition_key_correct(self, base_config, weight_config, stage1_top, stage2_top, stage3_top):
        """Hive 分区目录结构 selection_date=YYYY-MM-DD."""
        write_selection_history(
            stage1_top=stage1_top,
            stage2_top=stage2_top,
            stage3_top=stage3_top,
            config=base_config,
            weight_config=weight_config,
            selection_date="2026-06-23",
            stocks_on_date=2790,
            factor_list=[],
            factor_cols=[],
            direction_map={},
            flipped_factors=[],
            exclusion_stats={},
            output_dir=base_config.output_dir,
        )

        history_root = base_config.output_dir / "stock_selection_history"
        assert (history_root / "selection_date=2026-06-23").is_dir()

        # pyarrow.dataset 能正确识别 Hive 分区
        ds = pads.dataset(str(history_root), partitioning="hive")
        df = ds.to_table(filter=pc.field("selection_date") == "2026-06-23").to_pandas()
        assert (df["selection_date"] == "2026-06-23").all()

    def test_file_level_metadata_roundtrip(self, base_config, weight_config, stage1_top, stage2_top, stage3_top):
        """excluded_by_* 写入 file-level metadata 可读取还原."""
        exclusion_stats = {
            "excluded_by_amplitude": 5,
            "excluded_by_coverage": 12,
            "excluded_by_liquidity": 3,
            "excluded_by_confirmation": 33,
            "excluded_by_filter": {"cum_return_5d_breakdown": 7},
            "min_weight_coverage": 0.6,
        }
        partition_dir = write_selection_history(
            stage1_top=stage1_top,
            stage2_top=stage2_top,
            stage3_top=stage3_top,
            config=base_config,
            weight_config=weight_config,
            selection_date="2026-06-23",
            stocks_on_date=2790,
            factor_list=["rsi"],
            factor_cols=["rsi_6"],
            direction_map={},
            flipped_factors=[],
            exclusion_stats=exclusion_stats,
            output_dir=base_config.output_dir,
        )

        meta = pq.read_metadata(partition_dir / "part-0.parquet").metadata
        assert meta[b"excluded_by_amplitude"] == b"5"
        assert meta[b"excluded_by_coverage"] == b"12"
        assert meta[b"excluded_by_confirmation"] == b"33"
        assert meta[b"min_weight_coverage"] == b"0.6"
        assert meta[b"stocks_on_date"] == b"2790"
        # excluded_by_filter 是 JSON
        filter_data = json.loads(meta[b"excluded_by_filter"].decode("utf-8"))
        assert filter_data == {"cum_return_5d_breakdown": 7}
        # factor_list/factor_cols 也存在 file metadata
        assert json.loads(meta[b"factor_list_json"].decode("utf-8")) == ["rsi"]
        assert json.loads(meta[b"factor_cols_json"].decode("utf-8")) == ["rsi_6"]

    def test_rerun_same_date_overwrites_partition(self, base_config, weight_config, stage1_top, stage2_top, stage3_top):
        """同日重跑覆盖同分区, 其他分区不动."""
        # 第一次写 2026-06-22
        cfg_22 = base_config
        cfg_22.selection_date = "2026-06-22"
        write_selection_history(
            stage1_top=stage1_top,
            stage2_top=stage2_top,
            stage3_top=stage3_top,
            config=cfg_22,
            weight_config=weight_config,
            selection_date="2026-06-22",
            stocks_on_date=2790,
            factor_list=[],
            factor_cols=[],
            direction_map={},
            flipped_factors=[],
            exclusion_stats={},
            output_dir=base_config.output_dir,
        )
        path_22 = base_config.output_dir / "stock_selection_history" / "selection_date=2026-06-22" / "part-0.parquet"
        assert path_22.exists()
        size_22_before = path_22.stat().st_size

        # 第二次写 2026-06-23
        write_selection_history(
            stage1_top=stage1_top,
            stage2_top=stage2_top,
            stage3_top=stage3_top,
            config=base_config,
            weight_config=weight_config,
            selection_date="2026-06-23",
            stocks_on_date=2790,
            factor_list=[],
            factor_cols=[],
            direction_map={},
            flipped_factors=[],
            exclusion_stats={},
            output_dir=base_config.output_dir,
        )
        path_23 = base_config.output_dir / "stock_selection_history" / "selection_date=2026-06-23" / "part-0.parquet"
        assert path_23.exists()
        assert path_22.exists(), "其他分区不应被影响"
        assert path_22.stat().st_size == size_22_before, "其他分区文件大小不应变"

        # 第三次重写 2026-06-23 (覆盖), 用更少股票数据
        stage3_short = stage3_top[:10]
        for i, s in enumerate(stage3_short):
            s["rank"] = i + 1
        write_selection_history(
            stage1_top=stage1_top[:10],
            stage2_top=stage2_top[:10],
            stage3_top=stage3_short,
            config=base_config,
            weight_config=weight_config,
            selection_date="2026-06-23",
            stocks_on_date=2790,
            factor_list=[],
            factor_cols=[],
            direction_map={},
            flipped_factors=[],
            exclusion_stats={},
            output_dir=base_config.output_dir,
        )
        df_23 = pq.read_table(path_23).to_pandas()
        assert len(df_23) == 30, f"重跑后只剩 30 行 (10×3), 实际 {len(df_23)}"

    def test_single_stage_mode_only_stage3(self, base_config, weight_config, stage3_top, tmp_path):
        """enable_two_stage=False 时, stage1/stage2 传 [], 只归档 stage3."""
        cfg_single = StockSelectorConfig(
            top_n=30,
            selection_date="2026-06-23",
            factor_direction="positive",
            rolling_window=60,
            return_period="1d",
            data_source=tmp_path / "fake_data.parquet",
            ic_result_dir=tmp_path,
            weight_result_path=tmp_path / "fake_weight.json",
            output_dir=tmp_path / "out_single",
            min_amplitude=0.01,
            enable_two_stage=False,
        )
        partition_dir = write_selection_history(
            stage1_top=[],
            stage2_top=[],
            stage3_top=stage3_top,
            config=cfg_single,
            weight_config=weight_config,
            selection_date="2026-06-23",
            stocks_on_date=2790,
            factor_list=[],
            factor_cols=[],
            direction_map={},
            flipped_factors=[],
            exclusion_stats={},
            output_dir=cfg_single.output_dir,
        )
        df = pq.read_table(partition_dir / "part-0.parquet").to_pandas()
        assert len(df) == 30
        assert (df["stage"] == 3).all()
        # 单阶段模式 stage1_pool_size/stage2_sort_col/stage2_ascending 应为 null
        assert df["stage1_pool_size"].isna().all()
        assert df["stage2_sort_col"].isna().all()
        assert df["stage2_ascending"].isna().all()

    def test_excluded_at_stage3_field(self, base_config, weight_config, stage1_top, stage2_top, stage3_top):
        """Stage 2 中没进 Stage 3 的股票, excluded_at_stage3='stabilization'."""
        partition_dir = write_selection_history(
            stage1_top=stage1_top,
            stage2_top=stage2_top,
            stage3_top=stage3_top,
            config=base_config,
            weight_config=weight_config,
            selection_date="2026-06-23",
            stocks_on_date=2790,
            factor_list=[],
            factor_cols=[],
            direction_map={},
            flipped_factors=[],
            exclusion_stats={},
            output_dir=base_config.output_dir,
        )
        df = pq.read_table(partition_dir / "part-0.parquet").to_pandas()

        # fixture 设计: stage2 = S20000..S20029, stage3 前 20 只复用 S20000..S20019
        # 所以 Stage 2 中 S20020..S20029 这 10 只未进 Stage 3
        stage2_df = df[df["stage"] == 2]
        excluded = stage2_df[stage2_df["excluded_at_stage3"].notna()]
        assert len(excluded) == 10, f"期望 10 只 Stage 2 被 Stage 3 淘汰, 实际 {len(excluded)}"
        assert (excluded["excluded_at_stage3"] == "stabilization").all()

        # Stage 1 / Stage 3 行的 excluded_at_stage3 应为 null
        assert df[df["stage"] == 1]["excluded_at_stage3"].isna().all()
        assert df[df["stage"] == 3]["excluded_at_stage3"].isna().all()

    def test_stage2_sort_value_populated(self, base_config, weight_config, stage1_top, stage2_top, stage3_top):
        """Stage 2 行应带 stage2_sort_value, Stage 1 行不带."""
        partition_dir = write_selection_history(
            stage1_top=stage1_top,
            stage2_top=stage2_top,
            stage3_top=stage3_top,
            config=base_config,
            weight_config=weight_config,
            selection_date="2026-06-23",
            stocks_on_date=2790,
            factor_list=[],
            factor_cols=[],
            direction_map={},
            flipped_factors=[],
            exclusion_stats={},
            output_dir=base_config.output_dir,
        )
        df = pq.read_table(partition_dir / "part-0.parquet").to_pandas()

        # Stage 1 行 stage2_sort_value 全 null
        assert df[df["stage"] == 1]["stage2_sort_value"].isna().all()
        # Stage 2 行 stage2_sort_value 全有值
        assert df[df["stage"] == 2]["stage2_sort_value"].notna().all()

    def test_no_json_file_written(self, base_config, weight_config, stage1_top, stage2_top, stage3_top):
        """v3.7 防回归: 写入后输出目录不应产生 stock_selection_result.json."""
        write_selection_history(
            stage1_top=stage1_top,
            stage2_top=stage2_top,
            stage3_top=stage3_top,
            config=base_config,
            weight_config=weight_config,
            selection_date="2026-06-23",
            stocks_on_date=2790,
            factor_list=[],
            factor_cols=[],
            direction_map={},
            flipped_factors=[],
            exclusion_stats={},
            output_dir=base_config.output_dir,
        )
        json_path = base_config.output_dir / "stock_selection_result.json"
        assert not json_path.exists(), "v3.7 应不再生成 stock_selection_result.json"

    def test_empty_input_raises(self, base_config, weight_config):
        """三段全空抛 ValueError (契约: 至少要有 stage3)."""
        with pytest.raises(ValueError, match="没有行可写"):
            write_selection_history(
                stage1_top=[],
                stage2_top=[],
                stage3_top=[],
                config=base_config,
                weight_config=weight_config,
                selection_date="2026-06-23",
                stocks_on_date=2790,
                factor_list=[],
                factor_cols=[],
                direction_map={},
                flipped_factors=[],
                exclusion_stats={},
                output_dir=base_config.output_dir,
            )

    def test_rows_match_schema(self, base_config, weight_config, stage1_top, stage2_top, stage3_top):
        """读回的每行结构符合 comprehensive_factor/schemas/stock_selection_history.schema.json.

        合规性检查 (PROJECT.md 规则 #4: JSON Schema 校验输出).
        """
        import math

        import jsonschema

        schema_path = Path(__file__).parent.parent / "schemas" / "stock_selection_history.schema.json"
        with open(schema_path) as f:
            schema = json.load(f)

        write_selection_history(
            stage1_top=stage1_top,
            stage2_top=stage2_top,
            stage3_top=stage3_top,
            config=base_config,
            weight_config=weight_config,
            selection_date="2026-06-23",
            stocks_on_date=2790,
            factor_list=["rsi"],
            factor_cols=["rsi_6"],
            direction_map={"rsi": "positive"},
            flipped_factors=[],
            exclusion_stats={},
            output_dir=base_config.output_dir,
        )

        history_root = base_config.output_dir / "stock_selection_history"
        ds = pads.dataset(str(history_root), partitioning="hive")
        df = ds.to_table().to_pandas()

        validator = jsonschema.Draft7Validator(schema)
        for idx, row in df.iterrows():
            row_dict = {}
            for k, v in row.to_dict().items():
                # pandas NaN/NaT -> None (JSON Schema null)
                if v is None or (isinstance(v, float) and math.isnan(v)):
                    row_dict[k] = None
                elif hasattr(v, "isoformat"):  # Timestamp
                    row_dict[k] = v.isoformat()
                elif isinstance(v, bool):
                    row_dict[k] = bool(v)
                elif hasattr(v, "item"):  # numpy scalar
                    row_dict[k] = v.item()
                else:
                    row_dict[k] = v

            errors = sorted(validator.iter_errors(row_dict), key=lambda e: e.path)
            assert not errors, (
                f"Row {idx} (stage={row_dict['stage']}, rank={row_dict['rank']}) "
                f"违反 schema: {[e.message for e in errors]}"
            )
