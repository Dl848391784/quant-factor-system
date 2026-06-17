# Design: fix factor_generator Step 12 output OOM

> 作者: 云瑶
> 创建时间: 2026-06-17
> 状态: 用户已要求“请解决 step12 的 oom 问题”，按 Design-First 留痕后执行
> 关联实跑: `/usr/bin/time -v python data_fetchers/factor_generator.py` 已穿过 Step 11.8/11.9，在 `Step 12: 格式化输出...` 被 OOM-kill

---

## §1 背景与现场证据

上一轮行业财务 block 修复后，真实全链路已能完成：

```text
有效 industry_roe_trend: 1494704 (99.99%)
有效 industry_earnings_growth: 1494817 (100.00%)
有效 industry_pe_trend: 1494570 (99.98%)
有效 capital_flow_ratio_trend: 389709 (26.07%)
有效 capital_flow_intensity: 392787 (26.28%)
Step 12: 格式化输出...
Command terminated by signal 9
Maximum resident set size (kbytes): 3329868
```

`dmesg` 同步确认 Python 进程在 Step 12 附近被 OOM-kill，`anon-rss` 约 3.30GB。

---

## §2 规范触发与范围

| 规范 | 触发原因 | 处理 |
|------|----------|------|
| PROJECT.md H8（行 115-123） | 预计触及 `factor_generator.py`、helper 测试、流程文档 | 先提交本 design，再小范围实现 |
| PROJECT.md H9（行 161） | 控制单轮 ≤3 文件、≤200 行 | 本轮只改 3 个业务文件；design 单独提交 |
| data_fetchers/MODULE.md R16 | 大对象生命周期 / OOM | 避免全量 copy 和批量 `list[dict]`，异常路径释放中间对象 |
| PROJECT.md H11 | 日志惰性格式化 | 新日志使用 `%s/%d` 占位 |
| AGENTS.md #8 | 配套测试和流程文档 | 同步 helper pytest 与 `factor_generator_flow.md` |

---

## §3 根因分析

Step 12 当前热点：

```python
output_df = factor_df[list(_OUTPUT_COLS)].copy()
_write_factor_json_gz(output_df, output_path, logger)
```

`_write_factor_json_gz` 内部热点：

```python
batch_df = output_df.iloc[batch_start:batch_end]
batch_records = batch_df.to_dict("records")
batch_records = _nan_to_null(batch_records)
for record in batch_records:
    json.dump(record, f, ensure_ascii=False)
```

在 149 万行 × 31 列规模下，峰值来自三类对象共存：

1. 已完成 pipeline 的宽 `factor_df`。
2. `output_df.copy()` 复制出的 31 列全量 DataFrame。
3. 每批 `to_dict("records")` 生成的 Python `list[dict]`，并被 `_nan_to_null` 递归重建一次。

因此 Step 12 不是计算因子失败，而是输出格式化路径把 pandas 列式数据膨胀成 Python 对象图。

---

## §4 方案：列视图 + 逐行记录流式写出

### 核心变化

| 热点 | 当前做法 | 修改后 |
|------|----------|--------|
| 输出列选择 | `factor_df[list(_OUTPUT_COLS)].copy()` | 只做列视图/浅选择，不复制数据块 |
| JSON records | 每批 `to_dict("records")` + `_nan_to_null(list)` | `itertuples(index=False, name=None)` 逐行构造一个 record |
| NaN/np 标量 | 递归净化整个 batch | 单值级 `_json_safe_value` 转换 |
| 日期清单 | `unique().tolist()` | 保持现状，日期数量小，非主因 |
| 原子写 | 临时 gzip + `os.replace` | 保持现状 |

新增私有 helper：

```python
def _json_safe_value(value: Any) -> Any:
    """单值转换：NaN/inf -> None；numpy 标量 -> Python 标量。"""
```

调整 `_write_factor_json_gz`：

- 输入仍为 DataFrame，兼容测试和调用点。
- 内部不再 `to_dict("records")`。
- 预先保存 `columns = list(output_df.columns)`。
- 遍历 `for row in output_df.itertuples(index=False, name=None)`。
- 每行只构造一个 dict，然后立即 `json.dump` 并释放到下一轮。

调整 `_format_and_write_output`：

- 缺列校验后使用 `output_df = factor_df.loc[:, list(_OUTPUT_COLS)]`。
- 不再 `.copy()`。
- 保留 `del factor_df` 和 `finally del output_df`，缩短引用生命周期。

---

## §5 等价性证明

| 字段类型 | 当前输出 | 新输出 | 等价依据 |
|----------|----------|--------|----------|
| Python float NaN/inf | `_nan_to_null` -> `None` | `_json_safe_value` -> `None` | 同一判定：`math.isnan/isinf` |
| numpy floating NaN/inf | `_nan_to_null` -> `None` | `_json_safe_value` -> `None` | 同一判定：`np.floating` |
| numpy integer | Python int | Python int | 保留原语义 |
| numpy bool | Python bool | Python bool | 保留原语义，先于 integer 判断 |
| tuple/list/dict | 递归转换 | 通过 `_nan_to_null` fallback 递归 | 当前输出列主要为标量；复杂值仍兼容 |
| JSON 外层结构 | `{dates, data}` | `{dates, data}` | 写出顺序和字段名不变 |

---

## §6 实施拆分

### Round 1 — 代码修复（1 文件）

文件：`data_fetchers/factor_generator.py`

1. 新增 `_json_safe_value`。
2. `_nan_to_null` 内部复用 `_json_safe_value` 的标量分支，避免语义漂移。
3. `_write_factor_json_gz` 改为逐行 itertuples 写出。
4. `_format_and_write_output` 去掉 `.copy()`。

### Round 2 — 测试（1 文件）

文件：`data_fetchers/test_cases/test_factor_generator_helpers.py`

1. 新增 `_json_safe_value` 标量转换测试。
2. 新增 `_write_factor_json_gz` “禁止调用 `DataFrame.to_dict`” 测试，防止回退到 `list[dict]`。
3. 保留现有内容等价测试。

### Round 3 — 流程文档（1 文件）

文件：`data_fetchers/docs/factor_generator_flow.md`

记录 Step 12 OOM 修复：禁止全量 copy 和 `to_dict("records")`。

---

## §7 验证计划

轻量验证：

```bash
ruff format data_fetchers/factor_generator.py data_fetchers/test_cases/test_factor_generator_helpers.py
ruff check data_fetchers/factor_generator.py data_fetchers/test_cases/test_factor_generator_helpers.py
pytest data_fetchers/test_cases/test_factor_generator_helpers.py -q
```

真实验证：

```bash
/usr/bin/time -v python data_fetchers/factor_generator.py
```

通过标准：

1. 日志出现 `Step 13: 保存输出...` 后继续完成 Step 15 / 完成摘要。
2. `data_fetchers/result/factor_ic_data.json.gz` mtime 更新。
3. `dmesg` 无对应新 OOM-kill。
4. `factor_ic_data_columns.json` 同步写出。

---

## §8 不做项

- 不改变输出 JSON schema。
- 不改变 `_OUTPUT_COLS`、路径、下游读取契约。
- 不引入第三方 JSON 流式库，避免新增依赖。
- 不运行会 OOM 的 `pytest data_fetchers/test_cases/test_factor_generator.py -q` 作为轻量验证标准。
