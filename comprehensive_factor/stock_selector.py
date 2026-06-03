"""
股票选股脚本

功能:
1. 加载最优权重配置（从 weight_selection_result.json）
2. 加载因子数据（从 factor_ic_data.json.gz）
3. 使用最优权重方法计算综合因子值
4. 排序选出 Top N 股票

流程:
Step 1-5: 单因子分析 → 因子筛选 → 标准化 → 加权计算 → 分层回测
Step 6: 权重方式选择 (weight_selector.py)
Step 7: 股票选股 (stock_selector.py) ← 本脚本

作者: 云瑶
创建日期: 2026-06-03
"""

import json
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import cast

import numpy as np
import pandas as pd


# sys.path 处理（遵循 MODULE.md M49）
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))  # noqa: E402

# 导入公共模块（遵循 MODULE.md M2）
from comprehensive_factor.common.convert_types import convert_to_native_types  # noqa: E402
from comprehensive_factor.common.factor_loader import (  # noqa: E402
    load_factor_values,
    load_ic_daily,
    load_ic_results,
    standardize_factors,
)
from comprehensive_factor.common.logger_config import get_logger  # noqa: E402
from comprehensive_factor.common.weight_engine import WeightEngine  # noqa: E402


# ============================================================================
# 配置类
# ============================================================================

DEFAULT_DATA_SOURCE = PROJECT_ROOT / "data_fetchers" / "result" / "factor_ic_data.json.gz"
DEFAULT_IC_RESULT_DIR = PROJECT_ROOT / "factor_ic" / "result"
DEFAULT_WEIGHT_RESULT_PATH = PROJECT_ROOT / "comprehensive_factor" / "result" / "weight_selection_result.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "comprehensive_factor" / "result"

# 默认因子列表（与 CompositeLayerConfig 一致）
DEFAULT_FACTOR_LIST = [
    "rsi",
    "volume_ratio",
]

DEFAULT_FACTOR_COLS = [
    "rsi_6",
    "volume_ratio_5",
]


@dataclass
class StockSelectorConfig:
    """股票选股配置

    遵循 MODULE.md M46-48 规范：
    - 继承公共配置模式
    - 单一数据源

    Note:
        - factor_direction 固定为 'negative'（综合因子默认反向）
        - 参考 MODULE.md M79: 综合因子低值预期高收益
    """

    # === 因子参数 ===
    factor_list: list[str] = field(default_factory=lambda: DEFAULT_FACTOR_LIST)
    factor_cols: list[str] = field(default_factory=lambda: DEFAULT_FACTOR_COLS)

    # === 选股参数 ===
    top_n: int = 10  # 选出前 N 只股票
    factor_direction: str = "negative"  # 综合因子方向（反向）
    rolling_window: int = 60  # 滚动 ICIR 窗口

    # === 数据路径 ===
    data_source: Path | str | None = None  # 统一数据源
    ic_result_dir: Path | str | None = None  # IC 结果目录
    weight_result_path: Path | str | None = None  # 权重选择结果
    output_dir: Path | str | None = None  # 输出目录

    # === 时间参数 ===
    selection_date: str | None = None  # 选股日期（默认取最新日期）

    # === 其他 ===
    return_period: str = "1d"  # 收益周期

    def __post_init__(self) -> None:
        """路径默认值处理"""
        if self.data_source is None:
            self.data_source = DEFAULT_DATA_SOURCE
        if self.ic_result_dir is None:
            self.ic_result_dir = DEFAULT_IC_RESULT_DIR
        if self.weight_result_path is None:
            self.weight_result_path = DEFAULT_WEIGHT_RESULT_PATH
        if self.output_dir is None:
            self.output_dir = DEFAULT_OUTPUT_DIR

        # 转换为 Path 对象
        self.data_source = Path(self.data_source)
        self.ic_result_dir = Path(self.ic_result_dir)
        self.weight_result_path = Path(self.weight_result_path)
        self.output_dir = Path(self.output_dir)

    def validate(self) -> None:
        """校验配置完整性（遵循 MODULE.md H 规则）"""
        if not self.factor_list:
            raise ValueError("factor_list 不能为空")

        if not self.factor_cols:
            raise ValueError("factor_cols 不能为空")

        if len(self.factor_list) != len(self.factor_cols):
            raise ValueError(
                f"factor_list ({len(self.factor_list)}) 与 factor_cols ({len(self.factor_cols)}) 数量不一致"
            )

        if self.top_n <= 0:
            raise ValueError(f"top_n 必须大于 0，当前: {self.top_n}")

        if self.factor_direction not in ("positive", "negative"):
            raise ValueError(f"factor_direction 必须为 'positive' 或 'negative'，当前: {self.factor_direction}")


# ============================================================================
# 核心函数
# ============================================================================

# 浮点精度容差（遵循 MODULE.md M54）
EPSILON = 1e-10


def load_weight_config(weight_result_path: Path | str, logger: logging.Logger | None = None) -> dict:
    """加载权重选择结果

    Args:
        weight_result_path: 权重选择结果文件路径（Path 或 str）

    Raises:
        FileNotFoundError: 权重配置文件不存在
        ValueError: JSON 结构不完整
    """
    if logger is None:
        logger = get_logger(__name__)

    weight_result_path = Path(weight_result_path)

    if not weight_result_path.exists():
        raise FileNotFoundError(
            f"权重选择结果文件不存在: {weight_result_path}\n请先运行 weight_selector.py 生成最优权重配置"
        )

    logger.info("加载权重选择结果: %s", weight_result_path)

    try:
        with open(weight_result_path, encoding="utf-8") as f:
            weight_config = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"权重配置文件 JSON 解析失败: {weight_result_path}\n错误位置: {e.pos}") from e

    # 校验必需字段
    required_fields = ["best_selection"]
    for field_name in required_fields:
        if field_name not in weight_config:
            raise ValueError(f"权重配置文件缺失必需字段 '{field_name}'\n当前字段: {list(weight_config.keys())}")

    # 校验 best_selection 结构
    best_selection = weight_config["best_selection"]
    if "method" not in best_selection:
        raise ValueError(f"best_selection 缺失 'method' 字段\n当前字段: {list(best_selection.keys())}")

    logger.info(
        "最优权重方法: %s，综合得分: %.4f",
        best_selection["method"],
        best_selection.get("composite_score", "N/A"),
    )

    return weight_config


def get_latest_date(factor_df: pd.DataFrame, logger: logging.Logger | None = None) -> str:
    """获取最新日期

    Args:
        factor_df: 因子 DataFrame（包含 date 列）
        logger: 日志对象

    Returns:
        最新日期字符串（YYYY-MM-DD 格式）

    Raises:
        ValueError: date 列为空或数据为空
    """
    if logger is None:
        logger = get_logger(__name__)

    if len(factor_df) == 0:
        raise ValueError("factor_df 为空，无法获取最新日期")

    if "date" not in factor_df.columns:
        raise ValueError(f"factor_df 缺少 'date' 列，当前列: {list(factor_df.columns)}")

    # 获取唯一日期并排序
    dates = factor_df["date"].unique()
    dates_sorted = sorted(dates)
    latest_date = dates_sorted[-1]

    logger.info("数据最新日期: %s（共 %d 个日期）", latest_date, len(dates_sorted))

    return latest_date


def sort_and_select(
    composite_factor: pd.Series,
    factor_df: pd.DataFrame,
    top_n: int,
    factor_direction: str,
    logger: logging.Logger | None = None,
) -> list[dict]:
    """排序并选出 Top N 股票

    Args:
        composite_factor: 综合因子值 Series（索引与 factor_df 一致）
        factor_df: 因子 DataFrame（包含 asset 列）
        top_n: 选股数量
        factor_direction: 因子方向 ('positive' 或 'negative')
        logger: 日志对象

    Returns:
        选股结果列表，结构：
        [
            {"rank": 1, "code": "000001", "composite_value": -2.35, "factor_values": {...}},
            ...
        ]

    Note:
        - positive（正向）: 降序排序，值越大越好
        - negative（反向）: 升序排序，值越小越好
        - 缺失值（NaN）不参与排序，排在最后
    """
    if logger is None:
        logger = get_logger(__name__)

    # 构建 DataFrame（包含综合因子值）
    result_df = factor_df.copy()
    result_df["composite_factor"] = composite_factor

    # 过滤有效值（非 NaN）
    valid_mask = result_df["composite_factor"].notna()
    valid_count = valid_mask.sum()
    logger.info("有效综合因子值: %d 条（总计 %d 条）", valid_count, len(result_df))

    if valid_count == 0:
        raise ValueError(
            "综合因子值全部为 NaN，无法排序选股\n可能原因:\n  1. 所有因子值缺失\n  2. 标准化计算异常\n  3. 权重计算异常"
        )

    # 排序（根据因子方向）
    # ascending=True 升序（反向因子：值越小越好）
    # ascending=False 降序（正向因子：值越大越好）
    ascending: bool = factor_direction == "negative"

    # 先过滤有效值，再排序
    sorted_df = result_df[valid_mask].sort_values(by="composite_factor", ascending=ascending)

    # 取 Top N
    # 如果 top_n > 有效股票数，返回所有有效股票
    actual_n = min(top_n, len(sorted_df))
    top_stocks = sorted_df.head(actual_n)

    logger.info(
        "选出 Top %d 股票（排序方向: %s，实际有效股票: %d）",
        actual_n,
        "升序" if ascending else "降序",
        len(sorted_df),
    )

    # 构建结果列表
    result_list = []
    for rank_idx, (_, row) in enumerate(top_stocks.iterrows(), start=1):
        # 提取因子值
        factor_values = {}
        # 获取配置中的因子列（从 factor_df 列名推断）
        for col in factor_df.columns:
            if col in ["date", "asset", "composite_factor"] or col.endswith("_std"):
                continue
            if col in row:
                val = row[col]
                # 处理 NaN（遵循 MODULE.md M49）
                if pd.isna(val) or (isinstance(val, float) and np.abs(val) < EPSILON):
                    factor_values[col] = None
                else:
                    factor_values[col] = convert_to_native_types(val)

        result_list.append(
            {
                "rank": rank_idx,
                "code": row["asset"],
                "composite_value": convert_to_native_types(row["composite_factor"]),
                "factor_values": factor_values,
            }
        )

    return result_list


def build_result(
    top_stocks: list[dict],
    config: StockSelectorConfig,
    weight_config: dict,
    total_stocks: int,
    logger: logging.Logger | None = None,
) -> dict:
    """构建输出结果

    Args:
        top_stocks: 选股结果列表
        config: 配置对象
        weight_config: 权重配置
        total_stocks: 总股票数
        logger: 日志对象

    Returns:
        输出结果字典，结构见输出模板
    """
    if logger is None:
        logger = get_logger(__name__)

    best_selection = weight_config["best_selection"]

    result = {
        "meta": {
            "selection_date": config.selection_date,
            "weight_method": best_selection["method"],
            "composite_score": best_selection.get("composite_score"),
            "factor_direction": config.factor_direction,
            "top_n": config.top_n,
            "total_stocks": total_stocks,
            "valid_stocks": len(top_stocks),
            "created_at": datetime.now().isoformat(),
        },
        "top_stocks": top_stocks,
        "weight_config": {
            "method": best_selection["method"],
            "window": config.rolling_window if best_selection["method"] == "rolling_icir_weight" else None,
            "factor_list": config.factor_list,
            "factor_cols": config.factor_cols,
        },
    }

    logger.info("结果构建完成: 选股日期=%s，Top N=%d", config.selection_date, len(top_stocks))

    return result


def save_result(
    result: dict,
    output_dir: Path | str,
    logger: logging.Logger | None = None,
) -> Path:
    """保存结果到 JSON 文件

    Args:
        result: 结果字典
        output_dir: 输出目录（Path 或 str）
        logger: 日志对象

    Returns:
        输出文件路径

    Note:
        - 输出文件名: stock_selection_result.json
        - 遵循 MODULE.md M4: 输出到 comprehensive_factor/result/
    """
    if logger is None:
        logger = get_logger(__name__)

    # 转换为 Path
    output_dir = Path(output_dir)

    # 确保输出目录存在
    output_dir.mkdir(parents=True, exist_ok=True)

    # 输出文件名（固定）
    output_file = output_dir / "stock_selection_result.json"

    # 保存 JSON
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    logger.info("结果已保存: %s", output_file)

    return output_file


def select_stocks(
    config: StockSelectorConfig,
    logger: logging.Logger | None = None,
) -> tuple[dict, Path]:
    """股票选股主函数

    流程:
    1. 加载最优权重配置
    2. 加载因子数据
    3. 确定选股日期
    4. 过滤数据（只保留选股日期）
    5. 标准化因子
    6. 加载 IC 数据（根据权重方法）
    7. 计算综合因子
    8. 排序选出 Top N
    9. 构建结果
    10. 保存结果

    Args:
        config: 配置对象
        logger: 日志对象

    Returns:
        Tuple[result_dict, output_file_path]

    Raises:
        ValueError: 数据异常
        FileNotFoundError: 文件不存在
    """
    if logger is None:
        logger = get_logger(__name__)

    logger.info("=" * 60)
    logger.info("股票选股流程启动")
    logger.info("=" * 60)

    # Step 1: 校验配置
    config.validate()

    # Step 2: 加载最优权重配置
    # config.__post_init__ 已将 weight_result_path 转换为 Path，断言非 None
    assert config.weight_result_path is not None, "weight_result_path 应已初始化"
    weight_config = load_weight_config(config.weight_result_path, logger)
    best_method = weight_config["best_selection"]["method"]

    # Step 3: 加载因子数据
    logger.info("加载因子数据...")
    factor_df_raw = load_factor_values(config.factor_cols, config.data_source, logger)
    # 类型转换：load_factor_values 返回 DataFrame（pandas DataFrame 构造返回类型不稳定）
    factor_df = cast(pd.DataFrame, factor_df_raw)

    # Step 4: 确定选股日期
    if config.selection_date is None:
        config.selection_date = get_latest_date(factor_df, logger)

    # Step 5: 过滤数据（只保留选股日期）
    logger.info("过滤选股日期: %s", config.selection_date)
    factor_df = factor_df[factor_df["date"] == config.selection_date].copy()

    if len(factor_df) == 0:
        raise ValueError(f"选股日期 {config.selection_date} 无数据\n可用日期范围: 请检查 factor_ic_data.json.gz")

    total_stocks = len(factor_df)
    logger.info("选股日期股票数: %d", total_stocks)

    # Step 6: 标准化因子（截面标准化）
    # 注意：单日数据标准化时，每日截面就是当日所有股票
    logger.info("标准化因子...")
    factor_df = standardize_factors(factor_df, config.factor_cols, logger)

    # Step 7: 加载 IC 数据（根据权重方法）
    ic_results = None
    ic_daily_data = None

    if best_method == "rolling_icir_weight":
        # 滚动 ICIR 需要历史 IC 序列
        logger.info("加载 IC 每日序列（滚动 ICIR 需要）...")
        assert config.ic_result_dir is not None, "ic_result_dir 应已初始化"
        # 类型转换：config.__post_init__ 已将路径转换为 Path
        ic_result_dir_path = cast(Path, config.ic_result_dir)
        ic_daily_data = load_ic_daily(config.factor_list, ic_result_dir_path, config.return_period, logger)
    elif best_method in ("icir_weight", "ic_weight"):
        # 静态权重需要 IC 统计结果
        logger.info("加载 IC 统计结果（静态权重需要）...")
        assert config.ic_result_dir is not None, "ic_result_dir 应已初始化"
        # 类型转换：config.__post_init__ 已将路径转换为 Path
        ic_result_dir_path = cast(Path, config.ic_result_dir)
        ic_results, _ = load_ic_results(config.factor_list, ic_result_dir_path, config.return_period, logger)

    # Step 8: 计算综合因子
    logger.info("计算综合因子（权重方法: %s）...", best_method)
    weight_engine = WeightEngine(weight_method=best_method, window=config.rolling_window, logger=logger)
    composite_factor = weight_engine.calculate(factor_df, config.factor_cols, ic_results, ic_daily_data)

    # Step 9: 排序选出 Top N
    logger.info("排序选股（Top N: %d，方向: %s）...", config.top_n, config.factor_direction)
    top_stocks = sort_and_select(composite_factor, factor_df, config.top_n, config.factor_direction, logger)

    # Step 10: 构建结果
    result = build_result(top_stocks, config, weight_config, total_stocks, logger)

    # Step 11: 保存结果
    assert config.output_dir is not None, "output_dir 应已初始化"
    output_dir_path = cast(Path, config.output_dir)
    output_file = save_result(result, output_dir_path, logger)

    logger.info("=" * 60)
    logger.info("股票选股流程完成")
    logger.info("=" * 60)

    return result, output_file


# ============================================================================
# CLI 入口
# ============================================================================


def create_cli_entrypoint(config_class: type[StockSelectorConfig]) -> Callable[[], int]:
    """创建 CLI 入口（遵循 MODULE.md M41-45）

    遵循规范:
    - 退出码：成功 0，失败 1
    - 异常处理：保留堆栈信息
    - logger 传递：公共函数接收 logger 参数
    - 最小导入：CLI 入口只导入必需模块

    Args:
        config_class: 配置类

    Returns:
        CLI 入口函数
    """
    import argparse

    def main() -> int:
        """CLI 主函数"""
        logger = get_logger(__name__)

        parser = argparse.ArgumentParser(description="股票选股脚本 - 使用最优权重方法计算综合因子并选出 Top N 股票")

        # 选股参数
        parser.add_argument(
            "--top_n",
            type=int,
            default=10,
            help="选出前 N 只股票（默认: 10）",
        )

        parser.add_argument(
            "--selection_date",
            type=str,
            default=None,
            help="选股日期（YYYY-MM-DD，默认取最新日期）",
        )

        parser.add_argument(
            "--factor_direction",
            type=str,
            choices=["positive", "negative"],
            default="negative",
            help="因子方向（默认: negative，反向因子）",
        )

        parser.add_argument(
            "--rolling_window",
            type=int,
            default=60,
            help="滚动 ICIR 窗口（默认: 60）",
        )

        # 数据路径
        parser.add_argument(
            "--data_source",
            type=str,
            default=None,
            help="统一数据源路径（默认: data_fetchers/result/factor_ic_data.json.gz）",
        )

        parser.add_argument(
            "--ic_result_dir",
            type=str,
            default=None,
            help="IC 结果目录（默认: factor_ic/result）",
        )

        parser.add_argument(
            "--weight_result_path",
            type=str,
            default=None,
            help="权重选择结果路径（默认: comprehensive_factor/result/weight_selection_result.json）",
        )

        parser.add_argument(
            "--output_dir",
            type=str,
            default=None,
            help="输出目录（默认: comprehensive_factor/result）",
        )

        args = parser.parse_args()

        # 构建配置
        config = config_class(
            top_n=args.top_n,
            selection_date=args.selection_date,
            factor_direction=args.factor_direction,
            rolling_window=args.rolling_window,
            data_source=args.data_source,
            ic_result_dir=args.ic_result_dir,
            weight_result_path=args.weight_result_path,
            output_dir=args.output_dir,
        )

        # 执行选股
        try:
            result, output_file = select_stocks(config, logger)
            logger.info("选股成功！输出文件: %s", output_file)
            return 0
        except Exception as e:
            logger.error("选股失败: %s", e, exc_info=True)
            return 1

    return main


# 创建 CLI 入口
main = create_cli_entrypoint(StockSelectorConfig)


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
