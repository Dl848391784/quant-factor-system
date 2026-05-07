# 测试报告：regenerate_cache_batch.py v3.2_streaming

**测试时间**: 2026-04-04 11:08-11:18  
**测试环境**: Linux x64, 3.5GB RAM, ~1.7GB available  
**脚本版本**: 3.2_streaming

---

## 📊 测试结果摘要

| 测试项 | 预期 | 实际 | 状态 |
|--------|------|------|------|
| 版本号 | 3.2_streaming | 3.2_streaming | ✅ |
| 因子数据字段 | date, asset, close, rsi_6, volume_ratio_5 | 完全一致 | ✅ |
| 收益数据字段 | date, asset, forward_return_1d/3d/5d | 完全一致 | ✅ |
| 内存峰值 | < 1GB | **OOM (1.9GB)** | ❌ |
| 无OOM错误 | 无 | **OOM killed** | ❌ |
| 批次完成 | 8/8 | **7/8** (中断) | ⚠️ |
| 最终数据生成 | 完整 | **未完成** | ❌ |

---

## 🔴 发现的问题

### 问题1: OOM Kill

**现象**: 脚本在合并阶段被 OOM killer 终止

**日志证据**:
```
[1989146.375917] oom-kill:constraint=CONSTRAINT_NONE,...,task=python3,pid=543463
[1989146.375931] Out of memory: Killed process 543463 (python3) total-vm:2158416kB, anon-rss:1930240kB
```

**分析**:
- 脚本报告内存: ~370MB
- 实际内存使用: ~1.9GB (RSS)
- 差异原因: `resource.getrusage().ru_maxrss` 不包括 pandas/pyarrow 内部内存池

### 问题2: 合并阶段内存累积

**代码位置**: `merge_all_batches()` 函数

**问题代码**:
```python
# 第 170-180 行附近
existing_factor = pq.read_table(temp_factor_parquet)  # 加载全部已合并数据
existing_return = pq.read_table(temp_return_parquet)

combined_factor = pa.concat_tables([existing_factor, factor_table])  # 内存翻倍
combined_return = pa.concat_tables([existing_return, return_table])

pq.write_table(combined_factor, temp_factor_parquet)  # 重写整个文件
```

**内存累积过程**:
- 批次 1: 加载 200K 记录 → 合并 → 写入
- 批次 2: 加载 400K 记录 → 合并 → 写入
- 批次 3: 加载 600K 记录 → 合并 → 写入
- ...
- 批次 7: 加载 1.4M 记录 → **内存爆炸**

每合并一个批次，都需要:
1. 解压 gzip 文件到内存
2. 转换为 pandas DataFrame
3. 转换为 PyArrow Table
4. 加载已存在的 Parquet 文件
5. 连接两个表
6. 写入新文件

这导致内存峰值约为最终数据大小的 3-4 倍。

### 问题3: 内存监控不准确

**代码位置**: `get_memory_usage_mb()` 函数

```python
def get_memory_usage_mb():
    mem_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return mem_kb / 1024  # Linux 上 ru_maxrss 是 KB
```

**问题**: 
- `ru_maxrss` 只跟踪进程自身的最大 RSS
- 不包括 pandas/pyarrow 内部缓冲区
- 不包括内存碎片和临时对象
- 导致报告值与实际值相差 5 倍

---

## ✅ 验证通过的项目

### 1. 批次数据结构正确

**因子数据样本**:
```json
{
  "date": "2024-03-12",
  "asset": "000001",
  "close": 10.56,
  "rsi_6": 65.46,
  "volume_ratio_5": 1.12
}
```

**收益数据样本**:
```json
{
  "date": "2024-03-12",
  "asset": "000001",
  "forward_return_1d": -0.02178,
  "forward_return_3d": 0.003788,
  "forward_return_5d": -0.015152
}
```

### 2. 批次处理成功

| 批次 | 状态 | 因子记录数 | 股票数 | 内存(报告) |
|------|------|------------|--------|------------|
| 0 | ✅ | 200,000 | 400 | 321.6 MB |
| 1 | ✅ | 193,478 | 399 | 339.9 MB |
| 2 | ✅ | 200,000 | 400 | 360.9 MB |
| 3 | ✅ | 200,000 | 400 | 369.7 MB |
| 4 | ✅ | 200,000 | 400 | - |
| 5 | ✅ | 198,533 | 400 | - |
| 6 | ✅ | 191,124 | 400 | - |
| 7 | ❌ | (使用旧数据) | - | OOM |

### 3. 数据压缩效率良好

- 因子数据: ~2.1MB/批 (压缩后)
- 收益数据: ~2.9MB/批 (压缩后)
- 预估未压缩: ~60MB 因子, ~80MB 收益

---

## 🔍 根本原因分析

### 内存使用估算

| 阶段 | 内存需求 |
|------|----------|
| 单批拉取 | ~300-400MB |
| 单批处理 (pandas) | ~200MB |
| 合并阶段 (批次数累积) | **批次数 × 数据量** |
| Parquet 转换 | ~2x 数据大小 |

**合并 7 个批次时**:
- 7 批因子数据: ~420MB 未压缩
- 7 批收益数据: ~560MB 未压缩
- 加载到 pandas: ~1GB
- PyArrow Table 转换: ~500MB
- **总峰值: ~2GB+** (超出 1.9GB 限制)

### 系统限制

- 总内存: 3.5GB
- 可用内存: ~1.7GB
- OOM 触发阈值: ~1.9GB
- **结论**: 在此环境下，流式合并仍需优化

---

## 💡 建议优化方向

### 1. 避免全量加载合并

**当前**:
```python
# 每次都加载全部数据
existing = pq.read_table(parquet_file)
combined = concat([existing, new])
pq.write_table(combined, parquet_file)
```

**建议**:
```python
# 使用 Parquet 数据集写入
import pyarrow.parquet as pq
import pyarrow as pa

# 写入独立文件，最后合并
pq.write_table(table, f'batch_{i}.parquet')
# 最后一次性合并或使用 ParquetDataset
```

### 2. 分块写入 JSON

当前已实现流式写入，但合并阶段仍是瓶颈。

### 3. 内存监控改进

```python
import psutil  # 替代 resource

def get_memory_usage_mb():
    return psutil.Process().memory_info().rss / (1024 * 1024)
```

### 4. 降低批次大小或使用增量合并

- 减少每批股票数 (400 → 200)
- 或在每批处理后立即写入最终文件，不累积

---

## 📁 测试产生的文件

### 新创建的批次文件 (2026-04-04 11:09-11:18)

```
batch_0_factor.json.gz  2.2MB  (200,000 records)
batch_0_return.json.gz  3.0MB  (200,000 records)
batch_1_factor.json.gz  2.2MB  (193,478 records)
batch_1_return.json.gz  2.9MB  (193,478 records)
batch_2_factor.json.gz  2.2MB  (200,000 records)
batch_2_return.json.gz  3.0MB  (200,000 records)
batch_3_factor.json.gz  2.3MB  (200,000 records)
batch_3_return.json.gz  3.0MB  (200,000 records)
batch_4_factor.json.gz  2.2MB  (200,000 records)
batch_4_return.json.gz  3.0MB  (200,000 records)
batch_5_factor.json.gz  2.2MB  (198,533 records)
batch_5_return.json.gz  2.9MB  (198,533 records)
batch_6_factor.json.gz  2.2MB  (191,124 records)
batch_6_return.json.gz  2.9MB  (191,124 records)
```

**总计**: 7 个批次，~1.38M 因子记录，~1.38M 收益记录

### 旧文件 (保留自早期运行)

- `factor_data.json.gz` (17.2MB) - v3.1_batch, 545天, 3061只股票
- `return_data.json.gz` (21.9MB) - v3.1_batch
- `batch_7_*.json.gz` - 来自早期运行

---

## 🏁 结论

**版本 3.2_streaming 在当前测试环境下未能完成**，主要原因是：

1. **合并阶段内存溢出**: 流式合并策略未能有效控制峰值内存
2. **内存监控不准确**: 报告值与实际值差异大，误导判断
3. **系统内存受限**: 3.5GB 总内存不足以完成 ~1.5M 记录的合并

**但在受限环境前的批次处理是成功的**：
- 批次数据结构完全正确
- 字段定义符合预期
- 拉取阶段内存控制在 400MB 以内（报告值）

**下一步行动**：
- 需进一步优化合并阶段，或
- 在内存更充裕的环境运行，或
- 采用分批写入最终文件、最后只合并元数据的策略