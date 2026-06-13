# Design.md: 方案B（基本面动量因子）+ 方案C（资金流因子）

> 遵循 AGENTS.md Design-First 流程（涉及 2+ 文件改动）
> 创建日期: 2026-06-12
> 作者: 云瑶

---

## 1. 需求概述

### 方案A 已完成（v1.42, 2026-06-12）

行业级别量价方向性因子 3 个：
- `industry_momentum_5d` (IC=+0.026)
- `industry_turnover_trend`
- `industry_amplitude_trend`

### 方案B: 基本面动量因子（行业级别）

**核心洞察**: 方向性信号在行业层面而非个股层面（Pattern 14 结论）。基本面动量信号同样应在行业层面设计。

| 因子 | 列名 | 公式 | 含义 | 数据来源 |
|------|------|------|------|---------|
| 行业ROE趋势 | `industry_roe_trend` | groupby(industry)→mean(ΔROE)→赋个股 | 行业盈利能力改善方向 | akshare `stock_financial_analysis_indicator` → 净资产收益率(%) |
| 行业盈利增长 | `industry_earnings_growth` | groupby(industry)→mean(净利润增长率%)→赋个股 | 行业盈利增长趋势 | 同上 → 净利润增长率(%) |
| 行业PE趋势 | `industry_pe_trend` | groupby(industry)→mean(ΔPE)→赋个股 | 行业估值变化方向 | close(已有)/EPS(财务数据) → PE=close/EPS |

**数据可行性验证**（2026-06-12 实测）：
- `stock_financial_analysis_indicator(symbol, start_year)` ✅ 返回 13季度×86字段
- 净资产收益率(%) ✅ 全部有值
- 净利润增长率(%) ✅ 大部分有值（银行股部分季度NaN，属正常会计差异）
- 主营业务收入增长率(%) ⚠️ 银行/金融股常为NaN
- 每股收益 ✅ 全部有值
- 3019只股票需逐一拉取 → 需建缓存，耗时约1-2小时

**季度数据对齐日频的处理**：
- Point-forward fill（前推填充）：财报发布后至下一财报发布前，所有交易日使用同一季度数据
- 公式：在发布日期 `report_date` 之后的所有交易日，ROE值 = `ROE(report_date)`
- 这是标准做法：投资者在Q1财报发布后至Q2财报发布前，只能看到Q1数据
- 首日无前值 → NaN（自然排除）

**行业均值赋个股**：
- 方案A已验证的模式：groupby(industry,date)→mean→赋给同行业每只股票
- 无个股ROE数据的股票（如次新股）→ 同行业均值填充
- 同行业股票因子值相同 → IC衡量行业配置能力

### 方案C: 资金流因子（行业级别，[experimental]）

| 因子 | 列名 | 公式 | 含义 | 数据来源 |
|------|------|------|------|---------|
| 行业主力净流入趋势 | `industry_capital_flow_ratio_trend` | groupby(industry,date)→mean(main_inflow_ratio)→today/yesterday-1 | 行业资金流向变化方向 | akshare `stock_individual_fund_flow` → 主力净流入-净占比 |
| 行业资金流强度 | `industry_capital_flow_intensity` | groupby(industry,date)→mean(|main_inflow_ratio|)→赋个股 | 行业资金活跃度 | 同上 |

**⚠️ 数据可行性问题**（2026-06-12 实测）：
- `stock_individual_fund_flow`: 仅 **120天** 历史数据（2025-12-10 ~ 2026-06-11）
- 120天 ≈ 4个月 → 不足 ICIR 计算需要（通常需要1-2年 = 250~500天）
- `stock_sector_fund_flow_rank`: 仅当日/5日排名，无历史序列
- `stock_market_fund_flow`: 仅120天市场整体

**开发决策**：
- 方案C标注为 `[experimental]`
- IC 可做基本分析（120天足够算 IC 均值）
- ICIR 不可靠（短样本，ICIR_std大）
- 后续通过增量采集累积数据（每日运行 `fetch_fund_flow.py` 拉取最新数据追加缓存）
- 综合因子筛选中短样本惩罚机制会自动降低权重（遵循 Pitfall #50 豁免机制）

---

## 2. 文件修改清单

### Phase 1: 数据层（新建 + 修改 3 文件）

| 文件 | 修改内容 | 预估行数 |
|------|---------|---------|
| `data_fetchers/fetch_financial.py` | **新建**：财务数据拉取脚本（akshare → JSON缓存） | ~200行 |
| `data_fetchers/factor_calculator.py` | **新增** 5个 `calculate_*` 函数 | ~200行 |
| `data_fetchers/factor_generator.py` | **修改** `_EXTENDED_FACTOR_COLS` + Step 11.8 + Step 11.9 | ~50行 |

### Phase 1-C: 资金流数据层（新建 1 文件）

| 文件 | 修改内容 | 预估行数 |
|------|---------|---------|
| `data_fetchers/fetch_fund_flow.py` | **新建**：资金流数据拉取脚本（akshare → JSON缓存） | ~150行 |

### Phase 2: IC 脚本（新建 5 文件）

| 文件 | 修改内容 |
|------|---------|
| `factor_ic/ic_industry_roe_trend_1d.py` | 新建（复杂因子模式） |
| `factor_ic/ic_industry_earnings_growth_1d.py` | 新建（复杂因子模式） |
| `factor_ic/ic_industry_pe_trend_1d.py` | 新建（复杂因子模式） |
| `factor_ic/ic_industry_capital_flow_ratio_trend_1d.py` | 新建（复杂因子模式）[experimental] |
| `factor_ic/ic_industry_capital_flow_intensity_1d.py` | 新建（复杂因子模式）[experimental] |

### Phase 3: 分层回测脚本（新建 5 文件）

| 文件 | 修改内容 |
|------|---------|
| `backtest/layered_backtest_industry_roe_trend_1d.py` | 新建（薄声明配置） |
| `backtest/layered_backtest_industry_earnings_growth_1d.py` | 新建 |
| `backtest/layered_backtest_industry_pe_trend_1d.py` | 新建 |
| `backtest/layered_backtest_industry_capital_flow_ratio_trend_1d.py` | 新建 [experimental] |
| `backtest/layered_backtest_industry_capital_flow_intensity_1d.py` | 新建 [experimental] |

### Phase 4: 因子映射 + 定义（修改 3 文件）

| 文件 | 修改内容 |
|------|---------|
| `comprehensive_factor/common/factor_selector.py` | FACTOR_NAME_TO_COL_MAP 新增5条 |
| `comprehensive_factor/common/weight_engine.py` | FACTOR_NAME_TO_COL_MAP 新增5条（独立副本） |
| `factor_definitions.py` | FACTOR_DEFINITIONS 新增5条 |

### Phase 5: Pipeline + 文档更新（修改 4+ 文件）

| 文件 | 修改内容 |
|------|---------|
| `run_pipeline.py` | STAGE_0_SCRIPTS 新增 fetch_financial/fetch_fund_flow；STAGE_2_SCRIPTS 新增5个IC脚本 |
| `PROJECT.md` | 版本历史新增 v1.43/v1.44 |
| `data_fetchers/MODULE.md` | 版本历史 |
| `factor_ic/MODULE.md` | 版本历史 |

---

## 3. 核心计算逻辑

### 3.1 fetch_financial.py

**职责**: 从 akshare 拉取所有股票的财务指标数据，缓存为 JSON

```python
# 输出路径: data_fetchers/result/financial_data.json.gz
# 结构: {
#   "meta": { "version": "1.0", "date_range": ..., "stock_count": N },
#   "data": [
#     { "asset": "000001", "report_date": "2026-03-31",
#       "roe": 2.67, "weighted_roe": 2.83,
#       "net_profit_growth_yoy": 3.03,
#       "diluted_eps": 0.7484,
#       "revenue_growth_yoy": NaN  # 银行股可能缺失
#     },
#     ...
#   ]
# }

# 拉取策略：
# 1. 检查缓存 → 缓存未过期则跳过
# 2. 逐一拉取 stock_financial_analysis_indicator(symbol, start_year)
# 3. 提取关键字段: 净资产收益率(%), 加权净资产收益率(%), 净利润增长率(%),
#    摊薄每股收益(元), 主营业务收入增长率(%)
# 4. 合并写入缓存
```

### 3.2 factor_calculator.py 新增函数

#### calculate_industry_roe_trend

```python
def calculate_industry_roe_trend(
    factor_df: pd.DataFrame,
    financial_data_path: str | Path | None = None,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """行业ROE趋势因子: 行业ΔROE赋个股
    
    公式: 
    1. 加载季度财务数据 → ROE per (asset, report_date)
    2. Point-forward fill → 对齐日频 (report_date之后所有交易日用该季度ROE)
    3. ΔROE = ROE(current_quarter) - ROE(previous_quarter)
    4. groupby(industry, date) → mean(ΔROE) → 赋给同行业每只个股
    
    required_cols: date, asset, close
    """
```

#### calculate_industry_earnings_growth

```python
def calculate_industry_earnings_growth(
    factor_df: pd.DataFrame,
    financial_data_path: str | Path | None = None,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """行业盈利增长因子: 行业净利润增长率赋个股
    
    公式:
    1. 加载季度财务数据 → 净利润增长率(%) per (asset, report_date)
    2. Point-forward fill → 对齐日频
    3. groupby(industry, date) → mean(净利润增长率) → 赋给同行业每只个股
    
    required_cols: date, asset
    """
```

#### calculate_industry_pe_trend

```python
def calculate_industry_pe_trend(
    factor_df: pd.DataFrame,
    financial_data_path: str | Path | None = None,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """行业PE趋势因子: 行业ΔPE赋个股
    
    公式:
    1. 加载季度财务数据 → EPS per (asset, report_date)
    2. Point-forward fill → 对齐日频
    3. PE = close / (EPS × 季度年化系数)
       - Q1: EPS × 4 (年化)
       - Q2: EPS × 2 (半年年化)
       - Q3: EPS × 4/3 (9个月年化)
       - Q4: EPS × 1 (全年)
    4. ΔPE = PE(current_quarter) - PE(previous_quarter)
    5. groupby(industry, date) → mean(ΔPE) → 赋给同行业每只个股
    
    ⚠️ 比率型因子: 分母 EPS 可能趋近零 → clip(lower=0.01) 保护
    ⚠️ 负PE（亏损公司）需特殊处理 → abs(PE) 趋势或单独标记
    
    required_cols: date, asset, close
    """
```

#### calculate_industry_capital_flow_ratio_trend

```python
def calculate_industry_capital_flow_ratio_trend(
    factor_df: pd.DataFrame,
    fund_flow_data_path: str | Path | None = None,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """行业主力净流入趋势因子 [experimental]
    
    公式:
    1. 加载资金流数据 → main_inflow_ratio per (asset, date)
    2. groupby(industry, date) → mean(main_inflow_ratio)
    3. trend = mean(t) / mean(t-1) - 1 (分母clip保护)
    4. 赋给同行业每只个股
    
    ⚠️ 数据仅120天 → ICIR不可靠，标注 [experimental]
    ⚠️ 覆盖率约50%（非所有股票有资金流数据）
    
    required_cols: date, asset
    """
```

#### calculate_industry_capital_flow_intensity

```python
def calculate_industry_capital_flow_intensity(
    factor_df: pd.DataFrame,
    fund_flow_data_path: str | Path | None = None,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """行业资金流强度因子 [experimental]
    
    公式:
    1. 加载资金流数据 → |main_inflow_ratio| per (asset, date)
    2. groupby(industry, date) → mean(|main_inflow_ratio|)
    3. 赋给同行业每只个股
    
    ⚠️ 同上: 120天 + 50%覆盖率
    
    required_cols: date, asset
    """
```

### 3.3 factor_generator.py Step 新增

```python
# ========== Step 11.8: 计算行业基本面动量因子 ==========
logger.info("Step 11.8: 计算行业基本面动量因子...")

factor_df = calculate_industry_roe_trend(factor_df, logger_arg=logger)
industry_roe_trend_valid = int(factor_df["industry_roe_trend"].notna().sum())

factor_df = calculate_industry_earnings_growth(factor_df, logger_arg=logger)
industry_earnings_growth_valid = int(factor_df["industry_earnings_growth"].notna().sum())

factor_df = calculate_industry_pe_trend(factor_df, logger_arg=logger)
industry_pe_trend_valid = int(factor_df["industry_pe_trend"].notna().sum())

# ========== Step 11.9: 计算行业资金流因子 [experimental] ==========
logger.info("Step 11.9: 计算行业资金流因子...")

factor_df = calculate_industry_capital_flow_ratio_trend(factor_df, logger_arg=logger)
industry_capital_flow_ratio_trend_valid = int(factor_df["industry_capital_flow_ratio_trend"].notna().sum())

factor_df = calculate_industry_capital_flow_intensity(factor_df, logger_arg=logger)
industry_capital_flow_intensity_valid = int(factor_df["industry_capital_flow_intensity"].notna().sum())
```

---

## 4. 执行顺序（按 Phase 拆分，每任务 ≤3 文件 ≤200 行）

### Task 1 (Phase 1): fetch_financial.py 新建
- 文件: `data_fetchers/fetch_financial.py`
- 范围: 数据拉取 + 缓存逻辑
- 验证: 运行脚本，检查 `data_fetchers/result/financial_data.json.gz` 生成

### Task 2 (Phase 1): factor_calculator.py 新增3个基本面因子
- 文件: `data_fetchers/factor_calculator.py`
- 范围: calculate_industry_roe_trend, calculate_industry_earnings_growth, calculate_industry_pe_trend
- 验证: pytest 单元测试

### Task 3 (Phase 1): factor_generator.py 整合方案B
- 文件: `data_fetchers/factor_generator.py`
- 范围: `_EXTENDED_FACTOR_COLS` + Step 11.8 + 版本历史
- 验证: 运行 factor_generator，检查新因子列写入

### Task 4 (Phase 1-C): fetch_fund_flow.py 新建
- 文件: `data_fetchers/fetch_fund_flow.py`
- 范围: 资金流数据拉取 + 缓存逻辑
- 验证: 运行脚本，检查缓存生成

### Task 5 (Phase 1-C): factor_calculator.py 新增2个资金流因子
- 文件: `data_fetchers/factor_calculator.py`
- 范围: calculate_industry_capital_flow_ratio_trend, calculate_industry_capital_flow_intensity
- 验证: pytest 单元测试

### Task 6 (Phase 1-C): factor_generator.py 整合方案C
- 文件: `data_fetchers/factor_generator.py`
- 范围: `_EXTENDED_FACTOR_COLS` + Step 11.9 + 版本历史
- 验证: 运行 factor_generator

### Task 7-11 (Phase 2): 5个 IC 脚本（每个独立任务）
- 每个新建1个文件 + 1个测试文件

### Task 12-16 (Phase 3): 5个分层回测脚本（每个独立任务）

### Task 17 (Phase 4): 因子映射 + 定义更新
- 文件: factor_selector.py + weight_engine.py + factor_definitions.py

### Task 18 (Phase 5): Pipeline + 文档更新

---

## 5. 关键设计决策

### 5.1 季度数据前推填充策略

**What**: 财务数据是季度发布的（Q1/Q2/Q3/Q4），需对齐到日频才能与量价因子一起计算IC。

**How**: Point-forward fill（前推填充）
- 每只股票在每个 `report_date` 有一个 ROE 值
- 从 `report_date` 到下一个 `report_date` 之间的所有交易日，使用该季度 ROE 值
- `merge_asof(factor_df, financial_df, on='date', by='asset', direction='backward')`
  - `direction='backward'`: 交易日取最近已发布的财报数据（前推填充）
- 首日无前值 → NaN（自然排除，不做填充）

**Don't**: 使用 `ffill()` 填充（Pitfall #57：DataFrame.ffill() 在非时间排序的DataFrame上按行序而非时间序填充）

**Why**: Point-forward 是业界标准做法——投资者在Q1财报发布后至Q2财报发布前，只能看到Q1数据。使用未来数据（backfill）会导致前瞻偏差（look-ahead bias）。

**Examples**:
```python
# ✓ 正确: merge_asof 前推填充
daily_df = pd.merge_asof(
    factor_df.sort_values('date'),
    financial_df.sort_values('report_date'),
    by='asset',
    left_on='date',
    right_on='report_date',
    direction='backward'  # 取最近已发布的财报
)

# ✗ 错误: ffill 前瞻偏差
financial_df.ffill()  # 可能用未来数据填充过去
```

### 5.2 PE 年化处理

**What**: EPS 是季度累计值（Q1 EPS ≠ 年化 EPS），需年化才能计算合理 PE。

**How**: PE = close / annualized_EPS
- Q1: annualized_EPS = EPS × 4 (季度年化)
- Q2: annualized_EPS = EPS × 2 (半年年化)
- Q3: annualized_EPS = EPS × 4/3 (9个月年化)
- Q4: annualized_EPS = EPS × 1 (全年)

**Don't**: 直接 close / EPS（不年化 → PE 在不同季度不可比）

**Why**: Q1 EPS=0.5（年化=2.0） vs Q4 EPS=2.0（年化=2.0），不年化时 PE 会季度跳变。

### 5.3 方案C 数据标注策略

**What**: 资金流数据仅120天历史，ICIR不可靠。

**How**: 
- 因子名标注 `[experimental]`
- IC 脚本输出 meta 中标记 `data_quality: "experimental_120d"`
- 综合因子筛选中，短样本惩罚机制自动降低权重（Pitfall #50 豁免机制）
- 增量采集：每日运行 fetch_fund_flow.py 追加最新数据

**Don't**: 声称 ICIR 结果可靠（120天 ICIR 统计显著性极弱）

---

## 6. 验证检查清单

- [ ] fetch_financial.py 运行成功，缓存包含 3019 只股票 × 13 季度
- [ ] fetch_fund_flow.py 运行成功，缓存包含 5289 只股票 × 120 天
- [ ] factor_generator.py 运行成功，factor_ic_data.json.gz 包含5个新因子列
- [ ] 5个 IC 脚本运行成功，IC 结果文件生成
- [ ] 5个分层回测脚本运行成功，回测结果文件生成
- [ ] factor_selector.py + weight_engine.py 映射包含5个新因子
- [ ] factor_definitions.py 包含5个新因子定义
- [ ] run_pipeline.py 包含新脚本
- [ ] ruff check/format 通过
- [ ] pytest 通过（覆盖率≥70%）
- [ ] 方案B 因子 IC > 0（预期正向，行业基本面动量应偏好强势行业）
- [ ] 方案C 因子 IC 结果标注 experimental