     1|# factor_ic/common 公共模块
     2|
     3|> 版本: v1.0
     4|> 创建时间: 2026-05-22
     5|> 最后更新: 2026-05-22
     6|
     7|## 设计目标
     8|
     9|**核心问题：** 5个因子IC脚本存在大量重复代码（45%-70%），新增因子开发成本高。
    10|
    11|**解决方案：** 抽取公共模块，新增因子只需实现因子计算逻辑。
    12|
    13|| 模块 | 功能 | 每脚本减少行数 |
    14||------|------|----------------|
    15|| `data_loader.py` | 数据加载（gzip解压、日期转换、列验证） | ~80-120行 |
    16|| `ic_result_builder.py` | IC结果构建（统一输出结构） | ~60-100行 |
    17|| `incremental_engine.py` | 增量更新引擎 | ~150-200行 |
    18|| `factor_ic_runner.py` | 主入口模板 | ~100-150行 |
    19|
    20|**预期效果：** 新增因子脚本从 ~700-1100行 降至 ~50-200行。
    21|
    22|---
    23|
    24|## convert_types.py — 类型转换模块
    25|
    26|**文件路径：** `factor_ic/common/convert_types.py`
    27|
    28|### 核心函数
    29|
    30|```python
    31|def convert_to_native_types(obj: Any) -> Any:
    32|    """
    33|    递归转换 numpy/pandas 类型为 Python 原生类型
    34|    
    35|    解决 JSON 序列化时 numpy 类型无法直接序列化的问题。
    36|    """
    37|```
    38|
    39|### 类型检查规范（2026-05-22）
    40|
    41|| 类型 | 检查方式 | 说明 |
    42||------|---------|------|
    43|| numpy整数 | `isinstance(obj, np.integer)` | 抽象基类覆盖所有子类 |
    44|| numpy浮点 | `isinstance(obj, np.floating)` | 抽象基类覆盖所有子类 |
    45|| numpy布尔 | `isinstance(obj, np.bool_)` | **必须显式分开**，不能与 bool 合并 |
    46|| Python布尔 | `isinstance(obj, bool)` | **必须在 integer 之前**，因为 bool 是 int 子类 |
    47|| Python整数 | 直接返回 | 不需要类型检查（原生类型） |
    48|| Python浮点 | `isinstance(obj, float)` | 用 `math.isnan` 检查 NaN（标准库） |
    49|
    50|### NaN 检查规范（重要）
    51|
    52|**必须使用类型匹配的 isnan 函数：**
    53|
    54|| 浮点类型 | 正确写法 | 错误写法 |
    55||---------|---------|---------|
    56|| numpy浮点 | `np.isnan(obj)` | `math.isnan(obj)` |
    57|| Python float | `math.isnan(obj)` | `np.isnan(obj)` |
    58|
    59|**错误写法示例：**
    60|```python
    61|# 错误写法（语义不准确）
    62|elif isinstance(obj, float):
    63|    if np.isnan(obj):  # numpy 函数处理 Python 类型
    64|        return None
    65|
    66|# 正确写法（类型匹配）
    67|elif isinstance(obj, float):
    68|    if math.isnan(obj):  # 标准库处理 Python 类型
    69|        return None
    70|```
    71|
    72|**原因：**
    73|1. `np.isnan` 是为 numpy 类型设计的，处理 Python float 是额外支持
    74|2. `math.isnan` 是标准库函数，专为 Python float 设计，语义更准确
    75|3. 类型匹配更轻量、语义清晰，减少不必要的依赖
    76|
    77|**参考：** convert_types.py 源码注释（2026-05-22 更新）
    78|
    79|### isinstance 多类型检查规范（重要）
    80|
    81|**禁止合并写法：**
    82|```python
    83|# 错误写法（脆弱，依赖分支顺序）
    84|elif isinstance(obj, (np.bool_, bool)):
    85|    return bool(obj)
    86|
    87|# 正确写法（显式分开处理）
    88|elif isinstance(obj, np.bool_):
    89|    return bool(obj)
    90|elif isinstance(obj, bool):
    91|    return obj
    92|```
    93|
    94|**原因：**
    95|1. bool 是 int 的子类，`isinstance(True, int)` 返回 True
    96|2. 若有人在未来添加 `isinstance(obj, int)` 分支在 bool 检查之前，合并写法会将 True/False 误判为整数
    97|3. 显式分开处理：意图清晰，防止分支顺序变化导致的隐蔽 bug
    98|
    99|### 单例检查规范（重要）
   100|
   101|**必须用 `is` 判断单例对象：**
   102|
   103|| 单例对象 | 正确写法 | 错误写法 |
   104||---------|---------|---------|
   105|| pd.NaT | `obj is pd.NaT` | `isinstance(obj, type(pd.NaT))` |
   106|| pd.NA | `obj is pd.NA` | `isinstance(obj, type(pd.NA))` |
   107|| None | `obj is None` | `isinstance(obj, type(None))` |
   108|
   109|**错误写法示例：**
   110|```python
   111|# 错误写法（冗余 + 依赖私有类）
   112|elif obj is pd.NA or isinstance(obj, type(pd.NA)):
   113|    return None
   114|
   115|# 正确写法（单例用 is 即可）
   116|elif obj is pd.NA:
   117|    return None
   118|```
   119|
   120|**原因：**
   121|1. 单例对象（如 pd.NA、pd.NaT、None）全局唯一，`is` 检查完全覆盖
   122|2. `isinstance(obj, type(singleton))` 依赖私有内部类（如 `pandas.core.arrays.masked.NAType`），跨版本不稳定
   123|3. isinstance 检查单例是冗余的，增加不必要的类型查找开销
   124|
   125|**参考：** convert_types.py 源码注释（2026-05-22 更新）
   126|
   127|### 分支依赖关系（重要）
   128|
   129|**pd.Series.tolist() 与 pd.NA 处理的依赖关系：**
   130|
   131|```
   132|pd.Series 分支 → obj is pd.NA 分支
   133|```
   134|
   135|**原因：**
   136|- 扩展类型 Series（如 `pd.Series([1, pd.NA], dtype='Int64')`）的 `.tolist()` 返回 `[1, pd.NA]`，而非 `[1, None]`
   137|- 后续递归调用 `convert_to_native_types` 会处理列表中的 pd.NA
   138|- 若误删 `obj is pd.NA` 分支，扩展类型 Series 的缺失值无法转换为 None
   139|
   140|**维护警告：**
   141|- `pd.Series` 分支依赖 `obj is pd.NA` 分支正确工作
   142|- 删除 `pd.NA` 分支前必须确认无扩展类型 Series 使用场景
   143|
   144|**参考：** convert_types.py 第98-103行注释（2026-05-22 更新）
   145|
   146|---
   147|
   148|## data_completeness.py — 数据完整性检查模块
   149|
   150|**文件路径：** `factor_ic/common/data_completeness.py`
   151|
   152|### 核心函数
   153|
   154|| 函数 | 用途 |
   155||------|------|
   156|| `check_data_completeness()` | 检查数据完整性，返回处理模式（full/incremental/skip） |
   157|| `get_factor_data_dates()` | 获取因子数据日期列表 |
   158|| `get_cache_latest_date()` | 获取缓存最新日期 |
   159|| `get_cache_info()` | 获取缓存信息摘要 |
   160|| `_extract_dates_from_cache()` | 公共函数：从缓存数据提取日期（内部使用） |
   161|
   162|### 日期提取规范（重要）
   163|
   164|**缓存日期提取必须使用公共函数 `_extract_dates_from_cache()`：**
   165|
   166|```python
   167|# 错误写法（逻辑不一致）
   168|# get_cache_latest_date() 优先顶层 dates
   169|# get_cache_info() 只读 ic_series.dates
   170|# 同一文件返回不同日期
   171|
   172|# 正确写法（统一处理）
   173|def get_cache_latest_date(factor_name: str):
   174|    dates, latest_date = _extract_dates_from_cache(result)
   175|    return latest_date
   176|
   177|def get_cache_info(factor_name: str):
   178|    dates, latest_date = _extract_dates_from_cache(data)
   179|    info['n_days'] = len(dates)
   180|    info['latest_date'] = latest_date
   181|```
   182|
   183|**公共函数逻辑（`_extract_dates_from_cache()`）：**
   184|1. 优先读取顶层 `dates` 字段（新格式）
   185|2. 兼容旧格式：`ic_series.dates`
   186|3. 格式统一：处理 `"2026-04-03 00:00:00"` → `"2026-04-03"`
   187|4. 返回 `(dates, latest_date)` 元组
   188|
   189|**原因：**
   190|- 统一日期提取逻辑，避免不同函数返回不同日期
   191|- 格式统一处理，防止 `"YYYY-MM-DD HH:MM:SS"` 格式污染下游逻辑
   192|
   193|**参考：** data_completeness.py 第80-117行（公共函数定义）
   194|
   195|### JSON 数据日期提取规范（重要）
   196|
   197|**日期格式必须在源头统一标准化为 YYYY-MM-DD：**
   198|
   199|```python
   200|# 错误写法（格式不一致）
   201|# get_factor_data_dates() 返回 "2026-04-03 00:00:00"
   202|# _extract_dates_from_cache() 返回 "2026-04-03"
   203|# 字符串比较 "2026-04-03 00:00:00" > "2026-04-03" 结果错误
   204|
   205|# 正确写法（源头统一标准化）
   206|def get_factor_data_dates():
   207|    dates = meta.get('dates', [])
   208|    if dates:
   209|        # 格式统一：处理 "2026-04-03 00:00:00" → "2026-04-03"
   210|        normalized_dates = [d.split()[0] if ' ' in d else d for d in dates]
   211|        dates = normalized_dates
   212|    return dates
   213|```
   214|
   215|**标准化位置：**
   216|- `get_factor_data_dates()`：因子数据源日期提取时标准化
   217|- `_extract_dates_from_cache()`：缓存数据日期提取时标准化
   218|
   219|**标准化顺序（重要）：必须先标准化，再去重排序**
   220|
   221|```python
   222|# 错误写法（顺序错误）
   223|dates = sorted(set(dates))  # 先去重排序
   224|normalized_dates = [d.split()[0] if ' ' in d else d for d in dates]  # 后标准化
   225|dates = normalized_dates  # 可能产生重复（"2026-04-03" + "2026-04-03 12:00:00" → 两个 "2026-04-03")
   226|
   227|# 正确写法（先 str() 转换，再截断，最后去重排序）
   228|dates = [str(d) for d in dates]  # 先统一转换为字符串（防止 datetime 对象）
   229|normalized_dates = [d.split()[0] if ' ' in d else d for d in dates]  # 再截断时间戳
   230|dates = sorted(set(normalized_dates))  # 最后去重排序
   231|```
   232|
   233|**完整标准化流程：**
   234|1. **str() 转换**：将 datetime/int/Timestamp 等非字符串类型转换为字符串（防止 TypeError）
   235|2. **截断时间戳**：处理 `"2026-04-03 00:00:00"` → `"2026-04-03"`（确保格式一致）
   236|3. **去重排序**：sorted + set 去除截断后的重复项
   237|
   238|**原因：**
   239|1. 若原始数据存在 `"2026-04-03"` 和 `"2026-04-03 12:00:00"` 混合格式
   240|2. 先去重排序无法去除截断后的重复项（sorted + set 在截断之前完成）
   241|3. meta.dates 可能包含 datetime 对象，`' ' in d` 检查会抛出 TypeError
   242|4. 先 str() 转换确保类型一致，再截断，最后去重排序
   243|
   244|**参考：** data_completeness.py 第71-80行（2026-05-22 更新）
   245|
   246|**原因：**
   247|1. JSON 中的日期可能包含时间戳 `"YYYY-MM-DD HH:MM:SS"` 或 datetime 对象
   248|2. 字符串比较依赖格式一致性：`"2026-04-03 00:00:00" > "2026-04-03"` 因空格导致错误结果
   249|3. 标准化必须在源头进行，而非在使用前临时处理
   250|
   251|**影响范围：**
   252|- `check_data_completeness()` 使用 `d > cache_latest` 进行日期比较
   253|- 所有日期比较逻辑依赖 YYYY-MM-DD 格式一致性
   254|
   255|**参考：** data_completeness.py 第70-78行、第106-115行（2026-05-22 更新）
   256|
   257|**从 JSON 数据中提取日期时，必须强制转换为字符串：**
   258|
   259|```python
   260|# 错误写法（类型不一致隐患）
   261|dates = sorted(set(r.get('date') for r in data.get('data', []) if r.get('date')))
   262|
   263|# 正确写法（强制 str 转换，防止 TypeError）
   264|dates = sorted(set(str(r['date']) for r in data.get('data', []) if r.get('date') is not None))
   265|```
   266|
   267|**原因：**
   268|1. JSON 中的 date 字段可能是 datetime、int、Timestamp 等非字符串类型
   269|2. `sorted()` 对混合类型会抛出 TypeError（如 `sorted(['2026-01-01', datetime(2026,1,2)])`）
   270|3. `str()` 强制转换确保类型一致性，避免运行时错误
   271|
   272|**过滤条件：**
   273|- 使用 `r.get('date') is not None` 而非 `if r.get('date')`
   274|- `if r.get('date')` 会过滤掉空字符串 `''`，但空字符串可能是有效日期（不应过滤）
   275|- `is not None` 只过滤真正的缺失值，语义更准确
   276|
   277|**参考：** data_completeness.py 第66-69行（2026-05-22 更新）
   278|
   279|---
   280|
   281|## data_loader.py — 数据加载公共模块
   282|
   283|**文件路径：** `factor_ic/common/data_loader.py`
   284|
   285|### 核心函数
   286|
   287|```python
   288|def load_factor_return_data(
   289|    factor_cols: List[str],
   290|    return_col: str = 'forward_return_1d',
   291|    factor_cache_path: Optional[Path] = None,
   292|    return_cache_path: Optional[Path] = None,
   293|    dropna_cols: Optional[List[str]] = None,
   294|    validate_date_alignment: bool = True,
   295|    additional_factor_files: Optional[Dict[str, Path]] = None
   296|) -> Tuple[pd.DataFrame, pd.DataFrame, Dict]:
   297|    """
   298|    从缓存加载因子数据和收益数据
   299|    
   300|    返回:
   301|        (factor_df, return_df, raw_metadata)
   302|        - raw_metadata: 原始数据元信息（period_start, period_end, total_days, avg_stocks_per_day）
   303|    """
   304|```
   305|
   306|### 功能列表
   307|
   308|| 功能 | 描述 | 防御性检查 |
   309||------|------|------------|
   310|| gzip解压 + JSON加载 | 从缓存读取数据 | FileNotFoundError（可恢复） |
   311|| 日期类型转换 | 统一为 YYYY-MM-DD | NaT检查 + 无效样本显示 |
   312|| 列存在验证 | 检查必需列存在 | KeyError + 显示可用列列表 |
   313|| dropna前记录metadata | 原始数据范围 | 保留原始语义 |
   314|| dropna过滤 | 去除缺失值 | 指定过滤列 |
   315|| 日期对齐验证 | 因子 vs 收益日期 | 选择交集日期（可选） |
   316|| 额外因子文件合并 | 如换手率数据 | 内连接合并 |
   317|
   318|### 使用示例
   319|
   320|```python
   321|from factor_ic.common.data_loader import load_factor_return_data
   322|
   323|# RSI因子（直接用缓存列）
   324|factor_df, return_df, raw_metadata = load_factor_return_data(
   325|    factor_cols=['rsi_6']
   326|)
   327|
   328|# KDJ因子（需要 close, high, low）
   329|factor_df, return_df, raw_metadata = load_factor_return_data(
   330|    factor_cols=['close', 'high', 'low']
   331|)
   332|
   333|# 换手率突增（需要额外文件）
   334|from factor_ic.common.data_loader import DEFAULT_CACHE_DIR
   335|factor_df, return_df, raw_metadata = load_factor_return_data(
   336|    factor_cols=['close'],
   337|    additional_factor_files={
   338|        'turnover_rate': DEFAULT_CACHE_DIR / 'turnover_rate_data.json.gz'
   339|    }
   340|)
   341|
   342|# 查看原始数据范围
   343|print(f"原始数据: {raw_metadata['period_start']} ~ {raw_metadata['period_end']}")
   344|print(f"原始天数: {raw_metadata['total_days']}")
   345|print(f"原始平均股票数: {raw_metadata['avg_stocks_per_day']}")
   346|```
   347|
   348|### 辅助函数
   349|
   350|| 函数 | 用途 |
   351||------|------|
   352|| `get_cache_dir()` | 获取缓存目录路径 |
   353|| `get_factor_cache_path()` | 获取因子缓存文件路径 |
   354|| `get_return_cache_path()` | 获取收益缓存文件路径 |
   355|
   356|### 规范要点
   357|
   358|1. `raw_metadata` 在 dropna 之前记录，保留原始数据语义
   359|2. `period_start/end` 为字符串格式 `YYYY-MM-DD`
   360|3. 日期转换后 `isin` 操作类型匹配
   361|4. 列缺失时显示可用列列表（用户友好）
   362|5. **参数污染禁止**：函数内禁止修改参数（特别是可变参数如 List[str]）
   363|
   364|### 参数污染规范（重要）
   365|
   366|**禁止修改传入的参数：**
   367|
   368|```python
   369|# 错误写法（参数污染）
   370|def load_factor_return_data(factor_cols: List[str], additional_factor_files: Dict = None):
   371|    if additional_factor_files:
   372|        # 直接修改参数，污染调用方，调用方无感知
   373|        factor_cols = list(set(factor_cols) | set(additional_factor_files.keys()))
   374|        # set 合并后丢失顺序
   375|
   376|# 正确写法（使用独立变量）
   377|def load_factor_return_data(factor_cols: List[str], additional_factor_files: Dict = None):
   378|    all_factor_cols = factor_cols  # 独立变量，不污染调用方
   379|    if additional_factor_files:
   380|        # 保持顺序：先 factor_cols，再追加不在 factor_cols 的额外列
   381|        all_factor_cols = factor_cols + [k for k in additional_factor_files.keys() if k not in factor_cols]
   382|```
   383|
   384|**原因：**
   385|1. Python 参数是引用传递，修改参数会影响调用方
   386|2. 调用方传入 `factor_cols=['close']`，函数内修改为 `['close', 'turnover_rate']`
   387|3. 调用方后续代码可能依赖原 `factor_cols`，导致逻辑错误
   388|4. `list(set(...))` 丢失顺序，语义不确定
   389|
   390|**影响范围：**
   391|- `load_factor_return_data()` 的 `factor_cols` 参数
   392|- 任何可变参数（List、Dict、Set）的函数内修改
   393|
   394|**参考：** data_loader.py 第120行（all_factor_cols 独立变量定义）
   395|
   396|### dropna_cols 默认值规范（重要）
   397|
   398|**默认值应在参数修改之前确定：**
   399|
   400|```python
   401|# 错误写法（隐式包含额外列）
   402|def load_factor_return_data(factor_cols, additional_factor_files=None):
   403|    all_factor_cols = factor_cols
   404|    if additional_factor_files:
   405|        all_factor_cols = factor_cols + list(additional_factor_files.keys())
   406|    # dropna_cols 默认值在参数修改之后确定，隐式包含额外列
   407|    dropna_cols = all_factor_cols
   408|
   409|# 正确写法（在修改之前确定）
   410|def load_factor_return_data(factor_cols, additional_factor_files=None):
   411|    # 在修改 factor_cols 之前，确定 dropna_cols 默认值
   412|    default_dropna_cols = factor_cols
   413|    
   414|    all_factor_cols = factor_cols
   415|    if additional_factor_files:
   416|        all_factor_cols = factor_cols + list(additional_factor_files.keys())
   417|    # dropna_cols 默认值基于原始 factor_cols，不含额外列
   418|    dropna_cols = default_dropna_cols
   419|```
   420|
   421|**原因：**
   422|1. 用户传入 `factor_cols=['close']`，预期 dropna 默认只过滤 'close'
   423|2. 若 dropna_cols 在参数修改之后确定，会隐式包含额外列（如 'turnover_rate'）
   424|3. 隐式行为导致过多数据被过滤，用户未预期
   425|4. 若用户需要过滤额外列，需显式传入 `dropna_cols` 参数
   426|
   427|**参考：** data_loader.py 第122行（default_dropna_cols 定义）
   428|
   429|### inner join 数据丢失告知规范（重要）
   430|
   431|**合并额外因子文件时必须告知数据丢失情况：**
   432|
   433|```python
   434|# 错误写法（静默丢失数据）
   435|factor_df = pd.merge(factor_df, additional_df, on=['date', 'asset'], how='inner')
   436|print(f"  - 合并 {col_name} 后: {len(factor_df)} 行")  # 只打印结果行数
   437|
   438|# 正确写法（告知数据丢失）
   439|rows_before = len(factor_df)
   440|factor_df = pd.merge(factor_df, additional_df, on=['date', 'asset'], how='inner')
   441|rows_after = len(factor_df)
   442|rows_lost = rows_before - rows_after
   443|
   444|if rows_lost > 0:
   445|    print(f"  - 合并 {col_name} 后: {rows_after} 行（丢失 {rows_lost} 行，{rows_lost/rows_before*100:.1f}%）")
   446|else:
   447|    print(f"  - 合并 {col_name} 后: {rows_after} 行（无数据丢失）")
   448|```
   449|
   450|**原因：**
   451|1. inner join 会静默丢弃不匹配的行（如额外因子文件缺少某些日期/股票）
   452|2. 只打印合并后行数，用户无法感知数据丢失
   453|3. 数据丢失可能导致下游分析结果偏差，排查困难
   454|4. 打印丢失行数和百分比，帮助用户判断数据质量
   455|
   456|**输出示例：**
   457|- 有数据丢失：`合并 turnover_rate 后: 15000 行（丢失 500 行，3.2%）`
   458|- 无数据丢失：`合并 turnover_rate 后: 15500 行（无数据丢失）`
   459|
   460|**参考：** data_loader.py 第142-154行（合并前后对比行数）
   461|
   462|### raw_metadata 计算规范（重要）
   463|
   464|**必须在所有 merge 前快照原始数据：**
   465|
   466|```python
   467|# 错误写法（在 inner join 后计算，已不是"原始缓存"数据）
   468|factor_df = pd.merge(factor_df, additional_df, on=['date', 'asset'], how='inner')
   469|# inner join 会丢失数据，导致 avg_stocks_per_day 不准确
   470|raw_avg_stocks_per_day = int(factor_df.groupby('date').size().mean())
   471|
   472|# 正确写法（在所有 merge 前快照）
   473|factor_df = _convert_date_column(factor_df, '因子')
   474|# 在加载额外因子文件前，快照原始数据范围
   475|raw_period_start = str(factor_df['date'].min())
   476|raw_period_end = str(factor_df['date'].max())
   477|raw_total_days = factor_df['date'].nunique()
   478|raw_avg_stocks_per_day = round(factor_df.groupby('date').size().mean(), 1)
   479|
   480|# 后续 merge 不影响 raw_metadata
   481|if additional_factor_files:
   482|    factor_df = pd.merge(factor_df, additional_df, ...)
   483|```
   484|
   485|**精度处理：**
   486|- 使用 `round(x, 1)` 保留一位小数（如 155.7）
   487|- 禁止 `int()` 直接截断（如 int(155.7) = 155，不是四舍五入）
   488|- avg_stocks_per_day 是浮点数，不应强制截断为整数
   489|
   490|**原因：**
   491|1. raw_metadata 应反映原始缓存数据，而非 merge/dropna 后的数据
   492|2. inner join 会丢失数据，导致 avg_stocks_per_day 不准确
   493|3. int() 直接截断精度丢失，round() 四舍五入更合理
   494|
   495|**参考：** data_loader.py 第120-127行（在 merge 前快照原始数据）
   496|
   497|### DataFrame 函数修改规范（重要）
   498|
   499|**函数不应修改传入的 DataFrame（遵循最小惊讶原则）：**
   500|
   501|   501|```python
   502|# 错误写法（直接修改传入对象）
   503|def _convert_date_column(df: pd.DataFrame) -> pd.DataFrame:
   504|    df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
   505|    return df  # 同时修改了原始 df，违反最小惊讶原则
   506|
   507|# 正确写法（使用 .copy() 创建副本）
   508|def _convert_date_column(df: pd.DataFrame) -> pd.DataFrame:
   509|    df = df.copy()  # 创建副本，确保不修改原始对象
   510|    df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
   511|    return df  # 返回新对象，原始对象不变
   512|```
   513|
   514|**原则：**
   515|1. 函数有返回值时，不应同时修改传入对象
   516|2. 用户期望函数返回新对象，而非修改传入对象
   517|3. 使用 `.copy()` 创建副本，确保不修改原始对象
   518|4. 若必须修改传入对象，应在函数名和文档中明确声明（如 `_modify_xxx_inplace`）
   519|
   520|**原因：**
   521|1. DataFrame 是可变对象，直接修改会影响调用方
   522|2. 调用方可能后续使用原始 DataFrame，修改导致逻辑错误
   523|3. 违反最小惊讶原则，用户未预期传入对象被修改
   524|
   525|**参考：** data_loader.py 第263行（df.copy() 创建副本）
   526|
   527|### reset_index 规范（重要）
   528|
   529|**过滤/筛选操作后必须 reset_index：**
   530|
   531|```python
   532|# 错误写法（reset_index 缺失）
   533|factor_df = factor_df.dropna(subset=dropna_cols)  # dropna 后索引断裂
   534|factor_df = factor_df[factor_df['date'].isin(common_dates)]  # isin 筛选后索引断裂
   535|# 后续操作可能因索引断裂导致错误
   536|
   537|# 正确写法（统一 reset_index）
   538|factor_df = factor_df.dropna(subset=dropna_cols).reset_index(drop=True)
   539|factor_df = factor_df[factor_df['date'].isin(common_dates)].reset_index(drop=True)
   540|# 所有过滤操作后统一重置索引，行为一致
   541|```
   542|
   543|**原因：**
   544|1. dropna/isin 等过滤操作会导致索引断裂（不连续）
   545|2. 索引断裂可能导致下游操作错误（如 iloc/loc 混用）
   546|3. 与前面 dropna 后的 reset_index 行为一致，保持统一性
   547|4. `reset_index(drop=True)` 避免保留旧索引列
   548|
   549|**适用场景：**
   550|- dropna 过滤缺失值后
   551|- isin 筛选日期/股票后
   552|- merge 合并数据后（可选，视场景）
   553|- 任何导致行数减少的操作后
   554|
   555|**参考：** data_loader.py 第225-226行（日期对齐后 reset_index）
   556|
   557|### 未使用 import 规范（重要）
   558|
   559|**禁止导入未使用的模块：**
   560|
   561|```python
   562|# 错误写法（未使用 import）
   563|import numpy as np  # 代码中无 np 引用
   564|import pandas as pd
   565|...
   566|
   567|# 正确写法（只导入需要的模块）
   568|import gzip
   569|import json
   570|import pandas as pd
   571|from pathlib import Path
   572|```
   573|
   574|**原因：**
   575|1. 未使用 import 增加代码噪音，降低可读性
   576|2. 可能误导读者认为模块被使用
   577|3. 部分工具（如 lint）会检测未使用 import 并报错
   578|4. 保持代码整洁，只导入真正需要的模块
   579|
   580|**参考：** data_loader.py 第17-22行（import 列表）
   581|
   582|### 列表浅拷贝规范（重要）
   583|
   584|**列表赋值必须使用显式拷贝（防止引用污染）：**
   585|
   586|```python
   587|# 错误写法（浅拷贝，引用同一对象）
   588|default_dropna_cols = factor_cols  # 浅拷贝，引用调用方传入的列表
   589|all_factor_cols = factor_cols      # 同上，注释说"独立变量"但实际是引用
   590|# 调用方修改 factor_cols 会影响函数内的 default_dropna_cols
   591|
   592|# 正确写法（显式拷贝，创建新列表对象）
   593|default_dropna_cols = list(factor_cols)  # 真正的副本，不污染调用方
   594|all_factor_cols = list(factor_cols)      # 真正的副本，不污染调用方
   595|# 调用方修改 factor_cols 不影响函数内的副本
   596|```
   597|
   598|**原因：**
   599|1. Python 列表赋值是浅拷贝（引用传递），而非深拷贝
   600|2. `a = b` 让 a 和 b 指向同一对象，修改一个会影响另一个
   601|3. 函数参数是调用方传入的列表，函数内赋值仍引用原列表
   602|4. 注释说"独立变量"但实际是引用，语义矛盾，误导维护者
   603|5. 使用 `list()` 创建新列表对象，确保真正的独立
   604|
   605|**适用场景：**
   606|- 函数参数是可变对象（List、Dict、Set）
   607|- 需要在函数内修改副本而不影响调用方
   608|- 注释说"独立变量"或"副本"时必须使用显式拷贝
   609|
   610|**参考：** data_loader.py 第132-135行（list() 创建副本）
   611|
   612|### 列验证规范（重要）
   613|
   614|**在 merge/select 前验证列是否存在：**
   615|
   616|```python
   617|# 错误写法（列未验证，pandas 抛出不友好的 KeyError）
   618|factor_df = pd.merge(factor_df, additional_df[['date', 'asset', col_name]], ...)
   619|# 若 col_name 不存在，pandas KeyError: "['col_name'] not in index"
   620|
   621|# 正确写法（在 merge 前验证，提供友好错误信息）
   622|if col_name in additional_df.columns:
   623|    additional_df[col_name] = pd.to_numeric(additional_df[col_name], errors='coerce')
   624|else:
   625|    available_cols = sorted([c for c in additional_df.columns if c not in ['date', 'asset']])
   626|    raise KeyError(
   627|        f"额外因子文件 '{file_path}' 缺少指定列: '{col_name}'\n"
   628|        f"可用列: {available_cols}"
   629|    )
   630|
   631|factor_df = pd.merge(factor_df, additional_df[['date', 'asset', col_name]], ...)
   632|```
   633|
   634|**原因：**
   635|1. pandas 原生 KeyError 信息不友好，不显示可用列
   636|2. 用户无法快速定位问题，排查困难
   637|3. 提供可用列列表，帮助用户修正参数
   638|4. 验证时机应在 merge/select 前而非操作后
   639|
   640|**适用场景：**
   641|- merge 合并 DataFrame 前
   642|- select 选择列前（`df[['col1', 'col2']]`）
   643|- dropna 指定列前
   644|
   645|**参考：** data_loader.py 第148-155行（列验证 + 友好错误信息）
   646|
   647|### 列表去重保序规范（重要）
   648|
   649|**合并列表时必须去重并保持顺序：**
   650|
   651|```python
   652|# 错误写法（不去重，可能产生重复列）
   653|select_cols = ['date', 'asset'] + factor_cols
   654|# 若 factor_cols=['date', 'rsi_6']，select_cols=['date', 'asset', 'date', 'rsi_6']
   655|# factor_df 出现重复 'date' 列，下游操作异常
   656|
   657|# 正确写法（去重保序）
   658|select_cols = list(dict.fromkeys(['date', 'asset'] + factor_cols))
   659|# 结果：['date', 'asset', 'rsi_6']（去重后顺序正确）
   660|```
   661|
   662|**原理：**
   663|- `dict.fromkeys(iterable)` 创建字典，键来自 iterable，值全为 None
   664|- 字典键天然去重，保留首次出现顺序（Python 3.7+）
   665|- `list(dict.fromkeys(...))` 转为列表，实现去重保序
   666|
   667|**原因：**
   668|1. 用户可能传入 `factor_cols=['date', 'rsi_6']`（包含基础列）
   669|2. 直接合并会导致重复列名，DataFrame 操作异常
   670|3. `set()` 去重但丢失顺序，`dict.fromkeys()` 去重保序
   671|4. 保持顺序确保 'date'、'asset' 在前，方便调试
   672|
   673|**适用场景：**
   674|- 合并列表时去重（如 `base_cols + user_cols`）
   675|- DataFrame 列选择前去重（防止重复列）
   676|- 需要保持首次出现顺序的场景
   677|
   678|**参考：** data_loader.py 第204行（dict.fromkeys 去重保序）
   679|
   680|### dropna_cols 参数验证规范（重要）
   681|
   682|**使用 dropna 前验证列是否存在：**
   683|
   684|```python
   685|# 错误写法（列未验证，pandas 抛出不友好的 KeyError）
   686|factor_df = factor_df.dropna(subset=dropna_cols)
   687|# 若 dropna_cols=['invalid_col']，pandas KeyError: "['invalid_col'] not in index"
   688|
   689|# 正确写法（在 dropna 前验证，提供友好错误信息）
   690|missing_dropna_cols = [col for col in dropna_cols if col not in factor_df.columns]
   691|if missing_dropna_cols:
   692|    available_cols = sorted([c for c in factor_df.columns if c not in ['date', 'asset']])
   693|    raise KeyError(
   694|        f"dropna_cols 包含不存在的列: {missing_dropna_cols}\n"
   695|        f"可用列: {available_cols}"
   696|    )
   697|
   698|factor_df = factor_df.dropna(subset=dropna_cols).reset_index(drop=True)
   699|```
   700|
   701|**原因：**
   702|1. 用户显式传入 dropna_cols 参数时，可能包含不存在的列名
   703|2. pandas 原生 KeyError 信息不友好，不显示可用列
   704|3. 提供可用列列表，帮助用户快速修正参数
   705|4. 与其他参数验证风格一致（如 factor_cols、return_col）
   706|
   707|**适用场景：**
   708|- 用户显式传入 dropna_cols 参数
   709|- dropna 操作前验证列是否存在
   710|- 任何使用 subset 参数的 pandas 操作前
   711|
   712|**参考：** data_loader.py 第218-226行（dropna 前验证列）
   713|
   714|### 基础列验证时机规范（重要）
   715|
   716|**基础列验证应在数据加载后立即执行：**
   717|
   718|```python
   719|# 错误写法（验证时机晚，错误难以定位）
   720|factor_df = pd.DataFrame(factor_data['data'])
   721|print(f"  - 因子数据: {len(factor_df)} 行, {factor_df['asset'].nunique()} 只股票")
   722|# 若 asset 列不存在，KeyError 抛出在打印语句，难以定位问题根源
   723|# 用户可能以为是打印语句错误，而非数据缺少 asset 列
   724|
   725|# 正确写法（加载后立即验证，提供明确错误信息）
   726|factor_df = pd.DataFrame(factor_data['data'])
   727|
   728|# 基础列验证（加载后立即验证）
   729|for col in ['date', 'asset']:
   730|    if col not in factor_df.columns:
   731|        raise KeyError(f"因子数据缺少必需列: '{col}'，无法继续处理")
   732|
   733|print(f"  - 因子数据: {len(factor_df)} 行, {factor_df['asset'].nunique()} 只股票")
   734|```
   735|
   736|**原因：**
   737|1. 基础列（date, asset）是所有后续操作的依赖，必须首先验证
   738|2. 验证时机应在数据加载后立即执行，而非打印语句前
   739|3. 打印语句中访问列时，若列不存在会抛出 KeyError，错误位置难以定位
   740|4. 提前验证提供明确错误信息，帮助用户定位问题根源
   741|
   742|**验证顺序：**
   743|1. 加载数据 → 立即验证基础列 → 打印统计信息
   744|2. 日期转换 → 验证因子列/收益列 → 其他操作
   745|3. 基础列验证必须最先执行，其他验证可按逻辑顺序执行
   746|
   747|**参考：** data_loader.py 第100-106行（加载后立即验证基础列）
   748|
   749|### JSON键验证规范（重要）
   750|
   751|**JSON数据加载后应立即验证关键键存在：**
   752|
   753|```python
   754|# 错误写法（键未验证，抛出难以定位的 KeyError）
   755|factor_data = json.load(f)
   756|factor_df = pd.DataFrame(factor_data['data'])
   757|# 若 factor_data 缺少 'data' 键，pd.DataFrame 抛出 KeyError: "data"
   758|# 错误位置在 DataFrame 构造，而非 JSON 加载，难以定位
   759|
   760|# 正确写法（加载后立即验证键）
   761|factor_data = json.load(f)
   762|
   763|# 验证 JSON 结构键存在
   764|if 'data' not in factor_data:
   765|    raise KeyError(
   766|        f"因子缓存文件 '{factor_cache_path}' 缺少 'data' 键\n"
   767|        f"JSON 结构: {list(factor_data.keys())}"
   768|    )
   769|
   770|factor_df = pd.DataFrame(factor_data['data'])
   771|```
   772|
   773|**原因：**
   774|1. JSON 文件可能缺少 'data' 键（格式错误、损坏、版本不匹配）
   775|2. pd.DataFrame(factor_data['data']) 若键不存在，抛出 KeyError
   776|3. 错误位置在 DataFrame 构造，而非 JSON 加载，难以定位问题根源
   777|4. 提前验证键存在，提供明确错误信息（显示 JSON 结构）
   778|
   779|**验证顺序：**
   780|1. 加载 JSON → 立即验证关键键（'data'）→ 构建 DataFrame
   781|2. 验证基础列 → 打印统计信息 → 其他操作
   782|
   783|**参考：** data_loader.py 第100-105行（JSON 键验证）
   784|
   785|### 除零防护规范（重要）
   786|
   787|**除法运算前应检查除数是否为零：**
   788|
   789|```python
   790|# 错误写法（除零风险）
   791|rows_before = len(factor_df)
   792|rows_lost = rows_before - rows_after
   793|pct = rows_lost / rows_before * 100  # 若 rows_before == 0，抛出 ZeroDivisionError
   794|
   795|# 正确写法（检查除数）
   796|rows_before = len(factor_df)
   797|rows_lost = rows_before - rows_after
   798|
   799|if rows_lost > 0:
   800|    if rows_before > 0:
   801|        pct = rows_lost / rows_before * 100
   802|        print(f"丢失 {rows_lost} 行，{pct:.1f}%")
   803|    else:
   804|        print(f"丢失 {rows_lost} 行，原始数据为空")
   805|```
   806|
   807|**原因：**
   808|1. rows_before 可能为 0（数据为空、merge 后清空）
   809|2. 直接除法 rows_lost / rows_before 会抛出 ZeroDivisionError
   810|3. 分支检查 rows_before > 0 防止除零错误
   811|4. 特殊情况（rows_before == 0）提供友好提示
   812|
   813|**适用场景：**
   814|- 任何除法运算（计算百分比、比例）
   815|- 计算统计指标（IC、相关性）
   816|- 数据丢失率计算
   817|
   818|**参考：** data_loader.py 第199-204行（除零防护）
   819|
   820|---
   821|
   822|## 日志规范
   823|
   824|**遵循 PROJECT.md 项目级日志规范（第380-500行）。**
   825|
   826|### 核心要点
   827|
   828|| 规范内容 | PROJECT.md 定义位置 |
   829||---------|---------------------|
   830|| 日志框架 | Python 标准库 `logging` 模块（第384-392行） |
   831|| 日志级别 | DEBUG/INFO/WARNING/ERROR/CRITICAL（第423-438行） |
   832|| 日志路径 | 脚本当前目录下 `logs/` 子目录（第441-460行） |
   833|| 文件命名 | `<脚本名>_YYYY-MM-DD.log`（第473-492行） |
   834||| 日志格式 | `%(asctime)s | %(levelname)-8s | %(name)s | %(message)s`（第494-500行） |
   835||| 公共模块日志传递 | PROJECT.md 第783-857行（重要） |
   836|
   837|### 公共模块日志传递规范（重要）
   838|
   839|**核心原则：公共模块不独立创建 logger，由调用方传入。**
   840|
   841|遵循 PROJECT.md 第783-857行规范：
   842|- 公共函数签名：`def public_function(..., logger=None)`
   843|- 调用方传入：`load_data_from_cache(..., logger=logger)`
   844|- 日志定位：调用方的日志文件
   845|
   846|**logger 参数命名规范（防止遮蔽）：**
   847|
   848|| 问题 | 错误做法 | 正确做法 |
   849||------|---------|---------|
   850|| 参数遮蔽模块级变量 | `def func(logger=None)` + 模块级 `logger = get_logger()` | 使用已导入的 get_logger，不重复导入 |
   851|| fallback 重复导入 | `from .logger_config import get_logger` 在函数内再次导入 | 删除函数内导入，使用模块级已导入的 get_logger |
   852|
   853|**正确示例：**
   854|
   855|```python
   856|# 模块级导入（一次导入）
   857|from .logger_config import get_logger
   858|logger = get_logger(__name__)  # 模块级 logger（给 main 使用）
   859|
   860|def public_function(..., logger=None):
   861|    """
   862|    参数:
   863|        logger: 日志记录器（由调用方传入，默认使用模块 logger）
   864|    """
   865|    # fallback 使用已导入的 get_logger（不重复导入）
   866|    if logger is None:
   867|        logger = get_logger(__name__)
   868|    
   869|    logger.info("操作完成")
   870|```
   871|
   872|**禁止行为：**
   873|
   874|```
   875|❌ 函数内重复导入 get_logger（浪费资源）
   876|❌ 参数名与模块级变量同名且无明确 fallback 逻辑（遮蔽混淆）
   877|❌ 公共模块独立创建 logger（无法定位调用方）
   878|```
   879|
   880|### 迁移计划
   881|
   882|**Phase 1**：已完成（PROJECT.md 规范定义）
   883|**Phase 2**：替换 `factor_ic/common/*.py` 中所有 print → logging（待执行）
   884|**Phase 3**：替换 `factor_ic/*.py` 中所有 print → logging（待执行）
   885|
   886|**详细规范请参考：** `PROJECT.md` 第380-500行（日志规范章节）
   887|
   888|---
   889|
   890|## ic_result_builder.py — IC结果构建公共模块
   891|
   892|**文件路径：** `factor_ic/common/ic_result_builder.py`
   893|
   894|### 核心函数
   895|
   896|```python
   897|def build_ic_result(
   898|    ic_result: Dict,
   899|    raw_metadata: Dict,
   900|    factor_name: str,
   901|    return_period: str = '1d',
   902|    data_source: str = '',
   903|    factor_col: str = '',
   904|    update_mode: str = 'full'
   905|) -> Dict:
   906|    """
   907|    构建 IC 分析完整结果（符合 MODULE.md 输出结构统一性规范）
   908|    
   909|    参数:
   910|        ic_result: calculate_ic_with_direction_verification 返回值
   911|        raw_metadata: load_factor_return_data 返回的原始数据元信息
   912|        factor_name: 因子名称（如 'rsi_1d', 'volume_ratio_1d')
   913|    
   914|    返回:
   915|        符合 MODULE.md 规范的完整 JSON 结构字典
   916|    """
   917|```
   918|
   919|### 功能列表
   920|
   921|| 功能 | 描述 | 输出字段 |
   922||------|------|----------|
   923|| 结果组装 | 将 ic_calculator 返回值转换为完整结构 | 所有顶层字段 |
   924|| rolling_ic_mean | 20日窗口滚动均值（min_periods=10） | `rolling_ic_mean` |
   925|| sample_stats | 样本统计 + 口径范围说明 | `sample_stats` |
   926|| summary | 综合评价 + 推荐 | `summary` |
   927|| factor_stats | 因子基本信息 | `factor_stats` |
   928|| error_result | 错误情况默认结构 | 所有字段（默认值） |
   929|
   930|### 使用示例
   931|
   932|```python
   933|from factor_ic.common.data_loader import load_factor_return_data
   934|from factor_ic.common.ic_calculator import calculate_ic_with_direction_verification
   935|from factor_ic.common.ic_result_builder import build_ic_result, save_ic_result
   936|
   937|# 加载数据
   938|factor_df, return_df, raw_metadata = load_factor_return_data(
   939|    factor_cols=['rsi_6']
   940|)
   941|
   942|# 计算 IC
   943|ic_result = calculate_ic_with_direction_verification(
   944|    factor_df=factor_df,
   945|    return_df=return_df,
   946|    factor_col='rsi_6',
   947|    return_col='forward_return'
   948|)
   949|
   950|# 构建完整结果
   951|result = build_ic_result(
   952|    ic_result=ic_result,
   953|    raw_metadata=raw_metadata,
   954|    factor_name='rsi_1d',
   955|    data_source='data_fetchers/result/factor_data.json.gz',
   956|    factor_col='rsi_6'
   957|)
   958|
   959|# 保存
   960|save_ic_result(result)
   961|```
   962|
   963|### 辅助函数
   964|
   965|| 函数 | 用途 |
   966||------|------|
   967|| `build_sample_stats()` | 单独构建样本统计字段 |
   968|| `build_rolling_ic_mean()` | 单独计算滚动均值 |
   969|| `build_error_result()` | 构建错误默认结构 |
   970|| `get_ic_output_path()` | 获取输出文件路径 |
   971|| `save_ic_result()` | 保存结果到 JSON |
   972|
   973|### 规范要点
   974|
   975|1. 所有字段符合 MODULE.md "输出结构统一性规范"
   976|2. rolling_ic_mean 前 9 个为 None（min_periods=10）
   977|3. sample_stats.avg_stocks_period 包含口径说明
   978|4. summary 基于五维度判断生成推荐
   979|
   980|### 同名字段格式统一规范（重要）
   981|
   982|**同一模块输出的同名字段格式必须一致，避免消费方兼容处理**
   983|
   984|| 字段 | 格式 | 适用函数 |
   985||------|------|---------|
   986|| `calculation_date` | `datetime.now().isoformat()` | `build_ic_result`, `build_error_result` |
   987|
   988|**错误示例：**
   989|```python
   990|# build_ic_result
   991|'calculation_date': datetime.now().isoformat()  # '2026-05-22T14:30:00'
   992|
   993|# build_error_result
   994|'calculation_date': datetime.now().strftime('%Y-%m-%d')  # '2026-05-22'（格式不一致！）
   995|```
   996|
   997|### 函数参数必要结构说明规范（重要）
   998|
   999|**函数签名和文档必须说明参数的必要结构，避免 KeyError 无错误处理**
  1000|
  1001|  1001|| 函数 | 参数 | 必要结构 |
  1002||------|------|---------|
  1003|| `build_sample_stats` | `factor_df` | 必须含 `'date'` 列 |
  1004|| `build_ic_result` | `ic_result` | 必须含 `'ic_series'` 且非空 |
  1005|
  1006|**正确做法：**
  1007|```python
  1008|def build_sample_stats(..., factor_df: pd.DataFrame) -> Dict:
  1009|    """
  1010|    参数:
  1011|        factor_df: 过滤后因子数据 DataFrame【必须含 'date' 列】
  1012|    
  1013|    异常:
  1014|        KeyError: factor_df 缺少 'date' 列
  1015|    """
  1016|    if 'date' not in factor_df.columns:
  1017|        raise KeyError("factor_df 必须包含 'date' 列")
  1018|```
  1019|
  1020|### ICIR 分级规范（重要）
  1021|
  1022|**ICIR < 0 表示因子方向不稳定（ic_mean 与 ic_std 符号相反），需单独标注**
  1023|
  1024|| ICIR 范围 | 稳定性评级 |
  1025||----------|-----------|
  1026|| ICIR < 0 | 不稳定（方向需验证） |
  1027|| ICIR >= 2.0 | 优秀 |
  1028|| ICIR >= 1.0 | 良好 |
  1029|| ICIR < 1.0 | 一般 |
  1030|
  1031|### 入口校验规范（重要）
  1032|
  1033|**公共函数应在入口处校验关键参数，避免处理无效数据**
  1034|
  1035|| 函数 | 校验条件 | 错误处理 |
  1036||------|---------|---------|
  1037|| `build_ic_result` | `ic_series` 为空 | `ValueError` → 提示调用 `build_error_result` |
  1038|
  1039|---
  1040|
  1041|### 模块内部函数复用规范（重要）
  1042|
  1043|**DRY原则：模块内公共函数必须复用，禁止重复实现相同逻辑**
  1044|
  1045|| 场景 | 正确做法 | 错误做法 |
  1046||------|---------|---------|
  1047|| build_ic_result 需要滚动均值 | 调用 `build_rolling_ic_mean(ic_series)` | 直接实现 `ic_series.rolling(window=20, min_periods=10).mean()` |
  1048|
  1049|**原因：**
  1050|1. 避免后续修改窗口参数时需改多处
  1051|2. 公共函数已有完整注释和测试
  1052|3. 语义清晰，易于维护
  1053|
  1054|### 后缀处理规范（重要）
  1055|
  1056|**只处理后缀，避免误处理字符串中间的匹配**
  1057|
  1058|| 场景 | 正确做法 | 错误做法 |
  1059||------|---------|---------|
  1060|| 移除因子名 `_1d` 后缀 | `name[:-3] if name.endswith('_1d') else name` | `name.replace('_1d', '')` |
  1061|
  1062|**示例对比：**
  1063|```python
  1064|# 错误写法（误处理中间的 _1d）
  1065|factor_name = 'my_1d_factor_1d'
  1066|clean = factor_name.replace('_1d', '')  # → 'my_factor'（错误！）
  1067|
  1068|# 正确写法（只处理后缀）
  1069|clean = factor_name[:-3] if factor_name.endswith('_1d') else factor_name  # → 'my_1d_factor'
  1070|```
  1071|
  1072|---
  1073|
  1074|## incremental_engine.py — 增量更新引擎
  1075|
  1076|**文件路径：** `factor_ic/common/incremental_engine.py`
  1077|
  1078|### 核心函数
  1079|
  1080|```python
  1081|def incremental_update_ic(
  1082|    output_path: Path,
  1083|    factor_df_full: pd.DataFrame,
  1084|    return_df_full: pd.DataFrame,
  1085|    raw_metadata: Dict,
  1086|    factor_name: str,
  1087|    factor_col: str,
  1088|    return_col: str = 'forward_return',
  1089|    min_stocks: int = 10
  1090|) -> Dict:
  1091|    """
  1092|    执行增量更新
  1093|    
  1094|    流程:
  1095|        1. 读取现有缓存
  1096|        2. 确定缺失日期
  1097|        3. 计算缺失日期 IC（复用 calculate_single_day_ic）
  1098|        4. 合并数据（去重，新值覆盖旧值）
  1099|        5. 重算统计指标（复用 calculate_ic_statistics）
  1100|        6. 构建输出并保存
  1101|    """
  1102|```
  1103|
  1104|### 功能列表
  1105|
  1106|| 功能 | 描述 | 规范要点 |
  1107||------|------|----------|
  1108|| 缓存读取 | 读取现有 IC 结果 | FileNotFoundError → 全量，JSONDecodeError → 严重错误 |
  1109|| 缺失日期筛选 | 因子日期 - 缓存日期 | 全量加载 + 日期差集 |
  1110|| 逐日 IC 计算 | 复用 calculate_single_day_ic | 确保算法一致性 |
  1111|| 数据合并 | 字典去重（新值优先） | overlap_dates 记录覆盖事件 |
  1112|| 统计重算 | 复用 calculate_ic_statistics | 不手工构建统计字段 |
  1113|| 模式判断 | should_use_incremental() | 返回 UpdateMode 枚举（三值语义清晰） |
  1114|
  1115|### 步骤日志规范（重要）
  1116|
  1117|**步骤编号必须与实际步骤一致，每个步骤都应有对应日志**
  1118|
  1119|| 场景 | 正确做法 | 错误做法 |
  1120||------|---------|---------|
  1121|| 5步流程 | `[1/5]` `[2/5]` `[3/5]` `[4/5]` `[5/5]` | 只打 `[1/5]` `[2/5]`，后续无日志 |
  1122|| 流程注释 | "流程: 1-5（与日志编号一致）" | "流程: 1-6" 但日志只有 1-5 |
  1123|
  1124|### 字典访问防御性规范（重要）
  1125|
  1126|**访问外部传入字典字段必须使用 .get() 并提供默认值**
  1127|
  1128|| 场景 | 正确做法 | 错误做法 |
  1129||------|---------|---------|
  1130|| sample_stats | `raw_metadata.get('total_days', 0)` | `raw_metadata['total_days']` |
  1131|
  1132|**原因：** 外部字典字段可能缺失，KeyError 会中断流程
  1133|
  1134|### 日期比较格式规范（重要）
  1135|
  1136|**日期字符串比较前必须显式统一格式，避免格式不一致导致错误**
  1137|
  1138|```python
  1139|# 错误写法（格式不一致时比较出错）
  1140|if cache_latest >= factor_latest:  # '2026/05/22' vs '2026-05-22' → 错误
  1141|
  1142|# 正确写法（显式格式统一）
  1143|cache_date_normalized = cache_latest.replace('/', '-')
  1144|factor_date_normalized = factor_latest.replace('/', '-')
  1145|if cache_date_normalized >= factor_date_normalized:  # 安全
  1146|```
  1147|
  1148|### 返回值语义规范（重要）
  1149|
  1150|**返回值语义必须清晰，避免布尔多义（False 有多种含义）**
  1151|
  1152|| 场景 | 正确做法 | 错误做法 |
  1153||------|---------|---------|
  1154|| should_use_incremental | 返回 `UpdateMode` 枚举（INCREMENTAL/FULL/SKIP） | 返回 `bool`（False 含义：缓存不存在 OR 缓存已最新） |
  1155|
  1156|**UpdateMode 枚举定义：**
  1157|```python
  1158|class UpdateMode(Enum):
  1159|    INCREMENTAL = 'incremental'  # 缓存滞后，增量更新
  1160|    FULL = 'full'                # 缓存不存在，全量计算
  1161|    SKIP = 'skip'                # 缓存已最新，无需计算
  1162|```
  1163|
  1164|### 变量命名语义规范（重要）
  1165|
  1166|**变量名必须准确反映其语义，避免误导维护者**
  1167|
  1168|| 场景 | 错误命名 | 正确命名 |
  1169||------|---------|---------|
  1170|| 因子数据所有日期 | `dates_in_cache`（误导：缓存日期） | `dates_in_factor_data` |
  1171|| 缺失日期中不在因子数据的 | `dates_not_in_cache`（误导：不在缓存） | `phantom_dates`（幽灵日期） |
  1172|
  1173|---
  1174|
  1175|| 函数 | 用途 |
  1176||------|------|
  1177|| `get_cache_latest_date()` | 获取缓存最新日期 |
  1178|| `read_existing_cache()` | 读取现有缓存数据 |
  1179|| `calculate_missing_dates_ic()` | 计算缺失日期 IC |
  1180|| `merge_ic_data()` | 合并 IC 数据（去重） |
  1181|| `recalculate_statistics()` | 重算统计指标 |
  1182|| `should_use_incremental()` | 判断是否使用增量模式 |
  1183|
  1184|### 使用示例
  1185|
  1186|```python
  1187|from factor_ic.common.incremental_engine import incremental_update_ic, should_use_incremental
  1188|from factor_ic.common.data_loader import load_factor_return_data
  1189|
  1190|# 加载全量数据
  1191|factor_df, return_df, raw_metadata = load_factor_return_data(
  1192|    factor_cols=['rsi_6']
  1193|)
  1194|
  1195|# 判断模式
  1196|output_path = get_ic_output_path('rsi', '1d')
  1197|use_incremental = should_use_incremental(output_path, factor_df, force_full=False)
  1198|
  1199|if use_incremental:
  1200|    # 增量更新
  1201|    result = incremental_update_ic(
  1202|        output_path=output_path,
  1203|        factor_df_full=factor_df,
  1204|        return_df_full=return_df,
  1205|        raw_metadata=raw_metadata,
  1206|        factor_name='rsi_1d',
  1207|        factor_col='rsi_6'
  1208|    )
  1209|else:
  1210|    # 全量计算（使用 calculate_ic_with_direction_verification）
  1211|    ...
  1212|```
  1213|
  1214|### 规范要点
  1215|
  1216|**保存逻辑必须统一使用 save_ic_result：**
  1217|
  1218|```python
  1219|# 错误写法（增量模式裸写，全量模式不一致）
  1220|# 全量模式
  1221|save_ic_result(result, output_path)  # 封装调用
  1222|
  1223|# 增量模式（错误）
  1224|with open(output_path, 'w', encoding='utf-8') as f:
  1225|    json.dump(convert_to_native_types(result), f, ensure_ascii=False, indent=2)  # 裸写
  1226|
  1227|# 正确写法（全量/增量统一使用 save_ic_result）
  1228|save_ic_result(result, output_path)  # 全量模式
  1229|save_ic_result(result, output_path)  # 增量模式
  1230|```
  1231|
  1232|**原因：**
  1233|1. 全量/增量模式应使用统一的保存逻辑，便于维护
  1234|2. `save_ic_result` 内置异常处理（PermissionError、OSError），磁盘满/权限错误时有友好日志
  1235|3. 裸写 `json.dump` 无异常处理，磁盘满/权限错误时直接抛出未捕获异常
  1236|4. 封装函数便于统一修改保存逻辑（如添加校验、更改格式）
  1237|
  1238|**适用场景：**
  1239|- 全量模式保存
  1240|- 增量模式保存
  1241|- 任何 IC 结果保存场景
  1242|
  1243|**参考：** factor_ic_runner.py 第244-245行、ic_result_builder.py 第422-433行（2026-05-22 更新）
  1244|
  1245|---
  1246|
  1247|### incremental_engine 规范要点（旧版保留）
  1248|
  1249|1. 增量模式必须复用 calculate_single_day_ic（算法一致性）
  1250|2. 合并时使用字典去重（新值覆盖旧值）
  1251|3. overlap_dates 必须记录（事件追踪）
  1252|4. rolling_ic_mean 需对齐回 all_dates（None 填充）
  1253|
  1254|---
  1255|
  1256|## factor_ic_runner.py — 主入口模板
  1257|
  1258|**文件路径：** `factor_ic/common/factor_ic_runner.py`
  1259|
  1260|### 核心函数
  1261|
  1262|```python
  1263|def run_factor_ic_analysis(
  1264|    factor_name: str,
  1265|    factor_col: str,
  1266|    return_period: str = '1d',
  1267|    return_col: str = 'forward_return_1d',
  1268|    factor_cols: Optional[List[str]] = None,
  1269|    min_stocks: int = 10,
  1270|    force_full: bool = False,
  1271|    output_path: Optional[Path] = None,
  1272|    custom_factor_calculation: Optional[Callable] = None
  1273|) -> Dict:
  1274|    """
  1275|    因子 IC 分析统一主入口
  1276|    
  1277|    流程:
  1278|        1. 判断模式（全量/增量/跳过）
  1279|        2. 加载数据
  1280|        3. 执行计算
  1281|        4. 构建输出
  1282|        5. 保存结果
  1283|    """
  1284|```
  1285|
  1286|### 功能列表
  1287|
  1288|| 功能 | 描述 | 规范要点 |
  1289||------|------|----------|
  1290|| 模式判断 | should_use_incremental() | force_full → 全量 |
  1291|| 数据加载 | load_factor_return_data() | 支持额外因子文件 |
  1292|| 全量计算 | calculate_ic_with_direction_verification() | 五维度判断 |
  1293|| 增量更新 | incremental_update_ic() | 补充五维度判断 |
  1294|| 结果构建 | build_ic_result() | 符合输出结构规范 |
  1295|| 结果保存 | save_ic_result() | 自动路径生成 |
  1296|
  1297|### 快捷函数
  1298|
  1299|| 函数 | 用途 | 适用场景 |
  1300||------|------|----------|
  1301|| `run_simple_factor_ic()` | 简单因子（直接用缓存列） | RSI、量比 |
  1302|| `run_complex_factor_ic()` | 复杂因子（需预处理） | KDJ、布林带 |
  1303|
  1304|### 快捷函数语义清晰规范（重要）
  1305|
  1306|**函数参数必须与函数名语义一致：**
  1307|
  1308|```python
  1309|# 错误设计（语义矛盾）
  1310|def run_complex_factor_ic(
  1311|    factor_name: str,
  1312|    factor_col: str,
  1313|    factor_cols: List[str],
  1314|    custom_factor_calculation: Optional[Callable] = None  # Optional 与 "complex" 语义矛盾
  1315|):
  1316|    # 若传 None，等价于 run_simple_factor_ic，功能重叠
  1317|    # 调用者可能误用：run_complex_factor_ic('rsi', 'rsi_6', ['rsi_6'])  # 静默跳过自定义计算
  1318|
  1319|# 正确设计（语义清晰）
  1320|def run_complex_factor_ic(
  1321|    factor_name: str,
  1322|    factor_col: str,
  1323|    factor_cols: List[str],
  1324|    custom_factor_calculation: Callable  # 必须参数，与 "complex" 语义一致
  1325|):
  1326|    # 若无需自定义计算，调用者应使用 run_simple_factor_ic
  1327|    # 强制参数防止误用：run_complex_factor_ic('rsi', 'rsi_6', ['rsi_6'])  # TypeError
  1328|```
  1329|
  1330|**原因：**
  1331|1. 函数名定义了用途：`simple` = 无需自定义计算，`complex` = 必须有自定义计算
  1332|2. Optional 参数破坏语义，导致两个函数功能重叠
  1333|3. 调用者可能误用，传 None 导致复杂因子计算被静默跳过
  1334|4. 必须参数强制调用者选择正确的函数，防止误用
  1335|
  1336|**适用场景：**
  1337|- 任何快捷函数设计，参数必须与函数名语义一致
  1338|- 函数名暗示"必须"时，参数不应 Optional
  1339|- 功能重叠时，应明确区分（必须参数 vs 可选参数）
  1340|
  1341|**参考：** factor_ic_runner.py 第353行（2026-05-22 更新）
  1342|
  1343|### 使用示例
  1344|
  1345|```python
  1346|from factor_ic.common.factor_ic_runner import run_simple_factor_ic, run_complex_factor_ic
  1347|
  1348|# 简单因子（直接用缓存列）
  1349|result = run_simple_factor_ic('rsi', 'rsi_6')
  1350|result = run_simple_factor_ic('volume_ratio', 'volume_ratio_5')
  1351|
  1352|# 复杂因子（需自定义计算）
  1353|def calculate_kdj_j(factor_df):
  1354|    # KDJ 计算逻辑
  1355|    low_min = factor_df.groupby('asset')['low'].transform(lambda x: x.rolling(9, min_periods=9).min())
  1356|    high_max = factor_df.groupby('asset')['high'].transform(lambda x: x.rolling(9, min_periods=9).max())
  1357|    rsv = (factor_df['close'] - low_min) / (high_max - low_min) * 100
  1358|    k = rsv.ewm(alpha=1/3, adjust=False).mean()
  1359|    d = k.ewm(alpha=1/3, adjust=False).mean()
  1360|    j = 3 * k - 2 * d
  1361|    factor_df['kdj_j'] = j
  1362|    return factor_df
  1363|
  1364|result = run_complex_factor_ic(
  1365|    factor_name='kdj_j',
  1366|    factor_col='kdj_j',
  1367|    factor_cols=['close', 'high', 'low'],
  1368|    custom_factor_calculation=calculate_kdj_j
  1369|)
  1370|```
  1371|
  1372|### 规范要点（重要）
  1373|
  1374|**日志访问字段必须使用 .get() 防止 KeyError：**
  1375|
  1376|```python
  1377|# 错误写法（直接访问字段，KeyError 会被 except 误报）
  1378|try:
  1379|    ic_result = calculate_ic_with_direction_verification(...)
  1380|    _logger.info(f"IC 均值: {ic_result['ic_mean']:.4f}")  # 若 ic_mean 缺失，KeyError
  1381|except Exception as e:
  1382|    _logger.error(f"IC 计算失败: {e}")  # 实际是日志格式化失败，误报为 IC 计算失败
  1383|
  1384|# 正确写法（使用 .get() 防止 KeyError）
  1385|try:
  1386|    ic_result = calculate_ic_with_direction_verification(...)
  1387|    _logger.info(f"IC 均值: {ic_result.get('ic_mean', 0.0):.4f}")  # 安全访问
  1388|except Exception as e:
  1389|    _logger.error(f"IC 计算失败: {e}")  # 真正的 IC 计算错误
  1390|```
  1391|
  1392|**嵌套字段需双重保护（含 None fallback）：**
  1393|
  1394|```python
  1395|# 错误写法（嵌套访问无保护）
  1396|_logger.info(f"t 统计量: {ic_result['statistical_significance']['t_stat']:.2f}")
  1397|# 若 statistical_significance 缺失，KeyError；若 t_stat 缺失，KeyError
  1398|
  1399|# 错误写法（双重 .get() 无法处理 None 值）
  1400|t_stat = ic_result.get('statistical_significance', {}).get('t_stat', 0.0)
  1401|# 若 statistical_significance 值为 None（而非缺失），None.get() 抛 TypeError
  1402|
  1403|# 正确写法（显式 None fallback）
  1404|stats_sig = ic_result.get('statistical_significance') or {}
  1405|t_stat = stats_sig.get('t_stat', 0.0)
  1406|_logger.info(f"t 统计量: {t_stat:.2f}")
  1407|# .get() 默认值 {} 只在键缺失时生效，若键存在但值为 None，需 or {} fallback
  1408|```
  1409|
  1410|**保持全量/增量模式一致性：**
  1411|
  1412|```python
  1413|# 增量模式（正确示例）
  1414|_logger.info(
  1415|    f"五维度补充完成: 有效天数={len(valid_ic)}, "
  1416|    f"IC均值={stats_result.get('ic_mean', 0.0):.4f}, "
  1417|    f"ICIR={stats_result.get('icir', 0.0):.2f}"
  1418|)
  1419|
  1420|# 全量模式（应与增量模式一致）
  1421|_logger.info(f"IC 均值: {ic_result.get('ic_mean', 0.0):.4f}")
  1422|_logger.info(f"ICIR: {ic_result.get('icir', 0.0):.2f}")
  1423|```
  1424|
  1425|**原因：**
  1426|1. try 块内的 KeyError 会被 except Exception 捕获，掩盖真实原因
  1427|2. 日志格式化失败会被误报为"IC 计算失败"，用户难以定位问题
  1428|3. 嵌套字段访问需双重保护，防止任一层级缺失导致 KeyError
  1429|4. 全量/增量模式应使用一致的访问方式，便于维护
  1430|
  1431|**参考：** factor_ic_runner.py 第277-283行（2026-05-22 更新）
  1432|
  1433|---
  1434|
  1435|### 新增因子开发流程
  1436|
  1437|```
  1438|1. 确定因子类型：
  1439|   - 简单因子（缓存列直接可用）→ 使用 run_simple_factor_ic()
  1440|   - 复杂因子（需预处理）→ 使用 run_complex_factor_ic()
  1441|
  1442|2. 实现因子计算逻辑（复杂因子）：
  1443|   - 定义 custom_factor_calculation 函数
  1444|   - 输入: factor_df（包含原始列）
  1445|   - 输出: factor_df（添加 factor_col 列）
  1446|
  1447|3. 调用主入口：
  1448|   result = run_xxx_factor_ic(...)
  1449|
  1450|4. 检查结果：
  1451|   - update_mode: full/incremental/skip/failed
  1452|   - ic_mean, icir, p_value
  1453|   - 五维度判断结论
  1454|
  1455|总代码量：~50-200行（仅因子计算逻辑）
  1456|```
  1457|
  1458|### CLI 支持
  1459|
  1460|```bash
  1461|# 简单因子
  1462|python -m factor_ic.common.factor_ic_runner --factor rsi --col rsi_6
  1463|
  1464|# 强制全量
  1465|python -m factor_ic.common.factor_ic_runner --factor volume_ratio --col volume_ratio_5 --force-full
  1466|```