# 因子分类功能设计文档

> 创建: 2026-06-20
> 状态: 待审核
> 关联: 2026-06-20 因子多样性讨论

## 1. 背景与问题

### 1.1 问题描述

`select_factors` 的当前流程：

```
load_all → filter_invalid (M12) → identify_high_corr_groups (Union-Find, >0.7) → select_best_from_groups (保留 |ICIR| 最高)
```

**结构性盲区**：只看两两相关性去重，不考虑经济维度覆盖。当高相关组内一个非目标维度的因子 ICIR 最高时，整个维度被"代表"后消失。

**实际案例**（2026-06-20 排除涨停股后）：
- 动量组 7 个因子（momentum_strength, rsi, return_5d 等）与 bollinger_pb 相关 >0.7
- bollinger_pb ICIR=0.3384 最高，胜出
- 但 bollinger_pb 是均值回归因子，不是动量因子
- 结果：动量维度 7 个因子全部被淘汰，9 个选中因子全是价格位置类
- 新 Top 10 中 7/10 近 5 日下跌

### 1.2 业界做法

业界共识：混合多层方案——经济维度分类 → 维度内去重 → 跨维度配额 → 权重分配。

### 1.3 当前因子列表（34 个）

| 维度 | 因子 | 数量 |
|------|------|------|
| 动量/趋势 | momentum_strength, return_3d, return_5d, rsi, kdj_j, ma5_deviation, near_high_ratio_5, past_return_1d, positive_day_ratio_5 | 9 |
| 价格位置 | price_position, bollinger_pb, tail_price_position, tail_price_position_delta | 4 |
| 量能 | volume_ratio, turnover_surge, turnover_surge_delta, volume_price_strength, intraday_intensity | 5 |
| 尾盘行为 | tail_price_slope, tail_price_volume_intensity, tail_volume_acceleration, tail_volume_shrink, tail_volume_shrink_delta | 5 |
| 波动率 | amplitude, amplitude_delta | 2 |
| 隔夜跳空 | overnight_ret | 1 |
| 资金流 | capital_flow_ratio_trend, capital_flow_intensity | 2 |
| 行业 | industry_momentum_5d, industry_turnover_trend, industry_amplitude_trend, industry_roe_trend, industry_earnings_growth, industry_pe_trend | 6 |

---

## 2. 方案设计

### 方案 B（已选定）：维度内去重 + 跨维度保留

**核心原则**：高相关去重只在同一经济维度内进行，不同维度的因子即使统计相关性 >0.7 也不互相淘汰。跨维度仅对极端高相关（>0.9）做去重兜底。

**业界依据**：AQR/MSCI 的"两阶段筛选"——维度内去重 → 跨维度组合。经济含义不同的因子即使统计相关也应保留（Asness et al. 2013：价值与动量负相关 -0.4~-0.7，组合后 Sharpe 更高）。

**改动范围**：3 文件，~165 行

**改动点**：
1. `factor_definitions.py`：新增 `FACTOR_CATEGORIES` 字典（因子名 → 维度名）+ `CATEGORY_DIMENSIONS` 常量（8 个维度列表）
2. `factor_selector.py`：
   - `identify_high_corr_groups`：增加维度约束——只合并同维度高相关因子对；跨维度因子对仅当 |corr| > 0.9 时才合并
   - `select_factors`：传入维度信息，新增 `cross_dimension_corr_threshold` 阈值
   - `DEFAULT_THRESHOLDS`：新增 `cross_dimension_corr_threshold: 0.9`
3. `MODULE.md`：新增 M17 规则（因子维度分类与维度内去重）

**不做**：不修改 `select_best_from_groups`，不新增 rescue 函数，不修改 composite_runner/weight_selector/stock_selector。

**数据流**：
```
select_factors 流程（修改后）:
  Step 1: load_all_factor_results          ← 不变
  Step 2: filter_invalid_factors           ← 不变 (M12)
  Step 3: identify_high_corr_groups        ← 修改：维度感知
    ├─ 同维度因子对, |corr|>0.7 → 合并到高相关组（维度内去重）
    ├─ 跨维度因子对, |corr|>0.9 → 合并到高相关组（极端高相关兜底）
    └─ 跨维度因子对, 0.7<|corr|≤0.9 → 不合并（跨维度保留）
  Step 4: select_best_from_groups          ← 不变 (M14)
  Step 5: 输出                             ← 新增 dimension_coverage 字段
```

**为什么不在 select_best_from_groups 中做维度感知**：
- `select_best_from_groups` 的输入是已分好的高相关组，到这一步时跨维度的因子已经被分到同一组了
- 如果在这一步做"维度感知选择"，需要跨组协调（组 A 的胜出者维度影响组 B 的选择），引入复杂依赖
- 从源头（identify_high_corr_groups）控制哪些因子被合并，逻辑更简单、更正确

**优点**：
- 无矛盾：不会"先淘汰再救援"
- 改动集中：主要改 `identify_high_corr_groups`，`select_best_from_groups` 完全不变
- 向后兼容：返回结构向后兼容，新增 `dimension_coverage` 字段
- 符合业界：维度内去重 + 跨维度组合

**风险**：
- 两个不同维度但相关 0.75 的因子都被保留，组合中可能有信息冗余
- 缓解：跨维度 0.9 兜底阈值 + ICIR 加权时高相关因子权重会自然分散

---

## 4. 详细设计

### 4.1 `factor_definitions.py` 新增内容

```python
# 因子经济维度分类
# 定义来源: 2026-06-20 因子多样性讨论，参考 AQR 4 类风格 + MSCI FaCS 5 类
# 分类依据: 因子计算逻辑的经济含义，不是统计相关性
FACTOR_CATEGORIES: dict[str, str] = {
    # 动量/趋势 (9)
    "momentum_strength": "momentum",
    "return_3d": "momentum",
    "return_5d": "momentum",
    "rsi": "momentum",
    "kdj_j": "momentum",
    "ma5_deviation": "momentum",
    "near_high_ratio_5": "momentum",
    "past_return_1d": "momentum",
    "positive_day_ratio_5": "momentum",
    # 价格位置 (4)
    "price_position": "price_position",
    "bollinger_pb": "price_position",
    "tail_price_position": "price_position",
    "tail_price_position_delta": "price_position",
    # 量能 (5)
    "volume_ratio": "volume",
    "turnover_surge": "volume",
    "turnover_surge_delta": "volume",
    "volume_price_strength": "volume",
    "intraday_intensity": "volume",
    # 尾盘行为 (5)
    "tail_price_slope": "tail_behavior",
    "tail_price_volume_intensity": "tail_behavior",
    "tail_volume_acceleration": "tail_behavior",
    "tail_volume_shrink": "tail_behavior",
    "tail_volume_shrink_delta": "tail_behavior",
    # 波动率 (2)
    "amplitude": "volatility",
    "amplitude_delta": "volatility",
    # 隔夜跳空 (1)
    "overnight_ret": "overnight",
    # 资金流 (2)
    "capital_flow_ratio_trend": "capital_flow",
    "capital_flow_intensity": "capital_flow",
    # 行业 (6)
    "industry_momentum_5d": "industry",
    "industry_turnover_trend": "industry",
    "industry_amplitude_trend": "industry",
    "industry_roe_trend": "industry",
    "industry_earnings_growth": "industry",
    "industry_pe_trend": "industry",
}

# 维度列表（用于遍历）
CATEGORY_DIMENSIONS: list[str] = [
    "momentum", "price_position", "volume", "tail_behavior",
    "volatility", "overnight", "capital_flow", "industry",
]
```

### 4.2 `identify_high_corr_groups` 修改

新增 `factor_categories` 和 `cross_dimension_threshold` 参数。合并逻辑变为维度感知：

```python
def identify_high_corr_groups(
    valid_factors: dict[str, dict],
    corr_matrix: pd.DataFrame,
    threshold: float | None = None,
    factor_categories: dict[str, str] | None = None,   # 新增
    cross_dimension_threshold: float | None = None,     # 新增
    logger: logging.Logger | None = None,
) -> tuple[list[list[str]], list[tuple[str, str, float]]]:
```

合并判断逻辑：
```python
for i, name_i in enumerate(factor_names):
    for j, name_j in enumerate(factor_names):
        if i < j and ...:
            corr_val = abs(corr_matrix.loc[name_i, name_j])
            if not pd.isna(corr_val) and corr_val > threshold:
                # 维度感知：判断是否同维度
                cat_i = factor_categories.get(name_i) if factor_categories else None
                cat_j = factor_categories.get(name_j) if factor_categories else None

                if cat_i is not None and cat_j is not None and cat_i != cat_j:
                    # 跨维度：仅当超过 cross_dimension_threshold 才合并
                    if cross_dimension_threshold and corr_val > cross_dimension_threshold:
                        high_corr_pairs.append((name_i, name_j, corr_val))
                        union(name_i, name_j)
                        logger.debug("跨维度高相关(>%.2f): %s(%s) vs %s(%s), corr=%.2f",
                                     cross_dimension_threshold, name_i, cat_i, name_j, cat_j, corr_val)
                    else:
                        logger.debug("跨维度保留: %s(%s) vs %s(%s), corr=%.2f (维度不同, 不去重)",
                                     name_i, cat_i, name_j, cat_j, corr_val)
                else:
                    # 同维度或无分类信息：正常合并
                    high_corr_pairs.append((name_i, name_j, corr_val))
                    union(name_i, name_j)
                    logger.debug("同维度高相关: %s vs %s, corr=%.2f", name_i, name_j, corr_val)
```

### 4.3 `select_factors` 修改

- `DEFAULT_THRESHOLDS` 新增 `"cross_dimension_corr_threshold": 0.9`
- Step 3 调用 `identify_high_corr_groups` 时传入 `factor_categories` 和 `cross_dimension_threshold`
- 返回结构新增 `dimension_coverage` 字段

### 4.4 测试计划

| 测试 | 描述 |
|------|------|
| test_same_dimension_dedup | 同维度高相关因子被合并去重 |
| test_cross_dimension_preserved | 跨维度高相关因子(0.7-0.9)不被合并 |
| test_cross_dimension_extreme_dedup | 跨维度极端高相关(>0.9)被合并去重 |
| test_no_categories_backward_compat | 无分类时退化为原逻辑（向后兼容） |
| test_categories_complete | FACTOR_CATEGORIES 覆盖所有 34 个因子 |
| test_dimension_coverage_output | select_factors 返回 dimension_coverage 字段 |

---

## 5. 影响评估

| 方面 | 影响 |
|------|------|
| 现有筛选逻辑 | 不变（方案 A）|
| composite_runner | 无需修改（select_factors 返回结构向后兼容，新增字段） |
| weight_selector | 无需修改 |
| stock_selector | 无需修改 |
| 报告脚本 | 可选：后续可展示维度覆盖情况 |
| 测试 | 新增 ~6 个测试用例 |
| MODULE.md | 可选：后续补充 M17 规则 |
