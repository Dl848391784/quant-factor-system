#!/usr/bin/env python3
"""
KDJ_J 因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_complex_factor_ic()（禁止手写三模式分支）
- 因子计算逻辑复用 data_fetchers.factor_calculator（遵循 MODULE.md 约束 #3）

代码量：~186行（CLI 入口 + 结果摘要 + 异常处理），因子计算使用公共模块 run_complex_factor_ic。

因子定义：
- RSV(N) = (Close_t - Low_N) / (High_N - Low_N) × 100
- K_t = K_{t-1} × (M1-1)/M1 + RSV_t × 1/M1
- D_t = D_{t-1} × (M2-1)/M2 + K_t × 1/M2
- J_t = 3 × K_t - 2 × D_t

参数：
- N = 9（RSV 计算周期）
- M1 = 3（K值平滑周期）
- M2 = 3（D值平滑周期）

作者: 云瑶
重构日期: 2026-05-27（因子计算逻辑迁移到 factor_calculator.py）
原版作者: 云舟
原版日期: 2026-04-07
版本历史:
  v1.0 (2026-04-07): 初始版本，独立实现 KDJ_J 因子 IC 计算
  v2.0 (2026-05-27): 重构，使用 run_complex_factor_ic 公共模块
  v2.1 (2026-06-08):
    - 引入外部自定义异常类 FactorCalcError（区分业务失败与非预期 RuntimeError，定义在 factor_ic.common.exceptions）
    - 新增 result 为 None 防御性检查
    - 修正 positive_ratio 取值位置（从 ic_distribution_consistency 子字典）
    - 结果摘要合并为单条日志输出
    - 补全四字段 warning（ic_mean/ic_std/icir/positive_ratio 为 None 时告警）
    - "计算完成"日志移至结果处理末尾
    - argparse 导入移至文件顶部（遵循 PEP 8）
    - 代码量注释更新（~186行，反映实际行数）
  v2.2 (2026-06-15):
    - 删除冗余空注释块（自定义异常类分隔块本无内容）
    - 去除 ic_distribution 注释中硬编码的 MODULE.md 行号（改引用语义）
    - 合并四条 None 告警为单条汇总 warning（消除与结果摘要 N/A 的信息重复）
    - 在 main() docstring 显式声明异常契约与返回值，消除函数签名歧义
    - CLI 入口异常处理对齐 MODULE.md M22（logger.exception 替代 logger.error，保留完整堆栈）
  v2.3 (2026-06-15):
    - 反转 v2.2 M22 修复：业务异常 FactorCalcError 改用 logger.error 携带消息即可，
      不打印堆栈（堆栈对可预期业务失败是噪音）；仅未预期 Exception 保留 logger.exception
      （同步澄清 MODULE.md M22：按异常类别分类选择日志方法，非统一 logger.exception）
"""

import argparse
import sys

# 添加项目路径
# 导入公共模块主入口（遵循 PROJECT.md 强制复用规范）
from data_fetchers.factor_calculator import (
    DEFAULT_KDJ_M1 as DEFAULT_M1,  # K值平滑周期
)
from data_fetchers.factor_calculator import (
    DEFAULT_KDJ_M2 as DEFAULT_M2,  # D值平滑周期
)
from data_fetchers.factor_calculator import (
    DEFAULT_KDJ_N as DEFAULT_N,  # RSV 计算周期
)

# 重构后：从 factor_calculator 导入因子计算函数（遵循 MODULE.md 约束 #3）
from data_fetchers.factor_calculator import (
    calculate_kdj_j,
)
from factor_ic.common.cli_helpers import DEFAULT_MIN_STOCKS
from factor_ic.common.exceptions import FactorCalcError
from factor_ic.common.factor_ic_runner import run_factor_ic
from factor_ic.common.factor_spec import FactorSpec, register_factor
from factor_ic.common.logger_config import get_logger


logger = get_logger(__name__)

# ============================================================================
# FactorSpec 声明式注册（遵循 factor_cols_literal_constant_design.md §4.1）
# required_columns: JOIN_KEYS + OHLC + kdj_j（close/high/low 为 KDJ 计算输入）
# ============================================================================

SPEC = register_factor(
    FactorSpec(
        factor_name="kdj_j",
        factor_col="kdj_j",
        calculation=calculate_kdj_j,
        calc_params_fn=lambda a: {"n": a.n, "m1": a.m1, "m2": a.m2},
        extra_log_params_fn=lambda a: {"n": a.n, "m1": a.m1, "m2": a.m2},
    )
)

# ============================================================================
# CLI 入口
# ============================================================================


def main():
    """KDJ_J 因子 IC 计算 CLI 主入口

    Returns
    -------
    dict
        run_complex_factor_ic 的完整结果字典（成功路径下保证非 None）。

    Raises
    ------
    FactorCalcError
        result 为 None 时抛出，表示数据加载或公共模块计算失败（业务异常）。
        作为函数被外部模块导入调用时，调用方需自行处理本异常；
        作为脚本（``python ic_kdj_j_1d.py``）运行时，由 ``__main__`` 块捕获并 ``sys.exit(1)``。
    Exception
        其他未预期异常会原样向上传播，不在本函数内吞掉。
    """
    parser = argparse.ArgumentParser(description="KDJ_J IC 计算器")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--n", type=int, default=DEFAULT_N, help="RSV 计算周期")
    parser.add_argument("--m1", type=int, default=DEFAULT_M1, help="K值平滑周期")
    parser.add_argument("--m2", type=int, default=DEFAULT_M2, help="D值平滑周期")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")

    args = parser.parse_args()

    # 启动横幅由公共模块 factor_ic_runner 统一打印（含 min_stocks/force_full + extra_log_params）
    # 使用 FactorSpec 驱动入口（遵循 factor_cols_literal_constant_design.md §4.1）
    result = run_factor_ic(
        spec=SPEC,
        args=args,
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
        "=" * 60,
        "结果摘要",
        "=" * 60,
        f"因子名称: {result.get('factor_name', 'unknown')}",
        f"更新模式: {result.get('update_mode', 'unknown')}",
        f"计算参数: n={args.n}, m1={args.m1}, m2={args.m2}",
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
    logger.info("KDJ_J因子IC计算完成")

    return result


if __name__ == "__main__":
    try:
        main()
    except FactorCalcError as e:
        # 业务异常：消息已足够定位，堆栈是噪音（MODULE.md M22 业务异常子类规则）
        logger.error("KDJ_J因子IC计算失败: %s", e)
        sys.exit(1)
    except Exception:
        # 未预期异常（含非预期 RuntimeError）：必须打印堆栈以便定位
        logger.exception("未预期的错误")
        sys.exit(1)
