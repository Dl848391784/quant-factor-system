# 修复计划：avg_stocks_per_day 口径感知

> 诊断结论：混合问题（代码 bug + 规范遗漏）
> 创建时间：2026-05-19
> 根因：v1.37 注释承诺未被实现，total_days 无法传递时间范围，period 与 avg_stocks_per_day 口径可能不一致

---

## 问题分析

### 当前状态

**输出结构：**
```json
{
  "sample_stats": {
    "total_days": 545,           // 数量，无时间范围
    "avg_stocks_per_day": 2720   // 用户不知道这个值反映哪个时间段
  },
  "period": {
    "start": "2024-02-06",
    "end": "2026-05-15"
  }
}
```

**问题：**
1. period 可能覆盖历史缓存（如 2020-2025）
2. avg_stocks_per_day 只反映当前数据源（如 2024-2025）
3. 用户无法从输出判断 avg_stocks_per_day 的口径
4. 注释说"用户可通过 total_days 判断"，但 total_days 无法传递时间范围

---

## 修复方案

### 方案：在 sample_stats 中添加 avg_stocks_period 字段

**新增字段：**
```json
{
  "sample_stats": {
    "total_days": 545,
    "valid_days": 514,
    "avg_stocks_per_day": 2720,
    "avg_stocks_period": {         // 新增：avg_stocks_per_day 的口径范围
      "start": "2024-02-06",
      "end": "2026-05-15",
      "description": "avg_stocks_per_day 反映此范围内的平均每日股票数"
    }
  }
}
```

**效果：**
- 用户可明确知道 avg_stocks_per_day=2720 反映的是 2024-02-06 ~ 2026-05-15
- 即使 period 覆盖更大范围，avg_stocks_period 也明确标注了 avg_stocks_per_day 的口径
- 注释承诺被实现

---

## 任务清单

### Task 1: 添加 avg_stocks_period 字段（2分钟）

**目标：** 在 sample_stats 中添加 avg_stocks_period 字段，明确标注 avg_stocks_per_day 的口径范围

**文件：** `/home/admin/projects/factor_ic_analyzer/factor_ic/ic_rsi_1d.py`

**修改位置：** 第528-548行（`_incremental_update` 函数内的 sample_stats 字段）

**当前代码：**
```python
'sample_stats': {
    # ... 注释 ...
    'total_days': max(...),
    'valid_days': len(valid_ic),
    'avg_stocks_per_day': int(factor_df_full.groupby('date').size().mean())
},
```

**修改后：**
```python
'sample_stats': {
    # ... 注释 ...
    'total_days': max(...),
    'valid_days': len(valid_ic),
    'avg_stocks_per_day': int(factor_df_full.groupby('date').size().mean()),
    # avg_stocks_period：avg_stocks_per_day 的口径范围（遵循 PROJECT.md 输出字段口径规范）
    # - 用户可明确知道 avg_stocks_per_day 反映哪个时间段的股票数
    # - 即使 period 覆盖历史缓存，avg_stocks_period 也标注了当前数据源的口径
    'avg_stocks_period': {
        'start': str(factor_df_full['date'].min()),
        'end': str(factor_df_full['date'].max()),
        'description': f"avg_stocks_per_day 反映 {factor_df_full['date'].min()} ~ {factor_df_full['date'].max()} 范围内的平均每日股票数"
    }
},
```

---

### Task 2: 删除误导性注释（1分钟）

**目标：** 删除第540行"用户可通过 total_days 判断"的误导性注释

**当前注释（第540行）：**
```python
#   - 用户可通过 total_days 判断数据范围，理解统计口径
```

**删除原因：** total_days 无法传递时间范围信息，注释指向错误字段

---

### Task 3: 补充 PROJECT.md 规范（2分钟）

**目标：** 新增「输出字段口径规范」章节

**文件：** `/home/admin/projects/factor_ic_analyzer/PROJECT.md`

**插入位置：** 在「字典构建规范」章节后

**新增内容：**
```markdown
---

### 输出字段口径规范

**核心原则：** 输出字段如果包含统计口径限制，必须提供明确的时间范围字段，让用户感知口径。

**问题背景：**

增量模式下，某些字段只反映当前数据源的口径：
1. avg_stocks_per_day 只反映当前因子缓存范围内的股票数
2. period 可能覆盖历史缓存（更大范围）
3. 用户无法从 total_days 判断口径（total_days 只是数量）
4. 口径不一致会导致用户误解统计含义

**错误示例：**

```python
# ❌ 禁止：只输出统计值，不标注口径
sample_stats = {
    'avg_stocks_per_day': 2720  # 用户不知道这个值反映哪个时间段
}

# ❌ 禁止：注释承诺无法实现
# 用户可通过 total_days 判断数据范围  # total_days 无法传递时间范围
```

**正确实现：**

```python
# ✓ 正确：输出统计值 + 口径范围字段
sample_stats = {
    'avg_stocks_per_day': 2720,
    'avg_stocks_period': {  # 明确标注口径
        'start': '2024-02-06',
        'end': '2026-05-15',
        'description': 'avg_stocks_per_day 反映此范围内的平均每日股票数'
    }
}
```

**为何必须提供口径字段：**

```
1. 用户可明确知道统计值的口径范围
2. 即使全局 period 覆盖更大范围，口径字段也标注了局部统计的口径
3. 防止用户误解统计含义（如误以为 avg_stocks_per_day 是全历史均值）
4. 注释承诺必须可验证、可实现
```
```

---

### Task 4: 同步更新流程文档（1分钟）

**目标：** 版本递增 + 时间标注 + 更新内容

**文件：** `/home/admin/projects/factor_ic_analyzer/factor_ic/docs/ic_rsi_1d_flow.md`

**修改内容：**

1. **版本号递增：** v1.49 → v1.50

2. **生成时间更新：** 当前时间

3. **更新内容追加：**
```markdown
> 50. [v1.50] 新增 avg_stocks_period 字段：明确标注 avg_stocks_per_day 的口径范围
> 51. [v1.50] 删除第540行误导性注释"用户可通过 total_days 判断"（total_days 无法传递时间范围）
> 52. [v1.50] 补充 PROJECT.md 「输出字段口径规范」章节：统计字段必须提供口径范围字段
```

---

## 执行顺序

```
Task 1 → Task 2 → Task 3 → Task 4 → 验证
```

---

## 验证方式

1. 运行 `python factor_ic/ic_rsi_1d.py` 验证脚本正常执行
2. 检查输出文件包含 avg_stocks_period 字段
3. 验证 avg_stocks_period.start/end 与 factor_df_full 的日期范围一致

---

## 修改文件清单

| 文件 | 操作 |
|------|------|
| `factor_ic/ic_rsi_1d.py` | 添加 avg_stocks_period 字段 + 删除误导性注释 |
| `PROJECT.md` | 新增「输出字段口径规范」章节 |
| `factor_ic/docs/ic_rsi_1d_flow.md` | 版本递增、时间标注、更新内容追加 |