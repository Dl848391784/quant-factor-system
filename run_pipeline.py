#!/usr/bin/env python3
"""
因子分析完整流程串行执行脚本

执行顺序：
Stage 0: 基础数据拉取
  1. fetch_stock_list.py        → data_fetchers/result/stock_list.json
  2. fetch_factor_cache.py      → cache/factor_data/factor_data.json.gz（收益数据已内置于 factor_ic_data.json.gz）
  3. fetch_turnover.py          → data_fetchers/result/turnover_rate_data.json.gz
  4. fetch_industry.py          → result/stock_industry.json
  5. fetch_tail_trading.py      → data_fetchers/result/tail_trading_data.json.gz（尾盘5分钟K线数据）

Stage 1: 数据整合
  6. factor_generator.py        → data_fetchers/result/factor_ic_data.json.gz

Stage 2: IC计算
  7. ic_rsi_1d.py
  8. ic_volume_ratio_1d.py
  9. ic_kdj_j_1d.py
  10. ic_bollinger_pb_1d.py
  11. ic_turnover_surge_1d.py
  12. ic_amplitude_1d.py
  13. ic_price_position_1d.py
  14. ic_return_3d_1d.py
  15. ic_return_5d_1d.py
  16. ic_overnight_ret_1d.py
  17. ic_tail_price_position.py (新增 2026-06-02)
  18. ic_tail_price_slope_1d.py (新增 2026-06-02)
  19. ic_tail_price_volume_intensity.py (新增 2026-06-02)
  20. ic_tail_volume_acceleration_1d.py (新增 2026-06-02)

Stage 3: 分层回测
  21. layered_backtest_rsi_1d.py
  22. layered_backtest_volume_ratio_1d.py
  23. layered_backtest_kdj_j_1d.py
  24. layered_backtest_bollinger_pb_1d.py
  25. layered_backtest_turnover_surge_1d.py
  26. layered_backtest_amplitude_1d.py
  27. layered_backtest_price_position_1d.py
  28. layered_backtest_return_3d_1d.py
  29. layered_backtest_return_5d_1d.py
  30. layered_backtest_overnight_ret_1d.py
  31. layered_backtest_tail_price_position_1d.py (新增 2026-06-02)
  32. layered_backtest_tail_price_slope_1d.py (新增 2026-06-02)
  33. layered_backtest_tail_price_volume_intensity_1d.py (新增 2026-06-02)
  34. layered_backtest_tail_volume_acceleration_1d.py (新增 2026-06-02)

Stage 4: 综合因子
  35. composite_equal_weight_1d.py
  36. composite_icir_weight_1d.py
  37. composite_ic_weight_1d.py
  38. composite_rolling_icir_weight_1d.py

Stage 5: 权重选择（新增 2026-06-03）
  39. weight_selector.py         → comprehensive_factor/result/weight_selection_result.json

Stage 6: 股票选股（新增 2026-06-03）
  40. stock_selector.py          → comprehensive_factor/result/stock_selection_result.json

Stage 7: 汇总报告
  41. generate_factor_summary_report.py

版本历史：
- v1.0 (2026-05-27): 初始版本，完全串行执行，退出码检查，脚本级别重试
- v1.1 (2026-05-27): fetch_turnover 添加 --baostock 参数，获取历史换手率数据
- v1.2 (2026-06-02): 新增 4 个尾盘因子（tail_price_position, tail_price_slope, tail_price_volume_intensity, tail_volume_acceleration）
- v1.3 (2026-06-03): 新增 Stage 5 权重选择和 Stage 6 股票选股

作者: 云瑶
"""

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import NamedTuple


# ============================================================================
# 配置常量
# ============================================================================

# 项目根目录（脚本所在位置即为项目根）
PROJECT_ROOT = Path(__file__).parent.resolve()

# 脚本执行配置
MAX_RETRIES = 3          # 脚本级别最大重试次数
RETRY_DELAY = 30         # 重试间隔（秒）
SCRIPT_TIMEOUT = 1800    # 单个脚本最大执行时间（秒）= 30分钟

# ============================================================================
# 脚本定义
# ============================================================================

class ScriptTask(NamedTuple):
    """脚本任务定义"""
    name: str           # 任务名称（用于日志）
    script: str         # 脚本相对路径
    stage: int          # 所属阶段
    args: list[str]     # 命令行参数（可选）
    timeout: int | None = None  # 独立超时时间（秒），None 则使用默认 SCRIPT_TIMEOUT

# 完整执行流程（按顺序）
PIPELINE_SCRIPTS: list[ScriptTask] = [
    # Stage 0: 基础数据拉取
    ScriptTask('fetch_stock_list', 'data_fetchers/fetch_stock_list.py', 0, []),
    ScriptTask('fetch_factor_cache', 'data_fetchers/fetch_factor_cache.py', 0, []),
    ScriptTask('fetch_turnover', 'data_fetchers/fetch_turnover.py', 0, ['--baostock']),
    ScriptTask('fetch_industry', 'data_fetchers/fetch_industry.py', 0, []),  # 行业分类数据
    ScriptTask('fetch_tail_trading', 'data_fetchers/fetch_tail_trading.py', 0, [], timeout=10800),  # 尾盘5分钟K线数据（3小时超时，因每批停顿80秒）

    # Stage 1: 数据整合
    ScriptTask('factor_generator', 'data_fetchers/factor_generator.py', 1, []),

    # Stage 2: IC计算
    ScriptTask('ic_rsi', 'factor_ic/ic_rsi_1d.py', 2, []),
    ScriptTask('ic_volume_ratio', 'factor_ic/ic_volume_ratio_1d.py', 2, []),
    ScriptTask('ic_kdj_j', 'factor_ic/ic_kdj_j_1d.py', 2, []),
    ScriptTask('ic_bollinger_pb', 'factor_ic/ic_bollinger_pb_1d.py', 2, []),
    ScriptTask('ic_turnover_surge', 'factor_ic/ic_turnover_surge_1d.py', 2, []),
    ScriptTask('ic_amplitude', 'factor_ic/ic_amplitude_1d.py', 2, []),
    ScriptTask('ic_price_position', 'factor_ic/ic_price_position_1d.py', 2, []),
    ScriptTask('ic_return_3d', 'factor_ic/ic_return_3d_1d.py', 2, []),
    ScriptTask('ic_return_5d', 'factor_ic/ic_return_5d_1d.py', 2, []),
    ScriptTask('ic_overnight_ret', 'factor_ic/ic_overnight_ret_1d.py', 2, []),
    # 尾盘因子 IC 计算（2026-06-02 新增）
    ScriptTask('ic_tail_price_position', 'factor_ic/ic_tail_price_position.py', 2, []),
    ScriptTask('ic_tail_price_slope', 'factor_ic/ic_tail_price_slope_1d.py', 2, []),
    ScriptTask('ic_tail_price_volume_intensity', 'factor_ic/ic_tail_price_volume_intensity.py', 2, []),
    ScriptTask('ic_tail_volume_acceleration', 'factor_ic/ic_tail_volume_acceleration_1d.py', 2, []),

    # Stage 3: 分层回测
    ScriptTask('backtest_rsi', 'backtest/layered_backtest_rsi_1d.py', 3, []),
    ScriptTask('backtest_volume_ratio', 'backtest/layered_backtest_volume_ratio_1d.py', 3, []),
    ScriptTask('backtest_kdj_j', 'backtest/layered_backtest_kdj_j_1d.py', 3, []),
    ScriptTask('backtest_bollinger_pb', 'backtest/layered_backtest_bollinger_pb_1d.py', 3, []),
    ScriptTask('backtest_turnover_surge', 'backtest/layered_backtest_turnover_surge_1d.py', 3, []),
    ScriptTask('backtest_amplitude', 'backtest/layered_backtest_amplitude_1d.py', 3, []),
    ScriptTask('backtest_price_position', 'backtest/layered_backtest_price_position_1d.py', 3, []),
    ScriptTask('backtest_return_3d', 'backtest/layered_backtest_return_3d_1d.py', 3, []),
    ScriptTask('backtest_return_5d', 'backtest/layered_backtest_return_5d_1d.py', 3, []),
    ScriptTask('backtest_overnight_ret', 'backtest/layered_backtest_overnight_ret_1d.py', 3, []),
    # 尾盘因子分层回测（2026-06-02 新增）
    ScriptTask('backtest_tail_price_position', 'backtest/layered_backtest_tail_price_position_1d.py', 3, []),
    ScriptTask('backtest_tail_price_slope', 'backtest/layered_backtest_tail_price_slope_1d.py', 3, []),
    ScriptTask('backtest_tail_price_volume_intensity', 'backtest/layered_backtest_tail_price_volume_intensity_1d.py', 3, []),
    ScriptTask('backtest_tail_volume_acceleration', 'backtest/layered_backtest_tail_volume_acceleration_1d.py', 3, []),

    # Stage 4: 综合因子（启用自动筛选）
    ScriptTask('composite_equal', 'comprehensive_factor/composite_equal_weight_1d.py', 4, ['--auto_select']),
    ScriptTask('composite_icir', 'comprehensive_factor/composite_icir_weight_1d.py', 4, ['--auto_select']),
    ScriptTask('composite_ic', 'comprehensive_factor/composite_ic_weight_1d.py', 4, ['--auto_select']),
    ScriptTask('composite_rolling_icir', 'comprehensive_factor/composite_rolling_icir_weight_1d.py', 4, ['--auto_select']),

    # Stage 5: 权重选择（新增 2026-06-03）
    ScriptTask('weight_selector', 'comprehensive_factor/weight_selector.py', 5, []),

    # Stage 6: 股票选股（新增 2026-06-03）
    ScriptTask('stock_selector', 'comprehensive_factor/stock_selector.py', 6, []),

    # Stage 7: 汇总报告
    ScriptTask('summary_report', 'summary/generate_factor_summary_report.py', 7, []),
]

# ============================================================================
# 执行函数
# ============================================================================

def run_script(task: ScriptTask, retry_count: int = 0) -> bool:
    """
    执行单个脚本

    Args:
        task: 脚本任务定义
        retry_count: 当前重试次数（用于日志）

    Returns:
        True: 执行成功
        False: 执行失败（重试次数用尽）
    """
    script_path = PROJECT_ROOT / task.script

    # 检查脚本是否存在
    if not script_path.exists():
        print(f"[错误] 脚本不存在: {script_path}")
        return False

    # 构建命令
    cmd = [sys.executable, str(script_path)] + task.args

    # 日志前缀
    prefix = f"[{task.name}]" + (f"(重试#{retry_count})" if retry_count > 0 else "")

    print(f"{prefix} 开始执行...")
    print(f"{prefix} 脚本路径: {script_path}")

    # 计算实际超时时间（优先使用任务独立超时，否则使用默认值）
    actual_timeout = task.timeout if task.timeout is not None else SCRIPT_TIMEOUT

    start_time = time.time()

    try:
        # 执行脚本（捕获输出）
        result = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=actual_timeout,
            env={**dict(os.environ), 'PYTHONPATH': str(PROJECT_ROOT)}
        )

        elapsed = time.time() - start_time

        # 输出脚本日志（stdout）
        if result.stdout:
            for line in result.stdout.strip().split('\n'):
                print(f"  {line}")

        # 检查退出码
        if result.returncode == 0:
            print(f"{prefix} ✓ 执行成功 (耗时 {elapsed:.1f}s, 退出码 0)")
            return True
        else:
            print(f"{prefix} ✗ 执行失败 (耗时 {elapsed:.1f}s, 退出码 {result.returncode})")

            # 输出错误信息
            if result.stderr:
                print(f"{prefix} 错误输出:")
                for line in result.stderr.strip().split('\n'):
                    print(f"  {line}")

            return False

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        print(f"{prefix} ✗ 执行超时 (耗时 {elapsed:.1f}s > {actual_timeout}s)")
        return False

    except Exception as e:
        elapsed = time.time() - start_time
        print(f"{prefix} ✗ 执行异常: {type(e).__name__}: {e}")
        return False


def run_pipeline(
    start_stage: int = 0,
    start_script: str | None = None,
    skip_stages: list[int] | None = None
) -> bool:
    """
    执行完整流程

    Args:
        start_stage: 从哪个阶段开始（0-4）
        start_script: 从哪个脚本开始（脚本名称，如 'fetch_turnover'）
        skip_stages: 跳过的阶段列表

    Returns:
        True: 全部成功
        False: 有脚本失败
    """
    skip_stages = skip_stages or []

    # 过滤要执行的脚本
    scripts_to_run = []
    started = False

    for task in PIPELINE_SCRIPTS:
        # 跳过指定阶段
        if task.stage in skip_stages:
            continue

        # 从指定阶段开始
        if task.stage < start_stage:
            continue

        # 从指定脚本开始
        if start_script and not started:
            if task.name == start_script:
                started = True
            else:
                continue

        scripts_to_run.append(task)

    if not scripts_to_run:
        print("[信息] 无脚本需要执行")
        return True

    # 打印执行计划
    print("=" * 70)
    print("因子分析流程执行计划")
    print("=" * 70)
    print(f"项目根目录: {PROJECT_ROOT}")
    print(f"执行脚本数: {len(scripts_to_run)}")
    print(f"重试配置: 最大{MAX_RETRIES}次, 间隔{RETRY_DELAY}s")
    print("-" * 70)

    for i, task in enumerate(scripts_to_run, 1):
        print(f"  {i}. [{task.stage}] {task.name}: {task.script}")

    print("=" * 70)
    print()

    # 逐个执行脚本
    failed_scripts: list[tuple[ScriptTask, int]] = []  # (task, exit_code)
    success_count = 0

    for task in scripts_to_run:
        print()
        print(f"[阶段 {task.stage}] 执行: {task.name}")
        print("-" * 50)

        # 重试机制
        for retry in range(MAX_RETRIES + 1):
            success = run_script(task, retry)

            if success:
                success_count += 1
                break

            # 最后一次重试失败，记录失败
            if retry == MAX_RETRIES:
                print(f"[{task.name}] 重试次数用尽，标记为失败")
                failed_scripts.append((task, -1))
                break

            # 等待重试
            print(f"[{task.name}] 等待 {RETRY_DELAY}s 后重试...")
            time.sleep(RETRY_DELAY)

    # 打印执行结果
    print()
    print("=" * 70)
    print("执行结果汇总")
    print("=" * 70)
    print(f"成功: {success_count}/{len(scripts_to_run)}")

    if failed_scripts:
        print(f"失败: {len(failed_scripts)}")
        print("-" * 50)
        for task, _ in failed_scripts:
            print(f"  ✗ [{task.stage}] {task.name}: {task.script}")
        print("=" * 70)
        return False
    else:
        print("全部成功 ✓")
        print("=" * 70)
        return True


# ============================================================================
# CLI 入口
# ============================================================================

def main() -> int:
    """CLI 入口"""
    global MAX_RETRIES, RETRY_DELAY  # 必须在函数开头声明
    import argparse

    parser = argparse.ArgumentParser(
        description='因子分析完整流程串行执行脚本',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        '--start-stage', type=int, default=0, choices=[0, 1, 2, 3, 4, 5, 6, 7],
        help='从哪个阶段开始执行（0=数据拉取, 1=数据整合, 2=IC计算, 3=回测, 4=综合因子, 5=权重选择, 6=股票选股, 7=汇总报告）'
    )

    parser.add_argument(
        '--start-script', type=str, default=None,
        help='从哪个脚本开始执行（脚本名称，如 fetch_turnover）'
    )

    parser.add_argument(
        '--skip-stages', type=int, nargs='*', default=[],
        help='跳过的阶段（如 --skip-stages 0 1 跳过数据拉取和整合）'
    )

    parser.add_argument(
        '--max-retries', type=int, default=MAX_RETRIES,
        help=f'脚本级别最大重试次数（默认 {MAX_RETRIES}）'
    )

    parser.add_argument(
        '--retry-delay', type=int, default=RETRY_DELAY,
        help=f'重试间隔秒数（默认 {RETRY_DELAY}）'
    )

    args = parser.parse_args()

    # 更新全局配置
    MAX_RETRIES = args.max_retries
    RETRY_DELAY = args.retry_delay

    # 执行流程
    success = run_pipeline(
        start_stage=args.start_stage,
        start_script=args.start_script,
        skip_stages=args.skip_stages
    )

    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
