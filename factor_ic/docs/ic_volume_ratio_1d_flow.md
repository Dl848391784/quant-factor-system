     1|# 量比因子 IC 分析流程文档
     2|
     3|> 版本: v2.0
     4|> 生成时间: 2026-05-23 22:55 北京时间
     5|> 实测数据时间: 2026-05-23 22:55 北京时间（运行验证通过）
     6|> 脚本: ic_volume_ratio_1d.py（252行）
     7|> 更新内容:
     8|>   1. v1.0 首次创建流程文档
     9|>   2. v1.2 修复import位置、补充顶层字段、JSON序列化修复
    10|>   3. v1.3 代码质量优化（DEFAULT_MIN_STOCKS常量、NaN处理、min_stocks参数）
    11|>   4. v1.4 跨脚本一致性优化（2026-05-21）：
    12|>      - 函数注释更新：ic_series → dates/ic_values/rolling_ic_mean（顶层字段）
    13|>      - statistical_significance 添加 p_value_display 字段（跨脚本一致性）
    14|>      - 空数据分支已有 p_value_display（无需修改）
    15|>   5. v1.5 测试用例同步（2026-05-21 02:15）：
    16|>      - TC001预期日志添加min_stocks参数
    17|>      - nested_required字段添加p_value_display
    18|>      - 版本和时间标注同步更新
    19|>   6. v1.6 Newey-West 重构（2026-05-21 02:25）：
    20|>      - 改用公共模块 ic_calculator.py（Newey-West 标准）
    21|>      - statistical_significance 结构升级：添加 nw_lag, nw_lag_method, conclusion 字段
    22|>      - 五维度判断全部使用公共模块标准结构（与 ic_kdj_j_1d.py 对齐）
    23|>      - 空数据分支同步更新五维度结构
    24|>      - 实测结果：IC=-0.031, ICIR=0.31, t_stat=-7.13（NW调整）, nw_lag=5
    25|>   7. v1.7 废弃代码清理（2026-05-21 02:31）：
    26|>      - 删除废弃函数 calculate_daily_ic_series（已改用公共模块）
    27|>      - 删除废弃导入：spearmanr, scipy_stats_norm（公共模块已包含）
    28|>      - 删除废弃变量：scipy_stats_norm_cdf（不再使用）
    29|>      - 代码行数减少：776行 → 690行（精简86行）
    30|>      - 运行验证通过：IC=-0.031, ICIR=0.31
    31|>   8. v1.8 文档架构图更新（2026-05-21 02:35）：
    32|>      - 架构图更新：calculate_daily_ic_series → calculate_ic_with_direction_verification（公共模块）
    33|>      - 测试用例同步更新：nw_lag字段、五维度结构对齐、预期日志格式
    34|>      - 三文件版本同步：脚本v1.7、流程文档v1.8、测试用例v1.7
    35|>   9. v1.9 SKIP模式修复+异常处理优化（2026-05-23 22:45）：
    36|>      - SKIP模式不修改缓存对象（遵循 MODULE.md v3.7 规范）
    37|>      - 新增内部函数 do_full_recalculate() 处理 SKIP fallback
    38|>      - 数据加载异常分开处理（FileNotFoundError/JSONDecodeError/PermissionError/KeyError/Exception）
    39|>      - 步骤编号统一为 [N/4]
    40|>      - 日志取值路径统一使用 result['ic_metrics']
    41|>      - 代码行数：271行 → 236行（精简35行）
    42|>      - 运行验证通过（SKIP模式正常工作）
    43|>  10. v2.0 CLI参数解析+步骤日志完善（2026-05-23 22:55）：
    44|>      - 添加 CLI 参数解析：--force-full、--output、--min-stocks（与 ic_rsi_1d.py 保持一致）
    45|>      - FULL 模式添加 [2/4] 步骤日志（因子已在缓存中，跳过因子计算）
    46|>      - 移除冗余 convert_to_native_types 调用（save_ic_result 内部已处理）
    47|>      - 代码行数：236行 → 252行
    48|>      - CLI 参数验证通过：--force-full 成功触发全量计算
    49|
    50|---
    51|
    52|## 整体架构
    53|
    54|```
    55|┌─────────────────┐
    56|│  数据加载层      │
    57|│ load_factor_     │
    58|│ return_data()    │（公共模块）
    59|└─────────────────┘
    60|         │
    61|         ▼
    62|┌─────────────────┐
    63|│  模式判断层      │
    64|│ should_use_      │
    65|│ incremental()    │（公共模块）
    66|└─────────────────┘
    67|         │
    68|    ┌────┴────┐
    69|    │  三模式  │
    70|    ▼    ▼    ▼
    71|┌────┐ ┌────┐ ┌────┐
    72|│SKIP│ │INCR│ │FULL│
    73|└────┘ └────┘ └────┘
    74|    │    │    │
    75|    │    │    ▼
    76|    │    │  ┌─────────────────┐
    77|    │    │  │ do_full_        │
    78|    │    │  │ recalculate()   │（内部函数）
    79|    │    │  └─────────────────┘
    80|    │    │         │
    81|    │    ▼         ▼
    82|    │  ┌─────────────────┐
    83|    │  │ incremental_    │
    84|    │  │ update_ic()     │（公共模块）
    85|    │  └─────────────────┘
    86|    │         │
    87|    ▼    ▼    ▼
    88|┌─────────────────┐
    89|│  结果输出层      │
    90|│ build_ic_result │（公共模块）
    91|│ save_ic_result  │
    92|└─────────────────┘
    93|```
    94|
    95|---
    96|
    97|## 详细流程步骤
    98|
    99|### Step 1: 数据加载（[1/4]）
   100|
   101|**函数:** `load_factor_return_data()`（公共模块）
   102|
   103|**输入:** 缓存文件路径
   104|- `data_fetchers/result/factor_data.json.gz`（因子数据）
   105|- `data_fetchers/result/factor_ic_data.json.gz`（收益数据）
   106|
   107|**处理逻辑:**
   108|
   109|```
   110|1. 加载因子数据（gzip JSON）
   111|   └───────────────────────────────────┐
   112|   │ factor_df = pd.DataFrame(data)     │
   113|   │ 列: date, asset, volume_ratio_5     │
   114|   └───────────────────────────────────┘
   115|
   116|2. 加载收益数据（gzip JSON）
   117|   └───────────────────────────────────┐
   118|   │ return_df = pd.DataFrame(data)     │
   119|   │ 列: date, asset, forward_return_1d │
   120|   └───────────────────────────────────┘
   121|
   122|3. 记录原始数据范围（dropna 前）
   123|   ┌───────────────────────────────────┐
   124|   │ raw_period_start = min(date)       │
   125|   │ raw_period_end = max(date)         │
   126|   │ raw_total_days = nunique(date)     │
   127|   └───────────────────────────────────┘
   128|
   129|4. 过滤缺失值
   130|   ┌───────────────────────────────────┐
   131|   │ factor_df.dropna()                 │
   132|   │ return_df.dropna()                 │
   133|   └───────────────────────────────────┘
   134|
   135|5. 验证日期对齐（MODULE.md 数据对齐验证规范）
   136|   ┌───────────────────────────────────┐
   137|   │ factor_dates vs return_dates       │
   138|   │ 不对齐 → 选择交集日期              │
   139|   │ 打印对齐信息                       │
   140|   └───────────────────────────────────┘
   141|
   142|6. 异常处理（分开处理多种类型）
   143|   ┌───────────────────────────────────┐
   144|   │ FileNotFoundError → 数据源缺失     │
   145|   │ JSONDecodeError → 缓存损坏        │
   146|   │ PermissionError → 权限错误        │
   147|   │ KeyError → 数据结构错误           │
   148|   │ Exception → 未预期错误            │
   149|   └───────────────────────────────────┘
   150|
   151|7. 返回过滤后数据 + raw_metadata
   152|```
   153|
   154|**输出:**
   155|```python
   156|(factor_df, return_df, raw_metadata)
   157|# raw_metadata = {
   158|#   'period_start': str,
   159|#   'period_end': str,
   160|#   'total_days': int
   161|# }
   162|```
   163|
   164|---
   165|
   166|### Step 2: 模式判断
   167|
   168|**函数:** `should_use_incremental()`（公共模块）
   169|
   170|**判断逻辑:**
   171|
   172|```
   173|缓存不存在 → FULL（全量计算）
   174|缓存存在 → 读取 existing_dates
   175|比较 existing_dates vs factor_dates:
   176|  existing_dates ⊇ factor_dates → SKIP（跳过）
   177|  factor_dates 有缺失 → INCREMENTAL（增量）
   178|```
   179|
   180|---
   181|
   182|### Step 3: SKIP 模式处理（新增规范）
   183|
   184|**核心原则:** SKIP 模式不修改缓存对象，直接返回原数据。
   185|
   186|**处理逻辑:**
   187|
   188|```
   189|┌─────────────────────────────────────┐
   190|│ if mode == UpdateMode.SKIP:         │
   191|│   cached_data = json.load(cache)    │
   192|│   # 不修改 cached_data              │
   193|│   return cached_data                │
   194|│                                     │
   195|│   except FileNotFoundError:         │
   196|│     # fallback 到全量计算            │
   197|│     return do_full_recalculate()    │
   198|└─────────────────────────────────────┘
   199|```
   200|
   201|**为何不修改缓存对象:**
   202|
   203|| 原因 | 说明 |
   204||------|------|
   205|| 内存文件一致性 | 修改后不持久化，调用方数据与文件不同步 |
   206|| 行为可预测 | 下次读取时缓存内容不变，行为一致 |
   207|| 遵循最小修改原则 | SKIP 模式语义是"跳过"，不应有任何修改 |
   208|
   209|---
   210|
   211|### Step 4: INCREMENTAL 模式处理
   212|
   213|**函数:** `incremental_update_ic()`（公共模块）
   214|
   215|**步骤:**
   216|
   217|```
   218|[2/4] 因子已在缓存中，跳过因子计算
   219|[3/4] 执行增量 IC 计算
   220|      ┌─────────────────────────────────┐
   221|      │ 读取现有缓存                     │
   222|      │ 确定缺失日期                     │
   223|      │ 计算缺失日期 IC（复用核心函数）   │
   224|      │ 合并数据（去重）                 │
   225|      │ 重算统计指标                     │
   226|      └─────────────────────────────────┘
   227|```
   228|
   229|---
   230|
   231|### Step 5: FULL 模式处理
   232|
   233|**内部函数:** `do_full_recalculate()`
   234|
   235|**步骤:**
   236|
   237|```
   238|[3/4] 计算每日 IC
   239|      ┌─────────────────────────────────┐
   240|      │ calculate_ic_with_direction_    │
   241|      │ verification()（公共模块）       │
   242|      └─────────────────────────────────┘
   243|
   244|[4/4] 构建输出并保存
   245|      ┌─────────────────────────────────┐
   246|      │ build_ic_result()               │
   247|      │ convert_to_native_types()       │
   248|      │ save_ic_result()                │
   249|      └─────────────────────────────────┘
   250|```
   251|
   252|---
   253|
   254|### Step 6: 结果输出
   255|
   256|**输出结构:**
   257|
   258|```json
   259|{
   260|  "factor_name": "volume_ratio_1d",
   261|  "calculation_date": "2026-05-23",
   262|  "period": {
   263|    "start": "2024-02-06",
   264|    "end": "2026-05-15"
   265|  },
   266|  "ic_metrics": {
   267|    "ic_mean": -0.031,
   268|    "ic_std": 0.10,
   269|    "icir": 0.31,
   270|    "p_value": 9.86e-13,
   271|    "p_value_display": "9.86e-13"
   272|  },
   273|  "sample_stats": {
   274|    "total_days": 545,
   275|    "valid_days": 514,
   276|    "avg_stocks_per_day": 2720,
   277|    "avg_stocks_period": {
   278|      "start": "2024-02-06",
   279|      "end": "2026-05-15",
   280|      "description": "过滤后每日平均股票数（dropna 后）"
   281|    }
   282|  },
   283|  "statistical_significance": {
   284|    "t_stat": -7.13,
   285|    "p_value": 9.86e-13,
   286|    "p_value_display": "9.86e-13",
   287|    "nw_lag": 5,
   288|    "nw_lag_method": "newey_west",
   289|    "is_significant": true,
   290|    "conclusion": "|t|=7.13 > 1.96，统计显著"
   291|  },
   292|  "factor_direction": {
   293|    "ic_mean": -0.031,
   294|    "ic_mean_sign": "negative",
   295|    "direction_usage": "反向因子",
   296|    "conclusion": "IC均值=-0.031<0，反向因子"
   297|  },
   298|  "economic_significance": {
   299|    "abs_ic_mean": 0.031,
   300|    "level": "weak",
   301|    "is_economically_significant": true,
   302|    "conclusion": "|IC|=0.031 >= 0.03，弱显著"
   303|  },
   304|  "icir_stability": {
   305|    "icir": 0.31,
   306|    "level": "unusable",
   307|    "is_stable": true,
   308|    "conclusion": "ICIR=0.31 < 0.5，不显著"
   309|  },
   310|  "ic_distribution_consistency": {
   311|    "positive_ratio": 0.35,
   312|    "ic_mean_sign": "negative",
   313|    "consistency_type": "consistent_with_negative",
   314|    "is_consistent": true,
   315|    "conclusion": "正IC比例=35%，分布正常（反向因子）"
   316|  },
   317|  "dates": ["..."],
   318|  "ic_values": ["..."],
   319|  "rolling_ic_mean": ["..."],
   320|  "positive_ratio": 0.35,
   321|  "n_assets": 2720,
   322|  "summary": {
   323|    "ic_performance": "IC均值=-0.031, ICIR=0.31",
   324|    "statistical_significance": "|t|=7.13 > 1.96，统计显著",
   325|    "factor_direction": "IC均值=-0.031<0，反向因子",
   326|    "economic_significance": "|IC|=0.031 >= 0.03，弱显著",
   327|    "recommendation": "请结合五维度判断综合评估"
   328|  },
   329|  "factor_stats": {
   330|    "factor_name": "volume_ratio_1d",
   331|    "return_period": "1d",
   332|    "data_source": "data_fetchers/result/factor_data.json.gz",
   333|    "total_days": 545,
   334|    "valid_days": 514
   335|  },
   336|  "factor_col": "volume_ratio_5",
   337|  "update_mode": "full"
   338|}
   339|```
   340|
   341|---
   342|
   343|## 关键指标说明
   344|
   345|### 五维度判断（MODULE.md 规范）
   346|
   347|| 维度 | 指标 | 判断规则 | 说明 |
   348||------|------|---------|------|
   349|| **第1维：统计显著性** | t_stat, p_value | |t| > 1.96 ↔ p < 0.05 | 统计检验是否显著 |
   350|| **第2维：因子方向** | ic_mean符号 | ic_mean < -0.03 → 反向因子 | IC均值确定因子方向 |
   351|| **第3维：经济显著性** | |ic_mean| | |IC| >= 0.03 → 弱显著 | 因子预测能力强度 |
   352|| **第4维：ICIR稳定性** | ICIR | ICIR >= 0.5 → 可用 | IC信息比强度 |
   353|| **第5维：IC分布一致性** | positive_ratio | 反向因子：< 45% 正IC → 分布正常 | IC方向一致性 |
   354|
   355|---
   356|
   357|## 因子特性说明
   358|
   359|**量比因子（volume_ratio_5）：**
   360|
   361|| 特性 | 说明 |
   362||------|------|
   363|| **因子定义** | 当日成交量 / 5日平均成交量 |
   364|| **因子类型** | 反向因子（实测 ic_mean = -0.031） |
   365|| **分层逻辑** | 高量比 → Layer 1（反向因子分层） |
   366|
   367|**注意：** 因子方向必须根据实际 IC 测试结果确定，不能预设。
   368|
   369|---
   370|
   371|## 常见问题
   372|
   373|### Q1: SKIP 模式为何不修改缓存对象？
   374|
   375|**原因：**
   376|- 修改 `cached_data['update_mode'] = 'skip'` 后不持久化
   377|- 内存数据与文件不一致，下次读取行为不可预测
   378|- SKIP 模式语义是"跳过"，不应有任何修改
   379|
   380|### Q2: 为什么 valid_days < total_days？
   381|
   382|**原因：**
   383|- 因子数据缺失导致部分日期无法计算 IC
   384|- 股票数不足（< 10 只）导致日期被跳过
   385|- 收益数据等待（次日收益未收盘）
   386|
   387|### Q3: 如何判断因子有效性？
   388|
   389|**判断标准：**
   390|1. **统计显著：** |t| > 1.96（p < 0.05）
   391|2. **经济显著：** |ic_mean| > 0.03
   392|3. **ICIR可用：** ICIR > 0.5
   393|4. **稳定性：** IC_std < 0.15
   394|5. **一致性：** 正 IC 比例与 IC 方向一致
   395|
   396|---
   397|
   398|## 参考规范
   399|
   400|- PROJECT.md: SKIP 模式缓存对象处理规范（第319-360行）
   401|- PROJECT.md: 主函数数据加载异常处理规范（第100-113行）
   402|- MODULE.md: 输出结构统一性规范
   403|- MODULE.md: 五维度判断规范
   404|- MODULE.md: 数据对齐验证规范