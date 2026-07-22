# 修复计划：avg_stocks_per_day 计算口径规范补充

> 诊断结论：混合问题（设计不一致 + 规范遗漏）
> 创建时间：2026-05-19
> 根因：代码设计故意使用不同基准（total_days=dropna前，avg_stocks_per_day=dropna后），但规范未解释口径差异

---

## 问题分析

### 当前行为

```
total_days 语义：
  - 全量：raw_metadata['total_days'] → dropna 前的原始缓存日期数
  - 增量：max(raw_metadata['total_days'], factor_df_full['date'].nunique()) → 同样是 dropna 前
  
avg_stocks_per_day 语义：
  - 全量：factor_df.groupby('date').size().mean() → dropna 后的数据
  - 增量：factor_df_full.groupby('date').size().mean() → 同样是 dropna 后
```

### 口径差异问题

```
假设原始数据有 100 天：
- 5 天因子值全为 NaN（停牌/数据缺失）
- 10 天股票数不足（IC 计算跳过）

total_days = 100（原始缓存日期数）
avg_stocks_per_day = sum(95天的股票数) / 95 ≈ 均值偏高
valid_days = 85（实际计算出 IC 的天数）

用户看到的：total_days=100，但 avg_stocks_per_day 只反映95天
→ 用户误解为"100天内日均股票数"，实际是"95天内日均股票数"
→ 均值偏高（5天缺失数据的日期通常股票数较少，排除后均值上升）
```

### PROJECT.md 已有规范

第1750-1757行已解释 `total_days` 与 `valid_days` 的口径差异：
```
total_days - valid_days = 因股票不足或数据缺失跳过的交易日数

注意：total_days 是原始缓存日期数（dropna 前），可能包含：
      1. 因股票数不足跳过的日期（IC 计算时跳过）
      2. 因因子值全部为 NaN 被过滤的日期（停牌、数据缺失）
```

但**遗漏了** `avg_stocks_per_day` 的计算口径说明。

---

## 修复方案

### 方案：补充规范（保留设计差异，明确口径）

**不修改代码**，保留设计意图：
- total_days = 数据覆盖范围（原始缓存）
- avg_stocks_per_day = 有效数据均值（dropna 后）

**补充 PROJECT.md 规范**：
1. 在「输出字段口径规范」章节补充 avg_stocks_per_day 计算口径说明
2. 明确说明 avg_stocks_per_day 基于 dropna 后的数据
3. 解释与 total_days 的口径差异和均值偏高原因
4. 提供口径一致性检查表

---

## 任务清单

### Task 1: 补充 PROJECT.md avg_stocks_per_day 计算口径规范（2分钟）

**目标：** 新增「avg_stocks_per_day 计算口径说明」章节

**文件：** `/home/admin/projects/factor_ic_analyzer/PROJECT.md`

**新增内容位置：** 第920行（「输出字段口径规范」章节后）

**新增内容：**

```markdown
---

### avg_stocks_per_day 计算口径规范

**核心原则：** avg_stocks_per_day 基于 dropna 后的有效数据计算，与 total_days 口径不同，必须明确说明。

**口径差异说明：**

```
| 字段 | 数据基准 | 说明 |
|------|---------|------|
| total_days | dropna 前（原始缓存） | 因子缓存的日期数，包含 NaN 日期 |
| avg_stocks_per_day | dropna 后（有效数据） | 因子值非 NaN 的日期数，不含 NaN 日期 |
| valid_days | IC 计算后（有效 IC） | 股票数 >= min_stocks 的日期数 |

口径差异原因：
- total_days 设计为"数据覆盖范围"，反映原始缓存的完整性
- avg_stocks_per_day 设计为"有效数据均值"，反映实际参与计算的股票数
- 两者设计目的不同，故意使用不同基准
```

**均值偏高原因：**

```
假设原始数据有 100 天：
- 5 天因子值全为 NaN（停牌/数据缺失）→ 这些日期的股票数通常较少
- avg_stocks_per_day 排除这 5 天后计算均值 → 均值偏高

用户看到：
  total_days = 100
  avg_stocks_per_day = 2800（实际是95天的均值）
  
误解：以为"100天内日均2800只股票"
实际：95天内日均2800只股票（5天被排除）

正确理解：
  total_days - avg_stocks_per_day口径天数 = NaN日期数
  若 total_days=100, avg_stocks_period覆盖95天, 则5天为NaN日期
```

**正确实现：**

```python
# 全量模式
factor_df, return_df, raw_metadata = load_data_from_cache()

# factor_df 是 dropna 后的数据
# avg_stocks_per_day 基于 factor_df 计算
avg_stocks_per_day = int(factor_df.groupby('date').size().mean())

# total_days 基于 raw_metadata 计算（dropna 前）
total_days = raw_metadata['total_days']

# 口径差异已通过 avg_stocks_period 字段标注
avg_stocks_period = {
    'start': str(factor_df['date'].min()),  # dropna 后的最小日期
    'end': str(factor_df['date'].max()),    # dropna 后的最大日期
    'description': f"avg_stocks_per_day 反映此范围内的平均每日股票数"
}
```

**口径一致性检查表：**

```
□ total_days 基于 raw_metadata（dropna 前）
□ avg_stocks_per_day 基于 factor_df（dropna 后）
□ avg_stocks_period.start/end 基于 factor_df['date'].min/max（dropna 后）
□ total_days >= avg_stocks_period覆盖天数 >= valid_days
□ 若 total_days > avg_stocks_period覆盖天数，说明有 NaN 日期被排除
□ avg_stocks_period.description 明确标注口径范围
```

**禁止行为：**

```python
# ❌ 禁止：avg_stocks_per_day 使用 raw_metadata 的 total_days 计算
# 这会导致"0 股票日"拉低均值，语义混乱
avg_stocks_per_day = total_stocks / raw_metadata['total_days']  # 错误

# ❌ 禁止：注释承诺口径一致但实际不一致
# avg_stocks_per_day 与 total_days 口径一致  ← 错误承诺
avg_stocks_per_day = int(factor_df.groupby('date').size().mean())  ← 实际不一致
```
```

---

### Task 2: 同步更新流程文档（1分钟）

**目标：** 版本递增 + 时间标注 + 更新内容

**文件：** `/home/admin/projects/factor_ic_analyzer/factor_ic/docs/ic_rsi_1d_flow.md`

**修改内容：**

1. **版本号递增：** v1.51 → v1.52

2. **生成时间更新：** 当前时间

3. **更新内容追加：**
```markdown
> 54. [v1.52] 补充 PROJECT.md 「avg_stocks_per_day 计算口径规范」章节
> 55. [v1.52] 明确 avg_stocks_per_day 基于 dropna 后数据，与 total_days 口径不同
> 56. [v1.52] 解释均值偏高原因：NaN 日期被排除，这些日期通常股票数较少
> 57. [v1.52] 提供口径一致性检查表，确保用户理解统计含义
```

---

## 执行顺序

```
Task 1 → Task 2 → 验证
```

---

## 验证方式

1. 检查 PROJECT.md 是否新增「avg_stocks_per_day 计算口径规范」章节
2. 检查流程文档版本号和时间标注是否更新
3. 确认规范内容清晰、口径说明完整

---

## 修改文件清单

| 文件 | 操作 |
|------|------|
| `PROJECT.md` | 新增「avg_stocks_per_day 计算口径规范」章节 |
| `factor_ic/docs/ic_rsi_1d_flow.md` | 版本递增、时间标注、更新内容追加 |