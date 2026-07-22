# Design: composite_runner 消除重复数据加载

> 遵循 PROJECT.md Design-First 规则（涉及 2+ 文件改动）
> 创建时间: 2026-06-09

## 问题

`run_composite_backtest` 三次加载同一 216MB gzip JSON 文件（`factor_ic_data.json.gz`），每次解析耗时 ~22s：

| 调用点 | 行号 | 函数 | 用途 |
|--------|------|------|------|
| Step 2（自动筛选） | 231 | `load_factor_values` | 计算全量因子相关性矩阵 |
| Step 1（正式加载） | 303 | `load_factor_values` | 加载筛选后因子值做标准化+加权 |
| Step 8（回测） | 498 | `load_factor_return_data` | 分离 return_df 传入回测引擎 |

三次加载总耗时 ~66s，加上 run_pipeline 重试 3 次 → **198s 纯 I/O 空耗**。
这是 4 个综合因子步骤全部超时失败（重试3次耗尽）的根因。

## 根因

三个函数各自独立读取 gzip → JSON → DataFrame，没有数据共享机制：
- `load_factor_values`（factor_loader.py）只返回因子列子集
- `load_factor_return_data`（layered_backtest_runner.py）分离 return_df
- 两者都从同一文件读取，但互不知道对方已经加载过

## 修复方案

**核心思路：一次加载，三个用途共享。**

在 `run_composite_backtest` 入口处一次性加载全量数据（full_df），后续三个步骤从中提取所需子集，不再独立调用文件 I/O。

### 改动清单（≤3 文件）

| 文件 | 改动 | 行数估计 |
|------|------|----------|
| `comprehensive_factor/common/composite_runner.py` | 主改动：重构 run_composite_backtest 数据加载流程 | ~80 行 |
| `comprehensive_factor/common/factor_loader.py` | 新增 `load_full_data()` 函数，一次加载返回完整 DataFrame | ~30 行 |
| `comprehensive_factor/MODULE.md` | 版本历史记录 | ~5 行 |

**不改动** `backtest/common/layered_backtest_runner.py`（跨模块边界，只复用自己目录的 common/，遵循 PROJECT.md H1 模块边界）。

### 详细设计

#### 1. factor_loader.py：新增 `load_full_data()`

```python
def load_full_data(
    data_source: str | Path | None = None,
    logger: logging.Logger | None = None,
) -> pd.DataFrame:
    """一次加载统一数据源，返回完整 DataFrame（所有列）
    
    用于 composite_runner 入口处一次性加载，后续步骤从中提取子集。
    """
    # 与 load_factor_values 相同的文件读取逻辑
    # 但返回 full_df（不筛选列、不释放 data）
    # 校验 date/asset 类型
    # 返回完整 DataFrame
```

#### 2. composite_runner.py：重构 run_composite_backtest

```
原流程:
  Step 2: load_factor_values(all_cols)  → all_factor_df（筛选用）
  Step 1: load_factor_values(selected)  → factor_df（加权用）
  Step 8: load_factor_return_data()     → return_df（回测用）

新流程:
  入口: load_full_data()                → full_df（一次加载）
  Step 2: full_df[all_cols]             → all_factor_df（筛选用，0 I/O）
  Step 1: full_df[selected_cols + date/asset] → factor_df（加权用，0 I/O）
  Step 8: full_df[return_cols]          → return_df（回测用，0 I/O）
```

关键改动点：
- 第 231 行：`load_factor_values` → 从 full_df 提取子集
- 第 303 行：`load_factor_values` → 从 full_df 提取子集
- 第 498 行：`load_factor_return_data` → 从 full_df 提取子集

**内存安全**：full_df ~1.49M 行 × ~30 列 ≈ 400MB，进程有足够内存。
完成后显式 `del full_df` 释放。

#### 3. MODULE.md：版本历史

新增 v2.10 版本记录：消除重复数据加载，一次加载三用途共享。

## 不做的事（Don't）

- ❌ 不改 `backtest/common/layered_backtest_runner.py`（跨模块边界，规则 #1）
- ❌ 不改 `load_factor_return_data` 的调用签名（保持向后兼容）
- ❌ 不在 `load_factor_values` 加缓存（简单子集提取即可，不需要复杂缓存机制）
- ❌ 不改 run_pipeline 的重试机制（根因是数据加载，不是重试逻辑）

## 验证方法

1. `ruff check --fix .` + `ruff format .`
2. `pytest comprehensive_factor/test_cases/` — 确保无回归
3. 手动验证：`python comprehensive_factor/composite_equal_weight_1d.py --auto_select` 执行时间应从 ~3min 降到 ~1min
4. Spec Compliance：对照 MODULE.md M21（数据来源单一数据源）、M47（Config 默认值单一数据源）
---

## 附录：v2.23 流式加载升级（2026-06-14）

### 背景

v2.10 通过"一次加载三用途共享"消除了重复数据加载，但 `factor_ic_data.json.gz` 文件随因子集扩展持续增长（149 万行 × 44 列 ≈ 389 MB gzip），`json.load` 一次性解析峰值达 4.5 GB，在 7.3 GB 总内存机器上触发 OOM Kill（exit code -9）：

```
2026-06-13 22:00 ~ 2026-06-14 15:30 期间
6 次 OOM Kill 同一脚本 composite_equal_weight_1d.py
dmesg: anon-rss:4.17GB python，每次 SIGKILL
```

### 升级方案

直接复用 `factor_ic v3` 已生产验证的 ijson 流式 + 列式 dict 累积模板（参考 `factor_ic/common/data_loader.py:111-153`）：

- **解析**：`ijson.items(f, "data.item")` 流式逐条
- **累积**：`dict[col, list]` 列式累积（避免 list[dict] 对象头开销）
- **构建**：`pd.DataFrame(列式字典)` 一次性列存
- **fallback**：`ImportError` 时回退到 `json.load`（向后兼容）

### 核心改动

| 改动 | 文件 | 行数 |
|------|------|------|
| `load_full_data` 改流式 + 加 `factor_cols` 参数 | `factor_loader.py` | ~70 |
| `load_factor_values` 委托给 `load_full_data` | `factor_loader.py` | ~30 |
| 配套测试 4 个 | `test_factor_loader_streaming.py` | ~150 |
| MODULE.md M21 加载机制说明 | `MODULE.md` | ~15 |

### 性能对比

| 路径 | 旧（v2.10） | 新（v2.23） | 变化 |
|------|-----------|-----------|------|
| `load_full_data()` 全列 | 4.5 GB | ~760 MB | **-83%** |
| `load_factor_values()` 列子集 | 4.5 GB | ~175 MB | **-96%** |
| 加载耗时（149 万行） | ~22s | ~150s | +6.8x（可接受：vs OOM 完全失败） |

### 设计文档

完整设计稿: `designs/composite_streaming_load_design.md`（含背景、方案、影响范围、数据流对比、测试方案、风险回滚、验收标准 9 章）。

---

## 附录：v2.24 daily.json.gz 流式写入（2026-06-19）

### 背景

v2.23 解决了数据加载阶段的 OOM，但输出阶段 `daily.json.gz` 生成仍存在 OOM Kill。2026-06-19 凌晨 cron pipeline 中，4 个综合因子脚本（equal/icir/ic/rolling_icir）全部在保存 JSON 结果后、生成 daily.json.gz 时被 OOM Kill（退出码 -9），重试 3 次均失败。

```
dmesg: Out of memory: Killed process 2503152 (python3) anon-rss:3867444kB
```

### 根因

`composite_runner.py` Step 10 原实现：

```python
daily_output = {
    "meta": {...},
    "data": backtest_convert(factor_df[output_cols].to_dict("records")),  # 1.5M dict 列表
}
with gzip.open(daily_file, "wt") as f:
    json.dump(daily_output, f, indent=2, ensure_ascii=False)  # 全量序列化
```

三重内存峰值：
1. `to_dict("records")` — 150万行 × 6列 → 150万个 dict 对象 ~750MB
2. `backtest_convert()` — 递归转换生成完整副本 ~750MB
3. `json.dump(indent=2)` — 构建完整 JSON 字符串 ~1GB

峰值合计 ~2.5GB + DataFrame 本身 ~400MB = ~2.9GB，在 7.3GB 系统（含其他进程）触发 OOM。

### 修复方案

流式分块写入：5000 行/块，逐块 `to_dict("records")` + `backtest_convert` + `json.dump`，直接写入 gzip 文件句柄。

| 路径 | 旧（v2.23） | 新（v2.24） | 变化 |
|------|-----------|-----------|------|
| daily.json.gz 峰值内存 | ~2.9 GB | ~365 MB | **-87%** |
| 输出 JSON 格式 | `indent=2` 缩进 | 无缩进（data 数组） | 文件更小，格式兼容 |

### 验证

- 150万行模拟数据：峰值 365MB，JSON 格式完整，块边界正确
- `pytest comprehensive_factor/test_cases/` 32 passed（排除预存在 fixture 错误）
