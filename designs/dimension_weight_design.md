# 维度级别权重分配机制设计

> 日期: 2026-06-20
> 状态: 待审核
> 涉及文件: weight_engine.py, composite_runner.py, MODULE.md, test_dimension_weight.py

## 1. 问题

当前 rolling ICIR 加权按 `|ICIR_i| / Σ_all |ICIR_j|` 分配权重，不考虑维度。导致：

| 维度 | 因子数 | 当前权重 | 模拟维度等权 |
|------|--------|---------|------------|
| price_position | 4 | 51.5% | 25.0% |
| tail_behavior | 2 | 29.5% | 25.0% |
| volume | 2 | 9.6% | 25.0% |
| momentum | 2 | 9.4% | 25.0% |

tail_price_position 单因子 |ICIR|=0.787 远高于其他因子，使 price_position 维度主导选股，选出持续下跌的股票。

## 2. 方案

### 方案 A：维度等权（Dimension Equal Weight, DEW）

**逻辑**：每个维度等权重 1/n_dims，维度内因子按 |ICIR| 分配。

```
weight_i = (1/n_dims) × (|ICIR_i| / Σ_same_dim |ICIR_j|)
```

**优点**：简单直接，强制维度平衡
**缺点**：可能过度惩罚高质量维度（price_position 的 |ICIR| 普遍更高是数据事实）

### 方案 B：维度 ICIR 加权（Dimension ICIR Weight, DIW）—— 推荐

**逻辑**：维度权重 = 维度内因子平均 |ICIR| 归一化，维度内因子按 |ICIR| 分配。

```
dim_weight_d = avg_|ICIR|_d / Σ_dim avg_|ICIR|
weight_i = dim_weight_d × (|ICIR_i| / Σ_same_dim |ICIR_j|)
```

模拟分布：

| 维度 | 当前权重 | 方案 A | 方案 B |
|------|---------|--------|--------|
| momentum | 9.4% | 25.0% | 21.6% |
| price_position | 51.5% | 25.0% | 30.4% |
| tail_behavior | 29.5% | 25.0% | 29.5% |
| volume | 9.6% | 25.0% | 18.5% |

**优点**：兼顾维度平衡和维度质量——高 ICIR 维度仍有适度超配，但不会主导
**缺点**：计算略复杂

### 决策

| 方案 | 来源 | 理由 |
|------|------|------|
| 方案 B（推荐） | 业界 AQR/MSCI 风险预算实践 | 既平衡维度又尊重因子质量；Asness et al. 2013 表明多因子组合中各因子应大致等贡献 |
| 方案 A（备选） | 简单等权 | 作为 `--dimension_weight equal` 选项保留 |

两种方案均通过 CLI 参数 `--dimension_weight` 控制：
- `none`（默认）：不启用维度权重（当前行为，向后兼容）
- `equal`：方案 A
- `icir`：方案 B

## 3. 改动范围

### 3.1 weight_engine.py（核心改动）

**WeightEngine.__init__**：新增 `dimension_weight_method` 和 `factor_categories` 参数

**WeightEngine.calculate**：透传 `factor_categories` 到 method.calculate()

**RollingICIRWeightMethod**：
- `__init__`：新增 `dimension_weight_method` 和 `factor_categories` 参数
- `calculate()`：在权重计算阶段（L570-597），将单阶段归一化改为两阶段：
  1. 维度内归一化：`|ICIR_i| / Σ_same_dim |ICIR|`
  2. 维度间归一化：乘以维度权重（equal=1/n_dims, icir=dim_avg_icir/Σ）
- `_last_day_weights` 提取逻辑同步更新

**ICIRWeightMethod**（静态权重）：
- `get_weights()`：同步支持 `dimension_weight_method`
- `calculate()`：调用 `get_weights()` 获取维度感知权重后加权

### 3.2 composite_runner.py（传参改动）

- `run_composite_backtest()`：新增 `dimension_weight_method` 参数
- CLI 入口：新增 `--dimension_weight` 参数
- 将 `FACTOR_CATEGORIES` 传递给 WeightEngine

### 3.3 测试 test_dimension_weight.py（新建）

- 维度等权：4 维度各 25%
- 维度 ICIR 加权：高 ICIR 维度适度超配
- 无分类时退化为当前行为（向后兼容）
- dimension_weight_method=None 时行为不变
- 滚动 ICIR 动态权重中的维度感知

### 3.4 MODULE.md

- 新增 M58 规则（维度级别权重分配）
- 更新流程图（Step 6 加权增加维度感知分支）

## 4. 实现细节

### 4.1 两阶段权重计算伪代码

```python
# 当前（单阶段）：
weight_i = |rolling_icir_i| / Σ_all |rolling_icir_j|

# 方案 A/B（两阶段）：
# 第一阶段：维度内归一化
for dim, dim_cols in dimension_groups.items():
    dim_icir_sum = Σ |rolling_icir_j| for j in dim_cols
    for col in dim_cols:
        intra_weight[col] = |rolling_icir[col]| / dim_icir_sum

# 第二阶段：维度间归一化
if method == "equal":
    dim_weight = 1.0 / n_dims  # 每维度等权
elif method == "icir":
    # 维度权重 = 维度内平均|ICIR| 归一化
    dim_avg_icir = dim_icir_sum / len(dim_cols)
    dim_weight = dim_avg_icir / Σ_dim dim_avg_icir

for col in factor_cols:
    weight[col] = dim_weight[col_dim] * intra_weight[col]
```

### 4.2 滚动 ICIR 的特殊性

滚动 ICIR 权重是**每日动态**的，上述两阶段计算需要在**每个日期**上执行：
- `factor_df["weight_sum"]` 改为按维度分组计算
- `weight` 列需要乘以维度权重系数

### 4.3 向后兼容

- `dimension_weight_method=None`（默认）→ 当前行为
- `factor_categories=None` → 当前行为（退化为单阶段）
- CLI 不传 `--dimension_weight` → `none`（默认）

## 5. 验证

```bash
# ruff
ruff check --fix . && ruff format . && ruff check .

# pytest
pytest comprehensive_factor/test_cases/test_dimension_weight.py -v
pytest comprehensive_factor/test_cases/ -v --ignore=test_weight_selector.py

# 验证维度权重分布
python3 -c "
import json
from factor_definitions import FACTOR_CATEGORIES
with open('comprehensive_factor/result/composite_rolling_icir_weight_1d.json') as f:
    comp = json.load(f)
weights = comp['meta']['weight_meta']['last_day_weights']
# 检查各维度权重分布
"
```
