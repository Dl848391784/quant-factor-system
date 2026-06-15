#!/usr/bin/env python3
"""
振幅差分因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_factor_ic()（禁止手写三模式分支）
- 因子计算逻辑复用 data_fetchers.factor_calculator（遵循 MODULE.md 约束 #3）

因子定义：
- amplitude_delta = amplitude(T) - amplitude(T-1)
- 含义：振幅从低开始回升 = 止跌放量信号；振幅继续下降 = 闷跌加剧
- 遵循 H5: IC方向不预判，由数据决定

边界处理：
- 第一日无前值 → NaN（自然排除）
- amplitude 为 NaN → delta 也为 NaN（传播）

作者: 云瑶
创建日期: 2026-06-11
版本历史:
  v1.0 (2026-06-11): 初始版本，复用 factor_calculator.calculate_amplitude_delta
"""

import argparse
import sys
from pathlib import Path


# 添加项目路径（若脚本被移动或项目结构调整，下方断言将立即暴露问题）
sys.path.insert(0, str(Path(__file__).parent.parent))  # noqa: E402

# 路径有效性校验：验证关键包可导入（防止 sys.path.insert 静默失效）
try:
    import factor_ic as _path_check  # noqa: E402, F401 — 路径有效性校验，不使用模块
except ImportError as _path_err:
    raise ImportError(
        f"无法定位 factor_ic 包，sys.path.insert 添加的路径可能无效: {Path(__file__).parent.parent}"
    ) from _path_err

# 导入公共模块主入口（遵循 PROJECT.md 强制复用规范）
# 从 factor_calculator 导入因子计算函数（遵循 MODULE.md 约束 #3）
from data_fetchers.factor_calculator import calculate_amplitude_delta  # noqa: E402
from factor_ic.common.cli_helpers import DEFAULT_MIN_STOCKS  # noqa: E402
from factor_ic.common.data_columns import JOIN_KEYS  # noqa: E402
from factor_ic.common.exceptions import FactorCalcError  # noqa: E402
from factor_ic.common.factor_ic_runner import run_factor_ic  # noqa: E402
from factor_ic.common.factor_spec import FactorSpec, register_factor  # noqa: E402
from factor_ic.common.factor_summary_logger import log_factor_summary  # noqa: E402
from factor_ic.common.logger_config import get_logger  # noqa: E402


logger = get_logger(__name__)

# ============================================================================
# FactorSpec 声明式注册（遵循 factor_cols_literal_constant_design.md §4.1）
# required_columns: JOIN_KEYS + 上游因子列（amplitude 来自 factor_generator _EXTENDED_FACTOR_COLS）
# ============================================================================

SPEC = register_factor(
    FactorSpec(
        factor_name="amplitude_delta",
        factor_col="amplitude_delta",
        required_columns=JOIN_KEYS + ("amplitude",),
        calculation=calculate_amplitude_delta,
    )
)

# ============================================================================
# CLI 入口
# ============================================================================


def main():
    """CLI 主入口"""

    parser = argparse.ArgumentParser(description="振幅差分因子 IC 计算器")
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
    # 不在此处 logger.error，由底部 except FactorCalcError 统一打印，避免双重日志
    if result is None:
        raise FactorCalcError("run_factor_ic 返回 None，数据加载或计算可能失败")

    # 输出 IC 摘要 + None 状态整合告警（公共模块,M3.1）
    log_factor_summary(result, "振幅差分因子", logger)

    return result


if __name__ == "__main__":
    try:
        main()
    except FactorCalcError as e:
        # 已知业务异常，使用 error()（不打印完整堆栈，但保留错误内容）
        logger.error("振幅差分因子IC计算失败: %s", e)
        sys.exit(1)
    except Exception:
        # 未预期异常（含非预期 RuntimeError），使用 exception()（自动打印完整堆栈）
        logger.exception("未预期的错误")
        sys.exit(1)
