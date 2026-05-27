# batch_processor 流程文档

> 创建日期: 2026-05-27
> 作者: 云瑶
> 版本: v1.0

## 1. 模块概述

`batch_processor.py` 提供批次处理的核心功能：
- 批次保存（流式写入）
- N-way merge 合并（去重）
- 最终格式化（meta + data 结构）
- 临时文件清理

## 2. 调用流程图

```
┌─────────────────────────────────────────────────────────────────┐
│                    fetch_factor_cache.py                        │
│  （主脚本：批次数据获取 → 合并 → 格式化 → 清理）                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 1: save_batch_cache_sorted(batch_idx, factor_df, return_df)│
│  ├─ 输入：因子 DataFrame + 收益 DataFrame                        │
│  ├─ 处理：验证列 → 排序 → 流式写入 gzip JSON                    │
│  ├─ 输出：batch_0_factor.json.gz + batch_0_return.json.gz       │
│  └─ 内存：流式写入避免峰值                                        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ （循环 total_batches 次）
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 2: n_way_merge_deduplicate(total_batches, 'factor')       │
│  ├─ 输入：所有 batch_*_factor.json.gz 文件                       │
│  ├─ 处理：heap N-way merge + 按 batch_idx 去重                  │
│  ├─ 输出：merged_factor.json.gz                                  │
│  └─ 策略：相同 key 选最新 batch（batch_idx 降序）                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ （同理处理 'return'）
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 3: format_final_output(merged_factor, merged_return)      │
│  ├─ 输入：merged_factor.json.gz + merged_return.json.gz         │
│  ├─ 处理：读取 → 计算 meta（n_days, n_assets, date_range）      │
│  ├─ 输出：factor_data.json.gz + return_data.json.gz             │
│  └─ 格式：{meta: {...}, data: [...]}                             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 4: cleanup_batch_files(total_batches)                     │
│  ├─ 输入：total_batches                                          │
│  ├─ 处理：删除 batch_*_*.json.gz + merged_*.json.gz             │
│  ├─ 输出：删除文件数量                                            │
│  └─ 错误处理：删除失败仅 warning 日志                             │
└─────────────────────────────────────────────────────────────────┘
```

## 3. 函数参数说明

### 3.1 save_batch_cache_sorted

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| batch_idx | int | Y | 批次索引（从0开始） |
| factor_df | pd.DataFrame | Y | 因子数据，必需列见下表 |
| return_df | pd.DataFrame | Y | 收益数据，必需列见下表 |
| result_dir | Path | N | 结果目录，默认模块级 RESULT_DIR |
| logger_arg | logging.Logger | N | 日志记录器 |

**factor_df 必需列**：date, asset, open, close, high, low, rsi_6, volume_ratio_5
**return_df 必需列**：date, asset, forward_return_1d, forward_return_3d, forward_return_5d

### 3.2 n_way_merge_deduplicate

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| total_batches | int | Y | 总批次数 |
| data_type | str | N | 'factor' 或 'return'，默认 'factor' |
| result_dir | Path | N | 结果目录 |
| logger_arg | logging.Logger | N | 日志记录器 |

**返回值**：Path | None（无有效数据返回 None）

### 3.3 format_final_output

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| factor_merged_path | Path | str | Y | 合并后的因子数据路径 |
| return_merged_path | Path | str | Y | 合并后的收益数据路径 |
| result_dir | Path | N | 结果目录 |
| logger_arg | logging.Logger | N | 日志记录器 |

### 3.4 cleanup_batch_files

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| total_batches | int | Y | 总批次数 |
| result_dir | Path | N | 结果目录 |
| logger_arg | logging.Logger | N | 日志记录器 |

**返回值**：int（删除的文件数量）

## 4. 输出文件格式

### 4.1 批次文件（batch_*_*.json.gz）

```json
[
  {"date": "2026-05-27", "asset": "000001", "open": 10.0, ...},
  {"date": "2026-05-27", "asset": "000002", "open": 20.0, ...}
]
```

### 4.2 合并文件（merged_*.json.gz）

同批次文件格式，已按 (date, asset) 排序并去重。

### 4.3 最终文件（factor_data.json.gz / return_data.json.gz）

```json
{
  "meta": {
    "generated_at": "2026-05-27T14:30:00",
    "source": "sina_api_batch_external_merge",
    "n_days": 250,
    "n_assets": 5000,
    "n_records": 1250000,
    "date_range": {"start": "2026-01-01", "end": "2026-05-27"},
    "last_updated": "2026-05-27 14:30:00",
    "version": "2.14",
    "fields": ["date", "asset", "open", "close", ...]
  },
  "data": [
    {"date": "2026-01-01", "asset": "000001", "open": 10.0, ...},
    ...
  ]
}
```

## 5. BatchStream 类说明

BatchStream 是 N-way merge 的核心组件：
- 逐条读取批次数据（避免一次性加载）
- 支持 heap 比较（按 batch_idx）
- 提供 peek_key() / pop_record() 流式接口

```python
class BatchStream:
    batch_idx: int      # 原始批次索引
    data_type: str      # 'factor' 或 'return'
    path: Path          # 批次文件路径
    records: list       # 当前加载的记录
    idx: int            # 当前记录索引
    exhausted: bool     # 是否已耗尽
```

## 6. 错误处理

| 函数 | 异常类型 | 处理方式 |
|------|---------|---------|
| save_batch_cache_sorted | ValueError | 缺少必需列，直接抛出 |
| n_way_merge_deduplicate | JSONDecodeError | 批次文件损坏，直接抛出 |
| format_final_output | FileNotFoundError | merged 文件不存在，直接抛出 |
| cleanup_batch_files | Exception | 删除失败，仅 warning 日志 |

## 7. 调用示例（完整流程）

```python
import logging
from pathlib import Path
from data_fetchers.batch_processor import (
    save_batch_cache_sorted,
    n_way_merge_deduplicate,
    format_final_output,
    cleanup_batch_files
)

logger = logging.getLogger(__name__)

# Step 1: 批次保存（循环）
for batch_idx in range(total_batches):
    save_batch_cache_sorted(
        batch_idx, factor_df, return_df,
        logger_arg=logger
    )

# Step 2: N-way merge
factor_merged = n_way_merge_deduplicate(total_batches, 'factor', logger_arg=logger)
return_merged = n_way_merge_deduplicate(total_batches, 'return', logger_arg=logger)

# Step 3: 最终格式化
format_final_output(factor_merged, return_merged, logger_arg=logger)

# Step 4: 清理临时文件
cleanup_batch_files(total_batches, logger_arg=logger)
```

## 8. 约束遵循

遵循 MODULE.md 约束：
- 约束 19: PEP 8 导入顺序
- 约束 50: 异常日志包含 `type(e).__name__`
- 约束 77: logger 参数命名为 `logger_arg`
- 约束 8: 流程文档 docs/*.flow.md

遵循 PROJECT.md 规范：
- 使用 Python 标准库 logging 模块
- 公共模块函数接收 logger 参数
- 文件头版本历史
- docstring Example/Raises 章节