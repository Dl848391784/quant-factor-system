# data_fetchers 模块规范

> 版本: v3.08
> 创建时间: 2026-05-19
> 更新时间: 2026-06-02 22:15 北京时间
> 重构时间: 2026-05-24（补充目录结构+命名规则+公共模块规范+公共模块实现）

---

## 快速参考
    11|
    12|### 必须遵守的约束
    13|
    14|**遵循 PROJECT.md"输出数据规范"章节的跨模块通用原则：**
    15|- 输出结构必须统一
    16|- 字段值不可为 None
    17|- 结果输出到 result 目录
    18|
    19|**本模块特定约束（16条）：**
    20|
    21|||| # | 约束 | 说明 |
    22||---|------|------|
    23||| 1 | 脚本命名：`fetch_<数据源>.py` | 如 fetch_turnover.py、fetch_stock_list.py |
    24|| 2 | 输出到 result 目录 | 与 factor_ic 等模块保持一致（cache 为数据源原始缓存） |
    25|| 3 | 因子生成使用 factor_generator.py | 单一数据源，不分散 |
    26|| 4 | 公共模块必须复用 | 禁止脚本自行实现已有功能 |
    27|| 5 | pandas 3.0 使用 transform | 避免 rolling 返回 MultiIndex |
    28|| 6 | 函数修改 DataFrame 需文档说明 | 在 Note 节说明就地修改的列（如 `astype(str)`），不强制 copy |
    29|| 7 | 日志输出到 logs 目录 | 不散落在项目根目录 |
    30|| 8 | 流程文档配套 | docs/<脚本名>_flow.md |
    31|| 9 | N-way merge 去重使用正值 batch_idx | heap 元素为 `(key, batch_idx, counter, stream)`，counter 打破平局 |
    32|| 10 | 大文件验证分两次读 | 第一次加载完整提取 meta+records_count并释放，第二次流式行扫描只解析抽样行 |
    33|| 11 | meta 信息只保留标量 | date_start/date_end/n_assets，而非完整 dates_list/assets_list |
    34|| 12 | 数据验证综合判断 | 不仅检查天数达标，还需检查关键字段非空比例 >= 80% |
    35|| 13 | peek_key/pop_record 检查 exhausted | `if self.exhausted or self.idx >= len(self.records)`，语义一致性（两个方法对称） |
    36|| 14 | is_exhausted 逻辑用 or | `return self.exhausted or self.idx >= len(self.records)`（而非 and） |
    37|| 14 | get_memory_usage_mb Windows 兜底 | `import resource` 在 Windows 下会抛 ModuleNotFoundError，需 try-except 兜底返回 0.0 |
    38|| 15 | main docstring 无 Returns | None 返回类型的函数不需要 Returns 节 |
    39|| 16 | version 字段提取为常量 | 禁止硬编码版本号，提取为 `_OUTPUT_VERSION` 常量便于维护 |
    40|| 17 | datetime.now() 只调用一次 | 固定时间戳后生成两个格式，避免不一致 |
    41|| 18 | 抽样检查均匀抽样 | 避免 `[:1000]` 取前1000条偏差，改为均匀抽样 |
    42|| 21 | N-way merge 显式收集后选最大 | 收集相同 key 所有记录后按 batch_idx 降序选最大，不依赖弹出顺序 |
    43|| 22 | cleanup 增加兜底清理 | merged_*.json.gz 可能残留，cleanup_batch_files 应增加兜底 |
    44|| 23 | 模块级注释合并到常量 | 注释应紧贴常量定义，避免空泛的注释块 |
    45|| 24 | 变量初始化默认值 | 函数顶部初始化所有返回值变量，防止 NameError（包括 records_count） |
    46|| 25 | meta 解析用 json.loads | 避免手动字符串匹配脆弱，分两次加载（先 meta 后 data） |
    47|| 26 | 方法名语义清晰 | `_load_all` 表示一次性加载，而非 `_load_next_chunk` 暗示多次调用 |
    48|| 27 | 返回值避免冗余 | format_final_output 返回值仅用于日志，统计信息由 validate_final_data 提供 |
    49|| 28 | 函数接口契约说明 | 说明实际调用方行为，而非理想化"可以是 datetime 或字符串" |
    || 29 | vmrss 判断用 is not None | `if vmrss is not None` 而非 `if vmrss`（0 是 falsy） |
    || 30 | **新增输出字段完整链路检查** | 修改输出字段需同步 3 处：fetch_xxx.py 输出列 + batch_processor.py 保存逻辑 + factor_generator.py _BASE_COLS（详见约束 30 展开） |
    |

    ### 约束 30 展开：新增输出字段完整链路检查清单

    **问题背景（2026-06-02）**：添加 `volume` 字段到因子数据，经历 3 次修改 + 3 次脚本运行：
    1. 第一次：`fetch_factor_cache.py` 添加 volume 列 → 运行 → volume 未保存
    2. 第二次：`batch_processor.py` 添加保存逻辑 → 运行 → factor_ic_data 未包含
    3. 第三次：`factor_generator.py` 添加 _BASE_COLS → 运行 → 验证通过

    **效率问题**：每次只改一处，运行才发现下游遗漏，导致重复跑脚本。

    **完整链路检查清单**（新增字段必须一次性检查所有 3 处）：

    | 阶段 | 文件 | 修改位置 | 检查命令 |
    |------|------|----------|----------|
    | **数据获取** | `fetch_factor_cache.py` | 第 235 行输出字段列表 + 第 530 行 metadata fields | `grep -n "'volume'" fetch_factor_cache.py` |
    | **数据保存** | `batch_processor.py` | 第 290 行 `required_factor_cols` + 第 318 行 record 构建 | `grep -n "'volume'" batch_processor.py` |
    | **数据合并** | `factor_generator.py` | 第 136 行 `_BASE_COLS` 元组 | `grep -n "'volume'" factor_generator.py` |

    **执行流程**：
    ```
    1. 修改 3 个文件（同步修改，不分批）
    2. 运行 fetch_factor_cache.py --full
    3. 运行 factor_generator.py（合并数据）
    4. 验证最终输出：zcat factor_ic_data.json.gz | head -20 | grep volume
    ```

    **预防措施**：
    - 修改输出字段前，先 grep 搜索所有相关文件
    - 使用"模块链输出列同步"检查清单（见 superpowers-workflow skill Pitfall 表）
    - 新增字段时创建 TODO 列表，逐项核对

    **典型案例**：
    - `volume` 字段添加（2026-06-02）：3 处修改 + 3 次运行
    - 详见 `references/module-chain-column-synchronization-pitfall.md`
    52|| 33 | 函数签名与调用一致 | 返回 None 则调用方不接收，返回 tuple 则调用方接收，避免返回值被丢弃 |
    53|| 36 | BatchStream 提供 __lt__ | 用于 heap 比较，防御性编程 |
    54|| 37 | pop_record 更新 exhausted | 弹出后立即更新状态，保持一致性 |
    55|| 38 | del 注释准确描述 | "减少引用计数"而非"释放内存"（真正释放依赖 GC） |
    56|| 39 | sort_values 后 copy() | 避免 CoW 风险，链式操作用 copy() |
    57|| 40 | del 释放顺序正确 | del data 后 del full，而非只 del full |
    58|| 42 | 一次遍历提取元信息 | 避免 min/max/set 四次遍历，一次遍历同时收集 date_set/asset_set/first_date/last_date |
    59|| 43 | set 内存立即释放 | 提取完元信息后立即 del date_set, asset_set |
    60|| 44 | 合并路径双校验 | factor_merged_path 和 return_merged_path 都校验，避免 None 路径触发 TypeError |
    61|| 45 | 返回值与调用方一致 | 未使用的返回值不计算，函数签名与调用方匹配（避免 `_` 接收） |
    62|| 46 | 流式验证不加载 data | 第一次只读 meta（手动解析），第二次流式扫描边计数边抽样 |
    63|| 47 | 变量定义位置合理 | 避免重复赋值（如 n_records 定义一次，注释说明用途） |
    64|| 48 | mkdir 目录与输出路径一致 | 确保目录创建用正确的路径常量（如 RESULT_DIR 而非 CACHE_DIR） |
    65|| 49 | docstring 类型描述与签名一致 | 函数签名改为 dict，docstring Returns 也需同步修改 |
    66|| 50 | 异常日志包含类型名 | `[{type(e).__name__}]: {e}` 格式便于追溯 |
    67|| 51 | 导入在模块顶部 | PEP 8 规范，不在函数内导入（如 Counter） |
    68|| 52 | 原子写入异常处理 | try-except 包裹，失败时 unlink(missing_ok=True) 清理 |
    69|| 53 | __all__ 导出列表 | 公共模块明确导出接口 |
    70|| 54 | 数据映射添加注释 + TODO | 近似映射需说明用途 + 补充 TODO + 参考链接 |
    71|| 55 | 原子写入捕获所有异常 | except Exception（而非仅 OSError），保证 .tmp 清理 |
    72|| 56 | 日志位置在操作成功后 | rename 成功后才打印日志（而非 try 块外） |
    73|| 57 | 全局缓存线程安全（DCL） | threading.Lock + 双重检查锁，避免重复加载 |
    74|| 58 | 异常捕获需打印详情 | 静默 pass 改为 warning 日志，包含异常值 `{value!r}: {e}` |
    75|| 59 | 关键词映射避免歧义 | 检查关键词是否在多个行业重复，移除或改为具体关键词 |
    76|| 60 | __all__ 不含私有名称 | 以 `_` 开头的名称表示模块私有，不应放入 __all__ |
    77|| 61 | DataFrame 列名校验 | API 返回列名可能变化，需校验必需列存在（防御性编程） |
    78|| 62 | 路径提取常量 + 参数注入 | 避免跨模块硬编码耦合，提取为常量或通过参数注入 |
    79|| 63 | 导入语句不散落 | import 只在模块顶部，不在函数/类定义之间（PEP 8） |
    80|| 64 | 关键词映射消除重复 | 每个关键词只出现在一个行业，避免遍历顺序导致匹配错误 |
    81|| 65 | 注释与代码一致 | 修正误导性注释，确保注释描述与实际代码匹配 |
    82|| 66 | 备用数据写入缓存 | 避免 akshare 不可用时每次重复读文件，备用数据写入缓存 |
    83|| 67 | 缓存刷新失败降级 | 过期缓存刷新失败时降级使用旧缓存（而非直接返回备用数据） |
    84|| 68 | 数据映射注释说明具体 | 注释说明映射来源/依据（而非仅"近似映射"），移除 TODO（要么修正要么映射到其他） |
    85|| 69 | 文档注释与实现一致 | docstring 描述实际实现逻辑（如"名称关键词推断"而非"代码特征"） |
    86|| 70 | 注释诚实化 | 未核对官方标准需诚实说明，不编造来源（如"化学原料+化学制品"），恢复 TODO |
    87|| 71 | 映射核对官方标准 | 核对官方标准后修正映射，不存在的一级代码映射到 '其他'（而非猜测编造） |
    88|| 72 | 备用缓存写入策略（非致命） | 备用缓存写入失败为非致命错误（warning），主缓存失败抛异常，需在设计文档中明确说明 |
    89|| 73 | 日志信息准确反映流程 | 日志说明实际流程（如"akshare获取失败，尝试本地备用数据"而非"返回空映射"） |
    90|| 74 | 缓存数据完整性验证 | 检查 industries 是否为 dict 类型（防止缓存损坏导致后续 AttributeError） |
    91|| 75 | 模糊匹配优先级说明 | 关键词推断需在 Note 中说明模糊匹配优先级（如"中信银行"→证券） |
    92||| 76 | 返回类型注解完整 | 所有公共函数返回值需标注完整类型（如 `dict[str, int]`） |
    93||| 77 | logger参数命名规范 | 公共函数日志参数使用 `logger_arg` 避免遮蔽模块级 `logger`，内部变量用 `_logger = logger_arg or logger` |
    94||| 78 | session资源管理 | HTTP session 必须使用 `with` 语句确保连接池释放，禁止裸创建 |
    95||| 79 | ST股票检测前缀匹配 | 使用 `startswith('ST')` 而非 `'ST' in name`，避免"东ST"正常股票被误判剔除 |
    96||| 80 | 临时文件使用 tempfile | 使用 `tempfile.NamedTemporaryFile` 避免多进程并发冲突，禁止 `.with_suffix('.tmp')` |
    97||| 81 | 增量更新同步 name 字段 | API 返回的 name 可能是最新的，增量更新时需同步更新已存在股票的 name |
    98||| 82 | Optional 变量添加类型守卫 | 使用前添加 None 检查（`if data is None: raise`），确保类型安全 |
    99||| 83 | 验证逻辑与筛选逻辑一致 | validate_cache 必须使用与 is_valid_main_board_stock 一致的 ST 检查逻辑（前缀匹配） |
   100||| 84 | 重试循环内直接控制流 | 删除 success 变量，成功 break，失败在最后一次重试 raise，避免冗余检查 |
   101||| 85 | Optional 变量添加 assert | 使用前添加 `assert isinstance(var, expected_type)`，确保类型安全（比单独检查 None 更严格） |
   102||| 86 | 长列表字段截断 | removed_codes 等可能很长的列表字段限制最多50个，添加 truncated 字段说明是否截断 |
   103||| 19 | 常量定义在 import 之后 | PEP 8 顺序：docstring → __future__ → 标准库 → 第三方 → 本地 → 常量 |
   104||| 20 | cleanup_batch_files 用 try/except | 捕获异常继续清理，而非 try/finally（保证尽可能清理） |
   105|
   106|### 关键函数签名
   107|
   108||| 函数 | 文件 | 用途 |
   109||------|------|------|
   110|| `generate_all_factors(logger)` | factor_generator.py | 生成所有因子数据 |
   111|| `calculate_rsi(df, period)` | factor_calculator.py | 计算 RSI 因子 |
   112|| `calculate_bollinger_pb(df, n, k)` | factor_calculator.py | 计算布林带 %B 因子 |
   113|| `calculate_kdj_j(df, n, m1, m2)` | factor_calculator.py | 计算 KDJ_J 因子 |
   114|| `calculate_turnover_surge(df, window)` | factor_calculator.py | 计算换手率突增因子 |
   115|| `n_way_merge_deduplicate(batches, type)` | batch_processor.py | N-way 合并批次数据 |
   116|| `fetch_turnover_data()` | fetch_turnover.py | 拉取换手率数据 |
   117|
   118|---
   119|
   120|## 目录结构
   121|
   122|```
   123|data_fetchers/
   124|├── MODULE.md           # 本文件（模块规范）
   125|├── common/             # 公共函数
   126|│   ├── __init__.py
   127|│   ├── logger_config.py # 日志配置
   128|│   ├── paths.py         # 路径配置
   129|│   ├── cache_manager.py # 缓存管理
   130|│   ├── http_client.py   # HTTP 客户端
   131|│   ├── stock_utils.py   # 股票筛选
   132|│   ├── memory_utils.py  # 内存监控（2026-05-27新增）
   133|│   └── dataframe_utils.py # DataFrame 验证（2026-05-27新增）
   134|│
   135|├── docs/               # 流程文档
   136|│   ├── plans/           # 重构计划（2026-05-27新增）
   137|│   ├── factor_generator_flow.md
   138|│   └── fetch_<数据源>_flow.md
   139|│
   140|├── result/             # 数据拉取结果输出（元信息）
   141|│   └── .gitkeep
   142|│
   143|├── logs/               # 日志目录
   144|│   └── .gitkeep
   145|│
   146|├── test_cases/         # pytest 测试文件（2026-05-27更新）
   147|│   ├── __init__.py
   148|│   └── test_<脚本名>.py  # pytest 可执行文件
   149|│
   150|├── factor_generator.py # 统一因子生成入口
   151|├── factor_calculator.py # 统一因子计算（2026-05-27新增）
   152|├── batch_processor.py   # 批次处理+N-way合并（2026-05-27新增）
   153|├── fetch_turnover.py   # 换手率数据拉取
   154|├── fetch_stock_list.py # 股票列表拉取
   155|├── fetch_industry.py   # 行业分类拉取
   156|└── fetch_factor_cache.py # 因子缓存管理
   157|```
   158|
   159|---
   160|
   161|## 更新记录
   162|
   163|1. v1.0（2026-05-19）：首次创建模块规范
   164|2. v1.1（2026-05-24 15:22）：
   165|   - 新增"统一因子生成模块"章节
   166|   - 新增 factor_generator.py 规范
   167|   - 新增 pandas 3.0 兼容性规范
   168|3. v2.0（2026-05-24 17:59）：
   169|   - **目录结构规范化**：创建 common/、docs/、result/、logs/、test_cases/
   170|   - **补充快速参考表格**：8条约束 + 关键函数签名
   171|   - **补充脚本命名规则**：`fetch_<数据源>.py`
   172|   - **补充公共模块架构**：common/ 目录规范
   173|   - **补充公共模块强制复用规范**
   174|   - **补充输出目录规范**：result/、logs/ 目录职责
   175|   - **补充版本历史**：记录每次变更
   176|4. v2.1（2026-05-24 18:05）：
   177|   - **创建公共模块**：paths.py、cache_manager.py、http_client.py、stock_utils.py
   178|   - **公共模块架构更新**：从"待创建"状态改为"已实现"
   179|   - **新增 common/README.md**：公共模块使用文档
   180|5. v2.2（2026-05-24 20:35）：
   181|   - **cache_manager.py 优化**：接收 logger 参数（遵循 PROJECT.md 第783-857行规范）
   182|   - **新增 cache_manager.py 日志参数规范**：使用方式、参数类型、禁止行为
   183|   - **JSON 解析异常处理**：避免内存翻倍（参考 backtest-module-optimization-patterns.md）
   184|   - **参数类型支持**：`path` 支持 `Path | str`
   185|6. v2.3（2026-05-24 21:10）：
   186|   - **函数命名修复**：`_get_logger` → `get_module_logger`（遵循命名规范）
   187|   - **get_cache_file_info 日志使用**：添加 DEBUG/WARNING 日志输出
   188|   - **流程文档创建**：docs/cache_manager_flow.md
   189|   - **测试用例创建**：test_cases/cache_manager_test_cases.md
   190|7. v2.4（2026-05-24 21:40）：
   191|   - **代码重复消除**：新增 `_read_cache_impl`、`_write_cache_impl` 公共函数
   192|   - **文件类型判断优化**：新增 `_is_gzip_file` 函数统一判断
   193|   - **重构读写函数**：read_gzip_data_fetchers/result/read_json_data_fetchers/result/write_gzip_data_fetchers/result/write_json_cache 调用公共实现
   194|   - **append_to_cache 重构**：使用 `_is_gzip_file` 和公共实现函数
   195|   - **代码行数减少**：从 322行 → 272行（减少 50行）
   196|   - **流程文档更新**：版本历史 v1.2，架构图新增公共函数
   197|8. v2.5（2026-05-24 21:45）：
   198|   - **类型注解修复**：`new_data: list` → `List[Any]`（符合 Python 类型规范）
   199|   - **防御性编程**：append_to_cache 添加数据类型验证 + WARNING 日志
   200|   - **__all__ 导出**：明确定义公共API（7个函数）
   201|   - **测试代码增强**：新增 append_to_cache + 错误场景 + 防御性编程测试
   202|   - **流程文档更新**：版本历史 v1.3
   203|9. v2.6（2026-05-24 21:50）：
   204|   - **统一缓存 API**：新增 `read_cache`、`write_cache`（自动判断 gzip/json）
   205|   - **辅助函数**：新增 `cache_exists`、`delete_cache`（缓存存在性检查 + 删除）
   206|   - **大文件监控**：新增 `_LARGE_FILE_THRESHOLD_MB = 100`，>100MB 触发 WARNING
   207|   - **__all__ 更新**：新增 4 个函数（11个公共API）
   208|   - **测试代码增强**：新增统一 API + 辅助函数测试
   209|   - **流程文档更新**：版本历史 v1.4
   210|10. v2.7（2026-05-24 21:55）：
   211|   - **gzip 压缩级别控制**：新增 `compresslevel` 参数（默认 6，平衡压缩率和速度）
   212|   - **JSON 序列化格式选项**：新增 `json_indent`、`json_sort_keys` 参数
   213|   - **缓存数据类型验证**：`_write_cache_impl` 添加非字典类型 WARNING 日志
   214|   - **新增模块级常量**：`_DEFAULT_GZIP_COMPRESSLEVEL`、`_JSON_COMPACT_SEPARATORS`、`_JSON_READABLE_INDENT`
   215|   - **更新所有写入函数签名**：`write_gzip_cache`、`write_json_cache`、`write_cache` 新增参数
   216|   - **测试代码增强**：新增压缩级别 + 可读格式测试
   217|   - **流程文档更新**：版本历史 v1.5
   218|11. v2.8（2026-05-24 22:20）：
   219|   - **异常处理精确化**：捕获 `BadGzipFile`、`PermissionError`、`OSError`
   220|   - **空文件处理**：大小为 0 返回空字典 {}
   221|   - **__init__.py 导出修复**：新增 `get_module_logger`、`read_cache`、`write_cache`、`cache_exists`、`delete_cache` 导出
   222|   - **测试用例同步**：新增 TC022-TC024（gzip 损坏、空文件、权限错误）
   223|   - **流程文档更新**：版本历史 v1.6
   224|12. v2.9（2026-05-24 22:40）：
   225|   - **测试代码日志规范化**：替换 24处 print 为 logger.info/logger.debug
   226|   - **新增 setup_test_logger 函数**：遵循 PROJECT.md 第780-839行规范
   227|   - **日志文件输出**：data_fetchers/logs/cache_manager_YYYY-MM-DD.log
   228|   - **导入 datetime**：setup_logger 需要
   229|   - **流程文档更新**：版本历史 v1.7
   230|13. v2.10（2026-05-24 22:50）：
   231|   - **创建 logger_config.py**：遵循 PROJECT.md 第780-839行规范
   232|   - **定义 setup_logger 函数**：可被所有模块复用
   233|   - **复用 setup_logger**：cache_manager.py __main__ 复用 logger_config.py 的 setup_logger
   234|   - **删除 setup_test_logger**：避免重复定义，遵循 DRY 原则
   235|   - **__init__.py 导出新增**：`setup_logger`
   236|   - **流程文档更新**：版本历史 v1.8
   237|
   238|14. v2.11（2026-05-24 23:00）：
   239|   - **测试用例版本同步**：新增 v1.5/v1.6 版本历史
   240|   - **新增 TC025**：setup_logger 测试用例
   241|   - **删除冗余汇总表**：测试用例文档精简
   242|   - **时间标注修复**：流程文档 v1.8 时间改为 22:50
   243|   - **流程文档更新**：版本历史 v1.9
   244|
   245|15. v2.12（2026-05-24 23:10）：
   246|   - **发现 bug**：get_module_logger 缺少 global 声明
   247|   - **修复 UnboundLocalError**：添加 `global _MODULE_LOGGER`
   248|   - **新增 TC026**：get_module_logger global 声明测试
   249|   - **流程文档更新**：版本历史 v1.10
   250|
   251|16. v2.13（2026-05-24 23:20）：
   252|   - **删除冗余导入**：datetime 导入未使用（只在注释中引用）
   253|   - **测试用例版本同步**：v1.7 → v1.10
   254|   - **流程文档更新**：版本历史 v1.11
   255|
   256|17. v2.14（2026-05-25 00:10）：
   257|   - **类型注解修复**：`_write_cache_impl` 参数 `data` 类型从 `Dict[str, Any]` 改为 `Any`（与实际实现一致）
   258|   - **冗余代码消除**：`append_to_cache` 移除第373行重复的 `path.exists()` 检查
   259|   - **规范补充**：新增"缓存文件格式限制"说明（必须是 JSON 格式）
   260|   - **修复原因**：代码审查发现类型注解与实现不一致、冗余检查
   261|
   262|18. v2.15（2026-05-25 00:30）：
   263|   - **线程安全修复**：`_MODULE_LOGGER` 改为模块加载时直接初始化（避免延迟初始化的多线程竞争）
   264|   - **docstring 补充 Raises**：`append_to_cache` 新增异常说明
   265|   - **文档示例完善**：`delete_cache` Example 补充文件不存在场景
   266|   - **测试清理健壮化**：`__main__` 使用 try/finally 确保测试文件清理
   267|   - **修复原因**：代码审查发现线程安全、文档完整性、测试健壮性问题
   268|
   269|19. v2.16（2026-05-25 01:00）：
   270|   - **http_client.py 优化**：遵循 PROJECT.md 公共模块规范
   271|   - **logger 参数化**：新增 `get_module_logger` 函数 + 所有函数接收 logger 参数
   272|   - **__all__ 导出**：明确定义 6 个公共 API
   273|   - **模块级导入**：`import time` 从函数内移至模块级
   274|   - **类型注解修复**：`Exception | None` → `Optional[Exception]`、`Dict` → `Dict[str, Any]`
   275|   - **docstring 补充**：新增 Raises 说明（TypeError、HTTPError、JSONDecodeError）
   276|   - **__main__ 日志规范**：print → logger + try/finally + Session.close()
   277|   - **修复原因**：公共模块规范合规化（与 cache_manager.py 保持一致）
   278|
   279|20. v2.17（2026-05-25 01:30）：
   280|   - **http_client.py 第二轮优化**：深度审查修复
   281|   - **异常处理精确化**：区分 HTTPError/Timeout/ConnectionError/JSONDecodeError，避免宽泛捕获
   282|   - **异常链保留**：RuntimeError 使用 `from last_error` 保留原始异常类型
   283|   - **便捷函数参数补全**：`create_eastmoney_session`/`create_sina_session` 新增 logger 参数
   284|   - **__all__ 导出补充**：新增 `get_module_logger`（与 cache_manager.py 一致）
   285|   - **timeout 类型注解扩展**：支持 `(connect_timeout, read_timeout)` 元组
   286|   - **Retry 参数重构**：提取公共参数 `retry_params`，减少 try/except 内重复代码
   287|   - **import json 补充**：request_with_retry 需要 JSONDecodeError
   288|   - **response 变量初始化**：避免 except 分支未绑定错误
   289|   - **修复原因**：异常处理类型不一致、类型注解不完整、API 参数缺失
   290|
   291|21. v2.18（2026-05-25 02:00）：
   292|   - **http_client.py 第三轮优化**：与 cache_manager.py 对比分析
   293|   - **docstring Example 补充**：4 个公共函数新增使用示例
   294|   - **返回类型注解修复**：`request_with_retry` 返回 `Dict[str, Any]` → `Any`（JSON 可为任意类型）
   295|   - **模块级常量补全**：新增 7 个 `_DEFAULT_*` 私有常量（保持风格一致）
   296|   - **请求头数据来源注释**：补充"浏览器开发者工具抓包，2026-05-24"和用途说明
   297|   - **__main__ 测试增强**：5 项测试覆盖（Session 创建、自定义配置、logger、常量）
   298|   - **函数默认参数重构**：使用 `_DEFAULT_*` 常量替代硬编码数字
   299|   - **修复原因**：文档示例缺失、类型注解不精确、常量风格不一致
   300|
   301|22. v2.19（2026-05-25 02:30）：
   302|   - **http_client.py 第四轮优化**：深度审查完善
   303|   - **模块注释版本历史**：新增 v1.0-v1.3 版本演进说明（与 cache_manager.py 一致）
   304|   - **get_module_logger Example 补充**：新增 fallback logger 和调用方 logger 示例
   305|   - **重试状态码常量定义**：新增 `_DEFAULT_RETRY_STATUS_CODES`（注释说明各状态码含义）
   306|   - **HTTP 方法参数扩展**：新增 `allowed_methods` 参数支持 POST 等方法重试
   307|   - **便捷函数 Raises 补充**：create_eastmoney_session/create_sina_session 新增异常说明
   308|   - **User-Agent 版本更新注释**：补充"每季度检查更新"提示
   309|   - **__main__ 测试扩展**：新增测试 6（allowed_methods 参数）+ 异常测试说明
   310|   - **修复原因**：版本历史缺失、重试方法硬编码、文档不完整
   311|
   312|23. v2.20（2026-05-25 03:00）：
   313|   - **http_client.py 第五轮优化**：修复 4 个关键问题
   314|   - **最后一次失败日志补全**：Timeout/ConnectionError 分支最后一次失败新增警告日志
   315|   - **request_with_retry 方法参数**：新增 `method` 参数支持 GET/POST/PUT/DELETE
   316|   - **退避策略文档化**：docstring 明确说明"线性递增退避策略"及适用场景
   317|   - **create_retry_session 默认 headers 修复**：默认 None（不再使用东财请求头），调用方必须显式传入
   318|   - **__main__ 测试扩展**：新增测试 7（headers=None）+ 测试 8（method 参数验证）
   319|   - **修复原因**：代码bug（日志缺失、默认headers不合理）、规范遗漏（方法参数缺失、退避策略未说明）
   320|
   321|24. v2.21（2026-05-25 21:30）：
   322|   - **http_client.py 第六轮优化**：安全性修复（5 个问题）
   323|   - **JSON 解析异常捕获补全**：同时捕获 `json.JSONDecodeError` 和 `requests.exceptions.JSONDecodeError`
   324|   - **Retry 异常缩小捕获范围**：只捕获 allowed_methods 参数错误，其他 TypeError 正常抛出
   325|   - **response.text 安全访问**：使用 `getattr` 避免 streaming 模式问题，空字符串正确显示 N/A
   326|   - **DEFAULT_*_HEADERS 不可变**：使用 `MappingProxyType` 包装，防止外部修改影响所有调用
   327|   - **headers 类型注解修复**：`Dict[str, str]` → `Mapping[str, str]`（支持 MappingProxyType）
   328|   - **__main__ 测试重构**：移除私有常量测试，改为验证公共常量不可变性
   329|   - **修复原因**：代码bug（异常捕获不完整、安全访问缺失、可变常量）、规范遗漏（测试代码不规范）
   330|
   331|25. v2.22（2026-05-25 21:35）：
   332|   - **cache_manager.py 第七轮优化**：原子写入修复（3 个问题）
   333|   - **错误信息精确化**：区分 gzip/json 文件，显示"gzip JSON 文件内容解析失败"而非"JSON解析失败"
   334|   - **原子写入实现**：`_write_cache_impl` 使用临时文件 + `os.replace` 原子替换
   335|   - **append_to_cache 原子化**：受益于 `_write_cache_impl` 原子写入，写入中途崩溃不再丢失数据
   336|   - **失败清理机制**：写入失败时自动删除临时文件，避免残留
   337|   - **版本历史补全**：cache_manager.py 新增 v1.0-v1.12 版本演进说明
   338|   - **修复原因**：代码bug（错误信息误导、非原子操作风险、失败留损坏文件）
   339|
   340|26. v2.23（2026-05-25 21:40）：
   341|   - **stock_utils.py 优化**：遵循 PROJECT.md 公共模块规范
   342|   - **logger 参数化**：新增 `get_module_logger` 函数 + `load_main_board_stock_list` 接收 logger 参数
   343|   - **verbose 参数改为 logger**：`verbose: bool` → `logger: Optional[logging.Logger]`
   344|   - **__all__ 导出**：明确定义 9 个公共 API（6 个函数 + 3 个常量）
   345|   - **模块级导入优化**：`load_main_board_stock_list` 使用条件导入（__main__ 绝对导入，其他相对导入）
   346|   - **docstring 补充**：所有函数新增 Example，`is_main_board_stock` 补充剔除规则示例
   347|   - **__main__ 测试规范化**：print → logger + try/finally + setup_logger + 7 项测试
   348|   - **常量导出**：`MAIN_BOARD_PREFIXES`、`EXCLUDED_PREFIXES`、`EXCLUDED_NAME_KEYWORDS` 导出为公共 API
   349|   - **版本历史补全**：stock_utils.py 新增 v1.0-v1.1 版本演进说明
   350|   - **修复原因**：公共模块规范合规化（logger 参数化、__all__ 导出、测试规范化）
   351|
   352|27. v2.24（2026-05-25 21:41）：
   353|   - **stock_utils.py 第二轮优化**：深度审查优化
   354|   - **类型注解精确化**：`List[Dict]` → `List[Dict[str, Any]]`
   355|   - **条件导入缓存**：模块级缓存导入函数，避免每次调用判断 `__name__`
   356|   - **性能优化**：`is_main_board_stock` 使用 `any()` 替代 for 循环
   357|   - **防御性编程**：
   358|     - `is_main_board_stock` 空值返回 False
   359|     - `get_stock_codes_only` 过滤空代码 + WARNING 日志
   360|     - `get_stock_name_map` 过滤空代码和空名称 + WARNING 日志
   361|     - `filter_stocks_by_date` 参数验证 + DEBUG 日志
   362|   - **类型灵活性**：`load_main_board_stock_list` 支持 `Union[Path, str]`
   363|   - **测试扩展**：8项测试（含边界测试）
   364|   - **版本历史补全**：stock_utils.py 新增 v1.2 版本演进说明
   365|   - **修复原因**：代码bug（条件导入效率低、空值处理缺失）+ 规范遗漏（类型注解不精确）
   366|
   367|28. v2.25（2026-05-25 21:45）：
   368|   - **stock_utils.py 第三轮优化**：辅助函数性能 + 验证补全
   369|   - **辅助函数性能优化**：`get_stock_codes_only`、`get_stock_name_map`、`filter_stocks_by_date` 使用列表推导式
   370|   - **日期范围验证**：`filter_stocks_by_date` 新增 `start_date <= end_date` 检查
   371|   - **常量数据来源注释**：主板/剔除前缀/ST关键词补全数据来源（中国证券交易所规则）
   372|   - **空列表边界检查**：所有辅助函数新增空列表检查 + DEBUG 日志
   373|   - **docstring Raises 补全**：`get_stock_codes_only`、`get_stock_name_map` 补充 TypeError
   374|   - **日志信息精确化**：WARNING 日志补充"总数 X，有效 Y"
   375|   - **测试扩展**：8项测试（含空列表边界 + 日期范围验证）
   376|   - **版本历史补全**：stock_utils.py 新增 v1.3 版本演进说明
   377|   - **修复原因**：规范遗漏（数据来源注释缺失、日期范围验证缺失、边界检查缺失）
   378|
   379|29. v2.26（2026-05-25 21:50）：
   380|   - **stock_utils.py 第四轮优化**：类型安全 + 日期格式验证
   381|   - **筛选逻辑优化**：`load_main_board_stock_list` 使用列表推导式筛选主板股票
   382|   - **类型安全检查**：`get_stock_codes_only`、`get_stock_name_map`、`filter_stocks_by_date` 新增 `isinstance(stock_list, list)` 检查
   383|   - **日期格式正则验证**：新增 `_DATE_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}$')` 精确验证 YYYY-MM-DD
   384|   - **重复调用优化**：辅助函数改为 for 循环 + 变量缓存，避免列表推导式重复调用 `stock.get('code', '')`
   385|   - **空数据处理**：`load_main_board_stock_list` 新增空股票列表检查 + WARNING 日志
   386|   - **docstring Example 格式统一**：移除注释，统一使用 `>>>` 格式
   387|   - **测试扩展**：8项测试（含类型验证 + 日期格式正则验证）
   388|   - **版本历史补全**：stock_utils.py 新增 v1.4 版本演进说明
   389|   - **修复原因**：代码bug（类型安全未实现）+ 规范遗漏（日期格式验证不够严格）
   390|
   391|30. v2.27（2026-05-25 21:57）：
   392|   - **stock_utils.py 第五轮优化**：参数类型安全 + 线程安全 + 日期边界验证
   393|   - **参数类型安全检查**：`is_main_board_stock` 新增 `isinstance(code, str)` 和 `isinstance(name, str)` 检查
   394|   - **线程锁保护**：`_get_imported_functions` 使用双重检查锁定模式（DCL）避免多线程竞争
   395|   - **日期边界验证**：新增 `_MIN_DATE = '1990-12-19'`（A股市场始于1990）和 `_MAX_DATE = datetime.now()` 验证
   396|   - **数据格式验证**：`load_main_board_stock_list` 新增 `isinstance(data, dict)` 检查
   397|   - **常量不可变性注释**：`MAIN_BOARD_PREFIXES`、`EXCLUDED_PREFIXES`、`EXCLUDED_NAME_KEYWORDS` 补充"使用元组确保不可变"注释
   398|   - **docstring Example 格式统一**：`get_module_logger` 从注释改为 `>>>` 格式
   399|   - **docstring Raises 补全**：`is_main_board_stock` 补充 TypeError 说明
   400|   - **测试扩展**：8项测试（含参数类型验证 + 日期边界验证）
   401|   - **版本历史补全**：stock_utils.py 新增 v1.5 版本演进说明
   402|   - **修复原因**：代码bug（参数类型安全未实现、线程竞争）+ 规范遗漏（日期边界验证缺失、常量不可变性注释缺失）
   403|
   404|6. **stock_utils.py v1.6 (2026-05-25)** — 第六轮深度优化
   405|   - **日期边界动态获取**：`_MAX_DATE` 改为 `MAX_STOCK_DATE()` 函数（避免长时间运行程序过期）
   406|   - **日期常量公开**：`_MIN_DATE` → `MIN_STOCK_DATE`（公开常量，供外部查询）
   407|   - **异常链保留**：`load_main_board_stock_list` 使用 `from e` 保留原始异常链
   408|   - **元素类型安全检查**：3个辅助函数新增 `isinstance(stock, dict)` 检查，过滤非字典元素
   409|   - **stocks列表类型验证**：`load_main_board_stock_list` 新增 `isinstance(stocks, list)` 检查
   410|   - **docstring TypeError示例格式**：使用 `# doctest: +IGNORE_EXCEPTION_DETAIL` 规范格式
   411|   - **测试扩展**：元素类型过滤验证测试（验证过滤行为而非抛异常）
   412|   - **版本历史补全**：stock_utils.py 新增 v1.6 版本演进说明
   413|   - **修复原因**：代码bug（日期边界过期风险、元素类型安全未实现）+ 规范遗漏（异常链未保留、docstring示例格式不规范）
   414|
   415|7. **stock_utils.py v1.7 (2026-05-25)** — 第七轮深度优化
   416|   - **logger 参数类型验证**：`get_module_logger` 新增 `isinstance(logger, logging.Logger)` 检查
   417|   - **缓存函数 None 检查**：`load_main_board_stock_list` 新增 `_read_json_cache is None` 和 `_get_stock_list_file is None` 检查
   418|   - **docstring Example 格式规范**：辅助函数 Example 补充返回值显示（`>>> codes` 和 `>>> name_map`）
   419|   - **测试代码注释缩进修复**：`# 测试 8` 移到正确位置
   420|   - **测试清理逻辑补全**：`finally` 块新增日志处理器关闭和移除
   421|   - **logger 类型验证测试**：新增 logger 参数类型错误测试
   422|   - **版本历史补全**：stock_utils.py 新增 v1.7 版本演进说明
   423|   - **修复原因**：代码bug（缓存函数 None 未检查、测试代码缩进错误）+ 规范遗漏（logger 参数类型未验证、docstring Example 格式不规范）
   424|
   425|8. **stock_utils.py v1.8 (2026-05-25)** — 第八轮深度优化
   426|   - **filter_stocks_by_date Note 补充**：补充 Note 章节"自动过滤非字典元素和日期字段为空的元素"，与其他辅助函数保持一致
   427|   - **测试清理顺序修复**：先打印"测试清理完成"再关闭处理器（避免日志丢失）
   428|   - **http_client.py 同步更新**：get_module_logger 新增类型验证（与 stock_utils.py 保持一致）
   429|   - **版本历史补全**：stock_utils.py 新增 v1.8 版本演进说明，http_client.py 新增 v1.5 版本演进说明
   430|   - **修复原因**：代码bug（测试清理顺序导致日志丢失）+ 规范遗漏（filter_stocks_by_date 缺少 Note、http_client.py get_module_logger 未同步）
   431|
   432|9. **stock_utils.py v1.9 (2026-05-25)** — 第九轮深度优化
   433|   - **导入顺序 PEP 8 合规化**：标准库导入按字母顺序排列（json, logging, re, threading）
   434|   - **MAX_STOCK_DATE Note 补充**：补充 Note 章节"动态获取当前日期，长时间运行程序不会过期"
   435|   - **load_main_board_stock_list Raises 补全**：补充 RuntimeError（缓存函数未初始化）和 TypeError（logger 参数类型错误）
   436|   - **load_main_board_stock_list Note 补充**：补充 Note 章节"自动使用缓存路径、空股票列表返回空列表并打印警告"
   437|   - **版本历史补全**：stock_utils.py 新增 v1.9 版本演进说明
   438|   - **修复原因**：规范遗漏（导入顺序不规范、MAX_STOCK_DATE 缺少 Note、load_main_board_stock_list Raises 不完整）
   439|
   440|10. **stock_utils.py v1.10 (2026-05-25)** — 第十轮深度优化
   441|   - **is_main_board_stock docstring 中文逗号修复**：`),必须` → `），必须`（与其他 docstring 保持一致）
   442|   - **辅助函数 Raises 精确化**：移除"元素不是字典类型"描述（实际是过滤而非抛异常）
   443|   - **_get_imported_functions() 调用合并**：load_main_board_stock_list 统一在函数开头初始化（避免重复调用）
   444|   - **load_main_board_stock_list 非字典元素统计补全**：新增 invalid_elements 统计 + WARNING 日志（与其他辅助函数保持一致）
   445|   - **版本历史补全**：stock_utils.py 新增 v1.10 版本演进说明
   446|   - **修复原因**：代码bug（重复调用效率低、非字典元素统计缺失）+ 规范遗漏（docstring 格式不规范、Raises 描述不精确）
   447|
   448|11. **stock_utils.py v2.0 (2026-05-25)** — 第十一轮深度优化（重大重构）
   449|   - **DCL模式简化**：移除 `_get_imported_functions()` 双重检查锁定模式，改为模块级条件导入（if __name__ == '__main__'）
   450|   - **MAX_STOCK_DATE 命名改为 get_max_stock_date**：遵循最小惊讶原则（函数命名以 get_ 开头），保留 MAX_STOCK_DATE 别名向后兼容
   451|   - **get_stock_codes_only 空代码统计修复**：改用直接计数 empty_codes（而非减法计算 total_count - valid_count - invalid_elements）
   452|   - **filter_stocks_by_date date_value 格式验证补全**：新增 `_DATE_PATTERN.match(date_value)` 检查 + invalid_dates 统计 + WARNING 日志
   453|   - **移除 threading 导入**：不再需要线程锁保护
   454|   - **__all__ 导出更新**：新增 `get_max_stock_date`，保留 `MAX_STOCK_DATE` 别名（deprecated）
   455|   - **版本历史补全**：stock_utils.py 新增 v2.0 版本演进说明
   456|   - **修复原因**：代码bug（DCL模式复杂、空代码统计逻辑混乱、date_value 缺少格式验证）+ 规范遗漏（MAX_STOCK_DATE 命名违反最小惊讶原则）
   457|
   458|12. **stock_utils.py v2.1 (2026-05-25)** — 第十二轮深度优化
   459|   - **excluded_count 统计精确化**：只包含非主板股票（不含非字典元素），避免重复统计
   460|   - **日期合法性验证**：新增 `_validate_date()` 函数使用 `datetime.strptime` 验证日历合法性（如 2020-13-01 或 2020-02-30）
   461|   - **双重验证机制**：先正则验证格式（YYYY-MM-DD 必须为2位月份/日期），再 datetime.strptime 验证日历合法性
   462|   - **finally 块迭代安全**：先复制 `test_logger.handlers` 列表，避免迭代中修改列表的经典 Bug
   463|   - **前缀长度预期注释**：补充各前缀精确长度预期（30为2字符、688为3字符、8/4为1字符）+ 覆盖盲区说明
   464|   - **版本历史补全**：stock_utils.py 新增 v2.1 版本演进说明
   465|   - **修复原因**：代码bug（excluded_count 统计含义模糊、datetime.strptime 接受单数字月份/日期、finally迭代Bug）+ 规范遗漏（前缀长度预期注释缺失）
   466|
   467|13. **factor_generator.py v1.1 (2026-05-25)** — 第一轮公共模块规范化
   468|   - **logger 参数化**：`generate_all_factors` 参数 `verbose: bool` → `logger: Optional[logging.Logger]`
   469|   - **新增 get_module_logger**：遵循 PROJECT.md 公共模块日志规范
   470|   - **新增 __all__ 导出**：导出 `generate_all_factors` + `get_module_logger`
   471|   - **类型注解精确化**：`Optional[Path]` → `Optional[Union[Path, str]]`，返回值 `Dict` → `Dict[str, Any]`
   472|   - **移除 sys.path.insert**：改用标准导入方式（函数内导入因子计算函数）
   473|   - **异常处理补全**：文件加载 + JSON 解析 + 原子写入
   474|   - **原子写入**：使用临时文件 + `os.replace` 遵循 PROJECT.md 文件写入规范
   475|   - **CLI 日志规范化**：使用 `setup_logger` + try/finally 资源清理
   476|   - **docstring 补全**：Args/Returns/Raises/Note/Example 全部补齐
   477|   - **__init__.py 导出**：新增模块级导出
   478|   - **修复原因**：代码bug（print vs logger、sys.path.insert、缺少异常处理）+ 规范遗漏（缺少 __all__、logger 参数、docstring Raises）
   479|
   480|14. **factor_generator.py v1.3 (2026-05-25)** — 第二轮深度优化
   481|   - **常量命名私有化**：`DEFAULT_CACHE_DIR` → `_DEFAULT_CACHE_DIR`（遵循 cache_manager.py 私有常量规范）
   482|   - **导入顺序 PEP 8 合规化**：标准库按字母顺序（gzip, json, logging, os）+ 第三方库分隔
   483|   - **导入位置规范化**：函数内导入因子计算函数移到文件顶部（遵循 PROJECT.md 第401-418行规范）
   484|   - **版本历史补全**：factor_generator.py 新增 v1.3 版本演进说明
   485|   - **修复原因**：规范遗漏（常量命名不规范、导入顺序不规范、导入位置违反规范）
   486|
   487|15. **factor_generator.py v1.4 (2026-05-25)** — 第三轮深度优化
   488|   - **流程文档创建**：`docs/factor_generator_flow.md`（整体架构 + 8步流程 + 输出结构 + 版本历史）
   489|   - **测试用例创建**：`test_cases/factor_generator_test_cases.md`（10项正常测试 + 3项异常测试）
   490|   - **output_cols 注释补全**：索引含义说明（0:6=基础OHLCV，6:8=基础因子，8:=扩展因子）
   491|   - **valid_records_percent 补全**：新增百分比统计字段（与日志输出保持一致）
   492|   - **MODULE.md 版本历史更新**：新增 v2.28 版本记录
   493|   - **修复原因**：规范遗漏（流程文档缺失、测试用例缺失、输出注释缺失、返回值统计不完整）
   494|
   495|16. **factor_generator.py v1.5 (2026-05-25)** — 第四轮深度优化
   496|   - **条件导入合并简化**：移除 __main__ 测试重复 sys.path.insert（减少8行代码）
   497|   - **异常处理精确化**：区分 OSError/PermissionError/IOError（遵循 patterns.md）
   498|   - **metadata 字段注释补全**：generated_at、elapsed_seconds、valid_records_percent 等8字段含义
   499|   - **修复原因**：代码冗余（sys.path.insert 重复）、异常处理宽泛、返回值注释缺失
   500|
   501|   501|17. **factor_generator.py v1.6 (2026-05-25)** — 第五轮深度优化
   502|   - **JSONDecodeError 内存优化**：提取 lineno/colno/msg 信息，避免 e.doc 内存翻倍（遵循 patterns.md）
   503|   - **CLI 入口规范**：main() 返回退出码（0成功/1失败），而非 metadata
   504|   - **__main__ 测试补全**：required_fields 新增 valid_records_percent 字段验证
   505|   - **条件导入合并简化**：移除 CLI 入口块重复 sys.path.insert（减少6行代码）
   506|   - **修复原因**：内存优化遗漏、CLI 规范缺失、测试覆盖不完整、代码冗余
   507|
   508|18. **factor_generator.py v1.7 (2026-05-25)** — 第六轮深度优化
   509|   - **注释行号修正**：setup_logger 导入位置改为第364-367行（原注释说第333-341行）
   510|   - **docstring RuntimeError 补全**：文件系统错误异常说明（第297-306行会抛出）
   511|   - **main() 返回类型注解**：添加 `-> int`（符合 CLI 入口规范）
   512|   - **修复原因**：注释不一致、docstring Raises 缺失、类型注解缺失
   513|
   514|19. **factor_generator.py v1.8 (2026-05-25)** — 第七轮深度优化
   515|   - **gzip.BadGzipFile 异常处理补全**：gzip 文件损坏错误处理（第177-179行、208-210行）
   516|   - **docstring ValueError 补全**：补充 gzip 文件损坏异常说明
   517|   - **注释行号修正**：sys.path.insert 位置改为第42-53行（删除1行后位置变化）
   518|   - **修复原因**：gzip 异常处理缺失、注释行号不准确
   519|
   520|21. **fetch_stock_list.py v2.0 (2026-05-27)** — 公共模块规范化
   521|   - **输出目录迁移**：cache → result（遵循 MODULE.md 约束 2）
   522|   - **日志规范化**：复用 logger_config.py 的 setup_logger（遵循 PROJECT.md 第561-700行）
   523|   - **日志文件命名**：`stock_cache.log` → `fetch_stock_list_YYYY-MM-DD.log`
   524|   - **日志格式**：添加 `%(name)s` 字段
   525|   - **CLI 日志规范化**：print → logger（遵循 PROJECT.md 第780-839行）
   526|   - **类型注解补全**：所有公共函数添加完整类型注解
   527|   - **__all__ 导出**：明确定义 5 个公共 API
   528|   - **版本号常量提取**：`_OUTPUT_VERSION = '2.2'`（遵循 MODULE.md 约束 16）
   529|   - **datetime.now() 统一调用**：只调用一次，派生两个格式（遵循 MODULE.md 约束 17）
   530|   - **Path 对象迁移**：os.path → Path
   531|   - **公共模块复用**：logger_config.py、http_client.py、paths.py
   532|   - **原子写入**：使用临时文件 + replace
   533|   - **流程文档创建**：docs/fetch_stock_list_flow.md
   534|   - **测试用例创建**：test_cases/fetch_stock_list_test_cases.md
   535|   - **修复原因**：MODULE.md 规范违规（8项）+ PROJECT.md 规范违规（4项）
   536|
   537|22. **fetch_stock_list.py v2.1 (2026-05-27 06:35)** — 第二轮优化
   538|   - **requests 导入顶部化**：从 `__main__` 内移动到模块顶部（遵循 MODULE.md 约束 51）
   539|   - **原子写入异常捕获扩大**：OSError → Exception（遵循 MODULE.md 约束 55）
   540|   - **validate_cache logger 参数化**：新增 `logger_arg` 参数（遵循 PROJECT.md 日志参数规范）
   541|   - **set 类型注解完整化**：`set` → `set[str]`
   542|   - **ensure_cache_dir/ensure_result_dir logger 参数化**：新增 `logger_arg` 参数
   543|   - **修复原因**：深度审查发现 6 项遗漏问题
   544|
   545|23. **fetch_stock_list.py v2.2 (2026-05-27 06:50)** — 第三轮优化
   546|   - **导入顺序修正**：requests 移至标准库之后（遵循 PEP 8：标准库 → 第三方 → 本地）
   547|   - **ensure_cache_dir/ensure_result_dir 调用时传递 logger**：遵循 MODULE.md 约束 33（函数签名与调用一致）
   548|   - **修复原因**：导入顺序违规、调用方参数遗漏
   549|
   550|24. **fetch_stock_list.py v2.3 (2026-05-27 07:05)** — 第四轮优化
   551|   - **load_cache 异常捕获扩大**：`json.JSONDecodeError` → `Exception`（遵循 MODULE.md 约束 55）
   552|   - **潜在风险覆盖**：PermissionError、IsADirectoryError、OSError 等文件读取异常
   553|   - **修复原因**：异常捕获范围过小，文件读取可能抛出多种异常
   554|
   555|25. **fetch_stock_list.py v2.4 (2026-05-27 07:30)** — 第五轮深度修复
   556|   - **logger参数遮蔽修复**：`logger` → `logger_arg`（统一4个函数签名：fetch_stocks_from_sina、save_cache、load_cache、refresh_stock_cache）
   557|   - **session资源泄漏修复**：使用 `with create_sina_session(logger=_logger) as session:` 确保连接池释放
   558|   - **load_cache日志参数补充**：添加 `logger_arg` 参数，save_cache 调用时传递 `_logger`
   559|   - **ST股票误判修复**：substring 匹配 (`'ST' in name`) → 前缀匹配 (`startswith('ST')`)，避免"东ST"正常股票被误判
   560|   - **修复原因**：代码bug（4项）+ 规范缺失（MODULE.md 新增约束77/78/79）
   561|
   562|26. **fetch_stock_list.py v2.5 (2026-05-27 08:00)** — 第六轮深度修复
   563|   - **重试逻辑修复**：最后一次重试失败时直接 raise（删除无效 continue），避免异常被吞掉
   564|   - **validate_cache参数修复**：删除冗余 `logger_arg` 参数（函数内部未使用）
   565|   - **_write_json_file临时文件修复**：使用 `tempfile.NamedTemporaryFile` 避免多进程并发冲突
   566|   - **增量更新name字段修复**：同步更新已存在股票的最新名称（股票改名后 name 字段需更新）
   567|   - **data变量类型守卫**：添加 `if data is None: raise RuntimeError` 确保类型安全
   568|   - **修复原因**：代码bug（5项）+ 规范缺失（MODULE.md 新增约束80/81/82）
   569|
   570|27. **fetch_stock_list.py v2.6 (2026-05-27 08:30)** — 第七轮深度修复
   571|   - **_write_json_file参数名修复**：`logger` → `logger_arg`（遵循 PROJECT.md 日志参数规范）
   572|   - **validate_cache ST检查修复**：使用前缀匹配（`startswith('S')` 或 `startswith('ST')`），与 is_valid_main_board_stock 逻辑一致
   573|   - **is_valid_main_board_stock ST顺序修复**：先剔除 S 开头（含 SST、S*ST），再剔除 *ST 和 ST，避免逻辑混乱
   574|   - **重试逻辑简化**：删除 success 变量，循环内直接控制流（成功 break，失败在最后一次重试 raise）
   575|   - **修复原因**：代码bug（4项）+ 规范缺失（MODULE.md 新增约束83/84）
   576|
   577|28. **fetch_stock_list.py v2.7 (2026-05-27 09:00)** — 第八轮深度修复
   578|   - **data类型守卫增强**：添加 `assert isinstance(data, list)` 确保类型安全（比单独检查 None 更严格）
   579|   - **existing_stock_map注释说明**：明确引用修改预期行为（修改 existing_stock['name'] 会直接更新 existing_stocks）
   580|   - **removed_codes截断**：限制最多50个，添加 `removed_codes_truncated` 字段避免 JSON 文件过大
   581|   - **result初始化补全**：添加 `updated_count: 0` 避免字段缺失
   582|   - **CLI日志补全**：添加 updated_count 输出（仅当有更新时显示 `if updated_count > 0`）
   583|   - **修复原因**：代码bug（5项）+ 规范缺失（MODULE.md 新增约束85/86）
   584|
   585|29. **fetch_stock_list.py v2.8 (2026-05-27 09:30)** — 第九轮深度修复
   586|   - **ST前缀提取为模块级常量**：添加 `ST_PREFIXES` 常量便于维护（遵循 MODULE.md 约束 16）
   587|   - **fetch_stocks_from_sina doctest修复**：改为合法格式 `len(stocks) > 2500` → `True`
   588|   - **get_cached_stock_codes doctest修复**：改为合法格式 `len(codes) > 2500` → `True`
   589|   - **修复原因**：代码bug（3项）
   590|
   591|30. **fetch_turnover.py v2.0 (2026-05-27 10:00)** — 第一轮基础优化
   592|   - **导入顺序 PEP 8 规范化**：标准库 → 第三方库 → 本地模块（sys、logging 补充）
   593|   - **版本号提取为常量**：`_OUTPUT_VERSION = '2.0'` 便于维护（遵循 MODULE.md 约束 16）
   594|   - **datetime.now() 统一调用**：模块级 `_NOW`、`_NOW_ISO`、`_NOW_STR`（遵循 MODULE.md 约束 17）
   595|   - **session 资源管理**：使用 `with requests.Session() as session` 确保释放（遵循 MODULE.md 约束 78）
   596|   - **ST 检测前缀匹配**：`startswith(prefix)` 避免"东ST"误判（遵循 MODULE.md 约束 79）
   597|   - **修复原因**：代码bug（5项）
   598|
   599|31. **fetch_turnover.py v2.1 (2026-05-27 10:30)** — 第二轮深度优化
   600|   - **logger 参数化**：所有公共函数添加 `logger_arg` 参数（遵循 MODULE.md 约束 77）
   601|     - fetch_turnover_rate_eastmoney、load_cache、save_cache、main、fetch_turnover_rate_baostock
   602|   - **tempfile 使用**：save_cache 使用 `tempfile.NamedTemporaryFile` 避免并发冲突（遵循 MODULE.md 约束 80）
   603|   - **print → logger 迁移**：52处全部迁移为 logger.info/debug/error/warning
   604|   - **load_data_fetchers/result/save_cache logger 参数传递**：调用方传递 `_logger`（遵循 PROJECT.md 日志规范）
   605|   - **修复原因**：代码bug（6项）
   606|
   607|32. **fetch_turnover.py v2.2 (2026-05-27 11:00)** — 第三轮补充优化
   608|   - **ST_PREFIXES 常量提取**：模块级常量便于维护（遵循 MODULE.md 约束 16）
   609|   - **load_stock_list ST 检测修复**：前缀匹配 + 逻辑修正（`break + continue` 避免 continue 误用）
   610|   - **__all__ 导出列表**：添加公共函数导出列表（遵循 MODULE.md 约束 53）
   611|   - **__main__ logger 设置**：`logging.basicConfig` + `cli_logger`（遵循 PROJECT.md 日志规范）
   612|   - **CLI 参数简化**：`--baostock` 替代 `--source` 选择（更简洁）
   613|
   614|33. **测试规范迁移 (2026-05-27 12:00)** — pytest 测试框架迁移
   615|   - **PROJECT.md 测试规范更新**：测试用例从 `.md` 文档改为 pytest 可执行文件（`.py`）
   616|   - **MODULE.md 目录结构更新**：test_cases/ 从 `<脚本名>_test_cases.md` 改为 `test_<脚本名>.py`
   617|   - **MODULE.md 版本更新**：v3.01 → v3.02
   618|   - **cache_manager.py __main__ 块删除**：禁止脚本内嵌测试代码（遵循 PROJECT.md 新规范）
   619|   - **pytest 测试文件创建**：`test_cases/test_cache_manager.py`（从 __main__ 块转换）
   620|   - **cache_manager_test_cases.md 删除**：不再需要 .md 测试场景文档
   621|   - **测试命名规则**：`test_<脚本名>.py`（遵循 pytest 约定）
   622|   - **修复原因**：规范缺失（PROJECT.md 缺少 pytest 规范、MODULE.md 目录结构不规范、__main__ 块测试代码无法自动运行）
   623|
   624|34. **batch_processor.py v1.0 (2026-05-27 14:30)** — 公共模块规范化
   625|   - **文件头版本历史**：添加 v1.0 初始版本说明
   626|   - **logger 参数命名**：`logger` → `logger_arg`（遵循 MODULE.md 约束 77）
   627|   - **cleanup_batch_files 异常日志**：添加 `[{type(e).__name__}]: {e}`（遵循 MODULE.md 约束 50）
   628|   - **docstring Example 章节**：4个公共函数添加使用示例
   629|   - **docstring Raises 章节**：4个公共函数添加异常说明
   630|   - **导入顺序验证**：符合 PEP 8（标准库→第三方库→本地模块）
   631|   - **流程文档创建**：`docs/batch_processor_flow.md`（遵循 MODULE.md 约束 8）
   632|   - **pytest 测试文件**：`test_cases/test_batch_processor.py`（16个测试用例）
   633|   - **MODULE.md 版本更新**：v3.02 → v3.03
   634|   - **修复原因**：规范缺失（8项）
   635|
   636|35. **batch_processor.py v1.1 (2026-05-27 15:00)** — 第二轮深度优化
   637|   - **BatchStream 类 docstring**：添加 Example/Raises 章节（公共类规范化）
   638|   - **`_write_json_record` 类型注解**：`Any` → `TextIO`（更精确的类型）
   639|   - **修复原因**：类型注解不精确、公共类 docstring 不完整（2项）
   640|
   641|36. **batch_processor.py v1.2 (2026-05-27 15:30)** — 第三轮深度优化
   642|   - **函数签名类型注解完整化**：`Path = None` → `Path | None = None`（4个公共函数）
   643|   - **logger_arg 类型注解**：`logging.Logger = None` → `logging.Logger | None = None`
   644|   - **`self.records` 类型注解**：`list` → `list[dict]`（更精确）
   645|   - **format_final_output 入口处统一转换**：`Path(xxx).unlink()` → 入口处统一转换为 Path
   646|   - **异常处理日志**：`except json.JSONDecodeError: continue` → 添加 debug 日志
   647|   - **修复原因**：类型注解不完整、静默 fallback、冗余转换（4项）
   648|
   649|37. **batch_processor.py v1.3 (2026-05-27 16:00)** — 第四轮深度优化
   650|   - **新增模块级常量 `_DATA_TYPES`**：避免硬编码 `['factor', 'return']`（2处使用）
   651|   - **`_write_json_record` 添加 Example**：内部函数补充使用示例
   652|   - **删除冗余赋值**：`date_start = first_date` → 直接使用 `first_date`（代码简洁）
   653|   - **`cleanup_batch_files` 使用常量**：`for t in [...]` → `for data_type in _DATA_TYPES`
   654|   - **修复原因**：硬编码重复、冗余赋值、内部函数文档不完整（4项）
   655|
   656|33. **fetch_turnover.py v2.3 (2026-05-27 11:30)** — 第四轮补充优化
   657|   - **get_cached_turnover_codes 函数**：创建公共函数（__all__ 中已声明，补充实现）
   658|   - **类型注解完整性**：`Set[str]` 返回类型 + `logger_arg` 参数
   659|   - **函数文档字符串**：添加 Args/Returns/Example 说明
   660|   - **修复原因**：规范补充（1项）
   661|
   662|34. **fetch_turnover.py v2.4 (2026-05-27 12:00)** — 第五轮深度修复
   663|   - **fetch_turnover_rate_baostock 时间统计修复**：单独维护 `processed_count`/`skipped_count`（遵循 MODULE.md 约束 87）
   664|     - 跳过已有股票不计入处理统计
   665|     - 平均时间使用实际处理数量计算：`avg_time = elapsed / processed_count`
   666|   - **merge_records 空数据处理修复**：`new_records=[]` 时保留 `existing_data` 的 meta（遵循 MODULE.md 约束 88）
   667|     - 避免 `generated_at`、`last_updated` 被强制更新
   668|     - 避免 `source` 被强制改为 'mixed'
   669|   - **merge_records source 保留**：保留原始 source（遵循 MODULE.md 约束 88）
   670|   - **merge_records logger 参数**：添加 `logger_arg` 参数 + 调用方传递
   671|   - **修复原因**：代码bug（3项）
   672|
   673||| 87 | 处理进度统计准确 | 使用实际处理数量计算平均时间（processed_count），跳过项不计入统计 |
   674||| 88 | 空数据合并保护 | new_records=[] 时保留 existing_data 的 meta，避免强制覆盖 |
   675||| 89 | ST前缀元组用法 | ST_PREFIXES 使用元组直接传给 startswith，避免循环遍历 |
   676||| 90 | API异常边界处理 | total_pages=0 时添加警告日志，提示可能无数据或API异常 |
   677||| 91 | 长期运行时间偏差 | end_date 使用 datetime.now() 避免模块级 _NOW 偏差 |
   678|
   679|35. **fetch_turnover.py v2.5 (2026-05-27 12:30)** — 第六轮深度修复
   680|35. **fetch_turnover.py v2.5 (2026-05-27 12:30)** — 第六轮深度修复
   681|   - **ST_PREFIXES 元组优化**：改为元组直接传给 startswith（遵循 MODULE.md 约束 89）
   682|   - **ST_PREFIXES 优先级语义**：`*ST` 排在最前（退市风险优先检测）
   683|   - **total_pages=0 边界处理**：添加警告日志（遵循 MODULE.md 约束 90）
   684|   - **fetch_stock_history_baostock 返回类型**：实际与标注一致（无问题）
   685|   - **_NOW 模块级时间戳偏差**：end_date 使用 `datetime.now()`（遵循 MODULE.md 约束 91）
   686||| 91 | 长期运行时间偏差 | end_date 使用 datetime.now() 避免模块级 _NOW 偏差 |
   687||| 92 | 时间估算准确 | remaining 基于实际待处理数（total - skipped_count - processed_count） |
   688||| 93 | 数据源合并语义 | merge_records 添加 source 参数，existing_meta.source != source 时设为 'mixed' |
   689|
   690|36. **fetch_turnover.py v2.6 (2026-05-27 13:00)** — 第七轮深度修复
   691|   - **get_cached_turnover_codes 文档示例**：改为 `isinstance(codes, set)` → True（确定结果）
   692|     - 避免 `len(codes) > 2500` 结果不确定（依赖实际数据量）
   693|   - **load_cache _logger 赋值**：统一为 `logger_arg or logger`（遵循 MODULE.md 约束 77）
   694|     - 消除冗余的 `logging.getLogger(__name__)` 重复调用
   695||| 93 | 数据源合并语义 | merge_records 添加 source 参数，existing_meta.source != source 时设为 'mixed' |
   696||| 94 | 跳过日志粒度直观 | 跳过股票日志基于 skipped_count % 100（而非 idx % 100） |
   697|
   698|37. **fetch_turnover.py v2.7 (2026-05-27 13:30)** — 第八轮深度修复
   699|   - **fetch_turnover_rate_baostock 时间估算逻辑**：remaining 基于实际待处理数（遵循 MODULE.md 约束 92）
   700|   - **merge_records source 参数**：添加 source 参数 + 调用方传入数据源（遵循 MODULE.md 约束 93）
   701|   - **merge_records 数据源合并逻辑**：`existing_meta.source != source` 时设为 `'mixed'`
   702||| 94 | 跳过日志粒度直观 | 跳过股票日志基于 skipped_count % 100（而非 idx % 100） |
   703||| 95 | pages=0提前退出 | total_pages=0 时添加 break 提前退出循环 |
   704|
   705|38. **fetch_turnover.py v2.8 (2026-05-27 14:00)** — 第九轮深度修复
   706|   - **get_cached_turnover_codes doctest**：已修复为 `isinstance(codes, set)`（Round 17）
   707|   - **save_cache _logger 初始化**：统一为 `logger_arg or logger`（遵循 MODULE.md 约束 77）
   708|     - 与 load_cache 保持一致，消除冗余 `logging.getLogger(__name__)`
   709|   - **fetch_turnover_rate_baostock 跳过日志粒度**：基于 `skipped_count % 100`（遵循 MODULE.md 约束 94）
   710||| 95 | pages=0提前退出 | total_pages=0 时添加 break 提前退出循环 |
   711||| 96 | tempfile同块写入 | 在同一个 with 块内传文件对象给 gzip.open，不关闭再开 |
   712|
   713|39. **fetch_turnover.py v2.9 (2026-05-27 14:30)** — 第十轮深度修复
   714|   - **fetch_turnover_rate_eastmoney total_pages=0**：添加 break 提前退出（遵循 MODULE.md 约束 95）
   715|   - **INTERMEDIATE_SAVE_INTERVAL 常量**：删除未使用的冗余常量
   716|   - **修复原因**：代码bug（2项）
   717|
   718|40. **fetch_turnover.py v2.10 (2026-05-27 15:00)** — 第十一轮深度修复
   719|   - **save_cache tempfile 修复**：在同一个 with 块内直接传文件对象给 gzip.open（遵循 MODULE.md 约束 96）
   720|     - 原逻辑：先关闭临时文件，再重新打开写入（多余步骤）
   721|     - 新逻辑：传文件对象给 gzip.open，不关闭再开
   722|     - 删除 `mode='wb'` 参数（gzip.open 会处理文件模式）
   723|   - **修复原因**：代码bug（1项）
   724|
   725|20. **factor_generator.py v1.9 (2026-05-25)** — 第八轮深度优化
   726|   - **冗余导入清理**：移除条件导入块的 `_Path`（第44行），直接使用顶部导入的 `Path`
   727|   - **注释行号修正**：setup_logger 导入位置改为第369-374行（删除1行后位置变化）
   728|   - **修复原因**：冗余导入、注释行号不准确
   729|
   730|21. **factor_generator.py v1.10 (2026-05-25)** — 第九轮深度优化
   731|   - **gzip 导入合并**：移除 `from gzip import BadGzipFile`，改用 `gzip.BadGzipFile`（符合 PEP 8 导入规范）
   732|   - **main() 函数内冗余导入清理**：移除 `import logging`（使用模块级导入）
   733|   - **修复原因**：导入冗余
   734|
   735|22. **factor_generator.py v1.11 (2026-05-25)** — Bug修复
   736|   - **条件导入合并**：将 setup_logger 导入合并到顶部条件块（删除中间冗余的条件导入块）
   737|   - **__main__ 循环导入修复**：删除 `from data_fetchers.factor_generator import ...`（直接使用已定义的函数）
   738|   - **PermissionError 重复捕获简化**：`except (OSError, PermissionError, IOError)` → `except OSError`（PermissionError 是 OSError 子类）
   739|   - **temp_path 后缀处理修复**：`with_suffix('.tmp')` → `parent / (name + '.tmp')`（避免替换 .gz 后缀）
   740|   - **修复原因**：代码 bug（条件导入位置错误、循环导入、异常重复捕获、临时文件名错误）
   741|
   742|23. **factor_generator.py v1.12 (2026-05-25)** — Bug修复 + 规范补充
   743|   - **output_cols 注释修正**：`output_cols[0:6] = OHLCV` → `output_cols[0:2]=date/asset, output_cols[2:6]=open/close/high/low`（非标准 OHLCV 顺序）
   744|   - **dates 排序注释补充**：说明 YYYY-MM-DD 字符串排序正确（字典序与日期序一致）
   745|   - **total_records 除零保护**：空数据时百分比返回 0.0（`calc_pct` 函数）
   746|   - **版本历史移除硬编码行号**：改为描述性注释（避免行号不准确误导）
   747|   - **argparse 版本描述修正**：v1.3 版本历史补充说明 argparse 为 CLI 入口特有导入，保留函数内导入
   748|   - **修复原因**：代码 bug（注释不符、除零风险）+ 规范遗漏（日期排序说明、日志换行符规范）
   749|
   750|24. **MODULE.md v2.45 (2026-05-25)** — 规范补充
   751|   - **日志换行符规范**：新增章节说明换行符使用场景（错误日志多行格式化允许、__main__ 测试块视觉分隔允许、一般 info 日志不建议）
   752|   - **规范补充原因**：用户发现 logger.info 中 `\n` 换行符可能产生 handler 解析问题，需明确允许/禁止场景
   753|
   754|25. **factor_generator.py v1.13 (2026-05-25)** — Bug修复
   755|   - **缩进错误修正**：Step 8 注释缩进从 0 修正为 4（脱离函数体风险）
   756|   - **numpy.int64 类型转换**：bollinger_valid/kdj_valid/surge_valid 显式转换为 int（JSON 序列化兼容）
   757|   - **__main__ 块重构**：改为 CLI 入口调用 main()，测试代码移至 test_cases/test_factor_generator.py（测试与 CLI 分离）
   758|   - **修复原因**：代码 bug（缩进格式错误、类型不匹配、__main__ 结构不合理）
   759|
   760|26. **test_cases/test_factor_generator.py (2026-05-25)** — 新增测试脚本
   761|   - **测试与 CLI 分离**：独立测试脚本，与 __main__ CLI 入口分离
   762|   - **测试内容**：函数定义验证、get_module_logger 验证、generate_all_factors 验证、返回字段验证、因子列验证、有效记录数验证
   763|
   764|27. **factor_generator.py v1.14 (2026-05-25)** — Bug修复 + 代码结构优化
   765|   - **除零保护统一**：使用模块级私有函数 `_calc_pct`，替代函数内嵌套定义
   766|   - **硬编码常量**：新增 `_EXTENDED_FACTOR_COLS` 常量替代 `output_cols[8:]` 切片
   767|   - **docstring 补充**：Raises 补充空数据异常声明，Note 补充除零保护说明
   768|   - **turnover_missing 类型**：显式 `int()` 转换
   769|   - **修复原因**：代码 bug（除零风险未统一保护、硬编码切片脆弱、函数结构混乱）
   770|
   771|28. **MODULE.md v2.47 (2026-05-25)** — 规范补充
   772|   - **除零保护规范**：模块级私有函数 `_calc_pct` 模式，避免函数内嵌套定义
   773|   - **硬编码常量规范**：扩展因子列应使用常量定义，避免切片索引脆弱性
   774|
   775|29. **factor_generator.py v1.15 (2026-05-25)** — Bug修复 + 文档修正
   776|   - **docstring 修正**：移除 `json.JSONDecodeError` 声明（已内部捕获转换为 ValueError），补充说明调用方不会收到 JSONDecodeError
   777|   - **TOCTOU 竞争窗口修复**：`temp_path.unlink(missing_ok=True)` 替代 `exists() + unlink()`，消除 Time-of-check-to-time-of-use 竞争
   778|   - **修复原因**：代码 bug（文档不准确、并发安全风险）
   779|
   780|30. **MODULE.md v2.48 (2026-05-25)** — 规范补充
   781|   - **临时文件清理规范**：`unlink(missing_ok=True)` 原子操作，避免 TOCTOU 竞争窗口
   782|   - **docstring Raises 规范**：声明异常应与实际抛出一致，已捕获转换的异常不应声明
   783|
   784|31. **factor_generator.py v1.16 (2026-05-25)** — 代码结构优化
   785|   - **常量统一**：新增 `_BASE_COLS` 和 `_OUTPUT_COLS` 常量，output_cols 使用 `_OUTPUT_COLS` 引用（消除维护隐患）
   786|   - **sys 重复导入**：移除 __main__ 块中 sys 重复导入（顶部条件块已导入）
   787|   - **_calc_pct 语义**：修正为通用百分比计算函数（参数名 count/total，docstring 补充通用语义说明）
   788|   - **修复原因**：代码结构问题（常量关系不清晰、重复导入、函数语义不准确）
   789|
   790|32. **MODULE.md v2.49 (2026-05-25)** — 规范补充
   791|   - **常量引用关系规范**：相关常量应建立引用关系，避免各自硬编码导致维护遗漏
   792|   - **条件块导入规范**：顶部条件块已导入的模块，__main__ 块无需重复导入
   793|
   794|33. **factor_generator.py v1.17 (2026-05-25)** — Bug修复 + 文档优化
   795|   - **父目录创建**：`output_path.parent.mkdir(parents=True, exist_ok=True)`（避免 FileNotFoundError）
   796|   - **dates 字段来源**：从 `output_df['date']` 取（数据来源更清晰）
   797|   - **docstring 示例值**：改为范围说明（`# 实际耗时，单位秒（范围：0.0 ~ 数百秒，取决于数据量）`）
   798|   - **修复原因**：代码 bug（目录不存在风险）+ 文档问题（示例值过于具体）
   799|
   800|34. **MODULE.md v2.50 (2026-05-25)** — 规范补充
   801|   - **输出目录创建规范**：写入前确保父目录存在，`mkdir(parents=True, exist_ok=True)`
   802|   - **docstring 示例规范**：避免过于具体的示例值，改为范围说明或注释
   803|
   804|35. **factor_generator.py v1.18 (2026-05-25)** — Bug修复
   805|   - **版本历史描述修正**：v1.12 "logger换行符修复" 改为 "MODULE.md日志换行符规范补充"（错误日志允许多行格式化，符合规范）
   806|   - **可变对象返回副本**：`list(_EXTENDED_FACTOR_COLS)` 防止外部修改模块内部状态
   807|   - **修复原因**：版本历史描述不准确 + 可变对象引用风险
   808|
   809|36. **factor_generator.py v1.19 (2026-05-25)** — 代码结构优化
   810|   - **常量改为元组**：`_EXTENDED_FACTOR_COLS: tuple`、`_BASE_COLS: tuple`、`_OUTPUT_COLS: tuple`（防止意外修改）
   811|   - **docstring 示例补充注释**：`# 返回列表副本`（说明实际返回类型）
   812|   - **内存释放**：`del factor_df`（显式释放中间列内存）
   813|   - **优化原因**：代码结构优化（元组防止修改 + 内存管理）
   814|
   815|37. **MODULE.md v2.52 (2026-05-25)** — 规范补充
   816|   - **常量类型规范**：模块级常量列表应使用元组防止意外修改
   817|   - **内存释放规范**：大 DataFrame 使用完毕后显式释放（`del df`）
   818|
   819|38. **factor_generator.py v1.20 (2026-05-25)** — 代码结构优化
   820|   - **mkdir 位置调整**：移入 try 块统一异常处理（与原子写入语义一致）
   821|   - **注释位置优化**：_OUTPUT_COLS 索引切片说明移到常量定义处（注释与定义不分离）
   822|   - **docstring 补充示例**：_calc_pct 补充参数含义示例（count/total 语义清晰）
   823|   - **异常日志改进**：main() 增加 `type(e).__name__`（异常类型可追溯）
   824|   - **优化原因**：代码结构问题（异常处理不一致 + 注释分离 + 参数语义模糊 + 日志信息不足）
   825|
   826|39. **MODULE.md v2.53 (2026-05-25)** — 规范补充
   827|   - **mkdir 位置规范**：应在 try 块内创建目录，异常时可统一处理
   828|   - **常量注释规范**：常量结构说明应放在定义处，而非使用处
   829|   - **异常日志规范**：应包含异常类型名（`type(e).__name__`）便于追溯
   830|
   831|40. **factor_generator.py v1.21 (2026-05-25)** — Bug修复
   832|   - **docstring Example 格式修正**：注释放在 `>>>` 行而非返回值行、增加 `isinstance` 示例
   833|   - **修复原因**：docstring 格式不规范（注释位置错误 + 缺少类型验证示例）
   834|
   835|41. **MODULE.md v2.54 (2026-05-25)** — 规范补充
   836|   - **docstring Example 格式规范**：注释放在 `>>>` 行，返回值行无注释
   837|
   838|42. **factor_generator.py v1.22 (2026-05-25)** — 代码结构优化
   839|   - **冗余别名清理**：`output_cols = _OUTPUT_COLS` 改为直接使用 `_OUTPUT_COLS`
   840|   - **职责分离**：mkdir 单独 try 块处理（异常信息更精确）
   841|   - **内存释放**：`del base_data`、`del turnover_data`（JSON 加载的大对象）
   842|   - **错误信息改进**：missing_cols 增加 `_EXTENDED_FACTOR_COLS` 提示（排错路径更短）
   843|   - **优化原因**：代码结构问题（冗余别名 + 职责混乱 + 内存泄漏 + 错误信息模糊）
   844|
   845|43. **MODULE.md v2.55 (2026-05-25)** — 规范补充
   846|   - **冗余别名规范**：直接使用常量，无需局部别名
   847|   - **职责分离规范**：mkdir 单独处理，与文件写入异常分离
   848|   - **错误信息规范**：增加上下文提示，缩短排错路径
   849|
   850|44. **factor_generator.py v1.23 (2026-05-26)** — 代码结构优化
   851|   - **类型注解改进**：`tuple` → `tuple[str, ...]`（更精确表达字符串元组）
   852|   - **优化原因**：类型注解不够精确（Python 3.9+ 支持泛型元组）
   853|
   854|45. **MODULE.md v2.56 (2026-05-26)** — 规范补充
   855|   - **tuple 类型注解规范**：使用 `tuple[str, ...]` 表达字符串元组，而非 `tuple`
   856|
   857|46. **factor_generator.py v1.24 (2026-05-26)** — Bug修复 + 代码结构优化
   858|   - **内存释放**：`del turnover_df`（merge 完成后不再需要）
   859|   - **docstring 语义修正**：Example 标记非运行示例（需要输入数据文件）
   860|   - **pandas 兼容性**：`list(_OUTPUT_COLS)`（元组转列表，列选择需要列表）
   861|   - **修复原因**：内存泄漏 + docstring 语义问题 + pandas 元组索引兼容性
   862|
   863|47. **MODULE.md v2.57 (2026-05-26)** — 规范补充
   864|   - **DataFrame 内存释放规范**：merge 完成后立即释放（不再需要的 DataFrame）
   865|   - **docstring Example 规范**：标记非运行示例（需要外部依赖的函数）
   866|   - **pandas 列选择规范**：元组常量需转列表（`list(tuple)`）
   867|
   868|49. **factor_generator.py v1.25 (2026-05-26)** — Bug修复 + 文档修正
   869|   - **类型注解兼容性**：_calc_pct 补充兼容类型说明（int、numpy.int64、float）
   870|   - **docstring Raises修正**：删除"输入数据为空"场景（代码无对应检查）
   871|   - **兜底块异常信息**：补充 `{type(e).__name__}: {e}`
   872|
   873|50. **fetch_factor_cache.py v3.5 (2026-05-26)** — 代码结构优化（第一轮）
   874|   - **版本历史规范化**：采用标准格式（版本号 + 日期 + 描述）
   875|   - **sys.path.insert移除**：删除冗余路径配置
   876|   - **公共模块导入**：添加 setup_logger、get_logs_dir 导入
   877|   - **docstring补充**：get_memory_usage_mb、get_memory_info_str、save_batch_cache_sorted
   878|   - **流程文档创建**：docs/fetch_factor_cache_flow.md
   879|   - **测试用例创建**：test_cases/fetch_factor_cache_test_cases.md
   880|
   881|52. **factor_generator.py v1.26 (2026-05-26)** — 规范合规修复
   882|   - **输出路径修正**：从 data_fetchers/result/ 改为 data_fetchers/result/
   883|   - **输入输出分离**：输入使用 cache（数据源原始缓存），输出使用 result（遵循 MODULE.md 约束 #2）
   884|
   885|54. **MODULE.md v2.61 (2026-05-26)** — 版本更新
   886|   - **第二轮优化进度**：print → logger 迁移进行中
   887|
   888|57. **fetch_factor_cache.py v3.7 (2026-05-26)** — 代码规范化
   889|   - **导入顺序**：PEP 8 规范（标准库→第三方→本地→公共模块）
   890|   - **BatchStream 类**：完整 docstring + 类型注解（6个方法）
   891|   - **路径配置**：使用公共模块 get_cache_dir() 替代硬编码
   892|   - **类型注解**：使用 Path 对象替代 os.path.join
   893|
   894|59. **fetch_factor_cache.py v3.8 (2026-05-26)** — Path 对象规范化
   895|   - **os.path.join**：9处 → Path / 运算符
   896|   - **os.path.exists**：2处 → Path.exists()
   897|   - **os.path.getsize**：4处 → Path.stat().st_size
   898|   - **os.remove**：3处 → Path.unlink()
   899|
   900|61. **fetch_factor_cache.py v3.9 (2026-05-26)** — 类型注解完善
   901|   - **save_batch_cache_sorted**：factor_df: pd.DataFrame, return_df: pd.DataFrame
   902|   - **n_way_merge_deduplicate**：返回类型 tuple[Path | None, int]
   903|   - **fetch_batch_stocks**：loader: RealDataLoader, 返回类型 tuple[pd.DataFrame | None, pd.DataFrame | None]
   904|   - **format_final_output**：参数 Path | str, 返回类型 tuple[int, int, int]
   905|
   906|63. **fetch_factor_cache.py v3.10 (2026-05-26)** — 代码清理 + 类型修复
   907|   - **移除未使用导入**：os 模块（所有 os 调用已替换为 Path）
   908|   - **类型注解修复**：validate_final_data 返回类型 bool → tuple[bool, int, int, int]
   909|
   910|65. **fetch_factor_cache.py v3.11 (2026-05-26)** — main 函数完善
   911|   - **返回类型注解**：main 函数 -> None
   912|   - **版本号同步**：main 函数日志中的版本号 3.6 → 3.10
   913|
   914|66. **MODULE.md v2.67 (2026-05-26)** — 版本更新
   915|   - **v3.11版本记录**：main 函数完善
   916|   - **完成状态**：74处全量替换，无剩余
   917|   - **logger参数化**：6个核心函数（save_batch_cache_sorted、n_way_merge_deduplicate、fetch_batch_stocks、format_final_output、validate_final_data、cleanup_batch_files）
   918|   - **main函数日志初始化**：setup_logger + logs_dir 规范
   919|   - **docstring补充**：所有核心函数完整 Args/Returns/Note
   920|   - **约束 #2 修正**：从"输出到 cache 目录"改为"输出到 result 目录"
   921|   - **语义明确**：cache 为数据源原始缓存，result 为处理后的输出结果
   922|   - **修复原因**：docstring 描述与实际行为不符 + 错误信息不完整
   923|
   924|67. **fetch_factor_cache.py v3.12 (2026-05-26)** — Bug修复
   925|   - **format_final_output 返回值修复**：在 `del factor_records` 前保存记录数 `n_records = len(factor_records)`
   926|   - **n_way_merge_deduplicate 去重逻辑修复**：heap 元素使用 `batch_idx`（原始批次号）而非 `stream_idx`（列表索引）
   927|   - **BatchStream 类补充属性**：新增 `batch_idx` 和 `data_type` 属性，用于去重优先级判断
   928|   - **修复原因**：代码 bug（del 后变量名不存在、去重优先级错误）
   929|
   930|68. **MODULE.md v2.68 (2026-05-26)** — 规范补充
   931|   - **新增约束 #9**：N-way merge 去重使用 batch_idx
   932|   - **约束内容**：heap 元素为 `(key, batch_idx, stream)`，而非 `(key, stream_idx, stream)`
   933|   - **规范补充原因**：原有实现使用 stream_idx 导致去重优先级错误（批次缺失时索引与批次号不对应）
   934|
   935|69. **fetch_factor_cache.py v3.13 (2026-05-26)** — Bug修复（4项）
   936|   - **冗余导入删除**：fetch_batch_stocks 内 `import pandas as pd` 删除（文件顶部已导入）
   937|   - **未使用变量删除**：`merged_records = []` 定义后从未使用，删除
   938|   - **hasattr 无效检查改为列存在验证**：itertuples 的 namedtuple 字段由 DataFrame 列名决定，hasattr 对所有行结果相同，改为写入前验证列存在
   939|   - **format_final_output 内存峰值优化**：改为分阶段加载，先处理因子数据并 del，再加载收益数据
   940|
   941|70. **MODULE.md v2.69 (2026-05-26)** — 规范补充
   942|   - **新增约束 #10**：itertuples 前验证列存在（hasattr 对同一 DataFrame 无效）
   943|   - **新增约束 #11**：大文件分阶段加载（避免内存峰值）
   944|   - **规范补充原因**：代码审查发现无效防御性检查、内存峰值问题
   945|
   946|71. **fetch_factor_cache.py v3.14 (2026-05-26)** — Bug修复（5项）
   947|   - **validate_final_data 数据有效性验证**：增加 RSI 非空比例 >= 80% 检查，综合判断（天数 + 数据有效性）
   948|   - **peek_key 检查 exhausted**：`if self.exhausted or self.idx >= len(self.records)`，语义一致性
   949|   - **get_memory_usage_mb Windows 兜底**：`import resource` try-except 兜底返回 0.0
   950|   - **main docstring 删除冗余 Returns**：None 返回类型不需要 Returns 节
   951|   - **version 字段提取为常量**：`_OUTPUT_VERSION = '3.14'`，两处引用统一
   952|
   953|72. **MODULE.md v2.70 (2026-05-26)** — 规范补充
   954|   - **新增约束 #12-#16**：数据验证综合判断、peek_key 检查 exhausted、Windows 兜底、docstring 无 Returns、version 常量
   955|   - **规范补充原因**：代码审查发现验证逻辑宽松、语义不一致、跨平台兼容性缺失、版本号维护困难
   956|
   957|73. **fetch_factor_cache.py v3.15 (2026-05-26)** — Bug修复（2项）
   958|   - **n_way_merge 去重逻辑修正**：使用正值 `batch_idx`（而非负值），让高 batch_idx 后弹出，最终保留高 batch_idx 记录
   959|   - **变量名语义修正**：`stream_idx` → `batch_idx`，消除"流索引"vs"负批次号"的语义混乱
   960|
   961|74. **MODULE.md v2.71 (2026-05-26)** — 规范修正
   962|   - **约束 #9 修正**："N-way merge 去重使用正值 batch_idx"（而非"使用 batch_idx"）
   963|   - **修正原因**：负值会导致高 batch_idx 先弹出，与去重替换逻辑矛盾
   964|
   965|75. **fetch_factor_cache.py v3.16 (2026-05-26)** — Bug修复（4项）
   966|   - **main 版本号改用 _OUTPUT_VERSION**：`logger.info(f"  版本: {_OUTPUT_VERSION}")`（而非硬编码 3.10）
   967|   - **format_final_output 固定生成时间**：入口处 `generated_at = datetime.now().isoformat()`，避免两次调用不一致
   968|   - **save_batch_cache_sorted 入口 copy()**：防止修改调用方 DataFrame 引用
   969|   - **validate_final_data 均匀抽样**：`step = total_records // sample_size`，避免 `[:1000]` 取前1000条偏差
   970|
   971|76. **MODULE.md v2.72 (2026-05-26)** — 规范补充
   972|   - **新增约束 #17-#18**：datetime.now() 固定时间戳、抽样检查均匀抽样
   973|   - **约束 #6 补充说明**：包括 save_batch_cache_sorted
   974|   - **规范补充原因**：代码审查发现版本号维护困难、时间戳不一致、抽样偏差
   975|
   976|77. **fetch_factor_cache.py v3.17 (2026-05-26)** — Bug修复（4项）
   977|   - **_OUTPUT_VERSION 移到 import 之后**：遵循 PEP 8 模块级代码顺序规范
   978|   - **pop_record 检查 exhausted**：与 peek_key 对称，避免 exhausted=True 时仍返回数据
   979|   - **sys 导入移除**：未使用，v3.10 移除 os 但漏了 sys
   980|   - **cleanup_batch_files 用 try/finally**：保证临时文件清理（无论成功或失败）
   981|
   982|78. **MODULE.md v2.73 (2026-05-26)** — 规范补充
   983|   - **约束 #13 修正**：peek_key/pop_record 检查 exhausted（两个方法对称）
   984|   - **新增约束 #19-#20**：常量定义在 import 之后、cleanup_batch_files 用 try/finally
   985|   - **规范补充原因**：代码审查发现 PEP 8 顺序违规、方法不对称、临时文件清理不保证
   986|
   987|79. **fetch_factor_cache.py v3.18 (2026-05-26)** — Bug修复（3项）
   988|   - **n_way_merge 显式收集后选最大**：收集相同 key 所有记录后按 batch_idx 降序选最大，不依赖弹出顺序
   989|   - **datetime.now() 只调用一次**：`now = datetime.now()` 后生成 `generated_at` 和 `last_updated` 两个格式
   990|   - **save_batch_cache_sorted 移除 copy**：改为文档说明就地修改 date 列，避免内存峰值翻倍
   991|
   992|80. **MODULE.md v2.74 (2026-05-26)** — 规范修正
   993|   - **约束 #6 修正**：函数修改 DataFrame 需文档说明（不强制 copy）
   994|   - **约束 #17 修正**：datetime.now() 只调用一次（而非"固定时间戳"）
   995|   - **新增约束 #21**：N-way merge 显式收集后选最大
   996|   - **规范修正原因**：copy 导致内存峰值翻倍，文档说明更灵活；弹出顺序依赖不可靠
   997|
   998|81. **fetch_factor_cache.py v3.19 (2026-05-26)** — Bug修复（5项）
   999|   - **validate_final_data 流式读取**：避免 json.load 全量加载只为抽样，改为流式迭代
  1000|   - **format_final_output 只保留标量**：date_start/date_end/n_assets，而非完整 dates_list/assets_list
  1001|  1001|   - **模块级注释合并到常量**：注释紧贴 _MODULE_LOGGER 和 _OUTPUT_VERSION 定义
  1002|   - **cleanup_batch_files 增加兜底**：merged_*.json.gz 可能残留，增加兜底清理
  1003|   - **n_way_merge 移除冗余赋值**：`streams = []` 在函数返回前无实际效果
  1004|
  1005|82. **MODULE.md v2.75 (2026-05-26)** — 规范修正
  1006|   - **约束 #10-#11 修正**：大文件流式读取验证、meta 信息只保留标量
  1007|   - **新增约束 #22-#23**：cleanup 增加兜底清理、模块级注释合并到常量
  1008|   - **规范修正原因**：全量加载只为抽样浪费内存；完整列表用于 meta 信息冗余
  1009|
  1010|83. **fetch_factor_cache.py v3.20 (2026-05-26)** — Bug修复（4项）
  1011|   - **validate_final_data 初始化默认值**：n_days/n_assets/date_start/date_end 初始化为 0/""，防止 NameError
  1012|   - **validate_final_data 健壮 meta 解析**：收集 meta 行后用 json.loads 解析，而非手动字符串匹配
  1013|   - **validate_final_data step 保守估计**：若 n_days=0 则使用 sample_size*100 保守步长
  1014|   - **n_way_merge 增加 counter**：heap 元素增加唯一计数器，打破同批次相同 key 的平局
  1015|
  1016|84. **MODULE.md v2.76 (2026-05-26)** — 规范修正
  1017|   - **约束 #9 修正**：heap 元素增加 counter 打破平局
  1018|   - **新增约束 #24-#25**：变量初始化默认值、meta 解析用 json.loads
  1019|   - **规范修正原因**：变量未初始化导致 NameError；手动字符串匹配脆弱
  1020|
  1021|85. **fetch_factor_cache.py v3.21 (2026-05-26)** — Bug修复（4项）
  1022|   - **is_exhausted 逻辑修正**：`return self.exhausted or self.idx >= len(self.records)`（而非 and）
  1023|   - **_load_next_chunk 改名**：改为 `_load_all`，语义更清晰（一次性加载，而非暗示多次调用）
  1024|   - **main 返回值冗余**：删除 format_final_output 返回值使用，统计信息由 validate_final_data 提供
  1025|   - **save_batch_cache_sorted 接口契约**：补充 Note 说明输入/输出类型
  1026|
  1027|86. **MODULE.md v2.77 (2026-05-26)** — 规范修正
  1028|   - **新增约束 #14**：is_exhausted 逻辑用 or
  1029|   - **新增约束 #26-#28**：方法名语义清晰、返回值避免冗余、函数接口契约说明
  1030|   - **规范修正原因**：逻辑错误导致提前返回 False；方法名误导；返回值冗余；接口契约不清晰
  1031|
  1032|87. **fetch_factor_cache.py v3.22 (2026-05-26)** — Bug修复（3项）
  1033|   - **cleanup_batch_files 增加 try**：中途出错也继续清理，收集 errors 并 warning
  1034|   - **get_memory_info_str 用 is not None**：`if vmrss is not None` 而非 `if vmrss`（0 是 falsy）
  1035|   - **write_record 闭包捕获 f**：定义在 with 块内闭包捕获，而非定义在外部又传入参数
  1036|
  1037|88. **MODULE.md v2.78 (2026-05-26)** — 规范修正
  1038|   - **约束 #20 修正**：用 try 保证继续清理（而非 try/finally）
  1039|   - **新增约束 #29-#30**：vmrss 判断用 is not None、内嵌函数闭包捕获一致
  1040|   - **规范修正原因**：中途出错导致部分文件残留；0 是 falsy 导致跳过；参数传入与闭包捕获不一致
  1041|
  1042|89. **fetch_factor_cache.py v3.23 (2026-05-26)** — Bug修复（1项）
  1043|   - **validate_final_data 一次性加载**：直接 json.load(full) 后提取 meta/data，避免 meta 手动拼接脆弱
  1044|   - **简化代码**：删除两阶段流式读取，改为一次性加载（meta 小，可接受）
  1045|
  1046|90. **MODULE.md v2.79 (2026-05-26)** — 规范修正
  1047|   - **约束 #10/#25 修正**：大文件验证一次性加载（而非流式读取 meta）
  1048|   - **规范修正原因**：meta 手动拼接字符串脆弱，直接 json.load 更健壮
  1049|
  1050|91. **fetch_factor_cache.py v3.24 (2026-05-26)** — Bug修复（4项）
  1051|   - **valid_batch_indices 移除**：收集了但从未使用，删除冗余变量
  1052|   - **heap 注释缩进修正**：注释缩进从 0 改为 4，与代码对齐
  1053|   - **valid_df 增加 copy()**：避免 SettingWithCopyWarning，每次过滤后 .copy()
  1054|   - **forward_return 统一写法**：`x.shift(-1) / x - 1` 比 `x.pct_change().shift(-1)` 更直观
  1055|
  1056|92. **MODULE.md v2.80 (2026-05-26)** — 规范补充
  1057|   - **新增约束 #31-#32**：DataFrame 链式操作用 copy()、forward_return 统一写法
  1058|   - **规范补充原因**：SettingWithCopyWarning 导致赋值失败风险；pct_change().shift(-1) 不直观
  1059|
  1060|93. **fetch_factor_cache.py v3.25 (2026-05-26)** — 接口设计修正（2项）
  1061|   - **format_final_output 返回 None**：删除返回值，统计信息由 validate_final_data 提供（单一来源）
  1062|   - **save_batch_cache_sorted 接口契约**：说明"实际调用方总是传字符串"，而非理想化"可以是 datetime 或字符串"
  1063|
  1064|94. **MODULE.md v2.81 (2026-05-26)** — 规范补充
  1065|   - **约束 #28 修正**：接口契约说明实际调用方行为
  1066|   - **新增约束 #33-#34**：函数签名与调用一致、统计信息单一来源
  1067|   - **规范补充原因**：接口契约理想化不匹配实际；返回值被丢弃但函数做了大量工作
  1068|
  1069|95. **fetch_factor_cache.py v3.26 (2026-05-26)** — Bug修复（3项）
  1070|   - **format_final_output 缩进修正**：注释缩进从 0 改为 4，避免 IndentationError
  1071|   - **validate_final_data 分两次读**：第一次只读 meta，第二次流式扫描 data，避免一次性加载大文件
  1072|   - **records_count 初始化**：函数顶部初始化 records_count = 0，防止 NameError
  1073|
  1074|96. **MODULE.md v2.82 (2026-05-26)** — 规范修正
  1075|   - **约束 #10/#25 修正**：分两次读文件（而非一次性加载）
  1076|   - **约束 #24 修正**：函数顶部初始化所有返回值变量（包括 records_count）
  1077|   - **新增约束 #35**：缩进一致性检查
  1078|   - **规范修正原因**：一次性加载大文件内存峰值；records_count 未初始化；缩进错误导致 SyntaxError
  1079|
  1080|97. **fetch_factor_cache.py v3.27 (2026-05-26)** — 代码改进（7项）
  1081|   - **BatchStream.pop_record 更新 exhausted**：弹出后立即更新状态
  1082|   - **BatchStream.__lt__ 添加**：用于 heap 比较的防御性编程
  1083|   - **del 注释修正**：准确描述为"减少引用计数"而非"释放内存"
  1084|   - **combined 增加 copy()**：sort_values 后避免 CoW 风险
  1085|   - **del data 而非 del full**：释放内存顺序正确
  1086|   - **main 用 _ 接收**：未使用返回值明确表示不使用
  1087|   - **n_records 保留用于日志**：命名合理，格式化前的记录数
  1088|
  1089|98. **MODULE.md v2.83 (2026-05-26)** — 规范补充
  1090|   - **新增约束 #36-#41**：BatchStream.__lt__、pop_record 更新 exhausted、del 注释准确、sort_values 后 copy()、del 释放顺序、未使用返回值用 _
  1091|   - **规范补充原因**：heap 对象不可比较风险；状态不一致；注释误导；CoW 风险；内存释放顺序错误；未使用变量混淆
  1092|
  1093|99. **fetch_factor_cache.py v3.28 (2026-05-27)** — Bug修复（1项）
  1094|   - **validate_final_data 真正流式扫描**：第二次改为流式行扫描，只解析抽样的行，避免两次 json.load 内存峰值翻倍
  1095|
  1096|100. **MODULE.md v2.84 (2026-05-27)** — 规范修正
  1097|   - **约束 #10 修正**：明确第二次是"流式行扫描只解析抽样行"，而非"流式扫描 data"
  1098|   - **规范修正原因**：两次 json.load 整个大文件导致内存峰值翻倍，"分两次读"目标未实现
  1099|
  1100|101. **fetch_factor_cache.py v3.29 (2026-05-27)** — Bug修复（2项）
  1101|   - **format_final_output 一次遍历**：合并 min/max/set 四次遍历为一次，同时释放 set 内存
  1102|   - **main 双校验合并路径**：factor_merged_path 和 return_merged_path 都校验，避免 None 路径触发 TypeError
  1103|
  1104|102. **MODULE.md v2.85 (2026-05-27)** — 规范补充
  1105|   - **新增约束 #42-#44**：一次遍历提取元信息、set 内存立即释放、合并路径双校验
  1106|   - **规范补充原因**：四次遍历内存峰值（两份 set 同时存在）；return_merged_path 为 None 触发 TypeError
  1107|
  1108|103. **fetch_factor_cache.py v3.30 (2026-05-27)** — 代码改进（2项）
  1109|   - **format_final_output n_records 定义**：移到日志前，明确仅用于日志
  1110|   - **cleanup_batch_files docstring 修正**：描述为 try/except（而非 try/finally），与实际实现一致
  1111|
  1112|105. **MODULE.md v2.86 (2026-05-27)** — 规范修正
  1113|   - **约束 #20 修正**：cleanup_batch_files 用 try/except（而非 try/finally）
  1114|   - **规范修正原因**：docstring 描述与实现不一致
  1115|
  1116|106. **fetch_factor_cache.py v3.31 (2026-05-27)** — Bug修复
  1117|   - **n_way_merge_deduplicate 返回值简化**：只返回 merged_path（而非 `(merged_path, count)`）
  1118|   - **调用方适配**：不再用 `_` 接收第二个返回值
  1119|   - **修复原因**：count 未被使用，统计信息由 validate_final_data 提供（单一来源）
  1120|
  1121|108. **fetch_factor_cache.py v3.32 (2026-05-27)** — Bug修复（2项）
  1122|   - **format_final_output**：删除 n_records 重复赋值（第693行和第699行）
  1123|   - **validate_final_data**：改为真正流式验证（第一次只读 meta，第二次流式扫描边计数边抽样）
  1124|   - **修复原因**：重复赋值误导注释；第一次 json.load 加载完整 data 列表触发内存峰值
  1125|
  1126|109. **MODULE.md v2.88 (2026-05-27)** — 规范补充
  1127|   - **新增约束 #46-#47**：流式验证不加载 data、变量定义位置合理
  1128|   - **规范补充原因**：validate_final_data 加载完整 data 列表导致内存峰值；n_records 重复赋值误导注释
  1129|
  1130|110. **fetch_industry.py v1.1 (2026-05-27)** — 优化（6项）
  1131|   - **版本号常量**：添加 `_OUTPUT_VERSION = '1.1'`（MODULE.md 约束 #16）
  1132|   - **Dict → dict**：Python 3.9+ 使用内置类型注解
  1133|   - **iterrows → to_dict**：性能优化，避免逐行迭代
  1134|   - **输出路径修正**：从 cache 改为 result 目录（MODULE.md 约束 #2）
  1135|   - **__main__ logger**：遵循 PROJECT.md 日志规范
  1136|   - **文档头规范**：添加日期、版本、改进历史、约束合规说明
  1137|
  1138|111. **MODULE.md v2.89 (2026-05-27)** — 版本历史补充
  1139|   - **新增 fetch_industry.py v1.1 版本历史**
  1140|
  1141|112. **fetch_industry.py v1.2 (2026-05-27)** — Bug修复（5项）
  1142|   - **docstring Returns Dict→dict**：5处类型描述修正
  1143|   - **mkdir 用 RESULT_DIR**：输出目录与规范一致（MODULE.md 约束 #2）
  1144|   - **meta 添加 version 字段**：缓存文件包含版本号
  1145|   - **修复原因**：v1.1 只修改函数签名，遗漏 docstring 内部类型描述
  1146|
  1147|113. **MODULE.md v2.90 (2026-05-27)** — 版本历史补充
  1148|   - **新增 fetch_industry.py v1.2 版本历史**
  1149|
  1150|114. **fetch_industry.py v1.3 (2026-05-27)** — Bug修复（7项）
  1151|   - **文档头版本号同步**：v1.1 → v1.3（与代码一致）
  1152|   - **第355行 Dict→dict**：get_industry_distribution docstring 遗漏修改
  1153|   - **异常日志加类型名**：3处异常处理补充 `[{type(e).__name__}]`
  1154|   - **Counter 顶部导入**：从函数内移到模块顶部（PEP 8）
  1155|   - **原子写入异常处理**：try-except 包裹 rename，失败时 unlink 清理 .tmp
  1156|   - **__all__ 导出列表**：公共模块明确导出接口
  1157|
  1158|115. **MODULE.md v2.91 (2026-05-27)** — 规范补充
  1159|   - **新增约束 #50-#53**：异常日志类型名、顶部导入、原子写入异常处理、__all__导出
  1160|
  1161|116. **fetch_industry.py v1.4 (2026-05-27)** — Bug修复（3项）
  1162|   - **SW_INDUSTRY_CODE_MAP 添加注释 + TODO**：说明为近似映射，补充 TODO 核对官方标准
  1163|   - **原子写入捕获所有异常**：except Exception（而非仅 OSError），日志移到 rename 成功后
  1164|   - **全局缓存线程安全（DCL）**：threading.Lock + 双重检查锁
  1165|
  1166|117. **MODULE.md v2.92 (2026-05-27)** — 规范补充
  1167|   - **新增约束 #54-#57**：数据映射注释+TODO、原子写入异常范围、日志位置、线程安全缓存
  1168|
  1169|118. **fetch_industry.py v1.5 (2026-05-27)** — Bug修复（3项）
  1170|   - **日期解析异常 warning 日志**：`except ValueError as e` + `{updated_at!r}: {e}`（而非静默 pass）
  1171|   - **关键词映射移除歧义**：移除 '新能'（改为 '新能源'），移除 '信达'/'华创'（银行关键词）
  1172|   - **__all__ 移除私有名称**：移除 `_OUTPUT_VERSION`（以 `_` 开头表示模块私有）
  1173|
  1174|119. **MODULE.md v2.93 (2026-05-27)** — 规范补充
  1175|   - **新增约束 #58-#60**：异常捕获需打印详情、关键词映射避免歧义、__all__ 不含私有名称
  1176|
  1177|120. **fetch_industry.py v1.6 (2026-05-27)** — Bug修复（2项）
  1178|   - **DataFrame 列名校验**：校验 `_EXPECTED_INDUSTRY_COLS` 和 `_EXPECTED_STOCK_NAME_COLS`
  1179|   - **备用数据路径参数注入**：`STOCK_LIST_BACKUP_PATH` 常量 + `load_local_industry_backup(stock_list_path)` 参数
  1180|
  1181|121. **MODULE.md v2.94 (2026-05-27)** — 规范补充
  1182|   - **新增约束 #61-#62**：DataFrame 列名校验、路径提取常量 + 参数注入
  1183|
  1184|122. **fetch_industry.py v1.7 (2026-05-27)** — Bug修复（4项）
  1185|   - **threading 重复导入删除**：顶部已导入，删除第358行重复导入
  1186|   - **关键词重叠消除**：光伏/风电 只在电力中，新能源使用锂电/电池/太阳能
  1187|   - **注释修正**：中信在证券分类（而非银行），修正误导性注释
  1188|   - **备用数据写入缓存**：添加 `_write_backup_cache()` + `write_cache=True` 参数
  1189|
  1190|123. **MODULE.md v2.95 (2026-05-27)** — 规范补充
  1191|   - **新增约束 #63-#66**：导入语句不散落、关键词映射消除重复、注释与代码一致、备用数据写入缓存
  1192|
  1193|124. **fetch_industry.py v1.8 (2026-05-27)** — Bug修复（3项）
  1194|   - **缓存过期刷新失败降级**：`try: return refresh_industry_cache() except: return industries`（旧缓存）
  1195|   - **SW_INDUSTRY_CODE_MAP 注释修正**：说明具体映射来源（如"化学原料+化学制品 → 基础化工"），移除 TODO
  1196|   - **load_local_industry_backup 注释修正**：docstring 说明"基于名称关键词推断"（而非"代码特征"）
  1197|
  1198|125. **MODULE.md v2.96 (2026-05-27)** — 规范补充
  1199|   - **新增约束 #67-#69**：缓存刷新失败降级、数据映射注释说明具体、文档注释与实现一致
  1200|
  1201|126. **fetch_industry.py v1.9 (2026-05-27)** — Bug修复（注释诚实化）
  1202|   - **SW_INDUSTRY_CODE_MAP 注释诚实化**：承认"未核对申万官方标准"，恢复 TODO
  1203|   - **注释改为"二级归属待核实"**：不编造来源（如"化学原料+化学制品"）
  1204|   - **说明映射来源**：基于 akshare 实际返回数据建立，而非官方标准
  1205|
  1206|127. **MODULE.md v2.97 (2026-05-27)** — 规范补充
  1207|   - **新增约束 #70**：注释诚实化（未核对官方标准需诚实说明，不编造来源）
  1208|
  1209|128. **fetch_industry.py v2.0 (2026-05-27)** — Bug修复（映射核对官方标准）
  1210|   - **SW_INDUSTRY_CODE_MAP 核对申万2021官方标准**：移除错误映射
  1211|   - **不存在的一级代码映射到 '其他'**：22, 28, 33, 37, 47, 51, 61 → '其他'
  1212|   - **官方一级分类（31个行业）**：一级代码连续：11, 21, 23, 24, 25, 26, 27, 31, 32, 34, 35, 36, 41, 42, 43, 44, 45, 46, 48, 49, 62, 63, 64, 65, 71, 72, 73, 74, 75, 76, 77
  1213|
  1214|129. **MODULE.md v2.98 (2026-05-27)** — 规范补充
  1215|   - **新增约束 #71**：映射核对官方标准（核对官方标准后修正映射，不存在的一级代码映射到 '其他'）
  1216|
  1217|130. **fetch_industry.py v2.1 (2026-05-27)** — Bug修复（2项）
  1218|   - **日志信息修正**："akshare 获取失败，尝试本地备用数据..."（而非"获取失败，返回空映射"）
  1219|   - **备用缓存写入策略 docstring 说明**：非致命错误（warning），与主缓存策略不同（主缓存失败抛异常）
  1220|
  1221|131. **MODULE.md v2.99 (2026-05-27)** — 规范补充
  1222|   - **新增约束 #72-#73**：备用缓存写入策略（非致命）、日志信息准确反映流程
  1223|
  1224|132. **fetch_industry.py v2.2 (2026-05-27)** — Bug修复（数据完整性验证）
  1225|   - **load_stock_industry 缓存数据完整性验证**：检查 industries 是否为 dict 类型
  1226|   - **防止后续 AttributeError**：若 industries 为 None/list，删除损坏缓存并重新获取
  1227|
  1228|133. **MODULE.md v3.00 (2026-05-27)** — 规范补充
  1229|   - **新增约束 #74**：缓存数据完整性验证（检查 industries 是否为 dict 类型）
  1230|
  1231|134. **fetch_industry.py v2.3 (2026-05-27)** — Bug修复（3项）
  1232|   - **datetime.now() 单次调用**：固定时间戳避免不一致
  1233|   - **infer_industry_from_name Note 说明**：模糊匹配优先级（如"中信银行"→证券）
  1234|   - **get_industry_distribution 类型注解**：`dict[str, int]`
  1235|
  1236|135. **MODULE.md v3.01 (2026-05-27)** — 规范补充
  1237|   - **新增约束 #75-#76**：模糊匹配优先级说明、返回类型注解完整
  1238|
  1239|136. **dataframe_utils.py v1.0-v1.7 (2026-05-27)** — 公共模块新增
  1240|   - **v1.0**: 首次创建，validate_dataframe_columns 函数
  1241|   - **v1.1**: logger 参数化，错误信息包含可用列
  1242|   - **v1.2**: 导入顺序PEP8规范化，删除未使用导入，添加边界处理
  1243|   - **v1.3**: docstring Example 完善，正常+异常场景分离
  1244|   - **v1.4**: MODULE.md 版本历史同步，测试边界完善（TC009/TC010）
  1245|   - **v1.5**: __all__ 放置位置PEP8规范化，df_name 参数支持 None，类型注解更新
  1246|   - **v1.6**: 模块级常量定义，df_name 边界校验顺序优化，日志级别调整，集合操作优化
  1247|   - **v1.7**: df 类型检查改用 isinstance，删除冗余 info 日志，优化 debug 输出格式，缺失列顺序保持原始顺序
  1248|
  1249|137. **test_dataframe_utils.py v1.0-v1.5 (2026-05-27)** — 测试文件新增
  1250|   - **v1.0**: 首次创建，覆盖正常/异常/边界场景（TC001-TC008）
  1251|   - **v1.1**: 导入顺序PEP8规范化，测试日志命名合规化
  1252|   - **v1.2**: 新增 TC009/TC010 测试边界（df_name空字符串、列名大小写敏感）
  1253|   - **v1.3**: 删除 __main__ 块，新增 TC011（df_name 为 None）
  1254|   - **v1.4**: 新增 TC012/TC013 验证默认值在错误信息中的使用
  1255|   - **v1.5**: 更新 TC003/TC013 适配 isinstance 类型检查，新增 TC014/TC015/TC016 验证非DataFrame类型和顺序保持
  1256|
  1257|49. **MODULE.md v2.58 (2026-05-26)** — 规范补充
  1258|   - **类型注解兼容性规范**：补充兼容类型说明（Python 运行时不强制类型检查）
  1259|   - **docstring Raises 规范**：描述应与实际抛出一致，不应描述未实现的场景
  1260|   - **兜底块异常信息规范**：应包含异常类型和详情（便于追溯）
  1261|
  1262|50. **data_loader.py v2.0 (2026-05-27)** — 简化重构
  1263|   - **版本历史添加**：首次记录重大重构
  1264|   - **移除模块级函数**：load_real_data、load_factor_light、load_return_light、load_cached_data_combined_light（不再被外部调用）
  1265|   - **移除 __main__ 测试代码**：遵循 PROJECT.md 禁止 __main__ 块规范
  1266|   - **移除 calculate_rsi 类方法**：已迁移到 factor_calculator.py
  1267|   - **logger 参数化**：198处 print 替换为 self._logger（info/warning）
  1268|   - **公共模块导入**：paths.py、logger_config.py、factor_calculator.py
  1269|   - **get_module_logger 函数**：DCL 模式初始化，支持外部传入 logger
  1270|   - **__init__ logger 参数**：新增 logger 参数，self._logger 初始化
  1271|   - **类常量移除**：STOCK_LIST_URL、KLINE_URL、CACHE_DIR 等改为模块级常量
  1272|   - **代码行数减少**：2584行 → 2285行（减少299行）
  1273|   - **Git diff**：109增/410删（净减301行）
  1274|
  1275|---
  1276|
  1277|data_fetchers 模块负责：
  1278|1. 从外部数据源拉取因子数据、收益数据等
  1279|2. 统一因子生成（新增）
  1280|3. 存储到 cache 目录
  1281|
  1282|**模块定位：**
  1283|- 输入：外部数据源（API、数据库等）+ 基础因子数据
  1284|- 输出：data_fetchers/result/ 缓存文件
  1285|
  1286|---
  1287|
  1288|## 数据流程
  1289|
  1290|```
  1291|外部数据源 → data_fetchers/ → data_fetchers/result/ → factor_ic/
  1292|                   ↑
  1293|                   │
  1294|           factor_generator.py（统一因子生成）
  1295|```
  1296|
  1297|**关键原则：**
  1298|- factor_ic 不自行拉取数据，只使用 result 目录统一数据源
  1299|- data_fetchers 负责数据质量和格式转换
  1300|- **factor_generator.py 作为单一因子数据源（2026-05-24 新增）**
  1301|
  1302|---
  1303|
  1304|## 脚本命名规则
  1305|
  1306|### 数据拉取脚本
  1307|
  1308|**命名格式：** `fetch_<数据源名>.py`
  1309|
  1310|| 脚本名 | 数据源 | 说明 |
  1311||--------|--------|------|
  1312|| fetch_turnover.py | 换手率 | 拉取换手率数据 |
  1313|| fetch_stock_list.py | 股票列表 | 拉取 A 股股票列表 |
  1314|| fetch_industry.py | 行业分类 | 拉取行业分类数据 |
  1315|
  1316|### 因子生成脚本
  1317|
  1318|**命名格式：** `factor_generator.py`（统一入口）
  1319|
  1320|---
  1321|
  1322|## 公共模块架构
  1323|
  1324|**目录规范：data_fetchers 下的公共模块放在 `data_fetchers/common/` 目录。**
  1325|
  1326|禁止在脚本中重复实现已有公共功能，应复用 common 模块。
  1327|
  1328|### 模块清单
  1329|
  1330|| 模块 | 功能 | 核心函数 |
  1331||------|------|----------|
  1332|| `paths.py` | 路径管理 | `get_cache_dir()`, `get_factor_data_dir()`, `get_stock_list_file()` |
  1333|| `cache_manager.py` | 缓存读写 | `read_gzip_cache()`, `write_gzip_cache()` |
  1334|| `http_client.py` | HTTP 客户端 | `create_retry_session()`, `create_eastmoney_session()` |
  1335|| `stock_utils.py` | 股票筛选 | `is_main_board_stock()`, `load_main_board_stock_list()` |
  1336|
  1337|详细规范见 `data_fetchers/common/README.md`。
  1338|
  1339|### 使用方式
  1340|
  1341|```python
  1342|from data_fetchers.common import (
  1343|    get_cache_dir,
  1344|    read_gzip_cache,
  1345|    create_eastmoney_session,
  1346|    load_main_board_stock_list,
  1347|)
  1348|
  1349|# 获取路径
  1350|cache_dir = get_cache_dir()
  1351|
  1352|# 读取缓存
  1353|data = read_gzip_cache(cache_dir / 'factor_data/data.json.gz')
  1354|
  1355|# 创建 HTTP Session
  1356|session = create_eastmoney_session()
  1357|
  1358|# 加载主板股票列表
  1359|stocks = load_main_board_stock_list()
  1360|```
  1361|
  1362|---
  1363|
  1364|## 公共模块使用规范
  1365|
  1366|### cache_manager.py 日志参数规范（2026-05-24 新增）
  1367|
  1368|**遵循 PROJECT.md 第783-857行规范，公共模块接收 logger 参数。**
  1369|
  1370|**缓存文件格式限制（2026-05-25 补充）：**
  1371|- 缓存文件必须是 JSON 格式（gzip 压缩或非压缩）
  1372|- `.gz` 文件必须是 gzip 压缩的 JSON，不能是纯 gzip 二进制文件
  1373|- `read_cache`、`read_gzip_cache` 内部调用 `json.load()`，非 JSON 文件会抛 `ValueError`
  1374|- 违反此限制会导致 JSON 解析失败
  1375|
  1376|**使用方式：**
  1377|```python
  1378|from data_fetchers.common import read_gzip_cache
  1379|import logging
  1380|
  1381|# 调用方传入 logger（推荐）
  1382|logger = logging.getLogger('factor_ic.ic_rsi_1d')
  1383|data = read_gzip_cache(cache_file, logger=logger)
  1384|
  1385|# 不传 logger 时使用默认 logger（fallback）
  1386|data = read_gzip_cache(cache_file)  # 自动创建模块级 logger
  1387|```
  1388|
  1389|**参数类型：**
  1390|- `path`: 支持 `Path | str`，内部统一转换为 Path
  1391|- `logger`: 可选，传入调用方的 logger 以追溯调用方
  1392|
  1393|**禁止：**
  1394|```python
  1395|# ❌ 公共模块独立创建 logger（旧方式，已废弃）
  1396|# logger = logging.getLogger(__name__)  # 无法追溯调用方
  1397|```
  1398|
  1399|**为何必须传入 logger：**
  1400|1. 日志可追溯调用方，便于定位问题
  1401|2. 符合 PROJECT.md 公共模块日志规范
  1402|3. 模块级 fallback logger 作为兼容方案
  1403|
  1404|### 日志换行符规范（2026-05-25 新增）
  1405|
  1406|**原则：** logging 模块的格式化器通常不期望消息内含换行，某些 handler（如 RotatingFileHandler）处理含换行的日志可能产生解析问题。
  1407|
  1408|**允许使用换行符的场景：**
  1409|
  1410|1. **错误日志多行格式化**
  1411|   - 复杂错误（如 JSON 解析失败）允许多行格式化输出以提高可读性
  1412|   - 示例：
  1413|     ```python
  1414|     logger.error(
  1415|         "JSON 解析失败\n"
  1416|         "文件路径: %s\n"
  1417|         "错误位置: 行 %d, 列 %d\n"
  1418|         "错误信息: %s",
  1419|         file_path, e.lineno, e.colno, e.msg
  1420|     )
  1421|     ```
  1422|
  1423|2. **__main__ 测试块视觉分隔**
  1424|   - 自测试输出允许多行分隔符以提高可读性
  1425|   - 示例：
  1426|     ```python
  1427|     test_logger.info("\n[测试 1] 函数定义验证...")
  1428|     test_logger.info("\n" + "=" * 40)
  1429|     ```
  1430|
  1431|**不建议使用换行符的场景：**
  1432|
  1433|1. **一般 info 级别日志**
  1434|   - 避免 info 日志中使用 `\n` 换行符
  1435|   - 某些 handler（如 RotatingFileHandler）解析含换行的日志可能产生问题
  1436|   - 示例（禁止）：
  1437|     ```python
  1438|     # ❌ info 日志中使用换行符
  1439|     logger.info("数据加载完成\n记录数: %d", count)
  1440|     
  1441|     # ✅ 改为单行格式
  1442|     logger.info("数据加载完成，记录数: %d", count)
  1443|     ```
  1444|
  1445|**JSON 解析异常处理：**
  1446|- 抛出 `ValueError` 而非 `json.JSONDecodeError`
  1447|- 避免传递完整 JSON 文档导致内存翻倍
  1448|- 参考 `references/backtest-module-optimization-patterns.md Section 1.2`
  1449|
  1450|### 临时文件命名规范（2026-05-25 新增）
  1451|
  1452|**问题背景：**
  1453|- `Path.with_suffix('.tmp')` 会替换最后一个后缀
  1454|- 对于 `.json.gz` 文件，会变成 `.json.tmp`（丢失 `.gz` 后缀）
  1455|- 导致临时文件名与原文件名不一致
  1456|
  1457|**正确用法：**
  1458|```python
  1459|# ✅ 正确：追加 .tmp 后缀，保留原文件名
  1460|temp_path = output_path.parent / (output_path.name + '.tmp')
  1461|# factor_data.json.gz → factor_data.json.gz.tmp
  1462|
  1463|# ❌ 错误：替换最后一个后缀
  1464|temp_path = output_path.with_suffix('.tmp')
  1465|# factor_data.json.gz → factor_data.json.tmp（丢失 .gz）
  1466|```
  1467|
  1468|**适用场景：**
  1469|- 原子写入（临时文件 + os.replace）
  1470|- gzip 压缩文件写入
  1471|- 多后缀文件（如 `.tar.gz`、`.json.gz`）
  1472|
  1473|### 异常捕获规范（2026-05-25 新增）
  1474|
  1475|**问题背景：**
  1476|- `PermissionError` 是 `OSError` 的子类
  1477|- `IOError` 在 Python 3 中已合并到 `OSError`
  1478|- 重复捕获会导致代码冗余
  1479|
  1480|**正确用法：**
  1481|```python
  1482|# ✅ 正确：OSError 涵盖 PermissionError 和 IOError
  1483|except OSError as e:
  1484|    # 文件系统错误（磁盘/权限/IO）
  1485|    ...
  1486|
  1487|# ❌ 错误：重复捕获子类
  1488|except (OSError, PermissionError, IOError) as e:
  1489|    # PermissionError 是 OSError 子类，冗余
  1490|    ...
  1491|```
  1492|
  1493|**OSError 子类关系：**
  1494|- `PermissionError` ⊆ `OSError`
  1495|- `FileNotFoundError` ⊆ `OSError`
  1496|- `IOError` = `OSError`（Python 3 合并）
  1497|
  1498|### __main__ 测试块规范（2026-05-25 新增）
  1499|
  1500|**问题背景：**
  1501|  1501|- `if __name__ == '__main__'` 时，模块名是 `__main__`
  1502|- `from data_fetchers.xxx import ...` 会触发重新导入
  1503|- 导致模块被执行两次，产生循环/重复行为
  1504|
  1505|**正确用法：**
  1506|```python
  1507|# ✅ 正确：直接使用已定义的函数
  1508|if __name__ == '__main__':
  1509|    # 函数已在模块中定义，直接使用
  1510|    metadata = generate_all_factors(logger=test_logger)
  1511|
  1512|# ❌ 错误：重新导入自己（循环导入）
  1513|if __name__ == '__main__':
  1514|    from data_fetchers.factor_generator import generate_all_factors  # 触发重新导入
  1515|    metadata = generate_all_factors(logger=test_logger)
  1516|```
  1517|
  1518|**适用场景：**
  1519|- 模块自测试（__main__ 测试块）
  1520|- CLI 入口测试
  1521|
  1522|**__main__ 块结构规范（2026-05-25 补充）：**
  1523|
  1524|原则：`__main__` 块应作为 CLI 入口调用 `main()` 函数，测试代码应移至独立测试脚本。
  1525|
  1526|```python
  1527|# ✅ 正确：__main__ 块作为 CLI 入口
  1528|if __name__ == '__main__':
  1529|    import sys
  1530|    sys.exit(main())
  1531|
  1532|# ❌ 错误：__main__ 块直接运行测试代码
  1533|if __name__ == '__main__':
  1534|    test_logger = setup_logger(...)
  1535|    metadata = generate_all_factors(logger=test_logger)
  1536|    # ... 60行测试代码 ...
  1537|```
  1538|
  1539|**测试代码位置规范：**
  1540|- 测试脚本应放在 `test_cases/test_xxx.py`
  1541|- 示例：`data_fetchers/test_cases/test_factor_generator.py`
  1542|- 测试脚本独立运行，与 CLI 入口分离
  1543|
  1544|**为何必须分离：**
  1545|1. `__main__` 块应保持简洁，便于 CLI 调用
  1546|2. 测试代码复杂时会影响 CLI 入口可读性
  1547|3. 测试脚本可独立执行，便于 CI/CD 集成
  1548|
  1549|### 条件导入位置规范（2026-05-25 新增）
  1550|
  1551|**问题背景：**
  1552|- PEP 8 规范：导入应在文件顶部
  1553|- 多个 `if __name__ == '__main__'` 块分散在文件中间违反规范
  1554|
  1555|**正确用法：**
  1556|```python
  1557|# ✅ 正确：所有条件导入合并到顶部
  1558|if __name__ == '__main__':
  1559|    import sys
  1560|    from xxx import func_a
  1561|    from xxx import func_b
  1562|else:
  1563|    from .xxx import func_a
  1564|    from .xxx import func_b
  1565|
  1566|# ❌ 错误：条件导入分散在文件中间
  1567|if __name__ == '__main__':
  1568|    import sys
  1569|    from xxx import func_a
  1570|else:
  1571|    from .xxx import func_a
  1572|
  1573|# ... 几十行代码后 ...
  1574|
  1575|if __name__ == '__main__':
  1576|    from xxx import func_b  # 违反 PEP 8 导入位置规范
  1577|else:
  1578|    from .xxx import func_b
  1579|```
  1580|
  1581|### 除零保护规范（2026-05-25 新增）
  1582|
  1583|**问题背景：**
  1584|- 百分比计算 `count / total * 100` 在空数据时抛 `ZeroDivisionError`
  1585|- 函数内嵌套定义辅助函数导致作用域混乱
  1586|
  1587|**正确用法：**
  1588|```python
  1589|# ✅ 正确：模块级私有函数，作用域清晰
  1590|def _calc_pct(valid_count: int, total_count: int) -> float:
  1591|    if total_count <= 0:
  1592|        return 0.0
  1593|    return round(valid_count / total_count * 100, 2)
  1594|
  1595|# 调用方式
  1596|logger.info("有效记录: %d (%.2f%%)", valid, _calc_pct(valid, total))
  1597|
  1598|# ❌ 错误：函数内嵌套定义
  1599|def generate_all_factors(...):
  1600|    # ...几十行代码...
  1601|    def calc_pct(valid_count):  # 作用域混乱
  1602|        return round(valid_count / total * 100, 2) if total > 0 else 0.0
  1603|```
  1604|
  1605|**适用场景：**
  1606|- 有效记录百分比计算
  1607|- 缺失记录百分比计算
  1608|- 任何需要除零保护的百分比计算
  1609|
  1610|### 硬编码常量规范（2026-05-25 新增）
  1611|
  1612|**问题背景：**
  1613|- `output_cols[8:]` 等切片索引依赖列表顺序，脆弱
  1614|- 列顺序变化会导致索引错误
  1615|
  1616|**正确用法：**
  1617|```python
  1618|# ✅ 正确：常量定义，明确语义
  1619|_EXTENDED_FACTOR_COLS = ['bollinger_pb', 'kdj_j', 'turnover_surge']
  1620|metadata['factor_columns'] = _EXTENDED_FACTOR_COLS
  1621|
  1622|# ❌ 错误：切片索引，脆弱
  1623|output_cols = ['date', 'asset', 'open', 'close', 'high', 'low', 'rsi_6', 'volume_ratio_5', ...]
  1624|metadata['factor_columns'] = output_cols[8:]  # 依赖顺序
  1625|```
  1626|
  1627|**适用场景：**
  1628|- 扩展因子列名
  1629|- 固定字段列表
  1630|- 任何不应依赖顺序的常量列表
  1631|
  1632|### 临时文件清理规范（2026-05-25 新增）
  1633|
  1634|**问题背景：**
  1635|- `exists() + unlink()` 存在 TOCTOU（Time-of-check-to-time-of-use）竞争窗口
  1636|- 检查文件存在与删除文件之间存在时间差，并发场景可能产生 FileNotFoundError
  1637|
  1638|**正确用法：**
  1639|```python
  1640|# ✅ 正确：原子操作，消除 TOCTOU 竞争窗口
  1641|temp_path.unlink(missing_ok=True)
  1642|
  1643|# ❌ 错误：TOCTOU 竞争窗口
  1644|if temp_path.exists():
  1645|    temp_path.unlink()  # 竞争窗口：exists() 后文件可能被其他进程删除
  1646|```
  1647|
  1648|**适用场景：**
  1649|- 异常处理中的临时文件清理
  1650|- 原子写入失败后的清理
  1651|- 任何需要安全删除可能不存在文件的场景
  1652|
  1653|**Python 版本要求：**
  1654|- Python 3.8+ 支持 `missing_ok=True`
  1655|
  1656|### docstring Raises 规范（2026-05-25 新增）
  1657|
  1658|**问题背景：**
  1659|- Raises 声明的异常应与实际抛出一致
  1660|- 已内部捕获转换的异常不应声明（调用方永远不会收到）
  1661|
  1662|**正确用法：**
  1663|```python
  1664|# ✅ 正确：只声明调用方可能收到的异常
  1665|def generate_all_factors(...):
  1666|    """
  1667|    Raises:
  1668|        FileNotFoundError: 输入数据文件不存在
  1669|        ValueError: JSON 解析失败（已内部捕获转换）
  1670|        RuntimeError: 文件系统错误
  1671|    """
  1672|    try:
  1673|        data = json.load(f)
  1674|    except json.JSONDecodeError as e:
  1675|        raise ValueError(...) from e  # 转换，调用方收到 ValueError
  1676|
  1677|# ❌ 错误：声明已转换的异常
  1678|def generate_all_factors(...):
  1679|    """
  1680|    Raises:
  1681|        json.JSONDecodeError: JSON 解析失败  # 调用方永远不会收到
  1682|    """
  1683|```
  1684|
  1685|**原则：**
  1686|- Raises 声明应与实际抛出一致
  1687|- 已捕获转换的异常不应声明
  1688|- 补充 Note 说明内部转换逻辑
  1689|
  1690|### 常量引用关系规范（2026-05-25 新增）
  1691|
  1692|**问题背景：**
  1693|- 多个常量各自硬编码相同内容，没有引用关系
  1694|- 新增内容时需同时修改多处，极易遗漏
  1695|- 维护隐患：一处修改遗漏会导致不一致
  1696|
  1697|**正确用法：**
  1698|```python
  1699|# ✅ 正确：建立引用关系，一处定义多处使用
  1700|_EXTENDED_FACTOR_COLS = ['bollinger_pb', 'kdj_j', 'turnover_surge']
  1701|_BASE_COLS = ['date', 'asset', 'open', 'close', 'high', 'low', 'rsi_6', 'volume_ratio_5']
  1702|_OUTPUT_COLS = _BASE_COLS + _EXTENDED_FACTOR_COLS
  1703|
  1704|output_cols = _OUTPUT_COLS  # 引用，非硬编码
  1705|metadata['factor_columns'] = _EXTENDED_FACTOR_COLS  # 同一常量引用
  1706|
  1707|# ❌ 错误：各自硬编码，没有引用关系
  1708|_EXTENDED_FACTOR_COLS = ['bollinger_pb', 'kdj_j', 'turnover_surge']
  1709|output_cols = ['date', 'asset', ..., 'bollinger_pb', 'kdj_j', 'turnover_surge']  # 硬编码
  1710|metadata['factor_columns'] = ['bollinger_pb', 'kdj_j', 'turnover_surge']  # 硬编码
  1711|```
  1712|
  1713|**原则：**
  1714|- 相关常量应建立引用关系
  1715|- 新增内容只需修改一处
  1716|- 消除维护隐患
  1717|
  1718|### 条件块导入规范（2026-05-25 新增）
  1719|
  1720|**问题背景：**
  1721|- 顶部条件块已导入模块
  1722|- __main__ 块重复导入同一模块
  1723|- 冗余代码，增加维护负担
  1724|
  1725|**正确用法：**
  1726|```python
  1727|# ✅ 正确：顶部条件块导入，__main__ 块直接使用
  1728|if __name__ == '__main__':
  1729|    import sys
  1730|    sys.path.insert(0, str(project_root))
  1731|    from xxx import func_a
  1732|else:
  1733|    from .xxx import func_a
  1734|
  1735|# 底部 __main__ CLI 入口
  1736|if __name__ == '__main__':
  1737|    sys.exit(main())  # sys 已在顶部导入，直接使用
  1738|
  1739|# ❌ 错误：__main__ 块重复导入
  1740|if __name__ == '__main__':
  1741|    import sys  # 顶部已导入，重复
  1742|    sys.exit(main())
  1743|```
  1744|
  1745|**原则：**
  1746|- 条件块导入的模块在同一执行路径内可见
  1747|- 无需在 __main__ 块重复导入
  1748|- 减少冗余代码
  1749|
  1750|### 输出目录创建规范（2026-05-25 新增）
  1751|
  1752|**问题背景：**
  1753|- 输出文件父目录可能不存在
  1754|- 直接写入会导致 FileNotFoundError
  1755|- 需在写入前确保目录存在
  1756|
  1757|**正确用法：**
  1758|```python
  1759|# ✅ 正确：写入前确保父目录存在
  1760|output_path.parent.mkdir(parents=True, exist_ok=True)
  1761|temp_path = output_path.parent / (output_path.name + '.tmp')
  1762|
  1763|# ❌ 错误：未创建父目录，可能导致 FileNotFoundError
  1764|temp_path = output_path.parent / (output_path.name + '.tmp')
  1765|with open(temp_path, 'w') as f:  # 父目录不存在时报错
  1766|    json.dump(data, f)
  1767|```
  1768|
  1769|**参数说明：**
  1770|- `parents=True`：创建所有必要的父目录
  1771|- `exist_ok=True`：目录已存在时不报错
  1772|
  1773|**适用场景：**
  1774|- 文件写入前
  1775|- 临时文件创建前
  1776|- 任何需要确保目录存在的场景
  1777|
  1778|### docstring 示例规范（2026-05-25 新增）
  1779|
  1780|**问题背景：**
  1781|- 过于具体的示例值（如 `120.5`）可能误导用户
  1782|- 实际运行值可能与示例差距悬殊（单元测试耗时 < 1ms）
  1783|- docstring 应反映真实场景而非假设值
  1784|
  1785|**正确用法：**
  1786|```python
  1787|# ✅ 正确：范围说明或注释
  1788|>>> metadata['elapsed_seconds']  # 实际耗时，单位秒（范围：0.0 ~ 数百秒，取决于数据量）
  1789|
  1790|# ❌ 错误：过于具体的示例值
  1791|>>> metadata['elapsed_seconds']
  1792|120.5  # 单元测试可能耗时 < 1ms，差距悬殊
  1793|```
  1794|
  1795|**原则：**
  1796|- 示例值应反映真实场景
  1797|- 避免过于具体的假设值
  1798|- 改为范围说明或注释
  1799|- 适用于不确定的值（耗时、数据量等）
  1800|
  1801|### 可变对象返回副本规范（2026-05-25 新增）
  1802|
  1803|**问题背景：**
  1804|- 模块级常量（列表、字典等）是可变对象
  1805|- 直接返回引用，调用方可修改
  1806|- 修改会影响模块内部状态（意外副作用）
  1807|
  1808|**正确用法：**
  1809|```python
  1810|# ✅ 正确：返回副本，防止外部修改
  1811|_EXTENDED_FACTOR_COLS = ['bollinger_pb', 'kdj_j', 'turnover_surge']
  1812|metadata['factor_columns'] = list(_EXTENDED_FACTOR_COLS)  # 返回副本
  1813|
  1814|# ❌ 错误：返回引用，外部可修改模块内部状态
  1815|_EXTENDED_FACTOR_COLS = ['bollinger_pb', 'kdj_j', 'turnover_surge']
  1816|metadata['factor_columns'] = _EXTENDED_FACTOR_COLS  # 返回引用
  1817|# 调用方: cols = metadata['factor_columns']; cols.append('new')  # 修改了模块常量
  1818|```
  1819|
  1820|**适用场景：**
  1821|- 模块级列表常量返回
  1822|- 模块级字典常量返回
  1823|- 任何可变对象返回给外部
  1824|
  1825|**原则：**
  1826|- 返回副本而非引用
  1827|- 防止外部修改模块内部状态
  1828|- 使用 `list()`、`dict()`、`.copy()` 等方法
  1829|
  1830|### 常量类型规范（2026-05-25 新增）
  1831|
  1832|**问题背景：**
  1833|- 模块级常量列表是可变对象
  1834|- 意外修改会导致模块状态变化
  1835|- 元组是不可变对象，防止意外修改
  1836|
  1837|**正确用法：**
  1838|```python
  1839|# ✅ 正确：使用元组防止意外修改
  1840|_EXTENDED_FACTOR_COLS: tuple = ('bollinger_pb', 'kdj_j', 'turnover_surge')
  1841|_BASE_COLS: tuple = ('date', 'asset', 'open', 'close', 'high', 'low')
  1842|_OUTPUT_COLS: tuple = _BASE_COLS + _EXTENDED_FACTOR_COLS  # 元组相加仍是元组
  1843|
  1844|# ❌ 错误：使用列表，可能被意外修改
  1845|_EXTENDED_FACTOR_COLS = ['bollinger_pb', 'kdj_j', 'turnover_surge']
  1846|_EXTENDED_FACTOR_COLS.append('new')  # 模块状态被修改
  1847|```
  1848|
  1849|**原则：**
  1850|- 模块级常量列表应使用元组
  1851|- 元组不可变，防止意外修改
  1852|- 返回副本时使用 `list(tuple)` 转换
  1853|
  1854|### 内存释放规范（2026-05-25 新增）
  1855|
  1856|**问题背景：**
  1857|- 大 DataFrame 可能包含中间列（比输出更多）
  1858|- 使用完毕后仍占用内存
  1859|- 显式释放可减少内存占用
  1860|
  1861|**正确用法：**
  1862|```python
  1863|# ✅ 正确：显式释放不再需要的 DataFrame
  1864|output_df = factor_df[output_cols].copy()
  1865|del factor_df  # 显式释放内存
  1866|
  1867|# ❌ 错误：factor_df 仍占用内存（可能包含中间列）
  1868|output_df = factor_df[output_cols].copy()
  1869|# factor_df 未释放，内存持续占用
  1870|```
  1871|
  1872|**适用场景：**
  1873|- factor_df 包含中间列（比 output_df 更多）
  1874|- 大数据处理完毕后
  1875|- 内存敏感场景
  1876|
  1877|**原则：**
  1878|- 显式释放不再需要的变量
  1879|- 使用 `del var` 释放内存
  1880|- 在变量使用完毕后立即释放
  1881|
  1882|### mkdir 位置规范（2026-05-25 新增）
  1883|
  1884|**问题背景：**
  1885|- mkdir 在 try 块外调用，异常无法统一处理
  1886|- 与原子写入语义冲突（写入失败时无法捕获目录创建异常）
  1887|
  1888|**正确用法：**
  1889|```python
  1890|# ✅ 正确：mkdir 在 try 块内，异常可统一处理
  1891|temp_path = output_path.parent / (output_path.name + '.tmp')
  1892|try:
  1893|    output_path.parent.mkdir(parents=True, exist_ok=True)  # 在 try 块内
  1894|    with open(temp_path, 'w') as f:
  1895|        json.dump(data, f)
  1896|    os.replace(temp_path, output_path)
  1897|except OSError as e:
  1898|    temp_path.unlink(missing_ok=True)
  1899|    raise RuntimeError(...)
  1900|
  1901|# ❌ 错误：mkdir 在 try 块外，异常无法统一处理
  1902|output_path.parent.mkdir(parents=True, exist_ok=True)  # 在 try 块外
  1903|temp_path = output_path.parent / (output_path.name + '.tmp')
  1904|try:
  1905|    with open(temp_path, 'w') as f:
  1906|        json.dump(data, f)
  1907|except OSError as e:
  1908|    # mkdir 异常无法捕获
  1909|```
  1910|
  1911|**原则：**
  1912|- mkdir 应在 try 块内调用
  1913|- 异常可统一处理
  1914|- 与原子写入语义一致
  1915|
  1916|### 常量注释规范（2026-05-25 新增）
  1917|
  1918|**问题背景：**
  1919|- 常量结构说明放在使用处（函数内）
  1920|- 定义处无注释，维护困难
  1921|- 注释与定义分离，修改时易遗漏
  1922|
  1923|**正确用法：**
  1924|```python
  1925|# ✅ 正确：注释放在定义处
  1926|_OUTPUT_COLS: tuple = _BASE_COLS + _EXTENDED_FACTOR_COLS
  1927|# 结构说明：
  1928|# _OUTPUT_COLS[0:2]  = date, asset（索引字段）
  1929|# _OUTPUT_COLS[2:6]  = open, close, high, low（行情数据）
  1930|# ...
  1931|
  1932|# 使用处只需简短说明
  1933|output_cols = _OUTPUT_COLS  # 使用模块级常量
  1934|
  1935|# ❌ 错误：注释放在使用处
  1936|_OUTPUT_COLS: tuple = _BASE_COLS + _EXTENDED_FACTOR_COLS  # 定义处无注释
  1937|
  1938|def func():
  1939|    # _OUTPUT_COLS[0:2]  = date, asset  # 注释分离
  1940|    # _OUTPUT_COLS[2:6]  = open, close, high, low
  1941|    output_cols = _OUTPUT_COLS
  1942|```
  1943|
  1944|**原则：**
  1945|- 常量结构说明应放在定义处
  1946|- 使用处只需简短说明
  1947|- 注释与定义不分离
  1948|
  1949|### 异常日志规范（2026-05-25 新增）
  1950|
  1951|**问题背景：**
  1952|- 异常日志只包含错误消息
  1953|- 缺少异常类型，难以追溯问题
  1954|
  1955|**正确用法：**
  1956|```python
  1957|# ✅ 正确：包含异常类型名
  1958|except Exception as e:
  1959|    logger.error("执行失败 [%s]: %s", type(e).__name__, str(e))
  1960|
  1961|# ❌ 错误：缺少异常类型
  1962|except Exception as e:
  1963|    logger.error("执行失败: %s", str(e))
  1964|```
  1965|
  1966|**原则：**
  1967|- 异常日志应包含异常类型名
  1968|- 使用 `type(e).__name__` 获取类型名
  1969|- 便于追溯问题根源
  1970|
  1971|### docstring Example 格式规范（2026-05-25 新增）
  1972|
  1973|**问题背景：**
  1974|- 注释放在返回值行而非 `>>>` 行
  1975|- 格式不规范，影响 doctest 可读性
  1976|
  1977|**正确用法：**
  1978|```python
  1979|# ✅ 正确：注释放在 >>> 行，返回值行无注释
  1980|>>> metadata['factor_columns']  # 返回列表副本，防止外部修改
  1981|['bollinger_pb', 'kdj_j', 'turnover_surge']
  1982|>>> isinstance(metadata['elapsed_seconds'], float)
  1983|True
  1984|
  1985|# ❌ 错误：注释放在返回值行
  1986|>>> metadata['factor_columns']
  1987|['bollinger_pb', 'kdj_j', 'turnover_surge']  # 返回列表副本
  1988|>>> metadata['elapsed_seconds']  # 实际耗时
  1989|# 缺少返回值行
  1990|```
  1991|
  1992|**原则：**
  1993|- 注释放在 `>>>` 行末
  1994|- 返回值行无注释
  1995|- 保持格式简洁
  1996|
  1997|### 冗余别名规范（2026-05-26 新增）
  1998|
  1999|**问题背景：**
  2000|- 局部变量作为常量的别名（`output_cols = _OUTPUT_COLS`）
  2001|  2001|- 增加代码复杂度，无实际作用
  2002|- 维护时需修改多处（常量 + 别名）
  2003|
  2004|**正确用法：**
  2005|```python
  2006|# ✅ 正确：直接使用常量
  2007|missing_cols = [col for col in _OUTPUT_COLS if col not in df.columns]
  2008|output_df = df[_OUTPUT_COLS].copy()
  2009|
  2010|# ❌ 错误：冗余别名
  2011|output_cols = _OUTPUT_COLS  # 无意义的别名
  2012|missing_cols = [col for col in output_cols if col not in df.columns]
  2013|output_df = df[output_cols].copy()
  2014|```
  2015|
  2016|**原则：**
  2017|- 直接使用模块级常量
  2018|- 避免无意义的局部别名
  2019|- 减少代码复杂度
  2020|
  2021|### 职责分离规范（2026-05-26 新增）
  2022|
  2023|**问题背景：**
  2024|- mkdir 和文件写入在同一个 try 块
  2025|- temp_path 定义在 try 块外，unlink 存在路径未初始化风险
  2026|- 异常信息不够精确（无法区分目录创建失败 vs 文件写入失败）
  2027|
  2028|**正确用法：**
  2029|```python
  2030|# ✅ 正确：mkdir 单独处理，职责分离
  2031|try:
  2032|    output_path.parent.mkdir(parents=True, exist_ok=True)
  2033|except OSError as e:
  2034|    raise RuntimeError(f"创建输出目录失败: {output_path.parent}, ...") from e
  2035|
  2036|temp_path = output_path.parent / (output_path.name + '.tmp')  # mkdir 成功后才定义
  2037|try:
  2038|    with gzip.open(temp_path, 'wt') as f:
  2039|        json.dump(data, f)
  2040|    os.replace(temp_path, output_path)
  2041|except OSError as e:
  2042|    temp_path.unlink(missing_ok=True)
  2043|    raise RuntimeError(f"文件系统错误: {output_path}, ...") from e
  2044|
  2045|# ❌ 错误：mkdir 和写入混在一起
  2046|temp_path = output_path.parent / (output_path.name + '.tmp')  # mkdir 未执行就定义
  2047|try:
  2048|    output_path.parent.mkdir(parents=True, exist_ok=True)  # 混在一起
  2049|    with gzip.open(temp_path, 'wt') as f:
  2050|        json.dump(data, f)
  2051|except OSError as e:
  2052|    temp_path.unlink(missing_ok=True)  # temp_path 可能未初始化
  2053|```
  2054|
  2055|**原则：**
  2056|- mkdir 单独 try 块处理
  2057|- 异常信息区分职责（目录创建 vs 文件写入）
  2058|- temp_path 在 mkdir 成功后定义
  2059|
  2060|### 错误信息规范（2026-05-26 新增）
  2061|
  2062|**问题背景：**
  2063|- 错误信息过于模糊（"输出列不存在"）
  2064|- 缺少上下文提示，排错路径长
  2065|- 无法快速定位问题根源
  2066|
  2067|**正确用法：**
  2068|```python
  2069|# ✅ 正确：增加上下文提示
  2070|if missing_cols:
  2071|    raise KeyError(
  2072|        f"输出列不存在: {missing_cols}，"
  2073|        f"请检查因子计算函数的输出列名是否与 _EXTENDED_FACTOR_COLS 一致"
  2074|    )
  2075|
  2076|# ❌ 错误：错误信息过于模糊
  2077|if missing_cols:
  2078|    raise KeyError(f"输出列不存在: {missing_cols}")  # 缺少上下文
  2079|```
  2080|
  2081|**原则：**
  2082|- 错误信息应包含上下文提示
  2083|- 提供排错建议（指向可能的问题根源）
  2084|- 缩短排错路径
  2085|
  2086|### tuple 类型注解规范（2026-05-26 新增）
  2087|
  2088|**问题背景：**
  2089|- `tuple` 类型注解不够精确，无法表达元素类型
  2090|- Python 3.9+ 支持泛型元组 `tuple[str, ...]`
  2091|- 类型检查器无法推断元素类型
  2092|
  2093|**正确用法：**
  2094|```python
  2095|# ✅ 正确：使用泛型元组（Python 3.9+）
  2096|_EXTENDED_FACTOR_COLS: tuple[str, ...] = ('bollinger_pb', 'kdj_j', 'turnover_surge')
  2097|_BASE_COLS: tuple[str, ...] = ('date', 'asset', 'open', 'close', 'high', 'low')
  2098|
  2099|# ❌ 错误：类型注解不够精确
  2100|_EXTENDED_FACTOR_COLS: tuple = ('bollinger_pb', 'kdj_j', 'turnover_surge')  # 无法表达元素类型
  2101|```
  2102|
  2103|**原则：**
  2104|- 使用 `tuple[str, ...]` 表达字符串元组
  2105|- Python 3.9+ 支持泛型元组
  2106|- 类型检查器可推断元素类型
  2107|
  2108|### DataFrame 内存释放规范（2026-05-26 新增）
  2109|
  2110|**问题背景：**
  2111|- merge 完成后，源 DataFrame 仍驻留内存
  2112|- 直到函数结束才释放，内存占用持续
  2113|
  2114|**正确用法：**
  2115|```python
  2116|# ✅ 正确：merge 完成后立即释放
  2117|factor_df = factor_df.merge(turnover_df[['date', 'asset', 'turnover_rate']], ...)
  2118|del turnover_df  # merge 完成后立即释放
  2119|
  2120|# ❌ 错误：turnover_df 驻留内存直到函数结束
  2121|factor_df = factor_df.merge(turnover_df[['date', 'asset', 'turnover_rate']], ...)
  2122|# turnover_df 未释放，内存持续占用
  2123|```
  2124|
  2125|**适用场景：**
  2126|- merge 完成后源 DataFrame 不再需要
  2127|- 大数据量场景
  2128|- 内存敏感场景
  2129|
  2130|### docstring Example 规范（2026-05-26 新增）
  2131|
  2132|**问题背景：**
  2133|- Example 中的函数调用会实际执行完整流程
  2134|- 需要外部依赖（数据文件）才能运行
  2135|- doctest 会失败（缺少依赖）
  2136|
  2137|**正确用法：**
  2138|```python
  2139|# ✅ 正确：标记非运行示例
  2140|Example:
  2141|    # 以下为示例用法，非实际运行（generate_all_factors 需要输入数据文件）
  2142|    >>> from data_fetchers.factor_generator import generate_all_factors
  2143|    >>> metadata = generate_all_factors()  # 需要 data_fetchers/result/*.json.gz
  2144|
  2145|# ❌ 错误：未标记非运行示例（doctest 会失败）
  2146|Example:
  2147|    >>> from data_fetchers.factor_generator import generate_all_factors
  2148|    >>> metadata = generate_all_factors()  # 缺少数据文件，doctest 失败
  2149|```
  2150|
  2151|**原则：**
  2152|- 需要外部依赖的函数应标记非运行示例
  2153|- 补充依赖说明（需要哪些文件）
  2154|- 避免 doctest 失败
  2155|
  2156|### pandas 列选择规范（2026-05-26 新增）
  2157|
  2158|**问题背景：**
  2159|- pandas DataFrame 列选择使用元组有兼容性问题
  2160|- 元组可能被视为 MultiIndex 而非列名列表
  2161|- 需转换为列表才能正确选择列
  2162|
  2163|**正确用法：**
  2164|```python
  2165|# ✅ 正确：元组转列表
  2166|_OUTPUT_COLS: tuple[str, ...] = ('date', 'asset', 'open', 'close')
  2167|output_df = df[list(_OUTPUT_COLS)].copy()  # 元组转列表
  2168|
  2169|# ❌ 错误：直接使用元组（兼容性问题）
  2170|_OUTPUT_COLS: tuple[str, ...] = ('date', 'asset', 'open', 'close')
  2171|output_df = df[_OUTPUT_COLS].copy()  # 可能被视为 MultiIndex
  2172|
  2173|# ✅ 正确：迭代不受影响（for col in tuple 正常工作）
  2174|for col in _OUTPUT_COLS:  # 元组迭代正常
  2175|    if col not in df.columns:
  2176|        ...
  2177|```
  2178|
  2179|**原则：**
  2180|- DataFrame 列选择使用 `list(tuple)` 转换
  2181|- 元组迭代不受影响（for col in tuple 正常）
  2182|- 常量定义使用元组（防止修改），使用时转为列表
  2183|
  2184|### 类型注解兼容性规范（2026-05-26 新增）
  2185|
  2186|**问题背景：**
  2187|- 类型注解为 int，但实际可能传入 numpy.int64 或 float
  2188|- 静态类型检查器可能报警告
  2189|- Python 运行时不强制类型检查
  2190|
  2191|**正确用法：**
  2192|```python
  2193|# ✅ 正确：在 Note 中补充兼容类型说明
  2194|def _calc_pct(count: int, total: int) -> float:
  2195|    """
  2196|    ...
  2197|    Note:
  2198|        - 类型注解为 int，但实际接受 int、numpy.int64、float 等兼容类型
  2199|        - Python 运行时不强制类型检查，注解仅为静态分析提供参考
  2200|    """
  2201|
  2202|# ❌ 错误：未说明兼容类型（静态分析可能警告）
  2203|def _calc_pct(count: int, total: int) -> float:
  2204|    """..."""  # 未说明兼容类型
  2205|```
  2206|
  2207|**原则：**
  2208|- 类型注解为 int，但可接受兼容类型
  2209|- 在 Note 中补充兼容类型说明
  2210|- Python 运行时不强制类型检查
  2211|
  2212|### docstring Raises 规范（2026-05-26 新增）
  2213|
  2214|**问题背景：**
  2215|- docstring Raises 描述未实现的场景
  2216|- 与实际行为不符，误导调用方
  2217|
  2218|**正确用法：**
  2219|```python
  2220|# ✅ 正确：描述与实际一致
  2221|Raises:
  2222|    ValueError: 数据格式不正确（缺少 'data' 字段）、JSON 解析失败
  2223|
  2224|# ❌ 错误：描述未实现的场景
  2225|Raises:
  2226|    ValueError: ...、或输入数据为空  # 代码无对应检查，不会抛出
  2227|```
  2228|
  2229|**原则：**
  2230|- Raises 描述应与实际抛出一致
  2231|- 不应描述未实现的场景
  2232|- 删除不符合实际行为的描述
  2233|
  2234|### 兜底块异常信息规范（2026-05-26 新增）
  2235|
  2236|**问题背景：**
  2237|- 兜底块异常信息不完整
  2238|- 缺少异常类型和详情，难以追溯
  2239|
  2240|**正确用法：**
  2241|```python
  2242|# ✅ 正确：包含异常类型和详情
  2243|except Exception as e:
  2244|    raise RuntimeError(f"未知错误: {path}, {type(e).__name__}: {e}") from e
  2245|
  2246|# ❌ 错误：缺少异常类型和详情
  2247|except Exception as e:
  2248|    raise RuntimeError(f"未知错误: {path}") from e  # 缺少异常详情
  2249|```
  2250|
  2251|**原则：**
  2252|- 兜底块应包含异常类型（`type(e).__name__`）
  2253|- 包含异常详情（`str(e)`）
  2254|- 便于追溯问题根源
  2255|
  2256|### paths.py 使用规范
  2257|
  2258|### 强制规则
  2259|
  2260|```
  2261|❌ 目录下有 common/ 公共模块，脚本仍手写相同逻辑
  2262|❌ 公共模块已封装缓存读写，脚本自行实现 gzip 解压 + JSON 加载
  2263|❌ 公共模块已封装 API 调用，脚本自行实现 requests 请求
  2264|```
  2265|
  2266|### 正确做法
  2267|
  2268|```
  2269|✅ 开发前先检查 common/ 是否有可复用函数
  2270|✅ 公共模块已封装的逻辑，直接调用，不重复实现
  2271|✅ 仅实现数据源特有的逻辑（API 参数、数据转换）
  2272|```
  2273|
  2274|---
  2275|
  2276|## 输出目录规范
  2277|
  2278|### 缓存输出
  2279|
  2280|**所有数据拉取结果输出到 cache 目录，不输出到脚本同级目录。**
  2281|
  2282|| 数据类型 | 输出目录 | 文件格式 |
  2283||----------|---------|----------|
  2284|| 因子数据 | `data_fetchers/result/` | `factor_ic_data.json.gz` |
  2285|| 换手率数据 | `data_fetchers/result/` | `turnover_rate_data.json.gz` |
  2286|| 主力资金流 | `data_fetchers/result/` | `main_inflow_data.json.gz` |
  2287|
  2288|**禁止：**
  2289|```
  2290|❌ 输出到脚本同级目录（散乱，难管理）
  2291|❌ 输出到 data_fetchers/result/（临时元信息才用）
  2292|```
  2293|
  2294|### result 目录用途
  2295|
  2296|`data_fetchers/result/` 用于存储：
  2297|- 数据拉取元信息（拉取时间、数据范围、行数）
  2298|- 数据质量报告（缺失字段统计、异常值检测）
  2299|
  2300|### logs 目录用途
  2301|
  2302|`data_fetchers/logs/` 用于存储：
  2303|- 数据拉取日志（API 调用记录、错误日志）
  2304|- 因子生成日志（计算进度、耗时统计）
  2305|
  2306|**禁止：**
  2307|```
  2308|❌ 日志输出到项目根目录的 logs/（应输出到模块级 logs/）
  2309|❌ 日志文件与脚本同级（散乱，难管理）
  2310|```
  2311|
  2312|---
  2313|
  2314|## 统一因子生成模块
  2315|
  2316|### factor_generator.py
  2317|
  2318|**职责：** 生成所有因子数据到缓存，提供单一数据源。
  2319|
  2320|**位置：** `data_fetchers/factor_generator.py`
  2321|
  2322|**输出：** `data_fetchers/result/factor_ic_data.json.gz`
  2323|
  2324|### 支持的因子
  2325|
  2326|| 因子 | 列名 | 参数 | 数据依赖 |
  2327||------|------|------|---------|
  2328|| RSI | rsi_6 | period=6 | close |
  2329|| Volume_Ratio | volume_ratio_5 | window=5 | volume |
  2330|| Bollinger_PB | bollinger_pb | n=20, k=2.0 | close |
  2331|| KDJ_J | kdj_j | n=9, m1=3, m2=3 | close, high, low |
  2332|| Turnover_Surge | turnover_surge | window=5 | turnover_rate, close |
  2333|
  2334|### 输出结构
  2335|
  2336|```json
  2337|{
  2338|  "dates": ["2024-04-19", "2024-04-20", ...],
  2339|  "data": [
  2340|    {
  2341|      "date": "2024-04-19",
  2342|      "asset": "000001",
  2343|      "open": 10.71,
  2344|      "close": 10.69,
  2345|      "high": 10.82,
  2346|      "low": 10.66,
  2347|      "rsi_6": 64.42,
  2348|      "volume_ratio_5": 0.74,
  2349|      "bollinger_pb": null,
  2350|      "kdj_j": null,
  2351|      "turnover_surge": null
  2352|    },
  2353|    ...
  2354|  ]
  2355|}
  2356|```
  2357|
  2358|### 使用方式
  2359|
  2360|**CLI：**
  2361|```bash
  2362|python data_fetchers/factor_generator.py
  2363|```
  2364|
  2365|**Python：**
  2366|```python
  2367|import logging
  2368|from data_fetchers.factor_generator import generate_all_factors, get_module_logger
  2369|
  2370|# 使用模块默认 logger
  2371|metadata = generate_all_factors()
  2372|
  2373|# 使用自定义 logger
  2374|logger = logging.getLogger('my_app')
  2375|metadata = generate_all_factors(logger=logger)
  2376|```
  2377|
  2378|### 数据一致性验证
  2379|
  2380|factor_generator.py 的因子计算逻辑从 IC 脚本迁移：
  2381|- `calculate_bollinger_pb()` ← `ic_bollinger_pb_1d.py`
  2382|- `calculate_kdj_j()` ← `ic_kdj_j_1d.py`
  2383|- `calculate_turnover_surge()` ← `ic_turnover_surge_1d.py`
  2384|
  2385|**验证结果（2026-05-24）：**
  2386|- 均值差异 < 0.000001
  2387|- 有效数据数一致
  2388|- 因子计算逻辑完全一致
  2389|
  2390|---
  2391|
  2392|## 缓存格式
  2393|
  2394|### factor_data.json.gz（基础因子）
  2395|
  2396|**结构：**
  2397|```json
  2398|{
  2399|  "dates": ["2024-04-19", ...],
  2400|  "data": [
  2401|    {
  2402|      "date": "2024-04-19",
  2403|      "asset": "000001",
  2404|      "open": 10.71,
  2405|      "close": 10.69,
  2406|      "high": 10.82,
  2407|      "low": 10.66,
  2408|      "rsi_6": 64.42,
  2409|      "volume_ratio_5": 0.74
  2410|    },
  2411|    ...
  2412|  ]
  2413|}
  2414|```
  2415|
  2416|### factor_ic_data.json.gz（统一数据源）
  2417|
  2418|包含所有 5 个因子（见上方输出结构）。
  2419|
  2420|### turnover_rate_data.json.gz
  2421|
  2422|**结构：**
  2423|```json
  2424|{
  2425|  "data": [
  2426|    {
  2427|      "date": "2024-03-19",
  2428|      "asset": "000001",
  2429|      "turnover_rate": 0.6664
  2430|    },
  2431|    ...
  2432|  ]
  2433|}
  2434|```
  2435|
  2436|---
  2437|
  2438|## 因子计算参数规范
  2439|
  2440|### 参数默认值
  2441|
  2442|| 因子 | 参数 | 默认值 | 说明 |
  2443||------|------|--------|------|
  2444|| RSI | period | 6 | RSI 计算周期 |
  2445|| Volume_Ratio | window | 5 | 成交量均值窗口 |
  2446|| Bollinger_PB | n | 20 | 移动平均周期 |
  2447|| Bollinger_PB | k | 2.0 | 标差倍数 |
  2448|| KDJ_J | n | 9 | RSV 计算周期 |
  2449|| KDJ_J | m1 | 3 | K 值平滑周期 |
  2450|| KDJ_J | m2 | 3 | D 值平滑周期 |
  2451|| Turnover_Surge | window | 5 | 换手率均值窗口 |
  2452|
  2453|### 计算规范
  2454|
  2455|**遵循 PROJECT.md 规范：**
  2456|- 函数入口必须 `.copy()` 避免副作用
  2457|- 使用 `transform` 方法避免 pandas 3.0 索引问题
  2458|- 异常检测而非静默修正
  2459|- 使用 EPSILON 避免除零
  2460|
  2461|---
  2462|
  2463|## pandas 3.0 兼容性规范（2026-05-24 新增）
  2464|
  2465|**问题：**
  2466|```python
  2467|# ❌ 错误：pandas 3.0 返回 MultiIndex Series
  2468|middle = factor_df.groupby('asset', group_keys=False)['close'].rolling(window=n).mean()
  2469|factor_df['middle'] = middle  # TypeError: incompatible index
  2470|```
  2471|
  2472|**解决方案：**
  2473|```python
  2474|# ✓ 正确：使用 transform 返回 RangeIndex Series
  2475|middle = factor_df.groupby('asset', group_keys=False)['close'].transform(
  2476|    lambda x: x.rolling(window=n).mean()
  2477|)
  2478|factor_df['middle'] = middle  # 成功赋值
  2479|```
  2480|
  2481|**原因：**
  2482|- pandas 3.0 中，`groupby(group_keys=False).rolling()` 返回 MultiIndex Series
  2483|- 即使 `group_keys=False`，索引仍是 MultiIndex
  2484|- `transform` 返回与原 DataFrame 一致的 RangeIndex
  2485|
  2486|---
  2487|
  2488|## 模块边界规范
  2489|
  2490|**遵循 PROJECT.md 模块边界规范：**
  2491|
  2492|```
  2493|✓ factor_generator.py 独立运行（不依赖 factor_ic、backtest）
  2494|✓ 输出到 data_fetchers/result/
  2495|✓ 被 factor_ic 模块读取
  2496|```
  2497|
  2498|**禁止：**
  2499|```
  2500|❌ factor_generator.py 导入 factor_ic.common.*
  2501|  2501|❌ factor_generator.py 导入 backtest.common.*
  2502|```
  2503|
  2504|---
  2505|
  2506|## 流程文档配套规范
  2507|
  2508|**遵循 PROJECT.md"脚本配套文件规范"章节：**
  2509|
  2510|| 文件类型 | 位置 | 命名规则 | 示例 |
  2511||---------|------|---------|------|
  2512|| 流程文档 | `data_fetchers/docs/` | `<脚本名>_flow.md` | `factor_generator_flow.md` |
  2513|| 测试用例 | `data_fetchers/test_cases/` | `<脚本名>_test_cases.md` | `factor_generator_test_cases.md` |
  2514|
  2515|**新建脚本时：**
  2516|```
  2517|□ 创建脚本文件（如 fetch_xxx.py）
  2518|□ 同步创建流程文档（docs/fetch_xxx_flow.md）
  2519|□ 同步创建测试用例（test_cases/fetch_xxx_test_cases.md）
  2520|```
  2521|
  2522|---
  2523|
  2524|## 待补充内容
  2525|
  2526|```
  2527|□ 各脚本流程文档（docs/fetch_xxx_flow.md）
  2528|□ 各脚本测试用例（test_cases/fetch_xxx_test_cases.md）
  2529|□ 日期处理模块（common/date_utils.py，交易日判断、日期范围计算）
  2530|□ 数据验证模块（common/data_validator.py，字段完整性检查）
  2531|□ 增量更新策略规范
  2532|□ 数据质量检查自动化
  2533|□ 因子计算性能优化（大数据量测试）
  2534|
  2535|✓ 公共模块实现（paths.py、cache_manager.py、http_client.py、stock_utils.py）- 已完成 2026-05-24
  2536|```
  2537|
  2538|---
  2539|
  2540|*最后更新: 2026-05-25 10:30 北京时间*
  2541|---
  2542|
  2543|## factor_calculator.py 版本历史
  2544|
  2545|| 版本 | 时间 | 更新内容 |
  2546||-----|------|---------|
  2547|| v1.0 | 2026-05-27 17:00 | 初始创建：导入规范化、logger参数化（约束77）、类型注解精确化（约束76）、__all__修复（约束60）、docstring补全（Example章节） |
  2548|| v1.0 | 2026-05-27 17:00 | 配套文件：docs/factor_calculator_flow.md、test_cases/test_factor_calculator.py |
  2549|| v1.1 | 2026-05-27 19:30 | 第二轮深度优化：版本历史添加、常量命名私有化（DEFAULT_* → _DEFAULT_*）、__all__移到导入后位置 |
  2550|| v1.2 | 2026-05-27 20:00 | 第三轮深度优化：内部函数`_calculate_ewm_with_initial` docstring补全、新增私有常量（volume_ratio_window、forward_return_shift）、消除硬编码默认值 |
  2551|| v1.3 | 2026-05-27 21:00 | 第四轮深度优化：提取列名常量（6输入+3输出）、提取魔法数字常量（4个基准值+2个阈值）、消除硬编码字符串和魔法数字 |
  2552|
  2553|---
  2554|
  2555|*最后更新: 2026-05-27 17:00 北京时间*
  2556|