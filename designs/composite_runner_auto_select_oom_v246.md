# composite_runner auto_select OOM 修复 (v2.46)

**Author**: 云瑶
**Date**: 2026-06-23
**Status**: implementing
**Related**: pandas-oom-optimization-patterns skill 模式 3a (末端 copy + 失效契约), AGENTS.md 硬规则 #1/3

---

## 1. 背景

### 1.1 失败现象

2026-06-23 21:43 后台跑 `run_pipeline.py --start-stage 4` 时，**4 个 composite 脚本全部 SIGKILL (exit -9)**:

```
[composite_equal] ✗ 执行失败 (耗时 6.0s, 退出码 -9)
[composite_icir] ✗ 执行失败 (耗时 6.0s, 退出码 -9)
[composite_ic] ✗ 执行失败 (耗时 5.6s, 退出码 -9)
[composite_rolling_icir] ✗ 执行失败 (耗时 5.8s, 退出码 -9)
```

dmesg 实锤 OOM:
```
[21:46:05] oom-kill: task=python3, pid=2725620
           total-vm:6119144kB, anon-rss:3223688kB
```

每个 composite 进程被 OOM killer 杀于"加载所有因子数据用于相关性计算"步骤。

### 1.2 内存预算

- 物理内存 7.3 GB
- 其他进程已占用 ~4.1 GB (hermes-webui 1.6G + pyright 1.1G + hermes 本体 0.6G + 其他)
- composite 可用 ~3 GB
- composite 实测峰值 ~3.2 GB → **撞顶 OOM**

baseline (v2.39 / 06-22) 能跑通是因为当时其他进程占用更低 (~3.5G)，composite 同样的 3.2G 峰值刚好不撞顶。**OOM 不是 v2.45 改动引起**——require_positive_ic 是 selector 内部的 if 分支，零内存开销，且 SIGKILL 发生在 selector 调用之前。

### 1.3 OOM 链路

```
composite_runner.run_composite_pipeline() auto_select=True 路径:

L252:  full_df = load_full_data()                                   → 800 MB
L280:  all_factor_df = full_df[44列因子].copy()                     → +600 MB → 共 1.4 GB
L290:  return_df = full_df[5列].copy()                              → +120 MB → 共 1.52 GB
L293:  del full_df + gc.collect()                                   → -800 MB → 共 720 MB
L321:  standardize_factors(all_factor_df, ...)
       └─ L600: factor_df = factor_df.copy()                        → +600 MB → 共 1.32 GB
       └─ 新增 N 个 _std 列                                          → +600 MB → 共 1.93 GB
L325:  calc_factor_correlation(all_factor_df, ...)
       └─ 内部 pearson_corr 临时矩阵                                  → +300 MB → 共 2.23 GB
+ Python interpreter / pyarrow / pandas overhead ~1 GB              → 共 ~3.2 GB
→ 撞 OOM
```

**根本症结**：L280 的 `all_factor_df = full_df.copy()` **发生在 full_df 释放之前**，瞬时叠加峰值 1.4 GB。即使后续 del 也来不及——后续 standardize_factors 再叠 1.2 GB。

---

## 2. 修复方案

### 2.1 What

**重排 auto_select 内部步骤顺序**：
1. 先从 full_df 提取 return_df (轻量 ~120 MB)
2. **立即** del full_df + gc.collect (释放 800 MB)
3. 用 `load_full_data(factor_cols=all_factor_cols)` **二次列投影加载** all_factor_df (~600 MB)
4. 标准化 + 相关性计算 (峰值 ~1.2 GB)
5. 提取 factor_df → 释放 all_factor_df

### 2.2 How（代码改动）

```python
# 原 L275-297
all_factor_df = full_df[required_all_cols].copy()  # ⚠️ full_df 还在, 瞬时叠加
...
return_df = full_df[return_cols].copy()
del full_df

# 改为：
return_df = full_df[return_cols].copy()            # ✅ 先提取轻量数据
del full_df                                         # ✅ 释放 800 MB
gc.collect()

# 二次列投影加载因子数据（峰值约 600 MB, 此时 full_df 已释放）
logger.info("二次列投影加载因子数据用于相关性计算...")
all_factor_df = load_full_data(
    data_source=data_source,
    factor_cols=all_factor_cols_for_load,  # 仅加载因子列
    logger=logger,
)
# 注意: load_full_data 强制带 date/asset/return 列+过滤 untradeable/low_liq
#       与第一次加载行对齐自动保证 (相同 parquet + 相同过滤逻辑 + reset_index)
```

### 2.3 内存峰值对比

| 阶段 | 修复前峰值 | 修复后峰值 |
|---|---|---|
| L280 copy | **1.4 GB** | - |
| 二次加载 | - | 0.6 GB (full_df 已释放) |
| standardize | 1.93 GB | 1.2 GB |
| corr_matrix | **2.23 GB** | 1.5 GB |
| **总 anon-rss** | **3.2 GB (OOM)** | **~2.5 GB** |

预计修复后峰值 ~2.5 GB，留出 500 MB 余量。

### 2.4 时间成本

二次加载新增 parquet 列投影读取，预计 ~2-3 秒/composite。4 个 composite 共增 ~10s（vs 单次跑 ~10 分钟），可接受。

### 2.5 Don't

- ❌ **不改 `standardize_factors` 的 L600 内部 `.copy()`**：那是模块独立约束，影响面太大
- ❌ **不并行加载**：内存预算紧张，串行最稳
- ❌ **不跳过 untradeable/low_liquidity 过滤**：会破坏数据契约
- ❌ **不改 4 个 composite 入口脚本**：修复在 composite_runner.py 单文件内完成

---

## 3. 验证

### 3.1 单元测试

无需新增测试 — 行为不变（all_factor_df 内容与原方案完全等价，仅加载顺序变化）。已有 337 个测试覆盖回归。

### 3.2 集成验证

```bash
# 1. 单脚本验证 (跑得通 + max-RSS < 3GB)
/usr/bin/time -v python3 comprehensive_factor/composite_equal_weight_1d.py --dimension_weight icir 2>&1 | tee /tmp/composite_oom_test.log
grep "Maximum resident set size" /tmp/composite_oom_test.log
# 预期: Maximum resident set size (kbytes): < 2700000 (< 2.7 GB)

# 2. 完整 pipeline
python3 run_pipeline.py --start-stage 4
# 预期: 7/7 成功
```

### 3.3 数据契约一致性

修复后 `composite_*_weight_1d.json` 输出与历史 baseline 字段集应完全一致（同样的 selected 因子列表 + 同样的 composite 值）。允许 floating-point 末位差异。

---

## 4. 回滚

如出现异常：`git revert <commit>` 即可。改动仅 1 文件 (composite_runner.py) ~30 行。
