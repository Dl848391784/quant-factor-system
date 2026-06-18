"""中性化控制变量提供器协议（design.md §4.1）。

每个具体 Provider 提供一种风险因子的数据源 + 预处理 + 设计矩阵转换，
供 neutralizer 引擎组合成多元回归的 X 矩阵。

参考: designs/feat_neutralization_framework.md §4.1（协议定义）
"""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

import pandas as pd


@runtime_checkable
class ControlProvider(Protocol):
    """中性化控制变量提供器协议（design.md §4.1）。

    属性:
        name: 控制变量名（如 'industry' / 'log_market_cap'），作为 spec 字符串和
            注册表 key。必须与 PROVIDER_REGISTRY 的 key 一致。
        column_type: 列类型，决定引擎如何转设计矩阵。
            - 'categorical': to_design_columns 返回哑变量矩阵（多列）
            - 'numerical':   to_design_columns 返回单列连续值

    五个方法对应数据流的五个阶段：
        1. load(dates, assets) → 加载原始数据
        2. preprocess(df) → ln/winsorize/剔除等变换
        3. filter_invalid_rows(day_df, min_count) → 单日截面过滤
        4. to_design_columns(day_df, drop_first) → 转设计矩阵列
        5. get_meta() → 返回预处理统计信息（写入 ic_neutralized.control_meta）

    设计权衡（design.md §3.3）:
        - dropna 在引擎统一做（不在 Provider 内），避免多 control 时
          NaN 跨 Provider 传染时各 Provider 各自处理失控
        - drop_first 由引擎根据 providers 列表决定（含 numerical 时为 True），
          Provider 不感知组合上下文
    """

    name: str
    column_type: Literal["categorical", "numerical"]
    join_keys: list[str]
    """合并到 factor_df 时使用的 join key 列表。
       categorical 静态映射（如 industry）通常 ['asset']，按 asset broadcast 到所有日期。
       numerical 动态时序（如 log_market_cap）通常 ['date', 'asset']，按 (date, asset) 一对一。
    """

    def load(
        self,
        dates: list,
        assets: list,
        *,
        logger: Any = None,
    ) -> pd.DataFrame:
        """加载控制变量原始数据。

        参数:
            dates: 因子日期列表（用于按需切片，避免加载无关日期）
            assets: 资产代码列表
            logger: 日志器（可选）

        返回:
            DataFrame，必须含列 [date, asset, <self.name 或派生原始字段>]。
            缺失值用 NaN，后续由引擎统一 dropna。
        """
        ...

    def preprocess(
        self,
        df: pd.DataFrame,
        *,
        logger: Any = None,
    ) -> pd.DataFrame:
        """预处理（ln 变换 / 剔'其他' / winsorize 等）。

        输入: load() 返回的 DataFrame
        输出: 同 schema 但值已变换；可能行数减少（剔除规则）；
              派生列名（如 industry / log_market_cap）应已就绪。
        """
        ...

    def to_design_columns(
        self,
        day_df: pd.DataFrame,
        *,
        drop_first: bool = False,
    ) -> pd.DataFrame:
        """将 day_df（单日 cross-section）转换为设计矩阵列。

        参数:
            day_df: 单日截面 DataFrame
            drop_first: 是否丢弃第一个哑变量（多元回归共线性护栏）。
                categorical: drop_first=True 时 N→N-1 列
                numerical: drop_first 不影响（单列）

        返回:
            DataFrame，行数 = day_df 行数，列数 = 该 Provider 贡献的设计矩阵列数。
        """
        ...

    def filter_invalid_rows(
        self,
        day_df: pd.DataFrame,
        *,
        min_count: int,
        logger: Any = None,
    ) -> pd.DataFrame:
        """过滤当日 cross-section 中无效行。

        IndustryProvider: 剔除股票数 < min_count 的行业（min_count 通常 5）
        LogMarketCapProvider: 当日有效行数 < min_count 整批跳过（通常 20）

        返回:
            过滤后的 day_df（行数 ≤ 输入），空 DataFrame 表示该日整体跳过。
        """
        ...

    def get_meta(self) -> dict:
        """返回该 Provider 的预处理统计信息。

        引擎将其写入 ic_neutralized.control_meta[provider.name]。

        返回:
            dict，键值由各 Provider 自行约定（如行业数 / winsorize 计数）。
        """
        ...
