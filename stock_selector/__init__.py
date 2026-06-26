"""
stock_selector 模块 — 股票选股系统

从 comprehensive_factor 迁移为独立顶层模块 (2026-06-26)。

子模块:
- selector: 核心选股逻辑 + CLI
- config: 配置/常量/数据加载
- history: Parquet 选股历史写入
- lr: LR 过滤训练/应用
- weight_selector: 权重方式选择

向后兼容: `from stock_selector import X` 等价于原 `from comprehensive_factor.stock_selector import X`
"""

# Re-exports: 保持所有 `from stock_selector import X` 向后兼容
# 从 factor_definitions re-export（测试依赖）
from factor_definitions import FACTOR_CATEGORIES  # noqa: F401
from stock_selector.config import (  # noqa: F401
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
from stock_selector.history import write_selection_history  # noqa: F401
from stock_selector.lr import (  # noqa: F401
    apply_lr_filter,
    backfill_forward_return_1d,
    calibrate_lr_filter,
    save_lr_training_data,
)
from stock_selector.selector import (  # noqa: F401
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
