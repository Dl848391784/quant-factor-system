#!/usr/bin/env python3
"""
过去1日涨幅因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_simple_factor_ic()（预计算因子，直接读取）
- 因子数据已在 factor_generator.py 预计算，存储于 factor_ic_data.json.gz

代码量：~169行（CLI 入口 + 结果摘要 + 异常处理）。

因子定义：
- past_return_1d = close[t] / close[t-1] - 1
- 含义：过去1日涨跌幅（相对于昨日收盘价）
  - 正值 → 上涨
  - 负值 → 下跌
  - 范围：理论 [-∞, +∞)，A股日涨跌幅±10%

命名说明：
- past_return_1d = 过去1日收益（历史因子，与 forward_return_1d 对称）
- forward_return_1d = 未来1日收益（预测目标）

边界处理：
- 第一日数据设为 NaN（无昨日收盘价）
- close[t-1] = 0 时设为 NaN（无效数据）

作者: 云瑶
创建日期: 2026-06-04
版本历史:
  v1.0 (2026-06-04): 初始版本，因子名 return_1d
  v1.1 (2026-06-04): 重命名为 past_return_1d，与 forward_return_1d 对称
  v1.2 (2026-06-04): 移除 custom_factor_calculation，改为使用 run_simple_factor_ic（遵循数据层架构原则）
  v1.3 (2026-06-08):
    - 新增自定义异常类 FactorCalcError（区分业务失败与非预期 RuntimeError）
    - 新增 __main__ 块 try/except 异常处理
    - 新增启动参数日志（便于追溯 CLI 入参）
    - result 判空改为 if result is None（避免空字典误判）
    - 结果摘要合并为单条日志输出，补充日期范围/有效天数/IC标准差/IC>0占比
    - positive_ratio 从 ic_distribution_consistency 子字典取值
    - 补全四字段 warning（ic_mean/ic_std/icir/positive_ratio 为 None 时告警）
    - 新增"计算完成"日志
    - 代码量注释更新（~169行，反映实际行数）
"""

import argparse
import sys

# 添加项目路径
# 导入公共模块主入口（遵循 PROJECT.md 强制复用规范）
from factor_ic.common.cli_helpers import DEFAULT_MIN_STOCKS
from factor_ic.common.data_columns import JOIN_KEYS
from factor_ic.common.exceptions import FactorCalcError
from factor_ic.common.factor_ic_runner import run_factor_ic
from factor_ic.common.factor_spec import FactorSpec, register_factor
from factor_ic.common.factor_summary_logger import log_factor_summary
from factor_ic.common.logger_config import get_logger


logger = get_logger(__name__)

# ============================================================================
# FactorSpec 声明式注册（遵循 factor_cols_literal_constant_design.md §4.1）
# ============================================================================

SPEC = register_factor(
    FactorSpec(
        factor_name="past_return_1d",
        factor_col="past_return_1d",
        required_columns=JOIN_KEYS + ("past_return_1d",),
    )
)

# ============================================================================
# 自定义异常类
# ============================================================================
# ============================================================================
# CLI 入口
# ============================================================================


def main():
    """CLI 主入口"""
    parser = argparse.ArgumentParser(description="过去1日涨幅因子 IC 计算器")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")

    args = parser.parse_args()

    # 启动横幅由公共模块 factor_ic_runner 统一打印（含 min_stocks/force_full）
    # 使用 FactorSpec 驱动入口（遵循 factor_cols_literal_constant_design.md §4.1）
    # 因子数据已在 factor_generator.py 预计算，使用 run_factor_ic 直接读取
    result = run_factor_ic(
        spec=SPEC,
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        _logger=logger,
    )

    # 防御性检查：result 为 None 时抛出业务异常（遵循 PROJECT.md 异常处理规范）
    if result is None:
        raise FactorCalcError("run_factor_ic 返回 None，数据加载或计算可能失败")

    # 输出 IC 摘要 + None 状态整合告警（公共模块,M3.1）
    # 例外脚本：通过 extra_summary_lines 注入"因子方向"行（位于 IC 指标摘要末尾）
    factor_direction = result.get("factor_direction", "unknown")
    # 包裹 log_factor_summary：摘要层失败 → sys.exit(3) 显式辅助层失败信号
    # （PROJECT.md H12 R17）。因子计算 result 已成功生成，主结果产物可用，下游
    # backtest/comprehensive/summary 可正常消费；仅旁路日志摘要失败时返回 exit 3，
    # 与业务失败（exit 1）和 import-time 注册失败（exit 2）严格区分。
    try:
        log_factor_summary(
            result,
            "过去1日涨幅因子",
            logger,
            extra_summary_lines=[f"因子方向: {factor_direction}"],
        )
    except Exception:
        logger.exception(
            "log_factor_summary 摘要输出阶段失败（因子计算 result 已成功生成；"
            "故障源 = 摘要日志层而非 run_factor_ic 业务路径）"
        )
        sys.exit(3)  # H12 R17：辅助层失败专用退出码

    # 确认结果处理完成后才输出"计算完成"日志
    logger.info("过去1日涨幅因子IC计算完成")

    return result


if __name__ == "__main__":
    try:
        main()
    except FactorCalcError as e:
        # 已知业务异常，使用 error()（不打印完整堆栈，但保留错误内容）
        logger.error("过去1日涨幅因子IC计算失败: %s", e)
        sys.exit(1)
    except Exception:
        # 未预期异常（含非预期 RuntimeError），使用 exception()（自动打印完整堆栈）
        logger.exception("未预期的错误")
        sys.exit(1)
