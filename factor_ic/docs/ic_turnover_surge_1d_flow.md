     1|# Turnover_Surge_1D IC 计算流程文档
     2|
     3|> 生成时间: 2026-05-23 11:45 (北京时间)
     4|> 审阅版本: v2.2（异常检测顺序修正）
     5|> 实测数据时间: 2026-05-23
     6|> 更新内容:
     7|>   1. [v2.0] 重构：使用 run_complex_factor_ic() 公共模块主入口（遵循 PROJECT.md 第92行强制规范）
     8|>   2. [v2.0] 删除手写三模式分支（~200行冗余代码）
     9|>   3. [v2.0] 使用 additional_factor_files 参数加载换手率数据
    10|>   4. [v2.0] 代码量从389行降至158行（降幅75%）
    11|>   5. [v2.0] 更新整体架构图：反映 run_complex_factor_ic 调用
    12|>   6. [v2.1] 中间变量规范：daily_return 使用局部变量而非写入 DataFrame（遵循 factor-ic-analyzer skill）
    13|>   7. [v2.1] EPSILON 模块级常量：添加 EPSILON = 1e-10（遵循模块级常量规范）
    14|>   8. [v2.1] 除零防护：safe_avg_turnover.clip(lower=EPSILON)（遵循异常检测规范）
    15|>   9. [v2.1] 异常检测：turnover_surge < 0 检测并标记 pd.NA（遵循异常检测而非静默修正规范）
    16|>  10. [v2.2] 异常检测顺序修正：先检测数据质量异常（Step 3），再应用业务筛选条件（Step 5）
    17|>  11. [v2.2] 更新因子计算流程图：反映正确的异常检测位置（遵循异常处理顺序规范）
    18|
    19|---
    20|
    21|## 📋 整体架构
    22|
    23|```
    24|┌─────────────────────────────────────────────────────────────────────────┐
    25|│              ic_turnover_surge_1d.py（重构版）                            │
    26|├─────────────────────────────────────────────────────────────────────────┤
    27|│  入口: main()                                                            │
    28|│    ↓                                                                     │
    29|│  [1] 调用 run_complex_factor_ic() 公共模块主入口                         │
    30|│    │                                                                     │
    31|│    ├── [1/4] 加载因子和收益数据（公共模块）                               │
    32|│    │     │                                                               │
    33|│    │     ├── load_factor_return_data()                                  │
    34|│    │     │   ├── factor_cols=['close']                                  │
    35|│    │     │   ├── additional_factor_files={'turnover_rate': ...}         │
    36|│    │     │   └── 自动合并换手率数据                                       │
    37|│    │     │                                                               │
    38|│    │     └── 自动判断模式：skip/incremental/full                         │
    39|│    │                                                                     │
    40|│    ├── [2/4] 计算换手率突增因子（custom_factor_calculation）              │
    41|│    │     │                                                               │
    42|│    │     └── calculate_turnover_surge(factor_df, surge_window=5)        │
    43|│    │         │                                                           │
    44|│    │         ├── 计算5日换手率均值                                       │
    45|│    │         ├── 计算换手率突增 = 当日换手率 / 5日均值                    │
    46|│    │         ├── 计算涨跌幅                                              │
    47|│    │         ├── 应用筛选条件（surge>1, return>0）                       │
    48|│    │         └── 不满足条件的股票设为NaN                                  │
    49|│    │                                                                     │
    50|│    ├── [3/4] 计算 IC（公共模块）                                          │
    51|│    │     │                                                               │
    52|│    │     ├── calculate_ic_with_direction_verification()                 │
    53|│    │     │   ├── Spearman IC 计算                                        │
    54|│    │     │   ├── 五维度判断                                              │
    55|│    │     │   └── Newey-West t统计量                                      │
    56|│    │     │                                                               │
    57|│    │     └── 增量模式：incremental_update_ic()                           │
    58|│    │                                                                     │
    59|│    └── [4/4] 构建输出并保存（公共模块）                                    │
    60|│          │                                                               │
    61|│          ├── build_ic_result()                                          │
    62|│          │   ├── ic_metrics 结构                                        │
    63|│          │   ├── sample_stats 统计                                      │
    64|│          │   ├── rolling_ic_mean                                        │
    65|│          │   └── 五维度判断字段                                          │
    66|│          │                                                               │
    67|│          └── save_ic_result()                                           │
    68|│              └── 异常处理（PermissionError/OSError）                     │
    69|│                                                                         │
    70|│  [2] 输出结果摘要                                                         │
    71|│    └── logger.info("结果摘要: IC均值/ICIR/更新模式")                      │
    72|└─────────────────────────────────────────────────────────────────────────┘
    73|```
    74|
    75|---
    76|
    77|## 🔍 详细流程步骤
    78|
    79|### Step 1: 公共模块主入口调用
    80|
    81|```
    82|run_complex_factor_ic(
    83|    factor_name='turnover_surge',
    84|    factor_col='turnover_surge',
    85|    factor_cols=['close'],
    86|    custom_factor_calculation=calculate_turnover_surge,
    87|    custom_factor_calculation_params={'surge_window': args.surge_window},
    88|    additional_factor_files={
    89|        'turnover_rate': DEFAULT_CACHE_DIR / 'turnover_rate_data.json.gz'
    90|    },
    91|    min_stocks=args.min_stocks,
    92|    force_full=args.force_full,
    93|    _logger=logger
    94|)
    95|    │
    96|    ├── 公共模块内部流程（factor_ic_runner.py）
    97|    │   │
    98|    │   ├── [数据加载] load_factor_return_data()
    99|    │   │   ├── 加载 close 列
   100|    │   │   ├── 加载 turnover_rate 列（通过 additional_factor_files）
   101|    │   │   ├── 自动合并数据
   102|    │   │   └── 返回 (factor_df, return_df, raw_metadata)
   103|    │   │
   104|    │   ├── [模式判断] should_use_incremental()
   105|    │   │   ├── 检查缓存日期 vs 数据日期
   106|    │   │   └── 返回 UpdateMode 枚举
   107|    │   │
   108|    │   ├── [三模式分支]
   109|    │   │   │
   110|    │   │   ├── SKIP: 缓存已最新 → 直接返回 cached_data
   111|    │   │   │
   112|    │   │   ├── INCREMENTAL: 缓存滞后 → incremental_update_ic()
   113|    │   │   │   ├── 先调用 custom_factor_calculation（换手率突增计算）
   114|    │   │   │   ├── 计算缺失日期 IC
   115|    │   │   │   ├── 合并数据
   116|    │   │   │   └── 重算统计量
   117|    │   │   │
   118|    │   │   └── FULL: 缓存不存在 → 全量计算
   119|    │   │       ├── 先调用 custom_factor_calculation（换手率突增计算）
   120|    │   │       ├── calculate_ic_with_direction_verification()
   121|    │   │       ├── build_ic_result()
   122|    │   │       └── save_ic_result()
   123|    │   │
   124|    │   └── 返回 result 字典
   125|    │
   126|    └── 调用方防御性访问结果
   127|        └── ic_metrics = result.get('ic_metrics', {})
   128|        └── logger.info("结果摘要")
   129|```
   130|
   131|---
   132|
   133|### Step 2: 换手率突增因子计算（因子特有逻辑）
   134|
   135|```
   136|calculate_turnover_surge(factor_df, surge_window=5)
   137|    │
   138|    ├── [入口] factor_df.copy()（遵循 MODULE.md DataFrame副本规范）
   139|    │
   140|    ├── [Step 1] 计算5日换手率均值（局部变量）
   141|    │   │
   142|    │   ├── avg_turnover = turnover_rate.groupby('asset').transform(
   143|    │   │       lambda x: x.rolling(5, min_periods=5).mean()
   144|    │   │   )
   145|    │   │
   146|    │   └── 参数说明:
   147|    │       ├── window=5: 5日窗口（DEFAULT_SURGE_WINDOW）
   148|    │       ├── min_periods=5: 最少需要5个数据点（业务决策）
   149|    │       └── 按股票分组计算
   150|    │
   151|    ├── [Step 2] 计算换手率突增（除零防护）
   152|    │   │
   153|    │   ├── safe_avg_turnover = avg_turnover.clip(lower=EPSILON)
   154|    │   │
   155|    │   └── turnover_surge = turnover_rate / safe_avg_turnover
   156|    │       │
   157|    │       └── 因子定义: 当日换手率 / 过去5日换手率均值
   158|    │
   159|    ├── [Step 3] 异常检测（先于筛选条件）
   160|    │   │
   161|    │   ├── 检测异常负值:
   162|    │   │   ├── abnormal_mask = turnover_surge < 0
   163|    │   │   └── 异常原因: turnover_rate/avg_turnover理论上恒>=0，负值说明数据异常
   164|    │   │
   165|    │   ├── 处理异常:
   166|    │   │   ├── logger.warning(f"检测到 {abnormal_count} 个异常换手率突增（负值）")
   167|    │   │   └── turnover_surge.where(~abnormal_mask, pd.NA)
   168|    │   │
   169|    │   └── 注意: 异常检测必须在筛选条件之前（否则 surge>1 会排除 surge<0）
   170|    │
   171|    ├── [Step 4] 计算涨跌幅（局部变量）
   172|    │   │
   173|    │   ├── prev_close = close.groupby('asset').transform(lambda x: x.shift(1))
   174|    │   │
   175|    │   └── daily_return = (close - prev_close) / prev_close.clip(lower=EPSILON)
   176|    │       └── 使用局部变量，不污染输出 DataFrame（遵循中间变量规范）
   177|    │
   178|    ├── [Step 5] 应用业务筛选条件
   179|    │   │
   180|    │   ├── 条件1: turnover_surge > 1（换手率高于近期均值）
   181|    │   │
   182|    │   ├── 条件2: daily_return > 0（当日上涨）
   183|    │   │
   184|    │   └── condition = (surge > 1) & (return > 0)
   185|    │       │
   186|    │       └── 不满足条件的股票: turnover_surge = pd.NA
   187|    │           ├── 不参与 IC 计算
   188|    │           └── 体现资金异动信号筛选
   189|    │
   190|    └── [返回] factor_df（含 turnover_surge 列）
   191|```
   192|
   193|**筛选条件说明**：
   194|
   195|```
   196|换手率突增 + 上涨 = 资金异动信号
   197|
   198|┌────────────────────────────────────────────────────────────┐
   199|│  篮选逻辑:                                                  │
   200|│                                                            │
   201|│  条件1: turnover_surge > 1                                 │
   202|│  → 当日换手率高于近期均值，表明资金关注度提升               │
   203|│                                                            │
   204|│  条件2: daily_return > 0                                   │
   205|│  → 当日价格上涨，表明资金流入而非恐慌抛售                   │
   206|│                                                            │
   207|│  两个条件同时满足:                                          │
   208|│  → 换手率突增伴随上涨 = 主力资金主动买入信号                │
   209|│  → 预期后续继续上涨                                        │
   210|│                                                            │
   211|│  不满足条件的股票:                                          │
   212|│  → 因子值设为 NaN，不参与 IC 计算                          │
   213|└────────────────────────────────────────────────────────────┘
   214|```
   215|
   216|---
   217|
   218|### Step 3: 公共模块 IC 计算
   219|
   220|**公共模块统一处理（所有因子共享）**：
   221|
   222|```
   223|calculate_ic_with_direction_verification()
   224|    │
   225|    ├── Spearman IC 计算（正向因子，ascending=True）
   226|    │   │
   227|    │   ├── factor_rank = turnover_surge.rank(pct=True, ascending=True)
   228|    │   ├── return_rank = forward_return.rank(pct=True, ascending=True)
   229|    │   └── IC = factor_rank.corr(return_rank, method='spearman')
   230|    │
   231|    ├── 五维度判断（MODULE.md 规范）
   232|    │   ├── statistical_significance（p<0.05）
   233|    │   ├── factor_direction（方向验证）
   234|    │   ├── economic_significance（|ic_mean|>0.03）
   235|    │   ├── icir_stability（ICIR分级）
   236|    │   └── ic_distribution_consistency（正比例判断）
   237|    │
   238|    ├── Newey-West t统计量
   239|    │   ├── 自协方差对称性（k>0 乘以2）
   240|    │   └── Bartlett权重
   241|    │
   242|    └── 返回 ic_result（含五维度字段）
   243|```
   244|
   245|---
   246|
   247|### Step 4: 输出结构
   248|
   249|```json
   250|{
   251|    "factor_name": "turnover_surge_1d",
   252|    "calculation_date": "2026-05-21T23:00:00",
   253|    "ic_metrics": {
   254|        "ic_mean": 0.0345,
   255|        "ic_std": 0.0123,
   256|        "icir": 2.81,
   257|        "p_value": 0.0001,
   258|        "p_value_display": "p<0.001",
   259|        "t_stat": 4.23,
   260|        "positive_ratio": 0.72,
   261|        "n_days": 500
   262|    },
   263|    "sample_stats": {
   264|        "valid_days": 480,
   265|        "avg_stocks_per_day": 3500,
   266|        "period_start": "2025-01-01",
   267|        "period_end": "2026-05-20"
   268|    },
   269|    "statistical_significance": {
   270|        "is_significant": true,
   271|        "p_value": 0.0001,
   272|        "t_stat": 4.23,
   273|        "significance_level": "***"
   274|    },
   275|    "factor_direction": {
   276|        "direction": "positive",
   277|        "confidence": "high",
   278|        "ic_mean_sign": "positive"
   279|    },
   280|    "economic_significance": {
   281|        "is_economically_significant": true,
   282|        "ic_mean": 0.0345,
   283|        "threshold": 0.03
   284|    },
   285|    "icir_stability": {
   286|        "icir": 2.81,
   287|        "stability_level": "优秀"
   288|    },
   289|    "ic_distribution_consistency": {
   290|        "positive_ratio": 0.72,
   291|        "is_consistent": true
   292|    },
   293|    "dates": ["2025-01-01", ...],
   294|    "ic_values": [0.034, ...],
   295|    "rolling_ic_mean": [0.032, ...],
   296|    "update_mode": "full",
   297|    "data_source": "data_fetchers/result/factor_data.json.gz + turnover_rate_data.json.gz"
   298|}
   299|```
   300|
   301|---
   302|
   303|## 📊 关键指标含义
   304|
   305|| 指标 | 含义 | 判断标准 |
   306||------|------|----------|
   307|| **IC均值** | 因子预测能力 | > 0.05 = 有效；< -0.05 = 反向有效 |
   308|| **ICIR** | IC稳定性 | > 0.5 = 可用；> 1.0 = 较好；> 2.0 = 很好 |
   309|| **正比例** | IC > 0 的天数占比 | > 50% = 有预测能力 |
   310|
   311|---
   312|
   313|## 🔧 数据依赖
   314|
   315|```
   316|data_fetchers/result/
   317|    ├── turnover_rate_data.json.gz  ← 真实换手率（通过 additional_factor_files 加载）
   318|    ├── factor_data.json.gz         ← close（收盘价）
   319|    └── return_data.json.gz         ← forward_return_1d（未来收益）
   320|
   321|特点：换手率突增因子需要现场计算，且有筛选条件。
   322|```
   323|
   324|---
   325|
   326|## 📁 文件位置
   327|
   328|| 文件 | 路径 |
   329||------|------|
   330|| IC计算脚本 | `factor_ic/ic_turnover_surge_1d.py` |
   331|| 输出结果 | `factor_ic/result/turnover_surge_1d_ic_analysis_result.json` |
   332|| 本文档 | `factor_ic/docs/ic_turnover_surge_1d_flow.md` |
   333|
   334|---
   335|
   336|## 🔄 与其他因子的对比
   337|
   338|| 因子 | IC计算方式 | 排序方向 | 因子计算来源 | 篮选条件 | 公共模块入口 |
   339||------|------------|----------|--------------|----------|--------------|
   340|| RSI | calculate_ic_with_direction_verification | 反向 | 缓存预计算 | 无 | run_simple_factor_ic |
   341|| KDJ_J | calculate_ic_with_direction_verification | 反向 | 现场计算 | 无 | run_complex_factor_ic |
   342|| Bollinger_PB | calculate_ic_with_direction_verification | 反向 | 现场计算 | 无 | run_complex_factor_ic |
   343|| Volume_Ratio | calculate_ic_with_direction_verification | 正向 | 缓存预计算 | 无 | run_simple_factor_ic |
   344|| **Turnover_Surge** | calculate_ic_with_direction_verification | **正向** | **现场计算** | **有** | **run_complex_factor_ic** |
   345|| Main_Inflow_Ratio | calculate_ic_with_direction_verification | 正向 | 缓存预计算 | 无 | run_simple_factor_ic |
   346|
   347|---
   348|
   349|## 📝 规范遵循检查
   350|
   351|| 规范位置 | 内容 | 当前实现 |
   352||---------|------|---------|
   353|| PROJECT.md 第92行 | 禁止手写三模式分支 | ✓ 使用 run_complex_factor_ic() |
   354|| PROJECT.md 第121-143行 | 违规示例对比 | ✓ 已删除手写分支 |
   355|| PROJECT.md 第145-156行 | 正确示例对比 | ✓ 已实现 |
   356|| MODULE.md DataFrame副本规范 | 函数入口 .copy() | ✓ calculate_turnover_surge 第62行 |
   357|| factor-ic-analyzer skill | CLI异常处理堆栈保留 | ✓ logger.exception() |
   358|
   359|---
   360|
   361|## 📈 代码量对比
   362|
   363||| 版本 | 行数 | 说明 |
   364|||------|------|------||
   365||| v1.24（旧版） | 389行 | 手写三模式分支 + 数据加载 |
   366||| **v2.2（当前版）** | **178行** | **使用公共模块主入口 + 异常检测顺序修正** |
   367||| 降幅 | **54%** | **删除211行冗余代码** |
   368|
   369|---
   370|
   371|*文档结束*