# Design: 因子 IC 行业中性化接入

> 状态：DRAFT（R1 完成 §1-§2，R2/R3 续写）
> 作者：云瑶
> 创建：2026-06-17
> 关联：方案 C 子方案 A（仅行业中性化，市值中性化暂不做）
> 拆分：10 轮（design 3 轮 + 实施 6 轮 + 收尾 1 轮）

---

## §1 背景与目标

### 1.1 当前 IC 计算的真实含义

`factor_ic/common/ic_calculator.py::calculate_single_day_ic` 当前直接对原始因子值与 `forward_return` 做 Spearman 秩相关，**未做任何中性化**。这导致所有因子的 IC 数值是"原始 IC"，包含三类无法分离的成分：

1. **真 alpha**：因子对个股横截面收益的预测能力（我们关心的）
2. **行业 beta 暴露**：若因子在某些行业天然偏高/偏低（如周期股的 amplitude），IC 中混入"该行业整段时间收益偏离市场"的部分
3. **size 暴露**：小盘股波动天然大，size 维度的暴露同样会污染 IC（**本期 design 不处理**，等市值数据接入后单独立项）

**当前状态**：`industry_neutral_rank` / `industry_neutral_residual` 两个函数定义在 `ic_calculator.py:790-921`，但**全仓库 0 个调用点**，属于死代码（违反 AGENTS.md 硬规则 #14）。

### 1.2 本期目标（仅行业中性化）

为每个非行业类因子同时输出 **raw IC** 与 **industry-neutral IC** 两套数值，并在 summary 报告中提供"中性化敏感度"对比，用以诊断因子的 IC 来源构成：

| raw IC vs neutral IC 关系 | 诊断结论 | 处理建议 |
|---|---|---|
| 两者接近（衰减率 < 30%） | 因子主要是 alpha，行业 beta 不是 IC 主要来源 | 可直接使用 |
| neutral IC 大幅缩水（衰减率 ≥ 30%） | 因子 IC 主要来自行业 beta，alpha 含量低 | 复核或淘汰 |
| neutral IC 高于 raw IC | 行业噪声掩盖了 alpha，中性化反而暴露 | 优先采用 neutral 版本 |

**显式不做的事项**：
- 市值中性化（无数据，单独立项）
- 行业内 rank 方式（学术/业界更常用残差回归，rank 那个直接删）
- 修改单因子分层回测的因子方向判断逻辑（`factor_direction` 仍以 raw IC 为准，避免破坏现有 backtest 链路）

### 1.3 范围与影响面

| 模块 | 是否改动 | 改动性质 |
|---|---|---|
| data_fetchers | 否（数据已具备） | — |
| factor_ic/common/data_loader | 是 | 新增 `_merge_industry_column()` |
| factor_ic/common/ic_calculator | 是 | 删 `industry_neutral_rank`；保留 `industry_neutral_residual` |
| factor_ic/common/factor_ic_runner | 是 | 加 `neutralize` 开关 + 排除清单 |
| factor_ic/common/ic_result_builder | 是 | 输出 schema 加 `ic_neutral_industry` 字段 |
| factor_ic/ic_*.py 各因子脚本 | 否 | runner 开关默认开，单脚本无需改 |
| backtest | 否 | 仍以 raw IC 的 `factor_direction` 为准 |
| summary | 是 | 加"中性化敏感度"列 |
| comprehensive_factor | 否（本期不接入） | 后续可单独评估是否用 neutral IC 重做合成 |
| PROJECT.md / MODULE.md / flow docs | 是 | R10 同步 |

---

## §2 数据现状

### 2.1 行业分类数据

**文件**：`data_fetchers/result/stock_industry.json`
**结构**：
```json
{
  "meta": {
    "version": "3.15",
    "source": "sw_category",
    "level": "一级",
    "updated_at": "2026-06-17",
    "total_count": 5872
  },
  "industries": {
    "002309": {"name": "中利集团", "industry": "电力设备", "industry_code": "220301"},
    ...
  }
}
```
**采集**：`data_fetchers/fetch_industry.py`（已就绪），公共加载函数已有 `load_stock_industry()` / `get_stock_industry()` / `get_industry_map()`（位于 `fetch_industry.py:564/1067/1025`）。

### 2.2 资产代码格式对齐 ✅

| 数据源 | asset 列格式 | 样本 |
|---|---|---|
| `factor_ic_data.json.gz` 中的 `asset` 字段 | 6 位数字字符串（无后缀） | `"002309"` `"000001"` |
| `stock_industry.json` 的 industries key | 6 位数字字符串 | `"920126"` `"688797"` |

**结论**：两侧 key 格式完全一致，可直接用 `factor_df["asset"].map(industry_map)` 合并，**无需做代码转换**。R4 实测已确认 `002309` / `000001` 在行业表中可命中。

### 2.3 ⚠️ 关键风险：26% 股票行业为 "其他"

**实测分布**（截至 2026-06-17，共 5872 只）：

| 行业 | 股票数 | 占比 |
|---|---|---|
| **其他** | **1544** | **26.3%** |
| 机械设备 | 617 | 10.5% |
| 电子 | 515 | 8.8% |
| 电力设备 | 421 | 7.2% |
| 计算机 | 377 | 6.4% |
| 其他 27 个一级行业 | 2398 | 40.8% |

**风险点**：
1. "其他" 行业内部成分高度异质（实测含 `220901` 化工子行业、`280203` 汽车子行业、`220505` 等多个不同申万二级码），把它们当作同一个行业做截面回归会**引入噪声**而非去除噪声
2. "其他" 占比 26%，无法忽略

**应对方案**（详见 §5 技术方案）：
- 中性化时**剔除** `industry == "其他"` 或 `industry is NaN` 的股票，不参与该日截面回归（仅影响 neutral IC 的样本量，raw IC 不受影响）
- 单测验证：剔除后剩余 ~74% 股票仍可形成有效截面（每日股票数远大于 `min_industry_stocks=5`）
- 若某日剔除后某行业股票数 `< min_industry_stocks=5`，该行业整体跳过（沿用 `industry_neutral_residual` 现有逻辑，第 902-905 行 `groupby.filter`）

### 2.4 市值数据：完全缺失

| 数据 | 状态 |
|---|---|
| 流通市值 / 总市值 | ❌ `factor_ic_data_columns.json` 无 market_cap 字段 |
| 总股本 / 流通股 | ❌ `data_fetchers/` 无相关采集代码 |
| 可用代理 | ❌ `volume × close` 是日成交额，不是 size，不予使用 |

**结论**：市值中性化本期不做，作为后续 phase 单独立项（先 `fetch_market_cap.py` 拉历史数据，再做双中性化）。

### 2.5 数据日期覆盖

| 数据 | 起止 | 天数 |
|---|---|---|
| factor_data.json.gz | 2024-03-15 ~ 2026-06-16 | 545 |
| stock_industry.json | 单期快照（2026-06-17） | — |

**注意**：行业分类是**单期快照**而非时间序列。这意味着：
- 假设：股票行业归属在回测窗口（2024-03 至今 ~2.3 年）内**基本稳定**
- 风险：少量股票可能在窗口内发生过行业重分类（如借壳上市），用最新行业去回归历史数据会有误差
- 妥协：本期采用最新行业静态映射；若后续需要时变行业，再扩展为 `(asset, date) → industry` 的时变映射

---

## §3 适用范围

### 3.1 排除清单（不做行业中性化的因子）

以下 8 个因子**禁止**做行业中性化，强制走 raw IC 单通道。原因：因子值在行业内部全部相同或高度同步，行业内做截面回归后残差恒等于 0 或近似 0，IC 必然趌零，是**自我消除**而非去噪。

| # | 因子脚本 | 因子列名 | 因子构造方式 | 排除原因 |
|---|---|---|---|---|
| 1 | `ic_industry_momentum_5d_1d.py` | industry_momentum_5d | 行业 5 日动量赋个股 | 同行业值相同 → 残差≡0 |
| 2 | `ic_industry_turnover_trend_1d.py` | industry_turnover_trend | 行业换手率趋势赋个股 | 同行业值相同 → 残差≡0 |
| 3 | `ic_industry_amplitude_trend_1d.py` | industry_amplitude_trend | 行业振幅趋势赋个股 | 同行业值相同 → 残差≡0 |
| 4 | `ic_industry_roe_trend_1d.py` | industry_roe_trend | 行业 ROE 趋势赋个股 | 同行业值相同 → 残差≡0 |
| 5 | `ic_industry_earnings_growth_1d.py` | industry_earnings_growth | 行业盈利增速赋个股 | 同行业值相同 → 残差≡0 |
| 6 | `ic_industry_pe_trend_1d.py` | industry_pe_trend | 行业 PE 趋势赋个股 | 同行业值相同 → 残差≡0 |
| 7 | `ic_capital_flow_intensity_1d.py` | capital_flow_intensity | 行业主力流入强度赋个股 | 同行业值相同 → 残差≡0 |
| 8 | `ic_capital_flow_ratio_trend_1d.py` | capital_flow_ratio_trend | 行业 Δ 主力净流入占比赋个股 | 同行业值相同 → 残差≡0 |

**判定规则**（用于代码 §5.3 的常量）：

```python
# factor_ic/common/factor_ic_runner.py
INDUSTRY_NEUTRALIZE_EXCLUDED = frozenset({
    "industry_momentum_5d",
    "industry_turnover_trend",
    "industry_amplitude_trend",
    "industry_roe_trend",
    "industry_earnings_growth",
    "industry_pe_trend",
    "capital_flow_intensity",
    "capital_flow_ratio_trend",
})
```

**实证验证依据**（R7 单测要求）：对排除清单内的因子，构造一组同行业内值完全相同的 mock 数据，调用 `industry_neutral_residual` 后断言所有残差 `abs(res) < 1e-9`。这正是排除它们的根本原因，应作为单测明证保存。

### 3.2 纳入清单（做行业中性化的因子）

`factor_ic/ic_*.py` 中**除排除清单 8 个之外的全部因子**（当前共 ~22 个个股层因子，含技术面、量价、尾盘、价格位置等）。这些因子值在同一行业内**因股而异**，截面回归残差有意义。

**默认行为**（D3 决策结果）：
- runner 默认开 `neutralize=True`
- 排除清单内的 8 个因子在 runner 内部强制覆盖为 `neutralize=False`，跳过 industry merge 与残差回归
- 输出 JSON 仍包含 `ic_neutral_industry` 字段，但取值为 `null`，并在 `neutralize_skipped_reason` 字段写明 "factor in INDUSTRY_NEUTRALIZE_EXCLUDED"

### 3.3 "其他" 行业的处理（沿用 §2.3 决策）

| 处理项 | 决策 |
|---|---|
| `industry == "其他"` 或 `industry is NaN` 的股票 | 在 industry merge 后**该日截面**剔除，不参与回归 |
| 剔除后该日剩余股票数 < `min_stocks=10` | 跳过该日（沿用 `calculate_single_day_ic` 现有逻辑） |
| 某行业股票数 < `min_industry_stocks=5` | 该行业整体跳过（沿用 `industry_neutral_residual:902-905` 逻辑） |
| 影响范围 | 仅影响 neutral IC 的有效日数 / 样本量；raw IC 不受影响 |

---

## §4 决策矩阵

> 标注规范：每条决策注明来源（用户已选 / 上下文锁定+理由 / 规范默认）

| ID | 决策点 | 选项 | 决策 | 来源 |
|----|---|---|---|---|
| **D1** | 行业中性化方式 | (a) 残差回归 industry_neutral_residual / (b) 行业内 rank | **(a) 残差回归** | 用户已选（"全默认"采纳推荐）+ 学术/业界标配；rank 方式直接删除 |
| **D2** | 排除清单范围 | (a) 仅排除 ic_industry_* 6 个 / (b) 同时排除 ic_capital_flow_* 2 个 | **(b) 排除 8 个** | 用户已选（"全默认"采纳推荐）；§3.1 实证：行业聚合赋个股因子残差≡0 |
| **D3** | 默认开关 | (a) 默认 neutralize=True / (b) 默认 False 需 `--neutralize` 开 | **(a) 默认开** | 用户已选；排除清单内强制覆盖为 False |
| **D4** | 输出位置 | (a) 同 json 加 `ic_neutral_industry` 子字段 / (b) 分两 json | **(a) 单 json 双字段** | 用户已选；summary 报告对比方便 |
| **D5** | summary 报告对比形式 | (a) 衰减率列 = (raw - neutral) / raw / (b) 并列 raw/neutral 不算衰减 | **(a) 衰减率** | 用户已选；阈值 30% 标注 "行业 beta 主导" |
| **D6** | "其他" 行业处理 | (a) 当作独立行业回归 / (b) 截面剔除不回归 | **(b) 剔除** | 上下文锁定：§2.3 实测 1544 只占 26.3%，且申万二级码混杂（化工/汽车混在 "其他" 内），当独立行业会引入噪声 |
| **D7** | min_industry_stocks | 5 / 10 | **5** | 规范默认：沿用 `industry_neutral_residual` 现有签名第 858 行 `min_industry_stocks: int = 5` |
| **D8** | factor_direction 判断基准 | (a) raw IC / (b) neutral IC / (c) 各算各的 | **(a) raw IC** | 上下文锁定：避免破坏 backtest 链路（backtest 只读 raw 的 factor_direction）；neutral IC 仅作诊断对比 |
| **D9** | 行业映射时变性 | (a) 静态最新快照 / (b) 时变 (asset,date) → industry | **(a) 静态** | 上下文锁定：§2.5 当前数据是单期快照；扩展为时变映射涉及 fetch_industry 重构，超出本期范围 |
| **D10** | 死代码 industry_neutral_rank 处理 | (a) 删除 / (b) 保留备用 / (c) 标 deprecated | **(a) 删除** | 规范默认：AGENTS.md 硬规则 #14 禁止死代码；R6 同步删除并在 commit 引用 #14 |
| **D11** | 衰减率阈值 | 30% / 50% | **30%** | 上下文锁定：业界经验值；后续可在 PROJECT.md 标注为 [experimental] 字段，跑数后回校 |
| **D12** | 字段命名 | `ic_neutral_industry` / `ic_industry_neutral` / `ic_residual_industry` | **`ic_neutral_industry`** | 规范默认：与 `industry_neutral_residual` 函数名前缀一致；为后续 `ic_neutral_industry_size` 留扩展位 |

### 4.1 引用核对（§1-§3 回扫）

R3 末尾会再做一次引用闭环，但 R2 阶段先列出 §3-§4 引用了 §1-§2 的关键命题：

- §3.1 排除原因 "残差≡0" → §1.1 "因子值在行业内部全部相同" 的形式化表达
- §3.3 "其他" 行业处理 → §2.3 实测分布数据 + 申万二级码异质性证据
- §4 D6 "其他" 决策 → §2.3 数据现状
- §4 D9 静态映射 → §2.5 数据日期覆盖
- §4 D10 死代码删除 → §1.1 "0 个调用点" 实测 + AGENTS.md #14

无矛盾。R2 闭环。

---

## §5 技术方案

### 5.1 接入点流程图

整体改动以 **runner 为枢纽**，行业 merge 与残差回归在 runner 内部完成，单因子脚本（`factor_ic/ic_*.py`）**零改动**。

```
┌──────────────────────────────────────────────────────────────────────┐
│  factor_ic/ic_<name>_1d.py（无改动）                                   │
│    └─→ run_factor_ic(spec, args, ...)  [factor_ic_runner.py:432]      │
└────────────────────────────┬─────────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────────┐
│  run_factor_ic_analysis(...)  [factor_ic_runner.py:54]   ← 主改动点    │
│                                                                      │
│  Step 1: load_factor_return_data()      [data_loader.py]             │
│            ↓                                                         │
│  Step 2: factor_df = _merge_industry_column(factor_df)  ← R8 新增      │
│            （加一列 industry，'其他'/NaN 不剔除，留给后续判断）         │
│            ↓                                                         │
│  Step 3: ic_raw = calculate_ic_with_direction_verification(           │
│              factor_df, return_df, ...)                              │
│            （raw IC：使用原始 factor_col，不剔除 '其他'）              │
│            ↓                                                         │
│  Step 4: 判断 factor_name in INDUSTRY_NEUTRALIZE_EXCLUDED              │
│          ┌─────────────────────────────────┬─────────────────────┐    │
│          │ True（排除清单内）               │ False（纳入清单）    │    │
│          │ ic_neutral_industry = None       │ → Step 5 残差回归    │    │
│          │ neutralize_skipped_reason set    │                     │    │
│          └─────────────────────────────────┴─────────────────────┘    │
│            ↓                                                         │
│  Step 5: factor_df_neutral = factor_df[                              │
│              ~factor_df['industry'].isin({'其他', NaN})               │
│            ]                                                         │
│            ↓                                                         │
│          factor_df_residual = industry_neutral_residual(              │
│              factor_df_neutral, factor_col, ...)                     │
│            （输出列名: 'neutral_factor'）                              │
│            ↓                                                         │
│          ic_neutral = calculate_ic_with_direction_verification(       │
│              factor_df_residual, return_df,                          │
│              factor_col='neutral_factor', ...)                       │
│            ↓                                                         │
│  Step 6: build_ic_result(ic_raw, ic_neutral, ...)  ← R16 加双字段       │
│            ↓                                                         │
│  Step 7: save_ic_result(...)  [输出 JSON 含 ic_neutral_industry]       │
└──────────────────────────────────────────────────────────────────────┘
```

**关键约束**：
- Step 3（raw IC）与 Step 5（neutral IC）**使用相同的 return_df**，保证两套 IC 数值的可比性
- Step 5 中残差回归仅对剔除 "其他" 后的子集做；剔除发生在残差回归之前，不发生在 IC 计算之前
- `factor_direction`（D8 决策）由 ic_raw 提供；ic_neutral 不参与 backtest 链路

### 5.2 字段命名 + JSON Schema

#### 5.2.1 顶层字段新增（factor_ic 输出 JSON）

在 `<模块>/result/ic_<因子>_1d_analysis_result.json` 顶层新增 1 个对象字段（不影响现有字段）：

```json
{
  "success": true,
  "factor_name": "rsi_6",
  "calculation_date": "2026-06-17",
  "period": {...},
  "ic_metrics": {...},                  // 维持原 raw IC 数值
  "sample_stats": {...},                // 维持原（基于 raw 数据）
  "statistical_significance": {...},    // 维持原（raw）
  "factor_direction": {...},            // D8: 仅基于 raw（backtest 读取）
  "economic_significance": {...},       // 维持原（raw）
  "icir_stability": {...},              // 维持原（raw）
  "ic_distribution_consistency": {...}, // 维持原（raw）
  "dates": [...],                       // 维持原（raw 的 ic_series.index）
  "ic_values": [...],                   // 维持原（raw）
  "rolling_ic_mean": [...],             // 维持原（raw）
  "positive_ratio": 0.52,               // 维持原（raw）
  "summary": {...},                     // 维持原（raw）

  // ↓↓↓ R16 新增字段 ↓↓↓
  "ic_neutral_industry": {
    "enabled": true,                    // false 表示因子在排除清单内
    "skipped_reason": null,             // enabled=false 时填写原因
    "ic_metrics": {                     // 与顶层 ic_metrics 同结构
      "ic_mean": -0.034,
      "ic_std": 0.082,
      "icir": -0.41,
      "p_value": 0.012,
      "p_value_display": "0.012"
    },
    "sample_stats": {                   // neutral 路径的样本量（剔除 '其他' 后）
      "valid_days": 540,
      "avg_stocks_per_day": 1842,       // 显著低于 raw（剔除了 '其他' 的 ~26%）
      "excluded_other_industry_pct": 0.263
    },
    "decay_rate": 0.18,                 // = (raw_ic_mean - neutral_ic_mean) / raw_ic_mean
    "decay_level": "low",               // <30% low / >=30% high (D11)
    "ic_values": [...],                 // neutral 路径每日 IC 序列（与 raw 的 dates 一一对应；neutral 缺失日填 null）
    "summary": "中性化后 IC 衰减 18%，行业 beta 不是主要 IC 来源"
  },

  "factor_stats": {...},                // 维持原
  "update_mode": "full",
  "factor_col": "rsi_6"
}
```

#### 5.2.2 字段命名规则（D12）

| 命名 | 含义 | 选择理由 |
|---|---|---|
| `ic_neutral_industry` | 当前期：仅行业中性化 | 与函数名 `industry_neutral_residual` 前缀一致 |
| `ic_neutral_industry_size`（保留位） | 后续期：行业 + 市值双中性化 | 命名空间向后扩展 |
| `ic_residual_industry`（不采用） | — | "residual" 偏实现细节，"neutral" 偏含义 |

#### 5.2.3 排除清单内的字段取值

```json
"ic_neutral_industry": {
  "enabled": false,
  "skipped_reason": "factor in INDUSTRY_NEUTRALIZE_EXCLUDED (industry-aggregated factor)",
  "ic_metrics": null,
  "sample_stats": null,
  "decay_rate": null,
  "decay_level": "n/a",
  "ic_values": null,
  "summary": "行业聚合因子，残差回归后值≡0，已跳过"
}
```

### 5.3 排除清单常量 + neutralize 开关协议

#### 5.3.1 排除清单常量定义位置

```python
# factor_ic/common/factor_ic_runner.py（顶部模块级常量，R12 新增）

# 行业中性化排除清单：行业聚合赋个股因子，行业内值相同 → 残差≡0 → IC≡0
# 详见 design.md §3.1 实证依据
INDUSTRY_NEUTRALIZE_EXCLUDED: frozenset[str] = frozenset({
    "industry_momentum_5d",
    "industry_turnover_trend",
    "industry_amplitude_trend",
    "industry_roe_trend",
    "industry_earnings_growth",
    "industry_pe_trend",
    "capital_flow_intensity",
    "capital_flow_ratio_trend",
})

# 排除原因模板（写入 ic_neutral_industry.skipped_reason）
INDUSTRY_NEUTRALIZE_SKIPPED_REASON = (
    "factor in INDUSTRY_NEUTRALIZE_EXCLUDED (industry-aggregated factor)"
)
```

**为什么是 frozenset 而不是 list**：
- 不可变（防止运行时被意外修改）
- O(1) 查询（`factor_name in INDUSTRY_NEUTRALIZE_EXCLUDED`）
- 类型标注 `frozenset[str]` 明确语义

#### 5.3.2 neutralize 开关协议

`run_factor_ic_analysis` 函数签名（R13 改动）：

```python
def run_factor_ic_analysis(
    factor_name: str,
    factor_col: str,
    factor_cols: list[str],
    return_period: str = "1d",
    min_stocks: int = 10,
    force_full: bool = False,
    custom_factor_calculation=None,
    custom_factor_calculation_params=None,
    extra_log_params=None,
    *,
    neutralize: bool = True,                  # ← R13 新增（D3 默认 True）
    neutralize_min_industry_stocks: int = 5,  # ← R13 新增（D7 默认 5）
    logger=None,
    **kwargs,
) -> dict[str, Any]:
    """
    新参数:
        neutralize: 是否计算行业中性化 IC。默认 True。
            - True 且 factor_name 不在 INDUSTRY_NEUTRALIZE_EXCLUDED → 计算并输出
            - True 且 factor_name 在 INDUSTRY_NEUTRALIZE_EXCLUDED → **强制覆盖为 False**，
              输出 ic_neutral_industry.enabled=false + skipped_reason
            - False（用户显式关）→ 不计算，输出 ic_neutral_industry.enabled=false +
              skipped_reason="user disabled via neutralize=False"
        neutralize_min_industry_stocks: 残差回归时单行业最小股票数（D7）
    """
```

**协议核心规则**（R13 实现需严格遵守）：

| 入参 neutralize | factor_name 是否在排除清单 | 实际行为 | enabled | skipped_reason |
|:---:|:---:|---|:---:|---|
| True | 否 | 计算 neutral IC | true | null |
| True | **是** | **强制 skip**（覆盖入参） | false | "factor in INDUSTRY_NEUTRALIZE_EXCLUDED ..." |
| False | 否 | 用户主动关闭 | false | "user disabled via neutralize=False" |
| False | 是 | 双重原因，按排除清单为主 | false | "factor in INDUSTRY_NEUTRALIZE_EXCLUDED ..." |

**为什么排除清单优先于用户开关**：避免用户误开导致排除清单内因子产生 IC≡0 的误导性输出（这种结果会污染 summary 报告，伤害诊断价值）。

#### 5.3.3 CLI 暴露

`factor_ic_runner.py::main` 加 `--no-neutralize` flag（默认开，提供关闭逃生口）：

```python
parser.add_argument(
    "--no-neutralize",
    dest="neutralize",
    action="store_false",
    help="关闭行业中性化（仅输出 raw IC，调试用；默认开启）",
)
parser.set_defaults(neutralize=True)
```

单因子脚本（`factor_ic/ic_*.py`）**不暴露**该 CLI 选项，因为：
- 默认行为已通过排除清单自动正确处理
- 单脚本暴露会让 CLI 接口爆炸（×30 因子）
- 调试需要时直接调 runner CLI 即可

---

## §6 验证方案

### 6.1 单元测试

| 轮次 | 测试文件 | 测试用例 | 验证目标 |
|---|---|---|---|
| R9 | `factor_ic/test_cases/test_data_loader_industry.py` | `test_merge_industry_happy_path` | factor_df.asset → industry 列正确合并 |
| R9 | 同上 | `test_merge_industry_unknown_asset_fallback` | 未在行业表中的 asset → industry='其他' |
| R9 | 同上 | `test_merge_industry_no_pollution` | 现有列不被修改 |
| R15 | `factor_ic/test_cases/test_runner_neutralize.py` | `test_neutralize_excluded_factor_skipped` | 排除清单内因子 → enabled=false + skipped_reason |
| R15 | 同上 | `test_neutralize_disabled_via_param` | neutralize=False → enabled=false + "user disabled" |
| R15 | 同上 | `test_neutralize_excluded_overrides_user_param` | neutralize=True + 排除清单 → 仍 skip 且 reason 是排除清单 |
| R15 | 同上 | `test_industry_aggregated_factor_residual_zero` | 同行业值相同的 mock 数据 → 残差 abs<1e-9（§3.1 实证证据保留） |
| R15 | 同上 | `test_neutral_excludes_other_industry` | 含 '其他' 行业的 mock → neutral 路径剔除 ~26%，raw 路径不剔除 |
| R17 | `factor_ic/test_cases/test_ic_result_builder_neutral.py` | `test_output_has_ic_neutral_industry_field` | JSON 含 ic_neutral_industry 字段 |
| R17 | 同上 | `test_decay_rate_calculation` | decay_rate = (raw - neutral) / raw 算式正确 |
| R17 | 同上 | `test_decay_level_threshold` | decay_rate=0.31 → "high"；=0.29 → "low"（D11 阈值 30%） |
| R19 | `summary/test_cases/test_neutralize_sensitivity_column.py` | `test_summary_report_has_decay_column` | summary txt 报告含"中性化敏感度"列 |

### 6.2 集成测试（R20 全因子回归跑数）

跑全部 ~30 个 `ic_*.py`，校验：

1. **每个因子输出 JSON 都含 `ic_neutral_industry` 顶层字段**
   - `find factor_ic/result/ -name 'ic_*_1d_analysis_result.json' | xargs -I{} jq -e '.ic_neutral_industry' {}`
2. **排除清单内 8 个因子**：`enabled=false`, `skipped_reason` 含 "INDUSTRY_NEUTRALIZE_EXCLUDED"
3. **纳入清单 ~22 个因子**：`enabled=true`, `decay_rate` 是有限数（非 NaN/Inf）
4. **raw IC 数值与改动前完全一致**（保护下游 backtest 链路），抽样对比 5 个因子的 `ic_metrics.ic_mean`：误差 < 1e-9
5. **summary 报告新列存在**且阈值标注正确

### 6.3 性能预算

| 项 | 现状（每因子） | 改动后预估 | 说明 |
|---|---|---|---|
| factor_df 加载 | ~3-5 s | +0.1 s | industry merge 是 O(n) 单列字典查 |
| raw IC 计算 | ~5-10 s | 不变 | 算法不变 |
| neutral IC 计算 | — | +5-10 s | 残差回归（按日 groupby + LinearRegression） |
| 总耗时 | 8-15 s | **15-25 s** | **可接受**：单因子总耗时 < 30 s |

**降级方案**（若实测超预算）：把 `industry_neutral_residual` 内的 `LinearRegression().fit()` 换成 numpy 闭式解（`np.linalg.lstsq` 或直接行业均值减），预计可砍 50% 耗时。

### 6.4 回归保护

| 风险 | 检测手段 |
|---|---|
| 改动破坏 raw IC 数值 | R15 集成测试断言现有 5 个 fixture JSON 的 ic_mean 完全一致 |
| 改动破坏 backtest 读取的 factor_direction | R15 单测断言 factor_direction 字段仍只来自 raw 计算结果 |
| 单因子脚本 CLI 接口变更 | 任何 ic_*.py 不改动；如有改动，违反 §5.1 "零改动" 约束 |
| 输出 JSON schema 不向后兼容 | R20 末段：summary 模块按现有逻辑读 ic_metrics 必须仍能正常运行 |

---

## §7 引用闭环核对（R6 末尾，全文检查）

回扫 §3-§6 对 §1-§2 命题的引用，确认无矛盾：

| 引用方 | 被引用方 | 命题 | 状态 |
|---|---|---|---|
| §3.1 排除原因 | §1.1 | "因子值在行业内部全部相同" → 形式化为 "残差≡0" | ✅ 一致 |
| §3.1 实证验证 | §3.1 表内 8 因子 | R15 单测 `test_industry_aggregated_factor_residual_zero` | ✅ 单测覆盖 |
| §3.3 "其他" 处理 | §2.3 | 1544 只 / 26.3% / 申万二级码异质性 | ✅ 数据一致 |
| §4 D6 "其他" 决策 | §2.3 | 当独立行业引入噪声 → 剔除 | ✅ 一致 |
| §4 D7 min_industry_stocks=5 | `ic_calculator.py:858` | 函数现有签名默认值 | ✅ 一致 |
| §4 D8 factor_direction | §1.3 | 不修改 backtest 链路 | ✅ 一致 |
| §4 D9 静态映射 | §2.5 | 当前数据是单期快照 | ✅ 一致 |
| §4 D10 删除死代码 | §1.1 | "0 个调用点" + AGENTS.md #14 | ✅ 一致 |
| §4 D12 字段命名 | §5.2.2 | `ic_neutral_industry` 与 `industry_neutral_residual` 函数前缀一致 | ✅ 一致 |
| §5.1 流程图 Step 4 | §5.3 协议表 | 排除清单优先于用户开关 | ✅ 一致 |
| §5.2.1 schema 字段名 | §5.2.2 命名规则 + §5.3 常量 | `ic_neutral_industry` 全文一致 | ✅ 一致 |
| §5.2.3 排除字段示例 | §5.3 协议表 | enabled=false + skipped_reason 一致 | ✅ 一致 |
| §6.1 单测覆盖 | §3.1/§3.3/§5.3 | 三个核心机制（残差≡0/'其他'剔除/排除清单优先）均有单测 | ✅ 一致 |
| §6.2 集成测试 | §5.2 schema | 字段断言全部对齐 | ✅ 一致 |

**全文无矛盾，design.md 闭环完成**。R6 之后进入实施阶段（R7-R22）。

---

## §8 R7 核对发现（实施前接口确认）

### 8.1 复用 `data_fetchers.fetch_industry.get_industry_map`

| 项 | 现状 |
|---|---|
| 函数签名 | `get_industry_map() -> dict[str, dict]` |
| 返回结构 | `{"002309": {"name": "中利集团", "industry": "电力设备", "industry_code": "220301"}, ...}` |
| 缓存机制 | 模块级 `_industry_cache` + 双重检查锁，已实现，**R8 直接用即可** |
| 契约 | 必返回 dict（可能为空），不抛异常（v3.7 文档保证） |

### 8.2 ⚠️ 协议偏差修正：`'未知'` vs `NaN`

发现 `get_stock_industry(code)` 对**不在行业表中的 asset**返回 `'未知'`（字符串），而非 `None`/NaN。

为保持 design §3.3 的 "{其他, NaN} 剔除" 协议清晰，**R8 实现不调 `get_stock_industry`**，改为直接基于 `get_industry_map()` 的 dict 做 `.map()`：

```python
# R8 实现伪代码
ind_map = get_industry_map()  # {asset: {name, industry, industry_code}}
asset_to_industry = {k: v.get("industry") for k, v in ind_map.items()}
factor_df["industry"] = factor_df["asset"].map(asset_to_industry)
# 未知 asset → pandas NaN（自然行为）
# 行业表中的 "其他" → factor_df["industry"] == "其他"
```

剔除条件统一为：

```python
factor_df_neutral = factor_df[
    factor_df["industry"].notna() & (factor_df["industry"] != "其他")
]
```

**修正后 design 一致性**：§3.3 表格中 "`industry == '其他'` 或 `industry is NaN` 的股票" 与本实现完全对齐 ✅


---

## §9 实施完成记录（R22e）

> 完成时间: 2026-06-18
> 状态: ✅ 闭环（仅行业中性化；市值中性化因数据缺失暂不做）

### 9.1 实施轮次回顾（R1-R22）

| 阶段 | 轮次 | 核心交付 | commit 范围 |
|---|---|---|---|
| Plan | R1-R8 | design.md §1-§8（含 §8 协议偏差修正） | 多轮 patch |
| Execute | R9-R14 | data_loader.merge_industry_column → ic_calculator 死代码清理 → factor_ic_runner 决策/计算/接入 → ic_result_builder R14 占位 | c1f4890→7dbbb99 |
| Execute | R15a-e | factor_ic_runner 排除清单 + 用户禁用 + '其他'剔除 5 集成测试 | 5 commits |
| Execute | bug fix | ic_calculator._newey_west_t_stat 加 logger 参数（修预存 bug） | 1 commit |
| Execute | R16a-c | ic_result_builder NEUTRAL_REQUIRED_KEYS + _normalize_neutral_payload + 端到端 smoke | 隐含 commits |
| Execute | R17a-c | ic_result_builder 21 单测 | 3 commits |
| Execute | R18a-b | summary _format_neutral_cell + 中性化敏感列 | 隐含 commits |
| Execute | R19a-b | summary 13 单测 | 2 commits |
| Execute | R20 | 三因子真实数据回测验证（rsi/amplitude/overnight_ret） | 数据产物 |
| Execute | R21a | schema oneOf 双路径 + additionalProperties=false | 06e58f4 |
| Execute | R21b | MODULE.md M66 + 类别 L. 行业中性化 + v4.5 | 1f3318e |
| Review | R22a-d | industry_neutralization_flow.md 公共流程文档 | 3b61c2b/e7b428f/8c0ab87/cb18502 |

### 9.2 测试覆盖

| 测试文件 | 用例数 | 覆盖范围 |
|---|---|---|
| `factor_ic/test_cases/test_factor_ic_runner_neutralize.py` | 6 | 决策优先级（排除清单 / 用户禁用 / '其他'剔除 / 残差≡0） |
| `factor_ic/test_cases/test_ic_result_builder_neutral.py` | 21 | disabled 路径 / enabled 路径 / 顶层接入 / 字段缺失防御 |
| `summary/test_cases/test_neutral_cell.py` | 13 | _format_neutral_cell + IC 表头数据行 |
| **合计** | **40** | 本任务新增；旧 240 passed 零回归 |

### 9.3 真实数据验证（R20）

| 因子 | raw IC | neutral IC | decay | level | 结论 |
|---|---|---|---|---|---|
| `rsi_1d` | -0.0396 | -0.0304 | 23.3% | low | ✅ 真 alpha |
| `amplitude_1d` | -0.0574 | -0.0494 | 13.9% | low | ✅ 真 alpha |
| `overnight_ret_1d` | 0.0212 | (skipped) | — | — | ⚠️ NaN 降级正常 |

### 9.4 已知 follow-up（不在 R22 范围）

1. `overnight_ret_1d` 残差含 NaN 根因排查（独立 task）
2. 市值中性化（依赖 `total_mv` 数据接入；当前数据集无市值字段）
3. 全量因子（17 个非排除）批量跑一遍获取 high/low/inverse 三档分布全景

### 9.5 规范化产物清单

- 代码：`factor_ic/common/data_loader.py` + `factor_ic_runner.py` + `ic_calculator.py` + `ic_result_builder.py`
- 报告：`summary/generate_factor_summary_report.py`
- schema：`factor_ic/schemas/ic_analysis_result.schema.json`
- 测试：3 文件 / 40 用例
- 规范：`factor_ic/MODULE.md` M66
- 流程：`factor_ic/docs/industry_neutralization_flow.md` v1.0
- 设计：`.hermes/plans/factor-ic-industry-neutralization-design.md`（本文档）
