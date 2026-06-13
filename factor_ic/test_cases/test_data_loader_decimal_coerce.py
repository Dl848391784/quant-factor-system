#!/usr/bin/env python3
"""
data_loader Decimal 类型规范化测试

验证 load_factor_return_data 加载统一数据源后，OHLC 等数值列被正确转换为 numeric
dtype（Decimal/str → float），避免下游复杂因子（KDJ_J / bollinger_pb 等）触发
"unsupported operand type(s) for -: 'decimal.Decimal' and 'float'"。

回归依据：
- 2026-06-13 KDJ_J / bollinger_pb IC 脚本 update_mode=failed
- 根因：data_loader 未对统一数据源的 OHLC 列做 pd.to_numeric，下游 calculate_kdj_j /
  calculate_bollinger_pb 在 Decimal × float 混算时崩溃
- 修复：data_loader.py 在主数据加载完成后对所有非键列统一 pd.to_numeric

作者: 云瑶
日期: 2026-06-13
"""

from __future__ import annotations

import gzip
import json
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factor_ic.common.data_loader import load_factor_return_data


@pytest.fixture
def fake_unified_cache_with_decimal(tmp_path: Path) -> Path:
    """构造含 Decimal 字符串价格列的统一数据源缓存（gzip+JSON）"""
    records = []
    base_date = pd.Timestamp("2026-01-02")
    for i in range(5):
        date_str = (base_date + pd.Timedelta(days=i)).strftime("%Y-%m-%d")
        for asset in ("000001.SZ", "000002.SZ"):
            records.append(
                {
                    "date": date_str,
                    "asset": asset,
                    # JSON 里以字符串形式存储（模拟 Decimal 序列化产物）
                    "close": str(Decimal(f"{10 + i}.{i}5")),
                    "high": str(Decimal(f"{11 + i}.{i}0")),
                    "low": str(Decimal(f"{9 + i}.{i}0")),
                    "forward_return_1d": 0.001 * (i + 1),
                }
            )

    cache_path = tmp_path / "factor_ic_data.json.gz"
    with gzip.open(cache_path, "wt", encoding="utf-8") as f:
        json.dump({"data": records}, f)
    return cache_path


def test_ohlc_columns_coerced_to_numeric(fake_unified_cache_with_decimal: Path) -> None:
    """加载后 close/high/low 列应为 numeric dtype，可与 float 直接运算"""
    factor_df, _, _ = load_factor_return_data(
        factor_cols=["close", "high", "low"],
        data_cache_path=fake_unified_cache_with_decimal,
    )

    for col in ("close", "high", "low"):
        assert pd.api.types.is_numeric_dtype(factor_df[col]), (
            f"列 {col} 未被转为 numeric dtype，实际 dtype={factor_df[col].dtype}"
        )

    # 关键回归断言：能直接做 float 运算（这正是 KDJ_J / bollinger_pb 失败的场景）
    diff = factor_df["high"] - factor_df["low"] * 1.0
    assert pd.api.types.is_numeric_dtype(diff)
    assert not diff.isna().all()


def test_forward_return_remains_numeric(fake_unified_cache_with_decimal: Path) -> None:
    """已是数值的 forward_return 列经过规范化后仍可正常使用"""
    _, return_df, _ = load_factor_return_data(
        factor_cols=["close"],
        data_cache_path=fake_unified_cache_with_decimal,
    )
    assert pd.api.types.is_numeric_dtype(return_df["forward_return_1d"])
    assert np.isclose(return_df["forward_return_1d"].iloc[0], 0.001)
