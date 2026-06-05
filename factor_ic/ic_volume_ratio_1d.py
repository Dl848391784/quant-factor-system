#!/usr/bin/env python3
"""
量比因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_simple_factor_ic()（禁止手写三模式分支）
- 无需自定义因子计算（量比因子 volume_ratio_5 已在缓存中）

代码量：~165行（CLI 入口 + 结果摘要 + 异常处理），因子计算使用公共模块 run_simple_factor_ic。

因子定义：
- volume_ratio_5 = 当日成交量 / 过去5日平均成交量
- 含义：量比（成交量相对强度）
  - > 1 → 成交量放大（高于历史平均）
  - < 1 → 成交量萎缩（低于历史平均）
  - = 1 → 成交量正常

边界处理：
- 过去5日成交量不足时设为 NaN
- 成交量为 0 时设为 NaN

作者: 云瑶
创建日期: 2026-05-08
重构日期: 2026-05-23（v2：使用 run_simple_factor_ic）
版本历史:
  v1.0 (2026-05-08): 初始版本，独立实现量比因子 IC 计算（253行）
  v2.0 (2026-05-23): 重构，使用 run_simple_factor_ic 公共模块（代码量降至~60行）
  v2.1 (2026-06-01):
    - argparse 导入移至文件顶部（遵循 PEP 8）
    - 删除启动日志（公共模块已有等效日志）
    - 删除历史遗留注释（"问题2修复"、"问题3修复"）
    - 删除重复的 ic_metrics 赋值（第74行冗余）
    - 新增 result 为 None 保底处理
    - 新增 ic_distribution_consistency 字段读取（对齐 MODULE.md 第56行）
    - positive_ratio 取值位置修正（从 ic_distribution 取而非 result）
    - N/A 日志信息补充原因（ic_std/icir/positive_ratio）
    - 异常告警层级补充（ic_mean/ic_std/icir/positive_ratio warning）
    - 完成日志移至结果摘要后（语义更清晰）
    - 异常处理简化（删除 RuntimeError 分支）
    - 代码量注释更新（~165行，反映实际行数）
"""

import argparse
import sys
from pathlib import Path


# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

# 导入公共模块主入口（遵循 PROJECT.md 强制复用规范）
from factor_ic.common.factor_ic_runner import run_simple_factor_ic
from factor_ic.common.logger_config import get_logger


logger = get_logger(__name__)

# ============================================================================
# 参数统一管理
# ============================================================================
DEFAULT_MIN_STOCKS = 10


# ============================================================================
# CLI 入口
# ============================================================================

def main():
    """CLI 主入口"""
    parser = argparse.ArgumentParser(description='量比因子 IC 计算器')
    parser.add_argument('--force-full', action='store_true', help='强制全量计算')
    parser.add_argument('--min-stocks', type=int, default=DEFAULT_MIN_STOCKS, help='最小股票数')

    args = parser.parse_args()

    # 使用公共模块主入口（遵循 PROJECT.md 强制复用规范）
    # 注意：公共模块内部已有启动日志，此处不再重复打印
    # 注意：run_simple_factor_ic 只需 factor_col，公共模块自动加载该列
    result = run_simple_factor_ic(
        factor_name='volume_ratio',
        factor_col='volume_ratio_5',
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        _logger=logger
    )

    # 保底处理：公共模块异常返回 None 时直接退出
    # 注意：这是可预期的业务失败，不是运行时错误，直接退出更语义清晰
    if result is None:
        logger.error("run_simple_factor_ic 返回 None")
        sys.exit(1)

    # 使用 .get() + or {} 防御性访问结果（避免 None 导致格式化失败）
    ic_metrics = result.get('ic_metrics') or {}
    sample_stats = result.get('sample_stats') or {}
    period = result.get('period') or {}
    # 字段名 ic_distribution_consistency 来源于 MODULE.md 第56行输出结构
    # 语义：正比例与方向一致/矛盾判断（MODULE.md 第77行），非单纯分布统计
    ic_distribution = result.get('ic_distribution_consistency') or {}

    logger.info("=" * 60)
    logger.info("结果摘要")
    logger.info("=" * 60)
    logger.info(f"因子名称: {result.get('factor_name', 'unknown')}")
    logger.info(f"更新模式: {result.get('update_mode', 'unknown')}")
    logger.info(f"日期范围: {period.get('start', 'N/A')} ~ {period.get('end', 'N/A')}")
    logger.info(f"有效天数: {sample_stats.get('valid_days', 0)} 天")
    logger.info("--- IC指标 ---")

    ic_mean = ic_metrics.get('ic_mean')
    if ic_mean is not None:
        logger.info(f"IC 均值: {ic_mean:.4f}")
    else:
        logger.info("IC 均值: N/A（本次计算结果为空，请检查数据源）")

    ic_std = ic_metrics.get('ic_std')
    if ic_std is not None:
        logger.info(f"IC 标准差: {ic_std:.4f}")
    else:
        logger.info("IC 标准差: N/A（数据不足或全为相同值）")

    icir = ic_metrics.get('icir')
    if icir is not None:
        logger.info(f"ICIR: {icir:.2f}")
    else:
        logger.info("ICIR: N/A（IC 标准差为 0 或数据不足）")

    positive_ratio = ic_distribution.get('positive_ratio')
    if positive_ratio is not None:
        logger.info(f"IC>0 占比: {positive_ratio:.2%}")
    else:
        logger.info("IC>0 占比: N/A（字段名错误或数据缺失）")

    # 异常状态整体感知日志（运维巡检用）
    # ic_mean 为 None 表示整个 IC 计算结果为空，是最严重情况
    has_warning = False
    if ic_mean is None:
        logger.warning("本次IC计算结果为空，请检查数据源或参数配置")
        has_warning = True
    # ic_std 为 None 表示 IC 标准差无法计算，根因在此层而非 icir 层
    elif ic_std is None:
        logger.warning("IC标准差无法计算（数据不足或全为相同值），请检查因子数据分布")
        has_warning = True
    # icir 为 None 表示 ICIR 无法计算（通常因 ic_std=0 或数据不足）
    elif icir is None:
        logger.warning("ICIR无法计算（IC标准差为0或数据不足），请检查因子数据分布")
        has_warning = True

    # positive_ratio 为 None 表示分布一致性判断缺失（独立检查，不与上方 elif 链耦合）
    if positive_ratio is None:
        logger.warning("IC>0占比无法获取（字段名错误或数据缺失），请检查公共模块输出结构")
        has_warning = True

    if has_warning:
        logger.info("量比因子IC计算完成（存在异常，请关注上方警告）")
    else:
        logger.info("量比因子IC计算完成")

    return result


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # 未预期异常，使用 exception()（自动打印完整堆栈，无需重复传 e）
        logger.exception("未预期的错误")
        sys.exit(1)
