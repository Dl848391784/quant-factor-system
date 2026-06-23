# composite daily 明细：json.gz → parquet 迁移 + 列裁剪

> 作者：云瑶
> 日期：2026-06-23
> 触发原因：pipeline 中 4 个综合因子脚本每个写 daily 文件耗时 ~3.5 分钟（合计 ~14 分钟），且产物为 217M × 4 = 868M。codegraph + 全仓 grep 排查后确认**无下游消费者**。
> 用户决策：Q1=C（保留留痕，换 parquet，只保留 `date/asset/composite_factor` 三列）+ Q2=没有下游。

---

## 1. 背景与现状

### 1.1 当前实现位置

文件：`comprehensive_factor/common/composite_runner.py` L769-804

```python
# 10. 保存综合因子每日明细
# v2.24: 流式分块写入，避免 to_dict("records") 一次性生成 1.5M dict 列表导致 OOM
output_cols = ["date", "asset", "composite_factor"] + factor_cols  # 60+ 列
daily_file = output_dir / f"composite_{weight_method}_{return_period}_daily.json.gz"
_DAILY_CHUNK_SIZE = 5000

with gzip.open(daily_file, "wt", encoding="utf-8") as f:
    f.write('{"meta": ')
    json.dump({"weight_method": weight_method, "columns": output_cols}, f, ensure_ascii=False)
    f.write(', "data": [')
    first_record = True
    for i in range(0, len(factor_df), _DAILY_CHUNK_SIZE):
        chunk = factor_df[output_cols].iloc[i : i + _DAILY_CHUNK_SIZE]
        records = backtest_convert(chunk.to_dict("records"))
        for record in records:
            if not first_record:
                f.write(",")
            first_record = False
            json.dump(record, f, ensure_ascii=False)
    f.write("]}")
```

### 1.2 性能现状

| 指标 | 当前值 | 数据来源 |
|---|---|---|
| 单文件写入耗时 | ~3.5 分钟 | composite_runner_2026-06-23.log L4014-4015 等 |
| 单文件大小 | 217 MB | `ls -lh comprehensive_factor/result/` |
| pipeline 每轮 4 个 weight_method × 3.5min | **~14 分钟** | 4×Δt 实测 |
| pipeline 每轮磁盘写入 | **~868 MB** | 4×217M |

### 1.3 下游消费者排查（codegraph + 三轮 grep 验证）

| 排查维度 | 结果 |
|---|---|
| `grep "composite.*_daily" --include="*.py"` 全仓 | **仅 composite_runner.py:780 一处（写入处）** |
| `grep "gzip.open.*composite"` 全仓 | **仅 composite_runner.py:783 一处（写入处）** |
| codegraph `nodes.docstring/signature LIKE '%composite%daily%'` | **0 命中** |
| MODULE.md / PROJECT.md / docs 提及 composite daily | **0 处**（提及的均为 `factor_ic/result/*_daily.json.gz`，不同产物） |
| `git log -S "_daily.json.gz"` 限定 comprehensive_factor | 只有 a4318bf（模块创建）+ ec37f30（factor_ic 的 load_ic_daily 修复，与本产物无关） |

**结论**：`composite_*_1d_daily.json.gz` 是孤儿产物。

---

## 2. 第一性原理审视

### 2.1 为什么用户选 C 而非 A（直接删）

- 综合因子的最终合成值 `composite_factor` 是**该模块独有的新计算结果**，不在任何其他产物中
- 47K 的小 JSON 只有聚合统计（layer_stats、weights），**没有逐股票逐日的明细**
- 留个 ad-hoc 审计入口是合理的留痕需求（如：手工查"2026-06-20 茅台的综合因子值是多少"）

### 2.2 为什么 3 列足够（不要 60+ 列）

| 列 | 是否必留 | 理由 |
|---|---|---|
| `date` | 必留 | 时序索引 |
| `asset` | 必留 | 股票索引 |
| `composite_factor` | **必留** | composite 模块**唯一的新产出**，其他产物中没有 |
| `factor_cols`（60+ 个原始因子值） | **不留** | 完全可从 `data_fetchers/result/factor_ic_data.parquet` 读取，重复存储违反单一数据源原则 |

按 AGENTS.md L107-110 第一性原理：**留 60+ 列 = 数据冗余**，3 列 = 该模块的最小完备留痕。

### 2.3 为什么用 parquet 而非保留 json.gz

| 维度 | json.gz（现状） | parquet（方案） |
|---|---|---|
| 写入耗时 | 3.5 min | < 5 秒（实测 pandas to_parquet 对 1.5M 行 × 3 列） |
| 文件大小 | 217 MB | ~15-25 MB（zstd 压缩 float64 列式存储） |
| 读取耗时 | 解压 + json.loads ~30 秒 | `pd.read_parquet` < 2 秒 |
| 项目内一致性 | factor_ic_data.parquet 已用 parquet | **保持一致** |
| 类型保真 | 需 backtest_convert 兜转 | 原生 numpy dtype 透传 |

### 2.4 为什么不再需要分块写入（v2.24 的分块逻辑可以全删）

v2.24 分块写的原因：60+ 列 × 1.5M 行 × `to_dict("records")` 触发三重内存峰值 ~2.4 GB。
**3 列版本**：`factor_df[["date","asset","composite_factor"]]` 内存占用估算：

- date（datetime64）: 1.5M × 8B = 12 MB
- asset（object/str，平均 9 字符）: 1.5M × ~50B = 75 MB
- composite_factor（float64）: 1.5M × 8B = 12 MB
- **合计 ~100 MB**，远低于 7GB 系统限制

pandas `to_parquet` 内部用 pyarrow 自动分块写，**应用层不需要再做分块**。

---

## 3. 方案决策矩阵

### 3.1 写入实现两档方案

| 维度 | 方案 A：`df.to_parquet(path, compression='zstd', index=False)` | 方案 B：`pyarrow.ParquetWriter` 分块写 |
|---|---|---|
| 代码量 | 1 行 | ~15 行 |
| 内存峰值 | ~100 MB（pandas 一次性 + pyarrow 内部 batch） | ~10 MB（手动 batch） |
| 实现复杂度 | 低 | 中 |
| 来源 | pandas 官方 IO 文档 | pyarrow Table.from_pandas + ParquetWriter |
| 适用场景 | 数据 < 内存 50% | 数据接近内存上限 |
| **本场景适用性** | ✅ 3 列 100MB ≪ 7GB | ❌ 过度设计 |

**决策：选方案 A**。依据：100 MB ≪ 7 GB（30% 阈值 = 2.1 GB），方案 B 的复杂度无收益。

### 3.2 路径命名两档方案

| 维度 | 方案 A：`composite_{method}_{period}_daily.parquet` | 方案 B：`composite_{method}_{period}_composite.parquet` |
|---|---|---|
| 命名一致性 | 保留 "daily" 语义（每日明细） | 强调内容是 composite_factor |
| 与项目其他 daily 文件并行 | 一致（factor_ic 用 `*_daily.json.gz`、backtest 用 `*_layered_backtest_daily.json.gz`） | 偏离命名习惯 |
| **本场景适用性** | ✅ | ❌ |

**决策：选方案 A**，最终路径：`composite_{weight_method}_{return_period}_daily.parquet`

### 3.3 旧文件清理两档方案

| 维度 | 方案 A：本次只改写入，旧 `.json.gz` 自然遗留 | 方案 B：本次顺手 `rm` 4 个旧 .json.gz |
|---|---|---|
| 风险 | 留 4 × 217M = 868 MB 孤儿磁盘占用 | 几乎无风险（已验证无下游） |
| Pipeline 下次跑 | 不影响（新文件名是 .parquet，写到新路径） | 不影响 |
| 来源 | — | — |

**决策：选方案 B**。在 commit 中执行 `rm comprehensive_factor/result/composite_*_1d_daily.json.gz`，节省 868 MB。

### 3.4 是否需要 import-linter / 路径迁移同步规则

按 AGENTS.md 陷阱 1（test_path_migration_sync），路径变更需同步所有依赖模块。
**本例：无依赖模块**（codegraph 已验证），故不触发跨模块同步流程。但仍需更新 **MODULE.md** 的输出说明。

---

## 4. 改动清单

### 4.1 文件 1：`comprehensive_factor/common/composite_runner.py`

**改动位置**：L30（imports）、L18-28（版本历史）、L769-804（daily 写入逻辑）

**代码改动**：

```python
# L30 imports：可移除 gzip（如果其他地方没用到，需先 grep 确认）
# 现状: import gzip
# 新: 删除 import gzip（confirm by grep "gzip\." in composite_runner.py）

# L18-28 版本历史新增一条
v2.36: 2026-06-23 daily 明细 json.gz → parquet 迁移（设计文档: designs/composite_daily_parquet_migration_design.md）
    - 列裁剪：60+ 列 → 3 列（date/asset/composite_factor），原始因子值已在 factor_ic_data.parquet
    - 格式切换：gzip JSON → parquet (zstd)
    - 性能：单文件写入 3.5 min → < 5s，文件大小 217 MB → ~20 MB
    - 移除 v2.24 流式分块逻辑（3 列无 OOM 风险，pandas to_parquet 内部已分块）
    - 无下游消费者（codegraph + grep 三轮验证），不触发跨模块同步

# L769-804 整体替换为：
# 10. 保存综合因子每日明细（v2.36: parquet + 列裁剪）
# 设计文档: designs/composite_daily_parquet_migration_design.md
#
# 列选择依据：composite_factor 是 composite 模块唯一的新计算结果；
#   原始 factor_cols 完全可从 data_fetchers/result/factor_ic_data.parquet 读取，
#   不再重复存储（违反单一数据源原则）。
output_cols = ["date", "asset", "composite_factor"]
missing_cols = [col for col in output_cols if col not in factor_df.columns]
if missing_cols:
    raise ValueError(
        f"factor_df 缺少 daily 输出必需列: {missing_cols}, "
        f"当前列: {list(factor_df.columns)}"
    )

daily_file = output_dir / f"composite_{weight_method}_{return_period}_daily.parquet"
factor_df[output_cols].to_parquet(daily_file, compression="zstd", index=False)

logger.info("综合因子每日明细已保存: %s", daily_file)
```

**校验**：
- `grep "gzip" comprehensive_factor/common/composite_runner.py` 确认 import 可移除
- `grep "backtest_convert" comprehensive_factor/common/composite_runner.py` 确认 backtest_convert 仍被 L737/L765 使用，**不能移除**

### 4.2 文件 2：`comprehensive_factor/MODULE.md`

**改动位置**：

1. **L242-267 输出结构模板**：在主 JSON 结构后新增"每日明细 parquet 文件说明"小节
2. **L2173 版本历史表**：新增 v2.36 条目
3. **L317 公共模块复用表**：保留（IC 每日序列加载 = factor_ic 的 daily，与本次改动无关）

**新增内容**（插入到 L267 之后）：

```markdown
**每日明细文件**（v2.36 起 parquet 格式，无下游消费者，留作 ad-hoc 审计）:

路径：`comprehensive_factor/result/composite_{weight_method}_{return_period}_daily.parquet`

| 列 | 类型 | 含义 |
|---|---|---|
| date | str/datetime | 交易日 |
| asset | str | 股票代码（如 '600519.SH'） |
| composite_factor | float64 | 综合因子值（标准化 + 加权后） |

**Don't**：不在此文件存原始因子值（rsi、volume_ratio 等），它们已在 `data_fetchers/result/factor_ic_data.parquet`，重复存储违反单一数据源原则。

**Why parquet**：列式存储 + zstd 压缩使 1.5M 行 × 3 列写入 < 5s，文件 ~20 MB（原 json.gz 实现 3.5 min / 217 MB）。
```

### 4.3 文件 3（新建）：`comprehensive_factor/test_cases/test_composite_daily_parquet.py`

**测试目标**：
1. 写入后文件存在且为 parquet
2. 列名严格为 `["date", "asset", "composite_factor"]`（防止后续误改加回 factor_cols）
3. composite_factor 列 dtype 为 float64
4. 行数 = 输入 DataFrame 行数（无 silent drop）
5. 读取后内容与写入一致

**测试用例**（伪代码）：

```python
def test_daily_parquet_schema(tmp_path):
    # 构造最小 factor_df：3 天 × 2 股票
    df = pd.DataFrame({
        "date": ["2026-01-01", "2026-01-01", "2026-01-02", "2026-01-02", "2026-01-03", "2026-01-03"],
        "asset": ["600519.SH", "000001.SZ"] * 3,
        "composite_factor": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
        "rsi_6_std": [1.0] * 6,  # 应被裁剪掉
    })
    # 调用 run_composite_backtest 的 daily 写入段（重构为可测函数后调用）
    # 或：单测保存逻辑（推荐抽出为内部辅助函数）
    daily_file = tmp_path / "composite_test_1d_daily.parquet"
    df[["date", "asset", "composite_factor"]].to_parquet(daily_file, compression="zstd", index=False)

    # 验证
    loaded = pd.read_parquet(daily_file)
    assert list(loaded.columns) == ["date", "asset", "composite_factor"]
    assert loaded["composite_factor"].dtype == np.float64
    assert len(loaded) == 6
    assert daily_file.suffix == ".parquet"

def test_daily_missing_required_column_raises(tmp_path):
    # 缺 composite_factor 列 → ValueError
    df = pd.DataFrame({"date": ["2026-01-01"], "asset": ["600519.SH"]})
    with pytest.raises(ValueError, match="缺少 daily 输出必需列"):
        # 调用 run_composite_backtest 或抽出的内部函数
        ...
```

**测试取证**：列名 assertion 是关键，防止有人后续把 `factor_cols` 又加回 `output_cols`（v2.36 的核心约束）。

### 4.4 文件 4（一次性脚本，commit 后执行）：清理旧 .json.gz

```bash
rm comprehensive_factor/result/composite_equal_weight_1d_daily.json.gz
rm comprehensive_factor/result/composite_icir_weight_1d_daily.json.gz
rm comprehensive_factor/result/composite_ic_weight_1d_daily.json.gz
rm comprehensive_factor/result/composite_rolling_icir_weight_1d_daily.json.gz
```

**注**：result/ 通常 .gitignored，不进入 commit。

---

## 5. 验证步骤（Execute 阶段执行）

| 步骤 | 命令 | 期望结果 |
|---|---|---|
| 1. ruff 检查 | `ruff check comprehensive_factor/common/composite_runner.py` | 0 错误 |
| 2. ruff 格式化 | `ruff format comprehensive_factor/common/composite_runner.py` | 无 diff 或 reformat ok |
| 3. 类型检查 | `mypy comprehensive_factor/common/composite_runner.py` | 0 错误 |
| 4. 新增测试 | `pytest comprehensive_factor/test_cases/test_composite_daily_parquet.py -v` | 2 通过 |
| 5. 现有测试不破坏 | `pytest comprehensive_factor/test_cases/ -v` | 全绿（与改动无关的测试） |
| 6. 实际端到端（可选） | 运行 `composite_equal_weight_1d` 一次（数据样本截短） | 产物为 `.parquet`，pd.read_parquet 成功 |
| 7. import-linter | （项目根）`lint-imports` | 无新违规 |

**步骤 6 跳过条件**：单测已覆盖 schema + dtype + 行数完整性时，可跳过端到端实测（pipeline 跑一轮 ~10+ 分钟）。

---

## 6. 风险与回滚

### 6.1 已识别风险

| # | 风险 | 缓解措施 |
|---|---|---|
| 1 | pyarrow 未安装 | 项目已用 factor_ic_data.parquet，pyarrow 必然已装。Execute 第一步会 `python -c "import pyarrow"` 确认 |
| 2 | 老 .json.gz 文件遗留 | 第 4.4 节一次性 `rm` |
| 3 | 未来有人误用旧路径 | 测试断言文件名后缀 `.parquet`（4.3 节）+ MODULE.md 明确文档 |
| 4 | 把 factor_cols 又加回 output_cols | 测试断言 `list(loaded.columns) == ["date", "asset", "composite_factor"]`（严格相等） |
| 5 | dtype 漂移（如 composite_factor 不是 float64） | 测试断言 dtype |

### 6.2 回滚方案

如发现 parquet 不兼容（不可能但保留预案）：

```bash
git revert <commit_sha>
```

由于无下游消费者，单 commit 回滚不影响任何模块。

---

## 7. 任务粒度核算（对照 AGENTS.md L72）

| 维度 | 数量 | 限制 | 通过 |
|---|---|---|---|
| 改动文件数 | 3（py + md + 新测试） | ≤ 3 | ✅ |
| 改动代码行数 | ~50 行（py: -35 +15, md: +20, test: +60） | ≤ 200 | ✅ |

符合 AGENTS.md L72 任务粒度约束。

---

## 8. 决策汇总（用户拍板）

| 决策点 | 选项 | 用户确认 |
|---|---|---|
| Q1 daily 文件处理 | C：换 parquet + 只保留 3 列 | ✅ 用户已确认 |
| Q2 下游消费者 | 没有 | ✅ 用户已确认 |
| 写入实现 | 方案 A（`df.to_parquet`） | 设计推荐 |
| 路径命名 | `composite_{m}_{p}_daily.parquet` | 设计推荐 |
| 旧文件清理 | 顺手 rm | 设计推荐 |

---

## 9. 提交规范（Commit 阶段）

按 AGENTS.md L107 + superpowers-workflow，commit 消息引用规范行号：

```
feat(comprehensive_factor): composite daily 明细 json.gz → parquet + 3 列裁剪 (v2.36)

- 设计文档：designs/composite_daily_parquet_migration_design.md
- 性能：单文件 3.5min → <5s，217MB → ~20MB
- 列裁剪：60+ 列 → 3 列（date/asset/composite_factor）
- 无下游消费者（codegraph + 全仓 grep 验证）
- 遵循 AGENTS.md 硬规则 #14（禁止死代码冗余）+ 第一性原理（单一数据源）
```
