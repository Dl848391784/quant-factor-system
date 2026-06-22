"""test_mark_low_liquidity: R1 流动性前置标记的单元测试

测试目标:
- _mark_low_liquidity 按截面分位标记 is_low_liquidity 列
- 截面样本不足时跳过 (避免极端日全部过滤)
- 缺 volume / close 列时抛 KeyError
- 不同日期独立计算阈值

设计依据: designs/feat_liquidity_filter_to_factor_generator.md §2.4
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from data_fetchers.factor_generator import _mark_low_liquidity  # noqa: E402


def _make_logger() -> logging.Logger:
    """构造静默 logger（不在测试中产生 stderr 噪音）"""
    logger = logging.getLogger("test_mark_low_liquidity")
    logger.handlers = []
    logger.addHandler(logging.NullHandler())
    logger.setLevel(logging.DEBUG)
    return logger


def _make_panel(date: str, asset_amounts: list[tuple[str, float]]) -> pd.DataFrame:
    """构造单日面板. asset_amounts: [(asset, amount_in_yuan), ...]"""
    rows = []
    for asset, amount in asset_amounts:
        # 任意拆分 amount = volume * close
        close = 10.0
        volume = amount / close if amount > 0 else 0.0
        rows.append({"date": date, "asset": asset, "volume": volume, "close": close})
    return pd.DataFrame(rows)


class TestMarkLowLiquidity:
    """覆盖 _mark_low_liquidity 核心契约"""

    def test_one_low_amount_marked(self) -> None:
        """单日 20 只股票, 1 只 amount=1, 其余=1e8 → 最低 1 只被标记 (P5)"""
        # 20 只股票, P5 = 第 1 只 (0-indexed 0). amount=1 < threshold → flag=1
        amounts = [("000001", 1.0)] + [(f"00000{i}", 1e8) for i in range(2, 21)]
        df = _make_panel("2026-06-20", amounts)
        logger = _make_logger()

        result = _mark_low_liquidity(df, logger)

        assert "is_low_liquidity" in result.columns
        # amount=1 的样本被标记
        flagged = result[result["is_low_liquidity"] == 1]["asset"].tolist()
        assert "000001" in flagged, "amount=1 应被标记为低流动性"
        # amount=1e8 的不应被标记
        normal = result[result["is_low_liquidity"] == 0]["asset"].tolist()
        assert "000002" in normal, "amount=1e8 应正常"

    def test_sparse_day_skipped(self) -> None:
        """截面样本 < 10 → 不过滤, 全部 is_low_liquidity=0"""
        amounts = [(f"00000{i}", float(i)) for i in range(1, 6)]  # 5 只
        df = _make_panel("2026-06-20", amounts)
        logger = _make_logger()

        result = _mark_low_liquidity(df, logger)

        # 全部应为 0 (截面样本 5 < 10 默认下限)
        assert (result["is_low_liquidity"] == 0).all(), "样本不足时不应标记"

    def test_missing_volume_raises(self) -> None:
        """缺 volume 列 → KeyError"""
        df = pd.DataFrame({"date": ["2026-06-20"], "asset": ["000001"], "close": [10.0]})
        logger = _make_logger()

        with pytest.raises(KeyError, match="volume"):
            _mark_low_liquidity(df, logger)

    def test_missing_close_raises(self) -> None:
        """缺 close 列 → KeyError"""
        df = pd.DataFrame({"date": ["2026-06-20"], "asset": ["000001"], "volume": [100.0]})
        logger = _make_logger()

        with pytest.raises(KeyError, match="close"):
            _mark_low_liquidity(df, logger)

    def test_per_date_threshold(self) -> None:
        """两个日期分布不同 → 各自计算阈值"""
        # 日期 1: 全部低 (但样本充足)
        day1 = [(f"00000{i}", 100.0 + i) for i in range(1, 21)]
        # 日期 2: 1 只极低, 其余高
        day2 = [("000001", 0.1)] + [(f"00000{i}", 1e9) for i in range(2, 21)]
        df = pd.concat(
            [_make_panel("2026-06-19", day1), _make_panel("2026-06-20", day2)],
            ignore_index=True,
        )
        logger = _make_logger()

        result = _mark_low_liquidity(df, logger)

        # 日期 1: 截面 P5 = 第 1 只 (000001), 仅它被标
        day1_flag = result[result["date"] == "2026-06-19"]
        assert int(day1_flag["is_low_liquidity"].sum()) >= 1
        # 日期 2: 000001 (amount=0.1) 必被标
        day2_flag = result[result["date"] == "2026-06-20"]
        day2_vals = day2_flag.loc[day2_flag["asset"] == "000001", "is_low_liquidity"].tolist()
        assert day2_vals[0] == 1

    def test_nan_amount_marked_low(self) -> None:
        """volume=NaN 视为低流动性 (无法判断 → 保守标记)"""
        amounts = [(f"00000{i}", 1e8) for i in range(1, 21)]
        df = _make_panel("2026-06-20", amounts)
        # 篡改 1 只为 NaN volume
        df.loc[0, "volume"] = np.nan
        logger = _make_logger()

        result = _mark_low_liquidity(df, logger)

        assert result.loc[0, "is_low_liquidity"] == 1, "NaN volume 应标记为低流动性"

    def test_zero_amount_marked_low(self) -> None:
        """amount=0 (volume=0) 视为低流动性"""
        amounts = [("000001", 0.0)] + [(f"00000{i}", 1e8) for i in range(2, 21)]
        df = _make_panel("2026-06-20", amounts)
        logger = _make_logger()

        result = _mark_low_liquidity(df, logger)

        flag_vals = result.loc[result["asset"] == "000001", "is_low_liquidity"].tolist()
        assert flag_vals[0] == 1, "amount=0 应标记为低流动性"

    def test_output_column_dtype_int(self) -> None:
        """is_low_liquidity 列类型应为 int (0/1)"""
        amounts = [(f"00000{i}", 1e8) for i in range(1, 21)]
        df = _make_panel("2026-06-20", amounts)
        logger = _make_logger()

        result = _mark_low_liquidity(df, logger)

        assert pd.api.types.is_integer_dtype(result["is_low_liquidity"]), (
            f"is_low_liquidity 应为 int, 实际 {result['is_low_liquidity'].dtype}"
        )
        assert set(result["is_low_liquidity"].unique()).issubset({0, 1})

    def test_input_not_mutated(self) -> None:
        """输入 DataFrame 不被原地修改"""
        amounts = [(f"00000{i}", 1e8) for i in range(1, 21)]
        df = _make_panel("2026-06-20", amounts)
        original_cols = set(df.columns)
        logger = _make_logger()

        _ = _mark_low_liquidity(df, logger)

        assert set(df.columns) == original_cols, "输入 DataFrame 不应被修改"
        assert "is_low_liquidity" not in df.columns
