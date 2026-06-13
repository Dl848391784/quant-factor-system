# Design: 行业级别方向性因子（方案A）

> 遵循 AGENTS.md Design-First 流程，涉及 2+ 文件修改，必须先提交设计审核。

## 需求概述

**背景**：4个个股层面方向性因子（volume_price_strength, positive_day_ratio_5, ma5_deviation, near_high_ratio_5）实测 IC 全为负（1d/3d/5d horizon），方向性信号在个股层面不存在。但行业层面 `industry_momentum_5d` 实测 IC=+0.026（正值），说明方向性信号存在于行业而非个股层面。

**目标**：开发3个行业级别方向性因子，作为行业配置维度补充现有均值回归因子。

**因子定义**：

| 因子 | 列名 | 公式 | 含义 | 数据依赖 | IC预期 |
|------|------|------|------|---------|--------|
| 行业5日动量 | `industry_momentum_5d` | 按(行业,日期)分组 → mean(close/prev_close-1, 5日滚动) → 行业均值赋给每只股票 | 行业整体趋势方向 | close, asset, industry_map | **正**（已验证IC=+0.026） |
| 行业换手率趋势 | `industry_turnover_trend` | 按(行业,日期)分组 → mean(turnover_rate, 5日滚动变化比) → 行业均值赋给每只股票 | 行业整体换手趋势 | turnover_rate, industry_map | 不确定 |
| 行业振幅趋势 | `industry_amplitude_trend` | 按(行业,日期)分组 → mean(amplitude, 5日滚动变化比) → 行业均值赋给每只股票 | 行业整体波动趋势 | amplitude, industry_map | 不确定 |

**关键设计决策**：
- 因子值 = 行业均值赋给该行业内的每只股票（同行业股票因子值相同）
- 这是**复杂因子**：需要先从行业映射添加industry列，再按行业分组计算
- 遵循 H5：IC方向不预判，即使IC为负仍有维度互补价值

## 文件修改清单

| Phase | 文件 | 修改内容 | 新增/修改 |
|-------|------|---------|----------|
| **1** | `data_fetchers/factor_calculator.py` | 新增 `calculate_industry_momentum_5d()`、`calculate_industry_turnover_trend()`、`calculate_industry_amplitude_trend()` + required_cols 属性 | **新增** 3函数 |
| **1** | `data_fetchers/factor_generator.py` | `_EXTENDED_FACTOR_COLS` 添加3列名 + 导入3函数 + 新增 Step 计算 + metadata 统计 + 版本历史 | **修改** 5处 |
| **2** | `factor_ic/ic_industry_momentum_5d_1d.py` | 新建 IC 脚本（复杂因子模式） | **新建** |
| **2** | `factor_ic/ic_industry_turnover_trend_1d.py` | 新建 IC 脚本（复杂因子模式） | **新建** |
| **2** | `factor_ic/ic_industry_amplitude_trend_1d.py` | 新建 IC 脚本（复杂因子模式） | **新建** |
| **3** | `backtest/layered_backtest_industry_momentum_5d_1d.py` | 新建分层回测脚本（薄声明配置） | **新建** |
| **3** | `backtest/layered_backtest_industry_turnover_trend_1d.py` | 新建分层回测脚本（薄声明配置） | **新建** |
| **3** | `backtest/layered_backtest_industry_amplitude_trend_1d.py` | 新建分层回测脚本（薄声明配置） | **新建** |
| **4** | `comprehensive_factor/common/factor_selector.py` | `FACTOR_NAME_TO_COL_MAP` 添加3映射 | **修改** |
| **4** | `comprehensive_factor/common/weight_engine.py` | `FACTOR_NAME_TO_COL_MAP` 添加3映射（如独立定义） | **修改** |
| **4** | `factor_definitions.py` | `FACTOR_DEFINITIONS` 添加3定义 | **修改** |
| **5** | PROJECT.md + MODULE.md | 版本历史 + 文档更新 | **修改** |

**⚠️ 任务拆分**：Phase 1 = 数据层（≤3文件，≤200行），Phase 2 = IC脚本（3个独立脚本），Phase 3-5 依次推进。本次先执行 Phase 1。

## 核心计算逻辑

### 1. `calculate_industry_momentum_5d(factor_df, logger_arg=None)`

```python
"""
计算行业5日动量因子

公式:
  1. 添加 industry 列（从 fetch_industry.get_industry_map 映射）
  2. 计算个股 past_return_1d = close / close_prev - 1
  3. 按 (industry, date) 分组 → 5日滚动均值 = industry_momentum_5d
  4. 同行业所有股票赋相同行业动量值

边界处理:
  - industry 未知 → 赋 '其他' 行业
  - 行业股票数 < 5 → 该行业因子值 NaN（min_periods=5）
  - 涨跌停（close_prev=0） → past_return_1d=NaN → 行业均值跳过

required_cols: ["date", "asset", "close"]
"""
```

### 2. `calculate_industry_turnover_trend(factor_df, logger_arg=None)`

```python
"""
计算行业换手率趋势因子

公式:
  1. 添加 industry 列
  2. 按 (industry, date) 分组 → mean(turnover_rate) → industry_turnover_avg
  3. industry_turnover_trend = industry_turnover_avg(t) / industry_turnover_avg(t-1) - 1
  4. 同行业所有股票赋相同行业换手趋势值

边界处理:
  - industry_turnover_avg(t-1) = 0 或极小 → clip(lower=0.001)
  - 行业股票数 < 5 → NaN

required_cols: ["date", "asset", "turnover_rate"]
"""
```

### 3. `calculate_industry_amplitude_trend(factor_df, logger_arg=None)`

```python
"""
计算行业振幅趋势因子

公式:
  1. 添加 industry 列
  2. 按 (industry, date) 分组 → mean(amplitude) → industry_amplitude_avg
  3. industry_amplitude_trend = industry_amplitude_avg(t) / industry_amplitude_avg(t-1) - 1
  4. 同行业所有股票赋相同行业振幅趋势值

边界处理:
  - industry_amplitude_avg(t-1) = 0 → NaN（振幅=0意味着涨跌停，趋势无意义）
  - clip(lower=0.01) 保护
  - 行业股票数 < 5 → NaN

required_cols: ["date", "asset", "amplitude"]
"""
```

## 因子特殊性：行业级别因子

**与现有因子的关键差异**：
- 因子值 = 行业聚合值赋给每只个股（同行业股票因子值相同）
- 需要行业映射数据（从 `fetch_industry.get_industry_map()` 获取）
- IC 分析时截面相关性特殊（行业内无区分力，行业间有区分力）
- 这意味着 IC 衡量的是**行业配置能力**而非个股选择能力

**设计理由**：
- 行业级别因子不直接从 factor_ic_data.json.gz 读取（需要行业映射步骤）
- 但最终因子值写入 factor_ic_data.json.gz（遵循统一数据源原则）
- IC 脚本使用 `run_complex_factor_ic` + `custom_factor_calculation` 模式

## 执行顺序（Phase 划分）

```
Phase 1: 数据层（factor_calculator + factor_generator）→ ≤200行，≤3文件
Phase 2: IC 脚本（3个 ic_industry_*_1d.py）→ 每个≤80行
Phase 3: 分层回测脚本（3个 layered_backtest_*_1d.py）→ 薄声明配置，每个≤40行
Phase 4: 因子映射 + 定义（factor_selector, weight_engine, factor_definitions）
Phase 5: 文档更新（PROJECT.md + MODULE.md 版本历史）
```

## 验证检查清单

Phase 1 验证：
```bash
# 1. 因子计算函数可导入
python3 -c "from data_fetchers.factor_calculator import calculate_industry_momentum_5d; print('OK')"

# 2. factor_generator 运行成功（新增列写入 factor_ic_data.json.gz）
python3 data_fetchers/factor_generator.py

# 3. 输出文件包含新因子列
python3 -c "import gzip,json; d=json.load(gzip.open('data_fetchers/result/factor_ic_data.json.gz','rt')); print('industry_momentum_5d' in d['data'][0])"

# 4. ruff + pytest
ruff check --fix . && ruff format . && pytest
```

## 关键 Pitfall 参考

- Pitfall #47: 比率型因子分母趋近零 → industry_turnover_trend 和 industry_amplitude_trend 需 clip 保护
- Pitfall #64: IC/回测"做多盈利"只是相对排序优势 → 行业因子IC为正不代表绝对正收益
- Pitfall #163: 因子映射缺失 → Phase 4 必须更新 FACTOR_NAME_TO_COL_MAP
- Pitfall #164: 因子列定义缺失 → Phase 1 必须更新 _EXTENDED_FACTOR_COLS