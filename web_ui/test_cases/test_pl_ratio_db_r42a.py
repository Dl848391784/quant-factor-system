"""v0.4.8 R42a 单元测试: selection_date = master 最晚日时,优雅跳过而非 IndexError.

karpathy §18.1f v1.5.12 程序性 5 步: 改算法后新测试必含真实 parquet 验证, 不只 mock.
§18.2f 反模式 #2: 沙箱无 pyarrow, 必用项目 venv.

测试场景:
1. n_recent_dates=12, master parquet 最晚日 = selection_date → 不抛 IndexError
2. 返回结果不含最晚日 selection_date (07-06)
3. 返回的 dates 列表长度 < n_recent_dates (因为最晚日被跳过)
"""

from __future__ import annotations

import logging

import pytest
from web_ui.common.pl_ratio_db import (
    _MASTER_PARQUET_PATH,
    _SEGMENT_STOCK_DETAILS_PATH,
    load_pl_ratio_trend,
)


@pytest.mark.skipif(
    not _SEGMENT_STOCK_DETAILS_PATH.exists() or not _MASTER_PARQUET_PATH.exists(),
    reason="parquet 缺失, 跳过实测",
)
def test_load_pl_ratio_trend_no_indexerror_when_latest_selection_date():
    """R42a: selection_date = master 最晚日时, 显式守卫优雅跳过, 不抛 IndexError.

    真实数据: ssd selection_date 含 2026-07-06 (master 最晚日), 不应抛异常.
    """
    logger = logging.getLogger(__name__)
    # n_recent_dates=12 让 recent_dates 包含 ssd 最晚日 (2026-07-06)
    # master 最晚日也是 2026-07-06, idx+1 越界
    result = load_pl_ratio_trend(n_recent_dates=12, logger=logger)

    # 断言 1: 不抛 IndexError (主路径 try/except 已兜住, 这里再次确认无异常)
    assert result is not None, "n_recent_dates=12 应有至少一天有效日期"

    # 断言 2: 返回的 dates 不含 master 最晚日 (被守卫跳过)
    assert "07-06" not in result["dates"], (
        f"2026-07-06 = master 最晚日, 应被守卫跳过, 不应在 dates 里; 实际 dates={result['dates']}"
    )

    # 断言 3: dates 长度 < 12 (因为最晚日被跳过, 实际 10-11 天)
    assert len(result["dates"]) < 12, (
        f"dates 长度应 < 12 (07-06 被跳过), 实际 {len(result['dates'])}: {result['dates']}"
    )

    # 断言 4: 30 段 × N 天 结构完整
    assert len(result["segments"]) == 30
    for seg in result["segments"]:
        assert len(seg["pl_ratios"]) == len(result["dates"])


def test_load_pl_ratio_trend_handles_idx_plus_one_overflow(tmp_path, monkeypatch):
    """R42a 单元测试: 模拟 master_dates 只有一个日期 (idx+1 必越界), 验证守卫.

    不依赖真实 parquet, 用 tmp_path + monkeypatch 隔离.
    """
    import pandas as pd
    from web_ui.common import pl_ratio_db as mod

    # 准备 ssd (含 2 个 selection_date, 但 master 只有 1 个日期)
    ssd_path = tmp_path / "ssd.parquet"
    ssd_df = pd.DataFrame(
        {
            "selection_date": ["2026-01-01", "2026-01-02"],
            "segment_label": ["S1", "S1"],
            "asset": ["000001", "000002"],
            "weight_method": ["rolling_icir_weight", "rolling_icir_weight"],
        }
    )
    ssd_df.to_parquet(ssd_path)

    master_path = tmp_path / "master.parquet"
    master_df = pd.DataFrame(
        {
            "date": ["2026-01-01"],  # 只有 1 个日期
            "asset": ["000001"],
            "forward_return_1d": [0.05],
        }
    )
    master_df.to_parquet(master_path)

    monkeypatch.setattr(mod, "_SEGMENT_STOCK_DETAILS_PATH", ssd_path)
    monkeypatch.setattr(mod, "_MASTER_PARQUET_PATH", master_path)

    result = load_pl_ratio_trend(n_recent_dates=12, logger=logging.getLogger(__name__))

    # 断言: 2026-01-02 被守卫跳过, 只剩 2026-01-01 (T+1 不存在, 也被跳过)
    # 所以 valid_dates_mmdd 为空 → 返回 None
    assert result is None, f"master 只有 1 日, T+1 全空, 应返回 None; 实际 result={result}"
