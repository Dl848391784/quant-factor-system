#!/usr/bin/env python3
"""交互因子 IC 计算器: interaction_bollinger__ret5d_abs (v2.48, 2026-06-24)

设计依据: designs/feat_factor_definition_destigmatization_v1.md v1.2
因子定义 (ReLU 切半轴, 纯数学命名, 无经济叙事):
- interaction_bollinger__ret5d_pos = max(z_cs(return_5d), 0) × z_cs(bollinger_pb)
- interaction_bollinger__ret5d_neg = min(z_cs(return_5d), 0) × z_cs(bollinger_pb)
- interaction_bollinger__ret5d_abs =     |z_cs(return_5d)|   × z_cs(bollinger_pb)

方向 (factor_direction) 由 IC 闸口数据驱动决定, 不预设叙事标签
(遵循 CLAUDE.md §1.5 / PROJECT.md §数据驱动原则 + backtest/MODULE.md v2.5 M17).

边界处理 (继承 calculate_interaction_bollinger__ret5d_abs):
- return_5d / bollinger_pb 缺失 → 交互值 NaN
- 截面 std=0 → 加 1e-10 防除零
- 极端值 clip 到 ±3σ × ±3σ
- ReLU 半轴互斥: pos × neg ≡ 0; pos + neg ≡ z_cs(ret) × z_cs(factor)

作者: 云瑶
创建日期: 2026-06-24
版本历史:
  v1.0 (2026-06-24): v2.48 重构产物, 27 ReLU 变体替代旧单边公式
"""

import argparse
import sys

from data_fetchers.factor_calculator import calculate_interaction_bollinger__ret5d_abs
from factor_ic.common.cli_helpers import DEFAULT_MIN_STOCKS
from factor_ic.common.exceptions import DataSchemaError, FactorCalcError
from factor_ic.common.factor_ic_runner import run_factor_ic
from factor_ic.common.factor_spec import FactorSpec, register_factor
from factor_ic.common.logger_config import get_logger


logger = get_logger(__name__)


SPEC = register_factor(
    FactorSpec(
        factor_name="interaction_bollinger__ret5d_abs",
        factor_col="interaction_bollinger__ret5d_abs",
        calculation=calculate_interaction_bollinger__ret5d_abs,
    )
)


def main():
    """interaction_bollinger__ret5d_abs 因子 IC 计算 CLI 主入口."""
    parser = argparse.ArgumentParser(description="交互因子 IC 计算器: 布林%B__ret5d_abs")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")
    args = parser.parse_args()

    result = run_factor_ic(
        spec=SPEC,
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        logger=logger,
    )

    if result is None:
        raise FactorCalcError("run_factor_ic 返回 None, 数据加载或计算可能失败")

    ic_metrics = result.get("ic_metrics") or {}
    sample_stats = result.get("sample_stats") or {}
    period = result.get("period") or {}
    ic_distribution = result.get("ic_distribution_consistency") or {}

    ic_mean = ic_metrics.get("ic_mean")
    ic_std = ic_metrics.get("ic_std")
    icir = ic_metrics.get("icir")
    positive_ratio = ic_distribution.get("positive_ratio")

    ic_mean_str = f"{ic_mean:.4f}" if ic_mean is not None else "N/A"
    ic_std_str = f"{ic_std:.4f}" if ic_std is not None else "N/A"
    icir_str = f"{icir:.2f}" if icir is not None else "N/A"
    positive_ratio_str = f"{positive_ratio:.2%}" if positive_ratio is not None else "N/A"

    summary_lines = [
        "==== 结果摘要 ====",
        f"因子名称: {result.get('factor_name', 'unknown')}",
        f"更新模式: {result.get('update_mode', 'unknown')}",
        f"日期范围: {period.get('start', 'N/A')} ~ {period.get('end', 'N/A')}",
        f"有效天数: {sample_stats.get('valid_days', 0)} 天",
        "--- IC指标 ---",
        f"IC 均值: {ic_mean_str}",
        f"IC 标准差: {ic_std_str}",
        f"ICIR: {icir_str}",
        f"IC>0 占比: {positive_ratio_str}",
    ]
    logger.info("\n%s", "\n".join(summary_lines))

    missing_fields = [
        name
        for name, value in (
            ("ic_mean", ic_mean),
            ("ic_std", ic_std),
            ("icir", icir),
            ("positive_ratio", positive_ratio),
        )
        if value is None
    ]
    if missing_fields:
        logger.warning(
            "本次计算存在空值字段: %s, 请检查数据源 / 因子分布 / 公共模块输出结构",
            ", ".join(missing_fields),
        )

    logger.info("interaction_bollinger__ret5d_abs 因子IC计算完成")
    return result


if __name__ == "__main__":
    try:
        main()
    except DataSchemaError as e:
        logger.error("数据 Schema 校验失败 (factor=%s): %s", e.factor_name, e)
        sys.exit(4)
    except FactorCalcError as e:
        logger.error("interaction_bollinger__ret5d_abs 因子IC计算失败: %s", e)
        sys.exit(5)
    except Exception:
        logger.exception("未预期的错误")
        sys.exit(1)
