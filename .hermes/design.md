# Design: momentum_strength 极端值修复

## 问题描述

`momentum_strength = return_5d / std(return_1d, 5)` 公式中，当股票连续多天以几乎相同幅度涨/跌时，日收益率标准差极小但非零（未触发 `_EPSILON=1e-10` 的除零保护），导致比值爆炸。

**实测数据**：
- 600575 (2026-06-10): `return_5d=-0.148`, `std≈0.004` → `momentum_strength=-35.03`
- 全历史最大绝对值达 56772
- 最新日期 |ms|>10 的股票有 26 只

标准化后 z-score 达 ±11.7σ，远超正常范围。

## 修复方案

### 修复点1: `calculate_momentum_strength` 分母下限保护（源头修复）

**文件**: `data_fetchers/factor_calculator.py`
**位置**: 第 1148 行 `invalid_std_mask` 判断逻辑

**当前代码**:
```python
invalid_std_mask = df["_return_1d_std_5"].isna() | (df["_return_1d_std_5"].abs() < _EPSILON)
```

`_EPSILON = 1e-10` 仅防除零，不防分母极小。

**修复方案**:
添加 `_MOMENTUM_STRENGTH_STD_MIN = 0.01` 常量（日收益率标准差下限），对低于此阈值的 std 做 clamp：

```python
_MOMENTUM_STRENGTH_STD_MIN = 0.01  # 日收益率标准差下限（防止均匀涨跌时比值爆炸）

# 计算前对 std 做 clamp（而非设 NaN）
df["_return_1d_std_5"] = df["_return_1d_std_5"].clip(lower=_MOMENTUM_STRENGTH_STD_MIN)
```

**Why 0.01**:
- 日收益率 std 正常范围约 0.01-0.05（A股个股日均波动1%-5%）
- 0.01 是正常波动下限，低于此值说明5天内收益率几乎不变（均匀涨/跌）
- clamp 而非 NaN：保留因子信号方向，只限制极端幅度

**效果**:
- 600575: `ms = -0.148/0.01 = -14.8`（vs 原始 -35.03，合理但仍偏强）
- 正常股票 `std=0.03` → 不受影响（0.03 > 0.01）

### 修复点2: `standardize_factors` Winsorize 截断（二次防线）

**文件**: `comprehensive_factor/common/factor_loader.py`
**位置**: 第 475-477 行标准化计算

**当前代码**:
```python
factor_df[std_col] = factor_df.groupby("date")[col].transform(
    lambda x: (x - x.mean()) / x.std() if x.std() > 0 else np.nan
)
```

标准化后无截断，极端原始值 → 极端 z-score。

**修复方案**:
标准化后对 `_std` 列做 Winsorize 截断（±3σ），限制 z-score 范围：

```python
# Winsorize: 截断极端 z-score 到 ±3σ
_WINSORIZE_SIGMA = 3.0

factor_df[std_col] = factor_df.groupby("date")[col].transform(
    lambda x: np.clip(
        (x - x.mean()) / x.std() if x.std() > 0 else np.nan,
        -_WINSORIZE_SIGMA, _WINSORIZE_SIGMA
    )
)
```

**Why ±3σ**:
- 统计学常识：3σ 覆盖 99.7% 正态分布
- 超过 ±3σ 的 z-score 统计意义极弱（p<0.003），截断不损失有效信息
- 业界因子分析常用 Winsorize 阈值（Barra/Axioma 均有类似处理）

**效果**:
- 即使源头 clip 仍有 -14.8 的值，标准化后 z-score 从 -11.7σ 截断到 -3σ
- 双层防线：源头 clip → 标准化 Winsorize → 最终 z-score ≤ ±3

### 不修复的方案（Don't）

| 方案 | 拒绝理由 |
|------|----------|
| 仅在 `standardize_factors` 截断，不修源头 | 原始值 -35 仍进入数据，IC/回测计算受极端值干扰 |
| `_EPSILON` 调大到 0.01 | `_EPSILON` 是全局常量，其他因子（RSI等）也用它防除零，调大影响面广 |
| 设 NaN 而非 clip | NaN 会减少有效数据天数，违反"增量因子原则"（不能因覆盖率低排除） |

## 影响范围

| 模块 | 影响 |
|------|------|
| data_fetchers/factor_calculator.py | 新增常量 `_MOMENTUM_STRENGTH_STD_MIN`，修改 `calculate_momentum_strength` |
| comprehensive_factor/common/factor_loader.py | 修改 `standardize_factors` 添加 Winsorize |
| data_fetchers/MODULE.md | 版本历史 + 规范补充 |
| comprehensive_factor/MODULE.md | 版本历史 + 规范补充 |
| data_fetchers/test_cases/test_factor_calculator.py | 新增极端值测试 |

## 验证步骤

1. pytest: `test_factor_calculator` 新增极端低波动场景
2. pytest: `test_factor_loader` 确认标准化 Winsorize 逻辑
3. 重跑 pipeline Stage 1-7 验证全链路数据一致性
4. 检查 600575 momentum_strength 值合理（应为 ~-14.8 原始值，标准化后 ≤-3σ）