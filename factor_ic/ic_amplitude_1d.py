#!/usr/bin/env python3
"""
振幅因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_complex_factor_ic()（禁止手写三模式分支）
- 因子计算逻辑复用 data_fetchers.factor_calculator（遵循 MODULE.md 约束 #3）

因子定义：
- Amplitude = (High - Low) / Close
- 含义：当日振幅相对于收盘价的比率，反映价格波动强度
  - 值越大 → 波动越剧烈
  - 值越小 → 波动平稳
  - 范围：理论 [0, +∞)，实际通常 [0, 0.15]（A股振幅上限15%）

边界处理：
- Close = 0 时，设为 NaN（无效数据）
- High = Low 时，振幅为 0（一字涨停/跌停）

作者: 云瑶
创建日期: 2026-05-29
版本历史:
  v1.0 (2026-05-29): 初始版本，复用 factor_calculator.calculate_amplitude
  v1.1 (2026-05-31): 优化日志字段名 + 防御性 None 处理 + 删除未使用导入
  v1.2 (2026-06-08):
    - 引入外部自定义异常类 FactorCalcError（区分业务失败与非预期 RuntimeError，定义在 factor_ic.common.exceptions）
    - 补全四字段 warning（ic_mean/ic_std/icir/positive_ratio 为 None 时告警）
    - 结果摘要合并为单条日志输出
    - 保底处理改为抛出 FactorCalcError（遵循异常处理规范）
  v1.3 (2026-06-15):
    - 删除冗余空注释块（自定义异常类分隔块本无内容）
    - 删除调用方内部细节行内注释（公共模块 params 转换为 {} 属于公共模块文档职责）
    - 去除 ic_distribution 注释中硬编码的 MODULE.md 行号（改引用语义）
    - 合并四条 None 告警为单条汇总 warning（消除与结果摘要 N/A 的信息重复）
    - 在 main() docstring 显式声明异常契约与返回值，消除函数签名歧义
    - CLI 入口异常处理对齐 MODULE.md M22（logger.exception 替代 logger.error，保留完整堆栈）
  v1.4 (2026-06-15):
    - 反转 v1.3 M22 修复：业务异常 FactorCalcError 改用 logger.error 携带消息即可，
      不打印堆栈（堆栈对可预期业务失败是噪音）；仅未预期 Exception 保留 logger.exception
      （同步澄清 MODULE.md M22：按异常类别分类选择日志方法，非统一 logger.exception）
    - 删除 docstring 中易腐烂的代码行数列说明（可由 wc -l 实时获取）
    - 结果摘要标题与分隔线合并为单行 "==== 结果摘要 ===="，减少日志行数占用
"""

import argparse
import sys

# 添加项目路径
# 导入公共模块主入口（遵循 PROJECT.md 强制复用规范）
# 从 factor_calculator 导入因子计算函数（遵循 MODULE.md 约束 #3）
from data_fetchers.factor_calculator import calculate_amplitude
from factor_ic.common.cli_helpers import DEFAULT_MIN_STOCKS
from factor_ic.common.exceptions import DataSchemaError, FactorCalcError
from factor_ic.common.factor_ic_runner import run_factor_ic
from factor_ic.common.factor_spec import FactorSpec, register_factor
from factor_ic.common.logger_config import get_logger


logger = get_logger(__name__)

# ============================================================================
# FactorSpec 声明式注册（遵循 factor_cols_literal_constant_design.md §4.1）
# ============================================================================

SPEC = register_factor(
    FactorSpec(
        factor_name="amplitude",
        factor_col="amplitude",
        calculation=calculate_amplitude,
    )
)

# ============================================================================
# CLI 入口
# ============================================================================


def main():
    """振幅因子 IC 计算 CLI 主入口

    Returns
    -------
    dict
        run_complex_factor_ic 的完整结果字典（成功路径下保证非 None）。

    Raises
    ------
    FactorCalcError
        result 为 None 时抛出，表示数据加载或公共模块计算失败（业务异常）。
        作为函数被外部模块导入调用时，调用方需自行处理本异常；
        作为脚本（``python ic_amplitude_1d.py``）运行时，由 ``__main__`` 块捕获并 ``sys.exit(1)``。
    Exception
        其他未预期异常会原样向上传播，不在本函数内吞掉。
    """

    parser = argparse.ArgumentParser(description="振幅因子 IC 计算器")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")

    args = parser.parse_args()

    # 启动横幅由公共模块 factor_ic_runner 统一打印（含 min_stocks/force_full）
    # 使用 FactorSpec 驱动入口（遵循 factor_cols_literal_constant_design.md §4.1）
    result = run_factor_ic(
        spec=SPEC,
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        _logger=logger,
    )

    # 防御性检查：result 为 None 时抛出业务异常（遵循 PROJECT.md 异常处理规范）
    if result is None:
        raise FactorCalcError("run_factor_ic 返回 None，数据加载或计算可能失败")

    # 使用 .get() + or {} 防御性访问结果（避免 None 导致格式化失败）
    ic_metrics = result.get("ic_metrics") or {}
    sample_stats = result.get("sample_stats") or {}
    period = result.get("period") or {}
    # 字段名来源于 MODULE.md 输出结构模板章节（ic_distribution_consistency）
    ic_distribution = result.get("ic_distribution_consistency") or {}

    # 构建结果摘要（合并为单条日志便于阅读）
    ic_mean = ic_metrics.get("ic_mean")
    ic_std = ic_metrics.get("ic_std")
    icir = ic_metrics.get("icir")
    positive_ratio = ic_distribution.get("positive_ratio")

    # 格式化各字段（None 时显示 N/A）
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

    # 异常状态告警（运维巡检用）：摘要中已用 N/A 显式呈现，此处仅在存在缺失字段时输出一条汇总，避免与摘要逐字段重复
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
            "本次计算存在空值字段: %s，请检查数据源 / 因子分布 / 公共模块输出结构",
            ", ".join(missing_fields),
        )

    # 确认结果处理完成后才输出"计算完成"日志
    logger.info("振幅因子IC计算完成")

    return result


if __name__ == "__main__":
    try:
        main()
    except DataSchemaError as e:
        # 数据 Schema 校验失败（公共模块 validate_required_columns 抛出）：
        # H12 R18 → exit 4 与因子计算失败（exit 5）严格区分。
        # MODULE.md M22：业务异常用 logger.error 不打堆栈。
        logger.error("数据 Schema 校验失败 (factor=%s): %s", e.factor_name, e)
        sys.exit(4)  # H12 R18: schema 失败 → 检查上游数据
    except FactorCalcError as e:
        # 业务异常：消息已足够定位，堆栈是噪音（MODULE.md M22 业务异常子类规则）
        logger.error("振幅因子IC计算失败: %s", e)
        sys.exit(5)  # H12 R19: 因子计算失败 → 检查计算代码
    except Exception:
        # 未预期异常（含非预期 RuntimeError）：必须打印堆栈以便定位
        logger.exception("未预期的错误")
        sys.exit(1)
