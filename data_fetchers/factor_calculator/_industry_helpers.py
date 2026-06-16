"""factor_calculator 包内行业列注入 helper（_industry_helpers）。

设计定位（design.md §5.1 修正）
==============================
本模块从 ``_common.py`` 抽出 ``_add_industry_column`` helper，承担 ``_common.py``
不能承担的"反向依赖兄弟模块（``data_fetchers.fetch_industry``）"职责：

- ``_common.py`` 是 factor_calculator 包的依赖图根节点，仅可依赖
  ``stdlib + numpy + pandas + logging``；把 ``_add_industry_column`` 留在
  ``_common.py`` 会让根节点反向依赖 ``fetch_industry``，违反 §5.1 约束。
- 把该 helper 单独放在 ``_industry_helpers.py``，依赖图调整为：
  ``industry.py / fund_flow.py / industry_financial.py``
      → ``_industry_helpers.py``
          → ``data_fetchers.fetch_industry``
  ``_common.py`` 重新成为干净的根节点（只持纯计算 helper / 列常量 / logger）。

约束
====
- ``__all__ = []``：本模块不导出公共 API；外部需要的符号统一由
  ``data_fetchers/factor_calculator/__init__.py`` 显式 re-export（或通过
  ``_legacy.py`` re-import 维持原有 ``from ._common import _add_industry_column``
  调用方零修改）。
- 仅本模块允许 import ``data_fetchers.fetch_industry``。其它子模块（含
  ``_common.py``）禁止反向依赖 ``fetch_industry``。
- 历史 fallback ``from fetch_industry import get_industry_map`` 已删除：
  在包结构下裸模块名解析失败会 ImportError 并掩盖真实错误（原始问题清单 #2）；
  使用绝对路径 import，失败让异常向上传播。

历史
====
- v1.0 (2026-06-16) R2：从 ``_common.py`` 行 401-441 抽取 ``_add_industry_column``
  到本模块；删除裸名 fallback；外部 import 路径由 ``._common`` 改为 ``._industry_helpers``。
"""

from __future__ import annotations

import logging

import pandas as pd

from ._common import _COL_ASSET


__all__: list[str] = []


def _add_industry_column(
    df: pd.DataFrame,
    _logger: logging.Logger,
) -> pd.DataFrame:
    """为 DataFrame 添加 industry 列（从 fetch_industry 映射）

    Args:
        df: 包含 asset 列的 DataFrame
        _logger: 日志记录器

    Returns:
        DataFrame 新增 industry 列，未知股票赋 '其他'

    Note:
        使用 fetch_industry.get_industry_map() 获取行业映射，
        避免重复加载（模块级缓存+线程安全）。
        如果 industry 列已存在则跳过添加（避免重复添加）。

    Raises:
        ImportError: 当 ``data_fetchers.fetch_industry`` 不可用时直接抛出，
            不再用裸名 ``from fetch_industry import ...`` 兜底（旧 fallback
            在包结构下会因路径解析失败掩盖真实错误，原始问题清单 #2）。
    """
    # 如果 industry 列已存在则跳过（多次调用 / 上游已合并的场景）
    if "industry" in df.columns:
        _logger.debug(
            "_add_industry_column: industry 列已存在（rows=%d），跳过注入",
            len(df),
        )
        return df

    # 唯一允许反向依赖 fetch_industry 的位置（design.md §5.1 修正）。
    # 不再使用 try/except ImportError + 裸名 fallback：
    #   - 包结构下裸 ``from fetch_industry import ...`` 路径解析失败 → ImportError
    #   - 同时掩盖真实根因（fetch_industry 自身的 import-time 错误）
    # 失败应让异常向上传播，由调用方在 main() 入口决定是否降级。
    from data_fetchers.fetch_industry import get_industry_map

    industry_map = get_industry_map()

    # 映射：asset → industry
    df["industry"] = df[_COL_ASSET].map(lambda code: industry_map.get(str(code), {}).get("industry", "其他"))

    unknown_count = int((df["industry"] == "其他").sum())
    if unknown_count > 0:
        _logger.warning(
            "  行业未知股票数: %d (%.2f%%)",
            unknown_count,
            unknown_count / len(df) * 100 if len(df) > 0 else 0,
        )

    return df
