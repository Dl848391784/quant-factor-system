# ic_bollinger_pb_1d.py 全面优化计划

> 创建时间：2026-05-19
> 目标：参照 ic_rsi_1d.py v1.52 规范进行全面优化

---

## 问题诊断

| # | 问题 | 类型 | 说明 |
|---|------|------|------|
| 1 | 异常处理类型错误 | 代码 bug | ValueError 被 RuntimeError 包装，应保留原始类型 |
| 2 | total_days 计算错误 | 代码 bug | 使用 len(dates) 而非 raw_metadata['total_days'] |
| 3 | avg_stocks_period 缺失 | 规范遗漏 | 无法感知口径范围 |
| 4 | 增量模式缺失 | 功能缺失 | 只有全量计算，无 skip/incremental/full 三种模式 |
| 5 | 流程文档缺失 | 文档缺失 | 无 ic_bollinger_pb_1d_flow.md |

---

## 修复方案

参照 ic_rsi_1d.py v1.52 实现，全面重构 ic_bollinger_pb_1d.py：

1. **添加增量模式基础设施**
   - `_full_recalculate()` 全量计算函数
   - `_incremental_update()` 增量更新函数
   - 使用 check_data_completeness() 判断模式

2. **修复异常处理**
   - 分层捕获：FileNotFoundError/JSONDecodeError/KeyError/ValueError
   - ValueError 直接 raise，不包装

3. **修复 total_days 计算**
   - 全量：raw_metadata['total_days']
   - 增量：max(raw_metadata['total_days'], factor_df_full['date'].nunique())

4. **添加 avg_stocks_period 字段**
   - 包含 start、end、description

5. **创建流程文档**
   - ic_bollinger_pb_1d_flow.md

---

## 任务清单

### Task 1: 重构 ic_bollinger_pb_1d.py（核心任务）

**修改内容：**
- 添加 DEFAULT_MIN_STOCKS 常量
- 重构 load_data_from_cache() 添加异常分层捕获
- 添加 _full_recalculate() 全量计算函数
- 添加 _incremental_update() 增量更新函数
- 重构 generate_bollinger_pb_1d_ic_data() 为主入口函数
- 修复 calculate_daily_ic_series() 的 total_days 计算
- 添加 avg_stocks_period 字段

---

### Task 2: 补充 PROJECT.md 相关规范

**新增章节：** 布林带%B 因子规范（如需要）

---

### Task 3: 创建流程文档

**文件：** factor_ic/docs/ic_bollinger_pb_1d_flow.md

**内容：** 参照 ic_rsi_1d_flow.md 格式

---

## 执行顺序

Task 1 → Task 2 → Task 3 → 验证