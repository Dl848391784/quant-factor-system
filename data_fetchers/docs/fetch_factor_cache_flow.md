# fetch_factor_cache.py 流程文档

> 版本: v1.4
> 创建时间: 2026-05-26
> 更新时间: 2026-06-15 北京时间

---

## 概述

**脚本用途：** 分批拉取500天因子数据，使用外部排序流式合并实现极致内存优化。

**核心策略：**
1. 将股票分成多批（每批250只）
2. 每批拉取后立即保存到独立的 gzip 文件
3. 外部排序合并：N-way merge 合并已排序的批次
4. 内存峰值：仅一个批次数据 + N个最小记录

---

## 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                      main()                                  │
│  1. 获取股票列表                                             │
│  2. 分批拉取数据                                             │
│  3. N-way merge 合并                                         │
│  4. 格式化最终输出                                           │
│  5. 验证数据完整性                                           │
│  6. 清理临时文件                                             │
└─────────────────────────────────────────────────────────────┘
        │                    │                    │
        ▼                    ▼                    ▼
  fetch_batch_stocks   n_way_merge_deduplicate  format_final_output
        │                    │                    │
        ▼                    ▼                    ▼
  save_batch_cache_sorted  BatchStream          validate_final_data
```

---

## 流程步骤

### Step 1: 获取股票列表

```python
loader = RealDataLoader(enable_cache=True, use_mock=False, use_local=False, retries=3)
stock_list = loader.get_main_board_stocks(max_stocks=0)
```

**输出：**
- 主板股票列表（约5000只）

---

### Step 2: 分批拉取数据

```python
batches = [stock_list[i:i+BATCH_SIZE] for i in range(0, total_stocks, BATCH_SIZE)]
for batch_idx, stock_batch in enumerate(batches):
    factor_df, return_df = fetch_batch_stocks(loader, stock_batch, batch_idx, total_batches)
    save_batch_cache_sorted(batch_idx, factor_df, return_df)
```

**关键函数：**
- `fetch_batch_stocks()`: 拉取一批股票数据
- `save_batch_cache_sorted()`: 保存单批次数据到临时文件（预先排序）

**内存管理：**
- 每个子批次后强制 GC
- 内存超阈值时暂停（MEMORY_THRESHOLD_MB = 900MB）

---

### Step 3: N-way merge 合并

```python
factor_merged_path, factor_count = n_way_merge_deduplicate(total_batches, 'factor')
return_merged_path, return_count = n_way_merge_deduplicate(total_batches, 'return')
```

**关键类：**
- `BatchStream`: 批次数据流式读取器

**合并策略：**
- 使用 heap 进行 N-way merge
- 去重：相同 (date, asset) 只保留最后一次出现的值

---

### Step 4: 格式化最终输出

```python
n_days, n_assets, n_records = format_final_output(factor_merged_path, return_merged_path)
```

**输出文件：**
- `factor_data.json.gz`: 因子数据
- `return_data.json.gz`: 收益数据

**数据结构：**
```json
{
  "meta": {
    "generated_at": "2026-04-09T...",
    "source": "sina_api_batch_external_merge",
    "n_days": 500,
    "n_assets": 5000,
    "date_range": { "start": "...", "end": "..." },
    "version": "3.4_with_ohlc",
    "fields": ["date", "asset", "open", "close", "high", "low", "rsi_6", "volume_ratio_5"]
  },
  "data": [...]
}
```

---

### Step 5: 验证数据完整性

```python
is_valid, actual_days, actual_assets, actual_records = validate_final_data()
```

**验证项：**
- 交易日数 >= N_DAYS * 0.9
- RSI(6) 样本范围检查

---

### Step 6: 清理临时文件

```python
cleanup_batch_files(total_batches)
```

**删除文件：**
- `batch_{idx}_factor.json.gz`
- `batch_{idx}_return.json.gz`

---

## 配置参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| N_DAYS | 500 | 目标交易日数 |
| BATCH_SIZE | 250 | 每批股票数量 |
| FETCH_DAYS | int(N_DAYS * 1.5) + 30 | 实际拉取天数 |
| MEMORY_THRESHOLD_MB | 900 | 内存警告阈值 |
| MEMORY_PAUSE_SECONDS | 15 | 内存超阈值暂停时间 |

---

## 输出目录

```
cache/factor_data/
├── factor_data.json.gz      # 最终因子数据
├── return_data.json.gz      # 最终收益数据
├── regenerate_stats.json    # 运行统计
└── batch_*.json.gz          # 临时批次文件（合并后删除）
```

---

## 版本历史

- v1.4 (2026-06-15): 3 项编号体系治理与状态机健壮性修复
  - **修复 issue 编号冲突彻底消除**（issue #11）：v1.1/v1.2/v1.3 各自独立编号导致 issue #4 在三轮修复中分别指代"模块顶层 mkdir 副作用"、"末批 sleep 条件化"、"内存超阈值 warning 加子批次编号"三个不同问题。即使 v1.3 已用 `(v1.2，末批 sleep)` / `(v1.3)` 文字消歧，仍属于"用文字掩盖根本编号冲突"。本轮在文件头 docstring 建立**全局编号索引**（v1.1=#1~#8、v1.2=#1~#3+#9+#5、v1.3=#1~#3+#10、v1.4=#11~#13），将 v1.2 末批 sleep 改为 issue #9、v1.3 内存超阈值 warning 改为 issue #10，编号全局唯一不重复，跨版本可追溯
  - **validate_final_data 阶段 A `brace_count<0` 异常分支拦截**（issue #12）：原阶段 A `brace_count = sub.count("{") - sub.count("}")` 后仅判断 `> 0` 与隐含 `== 0`，缺失负数分支。当 meta 起始行截取子串 `}` 多于 `{`（格式异常 JSON / 截断输入），负数会 fall-through 到阶段 B，后续每行被 `elif in_meta` 捕获并继续累计负数，永远无法归零收敛，整个文件剩余内容被当作 meta 行消费而跳过 DATA 阶段，records_count=0，validate 返回 False 但**日志无任何针对负数 brace_count 的警告**（静默失败）。修复：阶段 A 增加 `if brace_count < 0` 分支，记录 warning 并重置 `in_meta=False`/`meta_lines=[]`/`brace_count=0` 后 `continue`，确保后续 DATA 阶段仍可推进
  - **`n_records_in_meta` 初值改 None 区分语义**（issue #13）：原 `records_valid = (records_count == n_records_in_meta) or (n_records_in_meta == 0)` 表达式中，`n_records_in_meta == 0` 同时覆盖两种语义截然不同的场景：(a) meta 中确实未提供 n_records 字段（合理豁免），(b) meta 解析失败导致变量保持初始值 0（应当告警）。两种场景无法区分 → meta 解析失败时静默通过记录数校验。修复：`n_records_in_meta: int | None = None` 初值改 None，`meta.get("n_records")` 不传默认值（缺失时返回 None），`json.JSONDecodeError` 分支显式赋 None；`records_valid = n_records_in_meta is None or records_count == n_records_in_meta` 让"字段缺失"与"解析失败"语义统一为 None；`if not records_valid and n_records_in_meta is not None and n_records_in_meta > 0` 守卫确保 None 不触发 `>` 误用
- v1.3 (2026-06-15): 4 项注释精确化与可观测性补强
  - **validate_final_data 守卫块必要性说明**：阶段 B 末尾 `if in_meta: continue` 守卫块**非冗余** — 若 meta 多行某行的字段值合法包含 `"data": [` 字面子串（如 fields 描述），缺失此守卫会 fall-through 污染 in_data 状态。注释从"本行已消费"改为明确防污染说明（issue #1）
  - **末批 sleep 修复注释消歧**：v1.1 issue #4 是模块顶层 mkdir 副作用，v1.2 issue #4 是末批 sleep — 同编号不同问题。给 v1.2 修复注释加 `(v1.2，末批 sleep)` 版本前缀并交叉引用 v1.1 的 mkdir 修复行号（issue #2）。**注**：v1.4 issue #11 进一步将该问题统一改 issue #9，本条仅保留历史描述
  - **validate_final_data 文件不存在前置检查**：在 gzip.open 之前显式 `if not factor_path.exists()` 判断，用 logger.error 输出含完整路径的明确信息；与 IO 中途失败（保留 warning + path + 异常类型）两类错误区分处理（issue #3）
  - **内存超阈值 warning 含子批次编号**：扩展 `⚠ 内存超阈值` warning 日志格式为 `⚠ [子批次 N/M] 内存超阈值 ...`，使内存压力下子批次粒度进度仍可追踪，与正常路径 logger.debug 输出对称（issue #4）。**注**：v1.4 issue #11 进一步将该问题统一改 issue #10，本条仅保留历史描述
- v1.2 (2026-06-15): 5 项控制流与失败路径修复
  - **validate_final_data 状态机重写**：消除原 if/elif/独立-if 三段并存的歧义控制流，重写为清晰的两阶段状态机（阶段 A 进入 + 阶段 B 累计 + 共用归零收敛点），单行/多行 meta 路径对称（issue #1）
  - **meta 内存释放对称化**：归零块同步 `del meta_content + del meta_lines + meta_lines = []`，与 sample_records 的 del 释放原则一致；移除"list 占用可忽略"的不准确注释（issue #2）
  - **format_final_output 输出兜底校验**：调用后、validate_final_data 前显式校验 `factor_data.json.gz` / `return_data.json.gz` 是否存在，避免静默写入失败时对旧文件/不完整文件产生 is_valid=True 误判（issue #3）
  - **末批 sleep(5) 跳过**：批次循环 `time.sleep(5)` 改为 `if batch_idx < total_batches - 1` 条件化，与子批次 `time.sleep(2)` 处理原则一致（issue #4）
  - **零批次成功快速失败**：批次循环结束后 `if successful == 0` 立即记录明确错误日志并 return False，避免无意义进入 N-way merge 阶段（issue #5）
- v1.1 (2026-06-15): 8 项稳健性修复
  - **validate_final_data meta 解析**：分离"进入分支(子串)"与"累计分支(stripped)"的 brace_count 统计；修复单行完整 meta 时 continue 导致的死循环（issue #1+#2）
  - **fetch_batch_stocks 截取稳定性**：`groupby.cumcount(ascending=False)` 之前显式 `sort_values(["asset","date"], kind="mergesort")` + reset_index，保证降序编号严格对应日期降序（issue #3）
  - **import 副作用消除**：模块级 `RESULT_DIR.mkdir` 移入 main() 首次使用前调用（issue #4）
  - **finally 健壮性**：main() 顶部初始化 `total_batches = 0`，避免 batches 计算前抛异常时 finally 块触发 UnboundLocalError（issue #5）
  - **冗余等待消除**：子批次内存超阈值 `time.sleep(MEMORY_PAUSE_SECONDS)` 后 `continue`，跳过无条件 `time.sleep(2)` 双重等待（issue #6）
  - **日志降噪**：子批次拉取/内存日志降级为 logger.debug（每批 8 个子批次的冗余 info 输出）（issue #7）
  - **代码整洁**：删除 `del meta_lines` 后多余的 `meta_lines = []` 重置（issue #8）
- v3.4_with_ohlc (2026-04-09): 新增 open/high/low 字段，支持选股回测
- v3.3 (2026-04-04): 外部排序 N-way merge，峰值内存优化
- v1.0 (2026-05-26): 流程文档创建

---

*最后更新: 2026-06-15 北京时间*