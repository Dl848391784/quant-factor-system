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

import gzip
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd


# 统一数据源路径（遵循 PROJECT.md 跨模块数据路径规范）
DEFAULT_DATA_SOURCE = Path(__file__).parent.parent.parent / "data_fetchers" / "result" / "factor_ic_data.json.gz"
DEFAULT_IC_RESULT_DIR = Path(__file__).parent.parent.parent / "factor_ic" / "result"


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

    full_df: pd.DataFrame

    try:
        import array

        import ijson

        # peek 首条记录决定列集合（仅当 factor_cols=None 时）+ 推断列类型
        with gzip.open(data_source, "rb") as f:
            first_record = next(iter(ijson.items(f, "data.item")), None)
        if first_record is None:
            raise KeyError(f"数据源 JSON 'data' 数组为空: {data_source}")

        if required_cols is None:
            required_cols = list(first_record.keys())

        # 类型分类：str 列用 list（date/asset），数值列用 array.array('d')（每元素 8 字节，
        # 比 list[float] 的 ~28 字节降 70% 内存）。后续 np.frombuffer 零拷贝转 numpy。
        # 对于 1.49M 行 × 42 数值列，columns 累积约 0.5GB（vs list[float] 1.87GB）
        STR_COLS = {"date", "asset"}
        str_columns: dict[str, list[str | None]] = {col: [] for col in required_cols if col in STR_COLS}
        num_columns: dict[str, array.array[float]] = {
            col: array.array("d") for col in required_cols if col not in STR_COLS
        }

        with gzip.open(data_source, "rb") as f:
            for record in ijson.items(f, "data.item"):
                for col, lst in str_columns.items():
                    val = record.get(col)
                    lst.append(str(val) if val is not None else None)
                for col, arr in num_columns.items():
                    val = record.get(col)
                    # ijson 对数字返回 Decimal，array('d') 接受 float
                    arr.append(float(val) if val is not None else float("nan"))

        if not str_columns.get("date") and "date" in required_cols:
            raise KeyError(f"数据源 JSON 'data' 数组为空: {data_source}")

        # 构建 DataFrame：数值列 zero-copy 转 numpy，str 列保持 list
        df_data: dict[str, object] = {}
        for col in required_cols:
            if col in str_columns:
                df_data[col] = str_columns[col]
            else:
                # np.frombuffer 共享 array.array 内存（zero-copy）
                df_data[col] = np.frombuffer(num_columns[col], dtype=np.float64).copy()

        full_df = pd.DataFrame(df_data)
        del df_data, str_columns, num_columns
        import gc

        gc.collect()
        logger.info("ijson 流式加载完成: %d 行 × %d 列", len(full_df), len(full_df.columns))

    except ImportError:
        # ijson 不可用 → 回退到 json.load（保留兼容性，与 factor_ic v3 一致）
        logger.warning("ijson 不可用，回退到 json.load（峰值 ~4GB，可能 OOM）")
        with gzip.open(data_source, "rt", encoding="utf-8") as f:
            data = json.load(f)
        if "data" not in data:
            raise KeyError(f"数据源 JSON 结构缺失 'data' 字段: {data_source}") from None
        full_df = pd.DataFrame(data["data"])
        del data
        import gc

        gc.collect()
        # fallback 路径下的列过滤
        if factor_cols is not None and required_cols is not None:
            # 只保留请求的列（容忍 required_cols 中部分列缺失，与流式路径行为一致）
            available = [c for c in required_cols if c in full_df.columns]
            full_df = full_df[available].copy()  # type: ignore[assignment]  # pandas list-indexing 返回 DataFrame

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
    numeric_cols = [c for c in full_df.columns if c not in ("date", "asset")]
    for col in numeric_cols:
        full_df[col] = pd.to_numeric(full_df[col], errors="coerce")
    logger.info("数值列类型规范化完成: %d 列（pd.to_numeric, Decimal/str → float）", len(numeric_cols))

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

        # 提取 ic_values 和 dates/valid_dates 字段
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


def standardize_factors(
    factor_df: pd.DataFrame, factor_cols: list[str], logger: logging.Logger | None = None
) -> pd.DataFrame:
    """截面标准化因子值

    每日对每个因子做截面标准化（减均值除标准差）。

    Args:
        factor_df: 因子 DataFrame（包含 date, asset, 因子列）
        factor_cols: 需标准化的因子列名
        logger: 日志对象

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
    """
    if logger is None:
        from comprehensive_factor.common.logger_config import get_logger

        logger = get_logger(__name__)

    factor_df = factor_df.copy()

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
        factor_df[std_col] = factor_df.groupby("date")[col].transform(
            lambda x: np.clip((x - x.mean()) / x.std(), -_WINSORIZE_SIGMA, _WINSORIZE_SIGMA) if x.std() > 0 else np.nan
        )

        # NaN 处理：原因子值为 NaN 时标准化后仍为 NaN
        # 使用 fillna 保持原本 NaN 的位置，而非 .loc 后置还原
        factor_df.loc[factor_df[col].isna(), std_col] = np.nan

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
