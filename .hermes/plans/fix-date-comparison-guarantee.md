# 修复计划：日期比较格式保证

> 诊断结论：规范遗漏（代码正确遵循现有规范，但规范缺少「日期比较操作」格式保证约定）
> 创建时间：2026-05-19
> 执行模式：代码加固 + 规范补充

---

## 任务清单

### Task 1: 添加日期格式断言（2-5分钟）

**目标：** 在日期比较前添加防御性断言，将隐式依赖转为显式保证

**文件：** `/home/admin/projects/factor_ic_analyzer/factor_ic/ic_rsi_1d.py`

**修改位置：** 第 503-508 行（`_incremental_update` 函数内）

**当前代码：**
```python
'period': {
    'start': min(all_dates[0], raw_metadata['period_start']),
    'end': max(all_dates[-1], raw_metadata['period_end'])
},
```

**修改后：**
```python
# 防御性断言：确保日期格式为 YYYY-MM-DD（遵循 PROJECT.md 日期字符串比较规范）
# 字典序比较依赖格式约定：年位 > 月位 > 日位
# 若格式不一致，min/max 会产生错误结果且不报错
import re
dates_to_compare = [all_dates[0], all_dates[-1], raw_metadata['period_start'], raw_metadata['period_end']]
for d in dates_to_compare:
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', str(d)):
        raise ValueError(
            f"日期格式不符合 YYYY-MM-DD 约定: {d}\n"
            f"位置: period 比较操作（增量模式）\n"
            f"请检查数据加载函数是否正确执行了日期转换"
        )

'period': {
    'start': min(all_dates[0], raw_metadata['period_start']),
    'end': max(all_dates[-1], raw_metadata['period_end'])
},
```

---

### Task 2: 补充 PROJECT.md 规范章节（2-5分钟）

**目标：** 新增「日期字符串比较规范」章节，明确格式约定与比较操作关系

**文件：** `/home/admin/projects/factor_ic_analyzer/PROJECT.md`

**插入位置：** 「日期类型一致性约定」章节后（约第 443 行后）

**新增内容：**
```markdown
---

### 日期字符串比较规范

基于日期类型一致性约定（所有日期为 "YYYY-MM-DD" 字符串），可以使用 min/max/sorted 进行字典序比较。

**隐式约定保证：**
- "YYYY-MM-DD" 格式 → 字典序 = 时间序（年位 > 月位 > 日位）
- 数据加载函数已确保所有日期来源统一为此格式
- 格式不一致的日期无法通过数据加载验证，不会进入比较环节

**代码要求：**
- 在使用 min/max/sorted 比较日期前，必须添加格式断言
- 断言位置：比较操作所在函数内（而非数据加载函数）
- 断言目的：防御未来其他代码路径引入未转换日期

**断言示例：**
```python
import re
dates_to_compare = [period_start, period_end, all_dates[0], all_dates[-1]]
for d in dates_to_compare:
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', str(d)):
        raise ValueError(
            f"日期格式不符合 YYYY-MM-DD 约定: {d}\n"
            f"位置: period 比较操作\n"
            f"请检查数据加载函数是否正确执行了日期转换"
        )

# 断言通过后，min/max/sorted 比较安全
period_start = min(dates_to_compare)
```

**为何必须断言：**
```
1. 格式约定在数据加载阶段保证，但比较操作可能来自多个路径
2. 未来其他代码路径可能引入未转换日期（如直接读取旧缓存）
3. 断言将隐式依赖转为显式保证，运行时捕获格式问题
4. 成本低（几行代码），风险防范效果好
```
```

---

### Task 3: 同步更新流程文档（2-5分钟）

**目标：** 流程文档版本递增 + 时间标注 + 更新内容说明

**文件：** `/home/admin/projects/factor_ic_analyzer/factor_ic/docs/ic_rsi_1d_flow.md`

**修改内容：**

1. **版本号递增：** v1.46 → v1.48（本次修复）

2. **生成时间更新：** 更新为当前时间

3. **更新内容追加：** 
```markdown
> 63. [v1.48] 新增日期字符串比较规范：比较操作前必须添加格式断言
> 64. [v1.48] 增量模式 period 比较前添加 YYYY-MM-DD 格式验证
> 65. [v1.48] 将隐式依赖转为显式保证，防御未来其他代码路径引入未转换日期
> 66. [v1.48] 补充 PROJECT.md 「日期字符串比较规范」章节
```

4. **在 Step 4 增量合并章节添加格式断言流程图：**
```
在合并计算 period 前新增格式断言步骤
```

---

## 执行顺序

```
Task 1 → Task 2 → Task 3 → 验证
```

固定顺序：代码 → 规范文档 → 流程文档 → 验证

---

## 验证方式

1. 运行 `python factor_ic/ic_rsi_1d.py` 验证脚本正常执行
2. 检查输出文件格式正确
3. 确认断言不触发（当前代码路径日期格式正确）

---

## 修改文件清单

| 文件 | 操作 |
|------|------|
| `factor_ic/ic_rsi_1d.py` | 第503-508行附近添加格式断言 |
| `PROJECT.md` | 新增「日期字符串比较规范」章节 |
| `factor_ic/docs/ic_rsi_1d_flow.md` | 版本递增、时间标注、更新内容追加 |