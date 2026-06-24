"""
因子数据加载模块

功能:
1. 从统一数据源 factor_ic_data.json.gz 加载因子原始值
2. 从 factor_ic/result/ 加载 IC 统计结果
3. 从 factor_ic/result/ 加载 IC 每日序列（用于滚动ICIR）
4. 合并多个因子数据到统一 DataFrame

更新历史（2026-05-27）：
- v2.7: 从统一数据源 factor_ic_data.json.gz 读取因子数据
- 移除 DEFAULT_CACHE_DIR（改为 DEFAULT_DATA_SOURCE）

更新历史（2026-06-14）：
- v2.23: load_full_data / load_factor_values 改用 ijson 流式加载
  根治 OOM Kill（exit code -9）：
  - v3a 列式 list[float] 累积 → 实测仍 4GB OOM（list[float] PyObject 头开销）
  - v3b 数值列 array.array('d') + str 列 list → numpy zero-copy 转 DataFrame
    估算峰值 ~1.1GB（线性外推 100K 行实测）
  设计文档: designs/composite_streaming_load_design.md
  复用模板: factor_ic/common/data_loader.py:111-153 (v3 已生产验证, 仅 4 列)

设计参考:
- factor_ic/common/data_loader.py
- backtest/common/data_loader.py

作者: 云瑶
创建日期: 2026-05-24
"""

import gc
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd


# 统一数据源路径（遵循 PROJECT.md 跨模块数据路径规范）
DEFAULT_DATA_SOURCE = Path(__file__).parent.parent.parent / "data_fetchers" / "result" / "factor_ic_data.parquet"
DEFAULT_IC_RESULT_DIR = Path(__file__).parent.parent.parent / "factor_ic" / "result"


def _trim_arena() -> None:
    """强制 glibc 归还 malloc arena 碎片给 OS（Linux 专用）。

    gc.collect() 回收 Python 对象，但 glibc malloc 只把碎片放入 arena bins
    不调用 munmap 归还 OS。多次循环后碎片累积导致 RSS 只增不减 → OOM。

    malloc_trim(0) 强制 glibc 归还所有 free 的 arena 页给 OS。
    非 Linux 环境无此函数，静默跳过。
    """
    import contextlib
    import ctypes
    import sys

    if sys.platform != "linux":
        return
    with contextlib.suppress(OSError, AttributeError):
        ctypes.CDLL("libc.so.6").malloc_trim(0)


def load_full_data(
    data_source: str | Path | None = None,
    factor_cols: list[str] | None = None,
    logger: logging.Logger | None = None,
) -> pd.DataFrame:
    """流式加载统一数据源（ijson + 列式累积）

    用于 composite_runner 入口处一次性加载，后续步骤从中提取子集，
    避免三次独立加载同一 gzip 文件。

    Args:
        data_source: 数据源文件路径（可选，默认使用 DEFAULT_DATA_SOURCE）
        factor_cols: 可选因子列过滤
            - None: 加载全部列（保持原有行为，composite_runner 入口走这条）
            - [...]: 仅加载 date + asset + factor_cols + forward_return_1d/3d/5d
        logger: 日志对象

    Returns:
        包含所需列的完整 DataFrame（date, asset, 行情, 因子, 收益）

    更新历史:
        - 2026-06-09 v2.10: 新增函数，消除 composite_runner 重复数据加载
        - 2026-06-14 v2.23: 改用 ijson 流式 + 列式 dict 累积，根治 OOM
          v1 (list[dict]) → ~600MB dict 头开销，OOM
          v2 (pd.concat)  → ~4GB 多块共存，OOM
          v3 (列式 dict)  → ~60MB 列式累积，成功
          fallback: ImportError → json.load（保留向后兼容）

    Note:
        - 校验 date、asset 列的数据类型（date 为 str，asset 为 str）
        - 数值列加载后统一 pd.to_numeric（消除 Decimal/str dtype 问题）
        - 调用方完成后应 del 返回值并 gc.collect() 释放内存
    """
    if logger is None:
        from comprehensive_factor.common.logger_config import get_logger

        logger = get_logger(__name__)

    if data_source is None:
        data_source = DEFAULT_DATA_SOURCE

    data_source = Path(data_source)

    if not data_source.exists():
        raise FileNotFoundError(
            f"统一数据源文件不存在: {data_source}\n请先运行 data_fetchers/factor_generator.py 生成数据"
        )

    logger.info("流式加载统一数据源: %s", data_source)

    # === 决定需加载的列集合 ===
    # factor_cols=None: 不限制（peek 首条记录后取全部 keys）
    # factor_cols=[...]: 限制为 date + asset + factor_cols + 3 个收益列
    required_cols: list[str] | None
    if factor_cols is not None:
        return_cols = ["forward_return_1d", "forward_return_3d", "forward_return_5d"]
        required_cols = list(dict.fromkeys(["date", "asset"] + factor_cols + return_cols))
    else:
        required_cols = None  # peek 阶段决定

    # is_untradeable: 不可交易标记列（涨停类），加载用于过滤
    # is_low_liquidity (R1): 低流动性标记列（截面成交额 P5），加载用于过滤
    if required_cols is not None:
        required_cols.append("is_untradeable")
        required_cols.append("is_low_liquidity")

    # v2.49: Arrow 层面行过滤，替代 pandas filter+reset_index 双拷贝。
    # 原实现 full_df = full_df[~mask].reset_index(drop=True) 产生两份拷贝
    # (boolean indexing copy + reset_index copy)，79列×1.5M行每次≈0.95GB，
    # 两次过滤峰值≈2.9GB 叠加已加载 DataFrame→OOM。
    # 修复：pq.read_table → Arrow compute 过滤 → to_pandas，只加载需要的行。
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    logger.info("从 Parquet 读取: %s", data_source)

    schema = pq.read_schema(data_source)
    available_cols = set(schema.names)

    # 决定读取列
    if required_cols is None:
        read_cols = sorted(available_cols)
    else:
        read_cols = [col for col in required_cols if col in available_cols]

    table = pq.read_table(data_source, columns=read_cols)

    # 补充缺失列为 null（向后兼容）
    if required_cols is not None:
        for col in required_cols:
            if col not in table.column_names:
                table = table.append_column(col, pa.nulls(table.num_rows, type=pa.null()))

    logger.info("Parquet 加载完成: %d 行 × %d 列", table.num_rows, table.num_columns)

    # === Arrow 层面行过滤（v2.49: to_pandas 之前过滤，避免 pandas 双拷贝） ===
    keep_mask = None
    filter_logs: list[tuple[str, int]] = []

    if "is_untradeable" in table.column_names:
        untradeable_col = pc.fill_null(table.column("is_untradeable"), 0)
        untradeable_count = pc.sum(pc.equal(untradeable_col, 1).cast("int64")).as_py()
        if untradeable_count > 0:
            keep_mask = pc.not_equal(untradeable_col, 1)
            filter_logs.append(("不可交易股票(涨停类)", untradeable_count))
    else:
        logger.warning("数据缺少 is_untradeable 列，跳过不可交易股票过滤")

    if "is_low_liquidity" in table.column_names:
        low_liq_col = pc.fill_null(table.column("is_low_liquidity"), 0)
        low_liq_count = pc.sum(pc.equal(low_liq_col, 1).cast("int64")).as_py()
        if low_liq_count > 0:
            m = pc.not_equal(low_liq_col, 1)
            keep_mask = m if keep_mask is None else pc.and_(keep_mask, m)
            filter_logs.append(("低流动性股票(截面成交额 P5)", low_liq_count))
    else:
        logger.warning("数据缺少 is_low_liquidity 列，跳过低流动性股票过滤")

    if keep_mask is not None:
        table = table.filter(keep_mask)

    # v2.52 (OOM 炸弹7): Arrow table → pandas 后立即释放 Arrow memory pool
    # pq.read_table 的 Arrow 列缓冲通过 Arrow 自己的 mmap 内存池分配, 不走 glibc malloc,
    # 所以 malloc_trim 无法回收. 必须用 pool.release_unused() 归还 mmap 页给 OS.
    # 诊断数据: del table 后 RSS=2828MB, pool.release_unused() 后 RSS=1228MB (-1600MB)
    full_df = table.to_pandas()
    del table
    gc.collect()
    pa.default_memory_pool().release_unused()
    _trim_arena()

    for label, excluded in filter_logs:
        logger.info("过滤%s: 排除 %d 条, 剩余 %d 条", label, excluded, len(full_df))

    # === 校验 date / asset 类型（保留现有逻辑） ===
    if len(full_df) > 0:
        first_date = full_df["date"].iloc[0]
        first_asset = full_df["asset"].iloc[0]

        if not isinstance(first_date, str):
            raise TypeError(
                f"date 列数据类型应为 str，实际为 {type(first_date).__name__}\n"
                f"首行 date 值: {first_date}\n"
                "可能原因：\n"
                "  1. JSON 文件中 date 字段为数字而非字符串\n"
                "  2. 数据生成脚本类型转换异常\n"
                "建议：检查 factor_ic_data.json.gz 生成逻辑"
            )

        if not isinstance(first_asset, str):
            raise TypeError(
                f"asset 列数据类型应为 str，实际为 {type(first_asset).__name__}\n"
                f"首行 asset 值: {first_asset}\n"
                "可能原因：\n"
                "  1. JSON 文件中 asset 字段为数字而非字符串\n"
                "  2. 数据生成脚本类型转换异常\n"
                "建议：检查 factor_ic_data.json.gz 生成逻辑"
            )

    logger.info("统一数据源: %d 条记录，类型校验通过", len(full_df))

    # === 数值列类型规范化（参考 factor_ic v3） ===
    # 背景：factor_ic_data.json.gz 中 OHLC 等价格列以 Decimal 字符串形式存储，
    #   pandas 读取后 dtype=object，下游计算触发 `Decimal - float` 类型不兼容。
    # 修复：对所有非键列统一 pd.to_numeric(errors="coerce")
    # v2.52 (OOM 炸弹7): Parquet 已保证数值列类型为 double, 只转换 object 类型列,
    #   避免逐列赋值 83 列产生 BlockManager 碎片 (~1GB overhead)
    numeric_cols = [c for c in full_df.columns if c not in ("date", "asset")]
    object_cols = [c for c in numeric_cols if full_df[c].dtype == "object"]
    if object_cols:
        for col in object_cols:
            full_df[col] = pd.to_numeric(full_df[col], errors="coerce")
        logger.info("数值列类型规范化完成: %d 列中 %d 列需转换（object→float）", len(numeric_cols), len(object_cols))
    else:
        logger.info("数值列类型规范化完成: %d 列（Parquet 已保证类型，无需转换）", len(numeric_cols))

    # v2.52 (OOM 炸弹7, 模式3c): 逐列 pd.to_numeric 赋值产生 BlockManager 碎片
    # 但不用 copy()（966MB × 2 在 7.3GB 系统上会 OOM），用 gc + trim 回收 glibc 碎片
    gc.collect()
    _trim_arena()

    return full_df


def load_factor_values(
    factor_cols: list[str], data_source: str | Path | None = None, logger: logging.Logger | None = None
) -> pd.DataFrame:
    """从统一数据源加载因子原始值（流式）

    内部委托 load_full_data(factor_cols=factor_cols)，避免双份维护流式逻辑。

    Args:
        factor_cols: 因子列名列表（如 ['rsi_6', 'volume_ratio_5']）
        data_source: 数据源文件路径（可选，默认使用 DEFAULT_DATA_SOURCE）
        logger: 日志对象

    Returns:
        包含 date, asset, 因子列的 DataFrame（不含 forward_return_*）

    更新历史:
        - 2026-05-27 v2.7: 从统一数据源 factor_ic_data.json.gz 读取
        - 2026-06-14 v2.23: 委托 load_full_data，自动获得 ijson 流式优化

    Note:
        - 校验 factor_cols 在数据源中存在（缺失列抛 ValueError）
        - 校验 date、asset 列的数据类型（继承 load_full_data 的校验）
        - 数值列已 pd.to_numeric（继承 load_full_data 的处理）
    """
    if logger is None:
        from comprehensive_factor.common.logger_config import get_logger

        logger = get_logger(__name__)

    # 委托给 load_full_data 走流式列子集加载（约 175MB 峰值）
    full_df = load_full_data(data_source=data_source, factor_cols=factor_cols, logger=logger)

    # 校验请求的 factor_cols 全部存在于加载结果中
    missing = [c for c in factor_cols if c not in full_df.columns]
    if missing:
        available_cols = [c for c in full_df.columns if c not in ("date", "asset")]
        raise ValueError(f"数据源中缺少因子列: {missing}\n可用列: {available_cols}")

    # 仅返回 date + asset + factor_cols（与 v2.7 签名兼容，不含 forward_return_*）
    result_df = full_df[["date", "asset"] + factor_cols].copy()  # type: ignore[assignment]

    # 显式释放完整 DataFrame
    del full_df
    import gc

    gc.collect()

    logger.info("因子数据: %d 条记录，%d 个因子列", len(result_df), len(factor_cols))

    return result_df


def load_ic_results(
    factor_names: list[str],
    ic_result_dir: Path | None = None,
    return_period: str = "1d",
    logger: logging.Logger | None = None,
) -> tuple[dict[str, dict], list[str]]:
    """从 factor_ic/result/ 加载 IC 统计结果

    Args:
        factor_names: 因子名称列表（如 ['rsi', 'volume_ratio']）
        ic_result_dir: IC结果目录路径
        return_period: 收益周期（如 '1d'）
        logger: 日志对象

    Returns:
        Tuple[ic_results, missing_factors]
        - ic_results: Dict[因子名, IC统计结果]
          {
              'rsi': {'ic_mean': -0.032, 'icir': -0.45, 'ic_std': 0.07, ...},
              'volume_ratio': {'ic_mean': -0.058, 'icir': -1.97, ...}
          }
        - missing_factors: 缺失因子列表（调用方可据此判断）

    Note:
        - 返回缺失因子列表，避免调用方不知道哪些因子缺失
        - ic_metrics/summary 字段回退时验证必需字段（ic_mean/icir）
    """
    if logger is None:
        from comprehensive_factor.common.logger_config import get_logger

        logger = get_logger(__name__)

    if ic_result_dir is None:
        ic_result_dir = DEFAULT_IC_RESULT_DIR

    ic_result_dir = Path(ic_result_dir)

    ic_results = {}
    missing_factors = []  # 修复：记录缺失因子列表

    # 必需字段：用于静态权重计算
    REQUIRED_IC_FIELDS = ["ic_mean", "icir"]

    for factor_name in factor_names:
        # IC结果文件命名: ic_<因子名>_<收益周期>_analysis_result.json
        ic_file = ic_result_dir / f"ic_{factor_name}_{return_period}_analysis_result.json"

        if not ic_file.exists():
            logger.warning("IC结果文件不存在: %s，跳过该因子", ic_file)
            missing_factors.append(factor_name)
            continue

        logger.info("加载 IC 结果: %s", ic_file)

        with open(ic_file, encoding="utf-8") as f:
            ic_data = json.load(f)

        # 提取 ic_metrics 字段（IC统计结果）
        # 修复：字段回退时验证必需字段
        extracted_data = None
        field_source = None

        if "ic_metrics" in ic_data:
            extracted_data = ic_data["ic_metrics"]
            field_source = "ic_metrics"
        elif "summary" in ic_data:
            # summary 字段结构可能与 ic_metrics 不同
            # 验证必需字段存在性
            extracted_data = ic_data["summary"]
            field_source = "summary"

            # 检查必需字段是否存在
            missing_fields = [f for f in REQUIRED_IC_FIELDS if f not in extracted_data]
            if missing_fields:
                logger.warning("IC结果文件 '%s' 字段缺失必需字段: %s，文件: %s", field_source, missing_fields, ic_file)

        if extracted_data is None:
            logger.warning("IC结果文件缺失 'ic_metrics' 和 'summary' 字段: %s", ic_file)
            missing_factors.append(factor_name)
            continue

        # 修复：验证必需字段（ic_mean, icir）存在性
        missing_required = [f for f in REQUIRED_IC_FIELDS if f not in extracted_data]
        if missing_required:
            logger.warning(
                "因子 %s IC 结果缺失必需字段: %s（来源: %s），文件: %s",
                factor_name,
                missing_required,
                field_source,
                ic_file,
            )
            # 不跳过该因子，但记录警告（下游使用时会回退等权）

        # Plan D: 注入中性化 IC 字段（供 weight_engine 优先使用）
        # 设计：designs/neutralized_ic_weighting_design.md §2
        # enabled=True → weight_engine 取 neutralized_icir / neutralized_ic_mean
        # enabled=False / 缺失 → 不设 neutralized_* 字段，weight_engine fallback to raw
        ic_neutralized = ic_data.get("ic_neutralized")
        if isinstance(ic_neutralized, dict) and ic_neutralized.get("enabled") is True:
            extracted_data["neutralized_enabled"] = True
            extracted_data["neutralized_icir"] = ic_neutralized.get("icir")
            extracted_data["neutralized_ic_mean"] = ic_neutralized.get("ic_mean")
            extracted_data["decay_level"] = ic_neutralized.get("decay_level")
            logger.debug(
                "因子 %s: 中性化 IC 已加载 (neutralized_icir=%s, decay_level=%s)",
                factor_name,
                ic_neutralized.get("icir"),
                ic_neutralized.get("decay_level"),
            )
        else:
            extracted_data["neutralized_enabled"] = False

        ic_results[factor_name] = extracted_data

    # 修复：返回缺失因子列表信息
    if missing_factors:
        logger.warning("部分因子 IC 结果缺失: %s，共 %d 个", missing_factors, len(missing_factors))

    if not ic_results:
        raise ValueError(f"未找到任何 IC 结果文件，路径: {ic_result_dir}\n缺失因子: {missing_factors}")

    logger.info("加载 IC 结果: %d 个因子（缺失 %d 个）", len(ic_results), len(missing_factors))

    return ic_results, missing_factors


def load_ic_daily(
    factor_names: list[str],
    ic_result_dir: Path | None = None,
    return_period: str = "1d",
    logger: logging.Logger | None = None,
) -> dict[str, pd.DataFrame]:
    """从 factor_ic/result/ 加载 IC 每日序列

    从现有的 IC 分析结果文件中提取 ic_values 和 dates 字段，
    用于滚动ICIR加权计算。

    Args:
        factor_names: 因子名称列表
        ic_result_dir: IC结果目录路径
        return_period: 收益周期
        logger: 日志对象

    Returns:
        Dict[因子名, IC每日DataFrame]
        {
            'rsi': DataFrame(columns=['date', 'ic']),
            'volume_ratio': DataFrame(...)
        }

    Note:
        - ic_sign 列已移除（死代码，未在后续计算中使用）
        - 日期与IC值数量不一致时抛出错误（不再静默截断）
    """
    if logger is None:
        from comprehensive_factor.common.logger_config import get_logger

        logger = get_logger(__name__)

    if ic_result_dir is None:
        ic_result_dir = DEFAULT_IC_RESULT_DIR

    ic_result_dir = Path(ic_result_dir)

    ic_daily_data = {}
    missing_factors = []  # 修复：记录缺失因子列表

    for factor_name in factor_names:
        # IC结果文件命名: ic_<因子名>_<收益周期>_analysis_result.json
        ic_file = ic_result_dir / f"ic_{factor_name}_{return_period}_analysis_result.json"

        if not ic_file.exists():
            logger.warning("IC结果文件不存在: %s，跳过该因子", ic_file)
            missing_factors.append(factor_name)
            continue

        logger.info("加载 IC 每日序列: %s", ic_file)

        with open(ic_file, encoding="utf-8") as f:
            ic_data = json.load(f)

        # Plan D: 优先使用中性化 IC 日序列（design.md §2.5）
        ic_neutralized = ic_data.get("ic_neutralized")
        if (
            isinstance(ic_neutralized, dict)
            and ic_neutralized.get("enabled") is True
            and ic_neutralized.get("ic_values")
        ):
            dates = ic_neutralized.get("dates", [])
            ic_values = ic_neutralized.get("ic_values", [])
            logger.debug("因子 %s: 使用中性化 IC 日序列 (n=%d)", factor_name, len(ic_values))
        else:
            # Fallback: raw IC 日序列
            if "ic_values" not in ic_data:
                logger.warning("IC结果文件缺失 'ic_values' 字段: %s", ic_file)
                missing_factors.append(factor_name)
                continue

            # 使用 valid_dates（有效日期）或 dates
            dates = ic_data.get("valid_dates", ic_data.get("dates", []))
            ic_values = ic_data.get("ic_values", [])

        # 修复：日期与IC值数量不一致时抛出错误（不再静默截断）
        # 原代码截断可能导致错位数据对齐到错误日期，产生错误的滚动ICIR
        if len(dates) != len(ic_values):
            raise ValueError(
                f"日期与IC值数量不一致: dates={len(dates)}, ic_values={len(ic_values)}\n"
                f"文件: {ic_file}\n"
                "可能原因：\n"
                "  1. IC 计算过程中部分日期缺失数据\n"
                "  2. JSON 文件写入异常\n"
                "  3. valid_dates 与 ic_values 字段对齐问题\n"
                "建议：重新运行 IC 分析脚本生成完整的 IC 结果文件"
            )

        # 修复：防御性处理 ic_values 中可能的 None 值
        # 原代码 v > 0 时 v 可能是 None，导致 TypeError
        # 同时移除 ic_sign 列（死代码，未在后续计算中使用）
        ic_values_cleaned = [v if v is not None else np.nan for v in ic_values]

        # 构建 DataFrame（移除 ic_sign 列）
        daily_df = pd.DataFrame({"date": dates, "ic": ic_values_cleaned})

        ic_daily_data[factor_name] = daily_df

    # 修复：返回缺失因子列表信息
    if missing_factors:
        logger.warning("部分因子 IC 每日数据缺失: %s，共 %d 个", missing_factors, len(missing_factors))

    if not ic_daily_data:
        raise ValueError(f"未找到任何 IC 每日数据，路径: {ic_result_dir}\n缺失因子: {missing_factors}")

    logger.info("加载 IC 每日序列: %d 个因子（缺失 %d 个）", len(ic_daily_data), len(missing_factors))

    return ic_daily_data


def _is_zero_inflated_group(group: "pd.Series[float]", zero_threshold: float, ratio_threshold: float) -> bool:
    """判断截面分组是否为零膨胀分布（零值占比 ≥ ratio_threshold）

    用于 standardize_factors 的 transform lambda 中，决定是否启用零值分离标准化。
    遵循第一性原理：零值占比 ≥ 5% 意味着零值是分布的固有属性（如 pvd 的 max(0,...) 截断），
    不是偶发噪声，σ 失真不可忽略。

    Args:
        group: 每日截面因子值 Series
        zero_threshold: |v| < 此阈值判定为零值
        ratio_threshold: 零值占比 ≥ 此阈值判定为零膨胀
    """
    if len(group) == 0:
        return False
    zero_ratio = (group.abs() < zero_threshold).sum() / len(group)
    return zero_ratio >= ratio_threshold


def _standardize_zero_inflated(
    group: "pd.Series[float]",
    winsorize_sigma: float,
    zero_threshold: float,
) -> "pd.Series[float]":
    """零值分离标准化——零值 z=0（中性），非零值用自身 μ/σ 标准化 + clip

    第一性原理推导：
    1. 零值是中性截断信号（如 pvd 的 shrink_signal=0 表示"不缩量=无背离"）
    2. 零值不应参与 σ 计算——它们压缩 σ 导致非零值 z-score 人为放大
    3. 非零值应用自身分布标准化——σ_nonzero 反映真实的信号离散度

    Args:
        group: 每日截面因子值 Series
        winsorize_sigma: Winsorize clip 阈值（±3σ）
        zero_threshold: |v| < 此阈值判定为零值

    Returns:
        标准化后的 Series（零值 → z=0，非零值 → 用非零值自身 μ/σ 标准化 + clip）
    """
    zero_mask = group.abs() < zero_threshold
    nonzero_vals = group[~zero_mask]

    if len(nonzero_vals) == 0:
        # 全为零值 → 全部 z = 0（中性）
        return pd.Series(0.0, index=group.index)

    if len(nonzero_vals) <= 1:
        # 非零值不足 → 非零值也无法标准化 → 全部 z = 0
        return pd.Series(0.0, index=group.index)

    mu = nonzero_vals.mean()
    sigma = nonzero_vals.std()

    if sigma == 0:
        # 所有非零值相同 → z = 0（无法区分信号强度）
        return pd.Series(0.0, index=group.index)

    # 非零值标准化 + clip ±winsorize_sigma
    z_nonzero = np.clip((nonzero_vals - mu) / sigma, -winsorize_sigma, winsorize_sigma)

    # 组合结果：零值 → z = 0，非零值 → z_nonzero
    result = pd.Series(0.0, index=group.index)
    result[~zero_mask] = z_nonzero

    return result


def standardize_factors(
    factor_df: pd.DataFrame,
    factor_cols: list[str],
    logger: logging.Logger | None = None,
    skip_point_mass: bool = False,
) -> pd.DataFrame:
    """截面标准化因子值

    每日对每个因子做截面标准化（减均值除标准差）。

    Args:
        factor_df: 因子 DataFrame（包含 date, asset, 因子列）
        factor_cols: 需标准化的因子列名
        logger: 日志对象
        skip_point_mass: 跳过点质量检测（auto_select 简化模式）
            - False（默认）：完整标准化（Winsorize ±3σ + 点质量检测 + NaN 还原）
            - True：仅截面 z-score + Winsorize ±3σ（用于 auto_select 相关性计算）
            - 设计依据：点质量检测将 z-score 置 NaN，仅影响因子内部极端值；
              Pearson corr() 对 NaN 鲁棒（自动跳过 NaN pair），相关性矩阵精度 <0.01 差异。
              详见 designs/composite_auto_select_memory_optimization_design.md §2.2

    Returns:
        标准化后的 DataFrame（新增标准化因子列，命名: <因子列>_std）

    接口约定（MODULE.md 规范）：
        - 输入列名：原始因子列名（如 'rsi_6', 'volume_ratio_5'）
        - 输出列名：新增 '_std' 后缀（如 'rsi_6_std', 'volume_ratio_5_std'）
        - WeightEngine.calculate() 接收原始列名，内部自动转换为 _std 列

    NaN 处理规范：
        1. 原始 NaN 保持 NaN（不参与标准化计算）
        2. 单只股票有有效值时，标准化结果为 NaN（样本标准差无法计算）
        3. 有效值数量 <=1 时记录警告日志

    Mutation 契约（v2.49, 2026-06-24）：
        - 原地修改：向输入 DataFrame 新增 _std 列，返回同一对象（不 copy）
        - 安全依据：两个调用方（composite_runner L336/L506）均使用 var=fn(var) 模式，
          从不复用旧引用；调用前已有独立 DataFrame（L302 read_parquet / L405 slice.copy()）
        - OOM 根因：1.39M 行 × 79 列全量 copy ≈ 1GB 冗余峰值，与调用方引用叠加致 OOM
        - 遵循 pandas-oom skill 模式 3a（管道末端 copy + 无契约测试守护）
    """
    if logger is None:
        from comprehensive_factor.common.logger_config import get_logger

        logger = get_logger(__name__)

    # v2.49: 删除 factor_df.copy() — 调用方均 var=fn(var) 不复用旧引用，
    # 全量 copy 1.39M×79列 ≈ 1GB 冗余，是 composite OOM 炸弹 1。
    # 函数仅新增 _std 列，不修改原始因子列，原地操作安全。

    # v2.52 (OOM 炸弹6, 模式3c): 用 dict 收集 _std 列，循环结束后 pd.concat 批量添加
    # 逐列 factor_df[std_col] = value 导致 pandas BlockManager 创建 N 个独立 Block
    # PerformanceWarning: "DataFrame is highly fragmented" → 实际内存膨胀 ~3x → OOM
    std_results: dict[str, pd.Series] = {}

    for col in factor_cols:
        std_col = f"{col}_std"

        # 修复：使用显式计算替代 lambda，避免条件判断与 NaN 处理冲突
        # 计算每日截面均值和标准差
        daily_stats = factor_df.groupby("date")[col].agg(["mean", "std", "count"])

        # 检查有效值数量不足的情况（count <= 1 的日期）
        low_count_mask = daily_stats["count"] <= 1
        # type: ignore[reportArgumentType] — pandas Index 是可迭代对象，LSP 类型推断不准确
        low_count_dates = list(daily_stats.index[low_count_mask])  # type: ignore
        if low_count_dates:
            logger.warning(
                "因子 %s 在 %d 个日期有效值数量 <=1，标准化结果将为 NaN: %s",
                col,
                len(low_count_dates),
                low_count_dates[:5],  # 只显示前5个
            )

        # 使用 transform 计算标准化值（保持索引对齐）
        # 注意：x.std(ddof=1) 单样本时返回 NaN，是正确行为
        # v2.16 新增：Winsorize 截断（±3σ），防止极端原始值导致 z-score 爆炸
        # 理由：momentum_strength 等比率类因子可能产生 ±50 的极端值，
        #   标准化后 z-score 达 ±11.7σ，统计意义极弱（p<0.003），截断不损失有效信息
        _WINSORIZE_SIGMA = 3.0

        # v2.20 新增：点质量检测——某值在截面中出现频率 >1% 时，z-score 置 NaN
        # 理由：tail_price_position 在 close=tail_low 时精确为 0.0，68/3019=2.3% 的股票
        #   挤在同一值上，z-score=-2.45 导致权重失真（名义 19.8% 实际贡献 41%）
        #   v1 clip±2σ 验证失败（贡献占比反升到 51%），v2 改为置 NaN：
        #   点质量是离散事件非正态尾部，z-score 无统计意义；NaN→fillna(0)=中性无信号
        #   弱势信号由相关因子携带（tail_price_position_delta corr=0.69）
        # v2.26 (2026-06-20): 离散型因子豁免——unique/N < 5% 或 unique < 20 的因子
        #   天然只有少量离散值（如 positive_day_ratio_5 只有 6 个值），高频聚集是
        #   固有属性而非数据噪声，点质量检测会误杀几乎所有股票的 z-score
        _POINT_MASS_THRESHOLD = 0.01  # 出现频率 >1% 判定为点质量
        _POINT_MASS_ZSCORE_GATE = 1.0  # z-score 超此阈值才检查点质量（性能优化，低门限确保跨日期一致检出）
        _DISCRETE_UNIQUE_RATIO = 0.05  # unique 值数 / N < 5% 判定为离散型
        _DISCRETE_MIN_UNIQUE = 20  # unique 值数 < 20 判定为离散型
        # v2.29 新增：零膨胀因子零值分离标准化（第一性原理推导）
        #   零值在 price_volume_divergence 等因子中有经济含义（中性截断信号，不是数据噪声）
        #   42%零值→σ全截面≈0.015人为压缩→非零值z-score被放大到±3→ICIR=0.16弱因子贡献22.5%
        #   修复：零值组z=0（中性），非零值组用自身μ/σ标准化→σ_nonzero≈0.03→z自然范围[-2,+2]
        _ZERO_INFLATED_THRESHOLD = 0.05  # 每日截面零值占比 ≥5% 触发零值分离标准化
        _ZERO_VALUE_THRESHOLD = 0.001  # |v| < 此阈值判定为零值（浮点精度保护）

        # v2.50: 向量化标准替代 groupby.transform(lambda) — OOM 炸弹2 修复
        # 原实现: 72因子 × groupby.transform(lambda 3分支) = 39528 次 per-group lambda 调用
        #   每次 transform 创建 549 group 临时 Series + pandas 索引重建 → ~100-200MB 中间体/次
        # 新实现: groupby.agg (Cython) + Series.map (向量化查找), 无 per-group 中间体
        # 遵循 pandas-oom skill 模式 2 (groupby.transform → 向量化)
        # 行为等价: 零膨胀检测 + 零值分离 + Winsorize ±3σ + 退化组 NaN

        # 步骤1: 零膨胀检测（向量化，替代 groupby.apply(lambda)）
        zero_mask = factor_df[col].abs() < _ZERO_VALUE_THRESHOLD
        # size() 计算总行数(含NaN), 与原 lambda 的 len(x) 一致
        daily_group_size = factor_df.groupby("date")[col].size()
        daily_zero_count = zero_mask.groupby(factor_df["date"]).sum()
        daily_zero_ratio = daily_zero_count / daily_group_size.clip(lower=1)
        is_zero_inflated = daily_zero_ratio >= _ZERO_INFLATED_THRESHOLD
        inflated_dates = list(daily_zero_ratio.index[is_zero_inflated])  # type: ignore[reportArgumentType]

        if inflated_dates:
            avg_zero_pct = daily_zero_ratio[is_zero_inflated].mean() * 100
            logger.info(
                "因子 %s 检测到零膨胀分布: %d/%d 日期零值占比≥%.0f%% (平均%.1f%%)，启用零值分离标准化",
                col,
                len(inflated_dates),
                len(daily_zero_ratio),
                _ZERO_INFLATED_THRESHOLD * 100,
                avg_zero_pct,
            )

        # 步骤2: 向量化 z-score 计算（替代 groupby.transform(lambda)）
        date_col = factor_df["date"]
        value_col = factor_df[col]

        # 复用 L622 的 daily_stats (Cython 优化的 groupby.agg)
        row_mean = date_col.map(daily_stats["mean"])
        row_std = date_col.map(daily_stats["std"])
        # std=0 或 NaN → 结果 NaN (对应原 lambda 的 x.std()>0 判断)
        z_normal = np.clip(
            (value_col - row_mean) / row_std.replace(0, np.nan),
            -_WINSORIZE_SIGMA,
            _WINSORIZE_SIGMA,
        )

        if inflated_dates:
            # 零膨胀日期: 零值→z=0, 非零值→用非零值自身 μ/σ 标准化 + clip
            # 对应 _standardize_zero_inflated 的零值分离逻辑
            nonzero_vals = value_col.where(~zero_mask)
            daily_mean_nz = nonzero_vals.groupby(factor_df["date"]).mean()
            daily_std_nz = nonzero_vals.groupby(factor_df["date"]).std()
            daily_count_nz = (~zero_mask).groupby(factor_df["date"]).sum()

            row_mean_nz = date_col.map(daily_mean_nz)
            row_std_nz = date_col.map(daily_std_nz)
            row_count_nz = date_col.map(daily_count_nz)

            z_zi = np.clip(
                (value_col - row_mean_nz) / row_std_nz.replace(0, np.nan),
                -_WINSORIZE_SIGMA,
                _WINSORIZE_SIGMA,
            )
            # 退化条件 → z=0 (对应 _standardize_zero_inflated 的 len<=1 和 sigma==0 分支)
            degenerate_mask = (row_count_nz <= 1) | row_std_nz.isna() | (row_std_nz == 0)
            z_zi = z_zi.where(~degenerate_mask, 0.0)
            # 零值 → z=0 (中性信号)
            z_zi = z_zi.where(~zero_mask, 0.0)

            # 按日期选择分支: 零膨胀日期用 z_zi, 正常日期用 z_normal
            is_zi_date = date_col.isin(inflated_dates)
            std_results[std_col] = z_zi.where(is_zi_date, z_normal)

            # v2.51 (OOM 炸弹4): 释放零膨胀分支临时对象
            # 35因子循环中，每个零膨胀因子产生 ~8 个 1.39M 元素 Series (~85MB)
            # pandas/numpy 内存分配器不还给 OS，35 次循环累积 ~3GB 碎片触发 global OOM
            del nonzero_vals, daily_mean_nz, daily_std_nz, daily_count_nz
            del row_mean_nz, row_std_nz, row_count_nz, z_zi, is_zi_date, degenerate_mask
        else:
            std_results[std_col] = z_normal

        # v2.51 (OOM 炸弹4): 每因子循环结束后释放临时对象
        # row_mean/row_std/z_normal 各 1.39M float64 ≈ 33MB/因子
        # 点质量检测的 groupby+merge 临时 DataFrame ≈ 60MB/因子
        # 不显式释放则 35 因子累积 ~3GB 碎片，叠加 factor_df + return_df + ic_data 触发 OOM
        del daily_stats, daily_group_size, daily_zero_count, daily_zero_ratio
        del row_mean, row_std, z_normal, zero_mask

        # v2.28: skip_point_mass=True 时跳过点质量检测（auto_select 简化模式）
        # 设计依据：相关性矩阵只需粗粒度 z-score，Pearson corr() 对 NaN 鲁棒；
        #   点质量检测仅影响因子内部极端值标记，不影响因子间线性关系。
        #   简化模式跳过 ~60MB × 45 次 groupby+merge 临时对象，显著降低内存峰值。
        if not skip_point_mass:
            # v2.20: 点质量检测——某值在截面中出现频率 >1% 且 z-score 超阈值时置 NaN
            # 典型场景：tail_price_position close=tail_low→0.0，68/3019=2.3% 股票挤在同一值
            # v2.24: 向量化重写——groupby+merge 预计算替代 iterrows+全表过滤
            #   根因：_POINT_MASS_ZSCORE_GATE=1.0 导致 30% 行被标记为 extreme，
            #   iterrows 每次 3 次 O(N) 全表扫描，150 万行 × 45 万组合 = 71 小时
            #   修复：groupby(["date", col]).size() 一次性预计算所有 (date, value) 频率，
            #   merge 回原 df 批量标记，复杂度 O(N log N)
            # v2.26 (2026-06-20): 离散型因子豁免——unique/N < 5% 或 unique < 20 时跳过
            #   典型场景：positive_day_ratio_5 只有 6 个值(0.0~1.0)，4/6 个值的 |z|>1.0
            #   导致 80%+ 股票 z-score 被置 NaN，因子实际零贡献
            val_counts = factor_df.groupby(["date", col]).size().reset_index(name="val_count")
            date_totals = factor_df.groupby("date")[col].count().reset_index(name="date_total")
            val_counts = val_counts.merge(date_totals, on="date")
            val_counts["frequency"] = val_counts["val_count"] / val_counts["date_total"]

            # v2.26: 离散度判断——每日截面 unique 值数
            daily_unique = factor_df.groupby("date")[col].nunique()
            daily_n = factor_df.groupby("date")[col].count()
            is_discrete = (daily_unique / daily_n < _DISCRETE_UNIQUE_RATIO) | (daily_unique < _DISCRETE_MIN_UNIQUE)
            discrete_dates = list(daily_unique.index[is_discrete])  # type: ignore[reportArgumentType]

            if discrete_dates:
                logger.info(
                    "因子 %s 在 %d 个日期判定为离散型 (unique/N < %.0f%% 或 unique < %d)，跳过点质量检测",
                    col,
                    len(discrete_dates),
                    _DISCRETE_UNIQUE_RATIO * 100,
                    _DISCRETE_MIN_UNIQUE,
                )

            # 只对非离散日期执行点质量检测
            point_mass = val_counts[
                (val_counts["frequency"] > _POINT_MASS_THRESHOLD) & (~val_counts["date"].isin(discrete_dates))
            ]

            # v2.27 (2026-06-20): 物理边界值豁免——高频值=当日截面 min/max 时不置 NaN
            # 理由：有界分布(如 [0,1])的边界值是真实极端信号，不是数据噪声。
            #   tail_price_position=0.0 表示"价格处于窗口期最低点"，11% 股票触底
            #   在下跌市中完全正常。将其置 NaN 等于消除最极端的真实信号。
            #   点质量检测应只针对中间值的异常聚集（可能是计算 bug），
            #   而非物理边界的自然聚集。遵循 AGENTS.md 规则 #15（第一性原理）。
            if not point_mass.empty:
                daily_bounds = factor_df.groupby("date")[col].agg(["min", "max"]).reset_index()
                daily_bounds.columns = ["date", "daily_min", "daily_max"]
                point_mass = point_mass.merge(daily_bounds, on="date")
                is_boundary = (point_mass[col] == point_mass["daily_min"]) | (
                    point_mass[col] == point_mass["daily_max"]
                )
                boundary_count = int(is_boundary.sum())
                if boundary_count > 0:
                    logger.info(
                        "因子 %s 物理边界豁免: %d 个 (date,value) 组合为截面 min/max，跳过点质量检测",
                        col,
                        boundary_count,
                    )
                point_mass = point_mass[~is_boundary].drop(columns=["daily_min", "daily_max"])

            if not point_mass.empty:
                pm_flags = factor_df[["date", col]].merge(
                    point_mass[["date", col]],
                    on=["date", col],
                    how="left",
                    indicator=True,
                )
                pm_mask = (pm_flags["_merge"] == "both").values
                z_mask = (std_results[std_col].abs() > _POINT_MASS_ZSCORE_GATE).values
                std_results[std_col] = std_results[std_col].where(~(pm_mask & z_mask), np.nan)

                # 逐值详情降为 debug：数万条/因子的逐值日志导致 416M 日志/次（v2.25 修复）
                for _, row in point_mass.iterrows():
                    logger.debug(
                        "因子 %s 在 %s 检测到点质量: value=%.4f, count=%d (%.1f%%), z-score 置 NaN",
                        col,
                        row["date"],
                        row[col],
                        int(row["val_count"]),
                        row["frequency"] * 100,
                    )
                # 汇总信息：每因子一条 info，足够运维判断
                pm_affected_rows = int((pm_mask & z_mask).sum())
                pm_affected_dates = len(set(point_mass["date"]))
                logger.info(
                    "因子 %s 点质量检测: %d 个 (date,value) 组合, 涉及 %d 天, %d 行 z-score 置 NaN",
                    col,
                    len(point_mass),
                    pm_affected_dates,
                    pm_affected_rows,
                )

            # NaN 处理：原因子值为 NaN 时标准化后仍为 NaN
            # 使用 fillna 保持原本 NaN 的位置，而非 .loc 后置还原
            std_results[std_col] = std_results[std_col].where(~factor_df[col].isna(), np.nan)

            # v2.51 (OOM 炸弹4): 释放点质量检测分支临时对象
            # groupby+merge 链产生 ~60MB/因子的临时 DataFrame，不释放则累积触发 OOM
            del val_counts, date_totals, daily_unique, daily_n
            if not point_mass.empty:
                del daily_bounds, pm_flags, pm_mask, z_mask

        # v2.51 (OOM 炸弹4): 每因子循环末尾 gc 回收内存碎片
        # date_col/value_col 是对 factor_df 列的引用（非独立 buffer），不需 del
        # 但 numpy/pandas 分配器缓存的临时 buffer 需要 gc 触发释放
        gc.collect()
        # v2.52 (OOM 炸弹5, 模式7): glibc malloc arena 碎片不归还 OS
        # gc.collect() 回收 Python 对象，但 glibc malloc 只把碎片放入 arena bins
        # 不调用 munmap 归还 OS。107 次标准化循环（auto_select 72 + 主流程 35）累积
        # ~5.6GB 碎片，远超 ~600MB 活跃数据 → OOM SIGKILL
        # malloc_trim(0) 强制 glibc 归还所有 free 的 arena 页给 OS
        _trim_arena()

    # v2.52 (OOM 炸弹6, 模式3c): pd.concat 批量添加所有 _std 列
    # 一次性创建所有新列的 Block，避免逐列 insert 的 N 次碎片化
    if std_results:
        factor_df = pd.concat([factor_df, pd.DataFrame(std_results, index=factor_df.index)], axis=1)
        del std_results
        gc.collect()
        _trim_arena()

    logger.info("因子标准化完成: %d 个因子", len(factor_cols))

    return factor_df


def calc_factor_correlation(
    factor_df: pd.DataFrame, factor_cols: list[str], logger: logging.Logger | None = None
) -> pd.DataFrame:
    """计算因子相关性矩阵

    Args:
        factor_df: 因子 DataFrame（必须包含标准化因子列 *_std）
        factor_cols: 因子列名（原始列名，会自动转换为 _std 列）
        logger: 日志对象

    Returns:
        相关性矩阵 DataFrame

    Precondition:
        factor_df 必须包含 *_std 列（由 standardize_factors 生成）
        如果 _std 列不存在，抛出 ValueError

    接口约定（MODULE.md 规范）：
        - 输入列名：原始因子列名（与 WeightEngine.calculate() 一致）
        - 内部转换：std_cols = [f'{col}_std' for col in factor_cols]
        - 调用方必须在调用此函数前先调用 standardize_factors()
    """
    if logger is None:
        from comprehensive_factor.common.logger_config import get_logger

        logger = get_logger(__name__)

    # 使用标准化后的因子计算相关性（更稳定）
    std_cols = [f"{col}_std" for col in factor_cols]

    # 修复：前置校验 _std 列存在性
    for std_col in std_cols:
        if std_col not in factor_df.columns:
            raise ValueError(
                f"factor_df 缺少标准化因子列 '{std_col}'，当前列: {list(factor_df.columns)}\n"
                "可能原因：\n"
                "  1. 调用方未先调用 standardize_factors()\n"
                "  2. standardize_factors 参数 factor_cols 与 calc_factor_correlation 不一致\n"
                "  3. factor_df 数据被意外修改或过滤\n"
                "调用顺序：load_factor_values → standardize_factors → calc_factor_correlation"
            )

    corr_matrix = factor_df[std_cols].corr()

    # 还原原始列名作为索引
    corr_matrix.index = factor_cols
    corr_matrix.columns = factor_cols

    logger.info("因子相关性矩阵计算完成")

    return corr_matrix
