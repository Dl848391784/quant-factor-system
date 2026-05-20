# ic_bollinger_pb_1d.py 全面优化计划

> 创建时间：2026-05-19
> 参考模板：ic_rsi_1d.py v1.52
> 目标：修复代码 bug + 补充规范 + 添加增量模式 + 创建流程文档

---

## 问题诊断

### 已识别问题

| # | 问题位置 | 问题类型 | 说明 |
|---|---------|---------|------|
| 1 | 第470-471行 | 代码 bug | 异常处理：所有异常被包装为 RuntimeError |
| 2 | 第401行 | 代码 bug | total_days 使用 len(dates) 而非 raw_metadata['total_days'] |
| 3 | 第400-404行 | 规范遗漏 | sample_stats 缺少 avg_stocks_period 子字段 |
| 4 | 全文件 | 功能缺失 | 没有增量模式（skip/incremental/full） |
| 5 | docs 目录 | 文档缺失 | 没有 ic_bollinger_pb_1d_flow.md 流程文档 |

---

## 修复方案

### 方案概述

参照 ic_rsi_1d.py v1.52 实现，进行全面优化：

1. **重构主函数架构**：拆分为 `_full_recalculate()` + `_incremental_update()` + 主入口函数
2. **修复代码 bug**：异常处理、total_days 计算
3. **补充规范字段**：avg_stocks_period、update_mode、icir_stability 等
4. **创建流程文档**：ic_bollinger_pb_1d_flow.md

---

## 任务清单

### Task 1: 重构 load_data_from_cache 函数（2分钟）

**目标：** 添加异常处理类型保留规范（参照 ic_rsi_1d.py 第640-656行）

**修改位置：** 第459-471行

**修改内容：**
- 分层捕获异常：FileNotFoundError → KeyError → ValueError → Exception
- ValueError 直接 raise，不包装（遵循 PROJECT.md 异常处理类型保留规范）
- 其他异常包装为 RuntimeError，提供友好错误信息

---

### Task 2: 修复 calculate_daily_ic_series total_days 计算（1分钟）

**目标：** 修复 total_days 使用 raw_metadata 而非 len(dates)

**修改位置：** 第322-411行（函数签名需添加 raw_metadata 参数）

**修改内容：**
1. 函数签名添加 `raw_metadata: dict` 参数
2. sample_stats.total_days 改用 `raw_metadata['total_days']`
3. 添加 avg_stocks_period 子字段
4. 添加 icir_stability 字段（参照 ic_rsi_1d.py 五维度判断）

---

### Task 3: 添加 _full_recalculate 函数（5分钟）

**目标：** 拆分全量计算逻辑为独立函数

**参照：** ic_rsi_1d.py 第355-394行 `_full_recalculate`

**新增函数：**
```python
def _full_recalculate(
    factor_df_full: pd.DataFrame,
    return_df_full: pd.DataFrame,
    raw_metadata: dict,
    n: int = 20,
    k: float = 2.0,
    min_stocks: int = DEFAULT_MIN_STOCKS,
    output_file: Path = None
) -> dict:
    """全量计算布林带%B IC（遵循 PROJECT.md 全量计算规范）"""
```

---

### Task 4: 添加 _incremental_update 函数（10分钟）

**目标：** 添加增量更新逻辑

**参照：** ic_rsi_1d.py 第397-483行 `_incremental_update`

**新增函数：**
```python
def _incremental_update(
    factor_df_full: pd.DataFrame,
    return_df_full: pd.DataFrame,
    existing_dates: List[str],
    missing_dates: List[str],
    raw_metadata: dict,
    n: int = 20,
    k: float = 2.0,
    min_stocks: int = DEFAULT_MIN_STOCKS,
    output_file: Path = None
) -> dict:
    """增量更新布林带%B IC（遵循 PROJECT.md 增量更新规范）"""
```

---

### Task 5: 重构主入口函数（3分钟）

**目标：** 重构 generate_bollinger_pb_1d_ic_data 为模式选择入口

**参照：** ic_rsi_1d.py 第486-568行主入口逻辑

**修改内容：**
1. 添加 DEFAULT_MIN_STOCKS 常量
2. 调用 check_data_completeness 判断模式
3. 根据 mode 调用 _full_recalculate 或 _incremental_update
4. 返回结果添加 update_mode 字段

---

### Task 6: 添加五维度判断完整结构（2分钟）

**目标：** 补充 icir_stability 和 ic_distribution_consistency 字段

**参照：** ic_rsi_1d.py 第306-320行五维度判断

---

### Task 7: 创建流程文档（5分钟）

**目标：** 创建 factor_ic/docs/ic_bollinger_pb_1d_flow.md

**参照：** ic_rsi_1d_flow.md 结构

**文档结构：**
```
# Bollinger_PB_1D IC 计算流程文档

> 生成时间: 2026-05-19
> 审阅版本: v1.00

## Step 0: 函数调用关系
## Step 1: 数据完整性检查
## Step 2: 数据加载
## Step 3: 布林带%B 因子计算
## Step 4: IC 计算
## Step 5: 五维度判断
## Step 6: 增量更新流程
```

---

## 执行顺序

```
Task 1 → Task 2 → Task 3 → Task 4 → Task 5 → Task 6 → Task 7 → 验证
```

---

## 验证方式

1. 运行 `python factor_ic/ic_bollinger_pb_1d.py` 验证脚本正常执行
2. 测试增量模式（运行两次，第一次全量，第二次 skip）
3. 检查输出 JSON 是否包含所有必需字段
4. 验证流程文档内容完整

---

## 修改文件清单

| 文件 | 操作 |
|------|------|
| `factor_ic/ic_bollinger_pb_1d.py` | 全面重构，添加增量模式 |
| `factor_ic/docs/ic_bollinger_pb_1d_flow.md` | 新建流程文档 |

---

## 预估工作量

- Task 1-6（代码修改）：约 25 分钟
- Task 7（流程文档）：约 5 分钟
- 验证：约 5 分钟
- 总计：约 35 分钟