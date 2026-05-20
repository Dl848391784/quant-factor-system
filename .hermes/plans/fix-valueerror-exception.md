# 修复计划：ValueError 异常处理类型保留

> 诊断结论：代码 bug（注释说"直接传递"，但实际包装为 RuntimeError）
> 创建时间：2026-05-19
> 根因：v1.41 开发者误解"保留原始异常类型"含义，保留错误信息但改变异常类型

---

## 问题分析

### 当前代码（第646-648行）

```python
except ValueError as e:
    # 数据量不足：直接传递，保留原始错误信息
    raise RuntimeError(f"数据验证失败: {e}") from e
```

**问题：**
- 注释说"直接传递"，暗示应保留 ValueError 类型
- 实际把 ValueError 包装为 RuntimeError
- 调用方无法用 `except ValueError` 捕获
- 数据验证错误应该保留原始类型，让调用方区分处理

---

## 修复方案

### 方案：直接 raise ValueError，不包装

**修复后代码：**
```python
except ValueError as e:
    # 数据量不足：直接传递，保留原始异常类型（遵循 PROJECT.md 异常处理类型保留规范）
    # 数据验证错误应保留原始类型，让调用方区分处理
    raise  # 直接传递 ValueError，不包装
```

**效果：**
- ValueError 直接传递给调用方
- 调用方可以用 `except ValueError` 捕获数据验证错误
- 调用方可以用 `except RuntimeError` 捕获基础设施错误
- 注释与行为一致

---

## 任务清单

### Task 1: 修复 ValueError 异常处理（1分钟）

**目标：** 删除 RuntimeError 包装，直接 raise ValueError

**文件：** `/home/admin/projects/factor_ic_analyzer/factor_ic/ic_rsi_1d.py`

**修改位置：** 第646-648行

---

### Task 2: 补充 PROJECT.md 异常处理规范（2分钟）

**目标：** 新增「异常处理类型保留原则」章节，明确区分"基础设施错误"和"数据验证错误"

**文件：** `/home/admin/projects/factor_ic_analyzer/PROJECT.md`

**新增内容：**
```markdown
---

### 异常处理类型保留规范

**核心原则：** 异常处理时，应区分"基础设施错误"和"数据验证错误"，数据验证错误必须保留原始异常类型。

**错误分类：**

| 类型 | 示例 | 处理方式 |
|------|------|---------|
| **基础设施错误** | FileNotFoundError、JSONDecodeError、KeyError | 可包装为 RuntimeError，提供友好错误信息 |
| **数据验证错误** | ValueError（股票数不足、数据格式错误） | 必须保留原始类型，直接 `raise` |

**为何区分处理：**

```
1. 基础设施错误：调用方通常不区分具体原因，统一处理即可
   - 文件不存在、JSON 格式错误 → RuntimeError（调用方无需区分）
   
2. 数据验证错误：调用方可能需要区分处理
   - 股票数不足（ValueError） → 可能需要降级处理
   - 数据格式错误（ValueError） → 可能需要重试
   
3. 如果 ValueError 包装为 RuntimeError：
   - 调用方无法用 `except ValueError` 捕获
   - 无法区分"文件不存在"和"股票数不足"
```

**正确实现：**

```python
try:
    factor_df, return_df = load_data_from_cache()
    
    # 数据验证
    if factor_df['asset'].nunique() < min_stocks:
        raise ValueError(f"股票数量不足: {factor_df['asset'].nunique()} < {min_stocks}")
    
except FileNotFoundError as e:
    # 基础设施错误：包装为 RuntimeError，提供友好错误信息
    raise RuntimeError(f"缓存文件不存在，请检查路径: {e}") from e
    
except ValueError as e:
    # 数据验证错误：直接传递，保留原始异常类型
    raise  # 不包装，让调用方区分处理
```

**禁止行为：**

```python
# ❌ 禁止：数据验证错误包装为 RuntimeError
except ValueError as e:
    raise RuntimeError(f"数据验证失败: {e}") from e  # 调用方无法用 except ValueError 捕获

# ❌ 禁止：注释说"直接传递"但实际包装
except ValueError as e:
    # 直接传递，保留原始错误信息  ← 注释说"直接传递"
    raise RuntimeError(f"数据验证失败: {e}") from e  ← 实际包装
```

**注释与行为一致性要求：**

```
- 如果说"直接传递"，必须直接 raise，不包装
- 如果说"包装传递"，必须包装为 RuntimeError
- 注释与行为不符会导致维护时误解
```
```

---

### Task 3: 同步更新流程文档（1分钟）

**目标：** 版本递增 + 时间标注 + 更新内容

**文件：** `/home/admin/projects/factor_ic_analyzer/factor_ic/docs/ic_rsi_1d_flow.md`

**修改内容：**

1. **版本号递增：** v1.50 → v1.51

2. **生成时间更新：** 当前时间

3. **更新内容追加：**
```markdown
> 53. [v1.51] 修复 ValueError 异常处理：删除 RuntimeError 包装，直接 raise（遵循 PROJECT.md 异常处理类型保留规范）
> 54. [v1.51] 数据验证错误保留原始异常类型，调用方可用 except ValueError 捕获
> 55. [v1.51] 补充 PROJECT.md 「异常处理类型保留规范」章节：区分基础设施错误和数据验证错误
```

---

## 执行顺序

```
Task 1 → Task 2 → Task 3 → 验证
```

---

## 验证方式

1. 运行 `python factor_ic/ic_rsi_1d.py` 验证脚本正常执行
2. 测试 ValueError 是否正确抛出（股票数不足场景）
3. 确认注释与行为一致

---

## 修改文件清单

| 文件 | 操作 |
|------|------|
| `factor_ic/ic_rsi_1d.py` | 删除 RuntimeError 包装，改为直接 raise |
| `PROJECT.md` | 新增「异常处理类型保留规范」章节 |
| `factor_ic/docs/ic_rsi_1d_flow.md` | 版本递增、时间标注、更新内容追加 |