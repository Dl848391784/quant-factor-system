# Diagnostic Design: 阴跌股根因 — v2.13 "统一负向语义"契约的架构盲区

> 作者: 云瑶
> 日期: 2026-06-22
> Phase: **Diagnostic (未到 Plan)**——根因已定位，方案选型待用户裁定
> 关联: v2.36 design.md §1 (条件 IC) + v2.39 design.md (独立门槛) + v2.13 commit

---

## 1. 现象（v2.39 重跑后实测）

| 验收项 | 实际 | 目标 |
|---|---|---|
| v2.36 三因子进池 | **1/3** (amp_compression ✓; amplitude/turnover 真实失效) | 3/3 |
| `factor_direction` | **negative** | positive |
| Top10 composite_value | **−0.99 ~ −1.18 全负** | 全正 |
| Top10 非阴跌股数 | **≈ 0** | ≥5 |

**关键现象**: 入选 16 因子方向分布 **8 negative : 8 positive 完全均衡**，但 `factor_direction` 仍判 negative，Top10 全是 composite 最负值。

---

## 2. 根因（架构溯源）

### 2.1 v2.13 "统一负向语义"契约

`comprehensive_factor/common/composite_runner.py`:

**关键代码 1** (行 121-122):
```python
# 2. 综合因子不加载 IC 文件，factor_direction 固定为 'negative'
self.factor_direction = "negative"
```

**关键代码 2** (行 474-505):
```python
# v2.13: 正向因子（ic_mean > 0）在负向因子组合中信号方向相反，
#   直接加权会抵消信号。取反后所有因子统一为负向语义：
#   标准化正值=差信号 → 综合因子低值=好信号 → factor_direction='negative'
for i, col in enumerate(factor_cols):
    ic_mean_val = ic_results[factor_name].get("ic_mean")
    if ic_mean_val > 0:
        factor_df[std_col] = -factor_df[std_col]  # 强制取反
        flipped_factors.append(factor_name)
```

**关键代码 3** `stock_selector.py` 行 470:
```python
ascending: bool = factor_direction == "negative"  # 选最负的 Top10
```

### 2.2 契约逻辑链

```
ic_mean > 0 的因子(positive) → _std 取反 → 全 16 因子语义"负向"
       ↓
ICIR 加权求和 (rolling_icir_weight)
       ↓
composite_factor (低值 = 设计期望的"好信号")
       ↓
factor_direction = "negative" (hardcoded)
       ↓
stock_selector: ascending=True → 选 composite 最低 Top10
```

### 2.3 阴跌股的产生机制

v2.36 design.md §1.1 已诊断: 综合因子选 Top10 = "所有维度都最弱的股票" = **阴跌股**。

v2.36 提出的方案 (交互因子) 想法是: 用乘法 `-z(weakness)×z(X)` 让 positive 翻正后能区分**反弹型弱势** vs **阴跌型弱势**。

**但 v2.13 契约破坏了这个意图**:
1. `interaction_intraday` ic_mean = +0.025 (positive) → 被强制取反
2. 取反后 = 原值的相反数 → "低值" 现在等价于"原值的高值"
3. 加权求和时，与"线性低 RSI / 低 bollinger" **简单相加**
4. composite 最低 ≠ "反弹型弱势"，仍然是 "全维度最弱（含反弹信号反转后也最低）"

### 2.4 第一性原理验证

**v2.13 契约的 implicit assumption**: 所有因子的"好信号方向"可以通过**线性取反**统一。

**反例（v2.36 三因子证明）**: 交互因子的"好信号"是**条件**的（在弱势子样本中高振幅=反弹），不是无条件的方向反转。线性取反丢失了条件信息。

**数学上**:
- 线性因子 `RSI`: ic_mean = −0.046 → 高 RSI = 强势 = 差信号 → "选低 RSI" 正确
- 交互因子 `interaction_intraday`: ic_mean = +0.025 (无条件) → **取反后**: 低值 = 高 intraday × 高 weakness 或 低 intraday × 低 weakness
  - 后者 (低 intraday × 低 weakness = 强势 + 低日内强度) 也被纳入"好信号"
  - 这与设计期望 (高 intraday × 高 weakness = 弱势反弹) **不一致**

---

## 3. 方案分歧点 (4 档)

### 3.1 方案 A: 架构重构 — 打破 v2.13 契约

```python
# composite_runner.py 改为:
# 1. 不再取反 positive 因子
# 2. factor_direction 改为 'auto'，根据 ic_mean 加权方向计算
# 3. 综合因子 = Σ sign(ic_mean_i) × w_i × _std_i
# 4. stock_selector 改为: positive 选高 / negative 选低
```

| 维度 | 评估 |
|---|---|
| 改动文件 | composite_runner.py + stock_selector.py + 4 个 composite_*.py weight_method + MODULE.md + ≥10 测试 |
| 行数 | ~400 行 |
| 风险 | **高**: 破坏 13+ 版本契约，4 种 weight_method 可比性需重新设计 |
| 第一性原理符合度 | **高**: 显式建模因子方向，不依赖隐式取反 |
| 解决阴跌股 | **可能**: 取决于交互因子真实贡献是否能盖过线性因子 |

### 3.2 方案 B: 调权重不动架构 — 让交互因子总权重 > 线性因子

ICIR 加权下交互因子 ICIR 低 (0.077~0.273) < 线性因子 ICIR (0.220~0.493)，自然权重低。
强制把 interaction_* 因子权重底线设为 5% (8 × 5% = 40%) → composite 偏 positive 侧。

| 维度 | 评估 |
|---|---|
| 改动文件 | weight_engine.py + design.md |
| 行数 | ~80 行 |
| 风险 | **中**: 调参式修复，违反第一性原理；ICIR 失去意义 |
| 解决阴跌股 | 可能 (没数学保证) |

### 3.3 方案 C: 选股层多样性硬过滤 — 不动架构

`stock_selector.py` Top10 后加 post-filter:
```python
# Top10 候选选出后，剔除最近 5 日累计收益 < -3% 的股票，再补足
recent_return = factor_df["return_5d"]  # 已有列
top_stocks = top_stocks[recent_return >= -0.03]
```

| 维度 | 评估 |
|---|---|
| 改动文件 | stock_selector.py + 配置 + 1 测试 |
| 行数 | ~30 行 |
| 风险 | **低**: 最小侵入，不破坏任何契约 |
| 第一性原理符合度 | **低**: 看到结果有毛病就补一刀，不改因素 |
| 解决阴跌股 | 直接 ✅ (定义上消除阴跌股) |
| 副作用 | Top10 可能不足 10 只 / 过滤后顺序失真 / 不能根本解决因子方向问题 |

### 3.4 方案 D: 暂不动架构 — push commits + 起独立 design

push 当前 92 个 commits 到 origin 锁定 v2.39 成果，独立起 design 调查 v2.13 契约可修性。

| 维度 | 评估 |
|---|---|
| 改动文件 | 无代码改动；新 design.md |
| 风险 | **极低**: 锁定已有成果 |
| 时机 | **合适**: 今天已 220+ 步，架构性问题需要冷静思考 |

### 3.5 决策矩阵

| 维度 | A 架构重构 | B 调权重 | C 选股过滤 | **D 暂缓 ✅** |
|---|---|---|---|---|
| 第一性原理符合度 | 高 | 低 | 低 | N/A |
| 实施风险 | 高 | 中 | 低 | 极低 |
| 解决阴跌股 | 可能 | 可能 | 直接 | 否 |
| 时机 | 不合适 (今天累) | 不合适 | 可考虑 | **合适** |
| 推荐 | 后续 | ❌ | 备选 | **本轮** |

---

## 4. 推荐路径

**今天剩余时间**: 仅做方案 D —— 锁定 v2.39 成果。

**未来 (你思考后)**: 在方案 A / C 之间裁定 (建议 A 长期方向 + C 短期止血)。

---

## 5. 待你裁定的问题

1. **本轮是否走方案 D** (push + 暂缓架构)？
2. **如果走方案 D，是否 push 全部 92 个 commits**？(memory 历史规则: "commit 但不要 push"——但这是默认规则，不是绝对禁令)
3. **未来方案优先级**: A 长期 / C 短期 / 同时？

---

## 6. 相关文件

- `comprehensive_factor/common/composite_runner.py` (行 121-122, 474-505) — v2.13 契约源头
- `comprehensive_factor/stock_selector.py` (行 470-473) — ascending 排序逻辑
- `designs/feat_interaction_factors.md` §1 + §10 — v2.36 条件 IC 诊断 + Post-Mortem
- `designs/feat_interaction_thresholds_v239.md` — v2.39 独立门槛（已 commit `9efd219`）
- `~/.hermes/skills/quant-development/factor-development/references/daily-ic-vs-pooled-ic-equivalence.md` — IC 口径教训
