# weight_selector.py 测试用例文档

> 版本: v1.0
> 最后更新: 2026-06-03
> 对应 pytest 文件: test_weight_selector.py

---

## 测试场景清单

| 类别 | 测试场景 | pytest 测试 | 状态 |
|------|---------|------------|------|
| **配置验证** | 指标数量为9 | test_default_config_metrics_count | ✓ |
| 配置验证 | 权重方式数量为4 | test_default_config_weight_methods_count | ✓ |
| 配置验证 | 权重方式命名正确 | test_default_config_weight_methods_names | ✓ |
| 配置验证 | EPSILON值正确 | test_epsilon_value | ✓ |
| 配置验证 | 版本号格式正确 | test_version_format | ✓ |
| **指标提取** | 返回字典类型 | test_extract_metrics_returns_dict | ✓ |
| 指标提取 | 方法数量正确 | test_extract_metrics_method_count | ✓ |
| 指标提取 | 包含9个指标 | test_extract_metrics_contains_all_metrics | ✓ |
| 指标提取 | 单调性取绝对值 | test_extract_metrics_monotonicity_abs | ✓ |
| **归一化** | 返回字典类型 | test_normalize_minmax_returns_dict | ✓ |
| 归一化 | 值在[0,1]区间 | test_normalize_minmax_range | ✓ |
| 归一化 | higher_better方向正确 | test_normalize_minmax_higher_better_direction | ✓ |
| 归一化 | lower_better方向正确 | test_normalize_minmax_lower_better_direction | ✓ |
| **综合得分** | 返回字典类型 | test_calculate_weighted_score_returns_dict | ✓ |
| 综合得分 | 值在[0,1]区间 | test_calculate_weighted_score_range | ✓ |
| **选择** | 返回tuple类型 | test_select_best_method_returns_tuple | ✓ |
| 选择 | 最优得分等于最高 | test_select_best_method_best_score | ✓ |
| **输出** | 返回字典类型 | test_generate_output_returns_dict | ✓ |
| 输出 | meta字段存在 | test_generate_output_meta_fields | ✓ |
| 输出 | best_selection字段存在 | test_generate_output_best_selection_fields | ✓ |
| 输出 | ranking字段存在 | test_generate_output_ranking_fields | ✓ |
| **边界测试** | 空字典抛ValueError | test_select_best_method_empty_dict | ✓ (新增) |
| 边界测试 | 单方法归一化 | test_normalize_minmax_single_method | ✓ (新增) |
| 边界测试 | 权重为零 | test_calculate_weighted_score_zero_weight | ✓ (新增) |

---

## 新增边界测试（v1.4）

### test_select_best_method_empty_dict

**目的**: 验证空字典场景抛出 ValueError

**测试数据**:
```python
final_scores = {}
```

**预期行为**:
```python
with pytest.raises(ValueError, match="final_scores 不能为空"):
    select_best_method(final_scores)
```

---

### test_normalize_minmax_single_method

**目的**: 验证单个方法归一化（所有指标得1.0）

**测试数据**:
```python
metrics_data = {"equal_weight": {...}}
```

**预期行为**:
```python
normalized = normalize_minmax(metrics_data, metric_configs)
for metric, score in normalized["equal_weight"].items():
    assert score == 1.0  # diff=0 → EPSILON容差 → 全给1.0
```

---

### test_calculate_weighted_score_zero_weight

**目的**: 验证权重为零场景

**测试数据**:
```python
metric_configs = {"metric1": {"direction": "higher_better", "weight": 0.0}}
normalized_scores = {"method1": {"metric1": 0.5}}
```

**预期行为**:
```python
score = calculate_weighted_score(normalized_scores, metric_configs)
assert score["method1"] == 0.0  # total_weight=0 → return 0.0
```

---

## pytest 运行命令

```bash
pytest comprehensive_factor/test_cases/test_weight_selector.py -v
```

---

## 测试覆盖率

| 模块 | 函数 | 测试覆盖 |
|------|------|---------|
| weight_selector | load_composite_results | 部分（需集成测试） |
| weight_selector | extract_metrics | ✓ |
| weight_selector | normalize_minmax | ✓ |
| weight_selector | calculate_weighted_score | ✓ |
| weight_selector | select_best_method | ✓ |
| weight_selector | generate_output | ✓ |

---

*创建时间: 2026-06-03*