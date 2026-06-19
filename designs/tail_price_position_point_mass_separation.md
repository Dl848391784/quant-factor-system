# Design: tail_price_position 点质量分离

> 2026-06-18 | 解决 tail_price_position raw=0.0 点质量导致 z-score 极端化、选股集中

## 1. 问题

| 维度 | 现状 |
|------|------|
| 原始值 0.0 | 68 只股票 (2.3%)，close=tail_low 时精确为 0.0 |
| z-score | -2.4542（全市场 mean=0.637, std=0.260） |
| 综合因子贡献 | 41%（名义权重仅 19.8%，2.1x 失真） |
| Top 10 集中度 | 9/10 只股票被同一信号选中 |

根因：`(close - tail_low) / (tail_high - tail_low)` 在 close=tail_low 时精确为 0.0，形成点质量（point mass）。z-score 标准化将点质量转为极端值，主导综合因子。

## 2. 方案：标准化层点质量置 NaN + 选股暴露限制

### 核心思路（v2 迭代）

不改原始值（保护 delta 因子计算），两层处理：

**第一层：标准化层** — `standardize_factors()` 检测点质量并将该值的 z-score 置为 NaN（→ 综合因子计算时 `fillna(0)` 视为中性无信号）。

**第二层：选股层** — `sort_and_select()` 新增单因子暴露限制，任一因子贡献占比超过 50% 时按比例缩减综合因子值。

### v1→v2 迭代：为什么从 clip 改为置 NaN

v1 方案（clip 到 ±2σ）实际验证失败：

| 指标 | 修复前 | clip ±2σ（v1） | 置 NaN（v2） |
|------|--------|---------------|-------------|
| z-score | -2.4542 | -2.0 | NaN→0（中性） |
| 贡献占比 | 41.0% | **51.0%** ⚠️ 反升 | 0% |
| 相对倍数 | 2.1x | **2.58x** ⚠️ 反升 | 0x |
| Top 10 中 raw=0.0 | 9/10 | 7/10 | 由 8 因子重新排序 |

clip 失败原因：clip 只减少 18% 的 z-score（2.45→2.0），但分母（综合因子均值）下降更多（68 只股票同时被 clip），导致贡献占比反升。且 z=-2.0 仍是所有因子中最极端的值，选股集中度改善有限。

### 为什么置 NaN 是科学的

1. **统计依据**：68 只股票精确等于 0.0 是离散点质量，不是正态分布尾部。对点质量计算 z-score 没有统计意义
2. **信号不完全丢失**：`tail_price_position_delta`（corr=0.69）、`tail_price_volume_intensity`（corr=0.56）仍携带弱势信号
3. **打散集中度**：68 只股票的综合因子由其余 8 因子重新排序，是否选入由多因子综合决定

### 为什么不全局改 Winsorize 阈值

全局将 `_WINSORIZE_SIGMA` 从 3.0 降到 2.0 会截断所有因子的真实极端值（如 momentum_strength z=-2.65），造成信息损失。本方案仅对检测到点质量的因子处理，精准定位。

### 为什么不新建二元因子

二元因子 `tail_price_at_low`（1.0 if close=tail_low）的 z-score 分析：
- p = 68/3019 = 2.3%，mean=0.023, std=0.149
- z(1.0) = (1-0.023)/0.149 = **6.59** → 比 -2.45 更极端，反而加剧集中度

### 第二层：选股暴露限制

即使置 NaN 解决了 tail_price_position 的集中度，其他因子也可能出现类似问题。选股环节加约束作为兜底：

- 任一因子贡献 `|w_i × z_i|` 占综合因子 `|Σ(w_i × z_i)|` 的比例超过 50% 时，按比例缩减综合因子值
- 缩减公式：`composite_adj = composite × (0.5 × |composite| / max_contrib)`
- 效果：降低单因子主导股票的排名，让多元化信号更强的股票上升

## 3. 实现

### 改动文件

| 文件 | 改动 | 行数 |
|------|------|------|
| `comprehensive_factor/common/factor_loader.py` | `standardize_factors()` 点质量 clip→置 NaN | ~10 行改动 |
| `comprehensive_factor/stock_selector.py` | `sort_and_select()` 新增暴露限制参数+逻辑 | ~40 行新增 |
| `comprehensive_factor/test_cases/test_standardize_point_mass.py` | 更新测试：clip→NaN | ~30 行改动 |
| `comprehensive_factor/test_cases/test_stock_selector.py` | 新增暴露限制测试 | ~40 行新增 |

### 标准化层逻辑

```python
_POINT_MASS_THRESHOLD = 0.01     # 出现频率 >1% 判定为点质量
_POINT_MASS_ZSCORE_GATE = 2.0    # z-score 超此阈值才检查点质量（性能优化）

# z-score 计算后，检测点质量并置 NaN
extreme_mask = factor_df[std_col].abs() > _POINT_MASS_ZSCORE_GATE
if extreme_mask.any():
    for each extreme (date, value):
        if frequency > _POINT_MASS_THRESHOLD:
            factor_df.loc[mask, std_col] = np.nan  # 置 NaN 而非 clip
```

### 选股暴露限制逻辑

```python
def sort_and_select(
    ...,
    max_exposure: float = 0.5,  # v2.20: 单因子最大贡献占比
):
    # 排序前：计算各因子贡献，对超限股票缩减综合因子值
    if max_exposure > 0 and weights:
        contrib_max = max(|w_i × z_i|)  # 每只股票的最大单因子贡献
        dominance = contrib_max / |composite|
        over_limit = dominance > max_exposure
        if over_limit.any():
            scale = (max_exposure / dominance).where(over_limit, 1.0)
            composite_factor = composite_factor * scale
```

## 5. 验证

- [ ] ruff check + format
- [ ] 点质量检测测试（构造 2.3% 重复值 → z-score clip 到 ±2σ）
- [ ] 正常分布无误触发测试（连续值 < 1% 重复 → z-score 正常）
- [ ] 现有标准化测试全通过（无回归）
- [ ] 重新生成综合因子 + 选股 + 报告
- [ ] 报告中集中度警告消失或显著降低

## 6. Tier B（未来，本 design 不实现）

如果需要保留"close=tail_low"的二元信号：
1. 新建 `tail_price_at_low` 因子（1.0/0.0）
2. 为二元因子设计专用标准化（如 clip ±1.5σ 或 rank-based）
3. 独立 IC 分析确定预测力
4. 如果 IC 显著，加入综合因子并分配权重
