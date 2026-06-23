# Design: 综合因子方向语义对齐到 positive（v2.47）

**日期**: 2026-06-23
**作者**: 云瑶
**触发**: 用户 push back —— v2.46 require_positive_ic=True 实验后报告 composite 全负 + 8 个 IC>0 因子被取反，反直觉。深查链路发现"取反到 negative"和"取反到 positive"数学完全镜像对称，但前者反直觉。
**遵循**: AGENTS.md 硬规则 #12（Design-First）、第一性原理元规则、superpowers-workflow

---

## 1. 第一性原理推导

对每个因子 i 定义"看好程度"：

```
signal_i = sign(IC_i) × z_i
```

- IC_i > 0 → signal_i = +z_i（z 大 = 看好）
- IC_i < 0 → signal_i = −z_i（z 小 = 看好）

不论原始 IC 方向，signal 语义永远是 **"signal 大 = 看好"**。

加权和：

```
composite = Σ w_i × sign(IC_i) × z_i = Σ w_i × signal_i
```

**composite 方向永远为 positive（值大 = 好）**，与各因子 IC 分布无关。
不需要"多数派/全集/用户"决定方向 —— 它是数据决定的、唯一的。

---

## 2. 旧逻辑（v2.13~v2.46）做了什么

```python
# composite_runner.py L499-534 + stock_selector.py L1104-1163
if ic_mean_val > 0:
    factor_df[std_col] = -factor_df[std_col]   # 取反到 negative
direction_map[name] = "positive"
# 最终: factor_direction = "negative"，composite 小 = 好
```

数学镜像对称，本身**没有计算错误**。问题在于：

| # | 问题 | 后果 |
|---|---|---|
| 1 | 反直觉：IC>0（看好上涨）→ 取反 → composite 负 = 选中 | 用户读 report 困惑 |
| 2 | `factor_direction` 永远 'negative'，但 4 个 composite 入口各自硬编码 | 冗余 + 易写错 |
| 3 | stock_selector 升序选 Top（小=好）反直觉 | 认知负担 |
| 4 | 当所有因子 IC>0 全被取反，报告里 8 个因子 z-score 全负，掩盖了"原始 z 全正"这个真实信号 | 排查困难 |

---

## 3. 新逻辑（v2.47）

```python
if ic_mean_val < 0:
    factor_df[std_col] = -factor_df[std_col]   # 取反到 positive
direction_map[name] = "negative"  # 记录原始 IC 方向
# 最终: factor_direction = "positive"，composite 大 = 好
```

**关键**：`direction_map` / `flipped_factors` **语义反转**：
- 旧 `flipped_factors` = 原 IC>0 被翻到 negative 的因子
- 新 `flipped_factors` = 原 IC<0 被翻到 positive 的因子

为了消除歧义，**新增字段 `aligned_to: "positive"`**（v2.47 标记），下游消费者可据此判断 flipped 含义。

---

## 4. 影响范围（穷举）

### 4.1 代码改动

| # | 文件 | 改动 | 难度 |
|---|---|---|---|
| C1 | `comprehensive_factor/common/composite_runner.py` L499-534 | `if ic_mean > 0` → `if ic_mean < 0`；日志文案"统一负向"→"统一正向"；新增 `aligned_to="positive"` 输出 | 易 |
| C2 | `comprehensive_factor/common/composite_runner.py` L128 | `self.factor_direction = "negative"` → `"positive"` | 易 |
| C3 | `comprehensive_factor/stock_selector.py` L1104-1163 | 同 C1，两条路径（composite 读取 + ic_results 回退）都改 | 易 |
| C4 | `comprehensive_factor/composite_equal_weight_1d.py` L57 | `factor_direction: str = "negative"` → `"positive"` | 易 |
| C5 | `comprehensive_factor/composite_ic_weight_1d.py` L57 | 同 C4 | 易 |
| C6 | `comprehensive_factor/composite_icir_weight_1d.py` L57 | 同 C4 | 易 |
| C7 | `comprehensive_factor/composite_rolling_icir_weight_1d.py` L66 | 同 C4 | 易 |
| C8 | `comprehensive_factor/composite_*_weight_1d.py` 4 个文件 long/short_layers | 反向因子 [1,2]/[4,5] → 正向因子 [4,5]/[1,2] | 易 |
| C9 | `comprehensive_factor/stock_selector.py` L125 | `factor_direction: str = "negative"` → `"positive"`（comment 同步）| 易 |
| C10 | `summary/generate_factor_summary_report.py` L1814-1818 / L2160-2164 / L2680 / L2186-2226 | 文案"已取反统一负向语义"→"已对齐统一正向语义"；`*` 标记从 flipped 改为 aligned_factor；comment 调整 | 中 |
| C11 | `comprehensive_factor/MODULE.md` M56 + 表 N | 规范文本：取反到 negative → 对齐到 positive；增加版本历史 v2.47 | 中 |
| C12 | `comprehensive_factor/docs/composite_runner_direction_unify_flow.md` | 流程图文本对齐 | 易 |

### 4.2 测试改动

| # | 文件 | 改动 |
|---|---|---|
| T1 | `comprehensive_factor/test_cases/test_direction_unify.py` | 断言反转：`flipped` 改为 IC<0 因子；`aligned_to == "positive"` |
| T2 | `comprehensive_factor/test_cases/test_composite_*.py` 涉及 composite_value 符号断言 | 反转符号 |
| T3 | `comprehensive_factor/test_cases/test_stock_selector*.py` 涉及 ascending 断言 | 改为 descending |
| T4 | `summary/test_cases/test_generate_factor_summary_report.py` 涉及文案 | 同步 C10 |

### 4.3 不动的地方（已确认）

| # | 文件 | 理由 |
|---|---|---|
| K1 | `backtest/common/layered_backtest.py` | 已支持 positive/negative，会自动根据传入的 `factor_direction` 调整 Layer 选择 |
| K2 | `comprehensive_factor/common/weight_engine.py` | 用 `abs(ic_mean)` / `abs(icir)`，方向无关 |
| K3 | `factor_ic/` 单因子 IC | 单因子方向语义不变，不受影响 |
| K4 | `data_fetchers/` | 数据生成不涉及方向 |

### 4.4 现有 result/ 文件影响

`comprehensive_factor/result/composite_*.json` + `stock_selection_result.json` 必须**重新生成**（旧文件的 composite_value 符号与新逻辑相反，下游 summary 报告会读错）。重跑 pipeline stage 4 + 后续 stages 即可。

---

## 5. 数学验证（确保数值等价）

设旧逻辑 composite_old，新逻辑 composite_new，证明：

```
composite_new = -composite_old  (假设权重相同)
```

**旧**：所有因子取反到 negative。设原始 z 集合 {z_i}，IC sign 集合 {s_i}：
- s_i = +1 时 std' = −z_i，s_i = −1 时 std' = z_i
- composite_old = Σ w_i × std'_i = Σ w_i × (−s_i × z_i) = −Σ w_i × s_i × z_i

**新**：所有因子对齐到 positive。
- s_i = +1 时 std' = z_i，s_i = −1 时 std' = −z_i
- composite_new = Σ w_i × std'_i = Σ w_i × (s_i × z_i) = Σ w_i × s_i × z_i

→ **composite_new = −composite_old** ✓

**选股结果不变**：旧"升序选最小" ≡ 新"降序选最大"。验证：旧选中股集合 = {top-N argmin(composite_old)} = {top-N argmax(−composite_old)} = {top-N argmax(composite_new)} = 新选中股集合。

**Layered backtest 结果不变**：Layer 1 (低 composite_old) ≡ Layer 5 (高 composite_new)，旧 long_layers=[1,2] ≡ 新 long_layers=[4,5]，多空组合收益数值完全相同。

→ **POC -50% 年化预测不变**（这是因子族本身的问题，方向修复不解决，但报告会变直观）。

---

## 6. 风险 & 回滚

| 风险 | 概率 | 缓解 |
|---|---|---|
| 漏改某处导致下游用反方向消费 composite | 中 | grep 全仓库 `factor_direction.*=.*"negative"` 确保零残留；跑 pytest 全套 |
| 旧 result/*.json 与新代码不兼容 | 高 | Execute 阶段重跑 pipeline stage 4+，验证报告符号正确 |
| MODULE.md M56 与代码不同步 | 中 | C11 强制同步，commit 引用 M56 行号 |
| baseline_20260621/ 旧文件保留 | 低 | 不改 baseline（历史快照），但新跑覆盖 result/ |

**回滚**：本设计是数学镜像对称，一行符号翻转可回滚（git revert 单 commit）。

---

## 7. 执行顺序（superpowers-workflow Plan→Execute→Review）

1. **审 design** ← 现在等用户
2. **Execute**（建议 3 个 commit）：
   - Commit 1（核心 + 测试）：C1+C2+C3+C9+T1+T2+T3（共 ~80 行）
   - Commit 2（4 个 composite 入口 + long/short_layers）：C4-C8（~50 行）
   - Commit 3（summary 文案 + 测试 + MODULE.md + docs）：C10+C11+C12+T4（~60 行）
3. **Review**：每 commit 前 ruff check/format + pytest 相关测试
4. **End-to-end 验证**：跑 pipeline `--start-stage 4`，读 summary 报告验证 composite_value 符号 + flipped_factors 语义正确
5. **DONE**：commit 不 push

---

## 8. 验收标准

- [ ] composite_value 符号 = `+sum(w × sign(IC) × z)` 形态（多数为正）
- [ ] stock_selection_result.json `factor_values_std` 含正值（不再全负）
- [ ] summary 报告"方向处理说明"显示"已对齐统一正向语义"
- [ ] 全 pytest 通过
- [ ] ruff check 0 error
- [ ] grep 验证：`factor_direction.*"negative"` 仅在历史注释 / baseline_20260621/ 内残留
- [ ] commit 消息引用 AGENTS.md #12 + MODULE.md M56

---

## 9. 后续（不在本 PR）

- decision_card.py close_position_5d 用当日 high/low 的 bug（用户已确认是另一个独立 bug，下次单独修）
- 实战观察 v2.45 真实净值是否如 POC 预测的 -50%
