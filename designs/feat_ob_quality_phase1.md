# ob_quality Pipeline — Phase 1: 换手率过滤

> 路径A第一波：超买股 + 高流动性 → 验证胜率提升假设
> 后续Phase 2: 行业过滤 / Phase 3: 市值过滤

**Goal:** 新建 `ob_quality` 管线（RSI>70 + turnover_rate>5%），含7条时间递减验证管线，纯配置驱动零代码改动。

**Architecture:** 复用现有 pipeline 全链路（slicer → IC → 回测 → composite → 选股 → 报告），仅通过 pipelines.yaml 新增 filter 表达式。PIPELINE_ALIAS 环境变量自动隔离所有产出物到 `result/ob_quality/` 下。

**Tech Stack:** pandas query 表达式 / parquet / YAML 配置

---

## 改动范围

| 文件 | 改动 | 原因 |
|------|------|------|
| `pipelines/pipelines.yaml` | 新增 8 条 pipeline 定义 | 1条日常 + 7条时间递减 |
| （零代码改动） | — | slicer/IC/回测/composite/选股全链路不变 |

---

## Pipeline 定义

### 日常管线（最新数据全量）

```yaml
ob_quality:
  filter: "rsi_6 > 70 and turnover_rate > 5"
  description: "超买股 × 高换手率 (>5%)，路径A第一波——验证流动性溢价假设"
```

### 时间递减验证管线（仿 temp_history 模式）

| 管线 | filter | 验证日 (T-1选→T买→T+1卖) |
|------|--------|------|
| `ob_quality_0624` | `rsi_6>70 & turnover>5 & date<='2026-06-24'` | 06-24选→06-25买→06-26卖 |
| `ob_quality_0623` | `rsi_6>70 & turnover>5 & date<='2026-06-23'` | 06-23选→06-24买→06-25卖 |
| `ob_quality_0622` | `rsi_6>70 & turnover>5 & date<='2026-06-22'` | 06-22选→06-23买→06-24卖 |
| `ob_quality_0618` | `rsi_6>70 & turnover>5 & date<='2026-06-18'` | 06-18选→06-22买→06-23卖 |
| `ob_quality_0617` | `rsi_6>70 & turnover>5 & date<='2026-06-17'` | 06-17选→06-18买→06-19卖 |
| `ob_quality_0616` | `rsi_6>70 & turnover>5 & date<='2026-06-16'` | 06-16选→06-17买→06-18卖 |
| `ob_quality_0615` | `rsi_6>70 & turnover>5 & date<='2026-06-15'` | 06-15选→06-16买→06-17卖 |

> 注：不设 `ob_quality_0627`（日常管线已覆盖最新日期），日期序列对齐 temp_history 方便交叉对比。

---

## 验证计划

```bash
# 批量跑全部 ob_quality 时间递减管线（Stage 2-7）
for alias in ob_quality_0624 ob_quality_0623 ob_quality_0622 \
             ob_quality_0618 ob_quality_0617 ob_quality_0616 ob_quality_0615; do
    python3 run_pipeline.py --pipeline $alias --start-stage 2
done
```

用户跑完后我会读取各管线报告，提取 Top30 胜率，与 ob_pool 同日期对比。

---

## 后续 Phase 规划

| Phase | 新增维度 | 需要代码改动 | 预计日期 |
|-------|---------|:---:|------|
| Phase 1 (本次) | turnover_rate > 5% | ❌ | 2026-06-28 |
| Phase 2 | + 行业过滤（半导体等） | ✅ (factor_generator 加 industry 列) | TBD |
| Phase 3 | + 市值过滤 (100-500亿) | ✅ (factor_generator 加 market_cap 列) | TBD |

---

## 对比基线

| 管线 | 胜率(baseline) | 候选池(日均) | 说明 |
|------|:---:|---:|------|
| ob_pool | ~45% (compBot) | 200-300 | RSI>70 全量 |
| ob_quality | **待验证** | **50-80** | RSI>70 + turnover>5% |

---

**Design status:** verified ✅
**版本:** v1.0
**创建:** 2026-06-28
**作者:** 云瑶
