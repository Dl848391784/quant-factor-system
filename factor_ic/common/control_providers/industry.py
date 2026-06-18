"""IndustryProvider: 行业控制变量提供器（design.md §4.1 / §8.2）。

封装现行行业中性化的数据加载与预处理逻辑，作为 ControlProvider 协议的
第一个具体实现。P1 重构期间必须与 `industry_neutral_residual` 行为完全一致：

- 行业映射：data_fetchers.fetch_industry.get_industry_map（asset 静态映射）
- 预处理：剔除 industry == "其他"
- 截面过滤：剔除股票数 < min_count 的行业
- 设计矩阵：pd.get_dummies（默认 drop_first=False，与现行行为一致）

参考:
    designs/feat_neutralization_framework.md §4.1, §8.2
    factor_ic/common/data_loader.py merge_industry_column
    factor_ic/common/ic_calculator.py industry_neutral_residual
"""

from __future__ import annotations

from typing import Any, Literal

import pandas as pd

from ..logger_config import get_logger


class IndustryProvider:
    """申万一级行业控制变量提供器。

    column_type='categorical'，按 asset 静态映射（行业不随日期变化）。
    """

    name: str = "industry"
    column_type: Literal["categorical", "numerical"] = "categorical"
    join_keys: list[str] = ["asset"]

    # 派生列名（preprocess 后写入 factor_df 的列）
    OUTPUT_COL: str = "industry"
    OTHER_LABEL: str = "其他"

    def __init__(self) -> None:
        self._meta: dict[str, Any] = {
            "n_industries": 0,
            "min_stocks": 0,
            "other_dropped": 0,
            "nan_dropped": 0,
        }

    def load(
        self,
        dates: list,
        assets: list,
        *,
        logger: Any = None,
    ) -> pd.DataFrame:
        """加载行业映射并构造 [asset, industry] DataFrame。

        行业是 asset 静态映射（design.md §3.1 行业不分日期），
        因此返回 schema = [asset, industry]，不含 date 列；
        引擎按 join_keys=['asset'] 合并时自动 broadcast 到所有日期。

        参数:
            dates: 因子日期（仅用于日志，行业映射不按日期切片）
            assets: 资产代码列表（仅用于日志/统计，映射本身全量加载）
            logger: 日志器

        返回:
            DataFrame[asset, industry]，缺失的 asset 不出现（引擎合并时自动 NaN）
        """
        if logger is None:
            logger = get_logger(__name__)

        # 延迟导入：避免顶层跨模块依赖（与 merge_industry_column 同模式）
        from data_fetchers.fetch_industry import get_industry_map

        industry_map = get_industry_map()
        rows = [{"asset": code, self.OUTPUT_COL: info.get("industry")} for code, info in industry_map.items()]
        df = pd.DataFrame(rows)
        logger.info(
            "[IndustryProvider.load] 加载行业映射: %d 个 asset (%d 输入 asset, %d 输入 dates)",
            len(df),
            len(assets),
            len(dates),
        )
        return df

    def preprocess(
        self,
        df: pd.DataFrame,
        *,
        logger: Any = None,
    ) -> pd.DataFrame:
        """剔除 industry == '其他'（design.md §3.3 / D6 决策）。

        '其他' 是申万一级里的混杂桶（含申万二级码 220901/280203 等），
        不应作为独立行业回归。industry == NaN 的行（未匹配 asset）由引擎统一 dropna 处理。
        """
        if logger is None:
            logger = get_logger(__name__)

        before = len(df)
        result = df[df[self.OUTPUT_COL] != self.OTHER_LABEL].copy()
        other_dropped = before - len(result)
        self._meta["other_dropped"] = other_dropped
        logger.info(
            "[IndustryProvider.preprocess] '其他' 行业剔除: %d 行（剩余 %d 行）",
            other_dropped,
            len(result),
        )
        return result

    def filter_invalid_rows(
        self,
        day_df: pd.DataFrame,
        *,
        min_count: int,
        logger: Any = None,
    ) -> pd.DataFrame:
        """剔除当日股票数 < min_count 的行业（与 industry_neutral_residual 一致）。"""
        result = day_df.groupby(self.OUTPUT_COL).filter(lambda x: len(x) >= min_count)
        return pd.DataFrame(result)

    def to_design_columns(
        self,
        day_df: pd.DataFrame,
        *,
        drop_first: bool = False,
    ) -> pd.DataFrame:
        """构造行业哑变量矩阵。

        drop_first=False（P1 默认）保持与 industry_neutral_residual 完全一致：
        sklearn LinearRegression(fit_intercept=True) + N 个哑变量全集 时，
        共线性由 sklearn 内部 pseudo-inverse 处理，残差结果稳定。
        """
        return pd.get_dummies(day_df[self.OUTPUT_COL], drop_first=drop_first)

    def get_meta(self) -> dict:
        """返回该 Provider 的预处理统计信息。"""
        return self._meta.copy()
