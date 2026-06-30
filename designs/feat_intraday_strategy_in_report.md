# 日内操作策略（Intraday Strategy）自动生成

> 版本: draft v1
> 设计阶段: Plan（superpowers-workflow）
> 关联: factor-development/references/t1-alignment-and-segment-winrate-analysis.md §7.7/§7.8
>     AGENTS.md 硬规则 #14 (数据 schema 一致) / #5 (T-1 对齐)
>     PROJECT.md 跨模块数据路径表 / 多管线架构段
>     summary/MODULE.md v2.2 持久化层规范

---

## 1. 背景与目标

### 1.1 现状

`summary/report/generate_factor_summary_report.py` 输出 9 大段报告（数据完整性 / 单因子 IC / 分层回测 / 相关性 / 因子筛选 / 综合因子 / 权重选择 / 选股 / 分段胜率），但**没有针对 S6 段的"开盘该怎么卖"的实战指引**。

用户在 2026-06-30 的会话里，针对 S6 段（30 分段 rank 21-25，ob_quality 池）问出操作建议的实证答案：

| 信号 | 操作 | 历史 18 只验证（8 天） |
|:---:|:---|:---:|
| **gap>+0.5%** | D+1 9:25 集合竞价 **以开盘价成交卖出** | 10/10 命中 |
| **gap<-0.5%** | 不在 9:25 卖，**等到盘中高点接近 D 日收盘价（买入成本价）即卖** | 12/13 命中 |
| **平开** | 数据样本小（3-4 只），无强规律 | — |

这是个**第一性原理**结论：低开股盘中反抽是减亏窗口（反抽率 92.3%），不是盈利窗口；高开股直接开盘价卖无回撤敞口。

### 1.2 目标

让**用户每天打开报告就能看到**今天的 ob_quality S6 段股票分组的"开盘前操作清单"，**支持盘中 09:25-09:50 的实盘决策**。

### 1.3 非目标

- ❌ 不改 `stock_selector.py`（不增加操作建议输出列）
- ❌ 不接入券商 API（保持只读分析）
- ❌ 不修改现有 §9 分段胜率 section（不动已有的"D1-D10 表格"逻辑）
- ❌ 不替代用户的最终决断（人类 3-5 只决定权保持不变）
- ❌ 不引入实时行情 API（用前一日 OHLC + 当日已产生的部分 09:25 数据）

---

## 2. 一句话设计原则

**"用真实前一日 close 算 gap，不要再被 forward_return_1d 反推的虚拟前收欺骗。"**

这是上一轮 user 抓出来的真 bug：001339 等复权异常股用 `close/(1+forward_return)` 反推会给出 -15% 的"伪跳空"，但真实跳空仅 -1.19%。本次所有 gap 计算**统一用真实 close[D]**。

---

## 3. 模块新增内容

新增 **3 个持久化函数** + **1 个计算函数** + **1 个渲染函数** + **1 个报告字段**，全部在 summary 模块内：

| 类型 | 位置 | 函数名 | 职责 |
|:---:|:---:|:---|:---|
| 持久化 | `summary/report/segment_win_db.py` | `save_intraday_strategy_recommendation()` | 写 `segment_intraday_strategy.parquet` |
| 持久化 | `summary/report/segment_win_db.py` | `load_intraday_strategy_recommendation()` | 纯读 |
| 计算 | `summary/report/segment_win_db.py` | `compute_intraday_strategy()` | 核心算法 |
| 加载 | `summary/report/data_loaders.py` | `load_intraday_strategy()` | 报告调用入口 |
| 渲染 | `summary/report/sections.py` | `_render_intraday_strategy_section()` | 输出表格 |
| 调度 | `summary/generate_factor_summary_report.py` | — | 在 §9 分段胜率后插入 §10 操作建议 |

**不破坏既有 structure**：
- `segment_win_db.py` 已经是 30 分段持久化枢纽，新函数同模块同命名风格
- `sections.py` 已有 `_render_decile_section` 在 §9，新增 §10 同级函数
- `data_loaders.py` 已有 `load_decile_stats`，新增同名风格的 `load_intraday_strategy`
- 主文件 `generate_factor_summary_report.py` 只在 line 269 之后插入 §10 调用

---

## 4. 数据契约

### 4.1 新持久化文件

```
summary/result/segment_intraday_strategy.parquet
  columns:
    pipeline          string        # 'ob_quality'
    selection_date    string        # T 日 (YYYY-MM-DD) — 用户选股日 (composite 计算日)
    trade_date        string        # T+1 日 — 实际开盘日
    segment_label     string        # 'S6' (固定)
    asset             string        # 股票代码
    prev_close        float64       # T 日真实收盘价 (不用 forward_return 反推)
    open              float64       # T+1 开盘价
    high              float64       # T+1 盘中高点 (用于等高卖减亏计算)
    low               float64       # T+1 盘中低点
    close             float64       # T+1 收盘价
    forward_return_1d float64       # 主数据源原始列 (T+1→T+2 收益)
    real_gap_pct      float64       # (open - prev_close) / prev_close * 100
    open_signal       string        # 'high' / 'low' / 'flat' (基于 real_gap_pct 阈值分桶)
    recommended_action string        # 'sell_at_open' / 'wait_bounce' / 'monitor' / 'data_abnormal'
    expected_return_pct float64     # 不同策略期望收益 (理论值, 给用户参考)
    stop_loss_price   float64       # 止损线 (仅 wait_bounce 有效)
    weight_method     string        # 'rolling_icir_weight' / 'equal_weight' 等
    created_at        timestamp
  partition  : 单文件不分 Hive (数据量小, 8 天 × 5 只 ≈ 40 行)
```

### 4.2 现有文件复用

- `segment_stock_details.parquet` — 取出 S6 段的 (asset, composite_value, rank)
- `data_fetchers/result/factor_ic_data.parquet` — 取 T+1 日 OHLC + T 日 close

### 4.3 阈值常量（hardcoded, 显式标注）

```python
OPEN_SIGNAL_THRESHOLD = 0.5     # ±0.5% 区分高开/低开 (与 §3.4 报告里 D1-D10 的阈值一致)
EXPECTED_GAP_LOWER = -0.5       # gap < -0.5% → 'low'
EXPECTED_GAP_UPPER = 0.5        # gap > +0.5% → 'high'
WAIT_BOUNCE_STOP_TIME = "09:50"  # 9:50 前必须离场
WAIT_BOUNCE_STOP_LOSS_PCT = -0.02  # 反向突破成本价 2% 强制止损 (保守)
```

---

## 5. 核心算法 (`compute_intraday_strategy`)

```python
def compute_intraday_strategy(
    pipeline: str,           # 'ob_quality'
    weight_method: str,
    selection_date: str,     # T 日
    logger: logging.Logger,
) -> pd.DataFrame | None:
    """只算当日 S6 段的日内操作建议.

    流程:
      1. 从 segment_stock_details 拿 S6 段 30 行的 (asset, rank, composite_value)
      2. 从 master 拿 T 日 close + T+1 日 OHLC (T+1 必须存在, 否则返回 None)
      3. 用 (open - prev_close) / prev_close 算 real_gap_pct, 不用反推
      4. 阈值分桶: high / low / flat
      5. 输出 recommended_action + 期望收益 + 止损线
      6. save_intraday_strategy_recommendation(pipeline, weight_method,
                                            selection_date, df)
    """
```

**关键边界**：

| 边界 | 处理 |
|:---|:---|
| T+1 日 OHLC 缺失 | 返回 None + log warning，不写 parquet |
| 复权异常 | 不剔除（保留），`open_signal` 标记为 `'data_abnormal'`，`recommended_action='monitor'` |
| S6 段 N 只 < 1 | 返回 None |
| 09:30 之前调用 | 函数照常跑（用 D+1 日盘中已存在的 open 即可算 gap） |

---

## 6. 报告渲染 (§10 段)

### 6.1 位置

插在 `sections.py` 的 `_render_decile_section` 调用之后 (line 824 后)，作为新的 `十、` section。

### 6.2 输出格式（草案）

```
十、S6 段日内操作建议 (2026-06-30)
----------------------------------------------------------------------
本次数据基于 T=06-29 (周二) 选股 → T+1=06-30 (周三) 开盘
基础数据源 (含复权异常股, 标 ⚠️):  共 N 只
已识别高开: K 只 | 已识别低开: L 只 | 平开/异常: M 只

【操作建议清单】
┌────┬────────┬────────┬────────┬─────────┬────────────┬─────────────────────────┐
│排名│ 代码   │ 名称   │ 真实跳空│open信号 │ 操作       │ 说明                    │
├────┼────────┼────────┼────────┼─────────┼────────────┼─────────────────────────┤
│ 21 │ 002179 │ XX     │ -2.13% │ low    │ wait_bounce│ 等盘中反弹, 9:50 前必出 │
│ 22 │ 600519 │ XX     │ +1.55% │ high   │ sell_at_open│ 9:25 集合竞价直接卖    │
│ 23 │ ...    │ ...    │ +0.12% │ flat   │ monitor   │ 按日内分时自行判断      │
│ 24 │ 002745 │ XX     │ -15.1%│ ⚠️数据 │ monitor   │ 复权异常, 推前收失真    │
└────┴────────┴────────┴────────┴─────────┴────────────┴─────────────────────────┘

【策略说明】
- 高开 (gap > +0.5%): 9:25 按当日集合竞价价卖 — 历史 100% 正向 (10/10)
- 低开 (gap < -0.5%): 等盘中反弹到买入成本价卖出 — 历史 92.3% 命中 (12/13)
   9:50 仍未反抽则跌破成本价 -2% 强制止损出场
- 平开 (-0.5% < gap < +0.5%): 样本不足, 无强规律
- ⚠️数据: 复权异常股 (如除权 / 分红 / 增发), 实盘建议手算

数据来源: segment_stock_details.parquet (S6 段明细) +
          factor_ic_data.parquet (T+1 日 OHLC, 真实 close)
----------------------------------------------------------------------
```

### 6.3 三个关键 invariant

1. **不能用 forward_return_1d 反推前收**（user 抓出 001339 的 -15% 假跳空）
2. **复权异常要明示**（不能默默忽略，但也不能默默包含）
3. **数字必须真实**（每股 prev_close / open / gap 都从 master 直接 merge，不能算错）

---

## 7. 测试用例 (`test_cases/test_intraday_strategy.py`)

| Test # | 验证内容 | 输入 |
|:---:|:---|:---|
| T1 | 18 只真实低开 / 10 只真实高开 / 3 只平开 边界正确 | 用 segment_stock_details + fixture master |
| T2 | 001339 类复权异常股被识别为 `data_abnormal` | 手工构造 fixture |
| T3 | T+1 OHLC 缺失 → 返回 None | 缺数据 fixture |
| T4 | gap > +0.5% → `sell_at_open` | 边界测试 |
| T5 | gap < -0.5% → `wait_bounce` + stop_loss_price = prev_close × 0.98 | 边界测试 |
| T6 | parquet 写后再读 = 原始数据 round-trip | 读写一致性 |
| T7 | 报告 sections 输出包含 §10 标题 + 至少 1 行操作建议 | mock sections 调用 |

---

## 8. 兼容性 / 风险 / Don't

### 8.1 Don't

- ❌ **不要让 report 第 9 节改造** — 现有 `_render_decile_section` 已经稳定，新增 §10 是 additive
- ❌ **不要在 segment_win_db.py 加新表的导出** — 之前有 P0 bug（详见 2026-06-30 commit 6f04608），所有新 parquet 必须走 `pd.read_parquet/df.to_parquet` 而不是 `pyarrow.parquet.write_table`
- ❌ **不要跨模块调用** — 只在 summary 模块内复用 master parquet，禁止从 comprehensive_factor 反向写
- ❌ **不要在主文件 main() 里 raise** — R20 规则
- ❌ **不要在主文件 main() 跑 load_intraday_strategy 时阻塞报告生成** — 失败 → skip §10 而不是整报告崩

### 8.2 Risks

| 风险 | 应对 |
|:---|:---|
| 复权异常股污染 | 显式标记 + 报告中说 "⚠️数据", 不剔除 (用户可能想看实际表现) |
| T+1 OHLC 缺失 | 缺数据 = 跳过当日 §10, 不影响 §1-§9 |
| 用户对 "开盘价" 含义混淆 | 报告里明确写 "D+1 9:25 集合竞价价" |
| 14 天后样本扩到能跑统计检验 | 等数据多了再加 out-of-sample 验证 (本版本只展示历史 8 天的小样本) |
| 多 pipeline / 多 weight_method | intraday_strategy 表加 weight_method 列，每个 (date, weight_method, segment) 一组建议 |

---

## 9. 行数估算（≤200 行 / ≤3 文件 强制）

| 文件 | 改动行数 |
|:---|:---:|
| `summary/report/segment_win_db.py` | ~95 行 (compute + save + load) |
| `summary/report/data_loaders.py` | ~30 行 (load wrapper) |
| `summary/report/sections.py` | ~85 行 (render section) |
| `summary/generate_factor_summary_report.py` | ~10 行 (调度) |
| `summary/test_cases/test_intraday_strategy.py` | ~150 行 (新建) |
| **总计** | **~370 行** |

> 触发 design-first: 涉及 5 个文件, 单文件 < 100 行但跨 5 文件, 必须 design.md 通过。

---

## 10. 后续步骤（如果这个 design 通过）

1. ✅ git init / 不需要 (项目已有 git)
2. **Plan 阶段**: user review 本 design (预计 1 轮)
3. **Execute 阶段**:
   - Step 1: segment_win_db.py 新增 compute / save / load 函数 + ruff
   - Step 2: data_loaders.py 加 wrapper + ruff
   - Step 3: sections.py 加 _render_intraday_strategy_section + ruff
   - Step 4: generate_factor_summary_report.py 调度 + ruff
   - Step 5: 实际运行 + 看报告输出 + 验证 §10 内容
   - Step 6: commit (单 commit, 包含测试 + 文档更新)
4. **Review 阶段**: ruff + pytest + Spec Compliance (回看本 design) + Code Quality
5. **Debug 阶段**: 跑一遍 pipeline 看新报告是否正常

---

## 11. 设计原则自审（第一性原理）

| 原则 | 本设计的体现 |
|:---|:---|
| **第一性原理** | 真实前收计算 gap (不被 forward_return 反推欺骗) |
| **可追溯** | 每只股的 prev_close / open / gap 都可以在 parquet 里查到 |
| **禁叙事标签** | 操作建议基于历史胜率实证, 不是叙事 ("强势股回调"等) |
| **战略目标 (量化辅助)** | 只展示 + 推荐, 3-5 只最终决定权留在人 |
| **AGENTS.md 一致** | 路径从 paths.py 导入 / 日志 % 格式 / 不在 main 里 raise |
| **数据驱动** | 阈值 (±0.5%) 来自 §7.7 历史验证, 不是任意假设 |
| **跨模块边界** | 只读 summary 模块, 不写其他模块 |

如果用户改 review, 改 §3/§5/§6 即可, 其他章节都是 derived 的。
