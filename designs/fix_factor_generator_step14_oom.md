# Design: fix factor_generator Step 14 OOM（交互因子 groupby.transform 内存放大）

> 作者: 云瑶
> 创建时间: 2026-06-22
> 状态: Step 13 OOM 修复 (commit 8fabb0b) 后, 进程推进到 Step 14 被 OOM-kill, 用户已确认继续修复
> 关联: `designs/fix_factor_generator_step13_oom.md`（前置）, `data_fetchers/factor_calculator/_common.py`（_per_asset_transform 同类模式）

---

## §1 背景与现场证据

Step 13 修复后跑 `/usr/bin/time -v python data_fetchers/factor_generator.py`：

```
01:44:21 INFO Step 13: 计算二阶导数企稳信号因子...
01:44:22 INFO   return_acceleration_5d: valid=1486366 (99.39%)
01:44:21 INFO   downside_deceleration: valid=1495447 (100.00%)
01:44:23 INFO   amplitude_compression: valid=1483296 (99.19%)
01:44:26 INFO   range_compression: valid=1483339 (99.19%)
01:44:28 INFO   volume_decay_rate: valid=1483339 (99.19%)
01:44:29 INFO   turnover_decay_rate: valid=1488595 (99.54%)
01:44:29 INFO Step 14: 计算交互因子族（条件因子方向方案B）...
Command terminated by signal 9
Maximum resident set size (kbytes): 3671944   # max-RSS 3.59GB
```

**Step 13 已经全部跑通**（6 因子 valid_count 与历史一致），OOM 触发位置移到 Step 14 内部。

---

## §2 规范触发

| 规范 | 触发 | 处理 |
|------|------|------|
| PROJECT.md H8 | 涉及 `_common.py` + `momentum.py` 2 文件 | 先提交 design |
| PROJECT.md H9 | ≤3 文件 ≤200 行 | 本批 2 文件预计 ~120 行 |
| data_fetchers/MODULE.md M54 | groupby.transform 大规模数据 OOM | 用 numpy 边界切片替代 |
| AGENTS.md §⚡ 第一性原理 | 不切数据库, 不全面重构 | 仅替换 `_cross_section_zscore` 实现 |
| skill ref `_per_asset_transform` docstring | "pandas groupby.transform 在 >1M 行 × >1k group 上产生 4GB+ 内存峰值" | 复用同类设计模式 |

---

## §3 根因分析（第一性原理）

### §3.1 OOM 现场分解

Step 14 内 3 个交互因子函数串行调用，每个函数：

```python
df = factor_df.copy()                                       # 复制 ~1.5GB
weakness = -_cross_section_zscore(df[col_ret3d], df[date])  # groupby.transform #1
factor_z = _cross_section_zscore(df[col_factor], df[date])  # groupby.transform #2
df[new_col] = weakness * factor_z
return df
```

3 个因子 × 2 次 `_cross_section_zscore` = **6 次大规模 groupby(date).transform**。

### §3.2 pandas groupby.transform 内存机制

```python
z = value.groupby(dates, sort=False).transform(_zscore_one)
```

pandas 内部行为（项目 backtest/MODULE.md M54 + `_per_asset_transform` docstring 已记录）：
1. 为每个 group 构建中间 Series（149万 行 ÷ ~545 个日期 ≈ 每组 2700 行）
2. transform 内部做**索引重建**：先对每组应用 fn，再回填到原 Series 的索引位置
3. 在 >1M 行 × >1k groups 场景下，索引重建产生 **4GB+ 临时对象**

我们的场景：149 万行 × **545 个日期 group**。日期 group 数虽少（vs asset 3000+），但**每组数据更大**（每日 2700+ 股票），中间对象仍可达 GB 级。

### §3.3 内存峰值估算

```
Step 14 进入时 factor_df 已经持有 Step 1-13 全部因子列 ≈ 1.5-1.8GB
calculate_interaction_amplitude 内部:
  df = factor_df.copy()                                    +1.5GB → 累计 3GB
  weakness 计算 (groupby.transform #1)                     +1GB → 累计 4GB  ← OOM
```

---

## §4 方案：numpy 边界切片版 _cross_section_zscore

### §4.1 核心方案

复用项目已有 `_per_asset_transform` 的设计思路：**按 date 排序 → np.flatnonzero 找边界 → 逐 group 切片 + numpy 计算 → 回填 + 恢复原顺序**。

```python
def _cross_section_zscore(
    value: pd.Series,
    dates: pd.Series,
    *,
    clip_sigma: float = _DEFAULT_INTERACTION_CLIP_SIGMA,
    std_min: float = _DEFAULT_INTERACTION_STD_MIN,
) -> pd.Series:
    """numpy 边界切片版（替代 groupby.transform）。

    第一性原理: pandas groupby.transform 在 >1M 行场景下因内部索引重建
    产生 4GB+ 内存峰值（见 backtest/MODULE.md M54）. numpy 边界切片
    只持有 一份 float64 输出 ndarray (~12MB), 内存友好.

    保持原 API 完全兼容: 输入/输出 pd.Series 同 index, NaN 行透传.
    """
    if len(value) != len(dates):
        raise ValueError(f"value/dates 长度不一致: {len(value)} vs {len(dates)}")

    n = len(value)
    if n == 0:
        return pd.Series([], dtype=np.float64, index=value.index)

    # 1. 提取 numpy 视图
    val_arr = value.to_numpy(dtype=np.float64)
    date_arr = dates.to_numpy()

    # 2. 按 date 排序（argsort 返回索引, 不复制数据）
    sort_idx = np.argsort(date_arr, kind="stable")
    val_sorted = val_arr[sort_idx]
    date_sorted = date_arr[sort_idx]

    # 3. 找 date 边界
    boundaries = np.flatnonzero(date_sorted[1:] != date_sorted[:-1]) + 1
    boundaries = np.concatenate([[0], boundaries, [n]])

    # 4. 逐 date 切片计算 z-score (numpy 向量化)
    out_sorted = np.full(n, np.nan, dtype=np.float64)
    for i in range(len(boundaries) - 1):
        s, e = boundaries[i], boundaries[i + 1]
        seg = val_sorted[s:e]
        # 用 nanmean/nanstd 处理 NaN 行
        mu = np.nanmean(seg)
        sigma = np.nanstd(seg, ddof=0)
        out_sorted[s:e] = (seg - mu) / (sigma + std_min)

    # 5. clip
    np.clip(out_sorted, -clip_sigma, clip_sigma, out=out_sorted)

    # 6. 恢复原顺序
    out = np.full(n, np.nan, dtype=np.float64)
    out[sort_idx] = out_sorted

    return pd.Series(out, index=value.index)
```

### §4.2 内存对比

| 实现 | 中间对象 | 峰值 |
|------|---------|------|
| 当前 `groupby.transform` | pandas group 中间索引 + 重建 | ~1GB+ |
| 新 numpy 切片版 | 2× float64 ndarray (sort + out) | ~24MB |

**节省 ~1GB**，3 个交互因子 × 2 次调用 = 6 次累计节省 ~6GB，远超 OOM 缺口。

### §4.3 行为等价性

| 维度 | 旧实现 | 新实现 | 等价? |
|------|--------|--------|-------|
| 截面均值/std | `s.mean()/s.std(ddof=0)` | `np.nanmean(seg)/np.nanstd(seg, ddof=0)` | ✓（NaN 处理一致）|
| 截面 std=0 防除零 | `+ std_min` | `+ std_min` | ✓ |
| clip 边界 | `.clip(-cs, +cs)` | `np.clip(..., out=)` | ✓ |
| NaN 传播 | pandas 透传 | numpy 透传（`nanmean` 跳过 NaN，子样本无效时 NaN 行保留 NaN）| ✓ |
| 返回类型 | `pd.Series` 同 index | `pd.Series` 同 index | ✓ |
| 单日全 NaN | 输出全 NaN（mean/std=NaN）| 输出全 NaN（`nanmean` 警告 + NaN）| ✓ + 略多警告日志 |

**唯一行为差异**：单日截面全 NaN 时，numpy 会发 `RuntimeWarning: Mean of empty slice`。可用 `with warnings.catch_warnings()` 抑制。

### §4.4 现有 19 个单元测试覆盖

`test_factor_calculator_interaction.py` 的 `TestCrossSectionZScore` 5 测试已覆盖：
1. `test_basic_zscore`: 截面均值≈0, std≈1
2. `test_zero_std_handling`: 防除零
3. `test_clip`: clip ±3σ
4. `test_nan_propagation`: NaN 透传
5. `test_length_mismatch_raises`: 长度校验

**新实现必须让这 5 个测试不改一行全过**——这是行为等价的硬证据。

---

## §5 改动范围

| 文件 | 改动 | 行 |
|------|------|-----|
| `data_fetchers/factor_calculator/_common.py` | 重写 `_cross_section_zscore` 函数体 | ~50 |

**总计 1 文件 ~50 行**——远小于 H9 200 行上限。

---

## §6 验收计划

### §6.1 单元测试（必过）

```bash
python3 -m pytest data_fetchers/test_cases/test_factor_calculator_interaction.py \
                  data_fetchers/test_cases/test_factor_calculator.py \
                  -q --no-header
```

期望：62/62 通过（行为等价）。

### §6.2 max-RSS 量化验证

```bash
/usr/bin/time -v python3 data_fetchers/factor_generator.py 2>&1 | grep -E "Step 14|Maximum resident|interaction_"
```

期望：
- Step 14 完整跑通（3 个 interaction 因子全部 valid_count 输出）
- max-RSS ≤ 3.2GB（节省 6 次 groupby.transform 累计 1+GB）
- 进程退出 exit_code=0

### §6.3 IC 等价性验证

```bash
python3 temporary/verify_interaction_factors_ic.py
```

期望：3 个交互因子 IC 与旧实现一致：
- interaction_amplitude IC ≈ +0.0195（误差 < 0.001）
- interaction_turnover IC ≈ +0.0163
- interaction_amp_compression IC ≈ +0.0083

### §6.4 不做项

- ❌ 不引入 `_per_date_zscore` 新公开 API（保持现有 `_cross_section_zscore` 函数签名）
- ❌ 不改 3 个 calculate_interaction_* 函数（它们仍调用 `_cross_section_zscore`）
- ❌ 不引入 numba/cython 加速（pure numpy 已足够）

---

## §7 实施拆分

单 commit，1 文件 1 函数体重写。

---

## §8 与 Step 13 修复的关系

| 维度 | Step 13 修复 | Step 14 修复（本设计）|
|------|-------------|---------------------|
| OOM 根因 | sort_values().copy() 双拷贝 | groupby.transform 索引重建 |
| 修复模式 | 删冗余代码 | 替换 pandas API 为 numpy 切片 |
| 文件 | 2 (momentum + volume_price) | 1 (_common) |
| 行数 | 6 | ~50 |
| 复用项目模式 | — | `_per_asset_transform` 同源 |

两次都是**局部内存优化**，没有触及架构。
