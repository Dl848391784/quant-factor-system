     1|# RSI_1D IC 计算流程文档
     2|
     3|> 生成时间: 2026-05-22 17:00 (北京时间)
     4|> 审阅版本: v1.54
     5|> 实测数据时间: 2026-05-22
     6|> 更新内容: 
     7|>   1. [v1.54] 修正旧函数引用：calculate_daily_ic_series → build_ic_result（公共模块重构后函数名变更）
     8|>   2. [v1.54] 同步代码版本：ic_rsi_1d.py 已移除本地 calculate_daily_ic_series，改用公共模块
     9|>   3. [v1.54] 更新流程图节点名称，反映实际代码实现 
    10|>   1. 增量计算单日 IC 改用 calculate_single_day_ic 核心函数（遵循 PROJECT.md 规范）
    11|>   2. 移除直接调用 scipy.stats.spearmanr，确保增量与全量计算算法一致
    12|>   3. 增量合并添加去重验证，防止日期重叠污染数据
    13|>   4. 使用字典去重，新值优先覆盖旧值
    14|>   5. [v1.36] 修复增量模式 total_days 语义与全量不一致问题
    15|>   6. [v1.36] 增量模式 total_days 改用 max(raw_metadata['total_days'], factor_df_full['date'].nunique())
    16|>   7. [v1.36] 保包含无效日期，语义与全量模式一致，total_days >= valid_days
    17|>   8. [v1.37] 明确 avg_stocks_per_day 增量模式语义限制
    18|>   9. [v1.37] avg_stocks_per_day/n_assets 只反映当前因子缓存范围，不含历史缓存中已不在当前数据源的日期
    19|>   10. [v1.37] 用户可通过 total_days 判断数据范围，理解统计口径
    20|>   11. [v1.38] 新增增量更新诊断规范：区分"数据源无数据"和"缓存缺失"
    21|>   12. [v1.38] 缺失日期不在缓存范围时打印警告和诊断信息
    22|>   13. [v1.38] 所有缺失日期均不在缓存范围时建议执行全量重算
    23|>   14. [v1.39] 新增增量更新事件记录规范：重叠覆盖事件必须记录到返回数据和 JSON 文件
    24|>   15. [v1.39] 新增 incremental_events 字段：overwritten_dates, overwritten_count, description
    25|>   16. [v1.39] 上游调用方可感知重叠覆盖事件，下次可复现问题
    26|>   17. [v1.40] 新增增量计算进度显示规范：完整展示总计算天数、有效天数、无效天数
    27|>   18. [v1.40] 修复信息展示不完整问题：打印"100 天计算，80 天有效，20 天跳过"
    28|>   19. [v1.40] 用户可判断数据源覆盖范围和数据质量
    29|>   20. [v1.41] 新增异常处理规范：必须保留原始异常类型和堆栈信息
    30|>   21. [v1.41] _full_recalculate 异常处理改为分层捕获：FileNotFoundError/JSONDecodeError/KeyError/ValueError
    31|>   22. [v1.41] 使用 raise ... from e 语法保留堆栈信息，用户可追溯问题来源
    32|>   23. [v1.42] 新增参数传递规范：关键参数必须通过函数签名传递，禁止多处硬编码
    33|>   24. [v1.42] 添加 DEFAULT_MIN_STOCKS 常量，统一管理 min_stocks 阈值
    34|>   25. [v1.42] 所有函数签名接受 min_stocks 参数，消除硬编码分散问题
    35|>   26. [v1.42] 用户可配置参数，无需修改多处代码
    36|>   27. [v1.43] 新增返回值标记规范：三种模式返回值必须标记 update_mode 字段
    37|>   28. [v1.43] skip 模式返回值添加 update_mode='skip' 标记
    38|>   29. [v1.43] skip-fallback 场景返回值添加 fallback_event 字段记录原计划与实际执行模式
    39|>   30. [v1.43] 调用方可通过返回值区分"缓存读取"和"意外触发全量计算"，避免长时间计算时毫不知情
    40|>   31. [v1.43] fallback_event 字段包含：original_mode, actual_mode, trigger_reason, error_message, description
    41|>   32. [v1.44] 新增错误信息格式规范：枚举类错误必须包含合法值列表
    42|>   33. [v1.44] 未知模式 RuntimeError 补充合法值列表 ['skip', 'incremental', 'full']
    43|>   34. [v1.44] 参考 KeyError 处理格式（第120-125行可用列列表），统一错误信息风格
    44|>   35. [v1.45] 新增 convert_to_native_types 行为验证规范：必须有单元测试验证 NaN → None → null
    45|>   36. [v1.45] 新增 test_convert_types.py 测试文件，验证 JSON 序列化行为一致性
    46|>   37. [v1.45] 引用 PROJECT.md NaN 处理规范，明确 convert_to_native_types 是兜底保障
    47|>   38. [v1.46] 新增函数签名变更同步规范：返回值变更时必须同步更新类型注解和 docstring
    48|>   39. [v1.46] load_data_from_cache 返回值从2个变成3个，类型注解同步更新为 Tuple[..., ..., dict]
    49|>   40. [v1.46] docstring 返回值描述同步更新，明确三个返回值及其语义
    50|>   41. [v1.47] 新增等价性验证三重保障机制规范：代码架构 + 单元测试 + 文档规范
    51|>   42. [v1.47] 新增 TestAlgorithmEquivalence.test_full_incremental_equivalence_multi_day：验证多日期场景等价性
    52|>   43. [v1.47] 补充 Step 4.5 强制保障机制章节：明确方向处理无反转逻辑
    53|>   44. [v1.48] 新增日期字符串比较规范：比较操作前必须添加格式断言（遵循 PROJECT.md 规范）
    54|>   45. [v1.48] 增量模式 period 比较前添加 YYYY-MM-DD 格式验证，防御未来其他代码路径引入未转换日期
    55|>   46. [v1.49] 新增字典构建规范：字段应集中定义在构建阶段，避免分散赋值
    56|>   47. [v1.49] 删除 update_mode 重复赋值，确保字段定义位置唯一
    57|>   48. [v1.50] 新增输出字段口径规范：统计字段必须明确口径范围
    58|>   49. [v1.50] avg_stocks_per_day 字段添加 avg_stocks_period 子字段描述口径范围
    59|>   50. [v1.50] 删除误导性注释，通过结构化字段让用户感知统计口径
    60|>   51. [v1.51] 修复 ValueError 异常处理：删除 RuntimeError 包装，直接 raise（遵循 PROJECT.md 异常处理类型保留规范）
    61|>   52. [v1.51] 数据验证错误保留原始异常类型，调用方可用 except ValueError 捕获
    62|>   53. [v1.51] 补充 PROJECT.md 「异常处理类型保留规范」章节：区分基础设施错误和数据验证错误
    63|>   54. [v1.52] 补充 PROJECT.md 「avg_stocks_per_day 计算口径规范」章节
    64|>   55. [v1.52] 明确 avg_stocks_per_day 基于 dropna 后数据，与 total_days 口径不同
    65|>   56. [v1.52] 解释均值偏高原因：NaN 日期被排除，这些日期通常股票数较少
    66|>   57. [v1.52] 提供口径一致性检查表，确保用户理解统计含义
    67|>   58. [v1.53] 修复 ic_metrics 字段缺失问题：添加 p_value 和 p_value_display（遵循 MODULE.md 输出结构规范）
    68|>   59. [v1.53] 导入 calculate_ic_statistics 移至顶部（遵循 PEP8 导入规范）
    69|>   60. [v1.53] required_fields 校验添加 p_value、p_value_display
    70|>   61. [v1.53] 全量/增量路径 ic_metrics 结构一致，跨脚本验证通过（RSI/布林带/KDJ 三脚本 5 字段一致）
    71|>
    72|
    73|---
    74|
    75|## 📋 整体架构
    76|
    77|```
    78|┌─────────────────────────────────────────────────────────────────┐
    79|│                    ic_rsi_1d.py 主流程                           │
    80|├─────────────────────────────────────────────────────────────────┤
    81|│  入口: generate_rsi_ic_data()                                    │
    82|│    ↓                                                             │
    83|│  [1] 参数类型转换 → output_file 统一转为 Path                      │
    84|│    ↓                                                             │
    85|│  [2] 数据完整性检查 → 决定是否需要计算                             │
    86|│    ↓                                                             │
    87|│  [3] 从缓存加载因子数据和收益数据                                   │
    88|│    ↓                                                             │
    89|│  [4] 调用 calculate_ic_with_direction_verification()             │
    90|│      - 先用原始 RSI 值计算正向 IC（Spearman）                      │
    91|│      - 根据 IC 均值和 p 值判断因子方向                             │
    92|│      - 输出 factor_direction 和 direction_confidence             │
    93|│    ↓                                                             │
    94|│  [5] 保存结果到 JSON 文件                                          │
    95|└─────────────────────────────────────────────────────────────────┘
    96|```
    97|
    98|---
    99|
   100|## 🔍 详细流程步骤
   101|
   102|### Step 1: 参数类型转换
   103|
   104|```
   105|generate_rsi_ic_data(output_file) 入口
   106|    │
   107|    ├── output_file is None?
   108|    │       │
   109|    │       ├── Yes → output_file = get_ic_output_path('rsi_1d')  # 返回 Path
   110|    │       │
   111|    │       └── No → output_file = Path(output_file)  # str → Path
   112|    │
   113|    └── output_file 现为 Path 对象，后续可安全使用 .parent.mkdir()
   114|```
   115|
   116|**规范依据**：PROJECT.md 参数类型约定
   117|
   118|---
   119|
   120|### Step 2: 增量判断（数据完整性检查）
   121|
   122|```
   123|check_data_completeness('rsi_1d')
   124|    │
   125|    ├── mode='skip'（缓存已最新）
   126|    │       │
   127|    │       ├── 读取缓存成功 ──→ return 缓存数据
   128|    │       │
   129|    │       └── 读取缓存失败 ──→ print warning ──→ fallback 到全量计算
   130|    │           │                   （无 return，代码继续向下执行）
   131|    │           │
   132|    │           └── 这是合理的容错设计，不是 bug
   133|    │               必须有注释说明 fallback 行为
   134|    │
   135|    ├── mode='incremental'（有缺失日期）
   136|    │       │
   137|    │       └── 调用 _incremental_update()
   138|    │               │
   139|    │               ├── 合并日期-IC值配对
   140|    │               │   paired = zip(existing) + zip(new)
   141|    │               │
   142|    │               ├── 按日期升序排序（关键步骤）
   143|    │               │   paired.sort(key=lambda x: x[0])
   144|    │               │
   145|    │               ├── 解构为 dates 和 ic_values
   146|    │               │   all_dates = [p[0] for p in paired]
   147|    │               │   all_ic_values = [p[1] for p in paired]
   148|    │               │
   149|    │               ├── 保留位置信息（过滤 None）
   150|    │               │   valid_indices = [i for i, ic in enumerate(all_ic_values) if ic is not None]
   151|    │               │   valid_dates = [all_dates[i] for i in valid_indices]  # 按日期升序
   152|    │               │   valid_ic = [all_ic_values[i] for i in valid_indices]
   153|    │               │
   154|    │               ├── 创建 ic_series（遵循输入约束）
   155|    │               │   ic_series = pd.Series(valid_ic, index=valid_dates)
   156|    │               │   # 约束：valid_dates 必须按日期升序排列
   157|    │               │   # （calculate_ic_statistics 输入约束：索引顺序决定输出顺序）
   158|    │               │
   159|    │               ├── 计算统计指标
   160|    │               │   result = calculate_ic_statistics(ic_series)
   161|    │               │   # 输出：rolling_ic_mean 长度 = len(ic_series)
   162|    │               │
   163|    │               ├── 防御性验证（v1.19 新增）
   164|    │               │   if len(rolling_ic_mean_raw) != len(valid_ic):
   165|    │               │       raise RuntimeError("长度不匹配，可能索引错位")
   166|    │               │
   167|    │               └── 将 rolling_ic_mean 映射回 all_dates
   168|    │                   │   valid_indices_set = set(valid_indices)  # O(1) 查找
   169|    │                   │
   170|    │                   │   for i in range(len(all_dates)):
   171|    │                   │       if i in valid_indices_set:
   172|    │                   │           aligned.append(rolling_ic_mean_raw[idx])
   173|    │                   │       else:
   174|    │                   │           aligned.append(None)
   175|    │                   │
   176|    │                   （None 日期填 None，与 dates/ic_values 长度一致）
   177|    │
   178|    └── mode='full'（缓存不存在或 force_full=True）
   179|            │
   180|            └── 进入全量计算流程
   181|```
   182|
   183|**三种模式完整行为流程（遵循 PROJECT.md 异常处理规范）**：
   184|
   185|| 模式 | 条件 | 正常行为 | 异常行为 |
   186||------|------|---------|---------|
   187|| `skip` | 缓存已最新 | 返回现有缓存数据 | fallback 到全量计算 |
   188|| `incremental` | 有缺失日期 | 追加新日期 IC | fallback 到全量计算 |
   189|| `full` | 缓存不存在 | 全量计算 | 抛出异常（数据源不可用） |
   190|
   191|---
   192|
   193|### Step 2.1: 返回值标记规范（v1.43 新增）
   194|
   195|**遵循 PROJECT.md 返回值标记规范：三种模式返回值必须标记 update_mode 字段，调用方可感知实际执行的模式。**
   196|
   197|```
   198|generate_rsi_ic_data() 返回值结构
   199|    │
   200|    ├── mode='skip'（缓存已最新，读取成功）
   201|    │       │
   202|    │       └── 返回值包含：
   203|    │           {
   204|    │               ...原有缓存数据...,
   205|    │               'update_mode': 'skip'  // 标记：从缓存读取
   206|    │           }
   207|    │           // 调用方判断：result['update_mode'] == 'skip' → 无计算开销
   208|    │
   209|    ├── mode='skip' + fallback（缓存读取失败，触发全量计算）
   210|    │       │
   211|    │       └── 返回值包含：
   212|    │           {
   213|    │               ...全量计算数据...,
   214|    │               'update_mode': 'full',  // 标记：实际执行了全量计算
   215|    │               'fallback_event': {
   216|    │                   'original_mode': 'skip',           // 原本期望的模式
   217|    │                   'actual_mode': 'full',             // 实际执行的模式
   218|    │                   'trigger_reason': 'cache_read_failed', // 触发原因
   219|    │                   'error_message': str(e),           // 原始错误信息
   220|    │                   'description': f"缓存读取失败，触发全量计算。原始错误: {e}"
   221|    │               }
   222|    │           }
   223|    │           // 调用方判断：result['update_mode'] == 'full' && 'fallback_event' in result → 意外触发全量计算
   224|    │           // 重要场景：全量计算耗时很长，调用方需要感知，避免毫不知情
   225|    │
   226|    ├── mode='incremental'（有缺失日期）
   227|    │       │
   228|    │       └── 返回值包含：
   229|    │           {
   230|    │               ...合并后数据...,
   231|    │               'update_mode': 'incremental',  // 标记：增量更新
   232|    │               'incremental_events': {
   233|    │                   'overwritten_dates': [...],
   234|    │                   'overwritten_count': N,
   235|    │                   'description': "..."
   236|    │               }
   237|    │           }
   238|    │           // 调用方判断：result['update_mode'] == 'incremental' → 增量计算
   239|    │
   240|    └── mode='full'（缓存不存在或 force_full=True）
   241|            │
   242|            └── 返回值包含：
   243|                {
   244|                    ...全量计算数据...,
   245|                    'update_mode': 'full'  // 标记：全量计算（正常路径）
   246|                }
   247|                // 调用方判断：result['update_mode'] == 'full' && 'fallback_event' not in result → 正常全量计算
   248|```
   249|
   250|**返回值标记设计原则（遵循 PROJECT.md 规范）**：
   251|
   252|| 场景 | update_mode | 附加字段 | 调用方判断逻辑 |
   253||------|------------|---------|---------------|
   254|| 正常 skip | `'skip'` | 无 | `update_mode == 'skip'` → 从缓存读取 |
   255|| skip-fallback | `'full'` | `fallback_event` | `update_mode == 'full' && 'fallback_event' in result` → 意外触发全量 |
   256|| 正常 incremental | `'incremental'` | `incremental_events` | `update_mode == 'incremental'` → 增量更新 |
   257|| 正常 full | `'full'` | 无 | `update_mode == 'full' && 'fallback_event' not in result` → 正常全量 |
   258|
   259|**为何必须标记返回值（设计动机）**：
   260|
   261|```
   262|问题背景：
   263|1. mode='skip' 时读取缓存失败会 fallback 到全量计算
   264|2. fallback 后返回值与正常全量计算返回值结构相同
   265|3. 调用方拿到的是"正常返回值"，无法区分来源
   266|4. 若全量计算耗时很长（如计算1000天IC），调用方毫不知情
   267|
   268|解决方案：
   269|1. 返回值必须标记 update_mode 字段
   270|2. fallback 场景必须添加 fallback_event 字段记录原计划与实际执行模式
   271|3. 调用方可通过返回值感知实际发生了什么，避免长时间计算时毫不知情
   272|
   273|设计一致性：
   274|- 增量模式已有 update_mode='incremental' + incremental_events 设计
   275|- skip-fallback 场景采用相同设计模式（update_mode + fallback_event）
   276|- 确保所有重要事件都能通过返回值传递给调用方
   277|```
   278|
   279|**调用方典型判断代码示例**：
   280|
   281|```python
   282|result = generate_rsi_ic_data()
   283|
   284|if result['update_mode'] == 'skip':
   285|    print("从缓存读取，无计算开销")
   286|elif result['update_mode'] == 'incremental':
   287|    print(f"增量更新，新增 {result['incremental_days']} 天")
   288|elif result['update_mode'] == 'full':
   289|    if 'fallback_event' in result:
   290|        event = result['fallback_event']
   291|        print(f"意外触发全量计算！原计划: {event['original_mode']}, 实际: {event['actual_mode']}")
   292|        print(f"触发原因: {event['trigger_reason']}")
   293|        print(f"错误信息: {event['error_message']}")
   294|        # 重要：调用方需要记录此事件，因为全量计算耗时可能很长
   295|    else:
   296|        print("正常全量计算")
   297|```
   298|
   299|---
   300|
   301|### Step 3: 数据加载
   302|
   303|```
   304|load_data_from_cache()
   305|    │
   306|    ├── 加载因子缓存: data_fetchers/result/factor_data.json.gz
   307|    │   │
   308|    │   ├── 解压 gzip → JSON
   309|    │   ├── 转为 DataFrame
   310|    │   ├── 提取列: [date, asset, rsi_6]
   311|    │   │
   312|    │   ├── [计算原始数据范围]（v1.28 新增，dropna 前）
   313|    │   │   │
   314|    │   │   ├── raw_period_start = factor_df['date'].min()
   315|    │   │   ├── raw_period_end = factor_df['date'].max()
   316|    │   │   ├── raw_total_days = factor_df['date'].nunique()
   317|    │   │   │
   318|    │   │   └── 语义定义（遵循 PROJECT.md 输出字段语义规范）：
   319|    │   │       - 基于原始缓存数据（dropna 前），而非过滤后数据
   320|    │   │       - 用于 period 和 sample_stats.total_days 计算
   321|    │   │
   322|    │   └── 过滤缺失值（dropna）
   323|    │       - 某日期所有股票因子值为 NaN → 该日期被过滤
   324|    │
   325|    ├── 加载收益缓存: data_fetchers/result/factor_ic_data.json.gz
   326|    │   │
   327|    │   ├── 解压 gzip → JSON
   328|    │   ├── 转为 DataFrame
   329|    │   ├── 提取列: [date, asset, forward_return_1d]
   330|    │   ├── 重命名: forward_return_1d → forward_return
   331|    │   └── 过滤缺失值
   332|    │
   333|    ├── [日期类型转换]（v1.27 新增异常处理）
   334|    │   │
   335|    │   ├── 使用 pd.to_datetime(..., errors='coerce') 处理异常格式
   336|    │   │   - 无效格式（如 "N/A"、空字符串）转为 NaT，不抛 ParserError
   337|    │   │
   338|    │   ├── 检查 NaT 数量
   339|    │   │   - nat_count > 0 → 抛 ValueError，包含无效样本
   340|    │   │   - 错误信息格式：
   341|    │   │       "因子数据中存在 X 个无效日期格式"
   342|    │   │       "无效日期示例: ['N/A', '', 'Invalid', ...]"
   343|    │   │       "请检查缓存数据源是否包含脏数据"
   344|    │   │
   345|    │   └── 转换为字符串 "YYYY-MM-DD"
   346|    │       - 确保 isin 操作类型匹配
   347|    │
   348|    └── 返回 (factor_df, return_df, raw_metadata)
   349|        - factor_df, return_df: 过滤后的数据
   350|        - raw_metadata: {period_start, period_end, total_days}（原始数据范围）
   351|```
   352|
   353|**数据源定义规范（遵循 PROJECT.md）：**
   354|
   355|`period` 和 `total_days` 必须基于**原始缓存数据**（dropna 前），而非过滤后的数据。
   356|
   357|**为何必须使用原始数据：**
   358|
   359|```
   360|load_data_from_cache 中的 dropna 操作可能过滤掉某些日期的全部股票：
   361|1. 某日期所有股票因子值都是 NaN（停牌、数据缺失）
   362|2. dropna 后该日期被完全移除
   363|3. factor_df['date'].min()/max()/nunique() 计算的是过滤后的范围
   364|4. 与语义定义冲突："原始缓存覆盖范围" ≠ "过滤后的数据范围"
   365|
   366|正确做法：
   367|- 在 dropna 之前，先计算 raw_period_start, raw_period_end, raw_total_days
   368|- 返回过滤后的数据 + raw_metadata
   369|- build_ic_result 使用 raw_metadata 构建 sample_stats/period 字段
   370|```
   371|
   372|**日期转换异常处理规范（遵循 PROJECT.md）：**
   373|
   374|| 异常格式 | `pd.to_datetime` 默认行为 | `errors='coerce'` 行为 |
   375||---------|--------------------------|----------------------|
   376|| `"N/A"` | 抛出 `ParserError` | 转为 NaT |
   377|| 空字符串 `""` | 抛出 `ParserError` | 转为 NaT |
   378|| `"Invalid"` | 抛出 `ParserError` | 转为 NaT |
   379|| `"2024-13-01"` | 抛出 `ParserError` | 转为 NaT |
   380|
   381|**为何必须检查 NaT：**
   382|
   383|1. `errors='coerce'` 将无效日期转为 NaT，不抛异常
   384|2. `NaT.strftime('%Y-%m-%d')` 产生字符串 `"NaT"`（不是 None）
   385|3. `"NaT"` 字符串会污染后续计算（isin、日期排序等）
   386|4. 必须在转换后立即检查 NaT 数量，发现脏数据时及时报错
   387|
   388|**输出示例**：
   389|
   390|```
   391|factor_df:
   392|| date       | asset   | rsi_6 |
   393||------------|---------|-------|
   394|| 2026-05-01 | 000001  | 25.5  |
   395|| 2026-05-01 | 000002  | 80.2  |
   396|| ...        | ...     | ...   |
   397|
   398|return_df:
   399|| date       | asset   | forward_return |
   400||------------|---------|----------------|
   401|| 2026-05-01 | 000001  | 0.05           |
   402|| 2026-05-01 | 000002  | -0.02          |
   403|| ...        | ...     | ...            |
   404|```
   405|
   406|---
   407|
   408|### Step 4: IC 计算（核心 - 方向验证流程）
   409|
   410|这是 `calculate_ic_with_direction_verification()` 模块的核心逻辑：
   411|
   412|**遵循 PROJECT.md 规范：因子方向必须根据实际 IC 测试结果确定，不可预设。**
   413|
   414|```
   415|calculate_ic_with_direction_verification(factor_df, return_df)
   416|    │
   417|    ├── [验证] 检查必需列是否存在
   418|    │
   419|    ├── [合并] 按键合并
   420|    │   │
   421|    │   └── merged = pd.merge(factor_df, return_df, on=[date, asset])
   422|    │
   423|    ├── [遍历] 按日期分组，逐日计算正向 IC
   424|    │   │
   425|    │   └─────────────────────────────────────────────┐
   426|    │   │                                             │
   427|    │   │  for each date:                              │
   428|    │   │      │                                       │
   429|    │   │      ├── 股票数 < 10? → 跳过该日              │
   430|    │   │      │                                       │
   431|    │   │      ├── 因子值全部相同? → IC = 0             │
   432|    │   │      │                                       │
   433|    │   │      ├── 收益值全部相同? → IC = 0             │
   434|    │   │      │                                       │
   435|    │   │      └── 计算该日正向 IC:                     │
   436|    │   │          │                                   │
   437|    │   │          └── IC = corr(rsi_6, forward_return, method='spearman')
   438|    │   │              # 使用原始 RSI 值，不反转        │
   439|    │   │                                              │
   440|    │   └─────────────────────────────────────────────┘
   441|    │
   442|    ├── [统计量] Newey-West 调整的 t 统计量和 p 值
   443|    │   │
   444|    │   ├── ic_mean = ic_series.mean()
   445|    │   ├── ic_std = ic_series.std()
   446|    │   ├── icir = |ic_mean| / ic_std  # 使用绝对值（PROJECT.md 规范）
   447|    │   ├── t_stat, p_value, nw_lag = newey_west_t_stat(ic_series)  # 自动选择lag
   448|    │   └── positive_ratio = IC > 0 的天数占比
   449|    │
   450|    ├── [五维度判断] 独立输出，不合并
   451|    │   │
   452|    │   ┌─────────────────────────────────────────────────────────────┐
   453|    │   │ 五维度判断（PROJECT.md 规范 - 独立输出）:                      │
   454|    │   │                                                           │
   455|    │   │ 维度1: 统计显著性                                          │
   456|    │   │   p_value < 0.05 → is_significant: true                  │
   457|    │   │   （详见 PROJECT.md "统计显著性判断简化"章节）              │
   458|    │   │   输出: nw_lag（实际使用的滞后阶数）                         │
   459|    │   │                                                           │
   460|    │   │ 维度2: 因子方向（仅符号判断，不含阈值）                       │
   461|    │   │   ic_mean < -1e-6 → negative（反向因子）                   │
   462|    │   │   ic_mean > 1e-6  → positive（正向因子）                   │
   463|    │   │   ic_mean ≈ 0     → zero（方向不明）                        │
   464|    │   │   注意: 方向判断仅描述符号，不代表有效性                     │
   465|    │   │                                                           │
   466|    │   │ 维度3: 经济显著性                                          │
   467|    │   │   |ic_mean| >= 0.05 → strong                              │
   468|    │   │   |ic_mean| >= 0.03 → weak                                │
   469|    │   │   |ic_mean| < 0.03  → none                                │
   470|    │   │                                                           │
   471|    │   │ 维度4: ICIR稳定性                                          │
   472|    │   │   ICIR >= 2.0  → excellent                                │
   473|    │   │   ICIR >= 1.0  → good                                     │
   474|    │   │   ICIR >= 0.5  → usable                                   │
   475|    │   │   ICIR < 0.5   → none                                     │
   476|    │   │                                                           │
   477|    │   │ 维度5: IC分布一致性                                        │
   478|    │   │   positive_ratio 与 ic_mean_sign 匹配判断                 │
   479|    │   │                                                           │
   480|    │   │   ⚠️ 核心原则：规则按序执行（if-elif链），匹配后直接返回      │
   481|    │   │                                                           │
   482|    │   │   判断规则（含优先级标注）：                                  │
   483|    │   │   优先级1（最高）: ic_mean_sign = 'zero' → balanced        │
   484|    │   │   优先级2: 正向因子 positive_ratio >= 50% → consistent    │
   485|    │   │   优先级2: 反向因子 positive_ratio <= 50% → consistent    │
   486|    │   │   优先级3: positive_ratio ∈ [49%, 51%] → balanced         │
   487|    │   │            （闭区间，代码用<=0.011应对浮点精度）         │
   488|    │   │   优先级4: 其他情况 → contradictory                        │
   489|    │   │                                                           │
   490|    │   │   边界示例（边界对称设计）：                                │
   491|    │   │   正向因子 49% → balanced（优先级3）                       │
   492|    │   │   正向因子 50% → consistent（优先级2）                     │
   493|    │   │   反向因子 50% → consistent（优先级2）                     │
   494|    │   │   反向因子 51% → balanced（优先级3）                       │
   495|    │   │   （详见 PROJECT.md "IC分布一致性判断边界规范"）            │
   496|    │   │                                                           │
   497|    │   │   输出: is_consistent, consistency_type                   │
   498|    │   │                                                           │
   499|    │   │ ⚠️ 五个维度独立输出，不合并为 valid/invalid                 │
   500|    │   └─────────────────────────────────────────────────────────────┘
   501|   501|    │
   502|    └── 返回结果字典
   503|```
   504|
   505|---
   506|
   507|### Step 4.1: NaN 处理规范（v1.29 新增）
   508|
   509|**遵循 PROJECT.md NaN 处理规范：NaN → None 转换应在数据生成阶段完成。**
   510|
   511|```
   512|calculate_ic_with_direction_verification(factor_df, return_df, raw_metadata)
   513|    │
   514|    ├── [计算 IC] 调用 calculate_ic_with_direction_verification
   515|    │
   516|    ├── [转换日期和 IC 值]
   517|    │   │
   518|    │   ├── dates = [str(d) for d in ic_series.index]
   519|    │   ├── ic_values = [round(v, 6) for v in ic_series.values]
   520|    │
   521|    ├── [计算 rolling_ic_mean]
   522|    │   │
   523|    │   ├── rolling_mean = ic_series.rolling(window=20, min_periods=10).mean()
   524|    │   │   - 前 9 天不满 min_periods=10 → 返回 NaN
   525|    │   │
   526|    │   ├── [NaN 处理]（遵循 PROJECT.md NaN 处理规范）
   527|    │   │   │
   528|    │   │   ├── 使用 pd.isna(v) 检查 NaN
   529|    │   │   ├── NaN → None（语义转换："无有效数据"）
   530|    │   │   │
   531|    │   │   └── rolling_ic_mean = [
   532|    │   │           round(v, 6) if not pd.isna(v) else None
   533|    │   │           for v in rolling_mean.values
   534|    │   │       ]
   535|    │   │
   536|    │   └── 为何必须在数据生成阶段处理：
   537|    │       1. 语义一致性：None 表示"无有效数据"，nan 是浮点数运算结果
   538|    │       2. 增量路径用 None 填充无效日期，全量路径用 NaN 填充不满 min_periods 的日期
   539|    │       3. 若延迟到 convert_to_native_types 处理，语义不一致
   540|    │       4. JSON 序列化时 None → null，标准 JSON 不支持 nan
   541|    │
   542|    └── [防御性校验] 确保 dates 升序排列 + 长度一致
   543|```
   544|
   545|---
   546|
   547|### Step 4.2: 日期排序规范（v1.30 新增）
   548|
   549|**遵循 PROJECT.md ic_series 排序规范：ic_series.index 必须按日期升序排列。**
   550|
   551|```
   552|calculate_ic_with_direction_verification(factor_df, return_df)
   553|    │
   554|    ├── [按日期计算 IC]
   555|    │   │
   556|    │   ├── for date, daily_data in merged.groupby(date_col):
   557|    │   │       ic_list.append({'date': date, 'ic': ic_value})
   558|    │   │
   559|    │   ├── ic_df = pd.DataFrame(ic_list)
   560|    │   ├── ic_series = ic_df.set_index('date')['ic']
   561|    │   │
   562|    │   ├── [显式排序]（遵循 PROJECT.md ic_series 排序规范）
   563|    │   │   │
   564|    │   │   └── ic_series = ic_series.sort_index()
   565|    │   │
   566|    │   └── 为何必须显式排序：
   567|    │       1. rolling 计算按位置顺序，而非 index 值顺序
   568|    │       2. 若 ic_series.index 乱序 → dates 与 rolling_ic_mean 对应错误
   569|    │       3. pandas groupby 默认 sort=True，但不应依赖隐式行为
   570|    │       4. 版本升级风险：pandas 可能改变默认行为
   571|    │       5. 增量路径合并后可能乱序
   572|    │
   573|    └── [返回 ic_series]
   574|```
   575|
   576|**防御性校验：**
   577|
   578|```
   579|build_ic_result(ic_result, raw_metadata, factor_name)
   580|    │
   581|    ├── [长度校验]
   582|    │   ├── len(dates) == len(ic_values)
   583|    │   └── len(dates) == len(rolling_ic_mean)
   584|    │
   585|    ├── [日期顺序校验]（遵循 PROJECT.md ic_series 排序规范）
   586|    │   │
   587|    │   └── if dates != sorted(dates):
   588|    │           raise RuntimeError("dates 未按升序排列")
   589|    │
   590|    └── 为何必须校验日期顺序：
   591|        1. 长度一致不代表语义对应正确
   592|        2. 若 dates 乱序，dates[i] 与 rolling_ic_mean[i] 对应错误
   593|        3. rolling_ic_mean[i] 是位置 i 的滚动均值，应对应 dates[i]
   594|        4. 若 dates[0]='2026-05-02', dates[1]='2026-05-01'
   595|           → rolling_ic_mean[0] 对应 '2026-05-02'（语义错误）
   596|```
   597|
   598|**ic_series 排序规范要点：**
   599|
   600|| 规范项 | 位置 | 说明 |
   601||-------|------|------|
   602|| 显式排序 | ic_calculator.py | `ic_series = ic_series.sort_index()` |
   603|| 防御性校验 | ic_rsi_1d.py | `if dates != sorted(dates): raise RuntimeError` |
   604|
   605|---
   606|
   607|### Step 4.3: 函数返回值契约校验（v1.31 新增）
   608|
   609|**遵循 PROJECT.md 函数返回值契约规范：调用方必须校验返回值字段存在性。**
   610|
   611|```
   612|generate_rsi_ic_data(factor_df, return_df, raw_metadata)
   613|    │
   614|    ├── [调用函数]
   615|    │   │
   616|    │   └── result = calculate_ic_with_direction_verification(...)
   617|    │
   618|    ├── [契约校验]（遵循 PROJECT.md 函数返回值契约规范）
   619|    │   │
   620|    │   ├── 定义必需字段列表：
   621|    │   │   required_fields = [
   622|    │   │       'ic_series', 'ic_mean', 'ic_std', 'icir',
   623|    │   │       'statistical_significance', 'factor_direction',
   624|    │   │       'economic_significance', 'icir_stability',
   625|    │   │       'ic_distribution_consistency', 'positive_ratio', 'n_days'
   626|    │   │   ]
   627|    │   │
   628|    │   ├── 检查缺失字段：
   629|    │   │   missing_fields = [f for f in required_fields if f not in result]
   630|    │   │
   631|    │   └── 若缺失字段 → 抛出 RuntimeError：
   632|    │       │
   633|    │       └── raise RuntimeError(
   634|    │               f"calculate_ic_with_direction_verification 返回值缺少必需字段\n"
   635|    │               f"缺失字段: {missing_fields}\n"
   636|    │               f"问题定位: factor_ic/common/ic_calculator.py\n"
   637|    │               f"期望字段: {required_fields}"
   638|    │           )
   639|    │
   640|    └── [安全访问]
   641|        │
   642|        └── ic_series = result['ic_series']  # 校验通过后安全访问
   643|```
   644|
   645|**为何必须校验返回值字段：**
   646|
   647|```
   648|1. 直接下标访问 result['field'] 会抛出 KeyError
   649|2. KeyError 错误信息：KeyError: 'ic_mean' ← 无法判断问题模块
   650|3. 函数返回值结构变更时，调用方静默失败
   651|4. 校验后的 RuntimeError 包含：
   652|   - 缺失字段列表（missing_fields）
   653|   - 问题定位（模块路径）
   654|   - 期望字段列表（required_fields）
   655|```
   656|
   657|**错误信息对比：**
   658|
   659|| 场景 | 未校验（KeyError） | 已校验（RuntimeError） |
   660||-----|-------------------|----------------------|
   661|| 错误信息 | `KeyError: 'ic_mean'` | `calculate_ic_with_direction_verification 返回值缺少必需字段\n缺失字段: ['ic_mean']\n问题定位: factor_ic/common/ic_calculator.py\n期望字段: [...]` |
   662|| 问题定位 | 无法判断 | 明确模块路径 |
   663|| 排查效率 | 低（需逐行检查） | 高（直接定位） |
   664|
   665|---
   666|
   667|### Step 4.4: 增量计算 None 处理规范（v1.32 新增）
   668|
   669|**遵循 PROJECT.md 增量计算 None 处理规范：增量计算中 None（股票数不足）的处理必须与全量计算保持一致。**
   670|
   671|```
   672|_incremental_update(missing_dates, output_file)
   673|    │
   674|    ├── [读取现有缓存]
   675|    │   │
   676|    │   ├── existing_dates = existing_data.get('dates', [])
   677|    │   ├── existing_ic_values = existing_data.get('ic_values', [])
   678|    │   │
   679|    │   └── 注意：来自全量计算，只有有效 IC 日期（不含 None）
   680|    │
   681|    ├── [计算新日期 IC]
   682|    │   │
   683|    │   ├── new_dates = sorted(factor_df_new['date'].unique())
   684|    │   ├── new_ic_values = []
   685|    │   │
   686|    │   ├── for date in new_dates:
   687|    │   │       ic_value = calculate_single_day_ic(...)
   688|    │.      │       new_ic_values.append(ic_value if ic_value is not None else None)
   689|    │   │
   690|    │   └── 注意：new_ic_values 可能含 None（股票数不足）
   691|    │
   692|    ├── [合并数据]
   693|    │   │
   694|    │   ├── [None 过滤]（遵循 PROJECT.md 增量计算 None 处理规范）
   695|    │   │   │
   696|    │   │   ├── date_ic_map = {}
   697|    │   │   ├── for date, ic in zip(existing_dates, existing_ic_values):
   698|    │   │   │       date_ic_map[date] = ic  # 只有有效 IC 值
   699|    │   │   │
   700|    │   │   └── for date, ic in zip(new_dates, new_ic_values):
   701|    │   │           if ic is not None:  # 只写入有效 IC 值（过滤股票数不足的 None）
   702|    │   │               date_ic_map[date] = ic
   703|    │   │
   704|    │   └── 为何必须过滤 None：
   705|    │       1. 全量计算：dates = ic_series.index（只有有效 IC 日期）
   706|    │       2. 增量计算：若写入 None → date_ic_map[date] = None
   707|    │       3. 合并后：existing_dates 不含 None，new_dates 可能含 None → 语义混乱
   708|    │       4. 统一语义：ic_values 不存储"股票数不足"的 None
   709|    │
   710|    └── [解构合并数据]
   711|        │
   712|        ├── all_dates = sorted(date_ic_map.keys())
   713|        └── all_ic_values = [date_ic_map[d] for d in all_dates]  # 不含 None
   714|```
   715|
   716|**None 语义定义：**
   717|
   718|| None 来源 | 语义 | 是否存储 |
   719||----------|------|---------|
   720|| `calculate_single_day_ic` 返回 None | 股票数 < min_stocks | **不存储**（过滤） |
   721|| 全量计算中 ic_series.index | 只有有效 IC 日期 | 不含 None |
   722|| 增量计算中 new_ic_values | 可能含 None | **过滤后存储** |
   723|
   724|**为何必须统一语义：**
   725|
   726|```
   727|问题：date_ic_map 混合"有效 IC 值"和"股票数不足的 None"
   728|1. existing_dates 不含 None（全量过滤）
   729|2. new_dates 可能含 None（股票数不足）
   730|3. 若不过滤 → date_ic_map[date] = None
   731|4. all_dates 中某些日期 ic_values = None，但语义不明确
   732|5. total_days - valid_days = 股票数不足跳过的日期数
   733|
   734|修复：增量计算合并时过滤 None（只写入有效 IC 值）
   735|结果：ic_values 不存储"股票数不足"的 None（与全量语义一致）
   736|```
   737|
   738|---
   739|
   740|### Step 4.5: 全量/增量 IC 计算等价性规范（v1.33 新增）
   741|
   742|**遵循 PROJECT.md 全量/增量 IC 计算等价性规范：全量计算与增量计算必须使用同一核心函数（calculate_single_day_ic）。**
   743|
   744|```
   745|全量/增量 IC 计算等价性验证
   746|    │
   747|    ├── [核心函数一致性]
   748|    │   │
   749|    │   ├── 全量计算路径
   750|    │   │   │
   751|    │   │   ├── calculate_ic_with_direction_verification()
   752|    │   │   │       │
   753|    │   │   │       ├── 内部调用 calculate_single_day_ic（第157-159行）
   754|    │   │   │       │   for date in dates:
   755|    │   │   │       │       ic = calculate_single_day_ic(...)
   756|    │   │   │       │       ic_series[date] = ic
   757|    │   │   │       │
   758|    │   │   │       └── docstring 必须说明：
   759|    │   │   │           "本函数内部调用 calculate_single_day_ic 计算每日 IC"
   760|    │   │   │
   761|    │   │   └── 增量计算路径
   762|    │   │       │
   763|    │   │       ├── _incremental_update()
   764|    │   │       │       │
   765|    │   │       │       ├── 直接调用 calculate_single_day_ic（第364-366行）
   766|    │   │       │       │   for date in missing_dates:
   767|    │   │       │       │       ic = calculate_single_day_ic(...)
   768|    │   │       │       │       if ic is not None:
   769|    │   │       │       │           date_ic_map[date] = ic
   770|    │   │       │       │
   771|    │   │       │       └── 注释必须说明：
   772|    │   │       │           "使用核心函数，确保与全量计算算法一致"
   773|    │   │       │
   774|    │   │       └── 等价性：两者使用同一 calculate_single_day_ic
   775|    │   │
   776|    │   └── [边界处理一致性]
   777|    │       │
   778|    │       ├── 股票数 < min_stocks → calculate_single_day_ic 返回 None
   779|    │       │   ├── 全量：跳过该日（dates 不含该日）
   780|    │       │   └── 增量：过滤 None（date_ic_map 不含该日）
   781|    │       │   └── 结果一致 ✓
   782|    │       │
   783|    │       ├── 因子值全相同 → calculate_single_day_ic 返回 0.0
   784|    │       │   ├── 全量：ic_series[date] = 0.0
   785|    │       │   └── 增量：date_ic_map[date] = 0.0
   786|    │       │   └── 结果一致 ✓
   787|    │       │
   788|    │       └── 收益值全相同 → calculate_single_day_ic 返回 0.0
   789|    │       │   ├── 全量：ic_series[date] = 0.0
   790|    │       │   └── 增量：date_ic_map[date] = 0.0
   791|    │       │   └── 结果一致 ✓
   792|    │
   793|    ├── [单元测试验证]
   794|    │   │
   795|    │   ├── test_full_incremental_same_core_function()
   796|    │   │   │
   797|    │   │   ├── 构造测试数据（单日，20只股票）
   798|    │   │   ├── 全量：calculate_ic_with_direction_verification()
   799|    │   │   ├── 增量：calculate_single_day_ic()
   800|    │   │   ├── 验证：abs(full_ic - incremental_ic) < 1e-6 ✓
   801|    │   │   │
   802|    │   │   └── 结论：两者产生相同 IC 值
   803|    │   │
   804|    │   ├── test_boundary_handling_equivalence_insufficient_stocks()
   805|    │   │   │
   806|    │   │   ├── 构造测试数据（5只股票 < min_stocks=10）
   807|    │   │   ├── 全量：calculate_ic_with_direction_verification()
   808|    │   │   ├── 增量：calculate_single_day_ic()
   809|    │   │   ├── 验证：incremental_ic is None ✓
   810|    │   │   │
   811|    │   │   └── 结论：股票数不足时两者都返回 None
   812|    │   │
   813|    │   └── test_boundary_handling_equivalence_constant_factor()
   814|    │   │   │
   815|    │   │   ├── 构造测试数据（因子值全相同）
   816|    │   │   ├── 全量：calculate_ic_with_direction_verification()
   817|    │   │   ├── 增量：calculate_single_day_ic()
   818|    │   │   ├── 验证：两者都返回 0.0 ✓
   819|    │   │   │
   820|    │   │   └── 结论：因子值全相同时两者都返回 0.0
   821|    │
   822|    └── [修改代码时必须同步更新]
   823|        │
   824|        ├── 修改 calculate_single_day_ic 边界处理
   825|        │   ├── 更新 calculate_ic_with_direction_verification docstring
   826|        │   ├── 更新单元测试验证等价性
   827|        │   └── 原因：确保等价性定义一致
   828|        │
   829|        ├── 修改 calculate_ic_with_direction_verification 内部逻辑
   830|        │   ├── 更新单元测试验证
   831|        │   ├── 原因：确保仍调用 calculate_single_day_ic
   832|        │   │
   833|        └── 修改增量计算路径调用方式
   834|            ├── 更新单元测试验证
   835|            ├── 原因：确保仍使用 calculate_single_day_ic
   836|```
   837|
   838|**为何必须等价：**
   839|
   840|```
   841|问题：全量与增量使用不同算法
   842|1. 全量计算使用 calculate_single_day_ic（有边界处理）
   843|2. 增量计算直接调用 scipy.stats.spearmanr（无边界处理）
   844|3. 边界情况结果不一致：
   845|   - 股票数不足：全量返回 None，增量可能返回 NaN
   846|   - 因子全相同：全量返回 0.0，增量可能返回 NaN
   847|4. 合并后数据语义混乱（同一日期全量/增量结果不一致）
   848|
   849|修复：
   850|1. 增量计算改用 calculate_single_day_ic（遵循 PROJECT.md 规范）
   851|2. 添加单元测试验证等价性
   852|3. 修改代码时同步更新 docstring 和单元测试
   853|
   854|结果：
   855|1. 全量/增量使用同一核心函数 ✓
   856|2. 边界处理一致 ✓
   857|3. 单元测试验证等价性 ✓
   858|```
   859|
   860|**禁止行为：**
   861|
   862|```python
   863|# ❌ 禁止：增量计算不使用 calculate_single_day_ic
   864|# 增量计算路径
   865|for date in missing_dates:
   866|    daily_data = merged[merged['date'] == date]
   867|    factor_values = daily_data['rsi_6'].values
   868|    return_values = daily_data['forward_return'].values
   869|    ic_value = scipy.stats.spearmanr(factor_values, return_values)[0]  # ❌
   870|    # 问题：
   871|    #   1. 全量使用 calculate_single_day_ic（有边界处理）
   872|    #   2. 增量直接调用 spearmanr（无边界处理）
   873|    #   3. 边界情况结果不一致
   874|
   875|# ✓ 正确：增量计算使用 calculate_single_day_ic
   876|for date in missing_dates:
   877|    daily_data = merged[merged['date'] == date]
   878|    ic_value = calculate_single_day_ic(
   879|        daily_data,
   880|        factor_col='rsi_6',
   881|        return_col='forward_return',
   882|        min_stocks=10
   883|    )
   884|    if ic_value is not None:
   885|        date_ic_map[date] = ic_value
   886|```
   887|
   888|**注意事项：**
   889|
   890|```
   891|1. calculate_ic_with_direction_verification docstring 必须明确说明内部调用 calculate_single_day_ic
   892|2. ic_rsi_1d.py 增量计算注释必须说明"使用核心函数，确保算法一致性"
   893|3. 单元测试必须验证全量/增量对同一日期产生相同 IC 值
   894|4. 修改核心函数时，必须检查等价性是否被破坏
   895|```
   896|
   897|**强制保障机制（v1.47 新增）：**
   898|
   899|```
   900|等价性验证三重保障机制
   901|    │
   902|    ├── [第一层：代码架构保障]
   903|    │   │
   904|    │   ├── 设计原则：全量/增量调用同一函数
   905|    │   │   ├── 全量路径：calculate_ic_with_direction_verification 内部调用 calculate_single_day_ic
   906|    │   │   └── 增量路径：直接调用 calculate_single_day_ic
   907|    │   │   └── 强制保障：两者无法独立演化，修改一处必影响另一处
   908|    │   │
   909|    │   ├── 方向处理保障：
   910|    │   │   ├── calculate_single_day_ic：计算原始 IC（不反转）
   911|    │   │   ├── _assess_factor_direction：只判断方向（不修改 IC 值）
   912|    │   │   ├── 返回的 ic_series：原始 IC 值（无负号）
   913|    │   │   └── 结论：不存在"方向相差负号"风险
   914|    │   │
   915|    │   └── 代码位置验证：
   916|    │       ├── ic_calculator.py:163-165（全量调用 calculate_single_day_ic）
   917|    │       ├── ic_rsi_1d.py:406-408（增量调用 calculate_single_day_ic）
   918|    │       └── 两者参数完全一致
   919|    │
   920|    ├── [第二层：单元测试保障]
   921|    │   │
   922|    │   ├── TestAlgorithmEquivalence 类（ic_rsi_1d_test_cases.py:472）
   923|    │   │
   924|    │   ├── test_full_incremental_same_core_function
   925|    │   │   ├── 验证：单日期场景，两者产生相同 IC 值
   926|    │   │   └── 断言：abs(incremental_ic - full_ic) < 1e-6
   927|    │   │
   928|    │   ├── test_boundary_handling_equivalence_insufficient_stocks
   929|    │   │   ├── 验证：股票数不足边界，两者行为一致
   930|    │   │   └── 断言：增量返回 None，全量抛出 ValueError
   931|    │   │
   932|    │   ├── test_boundary_handling_equivalence_constant_factor
   933|    │   │   ├── 验证：因子值全相同边界，两者返回 0.0
   934|    │   │   └── 断言：incremental_ic == 0.0, full_ic == 0.0
   935|    │   │
   936|    │   ├── test_full_incremental_equivalence_multi_day（v1.47 新增）
   937|    │   │   ├── 验证：多日期场景，逐日 IC 值一致性
   938|    │   │   ├── 验证：ic_mean 一致性
   939|    │   │   ├── 验证：方向一致性（factor_direction 与 incremental_ic_mean 符号匹配）
   940|    │   │   └── 断言：abs(full_ic - incremental_ic) < 1e-6（每个日期）
   941|    │   │
   942|    │   └── 运行命令：
   943|    │       pytest factor_ic/test_cases/ic_rsi_1d_test_cases.py::TestAlgorithmEquivalence -v
   944|    │
   945|    └── [第三层：文档规范保障]
   946|        │
   947|        ├── Step 4.5 规范：全量/增量必须使用同一核心函数
   948|        ├── PROJECT.md 规范：修改核心函数时必须检查等价性
   949|        ├── docstring 要求：calculate_ic_with_direction_verification 必须说明内部调用关系
   950|        └── 注释要求：ic_rsi_1d.py 增量计算必须说明"使用核心函数"
   951|```
   952|
   953|**验证等价性的方法：**
   954|
   955|```bash
   956|# 运行等价性单元测试
   957|pytest factor_ic/test_cases/ic_rsi_1d_test_cases.py::TestAlgorithmEquivalence -v
   958|
   959|# 预期结果：4 passed（含 test_full_incremental_equivalence_multi_day）
   960|
   961|# 若测试失败，说明：
   962|#   1. 全量/增量使用了不同的 IC 计算逻辑
   963|#   2. 边界处理不一致
   964|#   3. 方向处理存在反转逻辑
   965|# 需立即检查 ic_calculator.py 和 ic_rsi_1d.py 的调用路径
   966|```
   967|
   968|---
   969|
   970|### Step 4.6: 旧缓存兼容性处理规范（v1.34 新增）
   971|
   972|**遵循 PROJECT.md 旧缓存兼容性处理规范：增量计算读取现有缓存时，必须兼容旧版本缓存数据。**
   973|
   974|```
   975|旧缓存兼容性处理流程
   976|    │
   977|    ├── [问题背景]
   978|    │   │
   979|    │   ├── v1.32 之前版本：ic_values 可能包含 None（未过滤股票数不足）
   980|    │   ├── 增量更新读取现有缓存 → existing_ic_values 可能包含 None
   981|    │   ├── 合并逻辑语义不一致风险：
   982|    │   │   ├── existing 直接写入 → 旧 None 被保留
   983|    │   │   └── new 过滤 None → 新 None 被过滤
   984|    │   │   └── date_ic_map 混合"旧版本遗留 None"和"有效 IC 值"
   985|    │   │
   986|    │   └── 语义混乱：同一日期在不同版本缓存中语义不同
   987|    │
   988|    ├── [兼容性处理实现]
   989|    │   │
   990|    │   ├── _incremental_update() 第391-396行
   991|    │   │   │
   992|    │   │   ├── date_ic_map = {}
   993|    │   │   │
   994|    │   │   ├── for date, ic in zip(existing_dates, existing_ic_values):
   995|    │   │   │       if ic is not None:  # 兼容旧缓存：过滤可能存在的 None
   996|    │   │   │           date_ic_map[date] = ic  # 只有有效 IC 值
   997|    │   │   │
   998|    │   │   ├── for date, ic in zip(new_dates, new_ic_values):
   999|    │   │   │       if ic is not None:  # 只写入有效 IC 值
  1000|    │   │   │           date_ic_map[date] = ic
  1001|  1001|    │   │   │
  1002|    │   │   └── 结果：existing 和 new 都过滤 None（语义一致）
  1003|    │   │
  1004|    │   └── 自动清理旧版本遗留 None
  1005|    │       │
  1006|    │       ├── 旧缓存 ic_values = [0.1, None, 0.3, None, 0.5]
  1007|    │       ├── 合并时过滤 None → date_ic_map = [0.1, 0.3, 0.5]
  1008|    │       ├── 新计算值写入 → 合并后不含 None
  1009|    │       ├── 输出缓存 → ic_values = [0.1, 0.3, 0.5, ...]
  1010|    │       │
  1011|    │       └── 旧版本遗留 None 被自动清理，无需手动干预
  1012|    │
  1013|    ├── [版本兼容性说明]
  1014|    │   │
  1015|    │   ├── v1.32 之前：ic_values 可能含 None → 直接写入 date_ic_map
  1016|    │   ├── v1.32 及之后：ic_values 只含有效值 → 过滤 None 后写入
  1017|    │   ├── v1.34 及之后（当前）：existing 和 new 都过滤 None
  1018|    │   │
  1019|    │   └── 升级路径：
  1020|    │       1. v1.32 → v1.34：旧缓存自动清理
  1021|    │       2. 无需手动干预，增量更新时自动处理
  1022|    │
  1023|    └── [防御性验证]
  1024|        │
  1025|        ├── 第420-433行：验证 rolling_ic_mean_raw 与 valid_ic 长度一致
  1026|        │   │
  1027|        │   ├── if len(rolling_ic_mean_raw) != len(valid_ic):
  1028|        │   │       raise RuntimeError(...)
  1029|        │   │
  1030|        │   ├── 错误信息包含旧缓存兼容性诊断提示：
  1031|        │   │   1. calculate_ic_statistics 内部过滤（不应发生）
  1032|        │   │   2. ic_series 输入包含 NaN（调用方应过滤）
  1033|        │   │   3. 旧缓存兼容性问题（v1.32 之前 ic_values 可能含 None）
  1034|        │   │
  1035|        │   └── 诊断建议：检查 ic_series 是否含 NaN
  1036|        │
  1037|        └── 注意：calculate_ic_statistics 不会过滤 ic_series
  1038|            - 输入长度 = 输出长度（docstring 第746行明确声明）
  1039|            - 若触发异常 → 说明有其他问题（非 calculate_ic_statistics 内部过滤）
  1040|```
  1041|
  1042|**为何需要兼容性处理：**
  1043|
  1044|```
  1045|问题：合并逻辑语义不一致（旧版本遗留问题）
  1046|1. v1.32 规范：ic_values 不存储 None
  1047|2. 但 v1.32 之前版本可能写入 None
  1048|3. 增量更新读取旧缓存 → existing_ic_values 可能含 None
  1049|4. 若不处理：
  1050|   - 旧 None 被保留 → date_ic_map[date] = None
  1051|   - 新 None 被过滤 → 语义不一致
  1052|   - 同一日期在不同版本缓存中语义不同
  1053|
  1054|修复：
  1055|1. existing 和 new 都过滤 None
  1056|2. 旧版本遗留 None 被自动清理
  1057|3. 合并后 date_ic_map 只含有效 IC 值
  1058|
  1059|结果：
  1060|1. 兼容旧版本缓存 ✓
  1061|2. 自动清理遗留 None ✓
  1062|3. 语义一致性 ✓
  1063|```
  1064|
  1065|**注意事项：**
  1066|
  1067|```
  1068|1. 增量合并时，existing 和 new 都必须过滤 None（语义一致）
  1069|2. 旧版本遗留 None 会被自动清理（无需手动干预）
  1070|3. 防御性验证错误信息必须包含旧缓存兼容性诊断提示
  1071|4. calculate_ic_statistics 不会过滤 ic_series（输入长度 = 输出长度）
  1072|```
  1073|
  1074|---
  1075|
  1076|### Step 4.7: 增量模式 period 语义规范（v1.35 新增）
  1077|
  1078|**遵循 PROJECT.md 增量模式 period 语义规范：增量模式下 period 和 total_days 必须覆盖合并后的 all_dates 范围。**
  1079|
  1080|```
  1081|增量模式 period 语义处理流程
  1082|    │
  1083|    ├── [问题背景]
  1084|    │   │
  1085|    │   ├── 现有缓存：existing_dates 可能比当前因子缓存更早（历史数据）
  1086|    │   ├── raw_metadata['period_start'] = 当前因子缓存最小日期
  1087|    │   ├── 若只使用 raw_metadata：
  1088|    │   │   ├── period.start = 当前因子缓存最小日期
  1089|    │   │   ├── all_dates[0] = 历史缓存最小日期（可能更早）
  1090|    │   │   └── period.start > all_dates[0] → 语义矛盾
  1091|    │   │
  1092|    │   └── 注释语义："period 表示原始数据覆盖范围"与实际值矛盾
  1093|    │
  1094|    ├── [正确实现]
  1095|    │   │
  1096|    │   ├── _incremental_update() 第451-462行
  1097|    │   │   │
  1098|    │   │   ├── all_dates = sorted(date_ic_map.keys())
  1099|    │   │   │
  1100|    │   │   ├── 'period': {
  1101|    │   │   │       'start': min(all_dates[0], raw_metadata['period_start']),
  1102|    │   │   │       'end': max(all_dates[-1], raw_metadata['period_end'])
  1103|    │   │   │   }
  1104|    │   │   │
  1105|    │   │   ├── 'sample_stats': {
  1106|    │   │   │       'total_days': len(all_dates),
  1107|    │   │   │       'valid_days': len(valid_ic)
  1108|    │   │   │   }
  1109|    │   │   │
  1110|    │   │   └── 结果：period 覆盖合并后数据范围
  1111|    │   │
  1112|    │   └── 全量 vs 增量语义对比
  1113|    │       │
  1114|    │       ├── 全量：
  1115|    │       │   - period.start = raw_metadata['period_start']
  1116|    │       │   - period.end = raw_metadata['period_end']
  1117|    │       │   - total_days = raw_metadata['total_days']
  1118|    │       │   - period 覆盖当前因子缓存范围
  1119|    │       │
  1120|    │       └── 增量：
  1121|    │       │   - period.start = min(all_dates[0], raw_metadata['period_start'])
  1122|    │       │   - period.end = max(all_dates[-1], raw_metadata['period_end'])
  1123|    │       │   - total_days = len(all_dates)
  1124|    │       │   - period 覆盖合并后数据范围（包含历史缓存）
  1125|    │
  1126|    ├── [增量模式示例]
  1127|    │   │
  1128|    │   ├── 场景：
  1129|    │   │   - existing_dates = [2025-01-01, ..., 2025-05-31]（历史数据）
  1130|    │   │   - raw_metadata['period_start'] = 2025-06-01
  1131|    │   │   - all_dates = [2025-01-01, ..., 2025-06-30]
  1132|    │   │
  1133|    │   ├── 修复前（语义矛盾）：
  1134|    │   │   - period.start = 2025-06-01（当前因子缓存）
  1135|    │   │   - all_dates[0] = 2025-01-01（历史缓存）
  1136|    │   │   - period.start > all_dates[0] → 错误
  1137|    │   │
  1138|    │   └── 修复后（语义一致）：
  1139|    │       - period.start = min(2025-01-01, 2025-06-01) = 2025-01-01
  1140|    │       - period.end = max(2025-06-30, 2025-06-30) = 2025-06-30
  1141|    │       - total_days = len(all_dates) = 180天
  1142|    │       - period 覆盖合并后数据范围 ✓
  1143|    │
  1144|    └── [为何必须覆盖合并范围]
  1145|        │
  1146|        ├── period 应表示"最终输出数据的覆盖范围"
  1147|        │   - 非仅"当前因子缓存范围"
  1148|        │   - 增量合并后，输出数据包含历史缓存
  1149|        │   - period 必须覆盖完整输出范围
  1150|        │
  1151|        ├── total_days 应表示"最终输出数据的日期数"
  1152|        │   - 非仅"当前因子缓存日期数"
  1153|        │   - 必须与 len(all_dates) 一致
  1154|        │   - 与 period 覆盖范围对应
  1155|        │
  1156|        └── 语义一致性：
  1157|            - period.start ≤ all_dates[0]
  1158|            - period.end ≥ all_dates[-1]
  1159|            - total_days = len(all_dates)
  1160|```
  1161|
  1162|**为何必须覆盖合并范围：**
  1163|
  1164|```
  1165|问题：增量模式 period 语义矛盾（v1.34 之前版本）
  1166|1. 现有缓存可能比当前因子缓存更早
  1167|2. 若只使用 raw_metadata：
  1168|   - period.start = 当前因子缓存最小日期
  1169|   - all_dates[0] = 历史缓存最小日期（可能更早）
  1170|3. period.start > all_dates[0] → 语义矛盾
  1171|4. 注释说"period 表示原始数据覆盖范围"，但实际不覆盖历史数据
  1172|
  1173|修复：
  1174|1. period.start = min(all_dates[0], raw_metadata['period_start'])
  1175|2. period.end = max(all_dates[-1], raw_metadata['period_end'])
  1176|3. total_days = len(all_dates)
  1177|
  1178|结果：
  1179|1. period 覆盖合并后数据范围 ✓
  1180|2. total_days = len(all_dates) ✓
  1181|3. 语义一致性 ✓
  1182|```
  1183|
  1184|**注意事项：**
  1185|
  1186|```
  1187|1. 增量模式：period 覆盖合并后 all_dates 范围（包含历史缓存）
  1188|2. 全量模式：period 覆盖当前因子缓存范围
  1189|3. total_days 全量：raw_metadata['total_days']
  1190|4. total_days 增量：len(all_dates)
  1191|5. period 与 total_days 必须语义对应
  1192|```
  1193|
  1194|---
  1195|
  1196|### Step 5: 五维度判断结果
  1197|
  1198|**实测结果（2026-05-12 18:30:00 北京时间）:**
  1199|
  1200|```
  1201|RSI(6) IC 分析结果:
  1202|┌────────────────────────────────────────────────────────────┐
  1203|│  IC 均值: -0.0372                                          │
  1204|│  ICIR: 0.25                                                │
  1205|│  p 值: < 1e-06                                             │
  1206|│  t 统计量: -6.02                                            │
  1207|│  总天数: 515                                               │
  1208|│                                                            │
  1209|│  [五维度判断（独立输出）]                                    │
  1210|│  1. 统计显著性: p<1e-06 → 统计显著                          │
  1211|│  2. 方向判断: ic_mean=-0.0372 → 方向为负                    │
  1212|│  3. 经济显著性: |ic_mean|=0.0372≥0.03 → 经济显著弱          │
  1213|│  4. ICIR稳定性: ICIR=0.25<0.5 → 稳定性不足                  │
  1214|│  5. IC分布一致性: 正比例=38.1%与负方向一致 → IC分布正常      │
  1215|│                                                            │
  1216|│  五个维度独立输出，不合并为单一结论                           │
  1217|└────────────────────────────────────────────────────────────┘
  1218|```
  1219|
  1220|**五维度判断说明（PROJECT.md 规范）:**
  1221|
  1222|| 维度 | 判断标准 | 本次结果 |
  1223||-----|---------|---------|
  1224|| 统计显著性 | p_value < 0.05 | p<1e-06 → 统计显著 |
  1225|| 方向判断 | ic_mean 的符号 | negative（反向因子） |
  1226|| 经济显著性 | |ic_mean| ≥ 0.03（弱）或 ≥ 0.05（强） | weak（0.0372≥0.03） |
  1227|| ICIR稳定性 | ICIR ≥ 0.5（可用）或 ≥ 1.0（较好） | none（0.25<0.5） |
  1228|| IC分布一致性 | positive_ratio 与 ic_mean_sign 匹配 | consistent（38.1%<50%对应负方向） |
  1229|
  1230|**注意**: 五个维度独立输出，不合并为 factor_direction: valid/invalid
  1231|
  1232|---
  1233|
  1234|### Step 6: 输出结果
  1235|
  1236|输出结果符合 PROJECT.md 规范的数据结构（五维度判断）：
  1237|
  1238|**实测数据（2026-05-12 20:55 北京时间）:**
  1239|
  1240|```json
  1241|{
  1242|    "factor_name": "rsi_1d",
  1243|    "calculation_date": "2026-05-12",
  1244|    "period": {
  1245|        "start": "2024-03-21",
  1246|        "end": "2026-05-11"
  1247|    },
  1248|    "ic_metrics": {
  1249|        "ic_mean": -0.037205,
  1250|        "ic_std": 0.149815,
  1251|        "icir": 0.2483
  1252|    },
  1253|    "sample_stats": {
  1254|        "total_days": 515,
  1255|        "valid_days": 514,
  1256|        "avg_stocks_per_day": 2719
  1257|    },
  1258|    
  1259|    "statistical_significance": {
  1260|        "p_value": 1.78e-09,
  1261|        "p_value_display": "< 1e-06",
  1262|        "t_stat": -6.0168,
  1263|        "nw_lag": 5,
  1264|        "nw_lag_method": "Newey-West (1994): lag = int(4*(T/100)^(2/9))",
  1265|        "is_significant": true,
  1266|        "conclusion": "统计显著（p=< 1e-06<0.05）"
  1267|    },
  1268|    "factor_direction": {
  1269|        "ic_mean": -0.037205,
  1270|        "ic_mean_sign": "negative",
  1271|        "direction_usage": "反向因子：分层回测时做多低值组、做空高值组",
  1272|        "conclusion": "因子方向为反向（ic_mean=-0.0372<0），分层回测做多低值组"
  1273|    },
  1274|    "economic_significance": {
  1275|        "abs_ic_mean": 0.037205,
  1276|        "threshold_used": {"weak": 0.03, "strong": 0.05},
  1277|        "level": "weak",
  1278|        "is_economically_significant": true,
  1279|        "conclusion": "经济显著弱（|ic_mean|=0.0372>=0.03）"
  1280|    },
  1281|    "icir_stability": {
  1282|        "icir": 0.2483,
  1283|        "threshold_used": {"usable": 0.5, "good": 1.0, "excellent": 2.0},
  1284|        "level": "none",
  1285|        "is_stable": false,
  1286|        "conclusion": "IC稳定性不足（ICIR=0.25<0.5)"
  1287|    },
  1288|    "ic_distribution_consistency": {
  1289|        "positive_ratio": 0.3813,
  1290|        "ic_mean_sign": "negative",
  1291|        "is_consistent": true,
  1292|        "consistency_type": "consistent",
  1293|        "distribution_hint": "IC分布偏向负值（61.9%天数IC<0）",
  1294|        "conclusion": "一致：正比例<50%对应负方向，IC分布正常"
  1295|    },
  1296|    
  1297|    "dates": ["2024-03-21", "2024-03-22", ...],
  1298|    "ic_values": [-0.052, -0.023, -0.041, ...],
  1299|    "rolling_ic_mean": [null, null, null, null, null, null, null, null, null, -0.042, -0.041, ...],
  1300|    "positive_ratio": 0.3813,
  1301|    "n_assets": 2997,
  1302|    "summary": "IC均值=-0.0372, ICIR=0.25, p值=< 1e-06, 方向=negative, 统计显著=True, 经济显著=weak, ICIR稳定=none, 正比例=38.1%（IC>0天数占比）"
  1303|}
  1304|```
  1305|
  1306|**规范字段说明**：
  1307|
  1308|| 字段 | 类型 | 含义 |
  1309||------|------|------|
  1310|| `factor_name` | string | 因子标识，格式 `<因子名>_<周期>` |
  1311|| `calculation_date` | string | 计算日期 (YYYY-MM-DD) |
  1312|| `period.start` | string | 数据覆盖起始日期（因子缓存最小日期，可能 ≠ dates[0]） |
  1313|| `period.end` | string | 数据覆盖结束日期（因子缓存最大日期，可能 ≠ dates[-1]） |
  1314|| `ic_metrics.ic_mean` | float | IC均值 |
  1315|| `ic_metrics.ic_std` | float | IC标准差 |
  1316|| `ic_metrics.icir` | float | ICIR = |IC均值|/IC标准差（绝对值） |
  1317|| `sample_stats.total_days` | int | 因子缓存覆盖的日期数 |
  1318|| `sample_stats.valid_days` | int | 有效 IC 天数 |
  1319|| `sample_stats.avg_stocks_per_day` | int | 日均股票数 |
  1320|| `statistical_significance` | dict | 统计显著性判断（独立输出） |
  1321|| `factor_direction` | dict | 方向判断（独立输出，ic_mean符号） |
  1322|| `economic_significance` | dict | 经济显著性判断（独立输出） |
  1323|| `icir_stability` | dict | ICIR稳定性判断（独立输出） |
  1324|| `ic_distribution_consistency` | dict | IC分布一致性判断（独立输出） |
  1325|
  1326|**period 与 dates 的边界说明（重要）**：
  1327|
  1328|```
  1329|period 表示数据覆盖范围，dates 表示有效 IC 日期列表：
  1330|- period.start ≠ dates[0] → 首日因子数据无有效 IC（股票数不足等）
  1331|- period.end ≠ dates[-1] → 末日因子数据无有效 IC（股票数不足等）
  1332|- period 与 sample_stats.total_days 对应，dates 与 sample_stats.valid_days 对应
  1333|```
  1334|
  1335|**额外字段**（保留原有功能）：
  1336|
  1337|| 字段 | 类型 | 含义 |
  1338||------|------|------|
  1339|| `dates` | array | 计算日期列表 |
  1340|| `ic_values` | array | 每日 IC 值 |
  1341|| `rolling_ic_mean` | array | 20日滚动 IC 均值（window=20, min_periods=10，前9个为null）详见 PROJECT.md |
  1342|| `positive_ratio` | float | IC > 0 的天数比例 |
  1343|
  1344|---
  1345|
  1346|## 📊 关键指标含义
  1347|
  1348|| 指标 | 含义 | 判断标准 |
  1349||------|------|----------|
  1350|| **IC均值** | 因子预测能力 | 正向因子：> 0.05 有效；反向因子：< -0.05 有效 |
  1351|| **ICIR** | IC稳定性（|ic_mean|/ic_std） | > 0.5 = 可用；> 1.0 = 较好；> 2.0 = 很好（绝对值，无需区分方向） |
  1352|| **正比例** | IC分布特征 | 正向因子：> 50% 分布正常；反向因子：< 50% 分布正常 |
  1353|| **t统计量** | IC是否显著不为零（用于输出，不用于判断） | |t| > 1.96 = 95%显著（与 p < 0.05 等价） |
  1354|
  1355|---
  1356|
  1357|## 🔧 数据依赖
  1358|
  1359|```
  1360|data_fetchers/result/
  1361|    ├── factor_data.json.gz    ← RSI(6) 等因子值（预先计算）
  1362|    └── return_data.json.gz    ← forward_return_1d 未来收益（预先计算）
  1363|
  1364|这些缓存由上游预计算脚本生成，IC 计算器只读取，不生产。
  1365|```
  1366|
  1367|---
  1368|
  1369|## 📁 文件位置
  1370|
  1371|| 文件 | 路径 | 说明 |
  1372||------|------|------|
  1373|| IC计算脚本 | `factor_ic/ic_rsi_1d.py` | 主脚本 |
  1374|| 公共模块 | `factor_ic/common/ic_calculator.py` | 通用 IC 计算（方向验证）|
  1375|| 公共模块 | `factor_ic/common/data_completeness.py` | 数据完整性检查 |
  1376|| 公共模块 | `factor_ic/common/convert_types.py` | numpy 类型转换为原生 Python 类型 |
  1377|| 输出结果 | `factor_ic/result/ic_rsi_1d_analysis_result.json` | IC计算结果（规范命名） |
  1378|| 流程文档 | `factor_ic/docs/ic_rsi_1d_flow.md` | 本文档（规范命名） |
  1379|| 测试用例 | `factor_ic/test_cases/ic_rsi_1d_test_cases.py` | pytest测试文件 |
  1380|
  1381|---
  1382|
  1383|## 🔄 与其他因子的对比
  1384|
  1385|| 因子 | IC计算方式 | 方向验证结果 | 说明 |
  1386||------|------------|-------------|------|
  1387|| RSI | ic_calculator | negative | 方向由实测IC确定（ic_mean<0） |
  1388|| KDJ_J | ic_calculator | negative | 方向由实测IC确定（ic_mean<0） |
  1389|| Volume_Ratio | ic_calculator | positive | 方向由实测IC确定（ic_mean>0） |
  1390|| Turnover_Surge | ic_calculator | positive | 方向由实测IC确定（ic_mean>0） |
  1391|| Bollinger_PB | ic_calculator | negative | 方向由实测IC确定（ic_mean<0） |
  1392|| Main_Inflow_Ratio | ic_calculator | positive | 方向由实测IC确定（ic_mean>0） |
  1393|
  1394|**注意**: 所有因子均需通过方向验证流程确认方向，不可预设。
  1395|
  1396|---
  1397|
  1398|## 📝 错误信息格式规范（v1.44 新增）
  1399|
  1400|**遵循 PROJECT.md 错误信息格式规范：枚举类错误必须包含合法值列表，帮助用户理解正确用法。**
  1401|
  1402|### 规范要点
  1403|
  1404|| 规范项 | 要求 | 说明 |
  1405||-------|------|------|
  1406|| 枚举类错误 | 必须包含合法值列表 | 如 `mode` 取值错误，错误信息必须列出 `['skip', 'incremental', 'full']` |
  1407|| 参数缺失错误 | 必须包含可用选项列表 | 如 `factor_col` 不存在，错误信息必须列出 `可用列: [...]` |
  1408|| 错误信息格式 | 多行结构，每行一个信息点 | 便于用户快速定位问题 |
  1409|
  1410|### 正确示例
  1411|
  1412|```python
  1413|# KeyError：因子列不存在（ic_rsi_1d.py 第120-125行）
  1414|if factor_col not in factor_df.columns:
  1415|    available_cols = sorted(factor_df.columns.tolist())
  1416|    raise KeyError(
  1417|        f"因子列 '{factor_col}' 不存在于缓存数据中\n"
  1418|        f"可用列: {available_cols}"
  1419|    )
  1420|
  1421|# RuntimeError：未知计算模式（ic_rsi_1d.py 第728-734行）
  1422|else:
  1423|    raise RuntimeError(
  1424|        f"未知的计算模式: {mode}\n"
  1425|        f"合法值: ['skip', 'incremental', 'full']\n"
  1426|        f"请检查 check_data_completeness() 返回值是否正确"
  1427|    )
  1428|```
  1429|
  1430|### 错误示例（不推荐）
  1431|
  1432|```python
  1433|# 错误信息不包含合法值列表
  1434|raise RuntimeError(f"未知的计算模式: {mode}")
  1435|# 用户看到这个错误不知道合法值是什么，需要查阅源码或文档
  1436|
  1437|# 错误信息不包含可用选项
  1438|raise KeyError(f"因子列 '{factor_col}' 不存在")
  1439|# 用户不知道有哪些可用列，需要手动检查 DataFrame.columns
  1440|```
  1441|
  1442|### 规范来源
  1443|
  1444|此规范源于代码中的正确实践（KeyError 处理），但之前未形成明确条文，导致部分代码（如未知模式处理）遗漏了这一最佳实践。v1.44 将其正式写入流程文档，确保所有错误处理遵循统一格式。
  1445|
  1446|---
  1447|
  1448|## 🔬 convert_to_native_types 行为验证规范（v1.45 新增）
  1449|
  1450|**遵循 PROJECT.md NaN 处理规范：convert_to_native_types 是兜底保障，必须有单元测试验证其行为。**
  1451|
  1452|### 规范要点
  1453|
  1454|| 规范项 | 要求 | 说明 |
  1455||-------|------|------|
  1456|| NaN → None | 必须验证 numpy.float64(NaN) → None | 数据生成阶段的兜底保障 |
  1457|| None → null | 必须验证 JSON 序列化 None → null | 标准 JSON 不支持 NaN，必须转为 null |
  1458|| 行为一致性 | 必须有单元测试 | 确保 numpy NaN 和 Python float NaN 行为一致 |
  1459|
  1460|### 转换行为验证
  1461|
  1462|```
  1463|convert_to_native_types 转换路径：
  1464|    │
  1465|    ├── numpy.float64(NaN) → None
  1466|    │       └── json.dumps(None) → "null"
  1467|    │       └── JSON 标准：null 是合法值
  1468|    │
  1469|    ├── Python float(NaN) → None
  1470|    │       └── json.dumps(None) → "null"
  1471|    │       └── 与 numpy NaN 行为一致
  1472|    │
  1473|    └── numpy.int64 → int
  1474|    └── numpy.float64 → float
  1475|    └── numpy.ndarray → list
  1476|    └── pandas.Series → list
  1477|    └── pandas.Timestamp → str
  1478|```
  1479|
  1480|### 单元测试文件
  1481|
  1482|**位置**: `factor_ic/test_cases/test_convert_types.py`
  1483|
  1484|**测试覆盖**:
  1485|
  1486|| 测试类别 | 测试项 | 验证内容 |
  1487||---------|--------|---------|
  1488|| 基本类型转换 | numpy int/float/array | 转换为 Python 原生类型 |
  1489|| NaN 处理 | numpy NaN / Python NaN | 转换为 None |
  1490|| JSON 序列化 | 含 None 的数据 | None → null，JSON 输出不含 NaN |
  1491|| 嵌套结构 | dict/list 中的 NaN | 递归转换，确保 JSON 格式一致 |
  1492|| 边界情况 | None/空字典/空列表 | 正确处理 |
  1493|
  1494|### 测试执行
  1495|
  1496|```bash
  1497|cd /home/admin/projects/factor_ic_analyzer
  1498|python -m pytest factor_ic/test_cases/test_convert_types.py -v
  1499|```
  1500|
  1501|  1501|**期望结果**: 24 passed
  1502|
  1503|### 为何必须验证（设计动机）
  1504|
  1505|```
  1506|问题背景：
  1507|1. json.dump(convert_to_native_types(ic_data), f) 是全量和增量的共同出口
  1508|2. 若 convert_to_native_types 将 NaN 转为 "NaN" 字符串而非 null
  1509|   → 下游读取 JSON 时解析失败（JSON 标准：null 是合法值，NaN 不是）
  1510|3. 若 convert_to_native_types 报错而非静默转换
  1511|   → IC 计算在保存阶段崩溃，用户数据丢失
  1512|4. 代码中未验证其行为，用户无法确认输出 JSON 格式是否一致
  1513|
  1514|解决方案：
  1515|1. 必须有单元测试验证 convert_to_native_types 对 NaN 的处理行为
  1516|2. 测试覆盖 numpy NaN 和 Python float NaN（确保行为一致）
  1517|3. 测试验证 JSON 序列化结果（None → null，而非 NaN 或报错）
  1518|4. CI/CD 中运行测试，确保行为始终一致
  1519|
  1520|设计原则（遵循 PROJECT.md 规范）：
  1521|- NaN → None 转换应在数据生成阶段完成（主动处理）
  1522|- convert_to_native_types 作为兜底保障（防御性措施）
  1523|- 但必须验证兜底保障的行为，否则无法保证输出一致性
  1524|```
  1525|
  1526|### PROJECT.md 规范引用
  1527|
  1528|```
  1529|# PROJECT.md 第 1087-1090 行
  1530|convert_to_native_types 仍然会处理 NaN（防御性措施），但：
  1531|- 数据生成阶段应主动处理 NaN（语义明确）
  1532|- convert_to_native_types 仅作为兜底保障（防止遗漏）
  1533|- 必须有单元测试验证其行为（确保兜底有效）
  1534|```
  1535|
  1536|---
  1537|
  1538|## 📋 函数签名变更同步规范（v1.46 新增）
  1539|
  1540|**遵循 PROJECT.md 函数签名变更规范：返回值变更时必须同步更新类型注解和 docstring。**
  1541|
  1542|### 规范要点
  1543|
  1544|| 规范项 | 要求 | 说明 |
  1545||-------|------|------|
  1546|| 类型注解 | 返回值变更时必须同步更新 | 如 `Tuple[...]` 返回值从 2 个变成 3 个，类型注解必须同步 |
  1547|| docstring | 返回值描述必须同步更新 | docstring 的 Returns 部分必须与实际返回值一致 |
  1548|| 调用方检查 | 必须确认所有调用方已同步修改 | 避免调用方接收参数数量不匹配导致运行时错误 |
  1549|
  1550|### 正确示例
  1551|
  1552|```python
  1553|# 函数定义：返回值从 2 个变成 3 个
  1554|def load_data_from_cache(
  1555|    factor_col: str = 'rsi_6',
  1556|    return_col: str = 'forward_return_1d'
  1557|) -> Tuple[pd.DataFrame, pd.DataFrame, dict]:  # 类型注解同步更新
  1558|    """
  1559|    从缓存加载因子数据和收益数据
  1560|    
  1561|    返回:
  1562|        (factor_df, return_df, raw_metadata)  # docstring 同步更新
  1563|        - factor_df: 过滤后的因子数据 DataFrame
  1564|        - return_df: 过滤后的收益数据 DataFrame
  1565|        - raw_metadata: 原始数据元信息字典  # 新增返回值描述
  1566|            - period_start: 原始缓存最小日期
  1567|            - period_end: 原始缓存最大日期
  1568|            - total_days: 原始缓存日期数
  1569|    """
  1570|    ...
  1571|    return factor_df, return_df, raw_metadata  # 实际返回 3 个值
  1572|
  1573|# 调用方：同步接收 3 个返回值
  1574|factor_df, return_df, raw_metadata = load_data_from_cache()
  1575|```
  1576|
  1577|### 错误示例（不推荐）
  1578|
  1579|```python
  1580|# 类型注解未同步更新（错误）
  1581|def load_data_from_cache(...) -> Tuple[pd.DataFrame, pd.DataFrame]:  # 只有 2 个
  1582|    """返回: (factor_df, return_df)"""  # docstring 只有 2 个
  1583|    ...
  1584|    return factor_df, return_df, raw_metadata  # 实际返回 3 个
  1585|
  1586|# 调用方：类型注解误导，可能只接收 2 个
  1587|factor_df, return_df = load_data_from_cache()  # 运行时 ValueError: too many values to unpack
  1588|```
  1589|
  1590|### 变更检查清单
  1591|
  1592|当函数返回值变更时，必须检查以下内容：
  1593|
  1594|| 检查项 | 检查方法 | 说明 |
  1595||-------|---------|------|
  1596|| 类型注解 | 读取函数定义签名 | `-> Tuple[...]` 是否与实际返回值数量一致 |
  1597|| docstring | 读取函数 docstring | Returns 部分是否与实际返回值数量一致 |
  1598|| 调用方 | grep 搜索调用位置 | 所有调用方是否已同步接收新的返回值数量 |
  1599|| 流程文档 | 更新相关流程文档 | 返回值变更说明必须写入更新日志 |
  1600|
  1601|### 为何必须同步（设计动机）
  1602|
  1603|```
  1604|问题背景：
  1605|1. 函数返回值从 2 个变成 3 个（如 v1.28 新增 raw_metadata）
  1606|2. 类型注解未同步更新，仍标注为 Tuple[..., ...]（只有 2 个）
  1607|3. docstring 未同步更新，返回值描述只有 2 个
  1608|4. 调用方可能只接收 2 个值，导致运行时错误：
  1609|   ValueError: too many values to unpack (expected 2)
  1610|5. IDE 和静态类型检查器无法发现此问题（类型注解错误）
  1611|
  1612|解决方案：
  1613|1. 返回值变更时必须同步更新类型注解
  1614|2. 返回值变更时必须同步更新 docstring
  1615|3. 必须检查所有调用方是否已同步修改
  1616|4. 必须在流程文档中记录变更说明
  1617|```
  1618|
  1619|### 相关案例
  1620|
  1621|**案例**: `load_data_from_cache` 返回值变更（v1.28）
  1622|
  1623|- **变更**: 返回值从 `(factor_df, return_df)` 变为 `(factor_df, return_df, raw_metadata)`
  1624|- **原因**: 新增 raw_metadata 用于记录原始数据范围（dropna 前）
  1625|- **修复**: v1.46 同步更新类型注解和 docstring
  1626|
  1627|---
  1628|
  1629|*最后更新: 2026-05-20 00:15 (北京时间)*