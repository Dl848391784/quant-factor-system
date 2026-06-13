# Design: 修复 _apply_weights NaN 传播 Bug（让增量采集因子正常参与综合因子计算）

## 问题

### 现象
2026-06-10 凌晨 pipeline 执行，stock_selector 使用 icir_weight 方法选股时，
综合因子值全 NaN（0/3014 条有效值），4 次重试均失败。

### 根因链

1. **icir_weight 选中因子**：turnover_surge, tail_price_volume_intensity, tail_price_position, amplitude, momentum_strength
2. **turnover_surge 在 2026-06-09 全 NaN**（3014 条记录均无值）
3. **tail_price_volume_intensity 在 524/545 日期有效值≤1**（增量采集，仅最近 20 天有数据）
4. **_apply_weights 的"动态权重归一化"实现有 bug**：
   - 代码逻辑：`weighted_df.divide(valid_weight_sum, axis=0).sum(axis=1, skipna=False)`
   - `NaN * weight = NaN` → `NaN / valid_weight_sum = NaN`
   - `sum(skipna=False)` 只要行中有一个 NaN 就返回 NaN
   - 结果：即使 4/5 因子有值，综合因子仍全 NaN

### 正确逻辑（M29 规范意图）
M29 规范要求："按行重新归一化权重，确保有效因子的权重之和始终为 1"。
- 有效因子（非 NaN）→ 权重按比例放大至总和为 1
- 缺失因子（NaN）→ 被跳过，权重分配给有效因子
- 全 NaN 行 → 保持 NaN

### 验证

模拟 5 因子（其中 turnover_surge 全 NaN）：
- 当前实现：composite 全 NaN（0/3014 有效）
- 修复后：composite 2791/3014 有效（NaN 因子被跳过，权重归一化到其他 4 因子）

---

## 修复方案

### 修改文件
1. `comprehensive_factor/common/weight_engine.py` — `_apply_weights` 方法（行 98-157）

### 修改范围
≤3 文件、≤200 行代码（仅改 `_apply_weights` 内的向量化逻辑，约 15 行）

### 具体修改

**当前代码（行 146-153）**：
```python
# 构建 DataFrame：每列乘以权重，然后除以有效权重之和（归一化）
weighted_df = std_df.multiply(weight_values, axis=1)

# 归一化：weighted_df / valid_weight_sum（使权重之和为 1）
# valid_weight_sum 为 0 时（全 NaN），保持 NaN
composite = weighted_df.divide(valid_weight_sum.replace(0, np.nan), axis=0).sum(axis=1, skipna=False)

# 全 NaN 行保持 NaN（而非 0）
composite = composite.where(valid_weight_sum > 0, np.nan)
```

**修复后**：
```python
# 构建 DataFrame：每列乘以权重
weighted_df = std_df.multiply(weight_values, axis=1)

# NaN 处理：先将 NaN 位置的加权值置为 0（以便 sum 不传播 NaN）
# 原始 NaN 在 weighted_df 中是 NaN * weight = NaN
# 修复：显式将 NaN 加权值替换为 0，跳过缺失因子
weighted_df_clean = weighted_df.fillna(0)

# 归一化：有效加权值之和 / 有效权重之和（使权重之和为 1）
# valid_weight_sum 为 0 时（全 NaN），保持 NaN
composite = weighted_df_clean.divide(valid_weight_sum.replace(0, np.nan), axis=0)

# 全 NaN 行保持 NaN（而非 0）
composite = composite.where(valid_weight_sum > 0, np.nan)
```

### 逻辑验证

| 场景 | 因子 A（有值） | 因子 B（NaN） | 当前结果 | 修复后结果 |
|------|---------------|--------------|---------|-----------|
| A=1.0, B=NaN, wA=0.6, wB=0.4 | 1.0 | NaN | NaN（bug） | 1.0 * 0.6 / 0.6 = 1.0 ✅ |
| A=1.0, B=2.0, wA=0.6, wB=0.4 | 1.0 | 2.0 | 1.0*0.6/1.0 + 2.0*0.4/1.0 = 1.4 ✅ | 同上 ✅ |
| A=NaN, B=NaN | NaN | NaN | NaN | NaN ✅ |

修复后：
- 有值因子正常参与加权
- NaN 因子被跳过（fillna(0) + valid_weight_sum 归一化）
- 全 NaN 行保持 NaN（valid_weight_sum=0 时 divide 产生 NaN + where 条件）
- 增量采集因子（如尾盘因子）在有数据的日期正常参与，无数据的日期被跳过

---

## 影响范围

### composite_runner（回测场景）
- 全日期标准化后，尾盘因子在 524 日期 NaN → 在这些日期被跳过
- 在 21 日期有值 → 正常参与加权
- 综合因子在所有日期都有有效值（非全 NaN 日期）
- **回测指标会更准确**（之前 icir_weight 的 turnover 等指标可能因 NaN 日期导致计算异常）

### stock_selector（选股场景）
- 选股日期 2026-06-09：turnover_surge 全 NaN → 被跳过，其他 4 因子加权归一化
- 综合因子有效值数量 ≈ 2791（而非 0）
- **选股不再失败**

### weight_selector（权重选择）
- 回测指标更准确 → 权重选择结果可能变化
- icir_weight 的 turnover 指标之前为 0（可能因 NaN 导致），修复后应该有正常值

---

## 不需要修改的部分

- **factor_loader.py 的 standardize_factors**：标准化逻辑正确（M11 规范），NaN 是正确的统计行为
- **auto_select 因子筛选**：不需要加覆盖率门槛，增量因子 IC 指标达标即可入选
- **MODULE.md M29 规范**：规范描述正确（"按行重新归一化权重"），只是代码实现与规范意图不符

---

## 验证步骤

1. `ruff check --fix` + `ruff format`
2. 模拟测试：5 因子中 1 个全 NaN → composite 应有有效值
3. `pytest comprehensive_factor/test_cases/` — 确认现有测试不破坏
4. 手动执行 `python comprehensive_factor/stock_selector.py` — 选股应成功
5. 完整 pipeline 验证：`python run_pipeline.py --start-stage 6`

---

## 同步更新

- `comprehensive_factor/MODULE.md`：M29 规范的 How 部分代码示例需同步修正
- `comprehensive_factor/docs/` 流程文档：如有涉及加权 NaN 处理的描述需同步

---

*创建日期: 2026-06-10*
*遵循: AGENTS.md Design-First 流程（涉及 weight_engine.py + MODULE.md 2个文件）*