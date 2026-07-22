# Design: fix capital_flow OOM (Step 11.9)

> 作者: 云瑶
> 创建时间: 2026-06-17
> 关联: 上一轮 tail.py 重构（commit 57eee88..9ed0fb5）后实跑暴露的下一个 OOM 点

---

## §1 背景

`tail.py` 重构后，`factor_generator.py` 实跑可顺利穿过 Step 11（尾盘）/ 11.5～11.8 五个 step。新崩点：

```
2026-06-17 00:31:38 | INFO | factor_generator | Step 11.9: 计算资金流因子...
Command terminated by signal 9
Maximum resident set size (kbytes): 3301552  # 3.30 GB
```

dmesg 确认 OOM-killed: `task=python, pid=2409405, anon-rss:3264732kB`。

## §2 根因分析

`fund_flow.py`（339 行）实现了两个公共因子函数，被 `factor_generator.py` 当作两个独立 pipeline step 串行调用：

| 步骤 | 操作 | 内存代价（1.49M 行）|
|------|------|---------------------|
| step 11.9.1 `calculate_capital_flow_ratio_trend` | `_load_fund_flow_data` 全量读 + `_merge_fund_flow_daily` 1 次（main_inflow_ratio）| ~1 份全表副本 + merge 中间表 |
| step 11.9.2 `calculate_capital_flow_intensity` | `_load_fund_flow_data` **再读一次** + `_merge_fund_flow_daily` **2 次**（amount + volume）| 重复 I/O + 2 份 merge 中间表 |

雪球点：
1. **重复 I/O**：fund_flow_data.json.gz 在同一进程内被加载 2 次，每次 gzip 解压 + json.load + DataFrame 转换叠加。
2. **重复 merge**：3 次 `_merge_fund_flow_daily` 调用，每次都 `factor_df[[date, asset]].copy()` + left_merge 1.49M 行。
3. **每函数 `df = factor_df.copy()` + `df.sort_values()` 全表排序**：两次全表深拷贝 + 排序。
4. `df.set_index([industry, date]).index.map(lambda)` 1.49M 次 Python lambda 调用，慢且产生临时对象。

## §3 方案（方案 A'：模块级缓存 + 内部 orchestrator）

### §3.1 外部约束（不可破坏）

外部模块依赖**两个**公共 API（grep 已确认）：

```
backtest/layered_backtest_capital_flow_ratio_trend_1d.py
backtest/layered_backtest_capital_flow_intensity_1d.py
backtest/test_cases/test_layered_backtest_capital_flow_*_1d.py
factor_ic/test_cases/test_ic_capital_flow_*_1d.py
data_fetchers/factor_calculator/_legacy.py（re-export）
```

→ **`calculate_capital_flow_ratio_trend` / `calculate_capital_flow_intensity` 公共签名必须保留**。

### §3.2 设计决策矩阵

| 子问题 | 决策 | 来源 / 理由 |
|--------|------|--------|
| 是否合并两个公共函数？| **不合并**（保 thin wrapper 兼容外部）| 用户已选方案 A，但外部调用面发现 backtest/factor_ic 直接 import 这两个函数（grep 确认 6 个外部调用点），合并会破坏 4 个 backtest/IC 脚本 |
| pipeline 内是否合并 step？| **合并为 1 个 orchestrator step**（output_cols=2 列）| factor_generator 内部专属优化，不影响外部 API |
| 重复 I/O 怎么消？| `_load_fund_flow_data` 加 process-local cache（`functools.lru_cache(maxsize=1)`）| 同 PID 内 fund_flow_data.json.gz 内容不变，cache 完全安全。第二次调用直接返回同一 DataFrame |
| 重复 merge 怎么消？| pipeline 内部新建私有 helper `_calculate_capital_flow_block(factor_df, *, logger_arg)`，**一次 merge 同时拿 main_inflow_ratio / main_inflow_amount / total_volume 三列**，再算 ratio_trend + intensity | 同一份 fund_flow_df，三个值列共用同一次 merge keys |
| 公共 API 内部如何复用？| `calculate_capital_flow_ratio_trend(df)` / `calculate_capital_flow_intensity(df)` 仍调原路径（保字节级一致），仅 `_load_fund_flow_data` 走 cache 减少重复 I/O | thin wrapper 改动最小化，外部测试无需调整 |
| 全表 copy + sort 怎么消？| `_calculate_capital_flow_block` 内**只 copy 一次** + 仅在需要 shift 时排 sub_df（不排全表）| MODULE.md R16 大对象 del 释放 |

### §3.3 实施步骤（拆 4 个独立 commit）

**Round 1 — fund_flow.py 内 cache + multi-merge helper**（1 文件 ≤80 行改动）
- `_load_fund_flow_data` 改为模块级 `@functools.lru_cache(maxsize=1)`（注：参数 None 路径才 cache，自定义 path 不 cache）
- 新增私有 helper `_merge_fund_flow_daily_multi(factor_df, fund_flow_df, value_cols, logger_arg)` —— 一次 merge 返回 N 列
- 保留 `_merge_fund_flow_daily` 单列签名（thin wrapper 调 multi 版）维持外部依赖
- `calculate_capital_flow_ratio_trend` / `calculate_capital_flow_intensity` 函数体不动（cache 自动生效）
- ⚠️ 单元测试：保证 cache 在两次调用之间返回**同一对象**（id 相等）

**Round 2 — fund_flow.py 内 orchestrator helper（私有，仅 factor_generator 用）**（1 文件 ≤120 行改动）
- 新增 `_calculate_capital_flow_block(factor_df, *, logger_arg) -> pd.DataFrame`：
  - 一次 `_load_fund_flow_data`（cache 命中）
  - 一次 `_merge_fund_flow_daily_multi(..., ["main_inflow_ratio", "main_inflow_amount", "total_volume"])`
  - 一次 `_add_industry_column`
  - 内部分两段算 ratio_trend + intensity，共享 industry 列、共享 fund_flow_df 引用
  - 函数末尾 `del fund_flow_df, ratio_daily, amount_daily, volume_daily` + `gc.collect()`
- 公共签名 `_calculate_capital_flow_block.required_cols = [...]`、`output_cols=("capital_flow_ratio_trend", "capital_flow_intensity")`
- ⚠️ 字节级一致性测试：与原两个公共函数串行结果对比（assert_frame_equal）

**Round 3 — factor_generator.py pipeline 表替换**（1 文件 ≤30 行改动）
- 删除原两个 step（line 352-365）
- 新增单个 step：`{"step_label": "Step 11.9: 计算资金流因子...", "factor_func": _calculate_capital_flow_block, "output_cols": ("capital_flow_ratio_trend", "capital_flow_intensity"), "emit_valid_log": True}`
- import：从 `data_fetchers.factor_calculator.fund_flow` 引入 `_calculate_capital_flow_block`
- 启动期校验 `_EXTENDED_FACTOR_COLS_SET == _PIPELINE_OUTPUT_COLS_SET` 自动通过（output_cols 总集合不变）

**Round 4 — 实跑验收**
- 清理 result/*.tmp（如有）
- `/usr/bin/time -v python -m data_fetchers.factor_generator` 抓内存峰值
- 目标：max RSS < 3.0 GB（capital_flow 块降幅 ≥30%），管道走到 step 12 / 终点
- 因子 IC 抽查：capital_flow_ratio_trend / capital_flow_intensity 有效率 / 数值范围与历史一致（避免误改）

## §4 风险

| 风险 | 缓解 |
|------|------|
| `lru_cache` 在多次 factor_generator 同进程调用下持有大对象不释放 | maxsize=1 + 提供 `_load_fund_flow_data.cache_clear()` 调用钩子；factor_generator 在管道末尾显式 clear |
| `_merge_fund_flow_daily_multi` 在外部 backtest 单跑场景下未走 cache（path 自定义）| 测试覆盖 path=None 和 path=显式两种分支 |
| `_calculate_capital_flow_block` 与原两函数串行结果不字节一致（如 industry 列复用导致中间值漂移）| 每个 Round 跑 `assert_frame_equal` 等价性测试 + 数值快照对比 |
| factor_generator 内部 helper 命名 `_` 开头但被 pipeline 表引用 | 对比 tail：`calculate_tail_factors` 是公共函数。改用 `calculate_capital_flow_block`（不带下划线）作为内部 orchestrator，加 docstring 声明"factor_generator 专用编排函数，外部不应直接调用" |

最终选名：**`calculate_capital_flow_block`**（不带下划线，与 `calculate_tail_factors` 风格一致；docstring 显式声明语义）

## §5 验收标准（Round 4）

- [ ] ruff check + format 通过
- [ ] data_fetchers/test_cases/test_factor_calculator_fund_flow.py 全 pass（新建）
- [ ] backtest/test_cases/test_layered_backtest_capital_flow_*_1d.py 仍 pass（外部 API 兼容）
- [ ] factor_generator 实跑 max RSS 下降 ≥ 30%（基线 3.30 GB → 目标 < 2.3 GB）
- [ ] capital_flow_ratio_trend / capital_flow_intensity 有效率与重构前一致（容差 0 行）
- [ ] git commit 显式路径（多 agent 协作铁律），不裹其他 staged 文件

## §6 不在范围

- 行业映射缓存优化（`_add_industry_column` 已有 idempotent 保护，本次不动）
- `industry_financial.py` 同模式优化（独立任务）
- `data_fetchers/test_cases/test_factor_generator.py` 集成测试本身的 OOM（pre-existing，非本任务）
