# Design: generate_factor_summary_report.py 拆分重构

> 版本: v1.0
> 创建时间: 2026-06-26
> 状态: Plan 阶段

## 1. 背景

`summary/generate_factor_summary_report.py` 已增长至 3,207 行（44 个函数），单文件承担了数据新鲜度检查、数据加载、格式化工具、12 个 section 渲染、报告编排、CLI 入口 6 类职责。需要拆分为多文件包结构，提升可维护性。

## 2. 目标

- 将单文件拆分为 `summary/report/` 子包，按职责分模块
- **保持所有公共接口不变**——测试文件导入路径 `from summary.generate_factor_summary_report import ...` 必须继续可用
- 每个新文件控制在 200~400 行
- 拆分后行为 100% 一致（纯搬迁，不改逻辑）

## 3. 拆分方案

### 3.1 目标目录结构

```
summary/
├── __init__.py                         # 已存在
├── generate_factor_summary_report.py   # 主入口（~200行），保留 main() + generate_report()
├── report/                             # 新子包
│   ├── __init__.py                     # 空文件
│   ├── constants.py                    # 全局常量 + 配置表
│   ├── data_loaders.py                 # 所有 load_* 函数 + 辅助
│   ├── freshness_check.py              # 数据新鲜度检查
│   ├── formatters.py                   # 格式化工具函数
│   ├── factor_analysis.py              # 因子筛选/相关性/中性化分析
│   └── sections.py                     # 12 个 _generate_*_section 渲染函数
├── MODULE.md
├── ...
```

### 3.2 模块职责分配

#### `report/constants.py` (~120 行)

迁移内容：
- `PROJECT_ROOT`（保留在主文件，子模块通过参数传递或从主文件导入）
- `FACTOR_ABBR`, `_get_factor_abbr()`
- `COL_TO_FACTOR_NAME_MAP` (= `FACTOR_COL_TO_NAME_MAP`)
- `DATA_PATHS`, `DATA_FRESHNESS_HEAD_CHARS`, `DATA_CHECK_SOURCES`
- `CORR_THRESHOLD_HIGH/MEDIUM/MAX`, `ICIR_THRESHOLD`, `RETURN_THRESHOLD`
- `MAX_STOCKS_SAMPLE`, `RETURN_DATA_IS_DECIMAL`

**关键决策**: `PROJECT_ROOT` 和 `setup_logger` 保留在主文件中，因为 `sys.path` 操作必须在导入时执行。子模块需要 `PROJECT_ROOT` 时从主文件导入，或通过参数传入。为避免循环导入，`constants.py` 将定义自己的 `PROJECT_ROOT`（独立计算），因为 `Path(__file__).parent.parent.parent.resolve()` 从 `report/constants.py` 出发也能正确指向项目根目录。

#### `report/freshness_check.py` (~250 行)

迁移函数：
- `get_expected_t_minus_1()`
- `get_expected_t_minus_2()`
- `check_data_freshness()`
- `check_derived_data_freshness()`
- `_get_nested_field()`
- `_extract_date_from_json_content()`
- `_generate_data_check_section()`

依赖：`constants.py`

#### `report/data_loaders.py` (~350 行)

迁移函数：
- `load_json_file()`
- `_select_neutral_payload()`
- `load_ic_results()`
- `load_backtest_results()`
- `load_composite_results()`
- `load_weight_selection_result()`
- `load_stock_selection_result()`（含 `_meta_str/_meta_int/_meta_float/_meta_json/_row_to_stock_dict`）
- `load_stock_name_map()`
- `calculate_factor_correlation()`
- `merge_factor_data()`

依赖：`constants.py`

#### `report/formatters.py` (~150 行)

迁移函数：
- `get_monotonicity_symbol()`
- `get_weight_method_display()`
- `format_weights()`
- `format_percentage()`
- `convert_return_to_percentage()`
- `format_float()`
- `get_date_str()`

依赖：`constants.py`（`COL_TO_FACTOR_NAME_MAP`, `_get_factor_abbr`）

#### `report/factor_analysis.py` (~400 行)

迁移函数：
- `_extract_corr_pairs()`
- `generate_correlation_section()`
- `_format_exempt_note()`
- `get_factor_selection_info()`
- `_format_neutral_cell()`
- `_generate_neutralization_notes()`
- `_detect_duplicate_zscores()`
- `_compute_factor_concentration()`
- `_detect_weight_rank_anomalies()`

依赖：`constants.py`, `formatters.py`

#### `report/sections.py` (~900 行)

迁移函数：
- `_generate_ic_section()`
- `_generate_backtest_section()`
- `_generate_composite_section()`
- `_generate_weight_selection_section()`
- `_generate_lr_training_status()`
- `_generate_stock_selection_section()`（383 行，最大函数）
- `_generate_comparison_section()`（224 行）

依赖：`constants.py`, `formatters.py`, `factor_analysis.py`

#### `generate_factor_summary_report.py` (主文件, ~250 行)

保留内容：
- `__version__`, `__author__`
- 模块文档字符串（精简版本历史，保留最新版本号）
- `setup_logger()`
- `generate_report()`（编排函数）
- `main()`
- `PROJECT_ROOT` + `sys.path` 操作

从子模块 re-export 所有被测试导入的名称：
```python
from summary.report.constants import (
    COL_TO_FACTOR_NAME_MAP, FACTOR_ABBR, DATA_PATHS,
    DATA_CHECK_SOURCES, CORR_THRESHOLD_HIGH, ...
)
from summary.report.freshness_check import (
    check_data_freshness, check_derived_data_freshness,
    get_expected_t_minus_1, _get_nested_field,
    _extract_date_from_json_content, _generate_data_check_section,
)
from summary.report.data_loaders import (
    load_json_file, load_ic_results, load_backtest_results,
    load_composite_results, load_weight_selection_result,
    load_stock_selection_result, load_stock_name_map,
    calculate_factor_correlation, merge_factor_data,
    _select_neutral_payload,
)
from summary.report.formatters import (
    get_monotonicity_symbol, get_weight_method_display,
    format_weights, format_percentage, format_float,
    convert_return_to_percentage, get_date_str,
)
from summary.report.factor_analysis import (
    generate_correlation_section, get_factor_selection_info,
    _format_neutral_cell, _generate_neutralization_notes,
    _extract_corr_pairs, _format_exempt_note,
    _detect_duplicate_zscores, _compute_factor_concentration,
    _detect_weight_rank_anomalies,
)
from summary.report.sections import (
    _generate_ic_section, _generate_backtest_section,
    _generate_composite_section, _generate_weight_selection_section,
    _generate_lr_training_status, _generate_stock_selection_section,
    _generate_comparison_section,
)
```

### 3.3 测试兼容性策略

**核心原则**: 测试文件不改，通过主文件 re-export 保持 `from summary.generate_factor_summary_report import X` 可用。

测试文件导入的 22 个名称（含 `__version__`）必须在主文件 `__all__` 或模块级命名空间中可见。

`test_neutral_cell.py` 导入的 `_format_neutral_cell`, `_generate_ic_section`, `_select_neutral_payload` 同样通过 re-export 覆盖。

## 4. 执行计划（分轮次）

按 AGENTS.md 任务粒度约束（≤3 文件/轮），分 5 轮执行：

| 轮次 | 文件 | 内容 | 行数估计 |
|------|------|------|---------|
| R1 | `report/__init__.py` + `report/constants.py` | 创建子包 + 迁移常量 | ~150 |
| R2 | `report/formatters.py` + `report/freshness_check.py` | 格式化 + 新鲜度检查 | ~400 |
| R3 | `report/data_loaders.py` | 数据加载器 | ~350 |
| R4 | `report/factor_analysis.py` | 因子分析逻辑 | ~400 |
| R5 | `report/sections.py` + 改主文件 | Section 渲染 + 主文件瘦身 + re-export | ~900 + ~250 |

每轮完成后：
1. `ruff check --fix` + `ruff format`
2. `pytest summary/test_cases/` 全量通过
3. `git commit`（显式路径）

## 5. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 循环导入 | `constants.py` 不导入任何项目模块；其他模块单向依赖 `constants → formatters → factor_analysis → sections` |
| `PROJECT_ROOT` 不一致 | `constants.py` 独立计算 `PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()`，验证一致性 |
| 测试导入断裂 | 每轮完成后跑全量 pytest 验证 re-export |
| import-linter 误报 | import-linter 只约束 5 个顶层模块互不导入 common/，`summary.report` 是子包不受影响 |
| 行为变化 | 纯搬迁不改逻辑，不做任何"顺手优化" |

## 6. 验证标准

1. `ruff check summary/` 无新增错误
2. `pytest summary/test_cases/ -v` 全部通过
3. `python summary/generate_factor_summary_report.py --help` 正常运行
4. 主文件行数 < 300 行
5. 无循环导入（`python -c "import summary.generate_factor_summary_report"` 成功）
