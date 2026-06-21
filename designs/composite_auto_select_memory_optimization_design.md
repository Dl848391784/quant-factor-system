# Design：综合因子模块 auto_select 阶段内存优化（OOM 修复）

> 遵循 AGENTS.md Design-First 流程（涉及 ≥2 文件改动）
> 创建日期：2026-06-21
> 作者：云瑶
> 状态：待审

---

## 1. 背景与目标

### 1.1 痛点（实测 OOM）

**故障现象**（2026-06-21）：

`composite_equal_weight_1d.py` 执行退出码 -9（SIGKILL），dmesg 记录：

```
Out of memory: Killed process ... total-vm:4166112kB, anon-rss:3595044kB
```

**与前次 OOM 的区别**：

v2.23（2026-06-14）修复了 `load_full_data` 数据加载阶段的 OOM（json.load → ijson 流式，峰值 4.5GB → 760MB）。
本次 OOM 不在加载阶段，而在 **auto_select 后续处理阶段**：对全量 45 因子做 standardize_factors + calc_factor_correlation。

### 1.2 根因（内存峰值叠加）

数据规模：1.49M 行 × 45 因子列（+ ~42 个其他数值列）。

composite_runner.py 内存峰值时间线：

```
  T0   load_full_data() (ijson)               ~0.5GB
  T1   all_factor_df = full_df[...].copy()    ~0.5GB   ← 45因子子集复制
       full_df 仍在持有                        ~0.5GB
  T2   standardize_factors(all_factor_df, 45cols)
       - factor_df.copy() 内部复制            ~0.5GB
       - 新增 45 个 _std 列                   ~0.5GB
       - 点质量检测 groupby(["date",col]).size()
         45次迭代 × ~48MB 临时结果             ~0.5GB(峰值)
       - pm_flags merge                       ~0.05GB × 45
       此时 total ≈ 2.5GB+
  T3   calc_factor_correlation()              ~0.1GB
       full_df 仍在持有                        ~0.5GB
       all_factor_df 仍在持有(90列)            ~1.0GB
       total ≈ 2.6GB+
  T4   select_factors()                       ~0.1GB
       full_df 仍在持有                        ~0.5GB
       all_factor_df 仍在持有                  ~1.0GB
       total ≈ 2.6GB+  ← OOM Kill 触发
```

叠加 Python/pandas 运行时碎片 ≈ **3.5GB+** → 在 7.3GB 系统（可用 ~3.2GB）触发 OOM。

**核心问题**：
1. `all_factor_df`（标准化后 90 列，~1GB）在 auto_select 完成后未释放
2. `full_df`（~0.5GB）在整个流程中一直持有，直到 Step 8 才 del
3. `standardize_factors` 对 45 因子执行点质量检测（groupby + merge 重复 45 次），产生大量临时对象

### 1.3 目标

1. 峰值内存降至 **< 2GB**（7.3GB 系统安全运行）
2. 零行为变更：筛选结果、综合因子值、回测结果完全一致
3. 只改公共模块（factor_loader.py + composite_runner.py），4 个 CLI 脚本不变

---

## 2. 方案设计

### 2.1 三层优化策略

| 层 | 策略 | 预估收益 | 第一性原理依据 |
|----|------|---------|--------------|
| **L1: 及时释放** | auto_select 完成后立即 del all_factor_df/all_corr_matrix + gc.collect() | -1.0GB | 内存生命周期应匹配数据使用周期；不再需要的中间产物不应驻留 |
| **L2: 简化标准化** | auto_select 阶段用简化版 standardize_factors（跳过点质量检测），选中因子才做完整版 | -0.5GB | 点质量检测是「最终因子值质量守卫」，目的为确保入选因子 z-score 无失真；筛选阶段的标准化仅用于相关性计算，相关性矩阵只需粗粒度 z-score 即可（Pearson corr 对极端值有一定鲁棒性） |
| **L3: 提前释放 full_df** | 在提取完 all_factor_df 和 return_df 后立即 del full_df（而非等到 Step 8） | -0.5GB | full_df 是数据源容器，所有子集提取完成后即无使用价值；延迟释放是原代码的历史遗留（v2.10 一次性加载设计时，Step 8 才提取 return_df） |

### 2.2 L2 简化标准化：接口设计

**factor_loader.py — standardize_factors 新增 `skip_point_mass` 参数**：

```python
def standardize_factors(
    factor_df: pd.DataFrame,
    factor_cols: list[str],
    logger: logging.Logger | None = None,
    skip_point_mass: bool = False,  # 新增：auto_select 简化模式跳过点质量检测
) -> pd.DataFrame:
```

**语义**：
- `skip_point_mass=False`（默认）：完整标准化，含 Winsorize ±3σ + 点质量检测 + NaN 还原 → 用于最终入选因子
- `skip_point_mass=True`：仅做截面 z-score（groupby transform）+ Winsorize ±3σ → 用于 auto_select 相关性计算

**合理性论证（第一性原理）**：

相关性矩阵的计算输入是标准化后的因子值。点质量检测将 z-score 置 NaN，影响的是「同一因子内部的极端值」，而非「因子间的线性关系」。对于 Pearson 相关系数：
- 如果某因子的 z-score 有 2% 被置 NaN，corr() 会自动跳过 NaN pair，结果几乎不变
- 即使不做点质量检测， Winsorize ±3σ 已经截断了极端值，corr() 的结果在 0.01 精度内一致

因此，auto_select 阶段跳过点质量检测是**无损简化**：相关性矩阵精度不受影响，筛选结果一致。

### 2.3 优化后的内存时间线

```
  T0   load_full_data() (ijson)               ~0.5GB
  T1   all_factor_df = full_df[...].copy()    ~0.5GB   ← 45因子子集
       standardize_factors(skip_point_mass=True)
       - factor_df.copy()                     ~0.5GB
       - 新增 45 个 _std 列                   ~0.5GB
       - 无 groupby+merge 临时结果            ~0GB
       total ≈ 1.5GB
  T2   calc_factor_correlation()              ~0.1GB
  T3   select_factors()                       ~0.1GB
  T3.5 del all_factor_df/all_corr_matrix      ← 立即释放 -1.0GB
       gc.collect()
       total ≈ 0.6GB
  T4   return_df = full_df[...].copy()        ~0.1GB
       del full_df; gc.collect()              ← 提前释放 -0.5GB
       total ≈ 0.2GB
  T5   factor_df = full_df[cols].copy()       ← full_df 已释放
       改为从 all_factor_df 不再可行（已 del）
       改为重新 load_full_data(factor_cols=选中因子) ~0.1GB
       standardize_factors(完整版)             ~0.1GB
       total ≈ 0.4GB
  T6   backtest + 保存                        ~0.3GB
       total ≈ 0.7GB ★ 峰值 < 1.5GB
```

等等，T5 需要重新加载因子数据... 但这会增加一次 I/O（~22s）。

**方案 A**：auto_select 后释放中间数据，重新 load_full_data(factor_cols=选中因子列) 获取选中因子数据
**方案 B**：不释放 full_df，直接从中提取选中因子子集，只在 auto_select 中间产物上 del

方案 B 更简单，峰值估算：
```
  T0   full_df                                ~0.5GB
  T1   all_factor_df(简化标准化90列)           ~1.0GB
       total ≈ 1.5GB
  T3   del all_factor_df                      ← -1.0GB
       total ≈ 0.5GB
  T4   factor_df = full_df[cols].copy()       ~0.1GB
       standardize_factors(完整版)             ~0.2GB
       return_df = full_df[cols].copy()       ~0.1GB
       total ≈ 0.9GB
  T5   del full_df                            ← -0.5GB
       total ≈ 0.4GB
```

峰值 1.5GB，远低于 OOM 阈值。**方案 B 更优**（无额外 I/O，改动更少）。

### 2.4 具体改动清单

| # | 文件 | 改动 | 行数 |
|---|------|------|------|
| 1 | `factor_loader.py` | `standardize_factors` 新增 `skip_point_mass` 参数，True 时跳过点质量检测相关代码块 | ~20行 |
| 2 | `composite_runner.py` | (a) auto_select 阶段调用 `standardize_factors(skip_point_mass=True)` (b) auto_select 完成后 `del all_factor_df, all_corr_matrix; gc.collect()` (c) 提前提取 return_df 后 `del full_df; gc.collect()` (d) factor_df 提取改为在 full_df 释放前完成 | ~15行 |

**总规模**：~35 行，2 个文件，≤3 文件 ≤200 行约束满足。

---

## 3. 决策矩阵

| 决策 | 选项 A | 选项 B（采用） | 理由 |
|------|--------|---------------|------|
| full_df 释放时机 | auto_select 后立即 del + 重新加载选中因子 | full_df 保留到子集提取完成后 del | A 需额外 ~22s I/O，B 零额外开销 |
| auto_select 标准化 | 完整版（含点质量检测） | 简化版（skip_point_mass=True） | 点质量检测仅影响 z-score NaN 标记，corr() 对 NaN 鲁棒，筛选结果一致 |
| 中间数据释放 | 不释放（保持到函数结束） | auto_select 完成后立即 del | 内存生命周期应匹配使用周期 |
| 选中因子标准化 | 已在 all_factor_df 中完成 | 从 full_df 重新提取 + 完整版标准化 | all_factor_df 已 del，需重新提取；且选中因子需完整版标准化（含点质量检测） |

---

## 4. 数据流对比

### 4.1 旧流程（OOM）

```
full_df ──┬── all_factor_df[45cols].copy() ── standardize(完整版) ── corr_matrix ── select_factors
           │                                     ↑ 90列 ~1GB 驻留至函数结束
           ├── factor_df[cols].copy() ── standardize(完整版)
           │                                     ↑ ~0.3GB
           └── return_df[cols].copy()            ← Step 8 才提取
           └── del full_df                       ← Step 8 才释放
```

峰值：full_df(0.5G) + all_factor_df(1G) + factor_df(0.3G) ≈ 1.8GB + 运行时碎片 ≈ **2.5-3.5GB**

### 4.2 新流程（优化后）

```
full_df ──┬── all_factor_df[45cols].copy() ── standardize(简化版,skip_point_mass=True) ── corr_matrix ── select_factors
           │                                     ↑ 90列 ~1GB
           │── [del all_factor_df, all_corr_matrix] ← 立即释放
           │── factor_df[cols].copy() ── standardize(完整版) ← 从 full_df 提取
           │── return_df[cols].copy()             ← 提前提取
           │── [del full_df]                      ← 提前释放
```

峰值：full_df(0.5G) + all_factor_df(1G) ≈ **1.5GB**（all_factor_df 存在期间）

all_factor_df 释放后：full_df(0.5G) + factor_df(0.2G) + return_df(0.1G) ≈ **0.8GB**

---

## 5. 测试方案

### 5.1 验证标准

| # | 验证项 | 方法 |
|---|--------|------|
| V1 | `skip_point_mass=True` 输出列集合与 `False` 一致（45个 _std 列都生成） | pytest: 比较列名 |
| V2 | `skip_point_mass=True` 的 z-score 值不含 NaN（除了原始 NaN），`False` 版可能含 NaN | pytest: 简化版 NaN count ≤ 原始 NaN count |
| V3 | corr_matrix 精度：简化版 vs 完整版差异 < 0.01 | pytest: 两个 corr_matrix 最大元素差 |
| V4 | 退出码 = 0（不再 OOM） | 实测运行 composite_equal_weight_1d.py |

### 5.2 测试位置

`comprehensive_factor/test_cases/test_factor_loader.py`（追加测试到已有文件）

---

## 6. 风险与回滚

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| 简化版 corr_matrix 与完整版差异导致筛选结果不同 | 低（<0.01差异） | 筛选因子列表变化 | V3 测试验证；若差异超阈值则回退到完整版 |
| gc.collect() 导致性能抖动 | 极低 | ~0.1s 延迟 | 可接受 |
| full_df 提前释放后下游需要 full_df 列 | 中 | KeyError | 确保所有子集在 del 前提取完毕 |

回滚策略：删除 `skip_point_mass` 参数传递 + 删除 `del` 语句即可恢复原行为。

---

## 7. 关联规范

- AGENTS.md 规则 #14（死代码禁止）：del 语句不是死代码，是内存管理
- AGENTS.md 规则 #13（日志格式 % 惰性格式化）
- PROJECT.md 跨模块数据路径规范
- MODULE.md M9-M11（标准化规范）
