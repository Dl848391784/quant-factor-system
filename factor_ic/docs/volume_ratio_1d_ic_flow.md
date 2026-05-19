# Volume_Ratio_1D IC 计算流程文档

> 生成时间: 2026-05-08 00:00:00 (北京时间)
> 审阅版本: v1.0

---

## 📋 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    ic_volume_ratio_1d.py 主流程                  │
├─────────────────────────────────────────────────────────────────┤
│  入口: main()                                                    │
│    ↓                                                             │
│  [1] 从缓存加载因子数据（volume_ratio_5）                          │
│    ↓                                                             │
│  [2] 从缓存加载收益数据（forward_return_1d）                       │
│    ↓                                                             │
│  [3] 调用 calculate_daily_ic_series() 计算正向排名 IC              │
│    ↓                                                             │
│  [4] 保存结果到 JSON 文件                                          │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🔍 详细流程步骤

### Step 1: 数据加载

```
load_data_from_cache(factor_col='volume_ratio_5', return_col='forward_return_1d')
    │
    ├── [加载因子数据]
    │   │
    │   ├── 文件: cache/factor_data/factor_data.json.gz
    │   ├── 解压 gzip → JSON
    │   ├── 转为 DataFrame
    │   ├── 提取列: [date, asset, volume_ratio_5]
    │   └── 过滤缺失值
    │
    ├── [加载收益数据]
    │   │
    │   ├── 文件: cache/factor_data/return_data.json.gz
    │   ├── 解压 gzip → JSON
    │   ├── 转为 DataFrame
    │   ├── 提取列: [date, asset, forward_return_1d]
    │   ├── 重命名: forward_return_1d → forward_return
    │   └── 过滤缺失值
    │
    ├── [日期筛选]
    │   │
    │   └── 只保留最近 500 天数据
    │
    └── 返回 (factor_df, return_df)
```

**关键区别**：量比因子直接从缓存读取预计算值，无需现场计算。

---

### Step 2: IC 计算（正向排名）

这是 `calculate_daily_ic_series()` 的核心流程：

```
calculate_daily_ic_series(factor_df, return_df)
    │
    ├── [合并] 按键合并
    │   │
    │   └── merged = pd.merge(
    │       factor_df[['date', 'asset', 'volume_ratio_5']],
    │       return_df[['date', 'asset', 'forward_return']],
    │       on=['date', 'asset']
    │   )
    │
    ├── [遍历] 按日期分组，逐日计算 IC
    │   │
    │   └─────────────────────────────────────────────┐
    │   │                                             │
    │   │  for each date:                              │
    │   │      │                                       │
    │   │      ├── 股票数 < 10? → 跳过该日              │
    │   │      │                                       │
    │   │      └── 计算正向排名 IC（Spearman）:         │
    │   │          │                                   │
    │   │          └── IC = spearmanr(volume_ratio_5, forward_return)
    │   │              │                               │
    │   │              └── scipy.stats.spearmanr 直接计算
    │   │                  # 量比高 → 排名高 → 预期收益高
    │   │                                              │
    │   └─────────────────────────────────────────────┘
    │
    ├── [滚动均值] 计算 20 日滚动 IC 均值
    │   │
    │   └── rolling_mean = ic_series.rolling(window=20, min_periods=1).mean()
    │
    ├── [统计量计算]
    │   │
    │   ├── IC均值 = ic_series.mean()
    │   ├── IC标准差 = ic_series.std()
    │   ├── ICIR = |IC均值| / IC标准差  # 使用绝对值（PROJECT.md 规范）
    │   ├── 正比例 = IC > 0 的天数占比
    │   ├── t统计量 = IC均值 × sqrt(n) / IC标准差
    │   └
    │   └── 显著性判断:
    │       │
    │       ├── |t_stat| > 2.576 → "***"（99%显著）
    │       ├── |t_stat| > 1.96 → "**"（95%显著）
    │       ├── |t_stat| > 1.645 → "*"（90%显著）
    │       └── 否则 → 无星号
    │
    └── 返回结果字典
```

---

### Step 3: 正向排名原理

**量比因子特殊性**：

```
量比因子含义：
┌────────────────────────────────────────────────────────────┐
│  volume_ratio_5 = 当日成交量 / 过去5日平均成交量            │
│                                                            │
│  - 量比 > 1：当日成交量高于近期均值 → 资金关注度提升         │
│  - 量比 < 1：当日成交量低于近期均值 → 资金关注度降低         │
│                                                            │
│  量比是"正向指标":                                           │
│  - 量比越高 → 资金关注度越高 → 预期收益越高                  │
│  - 量比越低 → 资金关注度越低 → 预期收益越低                  │
│                                                            │
│  因此使用正向排名，无需反向处理                              │
└────────────────────────────────────────────────────────────┘

直接计算 Spearman IC:
  IC = spearmanr(volume_ratio_5, forward_return)
  
  示例（某日3只股票）:
  | 股票 | 量比 | 收益 | 排名关系 |
  |------|------|------|----------|
  | A    | 2.5  | 5%   | 量比高,收益高 → 正相关贡献 |
  | B    | 1.0  | 2%   | 量比中,收益中 → 中性 |
  | C    | 0.5  | -1%  | 量比低,收益低 → 正相关贡献 |
```

---

### Step 4: 输出结果

```json
{
    "factor_name": "volume_ratio_1d",
    "ic_metrics": {
        "ic_mean": 0.0345,
        "ic_std": 0.0123,
        "icir": 2.81,
        "positive_ratio": 0.72,
        "t_stat": 4.23,
        "significance": "***",
        "n_days": 500,
        "n_assets": 3500,
        "summary": "IC均值=0.0345, ICIR=2.81, 正比例=72.0%, 因子预测能力较强"
    },
    "ic_series": {
        "dates": ["2026-01-01", ...],
        "ic_values": [0.052, ...],
        "rolling_ic_mean": [0.05, ...]
    },
    "params": {
        "n_days": 500,
        "factor_col": "volume_ratio_5"
    }
}
```

---

## 📊 关键指标含义

| 指标 | 含义 | 判断标准 |
|------|------|----------|
| **IC均值** | 因子预测能力 | > 0.05 = 有效；< -0.05 = 反向有效 |
| **ICIR** | IC稳定性 | > 0.5 = 可用；> 1.0 = 较好；> 2.0 = 很好 |
| **正比例** | IC > 0 的天数占比 | > 50% = 有预测能力 |
| **t统计量** | IC是否显著不为零 | > 1.96 = 95%显著；> 2.58 = 99%显著 |

---

## 🔧 数据依赖

```
cache/factor_data/
    ├── factor_data.json.gz    ← volume_ratio_5（预计算因子）
    └── return_data.json.gz    ← forward_return_1d（未来收益）

特点：量比因子直接从缓存读取，无需现场计算。
```

---

## 📁 文件位置

| 文件 | 路径 |
|------|------|
| IC计算脚本 | `factor_ic/ic_volume_ratio_1d.py` |
| 输出结果 | `cache/factor_ic/volume_ratio_1d_ic.json` |
| 本文档 | `factor_ic/docs/volume_ratio_1d_ic_flow.md` |

---

## 🔄 与其他因子的对比

| 因子 | IC计算方式 | 排序方向 | 因子计算来源 |
|------|------------|----------|--------------|
| RSI | reverse_rank_ic | 反向 | 缓存预计算 |
| KDJ_J | reverse_rank_ic | 反向 | 现场计算 |
| Bollinger_PB | reverse_rank_ic | 反向 | 现场计算 |
| **Volume_Ratio** | **normal_rank_ic** | **正向** | **缓存预计算** |
| Turnover_Surge | normal_rank_ic | 正向 | 现场计算 |
| Main_Inflow_Ratio | normal_rank_ic | 正向 | 缓存预计算 |

---

*文档结束*