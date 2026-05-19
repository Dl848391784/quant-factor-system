# Bollinger_PB_1D IC 计算流程文档

> 生成时间: 2026-05-08 00:00:00 (北京时间)
> 审阅版本: v1.0

---

## 📋 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    ic_bollinger_pb_1d.py 主流程                  │
├─────────────────────────────────────────────────────────────────┤
│  入口: generate_bollinger_pb_1d_ic_data()                        │
│    ↓                                                             │
│  [1] 数据完整性检查 → 决定是否需要计算                             │
│    ↓                                                             │
│  [2] 从缓存加载 close 数据                                        │
│    ↓                                                             │
│  [3] 计算布林带 %B 因子值（向量化）                                 │
│    ↓                                                             │
│  [4] 调用 calculate_bollinger_pb_1d_ic() 计算反向排名 IC          │
│    ↓                                                             │
│  [5] 保存结果到 JSON 文件                                          │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🔍 详细流程步骤

### Step 1: 增量判断（数据完整性检查）

```
generate_bollinger_pb_1d_ic_data() 入口
    │
    ├── force_full=False? ──→ Yes ──→ check_data_completeness('bollinger_pb_1d')
    │                              │
    │                              ├── mode='skip' ──→ 数据完备，读取现有缓存返回
    │                              │
    │                              └── mode='incremental' or 'full' ──→ 继续
    │
    └── force_full=True ──→ 直接进入全量计算
```

---

### Step 2: 数据加载

```
load_factor_data_for_bollinger()
    │
    ├── 加载缓存: cache/factor_data/factor_data.json.gz
    │   │
    │   ├── 解压 gzip → JSON
    │   ├── 转为 DataFrame
    │   ├── 提取列: [date, asset, close]
    │   └── 过滤缺失值
    │
    └── 返回 factor_df（包含收盘价用于因子计算）
```

**关键区别**：布林带 %B 需要原始收盘价数据，而非预计算的因子值。

---

### Step 3: 布林带 %B 因子计算（核心）

这是 `calculate_bollinger_pb_1d_factor()` 的向量化计算流程：

```
calculate_bollinger_pb_1d_factor(factor_df, n=20, k=2.0)
    │
    ├── [验证] 检查必要列 [date, asset, close]
    │
    ├── [排序] 按 asset + date 排序
    │
    ├── [Step 1] 计算中轨（SMA）
    │   │
    │   ├── 按股票分组
    │   │
    │   └── middle_band = close.rolling(window=N, min_periods=1).mean()
    │       │
    │       └── N = 20（默认移动平均周期）
    │
    ├── [Step 2] 计算标准差
    │   │
    │   └── std_dev = close.rolling(window=N, min_periods=1).std()
    │
    ├── [Step 3] 计算上轨和下轨
    │   │
    │   ├── upper_band = middle_band + K × std_dev
    │   │
    │   └── lower_band = middle_band - K × std_dev
    │       │
    │       └── K = 2.0（默认标准差倍数）
    │
    ├── [Step 4] 计算 %B
    │   │
    │   ├── diff = upper_band - lower_band
    │   │
    │   └── %B = (close - lower_band) / diff
    │       │
    │       └── 边界处理: 当 diff=0 时，%B = 0.5（避免除零）
    │
    └── [统计] 输出因子统计（均值、标准差、超买超卖比例）
```

**布林带 %B 因子公式**：

```
Middle Band = SMA(Close, N)           # 中轨 = N日移动平均
Upper Band = Middle + K × StdDev      # 上轨 = 中轨 + K倍标准差
Lower Band = Middle - K × StdDev      # 下轨 = 中轨 - K倍标准差

%B = (Close - Lower) / (Upper - Lower)  # 价格在布林带中的位置

参数默认值：
- N = 20（移动平均周期）
- K = 2.0（标准差倍数）

%B 含义：
- %B > 1：价格突破上轨（超买）
- %B = 1：价格在上轨
- 0 < %B < 1：价格在布林带内
- %B = 0：价格在下轨
- %B < 0：价格跌破下轨（超卖）
```

---

### Step 4: IC 计算（反向排名）

```
calculate_bollinger_pb_1d_ic(factor_df, return_df)
    │
    ├── [验证] 检查必需列 [date, asset, bollinger_pb_1d, forward_return]
    │
    ├── [合并] 按键合并
    │   │
    │   └── merged = pd.merge(factor_df, return_df, on=[date, asset])
    │
    ├── [遍历] 按日期分组，逐日计算 IC
    │   │
    │   └─────────────────────────────────────────────┐
    │   │                                             │
    │   │  for each date:                              │
    │   │      │                                       │
    │   │      ├── 股票数 < 10? → 跳过该日              │
    │   │      │                                       │
    │   │      ├── %B值全部相同? → IC = 0              │
    │   │      │                                       │
    │   │      └── 计算反向排名 IC:                     │
    │   │          │                                   │
    │   │          ├── [1] %B排名（升序）              │
    │   │          │       rank = %B.rank(pct=True, ascending=True)
    │   │          │       # %B最低 → rank=0, %B最高 → rank=1
    │   │          │                                   │
    │   │          ├── [2] 反向得分                    │
    │   │          │       score = 1 - rank
    │   │          │       # %B<0（超卖）→ score=1（最看好）
    │   │          │       # %B>1（超买）→ score=0（最不看好）
    │   │          │                                   │
    │   │          ├── [3] 收益排名（升序）            │
    │   │          │       return_rank = forward_return.rank(pct=True)
    │   │          │                                   │
    │   │          └── [4] Spearman 相关系数          │
    │   │                  │                           │
    │   │                  └── IC = corr(score, return_rank)
    │   │                                              │
    │   └─────────────────────────────────────────────┘
    │
    ├── [汇总] 计算统计量
    │   │
    │   ├── IC均值 = ic_series.mean()
    │   ├── IC标准差 = ic_series.std()
    │   ├── ICIR = |IC均值| / IC标准差  # 使用绝对值（PROJECT.md 规范）
    │   ├── 正比例 = IC > 0 的天数占比
    │   ├── t统计量 = IC均值 / (IC标准差 / sqrt(n))
    │   └── 显著性标识: *** / ** / *
    │
    └── 返回结果字典
```

---

### Step 5: 反向排名原理

**布林带 %B 因子特殊性**：

```
%B 含义：
┌────────────────────────────────────────────────────────────┐
│  %B 反映价格相对于布林带的位置：                            │
│                                                            │
│  - %B > 1：价格突破上轨，严重超买 → 预期回落 → 不看好       │
│  - %B < 0：价格跌破下轨，严重超卖 → 预期反弹 → 看好         │
│  - 0 < %B < 1：价格在布林带内，正常区间                     │
│                                                            │
│  因此 %B 是"反向指标":                                      │
│  - %B 越低 → 预期收益越高                                   │
│  - %B 越高 → 预期收益越低                                   │
└────────────────────────────────────────────────────────────┘

反向排名处理:
  score = 1 - rank(%B)
  
  示例（某日3只股票）:
  | 股票 | %B  | rank(%B升序) | score=1-rank | 预期含义 |
  |------|-----|--------------|--------------|----------|
  | A    | -0.1| 0.0          | 1.0          | 跌破下轨,最看好 |
  | B    | 0.5 | 0.5          | 0.5          | 在布林带中间 |
  | C    | 1.2 | 1.0          | 0.0          | 突破上轨,最不看好 |
```

---

### Step 6: 输出结果

```json
{
    "factor_name": "bollinger_pb_1d",
    "dates": ["2026-01-01", ...],
    "ic_values": [0.052, ...],
    "rolling_ic_mean": [0.05, ...],
    "ic_mean": 0.0345,
    "ic_std": 0.0123,
    "icir": 2.81,
    "positive_ratio": 0.72,
    "t_stat": 4.23,
    "significance": "***",
    "n_days": 500,
    "n_assets": 3500,
    "summary": "IC均值=0.0345, ICIR=2.81, 正比例=72.0%, 因子有效"
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
    └── factor_data.json.gz    ← close（收盘价数据）
    
cache/factor_data/
    └── return_data.json.gz    ← forward_return_1d（未来收益）

注意：布林带 %B 需要自己计算因子值，不能直接读取预计算因子。
```

---

## 📁 文件位置

| 文件 | 路径 |
|------|------|
| IC计算脚本 | `factor_ic/ic_bollinger_pb_1d.py` |
| 输出结果 | `cache/factor_ic/bollinger_pb_1d_ic.json` |
| 本文档 | `factor_ic/docs/bollinger_pb_1d_ic_flow.md` |

---

## 🔄 与其他因子的对比

| 因子 | IC计算方式 | 排序方向 | 因子计算来源 |
|------|------------|----------|--------------|
| RSI | reverse_rank_ic | 反向 | 缓存预计算 |
| KDJ_J | reverse_rank_ic | 反向 | 现场计算 |
| **Bollinger_PB** | **reverse_rank_ic** | **反向** | **现场计算** |
| Volume_Ratio | normal_rank_ic | 正向 | 缓存预计算 |
| Turnover_Surge | normal_rank_ic | 正向 | 现场计算 |
| Main_Inflow_Ratio | normal_rank_ic | 正向 | 缓存预计算 |

---

*文档结束*