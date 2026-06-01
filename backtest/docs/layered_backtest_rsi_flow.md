     1|# RSI 分层回测流程文档
     2|
     3|> 生成时间: 2026-05-08
     4|> 审阅版本: v1.0
     5|
     6|---
     7|
     8|## 📋 整体架构
     9|
    10|```
    11|┌─────────────────────────────────────────────────────────────────────┐
    12|│              RSI分层回测系统架构                                      │
    13|├─────────────────────────────────────────────────────────────────────┤
    14|│                                                                     │
    15|│  rsi_layered_backtest.py (入口脚本)                                 │
    16|│         │                                                           │
    17|│         ├── RSILayerConfig (配置类)                                 │
    18|│         │      ├── 分层阈值定义                                      │
    19|│         │      ├── 因子方向设置                                      │
    20|│         │      └── 多空组合定义                                      │
    21|│         │                                                           │
    22|│         ├── load_data_from_cache() (数据加载)                       │
    23|│         │                                                           │
    24|│         └── LayeredBacktestEngine.run() (回测引擎)                  │
    25|│                │                                                    │
    26|│                ├── 数据合并                                          │
    27|│                ├── 每日分层                                          │
    28|│                ├── 收益计算                                          │
    29|│                ├── 换手率计算                                        │
    30|│                └── 统计汇总                                          │
    31|│                                                                     │
    32|│  输出: backtest/result/rsi_layered_backtest.json                     │
    33|│        backtest/result/rsi_layered_backtest_daily.json.gz            │
    34|│                                                                     │
    35|└─────────────────────────────────────────────────────────────────────┘
    36|```
    37|
    38|---
    39|
    40|## 🔍 详细流程步骤
    41|
    42|### Step 1: 配置初始化
    43|
    44|```
    45|RSILayerConfig 类定义
    46|    │
    47|    ├── 分层阈值 (固定阈值法)
    48|    │   LAYER_THRESHOLDS = [0, 20, 40, 60, 80, 100]
    49|    │   └───────────────────────────────────────────────
    50|    │   | Layer | RSI范围        | 含义              |
    51|    │   |-------|---------------|-------------------|
    52|    │   | 1     | RSI < 20      | 超卖层            |
    53|    │   | 2     | 20 ≤ RSI < 40 | 弱势层            |
    54|    │   | 3     | 40 ≤ RSI < 60 | 中性层            |
    55|    │   | 4     | 60 ≤ RSI < 80 | 强势层            |
    56|    │   | 5     | RSI ≥ 80      | 超买层            |
    57|    │   └───────────────────────────────────────────────
    58|    │
    59|    ├── 因子方向
    60|    │   FACTOR_DIRECTION = 'negative'  # RSI是反向因子
    61|    │   解释: RSI低 → 超卖 → 预期收益高
    62|    │         RSI高 → 超买 → 预期收益低
    63|    │
    64|    ├── 多空组合 (反向因子特点)
    65|    │   LONG_LAYERS = [1, 2]   # 多头: 超卖层+弱势层 (预期收益高)
    66|    │   SHORT_LAYERS = [4, 5]  # 空头: 强势层+超买层 (预期收益低)
    67|    │
    68|    └── 交易参数
    69|        TRADE_COST_RATE = 0.003        # 单边千分之三
    70|        MIN_STOCKS_PER_LAYER = 10      # 每层最少10只股票
    71|```
    72|
    73|---
    74|
    75|### Step 2: 数据加载
    76|
    77|```
    78|load_data_from_cache()
    79|    │
    80|    ├── 加载因子数据
    81|    │   │
    82|    │   └── data_fetchers/result/factor_data.json.gz
    83|    │       ├── 解压 gzip → JSON
    84|    │       ├── 转为 DataFrame
    85|    │       ├── 提取列: [date, asset, rsi_6]
    86|    │       └── 限制天数: 最近 n_days 天
    87|    │
    88|    ├── 加载收益数据
    89|    │   │
    90|    │   └── data_fetchers/result/factor_ic_data.json.gz
    91|    │       ├── 解压 gzip → JSON
    92|    │       ├── 转为 DataFrame
    93|    │       ├── 提取列: [date, asset, forward_return_1d]
    94|    │       └── 限制天数: 最近 n_days 天
    95|    │
    96|    └── 返回 (factor_df, return_df)
    97|```
    98|
    99|**数据格式示例**：
   100|
   101|```
   102|factor_df:
   103|| date       | asset   | rsi_6 |
   104||------------|---------|-------|
   105|| 2026-01-01 | 000001  | 25.5  |
   106|| 2026-01-01 | 000002  | 80.2  |
   107|| ...        | ...     | ...   |
   108|
   109|return_df:
   110|| date       | asset   | forward_return_1d |
   111||------------|---------|-------------------|
   112|| 2026-01-01 | 000001  | 0.05              |
   113|| 2026-01-01 | 000002  | -0.02             |
   114|| ...        | ...     | ...               |
   115|```
   116|
   117|---
   118|
   119|### Step 3: 回测引擎初始化
   120|
   121|```
   122|LayeredBacktestEngine.__init__()
   123|    │
   124|    ├── 参数接收
   125|    │   ├── factor_df    因子数据
   126|    │   ├── return_df    收益数据
   127|    │   ├── factor_col   = 'rsi_6'
   128|    │   ├── return_col   = 'forward_return_1d'
   129|    │   ├── date_col     = 'date'
   130|    │   └── asset_col    = 'asset'
   131|    │
   132|    └── 数据合并 (_merge_data)
   133|        │
   134|        ├── 选择需要的列
   135|        │   factor_cols = [date, asset, rsi_6]
   136|        │   return_cols = [date, asset, forward_return_1d]
   137|        │
   138|        ├── 内连接合并
   139|        │   merged_df = pd.merge(factor_df, return_df, on=[date, asset])
   140|        │
   141|        ├── 获取日期列表
   142|        │   dates = sorted(merged_df[date].unique())
   143|        │
   144|        └── 内存优化
   145|            ├── asset → category 类型
   146|            ├── rsi_6 → float32 类型
   147|            └── forward_return_1d → float32 类型
   148|```
   149|
   150|---
   151|
   152|### Step 4: 分层回测执行（核心循环）
   153|
   154|```
   155|LayeredBacktestEngine.run()
   156|    │
   157|    ├── 参数配置
   158|    │   ├── layer_method      = 'fixed_threshold' (固定阈值)
   159|    │   ├── thresholds        = [0, 20, 40, 60, 80, 100]
   160|    │   ├── factor_direction  = 'negative' (反向因子)
   161|    │   ├── long_layers       = [1, 2]
   162|    │   ├── short_layers      = [4, 5]
   163|    │   └── trade_cost_rate   = 0.003
   164|    │
   165|    └── 每日循环处理
   166|        │
   167|        └──────────────────────────────────────────────────────────────┐
   168|        │                                                              │
   169|        │  for each date in dates:                                     │
   170|        │      │                                                       │
   171|        │      ├── [过滤] 获取当日数据                                   │
   172|        │      │      day_data = merged_df[merged_df[date] == date]    │
   173|        │      │                                                       │
   174|        │      ├── [过滤] 去除因子NaN                                   │
   175|        │      │      day_data = day_data[rsi_6.notna()]               │
   176|        │      │                                                       │
   177|        │      ├── [检查] 股票数 < MIN_STOCKS_PER_LAYER?               │
   178|        │      │      → 跳过该日                                        │
   179|        │      │                                                       │
   180|        │      ├── [分层] 计算股票归属                                   │
   181|        │      │      get_layer_assignment()                           │
   182|        │      │          │                                            │
   183|        │      │          └─────────────────────────────────────────┐ │
   184|        │      │          │                                         │ │
   185|        │      │          │  固定阈值分层算法:                         │ │
   186|        │      │          │                                         │ │
   187|        │      │          │  for i in [0, 1, 2, 3, 4]:               │ │
   188|        │      │          │      lower = thresholds[i]               │ │
   189|        │      │          │      upper = thresholds[i+1]             │ │
   190|        │      │          │      mask = (rsi >= lower) & (rsi < upper)│ │
   191|        │      │          │      layer_assignment[mask] = i + 1      │ │
   192|        │      │          │                                         │ │
   193|        │      │          │  边界处理:                                │ │
   194|        │      │          │      rsi >= 100 → Layer5                 │ │
   195|        │      │          │      rsi < 0   → Layer1                  │ │
   196|        │      │          │                                         │ │
   197|        │      │          └─────────────────────────────────────────┘ │
   198|        │      │                                                       │
   199|        │      ├── [收益] 计算各层收益                                   │
   200|        │      │      calculate_layer_returns()                       │
   201|        │      │          │                                            │
   202|        │      │          │  for each layer_id:                        │
   203|        │      │          │      layer_mask = (layer_assignment == layer_id)│
   204|        │      │          │      layer_returns = returns[layer_mask]  │
   205|        │      │          │      │                                    │
   206|        │      │          │      股票数 < min_stocks? → return NaN      │
   207|        │      │          │      │                                    │
   208|        │      │          │      等权平均收益:                          │
   209|        │      │          │          mean_return = layer_returns.mean()│
   210|        │      │          │                                            │
   211|        │      │                                                       │
   212|        │      ├── [换手] 计算各层换手率                                 │
   213|        │      │      calculate_turnover()                             │
   214|        │      │          │                                            │
   215|        │      │          │  换手率 = 新入股票数 / 层股票总数             │
   216|        │      │          │      │                                    │
   217|        │      │          │  curr_stocks = 当前层股票集合               │
   218|        │      │          │  prev_stocks = 前期该层股票集合             │
   219|        │      │          │  new_stocks = curr_stocks - prev_stocks    │
   220|        │      │          │  turnover = len(new_stocks) / len(curr_stocks)│
   221|        │      │          │                                            │
   222|        │      │                                                       │
   223|        │      ├── [记录] 保存每日结果                                   │
   224|        │      │      for layer_id in [1, 2, 3, 4, 5]:                 │
   225|        │      │          daily_records.append({                       │
   226|        │      │              'date': date,                            │
   227|        │      │              'layer': layer_id,                       │
   228|        │      │              'n_stocks': 股票数,                       │
   229|        │      │              'return': 层收益,                         │
   230|        │      │              'turnover': 换手率                        │
   231|        │      │          })                                           │
   232|        │      │                                                       │
   233|        │      └── [更新] prev_assignment = 当日分层结果                 │
   234|        │                                                              │
   235|        └──────────────────────────────────────────────────────────────┘
   236|```
   237|
   238|---
   239|
   240|### Step 5: 统计汇总
   241|
   242|```
   243|_aggregate_results()
   244|    │
   245|    ├── [一] 各层统计
   246|    │   │
   247|    │   │  for layer_id in [1, 2, 3, 4, 5]:
   248|    │   │      layer_data = daily_df[daily_df['layer'] == layer_id]
   249|    │   │      │
   250|    │   │      ├── 日均收益 = layer_data['return'].mean()
   251|    │   │      ├── 日收益标准差 = layer_data['return'].std()
   252|    │   │      ├── 累计收益 = (1 + returns).cumprod() - 1
   253|    │   │      ├── 年化收益 = daily_return_mean * 252
   254|    │   │      ├── 年化波动 = daily_return_std * sqrt(252)
   255|    │   │      ├── 夏普比率 = annual_return / annual_volatility
   256|    │   │      ├── 最大回撤 = max_drawdown 计算
   257|    │   │      └── 平均换手率 = layer_data['turnover'].mean()
   258|    │   │
   259|    │   └── 输出: layer_stats = {layer_1: {...}, layer_2: {...}, ...}
   260|    │
   261|    ├── [二] 多空组合统计
   262|    │   │
   263|    │   │  for each date:
   264|    │   │      ├── 多头收益 = Layer[1,2] 收益均值
   265|    │   │      ├── 空头收益 = Layer[4,5] 收益均值
   266|    │   │      └── 多空收益 = 多头收益 - 空头收益
   267|    │   │
   268|    │   │  汇总:
   269|    │   │      ├── 多头日均收益
   270|    │   │      ├── 多头年化收益
   271|    │   │      ├── 空头日均收益
   272|    │   │      ├── 空头年化收益
   273|    │   │      ├── 多空日均收益
   274|    │   │      ├── 多空年化收益
   275|    │   │      ├── 多空夏普比率
   276|    │   │      ├── 多头平均换手率
   277|    │   │      └── 空头平均换手率
   278|    │   │
   279|    │   └── 输出: long_short = {...}
   280|    │
   281|    ├── [三] 单调性检验
   282|    │   │
   283|    │   │  _calculate_monotonicity()
   284|    │   │      │
   285|    │   │      ├── 提取各层日均收益: [r1, r2, r3, r4, r5]
   286|    │   │      ├── layer_ids = [1, 2, 3, 4, 5]
   287|    │   │      │
   288|    │   │      ├── 计算相关系数:
   289|    │   │      │   correlation = corrcoef(layer_ids, layer_returns)
   290|    │   │      │
   291|    │   │      ├── 反向因子判定:
   292|    │   │      │   correlation < -0.5 → 'good' (单调性良好)
   293|    │   │      │   correlation < 0    → 'moderate' (单调性一般)
   294|    │   │      │   correlation >= 0   → 'poor' (单调性较差)
   295|    │   │      │
   296|    │   │      └── 期望: Layer1收益 > Layer5收益 (反向因子)
   297|    │   │
   298|    │   └── 输出: monotonicity = {correlation, quality, layer_returns}
   299|    │
   300|    └── [四] 交易成本分析
   301|        │
   302|        │  _calculate_trading_costs()
   303|            │
   304|            ├── 多头交易成本 = long_turnover * trade_cost_rate
   305|            │   (单边成本)
   306|            │
   307|            ├── 空头交易成本 = short_turnover * trade_cost_rate * 2
   308|            │   (双边成本，做空需借券)
   309|            │
   310|            ├── 多空毛收益 = long_return - short_return
   311|            │
   312|            ├── 多空净收益 = (long_return - long_cost) - (short_return - short_cost)
   313|            │
   314|            └── 输出: trading_cost_analysis = {...}
   315|```
   316|
   317|---
   318|
   319|### Step 6: 输出结果
   320|
   321|#### 输出文件结构
   322|
   323|**主结果文件**: `rsi_layered_backtest.json`
   324|
   325|```json
   326|{
   327|    "meta": {
   328|        "n_layers": 5,
   329|        "factor_name": "rsi_6",
   330|        "factor_direction": "negative",
   331|        "long_layers": [1, 2],
   332|        "short_layers": [4, 5],
   333|        "n_days_total": 500,
   334|        "n_assets_total": 3500,
   335|        "layer_names": {
   336|            "1": "超卖层",
   337|            "2": "弱势层",
   338|            "3": "中性层",
   339|            "4": "强势层",
   340|            "5": "超买层"
   341|        }
   342|    },
   343|    "layer_stats": {
   344|        "layer_1": {
   345|            "n_days": 500,
   346|            "n_stocks_avg": 120,
   347|            "daily_return_mean": 0.00085,
   348|            "daily_return_std": 0.015,
   349|            "cumulative_return": 0.52,
   350|            "annual_return": 0.214,
   351|            "annual_volatility": 0.238,
   352|            "sharpe_ratio": 0.90,
   353|            "max_drawdown": -0.18,
   354|            "turnover_avg": 0.35
   355|        },
   356|        "layer_2": {...},
   357|        "layer_3": {...},
   358|        "layer_4": {...},
   359|        "layer_5": {...}
   360|    },
   361|    "long_short": {
   362|        "long_return_daily": 0.00072,
   363|        "long_return_annual": 0.181,
   364|        "short_return_daily": -0.00025,
   365|        "short_return_annual": -0.063,
   366|        "long_short_return_daily": 0.00097,
   367|        "long_short_return_annual": 0.244,
   368|        "long_short_sharpe": 1.25,
   369|        "n_days": 500
   370|    },
   371|    "monotonicity": {
   372|        "correlation": -0.82,
   373|        "quality": "good",
   374|        "layer_returns": [0.00085, 0.00045, 0.00020, -0.00015, -0.00035]
   375|    },
   376|    "trading_cost_analysis": {
   377|        "cost_rate": 0.003,
   378|        "long_turnover": 0.35,
   379|        "short_turnover": 0.42,
   380|        "long_daily_cost": 0.00105,
   381|        "short_daily_cost": 0.00252,
   382|        "long_short_gross_daily": 0.00097,
   383|        "long_short_net_daily": 0.00035
   384|    },
   385|    "config": {
   386|        "layer_thresholds": [0, 20, 40, 60, 80, 100],
   387|        "factor_direction": "negative",
   388|        "long_layers": [1, 2],
   389|        "short_layers": [4, 5],
   390|        "trade_cost_rate": 0.003
   391|    }
   392|}
   393|```
   394|
   395|**每日明细文件**: `rsi_layered_backtest_daily.json.gz` (压缩)
   396|
   397|```json
   398|{
   399|    "meta": {
   400|        "n_days": 500,
   401|        "columns": ["date", "layer", "n_stocks", "return", "turnover"]
   402|    },
   403|    "data": [
   404|        {"date": "2026-01-01", "layer": 1, "n_stocks": 118, "return": 0.0085, "turnover": 0.32},
   405|        {"date": "2026-01-01", "layer": 2, "n_stocks": 245, "return": 0.0045, "turnover": 0.28},
   406|        ...
   407|    ]
   408|}
   409|```
   410|
   411|---
   412|
   413|## 📊 关键指标含义
   414|
   415|### 各层统计指标
   416|
   417|| 指标 | 含义 | 计算方式 |
   418||------|------|----------|
   419|| **日均收益** | 该层每日平均收益 | returns.mean() |
   420|| **年化收益** | 年化后的收益 | 日均收益 × 252 |
   421|| **年化波动** | 年化后的波动率 | 日标准差 × sqrt(252) |
   422|| **夏普比率** | 风险调整后收益 | 年化收益 / 年化波动 |
   423|| **最大回撤** | 最大亏损幅度 | cumprod 回撤计算 |
   424|| **换手率** | 每日股票变动比例 | 新入股票数 / 层股票数 |
   425|
   426|### 多空组合指标
   427|
   428|| 指标 | 含义 | RSI反向因子预期 |
   429||------|------|-----------------|
   430|| **多头收益** | Layer[1,2]组合收益 | 正值（超卖层收益高） |
   431|| **空头收益** | Layer[4,5]组合收益 | 负值或低正值 |
   432|| **多空收益** | 多头 - 空头 | 正值（因子有效） |
   433|| **多空夏普** | 多空组合夏普比率 | > 0.5 表示有效 |
   434|
   435|### 单调性指标
   436|
   437|| 相关系数 | 质量 | 说明 |
   438||----------|------|------|
   439|| < -0.5 | good | Layer1收益明显高于Layer5 |
   440|| < 0 | moderate | 有一定单调性 |
   441|| >= 0 | poor | 无单调性，因子可能无效 |
   442|
   443|---
   444|
   445|## 🔧 RSI分层特点
   446|
   447|### 固定阈值分层 vs 百分位分层
   448|
   449|| 方法 | 特点 | 适用场景 |
   450||------|------|----------|
   451|| **固定阈值** | 使用绝对值划分，如RSI<20 | RSI等有明确含义的因子 |
   452|| **百分位** | 每层20%股票，相对划分 | 通用因子，无绝对含义 |
   453|
   454|**RSI使用固定阈值的原因**：
   455|- RSI有明确的超买/超卖含义（20/80是经典阈值）
   456|- 固定阈值更符合技术分析直觉
   457|- 不同市场环境下阈值含义稳定
   458|
   459|### 反向因子处理
   460|
   461|```
   462|正向因子 (如 Volume_Ratio):
   463|    高值 → 高收益预期
   464|    多头 = Layer4, Layer5 (高值层)
   465|    空头 = Layer1, Layer2 (低值层)
   466|
   467|反向因子 (如 RSI):
   468|    低值 → 高收益预期 (超卖反弹)
   469|    多头 = Layer1, Layer2 (低值层)
   470|    空头 = Layer4, Layer5 (高值层)
   471|```
   472|
   473|---
   474|
   475|## 📁 文件位置
   476|
   477|| 文件 | 路径 |
   478||------|------|
   479|| 入口脚本 | `backtest/rsi_layered_backtest.py` |
   480|| 回测引擎 | `backtest/layered_backtest.py` |
   481|| 输出结果 | `backtest/result/rsi_layered_backtest.json` |
   482|| 每日明细 | `backtest/result/rsi_layered_backtest_daily.json.gz` |
   483|| 本文档 | `backtest/docs/rsi_layered_backtest_flow.md` |
   484|
   485|---
   486|
   487|## 🔄 与其他因子回测的关系
   488|
   489|通用分层回测引擎 `LayeredBacktestEngine` 可用于多种因子：
   490|
   491|| 因子 | 方向 | 分层方法 | 多头组合 |
   492||------|------|----------|----------|
   493|| RSI | negative (反向) | fixed_threshold | Layer[1,2] |
   494|| KDJ_J | negative (反向) | fixed_threshold | Layer[1,2] |
   495|| Volume_Ratio | positive (正向) | percentile | Layer[4,5] |
   496|| Turnover_Surge | positive (正向) | percentile | Layer[4,5] |
   497|| Bollinger_PB | negative (反向) | fixed_threshold | Layer[1,2] |
   498|| Main_Inflow | positive (正向) | percentile | Layer[4,5] |
   499|
   500|---
   501|   501|
   502|## 🚀 使用方式
   503|
   504|### 命令行运行
   505|
   506|```bash
   507|cd ~/.openclaw/workspace/yunzhou/factor_ic_analyzer
   508|
   509|# 默认回测500天
   510|python -m backtest.rsi_layered_backtest
   511|
   512|# 指定回测天数
   513|python -m backtest.rsi_layered_backtest --n_days 250
   514|
   515|# 安静模式
   516|python -m backtest.rsi_layered_backtest --quiet
   517|```
   518|
   519|### Python调用
   520|
   521|```python
   522|from backtest.rsi_layered_backtest import run_rsi_layered_backtest
   523|
   524|result = run_rsi_layered_backtest(
   525|    n_days=500,
   526|    verbose=True
   527|)
   528|
   529|# 查看结果
   530|print(result['long_short']['long_short_return_annual'])
   531|print(result['monotonicity']['correlation'])
   532|```
   533|
   534|---
   535|
   536|*文档结束*