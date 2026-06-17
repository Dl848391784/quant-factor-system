# Design: fix industry financial OOM in factor_generator Step 11.8

> 作者: 云瑶
> 创建时间: 2026-06-17
> 状态: 待用户审核
> 关联实跑: `/usr/bin/time -v python data_fetchers/factor_generator.py` 在 `industry_earnings_growth` 后被 OOM-kill

---

## §1 背景与现场证据

上一轮已完成 Step 11.9 资金流修复：`factor_generator.py` 中资金流两因子已切为 `calculate_capital_flow_block` 单 step orchestrator，并提交 `d03e0b1`。

但随后真实全链路实跑仍失败：

```text
2026-06-17 11:45:31 | INFO | factor_generator |   有效 industry_earnings_growth: 1494817 (100.00%)
Command terminated by signal 9
Maximum resident set size (kbytes): 3304836
```

`dmesg` 同步确认：

```text
Out of memory: Killed process ... (python) ... anon-rss:3270036kB
```

结合 `_FACTOR_PIPELINE_STEPS` 顺序：

```text
Step 11.8:
  calculate_industry_roe_trend
  calculate_industry_earnings_growth
  calculate_industry_pe_trend     ← 当前真实崩点（以前 step_label=None，不打段头）
Step 11.9:
  calculate_capital_flow_block
```

因此本轮真实目标是：**修复 Step 11.8 行业财务三因子重复 I/O / 重复日频对齐 / 重复全表复制导致的 OOM，尤其是 `calculate_industry_pe_trend` 进入前内存已接近阈值的问题。**

---

## §2 规范触发与范围

| 规范 | 触发原因 | 处理 |
|------|----------|------|
| PROJECT.md H8 / Design-First（行 115-123） | 预计触及 4 个文件：`industry_financial.py`、`factor_generator.py`、测试、流程文档 | 先提交本 design，用户审核通过后再写代码 |
| PROJECT.md H9（行 161） | 总体改动可能 >200 行 | 拆 4 轮，每轮 ≤3 文件、≤200 行 |
| data_fetchers/MODULE.md R16 | OOM / 大对象生命周期 | block 内显式 `del` 大中间对象；减少重复 copy/merge |
| PROJECT.md H11 | 日志惰性格式化 | 所有新增日志用 `%s/%d`，不使用 f-string |
| AGENTS.md #8 | 新脚本/流程变更同步流程文档 + pytest | 同步 `factor_generator_flow.md` 与相关 pytest |

---

## §3 根因分析

`industry_financial.py` 当前三个公共函数被 pipeline 串行调用：

| 函数 | 当前行为 | 1.49M 行规模下的问题 |
|------|----------|----------------------|
| `calculate_industry_roe_trend` | `factor_df.copy()` + `_load_financial_data` + `_merge_asof_financial` + sort + groupby + `set_index().index.map(lambda)` | 全表复制 1 次，财务数据加载 1 次，日频对齐 1 次 |
| `calculate_industry_earnings_growth` | 再次 `copy/load/merge_asof/groupby/map` | 重复财务加载和日频对齐，返回后保留新增列 |
| `calculate_industry_pe_trend` | 第三次 `copy/load/merge_asof/sort/groupby/map`，还额外产生 `eps_daily/pe_daily/delta_pe` | 进入时已持有大量列，PE 又复制全表并新增 3 个中间列，触发 RSS ~3.3GB 后 OOM |

关键问题：

1. **重复 I/O**：`financial_data.json.gz` 被三次 gzip 解压 + JSON load + DataFrame 构造。
2. **重复日频对齐**：`_merge_asof_financial` 三次分别对齐 `roe` / `net_profit_growth_yoy` / `annualized_eps`。
3. **重复全表复制**：三个函数各自 `df = factor_df.copy()`，越到后面列越多，复制越贵。
4. **Python 级赋值路径**：三处 `df.set_index(...).index.map(lambda idx: trend_map.get(...))` 对 149 万行做 Python lookup，慢且产生临时对象。
5. **可观测性缺口**：`industry_pe_trend` 曾为 `step_label=None` 且 `emit_valid_log=False`，失败时日志停在 `industry_earnings_growth` 后，容易误判为 Step 11.9。

---

## §4 方案总览：行业财务三因子 block orchestrator

新增公共 orchestrator：

```python
def calculate_industry_financial_block(
    factor_df: pd.DataFrame,
    *,
    financial_data_path: str | Path | None = None,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """一次性产出 industry_roe_trend / industry_earnings_growth / industry_pe_trend。"""
```

### 核心优化

| 优化点 | 做法 | 预期效果 |
|--------|------|----------|
| 财务数据只加载一次 | block 内一次 `_load_financial_data` | 消除 2 次 gzip/json/DataFrame 构造 |
| 日频对齐合并 | 新增 `_merge_asof_financial_multi(..., value_cols)`，一次 `merge_asof` 返回三列 | 消除 2 次大 merge/sort |
| 全表只复制一次 | block 内 `df = factor_df.copy()` 一次 | 避免第三个 PE 函数复制宽表 |
| industry 只添加一次 | block 内一次 `_add_industry_column` | 减少重复 industry map |
| 行业聚合一次完成 | `groupby([industry, date]).agg(...)` 同时产出三列 | 减少 groupby 和中间对象 |
| 赋值 vectorized merge | `df.merge(industry_agg, on=[industry, date], how="left")` | 替代 1.49M 次 `lambda get` |
| 中间列生命周期收敛 | return 前 drop `roe_daily/growth_daily/eps_daily/pe_daily/delta_*` + `del` 大对象 | 降低峰值和残留 |

---

## §5 设计决策矩阵

| 子问题 | 决策 | 来源 / 理由 |
|--------|------|-------------|
| 是否删除原三个公共函数？ | **不删除，签名保持不变** | codegraph 显示三函数为 `factor_calculator` 公共节点；外部 backtest/IC 可能直接 import，公共 API 兼容优先 |
| pipeline 内是否合并 step？ | **合并为 1 个 `calculate_industry_financial_block` step，output_cols=3 列** | 用户已选择“更合理的修复方案”；资金流 R3 同类问题已验证 block 模式更合适 |
| block 是否带下划线？ | **不带下划线** | 与 `calculate_capital_flow_block` / `calculate_tail_factors` 风格一致；可被 pipeline 明确 import |
| 原三个函数是否复用 block？ | **本轮不强制复用，保留现状** | 降低外部行为变化风险；block 专供 factor_generator 优化，等价性由测试保障 |
| `_load_financial_data` 是否加 lru_cache？ | **不作为首要方案，可作为 Round 4 失败后的备选** | 单进程内 block 已只加载一次；对外公共函数连续调用可受益，但缓存 219k 行 DataFrame 可能延长对象生命周期 |
| `_merge_asof_financial` 是否改签名？ | **不改，新增 `_merge_asof_financial_multi`** | 避免破坏现有公共函数；单列 helper 保持兼容 |
| PE 可观测性如何处理？ | **pipeline block 的 step_label 明确为 `Step 11.8: 计算行业基本面动量因子...`，三列有效计数 INFO 输出** | 避免“earnings 后静默死亡”再次误判 |
| 行顺序如何保证？ | **保留当前串行函数最终行序：按 `asset,date` 排序后的顺序** | 原 `calculate_industry_roe_trend` 和 `calculate_industry_pe_trend` 都会 sort，最终 pipeline 已非原输入顺序；等价测试按同一索引/顺序比较 |
| 数值等价标准 | **与旧三个函数串行结果 `assert_frame_equal`，三列逐列一致** | 防止 vectorized merge 改变 NaN/均值/clip 语义 |

---

## §6 实施拆分

### Round 1 — `industry_financial.py` 新增 multi-merge + block（1 文件，≤160 行）

改动文件：

- `data_fetchers/factor_calculator/industry_financial.py`

内容：

1. 新增 `_merge_asof_financial_multi(factor_df, financial_df, value_cols, logger_arg)`：
   - 准备 `financial_df[[asset, report_date] + value_cols]`
   - rename `report_date -> date`
   - `pd.merge_asof(..., by=asset, on=date, direction="backward")`
   - 返回与 `factor_df` 行数对齐的 DataFrame（只含 value cols）
2. 新增 `calculate_industry_financial_block(...)`：
   - 一次 copy
   - 一次 load financial
   - 一次 multi asof 拿 `roe/net_profit_growth_yoy/annualized_eps`
   - 计算 `delta_roe/growth_daily/pe_daily/delta_pe`
   - 一次 `_add_industry_column`
   - 一次 `groupby(...).agg(...)`
   - vectorized merge 回写三列
   - drop/del 中间列
   - INFO 输出三列有效率
3. 设置：
   - `calculate_industry_financial_block.required_cols = ["date", "asset", "close"]`

不做：

- 不删除/不改签名 `calculate_industry_roe_trend` / `calculate_industry_earnings_growth` / `calculate_industry_pe_trend`
- 不改 `_legacy.py` / `__all__`，除非测试发现 `factor_generator.py` 无法从子模块直接 import

### Round 2 — 新增等价性测试（1 文件，≤160 行）

改动文件：

- 新增或扩展 `data_fetchers/test_cases/test_factor_calculator_industry_financial.py`

测试：

1. `_merge_asof_financial_multi` 与三次 `_merge_asof_financial` 单列结果一致。
2. `calculate_industry_financial_block` 与旧三个函数串行调用的三列结果一致：

```python
legacy = calculate_industry_pe_trend(
    calculate_industry_earnings_growth(
        calculate_industry_roe_trend(input_df, financial_data_path=fixture),
        financial_data_path=fixture,
    ),
    financial_data_path=fixture,
)
block = calculate_industry_financial_block(input_df, financial_data_path=fixture)
assert_frame_equal(
    legacy[["industry_roe_trend", "industry_earnings_growth", "industry_pe_trend"]],
    block[["industry_roe_trend", "industry_earnings_growth", "industry_pe_trend"]],
)
```

3. 覆盖 EPS ≤ 0 / EPS NaN / growth NaN 边界。
4. 覆盖输出列齐全和原输入不被原地污染。

### Round 3 — `factor_generator.py` pipeline 切换（2 文件，≤80 行）

改动文件：

- `data_fetchers/factor_generator.py`
- `data_fetchers/test_cases/test_factor_generator_helpers.py`

内容：

1. import `calculate_industry_financial_block`。
2. `_FACTOR_PIPELINE_STEPS` 中 Step 11.8 从 3 个独立 step 改成 1 个 step：

```python
{
    "step_label": "Step 11.8: 计算行业基本面动量因子...",
    "factor_func": calculate_industry_financial_block,
    "output_cols": ("industry_roe_trend", "industry_earnings_growth", "industry_pe_trend"),
    "emit_valid_log": True,
}
```

3. 同步测试中 step 数：26 → 24（Step 11.8 三合一减少 2 个 step；上一轮 Step 11.9 二合一已减少 1 个 step）。
4. `_EXTENDED_FACTOR_COLS_SET == _PIPELINE_OUTPUT_COLS_SET` 应保持自动通过（输出列集合不变）。

### Round 4 — 文档 + 实跑验收（1-2 文件，≤80 行）

改动文件：

- `data_fetchers/docs/factor_generator_flow.md`
- 必要时补 `data_fetchers/MODULE.md` 的实现说明（仅用户同意后；本轮默认不改规范）

验收：

```bash
ruff format data_fetchers/factor_generator.py data_fetchers/factor_calculator/industry_financial.py data_fetchers/test_cases/test_factor_calculator_industry_financial.py data_fetchers/test_cases/test_factor_generator_helpers.py
ruff check data_fetchers/factor_generator.py data_fetchers/factor_calculator/industry_financial.py data_fetchers/test_cases/test_factor_calculator_industry_financial.py data_fetchers/test_cases/test_factor_generator_helpers.py
pytest data_fetchers/test_cases/test_factor_calculator_industry_financial.py data_fetchers/test_cases/test_factor_generator_helpers.py -q
/usr/bin/time -v python data_fetchers/factor_generator.py
```

成功标准：

- 轻量 pytest 全 pass。
- 实跑至少穿过 Step 11.8，并进入 Step 11.9；理想目标是完整生成 `factor_ic_data.json.gz`。
- `Maximum resident set size` 不再在 `industry_pe_trend` 附近达到 ~3.3GB 后被 kill。
- 三个行业财务因子有效率与历史串行结果一致（测试夹具 0 容差；真实数据以日志对比为证据）。

---

## §7 风险与缓解

| 风险 | 缓解 |
|------|------|
| multi asof 与三次单列 asof 排序/NaN 语义不同 | Round 2 用单列 helper 对照 multi helper；block 对照旧三函数串行结果 |
| vectorized merge 改变行顺序 | 明确以旧串行最终行序为等价标准；必要时在 block 中按 `[asset,date]` 后再 merge，和旧 PE 最终状态一致 |
| block 输出三列但 `emit_valid_log=True` 会重复打印内部日志与 pipeline 日志 | 接受重复少量 INFO，优先可观测性；若噪音过多，内部日志只保留 step 级，pipeline 负责 valid count |
| 新增公共函数未重导出导致 pipeline import 失败 | pipeline 可直接从 `data_fetchers.factor_calculator.industry_financial` import；不强制改 `_legacy.__all__` |
| 实跑仍在后续 Step 11.9 或 Step 12 OOM | 视为下一瓶颈；本轮目标先消除 Step 11.8 PE OOM，并记录新崩点 |
| `test_factor_generator.py` 真实全量测试本身 OOM | 不作为轻量单测验收；真实全链路用 `/usr/bin/time -v python data_fetchers/factor_generator.py` 单独执行 |

---

## §8 不在本轮范围

- 不改因子定义、方向、IC 结论。
- 不改 `financial_data.json.gz` 数据结构。
- 不删除原三个行业财务公共函数。
- 不重构 `test_factor_generator.py` 的真实数据测试（它本身会 OOM，单独治理）。
- 不修改 PROJECT.md / MODULE.md 规范条文，除非用户另行确认。

---

## §9 用户确认点

请确认是否按本设计执行：

1. 接受新增 `calculate_industry_financial_block` 作为 factor_generator 专用三因子 orchestrator。
2. 原三个公共函数保持兼容，不删除、不改签名。
3. Round 3 pipeline step 数从 26 变为 24，输出列数仍为 31。
4. 实跑验收以 `/usr/bin/time -v python data_fetchers/factor_generator.py` 为准，`test_factor_generator.py` 暂不作为轻量 pytest 验收。