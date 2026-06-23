# 单因子筛选：IC 必须为正（require_positive_ic）

**Author**: 云瑶
**Date**: 2026-06-23
**Status**: implementing
**Related**: AGENTS.md 硬规则 #5（因子方向），PROJECT.md 数据驱动原则

---

## 1. 背景

### 1.1 用户动机

用户假设："阴跌股入选 Top 30" 的根因是反转族因子（原始 IC 负 → composite 取反 → 给低位 / 阴跌股高分）。
希望验证：**只保留原始 IC 为正的因子**（直接做多动量延续方向）能否避开阴跌。

### 1.2 POC 先验数据（temporary/exp_positive_only_factors.py，2026-06-23 已跑）

| 指标 | 8 个 IC>0 因子方案 | v2.44 baseline |
|---|---|---|
| 全期总收益 | -76.08% | +X% |
| 年化 | -50.35% | ≈+18% |
| 夏普 | -1.90 | +0.74 |
| OOS 年化 | -63.00% | +14.7% |
| 阴跌占比 (return_5d<-3%) | 32.0% | 类似 |

**POC 结论**：方案预期亏损严重，阴跌占比未改善。已告知用户，用户**仍坚持工程实施**以"真跑 run_pipeline 看数据"。

### 1.3 工程价值

不论结果好坏，新增 `require_positive_ic` 开关是一个 **可重用的实验性配置项**：
- 后续做"动量风格 vs 反转风格" A/B 实验都需要它
- 默认 False = 线上零影响
- 用户可通过 thresholds dict 灵活启用

---

## 2. 改动范围

**单文件修改**：`comprehensive_factor/common/factor_selector.py`

| 区段 | 改动 |
|---|---|
| `DEFAULT_THRESHOLDS` (L69-79) | 新增 `"require_positive_ic": False` |
| `INTERACTION_THRESHOLDS` (L91-101) | **不加**（merge 时会继承主 dict 的 False，需启用时只改主 dict） |
| `validate_factor` (L282+) | IC 均值检查段后追加"正 IC 硬门槛"分支 |
| 测试 | 新增 `test_factor_selector_positive_ic.py`（3 个 case） |

**不动的代码**：
- `composite_runner.py` 的 `direction_map` 生成逻辑
- `stock_selector.py` 的取反逻辑
- 下游所有模块

设计承诺：开关默认 False → 行为字节级与 v2.44 一致。

---

## 3. 技术方案

### 3.1 What

`thresholds["require_positive_ic"] = True` 时，校验函数对 `ic_mean < 0` 的因子直接判定为 invalid（**不可豁免**），原因字符串：
```
ic_mean=-0.0152<0（require_positive_ic=True）
```

### 3.2 How

在 `validate_factor` (L362-414) IC 均值检查段**之后**插入：

```python
# v2.45: 正 IC 硬门槛（require_positive_ic）
# 用途：动量风格实验 / 排除反转族因子
# 设计：硬门槛不可豁免（豁免会破坏"只用正向因子"的核心约束）
require_positive_ic = thresholds.get("require_positive_ic", False)
if require_positive_ic and ic_mean is not None and ic_mean < 0:
    reasons.append(f"ic_mean={ic_mean:+.4f}<0（require_positive_ic=True）")
    logger.debug("因子 %s: ic_mean=%+.4f<0, 被 require_positive_ic 过滤", factor_name, ic_mean)
```

**位置选择**：放在 IC 均值检查段后、p-value 检查段前（L416 之前）。
**理由**：
- 在 IC 均值豁免逻辑**之后** → 即使因子触发反向豁免，仍会被 positive_ic 过滤掉
- 在其他指标检查之前 → 早失败原则（reasons 排在前面，便于阅读）

### 3.3 Don't（强制不做）

- ❌ 不加豁免逻辑：positive_ic = 用户主张的硬约束，反向豁免会让 IC 略负但回测强的因子漏网
- ❌ 不动 `_get_thresholds_for_factor`：交互因子族 merge 会继承主 dict 的 `require_positive_ic`，开启后交互因子族里 IC<0 的也会被剔除
- ❌ 不改 `DEFAULT_THRESHOLDS` 默认值（保持 False）：避免影响线上 v2.44 行为
- ❌ 不暴露 CLI 参数：保持 thresholds dict 单一配置源（用户可通过自定义 thresholds 启用）

### 3.4 启用方式（给用户的接口）

用户跑 run_pipeline 时通过 thresholds 注入。最简方式：临时编辑 `DEFAULT_THRESHOLDS["require_positive_ic"] = True` 跑一次实验，跑完改回 False。或者用户层封装：

```python
from comprehensive_factor.common.factor_selector import DEFAULT_THRESHOLDS, select_factors

custom = dict(DEFAULT_THRESHOLDS)
custom["require_positive_ic"] = True
select_factors(thresholds=custom, ...)
```

---

## 4. 影响评估

| 维度 | 默认 (False) | 启用 (True) |
|---|---|---|
| v2.44 在线行为 | ✅ 零改动 | 改变（按用户意图） |
| 16 → N 个 selected | 不变 | 预计剩 ≤8 个（仅 ic_mean>0） |
| 测试 329/329 | 不变 | 新增 3 case |
| 数据契约 | 不变 | selection_reason 新增字符串模式 |

**LSP 误报**：用户已知 `temporary/exp_positive_only_factors.py` 的 LSP 误报（pandas 类型推断），不阻塞。

---

## 5. 验证步骤

### 5.1 单元测试（必跑）

1. `require_positive_ic=False`（默认）+ IC<0 因子 → valid=True（行为不变）
2. `require_positive_ic=True` + IC<0 因子 → valid=False, reasons 含 `ic_mean=...<0`
3. `require_positive_ic=True` + IC<0 + 高夏普高单调 → valid=False（**不被豁免**）

### 5.2 回归测试

`pytest comprehensive_factor/test_cases/ -q` → 329/329 通过（默认 False，行为不变）

### 5.3 实战验证（用户跑）

用户编辑 thresholds 后跑 `run_pipeline`，应看到：
- `selection_result.selected` 数量从 16 降到约 8
- 被淘汰的因子在 `invalid` 中，原因含 `ic_mean=...<0（require_positive_ic=True）`
- Top 30 表现预计接近 POC 的 -50% 年化（这是 POC 已预测的）

---

## 6. 回滚

如需回滚：将 `DEFAULT_THRESHOLDS["require_positive_ic"]` 改回 False 即可（如果用户启用过的话，否则无需操作）。代码逻辑保留作为后续 A/B 工具。
