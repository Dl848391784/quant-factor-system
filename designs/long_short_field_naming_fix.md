# Design: 多空组合字段命名一致性修复

> 创建时间: 2026-06-05
> 状态: 待审核
> 触发条件: 2+ 文件修改（Design-First 流程）

---

## 1. 问题诊断

### 发现的警告
所有 17 个因子分层回测均报"多空组合缺少 xxx 字段"警告：
- `多空组合缺少 cumulative_return 字段`
- `多空组合缺少 sharpe_ratio 字段`
- `多空组合缺少 max_drawdown 字段`

### 根因分析

**三处定义不一致**：

| 来源 | 位置 | 字段名定义 |
|------|------|-----------|
| **MODULE.md 规范** | 第 150-155 行 | `ls_return_daily`, `ls_return_annual`, `sharpe_ratio` |
| **layered_backtest.py 实际输出** | 第 759-774 行 | `long_short_return_daily`, `long_short_return_annual`, `long_short_sharpe` |
| **factor_cli.py 检查代码** | 第 253-274 行 | 检查 `cumulative_return`, `sharpe_ratio`, `max_drawdown` |

**诊断类型**: **混合问题**（规范定义不一致 + 检查代码过时）

**影响**: 
- 17 个因子全部触发警告（因字段名不匹配，非数据缺失）
- 不影响核心流程（实际数据已正确计算）

---

## 2. 修复方案

### 方案选择

遵循 **最小改动原则**（代码已正确计算，只需统一命名）：

| 文件 | 操作 | 改动量 |
|------|------|--------|
| `backtest/MODULE.md` | 更第 150-155 行字段名以匹配实际代码 | ~5 行 |
| `backtest/common/factor_cli.py` | 移除过时检查警告（字段不存在于 long_short 结构） | ~20 行 |

**不修改**:
- `layered_backtest.py`（实际计算逻辑正确）
- 分层回测脚本（薄声明，无需改动）

---

## 3. 详细修改计划

### Step 1: 更新 MODULE.md 规范

**位置**: `backtest/MODULE.md` 第 150-155 行

**修改内容**: 将规范字段名更新为实际代码输出的字段名

```diff
-  "long_short": {
-    "long_return_daily": <float>, "long_return_annual": <float>,
-    "short_return_daily": <float>, "short_return_annual": <float>,
-    "ls_return_daily": <float>, "ls_return_annual": <float>,
-    "sharpe_ratio": <float>
-  },
+  "long_short": {
+    "long_return_daily": <float>, "long_return_annual": <float>,
+    "short_return_daily": <float>, "short_return_annual": <float>,
+    "long_short_return_daily": <float>, "long_short_return_annual": <float>,
+    "long_short_sharpe": <float>,
+    "long_short_volatility": <float>,
+    "turnover_long_avg": <float>, "turnover_short_avg": <float>,
+    "n_days": <int>, "n_days_total": <int>, "coverage": <float>
+  },
```

**理由**: 规范应反映实际输出结构，而非理想结构。代码已正确计算，规范应同步。

### Step 2: 修复 factor_cli.py 检查逻辑

**位置**: `backtest/common/factor_cli.py` 第 253-280 行

**修改内容**: 移除过时字段检查，保留实际存在的字段检查

**需要移除的检查**:
- `cumulative_return`（不属于 long_short 结构，属于 layer_stats）
- `max_drawdown`（不属于 long_short 结构，属于 layer_stats）

**需要修正的检查**:
- `sharpe_ratio` → `long_short_sharpe`（字段名更正）

**修改后代码**:
```python
# 多空组合收益（显式区分键缺失 vs 真实零值）
long_short = result.get('long_short') or {}
if long_short:
    # 多空夏普比率（键名修正）
    if 'long_short_sharpe' not in long_short:
        logger.warning("多空组合缺少 long_short_sharpe 字段")
    else:
        val = long_short['long_short_sharpe']
        if val is None:
            logger.warning("多空组合 long_short_sharpe 为 None")
        else:
            logger.info(f"多空组合夏普比率: {val:.2f}")
    
    # 多空日均收益（新增，规范定义的字段）
    if 'long_short_return_daily' in long_short:
        val = long_short['long_short_return_daily']
        if val is not None:
            logger.info(f"多空日均收益: {val*100:.4f}%")
else:
    logger.warning("未生成多空组合指标")
```

---

## 4. 不改动的说明

### 不修改 layered_backtest.py

**原因**: 
- 实际计算逻辑正确（第 759-774 行）
- `long_short_sharpe` 比 `sharpe_ratio` 更精确（明确是多空组合的夏普比率）
- `long_short_return_daily` 比 `ls_return_daily` 更清晰（避免缩写歧义）

### 不新增 cumulative_return / max_drawdown

**原因**:
- `cumulative_return` 和 `max_drawdown` 是 `layer_stats` 的字段（每层统计）
- `long_short` 是多空组合的**日均收益**和**夏普比率**
- 两者语义不同，不应混入同一结构

---

## 5. 验证检查

### Spec Compliance

```
□ MODULE.md 字段名与实际输出一致
□ factor_cli.py 检查字段名正确
□ 不影响现有分层回测脚本
```

### Code Quality

```
□ ruff check --fix .
□ ruff format .
□ pytest backtest/test_cases/
```

---

## 6. 预期结果

修复后：
- 17 个因子分层回测不再触发"缺少字段"警告
- MODULE.md 规范反映实际输出结构
- 日志输出正确显示多空组合夏普比率

---

## 7. 涉及规范

| 规范 | 位置 | 说明 |
|------|------|------|
| Design-First | AGENTS.md 第 24 行 | 2+ 文件需先提交 design.md |
| 输出结构统一 | PROJECT.md H2 | MODULE.md 应定义实际输出结构 |

---

*等待用户审核确认后执行*