# Design: RollingICIR calculate 维度权重 OOM 修复

> **日期**: 2026-06-24
> **模式**: 模式 9（嵌套循环冗余子矩阵分配）+ 模式 3e（列清理）+ 重试熔断
> **涉及文件**: `comprehensive_factor/common/weight_engine.py`, `run_pipeline.py`
> **规范引用**: PROJECT.md 硬规则 #14（死代码禁止）、AGENTS.md 第一性原理

---

## 1. 问题

`composite_rolling_icir_weight_1d` 在 `RollingICIRWeightMethod.calculate()` 阶段反复 OOM（dmesg 确认 RSS 5.8GB SIGKILL）。前序 8 次 OOM 修复（模式 3a-3d, 7, 8）已将 `standardize_factors` 峰值降到 2.1GB，但 `calculate()` 峰值仍达 5.8GB。

## 2. 根因（第一性原理推导）

### 2.1 计算的是什么（不变量）

维度权重公式（design.md v1.20 方案 B，icir 模式）：

```
weight_i = intra_weight_i × dim_weight_d

  intra_weight_i = |icir_i| / Σ_{j∈dim(i)} |icir_j|           (维度内归一化)
  dim_weight_d   = mean_{j∈dim(d)} |icir_j| / Σ_{d'} mean     (维度间归一化)
```

计算结果**只依赖 `|icir_i|` 的值**，不依赖内存分配方式。

### 2.2 当前实现的冗余（可变量）

`_apply_dimension_weights`（L1218-1266）有两个循环，**各自独立调用** `factor_df[dim_rolling_cols].abs()`：

| 位置 | 代码 | 分配量 |
|------|------|--------|
| L1222（循环1） | `dim_abs_icir = factor_df[dim_rolling_cols].abs()` | 390MB |
| L1250（循环2） | `dim_abs_icir = factor_df[dim_rolling_cols].abs()` | 390MB（**重复**） |

两次 `.abs()` 计算的是**同一子矩阵的绝对值**，结果完全相同。第二次是冗余分配。

### 2.3 内存账（实测）

calculate 阶段峰值 5.8GB 的构成：

| 组件 | 内存 |
|------|------|
| factor_df（date + 35 _std + 35 _rolling_icir = 71列） | 790MB |
| 循环1 dim_abs_icir（35列×1.39M） | 390MB |
| 循环2 dim_abs_icir（重复分配） | 390MB |
| 35 _dim_weight 列（pd.concat） | 390MB |
| W = to_numpy(dtype=float) 矩阵 copy | 390MB |
| dim_weight_data dict（35 Series 累积） | 390MB |
| **理论峰值** | **~2.7GB** |
| glibc/numpy 分配器碎片 | ~3.1GB |
| **实测峰值** | **5.8GB** |

### 2.4 重试放大

`run_pipeline.py` 的 `MAX_RETRIES=3` + `RETRY_DELAY=30s` 对 SIGKILL（exit -9）触发重试。OOM 是确定性失败（内存不变，结果不变），重试只会再次 OOM，4 次重试 × 5min = 20min 纯浪费。

## 3. 方案

### 方案 A：`_apply_dimension_weights` 矩阵化（模式 9）

**改什么**：预计算一次 `abs_icir_matrix = factor_df[rolling_icir_cols].abs().to_numpy()`，两个循环复用同一矩阵。

**不改什么**：维度权重公式、NaN 处理、回退逻辑。

**数学等价性**：`|x|` 是纯函数，预计算不改变值。pandas `.abs()` 和 numpy `.abs()` 对 NaN 都返回 NaN。输出 bit-exact 相同。

**改动位置**：`weight_engine.py` L1213-1266（`_apply_dimension_weights` 方法体）

### 方案 B：calculate 内提前释放 `_rolling_icir` 列（模式 3e 列清理）

**改什么**：`_apply_dimension_weights` 返回后（L1424），`_dim_weight` 列已计算完毕，此时 35 个 `_rolling_icir` 列（390MB）不再被后续加权循环使用。提前 drop。

**不改什么**：加权公式、cap 逻辑、`_last_day_weights` 提取。

**依赖点分析**：
1. `_extract_weights_from_row` 回退分支（L1562-1584）：**无影响**——L1543 优先检查 `_dim_weight` 列是否存在，`_apply_dimension_weights` 一定生成这些列，永远不走回退。
2. `valid_rows` 查找（L1597）：**需预计算**——删除前先用 `factor_df[rolling_icir_cols].notna().any(axis=1)` 算出 boolean mask，删除后用 mask 替代。

**改动位置**：`weight_engine.py` L1424（`_apply_dimension_weights` 调用后）+ L1597（`valid_rows` 查找）

### 方案 D：run_pipeline SIGKILL 不重试

**改什么**：`run_script` 检测到 `returncode == -9`（SIGKILL）时，不触发重试，直接标记失败。

**不改什么**：超时重试、其他错误码重试。

**理由**：OOM 是确定性失败，重试不会成功。第一性原理——重试的前提是"失败是瞬态的"，但 SIGKILL by OOM 是稳态的（内存不变）。

**改动位置**：`run_pipeline.py` L627-632（`run_script_with_retry` 循环）

## 4. Don't

- ❌ 不改变维度权重公式（`intra_weight × dim_weight`）
- ❌ 不改变 NaN 回退逻辑（`fillna(1/n)`）
- ❌ 不改变 cap 逻辑（`_cap_weight_matrix`）
- ❌ 不改变 `_last_day_weights` 提取逻辑
- ❌ 不对 SIGKILL 以外的退出码禁用重试

## 5. 验证

1. **数学等价性**：pytest 现有 331 个 weight_engine/composite 测试全过
2. **内存峰值**：`/usr/bin/time -v python composite_rolling_icir_weight_1d.py` 确认 max RSS < 4.5GB
3. **端到端**：pipeline 跑通，输出 `composite_rolling_icir_weight_1d.json` + daily parquet
4. **重试熔断**：SIGKILL 后不重试，stdout 打印"OOM SIGKILL，不重试"

## 6. 任务拆分

| # | 文件 | 改动 | 行数 |
|---|------|------|------|
| 1 | weight_engine.py | 方案 A：`_apply_dimension_weights` 矩阵化 | ~40行 |
| 2 | weight_engine.py | 方案 B：calculate 内 drop `_rolling_icir` + 预计算 mask | ~10行 |
| 3 | run_pipeline.py | 方案 D：SIGKILL 不重试 | ~10行 |

总计 ≤60 行，≤3 文件，符合任务粒度约束。
