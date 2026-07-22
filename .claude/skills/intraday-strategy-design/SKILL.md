---
name: intraday-strategy-design
description: A 股 T+1 实战日内操作策略（开盘/反抽/止损三档信号 + β暴露误诊 + 连选前视偏差 + Day1三层过滤）。
version: 1.0
---

# intraday-strategy-design

> 自包含方法论要点。

## Overview
T-1 数据 -> T 日 09:25 算选股 -> T 日尾盘买入 -> **T+1 日卖出**。
日期语义权威定义 = PROJECT.md §核心数据契约，本 skill 不重复。

## ⚠️ β 暴露误诊反模式
**触发**：用户问"加稳因子 / 加低 β / 抗跌因子能让信号涨时涨、跌时也有胜率吗"。
**错误**：直接按诉求加因子。
**正确**：先用数据反驳--①看 segment 跨市场方向表现（跌日仍 65~70% 胜率说明已有 α）；②看"所有 segment 同步失守日"占比（市场系统性风险，非因子问题）；③算样本显著性（<60 天任何结论都不显著）。

## ⚠️ 连选前视偏差反模式
**触发**："连续入选的股票收益""Day 2 确认连选后买入""预测到 3d"。
**错误**：按 streak 最终长度分组算入场收益（用了未来信息）。
**正确**：只用入场时刻可知的信息。Day 2 入场无偏收益 **-0.66%**（全部 2 天 streak），不是 +1.59%（仅 3+ 天）。
**自检**：按 streak 长度分组算收益时问"这个分组条件入场时刻可知吗？"

**Day 1 无偏筛选组合**：`past_return_1d<0` + `turnover≥10%` + 当日候选池≥80 -> +1.95%, 胜率 64.7%, n=51。**breadth（候选池≥80）是 P0 一票否决**--breadth<80 时即使另两个满足 avg=-3.12%（比基线还差）。

## 核心三档信号
> ⚠️ 下方"实证"是 8 天 31 只样本快照，扩到 6 天 46 只后多组方向反转。实战以 `factor-summary-reporting` 报告 §10 数据驱动统计为准，**不依赖此顶部数字**。

- **信号1 高开(gap>+0.5%)**：T+1 09:25 集合竞价直接卖。新样本 +1.94%（相对死等尾盘少赚 1.86pp）。
- **信号2 低开(gap<-0.5%)**：不在 09:25 卖，等盘中反弹到买入成本价出手。新样本 5/24=20.8% 命中回本，等高卖均收 -2.80%（**反亏 1.19pp**）。止损线=`prev_close×0.98`（9:50 前必出）。
- **信号3 复权异常(|gap|>10%)**：标记 monitor，不自动建议，⚠️ 明示警告不静默剔除。

**双向 wording**：edge 必双向（"减亏 +X" / "反亏 -X"），不能写死"减亏"。

## 关键陷阱：反推前收 vs 真实前收
- ❌ `prev_close = close[D+1] / (1 + forward_return_1d[D+1])`（复权失真，001339 真实 gap=-1.19% 反推成 -15.12%）
- ✅ 用 T 日真实 `close[T]`：`gap = (open[D+1] - close[T]) / close[T] * 100`
- **invariant**：`assert abs((open[D+1]-close[D])/close[D]*100) < 10.0`（复权异常必出）

## 关键术语精确化
两个"开盘价"含义不同，禁用"开盘价"指代两个锚点：
- 低开等反抽回"开盘价" = **T 日收盘价（买入成本价）** = 出场目标
- 高开 9:25"开盘价"卖 = **T+1 集合竞价成交价**

## ⚠️ forward_return_1d T+1 日期错位（UNFIXED BUG）
`pl_ratio_db.py:148-160` + `generate_factor_summary_report.py:670-676` 从 `trade_date=master_dates[idx+1]` 行读 `forward_return_1d`，但该字段存 D 行（=D->D+1 收益）-> 取到 T+1->T+2。S13 +28% 实际 -24.9%。**影响**：`segment_win_rates.parquet` + WebUI 趋势图 + 复合资产值图全部不可信。验证：取一只股用 close 手算对比存储值。

## ⚠️ 段标签数据驱动，不写死 S6
`compute_intraday_strategy` 加 `segment_label` 参数，调度用 §9 算的 `best_seg`。Parquet schema 加 `segment_label` 列，`save` 去重 key 必含 `segment_label`（否则同 (pipeline,weight_method,date) 不同段互相覆盖）。

## Don't
- ❌ 用 `forward_return_1d` 反推前收（复权失真）
- ❌ 同文档"开盘价"指两个锚点
- ❌ 把反抽当盈利信号（是减亏窗口）
- ❌ §10 失败让整报告崩（try/except 包裹 + fallback）
- ❌ 凭"加稳因子"直觉改 composite（β 误诊，先数据反驳）
- ❌ 按 streak 最终长度分组算入场收益（前视偏差）
- ❌ 候选池<80 强行操作（breadth 是 P0 一票否决）
- ❌ 把连选股纳入 Day1 过滤（Day1=首次入选，须 `is_new_today` 排除连选股）
- ❌ `n_recent_dates=12` 截断趋势数据（应 None=全部）

## Verify
```bash
python3 -m pytest summary/test_cases/test_intraday_strategy.py -v
ruff check summary/report/segment_win_db.py summary/report/sections.py
```
