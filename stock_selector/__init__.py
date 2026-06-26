"""
stock_selector 模块 — 股票选股系统

从 comprehensive_factor 迁移为独立顶层模块 (2026-06-26)。

子模块:
- stock_selector: 核心选股逻辑 + CLI
- stock_selector_config: 配置/常量/数据加载
- stock_selector_history: Parquet 选股历史写入
- stock_selector_lr: LR 过滤训练/应用

Note: weight_selector.py 已移回 comprehensive_factor/composite_weight_selector.py

向后兼容: `from stock_selector import X` 等价于原 `from comprehensive_factor.stock_selector import X`
"""

# Re-exports: 保持所有 `from stock_selector import X` 向后兼容
# 从 factor_definitions re-export（测试依赖）
# 最后导入 stock_selector.stock_selector（它依赖上面的子模块）
# 用 suppress 处理 __main__ 运行时的循环导入
import contextlib

from factor_definitions import FACTOR_CATEGORIES  # noqa: F401

# 注意导入顺序：先导入不依赖 stock_selector.py 的子模块，
# 最后导入 stock_selector.stock_selector（它内部 re-export config/history/lr）。
# 当 stock_selector.py 作为 __main__ 运行时，它的 from stock_selector.xxx import
# 会触发本 __init__.py；若 __init__.py 先加载 config/history/lr，则 stock_selector.py
# 的后续 import 能直接从 sys.modules 取到，不会循环。
from stock_selector.stock_selector_config import (  # noqa: F401
    ALL_WEIGHT_METHODS,
    DEFAULT_DATA_SOURCE,
    DEFAULT_FACTOR_COLS,
    DEFAULT_FACTOR_LIST,
    DEFAULT_IC_RESULT_DIR,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_WEIGHT_RESULT_PATH,
    EPSILON,
    PROJECT_ROOT,
    StockSelectorConfig,
    get_latest_date,
    load_selected_factors_from_composite,
    load_weight_config,
)
from stock_selector.stock_selector_history import write_selection_history  # noqa: F401
from stock_selector.stock_selector_lr import (  # noqa: F401
    apply_lr_filter,
    backfill_forward_return_1d,
    calibrate_lr_filter,
    save_lr_training_data,
)


with contextlib.suppress(ImportError):
    from stock_selector.stock_selector import (  # noqa: F401
        apply_filter_role_factors,
        apply_stabilization_filter,
        apply_stage2_resort,
        build_result,
        select_stocks,
        sort_and_select,
    )


__all__ = [
    # config
    "ALL_WEIGHT_METHODS",
    "DEFAULT_DATA_SOURCE",
    "DEFAULT_FACTOR_COLS",
    "DEFAULT_FACTOR_LIST",
    "DEFAULT_IC_RESULT_DIR",
    "DEFAULT_OUTPUT_DIR",
    "DEFAULT_WEIGHT_RESULT_PATH",
    "EPSILON",
    "PROJECT_ROOT",
    "StockSelectorConfig",
    "get_latest_date",
    "load_selected_factors_from_composite",
    "load_weight_config",
    # history
    "write_selection_history",
    # lr
    "apply_lr_filter",
    "backfill_forward_return_1d",
    "calibrate_lr_filter",
    "save_lr_training_data",
    # selector
    "apply_filter_role_factors",
    "apply_stage2_resort",
    "apply_stabilization_filter",
    "build_result",
    "select_stocks",
    "sort_and_select",
]
