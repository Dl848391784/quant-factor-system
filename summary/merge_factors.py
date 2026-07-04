#!/usr/bin/env python3
"""
因子数据合并脚本

功能：
1. 加载主数据源 factor_data.json.gz
2. 加载所有 parquet 因子文件
3. 数据对齐（基于 date + asset）
4. 命名统一（使用 parquet 文件名作为因子名）
5. 生成合并后数据

使用方法：
    python summary/merge_factors.py                     # 使用默认因子列表
    python summary/merge_factors.py --factors A_FA_N0112 B_atr_pct  # 指定因子
    python summary/merge_factors.py --list-factors      # 列出可用因子
    python summary/merge_factors.py --output ./output   # 指定输出目录
    python summary/merge_factors.py --config factors.json  # 从配置文件读取因子列表

版本历史：
    v1.0: 基础版本（硬编码路径）
    v1.1: 2026-05-28 符合研发规范：添加版本常量、setup_logger、返回类型注解、异常处理、pytest测试
    v1.2: 2026-05-28 第二轮深度审查：精确化异常处理、删除未使用变量、函数拆分、argparse支持、流程文档
    v1.3: 2026-05-28 第三轮深度审查：删除未使用导入/常量、固定日志文件名、进度显示、数据验证、配置文件支持
    v1.4: 2026-05-28 第四轮深度审查（10项修复）：
        - load_main_data JSON顶层结构兼容处理，空数据时warning并返回None
        - 捕获pd.DataFrame异常(ValueError)
        - parquet异常类型修正(EmptyDataError无效，改为Exception)
        - detect_value_column取第一个非必需列而非最后一个
        - merge_single_factor合并前去重防止行数膨胀
        - merge_factors单次循环避免内存峰值
        - 添加因子列表来源日志(未指定时使用默认列表)
        - main函数明确打印因子列表来源
        - 删除冗余source_desc字段，改为source_file
        - list_available_factors单次输出避免刷屏
"""

__version__ = "1.4"
__author__ = "factor_ic_analyzer"

# 标准库导入
import argparse
import gzip
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# 第三方库导入
import pandas as pd


# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.resolve()

# 数据路径配置
DATA_PATHS = {
    "factor_data": "data_fetchers/result",
    "factors": "data_fetchers/result/factors",
    "config": "summary/config",
}

# 默认因子列表（可通过配置文件覆盖）
DEFAULT_FACTORS = [
    "A_FA_N0112",
    "A_FA_N0322",
    "A_FA_N0340",
    "B_atr_pct",
    "B_bollinger_width_20",
    "B_cci_overbought",
    "B_keltner_position",
    "B_ma_trend",
    "B_mfi_overbought",
    "B_plus_di_14",
    "B_rsi_24",
    "B_trend_strength",
    "B_volatility_ratio",
    "C_genetic_combo",
]

# 输出文件名常量
OUTPUT_FILES = {
    "metadata": "factor_data_merged_metadata.json",
    "parquet": "factor_data_merged.parquet",
}

# 必需列名（用于数据对齐）
REQUIRED_COLUMNS = ["date", "asset"]

# 预期因子值列名（按优先级排序）
FACTOR_VALUE_COLUMNS = ["factor_value", "value", "val"]

# 默认配置文件名
DEFAULT_CONFIG_FILE = "merge_factors_config.json"


def setup_logger(name: str = "merge_factors") -> logging.Logger:
    """配置日志记录器

    Args:
        name: 日志记录器名称

    Returns:
        配置好的 Logger 对象
    """
    logger = logging.getLogger(name)

    if not logger.handlers:
        # 日志文件路径（固定文件名，避免产生大量日志文件）
        log_dir = PROJECT_ROOT / "summary" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)

        log_file = log_dir / "merge_factors.log"

        # 文件处理器
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)

        # 控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)

        # 日志格式
        formatter = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        logger.setLevel(logging.DEBUG)

    return logger


def load_config(config_file: Path | None, logger: logging.Logger) -> list[str] | None:
    """从配置文件加载因子列表

    Args:
        config_file: 配置文件路径
        logger: 日志记录器

    Returns:
        因子列表，或 None（配置文件不存在或解析失败）
    """
    if config_file is None:
        return None

    if not config_file.exists():
        logger.warning("配置文件不存在: %s", config_file)
        return None

    try:
        with open(config_file, encoding="utf-8") as f:
            config = json.load(f)

        factors = config.get("factors", [])
        if factors:
            logger.info("从配置文件加载因子列表: %s (%s 个)", config_file, len(factors))
            return factors

        logger.warning("配置文件缺少 'factors' 字段: %s", config_file)
        return None

    except json.JSONDecodeError as e:
        logger.error("配置文件 JSON 解析失败: %s", e)
        return None
    except OSError as e:
        logger.error("配置文件读取失败: %s", e)
        return None


def load_main_data(logger: logging.Logger) -> pd.DataFrame | None:
    """加载主数据源

    Args:
        logger: 日志记录器

    Returns:
        主数据 DataFrame，或 None（加载失败）
    """
    main_data_file = PROJECT_ROOT / DATA_PATHS["factor_data"] / "factor_data.json.gz"

    if not main_data_file.exists():
        logger.warning("主数据源文件不存在: %s", main_data_file)
        return None

    logger.info("加载主数据源: %s", main_data_file)

    try:
        with gzip.open(main_data_file, "rt", encoding="utf-8") as f:
            raw_data = json.load(f)

        # 检查 JSON 结构：期望顶层是 dict 且包含 'data' 键
        if isinstance(raw_data, dict):
            data = raw_data.get("data", [])
            if not data:
                logger.warning("主数据源 JSON 'data' 字段为空或不存在")
                return None
        elif isinstance(raw_data, list):
            # 顶层直接是数组（兼容处理）
            data = raw_data
            logger.warning("主数据源 JSON 顶层为数组而非 dict，已兼容处理")
        else:
            logger.error("主数据源 JSON 结构异常: %s", type(raw_data).__name__)
            return None

        df = pd.DataFrame(data)
        logger.info("主数据源加载完成: %s 条记录, %s 列", len(df), len(df.columns))
        logger.debug("主数据列: %s", df.columns.tolist())
        return df
    except gzip.BadGzipFile as e:
        logger.error("主数据源 gzip 格式错误: %s", e)
        return None
    except json.JSONDecodeError as e:
        logger.error("主数据源 JSON 解析失败: %s", e)
        return None
    except (OSError, ValueError) as e:
        # ValueError: pd.DataFrame(data) 数据结构不合法（如嵌套结构不一致）
        logger.error("主数据源数据格式错误: %s", e)
        return None


def load_parquet_factor(factor_name: str, logger: logging.Logger) -> pd.DataFrame | None:
    """加载单个 parquet 因子文件

    Args:
        factor_name: 因子名称
        logger: 日志记录器

    Returns:
        因子 DataFrame，或 None（文件不存在或加载失败）
    """
    factors_dir = PROJECT_ROOT / DATA_PATHS["factors"]
    filepath = factors_dir / f"{factor_name}.parquet"

    if not filepath.exists():
        logger.warning("因子文件不存在: %s", filepath)
        return None

    try:
        df = pd.read_parquet(filepath)
        logger.info("加载因子 %s: %s 条记录", factor_name, len(df))
        return df
    except OSError as e:
        logger.error("因子 %s 文件读取错误: %s", factor_name, e)
        return None
    except Exception as e:
        # parquet 空文件或损坏可能抛出 pyarrow.lib.ArrowInvalid 等异常
        # pd.errors.EmptyDataError 仅适用于 CSV 等文本格式，parquet 不抛出此异常
        logger.error("因子 %s 数据解析错误 (%s): %s", factor_name, type(e).__name__, e)
        return None


def detect_value_column(factor_df: pd.DataFrame, factor_name: str, logger: logging.Logger) -> str | None:
    """检测因子值列名

    Args:
        factor_df: 因子 DataFrame
        factor_name: 因子名称（用于日志）
        logger: 日志记录器

    Returns:
        值列名，或 None（无法确定）
    """
    columns = factor_df.columns.tolist()

    # 按优先级检查预期列名
    for col in FACTOR_VALUE_COLUMNS:
        if col in columns:
            return col

    # 排除必需列后，取第一个非必需列（最后一列可能是时间戳等辅助字段）
    non_required_cols = [c for c in columns if c not in REQUIRED_COLUMNS]

    if non_required_cols:
        value_col = non_required_cols[0]  # 取第一个而非最后一个
        logger.debug("因子 %s 使用推断列名: %s", factor_name, value_col)
        return value_col

    logger.error("因子 %s 无法确定值列名，列: %s", factor_name, columns)
    return None


def merge_single_factor(
    merged_df: pd.DataFrame, factor_df: pd.DataFrame, factor_name: str, logger: logging.Logger
) -> pd.DataFrame:
    """合并单个因子到主数据

    Args:
        merged_df: 当前合并后的 DataFrame
        factor_df: 因子 DataFrame
        factor_name: 因子名称
        logger: 日志记录器

    Returns:
        合并后的 DataFrame
    """
    # 检查必需列
    if not all(col in factor_df.columns for col in REQUIRED_COLUMNS):
        logger.error("因子 %s 缺少必需列 %s，跳过", factor_name, REQUIRED_COLUMNS)
        return merged_df

    # 检测值列名
    value_col = detect_value_column(factor_df, factor_name, logger)
    if value_col is None:
        return merged_df

    # 重命名因子值列为因子名
    factor_df_renamed = factor_df[REQUIRED_COLUMNS + [value_col]].copy()
    factor_df_renamed.columns = REQUIRED_COLUMNS + [factor_name]

    # 去重检查：若因子文件中 date + asset 存在重复行，合并后行数会膨胀
    original_len = len(factor_df_renamed)
    factor_df_renamed = factor_df_renamed.drop_duplicates(subset=REQUIRED_COLUMNS, keep="first")
    if len(factor_df_renamed) < original_len:
        logger.warning("因子 %s 存在重复键（%s → %s），已去重", factor_name, original_len, len(factor_df_renamed))

    # 合并
    merged_df = merged_df.merge(factor_df_renamed, on=REQUIRED_COLUMNS, how="left")

    # 统计有效值
    total_rows = len(merged_df)
    valid_count = merged_df[factor_name].notna().sum()
    coverage_pct = valid_count / total_rows * 100 if total_rows > 0 else 0
    logger.info("  ✓ %s: 有效记录 %s / %s (%.1f%%)", factor_name, f"{valid_count:,}", f"{total_rows:,}", coverage_pct)

    return merged_df


def validate_merged_data(
    merged_df: pd.DataFrame, original_df: pd.DataFrame, merged_factors: list[str], logger: logging.Logger
) -> dict[str, bool]:
    """验证合并后的数据完整性

    Args:
        merged_df: 合并后的 DataFrame
        original_df: 原始主数据 DataFrame
        merged_factors: 成功合并的因子列表
        logger: 日志记录器

    Returns:
        验证结果字典 {检查项: 是否通过}
    """
    results = {}

    # 1. 检查记录数不变
    results["records_count"] = len(merged_df) == len(original_df)
    if not results["records_count"]:
        logger.error("验证失败: 记录数变化 %s → %s", len(original_df), len(merged_df))

    # 2. 检查必需列完整
    results["required_columns"] = all(col in merged_df.columns for col in REQUIRED_COLUMNS)
    if not results["required_columns"]:
        logger.error("验证失败: 缺少必需列 %s", REQUIRED_COLUMNS)

    # 3. 检查原始列保留
    original_cols = original_df.columns.tolist()
    results["original_columns"] = all(col in merged_df.columns for col in original_cols)
    if not results["original_columns"]:
        missing = [c for c in original_cols if c not in merged_df.columns]
        logger.error("验证失败: 原始列丢失 %s", missing)

    # 4. 检查新增因子列存在
    results["new_factors"] = all(f in merged_df.columns for f in merged_factors)
    if not results["new_factors"]:
        missing = [f for f in merged_factors if f not in merged_df.columns]
        logger.error("验证失败: 新因子列丢失 %s", missing)

    # 汇总
    all_passed = all(results.values())
    if all_passed:
        logger.info("数据验证通过: %s 条记录, %s 列", len(merged_df), len(merged_df.columns))
    else:
        failed = [k for k, v in results.items() if not v]
        logger.warning("数据验证部分失败: %s", failed)

    return results


def save_merged_data(
    merged_df: pd.DataFrame, output_dir: Path, merged_factors: list[str], logger: logging.Logger
) -> bool:
    """保存合并后的数据

    Args:
        merged_df: 合并后的 DataFrame
        output_dir: 输出目录
        merged_factors: 成功合并的因子列表
        logger: 日志记录器

    Returns:
        是否保存成功
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    output_parquet = output_dir / OUTPUT_FILES["parquet"]
    metadata_file = output_dir / OUTPUT_FILES["metadata"]

    logger.info("保存合并数据到: %s", output_dir)

    try:
        # 保存 Parquet 文件
        merged_df.to_parquet(output_parquet, index=False, compression="gzip")
        file_size_mb = output_parquet.stat().st_size / 1024 / 1024
        logger.info("  Parquet文件: %s", output_parquet)
        logger.info("  文件大小: %.2f MB", file_size_mb)

        # 保存元数据（merged_factors 已包含完整因子列表，无需冗余的 source 描述）
        total_factors = len(merged_df.columns) - len(REQUIRED_COLUMNS)

        metadata = {
            "created_at": datetime.now().isoformat(),
            "total_records": len(merged_df),
            "total_factors": total_factors,
            "merged_factors": merged_factors,  # 完整因子列表
            "factors": merged_df.columns.tolist(),
            "source_file": "factor_data.json.gz",  # 仅记录数据源文件名
            "script_version": __version__,
        }

        with open(metadata_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        logger.info("  元数据文件: %s", metadata_file)

        return True

    except OSError as e:
        logger.error("保存数据文件系统错误: %s", e)
        return False
    except ValueError as e:
        logger.error("保存数据格式错误: %s", e)
        return False


def merge_factors(
    logger: logging.Logger, factor_list: list[str] | None = None, output_dir: Path | None = None
) -> pd.DataFrame | None:
    """合并所有因子

    Args:
        logger: 日志记录器
        factor_list: 因子列表（None 则使用默认列表）
        output_dir: 输出目录（None 则使用默认目录）

    Returns:
        合并后的 DataFrame，或 None（合并失败）
    """
    # 使用默认值
    factors = factor_list if factor_list is not None else DEFAULT_FACTORS
    if factor_list is None:
        logger.info("未指定因子列表，使用内置默认列表（%s 个因子）", len(factors))
    out_dir = output_dir if output_dir is not None else PROJECT_ROOT / DATA_PATHS["factor_data"]

    logger.info("=" * 60)
    logger.info("开始合并因子数据 (版本 %s)", __version__)
    logger.info("目标因子数: %s", len(factors))
    logger.info("=" * 60)

    # 1. 加载主数据源
    main_df = load_main_data(logger)
    if main_df is None:
        logger.error("主数据源加载失败，无法继续合并")
        return None

    # 2. 单次循环：加载后立即合并再释放（避免内存峰值）
    merged_df = main_df.copy()
    merged_factors: list[str] = []
    loaded_count = 0
    logger.info("开始处理 %s 个因子（加载后立即合并）...", len(factors))

    for i, factor_name in enumerate(factors, 1):
        logger.info("[%s/%s] 处理 %s...", i, len(factors), factor_name)

        # 加载因子
        factor_df = load_parquet_factor(factor_name, logger)
        if factor_df is None:
            continue

        loaded_count += 1

        # 立即合并
        merged_df = merge_single_factor(merged_df, factor_df, factor_name, logger)

        # 检查是否成功合并
        if factor_name in merged_df.columns:
            merged_factors.append(factor_name)

        # 释放因子 DataFrame 内存（合并后不再需要）
        del factor_df

    logger.info("成功加载 %s / %s 个因子", loaded_count, len(factors))

    if not merged_factors:
        logger.warning("没有成功合并任何因子，返回原始主数据")
        return main_df

    # 4. 数据验证
    logger.info("=" * 60)
    logger.info("数据验证...")
    validate_merged_data(merged_df, main_df, merged_factors, logger)  # noqa: F841  # 函数内有 logger.info 副作用, 不检查返回值

    # 5. 汇总统计
    logger.info("=" * 60)
    logger.info("合并完成统计:")
    logger.info("  原始列数: %s", len(main_df.columns))
    logger.info("  合并后列数: %s", len(merged_df.columns))
    logger.info("  成功合并因子数: %s / %s", len(merged_factors), len(factors))
    logger.info("  新增因子数: %s", len(merged_df.columns) - len(main_df.columns))
    logger.info("  总记录数: %s", f"{len(merged_df):,}")
    logger.debug("  所有列: %s", merged_df.columns.tolist())

    # 6. 保存合并后的数据
    if save_merged_data(merged_df, out_dir, merged_factors, logger):
        logger.info("✓ 保存完成")
    else:
        logger.warning("保存失败，但合并数据仍可用")

    return merged_df


def list_available_factors(logger: logging.Logger) -> list[str]:
    """列出可用的因子文件

    Args:
        logger: 日志记录器

    Returns:
        可用因子名称列表
    """
    factors_dir = PROJECT_ROOT / DATA_PATHS["factors"]

    if not factors_dir.exists():
        logger.warning("因子目录不存在: %s", factors_dir)
        return []

    available = [f.stem for f in factors_dir.glob("*.parquet")]

    if available:
        # 单次输出因子列表，避免逐行刷屏
        sorted_factors = sorted(available)
        logger.info("可用因子 (%s 个): %s", len(available), ", ".join(sorted_factors))
    else:
        logger.warning("因子目录中没有 parquet 文件")

    return available


def parse_args() -> argparse.Namespace:
    """解析命令行参数

    Returns:
        解析后的参数对象
    """
    parser = argparse.ArgumentParser(
        description="合并因子数据到主数据源",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python summary/merge_factors.py                        # 使用默认因子列表
  python summary/merge_factors.py --factors A_FA_N0112 B_atr_pct  # 指定因子
  python summary/merge_factors.py --list-factors         # 列出可用因子
  python summary/merge_factors.py --output ./output      # 指定输出目录
  python summary/merge_factors.py --config factors.json  # 从配置文件读取因子列表
        """,
    )

    parser.add_argument("--factors", "-f", nargs="+", default=None, help="指定要合并的因子列表（默认使用内置14个因子）")

    parser.add_argument("--output", "-o", type=Path, default=None, help="指定输出目录（默认: data_fetchers/result）")

    parser.add_argument(
        "--config",
        "-c",
        type=Path,
        default=None,
        help=f"从配置文件读取因子列表（默认: summary/config/{DEFAULT_CONFIG_FILE}）",
    )

    parser.add_argument("--list-factors", "-l", action="store_true", help="列出因子目录中所有可用的因子文件")

    parser.add_argument("--version", "-v", action="version", version=f"merge_factors {__version__}")

    return parser.parse_args()


def main() -> None:
    """主函数"""
    args = parse_args()
    logger = setup_logger("merge_factors")

    # 列出可用因子
    if args.list_factors:
        list_available_factors(logger)
        sys.exit(0)

    # 确定因子列表（优先级：命令行 > 配置文件 > 默认）
    factor_list = args.factors
    source_desc = None  # 因子列表来源描述

    if factor_list is not None:
        source_desc = f"命令行参数 ({len(factor_list)} 个)"
    elif args.config is not None:
        factor_list = load_config(args.config, logger)
        if factor_list is not None:
            source_desc = f"配置文件 {args.config} ({len(factor_list)} 个)"
    else:
        # 尝试默认配置文件
        default_config = PROJECT_ROOT / DATA_PATHS["config"] / DEFAULT_CONFIG_FILE
        factor_list = load_config(default_config, logger)
        if factor_list is not None:
            source_desc = f"默认配置文件 {DEFAULT_CONFIG_FILE} ({len(factor_list)} 个)"

    # 明确打印因子列表来源
    if source_desc:
        logger.info("因子列表来源: %s", source_desc)
    else:
        logger.info("因子列表来源: 内置默认列表 (%s 个)", len(DEFAULT_FACTORS))

    # 合并因子
    merged_df = merge_factors(logger, factor_list=factor_list, output_dir=args.output)

    if merged_df is not None:
        logger.info("=" * 60)
        logger.info("✓ 因子合并流程完成")
        logger.info("=" * 60)
    else:
        logger.error("因子合并流程失败")
        sys.exit(1)


if __name__ == "__main__":
    main()
