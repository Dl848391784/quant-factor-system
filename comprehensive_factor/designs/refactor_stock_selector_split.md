# Design: stock_selector.py 拆分重构

> 日期: 2026-06-26
> 版本: v3.12
> 类型: 纯重构（行为不变）

## 动机

`stock_selector.py` 已达 2749 行 / 120KB，包含 19 个顶层定义，职责跨度大（配置加载、LR 过滤训练、Parquet 历史写入、选股编排、CLI）。函数间耦合度低（除 `select_stocks` 编排器外几乎无交叉调用），适合按职责拆分。

## 拆分方案

保持 `stock_selector.py` 作为门面文件（facade），提取 3 个子模块。所有现有 `from comprehensive_factor.stock_selector import X` 路径不变。

### 新文件结构

```
comprehensive_factor/
  stock_selector.py              # 门面：re-exports + 核心选股逻辑 + CLI (~1400 行)
  stock_selector_config.py       # 配置 + 数据加载 (~350 行)
  stock_selector_lr.py           # LR 过滤训练/应用/训练数据保存 (~650 行)
  stock_selector_history.py      # Parquet 选股历史写入 (~300 行)
```

### 各模块内容

#### stock_selector_config.py (~350 行)

| 符号 | 原行号 | 行数 | 说明 |
|------|--------|------|------|
| `PROJECT_ROOT` | L68 | 1 | 路径常量 |
| `DEFAULT_DATA_SOURCE` | L101 | 1 | 默认数据源路径 |
| `DEFAULT_IC_RESULT_DIR` | L102 | 1 | IC 结果目录 |
| `DEFAULT_WEIGHT_RESULT_PATH` | L103 | 1 | 权重结果路径 |
| `DEFAULT_OUTPUT_DIR` | L104 | 1 | 输出目录 |
| `DEFAULT_FACTOR_LIST` | L107 | 1 | 默认因子列表 |
| `DEFAULT_FACTOR_COLS` | L109 | 1 | 默认因子列 |
| `EPSILON` | L218 | 1 | 数值精度常量 |
| `ALL_WEIGHT_METHODS` | L1662 | 1 | 权重方法元组 |
| `StockSelectorConfig` | L113-220 | 108 | 配置 dataclass |
| `load_weight_config` | L221-283 | 63 | 加载权重配置 |
| `load_selected_factors_from_composite` | L284-348 | 65 | 从 composite 结果读取因子列表 |
| `get_latest_date` | L349-385 | 37 | 获取最新日期 |

**导入**: `sys`, `pathlib.Path`, `json`, `logging`, `dataclasses`, `typing`, `factor_definitions`(FACTOR_CATEGORIES, FACTOR_COL_TO_NAME_MAP), `comprehensive_factor.common.logger_config`

#### stock_selector_lr.py (~650 行)

| 符号 | 原行号 | 行数 | 说明 |
|------|--------|------|------|
| `_discover_features` | L893-975 | 83 | 特征发现 |
| `calibrate_lr_filter` | L976-1185 | 210 | LR 过滤校准 |
| `apply_lr_filter` | L1186-1296 | 111 | LR 过滤应用 |
| `save_lr_training_data` | L1755-1985 | 231 | LR 训练数据持久化 |
| `backfill_forward_return_1d` | L1986-2092 | 107 | 次日收益补写 |

**内部依赖**: `calibrate_lr_filter` → `_discover_features`; `save_lr_training_data` → `backfill_forward_return_1d`

**外部依赖**: 需要 `ALL_WEIGHT_METHODS`, `EPSILON` 从 config 导入; `WeightEngine` 从 common 导入; `FACTOR_COL_TO_NAME_MAP` 从 factor_definitions 导入

#### stock_selector_history.py (~300 行)

| 符号 | 原行号 | 行数 | 说明 |
|------|--------|------|------|
| `write_selection_history` | L1388-1642 | 255 | Parquet 选股历史写入 |
| `_load_stock_name_map` | L1643-1664 | 22 | 股票名称映射加载 |

**外部依赖**: 需要 `PROJECT_ROOT` 从 config 导入; `pyarrow`; `pandas`

#### stock_selector.py (瘦身后 ~1400 行)

保留的核心函数:

| 符号 | 原行号 | 行数 | 说明 |
|------|--------|------|------|
| `sort_and_select` | L386-648 | 263 | 排序选股核心 |
| `apply_filter_role_factors` | L649-691 | 43 | 角色因子过滤 |
| `apply_stage2_resort` | L692-787 | 96 | Stage 2 重排序 |
| `apply_stabilization_filter` | L788-892 | 105 | 企稳确认过滤 |
| `build_result` | L1297-1387 | 91 | 结果构建 |
| `_compute_composite_for_method` | L1665-1754 | 90 | 单方法综合因子计算 |
| `select_stocks` | L2093-2613 | 521 | 主编排函数 |
| `create_cli_entrypoint` | L2614-2749 | 136 | CLI 入口 |

**额外职责**: 从 3 个子模块 re-export 所有公共符号，保持 `from comprehensive_factor.stock_selector import X` 向后兼容。

### Re-export 清单

`stock_selector.py` 顶部需显式 re-export:

```python
# 从 config 模块 re-export
from comprehensive_factor.stock_selector_config import (
    StockSelectorConfig,
    load_weight_config,
    load_selected_factors_from_composite,
    get_latest_date,
    PROJECT_ROOT,
    DEFAULT_DATA_SOURCE,
    DEFAULT_IC_RESULT_DIR,
    DEFAULT_WEIGHT_RESULT_PATH,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_FACTOR_LIST,
    DEFAULT_FACTOR_COLS,
    EPSILON,
    ALL_WEIGHT_METHODS,
)
# 从 lr 模块 re-export
from comprehensive_factor.stock_selector_lr import (
    calibrate_lr_filter,
    apply_lr_filter,
    save_lr_training_data,
    backfill_forward_return_1d,
)
# 从 history 模块 re-export
from comprehensive_factor.stock_selector_history import (
    write_selection_history,
)
# 保持原有 re-export（factor_definitions / factor_loader）
from factor_definitions import FACTOR_CATEGORIES, FACTOR_COL_TO_NAME_MAP  # noqa: F401
from comprehensive_factor.common.factor_loader import load_ic_daily, load_ic_results  # noqa: F401
```

## 向后兼容性

**所有以下导入路径保持不变（零改动）：**

| 导入方 | 导入符号 | 新来源 |
|--------|---------|--------|
| test_stock_selector.py | StockSelectorConfig, build_result, get_latest_date, load_weight_config, select_stocks, sort_and_select | config + stock_selector |
| test_two_stage_selector.py | StockSelectorConfig, apply_stage2_resort, save_lr_training_data, calibrate_lr_filter, apply_lr_filter, _compute_composite_for_method | config + stock_selector + lr |
| test_liquidity_filter.py | sort_and_select | stock_selector |
| test_stock_selector_exposure.py | sort_and_select | stock_selector |
| test_selection_history_parquet.py | StockSelectorConfig, write_selection_history | config + history |
| test_stock_selector_filter.py | apply_stabilization_filter | stock_selector |
| test_filter_role.py | apply_filter_role_factors | stock_selector |
| test_p5_mapping_chain.py | FACTOR_CATEGORIES | stock_selector (re-export from factor_definitions) |
| summary/generate_factor_summary_report.py | StockSelectorConfig, calibrate_lr_filter | config + lr (via stock_selector) |
| temporary/backfill_lr_training_data.py | save_lr_training_data, load_ic_daily, load_ic_results | lr + factor_loader (via stock_selector) |

## sys.path 处理

每个新模块需要独立的 `sys.path` 插入（因为 `factor_definitions` 在项目根目录）:

```python
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
```

`stock_selector.py` 保留原有的 sys.path 处理不变。

## 执行步骤

### Step 1: 创建 stock_selector_config.py
提取配置类、常量、数据加载函数。更新 stock_selector.py 导入。

### Step 2: 创建 stock_selector_lr.py
提取 LR 过滤相关函数。更新 stock_selector.py 导入。

### Step 3: 创建 stock_selector_history.py
提取 Parquet 历史写入函数。更新 stock_selector.py 导入。

### Step 4: 验证 + 提交
- ruff check + format
- pytest 全部选股相关测试
- 更新 MODULE.md 版本记录
- git commit

## 风险评估

- **循环导入**: 无风险。依赖方向单向: `stock_selector.py → {config, lr, history}`; `lr → config`; `history → config`
- **行为变化**: 零。纯机械提取，不修改任何函数逻辑
- **测试**: 所有现有测试不改动，验证 re-export 正确性
