# Design: 决策卡片 v1（5 维 → 实际 4 维落地）

**作者**: 云瑶
**创建日期**: 2026-06-23
**状态**: Draft → 直接实施（用户已授权）
**前置**: commit 3253c69（Top 30 短名单已落地）
**关联规范**:
- PROJECT.md "战略目标：量化辅助 + 人工决断"
- PROJECT.md "数据驱动原则：禁止给系统贴叙事标签"
- PROJECT.md "实战交易规则：T 日尾盘买入 T+1 日卖出"
- AGENTS.md 规则 #12 Design-First

---

## 1. Why

Top 30 短名单已落地（commit 3253c69），但用户从 30 → 3~5 决断时缺少**正交于 composite 的客观维度**。决策卡片在 composite 之外叠加客观信号，**不替代用户决策**。

## 2. What — 5 维设计 vs 本期落地

| 维度 | 内容 | 数据源 | 本期实现 |
|---|---|---|---|
| **D1 客观分类** | 近 5 日跌幅档位 + 振幅档位 | factor_ic_data.parquet | ✅ |
| **D2 风险标记** | 近 5 日跌幅 / 流动性恶化 / 振幅异常 | factor_ic_data.parquet | ✅ |
| **D3 企稳信号** | volume_shrink / pv_divergence / lower_shadow 命中情况 | stock_selector 已有 | ✅ |
| **D4 历史画像** | 该股过去 N 日进入 Top 30 的次数 / 1d 平均回报 | 需历史 stock_selection 归档 | ❌ 留 null + 说明 |
| **D5 人工核查清单** | 公告/新闻/财报/股东（固定模板） | 固定 | ✅ |

**D4 不在本期**：当前 stock_selection_result.json 是单日文件，无历史。实现 D4 需独立模块（每日归档 30 只 → 累积形成历史画像），是另一个独立 design。本期接口预留 `d4_history` 字段为 `null`，并在报告中明确"需历史归档机制"。

## 3. D1~D5 客观字段定义（无叙事词）

### D1: 客观分类（事实陈述）

```python
@dataclass
class DimD1Classification:
    return_5d_bucket: str   # "深跌(<-15%)" | "中跌(-15~-5%)" | "温和(-5~0%)" | "横盘(0~3%)" | "上涨(>3%)"
    amplitude_bucket: str   # "极低(<2%)" | "低(2~4%)" | "中(4~8%)" | "高(>8%)"
    close_position_5d: str  # 收盘价相对近 5 日 high-low 区间位置: "底部" | "中部" | "顶部"
```

**判定**: 纯阈值, 不带"反弹候选"/"弱势反转"等叙事。

### D2: 风险标记

```python
@dataclass
class DimD2Risk:
    deep_decline_5d: bool      # return_5d < -10%
    low_liquidity: bool        # amount 在当日截面 < 5%
    extreme_amplitude: bool    # amplitude > 12% 或 < 1%（涨停 / 一字板风险）
    warning_count: int         # 上述命中数
```

### D3: 企稳信号

```python
@dataclass
class DimD3Stabilization:
    volume_shrink: bool | None         # volume_shrink_rate < 1.0
    pv_divergence: bool | None         # price_volume_divergence > 0
    lower_shadow: bool | None          # lower_shadow_ratio > 0.3
    hit_count: int                     # 命中数（0~3）
    raw_signals_available: bool        # 三个信号至少 1 个非 NaN
```

### D4: 历史画像（本期 null + 说明）

```python
@dataclass
class DimD4History:
    times_in_top30_last_60d: int | None = None
    avg_1d_return_when_in_top30: float | None = None
    note: str = "需历史归档机制（独立 design 待启动）"
```

### D5: 人工核查清单（固定模板）

```python
CHECKLIST_D5 = [
    "公告: 近 7 日有无重大事项 / 业绩预告 / 商誉减值",
    "新闻: 行业事件 / 政策风险 / 监管问询",
    "财报: 最近季度营收/净利同比 / 现金流",
    "股东: 近期增减持 / 解禁 / 大宗交易",
]
```

不动态调整（避免决策卡片越界给用户"看哪一项"的指引——人工自己判断）。

## 4. How — 模块结构

### 4.1 新建 `comprehensive_factor/decision_card.py`

```
comprehensive_factor/
  decision_card.py          ← 新建 (~250 行)
  stock_selector.py         ← 调用 decision_card.build_cards()
  test_cases/
    test_decision_card.py   ← 新建 (~180 行)
```

**API**:

```python
def build_decision_cards(
    top_stocks: list[dict],   # stock_selector 已选出的 30 只
    factor_df: pd.DataFrame,  # 当日因子+行情 (含 amount/amplitude/return_5d/...)
    logger: logging.Logger | None = None,
) -> list[dict]:
    """为每只股票生成决策卡片 (5 维客观字段).

    返回结构对齐到 stock_selector item:
        {
          "rank": ..., "code": ...,
          "decision_card": {
            "d1_classification": {...},
            "d2_risk": {...},
            "d3_stabilization": {...},
            "d4_history": {...},  # null + note
          }
        }
    """
```

### 4.2 stock_selector 集成

在 `build_result_payload` 之前调用一次 `build_decision_cards(top_stocks, factor_df)`, 把 `decision_card` 字段塞进每个 item。

### 4.3 summary 报告新增"决策卡片"块

Top 30 简表后追加。每只股票一行：

```
【决策卡片 (人工决断辅助)】
排名 股票代码 | D1 客观分类                    | D2 风险数 | D3 企稳数 | D4 历史 | D5 核查
   1 600377  | 跌-7.5% | 振幅 4.2% | 区间底部 | 0         | 2/3       | n/a    | →
   2 001210  | ... 
   ...
说明: D4 历史画像需历史归档机制（待启动独立 design）。D5 人工核查清单为固定模板, 见报告底部。
```

## 5. Don't

| 禁 | 原因 |
|---|---|
| ❌ D1 写"反弹候选" "弱势股" | 违反数据驱动原则 |
| ❌ 决策卡片做 ranking / 打分 | 越界——用户决断, 不是替代 |
| ❌ D5 动态调整内容 | 量化不应指导人工"看哪条" |
| ❌ 用 D4 跑 backtest | 历史画像是辅助维度, 不是策略信号 |
| ❌ 把决策卡片字段塞进 top_stocks 顶层 | 用嵌套 `decision_card` 字段隔离, 不污染原结构 |

## 6. 测试

| 测试 | 验证 |
|---|---|
| test_d1_classification_buckets | 边界值正确分桶 |
| test_d2_risk_warning_count | 命中数计数 |
| test_d3_stabilization_nan_handling | NaN → raw_signals_available=False |
| test_d4_returns_null_with_note | 接口预留正确 |
| test_build_cards_handles_missing_cols | factor_df 缺列时 fail-safe |
| test_card_attached_to_top_stocks | stock_selector 输出 item.decision_card 存在 |
| test_summary_renders_card_block | 报告输出含"决策卡片"标题 |

## 7. 不在本期

- D4 历史画像（独立 design + 历史归档模块）
- 决策卡片打分 / 排序（违反人工决断原则）
- 行业映射（factor_ic_data 无 industry 分类列，只有 industry_* 因子值）
- 市值字段（data_fetchers/result/market_cap_data.json.gz 已采但 stock_selector 未消费，独立 design）

## 8. 实施顺序

1. decision_card.py 模块 + test
2. stock_selector 集成（1 行调用 + 1 处赋值）
3. summary 报告渲染（~50 行新增）
4. 实跑 + commit
