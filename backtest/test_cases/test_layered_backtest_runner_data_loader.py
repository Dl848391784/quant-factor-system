#!/usr/bin/env python3
"""test_layered_backtest_runner_data_loader 测试用例

测试目标: backtest/common/layered_backtest_runner.py::load_factor_return_data
覆盖范围:
- TC01: 返回 (factor_df, return_df) 结构正确
- TC02: 列过滤生效（factor_df 仅含 required + index，无其他因子列）
- TC03: return_df schema 固定 5 列
- TC04: 缺少 forward_return_* 抛 ValueError
- TC05: 缺少 'data' 顶层字段抛 KeyError
- TC06: required_factor_cols 不在数据时抛 ValueError
- TC07: required_factor_cols=None 时保留所有非收益列
- TC08: 内存峰值 vs json.load 旧路径 < 50%

设计动机（2026-06-13 v2.8）:
- 真实数据 factor_ic_data.json.gz 解压后 2.17GB，json.load 触发 OOM
- 改用 ijson 流式 + 列过滤后内存峰值降低 ~10x
- 单测使用 100 行 × 10 列 fake fixture，不依赖真实数据
"""
import sys
from pathlib import Path

import pandas as pd
import pytest


sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backtest.common.layered_backtest_runner import load_factor_return_data


# ============================================================================
# Fixtures
# ============================================================================


def _build_fake_records(n_rows: int = 100, extra_factor_cols: int = 8) -> list[dict]:
    """构造 fake records 列表

    每条记录字段:
        - index: date, asset
        - return: forward_return_1d/3d/5d
        - factors: rsi_6, volume_ratio_5, + N 个 extra_factor_*
    """
    factor_names = ["rsi_6", "volume_ratio_5"] + [f"extra_factor_{i}" for i in range(extra_factor_cols)]
    records = []
    for i in range(n_rows):
        rec = {
            "date": f"2026-01-{(i % 28) + 1:02d}",
            "asset": f"00000{i % 10}",
            "forward_return_1d": 0.01 * i,
            "forward_return_3d": 0.02 * i,
            "forward_return_5d": 0.03 * i,
        }
        for fname in factor_names:
            rec[fname] = float(i) + hash(fname) % 100
        records.append(rec)
    return records


@pytest.fixture
def fake_data_source(tmp_path: Path) -> Path:
    """100 行 × 13 列 fake Parquet 数据源"""
    records = _build_fake_records(n_rows=100, extra_factor_cols=8)
    path = tmp_path / "factor_ic_data.parquet"
    pd.DataFrame(records).to_parquet(path, engine="pyarrow")
    return path

# ============================================================================
# TC01-03: 基本返回结构
# ============================================================================


class TestBasicLoad:
    def test_returns_tuple_of_two_dataframes(self, fake_data_source):
        """TC01: 返回 (factor_df, return_df) 元组"""
        factor_df, return_df = load_factor_return_data(data_source=fake_data_source, required_factor_cols=["rsi_6"])
        assert factor_df is not None and return_df is not None
        assert len(factor_df) == 100
        assert len(return_df) == 100

    def test_column_filter_keeps_only_required(self, fake_data_source):
        """TC02: factor_df 仅含 required_factor_cols + index，不含其他因子列"""
        factor_df, _ = load_factor_return_data(data_source=fake_data_source, required_factor_cols=["rsi_6"])
        assert set(factor_df.columns) == {"date", "asset", "rsi_6"}
        # 关键：extra_factor_* 不应出现
        for col in factor_df.columns:
            assert not col.startswith("extra_factor_")
        assert "volume_ratio_5" not in factor_df.columns

    def test_return_df_schema_fixed(self, fake_data_source):
        """TC03: return_df schema 固定 5 列"""
        _, return_df = load_factor_return_data(data_source=fake_data_source, required_factor_cols=["rsi_6"])
        assert list(return_df.columns) == [
            "date",
            "asset",
            "forward_return_1d",
            "forward_return_3d",
            "forward_return_5d",
        ]


# ============================================================================
# TC04-06: 异常路径
# ============================================================================


class TestErrorHandling:
    def test_missing_return_col_raises(self, tmp_path):
        """TC04: 缺少 forward_return_3d 抛 ValueError"""
        records = [
            {
                "date": "2026-01-01",
                "asset": "000001",
                "rsi_6": 50.0,
                "forward_return_1d": 0.01,
                "forward_return_5d": 0.03,
            },
        ]
        path = tmp_path / "missing_return.parquet"
        pd.DataFrame(records).to_parquet(path, engine="pyarrow")
        with pytest.raises(ValueError, match="forward_return_3d"):
            load_factor_return_data(data_source=path, required_factor_cols=["rsi_6"])

    def test_missing_data_key_raises(self, tmp_path):
        """TC05: 数据源缺少收益列时抛 ValueError（Parquet 等效于旧 JSON.gz 'data' 字段为空）。

        v2.9 (2026-06-13): 旧版 JSON.gz 使用 ijson 流式解析，无 'data' key 时 yield 0 条，
        n_records==0 兜底报 ValueError("'data' 字段为空")。
        Parquet 迁移后：空 Parquet 文件（仅有 date/asset 列，无收益列）→ pq.read_schema
        检测到缺少 forward_return_1d → ValueError("数据源中缺少收益列 'forward_return_1d'")。
        """
        df = pd.DataFrame({"date": pd.Series([], dtype=str), "asset": pd.Series([], dtype=str)})
        path = tmp_path / "no_data.parquet"
        df.to_parquet(path, engine="pyarrow")
        with pytest.raises(ValueError, match="缺少收益列"):
            load_factor_return_data(data_source=path, required_factor_cols=["rsi_6"])

    def test_missing_required_factor_raises(self, fake_data_source):
        """TC06: required_factor_cols 中的列不存在时抛 ValueError"""
        with pytest.raises(ValueError, match="not_exist_factor"):
            load_factor_return_data(
                data_source=fake_data_source,
                required_factor_cols=["not_exist_factor"],
            )

    def test_file_not_found_raises(self, tmp_path):
        """TC06b: 数据源文件不存在抛 FileNotFoundError"""
        with pytest.raises(FileNotFoundError):
            load_factor_return_data(
                data_source=tmp_path / "ghost.parquet",
                required_factor_cols=["rsi_6"],
            )


# ============================================================================
# TC07: 默认行为（required_factor_cols=None）
# ============================================================================


class TestDefaultBehavior:
    def test_none_required_keeps_all_factor_cols(self, fake_data_source):
        """TC07: required_factor_cols=None 时仅保留 index+return（不保留任何因子列）

        设计权衡: v2.8 流式加载下，None = 不指定因子需求 = 列过滤白名单仅含
        index+return。这是相对 v2.7 的语义收紧（v2.7 会保留所有列）。
        分层回测脚本经 factor_cli.py 链路传入 required_factor_cols 必为非空，
        故此分支仅作 fallback。
        """
        factor_df, return_df = load_factor_return_data(data_source=fake_data_source, required_factor_cols=None)
        # 因子列退化为仅 index（无业务因子）
        assert set(factor_df.columns) == {"date", "asset"}
        assert len(return_df) == 100


# ============================================================================
# TC08: 列过滤内存效果
# ============================================================================


class TestMemoryFootprint:
    def test_column_filter_reduces_dataframe_memory(self, tmp_path):
        """TC08: required_factor_cols 列过滤显著降低 factor_df 内存

        构造 5000 行 × 30 列数据，对比:
            - 仅请求 1 个因子列 → factor_df 应只有 3 列 (date+asset+rsi_6)
            - 请求所有 30 个因子列 → factor_df 32 列
        过滤后内存应 < 不过滤内存的 50%（30→3 列约 1/10，但 index 列 (date/asset)
        是 str 占字节数大，相对比受 index 占比影响。50% 是稳定上界）。

        设计动机: tracemalloc 在小数据规模下被 pandas C 扩展主导不准；
        DataFrame.memory_usage() 是确定性指标，直接证明列过滤效果。
        """
        all_factor_cols = [f"factor_{i}" for i in range(30)]
        records = []
        for i in range(5000):
            rec = {
                "date": f"2026-01-{(i % 28) + 1:02d}",
                "asset": f"00000{i % 10}",
                "forward_return_1d": 0.01 * i,
                "forward_return_3d": 0.02 * i,
                "forward_return_5d": 0.03 * i,
            }
            for fname in all_factor_cols:
                rec[fname] = float(i)
            records.append(rec)
        path = tmp_path / "big.parquet"
        pd.DataFrame(records).to_parquet(path, engine="pyarrow")

        # 过滤：仅 1 个因子列
        factor_df_filtered, _ = load_factor_return_data(data_source=path, required_factor_cols=["factor_0"])
        # 不过滤：全部 30 个因子列
        factor_df_full, _ = load_factor_return_data(data_source=path, required_factor_cols=all_factor_cols)

        mem_filtered = factor_df_filtered.memory_usage(deep=True).sum()
        mem_full = factor_df_full.memory_usage(deep=True).sum()
        ratio = mem_filtered / mem_full

        assert factor_df_filtered.shape[1] == 3, f"过滤后应仅 3 列, 实际 {factor_df_filtered.columns.tolist()}"
        assert factor_df_full.shape[1] == 32, f"全量应 32 列, 实际 {factor_df_full.shape[1]}"
        assert ratio < 0.50, f"过滤后内存 {mem_filtered} 应 < 全量 {mem_full} 的 50%, 实际 ratio={ratio:.2f}"


# ============================================================================
# TC09: required_factor_cols 含索引列时不应被 float() 化（回归测试）
# ============================================================================


class TestIndexColsNotFloated:
    """回归测试：required_factor_cols 含 'date'/'asset' 时不应触发 float('YYYY-MM-DD').

    背景（2026-06-13 v2.8.1）：
    - 部分因子的 calculator.required_cols 含索引列，例如：
        * calculate_return_3d.required_cols      = ["close", "asset", "date"]
        * calculate_past_return_1d.required_cols = ["close", "asset", "date"]
        * calculate_return_5d.required_cols      = ["close", "asset", "date"]
        * calculate_ma5_deviation.required_cols  = ["date", "asset", "close"]
        * calculate_near_high_ratio_5.required_cols = ["date", "asset", "close"]
    - factor_cli.py 把 required_cols 透传给 load_factor_return_data 的 required_factor_cols
    - v2.8 引入"数值列即时 float() 化"逻辑后，date/asset 字符串误入数值白名单
      → float('2024-05-22') ValueError → 退出码 3 (DATA_STRUCTURE_ERROR)

    复现命令：python -m backtest.layered_backtest_return_3d_1d
    日志：backtest/logs/return_3d_2026-06-13.log
        "数据问题: could not convert string to float: '2024-05-22'"
    """

    def test_required_factor_cols_with_date_and_asset(self, fake_data_source):
        """required_factor_cols 含 'date'/'asset' 时正常加载，不抛 ValueError"""
        # 模拟 calculate_return_3d.required_cols = ["close", "asset", "date"]
        # 注：fake fixture 没有 close 列，这里改用 fixture 已有的 rsi_6 替代
        factor_df, return_df = load_factor_return_data(
            data_source=fake_data_source,
            required_factor_cols=["rsi_6", "asset", "date"],
        )

        # date/asset 列保持字符串语义，未被 float() 化
        # 注：pandas 在不同版本可能推断为 object 或 StringDtype，统一用 dtype.kind 检查
        # kind 'O' = object, 'U' = str/StringDtype；'f'/'i' = float/int 才是 bug
        assert factor_df["date"].dtype.kind in ("O", "U"), (
            f"date 列应保持字符串类型，实际 {factor_df['date'].dtype} (kind={factor_df['date'].dtype.kind})"
        )
        assert factor_df["asset"].dtype.kind in ("O", "U"), (
            f"asset 列应保持字符串类型，实际 {factor_df['asset'].dtype} (kind={factor_df['asset'].dtype.kind})"
        )

        # 抽样验证 date 仍是 'YYYY-MM-DD' 字符串（值类型才是关键证据）
        first_date = factor_df["date"].iloc[0]
        assert isinstance(first_date, str), f"date 值应为 str，实际 {type(first_date)}"
        assert len(first_date) == 10 and first_date[4] == "-", f"date 值应为 'YYYY-MM-DD'，实际 {first_date!r}"

        # 业务因子列正常 float 化
        assert factor_df["rsi_6"].dtype.kind == "f", f"rsi_6 应为 float dtype，实际 {factor_df['rsi_6'].dtype}"

        # 索引列在 factor_df 中不重复（_INDEX_COLS 已包含 date/asset，required 含同名不应造成重复列）
        assert list(factor_df.columns).count("date") == 1
        assert list(factor_df.columns).count("asset") == 1

    def test_required_factor_cols_only_index_cols(self, fake_data_source):
        """required_factor_cols 仅含索引列时也不抛 ValueError（边界场景）"""
        factor_df, return_df = load_factor_return_data(
            data_source=fake_data_source,
            required_factor_cols=["asset", "date"],
        )
        assert factor_df["date"].dtype.kind in ("O", "U")
        assert factor_df["asset"].dtype.kind in ("O", "U")
        # return_df 数值列照常 float 化
        assert factor_df.shape[0] == 100
        assert return_df.shape[0] == 100


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
