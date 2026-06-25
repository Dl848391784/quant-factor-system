# Design: Bottom30 过热过滤替代 Top30 Stage 2/3

## 背景

### 问题陈述

当前 stock_selector 对 Top30（弱势股，composite 最高端）做三段处理（Stage 1 composite 排序 → Stage 2 turnover 重排 → Stage 3 企稳过滤），而 Bottom30（强势股，composite 最低端）仅做只读快照，无任何过滤。

数据分析（2026-06-25, 548 日全样本, 15531 条 Bottom30 记录）显示：
- Bottom30 整体 T+1 = +0.41%/天（年化 +104%）
- **过热信号**（高换手 + 放量）把 Bottom30 劈成两半：
  - 过热: T+1 = -0.31%/天（年化 -78%），胜率 42.6%
  - 未过热: T+1 = +0.55%/天（年化 +139%），胜率 47.6%
  - 差异 0.86%/天，p < 0.0001

### 改动目标

1. Top30 的 Stage 2/3 不再输出到 summary 报告
2. Bottom30 新增过热过滤：从 30 只里排除过热的，保留未过热的
3. 重心转到 Bottom30，调整报告格式、决策卡片字段

## 影响范围

```
□ 短名单 (30~50) ← 量化职责
  → 从 Top30（弱势股企稳过滤）改为 Bottom30（强势股过热过滤）
□ Layer 1 候选池 (549) ← 量化基础设施
  → 不变
□ 最终持仓 (3~5) ← 用户职责
  → 不变（量化不越界）
```

## 第一性原理

### 过热信号的物理含义

高换手率（截面高分位）意味着筹码松动、短线资金涌入；放量（volume_ratio_5 截面高分位）意味着多空分歧加大。两者结合 = "击鼓传花到最后阶段"，T+1 大概率回落。

这不是叙事标签，而是实证数据：p < 0.0001，样本 15000+，差异 0.86%/天。

### 为什么排除而非保留

Bottom30 是强势股，未过热的强势股 T+1 = +0.55%/天（趋势延续）。过热的强势股 T+1 = -0.31%/天（反转下跌）。**排除过热的 = 保留趋势延续的**，符合第一性原理。

### 阈值依据（v3.9.2: 彻底数据驱动, LR 模型）

| 参数 | v3.9 (写死) | v3.9.1 (分位校准) | v3.9.2 (LR 模型) |
|------|------------|-------------------|-----------------|
| 特征选择 | 主观选 turnover+volume_ratio | 同 (2 个固定特征) | Cohen's d 选 top 10 (数据发现) |
| 阈值 | 固定绝对值 1.5 | 分位网格搜索 | LR 模型打分, 底 30% 排除 |
| OOS 验证 | 无 | 无 | walk-forward 120 天, AUC > 0.55 |

**LR 校准逻辑** (`calibrate_lr_filter`):
1. 用全历史数据（549 天）每日取 Bottom30 样本
2. 扫描所有 ~78 个特征, 计算 Cohen's d, 选 top 10 (数据驱动)
3. Walk-forward: 120 天训练窗口滚动, 计算 OOS AUC
4. OOS AUC > 0.55 → 用全样本训练最终模型
5. 对当日 Bottom30 打分, 排除预测 T+1 跌概率最高的 30%

**Walk-forward 验证结果** (return_5d 选 Bottom30, 384 个 OOS 窗口):
- OOS AUC = 0.635 ± 0.128, 78% 窗口 > 0.55
- 保留组 T+1 = +0.0145%, 胜率 55.2%
- 排除组 T+1 = -0.0123%, 胜率 39.9%
- 差异 0.027%/天, p = 1e-83

## 详细设计

### 1. 新增 `apply_overheat_filter` 函数

**位置**: `comprehensive_factor/stock_selector.py`，在 `apply_stabilization_filter` 后

**签名** (v3.9.2):
```python
def _discover_features(
    bottom_df: pd.DataFrame,
    feature_cols: list[str],
    top_n: int,
    logger: logging.Logger,
) -> list[str]:
    """数据驱动特征发现: Cohen's d 选 top N 特征."""

def calibrate_lr_filter(
    factor_df: pd.DataFrame,
    composite_factor: pd.Series,
    top_n: int,
    n_features: int,          # top N 特征数 (默认 10)
    train_window: int,        # walk-forward 训练窗口 (默认 120 天)
    min_oos_auc: float,       # OOS AUC 门槛 (默认 0.55)
    filter_quantile: float,   # 排除底 N% (默认 0.3)
    logger: logging.Logger | None = None,
) -> tuple[LogisticRegression | None, StandardScaler | None, list[str], float]:
    """每次运行时训练 LR + walk-forward OOS 验证."""

def apply_lr_filter(
    bottom_stocks: list[dict[str, Any]],
    factor_df: pd.DataFrame,
    top_n: int,
    model: LogisticRegression,
    scaler: StandardScaler,
    selected_features: list[str],
    filter_quantile: float,
    logger: logging.Logger | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """LR 模型打分, 排除预测 T+1 跌概率最高的."""
```

**逻辑**:
1. `_discover_features`: 按 T+1 涨跌分组, 计算每个特征 Cohen's d, 选 top N
2. `calibrate_lr_filter`: walk-forward 120 天训练验证 OOS AUC > 0.55, 通过则全样本训练最终模型
3. `apply_lr_filter`: 对当日 Bottom30 打分 (proba_up), 排除底 30%, 递补标记 lr_warning
4. 重新编号 rank

**输入**: `bottom_stocks` = composite 升序最低 30 只（现有 `stage1_bottom_snapshot`）
**输出**: (filtered_stocks, excluded_count)

### 2. 修改 `select_stocks` 主流程

**当前流程** (行 1481-1589):
```
Stage 1: composite Top 200 → stage1_top_snapshot (30)
Stage 2: turnover 升序 → stage2_top_snapshot (30)  
Stage 3: 企稳过滤 → top_stocks (30) → 决策卡片
Bottom30: 只读快照 → stage1_bottom_snapshot (30)
```

**改动后流程**:
```
Stage 1: composite Top 200 → stage1_top_snapshot (30) [保留, 不再输出到报告]
Stage 2: 不再执行 [跳过 apply_stage2_resort]
Stage 3: 不再执行 [跳过 apply_stabilization_filter]
Bottom30: composite 升序取最低 30 → apply_overheat_filter → bottom_filtered (≤30) → 决策卡片
```

**关键变更点**:
- `enable_two_stage` 仍保留为 True（Stage 1 候选池逻辑不变）
- 跳过 Stage 2/3 的调用
- Bottom30 从只读快照升级为过滤后短名单
- 决策卡片应用于 Bottom30 过滤后的结果

### 3. 决策卡片字段调整

**当前 D1-D5 面向弱势股企稳**:
- D1: 跌幅档/振幅档/区间位置
- D2: 深跌/低流动性/极端振幅
- D3: 企稳信号（缩量/背离/下影线）
- D4: 历史画像（占位）
- D5: 人工核查清单

**改为面向强势股过热**:
- D1: 涨幅档/振幅档/区间位置（return_5d 分桶改为正向）
- D2: 过热风险（高换手/放量/高振幅）
- D3: 趋势确认（近高比例/布林上轨/RSI 超买）— 数据显示这些是正向信号
- D4: 历史画像（占位，不变）
- D5: 人工核查清单（不变）

### 4. Parquet 存储调整

**当前 stage 编号**:
- stage=1: Stage 1 Top 30
- stage=2: Stage 2 Top 30
- stage=3: Stage 3 Top 30 (最终短名单)
- stage=4: Bottom 30 (只读快照)

**改动后**:
- stage=1: Stage 1 Top 30 (保留, 候选池快照)
- stage=4: Bottom 30 过热过滤前 (原始快照)
- stage=5: Bottom 30 过热过滤后 (最终短名单, 含决策卡片)
- stage=2/3: 不再写入

**write_selection_history 参数调整**:
- `stage2_top` 参数: 传 []
- `stage3_top` 参数: 传 [] (不再有企稳过滤后的 Top30)
- 新增 `bottom_filtered` 参数: Bottom30 过热过滤后的最终短名单
- `stage1_bottom` 含义不变: 仍为过热过滤前的原始 Bottom30 快照

### 5. summary 报告格式调整

**删除**:
- Stage 2 简表（turnover 升序 Top 30）
- Stage 3 标题和说明
- Top30 详表/简表/决策卡片块

**保留**:
- Stage 1 简表（composite 降序 Top 30）— 改为"候选池"定位
- Bottom 30 原始快照简表

**新增**:
- Bottom30 过热过滤后短名单详表（Top 10 详表 + 11~N 简表）
- Bottom30 决策卡片块（D1 涨幅档/D2 过热风险/D3 趋势确认）
- 过热过滤统计行（排除 N 只过热股）

### 6. 配置参数

新增 `StockSelectorConfig` 字段:
```python
# Bottom30 过热过滤参数
enable_overheat_filter: bool = True
overheat_turnover_percentile: float = 0.7
overheat_volume_ratio_threshold: float = 1.5
```

## Don't

- ❌ 不要删除 `apply_stabilization_filter` 和 `apply_stage2_resort` 函数本身——它们是已验证的逻辑，只是不再被调用。未来可能复用。
- ❌ 不要删除 Stage 1 逻辑——composite 排序和候选池仍是基础设施。
- ❌ 不要给过热阈值使用硬编码绝对值（如 turnover_rate > 5%）——必须用截面分位，适应牛熊市场差异。
- ❌ 不要把 Bottom30 过热过滤和 Top30 企稳过滤同时输出到报告——用户明确要求只输出 Bottom30。

## Why

1. **数据驱动**: 过热信号 p < 0.0001，效果远超企稳信号（企稳信号在 Layer 5 内部差异仅 0.064%/天，且方向反了）
2. **战略目标对齐**: Bottom30 未过热的强势股 T+1 = +0.55%/天，作为短名单候选比 Top30 弱势股企稳后的表现更好
3. **简化系统**: 移除 Stage 2/3 的复杂重排+过滤逻辑，用单一过热过滤替代

## Verify

1. `pytest comprehensive_factor/test_cases/ -v` — 现有测试不破坏
2. 运行 `python -m comprehensive_factor.stock_selector` — 生成新格式 Parquet
3. 运行 `python -m summary.generate_factor_summary_report` — 报告输出 Bottom30 过热过滤后短名单
4. 检查 Parquet schema: stage=1/4/5 三段，stage=2/3 不再出现
5. `ruff check . && ruff format .` — 代码风格
6. `mypy comprehensive_factor/stock_selector.py summary/generate_factor_summary_report.py` — 类型检查
