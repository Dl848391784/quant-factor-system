# Phase A: data_splitter.py 设计文档

> 创建时间：2026-06-18
> 模块：reverse_discovery
> 关联规范：reverse_discovery/MODULE.md D2/D3、P1/P2/P3

---

## 1. 目标

将主数据源 `factor_ic_data.json.gz`（545 个交易日，~2.7M 条记录）按日期范围切分为 train / test / holdout 三个子集文件，schema 与主数据源完全一致，正向 pipeline 可通过 `--data-source` 零改动消费。

---

## 2. 已确认的技术约束

| 约束 | 来源 | 应对 |
|------|------|------|
| json.load 会 OOM（~2GB 解压后 4.5GB 峰值） | comprehensive_factor MODULE.md L107 | ijson 流式读取 |
| ijson 已安装但不在 pyproject.toml | pip show ijson = 3.3.0 | 补充到 dependencies |
| factor_ic/backtest 只读 `dates` + `data` 顶层 key | data_loader.py L137-139 | 输出加 `metadata` 不影响兼容 |
| 44 列 schema 必须原样保留 | MODULE.md D3 | 不增减列、不改类型 |
| 日期是字符串 "YYYY-MM-DD" | 数据探查 | 按字符串比较即可（ISO 格式天然有序） |

---

## 3. 核心设计决策

### D1: 单次切分 vs Walk-Forward

**Phase A 只实现单次切分**（`--train-end` + `--test-end`），Walk-Forward 多轮切分留给后续增强。

理由：
- 单次切分是最小可用单元，能立即支持 Phase B smoke 验证和 Phase C 收益画像
- Walk-Forward 本质是多次调用单次切分 + 不同参数，可后续加 `--walk-forward` 模式
- 控制 Phase A 的任务粒度（≤3 文件 ≤200 行约束）

### D2: 流式读取 + 流式写入

```
读取：ijson.items(f, "data.item", use_float=True)  → 逐条记录
过滤：record["date"] in target_dates  → O(1) 集合查找
写入：gzip.open + 手动 JSON 流式拼接  → 不累积全部记录
```

**写入格式**：
```json
{"metadata": {...}, "dates": ["2024-03-18", ...], "data": [{"date": "...", ...}, ...]}
```

写入策略：
1. 先写 `metadata` + `dates`（小数据，直接 json.dumps）
2. 流式写 `data` 数组：逐条 `json.dumps(record)` + 逗号拼接
3. 不在内存中累积 data 数组

### D3: 输出文件命名

遵循 MODULE.md L150-152 已定义：

| 子集 | 文件名 |
|------|--------|
| train | `factor_ic_data_train_<train_end>.json.gz` |
| test | `factor_ic_data_test_<train_end>.json.gz` |
| holdout | `factor_ic_data_holdout.json.gz` |

`<train_end>` 用日期字符串（如 `2026-03-15`），是 train 段最后一天的日期（不含 purge）。

### D4: purge 窗口处理

```
dates 数组：[d0, d1, ..., dN]

参数：--train-end 2026-03-15 --test-end 2026-05-10 --purge-days 2

切分逻辑：
  train_dates = dates 中 <= (train_end - purge_days 个交易日) 的日期
  test_dates  = dates 中 train_end < d <= test_end 的日期
  holdout_dates = dates 中 > test_end 的日期
```

注意：purge 是按交易日数剔除，不是按日历日。`train_end - purge_days` 意为从 train_end 往前数 purge_days 个交易日。

### D5: metadata 字段

```json
{
  "source": "reverse_discovery/data_splitter.py",
  "split_type": "train",
  "split_train_end_date": "2026-03-15",
  "split_test_end_date": "2026-05-10",
  "split_purge_days": 2,
  "date_range": {"start": "2024-03-18", "end": "2026-03-13"},
  "trading_days": 248,
  "parent_source": "data_fetchers/result/factor_ic_data.json.gz",
  "generated_at": "2026-06-18T17:30:00"
}
```

---

## 4. CLI 设计

```bash
python -m reverse_discovery.data_splitter \
    --train-end 2026-03-15 \
    --test-end 2026-05-10 \
    --purge-days 2 \
    [--data-source <path>]   # 默认 paths.FACTOR_IC_DATA
    [--output-dir <path>]    # 默认 paths.REVERSE_DISCOVERY_RESULT
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--train-end` | str (date) | **必填** | 训练段截止日期（YYYY-MM-DD） |
| `--test-end` | str (date) | **必填** | 测试段截止日期（YYYY-MM-DD） |
| `--purge-days` | int | 2 | purge 窗口天数（交易日） |
| `--data-source` | str | FACTOR_IC_DATA | 主数据源路径 |
| `--output-dir` | str | REVERSE_DISCOVERY_RESULT | 输出目录 |

---

## 5. 改动文件清单

| 文件 | 操作 | 预估行数 |
|------|------|---------|
| `paths.py` | 修改：新增 2 常量 + __all__ | +6 行 |
| `reverse_discovery/common/__init__.py` | 新建 | ~1 行 |
| `reverse_discovery/common/logger_config.py` | 新建（从 factor_ic 适配） | ~90 行 |
| `reverse_discovery/data_splitter.py` | 新建（核心脚本） | ~180 行 |
| `reverse_discovery/test_cases/__init__.py` | 新建 | ~1 行 |
| `reverse_discovery/test_cases/test_data_splitter.py` | 新建（测试） | ~150 行 |
| `reverse_discovery/docs/data_splitter_flow.md` | 新建（流程文档） | ~80 行 |
| `pyproject.toml` | 修改：补充 ijson 依赖 | +1 行 |

**总计**：8 文件，~510 行。超出 ≤3 文件 ≤200 行约束，拆分为多轮执行。

---

## 6. 执行轮次计划

| 轮次 | 内容 | 文件 |
|------|------|------|
| R1 | paths.py 更新 + common/__init__.py + logger_config.py | 3 文件 |
| R2 | data_splitter.py 核心切分逻辑（无 CLI） | 1 文件 |
| R3 | data_splitter.py CLI + main() | 同文件 patch |
| R4 | test_cases/test_data_splitter.py | 1 文件 |
| R5 | docs/data_splitter_flow.md | 1 文件 |
| R6 | pyproject.toml 补 ijson + ruff + pytest + commit | 1 文件 + 验证 |

---

## 7. 测试策略

| 测试场景 | 断言要点 |
|---------|---------|
| 日期切分边界 | train_dates ⊆ [start, train_end - purge]；test_dates ⊆ (train_end, test_end]；holdout ⊆ (test_end, end] |
| Purge 窗口隔离 | set(train) ∩ set(test) == set()；min(test) 在 dates 中索引 - max(train) 索引 >= purge_days + 1 |
| 子集 schema 一致性 | 输出 data 记录的 keys 与源数据首条记录 keys 完全一致 |
| metadata 完整性 | split_type / split_train_end_date / split_purge_days 非空 |
| 三段无重叠 | set(train) ∩ set(test) ∩ set(holdout) == set() |
| 空数据防护 | train_end 超出 dates 范围时抛 ValueError |

测试用构造的小数据（~10 条记录），不用真实 2GB 文件。
