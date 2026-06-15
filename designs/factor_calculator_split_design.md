# Design: factor_calculator.py 拆分重构

> 创建时间: 2026-06-15 (待补) 北京时间
> 作者: 云瑶
> 状态: **待审核 (Design-First, 遵循 PROJECT.md / AGENTS.md "0. 开发流程" 中的 Design-First 流程)**
> 触发原因: AGENTS.md 任务粒度约束（≤3 文件 ≤200 行）+ 涉及 80+ 外部 import 点，必须先通过 design.md 审核

---

## 目录

1. [背景与动机](#1-背景与动机)
2. [现状量化体检](#2-现状量化体检)
3. [拆分目标与非目标](#3-拆分目标与非目标)
4. [拆分方案：包化 + `__init__.py` 重导出](#4-拆分方案包化--__init__py-重导出)
5. [子模块函数清单（按行号映射）](#5-子模块函数清单按行号映射)
6. [外部依赖影响面](#6-外部依赖影响面)
7. [兼容性策略（无侵入式拆分）](#7-兼容性策略无侵入式拆分)
8. [PR 切片计划（Bite-sized Tasks）](#8-pr-切片计划bite-sized-tasks)
9. [测试与验证策略](#9-测试与验证策略)
10. [文档同步清单](#10-文档同步清单)
11. [风险与回滚预案](#11-风险与回滚预案)
12. [规范引用与取证](#12-规范引用与取证)
13. [审核 Checklist](#13-审核-checklist)

---

## 1. 背景与动机

### 1.1 问题陈述

`data_fetchers/factor_calculator.py` 已成长为 **2779 行 / 104 KB / 41 个函数** 的超大单文件，承担了远超"统一因子计算函数库"的职责：

- (a) 通用计算工具底座（`_per_asset_transform`、`_calculate_ewm_with_initial`、`_calculate_delta`、`_wilder_smoothing_rsi`、列名/魔法数字常量）
- (b) 基础技术指标（RSI、Volume Ratio、Bollinger %B、KDJ J、Turnover Surge、Forward Return、`calculate_rsi_df`）
- (c) 个股价格/动量族（price_position、amplitude、past_return_1d/3d/5d、momentum_strength、overnight_return、ma5_deviation、near_high_ratio_5、positive_day_ratio_5、volume_price_strength）
- (d) 止跌信号差分族（amplitude_delta、turnover_surge_delta、tail_price_position_delta、tail_volume_shrink_delta）
- (e) 行业聚合因子（industry_momentum_5d、industry_turnover_trend、industry_amplitude_trend）
- (f) 行业基本面因子 + **外部 parquet 加载**（industry_roe_trend、industry_earnings_growth、industry_pe_trend、`_load_financial_data`、`_merge_asof_financial`）
- (g) 资金流因子 + **外部 parquet 加载**（capital_flow_ratio_trend、capital_flow_intensity、`_load_fund_flow_data`、`_merge_fund_flow_daily`）

**(f)、(g) 已经显著突破"纯计算函数"语义边界** —— 它们包含 I/O 与文件路径解析逻辑（`_get_financial_data_path`、`_get_fund_flow_data_path`）。

### 1.2 核心动机

| 动机 | 现状 | 拆分后 |
|------|------|--------|
| **单一职责（SRP）** | 7 个不同领域混在 1 个文件 | 每个子模块只负责 1 个领域 |
| **修改放大效应** | 13 次版本迭代（v1.0→v1.13），每次新因子都改这一个文件 | 新因子定向落入对应子模块，不污染其他领域 |
| **审查成本** | code review 需上下滚 2779 行才能确认上下文 | 单次 PR 通常只触及 1-2 个子模块 |
| **测试聚焦** | 单测试文件需覆盖 41 函数 → 已经在膨胀 | 每个子模块对应 1 个测试文件，分摊压力 |
| **API 稳定性** | 任何拆分都会破坏 80+ 处外部 import | `__init__.py` 重导出 → 旧 import 路径完全不变 |

### 1.3 与 PROJECT.md / MODULE.md 的关系

- **MODULE.md 约束 #3（行 681-725）**：所有因子脚本必须复用 `factor_calculator` 中的计算函数。拆分后此约束 **不变**，只是物理位置从单文件变为包内子模块；通过 `__init__.py` 重导出保证 import 路径不变。
- **MODULE.md 模块边界规范（行 919）**：拆分发生在 `data_fetchers/` 模块内部，不跨模块边界，不违反任何模块隔离规则。
- **AGENTS.md 跨模块数据路径表**：本拆分 **不影响** 任何模块的输出目录、文件名、字段（因子计算函数是工具，不产出 result/ 文件）。

---

## 2. 现状量化体检

### 2.1 文件体积对比

```
data_fetchers/ 模块内 .py 文件行数排名：
  2779  factor_calculator.py     ← 本次拆分目标
  1474  factor_generator.py      （第 2 名，是本文件的 53%）
  1196  fetch_industry.py
  1167  fetch_tail_trading.py
  1013  fetch_turnover.py
  1004  fetch_stock_list.py
   818  batch_processor.py
   558  fetch_factor_cache.py
   407  data_loader.py
   354  fetch_financial.py
   279  fetch_fund_flow.py
    23  __init__.py
```

**关键判断**：`factor_calculator.py` 比同模块第二名 **高出 88%**，是模块离群值。

### 2.2 函数族分布（行号区段）

| 区段 | 行号范围 | 内容 | 函数数 |
|------|----------|------|--------|
| 文件头 + docstring + 导入 + 常量 | 1 - 234 | 元数据 + `__all__` + 列名常量 + 默认参数常量 | — |
| 通用底座 | 235 - 469 | logger / wilder smoothing / `_per_asset_transform` / `_calculate_ewm_with_initial`（部分） | 4-5 |
| 基础技术指标 | 316 - 832 | RSI / volume_ratio / forward_return / bollinger_pb / kdj_j / turnover_surge | 6 |
| 价格/动量族 | 834 - 1450 | price_position / amplitude / past_return_1d / return_3d/5d / momentum_strength / overnight_return / rsi_df | 8 |
| 差分族 | 1452 - 1630 | `_calculate_delta` + 4 个 `*_delta` | 5 |
| 量价合成族 | 1630 - 1845 | volume_price_strength / positive_day_ratio_5 / ma5_deviation / near_high_ratio_5 | 4 |
| 行业聚合 | 1845 - 2136 | `_add_industry_column` / industry_momentum_5d / industry_turnover_trend / industry_amplitude_trend | 4 |
| 行业基本面（含 I/O） | 2136 - 2508 | `_get_financial_data_path` / `_load_financial_data` / `_merge_asof_financial` / industry_roe_trend / industry_earnings_growth / industry_pe_trend | 6 |
| 资金流（含 I/O） | 2508 - 2779 | `_get_fund_flow_data_path` / `_load_fund_flow_data` / `_merge_fund_flow_daily` / capital_flow_ratio_trend / capital_flow_intensity | 5 |

**结论**：文件已天然按 7 个领域聚集，拆分边界清晰，无需大幅重排函数顺序。

### 2.3 外部依赖广度

`grep -rn "from data_fetchers.factor_calculator\|from .factor_calculator\|from factor_calculator" --include="*.py"` 命中 **80+ 个文件**：

| 来源模块 | 命中数 | 典型 import |
|----------|--------|-------------|
| `backtest/layered_backtest_*.py` | ~25 | `from data_fetchers.factor_calculator import calculate_xxx` |
| `backtest/test_cases/*.py` | ~15 | 同上 |
| `factor_ic/ic_*_1d.py` | ~25 | 同上 |
| `factor_ic/test_cases/*.py` | ~15 | 同上 |
| `data_fetchers/factor_generator.py` | 2 | 函数内动态 import（绝对 + 相对，兼容 `__main__`） |
| `data_fetchers/fetch_factor_cache.py` | 2 | try/except 双路 import（绝对/直接） |
| `data_fetchers/test_cases/*.py` | 3 | 测试文件 |

**关键约束**：
1. 所有 import 形式都是 `from data_fetchers.factor_calculator import <function>` 的扁平 API。
2. 没有 `import data_fetchers.factor_calculator as fc`（即不存在 "fc.xxx" 形式的命名空间用法）。
3. 这意味着 **只要 `__init__.py` 把所有公共函数重导出，所有外部代码一字不改就能继续工作**。

### 2.4 私有 API 的外部使用

`grep` 还命中：
- `data_fetchers/test_cases/test_per_asset_transform.py` 导入 `_per_asset_transform`、`_calculate_ewm_with_initial`（私有函数被测试直接引用）
- `MODULE.md` 行 690 文档化引用 `data_fetchers.factor_calculator._per_asset_transform`（约束 #3 中的 helper 入口）

**含义**：`_per_asset_transform` 与 `_calculate_ewm_with_initial` 虽以下划线开头，**实际是半公开 API**，必须通过 `__init__.py` 同步重导出，否则会破坏测试和 MODULE.md 已声明的契约。

## 3. 拆分目标与非目标

### 3.1 拆分目标（必须达成）

| # | 目标 | 验收标准 |
|---|------|----------|
| G1 | **零侵入兼容**：所有 80+ 处外部 import 一字不改 | `grep "from data_fetchers.factor_calculator import"` 命中数与拆分前完全一致；`pytest` 全量通过 |
| G2 | **单一职责**：每个子模块只承担 1 个领域 | 子模块平均行数 ≤ 500，最大不超过 700 |
| G3 | **半公开 API 保留**：`_per_asset_transform`、`_calculate_ewm_with_initial`、`_calculate_delta` 仍可被测试和 MODULE.md 引用 | `from data_fetchers.factor_calculator import _per_asset_transform` 工作正常 |
| G4 | **新因子落点明确**：未来新增因子能定向落入对应子模块 | design.md §5 的子模块清单 + 决策树 |
| G5 | **文档同步**：MODULE.md / docs/factor_calculator_flow.md / 版本历史同步更新 | 三处文档均反映新结构 |
| G6 | **测试不退化**：`pytest data_fetchers/test_cases/ -v` 通过率与拆分前一致 | 测试 pass/fail 数完全相同 |
| G7 | **CI 不退化**：ruff / mypy / import-linter / JSON Schema 全绿 | `ruff check . && mypy . && pytest --cov-fail-under=70` 通过 |

### 3.2 非目标（本次明确不做）

| # | 非目标 | 不做的原因 |
|---|--------|------------|
| N1 | **不重写因子计算公式** | 拆分是结构调整，不应触碰任何业务逻辑。计算结果必须与拆分前 byte-level 一致。 |
| N2 | **不调整因子方向（is_inverse）** | 因子方向由 PROJECT.md 规则 #5 + 实测 IC 决定，与文件物理位置无关。 |
| N3 | **不引入新依赖** | 不引入 abc、Protocol、注册表、动态发现等"过度工程"机制。重导出用最朴素的 `from .x import *` 或显式重导出。 |
| N4 | **不修改 docstring 内容** | 仅在 docstring 顶部的"版本历史"补一条 v2.0 说明，不调整原有 Args/Returns/Example。 |
| N5 | **不删除/合并任何函数** | 即使存在貌似可合并的相似函数（如 `calculate_return_3d` 与 `calculate_return_5d`），本次也不做合并。 |
| N6 | **不调整 `__all__` 范围** | 拆分前哪些是公共 API、拆分后还是哪些；只是物理位置变化。 |
| N7 | **不动 `factor_generator.py` 与 `fetch_factor_cache.py` 的 try/except 双路 import** | 那是为支持 `python -m data_fetchers.factor_generator` 与 `python factor_generator.py` 两种入口的兼容代码，与本次拆分正交。 |
| N8 | **不在本设计中决定下一波因子开发** | 设计专注"如何拆"，不讨论"接下来加哪些因子"。 |

## 4. 拆分方案：包化 + `__init__.py` 重导出

### 4.1 包目录结构

将 `data_fetchers/factor_calculator.py`（单文件）转换为 `data_fetchers/factor_calculator/`（包）。Python 的 import 系统对"模块"与"包"提供相同的 `from X import Y` 语义，这是本方案能做到零侵入的根本原因。

```
data_fetchers/
├── factor_calculator/                    # ← 新：包（替代原单文件）
│   ├── __init__.py                       # 重导出全部公共 + 半公开 API（参见 §4.2）
│   ├── _common.py                        # 通用底座（私有）
│   │       常量 + _per_asset_transform / _calculate_ewm_with_initial /
│   │       _calculate_delta / _wilder_smoothing_rsi / get_module_logger
│   ├── basic.py                          # 基础技术指标
│   │       calculate_rsi / calculate_volume_ratio / calculate_forward_return /
│   │       calculate_bollinger_pb / calculate_kdj_j / calculate_turnover_surge /
│   │       calculate_rsi_df
│   ├── momentum.py                       # 价格 / 动量族
│   │       calculate_price_position / calculate_amplitude /
│   │       calculate_past_return_1d / calculate_return_3d / calculate_return_5d /
│   │       calculate_momentum_strength / calculate_overnight_return
│   ├── delta.py                          # 止跌信号差分族
│   │       calculate_amplitude_delta / calculate_turnover_surge_delta /
│   │       calculate_tail_price_position_delta / calculate_tail_volume_shrink_delta
│   ├── volume_price.py                   # 量价合成族
│   │       calculate_volume_price_strength / calculate_positive_day_ratio_5 /
│   │       calculate_ma5_deviation / calculate_near_high_ratio_5
│   ├── industry.py                       # 行业聚合（无外部 I/O）
│   │       _add_industry_column / calculate_industry_momentum_5d /
│   │       calculate_industry_turnover_trend / calculate_industry_amplitude_trend
│   ├── industry_financial.py             # 行业基本面（含外部 parquet I/O）
│   │       _get_financial_data_path / _load_financial_data /
│   │       _merge_asof_financial / calculate_industry_roe_trend /
│   │       calculate_industry_earnings_growth / calculate_industry_pe_trend
│   └── fund_flow.py                      # 资金流（含外部 parquet I/O）
│           _get_fund_flow_data_path / _load_fund_flow_data /
│           _merge_fund_flow_daily / calculate_capital_flow_ratio_trend /
│           calculate_capital_flow_intensity
└── factor_calculator.py                  # ← 删除（被同名包替代）
```

**关键设计决策**：
1. **常量集中放 `_common.py`**：所有 `_COL_*`、`_DEFAULT_*`、`_EPSILON` 等常量统一放底座，子模块通过 `from ._common import _COL_CLOSE, ...` 显式 import；不使用 `*` import，避免污染命名空间。
2. **底座文件 `_common.py` 以下划线开头**：表示这是包内私有，外部 **不应** 直接 `from data_fetchers.factor_calculator._common import ...`；外部需要的半公开 helper 由顶层 `__init__.py` 重导出。
3. **保留 `industry.py` 与 `industry_financial.py` 的拆分**：前者纯计算（行业聚合），后者含 I/O（财务数据加载）。这是 §1.1 中点出的"超出纯计算函数语义"问题的修复。
4. **`fund_flow.py` 单独成模**：与 `industry_financial.py` 同样含 I/O，但数据源不同（fund flow vs financial），独立成模便于未来扩展（如新增板块资金流、北向资金流）。

### 4.2 `__init__.py` 重导出策略

采用 **显式重导出**（PEP 8 推荐），不使用 `from .x import *`。理由：
- 显式列表是 API 契约，code review 时一眼可见 API 边界
- mypy `--strict` 与 `ruff` 的 `F401` 规则要求重导出必须用 `as` 别名或显式 `__all__`
- 与原 `factor_calculator.py` 顶部的 `__all__` 一致

`__init__.py` 模板（仅示意，最终代码在 Execute 阶段写）：

```python
"""data_fetchers.factor_calculator 包：统一因子计算函数库。

历史背景：原为单文件 factor_calculator.py（v1.0 - v1.13，2779 行），
v2.0 (2026-06-XX) 拆分为 8 个子模块。所有公共 API 通过本 __init__.py
重导出，外部 import 路径完全保持兼容。

子模块结构详见 designs/factor_calculator_split_design.md。
"""

# ===== 半公开 helper（被 test / MODULE.md 引用，必须重导出） =====
from ._common import (
    _calculate_delta,
    _calculate_ewm_with_initial,
    _per_asset_transform,
    _wilder_smoothing_rsi,
    get_module_logger,
)

# ===== 基础技术指标 =====
from .basic import (
    calculate_bollinger_pb,
    calculate_forward_return,
    calculate_kdj_j,
    calculate_rsi,
    calculate_rsi_df,
    calculate_turnover_surge,
    calculate_volume_ratio,
)

# ===== 价格 / 动量族 =====
from .momentum import (
    calculate_amplitude,
    calculate_momentum_strength,
    calculate_overnight_return,
    calculate_past_return_1d,
    calculate_price_position,
    calculate_return_3d,
    calculate_return_5d,
)

# ===== 差分族 =====
from .delta import (
    calculate_amplitude_delta,
    calculate_tail_price_position_delta,
    calculate_tail_volume_shrink_delta,
    calculate_turnover_surge_delta,
)

# ===== 量价合成族 =====
from .volume_price import (
    calculate_ma5_deviation,
    calculate_near_high_ratio_5,
    calculate_positive_day_ratio_5,
    calculate_volume_price_strength,
)

# ===== 行业聚合 =====
from .industry import (
    calculate_industry_amplitude_trend,
    calculate_industry_momentum_5d,
    calculate_industry_turnover_trend,
)

# ===== 行业基本面（含 I/O） =====
from .industry_financial import (
    calculate_industry_earnings_growth,
    calculate_industry_pe_trend,
    calculate_industry_roe_trend,
)

# ===== 资金流（含 I/O） =====
from .fund_flow import (
    calculate_capital_flow_intensity,
    calculate_capital_flow_ratio_trend,
)

# ===== 公共常量别名（被 ic_kdj_j、ic_rsi 等脚本 import） =====
# PR-1 阶段从 _legacy.py 重导出；PR-2 起从 ._common 重导出，
# 别名定义（DEFAULT_xxx = _DEFAULT_xxx）随 _common.py 一并搬运
from ._common import (
    DEFAULT_BOLLINGER_K,
    DEFAULT_BOLLINGER_N,
    DEFAULT_FORWARD_RETURN_SHIFT,
    DEFAULT_KDJ_M1,
    DEFAULT_KDJ_M2,
    DEFAULT_KDJ_N,
    DEFAULT_RSI_PERIOD,
    DEFAULT_SURGE_WINDOW,
    DEFAULT_VOLUME_RATIO_WINDOW,
)

__all__ = [
    # 与原 factor_calculator.py 顶部 __all__ 完全一致（按字母序）
    # 半公开 helper 不放 __all__（保持私有约定，但仍可被显式 import）
    "calculate_amplitude",
    "calculate_amplitude_delta",
    "calculate_bollinger_pb",
    "calculate_capital_flow_intensity",
    "calculate_capital_flow_ratio_trend",
    "calculate_forward_return",
    "calculate_industry_amplitude_trend",
    "calculate_industry_earnings_growth",
    "calculate_industry_momentum_5d",
    "calculate_industry_pe_trend",
    "calculate_industry_roe_trend",
    "calculate_industry_turnover_trend",
    "calculate_kdj_j",
    "calculate_ma5_deviation",
    "calculate_momentum_strength",
    "calculate_near_high_ratio_5",
    "calculate_overnight_return",
    "calculate_past_return_1d",
    "calculate_positive_day_ratio_5",
    "calculate_price_position",
    "calculate_return_3d",
    "calculate_return_5d",
    "calculate_rsi",
    "calculate_rsi_df",
    "calculate_tail_price_position_delta",
    "calculate_tail_volume_shrink_delta",
    "calculate_turnover_surge",
    "calculate_turnover_surge_delta",
    "calculate_volume_price_strength",
    "calculate_volume_ratio",
    # ----- 公共常量别名（v1.0 起即在 __all__，被外部脚本 import） -----
    "DEFAULT_BOLLINGER_K",
    "DEFAULT_BOLLINGER_N",
    "DEFAULT_FORWARD_RETURN_SHIFT",
    "DEFAULT_KDJ_M1",
    "DEFAULT_KDJ_M2",
    "DEFAULT_KDJ_N",
    "DEFAULT_RSI_PERIOD",
    "DEFAULT_SURGE_WINDOW",
    "DEFAULT_VOLUME_RATIO_WINDOW",
]
```

**ruff 兼容**：所有重导出的 import 语句若被 ruff 报 `F401 (imported but unused)`，可通过：
- 把符号写入 `__all__` 即视为"被使用"（ruff 推荐做法），或
- 在文件顶部加 `# ruff: noqa: F401`（仅在必要时使用，本设计倾向前者）

半公开 helper（`_per_asset_transform` 等）**不进 `__all__`** 但仍 import 到顶层，需在 `__init__.py` 末尾添加：

```python
# 半公开 helper：不进 __all__（约定为私有），但显式 import 保证兼容性
_ = (_per_asset_transform, _calculate_ewm_with_initial, _calculate_delta,
     _wilder_smoothing_rsi, get_module_logger)  # ruff: noqa
```

或更整洁：直接列入一个独立的私有 tuple `_REEXPORT_PRIVATE = (...)` 抑制 F401。**最终写法在 Execute 阶段定稿**。

#### 4.2.1 公共常量别名兼容契约（PR-1 校准）

PR-1 实施时发现 design.md v1.0 漏列了一组真实公共 API：原 `factor_calculator.py` 行 219-227 定义了 9 个常量别名（去掉 `_` 前缀的版本，如 `DEFAULT_RSI_PERIOD = _DEFAULT_RSI_PERIOD`）并写入了 `__all__`，外部脚本（`factor_ic/ic_kdj_j_1d.py`、`ic_rsi_*.py` 等）**直接 import 这些公开常量**而非私有的 `_DEFAULT_*`。

| 公开别名 | 私有源（`_common.py` 内） | 已知调用方（部分） |
|----------|---------------------------|--------------------|
| `DEFAULT_RSI_PERIOD` | `_DEFAULT_RSI_PERIOD` | `factor_ic/ic_rsi_*.py` |
| `DEFAULT_BOLLINGER_N` | `_DEFAULT_BOLLINGER_N` | `factor_ic/ic_bollinger_pb_*.py` |
| `DEFAULT_BOLLINGER_K` | `_DEFAULT_BOLLINGER_K` | 同上 |
| `DEFAULT_KDJ_N` | `_DEFAULT_KDJ_N` | `factor_ic/ic_kdj_j_*.py` |
| `DEFAULT_KDJ_M1` | `_DEFAULT_KDJ_M1` | 同上 |
| `DEFAULT_KDJ_M2` | `_DEFAULT_KDJ_M2` | 同上 |
| `DEFAULT_SURGE_WINDOW` | `_DEFAULT_SURGE_WINDOW` | `factor_ic/ic_turnover_surge_*.py` |
| `DEFAULT_VOLUME_RATIO_WINDOW` | `_DEFAULT_VOLUME_RATIO_WINDOW` | `factor_ic/ic_volume_ratio_*.py` |
| `DEFAULT_FORWARD_RETURN_SHIFT` | `_DEFAULT_FORWARD_RETURN_SHIFT` | `factor_ic/ic_forward_return_*.py` |

**契约**：
1. 这 9 个 `DEFAULT_*` 常量与 30 个 `calculate_*` 函数 **同等优先级**，必须在 `__init__.py` 重导出，不得遗漏
2. 别名定义（`DEFAULT_xxx = _DEFAULT_xxx`）随 `_common.py` 一并搬运（PR-2a 范围）
3. 验证脚本（§7.4）必须把 9 个常量加入 import 列表（已更新）

**经验教训**：design.md 撰写时 grep `from data_fetchers.factor_calculator import` **必须** 完整看 import 项目（不要被 `calculate_*` 模式诱导跳过常量名）。该校准已纳入 §13.1 Checklist。

## 5. 子模块函数清单（按行号映射）

本章为 Execute 阶段的"搬运清单"。每个子模块给出：
1. **函数列表（含原行号区段）** — 便于 git mv-style 搬运校验
2. **依赖（imports）** — 告诉子模块需要从 `_common` 拿什么
3. **预计文件大小** — 验证 G2 目标（每文件 ≤ 700 行）

### 5.1 子模块 1：`_common.py`（通用底座）

**职责**：常量、logger、纯计算 helper。**所有其他子模块都从这里 import**。

| 原行号 | 内容 | 类型 |
|--------|------|------|
| 100 - 234 | 列名常量 `_COL_*`、默认参数常量 `_DEFAULT_*`、`_EPSILON`、`__all__` 移植 | 模块级常量 |
| 235 - 265 | `get_module_logger(logger_arg)` | 半公开函数 |
| 267 - 314 | `_wilder_smoothing_rsi(series, n)` | 半公开私有函数 |
| 470 - 531 | `_per_asset_transform(df, group_col, value_col, fn, ...)` | **核心 helper**（MODULE.md 行 690 引用） |
| 618 - 652 | `_calculate_ewm_with_initial(series, alpha, initial_value)` | 半公开私有函数 |
| 1452 - 1504 | `_calculate_delta(df, source_col, target_col, ...)` | 差分通用 helper |

**预计行数**：约 380 - 450 行（含 docstring 与常量定义）。

**依赖**：仅标准库 + `numpy` + `pandas` + `logging`（无内部依赖，是依赖图的根节点）。

**导出契约**：
```python
__all__ = []  # _common 不导出公共 API；通过包级 __init__.py 重导出半公开 helper
```

**注意事项**：
- 原 `factor_calculator.py` 顶部 `__all__` 列表保持不变，只是物理上移到 `__init__.py`
- 所有 `_COL_*` / `_DEFAULT_*` 常量 **必须** 集中在此处，避免子模块各自定义产生不一致
- `get_module_logger` 不以下划线开头（参考原文件惯例），但在 `__all__` 中也未列出，属"约定半公开"

### 5.2 子模块 2：`basic.py`（基础技术指标）

**职责**：经典量化技术指标。这些因子是项目最早建立的一批，使用频率最高。

| 原行号 | 函数 | 输入 | 输出列名 |
|--------|------|------|----------|
| 316 - 383 | `calculate_rsi(close_prices, period=14)` | `pd.Series` | RSI 序列 |
| 385 - 428 | `calculate_volume_ratio(volume, window=5)` | `pd.Series` | 量比序列 |
| 430 - 468 | `calculate_forward_return(close_prices, shift=1)` | `pd.Series` | 前瞻收益序列 |
| 533 - 616 | `calculate_bollinger_pb(factor_df, ...)` | `pd.DataFrame` | `_COL_BOLLINGER_PB` |
| 654 - 751 | `calculate_kdj_j(factor_df, ...)` | `pd.DataFrame` | `_COL_KDJ_J` |
| 753 - 832 | `calculate_turnover_surge(factor_df, ...)` | `pd.DataFrame` | `_COL_TURNOVER_SURGE` |
| 1381 - 1450 | `calculate_rsi_df(factor_df, ...)` | `pd.DataFrame` | RSI 列（按资产分组） |

**预计行数**：约 530 - 600 行（这是子模块中最大的一个）。

**依赖**：
```python
from ._common import (
    _COL_ASSET, _COL_CLOSE, _COL_DATE, _COL_HIGH, _COL_LOW, _COL_TURNOVER_RATE,
    _COL_BOLLINGER_PB, _COL_KDJ_J, _COL_TURNOVER_SURGE,
    _DEFAULT_RSI_PERIOD, _DEFAULT_VOLUME_RATIO_WINDOW, _DEFAULT_FORWARD_RETURN_SHIFT,
    _RSI_NEUTRAL_VALUE, _RSI_MAX_VALUE, _BOLLINGER_NEUTRAL_VALUE, _KD_NEUTRAL_VALUE,
    _EPSILON,
    _wilder_smoothing_rsi, _calculate_ewm_with_initial, _per_asset_transform,
    get_module_logger,
)
```

**注意事项**：
- `calculate_rsi_df` 内部包含闭包 `calc_rsi_for_asset`（codegraph 节点，行 1135），搬运时需保留闭包结构
- `calculate_kdj_j` 调用 `_calculate_ewm_with_initial`，依赖明确

### 5.3 子模块 3：`momentum.py`（价格 / 动量族）

**职责**：基于个股价格序列的动量类因子，不涉及成交量复杂合成。

| 原行号 | 函数 | 公式核心 | 输出列名 |
|--------|------|----------|----------|
| 834 - 894 | `calculate_price_position(factor_df, ...)` | `(close - low) / (high - low)`（全天位置） | `_COL_PRICE_POSITION` |
| 896 - 964 | `calculate_amplitude(factor_df, ...)` | `(high - low) / close` | `_COL_AMPLITUDE` |
| 966 - 1040 | `calculate_past_return_1d(factor_df, ...)` | `close.shift(0) / close.shift(1) - 1`（按资产分组） | `_COL_PAST_RETURN_1D` |
| 1042 - 1116 | `calculate_return_3d(factor_df, ...)` | 3 日累计涨幅（按资产分组） | `_COL_RETURN_3D` |
| 1118 - 1212 | `calculate_return_5d(factor_df, ...)` | 5 日累计涨幅（按资产分组） | `_COL_RETURN_5D` |
| 1214 - 1320 | `calculate_momentum_strength(factor_df, ...)` | `return_5d / std(return_1d, 5d)` | `_COL_MOMENTUM_STRENGTH` |
| 1322 - 1379 | `calculate_overnight_return(factor_df, ...)` | `(open - prev_close) / prev_close` | `_COL_OVERNIGHT_RETURN` |

**预计行数**：约 540 - 600 行。

**依赖**：
```python
from ._common import (
    _COL_ASSET, _COL_CLOSE, _COL_DATE, _COL_HIGH, _COL_LOW, _COL_OPEN,
    _COL_PRICE_POSITION, _COL_AMPLITUDE, _COL_PAST_RETURN_1D,
    _COL_RETURN_3D, _COL_RETURN_5D, _COL_MOMENTUM_STRENGTH, _COL_OVERNIGHT_RETURN,
    _DEFAULT_RETURN_3D_WINDOW, _DEFAULT_RETURN_5D_WINDOW,
    _DEFAULT_MOMENTUM_STRENGTH_WINDOW,
    _DEFAULT_PRICE_POSITION_EPSILON, _DEFAULT_AMPLITUDE_EPSILON,
    _per_asset_transform,
    get_module_logger,
)
```

**注意事项**：
- `momentum_strength` 内部依赖 `return_5d` 与 `past_return_1d` 的 **概念**（公式输入），但 **不依赖** 这两个函数本身（它直接对 close 列做 rolling），故同模块内无函数级互调
- 所有按资产分组的滚动计算 **必须** 通过 `_per_asset_transform` 入口（MODULE.md 约束 #3，行 681）

### 5.4 子模块 4：`delta.py`（止跌信号差分族）

**职责**：v1.13 (2026-06-11) 新增的 4 个差分因子，统一用于"止跌信号"维度。

| 原行号 | 函数 | 源因子 | 输出列名 |
|--------|------|--------|----------|
| 1506 - 1531 | `calculate_amplitude_delta(factor_df, ...)` | `_COL_AMPLITUDE` | `_COL_AMPLITUDE_DELTA` |
| 1533 - 1556 | `calculate_turnover_surge_delta(factor_df, ...)` | `_COL_TURNOVER_SURGE` | `_COL_TURNOVER_SURGE_DELTA` |
| 1558 - 1583 | `calculate_tail_price_position_delta(factor_df, ...)` | `tail_price_position`（外部因子） | `_COL_TAIL_PRICE_POSITION_DELTA` |
| 1585 - 1628 | `calculate_tail_volume_shrink_delta(factor_df, ...)` | `tail_volume_shrink`（外部因子） | `_COL_TAIL_VOLUME_SHRINK_DELTA` |

**预计行数**：约 130 - 160 行（最小子模块）。

**依赖**：
```python
from ._common import (
    _COL_ASSET, _COL_DATE, _COL_AMPLITUDE, _COL_TURNOVER_SURGE,
    _COL_AMPLITUDE_DELTA, _COL_TURNOVER_SURGE_DELTA,
    _COL_TAIL_PRICE_POSITION_DELTA, _COL_TAIL_VOLUME_SHRINK_DELTA,
    _calculate_delta,
    get_module_logger,
)
```

**注意事项**：
- 所有 4 个函数都是 `_calculate_delta` 的薄包装；`_calculate_delta` 仍住 `_common.py`（被多模块复用）
- `tail_price_position` 与 `tail_volume_shrink` 是 `data_fetchers/fetch_tail_trading.py` 的输出列，**不是** `factor_calculator` 的产出；`delta.py` 只读取这些列做差分
- 4 个 delta 因子的方向遵循 PROJECT.md 规则 #5（IC 决定，不预判，对应 H5）

### 5.5 子模块 5：`volume_price.py`（量价合成族）

**职责**：同时使用价格 + 成交量 / 涨跌幅信号的复合因子。

| 原行号 | 函数 | 公式核心 | 输出列名 |
|--------|------|----------|----------|
| 1630 - 1672 | `calculate_volume_price_strength(factor_df, ...)` | 量价配合（成交量与涨跌方向一致性） | `_COL_VOLUME_PRICE_STRENGTH` |
| 1674 - 1722 | `calculate_positive_day_ratio_5(factor_df, ...)` | 5 日内上涨天数比例 | `_COL_POSITIVE_DAY_RATIO_5` |
| 1724 - 1774 | `calculate_ma5_deviation(factor_df, ...)` | `(close - ma5) / ma5` | `_COL_MA5_DEVIATION` |
| 1776 - 1843 | `calculate_near_high_ratio_5(factor_df, ...)` | `close / max(high, 5d)`（5 日新高接近度） | `_COL_NEAR_HIGH_RATIO_5` |

**预计行数**：约 200 - 230 行。

**依赖**：
```python
from ._common import (
    _COL_ASSET, _COL_CLOSE, _COL_DATE, _COL_HIGH, _COL_VOLUME,
    _COL_VOLUME_PRICE_STRENGTH, _COL_POSITIVE_DAY_RATIO_5,
    _COL_MA5_DEVIATION, _COL_NEAR_HIGH_RATIO_5,
    _DEFAULT_POSITIVE_DAY_WINDOW, _DEFAULT_MA5_WINDOW,
    _DEFAULT_NEAR_HIGH_WINDOW,
    _per_asset_transform,
    get_module_logger,
)
```

**注意事项**：
- 这 4 个因子与 `momentum.py` 同属"个股层因子"，但因为 **同时使用 price + volume**（或 5 日窗口聚合）而独立成模，便于未来在此模块下扩展量价合成因子（如 OBV、A/D Line、MFI）
- `positive_day_ratio_5` 与 `near_high_ratio_5` 都使用 5 日窗口；若未来引入更多窗口期（10d、20d），可在同模块下增加变体而不影响其他子模块

### 5.6 子模块 6：`industry.py`（行业聚合，无外部 I/O）

**职责**：基于个股因子向行业层聚合，**仅读取** `factor_df` 内既有列，不加载任何外部 parquet。

| 原行号 | 函数 | 聚合逻辑 | 输出列名 |
|--------|------|----------|----------|
| 1845 - 1886 | `_add_industry_column(factor_df, industry_df, ...)` | 把 industry 列 merge 到主 factor_df | （helper） |
| 1888 - 1969 | `calculate_industry_momentum_5d(factor_df, ...)` | 行业 5 日动量（行业内个股 return_5d 均值） | `_COL_INDUSTRY_MOMENTUM_5D` |
| 1971 - 2042 | `calculate_industry_turnover_trend(factor_df, ...)` | 行业换手率趋势（行业内换手率 5 日斜率） | `_COL_INDUSTRY_TURNOVER_TREND` |
| 2044 - 2134 | `calculate_industry_amplitude_trend(factor_df, ...)` | 行业振幅趋势（行业内振幅 5 日均值变化） | `_COL_INDUSTRY_AMPLITUDE_TREND` |

**预计行数**：约 280 - 320 行。

**依赖**：
```python
from ._common import (
    _COL_ASSET, _COL_DATE, _COL_INDUSTRY,
    _COL_INDUSTRY_MOMENTUM_5D, _COL_INDUSTRY_TURNOVER_TREND,
    _COL_INDUSTRY_AMPLITUDE_TREND,
    _DEFAULT_INDUSTRY_WINDOW,
    get_module_logger,
)
```

**注意事项**：
- 3 个 industry 因子都通过 `_add_industry_column` 把 industry 信息合并到主表后再做 groupby 聚合
- **不依赖** `industry_financial.py`（行业基本面）或 `fund_flow.py`（资金流），是 industry 类因子中最"轻"的一组
- 不读取任何外部 parquet 文件，所有行业元信息由调用方（如 `factor_generator.py`）通过 `industry_df` 参数传入

### 5.7 子模块 7：`industry_financial.py`（行业基本面，含外部 I/O）

**职责**：基于行业层财务数据（ROE / 利润增长 / PE）的因子。**包含 parquet 文件加载逻辑**。

| 原行号 | 函数 | 数据来源 | 输出列名 |
|--------|------|----------|----------|
| 2136 - 2152 | `_get_financial_data_path(logger_arg)` | `paths.py` 解析 financial parquet 路径 | （helper） |
| 2154 - 2203 | `_load_financial_data(path, logger_arg)` | 读取 financial parquet（含 schema 校验） | `pd.DataFrame` |
| 2205 - 2246 | `_merge_asof_financial(factor_df, financial_df, ...)` | 时间对齐 merge（asof） | （helper） |
| 2248 - 2327 | `calculate_industry_roe_trend(factor_df, ...)` | 行业 ROE 趋势（行业内 ROE 中位数 5 日变化） | `_COL_INDUSTRY_ROE_TREND` |
| 2329 - 2398 | `calculate_industry_earnings_growth(factor_df, ...)` | 行业利润同比增速（行业内 EPS 同比中位数） | `_COL_INDUSTRY_EARNINGS_GROWTH` |
| 2400 - 2506 | `calculate_industry_pe_trend(factor_df, ...)` | 行业 PE 趋势（行业内 PE 中位数 5 日变化） | `_COL_INDUSTRY_PE_TREND` |

**预计行数**：约 350 - 400 行。

**依赖**：
```python
from ._common import (
    _COL_ASSET, _COL_DATE, _COL_INDUSTRY,
    _COL_INDUSTRY_ROE_TREND, _COL_INDUSTRY_EARNINGS_GROWTH, _COL_INDUSTRY_PE_TREND,
    _DEFAULT_FINANCIAL_WINDOW,
    get_module_logger,
)
# 注意：本模块还需要 paths.py 提供财务 parquet 路径
from paths import FINANCIAL_DATA_FILE  # 假定常量名（实际以 paths.py 为准）
```

**注意事项**：
- ⚠️ **I/O 边界声明**：本模块 **明确包含 parquet 读取**，与 `_common.py`、`basic.py`、`momentum.py`、`delta.py`、`volume_price.py`、`industry.py` 的"纯计算"语义不同
- 路径必须从 `paths.py` 导入（AGENTS.md 规则 #11，行 64）；禁止字符串字面量
- `_load_financial_data` 含失败重抛 `FileNotFoundError`、schema 校验等防御逻辑，搬运时 **不简化**
- 这是把"行业聚合纯计算"与"行业基本面 I/O"分离的关键意义所在 —— 未来若要 mock financial 数据做测试，只需 mock `_load_financial_data`，而 `industry.py` 完全不受影响

### 5.8 子模块 8：`fund_flow.py`（资金流因子，含外部 I/O）

**职责**：基于主力资金流向数据的因子。**包含 parquet 文件加载逻辑**。

| 原行号 | 函数 | 数据来源 | 输出列名 |
|--------|------|----------|----------|
| 2508 - 2520 | `_get_fund_flow_data_path(logger_arg)` | `paths.py` 解析 fund_flow parquet 路径 | （helper） |
| 2522 - 2577 | `_load_fund_flow_data(path, logger_arg)` | 读取 fund_flow parquet（含 schema 校验） | `pd.DataFrame` |
| 2579 - 2616 | `_merge_fund_flow_daily(factor_df, fund_flow_df, ...)` | 日度对齐 merge | （helper） |
| 2618 - 2696 | `calculate_capital_flow_ratio_trend(factor_df, ...)` | 主力资金净流入占比趋势（5 日均值） | `_COL_CAPITAL_FLOW_RATIO_TREND` |
| 2698 - 2779 | `calculate_capital_flow_intensity(factor_df, ...)` | 主力资金净流入强度（z-score） | `_COL_CAPITAL_FLOW_INTENSITY` |

**预计行数**：约 280 - 320 行。

**依赖**：
```python
from ._common import (
    _COL_ASSET, _COL_DATE,
    _COL_CAPITAL_FLOW_RATIO_TREND, _COL_CAPITAL_FLOW_INTENSITY,
    _DEFAULT_FUND_FLOW_WINDOW,
    get_module_logger,
)
from paths import FUND_FLOW_DATA_FILE  # 假定常量名（实际以 paths.py 为准）
```

**注意事项**：
- ⚠️ **I/O 边界声明**：与 `industry_financial.py` 同属"含 I/O 的因子模块"
- `fund_flow` 数据由 `data_fetchers/fetch_fund_flow.py` 拉取并写入 parquet，本模块仅负责 **读取 + 计算因子**
- 与 `industry_financial.py` 是 **同级关系**（不是父子或包含），二者都依赖 `_common.py`，互不依赖
- 未来若新增"北向资金流因子"，建议在本模块下扩展，或独立建 `northbound_flow.py`（视复杂度而定）

### 5.9 子模块依赖关系图

```
                    ┌──────────────┐
                    │  _common.py  │ ← 依赖图根节点
                    └──────┬───────┘
                           │（被以下所有子模块 import）
        ┌──────┬──────┬────┴────┬──────┬────────────┬──────────────┐
        │      │      │         │      │            │              │
   ┌────▼──┐ ┌─▼────┐ ┌▼─────┐ ┌▼────┐ ┌▼──────────┐ ┌▼─────────────┐ ┌▼──────────┐
   │basic  │ │mome- │ │delta │ │vol_ │ │industry   │ │industry_     │ │fund_flow  │
   │       │ │ntum  │ │      │ │price│ │           │ │financial     │ │           │
   └───────┘ └──────┘ └──────┘ └─────┘ └───────────┘ └──────────────┘ └───────────┘
       (纯计算)                          (纯计算)      (含 parquet I/O)  (含 parquet I/O)

         所有 8 个子模块通过包级 __init__.py 重导出 → 外部 import 路径不变
```

**关键性质**：
- **依赖图为树**（无环）：所有子模块只依赖 `_common.py`，子模块之间不互相 import
- 这保证了 PR 切片可以并行验证（每个子模块独立可测）
- `_common.py` 是唯一的 cross-cutting 节点，搬运它时必须特别小心

## 6. 外部依赖影响面

### 6.1 调用方分类（基于 grep 全量扫描结果）

| 类别 | 文件数 | 典型 import 模式 | 拆分后是否需改动 |
|------|--------|------------------|------------------|
| `backtest/layered_backtest_*.py` | ~25 | `from data_fetchers.factor_calculator import calculate_xxx` | **否** |
| `backtest/test_cases/test_layered_backtest_*.py` | ~15 | 同上 | **否** |
| `factor_ic/ic_*_1d.py` | ~25 | `from data_fetchers.factor_calculator import calculate_xxx  # noqa: E402` | **否** |
| `factor_ic/test_cases/*.py` | ~15 | 同上 | **否** |
| `data_fetchers/factor_generator.py` | 1 文件 / 2 import 点 | 函数内动态 import：`from data_fetchers.factor_calculator import (...)` 与 `from .factor_calculator import (...)` | **否** |
| `data_fetchers/fetch_factor_cache.py` | 1 文件 / 2 import 点 | `try: from data_fetchers.factor_calculator import ... except ImportError: from factor_calculator import ...` | **否**（包替代单文件后两条路径都成立） |
| `data_fetchers/test_cases/test_factor_calculator.py` | 1 | `from data_fetchers.factor_calculator import (...)` | **否** |
| `data_fetchers/test_cases/test_per_asset_transform.py` | 1 | `from data_fetchers.factor_calculator import _per_asset_transform, _calculate_ewm_with_initial` | **否**（半公开 helper 已在 §4.2 重导出） |
| `data_fetchers/test_cases/test_calculate_rsi_df.py` | 1 | `from data_fetchers.factor_calculator import calculate_rsi, calculate_rsi_df` | **否** |
| `factor_definitions.py` | 1 | 仅 docstring 引用，无 import | **否** |

**结论**：在 80+ 个 import 点中，**0 个**需要修改源代码。这是 §3.1 G1 目标的核心保证。

### 6.2 间接引用扫描（非 import 但提到 factor_calculator 的位置）

| 类别 | 位置 | 是否需要更新 |
|------|------|--------------|
| `data_fetchers/MODULE.md` | 行 681-725 引用 `_per_asset_transform`、行 1139 起的版本历史 | **是**（更新版本历史，新增 v2.0 拆分说明，详见 §10） |
| `data_fetchers/docs/factor_calculator_flow.md` | 流程文档 | **是**（同步反映新结构） |
| `data_fetchers/docs/plans/factor_calculator_optimization_plan.md` | 历史优化计划 | **是**（新增"v2.0 拆分"章节，或新建独立 plan） |
| `data_fetchers/data_loader.py` 行 12, 124 | docstring 提及"已迁移到 factor_calculator.py" | **可选**（建议改为"已迁移到 factor_calculator 包"，但不强求） |
| `factor_ic/ic_*_1d.py` 头部 docstring | 多处提及"复用 factor_calculator"（v1.0 注释） | **否**（语义不变） |

### 6.3 风险点扫描

| 风险点 | 现象 | 缓解 |
|--------|------|------|
| **`fetch_factor_cache.py` 的 `from factor_calculator import ...` 兼容路径** | 当 `python factor_calculator.py` 直接执行（非 -m）时走第二条 import | 包化后该路径变为 `import factor_calculator`（一个目录），Python `import` 语义保留兼容；但需在 Execute 阶段 **跑一次 `cd data_fetchers && python -c "from factor_calculator import calculate_rsi"`** 验证 |
| **`__main__` 双重 import 副作用**（MODULE.md 行 77 警告） | `python factor_calculator.py` 会让模块以 `factor_calculator` 与 `data_fetchers.factor_calculator` 两个名字加载两次 | 拆分后 `factor_calculator` 是包，没有 `__main__` 入口，**风险被消除**（这是隐性收益） |
| **私有符号 import（`_per_asset_transform`）** | 测试文件直接 import 私有函数 | §4.2 已显式重导出，覆盖此场景 |
| **静态分析工具（mypy / ruff）误报** | mypy 可能不识别从 `__init__.py` 重导出的函数签名 | 通过 `from .x import name as name` 形式（PEP 484 显式重导出语义），或在 `__all__` 中列出 |

## 7. 兼容性策略（无侵入式拆分）

### 7.1 三大兼容性保证

| 保证 | 机制 | 验证手段 |
|------|------|----------|
| **C1：import 路径完全兼容** | 包名 = 旧文件名（去 `.py`），`__init__.py` 重导出全部公共 + 半公开 API | `pytest data_fetchers/test_cases/ -v` 全绿 |
| **C2：函数签名完全兼容** | 子模块函数定义直接搬运，**不改任何 Args / Returns / 类型注解** | mypy 通过；调用方代码 0 改动 |
| **C3：函数行为完全兼容** | 不重排函数内部逻辑，不改公式、不改边界处理 | 计算结果指纹测试（详见 §9.2） |

### 7.2 包替代文件的 Python 语义

Python 在解析 `from data_fetchers.factor_calculator import calculate_rsi` 时：
1. 找 `data_fetchers/factor_calculator/__init__.py` → 优先匹配（因目录优先于同名文件）
2. 若无目录，再找 `data_fetchers/factor_calculator.py`

**含义**：拆分时只要 **保留旧文件直到包就位**，可做无缝切换。但 PR 切片必须保证：
- ❌ 不能同时存在 `factor_calculator.py` 和 `factor_calculator/` 目录（Python 会优先选目录，旧文件成死代码）
- ✅ 应在最后一个搬运 PR 中 **同步删除旧文件**

### 7.3 半公开 API 的兼容承诺

| 符号 | 类型 | 兼容承诺 |
|------|------|----------|
| `_per_asset_transform` | 函数 | **保留**（MODULE.md 行 690 已文档化为约束 #3 入口） |
| `_calculate_ewm_with_initial` | 函数 | **保留**（被 `test_per_asset_transform.py` 直接 import） |
| `_calculate_delta` | 函数 | **保留**（搬到 `_common.py` 后通过 `__init__.py` 重导出） |
| `_wilder_smoothing_rsi` | 函数 | **保留** |
| `get_module_logger` | 函数 | **保留** |
| `DEFAULT_RSI_PERIOD` 等 9 个 | 常量别名 | **保留**（v1.0 起即在 `__all__`，详见 §4.2.1） |
| `_COL_*`、`_DEFAULT_*`、`_EPSILON` | 常量 | **不重导出**（原文件中也未被外部导入；属严格私有） |

**裁定原则**：grep 命中外部 import = 必须重导出；grep 不命中 = 不重导出。这是基于 **实际使用** 而非主观判断的兼容裁定。

### 7.4 验证脚本（Execute 阶段必跑）

在 Execute 阶段，每个 PR 合并前必须跑：

```bash
# (1) 静态导入验证
python -c "
from data_fetchers.factor_calculator import (
    calculate_rsi, calculate_rsi_df, calculate_volume_ratio,
    calculate_forward_return, calculate_bollinger_pb, calculate_kdj_j,
    calculate_turnover_surge, calculate_amplitude, calculate_price_position,
    calculate_past_return_1d, calculate_return_3d, calculate_return_5d,
    calculate_momentum_strength, calculate_overnight_return,
    calculate_amplitude_delta, calculate_turnover_surge_delta,
    calculate_tail_price_position_delta, calculate_tail_volume_shrink_delta,
    calculate_volume_price_strength, calculate_positive_day_ratio_5,
    calculate_ma5_deviation, calculate_near_high_ratio_5,
    calculate_industry_momentum_5d, calculate_industry_turnover_trend,
    calculate_industry_amplitude_trend,
    calculate_industry_roe_trend, calculate_industry_earnings_growth,
    calculate_industry_pe_trend,
    calculate_capital_flow_ratio_trend, calculate_capital_flow_intensity,
    _per_asset_transform, _calculate_ewm_with_initial, _calculate_delta,
    DEFAULT_RSI_PERIOD, DEFAULT_BOLLINGER_N, DEFAULT_BOLLINGER_K,
    DEFAULT_KDJ_N, DEFAULT_KDJ_M1, DEFAULT_KDJ_M2,
    DEFAULT_SURGE_WINDOW, DEFAULT_VOLUME_RATIO_WINDOW, DEFAULT_FORWARD_RETURN_SHIFT,
)
print('OK: 30 public + 3 semi-public + 9 const aliases importable')
"

# (2) 双路径 import（fetch_factor_cache 兼容）
cd data_fetchers && python -c "from factor_calculator import calculate_rsi; print('cd-style OK')"

# (3) 行为一致性（详见 §9.2）
pytest data_fetchers/test_cases/ -v
pytest factor_ic/test_cases/ -v
pytest backtest/test_cases/ -v
```

## 8. PR 切片计划（Bite-sized Tasks）

按 AGENTS.md 任务粒度约束（≤ 3 文件 ≤ 200 行）+ superpowers-workflow Bite-sized Tasks 原则，把整个拆分切成 **5 个递进式 PR**。每个 PR 独立可测、独立可回滚。

### 8.1 PR 切片总览

| PR | 名称 | 关键产出 | 文件数 | 估计行变更 | 风险 |
|----|------|----------|--------|-----------|------|
| **PR-1** | 创建 `_common.py` + 包骨架 | 抽取常量与底座 helper 到 `_common.py`；新建 `__init__.py`（先做"全量从旧文件转发"） | +3, ±0, -0 | ~500 (新增) | 低 |
| **PR-2** | 搬运 `basic.py` + `momentum.py` | 14 个个股层因子函数搬到子模块，`__init__.py` 切到从子模块 import | +2, ±1 | ~1100 移动，+0 净增 | 中 |
| **PR-3** | 搬运 `delta.py` + `volume_price.py` | 8 个差分/量价因子搬运 | +2, ±1 | ~350 移动 | 低 |
| **PR-4** | 搬运 `industry.py` + `industry_financial.py` + `fund_flow.py` | 11 个行业 / 资金流因子 + 2 个 I/O loader 搬运 | +3, ±1 | ~900 移动 | 中（涉及 I/O 与 paths 引用） |
| **PR-5** | 删除旧 `factor_calculator.py` + 文档同步 | 旧文件下线；`MODULE.md`、`docs/factor_calculator_flow.md` 同步 | -1, ±2 | ~200 文档更新 | 低 |

### 8.2 PR-1 详细分解

**目标**：建立包骨架，让 `data_fetchers/factor_calculator/` 与旧 `factor_calculator.py` 共存（旧文件仍是真实实现，包只是壳）。

**操作**：
1. 创建 `data_fetchers/factor_calculator/__init__.py`（暂时直接 `from data_fetchers.factor_calculator_legacy import *`；或更安全：用条件 sys.path 让 `factor_calculator/` 优先生效）
2. 创建 `data_fetchers/factor_calculator/_common.py` —— 仅放 **常量**（不动函数），让 PR-2/3/4 可以从这里 import
3. 不动旧文件
4. 跑全量 pytest 验证 0 改动

⚠️ **路径冲突风险**：包名与旧单文件同名时，必须二选一。**推荐方案**：在 PR-1 中把旧文件 **直接重命名为 `factor_calculator/_legacy.py`**（一并完成），然后 `__init__.py` 用 `from ._legacy import *` 转发；后续 PR 逐步把符号从 `_legacy.py` 移走，直到 `_legacy.py` 为空再删除。这样：
- 任何时刻 import 路径都成立
- 每个 PR 都独立可测
- 没有"两个版本同时存在"的歧义

**预计变更**：
- 新建：`data_fetchers/factor_calculator/__init__.py`、`data_fetchers/factor_calculator/_common.py`
- 重命名：`data_fetchers/factor_calculator.py` → `data_fetchers/factor_calculator/_legacy.py`
- 改动：`_common.py` 增加全量常量定义；`__init__.py` 写 `from ._legacy import *` + 显式重导出半公开 helper

### 8.3 PR-2 - PR-4 详细分解

每个 PR 走相同模式：
1. 在 `_legacy.py` 中删除目标函数
2. 在新子模块（如 `basic.py`）中重新粘贴该函数 + 补 `from ._common import ...` 头
3. 在 `__init__.py` 中把 `from ._legacy import calculate_rsi` 改为 `from .basic import calculate_rsi`
4. 跑 §7.4 验证脚本 + pytest
5. 跑 §9.2 指纹测试确认行为一致
6. ruff + mypy 通过后 commit

### 8.4 PR-5 详细分解

**目标**：清理 `_legacy.py` 残骸 + 文档同步。

**操作**：
1. 确认 `_legacy.py` 已为空（或只剩注释）
2. 删除 `_legacy.py`
3. 更新 `data_fetchers/MODULE.md`：
   - 在版本历史新增 v2.0 (2026-06-XX) "包化拆分"条目
   - 第 690 行 `from data_fetchers.factor_calculator import _per_asset_transform` 路径无需改
4. 更新 `data_fetchers/docs/factor_calculator_flow.md`：
   - 顶部加"v2.0 包化"说明
   - 章节按子模块重组（可选）
5. 更新 `data_fetchers/data_loader.py` 行 12, 124 docstring（"已迁移到 factor_calculator.py" → "已迁移到 factor_calculator 包"）
6. 全量回归测试
7. commit message 引用 PROJECT.md 规则号 + AGENTS.md 拆分原则

## 9. 测试与验证策略

### 9.1 三层验证矩阵

| 层级 | 测试 | 触发时机 | 通过标准 |
|------|------|----------|----------|
| L1 静态 | `python -c "from data_fetchers.factor_calculator import ..."`（§7.4 (1)） | 每个 PR 提交前 | 30 公共 + 3 半公开符号全部可 import |
| L1' | `cd data_fetchers && python -c "from factor_calculator import calculate_rsi"`（§7.4 (2)） | PR-1, PR-5 | `fetch_factor_cache.py` 双路 import 兼容 |
| L2 单测 | `pytest data_fetchers/test_cases/ -v` | 每个 PR | 通过率与拆分前完全一致 |
| L2' | `pytest factor_ic/test_cases/ -v && pytest backtest/test_cases/ -v` | 每个 PR | 同上 |
| L3 端到端 | 跑一遍完整 pipeline（factor_generator → factor_ic → backtest） | PR-2, PR-4, PR-5 | 输出 JSON 与拆分前 byte-level 一致或 IC 数值差异 < 1e-12 |
| L3' 指纹 | 见 §9.2 | PR-2, PR-3, PR-4 | hash 一致 |
| L4 静态分析 | `ruff check . && ruff format --check . && mypy .` | 每个 PR | 无新增 warning/error |

### 9.2 行为一致性指纹测试（核心防退化机制）

为防止"搬运中无意改了行为"（superpowers-workflow 中常见 pitfall），引入 **指纹测试**：

**步骤**：
1. **拆分前** 跑一次基线生成脚本 `scripts/factor_calculator_baseline_fingerprint.py`：
   ```python
   # 该脚本：
   # 1. 加载小型固定测试数据（如 50 个 asset × 30 日 × 全字段）
   # 2. 对每个 calculate_xxx 函数，调用并取结果 DataFrame
   # 3. 用 pandas.util.hash_pandas_object(df).sum() 生成指纹
   # 4. 写入 designs/factor_calculator_split_baseline_fingerprint.json
   ```
2. **每个搬运 PR** 之后跑一次 `scripts/factor_calculator_verify_fingerprint.py`：
   - 用同样的输入跑一遍当前实现
   - 比对指纹与基线 JSON
   - 任何不一致 → 阻断 PR（说明搬运过程意外改了行为）

**该脚本属于 `temporary/` 还是 `scripts/`？**
- 长期保留：放 `scripts/`（与现有 `scripts/check_*.py` 同级）
- 拆分完成后即可删除：放 `temporary/`（遵循 AGENTS.md 规则 #3）
- **本设计推荐 `temporary/`**：拆分完成、PR-5 合并后，指纹脚本与 baseline JSON 一并删除，避免长期维护负担

### 9.3 性能不退化验证

- 拆分应 **不引入** 任何运行时性能损失（仅 import 时多解析几个文件，开销 < 1ms）
- 不需要专门 benchmark；若 L3 端到端运行时间相对基线波动 > 5%，触发调查

### 9.4 增量回归测试样本

每个 PR 最少跑以下子集（避免每次都跑全量）：

| PR | 必跑子集 | 时间预算 |
|----|----------|----------|
| PR-1 | `pytest data_fetchers/test_cases/test_factor_calculator.py test_per_asset_transform.py test_calculate_rsi_df.py` | < 1 min |
| PR-2 | 上一行 + `factor_ic/test_cases/test_ic_amplitude*.py test_ic_return_*.py test_ic_momentum_strength*.py` | < 3 min |
| PR-3 | 上一行 + `factor_ic/test_cases/test_ic_*_delta_1d.py test_ic_volume_price_strength_1d.py test_ic_ma5_deviation_1d.py` | < 3 min |
| PR-4 | 上一行 + `factor_ic/test_cases/test_ic_industry_*.py test_ic_capital_flow_*.py` | < 5 min |
| PR-5 | **全量** `pytest`（含 backtest、summary） | < 15 min |

### 9.5 失败回滚策略

- 任何 PR 跑挂 → 立即 `git revert`，不在已破环境上调试
- 在 commit 历史中保留独立 PR commit（不 squash），便于精确二分定位

## 10. 文档同步清单

按 AGENTS.md 文档偏好（强烈）+ 用户文档偏好（精度敏感、行号引用），所有改动必须同步以下文档。

### 10.1 必须更新的文档

| 文档 | 章节 | 变更内容 | 触发 PR |
|------|------|----------|---------|
| `data_fetchers/MODULE.md` | 行 1139 起的"factor_calculator.py 版本" | 新增 v2.0 (2026-06-XX) "包化拆分"条目，列 8 个子模块名 | PR-5 |
| `data_fetchers/MODULE.md` | 行 681-725 约束 #3 | 把 "factor_calculator.py" 表述改为 "factor_calculator 包"；保留 `_per_asset_transform` 重导出契约说明 | PR-5 |
| `data_fetchers/docs/factor_calculator_flow.md` | 顶部 | 加 v2.0 说明 + 新结构链接 | PR-5 |
| `data_fetchers/docs/factor_calculator_flow.md` | 主体（按需） | 流程图按子模块重组（可选；初期可保留旧结构 + 顶部声明） | PR-5（可选） |
| `data_fetchers/docs/plans/factor_calculator_optimization_plan.md` | 末尾 | 加 v2.0 拆分计划摘要（链接到本 design.md） | PR-5 |
| `designs/factor_calculator_split_design.md` | 版本历史表 | 更新 v0.1 → v1.0（审核通过后） | 审核通过时 |

### 10.2 可选/可不更新的文档

| 文档 | 行 | 状态 | 理由 |
|------|----|------|------|
| `data_fetchers/data_loader.py` 行 12, 124 | docstring | **建议更新** | 措辞精度："已迁移到 factor_calculator.py" → "已迁移到 factor_calculator 包" |
| `factor_ic/ic_*_1d.py` 头部 docstring | 多处提及"复用 factor_calculator" | **不更新** | 表述不区分文件/包，语义不变 |
| `backtest/layered_backtest_*.py` 头部 docstring | 同上 | **不更新** | 同上 |

### 10.3 文档结构归类（用户偏好）

按用户文档偏好（"文档必须按主题章节归类"）：
- **包级 README（可选新建）**：`data_fetchers/factor_calculator/README.md` 列出 8 个子模块的职责，作为开发者落地指南。**本设计建议第二阶段添加**，初期不强求。
- **子模块 docstring**：每个 `.py` 文件顶部用 ≤ 5 行 docstring 说明该模块定位（如 "basic.py: 经典量化技术指标，无外部 I/O"），便于 IDE 悬停查看。

### 10.4 Skills 同步

按 AGENTS.md / 已加载 superpowers-workflow skill 的"After difficult/iterative tasks, offer to save as a skill" 要求：
- 拆分完成后，**评估是否更新** `factor-development` skill 中关于 "因子写在哪里" 的指引：从 "写到 factor_calculator.py" → "按因子类型写到对应子模块（basic / momentum / delta / volume_price / industry / industry_financial / fund_flow）"
- 若更新，遵循 memory 中"superpowers-workflow SKILL.md 已达 100KB 上限"约束 → 写入 `references/factor-calculator-package-layout.md`

## 11. 风险与回滚预案

### 11.1 风险矩阵

| 风险 | 概率 | 影响 | 等级 | 缓解 |
|------|------|------|------|------|
| **R1：__init__.py 遗漏某个公共函数** | 中 | 高（80+ 调用方挂掉） | **高** | §7.4 (1) 静态 import 验证脚本（30+3 符号全列），每 PR 跑 |
| **R2：搬运过程改了内部行为** | 低 | 高（IC 数值漂移，不易发现） | **高** | §9.2 指纹测试（基于 hash），任何不一致阻断 PR |
| **R3：包名冲突（_legacy.py 时段）** | 高 | 中 | **中** | §8.2 推荐方案（包内 `_legacy.py` + 重导出），从 PR-1 开始保持单一来源 |
| **R4：循环导入** | 低 | 高 | **中** | §5.9 依赖图为树，子模块只 import `_common`，结构上杜绝循环；mypy / Python import 系统会即时报错 |
| **R5：`_per_asset_transform` 重导出失败导致 MODULE.md 行 690 文档化路径失效** | 低 | 中 | **中** | §4.2 显式重导出 + §7.3 兼容承诺表；每 PR 跑 `pytest test_per_asset_transform.py` |
| **R6：mypy 不识别从 `__init__.py` 重导出的类型** | 中 | 低 | 低 | 用 `from .x import name as name`（PEP 484 显式语义）或在 `__all__` 中列出 |
| **R7：ruff F401 误报** | 中 | 低 | 低 | `__all__` 包含 → 自动豁免；半公开 helper 用 `# noqa: F401` |
| **R8：拆分进行中新因子 PR 撞上** | 低 | 中 | 低 | 在 PR-1 前 freeze 1 - 2 天的因子开发；或并行 PR 在 review 时手动 rebase |
| **R9：性能退化** | 极低 | 低 | 低 | §9.3 端到端时间监控；初次启动 import 多花 < 10ms，业务运行无影响 |
| **R10：Code review 看不懂跨 PR 上下文** | 中 | 低 | 低 | 每个 PR commit message 引用本 design.md 章节 + AGENTS.md 规则号（取证） |

### 11.2 回滚预案（按 PR 颗粒）

每个 PR 都设计为 **独立可回滚**。回滚策略：

| 失败场景 | 回滚动作 | 状态恢复 |
|----------|----------|----------|
| PR-1 跑挂 | `git revert HEAD` | 回到无包结构的原状 |
| PR-2 跑挂 | `git revert HEAD` | 包骨架仍在，被 revert 的因子函数回到 `_legacy.py` |
| PR-3 跑挂 | 同上 | basic + momentum 已在子模块；delta + volume_price 回到 `_legacy.py` |
| PR-4 跑挂 | 同上 | 7 个子模块在位；行业/资金流回到 `_legacy.py` |
| PR-5 跑挂 | `git revert HEAD` | `_legacy.py` 复活，文档回旧版；注意 5 不影响功能（仅清理） |

**关键约束**：
- 每个 PR 必须独立 commit，**禁止 squash**（与 superpowers-workflow L553 约束一致：commit 但不 push）
- commit message 必须包含 `Refs: designs/factor_calculator_split_design.md §X.Y` 取证

### 11.3 失败模式与逃生通道

**最坏情况**：拆分进行到 PR-3，发现某个因子的指纹漂移，定位到 `_per_asset_transform` 在新位置的执行顺序与旧位置略有差异（极低概率，但需有应对）。

**逃生通道**：
1. 立即 revert 对应 PR
2. 在 design.md 中记录该 pitfall（通过 patch 增加 §11.4）
3. 评估是否需调整方案：是否要把 `_per_asset_transform` 留在原位、子模块 `from data_fetchers.factor_calculator._legacy import _per_asset_transform`？
4. 如调整方案，重新提交 design.md v1.1 走审核

**底线兜底**：本拆分是 **结构性重构**，不解决业务问题。任何阶段觉得 ROI 不划算 → 全量 revert，回到单文件，**不损失任何业务能力**。这是该拆分的核心安全保证。

## 12. 规范引用与取证

按 AGENTS.md "规范引用取证（弱模型防御）"要求，本设计与所有后续 PR commit 必须引用具体规范行号，便于审核者快速核对。

### 12.1 本设计遵循的规范

| 规范 | 行号 | 引用内容 | 本设计如何遵循 |
|------|------|----------|----------------|
| `AGENTS.md` | 全文 §0 开发流程表 | "涉及 2+ 文件先提交 design.md" | **本文件即 design.md**，提交审核后才进入 Execute |
| `AGENTS.md` | 行 64（规则 #11） | 路径必须从 `paths.py` 导入 | §5.7 / §5.8 子模块的 financial / fund_flow 路径明确从 `paths.py` 导入 |
| `AGENTS.md` | 行 67-68（规则 #12） | Design-First：2+ 文件先提交 design.md | §3.1 G1-G7 即为 design 验收标准；§13 Checklist 走审核 |
| `AGENTS.md` | §3 陷阱 1 | 路径迁移必须验证新文件 + 同步代码 + 同步文档 | §10 文档同步 + §9 三层验证 |
| `AGENTS.md` | §4 任务粒度约束 | ≤3 文件 ≤200 行 | §8 切成 5 个 PR，每个 PR ≤ 4 文件（PR-4 最大），变更线性可控 |
| `AGENTS.md` | §5 任务后必做 | ruff + mypy + pytest + JSON Schema + 行号引用 + commit | §11.2 强制独立 commit + Refs 标注；§9.1 L4 静态分析 |
| `data_fetchers/MODULE.md` | 行 681-725 约束 #3 | `_per_asset_transform` 是规范化入口 | §4.2 + §7.3 显式重导出该 helper；§5.1 把它放在 `_common.py` |
| `data_fetchers/MODULE.md` | 行 690 | 明确 import 路径 `data_fetchers.factor_calculator._per_asset_transform` | §7.3 兼容承诺；§9.4 PR-1 必跑 `test_per_asset_transform.py` |
| `data_fetchers/MODULE.md` | 行 919 模块边界规范 | 模块边界不被拆分破坏 | §1.3 拆分发生在 `data_fetchers/` 模块内部，不跨模块 |
| `PROJECT.md` | 规则 #5 | 因子方向由 IC 决定 | §3.2 N2 明确不调整因子方向 |
| `PROJECT.md` | Design-First 流程 | 同 AGENTS.md | 同上 |
| `superpowers-workflow` skill | "Bite-sized Tasks（2-5 分钟）" | 任务粒度 | §8.1 PR 切片（每个 PR 是一个 bite） |
| `superpowers-workflow` skill | "Two-stage Review" | Spec Compliance + Code Quality | §13 Checklist 双阶段审核 |
| `superpowers-workflow` skill | L562 / L1219 / L553 | 写完即 commit、commit 但不 push | §11.2 强制约束 |

### 12.2 提交消息模板

每个 PR 的 commit message 必须按此模板写：

```
factor_calculator: [PR-N 名称]

变更：
- [本 PR 的具体动作 1]
- [本 PR 的具体动作 2]
- [...]

验证：
- L1 静态 import: PASS (30+3 symbols)
- L1' cd-style import: PASS
- L2 unit test: pytest data_fetchers/test_cases/  PASS (X tests)
- L3' fingerprint: hash match (基线 vs PR-N)
- L4 ruff/mypy: clean

Refs:
- designs/factor_calculator_split_design.md §[X.Y]
- AGENTS.md 规则 #12（Design-First, 行 67-68）
- data_fetchers/MODULE.md 约束 #3（行 681-725）
- superpowers-workflow §PHASE 2 Bite-sized Tasks
```

### 12.3 review 时的快速核对清单

审核者只需做 3 件事：
1. 在本 PR diff 中找 commit message 的 Refs 行号
2. 用 `read_file path:designs/factor_calculator_split_design.md offset:<行号>` 跳到对应章节核对
3. 跑一次 §7.4 验证脚本 + §9.4 该 PR 必跑测试子集

## 13. 审核 Checklist

请在审核本 design.md 时逐项打勾。任何一项 ✗ 都阻塞 Execute 阶段。

### 13.1 Spec Compliance（规范合规）

- [ ] 本 design.md 路径正确（`designs/factor_calculator_split_design.md`），与项目其他 design 同目录
- [ ] §12.1 规范引用表覆盖了 AGENTS.md / PROJECT.md / MODULE.md / superpowers-workflow 四个层级
- [ ] §3.1 拆分目标 G1-G7 全部可量化、有验收标准
- [ ] §3.2 非目标 N1-N8 明确划界，不偷偷夹带计算逻辑变更
- [ ] §5 子模块清单覆盖原文件全部 41 个函数（无遗漏、无重复）
- [ ] §6.1 列出全部 80+ import 点，每个的兼容裁定都有依据
- [ ] §7.3 半公开 API 重导出表与 §6.1 / §6.2 grep 结果一致
- [ ] §4.2.1 公共常量别名兼容契约 9 项全部覆盖；§4.2 import 块、`__all__` 列表、§7.3 表格、§7.4 验证脚本四处一致

### 13.2 Code Quality（代码质量）

- [ ] §4.1 包目录结构与 §5 子模块清单一致（命名、放置一致）
- [ ] §4.2 `__init__.py` 重导出代码可直接复制即可工作（语法正确）
- [ ] §5.9 依赖图为 DAG（无环），且只有 `_common` 是 cross-cutting 节点
- [ ] §7.2 包替代单文件的 Python 语义解释正确
- [ ] §8 PR 切片每个都是独立可测、独立可回滚
- [ ] §9.2 指纹测试设计能真正捕获行为漂移
- [ ] §11.2 回滚预案对每个 PR 都覆盖

### 13.3 风险评估

- [ ] §11.1 风险矩阵中所有"高"风险都有对应缓解
- [ ] §11.3 逃生通道明确（最坏情况下能完整回滚到单文件）
- [ ] 没有"必须一次性完成"的步骤（所有变更可分阶段验证）

### 13.4 用户偏好对齐（来自 USER PROFILE）

- [ ] **方法论严谨性**：所有阈值/数字都有依据（无"估计"、"大概"未带来源）
- [ ] **数据一致性**：design 内部前后陈述一致（如行数估算、PR 数量等）
- [ ] **文档精度**：行号引用准确，无 markdown 语法错误（无 `||`、`.pyproject.toml` 类问题）
- [ ] **结构归类**：13 章节按"为什么 → 怎么做 → 风险/回滚"递进
- [ ] **稳定性标签**：本 design 整体处于 [experimental] 阶段，审核通过后升 [stable]

### 13.5 审核结论

```
□ APPROVED — 进入 Execute 阶段（PR-1 起步）
□ APPROVED with changes — 修订点：________
□ REJECTED — 主要问题：________
```

审核人：________
审核时间：________

---

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v0.1-skeleton | 2026-06-15 | 初始骨架（章节占位，待逐章 patch） |
| v0.2 | 2026-06-15 | §1 背景动机 + §2 现状量化体检 |
| v0.3 | 2026-06-15 | §3 拆分目标与非目标（G1-G7 / N1-N8） |
| v0.4 | 2026-06-15 | §4 拆分方案（包目录 + `__init__.py` 重导出策略） |
| v0.5 | 2026-06-15 | §5 子模块函数清单（8 个子模块 + 依赖图） |
| v0.6 | 2026-06-15 | §6 外部依赖影响面（80+ import 点 + 风险扫描） |
| v0.7 | 2026-06-15 | §7 兼容性策略（C1-C3 + 验证脚本） |
| v0.8 | 2026-06-15 | §8 PR 切片计划（5 个递进式 PR） |
| v0.9 | 2026-06-15 | §9 测试与验证（三层矩阵 + 指纹测试） |
| v0.10 | 2026-06-15 | §10 文档同步清单 |
| v0.11 | 2026-06-15 | §11 风险与回滚（10 风险点 + 逃生通道） |
| v0.12 | 2026-06-15 | §12 规范引用（取证表 + 提交消息模板） |
| v1.0-draft | 2026-06-15 | §13 审核 Checklist 完成；提交审核 |
| **v1.0-approved** | **2026-06-15** | **审核通过 ✅；触发 Execute 阶段 PR-1** |
| v1.1 | 2026-06-15 | PR-1 校准：补 §4.2 / §4.2.1 / §7.3 / §7.4 / §13.1 共 9 个公共常量别名兼容契约 |

> 审核状态：APPROVED（用户于 2026-06-15 确认）。Execute 阶段从 PR-1 起步。
