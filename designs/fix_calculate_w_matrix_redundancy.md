# Design: calculate 内部 W 矩阵冗余提取 + 加权循环矩阵化

> **日期**: 2026-06-24
> **模式**: 模式9（冗余子矩阵分配）+ 模式3a（循环→矩阵化）
> **涉及文件**: `comprehensive_factor/common/weight_engine.py`
> **前置**: commit 3ff9bf7（方案A+B+D 已实施，Max RSS 5376MB）
> **目标**: 进一步降低 calculate 峰值 ~1.5GB，从 5.25GB 降至 ~3.75GB

## 问题分析

calculate 内部 L1296 和 L1482 两次提取同一 _dim_weight 矩阵到 numpy（780MB 冗余），
且加权循环 L1518-1528 逐列 Series 乘法可矩阵化。

## 修复方案

### 方案 E: 合并两次 W 提取为一次

**当前流程** (L1286-L1500):
```
L1286: pd.concat 添加 35 _dim_weight 列到 factor_df
L1296: W = factor_df[dim_weight_cols].to_numpy()     ← 第一次提取 390MB
L1297: W = W / total_weight_safe                      ← 归一化（新数组 390MB）
L1301: factor_df[dim_weight_cols] = W                 ← 写回 DataFrame
       del W (当前未 del)
L1482: W = factor_df[dim_weight_cols].to_numpy()     ← 第二次提取！390MB
L1484: W_capped = _cap_weight_matrix(W)               ← 内部 copy 390MB
L1500: factor_df[dim_weight_cols] = W_capped          ← 第二次写回
```

**优化后流程**:
```
L1286: pd.concat 添加 35 _dim_weight 列到 factor_df
L1296: W = factor_df[dim_weight_cols].to_numpy().copy()  ← 提取一次
L1297: W = W / total_weight_safe[:, None]                 ← 原地归一化
       (不写回 DataFrame，直接传给 cap)
L1484: W_capped = _cap_weight_matrix(W)                   ← cap 操作
       del W                                               ← 释放原始 W
L1500: factor_df[dim_weight_cols] = W_capped              ← 只写回一次
```

**省**: 390MB（第二次 W 提取）+ 390MB（中间写回 DataFrame 的列 copy）= 780MB

### 方案 F: 加权循环矩阵化

**当前实现** (L1518-1528):
```python
composite = pd.Series(0.0, index=factor_df.index)          # 11MB
valid_weight_per_row = pd.Series(0.0, index=factor_df.index)  # 11MB
for col, std_col, rolling_col in zip(factor_cols, std_cols, rolling_icir_cols):
    weight = factor_df[f"{col}_dim_weight"]                 # 11MB view
    weighted_value = (factor_df[std_col] * weight).fillna(0)  # 11MB temp
    is_valid = factor_df[std_col].notna()                   # 1.7MB temp
    composite = composite + weighted_value                  # 11MB new
    valid_weight_per_row = valid_weight_per_row + weight.where(is_valid, 0)  # 11MB new
```
35 次循环 × 临时 Series = ~385MB 峰值

**矩阵化**:
```python
std_matrix = factor_df[std_cols].to_numpy(dtype=float)      # 390MB
W_final = factor_df[dim_weight_cols].to_numpy(dtype=float)  # 390MB (or reuse W_capped)
# NaN 置 0
nan_mask = np.isnan(std_matrix)
std_matrix_safe = np.where(nan_mask, 0.0, std_matrix)       # 390MB
# 权重仅在因子有效时计入
W_masked = np.where(nan_mask, 0.0, W_final)                 # 390MB
composite = pd.Series(std_matrix_safe.sum(axis=1) ... no
# 正确: composite = Σ(std_i * w_i), valid_weight = Σ(w_i where std_i not NaN)
composite_np = (std_matrix_safe * W_masked).sum(axis=1)     # (n_days,) 11MB
valid_weight_np = W_masked.sum(axis=1)                       # (n_days,) 11MB
composite = pd.Series(composite_np / valid_weight_np, ...)
```

**省**: ~385MB 临时 Series + Python 循环开销

### 方案 G: _cap_weight_matrix 消除防御性 copy

L466 `W = W.copy()` → 调用方传入的 W 不再需要，可直接原地操作。

**省**: 390MB

## 数学等价性

| 方案 | 改什么 | 数学影响 |
|------|--------|---------|
| E | 合并两次提取，不写回中间结果 | 零 — 归一化→cap→写回，公式不变 |
| F | Σ(std_i × w_i) 循环→矩阵乘法 | 零 — 结合律，逐元素乘法+求和顺序不变 |
| G | cap 原地操作 vs copy | 零 — 同一矩阵上的同一算法 |

## 预期效果

| 优化 | 省内存 | 累计峰值 |
|------|--------|---------|
| 修复前 (3ff9bf7) | — | 5250MB |
| +方案E (合并W提取) | -780MB | ~4470MB |
| +方案F (加权矩阵化) | -385MB | ~4085MB |
| +方案G (cap原地) | -390MB | ~3695MB |
| **总计** | **-1555MB** | **~3695MB** |

## 规范引用

- PROJECT.md 硬规则 #14（死代码禁止——冗余提取为隐性死代码）
- pandas-oom skill 模式9（冗余子矩阵分配）+ 模式3a（循环→矩阵化）
