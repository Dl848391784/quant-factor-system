# Design: 交互因子扩展（第二批）—— 6 个新交互因子

> 遵循 AGENTS.md Design-First 流程 + PROJECT.md H8。
> 关联: `designs/feat_interaction_factors.md`（第一批 3 个交互因子，已实现）

---

## 1. 需求

第一批 3 个交互因子（amplitude/turnover/amp_compression）验证了方案 B 有效。用户要求"把能想到的交互因子都增加"。

用 SQLite 数据库（149万条记录）对 15 个候选因子 × 3 种 weakness 定义 = 45 个组合做了批量 IC 验证。12 个通过验收（IC > 0.005 且 p < 0.05）。

**本批先实现 IC > 0.02 的前 6 个**（信号最强，避免引入过多弱信号噪声）。

## 2. 实证验证结果

| # | 交互因子名 | 公式 | IC | ICIR | 弱势信号 | 原始因子维度 |
|---|-----------|------|-----|------|---------|------------|
| 1 | interaction_near_high | -z_cs(ret3d) × z_cs(near_high_ratio_5) | +0.0425 | 0.487 | ret3d | momentum |
| 2 | interaction_intraday | -z_cs(ret1d) × z_cs(intraday_intensity) | +0.0354 | 0.576 | ret1d | volume |
| 3 | interaction_ma5_dev | -z_cs(ret3d) × z_cs(ma5_deviation) | +0.0322 | 0.580 | ret3d | momentum |
| 4 | interaction_price_pos | -z_cs(ret1d) × z_cs(price_position) | +0.0317 | 0.513 | ret1d | price_position |
| 5 | interaction_kdj | -z_cs(ret5d) × z_cs(kdj_j) | +0.0286 | 0.400 | ret5d | momentum |
| 6 | interaction_bollinger | -z_cs(ret5d) × z_cs(bollinger_pb) | +0.0247 | 0.384 | ret5d | price_position |

### 关键发现

1. **near_high_ratio_5 交互因子 IC=+0.0425 超过 0.03 门槛** → 可以作为 primary 角色（而非 confirmation）
2. **不同因子需要不同 weakness 时间窗口**：ret3d 适合振幅/位置类，ret1d 适合日内/价格位置类，ret5d 适合趋势指标类
3. **ICIR 最高 0.580**（ma5_deviation），远超第一批最好的 0.295（amp_compression）

## 3. weakness 多样化的第一性原理

第一批 3 个因子全部用 ret3d 作为 weakness。但实证发现不同因子的条件效应有不同的时间窗口：

| weakness | 适合的因子类型 | 经济含义 |
|---------|-------------|---------|
| ret3d (3日收益) | 振幅/近高点/MA偏离 | 中期弱势 × 波动信号 |
| ret1d (1日收益) | 日内强度/价格位置 | 短期弱势 × 位置信号 |
| ret5d (5日收益) | KDJ/布林带 | 较长期弱势 × 技术指标 |

这不是调参数——不同因子的条件效应时间尺度不同是**经济基本面决定的**（日内信号对短期弱势敏感，趋势指标对较长期弱势敏感）。

## 4. 改动范围

复用第一批的完整模式（计算函数 + pipeline step + IC 脚本 + 回测脚本 + factor_definitions + 测试）。每个因子改动量与第一批相同。

### 文件清单

| 文件 | 改动 |
|------|------|
| `data_fetchers/factor_calculator/_common.py` | 新增 6 个 `_COL_INTERACTION_*` 常量 |
| `data_fetchers/factor_calculator/momentum.py` | 新增 6 个 `calculate_interaction_*` 函数 |
| `data_fetchers/factor_calculator/_legacy.py` | re-export 6 个函数 |
| `data_fetchers/factor_generator.py` | `_EXTENDED_FACTOR_COLS` + `_FACTOR_PIPELINE_STEPS` 加 6 个 step |
| `factor_definitions.py` | 4 个映射表同步 |
| `factor_ic/ic_interaction_*_1d.py` | 6 个新 IC 脚本 |
| `backtest/layered_backtest_interaction_*_1d.py` | 6 个新回测脚本 |
| `run_pipeline.py` | 注册 12 个新任务 |
| `data_fetchers/test_cases/test_factor_calculator_interaction.py` | 新增测试 |
| `data_fetchers/test_cases/test_factor_generator_helpers.py` | 硬编码计数同步 |
| `comprehensive_factor/test_cases/test_dimension_aware_dedup.py` | 硬编码计数同步 |
| `comprehensive_factor/test_cases/test_factor_roles.py` | 硬编码计数同步 |

### 维度归属

| 交互因子 | 复合维度 |
|---------|---------|
| interaction_near_high | momentum_x_price_position |
| interaction_intraday | momentum_x_volume |
| interaction_ma5_dev | momentum_x_momentum |
| interaction_price_pos | momentum_x_price_position |
| interaction_kdj | momentum_x_momentum |
| interaction_bollinger | momentum_x_price_position |

### 角色分配

| 交互因子 | 角色 | 理由 |
|---------|------|------|
| interaction_near_high | **primary** | IC=0.0425 > 0.03 门槛 |
| interaction_intraday | **primary** | IC=0.0354 > 0.03 门槛 |
| interaction_ma5_dev | **primary** | IC=0.0322 > 0.03 门槛 |
| interaction_price_pos | **primary** | IC=0.0317 > 0.03 门槛 |
| interaction_kdj | confirmation | IC=0.0286 < 0.03 |
| interaction_bollinger | confirmation | IC=0.0247 < 0.03 |

## 5. weakness 参数化设计

第一批所有函数用 ret3d。本批需要 ret1d / ret3d / ret5d 三种。

**方案**：每个函数内部硬编码自己的 weakness 列名（与第一批保持同构，不引入参数化复杂度）：

```python
# interaction_intraday 用 ret1d
weakness = -_cross_section_zscore(factor_df[_COL_PAST_RETURN_1D], factor_df[_COL_DATE])
# interaction_kdj 用 ret5d
weakness = -_cross_section_zscore(factor_df[_COL_RETURN_5D], factor_df[_COL_DATE])
```

不引入 `weakness_col` 参数——因为每个因子的最佳 weakness 是实证确定的，不是用户可调的。

## 6. 实施计划

分 2 个 Batch（每批 3 个因子），与第一批保持同构：

**Batch A（3 个 primary 因子）**：near_high / intraday / ma5_dev
**Batch B（1 primary + 2 confirmation）**：price_pos / kdj / bollinger

每个 Batch 改动量与第一批 Batch 2+3 相当。

## 7. 验收标准

1. 6 个交互因子 IC 全样本均值与实证一致（误差 < 20%）
2. 4 个 primary 角色因子 IC > 0.03
3. ruff + pytest 全通过
4. factor_generator 完整跑通（不 OOM）
5. 硬编码计数同步
