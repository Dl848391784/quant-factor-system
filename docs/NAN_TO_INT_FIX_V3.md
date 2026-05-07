# NaN 转整数问题修复方案（v3 完善）

## 问题描述

### 代码位置
- 文件：`/home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer/common/scoring_engine.py`
- 第 2908-2910 行：`rank` 列生成
- 第 3117 行：`int(row['rank'])` 使用

### 问题代码
```python
# 第 2908-2910 行
selected_df['rank'] = selected_df.groupby('date')['total_score'].rank(
    ascending=False, method='first'
).astype(int)
```

### 问题根因
1. **rank() 可能产生 NaN**：当 `total_score` 有 NaN 时，`rank()` 会返回 NaN
2. **astype(int) 不支持 NaN**：调用 `.astype(int)` 时如果有 NaN 会抛出 `ValueError`
3. **Int64 类型不兼容**：若使用 `astype('Int64')`（pandas 可空整数），则 <NA> 值在第 3117 行 `int(row['rank'])` 时会失败

---

## 方案 A 完善分析

### 原方案 A
```python
rank_values = selected_df.groupby('date')['total_score'].rank(
    ascending=False, method='first'
)

nan_count = rank_values.isna().sum()
if nan_count > 0:
    nan_dates = selected_df[rank_values.isna()]['date'].unique()
    logger.warning(f"[回测] 发现 {nan_count} 个 NaN 排名值，涉及日期: {nan_dates[:5]}...")
    selected_df = selected_df[rank_values.notna()].copy()
    rank_values = rank_values.dropna()

selected_df['rank'] = rank_values.astype(int)
```

### 问题审查

| 检查项 | 状态 | 说明 |
|--------|------|------|
| 过滤 NaN + 日志 | ✅ 正确 | 有警告日志，记录受影响日期 |
| 避免使用 Int64 | ✅ 正确 | 过滤后直接 `.astype(int)`，无 NaN 问题 |
| 索引对齐 | ⚠️ 有风险 | 需确保索引一致性 |

### 发现的问题

**索引对齐隐患**：
```python
selected_df = selected_df[rank_values.notna()].copy()  # 保留原索引
rank_values = rank_values.dropna()                      # dropna() 也保留原索引
```
虽然两者都是布尔过滤，但逻辑上应该显式保证一致性。

**缺少边界情况处理**：
- 如果所有行都是 NaN，`selected_df` 会变成空 DataFrame
- 应该提前返回，避免后续无意义计算

---

## 最终修复方案

### 修复后代码
```python
# v3 bugfix：修复 NaN 转整数问题
# 第 2907-2920 行（替换原 2907-2910 行）

# 添加排名
rank_values = selected_df.groupby('date')['total_score'].rank(
    ascending=False, method='first'
)

# 检查并处理 NaN 排名值
nan_count = rank_values.isna().sum()
if nan_count > 0:
    # 记录受影响的日期，便于问题排查
    nan_mask = rank_values.isna()
    nan_dates = selected_df[nan_mask]['date'].unique()
    logger.warning(
        f"[回测] 发现 {nan_count} 个 NaN 排名值，涉及日期: {nan_dates[:5].tolist()}..."
    )
    
    # 过滤掉 NaN 行（同时过滤 DataFrame 和 rank_values）
    valid_mask = rank_values.notna()
    selected_df = selected_df[valid_mask].copy()
    rank_values = rank_values[valid_mask]
    
    # 边界检查：如果过滤后为空，提前返回
    if selected_df.empty:
        logger.warning("[回测] 过滤 NaN 后无有效数据")
        return selected_df

# 安全转换为整数类型
selected_df['rank'] = rank_values.astype(int)
```

### 修改要点

1. **显式索引对齐**：
   ```python
   valid_mask = rank_values.notna()
   selected_df = selected_df[valid_mask].copy()
   rank_values = rank_values[valid_mask]  # 使用相同的 mask
   ```

2. **边界检查**：过滤 NaN 后检查是否为空，避免后续空 DataFrame 操作

3. **日志改进**：`.tolist()` 确保日期列表格式化输出

4. **不使用 Int64**：过滤后直接 `astype(int)`，避免 Int64 的 <NA> 问题

---

## 兼容性验证

### 第 3117 行代码
```python
'rank': int(row['rank']),
```

### 验证结果
- ✅ 过滤后 `selected_df['rank']` 是普通 `int64` 类型
- ✅ `int(row['rank'])` 可以正常工作
- ✅ 不会遇到 Int64 <NA> 转换错误

---

## 实施检查清单

- [ ] 确认第 2907-2910 行代码被替换
- [ ] 确认边界检查逻辑正确
- [ ] 确认日志输出格式
- [ ] 验证与第 3117 行的兼容性
- [ ] 运行单元测试验证

---

## 测试用例

```python
import pandas as pd
import numpy as np

def test_nan_rank_handling():
    """测试 NaN 排名处理"""
    # 模拟数据（含 NaN）
    test_df = pd.DataFrame({
        'date': ['2024-01-01'] * 3 + ['2024-01-02'] * 2,
        'asset': ['A', 'B', 'C', 'D', 'E'],
        'total_score': [0.9, np.nan, 0.7, 0.8, np.nan]
    })
    
    # 执行排名
    rank_values = test_df.groupby('date')['total_score'].rank(
        ascending=False, method='first'
    )
    
    # 验证 NaN 检测
    nan_count = rank_values.isna().sum()
    assert nan_count == 2, f"期望 2 个 NaN，实际 {nan_count}"
    
    # 验证过滤逻辑
    valid_mask = rank_values.notna()
    filtered_df = test_df[valid_mask].copy()
    filtered_ranks = rank_values[valid_mask].astype(int)
    
    assert len(filtered_df) == 3, f"期望 3 行，实际 {len(filtered_df)}"
    assert not filtered_ranks.isna().any(), "排名中不应有 NaN"
    assert filtered_ranks.dtype == np.int64, f"期望 int64，实际 {filtered_ranks.dtype}"

if __name__ == '__main__':
    test_nan_rank_handling()
    print("✅ 测试通过")
```

---

## 相关文档

- [BUG_FIX_2883_2887.md](./BUG_FIX_2883_2887.md) - 同一文件的其他修复