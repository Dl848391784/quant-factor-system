#!/usr/bin/env python3
"""
因子分层回测 CLI 公共入口

将因子脚本的 CLI 入口、异常处理、结果摘要打印抽取为公共函数，
让每个因子脚本压缩到 ~30 行。

使用方式：
    简单脚本（无自定义参数）：
        from backtest.common.factor_cli import factor_cli_main

        if __name__ == '__main__':
            sys.path.insert(0, str(Path(__file__).parent.parent))
            factor_cli_main(
                config_cls=AmplitudeLayerConfig,
                factor_calculator=calculate_amplitude
            )

    复杂脚本（有自定义参数如 --rsi-n）：
        def add_rsi_args(parser):
            parser.add_argument('--rsi-n', type=int, default=6)

        def setup_rsi_calculator(args, calc):
            return partial(calc, n=args.rsi_n)

        factor_cli_main(
            config_cls=RSILayerConfig,
            factor_calculator=calculate_rsi,
            add_cli_args=add_rsi_args,
            setup_calculator=setup_rsi_calculator
        )

退出码规范：
    0: 成功完成
    1: result 为 None（公共模块异常返回）
    2: 无有效数据（n_days_total == 0）
    3: 数据结构问题（KeyError/ValueError）
    4: 数据文件不存在（FileNotFoundError）
    5: RuntimeError（已知业务异常）
    6: 未预期异常

作者: 云瑶
创建日期: 2026-06-01
版本历史:
  v2.1 (2026-06-01):
    - argparse 长选项改为 kebab-case（GNU 惯例）
    - 退出码改为 IntEnum（避免魔法数字）
    - 抽取 _die() 辅助函数收敛错误处理
    - 显式区分 long_short 键缺失 vs 真实零值
    - 启动时回放 CLI 参数
    - layer_stats 按层序排序输出
    - 添加回测耗时日志
"""

import argparse
import sys
from collections.abc import Callable
from enum import IntEnum
from time import perf_counter

from backtest.common.layered_backtest_runner import LayerConfigBase, run_layered_backtest
from backtest.common.logger_config import get_logger


class ExitCode(IntEnum):
    """退出码枚举（避免魔法数字，便于外部脚本/CI 解析）"""

    SUCCESS = 0
    RESULT_NONE = 1
    NO_DATA = 2
    DATA_STRUCTURE_ERROR = 3
    FILE_NOT_FOUND = 4
    RUNTIME_ERROR = 5  # 已知业务异常（数据请求失败、缓存读写失败等）
    UNEXPECTED_ERROR = 6  # 未预期异常


def _die(logger, code: ExitCode, msg: str) -> None:
    """错误处理辅助函数：收敛 logger.error + sys.exit 模式

    Args:
        logger: 日志对象
        code: 退出码（ExitCode 枚举）
        msg: 错误消息
    """
    logger.error(msg)
    sys.exit(code)


def factor_cli_main(
    config_cls: type[LayerConfigBase],
    factor_calculator: Callable | None = None,  # 允许 None（预计算因子）
    *,
    add_cli_args: Callable[[argparse.ArgumentParser], None] | None = None,
    setup_calculator: Callable[[argparse.Namespace, Callable], Callable] | None = None,
) -> None:
    """因子分层回测 CLI 公共入口

    设计变更（v2.3，2026-06-01）：
    - 删除 factor_col 和 required_factor_cols 参数，从 config_cls 按需派生
    - 收敛"因子描述配置"到 LayerConfigBase 子类，压扁封装
    - 启动时打印 INFO 日志包含 factor_name/direction/n_layers

    Args:
        config_cls: 分层配置类（LayerConfigBase 子类，需有 factor_name ClassVar）
        factor_calculator: 因子计算函数（预计算因子传 None）

        add_cli_args: 添加自定义 CLI 参数的函数
        setup_calculator: 根据 args 包装 calculator 的函数（如 partial）

    退出码：
        0: 成功
        1: result 为 None
        2: 无有效数据
        3: KeyError/ValueError
        4: FileNotFoundError
        5: RuntimeError（已知业务异常）
        6: 未预期异常

    Example:
        # 简单脚本（因子列名 = factor_name）
        factor_cli_main(Return5dLayerConfig, calculate_return_5d)

        # 预计算因子（factor_col 显式声明在配置类）
        class VolumeRatioLayerConfig(LayerConfigBase):
            factor_name: ClassVar[str] = 'volume_ratio'
            factor_col: ClassVar[str] = 'volume_ratio_5'
        factor_cli_main(VolumeRatioLayerConfig)

        # 复杂脚本（自定义参数）
        def add_args(p):
            p.add_argument('--rsi-n', type=int, default=6)

        def setup(args, calc):
            from functools import partial
            return partial(calc, n=args.rsi_n)

        factor_cli_main(RSILayerConfig, calculate_rsi,
                        add_cli_args=add_args, setup_calculator=setup)
    """
    # 从 config_cls 提取 factor_name（单一来源）
    factor_name = getattr(config_cls, "factor_name", None)
    if factor_name is None:
        raise ValueError(f"config_cls 需要定义 factor_name ClassVar，当前类: {config_cls.__name__}")

    # CLI 描述自动生成
    description = f"{factor_name} 因子分层回测"
    # CLI 参数解析
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--data-source",
        type=str,
        default=None,
        dest="data_source",  # Python 属性名保持下划线
        help="数据源文件路径",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        dest="output_dir",  # Python 属性名保持下划线
        help="输出目录路径",
    )
    parser.add_argument("--quiet", action="store_true", help="静默模式")

    # 自定义参数
    if add_cli_args:
        add_cli_args(parser)

    args = parser.parse_args()

    # --quiet 控制日志级别（静默模式：WARNING 级别，只显示错误和警告）
    logger = get_logger(factor_name)
    if args.quiet:
        logger.setLevel("WARNING")

    # 启动时回放 CLI 参数（事后可复现具体 data_source/output_dir 取值）
    if not args.quiet:
        logger.info("运行参数: %s", vars(args))

    # 记录开始时间（计算回测耗时）
    start_time = perf_counter()

    # 配置实例（基类 __post_init__ 已打印启动日志）
    config = config_cls()

    # 因子列名从 config 派生（优先 factor_col，否则 factor_name）
    factor_col = config.factor_col_resolved

    # required_factor_cols 派生：
    #   1. 预计算因子：factor_col 本身就是所需列
    #   2. 需计算因子：从 calculator.required_cols 读取
    if factor_calculator is None:
        required_factor_cols = [factor_col]
    else:
        required_factor_cols = getattr(factor_calculator, "required_cols", None)

    # 包装 calculator（如 partial）
    if setup_calculator and factor_calculator is not None:
        factor_calculator = setup_calculator(args, factor_calculator)  # type: ignore[arg-type]

    # try 范围收窄：仅包裹 run_layered_backtest() 调用
    try:
        result = run_layered_backtest(
            factor_name=factor_name,
            factor_col=factor_col,
            config=config,
            factor_calculator=factor_calculator,  # type: ignore[arg-type]
            required_factor_cols=required_factor_cols,
            data_source=args.data_source,
            output_dir=args.output_dir,
            verbose=not args.quiet,
            logger=logger,
        )
    except FileNotFoundError as e:
        _die(logger, ExitCode.FILE_NOT_FOUND, f"数据文件不存在: {e}")
    except (KeyError, ValueError) as e:
        _die(logger, ExitCode.DATA_STRUCTURE_ERROR, f"数据问题: {e}")
    except RuntimeError as e:
        # 已知业务异常（数据请求失败、缓存读写失败等），error() 不打印完整堆栈
        _die(logger, ExitCode.RUNTIME_ERROR, f"回测失败: {e}")
    except Exception:
        # 未预期异常，exception() 自动打印完整堆栈便于排查
        logger.exception("未预期的错误")
        sys.exit(ExitCode.UNEXPECTED_ERROR)

    # 结果摘要（移出 try 块）

    # 保底处理
    if result is None:
        _die(logger, ExitCode.RESULT_NONE, "run_layered_backtest 返回 None")

    # 检查有效数据
    meta = result.get("meta") or {}
    n_days_total = meta.get("n_days_total") or 0
    if n_days_total == 0:
        _die(logger, ExitCode.NO_DATA, "回测无有效数据，程序终止")

    # 结果摘要
    logger.info("回测结果摘要")
    logger.info("因子名称: %s", factor_name)  # 直接用变量，不从 meta 反查
    logger.info("回测周期: %s 天", n_days_total)

    # 各分层收益（按层序排序输出，避免依赖字典插入顺序）
    layer_stats = result.get("layer_stats") or {}
    # 排序：按 layer_key 中的数字部分排序（layer_1, layer_2, ... → 1, 2, ...）
    sorted_layer_keys = sorted(layer_stats.keys(), key=lambda k: int(k.replace("layer_", "")))
    for layer_key in sorted_layer_keys:
        stats = layer_stats[layer_key]
        # layer_key 格式: 'layer_1', 'layer_2', ...
        layer_id = layer_key.replace("layer_", "")
        display_name = config.layer_names_dict.get(layer_id, f"Layer{layer_id}")
        cumulative_return = stats.get("cumulative_return") or 0.0
        logger.info("Layer %s (%s) 累计收益: %.4f", layer_id, display_name, cumulative_return)

    # 多空组合收益（统一处理：键缺失/值为 None 时打 warning）
    long_short = result.get("long_short") or {}
    if long_short:
        # 多空日均收益（规范定义字段）
        if "long_short_return_daily" not in long_short:
            logger.warning("多空组合缺少 long_short_return_daily 字段")
        else:
            val = long_short["long_short_return_daily"]
            if val is None:
                logger.warning("多空组合 long_short_return_daily 为 None")
            else:
                logger.info("多空日均收益: %.4f%%", val * 100)

        # 多空夏普比率（规范定义字段）
        if "long_short_sharpe" not in long_short:
            logger.warning("多空组合缺少 long_short_sharpe 字段")
        else:
            val = long_short["long_short_sharpe"]
            if val is None:
                logger.warning("多空组合 long_short_sharpe 为 None")
            else:
                logger.info("多空组合夏普比率: %.2f", val)

        # 数据覆盖率（规范定义字段）
        if "coverage" not in long_short:
            logger.warning("多空组合缺少 coverage 字段")
        else:
            val = long_short["coverage"]
            if val is None:
                logger.warning("多空组合 coverage 为 None")
            else:
                logger.info("数据覆盖率: %.1f%%", val * 100)
    else:
        logger.warning("未生成多空组合指标")

    # 回测耗时日志（分层回测属计算密集任务）
    elapsed = perf_counter() - start_time
    logger.info("回测耗时: %.1fs", elapsed)
    logger.info("%s 因子分层回测完成", factor_name)
