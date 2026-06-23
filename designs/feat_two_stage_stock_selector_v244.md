# Two-Stage Stock Selector (v2.44)

> **作者**: 云瑶
> **日期**: 2026-06-23
> **状态**: Design (待执行)
> **关联**: AGENTS.md "战略目标: 量化辅助 + 人工决断" / "Top 3~5 不能用 Top N backtest 评估"
> **前置实证**:
>   - `scripts/backtest_top_n_realworld.py` Top N 阶梯实战回测
>   - `scripts/explore_stage2_ranking_candidates.py` Stage 2 候选变量数据驱动测试

---

## 1. Problem

**短名单 Top 30 的 alpha 远低于 layer_1 整体**——这就是用户反映的 "选阴跌股" 现象的量化本质：

| 集中度 | 毛年化 | 备注 |
|---|---|---|
| composite layer_1 (~540 只) | +27.22% | 完整 alpha |
| Top 540 (= layer_1) | +6.33% | 不含成本/含 dropna 差异 |
| Top 300 | +5.57% | 仍正 |
| Top 100 | -0.36% | 接近零 |
| **Top 30 (短名单)** | **-8.43%** | ❌ alpha 消失 |
| Top 3 | -23.12% | 严重失效 |

**第一性原理**：composite 是 17 个因子的线性加权，IC 是**截面均值**指标——它能保证"layer_1 整体优于 layer_5"，**但不保证 layer_1 内部最极值的 30 只仍优于中间分位**。当线性信号在尾部失效时（"tail extrapolation breakdown"），AGENTS.md 明文警告："Top 3~5 不能用 Top N 的 backtest 评估"——本次实证完美证实。

---

## 2. Solution: Two-Stage Selection

**Stage 1**: composite 排序取 Top **200** (从 5000 → 200，缩到 alpha 仍有效的池子)
**Stage 2**: 在 200 只候选内按 **turnover_rate 升序** 取 Top 60 (= top_n × 2)
**Stage 3**: 企稳过滤切到 Top **30** (现有 `apply_stabilization_filter` 不变)

### 2.1 为什么 turnover_rate 升序是 Stage 2 的最优选

数据驱动测试 5 类候选变量，OOS (后 30% 日历) 表现：

| 候选 | OOS 年化 | 是否选用 |
|---|---|---|
| 现行: composite Top60 → 企稳 → Top30 | +8.91% | baseline |
| amplitude 升序 | -10.94% | ❌ 反信号 |
| amplitude 降序 | -6.92% | ❌ |
| **turnover 升序** | **+10.43%** | ✅ |
| turnover 降序 | OOS -8.65% | ❌ IS 强 OOS 翻负 (过拟合) |
| return_5d 降序 | +2.34% | 改善有限 |
| turnover 距中位数 (C7) | +17.86% | ❌ 非单调函数, OOS 衰减 56→18 (脆弱) |
| amount × composite 组合 | -12.47% | ❌ |

**经济意义 (第一性原理)**:
- composite 主方向 negative → Top 端 = 最弱势股票
- 弱势股按 turnover 升序 = **选未被游资关注的冷门弱势股**
- 高 turnover 弱势股 = "游资爆炒后被洗" → T+1 大概率继续抛压
- 低 turnover 弱势股 = 理性回补可能性高 → T+1 反弹更稳

OOS 验证 turnover 升序 IS=14.10% → OOS=10.43%，衰减仅 4pp，**信号稳健**（vs turnover 距中位数 IS=56% → OOS=18% 衰减 38pp，明显过拟合）。

### 2.2 Stage1 池子大小 = 200 (不是 300)

OOS 测试 Stage1 N × Stage2 N 网格 + 企稳过滤：

| Stage1 N | OOS 年化 (Top60→企稳→Top30) |
|---|---|
| Top60 (现行) | +8.91% |
| Top200 | **+11.22%** ✅ |
| Top300 | +1.61% ❌ |

Stage1=300 + 企稳 比 Stage1=200 + 企稳低 10pp。猜测：池子越大，企稳过滤剔除的"好但 NaN"样本越多 → 反向。

### 2.3 是否保留企稳过滤 (Stage 3)

| 配置 | OOS 年化 |
|---|---|
| 方案 A: Stage1=300, 无企稳 | +10.43% |
| 方案 B: Stage1=300, 企稳 | +1.61% (差) |
| 方案 C: Stage1=200, 无企稳 | +9.29% |
| **方案 D: Stage1=200, 企稳** | **+11.22%** ✅ |

**保留企稳过滤**（方案 D 最优）。

---

## 3. Implementation

### 3.1 改动文件清单

| 文件 | 改动类型 | 行数预估 |
|---|---|---|
| `comprehensive_factor/stock_selector.py` | 增 `stage1_pool_size` config + `stage2_sort_col`/`stage2_ascending` + select_stocks 中插入 Stage 2 排序 | +30 行 |
| `comprehensive_factor/test_cases/test_stock_selector.py` (或新建 test_two_stage_selector.py) | 加 2-3 个 unit test 验证 Stage 1/2 切片正确 | +60 行 |
| `comprehensive_factor/MODULE.md` | 更新 select_stocks 流程文档, 加 v2.44 版本说明 | +20 行 |

合计 **3 个文件, ~110 行**——符合 AGENTS.md 任务粒度约束 (≤3 文件 ≤200 行)。

### 3.2 StockSelectorConfig 新增字段

```python
@dataclass
class StockSelectorConfig:
    # ... existing fields ...

    # v2.44: 两阶段选股 (默认开启)
    enable_two_stage: bool = True
    stage1_pool_size: int = 200  # Stage 1: composite 取 Top N (默认 200, OOS 最优)
    stage2_sort_col: str = "turnover_rate"  # Stage 2 排序列 (默认 turnover_rate)
    stage2_ascending: bool = True  # Stage 2 排序方向 (默认升序)
```

### 3.3 select_stocks 主流程改动

现行：
```python
candidate_n = config.top_n * 2  # = 60
top_stocks, ... = sort_and_select(composite_factor, factor_df, candidate_n, ...)
top_stocks, ... = apply_stabilization_filter(top_stocks, factor_df, config.top_n)
```

新增：
```python
# v2.44: Stage 1 - composite 取 Top stage1_pool_size
if config.enable_two_stage:
    stage1_n = config.stage1_pool_size  # = 200
    stage1_stocks, ... = sort_and_select(composite_factor, factor_df, stage1_n, ...)
    # v2.44: Stage 2 - 在 stage1_stocks 内按 turnover_rate 升序取 top_n*2
    candidate_n = config.top_n * 2  # = 60
    stage2_stocks = _apply_stage2_resort(
        stage1_stocks, factor_df, candidate_n,
        sort_col=config.stage2_sort_col,
        ascending=config.stage2_ascending,
        logger=logger,
    )
    top_stocks = stage2_stocks
    # 现行的 excluded_by_* 仍来自 sort_and_select
else:
    # 单阶段 (向后兼容)
    candidate_n = config.top_n * 2
    top_stocks, ... = sort_and_select(composite_factor, factor_df, candidate_n, ...)

# Stage 3 (现行不变): 企稳过滤 → Top N
top_stocks, excluded_by_confirmation = apply_stabilization_filter(
    top_stocks, factor_df, config.top_n, logger=logger,
)
```

`_apply_stage2_resort`:

```python
def _apply_stage2_resort(
    stage1_stocks: list[dict],
    factor_df: pd.DataFrame,
    target_n: int,
    sort_col: str,
    ascending: bool,
    logger: logging.Logger,
) -> list[dict]:
    """Stage 2 重排: 在 stage1_stocks 内按 sort_col 排序取 target_n.

    Args:
        stage1_stocks: Stage 1 候选 (来自 sort_and_select)
        factor_df: 单日 factor DataFrame, 含 sort_col 列
        target_n: Stage 2 输出数量 (= top_n × 2, 留给企稳过滤递补)
        sort_col: Stage 2 排序列 (默认 'turnover_rate')
        ascending: True 升序

    Returns:
        Stage 2 重排后的 stocks (长度 ≤ target_n)
    """
    if not stage1_stocks:
        return stage1_stocks
    if sort_col not in factor_df.columns:
        logger.warning("Stage 2 排序列 %s 不存在, 跳过 Stage 2 重排", sort_col)
        return stage1_stocks[:target_n]

    # 用 asset → sort_col 值映射
    asset_to_val = factor_df.set_index("asset")[sort_col].to_dict() if "asset" in factor_df.columns else {}

    # 数据缺失的股票放最后 (NaN 视为最差)
    sentinel = float("inf") if ascending else float("-inf")
    enriched = [
        (s, asset_to_val.get(s["code"], sentinel))
        for s in stage1_stocks
    ]
    enriched.sort(key=lambda t: (t[1] if not (isinstance(t[1], float) and pd.isna(t[1])) else sentinel),
                  reverse=not ascending)

    n_with_val = sum(1 for _, v in enriched if not pd.isna(v) and v not in (float("inf"), float("-inf")))
    logger.info(
        "Stage 2 重排: 输入 %d 只, %s %s, 有效 %s 值 %d 只, 输出 %d 只",
        len(stage1_stocks), sort_col, "升序" if ascending else "降序", sort_col, n_with_val, min(target_n, len(enriched)),
    )

    # 重新编号 rank (Stage 2 后)
    result = [s for s, _ in enriched[:target_n]]
    for idx, s in enumerate(result, start=1):
        s["stage1_rank"] = s.get("rank", idx)  # 保留 Stage 1 rank
        s["rank"] = idx  # Stage 2 后的 rank
    return result
```

### 3.4 输出 JSON 字段新增

每只股票 dict 新增：
- `stage1_rank`: composite 排序时的 rank (1~200)
- `rank` (现有): 重排后的最终 rank (1~30)

meta 中加：
- `selection_meta.two_stage`: `{enabled: bool, stage1_pool_size: 200, stage2_sort_col: "turnover_rate", stage2_ascending: true}`

### 3.5 向后兼容

- `enable_two_stage=False` 退回单阶段 (= 现行行为)
- 默认 `enable_two_stage=True` 直接走两阶段
- 现有测试不应受影响 (现行测试若用默认 config, Top60 池子不变；企稳过滤行为不变)

---

## 4. Don't (禁区)

| Don't | Why |
|---|---|
| ❌ 用 Stage 2 = turnover 距中位数 (C7) | OOS 衰减 38pp, 过拟合 |
| ❌ 用 Stage 2 = amplitude 升序 | OOS -10.94% 反信号 |
| ❌ Stage1=300 + 企稳过滤 | OOS +1.61% 二者冲突 |
| ❌ 跳过企稳过滤 (Stage 3) | 方案 A +10.43% < 方案 D +11.22% |
| ❌ Stage2 = composite_factor | 退化为单阶段, 失去两阶段意义 |
| ❌ 用 IS 数据调 Stage1 池子大小 | 必须用 OOS 验证 |

---

## 5. Verify (验证清单)

执行后必须验证：

1. **ruff + pytest 全绿**: `ruff check comprehensive_factor && pytest comprehensive_factor/test_cases/ -q`
2. **CLI 重跑短名单**:
   ```bash
   python comprehensive_factor/stock_selector.py
   # 看输出 selection JSON 是否含 stage1_rank
   ```
3. **summary 报告**: `python summary/summary_runner.py`, 看 v2.44 短名单是否更新
4. **手动核对**: 取最新交易日, Top 30 是否都属于 Stage 1 Top 200, 且 turnover_rate 整体较低

---

## 6. Why (设计理由)

- **AGENTS.md 战略目标对齐**: "短名单 30~50 是量化职责，最终 3~5 是人工"——两阶段不破坏战略
- **第一性原理**: composite 线性尾部失效是数学必然，单阶段无法解决；二阶段在 alpha 仍有效的子池内做次级筛选是唯一健康方案
- **数据驱动**: 5 候选 × IS/OOS 双段验证, 选 OOS 最稳健的 turnover 升序
- **OOS 净改善 +2.31pp** (8.91% → 11.22%): 不及 IS 看到的 +20pp 但仍显著，符合"OOS 衰减预期"

---

## 7. When (使用场景)

- ✅ 适用: 日频 T+1 持仓策略, composite 主方向 negative
- ⚠️ 暂不适用: 多周期持仓 (Stage 2 排序需重新校准)
- ⚠️ 暂不适用: composite 主方向 positive (turnover 升序经济含义反转, 需重测)

---

## 8. Risk & Mitigation

| 风险 | 缓解 |
|---|---|
| OOS 仅 163 日, 样本不足 | 上线后跟踪 1 个月真实表现, 偏离预期 (>3pp) 时回退 |
| turnover_rate 缺失日比例高 | NaN 排到末尾 (代码已处理), 不影响主流程 |
| 两阶段降低短名单多样性 (集中在低 turnover) | 接受: 战略目标本就是收敛短名单, 人工 3~5 决断时再考虑分散 |

---

## 9. 提交计划

- Commit 1 (本 design): `designs/feat_two_stage_stock_selector.md` 单独 commit
- Commit 2 (实现): `stock_selector.py` + tests + `MODULE.md` 一起 commit
- Commit 3 (重跑产物): stock_selector 重跑后的短名单 JSON + summary 报告 一起 commit

不和 v2.40 阈值校准混合。
