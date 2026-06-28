# Design: ob_pool 二次排序（换手率 + 市值）

## What

对 ob_pool (RSI>70) 选出的所有股票（非 Top30），基于 **换手率 + 市值** 做二次排序，全部输出。

## Why

跨 4 个 pipeline（840 只股票）的实证分析发现：
- **换手率** p=0.008（稳定上涨组 8.78% vs 下跌组 5.18%）
- **市值** p≈0.05（上涨组中位 197 亿 vs 下跌组 85 亿）
- 100 亿以下超买股更易下跌，100-500 亿中盘股表现最好

composite 因子的 6 个组成因子中只有 1 个显著（tail_price_slope p=0.004），且方向是"下跌股更高"。换手率和市值不在 composite 组成因子里，是全新的二次排序维度。

## How

### 改动范围

1. **`stock_selector/stock_selector.py`** — `sort_and_select` 函数新增 ob_pool 二次排序
2. **`stock_selector/stock_selector_config.py`** — 新增配置开关
3. **`summary/report/sections.py`** — 报告展示二次排序结果

### 实现方案

#### 1. StockSelectorConfig 新增配置

```python
# v3.15: ob_pool 二次排序（换手率 + 市值）
enable_secondary_sort: bool = True
secondary_sort_factors: tuple[str, ...] = ("turnover_rate", "total_market_cap")
secondary_sort_weights: tuple[float, ...] = (0.6, 0.4)  # 换手率权重更高
```

#### 2. sort_and_select 新增二次排序逻辑

在 composite 排序后、取 Top N 前，对 **ob_pool（股票池 ≤400 只）** 的全部股票做二次排序：

```python
# v3.15: ob_pool 二次排序（仅对股票池 ≤400 只的 pipeline 生效）
if config.enable_secondary_sort and len(sorted_df) <= 400:
    sorted_df = _apply_secondary_sort(sorted_df, config, factor_df)
```

`_apply_secondary_sort` 逻辑：
1. 从 `market_cap_data.json.gz` 加载选股日市值数据
2. 合并 `turnover_rate`（已在 factor_df 中）和 `total_market_cap`
3. 两个因子分别做截面 z-score 标准化
4. 加权求和得到 `secondary_score`
5. 最终排序键 = `composite_factor` × 0.5 + `secondary_score` × 0.5（保留 composite 信号）
6. 按 final_score 降序排列

#### 3. 报告展示

报告在全量展示区之后，新增"二次排序结果"区块，输出全部股票的二次排名。

## Don't

- ❌ 不要只对 Top30 做二次排序——用户明确要求对 ob_pool 所有股做
- ❌ 不要用硬编码阈值（如"市值<100亿排除"）——用 z-score 标准化
- ❌ 不要对全市场 pipeline（5000+ 只）启用——只对 ≤400 只的 ob_pool 生效
- ❌ 不要完全替换 composite 排序——二次排序是 composite 基础上的调整

## When

仅当 `enable_secondary_sort=True` 且股票池 ≤400 只时启用。

## Verify

```bash
pytest stock_selector/test_cases/ -q
ruff check stock_selector/ summary/report/
```
