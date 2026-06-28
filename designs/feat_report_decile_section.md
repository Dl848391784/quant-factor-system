# 报告新增十分位分段胜率（D1-D10）

> **目标:** 在 summary 报告的"股票选股结果"后面追加"D1-D10 十分位分段胜率"表格, 包含胜率/均收/盈亏比/涨跌数.
> 纯展示增强, 不改选股逻辑.

**版本:** v1.0  
**创建:** 2026-06-29  
**作者:** 云瑶

---

## 改动范围

| # | 文件 | 改动 | 行数 |
|---|------|------|:---:|
| 1 | `summary/report/constants.py` | 加 `FACTOR_IC_DATA_MASTER` 导入 | +1 |
| 2 | `summary/report/data_loaders.py` | 新增 `load_decile_stats()` 函数 | +50 |
| 3 | `summary/report/sections.py` | 在 `_generate_stock_selection_section` 尾部追加 D1-D10 表格 | +35 |
| 4 | `summary/test_cases/test_generate_factor_summary_report.py` | 新增测试 | +30 |

总改动: **4 文件, ~115 行**

---

## 设计决策

### D1-D10 划分

```
composite_factor 降序排名 → pd.qcut(10 等份) → D1(Top10%)...D10(Bot10%)
```

- D1 = composite 最高的 10%, D10 = composite 最低的 10%
- 每段等量（±1 只），非固定阈值
- 仅对最新选股日计算（单日截面），不做跨日合并

### T-1 对齐

composite[D] 的实战收益是 forward_return_1d[D+1]（T日尾盘买→T+1日尾盘卖）：

```
1. 从 composite daily parquet 取 date=D 的 composite_factor
2. 从主数据源 FACTOR_IC_DATA_MASTER 取 date=D+1 的 forward_return_1d
3. 按 code merge → 按 composite 排名 qcut(10) → 每段算胜率
```

`D+1` 通过 `FACTOR_IC_DATA_MASTER` 中查找选股日的下一个交易日实现。

### Why FACTOR_IC_DATA_MASTER 而非 pipeline 子集

pipeline 子集（如 ob_quality_0624）数据截止到 D，不含 D+1 的 forward_return_1d。主数据源包含最新全量数据，有 D+1 收益。

### 降级策略

- 主数据源无 D+1 数据 → 跳过此段（如最新日选股，T+1 尚未发生）
- composite daily 不存在 → 跳过
- 股票 < 20 只 → 不分段（qcut 需要足够样本）

---

## 实现细节

### 1. `constants.py`

```python
from paths import FACTOR_IC_DATA_MASTER  # 新增
```

### 2. `data_loaders.py` — `load_decile_stats()`

```python
def load_decile_stats(
    weight_method: str,
    selection_date: str,
    logger: logging.Logger,
    n_segments: int = 10,
) -> dict | None:
```

**流程:**
1. 读 composite daily parquet → 取 selection_date 行 → composite 降序
2. 读 FACTOR_IC_DATA_MASTER → 找 selection_date 的下一个交易日 next_date
3. 取 master[next_date] 的 forward_return_1d
4. merge → qcut(rank, n_segments) → 每段统计

**返回:**
```python
{
    "selection_date": "2026-06-24",
    "trade_date": "2026-06-25",      # T+1 交易日
    "n_total": 129,
    "segments": [
        {"label": "D1", "n": 13, "win_rate": 15.4, "avg_ret": -4.17, 
         "pl_ratio": 0.45, "wins": 2, "losses": 11},
        ...
    ]
}
```

### 3. `sections.py` — 追加表格

在全量展示尾部 (`lines.append("")` 之后, 最终短名单之前) 插入:

```
【十分位分段胜率 (composite 降序, T+1 收益)】
选股日: 2026-06-24, 交易验证日: 2026-06-25
  段     N    胜率     均收     盈亏比   涨:跌
--------------------------------------------------
 D1     13   15.4%   -4.17%    0.45    2:11
 D2     13   23.1%   -3.31%    0.62    3:10
 ...
 D3     13   15.4%   -4.17%    0.45    2:11   <-- 最佳段
 D10    13   38.5%   +0.14%    1.32    5:8
--------------------------------------------------
```

### 4. 测试

- mock FACTOR_IC_DATA_MASTER 路径, 验证 load_decile_stats 返回结构
- 验证 10 段每段 N 正确
- 验证降级（无 T+1 数据 → None）

---

## 不在此次改动

- ❌ 不改选股逻辑
- ❌ 不做跨日合并（每天独立 10 段）
- ❌ 不把分段分析写回 stock_selector（那是运行时的增强, 这是报告的展示）
- ❌ 不做高开/低开日内策略分析（那是分析脚本的事, 不适合硬编码进报告生成器）

---

## 验证清单

- [ ] ruff check
- [ ] pytest
- [ ] 手工跑一条 ob_quality 管线确认报告新增了分段表
- [ ] git commit
