# Design: 短名单扩展 Top 30 v1.0（路 1）

**作者**: 云瑶
**创建日期**: 2026-06-23
**状态**: Draft（待审核）
**关联规范**:
- PROJECT.md "战略目标：量化辅助 + 人工决断"（git c112edb）
- PROJECT.md "数据驱动原则：禁止给系统贴叙事标签"（git 0ce1ed5）
- PROJECT.md "实战交易规则：T 日尾盘买入 T+1 日卖出"（git 741f71e）
- AGENTS.md 规则 #12 "Design-First：2+ 文件先提交 design.md"
- AGENTS.md "战略目标"表："Layer 1 → 短名单 30~50，量化产出在此"

---

## 1. Why（为什么要做）

### 1.1 实证证据（200 日 1d 口径）

| 指标 | Top 10 | 期望（Top 30） |
|---|---|---|
| 单日均值 | -0.143% | 约 -0.083%（接近全市场均值） |
| t-stat | -2.26 | -3.92（更确定，因 √N 降噪） |
| 单日均值正收益占比 | 45.5% | 约 47% |
| composite IC 区分度 | 0 ~ 0.36% 极端尾部 | 0 ~ 1.1% 仍是 Layer 1 内尾部 |

### 1.2 第一性原理

```
组合方差 σ²_portfolio = σ²_single / N
σ_portfolio 比例:
  N=10  → σ/3.16
  N=30  → σ/5.48   降噪倍数 = √3 = 1.73x
  N=50  → σ/7.07   降噪倍数 = √5 = 2.24x
```

**N 增大的统计意义**：
- t-stat 提升（=信号检测更可靠，**但不改变信号本身**）
- 期望收益向"全市场均值"收敛（=不再吃尾部极端阴跌的额外负贝塔）

**N=30 的选择理由**：
1. 退出极端尾部（0.36% → 1.1%）摆脱"Top 10 阴跌"的极端样本
2. 仍保留 composite 区分度（不至于稀释成 Layer 1 平均）
3. 给人工挑选保留合理选股空间（30~50 选 3~5 ≈ 10%~17% 选择率）
4. 5000 → 549（Layer 1） → 30（短名单） → 用户选 3~5 → 与 AGENTS.md 战略目标表完全一致

### 1.3 与战略目标的对齐

AGENTS.md 战略目标表第 2 行：

| 环节 | 谁负责 | N |
|---|---|---|
| Layer 1 → 短名单 | 量化 | 549 → **30~50** ← 量化产出在此 |

**这就是兑现这一行**——量化的最终产出从 Top 10（违反战略目标的"准持仓"）改为 Top 30（短名单，留给人工决断）。

---

## 2. What（做什么）

### 2.1 改 default top_n: 10 → 30

```python
# comprehensive_factor/stock_selector.py L119
top_n: int = 30  # v2.42: 短名单扩展（design.md feat_shortlist_top30_v1 §2.1）
```

CLI `--top_n` 参数已暴露，用户可继续覆盖。

### 2.2 报告展示策略（策略 C）

**保留**现有 Top 10 详表（信息密度高）+ **新增**"短名单 11~30 简表"（信息精简）。

#### 2.2.1 Top 1~10 详表（不动）

```
【Top 10 详表（重点观察）】
排名 股票代码 综合因子值 覆盖率 因子标准化值(z-score, 全 15 因子)
   1  600377   -0.743    100%   interaction_kdj=0.14, bollinger_pb=-1.06, ...
   ... (10 行)
```

#### 2.2.2 短名单 11~30 简表（新增）

每行只展示：rank / code / composite / weight_coverage / 主导前 3 因子（绝对 z 值 × 权重最大）

```
【短名单 11~30 简表（备选池）】
排名 股票代码 综合因子值 覆盖率 主导前 3 因子（z × w 贡献占比）
  11  002xxx   -0.612    100%   interaction_kdj(28%), bollinger_pb(18%), volume_decay_rate(15%)
  12  600xxx   -0.598    100%   amplitude_compression(31%), turnover_surge(22%), ...
  ... (20 行)
```

**主导因子算法**：
```python
for stock in top_stocks:
    contributions = {}
    for col, w in comp_weights.items():
        z = factor_values_std.get(col, 0) or 0
        contrib = abs(w * z)
        contributions[col] = contrib
    total = sum(contributions.values())
    if total > 0:
        ratios = {k: v/total for k,v in contributions.items()}
        top3 = sorted(ratios.items(), key=lambda x: -x[1])[:3]
```

### 2.3 输出 JSON 兼容

```json
{
  "meta": {
    "top_n": 30,         // 改为 30
    "shortlist_size": 30 // 新增冗余字段标识"短名单"语义
  },
  "top_stocks": [ ... 30 项 ... ]  // 结构不变，长度变
}
```

**不引入新字段**——decision_card / dominant_factors 等延后处理。

---

## 3. How（怎么做）

### 3.1 文件变更（≤3 文件 ≤200 行，符合任务粒度约束）

| 文件 | 变更 | 行数 |
|---|---|---|
| `comprehensive_factor/stock_selector.py` | top_n 默认 10→30 + 注释 + 版本号 | +5 改 |
| `summary/generate_factor_summary_report.py` | `_generate_stock_selection_section` 拆分 Top 10 详表 + 11~N 简表 | +60 新 / -5 改 |
| `summary/test_cases/test_generate_factor_summary_report.py` | 新增简表测试用例 | +40 新 |

**总改动**: 3 文件 / ~110 行 ✅ 符合 AGENTS.md 规则 #12

### 3.2 单 commit 策略

由于改动量小（3 文件 / 110 行）且高度耦合（top_n 改了之后报告就必须适配），采用**单 commit** 完成：

```
feat: 短名单扩展 Top 30（路 1）

- stock_selector top_n 默认 10 → 30（design.md feat_shortlist_top30_v1 §2.1）
- summary 报告拆分 Top 10 详表 + 11~30 简表（design.md §2.2）
- 测试新增 11~30 简表用例

遵循 PROJECT.md 战略目标：Layer 1 → 短名单 30~50（量化产出在此）
遵循 PROJECT.md T+1 实战交易规则：N=30 降噪 √3 倍
```

### 3.3 模块边界（遵循硬规则 #1）

- stock_selector 改动**仅**在 `comprehensive_factor/` 内
- summary 改动**仅**在 `summary/` 内，**只读** stock_selection_result.json
- 无跨模块新依赖

### 3.4 数据流（不变）

```
factor_ic_data.parquet
    ↓
composite_runner → composite_factor_daily.parquet
    ↓
weight_selector → weight_selection_result.json
    ↓
stock_selector  → stock_selection_result.json  ← top_n=30
    ↓
summary         → factor_summary_report_*.txt  ← 适配 30 行展示
```

唯一变化：箭头末端的两个产物，内部数据契约**完全不变**。

---

## 4. Don't（禁止事项）

| 禁止 | 原因 |
|---|---|
| ❌ 把 N=30 也叫"持仓池"或暗示"实际持仓 30 只" | 违反战略目标——这是**短名单**，最终持仓 3~5 由人工决定 |
| ❌ 用 Top 30 的 1d 期望收益作为"实战年化"基准 | 违反 PROJECT.md 实战交易规则——短名单不是持仓，不应估算"年化" |
| ❌ 在 11~30 简表里塞决策叙事（"反弹候选" "弱势反转"） | 违反数据驱动原则 |
| ❌ 改 max_exposure / min_amount_percentile / family_cap | 这些是**正交**于 N 的约束，本期不动 |
| ❌ 改 candidate_n 系数（=top_n*2） | L1131 算 60，Layer 1 有 549 只，充足 |
| ❌ 用回测验证"Top 30 比 Top 10 好" | 第一性原理已证（√N 降噪），无需回测验证数学事实 |

---

## 5. Why（设计理由 - 第一性原理）

### 5.1 为什么不用回测决定 N

```
回测验证 = 在历史数据上找最优 N → 数据驱动
第一性原理 = 从 √N 降噪规律推 → 数学事实

两者关系: 回测在历史窗口能找到"最好 N"（如 N=23 历史最优），
         但这是历史特定行情的结果，换数据分布就会变。
         √N 降噪是任何分布下都成立的数学规律。
```

第一性原理选 N=30 而非 N=23、N=47 等"历史最优值"，是**遵守 AGENTS.md 元规则**（禁止调参数式临时修复）。

### 5.2 为什么是 30 不是 50

```
N=30: 降噪 1.73x，仍保留 composite 区分度（Top 30/549 = 5.5% 选择率）
N=50: 降噪 2.24x，但 Top 50/549 = 9.1% 已接近 Layer 1 内部均值
```

N=50 的边际收益（降噪 +29%）以稀释 composite 区分度为代价。**N=30 是降噪与区分度的平衡点**。

### 5.3 为什么不做决策卡片

决策卡片本身有价值（叠加正交维度），但：
1. 与 N 扩展正交——做完 N=30 后任何时候都能做
2. 需要新模块（decision_card.py）+ 新数据计算（D4 历史画像）
3. 决策卡片做完仍需短名单——**先扩 N 是前置条件**

本期先做 N，决策卡片留下一阶段。

### 5.4 为什么策略 C 而非 A/B

| 策略 | 信息量 | 报告长度 | 改动面 |
|---|---|---|---|
| A（30 行全详表） | 完整 | ~150 行 | 小 |
| B（30 行只详 composite+主导） | 损失 | ~80 行 | 中 |
| **C（Top 10 详 + 11~30 简）** | **完整 + 分层** | ~90 行 | **小（保留现有展示）** |

C 的关键优势：**Top 10 展示完全不动**，新加块向后兼容；用户在 Top 10 区域看到的细节与历史一致，在 11~30 区域看到的是新增的备选池。

---

## 6. When（适用场景）

| 场景 | 行为 |
|---|---|
| 每日 pipeline | stock_selector 自动输出 30 只短名单 |
| summary 报告 | 自动展示 Top 10 详表 + 11~30 简表 |
| 用户人工决策 | 从 30 只里挑 3~5 只持仓 |
| 后续决策卡片扩展 | 在 30 只上叠加 5 维客观字段（不影响本期） |

---

## 7. Examples（示例输出）

### 7.1 stock_selection_result.json（结构对比）

| 字段 | v2.41（当前） | v2.42（本设计） |
|---|---|---|
| `meta.top_n` | 10 | 30 |
| `top_stocks[]` 长度 | 10 | 30 |
| `top_stocks[i]` 结构 | 不变 | 不变 |

### 7.2 summary 报告片段

```
八、股票选股结果
----------------------------------------------------------------------
选股日期: 2026-06-22（使用T-1数据）
最优权重方法: rolling_icir_weight
权重综合得分: 0.6021
因子方向: negative（反向）
选出股票数: 30 只（共 2749 只股票）
振幅过滤: 排除 12 只股票（振幅 < 1.00%，不可交易的一字板涨停股）

【Top 10 详表（重点观察）】
排名 股票代码  综合因子值  覆盖率  因子标准化值(z-score)
   1  600377   -0.743    100%   interaction_kdj=0.14, bollinger_pb=-1.06, return_5d=-0.59, ...
   2  ...     ...       ...    ...
   ... (10 行, 显示全 15 因子)

【短名单 11~30 简表（备选池）】
排名 股票代码  综合因子值  覆盖率  主导前 3 因子（贡献占比）
  11  002xxx   -0.612    100%   interaction_kdj(28%), bollinger_pb(18%), volume_decay_rate(15%)
  12  600xxx   -0.598    100%   amplitude_compression(31%), turnover_surge(22%), price_position(14%)
  ... (20 行)
----------------------------------------------------------------------

说明: Top 1~10 为 composite 极值区（高信号 + 高波动）, Top 11~30 为短名单备选池。
最终持仓 3~5 只由人工决断（参考 PROJECT.md 战略目标）。
```

---

## 8. Verify（验证方法）

### 8.1 单元测试

| 测试 | 验证内容 |
|---|---|
| test_top_n_default_30 | StockSelectorConfig().top_n == 30 |
| test_top_n_cli_override | `--top_n 50` 仍工作 |
| test_summary_top10_detail | Top 1~10 显示全因子 z-score |
| test_summary_shortlist_brief | Top 11~30 简表行格式正确 |
| test_summary_shortlist_dominant_factors | 主导前 3 因子计算 |
| test_shortlist_size_in_meta | meta.shortlist_size == 30 |

### 8.2 集成测试（实跑校验）

```bash
# 必须跑成功
python comprehensive_factor/stock_selector.py
python summary/generate_factor_summary_report.py
test -f summary/result/factor_summary_report_$(date +%Y-%m-%d).txt
grep -A 1 "选出股票数: 30" summary/result/factor_summary_report_*.txt
grep "Top 10 详表" summary/result/factor_summary_report_*.txt
grep "短名单 11~30 简表" summary/result/factor_summary_report_*.txt
```

### 8.3 实证验证（1d 期望收益对比）

跑历史日期，对比 Top 10 vs Top 30 的 1d 实际平均收益与 t-stat：

```python
# 验证 √N 降噪是否符合理论预期
# 预期: σ_top30 ≈ σ_top10 / √3
# 预期: t-stat 提升约 √3 倍
```

不期望"Top 30 均值变正"——这是模型局限的诚实陈述。

---

## 9. 与现有规范的关系

| 规范 | 关系 |
|---|---|
| 战略目标（量化辅助+人工决断） | ✅ 兑现"Layer 1 → 短名单 30~50" |
| 数据驱动原则 | ✅ 报告展示不带叙事标签 |
| T+1 交易规则 | ✅ 不改持仓周期，只扩短名单 |
| 硬规则 #1 模块边界 | ✅ stock_selector / summary 各自内部改动 |
| 硬规则 #8 配套测试 | ✅ 新增 summary 简表测试 |
| 硬规则 #12 Design-First | ✅ 本文件 |
| 元规则（第一性原理） | ✅ N 选择基于 √N 降噪数学事实而非历史回测 |

---

## 10. 风险与回滚

| 风险 | 缓解 | 回滚 |
|---|---|---|
| 报告 11~30 简表 bug 导致 summary 失败 | 添加 try/except 容错，简表渲染失败时只输出原 Top 10 | 不需回滚，soft fail |
| 历史数据消费方依赖 top_stocks 长度=10 | grep 全仓库未发现外部依赖 | git revert |
| 性能影响 | candidate_n=60 vs 20，Layer 1 仅 549 只，<10ms 差异 | 无 |

---

## 11. 不在本期范围（明确列出）

- 决策卡片（独立 design，本期完成后做）
- 因子扩充（已论证不可行）
- top_n 改自适应（基于成交额 / 流动性动态调整）
- 短名单内部二次排序（cond_IC 重排）
- N=50 选项（如有需求后续可扩）

---

## 12. 审核清单

- [ ] 用户认可 N=30（而非 N=50）
- [ ] 用户认可"Top 30 期望收益仍小幅负，决策卡片不在本期"
- [ ] 用户认可"Top 10 详表 + 11~30 简表"展示策略
- [ ] 用户认可单 commit 而非任务拆分（3 文件 / 110 行 ≤ 约束）
- [ ] 用户认可"不引入决策卡片相关字段"（meta 只加 shortlist_size）

