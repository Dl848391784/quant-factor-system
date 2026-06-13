# Design: 方向性因子（Directional Factors）

> 遵循 AGENTS.md Design-First 流程：涉及 2+ 文件改动，必须先提交 design.md 通过审核才能动手。

---

## 1. 需求概述

**问题根因**（Pitfall #55/60）：8个选中因子全部IC<0（均值回归因子），综合因子偏好"极端弱势"股票（低振幅+低换手+弱动量=闷跌股）。IC和分层回测说的"做多盈利"只是"比高振幅股跌得更少"，不是绝对正收益。

**解决方案**：补充方向性因子——IC正向时偏好强势上升股，与现有均值回归因子形成维度互补。即使IC为负（均值回归主导），方向性因子仍提供不同维度的信息。

**遵循 H5**：IC方向不预判，由数据决定。

---

## 2. 因子定义

| # | 因子名 | 公式 | 含义 | required_cols | 边界处理 |
|---|--------|------|------|--------------|---------|
| 1 | volume_price_strength | sign(close-open)/open × turnover_surge | 量价齐升：上涨+放量=强势，下跌+放量=弱势 | open, close, turnover_surge | open=0→NaN; turnover_surge=NaN→NaN |
| 2 | positive_day_ratio_5 | count(close>prev_close, 5日)/5 | 近5日阳线比例：持续上涨=上升趋势 | date, asset, close | 前4日无完整窗口→NaN; 全NaN→NaN |
| 3 | ma5_deviation | (close - MA5) / MA5 | 5日均线偏离度：在均线之上=多头 | date, asset, close | 前4日→NaN; MA5=0→NaN; clip极端值 |
| 4 | near_high_ratio_5 | (close-min(close,5))/(max(close,5)-min(close,5)) | 近5日高低位置：接近高点=强势 | date, asset, close | 前4日→NaN; max=min(一字板)→position=1.0 |

---

## 3. 核心计算逻辑

### 3.1 volume_price_strength

```python
def calculate_volume_price_strength(factor_df, *, logger_arg=None):
    intraday_return = (factor_df["close"] - factor_df["open"]) / factor_df["open"]
    # open=0 时 intraday_return 为 inf/NaN → clip
    result = intraday_return * factor_df["turnover_surge"]
    # 比率型因子：intraday_return 可极端 → Winsorize ±3σ 后续处理
    factor_df["volume_price_strength"] = result
    factor_df["volume_price_strength"].attrs["required_cols"] = ["open", "close", "turnover_surge"]
    return factor_df
```

### 3.2 positive_day_ratio_5

```python
def calculate_positive_day_ratio_5(factor_df, *, logger_arg=None):
    # 按asset分组，rolling 5日窗口计算阳线比例
    daily_return = factor_df.groupby("asset")["close"].diff()
    positive_mask = (daily_return > 0).astype(float)
    ratio = positive_mask.groupby(factor_df["asset"]).rolling(5, min_periods=5).mean().reset_index(level=0, drop=True)
    factor_df["positive_day_ratio_5"] = ratio
    return factor_df
```

### 3.3 ma5_deviation

```python
def calculate_ma5_deviation(factor_df, *, logger_arg=None):
    ma5 = factor_df.groupby("asset")["close"].rolling(5, min_periods=5).mean().reset_index(level=0, drop=True)
    deviation = (factor_df["close"] - ma5) / ma5.replace(0, np.nan)
    # clip极端值（比率型因子分母趋近零保护）
    factor_df["ma5_deviation"] = deviation
    return factor_df
```

### 3.4 near_high_ratio_5

```python
def calculate_near_high_ratio_5(factor_df, *, logger_arg=None):
    roll_max = factor_df.groupby("asset")["close"].rolling(5, min_periods=5).max().reset_index(level=0, drop=True)
    roll_min = factor_df.groupby("asset")["close"].rolling(5, min_periods=5).min().reset_index(level=0, drop=True)
    diff = roll_max - roll_min
    # 涨跌停一字板：diff=0 → position=1.0（收盘价在区间最高点=最强）
    position = np.where(diff == 0, 1.0, (factor_df["close"] - roll_min) / diff)
    factor_df["near_high_ratio_5"] = position
    return factor_df
```

---

## 4. 文件修改清单

| Phase | 文件 | 位置 | 修改内容 |
|-------|------|------|---------|
| 1 | `factor_calculator.py` | 函数区+常量区+__all__ | 新增4个calculate函数+4个_COL常量 |
| 1 | `factor_generator.py` | `_EXTENDED_FACTOR_COLS` | 添加4个新列名 |
| 1 | `factor_generator.py` | 导入区 | 添加4个导入 |
| 1 | `factor_generator.py` | Step区 | 添加Step计算 |
| 1 | `factor_generator.py` | metadata | valid_records |
| 1 | `factor_generator.py` | 版本历史 | v1.41 |
| 2 | `factor_ic/ic_volume_price_strength_1d.py` | 新建 | IC脚本 |
| 2 | `factor_ic/ic_positive_day_ratio_5_1d.py` | 新建 | IC脚本 |
| 2 | `factor_ic/ic_ma5_deviation_1d.py` | 新建 | IC脚本 |
| 2 | `factor_ic/ic_near_high_ratio_5_1d.py` | 新建 | IC脚本 |
| 3 | `backtest/layered_backtest_*_1d.py` | 新建（仅IC显著因子） | 薄声明Config类 |
| 4 | `factor_selector.py` | FACTOR_NAME_TO_COL_MAP | 添加4映射（数据源已有列） |
| 4 | `factor_definitions.py` | FACTOR_DEFINITIONS | 添加4定义 |
| 4 | `weight_engine.py` | 不修改（复杂因子不加映射） | — |
| 5 | `run_pipeline.py` | STAGE_2/3 | 添加新脚本 |
| 5 | `generate_factor_summary_report.py` | 映射+缩写 | 添加4因子 |

---

## 5. 验证检查清单

- [ ] factor_generator.py 运行成功，新因子列存在且非全NaN
- [ ] 4个IC脚本运行成功，IC结果有值
- [ ] IC不显著因子淘汰（Phase 2.6关键筛选节点）
- [ ] 仅IC显著因子开发回测脚本
- [ ] 综合因子脚本识别新因子
- [ ] 选股结果改善（不再偏好闷跌股）
- [ ] ruff check/format 通过
- [ ] pytest 通过（新增代码不引入新failure）

---

## 6. 关键设计决策

1. **遵循 H5**：IC方向不预判。方向性因子可能IC为正（趋势延续）或IC为负（均值回归），两种都有价值
2. **比率型因子保护**：volume_price_strength 和 ma5_deviation 分母可能趋近零，需 clip/NaN 保护（遵循 Pitfall #47）
3. **一字板处理**：near_high_ratio_5 遵循 Pitfall #45 的处理逻辑——涨跌停时 max=min → position=1.0（最强信号）
4. **rolling窗口最小天数**：min_periods=5，前4天不产生有效值（NaN自然排除）
5. **factor_cols参数**：volume_price_strength需要 open+close+turnover_surge（简单列）；其他3个需要 date+asset+close（用于groupby+rolling）