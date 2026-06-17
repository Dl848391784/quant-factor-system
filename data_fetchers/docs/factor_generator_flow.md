     1|# factor_generator.py 流程文档
     2|
     3|> 版本: v1.0
     4|> 创建时间: 2026-05-25 10:25 北京时间
     5|> 脚本路径: `data_fetchers/factor_generator.py`
     6|
     7|---
     8|
     9|## 整体架构
    10|
    11|```
    12|┌─────────────────────────────────────────────────────────────────────────┐
    13|│                       factor_generator.py 统一因子生成                    │
    14|├─────────────────────────────────────────────────────────────────────────┤
    15|│                                                                         │
    16|│   输入数据                                                               │
    17|│   ┌──────────────────┐    ┌──────────────────┐                         │
    18|│   │factor_data.json.gz│    │turnover_rate_data│                         │
    19|│   │  (基础因子数据)    │    │   .json.gz       │                         │
    20|│   │  - rsi_6         │    │  (换手率数据)     │                         │
    21|│   │  - volume_ratio_5│    │                  │                         │
    22|│   └──────────────────┘    └──────────────────┘                         │
    23|│           │                        │                                    │
    24|│           ▼                        ▼                                    │
    25|│   ┌─────────────────────────────────────────────────────────────┐      │
    26|│   │                    Step 1-2: 数据加载                         │      │
    27|│   │  - 加载基础因子数据（gzip JSON）                              │      │
    28|│   │  - 加载换手率数据并合并                                       │      │
    29|│   └─────────────────────────────────────────────────────────────┘      │
    30|│                              │                                          │
    31|│                              ▼                                          │
    32|│   ┌─────────────────────────────────────────────────────────────┐      │
    33|│   │                 Step 3-5: 扩展因子计算                        │      │
    34|│   │  - calculate_bollinger_pb (布林带 %B)                        │      │
    35|│   │  - calculate_kdj_j (KDJ 指标 J 值)                           │      │
    36|│   │  - calculate_turnover_surge (换手率突增)                     │      │
    37|│   └─────────────────────────────────────────────────────────────┘      │
    38|│                              │                                          │
    39|│                              ▼                                          │
    40|│   ┌─────────────────────────────────────────────────────────────┐      │
    41|│   │                    Step 6-7: 输出格式化                        │      │
    42|│   │  - 格式化日期（YYYY-MM-DD）                                   │      │
    43|│   │  - 构建 dates + data 结构                                     │      │
    44|│   │  - 原子写入 gzip JSON                                         │      │
    45|│   └─────────────────────────────────────────────────────────────┘      │
    46|│                              │                                          │
    47|│                              ▼                                          │
    48|│   ┌─────────────────────────────────────────────────────────────┐      │
│   │                 factor_ic_data.json.gz                    │      │
│   │  - dates: [日期列表]                                          │      │
│   │  - data: [所有因子+收益数据]                                  │      │
│   │  (包含因子: rsi_6, volume_ratio_5, bollinger_pb,            │      │
│   │   kdj_j, turnover_surge + return_3d, return_5d)             │      │
    54|│   └─────────────────────────────────────────────────────────────┘      │
    55|│                                                                         │
    56|└─────────────────────────────────────────────────────────────────────────┘
    57|```
    58|
    59|---
    60|
    61|## 详细流程步骤
    62|
    63|### Step 1: 加载基础因子数据
    64|
    65|**输入**: `data_fetchers/result/factor_data.json.gz`
    66|
    67|**操作**:
    68|```python
    69|with gzip.open(factor_data_path, 'rt') as f:
    70|    base_data = json.load(f)
    71|factor_df = pd.DataFrame(base_data['data'])
    72|factor_df['date'] = pd.to_datetime(factor_df['date'])
    73|```
    74|
    75|**验证**:
    76|- 检查 `data` 字段存在
    77|- 检查 `date` 列存在
    78|
    79|---
    80|
    81|### Step 2: 加载换手率数据并合并
    82|
    83|**输入**: `data_fetchers/result/turnover_rate_data.json.gz`
    84|
    85|**操作**:
    86|```python
    87|turnover_df = pd.DataFrame(turnover_data['data'])
    88|turnover_df['date'] = pd.to_datetime(turnover_df['date'], format='mixed')
    89|factor_df = factor_df.merge(
    90|    turnover_df[['date', 'asset', 'turnover_rate']],
    91|    on=['date', 'asset'], how='left'
    92|)
    93|```
    94|
    95|**验证**:
    96|- 检查 `data` 字段存在
    97|- 记录换手率缺失数量
    98|
    99|---
   100|
   101|### Step 3: 计算 Bollinger_PB 因子
   102|
   103|**调用**: `calculate_bollinger_pb(factor_df)`
   104|
   105|**参数**:
   106|- n=20（移动平均周期）
   107|- k=2.0（标准差倍数）
   108|
   109|**依赖**:
   110|- close（收盘价）
   111|
   112|**输出列**: `bollinger_pb`
   113|
   114|---
   115|
   116|### Step 4: 计算 KDJ_J 因子
   117|
   118|**调用**: `calculate_kdj_j(factor_df)`
   119|
   120|**参数**:
   121|- n=9（RSV 计算周期）
   122|- m1=3（K 值平滑周期）
   123|- m2=3（D 值平滑周期）
   124|
   125|**依赖**:
   126|- close（收盘价）
   127|- high（最高价）
   128|- low（最低价）
   129|
   130|**输出列**: `kdj_j`
   131|
   132|---
   133|
   134|### Step 5: 计算 Turnover_Surge 因子
   135|
   136|**调用**: `calculate_turnover_surge(factor_df)`
   137|
   138|**参数**:
   139|- window=5（换手率均值窗口）
   140|
   141|**依赖**:
   142|- turnover_rate（换手率）
   143|- close（收盘价）
   144|
   145|**输出列**: `turnover_surge`
   146|
   147|---
   148|
   149|### Step 6: 格式化输出
   150|
   151|**操作**:
   152|```python
   153|factor_df['date'] = factor_df['date'].dt.strftime('%Y-%m-%d')
   154|
   155|output_cols = [
   156|    'date', 'asset', 'open', 'close', 'high', 'low',
   157|    'rsi_6', 'volume_ratio_5',
   158|    'bollinger_pb', 'kdj_j', 'turnover_surge'
   159|]
   160|
   161|output_df = factor_df[output_cols].copy()
   162|```
   163|
   164|**列说明**:
   165|| 索引范围 | 内容 | 说明 |
   166||---------|------|------|
   167|| 0:6 | date, asset, open, close, high, low | 基础 OHLCV 数据 |
   168|| 6:8 | rsi_6, volume_ratio_5 | 基础因子（来自输入） |
   169|| 8:11 | bollinger_pb, kdj_j, turnover_surge | 扩展因子（本次计算） |
   170|
   171|---
   172|
   173|### Step 7: 保存输出
   174|
   175|**输出路径**: `data_fetchers/result/factor_ic_data.json.gz`
   176|
   177|**操作**:
   178|```python
   179|output_data = {
   180|    'dates': sorted(factor_df['date'].unique().tolist()),
   181|    'data': output_df.to_dict('records')
   182|}
   183|
   184|# 原子写入：临时文件 + os.replace
   185|temp_path = output_path.with_suffix('.tmp')
   186|with gzip.open(temp_path, 'wt') as f:
   187|    json.dump(output_data, f)
   188|os.replace(temp_path, output_path)
   189|```
   190|
   191|---
   192|
   193|### Step 8: 返回元数据
   194|
   195|**返回结构**:
   196|```python
   197|metadata = {
   198|    'generated_at': 'YYYY-MM-DD HH:MM:SS',
   199|    'elapsed_seconds': 120.5,
   200|    'total_records': 1480000,
   201|    'valid_records': {
   202|        'bollinger_pb': 1460000,
   203|        'kdj_j': 1460000,
   204|        'turnover_surge': 1460000,
   205|    },
   206|    'valid_records_percent': {
   207|        'bollinger_pb': 98.65,
   208|        'kdj_j': 98.65,
   209|        'turnover_surge': 98.65,
   210|    },
   211|    'factor_columns': ['bollinger_pb', 'kdj_j', 'turnover_surge'],
   212|    'input_sources': {...},
   213|    'output_path': '...'
   214|}
   215|```
   216|
   217|---
   218|
   219|## 输出结构
   220|
   221|### factor_ic_data.json.gz
   222|
   223|```json
   224|{
   225|  "dates": ["2024-04-19", "2024-04-20", ...],
   226|  "data": [
   227|    {
   228|      "date": "2024-04-19",
   229|      "asset": "000001",
   230|      "open": 10.71,
   231|      "close": 10.69,
   232|      "high": 10.82,
   233|      "low": 10.66,
   234|      "rsi_6": 64.42,
   235|      "volume_ratio_5": 0.74,
   236|      "bollinger_pb": null,
   237|      "kdj_j": null,
   238|      "turnover_surge": null
   239|    },
   240|    ...
   241|  ]
   242|}
   243|```
   244|
   245|**字段说明**:
   246|
   247|| 字段 | 类型 | 说明 |
   248||------|------|------|
   249|| dates | list[str] | 日期列表（YYYY-MM-DD 格式） |
   250|| data | list[dict] | 因子数据列表 |
   251|| date | str | 日期 |
   252|| asset | str | 股票代码 |
   253|| open/close/high/low | float | OHLCV 价格数据 |
   254|| rsi_6 | float | RSI(6) 指标 |
   255|| volume_ratio_5 | float | 量比(5) 指标 |
   256|| bollinger_pb | float/null | 布林带 %B |
   257|| kdj_j | float/null | KDJ 指标 J 值 |
   258|| turnover_surge | float/null | 换手率突增 |
   259|
   260|---
   261|
   262|## 关键指标定义
   263|
   264|### valid_records
   265|
   266|**定义**: 因子值非空的记录数
   267|
   268|**计算方式**:
   269|```python
   270|bollinger_valid = factor_df['bollinger_pb'].notna().sum()
   271|kdj_valid = factor_df['kdj_j'].notna().sum()
   272|surge_valid = factor_df['turnover_surge'].notna().sum()
   273|```
   274|
   275|### valid_records_percent
   276|
   277|**定义**: 有效记录占总记录的百分比
   278|
   279|**计算方式**:
   280|```python
   281|percent = round(valid_count / total_records * 100, 2)
   282|```
   283|
   284|### elapsed_seconds
   285|
   286|**定义**: 因子生成总耗时（秒）
   287|
   288|---
   289|
   290|## CLI 使用方式
   291|
   292|### 默认运行
   293|
   294|```bash
   295|python data_fetchers/factor_generator.py
   296|```
   297|
   298|### 自定义路径
   299|
   300|```bash
   301|python data_fetchers/factor_generator.py \
   302|    --factor_data path/to/factor_data.json.gz \
   303|    --turnover_data path/to/turnover_rate_data.json.gz \
   304|    --output path/to/output.json.gz
   305|```
   306|
   307|### 静默模式
   308|
   309|```bash
   310|python data_fetchers/factor_generator.py --quiet
   311|```
   312|
   313|---
   314|
   315|## Python API 使用方式
   316|
   317|```python
   318|from data_fetchers.factor_generator import generate_all_factors
   319|
   320|# 使用默认 logger
   321|metadata = generate_all_factors()
   322|
   323|# 使用自定义 logger
   324|import logging
   325|logger = logging.getLogger('my_app')
   326|metadata = generate_all_factors(logger=logger)
   327|
   328|# 自定义路径
   329|metadata = generate_all_factors(
   330|    factor_data_path='path/to/factor_data.json.gz',
   331|    turnover_data_path='path/to/turnover_rate_data.json.gz',
   332|    output_path='path/to/output.json.gz',
   333|    logger=logger
   334|)
   335|```
   336|
   337|---
   338|
   339|## 当前实现补充（2026-06-17）
   340|
   341|### Step 11.9: 资金流因子 OOM 修复
   342|
   343|- **调用**: `calculate_capital_flow_block(factor_df)`
   344|- **输出列**: `capital_flow_ratio_trend`, `capital_flow_intensity`
   345|- **实现约束**: 两个资金流输出必须由单个 orchestrator step 一次性生成，禁止在 `factor_generator.py` pipeline 中拆回 `calculate_capital_flow_ratio_trend` 与 `calculate_capital_flow_intensity` 两个独立 step。
   346|- **原因**: 拆成两个 step 会重复加载资金流数据并重复构造 149 万行级 merge 中间表，实跑在 Step 11.8 后进入资金流阶段时出现 OOM-kill（signal 9）。
   347|- **验证**: `_FACTOR_PIPELINE_STEPS` 中资金流 step 数量为 1，且 `factor_func.__name__ == "calculate_capital_flow_block"`。
   348|
   349|---
   350|
   351|## 版本历史
   352|
   353|| 版本 | 日期 | 更新内容 |
   354||------|------|---------|
   355|| v1.1 | 2026-06-17 | Step 11.9 资金流因子切换为单 step orchestrator，避免 OOM |
   356|| v1.0 | 2026-05-25 | 创建流程文档 |
   357|
   358|---
   359|
   360|*创建时间: 2026-05-25 10:25 北京时间；最近更新: 2026-06-17 北京时间*