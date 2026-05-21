# Turnover_Surge_1D IC 计算流程文档

> 生成时间: 2026-05-23 10:30 (北京时间)
> 审阅版本: v2.1（规范强化）
> 实测数据时间: 2026-05-23
> 更新内容:
>   1. [v2.0] 重构：使用 run_complex_factor_ic() 公共模块主入口（遵循 PROJECT.md 第92行强制规范）
>   2. [v2.0] 删除手写三模式分支（~200行冗余代码）
>   3. [v2.0] 使用 additional_factor_files 参数加载换手率数据
>   4. [v2.0] 代码量从389行降至158行（降幅75%）
>   5. [v2.0] 更新整体架构图：反映 run_complex_factor_ic 调用
>   6. [v2.1] 中间变量规范：daily_return 使用局部变量而非写入 DataFrame（遵循 factor-ic-analyzer skill）
>   7. [v2.1] EPSILON 模块级常量：添加 EPSILON = 1e-10（遵循模块级常量规范）
>   8. [v2.1] 除零防护：safe_avg_turnover.clip(lower=EPSILON)（遵循异常检测规范）
>   9. [v2.1] 异常检测：turnover_surge < 0 检测并标记 pd.NA（遵循异常检测而非静默修正规范）

---

## 📋 整体架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│              ic_turnover_surge_1d.py（重构版）                            │
├─────────────────────────────────────────────────────────────────────────┤
│  入口: main()                                                            │
│    ↓                                                                     │
│  [1] 调用 run_complex_factor_ic() 公共模块主入口                         │
│    │                                                                     │
│    ├── [1/4] 加载因子和收益数据（公共模块）                               │
│    │     │                                                               │
│    │     ├── load_factor_return_data()                                  │
│    │     │   ├── factor_cols=['close']                                  │
│    │     │   ├── additional_factor_files={'turnover_rate': ...}         │
│    │     │   └── 自动合并换手率数据                                       │
│    │     │                                                               │
│    │     └── 自动判断模式：skip/incremental/full                         │
│    │                                                                     │
│    ├── [2/4] 计算换手率突增因子（custom_factor_calculation）              │
│    │     │                                                               │
│    │     └── calculate_turnover_surge(factor_df, surge_window=5)        │
│    │         │                                                           │
│    │         ├── 计算5日换手率均值                                       │
│    │         ├── 计算换手率突增 = 当日换手率 / 5日均值                    │
│    │         ├── 计算涨跌幅                                              │
│    │         ├── 应用筛选条件（surge>1, return>0）                       │
│    │         └── 不满足条件的股票设为NaN                                  │
│    │                                                                     │
│    ├── [3/4] 计算 IC（公共模块）                                          │
│    │     │                                                               │
│    │     ├── calculate_ic_with_direction_verification()                 │
│    │     │   ├── Spearman IC 计算                                        │
│    │     │   ├── 五维度判断                                              │
│    │     │   └── Newey-West t统计量                                      │
│    │     │                                                               │
│    │     └── 增量模式：incremental_update_ic()                           │
│    │                                                                     │
│    └── [4/4] 构建输出并保存（公共模块）                                    │
│          │                                                               │
│          ├── build_ic_result()                                          │
│          │   ├── ic_metrics 结构                                        │
│          │   ├── sample_stats 统计                                      │
│          │   ├── rolling_ic_mean                                        │
│          │   └── 五维度判断字段                                          │
│          │                                                               │
│          └── save_ic_result()                                           │
│              └── 异常处理（PermissionError/OSError）                     │
│                                                                         │
│  [2] 输出结果摘要                                                         │
│    └── logger.info("结果摘要: IC均值/ICIR/更新模式")                      │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 🔍 详细流程步骤

### Step 1: 公共模块主入口调用

```
run_complex_factor_ic(
    factor_name='turnover_surge',
    factor_col='turnover_surge',
    factor_cols=['close'],
    custom_factor_calculation=calculate_turnover_surge,
    custom_factor_calculation_params={'surge_window': args.surge_window},
    additional_factor_files={
        'turnover_rate': DEFAULT_CACHE_DIR / 'turnover_rate_data.json.gz'
    },
    min_stocks=args.min_stocks,
    force_full=args.force_full,
    _logger=logger
)
    │
    ├── 公共模块内部流程（factor_ic_runner.py）
    │   │
    │   ├── [数据加载] load_factor_return_data()
    │   │   ├── 加载 close 列
    │   │   ├── 加载 turnover_rate 列（通过 additional_factor_files）
    │   │   ├── 自动合并数据
    │   │   └── 返回 (factor_df, return_df, raw_metadata)
    │   │
    │   ├── [模式判断] should_use_incremental()
    │   │   ├── 检查缓存日期 vs 数据日期
    │   │   └── 返回 UpdateMode 枚举
    │   │
    │   ├── [三模式分支]
    │   │   │
    │   │   ├── SKIP: 缓存已最新 → 直接返回 cached_data
    │   │   │
    │   │   ├── INCREMENTAL: 缓存滞后 → incremental_update_ic()
    │   │   │   ├── 先调用 custom_factor_calculation（换手率突增计算）
    │   │   │   ├── 计算缺失日期 IC
    │   │   │   ├── 合并数据
    │   │   │   └── 重算统计量
    │   │   │
    │   │   └── FULL: 缓存不存在 → 全量计算
    │   │       ├── 先调用 custom_factor_calculation（换手率突增计算）
    │   │       ├── calculate_ic_with_direction_verification()
    │   │       ├── build_ic_result()
    │   │       └── save_ic_result()
    │   │
    │   └── 返回 result 字典
    │
    └── 调用方防御性访问结果
        └── ic_metrics = result.get('ic_metrics', {})
        └── logger.info("结果摘要")
```

---

### Step 2: 换手率突增因子计算（因子特有逻辑）

```
calculate_turnover_surge(factor_df, surge_window=5)
    │
    ├── [入口] factor_df.copy()（遵循 MODULE.md DataFrame副本规范）
    │
    ├── [Step 1] 计算5日换手率均值
    │   │
    │   ├── avg_turnover = turnover_rate.groupby('asset').transform(
    │   │       lambda x: x.rolling(5, min_periods=5).mean()
    │   │   )
    │   │
    │   └── 参数说明:
    │       ├── window=5: 5日窗口（DEFAULT_SURGE_WINDOW）
    │       ├── min_periods=5: 最少需要5个数据点（业务决策）
    │       └── 按股票分组计算
    │
    ├── [Step 2] 计算换手率突增
    │   │
    │   └── turnover_surge = turnover_rate / avg_turnover
    │       │
    │       └── 因子定义: 当日换手率 / 过去5日换手率均值
    │
    ├── [Step 3] 计算涨跌幅
    │   │
    │   ├── prev_close = close.groupby('asset').transform(lambda x: x.shift(1))
    │   │
    │   └── daily_return = (close - prev_close) / prev_close
    │
    ├── [Step 4] 应用筛选条件
    │   │
    │   ├── 条件1: turnover_surge > 1（换手率高于近期均值）
    │   │
    │   ├── 条件2: daily_return > 0（当日上涨）
    │   │
    │   └── condition = (surge > 1) & (return > 0)
    │       │
    │       └── 不满足条件的股票: turnover_surge = np.nan
    │           ├── 不参与 IC 计算
    │           └── 体现资金异动信号筛选
    │
    └── [返回] factor_df（含 turnover_surge 列）
```

**筛选条件说明**：

```
换手率突增 + 上涨 = 资金异动信号

┌────────────────────────────────────────────────────────────┐
│  篮选逻辑:                                                  │
│                                                            │
│  条件1: turnover_surge > 1                                 │
│  → 当日换手率高于近期均值，表明资金关注度提升               │
│                                                            │
│  条件2: daily_return > 0                                   │
│  → 当日价格上涨，表明资金流入而非恐慌抛售                   │
│                                                            │
│  两个条件同时满足:                                          │
│  → 换手率突增伴随上涨 = 主力资金主动买入信号                │
│  → 预期后续继续上涨                                        │
│                                                            │
│  不满足条件的股票:                                          │
│  → 因子值设为 NaN，不参与 IC 计算                          │
└────────────────────────────────────────────────────────────┘
```

---

### Step 3: 公共模块 IC 计算

**公共模块统一处理（所有因子共享）**：

```
calculate_ic_with_direction_verification()
    │
    ├── Spearman IC 计算（正向因子，ascending=True）
    │   │
    │   ├── factor_rank = turnover_surge.rank(pct=True, ascending=True)
    │   ├── return_rank = forward_return.rank(pct=True, ascending=True)
    │   └── IC = factor_rank.corr(return_rank, method='spearman')
    │
    ├── 五维度判断（MODULE.md 规范）
    │   ├── statistical_significance（p<0.05）
    │   ├── factor_direction（方向验证）
    │   ├── economic_significance（|ic_mean|>0.03）
    │   ├── icir_stability（ICIR分级）
    │   └── ic_distribution_consistency（正比例判断）
    │
    ├── Newey-West t统计量
    │   ├── 自协方差对称性（k>0 乘以2）
    │   └── Bartlett权重
    │
    └── 返回 ic_result（含五维度字段）
```

---

### Step 4: 输出结构

```json
{
    "factor_name": "turnover_surge_1d",
    "calculation_date": "2026-05-21T23:00:00",
    "ic_metrics": {
        "ic_mean": 0.0345,
        "ic_std": 0.0123,
        "icir": 2.81,
        "p_value": 0.0001,
        "p_value_display": "p<0.001",
        "t_stat": 4.23,
        "positive_ratio": 0.72,
        "n_days": 500
    },
    "sample_stats": {
        "valid_days": 480,
        "avg_stocks_per_day": 3500,
        "period_start": "2025-01-01",
        "period_end": "2026-05-20"
    },
    "statistical_significance": {
        "is_significant": true,
        "p_value": 0.0001,
        "t_stat": 4.23,
        "significance_level": "***"
    },
    "factor_direction": {
        "direction": "positive",
        "confidence": "high",
        "ic_mean_sign": "positive"
    },
    "economic_significance": {
        "is_economically_significant": true,
        "ic_mean": 0.0345,
        "threshold": 0.03
    },
    "icir_stability": {
        "icir": 2.81,
        "stability_level": "优秀"
    },
    "ic_distribution_consistency": {
        "positive_ratio": 0.72,
        "is_consistent": true
    },
    "dates": ["2025-01-01", ...],
    "ic_values": [0.034, ...],
    "rolling_ic_mean": [0.032, ...],
    "update_mode": "full",
    "data_source": "cache/factor_data/factor_data.json.gz + turnover_rate_data.json.gz"
}
```

---

## 📊 关键指标含义

| 指标 | 含义 | 判断标准 |
|------|------|----------|
| **IC均值** | 因子预测能力 | > 0.05 = 有效；< -0.05 = 反向有效 |
| **ICIR** | IC稳定性 | > 0.5 = 可用；> 1.0 = 较好；> 2.0 = 很好 |
| **正比例** | IC > 0 的天数占比 | > 50% = 有预测能力 |

---

## 🔧 数据依赖

```
cache/factor_data/
    ├── turnover_rate_data.json.gz  ← 真实换手率（通过 additional_factor_files 加载）
    ├── factor_data.json.gz         ← close（收盘价）
    └── return_data.json.gz         ← forward_return_1d（未来收益）

特点：换手率突增因子需要现场计算，且有筛选条件。
```

---

## 📁 文件位置

| 文件 | 路径 |
|------|------|
| IC计算脚本 | `factor_ic/ic_turnover_surge_1d.py` |
| 输出结果 | `cache/factor_ic/turnover_surge_1d_ic_analysis_result.json` |
| 本文档 | `factor_ic/docs/ic_turnover_surge_1d_flow.md` |

---

## 🔄 与其他因子的对比

| 因子 | IC计算方式 | 排序方向 | 因子计算来源 | 篮选条件 | 公共模块入口 |
|------|------------|----------|--------------|----------|--------------|
| RSI | calculate_ic_with_direction_verification | 反向 | 缓存预计算 | 无 | run_simple_factor_ic |
| KDJ_J | calculate_ic_with_direction_verification | 反向 | 现场计算 | 无 | run_complex_factor_ic |
| Bollinger_PB | calculate_ic_with_direction_verification | 反向 | 现场计算 | 无 | run_complex_factor_ic |
| Volume_Ratio | calculate_ic_with_direction_verification | 正向 | 缓存预计算 | 无 | run_simple_factor_ic |
| **Turnover_Surge** | calculate_ic_with_direction_verification | **正向** | **现场计算** | **有** | **run_complex_factor_ic** |
| Main_Inflow_Ratio | calculate_ic_with_direction_verification | 正向 | 缓存预计算 | 无 | run_simple_factor_ic |

---

## 📝 规范遵循检查

| 规范位置 | 内容 | 当前实现 |
|---------|------|---------|
| PROJECT.md 第92行 | 禁止手写三模式分支 | ✓ 使用 run_complex_factor_ic() |
| PROJECT.md 第121-143行 | 违规示例对比 | ✓ 已删除手写分支 |
| PROJECT.md 第145-156行 | 正确示例对比 | ✓ 已实现 |
| MODULE.md DataFrame副本规范 | 函数入口 .copy() | ✓ calculate_turnover_surge 第62行 |
| factor-ic-analyzer skill | CLI异常处理堆栈保留 | ✓ logger.exception() |

---

## 📈 代码量对比

| 版本 | 行数 | 说明 |
|------|------|------|
| v1.24（旧版） | 389行 | 手写三模式分支 + 数据加载 |
| **v2.0（重构版）** | **158行** | **使用公共模块主入口** |
| 降幅 | **75%** | **删除231行冗余代码** |

---

*文档结束*