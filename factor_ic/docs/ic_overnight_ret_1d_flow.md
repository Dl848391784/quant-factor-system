# 隔夜收益率因子 IC 计算流程文档

> 版本: v1.0  
> 创建时间: 2026-05-28 23:55 北京时间  
> 作者: 云瑶  
> 因子名称: overnight_ret  
> 收益周期: 1d  

---

## 一、整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    隔夜收益率因子 IC 计算流程                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  [数据加载] ────▶ [因子计算] ────▶ [IC计算] ────▶ [结果构建]        │
│      │              │              │              │              │
│      ▼              ▼              ▼              ▼              │
│  factor_ic_data  overnight_ret   Spearman IC   五维度判断        │
│  (open, close)   (自定义函数)     + 统计检验    + 输出结构         │
│                                                                 │
│  数据来源: data_fetchers/result/factor_ic_data.json.gz            │
│  输出路径: factor_ic/result/ic_overnight_ret_1d_analysis_result.json │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**关键组件：**
- **数据加载**：`run_complex_factor_ic` → `load_factor_return_data`（公共模块）
- **因子计算**：`calculate_overnight_return`（自定义函数）
- **IC计算**：`calculate_ic_with_direction_verification`（公共模块）
- **结果构建**：`build_ic_result`（公共模块）

---

## 二、详细流程步骤

### Step 1: 数据加载（公共模块）

**函数：** `load_factor_return_data(factor_cols=['open', 'close'])`

**数据来源：** `data_fetchers/result/factor_ic_data.json.gz`

**加载字段：**
- 必需字段：`open`, `close`（用于计算隔夜收益）
- 收益字段：`forward_return_1d`（IC计算目标）
- 索引字段：`date`, `asset`

**数据验证：**
- 列名检查：确保 `open`, `close` 存在
- 日期格式：YYYY-MM-DD（强制格式）
- 空值处理：自然保留，后续计算会过滤

**输出：**
```python
factor_df: pd.DataFrame  # 包含 open, close 列
return_df: pd.DataFrame  # 包含 forward_return_1d 列
raw_metadata: dict       # 数据范围信息
```

---

### Step 2: 因子计算（自定义函数）

**函数：** `calculate_overnight_return(factor_df)`

**计算公式：**
```
overnight_ret = (今日开盘价 - 昨日收盘价) / 昨日收盘价
```

**实现步骤：**

```python
# 1. 函数入口先 copy()（遵循 MODULE.md 约束 #4）
factor_df = factor_df.copy()

# 2. 按资产分组，获取昨日收盘价
prev_close = factor_df.groupby('asset')['close'].shift(1)

# 3. 计算隔夜收益率
factor_df['overnight_ret'] = (factor_df['open'] - prev_close) / prev_close

# 4. 除零防护（prev_close < EPSILON 时设为 NaN）
abnormal_mask = prev_close < EPSILON  # EPSILON = 1e-10
factor_df.loc[abnormal_mask, 'overnight_ret'] = np.nan
```

**关键特性：**
- 第一天数据为 NaN（无昨日收盘价）
- 每只股票独立计算（按资产分组）
- 除零防护（避免异常值）

**示例计算：**

| asset | date | open | close | prev_close | overnight_ret |
|-------|------|------|-------|------------|---------------|
| A | 2026-05-01 | 10.0 | 10.2 | NaN | NaN |
| A | 2026-05-02 | 10.5 | 10.8 | 10.2 | 0.0294 |
| A | 2026-05-03 | 11.0 | 11.2 | 10.8 | 0.0185 |
| B | 2026-05-01 | 20.0 | 20.5 | NaN | NaN |
| B | 2026-05-02 | 21.0 | 21.5 | 20.5 | 0.0244 |

**计算验证：**
- Asset A, 2026-05-02: (10.5 - 10.2) / 10.2 = 0.0294 ✓
- Asset B, 2026-05-02: (21.0 - 20.5) / 20.5 = 0.0244 ✓

---

### Step 3: IC 计算（公共模块）

**函数：** `calculate_ic_with_direction_verification(factor_df, return_df, factor_col='overnight_ret')`

**计算方法：** Spearman 秩相关系数（每日）

**流程：**

```
1. 合并因子数据和收益数据（按 date, asset）
2. 按日期分组，计算每日 IC
   - IC = Spearman(overnight_ret, forward_return_1d)
   - 要求：股票数 >= min_stocks（默认10）
3. 计算 IC 统计指标
   - ic_mean: IC 均值
   - ic_std: IC 标准差
   - ICIR: abs(ic_mean) / ic_std
4. Newey-West t 检验（统计显著性）
   - 样本量 T = valid_days（不是 total_days）
   - nw_lag = max(1, floor(4 * (T/100)^(2/9)))
5. 五维度判断
   - 统计显著性（p < 0.05）
   - 因子方向（ic_mean 符号）
   - 经济显著性（|ic_mean| >= 0.03）
   - ICIR 稳定性（|ICIR| >= 0.5）
   - IC 分布一致性（正比例与方向一致）
```

**关键指标：**
- **IC 均值**：衡量因子预测能力
- **ICIR**：衡量 IC 稳定性（越大越好）
- **p_value**：统计显著性（< 0.05 为显著）

---

### Step 4: 结果构建（公共模块）

**函数：** `build_ic_result(ic_result, raw_metadata, factor_name='overnight_ret')`

**输出结构：**

```json
{
  "factor_name": "overnight_ret",
  "calculation_date": "2026-05-28T23:55:00",
  "period": {
    "start": "2025-01-01",
    "end": "2026-05-27",
    "description": "IC 计算有效日期范围"
  },
  "ic_metrics": {
    "ic_mean": -0.0250,
    "ic_std": 0.1050,
    "icir": 0.24,
    "p_value": 0.12,
    "p_value_display": "p=0.12"
  },
  "sample_stats": {
    "total_days": 545,
    "valid_days": 514,
    "avg_stocks_per_day": 2800.0,
    "avg_stocks_period": {
      "start": "2025-01-01",
      "end": "2026-05-27",
      "description": "平均股票数统计口径"
    }
  },
  "statistical_significance": {
    "t_stat": -1.56,
    "p_value": 0.12,
    "p_value_display": "p=0.12",
    "nw_lag": 6,
    "nw_lag_method": "Newey-West (4*(T/100)^(2/9))",
    "is_significant": false,
    "conclusion": "统计不显著（p >= 0.05）"
  },
  "factor_direction": {
    "ic_mean": -0.0250,
    "ic_mean_sign": "negative",
    "direction_usage": "反向因子：高因子值 → 低收益",
    "conclusion": "反向因子（ic_mean < 0）"
  },
  "economic_significance": {
    "abs_ic_mean": 0.0250,
    "threshold_used": {"weak": 0.03, "strong": 0.05},
    "level": "weak",
    "is_economically_significant": false,
    "conclusion": "经济显著性较弱（|ic_mean| < 0.03）"
  },
  "icir_stability": {
    "icir": 0.24,
    "threshold_used": {"usable": 0.5, "good": 1.0, "excellent": 2.0},
    "level": "unusable",
    "is_stable": false,
    "conclusion": "ICIR 不稳定（< 0.5）"
  },
  "ic_distribution_consistency": {
    "positive_ratio": 0.45,
    "ic_mean_sign": "negative",
    "consistency_type": "contradictory",
    "distribution_hint": "反向因子：正比例 < 50% 为正常",
    "is_consistent": true,
    "conclusion": "分布一致性良好（反向因子，正比例 < 50%）"
  },
  "dates": ["2025-01-02", "2025-01-03", ...],
  "ic_values": [-0.03, 0.02, -0.01, ...],
  "rolling_ic_mean": [null, null, ..., -0.02, -0.025],
  "positive_ratio": 0.45,
  "n_assets": 2800,
  "summary": {
    "ic_performance": "IC 表现较弱",
    "statistical_significance": "统计不显著",
    "factor_direction": "反向因子",
    "economic_significance": "经济显著性较弱",
    "recommendation": "因子预测能力较弱，不建议用于策略"
  },
  "factor_stats": {
    "factor_name": "overnight_ret",
    "return_period": "1d",
    "data_source": "factor_ic_data.json.gz",
    "total_days": 545,
    "valid_days": 514
  },
  "factor_col": "overnight_ret",
  "update_mode": "full"
}
```

**输出路径：** `factor_ic/result/ic_overnight_ret_1d_analysis_result.json`

---

## 三、关键指标说明

### 3.1 IC 统计指标

| 指标 | 含义 | 判断标准 |
|------|------|---------|
| ic_mean | IC 均值 | > 0.03 正向，< -0.03 反向，其他无效 |
| ic_std | IC 标准差 | 越小越稳定 |
| ICIR | 信息比率 | > 0.5 可用，> 1.0 良好，> 2.0 优秀 |
| p_value | 统计显著性 | < 0.05 显著 |

### 3.2 五维度判断

| 维度 | 判断依据 | 结论字段 |
|------|---------|---------|
| 统计显著性 | p < 0.05 | statistical_significance.is_significant |
| 因子方向 | ic_mean 符号 | factor_direction.ic_mean_sign |
| 经济显著性 | \|ic_mean\| >= 0.03 | economic_significance.is_economically_significant |
| ICIR 稳定性 | \|ICIR\| >= 0.5 | icir_stability.is_stable |
| IC 分布一致性 | 正比例与方向一致 | ic_distribution_consistency.is_consistent |

### 3.3 预期表现（基于隔夜收益特性）

**隔夜收益率因子特点：**
- 反映隔夜市场情绪变化
- 通常预测能力较弱（ICIR < 0.5）
- 方向不确定（需实测确定）

**预期指标范围：**
- IC 均值：-0.03 ~ 0.03（弱预测能力）
- ICIR：0.2 ~ 0.4（不稳定）
- 有效天数：~500 天（第一天为 NaN）

---

## 四、异常处理

### 4.1 数据异常

| 异常类型 | 检测方法 | 处理方式 |
|---------|---------|---------|
| 列名缺失 | `required_fields` 校验 | 抛出 ValueError |
| prev_close = 0 | `prev_close < EPSILON` | 设为 NaN + 日志警告 |
| 股票数不足 | `len(group) < min_stocks` | 跳过当日 IC 计算 |
| 收益数据缺失 | `forward_return_1d` 为 NaN | 自然过滤（不影响计算） |

### 4.2 计算异常

| 异常类型 | 检测方法 | 处理方式 |
|---------|---------|---------|
| 除零错误 | EPSILON 阈值 | 设为 NaN（防御性编程） |
| 空数据 | `len(factor_df) == 0` | 抛出 RuntimeError |
| NaN 过多 | 有效天数 < 10 | 抛出 RuntimeError |

### 4.3 输出异常

| 异常类型 | 检测方法 | 处理方式 |
|---------|---------|---------|
| JSON 写入失败 | `json.dump` 异常 | 抛出 IOError |
| 目录不存在 | `Path.mkdir` | 自动创建 |

---

## 五、验证检查清单

### 5.1 数据验证

```
□ factor_cols=['open', 'close'] 正确
□ 数据加载无异常
□ 日期格式 YYYY-MM-DD 一致
□ prev_close 第一天为 NaN（预期）
□ 除零防护生效（EPSILON=1e-10）
```

### 5.2 计算验证

```
□ 隔夜收益率计算正确（公式验证）
□ 按资产分组正确（每只股票独立）
□ NaN 处理正确（第一天 + 除零）
□ 有效天数统计正确（排除 NaN）
```

### 5.3 输出验证

```
□ 输出结构符合 MODULE.md 模板
□ 五维度判断完整
□ 字段值非 None（排除预期 NaN）
□ JSON 格式正确
□ 文件路径正确：factor_ic/result/
```

---

## 六、性能监控

### 6.1 执行时间

| 步骤 | 预计时间 | 实测时间（待补充） |
|------|---------|------------------|
| 数据加载 | < 5s | - |
| 因子计算 | < 10s | - |
| IC 计算 | < 15s | - |
| 结果构建 | < 1s | - |
| 总计 | < 30s | - |

### 6.2 内存占用

| 数据类型 | 预计大小 |
|---------|---------|
| factor_df | ~100MB（545天 × 2800股） |
| return_df | ~50MB |
| IC 结果 | < 1MB |

---

## 七、更新记录

| 版本 | 时间 | 更新内容 |
|------|------|---------|
| v1.0 | 2026-05-28 23:55 | 初始版本，创建流程文档 |

---

## 八、参考规范

- **PROJECT.md**: 公共模块强制复用规范、日志规范、输出目录规范
- **MODULE.md**: IC 计算规范、五维度判断、输出结构模板
- **factor_ic_runner.py**: run_complex_factor_ic 主入口规范

---

*最后更新: 2026-05-28 23:55 (v1.0 - 初始版本)*