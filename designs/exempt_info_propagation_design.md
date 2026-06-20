# Design: 报告展示与筛选逻辑同步——维度感知高相关展示 + 豁免信息传递链

> 日期: 2026-06-20
> 遵循: AGENTS.md Design-First 流程（规则 #12）、MODULE.md M57/M58
> 背景: 下午 8fc7826/719eb3a/883dca5 引入维度感知去重和豁免机制，summary 报告未同步

## 1. 问题陈述

### 问题1: 报告第三章用旧标准提示"建议剔除"跨维度高相关对

bollinger_pb[price_position] vs rsi[momentum] corr=0.92，按 M57 规范（8fc7826）
跨维度不合并是 by design。但 `generate_correlation_section` 不分维度，直接对
所有 |corr|>0.7 打印"建议剔除其中一个"，与筛选结果自相矛盾。

**根因**: `generate_factor_summary_report.py` 未导入 FACTOR_CATEGORIES，
`generate_correlation_section` 的 `selection_result` 参数注释"预留，暂不使用"。

### 问题2: 报告第四章不展示豁免信息，导致筛选标准"看起来不一致"

| 因子 | \|IC均值\| | \|夏普\| | \|单调性\| | 豁免结果 | 报告显示 |
|------|-----------|---------|-----------|---------|---------|
| tail_volume_acceleration | 0.0168<0.03❌ | 5.54>1.5✓ | 0.53>0.5✓ | **豁免→入选** | 无标注 |
| tail_volume_shrink_delta | 0.0127<0.03❌ | 1.43<1.5❌ | 0.62>0.5✓ | **未豁免→剔除** | 仅"\|ic_mean\|=0.013<0.03" |

`validate_factor` 有豁免逻辑（行263-278），但返回值 `(is_valid, reasons)` 不包含
豁免信息。报告无法知道因子是"豁免入选"还是"正常通过"，也无法知道被剔除因子
"为什么没豁免"。

## 2. 方案设计

### 2.1 问题1: 报告维度感知高相关展示（1文件，~20行）

**改动文件**: `summary/generate_factor_summary_report.py`

**改动点**:
1. 行89-93 导入补充 `FACTOR_CATEGORIES`
2. `generate_correlation_section` 行1228-1244 修改高相关对展示逻辑

**逻辑**:
```python
# 当前（旧逻辑）: 不分维度，所有 |corr|>0.7 都打"建议剔除"
high_corr_pairs = _extract_corr_pairs(corr_matrix, factor_names, 0.7, 1.0)
if high_corr_pairs:
    lines.append("选中因子中高相关因子对（|corr| > 0.7，建议剔除其中一个）：")

# 改为: 按维度分类展示
for pair in high_corr_pairs:
    cat_i = FACTOR_CATEGORIES.get(pair[0])
    cat_j = FACTOR_CATEGORIES.get(pair[1])
    if cat_i and cat_j and cat_i != cat_j:
        cross_dim_pairs.append(pair)  # 跨维度保留
    else:
        same_dim_pairs.append(pair)   # 同维度（应已被筛选去重）

# 跨维度: "跨维度保留（维度不同，经济含义不同，不去重）"
# 同维度: "建议检查筛选逻辑（同维度高相关应已被去重）"
```

### 2.2 问题2: 豁免信息从筛选源头传递到报告（3文件，~80行）

#### 2.2.1 `validate_factor` 返回值扩展

**当前**: `tuple[bool, list[str]]` → `(is_valid, reasons)`
**改为**: `tuple[bool, list[str], list[dict]]` → `(is_valid, reasons, exempt_details)`

`exempt_details` 结构——每个触发豁免检查的阈值一条记录:

```python
# 豁免成功
{
    "trigger": "ic_mean",        # 触发阈值: "ic_mean" | "icir"
    "threshold": 0.03,            # 阈值
    "actual": 0.0168,             # 实际值
    "exempted": True,             # 豁免成功
    "conditions": {               # 豁免条件实际值
        "sharpe": 5.54,
        "mono_corr": 0.5338,
        "ic_mean_abs": 0.0168,
    },
    "detail": "回测强劲(夏普=5.54>1.5,单调性=0.53>0.5)",
}

# 豁免失败
{
    "trigger": "ic_mean",
    "threshold": 0.03,
    "actual": 0.0127,
    "exempted": False,
    "conditions": {
        "sharpe": 1.43,
        "mono_corr": 0.6186,
        "ic_mean_abs": 0.0127,
    },
    "detail": "未满足豁免: 夏普=1.43<1.5",
}

# 无豁免触发（阈值通过或非豁免项）→ exempt_details = []
```

**豁免检查覆盖范围**:
- ic_mean 豁免（行263-278）: `is_reverse_factor_candidate`
- ICIR 豁免（行310-331）: `is_icir_exempt`
- 两者豁免条件相同: `|夏普|>1.5 + |单调性|>0.5 + |ic_mean|>=0.005`

**不覆盖的豁免**（不影响入选/剔除，无需传递）:
- p_value 小样本豁免（行289-300）: 跳过检查，不改变结果
- 短样本回测强劲豁免（行244-253）: 影响标记，不影响有效性

#### 2.2.2 `filter_invalid_factors` 结果扩展

**新增字段**: `exempted_factors: dict[str, list[dict]]`

```python
# 所有触发过豁免检查的因子（无论成功失败）
# key: factor_name, value: exempt_details list
{
    "tail_volume_acceleration": [{...exempted=True...}],
    "tail_volume_shrink_delta": [{...exempted=False...}],
}
```

构建逻辑: 遍历 `validate_factor` 返回的 `exempt_details`，非空即加入。

#### 2.2.3 `select_factors` 透传

在返回结果中增加:
```python
"exempted_factors": filter_result.get("exempted_factors", {}),
```

#### 2.2.4 报告展示

`get_factor_selection_info` 读取 `selection_result["exempted_factors"]`:

**入选因子中被豁免的**——在"选中因子"行追加标注:
```
tail_volume_acceleration(ICIR=0.33,权重=19.2%,豁免:|ic_mean|=0.017<0.03,回测强劲 夏普=5.54>1.5)
```

**被剔除因子中豁免失败的**——在剔除原因后追加说明:
```
tail_volume_shrink_delta(|ic_mean|=0.013<0.03; 未满足豁免: 夏普=1.43<1.5)
```

## 3. 决策矩阵

### 3.1 问题1: 为什么不改筛选算法而改报告？

| 选项 | 来源 | 理由 |
|------|------|------|
| ✅ 改报告 | M57 (MODULE.md 行1897-1960) | 跨维度不合并是 by design，报告用旧标准才矛盾 |
| ❌ 改筛选 | 无 | 会回退下午 8fc7826 的修复，重现已解决的维度坍塌 |

### 3.2 问题2: 为什么选路径B（改接口）而非路径A（报告重算）？

| | 路径A（报告重算） | 路径B（接口传递）✅ |
|---|---|---|
| 豁免逻辑 | 报告端重复实现 | 单一来源（validate_factor） |
| 一致性风险 | 阈值改两处易遗漏 | 只改一处 |
| 第一性原理 | 信息从结果端反推 | 信息从源头传递 |
| 改动量 | 1文件~30行 | 3文件~80行 |
| 测试 | 无法直接测试 | 可单元测试 validate_factor 返回 |

### 3.3 豁免信息结构: 为什么用 list[dict] 而非单个 dict？

| 因子可能同时触发 ic_mean 和 icir 两个豁免（如 tail_volume_shrink: |ic_mean|=0.001<0.03 且 |icir|=0.023<0.15），需要分别记录每个豁免的详情。list[dict] 天然支持多条记录。

## 4. 文件影响评估

| 文件 | 改动 | 行数估计 | 风险 |
|------|------|---------|------|
| `comprehensive_factor/common/factor_selector.py` | validate_factor 返回值 + filter_invalid_factors 结果 + select_factors 透传 | ~40行 | 中（接口变更，但调用链单一） |
| `summary/generate_factor_summary_report.py` | 导入 FACTOR_CATEGORIES + 维度感知展示 + 豁免信息展示 | ~30行 | 低（只改展示） |
| `comprehensive_factor/test_cases/test_factor_selector_exemption.py` | 新增测试文件 | ~50行 | 无 |

**合计**: 3文件，~120行。符合 AGENTS.md 单任务 ≤3文件 ≤200行约束。

## 5. 执行计划

### 轮次1: factor_selector.py 接口变更 + 测试
- validate_factor 返回值扩展为 (is_valid, reasons, exempt_details)
- filter_invalid_factors 增加 exempted_factors 字段
- select_factors 透传 exempted_factors
- 新增 test_factor_selector_exemption.py: 验证豁免成功/失败/无触发三种场景
- ruff + pytest + commit

### 轮次2: summary 报告展示同步
- 导入 FACTOR_CATEGORIES
- generate_correlation_section: 维度感知高相关展示
- get_factor_selection_info: 豁免信息展示
- ruff + pytest + commit

### 轮次3: MODULE.md 更新
- M57 补充"报告展示须同步维度感知"说明
- 新增豁免信息传递链规范（或补充到现有规则）
- commit

## 6. 验证方法

```bash
# 轮次1
pytest comprehensive_factor/test_cases/test_factor_selector_exemption.py -v
pytest comprehensive_factor/test_cases/test_dimension_aware_dedup.py -v

# 轮次2
ruff check summary/generate_factor_summary_report.py
ruff format summary/generate_factor_summary_report.py
# 重跑 pipeline 生成新报告，验证:
#   1. 第三章跨维度高相关对标注"跨维度保留"而非"建议剔除"
#   2. 第四章豁免因子标注"豁免:..."
#   3. 第四章未豁免被剔除因子标注"未满足豁免:..."
```
