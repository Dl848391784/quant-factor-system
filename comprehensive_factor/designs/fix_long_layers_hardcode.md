# Design: 修复 long_layers 硬编码 bug

## 问题

`composite_weight_selector.py:148` 硬编码 `long_layers: ["layer_1", "layer_2"]`，
但 backtest `meta.long_layers` 因子方向自适应：IC>0 因子为 `[1,2]`（50个），IC<0 因子为 `[4,5]`（22个）。

对 IC<0 因子（如 ob_quality 的 composite），layer_1/layer_2 是做空层不是做多层，
导致 `long_return_annual` 用了做空层收益（-1.072），实际做多层收益为 +0.121。方向完全反了。

同一根因存在于 `factor_selector.py:557`：硬编码读 `layer_1` 做"买入层"检查，
对 `meta.long_layers=[4,5]` 的因子，layer_1 是做空层不是买入层。

## 根因

层级编号在不同因子方向下含义不同，但两处代码都硬编码了固定层名，未从 backtest meta 动态读取。

## 修复方案（第一性原理）

**从 `backtest.meta.long_layers` 动态读取做多层，而非 hardcode 任何层号。**

这是唯一在任何因子方向下都成立的方案。hardcode `[1,2]` 或 `[4,5]` 都只对一种方向正确。

### 改动 1: composite_weight_selector.py

位置：`MetricExtractor.extract` 方法（行 341-394）

```python
# 读取 backtest meta 的 long_layers（整数列表），转换为 layer_stats 键名
meta = backtest.get("meta", {})
meta_long_layers = meta.get("long_layers", None)

if meta_long_layers:
    # 动态: [4, 5] -> ["layer_4", "layer_5"]
    long_layer_names = [f"layer_{n}" for n in meta_long_layers]
else:
    # 回退: 旧数据无 meta 字段时用默认值（向后兼容）
    long_layer_names = list(self._config.long_layers)

# 用动态层名提取 long_return_annual / long_sharpe / max_drawdown
long_layer_data = [layer_stats[name] for name in long_layer_names if name in layer_stats]

# layer_1_annual 改为 "首个做多层" 的 annual_return
first_long_layer_name = long_layer_names[0]  # e.g. "layer_4"
first_long_layer = layer_stats.get(first_long_layer_name, {})
layer_1_annual = first_long_layer.get("annual_return")  # 保留原字段名向后兼容
```

DEFAULT_CONFIG 的 `long_layers: ["layer_1", "layer_2"]` 保留作为回退默认值，不删除。

### 改动 2: factor_selector.py

位置：`validate_factor` 函数（行 546-572）

```python
# 从 backtest meta 动态读取做多层
meta = backtest.get("meta", {})
meta_long_layers = meta.get("long_layers", [1])  # 回退 [1]
first_long_layer_name = f"layer_{meta_long_layers[0]}"  # e.g. "layer_4"

layer_stats = backtest.get("layer_stats", {})
first_long_layer = layer_stats.get(first_long_layer_name, {})
layer_1_annual = first_long_layer.get("annual_return", None)
layer_1_sharpe = first_long_layer.get("sharpe_ratio", None)
```

### 改动 3: 测试更新

两个测试文件的 fixture 需添加 `meta.long_layers` 字段，并新增 IC<0（long_layers=[4,5]）的测试用例。

## 不改什么

- `DEFAULT_CONFIG["long_layers"]` 保留作为回退默认值（旧数据/测试无 meta 时用）
- `weight_selection_result.json` 的字段名 `layer_1_annual` 不改（下游消费者依赖）
- `factor_selector.py` 的阈值逻辑不改（72->1 筛选是超买域经济必然，非 bug）

## 影响范围

- `ob_quality` composite 的 weight_selection_result.json: long_return_annual 从 -1.072 变为 +0.121
- `default` pipeline（如有 IC<0 因子构建的 composite）同样受益
- 个体因子筛选：22 个 [4,5] 因子的 layer_1_annual 检查修正（但实测全部 long_return<0 已被淘汰，仅 tail_volume_acceleration 边界受影响）

## 验证

1. `pytest comprehensive_factor/test_cases/test_composite_weight_selector.py` - 原有 + 新增 [4,5] 用例
2. `pytest comprehensive_factor/test_cases/test_factor_selector_p1.py` - 原有 + 新增 [4,5] 用例
3. 重跑 ob_quality weight_selector 确认 long_return_annual > 0
