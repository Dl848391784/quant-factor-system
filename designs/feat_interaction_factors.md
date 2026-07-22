# Design: 交互因子（Interaction Factors）—— 条件因子方向方案 B

> 遵循 AGENTS.md Design-First 流程 + PROJECT.md H8。涉及 6+ 文件改动，必须先通过审核才能动手。
> 关联讨论: 2026-06-22 会话（条件IC分析）+ skill ref `conditional-ic-analysis.md`
> 关联规范: `factor-pool-diversity-and-selection-framework.md` §5（方向多样性不够）+ §15（极端值规避：补丁vs根本解法）

---

## 1. 需求与根因

### 1.1 问题
综合因子选股 Top 10 全为持续阴跌股（composite≈-1.2，z-score -2~-3）。45 个因子中 39 个 IC 为负，6 个 IC 为正的全部不显著 → 综合因子方向=negative → 选低值 → 选到全维度最弱势的股票 → 阴跌股。

### 1.2 根因（第一性原理推导）
IC 是**无条件**相关系数，假设"因子-收益关系在所有条件下相同"。但实测发现：

| 因子 | 全样本IC | 弱势股IC(RSI<30) | 更弱IC(RSI<25) | 信号反转? |
|------|---------|-----------------|---------------|----------|
| amplitude | -0.022 | **+0.083** | **+0.112** | YES |
| amplitude_compression | -0.005 | **+0.068** | **+0.092** | YES |
| turnover_rate | -0.028 | **+0.044** | **+0.065** | YES |
| volume_ratio_5 | -0.001 | **+0.036** | **+0.060** | YES |

实证证明因子效应是**条件依赖**的：高振幅在强势股中=坏（高位风险），在弱势股中=好（反弹信号）。无条件 IC 是两种条件的加权平均（弱势15% × +0.083 + 强势85% × -0.035 ≈ -0.022），方向被强势股稀释。

**完整实证数据来源**：skill `factor-development` ref `conditional-ic-analysis.md` §3-4。

### 1.3 目标
通过交互因子（interaction factor）让"条件方向"被自然捕捉到无条件 IC 中，使综合因子能选到"反弹型弱势股"而非"阴跌型弱势股"。

---

## 2. 方案选型（架构两档）

### 2.1 方案 A：交互因子（推荐 ✅）

**核心**：构建乘法形式的复合因子，`interaction = weakness_score × factor_z`，让条件方向被乘法运算自然吸收。

```
weakness_score = -z_cs(return_3d)              # 截面z-score，跌得越多越弱势
amplitude_z    =  z_cs(amplitude)              # 截面z-score
interaction_amplitude = weakness_score × amplitude_z
```

逻辑：
- 弱势股(w>0) × 高振幅(a>0) → 交互值正 → 反弹型
- 弱势股(w>0) × 低振幅(a<0) → 交互值负 → 阴跌型
- 强势股(w<0) × 高振幅(a>0) → 交互值负 → 高位风险型
- 强势股(w<0) × 低振幅(a<0) → 交互值正 → 平稳型

实证全样本 IC=+0.020（已翻正），方向="positive"，进综合因子时选高值=反弹/平稳，避开阴跌。

**优点**：
1. 无硬编码阈值（weakness 是连续 z-score）
2. 全样本 IC 自动翻正（不需在 weight_engine 加条件分支）
3. 不循环依赖（weakness 用过去收益，外生于综合因子）
4. 数据分布变化时仍成立（条件效应由乘法自然提取）
5. 符合 AGENTS.md 第一性原理元规则

**缺点**：
- 单交互因子 IC=+0.020 偏弱（vs 最强单因子|IC|=0.067）
- 需要多个交互因子组合才能形成有效信号

### 2.2 方案 B：分段 weight_engine（备选 ❌）

**核心**：在 `weight_engine.py` 加 RSI 分段逻辑，弱势股翻转 8 个因子方向。

```python
if stock_rsi < 30:
    factor_direction = {'amplitude': 'positive', ...}  # 翻转
else:
    factor_direction = {'amplitude': 'negative', ...}
```

**致命缺陷**：
1. RSI<30 是任意阈值（违反 AGENTS.md 第一性原理元规则）
2. RSI=29 vs RSI=31 突变（非平滑）
3. 改动 weight_engine 影响所有因子流程，回退风险大
4. 多个阈值候选（RSI/price_position/return_5d）无法统一

**结论**：违反规则 #15，**否决**。

### 2.3 决策矩阵

| 维度 | 方案A 交互因子 | 方案B 分段翻转 | 依据来源 |
|------|--------------|---------------|---------|
| 第一性原理（无硬编码阈值） | ✅ 连续 z-score | ❌ RSI<30 任意 | AGENTS.md §⚡ |
| 改动范围 | ✅ 新增 6 文件（与新因子模式同构） | ❌ 改 weight_engine 核心 | 本设计 §3 |
| 回退风险 | ✅ 低（新增不影响存量） | ❌ 高（影响所有因子） | 本设计 §3 |
| 数据稳健性 | ✅ 9 种弱势定义下结论一致 | ❌ 阈值依赖 | conditional-ic-analysis.md §3 |
| 与现有因子框架兼容 | ✅ 走标准因子流程 | ❌ 需特殊处理 | factor-development skill |

**最终选定：方案 A 交互因子。**

---

## 3. 因子定义

按条件IC强度排序，**首批先实施 3 个最强的交互因子**（先验证后扩展）：

| # | 因子名 | 公式 | 维度归属 | 全样本IC（实证） |
|---|--------|------|---------|----------------|
| 1 | interaction_amplitude | -z_cs(return_3d) × z_cs(amplitude) | momentum_x_volatility | +0.020 |
| 2 | interaction_turnover | -z_cs(return_3d) × z_cs(turnover_rate) | momentum_x_volume | +0.016 |
| 3 | interaction_amp_compression | -z_cs(return_3d) × z_cs(amplitude_compression) | momentum_x_volatility | +0.008 |

**注**：
- 全样本 IC 来自 `/tmp/verify_conditional_ic.py` 实证（2026-06-22 会话）
- weakness 用 `return_3d` 是因为它在所有测试中 IC 表现最好（vs return_5d/past_return_1d/rsi）
- 维度归属用**复合名**（momentum_x_volatility）表示交互因子的跨维度本质，避免被单维度去重淘汰

### 3.1 计算函数定位

放在 `data_fetchers/factor_calculator/momentum.py`（与现有 amplitude、return_3d 同文件）。

### 3.2 输入列依赖

| 因子 | required_cols | 备注 |
|------|--------------|------|
| interaction_amplitude | return_3d, amplitude | 都是 factor_generator 上游已计算的列 |
| interaction_turnover | return_3d, turnover_rate | turnover_rate 来自 fetch_turnover |
| interaction_amp_compression | return_3d, amplitude_compression | amplitude_compression 是 factor_generator 上游列 |

**依赖图**：交互因子必须在 return_3d、amplitude、turnover_rate、amplitude_compression 之后计算，即 `_FACTOR_PIPELINE_STEPS` 中位置靠后。

---

## 4. 核心计算逻辑

### 4.1 截面 z-score 工具函数（复用）

```python
def _cross_section_zscore(s: pd.Series, dates: pd.Series, clip: float = 3.0) -> pd.Series:
    """按日期截面计算 z-score，clip 到 ±3σ"""
    z = s.groupby(dates).transform(lambda x: (x - x.mean()) / (x.std(ddof=0) + 1e-10))
    return z.clip(-clip, clip)
```

### 4.2 计算函数（以 interaction_amplitude 为例）

```python
def calculate_interaction_amplitude(
    factor_df: pd.DataFrame, logger_arg: logging.Logger | None = None
) -> pd.DataFrame:
    """
    交互因子: weakness × amplitude

    公式: interaction_amplitude = -z_cs(return_3d) × z_cs(amplitude)
        其中 z_cs 是按日期的截面 z-score, clip 到 ±3σ
    含义: 捕捉"弱势(跌得多) × 高振幅"的反弹信号

    Args:
        factor_df: 包含 date/asset/return_3d/amplitude 列的 DataFrame
        logger_arg: 日志记录器（可选）

    Returns:
        添加 interaction_amplitude 列的 DataFrame

    边界处理:
        - return_3d 或 amplitude 缺失 → interaction_amplitude=NaN
        - 截面 std=0 → 加 1e-10 防除零
        - z-score clip 到 ±3σ 防极端值
    """
    _logger = get_module_logger(logger_arg)
    df = factor_df.copy()  # MODULE.md 约束

    required = [_COL_DATE, _COL_RETURN_3D, _COL_AMPLITUDE]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise FactorCalcError("interaction_amplitude 缺失必需列: %s" % missing)

    # 截面 z-score
    weakness = -_cross_section_zscore(df[_COL_RETURN_3D], df[_COL_DATE])
    amp_z = _cross_section_zscore(df[_COL_AMPLITUDE], df[_COL_DATE])

    df[_COL_INTERACTION_AMPLITUDE] = weakness * amp_z

    nan_count = df[_COL_INTERACTION_AMPLITUDE].isna().sum()
    _logger.info("interaction_amplitude 计算完成: %s 条记录, NaN=%s", len(df), nan_count)
    return df


calculate_interaction_amplitude.required_cols = ["return_3d", "amplitude"]  # type: ignore[attr-defined]
```

---

## 5. 改动范围

### 5.1 文件清单（首批 3 因子）

按 superpowers-workflow H9 任务粒度（≤3 文件 ≤200 行），**分 3 批 commit**：

**Batch 1：基础设施 + interaction_amplitude（3 文件）**
| # | 文件 | 改动 |
|---|------|------|
| 1 | `data_fetchers/factor_calculator/_common.py` | 新增 3 个常量 `_COL_INTERACTION_*` |
| 2 | `data_fetchers/factor_calculator/momentum.py` | 新增 `_cross_section_zscore` + `calculate_interaction_amplitude` |
| 3 | `data_fetchers/factor_calculator/__init__.py` | re-export `calculate_interaction_amplitude` |

**Batch 2：pipeline 集成 + IC 脚本（3 文件）**
| # | 文件 | 改动 |
|---|------|------|
| 4 | `data_fetchers/factor_generator.py` | `_EXTENDED_FACTOR_COLS` + `_FACTOR_PIPELINE_STEPS` 加 interaction_amplitude |
| 5 | `factor_ic/ic_interaction_amplitude_1d.py` | 新建（走 complex_factor_pattern） |
| 6 | `comprehensive_factor/common/factor_definitions.py` | FACTOR_CATEGORIES 加 `interaction_amplitude: 'momentum_x_volatility'` |

**Batch 3：回测 + 测试 + pipeline 注册（4 文件，超 H9，需 design 豁免）**
| # | 文件 | 改动 |
|---|------|------|
| 7 | `backtest/layered_backtest_interaction_amplitude_1d.py` | 新建 |
| 8 | `factor_ic/test_cases/test_ic_interaction_amplitude_1d.py` | 新建测试 |
| 9 | `data_fetchers/test_cases/test_factor_generator_helpers.py` | 同步硬编码计数 |
| 10 | `comprehensive_factor/test_cases/test_dimension_aware_dedup.py` | 同步 FACTOR_CATEGORIES 计数 |
| 11 | `run_pipeline.py` | 注册 ic + backtest 新脚本 |

**说明**：Batch 3 因测试同步本质上是 Batch 2 的连带改动，按 PROJECT.md H9 仲裁规则可在 design.md 通过后整批提交（H8 优先于 H9）。

### 5.2 后续扩展（首批通过后）

interaction_turnover、interaction_amp_compression 按同样模式增量加入，每个走一轮上述 Batch 1-3。

---

## 6. 测试计划

| 测试类型 | 文件 | 用例 |
|---------|------|------|
| 计算函数单元测试 | `test_factor_calculator.py` | 1. 正常数据 z-score 正确；2. 缺失列报错；3. 截面 std=0 不崩；4. clip 边界 |
| IC 脚本测试 | `test_ic_interaction_amplitude_1d.py` | 1. 计算入口；2. 全样本IC 在 [+0.01, +0.04] 范围内（实证 ±0.02）；3. ICIR > 0 |
| 分层回测测试 | `test_layered_backtest_interaction_amplitude_1d.py` | 1. 分层单调性；2. layer_1 多头收益 > 0（H5 实证导出）|
| 集成测试 | 已有 `test_dimension_aware_dedup.py` | FACTOR_CATEGORIES 含新维度 `momentum_x_volatility` |

**关键验证（H5 实证）**：跑完 IC 脚本后必须验证 ic_mean ≈ +0.020 ± 容差。如果偏差>50% 说明计算实现与设计不符。

---

## 7. 风险与回退

| 风险 | 应对 |
|------|------|
| 交互因子 IC=+0.020 低于综合因子门槛 (|IC|≥0.03) | 接受 → 进入综合因子池作为方向多样化补充因子，不要求单独显著（与现有 `lower_shadow_ratio` 等弱因子并列）|
| 维度去重把 3 个交互因子合并 | 用复合维度名 `momentum_x_volatility` / `momentum_x_volume` 分散；同维度内只保留 ICIR 最高一个 |
| 实证 IC 与设计偏差 | Phase 3 Review 必须读 ic_*_analysis_result.json 验证 ic_mean，不信测试通过 |
| 回退路径 | 单 commit 颗粒，回退仅需 `git revert` 对应 commit；不动 weight_engine 等核心模块 |

---

## 8. 验收标准

> **⚠️ Post-Mortem 注（2026-06-22 v2.36 实施后追加）**：
> 验收标准 #1 用的 "+0.005~+0.035 全样本均值" 是**池化全样本 Spearman IC 口径**
> （SQLite 一次性 spearmanr(factor, return)），与 pipeline 实际产出的 **逐日截面 IC 等权均值** 不等价。
> 详见 §10 Post-Mortem。

1. ✅ 3 个交互因子 IC 全样本均值在 [+0.005, +0.035]，方向="positive"
2. ✅ 进入综合因子池后参与 select_factors 流程，至少 1 个被选中
3. ✅ stock_selection_result.json 的 Top 10 中至少有 3 只**非阴跌型**股票（5日累计收益 > -3%）—— 与基线对比
4. ✅ ruff check / pytest 全通过；测试覆盖率不下降
5. ✅ 流程文档（factor_generator_flow.md）同步更新交互因子相关字段说明

---

## 9. Phase 划分（superpowers-workflow）

| Phase | 内容 | 产出 |
|-------|------|------|
| Plan | 本设计文档 | designs/feat_interaction_factors.md（已就绪，待审核）|
| Execute Batch 1-3 | 11 文件改动 | 见 §5.1 |
| Review | ruff + pytest + Spec Compliance + 实证 IC | 报告 |
| Debug | 测试失败处理 | systematic-debugging skill |

---

## 10. Post-Mortem：IC 口径错配导致的"预期未达成"

> **追加日期**：2026-06-22（实施后诊断）
> **触发**：pipeline 重跑后，3 个因子 IC 实测 (+0.0048/+0.0016/+0.0077) 远低于 §3 设计预期 (+0.020/+0.016/+0.008)，怀疑因子失效

### 10.1 根因诊断（已闭环）

经逐列数值核对（`temporary/compare_sql_vs_pipeline_input.py`）：

1. **数据源 100% 一致**：SQLite `/tmp/factor_ic.db` 与 `factor_ic_data.json.gz` 在所有 5 列、1467504 行上 `相等比例=1.0`，**排除"数据不一致"假设**。
2. **IC 口径不等价**：

| 因子 | 设计预期（池化 IC） | Pipeline 实测（逐日 IC, min_stocks=10）| 我的逐日 IC（min_stocks=30）|
|---|---|---|---|
| interaction_amplitude | +0.020 (池化=+0.0195 ✓) | **+0.0048** | +0.0126 |
| interaction_turnover | +0.016 (池化=+0.0163 ✓) | **+0.0016** | +0.0063 |
| interaction_amp_compression | +0.008 (池化=+0.0083 ✓) | **+0.0077** | +0.0129 |

**结论**：设计 §3 IC 预期用 `scipy.stats.spearmanr(全样本 factor, 全样本 return)`（池化 IC）算出，
而 pipeline `factor_ic/common/ic_calculator.py` 用**逐日 groupby + spearman 后等权平均**（逐日 IC）。
两者数学上不等价（详见 skill ref `daily-ic-vs-pooled-ic-equivalence.md`）：

```
ic_pooled  ≈ Σ wₜ · icₜ   (wₜ = nₜ/N, 每日权重 ∝ 当日股票数)
ic_daily   = (1/T) · Σ icₜ  (每日等权)
```

差值 = `Σ (wₜ - 1/T) · icₜ` = "样本规模与截面 IC 的协方差"。

### 10.2 分段 IC 详情（interaction_amplitude，pipeline 实测）

| 区段 | mean IC | std | 备注 |
|---|---|---|---|
| 前 30 日 | **−0.0065** | 0.0964 | n=10~150，噪声极大且偏负 |
| 31-100 日 | **+0.0193** | 0.0675 | 接近设计预期 |
| 101-300 日 | **+0.0024** | 0.0642 | 已开始衰减 |
| 最近 200 日 | **+0.0044** | 0.0514 | 持续低于设计预期 |

**关键**：amplitude/turnover 在所有时段（包括最近 200 日）IC < 设计预期 → 不是"实时失效"，是**设计预期口径用错**。
**例外**：amp_compression 的 daily IC (+0.0077) ≈ 设计预期 (+0.008) → 这个因子设计基本正确。

### 10.3 决议

| 项 | 决议 | 理由 |
|---|---|---|
| §3 的池化 IC 数值 | **保留但加 ⚠️ 注** | 历史依据，体现设计推导逻辑 |
| 验收标准 #1 的口径 | **重新表述为 daily IC** | 与生产线对齐 |
| interaction_amplitude / turnover 是否上线 | **依综合贡献 + Top10 多样性判断**（验收 #2/#3） | 单因子 IC ≠ 综合贡献，需看实际选股效果 |
| 后续设计 IC 预期推导 | **必须复刻 pipeline 逐日 IC 算法** | 见 PROJECT.md 待补充规则 |

### 10.4 改进项（建议在后续 design 中实施）

- [ ] **PROJECT.md 新规则**：design.md §3 的 IC 预期值必须标注口径（pooled / daily）+ 计算脚本路径
- [ ] **factor_ic 报告增强**：除 `ic_metrics.ic_mean`（daily），同时输出 `ic_pooled_full_sample` 辅助 sanity check
- [ ] **factor_summary 增加"IC 时段分解"表**：前 30 日 / 中期 / 最近 200 日，暴露衰减
- [ ] **min_stocks 默认值讨论**：是否升到 30 以削减前期稀疏样本污染（独立 design.md）

### 10.5 相关 ref

- skill `factor-development` ref `daily-ic-vs-pooled-ic-equivalence.md` — 两种 IC 数学不等价的完整证明
- skill `factor-development` ref `conditional-ic-analysis.md` — 条件 IC 分解工具
- `temporary/compare_sql_vs_pipeline_input.py` — 本次诊断验证脚本（可保留为回归测试模板）
- `temporary/verify_interaction_factors_ic.py` — 池化 IC 验证脚本（注意输出与生产 IC 不同口径）

---

**审核问题（请用户回答后再启动 Execute）**：

1. **首批因子数量**：先做 3 个（interaction_amplitude / turnover / amp_compression）还是只先做 1 个 amplitude 跑通后再扩展？
2. **维度命名**：复合维度名 `momentum_x_volatility` / `momentum_x_volume` 可接受么？还是用单维度名 `interaction`？
3. **commit 粒度**：Batch 1-3 三次 commit 可接受么？或需要更细拆分？
4. **数据重跑**：实施完后是否要重跑完整 pipeline 生成新的 factor_ic_data.json.gz？（约 30 分钟，会影响其他模块）
