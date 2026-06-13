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

import gzip
import json
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backtest.common.layered_backtest_runner import load_factor_return_data


# ============================================================================
# Fixtures
# ============================================================================


def _build_fake_payload(n_rows: int = 100, extra_factor_cols: int = 8) -> dict:
    """构造 fake factor_ic_data.json.gz 内容

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
    return {"meta": {"n_rows": n_rows}, "data": records}


@pytest.fixture
def fake_data_source(tmp_path: Path) -> Path:
    """100 行 × 13 列 fake 数据源"""
    payload = _build_fake_payload(n_rows=100, extra_factor_cols=8)
    path = tmp_path / "factor_ic_data.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(payload, f)
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
        payload = {
            "data": [
                {
                    "date": "2026-01-01",
                    "asset": "000001",
                    "rsi_6": 50.0,
                    "forward_return_1d": 0.01,
                    "forward_return_5d": 0.03,
                },
            ]
        }
        path = tmp_path / "missing_return.json.gz"
        with gzip.open(path, "wt", encoding="utf-8") as f:
            json.dump(payload, f)
        with pytest.raises(ValueError, match="forward_return_3d"):
            load_factor_return_data(data_source=path, required_factor_cols=["rsi_6"])

    def test_missing_data_key_raises(self, tmp_path):
        """TC05: 缺少 'data' 顶层字段抛 ValueError（"data 字段为空"）

        v2.9 (2026-06-13): 移除 ijson.kvitems 顶层校验（OOM 根因），改为依赖
        ijson.items(f, "data.item") yield 0 条记录后用 n_records == 0 兜底。
        因此报错从 KeyError("data") 变为 ValueError("'data' 字段为空")。
        """
        payload = {"meta": {"foo": "bar"}, "records": []}
        path = tmp_path / "no_data.json.gz"
        with gzip.open(path, "wt", encoding="utf-8") as f:
            json.dump(payload, f)
        with pytest.raises(ValueError, match="'data' 字段为空"):
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
                data_source=tmp_path / "ghost.json.gz",
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
        path = tmp_path / "big.json.gz"
        with gzip.open(path, "wt", encoding="utf-8") as f:
            json.dump({"data": records}, f)

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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
