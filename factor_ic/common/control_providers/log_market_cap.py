"""LogMarketCapProvider: 流通市值对数控制变量提供器（design.md §9.2 P2.1）。

数据源：`data_fetchers/result/market_cap_data.json.gz`，结构为 gzip JSON
`{"meta": ..., "data": [...]}`（不是裸 records）。Provider 只读取 `data` 中的
`[date, asset, circ_market_cap]`，预处理为 `log_market_cap`：

1. 剔除 `circ_market_cap` 缺失或 <= 0 的行；
2. `log_market_cap = ln(circ_market_cap)`；
3. 每日截面独立 winsorize 到 1% / 99% 分位；
4. 不标准化（OLS 对量纲不敏感，避免 residual 解释复杂化）。

参考:
    designs/feat_neutralization_framework.md §9.2（P2.1）
    data_fetchers/schemas/market_cap_data.schema.json
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd

from ..logger_config import get_logger


class LogMarketCapProvider:
    """流通市值对数控制变量提供器。"""

    name: str = "log_market_cap"
    column_type: Literal["categorical", "numerical"] = "numerical"
    join_keys: list[str] = ["date", "asset"]

    SOURCE_FIELD: str = "circ_market_cap"
    OUTPUT_COL: str = "log_market_cap"
    WINSORIZE_QUANTILES: tuple[float, float] = (0.01, 0.99)

    def __init__(self, source_path: Path | None = None) -> None:
        self._source_path = source_path
        self._meta: dict[str, Any] = {
            "source_field": self.SOURCE_FIELD,
            "winsorize_quantiles": list(self.WINSORIZE_QUANTILES),
            "n_loaded": 0,
            "n_after_slice": 0,
            "n_missing_or_non_positive_dropped": 0,
            "n_winsorized_low": 0,
            "n_winsorized_high": 0,
        }

    @property
    def source_path(self) -> Path:
        """真实数据路径（延迟解析，避免 import-time 跨模块副作用）。"""
        if self._source_path is not None:
            return self._source_path
        from data_fetchers.common.paths import get_market_cap_data_file

        return get_market_cap_data_file()

    def load(
        self,
        dates: list,
        assets: list,
        *,
        logger: Any = None,
    ) -> pd.DataFrame:
        """加载并按 dates/assets 切片市值数据。

        market_cap_data.json.gz 顶层结构是 `{meta, data}`，因此必须 `json.load`
        后取 `data` 字段；不能直接 `pd.read_json(path, compression="gzip")`。
        """
        if logger is None:
            logger = get_logger(__name__)

        path = self.source_path
        if not path.exists():
            raise FileNotFoundError(f"市值数据文件不存在: {path}")

        with gzip.open(path, "rt", encoding="utf-8") as fp:
            payload = json.load(fp)
        records = payload.get("data", [])
        self._meta["n_loaded"] = len(records)

        df = pd.DataFrame.from_records(records)
        if df.empty:
            result = pd.DataFrame(columns=["date", "asset", self.SOURCE_FIELD])
            self._meta["n_after_slice"] = 0
            return result

        required_cols = {"date", "asset", self.SOURCE_FIELD}
        missing = required_cols - set(df.columns)
        if missing:
            raise ValueError(f"市值数据缺少必需列: {sorted(missing)}; path={path}")

        date_values = list(dict.fromkeys(dates))
        asset_values = list(dict.fromkeys(assets))
        mask = df["date"].isin(date_values) & df["asset"].isin(asset_values)
        result = df.loc[mask, ["date", "asset", self.SOURCE_FIELD]].copy()
        self._meta["n_after_slice"] = len(result)
        logger.info(
            "[LogMarketCapProvider.load] 加载市值数据: raw=%d sliced=%d (%d dates, %d assets)",
            len(df),
            len(result),
            len(date_values),
            len(asset_values),
        )
        return result

    def preprocess(self, df: pd.DataFrame, *, logger: Any = None) -> pd.DataFrame:
        """剔无效市值 → ln → 每日截面 winsorize。"""
        if logger is None:
            logger = get_logger(__name__)

        if df.empty:
            return pd.DataFrame(columns=["date", "asset", self.OUTPUT_COL])

        valid_mask = df[self.SOURCE_FIELD].notna() & (df[self.SOURCE_FIELD] > 0)
        dropped = int((~valid_mask).sum())
        self._meta["n_missing_or_non_positive_dropped"] = dropped

        result = df.loc[valid_mask, ["date", "asset", self.SOURCE_FIELD]].copy()
        result[self.OUTPUT_COL] = np.log(result[self.SOURCE_FIELD].astype(float))

        lo_q, hi_q = self.WINSORIZE_QUANTILES
        grouped = result.groupby("date")[self.OUTPUT_COL]
        lo = grouped.transform(lambda s: s.quantile(lo_q))
        hi = grouped.transform(lambda s: s.quantile(hi_q))

        self._meta["n_winsorized_low"] = int((result[self.OUTPUT_COL] < lo).sum())
        self._meta["n_winsorized_high"] = int((result[self.OUTPUT_COL] > hi).sum())
        result.loc[:, self.OUTPUT_COL] = result[self.OUTPUT_COL].clip(lower=lo, upper=hi)

        logger.info(
            "[LogMarketCapProvider.preprocess] dropped=%d winsor_low=%d winsor_high=%d rows=%d",
            dropped,
            self._meta["n_winsorized_low"],
            self._meta["n_winsorized_high"],
            len(result),
        )
        return result.drop(columns=[self.SOURCE_FIELD])

    def filter_invalid_rows(
        self,
        day_df: pd.DataFrame,
        *,
        min_count: int,
        logger: Any = None,
    ) -> pd.DataFrame:
        """当日有效市值样本数低于 min_count 时整日跳过。"""
        if len(day_df) < min_count:
            return day_df.iloc[0:0].copy()
        return day_df

    def to_design_columns(self, day_df: pd.DataFrame, *, drop_first: bool = False) -> pd.DataFrame:
        """numerical provider 直接贡献单列；drop_first 对连续变量无影响。"""
        return day_df[[self.OUTPUT_COL]]

    def get_meta(self) -> dict:
        """返回预处理统计信息副本。"""
        return self._meta.copy()
