# Design: composite_runner 消除重复数据加载

> 遵循 PROJECT.md Design-First 规则（涉及 2+ 文件改动）
> 创建时间: 2026-06-09

## 问题

`run_composite_backtest` 三次加载同一 216MB gzip JSON 文件（`factor_ic_data.json.gz`），每次解析耗时 ~22s：

| 调用点 | 行号 | 函数 | 用途 |
|--------|------|------|------|
| Step 2（自动筛选） | 231 | `load_factor_values` | 计算全量因子相关性矩阵 |
| Step 1（正式加载） | 303 | `load_factor_values` | 加载筛选后因子值做标准化+加权 |
| Step 8（回测） | 498 | `load_factor_return_data` | 分离 return_df 传入回测引擎 |

三次加载总耗时 ~66s，加上 run_pipeline 重试 3 次 → **198s 纯 I/O 空耗**。
这是 4 个综合因子步骤全部超时失败（重试3次耗尽）的根因。

## 根因

三个函数各自独立读取 gzip → JSON → DataFrame，没有数据共享机制：
- `load_factor_values`（factor_loader.py）只返回因子列子集
- `load_factor_return_data`（layered_backtest_runner.py）分离 return_df
- 两者都从同一文件读取，但互不知道对方已经加载过

## 修复方案

**核心思路：一次加载，三个用途共享。**

在 `run_composite_backtest` 入口处一次性加载全量数据（full_df），后续三个步骤从中提取所需子集，不再独立调用文件 I/O。

### 改动清单（≤3 文件）

| 文件 | 改动 | 行数估计 |
|------|------|----------|
| `comprehensive_factor/common/composite_runner.py` | 主改动：重构 run_composite_backtest 数据加载流程 | ~80 行 |
| `comprehensive_factor/common/factor_loader.py` | 新增 `load_full_data()` 函数，一次加载返回完整 DataFrame | ~30 行 |
| `comprehensive_factor/MODULE.md` | 版本历史记录 | ~5 行 |

**不改动** `backtest/common/layered_backtest_runner.py`（跨模块边界，只复用自己目录的 common/，遵循 AGENTS.md 规则 #1）。

### 详细设计

#### 1. factor_loader.py：新增 `load_full_data()`

```python
def load_full_data(
    data_source: str | Path | None = None,
    logger: logging.Logger | None = None,
) -> pd.DataFrame:
    """一次加载统一数据源，返回完整 DataFrame（所有列）
    
    用于 composite_runner 入口处一次性加载，后续步骤从中提取子集。
    """
    # 与 load_factor_values 相同的文件读取逻辑
    # 但返回 full_df（不筛选列、不释放 data）
    # 校验 date/asset 类型
    # 返回完整 DataFrame
```

#### 2. composite_runner.py：重构 run_composite_backtest

```
原流程:
  Step 2: load_factor_values(all_cols)  → all_factor_df（筛选用）
  Step 1: load_factor_values(selected)  → factor_df（加权用）
  Step 8: load_factor_return_data()     → return_df（回测用）

新流程:
  入口: load_full_data()                → full_df（一次加载）
  Step 2: full_df[all_cols]             → all_factor_df（筛选用，0 I/O）
  Step 1: full_df[selected_cols + date/asset] → factor_df（加权用，0 I/O）
  Step 8: full_df[return_cols]          → return_df（回测用，0 I/O）
```

关键改动点：
- 第 231 行：`load_factor_values` → 从 full_df 提取子集
- 第 303 行：`load_factor_values` → 从 full_df 提取子集
- 第 498 行：`load_factor_return_data` → 从 full_df 提取子集

**内存安全**：full_df ~1.49M 行 × ~30 列 ≈ 400MB，进程有足够内存。
完成后显式 `del full_df` 释放。

#### 3. MODULE.md：版本历史

新增 v2.10 版本记录：消除重复数据加载，一次加载三用途共享。

## 不做的事（Don't）

- ❌ 不改 `backtest/common/layered_backtest_runner.py`（跨模块边界，规则 #1）
- ❌ 不改 `load_factor_return_data` 的调用签名（保持向后兼容）
- ❌ 不在 `load_factor_values` 加缓存（简单子集提取即可，不需要复杂缓存机制）
- ❌ 不改 run_pipeline 的重试机制（根因是数据加载，不是重试逻辑）

## 验证方法

1. `ruff check --fix .` + `ruff format .`
2. `pytest comprehensive_factor/test_cases/` — 确保无回归
3. 手动验证：`python comprehensive_factor/composite_equal_weight_1d.py --auto_select` 执行时间应从 ~3min 降到 ~1min
4. Spec Compliance：对照 MODULE.md M21（数据来源单一数据源）、M47（Config 默认值单一数据源）