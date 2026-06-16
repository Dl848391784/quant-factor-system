# 日内价格强度因子 IC 分析流程文档

> 版本: v1.0
> 生成时间: 2026-06-02 20:55 北京时间
> 实测数据时间: 2026-06-02 20:55 北京时间（运行验证通过）
> 脚本: ic_intraday_intensity_1d.py（约220行，含因子计算函数）
> 更新内容:
>   1. v1.0 首次创建流程文档（使用 run_complex_factor_ic 公共模块）

---

## 整体架构

```
┌─────────────────┐
│  CLI 入口层      │
│ main()          │
└─────────────────┘
         │
         ▼
┌─────────────────────────────┐
│  公共模块入口                 │
│ run_complex_factor_ic()     │
│ (factor_ic_runner.py)       │
└─────────────────────────────┘
         │
    ┌────┴────┐
    │ 三模式  │
    ▼    ▼    ▼
┌────┐ ┌────┐ ┌────┐
│SKIP│ │INCR│ │FULL│
└────┘ └────┘ └────┘
    │    │    │
    │    │    ▼
    │    │  ┌─────────────────┐
    │    │  │ 自定义因子计算   │
    │    │  │ calculate_      │
    │    │  │ intraday_       │
    │    │  │ intensity()     │
    │    │  └─────────────────┘
    │    │         │
    │    ▼         ▼
    │  ┌─────────────────┐
    │  │ 增量更新逻辑    │
    │  │ (公共模块处理) │
    │  └─────────────────┘
    │         │
    ▼    ▼    ▼
┌─────────────────┐
│  IC 计算层       │
│ calculate_ic_   │
│ with_direction_ │
│ verification()  │（公共模块）
└─────────────────┘
         │
         ▼
┌─────────────────┐
│  结果输出层      │
│ build_ic_result │（公共模块）
│ save_ic_result  │
└─────────────────┘
```

---

## 因子定义

### 公式
```
intraday_intensity = (Close - Open) / (High - Low)
```

### 含义
- **值范围**: -1 到 1
- **正值（阳线）**: 收盘价高于开盘价，值越大表示涨幅占振幅比例越大
- **负值（阴线）**: 收盘价低于开盘价，值越小表示跌幅占振幅比例越大
- **= 0**: 收盘价等于开盘价（十字星）
- **边界处理**: High = Low 时分母为 0，设为 NaN

### 使用场景
- 反映日内价格走势的强度和方向
- 正值越大：强势上涨，买方力量主导
- 负值越小：强势下跌，卖方力量主导
- 绝对值接近 0：震荡行情，多空平衡

---

## 详细流程步骤

### Step 1: 数据加载（公共模块处理）

**函数:** `load_factor_return_data()`（公共模块）

**数据源:**
- `data_fetchers/result/factor_ic_data.json.gz`

**必需列:**
- `open`, `close`, `high`, `low`（用于计算因子）
- `forward_return_1d`（次日收益）

**处理逻辑:**
```
1. 从统一数据源读取数据
2. 过滤缺失值（open/close/high/low）
3. 验证日期对齐
4. 返回 factor_df + return_df + metadata
```

---

### Step 2: 因子计算（自定义函数）

**函数:** `calculate_intraday_intensity()`

**输入:**
```python
factor_df: DataFrame
# 列: date, asset, open, close, high, low
```

**计算逻辑:**
```python
# 1. 数据校验
required_cols = ['open', 'close', 'high', 'low']
missing_cols → raise ValueError

# 2. 有效数据量校验
valid_rows < 100 → raise ValueError

# 3. 计算振幅（分母）
amplitude = high - low

# 4. 计算日内强度
intraday_intensity = (close - open) / amplitude

# 5. 除零保护
High == Low → 设为 NaN

# 6. 添加因子列
factor_df['intraday_intensity'] = intraday_intensity
```

**输出:**
```python
factor_df: DataFrame
# 新增列: intraday_intensity
```

**实测数据:**
- 有效数据行数: 1,487,081
- 振幅为零记录: 3,164 条（已设为 NaN）
- 有效因子值: 1,483,917 条

---

### Step 3: IC 计算（公共模块处理）

**函数:** `calculate_ic_with_direction_verification()`（公共模块）

**计算方法:**
- Spearman 秩相关系数（Rank IC）
- Newey-West 标准误调整（lag=5）
- t 统计量显著性检验

**五维度判断:**
1. 统计显著性：p < 0.05
2. 经济显著性：|ic_mean| > 0.03
3. ICIR 稳定性：ICIR > 0.5
4. IC 分布一致性：正比例与 IC 方向一致
5. 因子方向：从 IC 文件加载

---

### Step 4: 结果输出

**输出文件:**
```
factor_ic/result/ic_intraday_intensity_1d_analysis_result.json
```

**输出结构:**
```json
{
  "factor_name": "intraday_intensity_1d",
  "calculation_date": "2026-06-02T20:55:36",
  "period": {
    "start": "2024-04-16",
    "end": "2026-05-29"
  },
  "ic_metrics": {
    "ic_mean": -0.021762,
    "ic_std": 0.136412,
    "icir": 0.1595,
    "p_value": 1.66e-05,
    "p_value_display": "1.66e-05"
  },
  "sample_stats": {
    "total_days": 545,
    "valid_days": 513,
    "avg_stocks_per_day": 2734.1
  },
  "statistical_significance": {
    "p_value": 1.66e-05,
    "t_stat": -4.3065,
    "nw_lag": 5,
    "is_significant": true,
    "conclusion": "统计显著（p=1.66e-05<0.05）"
  },
  "factor_direction": {
    "ic_mean": -0.021762,
    "ic_mean_sign": "negative",
    "direction_usage": "反向因子：分层回测时做多低值组、做空高值组"
  },
  "economic_significance": {
    "abs_ic_mean": 0.021762,
    "level": "none",
    "is_economically_significant": false,
    "conclusion": "经济不显著（|ic_mean|=0.0218<0.03）"
  },
  "icir_stability": {
    "icir": 0.1595,
    "level": "none",
    "is_stable": false,
    "conclusion": "IC稳定性不足（ICIR=0.16<0.5)"
  },
  "ic_distribution_consistency": {
    "positive_ratio": 0.4269,
    "ic_mean_sign": "negative",
    "is_consistent": true,
    "conclusion": "一致：正比例<50%对应负方向，IC分布正常"
  },
  "dates": ["2024-04-16", ...],
  "ic_values": [-0.0234, ...],
  "rolling_ic_mean": [...]
}
```

---

## 实测结果摘要

| 维度 | 值 | 判断 |
|------|-----|------|
| IC 均值 | -0.0218 | 负向因子 |
| IC 标准差 | 0.1364 | 波动较大 |
| ICIR | 0.16 | 稳定性不足 |
| t 统计量 | -4.31 | 统计显著 |
| p 值 | 1.66e-05 | p < 0.05 |
| IC>0 占比 | 42.69% | 与负方向一致 |
| 有效天数 | 513 天 | 数据充足 |
| 日均股票数 | 2734 | 样本充足 |

**综合判断:**
- ✓ 统计显著：p < 0.05，IC 均值可信
- ✗ 经济不显著：|IC| < 0.03，预测能力弱
- ✗ ICIR 稳定性不足：ICIR < 0.5，IC 波动大
- ✓ IC 分布一致：正比例与负方向对应

**因子方向:**
- 反向因子（ic_mean < 0）
- 分层回测时：做多低值组（日内强度小的股票）、做空高值组

---

## 代码结构说明

### 主脚本职责（遵循 MODULE.md 约束）
1. 定义因子计算函数（calculate_intraday_intensity）
2. CLI 参数解析（--force-full, --min-stocks）
3. 调用公共模块入口（run_complex_factor_ic）
4. 结果摘要输出

### 公共模块职责
- 数据加载（load_factor_return_data）
- 模式判断（should_use_incremental）
- IC 计算（calculate_ic_with_direction_verification）
- 五维度判断（全部由公共模块处理）
- 结果保存（build_ic_result, save_ic_result）

### 边界处理
- High == Low 时设为 NaN（除零保护）
- 使用 `np.nan` 替代 `pd.NA`（遵循 MODULE.md 约束 10）
- DataFrame 参数先 `copy()`（遵循 MODULE.md 约束 4）

---

## 运行命令

```bash
# 正常运行（自动判断模式）
python -m factor_ic.ic_intraday_intensity_1d

# 强制全量计算
python -m factor_ic.ic_intraday_intensity_1d --force-full

# 自定义最小股票数
python -m factor_ic.ic_intraday_intensity_1d --min-stocks 20
```

---

## 关键字段对照表

| 字段 | 描述 | 来源 |
|------|------|------|
| `open` | 开盘价 | 数据源 |
| `close` | 收盘价 | 数据源 |
| `high` | 最高价 | 数据源 |
| `low` | 最低价 | 数据源 |
| `intraday_intensity` | 日内强度因子 | 自定义计算 |
| `forward_return_1d` | 次日收益 | 数据源 |

---

## 常见问题

### Q1: 为什么 IC 均值是负值？
日内强度因子为负值时，表示当日下跌（收 < 开）。IC 均值负，意味着下跌日的股票次日表现更好（反转效应）。

### Q2: High == Low 时如何处理？
振幅为零时，日内强度公式分母为 0，此时设为 NaN。实测发现 3164 条此类记录（涨跌停板或数据异常）。

### Q3: 为什么使用 run_complex_factor_ic？
因为日内强度需要从 open/close/high/low 列计算派生，数据源中无现成列，需自定义 `calculate_intraday_intensity` 函数。

---

## 版本历史

| 版本 | 时间 | 变更 |
|------|------|------|
| v1.0 | 2026-06-02 | 首次创建，使用 run_complex_factor_ic 公共模块 |