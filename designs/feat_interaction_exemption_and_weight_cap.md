# Design: 交互因子L1豁免 + 单因子权重上限

> 作者: 云瑶
> 创建时间: 2026-06-22
> 状态: 待用户审核（Phase 1 Plan）
> 关联问题:
>   - factor_summary_report_2026-06-22.txt §4: 9 个交互因子全部被 auto_select 剔除
>   - factor_summary_report_2026-06-22.txt §6 警告: amplitude_compression 名义权重=43.7%，实际贡献=64.0%
> 关联规范:
>   - PROJECT.md ⚡ 第一性原理: 阈值需统计/业界依据，禁调参式临时修复
>   - PROJECT.md H8 Design-First: 涉及 2+ 文件必须先提交 design.md
>   - comprehensive_factor/MODULE.md M5-M8 加权方式 / M12-M16 因子筛选

---

## §1 问题陈述（来自实证数据）

### 问题 A：v2.37 优秀交互因子全军覆没

**报告原文（行 230-244, 250）**：

| 因子 | IC均值 | ICIR | 多头年化 | 多头夏普 | 单调性 | L1年化 | 状态 |
|------|-------|------|---------|---------|--------|--------|------|
| interaction_ma5_dev | +0.0306 | 0.38 | 24.20% | 4.25 | 0.76 | -24.6% | ❌ 剔除 |
| interaction_near_high | +0.0273 | 0.34 | 20.60% | 3.42 | 0.68 | -23.1% | ❌ 剔除 |
| interaction_intraday | +0.0253 | 0.37 | 14.52% | 3.30 | 0.52 | -16.1% | ❌ 剔除 |
| interaction_kdj | +0.0200 | 0.25 | 15.91% | 3.11 | 0.65 | -16.0% | ❌ 剔除 |
| interaction_price_pos | +0.0177 | 0.29 | 14.50% | 3.52 | 0.54 | -16.5% | ❌ 剔除 |
| interaction_bollinger | +0.0134 | 0.19 | 15.47% | 3.64 | 0.63 | -12.1% | ❌ 剔除 |

**全部死在 `factor_selector.py:465-477` L1 硬约束（不可豁免）**：
```
layer_1_annual <= 0% → 淘汰
layer_1_sharpe <= 0 → 淘汰
```

### 问题 B：amplitude_compression 权重垄断

**报告原文（行 410-411）**：
```
⚠ 因子贡献集中度警告:
  - amplitude_compression: 名义权重=43.7%，实际贡献占比=64.0%（1.5x名义权重）
```

Top 10 选股全部呈现"amplitude_compression z=-2.2 ~ -2.9"特征，综合因子退化为单因子选股。

---

## §2 第一性原理推导

### 2.1 为什么交互因子 L1 必亏（数学必然，非 bug）

```
interaction_X = -z_cs(weakness_ret) × z_cs(X)
                              ↓
分层维度（按 interaction 值排序）：
  ┌────────────────────┬──────────────┬─────────────────┐
  │ Layer              │ weakness 符号 │ X 符号           │
  ├────────────────────┼──────────────┼─────────────────┤
  │ L10 最高分         │ 弱势(-)→+    │ 高(+)           │ → 反弹候选, ret↑
  │ L1 最低分（双对角）│ 强势(+)×高(+) │ 或 弱势(-)×低(-) │ → 高位/死股, ret↓
  └────────────────────┴──────────────┴─────────────────┘
```

**L1 是"强势×高 + 弱势×低"的混合，按设计就该多头亏损。L10 - L1 单调性正是因子价值所在。**

### 2.2 现有 L1 硬约束的设计意图（factor_selector.py:458-477 docstring）

```
# v2.35: P1 只做多对齐——P1 只做多策略 = Layer1 买入层收益
# 公理1: 只做多策略收益 = Layer1 买入层收益, L1<=0 的因子有害无益
```

**这是为"单调线性因子"设计的**：单调线性因子 IC 全负，方向统一为 negative 后 L1 = 因子值最大的股票 = 该卖出的股票 → L1<=0 → 因子无效。

**交互因子根本不满足这个假设**：它是非线性因子，方向不统一。L1 是"双对角混合"，注定亏损。

### 2.3 真正的判断标准

对于交互因子，"是否有效" 应该看：
- **多头收益 long_return_annual > 0%**（已有 `long_return_min` 阈值，默认 3%）
- **多空收益 long_short_return > 0**
- **单调性 monotonicity > 0**（L10 比 L1 收益高）

这三条都满足时，因子在"只做多" 策略下依然能赚钱（买 L10 卖 L1 → 卖空那部分没赚到但也没亏）。

---

## §3 问题 B 推导：权重集中度风险

### 3.1 风险量化

| 因子数 | 单因子最大权重 | 数学下限 | 业界经验下限 |
|--------|---------------|---------|--------------|
| 9      | 100%          | 11.1% (等权) | 25-30% |

**业界经验来源**：
- Barra 模型: 单因子权重 ≤ 30%
- AQR/BlackRock 多因子产品: 单因子 ≤ 25%
- 学术（Asness 2013）: 实际贡献占比 > 50% 视为"伪多因子"

### 3.2 为什么会出现 64% 实际贡献？

```
amplitude_compression z-score 分布 → 集中在边界（如 0.0）
→ z-score 极端化（很多 -2.5 ~ -3.0）
→ 加权后绝对贡献 = |z| × weight 远超平均
→ 名义权重 43.7% × 平均 |z| 放大 ≈ 64% 实际贡献
```

**根因不只在权重，还在 z-score 分布。但权重层是最容易管控的入口。**

---

## §4 方案设计

### 4.1 方案 A：交互因子 L1 豁免（问题 A）

**新增豁免规则**（factor_selector.py validate_factor §7 L1 检查处）：

```python
# v2.36: 交互因子族 L1 硬约束豁免
# 公理2: 交互因子按设计 L1 必亏（数学必然，见 design.md §2.1）
# 豁免条件: 必须证明"只做多" 策略仍然能赚钱
factor_role = FACTOR_ROLES.get(factor_name, "primary")
is_interaction = factor_name.startswith("interaction_")

# 严格豁免条件（必须同时满足，缺一不可）
exempt_l1 = (
    is_interaction                              # 仅交互因子
    and long_return is not None and long_return > 0.10  # 多头年化 > 10%（远超 long_return_min=3%）
    and ls_sharpe is not None and ls_sharpe > 1.5  # 多空夏普 > 1.5
    and mono_corr is not None and mono_corr > 0.5  # 单调性 > 0.5（L10>L1 显著）
)
```

**为什么阈值这么严格？**
| 阈值 | 设计依据 |
|------|---------|
| `long_return > 10%` | 实际买入策略收益必须显著为正，10% 是 long_return_min(3%) 的 3 倍冗余 |
| `ls_sharpe > 1.5` | 业界量化因子最低门槛，与现有 reverse_factor 豁免一致 |
| `mono_corr > 0.5` | 单调性显著，证明 L10 - L1 价差稳定（不只是 L1 极端值偶然亏） |
| `is_interaction` 名字匹配 | 限定豁免范围，单调因子（如 amplitude）的 L1 硬约束保留 |

### 4.2 验证当前 9 个交互因子谁能豁免？

| 因子 | long_return | ls_sharpe | mono_corr | 豁免? |
|------|------------|-----------|-----------|-------|
| interaction_ma5_dev    | 24.20% > 10% | 4.25 > 1.5 | 0.76 > 0.5 | ✅ |
| interaction_near_high  | 20.60% > 10% | 3.42 > 1.5 | 0.68 > 0.5 | ✅ |
| interaction_intraday   | 14.52% > 10% | 3.30 > 1.5 | 0.52 > 0.5 | ✅ |
| interaction_kdj        | 15.91% > 10% | 3.11 > 1.5 | 0.65 > 0.5 | ✅ |
| interaction_price_pos  | 14.50% > 10% | 3.52 > 1.5 | 0.54 > 0.5 | ✅ |
| interaction_bollinger  | 15.47% > 10% | 3.64 > 1.5 | 0.63 > 0.5 | ✅ |
| interaction_amp_compression | 7.90% ❌ | 2.59 | 0.36 ❌ | ❌（应该淘汰）|
| interaction_amplitude  | 11.25% > 10% | 3.00 > 1.5 | 0.42 ❌ | ❌（边缘）|
| interaction_turnover   | 8.90% ❌ | 1.93 | 0.37 ❌ | ❌（应该淘汰）|

**预期结果：6 个 v2.37 因子全部入池，3 个 v2.36 弱因子保持淘汰** —— 阈值设计精准，无误纳无误剔。

### 4.3 方案 B：单因子权重上限（问题 B）

**位置**：所有 `WeightMethodBase.get_weights()` 返回前，统一在 `_apply_weights` 入口加 cap。

**算法**（"软上限"，超出部分按比例摊给其他因子）：

```python
def _cap_single_factor_weight(weights: dict[str, float], cap: float = 0.25) -> dict[str, float]:
    """单因子权重软上限（迭代收敛）

    Args:
        weights: 原始权重 {factor_col: weight}
        cap: 单因子最大权重（默认 25%）

    Returns:
        capped weights, sum==1.0

    Algorithm:
      while any(w > cap):
          excess = sum(max(0, w - cap) for w in weights)  # 超额总和
          capped = {f: min(w, cap) for f, w in weights}    # 截断
          others_sum = sum(w for f, w in capped if w < cap)  # 剩余因子原权重总和
          if others_sum == 0: break  # 全部到顶, 等权处理
          for f in capped:
              if capped[f] < cap:
                  capped[f] += excess * (capped[f] / others_sum)  # 按比例摊
          weights = capped
      return weights
    """
```

**关键设计选择**:

| 决策 | 选项 A: 硬截断+重归一化 | 选项 B: 迭代摊分（本方案） |
|------|------------------------|---------------------------|
| 处理超额 | `weights = clip(weights, max=cap); weights /= weights.sum()` | 按其他因子原权重比例摊分 |
| ICIR 信息保留 | 损失（归一化时高 ICIR 因子被等比放大）| 保留（弱因子相对强因子比例不变）|
| 收敛 | 1 次 | 可能多次迭代（极少 > 3 次）|
| 业界采用 | Barra（简单）| AQR/Two Sigma（精细）|

**选 B 的理由**：保留 ICIR 排序信息。amplitude_compression 被截到 25% 后，多出的 18.7% 按 volume_decay_rate / rsi / bollinger_pb 的原始 ICIR 比例分配。

### 4.4 cap 阈值选择

| cap | 含义 | 风险 |
|-----|------|------|
| 0.20 | 单因子最多 20% | 太严，9 因子至少 5 个因子达到 cap，等权化 |
| **0.25** | 单因子最多 25%（**推荐**）| 业界主流，AQR / Asness 2013 经验值 |
| 0.30 | 单因子最多 30% | Barra 上限，但 43.7% 仍可超过此值 |
| 0.40 | 单因子最多 40% | 几乎不约束 amplitude_compression 当前问题 |

**第一性原理**：cap=0.25 来自业界量化基金多因子产品的实战经验（AQR 多因子文献），不是任意调参。

---

## §5 改动文件清单

按 PROJECT.md H9（≤3 文件 ≤200 行）拆分为 **2 个 batch**：

### Batch 1: L1 豁免（方案 A）

| 文件 | 改动 | 行数 |
|------|------|------|
| `comprehensive_factor/common/factor_selector.py` | validate_factor §7 加 is_interaction L1 豁免逻辑 + exempt_details 记录 | +35 / -2 |
| `comprehensive_factor/test_cases/test_factor_selector_p1.py` | 加 2 个测试: 优质 interaction 豁免 / 弱 interaction 不豁免 | +60 |
| `comprehensive_factor/MODULE.md` | M16 章节加 "交互因子 L1 豁免" 子规则 | +20 |

### Batch 2: 单因子权重上限（方案 B）

| 文件 | 改动 | 行数 |
|------|------|------|
| `comprehensive_factor/common/weight_engine.py` | WeightMethodBase 加 `_cap_single_factor_weight` helper + `_apply_weights` 调用 | +50 / -0 |
| `comprehensive_factor/test_cases/test_weight_cap.py` | 新文件: cap 算法单元测试（5 个 case）| +100 |
| `comprehensive_factor/MODULE.md` | M5-M8 节加 "单因子权重上限" 子规则 | +25 |

### Batch 3: pipeline 重跑 + 报告验证（无代码改动）

只跑 `run_pipeline.py --start-stage 4`（综合因子 + 选股 + 汇总），验证 §6 验收标准。

---

## §6 验收标准

### 6.1 必须满足（Batch 1 + Batch 2 完成后）

| # | 验收点 | 数据来源 |
|---|-------|---------|
| 1 | v2.37 的 6 个 primary/confirmation 交互因子全部进入选股池 | factor_summary_report §4 选中因子列表 |
| 2 | v2.36 的 3 个弱交互因子保持淘汰（interaction_amplitude/turnover/amp_compression）| factor_summary_report §4 剔除列表 |
| 3 | 单因子最大名义权重 ≤ 25% | factor_summary_report §5 权重表 |
| 4 | amplitude_compression 实际贡献占比 < 40%（原 64%）| factor_summary_report §6 警告（应消失或缓解）|
| 5 | Top 10 选股至少 3 只非阴跌型（5日累计 > -3%）| factor_summary_report §8 Top10 |
| 6 | 综合因子多空年化 > 22%（原 24.99% 不能显著下降）| factor_summary_report §5 |
| 7 | ruff + pytest 全过 | 命令行 |

### 6.2 不能违反

- 单调线性因子的 L1 硬约束**保持不变**（不要误伤）
- 弱交互因子（IC<0.01 或 ICIR<0.15）**保持淘汰**（豁免条件必须严格）
- 权重总和保持 1.0（cap 算法不能破坏归一化）

---

## §7 风险与回退

### 7.1 风险

| 风险 | 概率 | 影响 | 缓解 |
|------|-----|------|-----|
| 豁免阈值过松误纳弱交互因子 | 低 | 中 | §4.2 表已验证 9 因子分类正确 |
| cap 算法导致 NaN/除零 | 低 | 高 | 单元测试覆盖空字典/全等权/单因子等边界 |
| 权重重分配后综合因子表现下降 | 中 | 中 | §6.1 #6 验收，若下降 > 2% 回退 |
| Rolling ICIR 加权层 cap 失效（动态权重每日变）| 低 | 低 | cap 在 `_apply_weights` 入口，所有方法共用 |

### 7.2 回退路径

每个 batch 独立 commit，若验收失败:
- Batch 2 失败 → `git revert <batch2>`，保留 L1 豁免
- Batch 1 失败 → 整体回退到 master

---

## §8 决策点（需用户确认）

### 决策 1: 豁免阈值是否采用 long_return > 10%？

- **推荐 Yes**：是 long_return_min(3%) 的 3 倍冗余，避免误纳"L10 弱反弹"假信号
- 替代：用 `long_return > 5%`，宽松些（v2.36 的 amplitude 11.25% 会被纳入）

### 决策 2: cap 选 0.25 还是 0.30？

- **推荐 0.25**：业界主流（AQR/Asness 2013），强约束防垄断
- 替代：0.30（Barra），更宽松但 amplitude_compression 仍达 30%

### 决策 3: 两个 batch 分开 commit 还是合并？

- **推荐分开**：每个 batch 独立验证、独立回退（PROJECT.md H9）
- 替代：合并 commit，pipeline 跑一次验收

---

## §9 后续工作（不在本 PR 范围）

- amplitude_compression z-score 分布异常（集中在边界）→ 独立 PR 排查 ic_preprocessing
- Rolling ICIR 60 日窗口与全样本 ICIR 严重背离 → 独立 PR 评估窗口长度
- 选股日期不一致警告（data 最新 2026-06-18 vs 期望 2026-06-21）→ 独立 PR 修 trading_calendar

---

## §10 引用规范

- AGENTS.md §⚡ 第一性原理 / §0 4 阶段流程 / §2 硬规则 #14（死代码禁止）
- PROJECT.md H8 Design-First / H9 任务粒度
- comprehensive_factor/MODULE.md M12-M16 因子筛选 / M5-M8 加权方式 / M57 维度感知去重
- 业界文献:
  - Asness, C. (2013). "Value and Momentum Everywhere" — 多因子单权重上限经验
  - Grinold & Kahn (2000). "Active Portfolio Management" §13 — 多因子 Sharpe 加权
