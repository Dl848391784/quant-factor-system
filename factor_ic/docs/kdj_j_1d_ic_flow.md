# KDJ_J_1D IC 计算流程文档

> 生成时间: 2026-05-08 00:00:00 (北京时间)
> 审阅版本: v1.0

---

## 📋 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    ic_kdj_j_1d.py 主流程                         │
├─────────────────────────────────────────────────────────────────┤
│  入口: generate_kdj_j_ic_data()                                  │
│    ↓                                                             │
│  [1] 数据完整性检查 → 决定是否需要计算                             │
│    ↓                                                             │
│  [2] 从缓存加载 close/high/low 数据                               │
│    ↓                                                             │
│  [3] 计算 KDJ_J 因子值（向量化）                                   │
│    ↓                                                             │
│  [4] 调用 calculate_kdj_j_ic() 计算反向排名 IC                    │
│    ↓                                                             │
│  [5] 保存结果到 JSON 文件                                          │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🔍 详细流程步骤

### Step 1: 增量判断（数据完整性检查）

```
generate_kdj_j_ic_data() 入口
    │
    ├── force_full=False? ──→ Yes ──→ check_data_completeness('kdj_j_1d')
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
load_factor_data_for_kdj_j()
    │
    ├── 加载缓存: cache/factor_data/factor_data.json.gz
    │   │
    │   ├── 解压 gzip → JSON
    │   ├── 转为 DataFrame
    │   ├── 提取列: [date, asset, close, high, low]
    │   └── 过滤缺失值
    │
    └── 返回 factor_df（包含价格数据用于因子计算）
```

**关键区别**：KDJ_J 需要原始价格数据（close/high/low），而非预计算的因子值。

---

### Step 3: KDJ_J 因子计算（核心）

这是 `calculate_kdj_j_factor()` 的向量化计算流程：

```
calculate_kdj_j_factor(factor_df, n=9, m1=3, m2=3)
    │
    ├── [验证] 检查必要列 [date, asset, close, high, low]
    │
    ├── [排序] 按 asset + date 排序
    │
    ├── [Step 1] 计算 RSV（未成熟随机值）
    │   │
    │   ├── rolling_high = 按股票分组，过去 N 天最高价的最大值
    │   ├── rolling_low = 按股票分组，过去 N 天最低价的最小值
    │   │
    │   └── RSV = (Close - rolling_low) / (rolling_high - rolling_low) × 100
    │       │
    │       └── 边界处理: 当 high==low 时，RSV = 50（避免除零）
    │
    ├── [Step 2] 计算 K 值（EWM 平滑）
    │   │
    │   ├── alpha_k = 1/M1 = 1/3
    │   │
    │   └── K = RSV 的 EWM(alpha=alpha_k, adjust=False)
    │       │
    │       └── 初始值修正: K_0 = 50 × 2/3 + RSV_0 × 1/3
    │
    ├── [Step 3] 计算 D 值（EWM 平滑）
    │   │
    │   ├── alpha_d = 1/M2 = 1/3
    │   │
    │   └── D = K 的 EWM(alpha=alpha_d, adjust=False)
    │       │
    │       └── 初始值修正: D_0 = 50 × 2/3 + K_0 × 1/3
    │
    ├── [Step 4] 计算 J 值
    │   │
    │   └── J = 3 × K - 2 × D
    │
    └── [统计] 输出因子统计（均值、标准差、超买超卖比例）
```

**KDJ_J 因子公式**：

```
RSV(N) = (Close_t - Low_N) / (High_N - Low_N) × 100

K_t = K_{t-1} × (M1-1)/M1 + RSV_t × 1/M1
D_t = D_{t-1} × (M2-1)/M2 + K_t × 1/M2
J_t = 3 × K_t - 2 × D_t

参数默认值：
- N = 9（RSV 计算周期）
- M1 = 3（K值平滑周期）
- M2 = 3（D值平滑周期）
- K_0 = 50, D_0 = 50（初始值）
```

---

### Step 4: IC 计算（反向排名）

```
calculate_kdj_j_ic(factor_df, return_df)
    │
    ├── [验证] 检查必需列 [date, asset, kdj_j, forward_return]
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
    │   │      ├── J值全部相同? → IC = 0               │
    │   │      │                                       │
    │   │      └── 计算反向排名 IC:                     │
    │   │          │                                   │
    │   │          ├── [1] J值排名（升序）              │
    │   │          │       rank = J.rank(pct=True, ascending=True)
    │   │          │       # J最低 → rank=0, J最高 → rank=1
    │   │          │                                   │
    │   │          ├── [2] 反向得分                    │
    │   │          │       score = 1 - rank
    │   │          │       # J<0（超卖）→ score=1（最看好）
    │   │          │       # J>100（超买）→ score=0（最不看好）
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

**KDJ_J 因子特殊性**：

```
KDJ_J 含义：
┌────────────────────────────────────────────────────────────┐
│  J 值范围：理论上无界限，实际常见 [-50, 150]               │
│                                                            │
│  - J > 100：严重超买，价格可能回调 → 不看好                 │
│  - J < 0：严重超卖，价格可能反弹 → 看好                     │
│  - J 在 0-100 之间：正常区间                                │
│                                                            │
│  因此 KDJ_J 是"反向指标":                                   │
│  - J 越低 → 预期收益越高                                    │
│  - J 越高 → 预期收益越低                                    │
└────────────────────────────────────────────────────────────┘

反向排名处理:
  score = 1 - rank(J)
  
  示例（某日3只股票）:
  | 股票 | J值 | rank(J升序) | score=1-rank | 预期含义 |
  |------|-----|-------------|--------------|----------|
  | A    | -20 | 0.0         | 1.0          | 最超卖,最看好 |
  | B    | 50  | 0.5         | 0.5          | 中性     |
  | C    | 120 | 1.0         | 0.0          | 最超买,最不看好 |
```

---

### Step 6: 输出结果

```json
{
    "factor_name": "kdj_j_1d",
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
    └── factor_data.json.gz    ← close, high, low（原始价格数据）
    
cache/factor_data/
    └── return_data.json.gz    ← forward_return_1d（未来收益）

注意：KDJ_J 需要自己计算因子值，不能直接读取预计算因子。
```

---

## 📁 文件位置

| 文件 | 路径 |
|------|------|
| IC计算脚本 | `factor_ic/ic_kdj_j_1d.py` |
| 输出结果 | `cache/factor_ic/kdj_j_1d_ic.json` |
| 本文档 | `factor_ic/docs/kdj_j_1d_ic_flow.md` |

---

## 🔄 与其他因子的对比

| 因子 | IC计算方式 | 排序方向 | 因子计算来源 |
|------|------------|----------|--------------|
| RSI | reverse_rank_ic | 反向 | 缓存预计算 |
| **KDJ_J** | **reverse_rank_ic** | **反向** | **现场计算** |
| Bollinger_PB | reverse_rank_ic | 反向 | 现场计算 |
| Volume_Ratio | normal_rank_ic | 正向 | 缓存预计算 |
| Turnover_Surge | normal_rank_ic | 正向 | 现场计算 |
| Main_Inflow_Ratio | normal_rank_ic | 正向 | 缓存预计算 |

---

*文档结束*