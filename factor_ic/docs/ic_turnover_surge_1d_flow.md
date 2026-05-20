# Turnover_Surge_1D IC 计算流程文档

> 生成时间: 2026-05-21 02:30 (北京时间)
> 审阅版本: v1.19
> 实测数据时间: 2026-05-20
> 更新内容:
>   1. [v1.1] 修复 ic_metrics 字段缺失问题：添加 p_value_display（遵循 MODULE.md 输出结构规范）
>   2. [v1.1] 修复 rolling_ic_mean NaN 处理：在数据生成阶段将 NaN 转为 None（遵循 PROJECT.md 规范）
>   3. [v1.1] 空数据返回路径添加 p_value_display 字段
>   4. [v1.1] 流程文档重命名：turnover_surge_1d_ic_flow.md → ic_turnover_surge_1d_flow.md（遵循 PROJECT.md 命名规范）
>   5. [v1.1] 跨脚本验证通过：ic_metrics 5 字段一致（RSI/布林带/KDJ/换手率突增）
>   6. [v1.2] 使用公共模块 calculate_ic_with_direction_verification 计算 IC（遵循 PROJECT.md 公共模块复用规范）
>   7. [v1.2] 添加五维度判断字段（statistical_significance、factor_direction 等）
>   8. [v1.2] 修复 sample_stats.total_days 语义：使用 raw_metadata['total_days']（遵循 PROJECT.md 输出字段语义规范）
>   9. [v1.2] 添加 DEFAULT_MIN_STOCKS 常量（遵循 PROJECT.md 参数传递规范）
>   10. [v1.2] 添加 update_mode='full' 返回标记（遵循 PROJECT.md 返回值标记规范）
>   11. [v1.2] 删除自定义 IC 计算逻辑，改用公共模块统一实现
>   12. [v1.3] 删除未使用的导入：scipy.stats, gc（遵循代码规范）
>   13. [v1.3] 重构主函数：添加 _full_recalculate 全量计算封装函数
>   14. [v1.3] 实现显式控制流架构：每个分支都有明确的 return（遵循 PROJECT.md 控制流规范）
>   15. [v1.3] 添加 skip 模式 update_mode 标记（遵循 PROJECT.md 返回值标记规范）
>   16. [v1.3] 添加 fallback_event 和 incremental_fallback 字段（遵循 PROJECT.md 返回值标记规范）
>   17. [v1.3] 增量模式 fallback 处理：换手率突增因子需要5日窗口计算，增量模式暂用全量计算替代
>   18. [v1.4] 修复异常处理类型不一致：区分 FileNotFoundError/ValueError/Exception，遵循 PROJECT.md 异常处理规范
>   19. [v1.4] 添加 sample_stats.avg_stocks_period 字段：口径范围说明，遵循 MODULE.md 输出结构统一性规范
>   20. [v1.4] 改进异常处理注释：说明为何保留 FileNotFoundError 原始类型
>   21. [v1.4] 改进增量模式注释：说明设计决策和技术原因
>   22. [v1.4] 修复跨脚本输出结构不一致：将 dates/ic_values/rolling_ic_mean 提升为顶层字段（遵循 MODULE.md 输出结构统一性规范）
>   23. [v1.5] 修复代码注释过时：第395行注释更新为顶层字段规范（遵循 MODULE.md 输出结构统一性规范）
>   24. [v1.5] 更新测试用例过时内容：函数名、输出结构、字段名、必需字段列表等（ic_series→顶层字段, significance→移除, n_days→valid_days）
>   25. [v1.5] 测试用例 TC007 重构：删除不存在的日期限制功能测试，改为缓存数据检查测试
>   26. [v1.6] 修复遗留 ic_series 注释：第341行和第488行注释更新为顶层字段说明（遵循 MODULE.md 输出结构统一性规范）
>   27. [v1.7] 修复 DataFrame 副作用问题：calculate_turnover_surge_factor 函数入口处添加 factor_df.copy()（遵循 MODULE.md DataFrame 参数副本规范）
>   28. [v1.7] MODULE.md 新增 DataFrame 参数副本规范章节：明确函数入口处必须先 .copy() 防止副作用
>   29. [v1.8] 补充滚动窗口参数业务决策注释：window=5, min_periods=5 的设计决策说明（遵循 MODULE.md 滚动窗口参数规范）
>   30. [v1.8] 补充 filter_stats 统计口径注释：说明 total_records 和 filtered_count 的统计口径（遵循 MODULE.md filter_stats 统计口径规范）
>   31. [v1.8] MODULE.md 新增滚动窗口参数规范章节：明确业务决策必须注释说明 min_periods 选择理由和影响范围
>   32. [v1.9] 补充 sample_stats 统计口径注释：avg_stocks_per_day 基于 dropna 后数据（遵循 MODULE.md 第1870行规范）
>   33. [v1.9] 补充函数参数预期注释：factor_df 可以含有 turnover_surge=None 的记录（遵循 MODULE.md 隐式行为显式化原则）
>   34. [v1.9] 补充 dropna 过滤注释：说明函数内部隐式行为和口径影响（遵循 MODULE.md 隐式行为显式化原则）
>   35. [v1.10] 修复 filter_stats 字段名语义混淆：filtered_count → valid_count（语义清晰：有效计数）
>   36. [v1.10] 修复 filter_stats 字段名语义混淆：filter_ratio → retention_ratio（语义清晰：保留比例）
>   37. [v1.10] MODULE.md 更新 filter_stats 统计口径规范：新增字段命名规范章节，禁止使用模糊命名
>   38. [v1.11] 修复异常处理链两层叠加：load_data_from_cache 底层抛出语义清晰异常（遵循 MODULE.md 异常处理链规范）
>   39. [v1.11] 修复异常处理链两层叠加：_full_recalculate 中间层裸 raise（不叠加消息）
>   40. [v1.11] MODULE.md 新增异常处理链规范章节：明确单层包装原则、底层语义清晰原则
>   41. [v1.12] 修复空数据返回值不完整：factor_data.empty 路径添加五维度判断和顶层字段（遵循 MODULE.md 输出结构统一性规范）
>   42. [v1.12] 修复空数据返回值不完整：ValueError 异常路径添加五维度判断和顶层字段（遵循 MODULE.md 输出结构统一性规范）
>   43. [v1.12] 调用方 _full_recalculate 直接访问 ic_data['factor_direction'] 等字段，空数据返回值必须完整
>   44. [v1.13] 修复变量命名语义混淆：pct_change → price_pct_change（遵循 MODULE.md 变量命名语义清晰原则规范）
>   45. [v1.13] MODULE.md 新增变量命名语义清晰原则规范：明确数据源前缀原则、上下文明确原则
>   46. [v1.14] 补充数据对齐验证：load_data_from_cache 中验证 factor_df 与 return_df 日期对齐（遵循 MODULE.md 数据对齐验证规范）
>   47. [v1.14] MODULE.md 新增数据对齐验证规范：避免静默丢失数据，选择交集日期
>   48. [v1.15] 修复极端值裁剪范围矛盾：clip(0.5, 10) -> clip(1.0, 10)（遵循 MODULE.md 极端值裁剪规范）
>   49. [v1.15] MODULE.md 新增极端值裁剪规范：裁剪范围必须与筛选条件一致
>   50. [v1.16] 删除未使用的导入：calculate_single_day_ic 和 calculate_ic_statistics（增量模式已 fallback）
>   51. [v1.16] 删除冗余的 update_mode 赋值：_full_recalculate 已设置，外部无需重复赋值
>   52. [v1.17] 补充主入口错误处理：if __name__ == '__main__' 添加 try-except 块（遵循 MODULE.md 主入口错误处理规范）
>   53. [v1.17] MODULE.md 新增主入口错误处理规范：异常不能直接暴露给用户，需提供友好提示
>   54. [v1.18] 修复 raw_metadata 统计口径错误：日期对齐前先记录原始范围（遵循 PROJECT.md 输出字段语义规范）
>   55. [v1.19] 修复空数据返回值字段不一致：补充 icir_stability、ic_distribution_consistency、filter_stats、t_stat（遵循 MODULE.md 输出结构统一性规范）
>   56. [v1.19] 修复空数据返回值字段不一致：删除 factor_stats 字段（正常路径无此字段）

---

## 📋 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    ic_turnover_surge_1d.py 主流程                │
├─────────────────────────────────────────────────────────────────┤
│  入口: main()                                                    │
│    ↓                                                             │
│  [1] 加载换手率数据（turnover_rate_data.json.gz）                 │
│    ↓                                                             │
│  [2] 加载收盘价数据（factor_data.json.gz）                        │
│    ↓                                                             │
│  [3] 加载收益数据（return_data.json.gz）                          │
│    ↓                                                             │
│  [4] 计算换手率突增因子（带筛选条件）                              │
│    ↓                                                             │
│  [5] 调用 calculate_turnover_surge_ic() 计算正向排名 IC           │
│    ↓                                                             │
│  [6] 保存结果到 JSON 文件                                          │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🔍 详细流程步骤

### Step 1: 数据加载

```
load_data_for_turnover_surge(n_days=500)
    │
    ├── [Step 1] 加载换手率数据
    │   │
    │   ├── 文件: cache/factor_data/turnover_rate_data.json.gz
    │   ├── 提取: [date, asset, turnover_rate]
    │   └── 过滤缺失值
    │
    ├── [Step 2] 加载收盘价数据
    │   │
    │   ├── 文件: cache/factor_data/factor_data.json.gz
    │   ├── 提取: [date, asset, close]
    │   └── 过滤缺失值
    │
    ├── [Step 3] 合并换手率和收盘价
    │   │
    │   └── factor_df = pd.merge(turnover_df, close_df, on=['date', 'asset'])
    │
    ├── [Step 4] 加载收益数据
    │   │
    │   ├── 文件: cache/factor_data/return_data.json.gz
    │   ├── 提取: [date, asset, forward_return_1d]
    │   └── 重命名: forward_return_1d → forward_return
    │
    └── 返回 (factor_df, return_df)
```

**关键区别**：换手率突增因子需要三个数据源：换手率、收盘价、收益数据。

---

### Step 2: 换手率突增因子计算（核心）

这是 `calculate_turnover_surge_factor()` 的计算流程：

```
calculate_turnover_surge_factor(factor_df, filter_conditions=True)
    │
    ├── [Step 1] 计算换手率突增因子
    │   │
    │   ├── 按股票分组，按日期排序
    │   │
    │   ├── 计算 5 日换手率均值:
    │   │   │
    │   │   └── turnover_ma = turnover_rate.rolling(window=5, min_periods=5).mean()
    │   │
    │   └── 计算换手率突增:
    │   │   │
    │   │   └── turnover_surge = turnover_rate / turnover_ma
    │   │
    │   └── 因子定义: turnover_surge = 当日换手率 / 过去5日换手率均值
    │
    ├── [Step 2] 计算当日涨跌幅
    │   │
    │   └── pct_change = close.pct_change()（按股票分组）
    │
    ├── [Step 3] 应用筛选条件（filter_conditions=True）
    │   │
    │   ├── 条件1: turnover_surge > 1（换手率高于近期均值）
    │   │
    │   ├── 条件2: pct_change > 0（当日上涨）
    │   │
    │   └── 同时满足两个条件才保留因子值，否则设为 None
    │       │
    │       └── 不满足条件的股票，turnover_surge 设为 None
    │
    ├── [Step 4] 极端值处理
    │   │
    │   └── turnover_surge.clip(0.5, 10)
    │       │
    │       └── 将因子值裁剪到 [0.5, 10] 范围
    │
    └── [统计] 输出筛选统计
        │
        ├── 总记录数
        ├── 换手率突增记录数（surge > 1）
        ├── 上涨记录数（pct_change > 0）
        ├── 同时满足两条件记录数
        └── 有效因子记录数
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
│  条件2: pct_change > 0                                     │
│  → 当日价格上涨，表明资金流入而非恐慌抛售                   │
│                                                            │
│  两个条件同时满足:                                          │
│  → 换手率突增伴随上涨 = 主力资金主动买入信号                │
│  → 预期后续继续上涨                                        │
│                                                            │
│  不满足条件的股票:                                          │
│  → 因子值设为 None，不参与 IC 计算                          │
└────────────────────────────────────────────────────────────┘
```

---

### Step 3: IC 计算（正向排名）

```
calculate_turnover_surge_ic(factor_df, return_df)
    │
    ├── [验证] 检查必需列 [date, asset, turnover_surge, forward_return]
    │
    ├── [合并] 按键合并
    │   │
    │   └── merged = pd.merge(factor_df, return_df, on=['date', 'asset'])
    │   │
    │   └── 只保留 turnover_surge 不为 None 的记录
    │
    ├── [遍历] 按日期分组，逐日计算 IC
    │   │
    │   └─────────────────────────────────────────────┐
    │   │                                             │
    │   │  for each date:                              │
    │   │      │                                       │
    │   │      ├── 股票数 < 10? → 跳过该日              │
    │   │      │                                       │
    │   │      └── 计算正向排名 IC:                     │
    │   │          │                                   │
    │   │          ├── factor_rank = turnover_surge.rank(pct=True, ascending=True)
    │   │          │                                   │
    │   │          ├── return_rank = forward_return.rank(pct=True, ascending=True)
    │   │          │                                   │
    │   │          └── IC = factor_rank.corr(return_rank, method='spearman')
    │   │                                              │
    │   └─────────────────────────────────────────────┘
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
    │       ├── |t_stat| > 3.29 → "***"（99.9%显著）
    │       ├── |t_stat| > 2.58 → "**"（99%显著）
    │       ├── |t_stat| > 1.96 → "*"（95%显著）
    │       └── 否则 → 无星号
    │
    └── 返回结果字典
```

---

### Step 4: 正向排名原理

**换手率突增因子特殊性**：

```
换手率突增因子含义：
┌────────────────────────────────────────────────────────────┐
│  turnover_surge = 当日换手率 / 过去5日换手率均值            │
│                                                            │
│  - surge > 1 且价格上涨 → 主力资金主动买入                  │
│  - surge < 1 → 资金关注度降低                              │
│                                                            │
│  通过筛选条件（surge > 1 且 pct_change > 0）后:              │
│  - surge 越高 → 资金异动越强烈 → 预期收益越高               │
│                                                            │
│  因此是"正向指标"，使用正向排名                             │
└────────────────────────────────────────────────────────────┘

正向排名处理:
  factor_rank = turnover_surge.rank(pct=True, ascending=True)
  
  示例（某日3只满足筛选条件的股票）:
  | 股票 | surge | 收益 | 排名关系 |
  |------|-------|------|----------|
  | A    | 3.0   | 8%   | surge高,收益高 → 正相关贡献 |
  | B    | 1.5   | 3%   | surge中,收益中 → 中性 |
  | C    | 1.2   | 1%   | surge低,收益低 → 正相关贡献 |
```

---

### Step 5: 输出结果

```json
{
    "factor_name": "turnover_surge_1d",
    "ic_metrics": {
        "ic_mean": 0.0345,
        "ic_std": 0.0123,
        "icir": 2.81,
        "positive_ratio": 0.72,
        "t_stat": 4.23,
        "significance": "***",
        "n_days": 500,
        "n_assets": 3500,
        "filter_stats": {
            "total_records": 1500000,
            "turnover_surge_count": 450000,
            "price_up_count": 750000,
            "both_conditions_count": 225000,
            "filter_ratio": 0.15
        },
        "summary": "IC均值=0.0345, ICIR=2.81, 正比例=72.0%, 因子有效"
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
| **筛选比例** | 满足筛选条件的股票比例 | 体现因子覆盖度 |

---

## 🔧 数据依赖

```
cache/factor_data/
    ├── turnover_rate_data.json.gz  ← 真实换手率（必需）
    ├── factor_data.json.gz         ← close（收盘价）
    └── return_data.json.gz         ← forward_return_1d（未来收益）

特点：换手率突增因子需要现场计算，且有筛选条件。
```

---

## 📁 文件位置

| 文件 | 路径 |
|------|------|
| IC计算脚本 | `factor_ic/ic_turnover_surge_1d.py` |
| 输出结果 | `cache/factor_ic/turnover_surge_1d_ic.json` |
| 本文档 | `factor_ic/docs/turnover_surge_1d_ic_flow.md` |

---

## 🔄 与其他因子的对比

| 因子 | IC计算方式 | 排序方向 | 因子计算来源 | 筛选条件 |
|------|------------|----------|--------------|----------|
| RSI | reverse_rank_ic | 反向 | 缓存预计算 | 无 |
| KDJ_J | reverse_rank_ic | 反向 | 现场计算 | 无 |
| Bollinger_PB | reverse_rank_ic | 反向 | 现场计算 | 无 |
| Volume_Ratio | normal_rank_ic | 正向 | 缓存预计算 | 无 |
| **Turnover_Surge** | **normal_rank_ic** | **正向** | **现场计算** | **有** |
| Main_Inflow_Ratio | normal_rank_ic | 正向 | 缓存预计算 | 无 |

---

*文档结束*