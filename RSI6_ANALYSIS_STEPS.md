# RSI(6) 因子分析步骤文档

## 概述

本文档详细说明 RSI(6) 因子的 RankIC、分层回测和多空分析的完整计算流程。

---

## 一、数据准备

### 1.1 数据获取
- **数据源**: 新浪财经 API
- **股票范围**: 沪深主板股票（60/00开头，剔除创业板、科创板、北交所）
- **历史数据**: 约500个交易日（约2年）

### 1.2 数据结构
| 字段 | 说明 |
|------|------|
| date | 交易日期 |
| asset | 股票代码 |
| rsi_6 | RSI(6) 因子值（0-100） |
| forward_return | 前瞻收益（下一天收盘价/当天收盘价 - 1） |
| volume | 成交量 |
| close | 收盘价 |
| prev_close | 前一日收盘价 |

---

## 二、动态过滤异常股票

### 2.1 过滤条件（每日独立执行）

| 条件 | 判断方法 | 说明 |
|------|----------|------|
| 停牌 | `volume == 0 或 volume is None` | 无法交易 |
| ST股票 | `股票名称含 "ST"` | 涨跌幅限制5% |
| 涨停 | `close >= prev_close * 1.10 * 0.998` | 无法买入 |
| 跌停 | `close <= prev_close * 0.90 * 1.002` | 无法卖出 |

### 2.2 涨停/跌停价计算
```
涨停价 = 前一日收盘价 × 1.10（主板10%）
跌停价 = 前一日收盘价 × 0.90
```

### 2.3 过滤流程
```
原始数据 → 剔除停牌 → 剔除ST → 剔除涨停 → 剔除跌停 → 过滤后数据
```

---

## 三、去极值处理

### 3.1 方法：分位数法 + numpy.clip

```python
def winsorize_factor(factor_values, lower_quantile=0.025, upper_quantile=0.975):
    """
    分位数法去极值
    """
    lower = np.quantile(factor_values, 0.025)  # 下界：2.5%分位数
    upper = np.quantile(factor_values, 0.975)  # 上界：97.5%分位数
    winsorized = np.clip(factor_values, lower, upper)
    return winsorized
```

### 3.2 执行方式
- **逐日进行**：每天独立计算上下界，不跨日处理
- **示例**：
  ```
  某日RSI分布: [5, 10, 20, 30, 40, 50, 60, 70, 80, 95]
  下界(2.5%): 5.5
  上界(97.5%): 93.5
  去极值后: [5.5, 10, 20, 30, 40, 50, 60, 70, 80, 93.5]
  ```

---

## 四、RankIC 计算

### 4.1 计算公式

```
IC(day) = corr(rank(factor), rank(return))
```

### 4.2 详细步骤

```python
for each day:
    1. 获取该日所有股票的因子值和收益值
    2. 对因子值进行去极值处理
    3. 计算因子值的排名: factor_ranks = factor_values.rank()
    4. 计算收益值的排名: return_ranks = return_values.rank()
    5. 计算 Spearman 相关系数: IC = factor_ranks.corr(return_ranks)
```

### 4.3 IC 统计指标

| 指标 | 公式 | 说明 |
|------|------|------|
| IC均值 | `mean(IC)` | 因子预测能力的平均水平 |
| IC标准差 | `std(IC)` | IC的波动性 |
| ICIR | `mean(IC) / std(IC)` | 信息比率，衡量因子稳定性 |
| IC>0比例 | `count(IC>0) / count(IC)` | 正相关天数占比 |

---

## 五、分层回测

### 5.1 分层方法

```
Step 1: 对每日股票按因子值排序
Step 2: 等分为N层（默认5层）
Step 3: 计算每层的平均收益
```

### 5.2 详细步骤

```python
for each day:
    1. 对该日所有股票按因子值（去极值后）升序排序
    2. 等分为5层：
       - Layer 1: 因子值最小的20%股票（RSI最低，最超卖）
       - Layer 2: 次小的20%股票
       - Layer 3: 中间20%股票
       - Layer 4: 次大的20%股票
       - Layer 5: 因子值最大的20%股票（RSI最高，最超买）
    3. 计算每层的等权平均收益
```

### 5.3 分层收益计算

```
Layer_i 收益 = mean(该层所有股票的 forward_return)
```

### 5.4 累计净值计算

```
累计净值 = cumprod(1 + 每日收益)
```

---

## 六、多空收益分析

### 6.1 多空组合构建

```
做多: Layer 1（因子值最小的股票）
做空: Layer 5（因子值最大的股票）
多空收益 = Layer 1 收益 - Layer 5 收益
```

### 6.2 统计指标

| 指标 | 公式 | 说明 |
|------|------|------|
| 年化收益 | `mean(多空收益) * 252` | 年化后的平均收益 |
| 年化波动率 | `std(多空收益) * sqrt(252)` | 年化后的波动率 |
| 夏普比率 | `年化收益 / 年化波动率` | 风险调整后收益 |
| 最大回撤 | `max(累计净值回撤)` | 最大亏损幅度 |
| 胜率 | `count(多空收益>0) / count(多空收益)` | 盈利天数占比 |

---

## 七、单调性检验

### 7.1 检验方法

```
检验各层收益是否单调递增或递减：
- 如果 Layer1 < Layer2 < Layer3 < Layer4 < Layer5：单调递增
- 如果 Layer1 > Layer2 > Layer3 > Layer4 > Layer5：单调递减
- 否则：单调性不通过
```

### 7.2 判断标准

```
✓ 单调性通过: 各层收益呈单调关系
✗ 单调性不通过: 各层收益存在波动
```

---

## 八、完整流程图

```
┌─────────────────────────────────────────────────────────────────┐
│                     RSI(6) 因子分析完整流程                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. 数据获取                                                    │
│     ├── 获取股票列表（主板）                                     │
│     ├── 获取K线数据（500天）                                     │
│     └── 计算 RSI(6) 和前瞻收益                                   │
│                     ↓                                           │
│  2. 数据缓存                                                    │
│     ├── factor_data.json.gz（因子数据）                         │
│     ├── return_data.json.gz（收益数据）                         │
│     └── stock_status.json.gz（交易状态）                        │
│                     ↓                                           │
│  3. 动态过滤（每日独立）                                         │
│     ├── 剔除停牌股票                                            │
│     ├── 剔除ST股票                                              │
│     ├── 剔除涨停股票                                            │
│     └── 剔除跌停股票                                            │
│                     ↓                                           │
│  4. 去极值处理（每日独立）                                       │
│     └── 分位数法（2.5%/97.5%）                                  │
│                     ↓                                           │
│  5. RankIC 计算                                                 │
│     ├── 每日计算 IC                                             │
│     └── 汇总统计（IC均值、ICIR、IC>0比例）                       │
│                     ↓                                           │
│  6. 分层回测                                                    │
│     ├── 按因子值分层（5层）                                     │
│     ├── 计算各层收益                                            │
│     └── 计算累计净值                                            │
│                     ↓                                           │
│  7. 多空分析                                                    │
│     ├── 构建多空组合                                            │
│     ├── 计算年化收益、夏普比率                                   │
│     └── 单调性检验                                              │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 九、代码调用示例

```python
from real_data_loader import RealDataLoader
from layered_backtest_optimized import run_layered_backtest

# 1. 加载数据
loader = RealDataLoader(enable_cache=True)
factor_df, return_df = loader.load_data_multithreaded(n_days=500)

# 2. 计算 RankIC
ic_df = loader.calculate_rank_ic(
    factor_df, 
    return_df,
    enable_filter=True,      # 启用动态过滤
    enable_winsorize=True    # 启用去极值
)

# 3. 分层回测
result = run_layered_backtest(
    factor_df, 
    return_df,
    num_layers=5,
    enable_filter=True,
    enable_winsorize=True
)

# 4. 查看结果
print(result.statistics)      # 各层统计
print(result.long_short)      # 多空组合
```

---

## 十、注意事项

1. **过滤时机**: 在因子计算后、IC计算前进行过滤
2. **去极值时机**: 在过滤后、分层前进行去极值
3. **每日独立**: 过滤和去极值都是逐日独立进行的
4. **不修改缓存**: 所有处理都在内存中进行，不修改原始缓存数据

---

文档生成时间: 2026-04-03