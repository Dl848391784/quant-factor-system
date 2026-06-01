     1|# fetch_turnover 流程文档
     2|
     3|> 版本: v2.11
     4|> 创建时间: 2026-05-27 19:00 北京时间
     5|> 更新时间: 2026-05-27 19:00 北京时间
     6|
     7|---
     8|
     9|## 概述
    10|
    11|换手率数据拉取脚本，包含两个数据源：
    12|1. 东财千股千评 API（fetch_turnover_rate_eastmoney）- 实时数据
    13|2. baostock 数据源（fetch_turnover_rate_baostock）- 历史数据
    14|
    15|**缓存路径：** `data_fetchers/result/turnover_rate_data.json.gz`
    16|
    17|---
    18|
    19|## 目录
    20|
    21|1. [数据结构](#数据结构)
    22|2. [核心流程](#核心流程)
    23|3. [函数接口](#函数接口)
    24|4. [CLI 参数](#cli-参数)
    25|5. [错误处理](#错误处理)
    26|6. [版本历史](#版本历史)
    27|
    28|---
    29|
    30|## 数据结构
    31|
    32|### 输出结构
    33|
    34|```json
    35|{
    36|  "meta": {
    37|    "generated_at": "2026-05-27T19:00:00",
    38|    "source": "eastmoney",
    39|    "n_days": 1,
    40|    "n_assets": 2500,
    41|    "date_range": {
    42|      "start": "2026-05-26",
    43|      "end": "2026-05-27"
    44|    },
    45|    "last_updated": "2026-05-27 19:00:00",
    46|    "version": "2.11"
    47|  },
    48|  "data": [
    49|    {
    50|      "date": "2026-05-27",
    51|      "asset": "600000",
    52|      "turnover_rate": 2.5,
    53|      "name": "浦发银行"
    54|    }
    55|  ]
    56|}
    57|```
    58|
    59|### 字段说明
    60|
    61|| 字段 | 类型 | 说明 |
    62||-----|------|------|
    63|| meta.generated_at | string | 数据生成时间（ISO格式） |
    64|| meta.source | string | 数据源（eastmoney/baostock/mixed） |
    65|| meta.n_days | int | 交易日数 |
    66|| meta.n_assets | int | 股票数量 |
    67|| meta.date_range.start | string | 日期范围起始 |
    68|| meta.date_range.end | string | 日期范围结束 |
    69|| meta.last_updated | string | 最后更新时间 |
    70|| meta.version | string | 版本号 |
    71|| data[].date | string | 交易日期 |
    72|| data[].asset | string | 股票代码 |
    73|| data[].turnover_rate | float | 换手率（%） |
    74|| data[].name | string | 股票名称（东财数据源有） |
    75|
    76|---
    77|
    78|## 核心流程
    79|
    80|### 东财数据源流程
    81|
    82|```
    83|┌─────────────────────────────────────────────────────────────┐
    84|│  Step 1: 加载现有缓存                                         │
    85|│  load_cache() → existing_data                               │
    86|└─────────────────────────────────────────────────────────────┘
    87|                              ↓
    88|┌─────────────────────────────────────────────────────────────┐
    89|│  Step 2: 拉取新数据                                           │
    90|│  fetch_turnover_rate_eastmoney() → new_records              │
    91|│  - 分页获取（pageSize=500）                                   │
    92|│  - 主板股票过滤（60/00开头）                                   │
    93|│  - ST/退市股票剔除                                            │
    94|└─────────────────────────────────────────────────────────────┘
    95|                              ↓
    96|┌─────────────────────────────────────────────────────────────┐
    97|│  Step 3: 合并去重                                             │
    98|│  merge_records(existing_data, new_records) → merged_data    │
    99|│  - (date, asset) 作为唯一键                                   │
   100|│  - 数据源标记（eastmoney/baostock/mixed）                     │
   101|└─────────────────────────────────────────────────────────────┘
   102|                              ↓
   103|┌─────────────────────────────────────────────────────────────┐
   104|│  Step 4: 保存缓存                                             │
   105|│  save_cache(merged_data)                                    │
   106|│  - tempfile 原子写入                                         │
   107|│  - gzip 压缩                                                 │
   108|└─────────────────────────────────────────────────────────────┘
   109|```
   110|
   111|### baostock 数据源流程
   112|
   113|```
   114|┌─────────────────────────────────────────────────────────────┐
   115|│  Step 0: 登录 baostock                                        │
   116|│  bs.login() → lg                                             │
   117|└─────────────────────────────────────────────────────────────┘
   118|                              ↓
   119|┌─────────────────────────────────────────────────────────────┐
   120|│  Step 1: 加载主板股票列表                                      │
   121|│  load_stock_list() → all_stocks                             │
   122|│  - 从 data_fetchers/result/stock_list.json 读取                             │
   123|│  - 主板股票过滤                                               │
   124|└─────────────────────────────────────────────────────────────┘
   125|                              ↓
   126|┌─────────────────────────────────────────────────────────────┐
   127|│  Step 2: 加载现有缓存                                          │
   128|│  load_cache() → existing_stocks（增量模式跳过已有股票）        │
   129|└─────────────────────────────────────────────────────────────┘
   130|                              ↓
   131|┌─────────────────────────────────────────────────────────────┐
   132|│  Step 3: 计算日期范围                                          │
   133|│  end_date = datetime.now()                                   │
   134|│  start_date = end_date - timedelta(days=n_days * 1.5)       │
   135|└─────────────────────────────────────────────────────────────┘
   136|                              ↓
   137|┌─────────────────────────────────────────────────────────────┐
   138|│  Step 4: 串行拉取                                              │
   139|│  for stock in all_stocks:                                    │
   140|│    - 跳过已有股票（增量模式）                                   │
   141|│    - query_history_k_data_plus()                             │
   142|│    - 连续失败检测 + 暂停机制                                   │
   143|│    - 时间估算 + 进度显示                                       │
   144|└─────────────────────────────────────────────────────────────┘
   145|                              ↓
   146|┌─────────────────────────────────────────────────────────────┐
   147|│  Step 5: 合并并保存                                            │
   148|│  merge_records() → save_cache()                             │
   149|└─────────────────────────────────────────────────────────────┘
   150|                              ↓
   151|┌─────────────────────────────────────────────────────────────┐
   152|│  Step 6: 登出 baostock                                        │
   153|│  bs.logout()                                                 │
   154|└─────────────────────────────────────────────────────────────┘
   155|```
   156|
   157|---
   158|
   159|## 函数接口
   160|
   161|### 公共函数（__all__ 导出）
   162|
   163|| 函数 | 返回类型 | 说明 |
   164||-----|---------|------|
   165|| `load_cache(logger_arg)` | `dict[str, Any] | None` | 加载现有缓存 |
   166|| `save_cache(data, logger_arg)` | `None` | 保存缓存文件 |
   167|| `get_cached_turnover_codes(logger_arg)` | `set[str]` | 获取缓存的股票代码集合 |
   168|| `fetch_turnover_rate_eastmoney(logger_arg)` | `list[dict[str, Any]]` | 东财数据源拉取 |
   169|| `fetch_turnover_rate_baostock(n_days, max_stocks, full, logger_arg)` | `bool` | baostock 数据源拉取 |
   170|| `main(logger_arg)` | `bool` | 主函数（东财版本） |
   171|
   172|### 内部函数
   173|
   174|| 函数 | 说明 |
   175||-----|------|
   176|| `is_main_board_stock(code, name)` | 主板股票判断 |
   177|| `load_stock_list()` | 加载主板股票列表 |
   178|| `get_baostock_code(stock_code)` | 转换为 baostock 格式 |
   179|| `fetch_stock_history_baostock(...)` | 拉取单只股票历史数据 |
   180|| `get_existing_stocks(cache_data)` | 获取已有数据的股票代码 |
   181|| `merge_records(existing_data, new_records, source, logger_arg)` | 合并数据 |
   182|| `format_time(seconds)` | 格式化时间显示 |
   183|
   184|---
   185|
   186|## CLI 参数
   187|
   188|| 参数 | 默认值 | 说明 |
   189||-----|-------|------|
   190|| `--baostock` | False | 使用 baostock 数据源 |
   191|| `--full` | False | 全量拉取（不使用缓存） |
   192|| `--n-days` | 500 | 历史天数（baostock） |
   193|| `--max-stocks` | 0 | 最大股票数（baostock，0为不限制） |
   194|
   195|### 使用示例
   196|
   197|```bash
   198|# 东财数据源（默认）
   199|python data_fetchers/fetch_turnover.py
   200|
   201|# baostock 数据源
   202|python data_fetchers/fetch_turnover.py --baostock
   203|
   204|# baostock 全量拉取 100 天
   205|python data_fetchers/fetch_turnover.py --baostock --full --n-days 100
   206|```
   207|
   208|---
   209|
   210|## 错误处理
   211|
   212|### CLI 异常处理（v2.11）
   213|
   214|```python
   215|try:
   216|    if args.baostock:
   217|        success = fetch_turnover_rate_baostock(...)
   218|    else:
   219|        success = main(...)
   220|    sys.exit(0 if success else 1)
   221|except Exception as e:
   222|    cli_logger.error(f"执行失败: [{type(e).__name__}]: {e}")
   223|    sys.exit(1)
   224|```
   225|
   226|### load_cache 类型校验（v2.11）
   227|
   228|```python
   229|if not isinstance(data, dict):
   230|    _logger.warning(f"[缓存] JSON 类型异常: 期望 dict，实际 {type(data).__name__}")
   231|    return None
   232|```
   233|
   234|### 重试机制
   235|
   236|- 东财 API：最多重试 3 次，等待时间递增（2s → 4s → 6s）
   237|- baostock：连续失败 5 次暂停 30 秒
   238|
   239|---
   240|
   241|## 版本历史
   242|
   243|| 版本 | 日期 | 改进内容 |
   244||-----|------|---------|
   245|| v2.11 | 2026-05-27 | 类型系统规范化：CLI异常处理、load_cache类型校验、typing内置泛型、ST_PREFIXES注释修正 |
   246|| v2.10 | 2026-05-27 | tempfile修复：同一with块内写入 |
   247|| v2.9 | 2026-05-27 | total_pages=0边界处理+冗余常量删除 |
   248|| v2.8 | 2026-05-27 | logger初始化统一+跳过日志粒度优化 |
   249|| v2.7 | 2026-05-27 | 时间估算逻辑+数据源合并逻辑 |
   250|| v2.6 | 2026-05-27 | doctest修复+logger赋值统一 |
   251|| v2.5 | 2026-05-27 | ST_PREFIXES元组优化+优先级语义+边界处理 |
   252|| v2.4 | 2026-05-27 | 时间统计修复+空数据处理+数据源保留 |
   253|| v2.3 | 2026-05-27 | 公共函数创建+类型注解+文档字符串 |
   254|| v2.2 | 2026-05-27 | ST_PREFIXES常量+ST检测修复+__all__导出+CLI简化 |
   255|| v2.1 | 2026-05-27 | logger参数化+tempfile+session资源管理+print迁移 |
   256|| v2.0 | 2026-05-27 | PEP8导入顺序+版本号常量+datetime统一 |
   257|| v1.2 | 2026-04-08 | 初始版本 |
   258|
   259|---
   260|
   261|## 相关文件
   262|
   263|| 文件 | 说明 |
   264||-----|------|
   265|| `data_fetchers/fetch_turnover.py` | 主脚本 |
   266|| `data_fetchers/result/turnover_rate_data.json.gz` | 缓存文件 |
   267|| `data_fetchers/result/stock_list.json` | 股票列表（baostock依赖） |
   268|| `data_fetchers/logs/fetch_turnover_*.log` | 日志文件 |
   269|
   270|---
   271|
   272|## 开发后动作
   273|
   274|```
   275|□ 修改代码后运行导入测试：python -c "from data_fetchers.fetch_turnover import load_cache, save_cache"
   276|□ 检查缓存文件完整性：gzip -dc data_fetchers/result/turnover_rate_data.json.gz | python -m json.tool
   277|□ 更新版本历史和版本号
   278|□ 检查 MODULE.md 约束编号是否需要新增
   279|□ 检查流程文档时间标注是否同步更新
   280|```
   281|
   282|---
   283|
   284|*最后更新: 2026-05-27 19:00 北京时间*