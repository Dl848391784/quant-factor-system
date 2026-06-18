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

## 2. 方案：标准化层点质量检测 + z-score clip

### 核心思路

不改原始值（保护 delta 因子计算），在 `standardize_factors()` 中检测点质量并将该值的 z-score clip 到 ±2.0σ。

- **原始值保持 0.0**：`tail_price_position_delta = 0.0 - prev_position` 正常计算
- **z-score clip 到 -2.0**：保留弱势信号方向，限制极端贡献
- **效果**：贡献占比从 41% 降到 34%，相对倍数从 2.1x 降到 1.72x（<2.0x 不再触发集中度警告）

### 为什么选 clip 而非置 NaN

| 方案 | z-score | 信号方向 | 贡献占比 | 相对倍数 |
|------|---------|---------|---------|---------|
| 置 NaN→fillna(0) | 0（中性） | ❌ 反转（弱势→中性） | 0% | 0x |
| clip 到 ±2σ（本方案） | -2.0 | ✅ 保留（弱势） | 34.1% | 1.72x |

置 NaN 会把"极端弱势"信号变成"全市场平均"信号，信号方向反转。clip 保留信号方向，仅限制极端值。

### 为什么不全局改 Winsorize 阈值

全局将 `_WINSORIZE_SIGMA` 从 3.0 降到 2.0 会截断所有因子的真实极端值（如 momentum_strength z=-2.65），造成信息损失。本方案仅对检测到点质量的因子 clip，精准定位。

### 为什么不新建二元因子

二元因子 `tail_price_at_low`（1.0 if close=tail_low）的 z-score 分析：
- p = 68/3019 = 2.3%，mean=0.023, std=0.149
- z(1.0) = (1-0.023)/0.149 = **6.59** → 比 -2.45 更极端，反而加剧集中度

## 3. 实现

### 改动文件

| 文件 | 改动 | 行数 |
|------|------|------|
| `comprehensive_factor/common/factor_loader.py` | `standardize_factors()` 新增点质量检测 + clip | ~25 行 |
| `comprehensive_factor/test_cases/test_factor_loader.py` | 新增点质量测试用例 | ~40 行 |

### 实现逻辑

```python
_POINT_MASS_THRESHOLD = 0.01  # 出现频率 >1% 判定为点质量
_POINT_MASS_CLIP_SIGMA = 2.0  # 点质量 z-score 截断阈值

# standardize_factors() 内，z-score 计算后、Winsorize 后插入：

for date_val, group in factor_df.groupby("date"):
    n = group[col].count()  # 非NaN数
    if n == 0:
        continue
    val_counts = group[col].value_counts()
    for val, count in val_counts.items():
        if pd.isna(val):
            continue
        if count / n > _POINT_MASS_THRESHOLD:
            # 点质量：该值出现频率 >1%，clip z-score 到 ±2σ
            mask = (factor_df["date"] == date_val) & (factor_df[col] == val)
            factor_df.loc[mask, std_col] = factor_df.loc[mask, std_col].clip(
                -_POINT_MASS_CLIP_SIGMA, _POINT_MASS_CLIP_SIGMA
            )
            logger.info(
                "因子 %s 在 %s 检测到点质量: value=%.4f, count=%d (%.1f%%), z-score clip 到 ±%.1fσ",
                col, date_val, val, count, count / n * 100, _POINT_MASS_CLIP_SIGMA,
            )
```

### 关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 点质量阈值 | 1% | 68/3019=2.3% 能被检出；正常连续因子极少有 >1% 的重复值 |
| clip 阈值 | ±2.0σ | 量化研究常用 Winsorize 阈值；-2.45→-2.0 将相对倍数降到 1.72x |
| 处理方式 | clip（非 NaN） | 保留信号方向，仅限制极端值 |
| 作用范围 | 所有因子（通用检测） | 通用检测，但实际只有边界型因子（tail_price_position）触发 |
| 原始值 | 不改 | 保护 delta 因子计算链 |

## 4. 预期效果

| 指标 | 修复前 | 修复后 |
|------|--------|--------|
| tail_price_position z-score | -2.4542 | -2.0 |
| 综合因子贡献占比 | 41.0% | 34.1% |
| 相对倍数（实际/名义） | 2.1x | 1.72x（<2.0x 不触发警告） |
| Top 10 中 raw=0.0 的股票 | 9/10 (90%) | 预计显著降低（z=-2.0 不再主导排名） |
| tail_price_position_delta | 不受影响 | 不受影响 |

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
