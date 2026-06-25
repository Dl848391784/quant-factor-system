# Design: 四种权重方式每天各存一份 LR 训练数据 (v3.11)

> **状态**: [experimental]
> **日期**: 2026-06-25
> **父设计**: designs/feat_lr_training_data.md (v3.10)
> **动机**: 用户指出当前只存 best_method 一份数据是浪费——如果 best_method 切换，训练数据从零开始

## What

每天对四种权重方式 (equal_weight, icir_weight, ic_weight, rolling_icir_weight) 各计算一次 composite 排序，各取 Bottom90，各存一份 LR 训练数据。选股仍只用 best_method。

## Why

1. **best_method 切换时不冷启动**: 当前 equal_weight 积累了 510 天数据，但如果某天 best_method 切到 rolling_icir_weight，后者训练数据为空，需 90 天才能启用过滤
2. **OOS AUC 对比**: 当前只看到 equal_weight 的 AUC=0.503（接近随机）。其他方式的 Bottom90 分布不同，LR 信号可能更强。存四种数据后可在 summary 中对比
3. **第一性原理**: 训练分布 = 应用分布。如果未来 best_method 可能切换，那四种方式的训练数据都应该积累

## How

### 核心重构: Step 7-9 封装为 `compute_composite_for_method()`

当前 `select_stocks` 的 Step 7-9 是为单一 best_method 设计的：
- Step 7: standardize_factors (按 factor_cols 标准化)
- Step 7.5: direction_map (方向统一化)
- Step 8: 加载 IC 数据
- Step 9: weight_engine.calculate → composite_factor

**重构方案**: 把 Step 7-9 封装成函数，对四种方式各调用一次。

```python
def _compute_composite_for_method(
    method: str,
    factor_df: pd.DataFrame,
    composite_data: dict,
    config: StockSelectorConfig,
    factor_list: list[str],
    factor_cols: list[str],
    ic_result_dir: Path,
    logger: logging.Logger,
) -> pd.Series:
    """对单个 weight_method 计算 composite_factor.

    1. 从 composite_<method>_1d.json 读取 factor_list, factor_cols, direction_map
    2. standardize_factors (截面标准化)
    3. 方向统一化 (direction_map)
    4. 加载 IC 数据 (rolling_icir 需要 ic_daily, icir/ic 需要 ic_results)
    5. weight_engine.calculate → composite_factor
    """
    # 注意: 每种方式的 factor_list 不同, 需要从各自的 composite JSON 读取
    ...
```

### 调用点: Step 13 改为循环

```python
# Step 13: v3.11 保存四种权重方式的 LR 训练数据
ALL_WEIGHT_METHODS = ["equal_weight", "icir_weight", "ic_weight", "rolling_icir_weight"]

for method in ALL_WEIGHT_METHODS:
    composite_file_m = config.output_dir / f"composite_{method}_{config.return_period}.json"
    if not composite_file_m.exists():
        logger.warning("跳过 %s: composite 文件不存在", method)
        continue

    with open(composite_file_m) as f:
        composite_data_m = json.load(f)

    # 对该方式计算 composite_factor
    composite_factor_m = _compute_composite_for_method(
        method=method,
        factor_df=factor_df.copy(),  # 避免标准化的 side-effect 污染
        composite_data=composite_data_m,
        config=config,
        factor_list=factor_list,  # best_method 的 factor_list (用于共性因子)
        factor_cols=factor_cols,  # best_method 的 factor_cols
        ic_result_dir=config.ic_result_dir,
        logger=logger,
    )

    # 取 Bottom90
    valid_cf_m = composite_factor_m.dropna()
    if len(valid_cf_m) == 0:
        continue
    bottom_pool_m = valid_cf_m.nsmallest(config.lr_bottom_pool_size)

    # 构建 bottom_stocks 格式
    full_ranked_m = valid_cf_m.sort_values(ascending=False)
    rank_map_m = {idx: i + 1 for i, idx in enumerate(full_ranked_m.index)}
    bottom_stocks_m = [
        {"rank": rank_map_m[idx], "code": factor_df.loc[idx, "asset"], "composite_value": val}
        for idx, val in bottom_pool_m.items()
    ]

    # 保存训练数据
    save_lr_training_data(
        bottom_stocks=bottom_stocks_m[:config.lr_bottom_pool_size],
        factor_df=factor_df,
        weight_config=composite_data_m,
        config=config,
        selection_date=selection_date,
        logger=logger,
    )
```

### 关键约束

1. **factor_df 的 side-effect 问题**: `standardize_factors` 会修改 factor_df (添加 _std 列)。四种方式的 factor_list 不同，_std 列会冲突。必须每次传 `factor_df.copy()` 或在函数内部隔离。

2. **direction_map 每种方式不同**: 每种方式的 composite JSON 里有自己的 `config.direction_map` 和 `config.flipped_factors`。不能复用 best_method 的。

3. **IC 数据加载**: rolling_icir 需要 `ic_daily_data` (历史 IC 序列), icir/ic 需要 `ic_results` (静态 IC 统计)。每种方式加载逻辑不同，需在函数内分别处理。

4. **权重读取**: save_lr_training_data 从 `weight_config.meta.weight_meta.last_day_weights` 读取权重。每种方式的 composite JSON 结构一致，但 last_day_weights 可能为空 (equal_weight/icir/ic 无显式权重 → 自动生成 1/n)。

5. **选股结果不受影响**: Step 10-12 仍然只用 best_method 的 composite_factor 做选股。Step 13 的循环只影响训练数据保存，不影响选股结果。

### summary 展示改动

`_generate_lr_training_status` 已经按 weight_method 分区读取，无需改动。回填四种方式的数据后，summary 会自动展示四种方式的 OOS AUC 对比。

### 回填脚本改动

`temporary/backfill_lr_training_data.py` 需要改为对四种方式各回填一次。每天 90 行 × 4 = 360 行。

## Don't

- ❌ 不要在 Step 13 循环中修改 factor_df 原始对象 (side-effect 污染)
- ❌ 不要复用 best_method 的 direction_map 给其他方式 (每种方式的 flipped_factors 不同)
- ❌ 不要在 Step 13 循环中做选股决策 (选股只用 best_method)
- ❌ 不要跳过 composite 文件不存在的方式 (warn + continue, 不抛异常)

## 任务拆分

| Task | 文件 | 改动 | 行数估算 |
|------|------|------|---------|
| 1 | stock_selector.py | 新增 `_compute_composite_for_method()` 函数 + Step 13 改循环 | ~80 行 |
| 2 | stock_selector.py | 测试: 四种方式各存一份训练数据 | ~30 行 |
| 3 | temporary/backfill_lr_training_data.py | 改为四种方式各回填一次 | ~40 行 |
| 4 | MODULE.md + design.md | 版本更新 + 规范补充 | ~20 行 |

## Verify

1. `ruff check + format` 全通过
2. `pytest comprehensive_factor/test_cases/test_two_stage_selector.py` 全通过
3. 实际运行 stock_selector: 验证四种方式各写入 90 行训练数据
4. `_generate_lr_training_status()`: 展示四种方式的积累天数和 OOS AUC
5. 回填脚本: 四种方式各回填 510 天
