# stock_selector 模块规范

> 最后更新: 2026-06-26（从 comprehensive_factor 迁移为独立顶层模块）

## 目录

- [模块概述](#模块概述)
- [脚本清单](#脚本清单)
- [选股流程](#选股流程)
- [权重选择脚本](#权重选择脚本)
- [选股脚本](#选股脚本)
- [输出路径](#输出路径)
- [跨模块依赖](#跨模块依赖)
- [版本历史](#版本历史)

---

## 模块概述

stock_selector 是独立顶层模块，负责股票选股全流程：权重方式选择 → 综合因子计算 → 排序选股 → 历史归档。

从 `comprehensive_factor/` 迁移而来（2026-06-26），迁移后代码位置变更但输出路径不变（数据仍写入 `comprehensive_factor/result/`）。

---

## 脚本清单

| 脚本 | 职责 |
|------|------|
| `selector.py` | 核心选股逻辑 + CLI（原 stock_selector.py） |
| `config.py` | 配置/常量/数据加载（原 stock_selector_config.py） |
| `history.py` | Parquet 选股历史写入（原 stock_selector_history.py） |
| `lr.py` | LR 过滤训练/应用/训练数据持久化（原 stock_selector_lr.py） |

> **Note**: `weight_selector.py` 已移回 `comprehensive_factor/composite_weight_selector.py`（职责属于综合因子权重评估，不属于选股）。

---

## 选股流程

```
Step 6: 权重方式选择 (comprehensive_factor/composite_weight_selector.py)
  ├─ 提取评价指标（v2.35: 7指标全对齐只做多——含layer_1_annual/layer_1_sharpe）
  ├─ Min-Max归一化（方向统一化）
  ├─ 等权综合得分
  └─ 输出最优权重方法
                              ↓
Step 7: 股票选股 (selector.py)
  ├─ 加载最优权重配置（weight_selection_result.json）
  ├─ 加载当日因子数据（factor_ic_data.parquet）
  ├─ 标准化因子值
  ├─ 方向统一化（反向因子取反对齐到正向，同 comprehensive_factor Step 3.5）
  ├─ 加载 IC 每日序列（滚动ICIR需要）
  ├─ 计算综合因子值（使用最优权重方法）
  ├─ 按因子方向排序（反向升序/正向降序）
  ├─ v2.44: Stage 1 — composite Top stage1_pool_size (默认 200, 设计 §2.2)
  ├─ v2.44: Stage 2 — 在 Stage 1 内按 stage2_sort_col 升序取 top_n*2 (默认 turnover_rate 升序)
  ├─ v2.35: P6 企稳确认过滤（Stage 3，排除无企稳信号股票）
  └─ 输出 Top N 股票列表
```

---

## 选股脚本

**脚本**: `selector.py`

**功能**: 使用最优权重方法计算股票综合因子值并选出 Top N

**因子列表来源**（遵循数据层架构原则）:
- 因子列表从最优权重方法的 composite 结果中读取（`composite_{method}_weight_{return_period}.json`）
- 不应硬编码默认值（如 `rsi/volume_ratio`），因为筛选后的因子由 comprehensive_factor 模块决定
- **数据流**：`factor_selector.py` 篮选因子 → `composite_runner.py` 保存筛选结果 → `selector.py` 读取筛选结果

**前置过滤**（v1.12 新增）:
- **振幅过滤**: 振幅 < `min_amplitude`（默认1%）的股票被排除
  - 原因：振幅<1%的股票通常是一字板或接近一字板的涨停股，实际不可买入（全天封板无成交机会）
  - 若涨停打开可买入，往往意味着趋势反转，恰恰是卖点而非买点
  - 振幅=0（一字板）占约0.1%股票，振幅<1%占约0.4%股票，排除比例极小

**流程**:
```
1. 加载最优权重配置（weight_selection_result.json）
2. 从最优权重 composite 结果读取因子列表（factor_list/factor_cols）
3. 加载当日因子数据（factor_ic_data.parquet）
4. 确定选股日期（默认取最新日期）
5. 过滤数据（只保留选股日期）
6. 标准化因子（截面标准化）
7. 加载 IC 数据（根据权重方法）
8. 计算综合因子（使用最优权重方法）
9. 排序选出 Top N（含前置过滤：覆盖率过滤 + 振幅过滤）
10. 输出结果
```

**过滤顺序**:
1. NaN 综合因子值过滤
2. 因子覆盖率过滤（覆盖率 < 50% 排除，安全网）
3. 振幅过滤（振幅 < min_amplitude 排除，排除不可交易的一字板涨停股）
4. 排序 + Top N

**排序规则**:
- **反向因子** (`factor_direction=negative`): 升序排序（综合因子值越小越好）
- **正向因子** (`factor_direction=positive`): 降序排序（综合因子值越大越好）

**输出 (v3.7, designs/feat_stock_selection_history_parquet.md)**:

`comprehensive_factor/result/stock_selection_history/selection_date=YYYY-MM-DD/part-0.parquet`

**布局**: Hive-style 分区 Parquet 数据集. 每天一个分区, 含 Stage 1/2/3 Top 30 共 ~90 行 (单阶段模式仅 stage3, ~30 行). 同日重跑覆盖该分区, 历史分区不动. **无 JSON 兜底**——写失败抛 RuntimeError, pipeline 退出码 1.

**Schema** (23 列, 详见 `stock_selector/schemas/stock_selection_history.schema.json`):

| 列 | 类型 | 说明 |
|---|---|---|
| selection_date | string (分区键, 虚拟列) | 选股日期 |
| stage | int8 | 1=composite 降序 / 2=stage2_sort_col 重排 / 3=企稳+决策卡 |
| rank | int16 | 该 stage 内名次 (1-based) |
| code | string | 股票代码 |
| composite_value | float64 | 标准化综合因子值 (z-score) |
| weight_coverage | float64 (nullable) | v1.15 权重覆盖率 |
| stage1_rank | int16 (nullable) | Stage 1 名次 (Stage 2/3 行保留以供轨迹追溯) |
| stage2_sort_value | float64 (nullable) | Stage 2 排序列原始值 (仅 Stage 2 行) |
| excluded_at_stage3 | string (nullable) | 'stabilization' = Stage 2 被企稳过滤淘汰 |
| weight_method, factor_direction, top_n | — | 配置快照 |
| stage1_pool_size, stage2_sort_col, stage2_ascending | nullable | 两阶段配置 (单阶段全 null) |
| direction_map_json, flipped_factors_json | string | 方向统一化元数据 (JSON 串) |
| composite_score | float64 | weight_selector 最优分数 |
| created_at | timestamp[us,UTC] | 写入时刻 |
| run_id | string (uuid) | 审计 UUID |
| factor_values_json, factor_values_std_json, decision_card_json | nullable | 嵌套字段 JSON 序列化, 仅 Stage 3 行有值 |

**File-level metadata** (`pq.read_metadata(...).metadata`, 不在 schema 中, 用于统计):
- `excluded_by_amplitude` / `excluded_by_coverage` / `excluded_by_liquidity` / `excluded_by_confirmation` (整数字符串)
- `excluded_by_filter` (filter 角色排除字典 JSON 串)
- `min_amplitude` / `min_weight_coverage` / `stocks_on_date` / `factor_list_json` / `factor_cols_json` / `generated_at`

**读取 (示例)**:

```python
import pyarrow.compute as pc
import pyarrow.dataset as pads

ds = pads.dataset("comprehensive_factor/result/stock_selection_history", partitioning="hive")
# 单日 stage 3 短名单
df = ds.to_table(
    filter=(pc.field("selection_date") == "2026-06-23") & (pc.field("stage") == 3)
).to_pandas()
# 跨日轨迹: 某股票每天 stage 3 名次变化
trajectory = ds.to_table(
    filter=(pc.field("code") == "002126") & (pc.field("stage") == 3)
).to_pandas().sort_values("selection_date")
```

**Schema 演进硬约束** (`design §5.2`):
- ✅ 加列 (nullable)
- ❌ 删/改名现有列
- ❌ 改 nullable 属性
- ❌ 改分区键格式

**已废弃** (v3.6 及之前, 保留只读):
- `result/stock_selection_result.json` 单文件输出, schema 见 `comprehensive_factor/schemas/stock_selection_result.deprecated.schema.json`
- `result_baseline_20260621/stock_selection_result.json` 备份目录历史快照

**CLI 参数**:
```bash
python -m stock_selector.selector \
    --top_n 10 \
    --min_amplitude 0.01 \
    --selection_date 2026-06-01 \
    --factor_direction negative \
    --rolling_window 60
```

**Note**:
- `top_n` 默认值改为 10（v1.12: 从3改为10，扩大选股范围），而非 3
- `min_amplitude` 默认值 0.01（1%），排除振幅<1%的一字板涨停股（v1.12新增）
- `factor_list/factor_cols` 从 composite 结果动态读取，示例中显示的是实际筛选后的因子名

---

## LR 过滤模块 (lr.py)

**功能**: Logistic Regression 过滤训练/应用/训练数据持久化

- `calibrate_lr_filter()`: 从 lr_training_data Parquet 读取训练样本，训练 LR 模型
- `apply_lr_filter()`: 对 Bottom90 候选打分排序（v3.13: 不截断，仅打分）
- `save_lr_training_data()`: 每日保存 Bottom90 + 因子权重 + 因子原始值到 Parquet 双分区
- `backfill_forward_return_1d()`: 次日补写 T+1 收益

**训练数据路径**: `comprehensive_factor/result/lr_training_data/weight_method=<method>/selection_date=YYYY-MM-DD/`

---

## 输出路径

> **注意**: 迁移后输出路径仍指向 `comprehensive_factor/result/`，保持数据连续性。

| 输出 | 路径 | 来源脚本 |
|------|------|----------|
| 选股历史 Parquet | `comprehensive_factor/result/stock_selection_history/` | `history.py` |
| LR 训练数据 | `comprehensive_factor/result/lr_training_data/` | `lr.py` |

---

## 跨模块依赖

### 合法依赖（comprehensive_factor 共享基础设施）

| 依赖 | 来源 | 用途 |
|------|------|------|
| `factor_loader` | `comprehensive_factor.common` | 因子数据加载 |
| `weight_engine` | `comprehensive_factor.common` | 权重引擎 |
| `convert_types` | `comprehensive_factor.common` | 类型转换 |
| `build_decision_cards` | `comprehensive_factor.decision_card` | 决策卡构建 |

### 上游数据

| 数据 | 来源 | 路径 |
|------|------|------|
| 因子数据 | `factor_ic_data.parquet` | `data_fetchers/result/` |
| 权重配置 | `weight_selection_result.json` | `comprehensive_factor/result/` |
| Composite 结果 | `composite_*_weight_*.json` | `comprehensive_factor/result/` |
| IC 结果 | `ic_*_analysis_result.json` | `factor_ic/result/` |

### 下游消费者

| 消费者 | 数据 | 用途 |
|--------|------|------|
| `summary` | 选股历史 Parquet | 报告"八、股票选股结果"展示 |
| `summary` | `StockSelectorConfig` | LR 训练状态展示 |

---

## 版本历史

| 版本 | 日期 | 说明 |
|------|------|------|
| v3.15 | 2026-06-26 | 从 comprehensive_factor 迁移为独立顶层模块 stock_selector/. 文件重命名: stock_selector.py→selector.py, stock_selector_config.py→config.py, stock_selector_history.py→history.py, stock_selector_lr.py→lr.py. weight_selector.py 保持不变. 输出路径不变. |
| v3.14 | 2026-06-26 | select_stocks 内部重构——521行上帝函数提取为6个内部辅助函数. 纯重构, 行为零改动. |
| v3.13 | 2026-06-26 | apply_lr_filter 从排除过滤器转为不截断排序器. 全部90只按proba_up降序输出. |
| v3.12 | 2026-06-26 | 纯重构拆分——2749行单文件拆为4文件. |
| v3.11 | 2026-06-25 | 四种权重方式每天各存一份LR训练数据. |
| v3.10 | 2026-06-25 | LR训练数据持久化+第一性原理修复. |
| v3.7 | 2026-06-24 | 废除JSON单文件,改用Parquet分区数据集. |
