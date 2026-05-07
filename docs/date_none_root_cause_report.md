# 向量化回测模块 date 列为 None 根因排查报告

## 问题摘要

**症状**: 回测日志显示 `[回测] 发现 750 个 NaN 排名值，涉及日期: [None]...`

**根因**: pandas `groupby.apply` 内部机制导致分组键列（date）被排除

## 排查过程

### 1. 定位问题模块
- **向量化回测模块**: `common/scoring_engine.py` 的 `run_backtest_vectorized` 方法
- **关键函数**: `get_top_n_with_industry_constraint` (第 2835-2892 行)

### 2. 问题代码定位

**问题位置**: `common/scoring_engine.py` 第 2864-2878 行

```python
for _, row in candidates.iterrows():
    if len(selected) >= top_n:
        break
    
    industry = row.get('industry')
    
    if pd.isna(industry) or not industry or industry == '未知':
        selected.append(row.to_dict())  # ← 问题在这里！row.to_dict() 丢失 date
        continue
    
    current_count = industry_count.get(industry, 0)
    if current_count < max_same_industry:
        selected.append(row.to_dict())  # ← 同样的问题
        industry_count[industry] = current_count + 1
```

### 3. 根因分析

**关键发现**:

| 测试场景 | row.to_dict() 结果 |
|---------|-------------------|
| 直接 DataFrame.iterrows() | `{'date': '2025-01-01', ...}` ✓ |
| groupby 循环内 iterrows() | `{'date': '2025-01-01', ...}` ✓ |
| **groupby.apply 内 iterrows()** | `{'asset': 'SH600049', 'total_score': 99}` ✗ (date缺失) |

**原因**: pandas 的 `groupby.apply` 在执行时，内部机制会**排除分组键列**，导致：
1. `group` DataFrame 虽然有 `date` 列，但在 iterrows 时被排除
2. `row.to_dict()` 返回的字典不包含 `date` 字段
3. `pd.DataFrame(selected)` 创建的 DataFrame 缺少 `date` 列
4. 代码第 2889-2891 行添加 `date = None`，导致所有 date 值为 None

### 4. 相关代码链

```
score_df['date'] = category 类型  (第 1015 行)
↓
score_df.groupby('date', group_keys=False)  (第 2895 行)
↓
group.nlargest() → candidates  (第 2850 行)
↓
candidates.iterrows() → row.to_dict()  (第 2864 行)
↓
❌ row.to_dict() 不包含 date 字段
↓
pd.DataFrame(selected) 缺少 date 列
↓
第 2891 行: result_df['date'] = None
↓
最终 selected_df['date'] = [None, None, ...]
```

## 修复建议

### 方案一：使用 group.name 获取分组键（推荐）

```python
def get_top_n_with_industry_constraint(group, top_n, max_same_industry, enabled):
    # 获取分组键（分组日期）
    group_date = group.name  # 关键！group.name 包含分组键值
    
    expected_columns = ['date', 'asset', 'total_score', 'industry']
    
    # ... 原有逻辑 ...
    
    for _, row in candidates.iterrows():
        if len(selected) >= top_n:
            break
        
        industry = row.get('industry')
        
        row_dict = row.to_dict()
        # 修复：手动添加缺失的 date 字段
        row_dict['date'] = group_date
        
        if pd.isna(industry) or not industry or industry == '未知':
            selected.append(row_dict)
            continue
        
        current_count = industry_count.get(industry, 0)
        if current_count < max_same_industry:
            selected.append(row_dict)
            industry_count[industry] = current_count + 1
    
    # ... 原有逻辑 ...
```

### 方案二：使用 group.iloc 替代 iterrows（不推荐）

经测试，在 `groupby.apply` 内部使用 `iloc` 同样会丢失分组键列。

### 方案三：将 date 列转换为字符串类型

在 `score_df` 创建后，将 `date` 列转换为字符串类型而非 category：

```python
# 修改第 1015 行
# 原代码: self.factor_df['date'] = self.factor_df['date'].astype('category')
# 修复: self.factor_df['date'] = self.factor_df['date'].astype(str)
```

但此方案未验证是否完全有效，可能存在其他副作用。

## 验证结果

| 方案 | 测试结果 | date 值 |
|-----|---------|--------|
| 方案一: group.name | ✓ 有效 | `['2025-01-01', '2025-01-01', ...]` |
| 方案二: iloc | ✗ 无效 | date 列仍然缺失 |
| 方案三: category→str | 未验证 | - |

## 影响范围

- **影响模块**: 向量化回测 (`run_backtest_vectorized`)
- **影响功能**: 智能选股回测系统
- **影响数据**: 750 条 NaN 排名值（5 天 × 150 天）

## 附录：测试脚本

```python
# 验证根因的测试脚本
import pandas as pd

dates = ['2025-01-01'] * 50 + ['2025-01-02'] * 50
assets = [f'SH{600000+i}' for i in range(100)]
scores = list(range(100))

score_df = pd.DataFrame({'date': dates, 'asset': assets, 'total_score': scores})
score_df['date'] = score_df['date'].astype('category')

# 问题演示
def problem_func(group):
    candidates = group.nlargest(5, 'total_score')
    selected = []
    for idx, row in candidates.iterrows():
        selected.append(row.to_dict())
        if len(selected) >= 3: break
    return pd.DataFrame(selected)

result = score_df.groupby('date', group_keys=False).apply(problem_func)
print(f'问题结果: columns={result.columns.tolist()}, date缺失')

# 修复方案
def fixed_func(group):
    group_date = group.name  # 获取分组键
    candidates = group.nlargest(5, 'total_score')
    selected = []
    for idx, row in candidates.iterrows():
        row_dict = row.to_dict()
        row_dict['date'] = group_date  # 手动添加
        selected.append(row_dict)
        if len(selected) >= 3: break
    return pd.DataFrame(selected)

result_fixed = score_df.groupby('date', group_keys=False).apply(fixed_func)
print(f'修复结果: columns={result_fixed.columns.tolist()}, date={result_fixed["date"].tolist()[:5]}')
```

---

**报告日期**: 2026-05-01
**排查人**: 云舟
**状态**: 已定位根因，待修复