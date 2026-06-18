# data_splitter.py 流程文档

> 创建时间：2026-06-18
> 脚本：reverse_discovery/data_splitter.py
> 版本：v1.0

---

## 1. 概述

将主数据源 `factor_ic_data.json.gz`（545 个交易日，~2.7M 条记录）按日期范围切分为 train / test / holdout 三个子集文件。

**遵循规范**：
- MODULE.md D2（时间隔离）、D3（不修改主数据源）、P1（Walk-Forward）、P2（Purge 窗口）

---

## 2. 数据流

```
┌──────────────────────────────────┐
│   data_fetchers/result/          │
│   factor_ic_data.json.gz         │ ← 主数据源（只读）
│   {"dates": [...545], "data": [...2.7M 条]}
└────────────┬─────────────────────┘
             │ ijson 流式读取
             ▼
┌──────────────────────────────────┐
│   data_splitter.py               │
│                                  │
│   1. 读取 dates 数组             │
│   2. compute_date_splits()       │
│      ├─ train: dates[0] ~ dates[train_end_idx - purge_days]
│      ├─ test:  train_end < d <= test_end
│      └─ holdout: d > test_end
│   3. 逐子集流式写入              │
│      ijson 读 data.item →        │
│      按 date 过滤 →              │
│      gzip 流式写 JSON            │
└────────────┬─────────────────────┘
             │
    ┌────────┼────────┐
    ▼        ▼        ▼
┌────────┐┌────────┐┌──────────┐
│ train  ││ test   ││ holdout  │
│ .json  ││ .json  ││ .json    │
│ .gz    ││ .gz    ││ .gz      │
└────────┘└────────┘└──────────┘
reverse_discovery/result/
```

---

## 3. CLI 用法

```bash
python -m reverse_discovery.data_splitter \
    --train-end 2026-03-15 \
    --test-end 2026-05-10 \
    --purge-days 2
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--train-end` | str | 必填 | 训练段截止日期（YYYY-MM-DD） |
| `--test-end` | str | 必填 | 测试段截止日期（YYYY-MM-DD） |
| `--purge-days` | int | 2 | Purge 窗口天数（交易日） |
| `--data-source` | str | FACTOR_IC_DATA | 主数据源路径 |
| `--output-dir` | str | REVERSE_DISCOVERY_RESULT | 输出目录 |

---

## 4. 切分逻辑

### 4.1 日期切分（compute_date_splits）

```
dates = ["2024-03-18", "2024-03-19", ..., "2026-06-17"]  # 545 个交易日

参数：--train-end 2026-03-15 --test-end 2026-05-10 --purge-days 2

步骤：
1. 找到 train_end 在 dates 中的索引 → train_end_idx
2. train_cutoff_idx = train_end_idx - purge_days
3. 三段分配：
   train   = dates[0] ~ dates[train_cutoff_idx]     （含 train_cutoff_idx）
   test    = (train_end, test_end]                   （不含 train_end，含 test_end）
   holdout = (test_end, dates[-1]]                   （不含 test_end，含最后一天）

purge 天（dates[train_cutoff_idx+1] ~ dates[train_end_idx]）不分配给任何段。
```

### 4.2 Purge 窗口示意

```
dates: ... | 2026-03-12 | 2026-03-13 | 2026-03-14 | 2026-03-15 | 2026-03-16 | ...
                        ↑                           ↑
                  train_cutoff                  train_end
                  (含)                          (purge 区)
                                               不分配
train:  ... ~ 2026-03-13
purge:  2026-03-14, 2026-03-15  (2 天，不分配)
test:   2026-03-16 ~ 2026-05-10
```

---

## 5. 输出文件

| 子集 | 文件名 | 示例 |
|------|--------|------|
| train | `factor_ic_data_train_<train_end>.json.gz` | `factor_ic_data_train_2026-03-15.json.gz` |
| test | `factor_ic_data_test_<train_end>.json.gz` | `factor_ic_data_test_2026-03-15.json.gz` |
| holdout | `factor_ic_data_holdout.json.gz` | `factor_ic_data_holdout.json.gz` |

### 输出 JSON 结构

```json
{
  "metadata": {
    "source": "reverse_discovery/data_splitter.py",
    "split_type": "train",
    "split_train_end_date": "2026-03-15",
    "split_test_end_date": "2026-05-10",
    "split_purge_days": 2,
    "date_range": {"start": "2024-03-18", "end": "2026-03-13"},
    "trading_days": 478,
    "parent_source": "data_fetchers/result/factor_ic_data.json.gz",
    "generated_at": "2026-06-18T17:30:00"
  },
  "dates": ["2024-03-18", "2024-03-19", ...],
  "data": [
    {"date": "2024-03-18", "asset": "000001", "open": ..., "close": ..., ...}
  ]
}
```

**关键约束**：
- `data` 字段 schema 与主数据源完全一致（44 列，不增减）
- `metadata` 是新增字段，正向 pipeline（factor_ic / backtest）不读此字段，不影响兼容

---

## 6. 流式读写实现

### 为什么不用 json.load？

主数据源解压后 ~2GB，`json.load` 峰值内存 4.5GB，在 7.3GB 总内存机器上触发 OOM Kill。

### ijson 流式方案

```python
# 读取：逐条解析 data 数组
with gzip.open(data_source, "rb") as f:
    for record in ijson.items(f, "data.item", use_float=True):
        if record["date"] in target_dates:
            # 写入输出文件
```

```python
# 写入：手动拼接 JSON（不累积全部记录）
with gzip.open(output_path, "wt", encoding="utf-8") as out_f:
    out_f.write('{"metadata": ')
    out_f.write(json.dumps(metadata))
    out_f.write(', "dates": ')
    out_f.write(json.dumps(subset_dates))
    out_f.write(', "data": [')
    # 逐条写入
    for record in filtered_records:
        if not first:
            out_f.write(",")
        out_f.write(json.dumps(record))
        first = False
    out_f.write("]}")
```

---

## 7. 验证方法

### 单元测试

```bash
python -m pytest reverse_discovery/test_cases/test_data_splitter.py -v
```

测试覆盖 6 个场景：
1. 日期切分边界（train/test/holdout 各自日期范围正确）
2. Purge 窗口隔离（train 与 test 无重叠，间隔 >= purge_days）
3. 三段无重叠（set 交集为空）
4. 子集 schema 一致性（列名与源数据一致）
5. metadata 完整性（split_type / split_train_end_date / split_purge_days 非空）
6. 错误处理（空 dates / train_end >= test_end / 超范围 / purge 过大）

### 端到端 smoke（Phase B）

```bash
# 切分
python -m reverse_discovery.data_splitter --train-end 2026-03-15 --test-end 2026-05-10

# 验证 factor_ic 能消费 test 子集
python -m factor_ic.common.factor_ic_runner \
    --factor rsi --col rsi_6 \
    --data-source reverse_discovery/result/factor_ic_data_test_2026-03-15.json.gz
```
