#!/usr/bin/env python3
"""
振幅因子分层回测脚本

因子定义：
- 含义: 过去N日价格波动幅度

分层模式：percentile 5层（每层约20%）

注：因子元数据派生机制（factor_direction / n_layers / long_short_layers）
为基类 LayerConfigBase 通用职责，详见基类 docstring。
"""

import sys
from collections.abc import Sequence
from typing import ClassVar

from backtest.common.factor_cli import factor_cli_main
from backtest.common.layered_backtest_runner import LayerConfigBase
from backtest.common.logger_config import get_logger
from data_fetchers.factor_calculator import calculate_amplitude


class AmplitudeLayerConfig(LayerConfigBase):
    """振幅因子分层配置

    瘦声明（minimal declaration）：仅定义因子名称与分层命名，逻辑完全下沉基类。
    """

    factor_name: ClassVar[str] = "amplitude"

    layer_names: ClassVar[Sequence[str]] = ("lowest", "lower", "normal", "higher", "highest")

    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层(振幅最小)",
        "偏低层(振幅较小)",
        "正常层(振幅适中)",
        "偏高层(振幅较大)",
        "极高层(振幅最大)",
    )


if __name__ == "__main__":
    # 最外层兜底：factor_cli_main 内部已收敛业务异常并以 ExitCode 退出。
    # 此处仅保护 SystemExit 之外的"启动期/未预期异常"（如 import 期失败、
    # 配置类构造抛出未被 CLI 捕获的异常），保证 CI/调度系统能拿到非 0 退出码。
    _logger = get_logger("amplitude")
    _logger.debug("启动参数 argv=%s", sys.argv)
    try:
        factor_cli_main(config_cls=AmplitudeLayerConfig, factor_calculator=calculate_amplitude)
    except SystemExit:
        # factor_cli_main 通过 sys.exit(ExitCode.*) 主动退出，透传码值
        raise
    except Exception:
        _logger.exception("amplitude 因子分层回测启动期未预期异常")
        sys.exit(1)
