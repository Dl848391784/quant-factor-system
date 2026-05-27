# data_fetchers 模块规范

> 版本: v3.06
> 创建时间: 2026-05-19
> 更新时间: 2026-05-27 16:00 北京时间
> 重构时间: 2026-05-24（补充目录结构+命名规则+公共模块规范+公共模块实现）

---

## 快速参考

### 必须遵守的约束

**遵循 PROJECT.md"输出数据规范"章节的跨模块通用原则：**
- 输出结构必须统一
- 字段值不可为 None
- 结果输出到 result 目录

**本模块特定约束（16条）：**

||| # | 约束 | 说明 |
|---|------|------|
|| 1 | 脚本命名：`fetch_<数据源>.py` | 如 fetch_turnover.py、fetch_stock_list.py |
| 2 | 输出到 result 目录 | 与 factor_ic 等模块保持一致（cache 为数据源原始缓存） |
| 3 | 因子生成使用 factor_generator.py | 单一数据源，不分散 |
| 4 | 公共模块必须复用 | 禁止脚本自行实现已有功能 |
| 5 | pandas 3.0 使用 transform | 避免 rolling 返回 MultiIndex |
| 6 | 函数修改 DataFrame 需文档说明 | 在 Note 节说明就地修改的列（如 `astype(str)`），不强制 copy |
| 7 | 日志输出到 logs 目录 | 不散落在项目根目录 |
| 8 | 流程文档配套 | docs/<脚本名>_flow.md |
| 9 | N-way merge 去重使用正值 batch_idx | heap 元素为 `(key, batch_idx, counter, stream)`，counter 打破平局 |
| 10 | 大文件验证分两次读 | 第一次加载完整提取 meta+records_count并释放，第二次流式行扫描只解析抽样行 |
| 11 | meta 信息只保留标量 | date_start/date_end/n_assets，而非完整 dates_list/assets_list |
| 12 | 数据验证综合判断 | 不仅检查天数达标，还需检查关键字段非空比例 >= 80% |
| 13 | peek_key/pop_record 检查 exhausted | `if self.exhausted or self.idx >= len(self.records)`，语义一致性（两个方法对称） |
| 14 | is_exhausted 逻辑用 or | `return self.exhausted or self.idx >= len(self.records)`（而非 and） |
| 14 | get_memory_usage_mb Windows 兜底 | `import resource` 在 Windows 下会抛 ModuleNotFoundError，需 try-except 兜底返回 0.0 |
| 15 | main docstring 无 Returns | None 返回类型的函数不需要 Returns 节 |
| 16 | version 字段提取为常量 | 禁止硬编码版本号，提取为 `_OUTPUT_VERSION` 常量便于维护 |
| 17 | datetime.now() 只调用一次 | 固定时间戳后生成两个格式，避免不一致 |
| 18 | 抽样检查均匀抽样 | 避免 `[:1000]` 取前1000条偏差，改为均匀抽样 |
| 21 | N-way merge 显式收集后选最大 | 收集相同 key 所有记录后按 batch_idx 降序选最大，不依赖弹出顺序 |
| 22 | cleanup 增加兜底清理 | merged_*.json.gz 可能残留，cleanup_batch_files 应增加兜底 |
| 23 | 模块级注释合并到常量 | 注释应紧贴常量定义，避免空泛的注释块 |
| 24 | 变量初始化默认值 | 函数顶部初始化所有返回值变量，防止 NameError（包括 records_count） |
| 25 | meta 解析用 json.loads | 避免手动字符串匹配脆弱，分两次加载（先 meta 后 data） |
| 26 | 方法名语义清晰 | `_load_all` 表示一次性加载，而非 `_load_next_chunk` 暗示多次调用 |
| 27 | 返回值避免冗余 | format_final_output 返回值仅用于日志，统计信息由 validate_final_data 提供 |
| 28 | 函数接口契约说明 | 说明实际调用方行为，而非理想化"可以是 datetime 或字符串" |
| 29 | vmrss 判断用 is not None | `if vmrss is not None` 而非 `if vmrss`（0 是 falsy） |
| 31 | DataFrame 链式操作用 copy() | 避免 SettingWithCopyWarning，每次过滤后 .copy() |
| 33 | 函数签名与调用一致 | 返回 None 则调用方不接收，返回 tuple 则调用方接收，避免返回值被丢弃 |
| 36 | BatchStream 提供 __lt__ | 用于 heap 比较，防御性编程 |
| 37 | pop_record 更新 exhausted | 弹出后立即更新状态，保持一致性 |
| 38 | del 注释准确描述 | "减少引用计数"而非"释放内存"（真正释放依赖 GC） |
| 39 | sort_values 后 copy() | 避免 CoW 风险，链式操作用 copy() |
| 40 | del 释放顺序正确 | del data 后 del full，而非只 del full |
| 42 | 一次遍历提取元信息 | 避免 min/max/set 四次遍历，一次遍历同时收集 date_set/asset_set/first_date/last_date |
| 43 | set 内存立即释放 | 提取完元信息后立即 del date_set, asset_set |
| 44 | 合并路径双校验 | factor_merged_path 和 return_merged_path 都校验，避免 None 路径触发 TypeError |
| 45 | 返回值与调用方一致 | 未使用的返回值不计算，函数签名与调用方匹配（避免 `_` 接收） |
| 46 | 流式验证不加载 data | 第一次只读 meta（手动解析），第二次流式扫描边计数边抽样 |
| 47 | 变量定义位置合理 | 避免重复赋值（如 n_records 定义一次，注释说明用途） |
| 48 | mkdir 目录与输出路径一致 | 确保目录创建用正确的路径常量（如 RESULT_DIR 而非 CACHE_DIR） |
| 49 | docstring 类型描述与签名一致 | 函数签名改为 dict，docstring Returns 也需同步修改 |
| 50 | 异常日志包含类型名 | `[{type(e).__name__}]: {e}` 格式便于追溯 |
| 51 | 导入在模块顶部 | PEP 8 规范，不在函数内导入（如 Counter） |
| 52 | 原子写入异常处理 | try-except 包裹，失败时 unlink(missing_ok=True) 清理 |
| 53 | __all__ 导出列表 | 公共模块明确导出接口 |
| 54 | 数据映射添加注释 + TODO | 近似映射需说明用途 + 补充 TODO + 参考链接 |
| 55 | 原子写入捕获所有异常 | except Exception（而非仅 OSError），保证 .tmp 清理 |
| 56 | 日志位置在操作成功后 | rename 成功后才打印日志（而非 try 块外） |
| 57 | 全局缓存线程安全（DCL） | threading.Lock + 双重检查锁，避免重复加载 |
| 58 | 异常捕获需打印详情 | 静默 pass 改为 warning 日志，包含异常值 `{value!r}: {e}` |
| 59 | 关键词映射避免歧义 | 检查关键词是否在多个行业重复，移除或改为具体关键词 |
| 60 | __all__ 不含私有名称 | 以 `_` 开头的名称表示模块私有，不应放入 __all__ |
| 61 | DataFrame 列名校验 | API 返回列名可能变化，需校验必需列存在（防御性编程） |
| 62 | 路径提取常量 + 参数注入 | 避免跨模块硬编码耦合，提取为常量或通过参数注入 |
| 63 | 导入语句不散落 | import 只在模块顶部，不在函数/类定义之间（PEP 8） |
| 64 | 关键词映射消除重复 | 每个关键词只出现在一个行业，避免遍历顺序导致匹配错误 |
| 65 | 注释与代码一致 | 修正误导性注释，确保注释描述与实际代码匹配 |
| 66 | 备用数据写入缓存 | 避免 akshare 不可用时每次重复读文件，备用数据写入缓存 |
| 67 | 缓存刷新失败降级 | 过期缓存刷新失败时降级使用旧缓存（而非直接返回备用数据） |
| 68 | 数据映射注释说明具体 | 注释说明映射来源/依据（而非仅"近似映射"），移除 TODO（要么修正要么映射到其他） |
| 69 | 文档注释与实现一致 | docstring 描述实际实现逻辑（如"名称关键词推断"而非"代码特征"） |
| 70 | 注释诚实化 | 未核对官方标准需诚实说明，不编造来源（如"化学原料+化学制品"），恢复 TODO |
| 71 | 映射核对官方标准 | 核对官方标准后修正映射，不存在的一级代码映射到 '其他'（而非猜测编造） |
| 72 | 备用缓存写入策略（非致命） | 备用缓存写入失败为非致命错误（warning），主缓存失败抛异常，需在设计文档中明确说明 |
| 73 | 日志信息准确反映流程 | 日志说明实际流程（如"akshare获取失败，尝试本地备用数据"而非"返回空映射"） |
| 74 | 缓存数据完整性验证 | 检查 industries 是否为 dict 类型（防止缓存损坏导致后续 AttributeError） |
| 75 | 模糊匹配优先级说明 | 关键词推断需在 Note 中说明模糊匹配优先级（如"中信银行"→证券） |
|| 76 | 返回类型注解完整 | 所有公共函数返回值需标注完整类型（如 `dict[str, int]`） |
|| 77 | logger参数命名规范 | 公共函数日志参数使用 `logger_arg` 避免遮蔽模块级 `logger`，内部变量用 `_logger = logger_arg or logger` |
|| 78 | session资源管理 | HTTP session 必须使用 `with` 语句确保连接池释放，禁止裸创建 |
|| 79 | ST股票检测前缀匹配 | 使用 `startswith('ST')` 而非 `'ST' in name`，避免"东ST"正常股票被误判剔除 |
|| 80 | 临时文件使用 tempfile | 使用 `tempfile.NamedTemporaryFile` 避免多进程并发冲突，禁止 `.with_suffix('.tmp')` |
|| 81 | 增量更新同步 name 字段 | API 返回的 name 可能是最新的，增量更新时需同步更新已存在股票的 name |
|| 82 | Optional 变量添加类型守卫 | 使用前添加 None 检查（`if data is None: raise`），确保类型安全 |
|| 83 | 验证逻辑与筛选逻辑一致 | validate_cache 必须使用与 is_valid_main_board_stock 一致的 ST 检查逻辑（前缀匹配） |
|| 84 | 重试循环内直接控制流 | 删除 success 变量，成功 break，失败在最后一次重试 raise，避免冗余检查 |
|| 85 | Optional 变量添加 assert | 使用前添加 `assert isinstance(var, expected_type)`，确保类型安全（比单独检查 None 更严格） |
|| 86 | 长列表字段截断 | removed_codes 等可能很长的列表字段限制最多50个，添加 truncated 字段说明是否截断 |
|| 19 | 常量定义在 import 之后 | PEP 8 顺序：docstring → __future__ → 标准库 → 第三方 → 本地 → 常量 |
|| 20 | cleanup_batch_files 用 try/except | 捕获异常继续清理，而非 try/finally（保证尽可能清理） |

### 关键函数签名

|| 函数 | 文件 | 用途 |
|------|------|------|
| `generate_all_factors(logger)` | factor_generator.py | 生成所有因子数据 |
| `calculate_rsi(df, period)` | factor_calculator.py | 计算 RSI 因子 |
| `calculate_bollinger_pb(df, n, k)` | factor_calculator.py | 计算布林带 %B 因子 |
| `calculate_kdj_j(df, n, m1, m2)` | factor_calculator.py | 计算 KDJ_J 因子 |
| `calculate_turnover_surge(df, window)` | factor_calculator.py | 计算换手率突增因子 |
| `n_way_merge_deduplicate(batches, type)` | batch_processor.py | N-way 合并批次数据 |
| `fetch_turnover_data()` | fetch_turnover.py | 拉取换手率数据 |

---

## 目录结构

```
data_fetchers/
├── MODULE.md           # 本文件（模块规范）
├── common/             # 公共函数
│   ├── __init__.py
│   ├── logger_config.py # 日志配置
│   ├── paths.py         # 路径配置
│   ├── cache_manager.py # 缓存管理
│   ├── http_client.py   # HTTP 客户端
│   ├── stock_utils.py   # 股票筛选
│   ├── memory_utils.py  # 内存监控（2026-05-27新增）
│   └── dataframe_utils.py # DataFrame 验证（2026-05-27新增）
│
├── docs/               # 流程文档
│   ├── plans/           # 重构计划（2026-05-27新增）
│   ├── factor_generator_flow.md
│   └── fetch_<数据源>_flow.md
│
├── result/             # 数据拉取结果输出（元信息）
│   └── .gitkeep
│
├── logs/               # 日志目录
│   └── .gitkeep
│
├── test_cases/         # pytest 测试文件（2026-05-27更新）
│   ├── __init__.py
│   └── test_<脚本名>.py  # pytest 可执行文件
│
├── factor_generator.py # 统一因子生成入口
├── factor_calculator.py # 统一因子计算（2026-05-27新增）
├── batch_processor.py   # 批次处理+N-way合并（2026-05-27新增）
├── fetch_turnover.py   # 换手率数据拉取
├── fetch_stock_list.py # 股票列表拉取
├── fetch_industry.py   # 行业分类拉取
└── fetch_factor_cache.py # 因子缓存管理
```

---

## 更新记录

1. v1.0（2026-05-19）：首次创建模块规范
2. v1.1（2026-05-24 15:22）：
   - 新增"统一因子生成模块"章节
   - 新增 factor_generator.py 规范
   - 新增 pandas 3.0 兼容性规范
3. v2.0（2026-05-24 17:59）：
   - **目录结构规范化**：创建 common/、docs/、result/、logs/、test_cases/
   - **补充快速参考表格**：8条约束 + 关键函数签名
   - **补充脚本命名规则**：`fetch_<数据源>.py`
   - **补充公共模块架构**：common/ 目录规范
   - **补充公共模块强制复用规范**
   - **补充输出目录规范**：result/、logs/ 目录职责
   - **补充版本历史**：记录每次变更
4. v2.1（2026-05-24 18:05）：
   - **创建公共模块**：paths.py、cache_manager.py、http_client.py、stock_utils.py
   - **公共模块架构更新**：从"待创建"状态改为"已实现"
   - **新增 common/README.md**：公共模块使用文档
5. v2.2（2026-05-24 20:35）：
   - **cache_manager.py 优化**：接收 logger 参数（遵循 PROJECT.md 第783-857行规范）
   - **新增 cache_manager.py 日志参数规范**：使用方式、参数类型、禁止行为
   - **JSON 解析异常处理**：避免内存翻倍（参考 backtest-module-optimization-patterns.md）
   - **参数类型支持**：`path` 支持 `Path | str`
6. v2.3（2026-05-24 21:10）：
   - **函数命名修复**：`_get_logger` → `get_module_logger`（遵循命名规范）
   - **get_cache_file_info 日志使用**：添加 DEBUG/WARNING 日志输出
   - **流程文档创建**：docs/cache_manager_flow.md
   - **测试用例创建**：test_cases/cache_manager_test_cases.md
7. v2.4（2026-05-24 21:40）：
   - **代码重复消除**：新增 `_read_cache_impl`、`_write_cache_impl` 公共函数
   - **文件类型判断优化**：新增 `_is_gzip_file` 函数统一判断
   - **重构读写函数**：read_gzip_cache/read_json_cache/write_gzip_cache/write_json_cache 调用公共实现
   - **append_to_cache 重构**：使用 `_is_gzip_file` 和公共实现函数
   - **代码行数减少**：从 322行 → 272行（减少 50行）
   - **流程文档更新**：版本历史 v1.2，架构图新增公共函数
8. v2.5（2026-05-24 21:45）：
   - **类型注解修复**：`new_data: list` → `List[Any]`（符合 Python 类型规范）
   - **防御性编程**：append_to_cache 添加数据类型验证 + WARNING 日志
   - **__all__ 导出**：明确定义公共API（7个函数）
   - **测试代码增强**：新增 append_to_cache + 错误场景 + 防御性编程测试
   - **流程文档更新**：版本历史 v1.3
9. v2.6（2026-05-24 21:50）：
   - **统一缓存 API**：新增 `read_cache`、`write_cache`（自动判断 gzip/json）
   - **辅助函数**：新增 `cache_exists`、`delete_cache`（缓存存在性检查 + 删除）
   - **大文件监控**：新增 `_LARGE_FILE_THRESHOLD_MB = 100`，>100MB 触发 WARNING
   - **__all__ 更新**：新增 4 个函数（11个公共API）
   - **测试代码增强**：新增统一 API + 辅助函数测试
   - **流程文档更新**：版本历史 v1.4
10. v2.7（2026-05-24 21:55）：
   - **gzip 压缩级别控制**：新增 `compresslevel` 参数（默认 6，平衡压缩率和速度）
   - **JSON 序列化格式选项**：新增 `json_indent`、`json_sort_keys` 参数
   - **缓存数据类型验证**：`_write_cache_impl` 添加非字典类型 WARNING 日志
   - **新增模块级常量**：`_DEFAULT_GZIP_COMPRESSLEVEL`、`_JSON_COMPACT_SEPARATORS`、`_JSON_READABLE_INDENT`
   - **更新所有写入函数签名**：`write_gzip_cache`、`write_json_cache`、`write_cache` 新增参数
   - **测试代码增强**：新增压缩级别 + 可读格式测试
   - **流程文档更新**：版本历史 v1.5
11. v2.8（2026-05-24 22:20）：
   - **异常处理精确化**：捕获 `BadGzipFile`、`PermissionError`、`OSError`
   - **空文件处理**：大小为 0 返回空字典 {}
   - **__init__.py 导出修复**：新增 `get_module_logger`、`read_cache`、`write_cache`、`cache_exists`、`delete_cache` 导出
   - **测试用例同步**：新增 TC022-TC024（gzip 损坏、空文件、权限错误）
   - **流程文档更新**：版本历史 v1.6
12. v2.9（2026-05-24 22:40）：
   - **测试代码日志规范化**：替换 24处 print 为 logger.info/logger.debug
   - **新增 setup_test_logger 函数**：遵循 PROJECT.md 第780-839行规范
   - **日志文件输出**：data_fetchers/logs/cache_manager_YYYY-MM-DD.log
   - **导入 datetime**：setup_logger 需要
   - **流程文档更新**：版本历史 v1.7
13. v2.10（2026-05-24 22:50）：
   - **创建 logger_config.py**：遵循 PROJECT.md 第780-839行规范
   - **定义 setup_logger 函数**：可被所有模块复用
   - **复用 setup_logger**：cache_manager.py __main__ 复用 logger_config.py 的 setup_logger
   - **删除 setup_test_logger**：避免重复定义，遵循 DRY 原则
   - **__init__.py 导出新增**：`setup_logger`
   - **流程文档更新**：版本历史 v1.8

14. v2.11（2026-05-24 23:00）：
   - **测试用例版本同步**：新增 v1.5/v1.6 版本历史
   - **新增 TC025**：setup_logger 测试用例
   - **删除冗余汇总表**：测试用例文档精简
   - **时间标注修复**：流程文档 v1.8 时间改为 22:50
   - **流程文档更新**：版本历史 v1.9

15. v2.12（2026-05-24 23:10）：
   - **发现 bug**：get_module_logger 缺少 global 声明
   - **修复 UnboundLocalError**：添加 `global _MODULE_LOGGER`
   - **新增 TC026**：get_module_logger global 声明测试
   - **流程文档更新**：版本历史 v1.10

16. v2.13（2026-05-24 23:20）：
   - **删除冗余导入**：datetime 导入未使用（只在注释中引用）
   - **测试用例版本同步**：v1.7 → v1.10
   - **流程文档更新**：版本历史 v1.11

17. v2.14（2026-05-25 00:10）：
   - **类型注解修复**：`_write_cache_impl` 参数 `data` 类型从 `Dict[str, Any]` 改为 `Any`（与实际实现一致）
   - **冗余代码消除**：`append_to_cache` 移除第373行重复的 `path.exists()` 检查
   - **规范补充**：新增"缓存文件格式限制"说明（必须是 JSON 格式）
   - **修复原因**：代码审查发现类型注解与实现不一致、冗余检查

18. v2.15（2026-05-25 00:30）：
   - **线程安全修复**：`_MODULE_LOGGER` 改为模块加载时直接初始化（避免延迟初始化的多线程竞争）
   - **docstring 补充 Raises**：`append_to_cache` 新增异常说明
   - **文档示例完善**：`delete_cache` Example 补充文件不存在场景
   - **测试清理健壮化**：`__main__` 使用 try/finally 确保测试文件清理
   - **修复原因**：代码审查发现线程安全、文档完整性、测试健壮性问题

19. v2.16（2026-05-25 01:00）：
   - **http_client.py 优化**：遵循 PROJECT.md 公共模块规范
   - **logger 参数化**：新增 `get_module_logger` 函数 + 所有函数接收 logger 参数
   - **__all__ 导出**：明确定义 6 个公共 API
   - **模块级导入**：`import time` 从函数内移至模块级
   - **类型注解修复**：`Exception | None` → `Optional[Exception]`、`Dict` → `Dict[str, Any]`
   - **docstring 补充**：新增 Raises 说明（TypeError、HTTPError、JSONDecodeError）
   - **__main__ 日志规范**：print → logger + try/finally + Session.close()
   - **修复原因**：公共模块规范合规化（与 cache_manager.py 保持一致）

20. v2.17（2026-05-25 01:30）：
   - **http_client.py 第二轮优化**：深度审查修复
   - **异常处理精确化**：区分 HTTPError/Timeout/ConnectionError/JSONDecodeError，避免宽泛捕获
   - **异常链保留**：RuntimeError 使用 `from last_error` 保留原始异常类型
   - **便捷函数参数补全**：`create_eastmoney_session`/`create_sina_session` 新增 logger 参数
   - **__all__ 导出补充**：新增 `get_module_logger`（与 cache_manager.py 一致）
   - **timeout 类型注解扩展**：支持 `(connect_timeout, read_timeout)` 元组
   - **Retry 参数重构**：提取公共参数 `retry_params`，减少 try/except 内重复代码
   - **import json 补充**：request_with_retry 需要 JSONDecodeError
   - **response 变量初始化**：避免 except 分支未绑定错误
   - **修复原因**：异常处理类型不一致、类型注解不完整、API 参数缺失

21. v2.18（2026-05-25 02:00）：
   - **http_client.py 第三轮优化**：与 cache_manager.py 对比分析
   - **docstring Example 补充**：4 个公共函数新增使用示例
   - **返回类型注解修复**：`request_with_retry` 返回 `Dict[str, Any]` → `Any`（JSON 可为任意类型）
   - **模块级常量补全**：新增 7 个 `_DEFAULT_*` 私有常量（保持风格一致）
   - **请求头数据来源注释**：补充"浏览器开发者工具抓包，2026-05-24"和用途说明
   - **__main__ 测试增强**：5 项测试覆盖（Session 创建、自定义配置、logger、常量）
   - **函数默认参数重构**：使用 `_DEFAULT_*` 常量替代硬编码数字
   - **修复原因**：文档示例缺失、类型注解不精确、常量风格不一致

22. v2.19（2026-05-25 02:30）：
   - **http_client.py 第四轮优化**：深度审查完善
   - **模块注释版本历史**：新增 v1.0-v1.3 版本演进说明（与 cache_manager.py 一致）
   - **get_module_logger Example 补充**：新增 fallback logger 和调用方 logger 示例
   - **重试状态码常量定义**：新增 `_DEFAULT_RETRY_STATUS_CODES`（注释说明各状态码含义）
   - **HTTP 方法参数扩展**：新增 `allowed_methods` 参数支持 POST 等方法重试
   - **便捷函数 Raises 补充**：create_eastmoney_session/create_sina_session 新增异常说明
   - **User-Agent 版本更新注释**：补充"每季度检查更新"提示
   - **__main__ 测试扩展**：新增测试 6（allowed_methods 参数）+ 异常测试说明
   - **修复原因**：版本历史缺失、重试方法硬编码、文档不完整

23. v2.20（2026-05-25 03:00）：
   - **http_client.py 第五轮优化**：修复 4 个关键问题
   - **最后一次失败日志补全**：Timeout/ConnectionError 分支最后一次失败新增警告日志
   - **request_with_retry 方法参数**：新增 `method` 参数支持 GET/POST/PUT/DELETE
   - **退避策略文档化**：docstring 明确说明"线性递增退避策略"及适用场景
   - **create_retry_session 默认 headers 修复**：默认 None（不再使用东财请求头），调用方必须显式传入
   - **__main__ 测试扩展**：新增测试 7（headers=None）+ 测试 8（method 参数验证）
   - **修复原因**：代码bug（日志缺失、默认headers不合理）、规范遗漏（方法参数缺失、退避策略未说明）

24. v2.21（2026-05-25 21:30）：
   - **http_client.py 第六轮优化**：安全性修复（5 个问题）
   - **JSON 解析异常捕获补全**：同时捕获 `json.JSONDecodeError` 和 `requests.exceptions.JSONDecodeError`
   - **Retry 异常缩小捕获范围**：只捕获 allowed_methods 参数错误，其他 TypeError 正常抛出
   - **response.text 安全访问**：使用 `getattr` 避免 streaming 模式问题，空字符串正确显示 N/A
   - **DEFAULT_*_HEADERS 不可变**：使用 `MappingProxyType` 包装，防止外部修改影响所有调用
   - **headers 类型注解修复**：`Dict[str, str]` → `Mapping[str, str]`（支持 MappingProxyType）
   - **__main__ 测试重构**：移除私有常量测试，改为验证公共常量不可变性
   - **修复原因**：代码bug（异常捕获不完整、安全访问缺失、可变常量）、规范遗漏（测试代码不规范）

25. v2.22（2026-05-25 21:35）：
   - **cache_manager.py 第七轮优化**：原子写入修复（3 个问题）
   - **错误信息精确化**：区分 gzip/json 文件，显示"gzip JSON 文件内容解析失败"而非"JSON解析失败"
   - **原子写入实现**：`_write_cache_impl` 使用临时文件 + `os.replace` 原子替换
   - **append_to_cache 原子化**：受益于 `_write_cache_impl` 原子写入，写入中途崩溃不再丢失数据
   - **失败清理机制**：写入失败时自动删除临时文件，避免残留
   - **版本历史补全**：cache_manager.py 新增 v1.0-v1.12 版本演进说明
   - **修复原因**：代码bug（错误信息误导、非原子操作风险、失败留损坏文件）

26. v2.23（2026-05-25 21:40）：
   - **stock_utils.py 优化**：遵循 PROJECT.md 公共模块规范
   - **logger 参数化**：新增 `get_module_logger` 函数 + `load_main_board_stock_list` 接收 logger 参数
   - **verbose 参数改为 logger**：`verbose: bool` → `logger: Optional[logging.Logger]`
   - **__all__ 导出**：明确定义 9 个公共 API（6 个函数 + 3 个常量）
   - **模块级导入优化**：`load_main_board_stock_list` 使用条件导入（__main__ 绝对导入，其他相对导入）
   - **docstring 补充**：所有函数新增 Example，`is_main_board_stock` 补充剔除规则示例
   - **__main__ 测试规范化**：print → logger + try/finally + setup_logger + 7 项测试
   - **常量导出**：`MAIN_BOARD_PREFIXES`、`EXCLUDED_PREFIXES`、`EXCLUDED_NAME_KEYWORDS` 导出为公共 API
   - **版本历史补全**：stock_utils.py 新增 v1.0-v1.1 版本演进说明
   - **修复原因**：公共模块规范合规化（logger 参数化、__all__ 导出、测试规范化）

27. v2.24（2026-05-25 21:41）：
   - **stock_utils.py 第二轮优化**：深度审查优化
   - **类型注解精确化**：`List[Dict]` → `List[Dict[str, Any]]`
   - **条件导入缓存**：模块级缓存导入函数，避免每次调用判断 `__name__`
   - **性能优化**：`is_main_board_stock` 使用 `any()` 替代 for 循环
   - **防御性编程**：
     - `is_main_board_stock` 空值返回 False
     - `get_stock_codes_only` 过滤空代码 + WARNING 日志
     - `get_stock_name_map` 过滤空代码和空名称 + WARNING 日志
     - `filter_stocks_by_date` 参数验证 + DEBUG 日志
   - **类型灵活性**：`load_main_board_stock_list` 支持 `Union[Path, str]`
   - **测试扩展**：8项测试（含边界测试）
   - **版本历史补全**：stock_utils.py 新增 v1.2 版本演进说明
   - **修复原因**：代码bug（条件导入效率低、空值处理缺失）+ 规范遗漏（类型注解不精确）

28. v2.25（2026-05-25 21:45）：
   - **stock_utils.py 第三轮优化**：辅助函数性能 + 验证补全
   - **辅助函数性能优化**：`get_stock_codes_only`、`get_stock_name_map`、`filter_stocks_by_date` 使用列表推导式
   - **日期范围验证**：`filter_stocks_by_date` 新增 `start_date <= end_date` 检查
   - **常量数据来源注释**：主板/剔除前缀/ST关键词补全数据来源（中国证券交易所规则）
   - **空列表边界检查**：所有辅助函数新增空列表检查 + DEBUG 日志
   - **docstring Raises 补全**：`get_stock_codes_only`、`get_stock_name_map` 补充 TypeError
   - **日志信息精确化**：WARNING 日志补充"总数 X，有效 Y"
   - **测试扩展**：8项测试（含空列表边界 + 日期范围验证）
   - **版本历史补全**：stock_utils.py 新增 v1.3 版本演进说明
   - **修复原因**：规范遗漏（数据来源注释缺失、日期范围验证缺失、边界检查缺失）

29. v2.26（2026-05-25 21:50）：
   - **stock_utils.py 第四轮优化**：类型安全 + 日期格式验证
   - **筛选逻辑优化**：`load_main_board_stock_list` 使用列表推导式筛选主板股票
   - **类型安全检查**：`get_stock_codes_only`、`get_stock_name_map`、`filter_stocks_by_date` 新增 `isinstance(stock_list, list)` 检查
   - **日期格式正则验证**：新增 `_DATE_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}$')` 精确验证 YYYY-MM-DD
   - **重复调用优化**：辅助函数改为 for 循环 + 变量缓存，避免列表推导式重复调用 `stock.get('code', '')`
   - **空数据处理**：`load_main_board_stock_list` 新增空股票列表检查 + WARNING 日志
   - **docstring Example 格式统一**：移除注释，统一使用 `>>>` 格式
   - **测试扩展**：8项测试（含类型验证 + 日期格式正则验证）
   - **版本历史补全**：stock_utils.py 新增 v1.4 版本演进说明
   - **修复原因**：代码bug（类型安全未实现）+ 规范遗漏（日期格式验证不够严格）

30. v2.27（2026-05-25 21:57）：
   - **stock_utils.py 第五轮优化**：参数类型安全 + 线程安全 + 日期边界验证
   - **参数类型安全检查**：`is_main_board_stock` 新增 `isinstance(code, str)` 和 `isinstance(name, str)` 检查
   - **线程锁保护**：`_get_imported_functions` 使用双重检查锁定模式（DCL）避免多线程竞争
   - **日期边界验证**：新增 `_MIN_DATE = '1990-12-19'`（A股市场始于1990）和 `_MAX_DATE = datetime.now()` 验证
   - **数据格式验证**：`load_main_board_stock_list` 新增 `isinstance(data, dict)` 检查
   - **常量不可变性注释**：`MAIN_BOARD_PREFIXES`、`EXCLUDED_PREFIXES`、`EXCLUDED_NAME_KEYWORDS` 补充"使用元组确保不可变"注释
   - **docstring Example 格式统一**：`get_module_logger` 从注释改为 `>>>` 格式
   - **docstring Raises 补全**：`is_main_board_stock` 补充 TypeError 说明
   - **测试扩展**：8项测试（含参数类型验证 + 日期边界验证）
   - **版本历史补全**：stock_utils.py 新增 v1.5 版本演进说明
   - **修复原因**：代码bug（参数类型安全未实现、线程竞争）+ 规范遗漏（日期边界验证缺失、常量不可变性注释缺失）

6. **stock_utils.py v1.6 (2026-05-25)** — 第六轮深度优化
   - **日期边界动态获取**：`_MAX_DATE` 改为 `MAX_STOCK_DATE()` 函数（避免长时间运行程序过期）
   - **日期常量公开**：`_MIN_DATE` → `MIN_STOCK_DATE`（公开常量，供外部查询）
   - **异常链保留**：`load_main_board_stock_list` 使用 `from e` 保留原始异常链
   - **元素类型安全检查**：3个辅助函数新增 `isinstance(stock, dict)` 检查，过滤非字典元素
   - **stocks列表类型验证**：`load_main_board_stock_list` 新增 `isinstance(stocks, list)` 检查
   - **docstring TypeError示例格式**：使用 `# doctest: +IGNORE_EXCEPTION_DETAIL` 规范格式
   - **测试扩展**：元素类型过滤验证测试（验证过滤行为而非抛异常）
   - **版本历史补全**：stock_utils.py 新增 v1.6 版本演进说明
   - **修复原因**：代码bug（日期边界过期风险、元素类型安全未实现）+ 规范遗漏（异常链未保留、docstring示例格式不规范）

7. **stock_utils.py v1.7 (2026-05-25)** — 第七轮深度优化
   - **logger 参数类型验证**：`get_module_logger` 新增 `isinstance(logger, logging.Logger)` 检查
   - **缓存函数 None 检查**：`load_main_board_stock_list` 新增 `_read_json_cache is None` 和 `_get_stock_list_file is None` 检查
   - **docstring Example 格式规范**：辅助函数 Example 补充返回值显示（`>>> codes` 和 `>>> name_map`）
   - **测试代码注释缩进修复**：`# 测试 8` 移到正确位置
   - **测试清理逻辑补全**：`finally` 块新增日志处理器关闭和移除
   - **logger 类型验证测试**：新增 logger 参数类型错误测试
   - **版本历史补全**：stock_utils.py 新增 v1.7 版本演进说明
   - **修复原因**：代码bug（缓存函数 None 未检查、测试代码缩进错误）+ 规范遗漏（logger 参数类型未验证、docstring Example 格式不规范）

8. **stock_utils.py v1.8 (2026-05-25)** — 第八轮深度优化
   - **filter_stocks_by_date Note 补充**：补充 Note 章节"自动过滤非字典元素和日期字段为空的元素"，与其他辅助函数保持一致
   - **测试清理顺序修复**：先打印"测试清理完成"再关闭处理器（避免日志丢失）
   - **http_client.py 同步更新**：get_module_logger 新增类型验证（与 stock_utils.py 保持一致）
   - **版本历史补全**：stock_utils.py 新增 v1.8 版本演进说明，http_client.py 新增 v1.5 版本演进说明
   - **修复原因**：代码bug（测试清理顺序导致日志丢失）+ 规范遗漏（filter_stocks_by_date 缺少 Note、http_client.py get_module_logger 未同步）

9. **stock_utils.py v1.9 (2026-05-25)** — 第九轮深度优化
   - **导入顺序 PEP 8 合规化**：标准库导入按字母顺序排列（json, logging, re, threading）
   - **MAX_STOCK_DATE Note 补充**：补充 Note 章节"动态获取当前日期，长时间运行程序不会过期"
   - **load_main_board_stock_list Raises 补全**：补充 RuntimeError（缓存函数未初始化）和 TypeError（logger 参数类型错误）
   - **load_main_board_stock_list Note 补充**：补充 Note 章节"自动使用缓存路径、空股票列表返回空列表并打印警告"
   - **版本历史补全**：stock_utils.py 新增 v1.9 版本演进说明
   - **修复原因**：规范遗漏（导入顺序不规范、MAX_STOCK_DATE 缺少 Note、load_main_board_stock_list Raises 不完整）

10. **stock_utils.py v1.10 (2026-05-25)** — 第十轮深度优化
   - **is_main_board_stock docstring 中文逗号修复**：`),必须` → `），必须`（与其他 docstring 保持一致）
   - **辅助函数 Raises 精确化**：移除"元素不是字典类型"描述（实际是过滤而非抛异常）
   - **_get_imported_functions() 调用合并**：load_main_board_stock_list 统一在函数开头初始化（避免重复调用）
   - **load_main_board_stock_list 非字典元素统计补全**：新增 invalid_elements 统计 + WARNING 日志（与其他辅助函数保持一致）
   - **版本历史补全**：stock_utils.py 新增 v1.10 版本演进说明
   - **修复原因**：代码bug（重复调用效率低、非字典元素统计缺失）+ 规范遗漏（docstring 格式不规范、Raises 描述不精确）

11. **stock_utils.py v2.0 (2026-05-25)** — 第十一轮深度优化（重大重构）
   - **DCL模式简化**：移除 `_get_imported_functions()` 双重检查锁定模式，改为模块级条件导入（if __name__ == '__main__'）
   - **MAX_STOCK_DATE 命名改为 get_max_stock_date**：遵循最小惊讶原则（函数命名以 get_ 开头），保留 MAX_STOCK_DATE 别名向后兼容
   - **get_stock_codes_only 空代码统计修复**：改用直接计数 empty_codes（而非减法计算 total_count - valid_count - invalid_elements）
   - **filter_stocks_by_date date_value 格式验证补全**：新增 `_DATE_PATTERN.match(date_value)` 检查 + invalid_dates 统计 + WARNING 日志
   - **移除 threading 导入**：不再需要线程锁保护
   - **__all__ 导出更新**：新增 `get_max_stock_date`，保留 `MAX_STOCK_DATE` 别名（deprecated）
   - **版本历史补全**：stock_utils.py 新增 v2.0 版本演进说明
   - **修复原因**：代码bug（DCL模式复杂、空代码统计逻辑混乱、date_value 缺少格式验证）+ 规范遗漏（MAX_STOCK_DATE 命名违反最小惊讶原则）

12. **stock_utils.py v2.1 (2026-05-25)** — 第十二轮深度优化
   - **excluded_count 统计精确化**：只包含非主板股票（不含非字典元素），避免重复统计
   - **日期合法性验证**：新增 `_validate_date()` 函数使用 `datetime.strptime` 验证日历合法性（如 2020-13-01 或 2020-02-30）
   - **双重验证机制**：先正则验证格式（YYYY-MM-DD 必须为2位月份/日期），再 datetime.strptime 验证日历合法性
   - **finally 块迭代安全**：先复制 `test_logger.handlers` 列表，避免迭代中修改列表的经典 Bug
   - **前缀长度预期注释**：补充各前缀精确长度预期（30为2字符、688为3字符、8/4为1字符）+ 覆盖盲区说明
   - **版本历史补全**：stock_utils.py 新增 v2.1 版本演进说明
   - **修复原因**：代码bug（excluded_count 统计含义模糊、datetime.strptime 接受单数字月份/日期、finally迭代Bug）+ 规范遗漏（前缀长度预期注释缺失）

13. **factor_generator.py v1.1 (2026-05-25)** — 第一轮公共模块规范化
   - **logger 参数化**：`generate_all_factors` 参数 `verbose: bool` → `logger: Optional[logging.Logger]`
   - **新增 get_module_logger**：遵循 PROJECT.md 公共模块日志规范
   - **新增 __all__ 导出**：导出 `generate_all_factors` + `get_module_logger`
   - **类型注解精确化**：`Optional[Path]` → `Optional[Union[Path, str]]`，返回值 `Dict` → `Dict[str, Any]`
   - **移除 sys.path.insert**：改用标准导入方式（函数内导入因子计算函数）
   - **异常处理补全**：文件加载 + JSON 解析 + 原子写入
   - **原子写入**：使用临时文件 + `os.replace` 遵循 PROJECT.md 文件写入规范
   - **CLI 日志规范化**：使用 `setup_logger` + try/finally 资源清理
   - **docstring 补全**：Args/Returns/Raises/Note/Example 全部补齐
   - **__init__.py 导出**：新增模块级导出
   - **修复原因**：代码bug（print vs logger、sys.path.insert、缺少异常处理）+ 规范遗漏（缺少 __all__、logger 参数、docstring Raises）

14. **factor_generator.py v1.3 (2026-05-25)** — 第二轮深度优化
   - **常量命名私有化**：`DEFAULT_CACHE_DIR` → `_DEFAULT_CACHE_DIR`（遵循 cache_manager.py 私有常量规范）
   - **导入顺序 PEP 8 合规化**：标准库按字母顺序（gzip, json, logging, os）+ 第三方库分隔
   - **导入位置规范化**：函数内导入因子计算函数移到文件顶部（遵循 PROJECT.md 第401-418行规范）
   - **版本历史补全**：factor_generator.py 新增 v1.3 版本演进说明
   - **修复原因**：规范遗漏（常量命名不规范、导入顺序不规范、导入位置违反规范）

15. **factor_generator.py v1.4 (2026-05-25)** — 第三轮深度优化
   - **流程文档创建**：`docs/factor_generator_flow.md`（整体架构 + 8步流程 + 输出结构 + 版本历史）
   - **测试用例创建**：`test_cases/factor_generator_test_cases.md`（10项正常测试 + 3项异常测试）
   - **output_cols 注释补全**：索引含义说明（0:6=基础OHLCV，6:8=基础因子，8:=扩展因子）
   - **valid_records_percent 补全**：新增百分比统计字段（与日志输出保持一致）
   - **MODULE.md 版本历史更新**：新增 v2.28 版本记录
   - **修复原因**：规范遗漏（流程文档缺失、测试用例缺失、输出注释缺失、返回值统计不完整）

16. **factor_generator.py v1.5 (2026-05-25)** — 第四轮深度优化
   - **条件导入合并简化**：移除 __main__ 测试重复 sys.path.insert（减少8行代码）
   - **异常处理精确化**：区分 OSError/PermissionError/IOError（遵循 patterns.md）
   - **metadata 字段注释补全**：generated_at、elapsed_seconds、valid_records_percent 等8字段含义
   - **修复原因**：代码冗余（sys.path.insert 重复）、异常处理宽泛、返回值注释缺失

17. **factor_generator.py v1.6 (2026-05-25)** — 第五轮深度优化
   - **JSONDecodeError 内存优化**：提取 lineno/colno/msg 信息，避免 e.doc 内存翻倍（遵循 patterns.md）
   - **CLI 入口规范**：main() 返回退出码（0成功/1失败），而非 metadata
   - **__main__ 测试补全**：required_fields 新增 valid_records_percent 字段验证
   - **条件导入合并简化**：移除 CLI 入口块重复 sys.path.insert（减少6行代码）
   - **修复原因**：内存优化遗漏、CLI 规范缺失、测试覆盖不完整、代码冗余

18. **factor_generator.py v1.7 (2026-05-25)** — 第六轮深度优化
   - **注释行号修正**：setup_logger 导入位置改为第364-367行（原注释说第333-341行）
   - **docstring RuntimeError 补全**：文件系统错误异常说明（第297-306行会抛出）
   - **main() 返回类型注解**：添加 `-> int`（符合 CLI 入口规范）
   - **修复原因**：注释不一致、docstring Raises 缺失、类型注解缺失

19. **factor_generator.py v1.8 (2026-05-25)** — 第七轮深度优化
   - **gzip.BadGzipFile 异常处理补全**：gzip 文件损坏错误处理（第177-179行、208-210行）
   - **docstring ValueError 补全**：补充 gzip 文件损坏异常说明
   - **注释行号修正**：sys.path.insert 位置改为第42-53行（删除1行后位置变化）
   - **修复原因**：gzip 异常处理缺失、注释行号不准确

21. **fetch_stock_list.py v2.0 (2026-05-27)** — 公共模块规范化
   - **输出目录迁移**：cache → result（遵循 MODULE.md 约束 2）
   - **日志规范化**：复用 logger_config.py 的 setup_logger（遵循 PROJECT.md 第561-700行）
   - **日志文件命名**：`stock_cache.log` → `fetch_stock_list_YYYY-MM-DD.log`
   - **日志格式**：添加 `%(name)s` 字段
   - **CLI 日志规范化**：print → logger（遵循 PROJECT.md 第780-839行）
   - **类型注解补全**：所有公共函数添加完整类型注解
   - **__all__ 导出**：明确定义 5 个公共 API
   - **版本号常量提取**：`_OUTPUT_VERSION = '2.2'`（遵循 MODULE.md 约束 16）
   - **datetime.now() 统一调用**：只调用一次，派生两个格式（遵循 MODULE.md 约束 17）
   - **Path 对象迁移**：os.path → Path
   - **公共模块复用**：logger_config.py、http_client.py、paths.py
   - **原子写入**：使用临时文件 + replace
   - **流程文档创建**：docs/fetch_stock_list_flow.md
   - **测试用例创建**：test_cases/fetch_stock_list_test_cases.md
   - **修复原因**：MODULE.md 规范违规（8项）+ PROJECT.md 规范违规（4项）

22. **fetch_stock_list.py v2.1 (2026-05-27 06:35)** — 第二轮优化
   - **requests 导入顶部化**：从 `__main__` 内移动到模块顶部（遵循 MODULE.md 约束 51）
   - **原子写入异常捕获扩大**：OSError → Exception（遵循 MODULE.md 约束 55）
   - **validate_cache logger 参数化**：新增 `logger_arg` 参数（遵循 PROJECT.md 日志参数规范）
   - **set 类型注解完整化**：`set` → `set[str]`
   - **ensure_cache_dir/ensure_result_dir logger 参数化**：新增 `logger_arg` 参数
   - **修复原因**：深度审查发现 6 项遗漏问题

23. **fetch_stock_list.py v2.2 (2026-05-27 06:50)** — 第三轮优化
   - **导入顺序修正**：requests 移至标准库之后（遵循 PEP 8：标准库 → 第三方 → 本地）
   - **ensure_cache_dir/ensure_result_dir 调用时传递 logger**：遵循 MODULE.md 约束 33（函数签名与调用一致）
   - **修复原因**：导入顺序违规、调用方参数遗漏

24. **fetch_stock_list.py v2.3 (2026-05-27 07:05)** — 第四轮优化
   - **load_cache 异常捕获扩大**：`json.JSONDecodeError` → `Exception`（遵循 MODULE.md 约束 55）
   - **潜在风险覆盖**：PermissionError、IsADirectoryError、OSError 等文件读取异常
   - **修复原因**：异常捕获范围过小，文件读取可能抛出多种异常

25. **fetch_stock_list.py v2.4 (2026-05-27 07:30)** — 第五轮深度修复
   - **logger参数遮蔽修复**：`logger` → `logger_arg`（统一4个函数签名：fetch_stocks_from_sina、save_cache、load_cache、refresh_stock_cache）
   - **session资源泄漏修复**：使用 `with create_sina_session(logger=_logger) as session:` 确保连接池释放
   - **load_cache日志参数补充**：添加 `logger_arg` 参数，save_cache 调用时传递 `_logger`
   - **ST股票误判修复**：substring 匹配 (`'ST' in name`) → 前缀匹配 (`startswith('ST')`)，避免"东ST"正常股票被误判
   - **修复原因**：代码bug（4项）+ 规范缺失（MODULE.md 新增约束77/78/79）

26. **fetch_stock_list.py v2.5 (2026-05-27 08:00)** — 第六轮深度修复
   - **重试逻辑修复**：最后一次重试失败时直接 raise（删除无效 continue），避免异常被吞掉
   - **validate_cache参数修复**：删除冗余 `logger_arg` 参数（函数内部未使用）
   - **_write_json_file临时文件修复**：使用 `tempfile.NamedTemporaryFile` 避免多进程并发冲突
   - **增量更新name字段修复**：同步更新已存在股票的最新名称（股票改名后 name 字段需更新）
   - **data变量类型守卫**：添加 `if data is None: raise RuntimeError` 确保类型安全
   - **修复原因**：代码bug（5项）+ 规范缺失（MODULE.md 新增约束80/81/82）

27. **fetch_stock_list.py v2.6 (2026-05-27 08:30)** — 第七轮深度修复
   - **_write_json_file参数名修复**：`logger` → `logger_arg`（遵循 PROJECT.md 日志参数规范）
   - **validate_cache ST检查修复**：使用前缀匹配（`startswith('S')` 或 `startswith('ST')`），与 is_valid_main_board_stock 逻辑一致
   - **is_valid_main_board_stock ST顺序修复**：先剔除 S 开头（含 SST、S*ST），再剔除 *ST 和 ST，避免逻辑混乱
   - **重试逻辑简化**：删除 success 变量，循环内直接控制流（成功 break，失败在最后一次重试 raise）
   - **修复原因**：代码bug（4项）+ 规范缺失（MODULE.md 新增约束83/84）

28. **fetch_stock_list.py v2.7 (2026-05-27 09:00)** — 第八轮深度修复
   - **data类型守卫增强**：添加 `assert isinstance(data, list)` 确保类型安全（比单独检查 None 更严格）
   - **existing_stock_map注释说明**：明确引用修改预期行为（修改 existing_stock['name'] 会直接更新 existing_stocks）
   - **removed_codes截断**：限制最多50个，添加 `removed_codes_truncated` 字段避免 JSON 文件过大
   - **result初始化补全**：添加 `updated_count: 0` 避免字段缺失
   - **CLI日志补全**：添加 updated_count 输出（仅当有更新时显示 `if updated_count > 0`）
   - **修复原因**：代码bug（5项）+ 规范缺失（MODULE.md 新增约束85/86）

29. **fetch_stock_list.py v2.8 (2026-05-27 09:30)** — 第九轮深度修复
   - **ST前缀提取为模块级常量**：添加 `ST_PREFIXES` 常量便于维护（遵循 MODULE.md 约束 16）
   - **fetch_stocks_from_sina doctest修复**：改为合法格式 `len(stocks) > 2500` → `True`
   - **get_cached_stock_codes doctest修复**：改为合法格式 `len(codes) > 2500` → `True`
   - **修复原因**：代码bug（3项）

30. **fetch_turnover.py v2.0 (2026-05-27 10:00)** — 第一轮基础优化
   - **导入顺序 PEP 8 规范化**：标准库 → 第三方库 → 本地模块（sys、logging 补充）
   - **版本号提取为常量**：`_OUTPUT_VERSION = '2.0'` 便于维护（遵循 MODULE.md 约束 16）
   - **datetime.now() 统一调用**：模块级 `_NOW`、`_NOW_ISO`、`_NOW_STR`（遵循 MODULE.md 约束 17）
   - **session 资源管理**：使用 `with requests.Session() as session` 确保释放（遵循 MODULE.md 约束 78）
   - **ST 检测前缀匹配**：`startswith(prefix)` 避免"东ST"误判（遵循 MODULE.md 约束 79）
   - **修复原因**：代码bug（5项）

31. **fetch_turnover.py v2.1 (2026-05-27 10:30)** — 第二轮深度优化
   - **logger 参数化**：所有公共函数添加 `logger_arg` 参数（遵循 MODULE.md 约束 77）
     - fetch_turnover_rate_eastmoney、load_cache、save_cache、main、fetch_turnover_rate_baostock
   - **tempfile 使用**：save_cache 使用 `tempfile.NamedTemporaryFile` 避免并发冲突（遵循 MODULE.md 约束 80）
   - **print → logger 迁移**：52处全部迁移为 logger.info/debug/error/warning
   - **load_cache/save_cache logger 参数传递**：调用方传递 `_logger`（遵循 PROJECT.md 日志规范）
   - **修复原因**：代码bug（6项）

32. **fetch_turnover.py v2.2 (2026-05-27 11:00)** — 第三轮补充优化
   - **ST_PREFIXES 常量提取**：模块级常量便于维护（遵循 MODULE.md 约束 16）
   - **load_stock_list ST 检测修复**：前缀匹配 + 逻辑修正（`break + continue` 避免 continue 误用）
   - **__all__ 导出列表**：添加公共函数导出列表（遵循 MODULE.md 约束 53）
   - **__main__ logger 设置**：`logging.basicConfig` + `cli_logger`（遵循 PROJECT.md 日志规范）
   - **CLI 参数简化**：`--baostock` 替代 `--source` 选择（更简洁）

33. **测试规范迁移 (2026-05-27 12:00)** — pytest 测试框架迁移
   - **PROJECT.md 测试规范更新**：测试用例从 `.md` 文档改为 pytest 可执行文件（`.py`）
   - **MODULE.md 目录结构更新**：test_cases/ 从 `<脚本名>_test_cases.md` 改为 `test_<脚本名>.py`
   - **MODULE.md 版本更新**：v3.01 → v3.02
   - **cache_manager.py __main__ 块删除**：禁止脚本内嵌测试代码（遵循 PROJECT.md 新规范）
   - **pytest 测试文件创建**：`test_cases/test_cache_manager.py`（从 __main__ 块转换）
   - **cache_manager_test_cases.md 删除**：不再需要 .md 测试场景文档
   - **测试命名规则**：`test_<脚本名>.py`（遵循 pytest 约定）
   - **修复原因**：规范缺失（PROJECT.md 缺少 pytest 规范、MODULE.md 目录结构不规范、__main__ 块测试代码无法自动运行）

34. **batch_processor.py v1.0 (2026-05-27 14:30)** — 公共模块规范化
   - **文件头版本历史**：添加 v1.0 初始版本说明
   - **logger 参数命名**：`logger` → `logger_arg`（遵循 MODULE.md 约束 77）
   - **cleanup_batch_files 异常日志**：添加 `[{type(e).__name__}]: {e}`（遵循 MODULE.md 约束 50）
   - **docstring Example 章节**：4个公共函数添加使用示例
   - **docstring Raises 章节**：4个公共函数添加异常说明
   - **导入顺序验证**：符合 PEP 8（标准库→第三方库→本地模块）
   - **流程文档创建**：`docs/batch_processor_flow.md`（遵循 MODULE.md 约束 8）
   - **pytest 测试文件**：`test_cases/test_batch_processor.py`（16个测试用例）
   - **MODULE.md 版本更新**：v3.02 → v3.03
   - **修复原因**：规范缺失（8项）

35. **batch_processor.py v1.1 (2026-05-27 15:00)** — 第二轮深度优化
   - **BatchStream 类 docstring**：添加 Example/Raises 章节（公共类规范化）
   - **`_write_json_record` 类型注解**：`Any` → `TextIO`（更精确的类型）
   - **修复原因**：类型注解不精确、公共类 docstring 不完整（2项）

36. **batch_processor.py v1.2 (2026-05-27 15:30)** — 第三轮深度优化
   - **函数签名类型注解完整化**：`Path = None` → `Path | None = None`（4个公共函数）
   - **logger_arg 类型注解**：`logging.Logger = None` → `logging.Logger | None = None`
   - **`self.records` 类型注解**：`list` → `list[dict]`（更精确）
   - **format_final_output 入口处统一转换**：`Path(xxx).unlink()` → 入口处统一转换为 Path
   - **异常处理日志**：`except json.JSONDecodeError: continue` → 添加 debug 日志
   - **修复原因**：类型注解不完整、静默 fallback、冗余转换（4项）

37. **batch_processor.py v1.3 (2026-05-27 16:00)** — 第四轮深度优化
   - **新增模块级常量 `_DATA_TYPES`**：避免硬编码 `['factor', 'return']`（2处使用）
   - **`_write_json_record` 添加 Example**：内部函数补充使用示例
   - **删除冗余赋值**：`date_start = first_date` → 直接使用 `first_date`（代码简洁）
   - **`cleanup_batch_files` 使用常量**：`for t in [...]` → `for data_type in _DATA_TYPES`
   - **修复原因**：硬编码重复、冗余赋值、内部函数文档不完整（4项）

33. **fetch_turnover.py v2.3 (2026-05-27 11:30)** — 第四轮补充优化
   - **get_cached_turnover_codes 函数**：创建公共函数（__all__ 中已声明，补充实现）
   - **类型注解完整性**：`Set[str]` 返回类型 + `logger_arg` 参数
   - **函数文档字符串**：添加 Args/Returns/Example 说明
   - **修复原因**：规范补充（1项）

34. **fetch_turnover.py v2.4 (2026-05-27 12:00)** — 第五轮深度修复
   - **fetch_turnover_rate_baostock 时间统计修复**：单独维护 `processed_count`/`skipped_count`（遵循 MODULE.md 约束 87）
     - 跳过已有股票不计入处理统计
     - 平均时间使用实际处理数量计算：`avg_time = elapsed / processed_count`
   - **merge_records 空数据处理修复**：`new_records=[]` 时保留 `existing_data` 的 meta（遵循 MODULE.md 约束 88）
     - 避免 `generated_at`、`last_updated` 被强制更新
     - 避免 `source` 被强制改为 'mixed'
   - **merge_records source 保留**：保留原始 source（遵循 MODULE.md 约束 88）
   - **merge_records logger 参数**：添加 `logger_arg` 参数 + 调用方传递
   - **修复原因**：代码bug（3项）

|| 87 | 处理进度统计准确 | 使用实际处理数量计算平均时间（processed_count），跳过项不计入统计 |
|| 88 | 空数据合并保护 | new_records=[] 时保留 existing_data 的 meta，避免强制覆盖 |
|| 89 | ST前缀元组用法 | ST_PREFIXES 使用元组直接传给 startswith，避免循环遍历 |
|| 90 | API异常边界处理 | total_pages=0 时添加警告日志，提示可能无数据或API异常 |
|| 91 | 长期运行时间偏差 | end_date 使用 datetime.now() 避免模块级 _NOW 偏差 |

35. **fetch_turnover.py v2.5 (2026-05-27 12:30)** — 第六轮深度修复
35. **fetch_turnover.py v2.5 (2026-05-27 12:30)** — 第六轮深度修复
   - **ST_PREFIXES 元组优化**：改为元组直接传给 startswith（遵循 MODULE.md 约束 89）
   - **ST_PREFIXES 优先级语义**：`*ST` 排在最前（退市风险优先检测）
   - **total_pages=0 边界处理**：添加警告日志（遵循 MODULE.md 约束 90）
   - **fetch_stock_history_baostock 返回类型**：实际与标注一致（无问题）
   - **_NOW 模块级时间戳偏差**：end_date 使用 `datetime.now()`（遵循 MODULE.md 约束 91）
|| 91 | 长期运行时间偏差 | end_date 使用 datetime.now() 避免模块级 _NOW 偏差 |
|| 92 | 时间估算准确 | remaining 基于实际待处理数（total - skipped_count - processed_count） |
|| 93 | 数据源合并语义 | merge_records 添加 source 参数，existing_meta.source != source 时设为 'mixed' |

36. **fetch_turnover.py v2.6 (2026-05-27 13:00)** — 第七轮深度修复
   - **get_cached_turnover_codes 文档示例**：改为 `isinstance(codes, set)` → True（确定结果）
     - 避免 `len(codes) > 2500` 结果不确定（依赖实际数据量）
   - **load_cache _logger 赋值**：统一为 `logger_arg or logger`（遵循 MODULE.md 约束 77）
     - 消除冗余的 `logging.getLogger(__name__)` 重复调用
|| 93 | 数据源合并语义 | merge_records 添加 source 参数，existing_meta.source != source 时设为 'mixed' |
|| 94 | 跳过日志粒度直观 | 跳过股票日志基于 skipped_count % 100（而非 idx % 100） |

37. **fetch_turnover.py v2.7 (2026-05-27 13:30)** — 第八轮深度修复
   - **fetch_turnover_rate_baostock 时间估算逻辑**：remaining 基于实际待处理数（遵循 MODULE.md 约束 92）
   - **merge_records source 参数**：添加 source 参数 + 调用方传入数据源（遵循 MODULE.md 约束 93）
   - **merge_records 数据源合并逻辑**：`existing_meta.source != source` 时设为 `'mixed'`
|| 94 | 跳过日志粒度直观 | 跳过股票日志基于 skipped_count % 100（而非 idx % 100） |
|| 95 | pages=0提前退出 | total_pages=0 时添加 break 提前退出循环 |

38. **fetch_turnover.py v2.8 (2026-05-27 14:00)** — 第九轮深度修复
   - **get_cached_turnover_codes doctest**：已修复为 `isinstance(codes, set)`（Round 17）
   - **save_cache _logger 初始化**：统一为 `logger_arg or logger`（遵循 MODULE.md 约束 77）
     - 与 load_cache 保持一致，消除冗余 `logging.getLogger(__name__)`
   - **fetch_turnover_rate_baostock 跳过日志粒度**：基于 `skipped_count % 100`（遵循 MODULE.md 约束 94）
|| 95 | pages=0提前退出 | total_pages=0 时添加 break 提前退出循环 |
|| 96 | tempfile同块写入 | 在同一个 with 块内传文件对象给 gzip.open，不关闭再开 |

39. **fetch_turnover.py v2.9 (2026-05-27 14:30)** — 第十轮深度修复
   - **fetch_turnover_rate_eastmoney total_pages=0**：添加 break 提前退出（遵循 MODULE.md 约束 95）
   - **INTERMEDIATE_SAVE_INTERVAL 常量**：删除未使用的冗余常量
   - **修复原因**：代码bug（2项）

40. **fetch_turnover.py v2.10 (2026-05-27 15:00)** — 第十一轮深度修复
   - **save_cache tempfile 修复**：在同一个 with 块内直接传文件对象给 gzip.open（遵循 MODULE.md 约束 96）
     - 原逻辑：先关闭临时文件，再重新打开写入（多余步骤）
     - 新逻辑：传文件对象给 gzip.open，不关闭再开
     - 删除 `mode='wb'` 参数（gzip.open 会处理文件模式）
   - **修复原因**：代码bug（1项）

20. **factor_generator.py v1.9 (2026-05-25)** — 第八轮深度优化
   - **冗余导入清理**：移除条件导入块的 `_Path`（第44行），直接使用顶部导入的 `Path`
   - **注释行号修正**：setup_logger 导入位置改为第369-374行（删除1行后位置变化）
   - **修复原因**：冗余导入、注释行号不准确

21. **factor_generator.py v1.10 (2026-05-25)** — 第九轮深度优化
   - **gzip 导入合并**：移除 `from gzip import BadGzipFile`，改用 `gzip.BadGzipFile`（符合 PEP 8 导入规范）
   - **main() 函数内冗余导入清理**：移除 `import logging`（使用模块级导入）
   - **修复原因**：导入冗余

22. **factor_generator.py v1.11 (2026-05-25)** — Bug修复
   - **条件导入合并**：将 setup_logger 导入合并到顶部条件块（删除中间冗余的条件导入块）
   - **__main__ 循环导入修复**：删除 `from data_fetchers.factor_generator import ...`（直接使用已定义的函数）
   - **PermissionError 重复捕获简化**：`except (OSError, PermissionError, IOError)` → `except OSError`（PermissionError 是 OSError 子类）
   - **temp_path 后缀处理修复**：`with_suffix('.tmp')` → `parent / (name + '.tmp')`（避免替换 .gz 后缀）
   - **修复原因**：代码 bug（条件导入位置错误、循环导入、异常重复捕获、临时文件名错误）

23. **factor_generator.py v1.12 (2026-05-25)** — Bug修复 + 规范补充
   - **output_cols 注释修正**：`output_cols[0:6] = OHLCV` → `output_cols[0:2]=date/asset, output_cols[2:6]=open/close/high/low`（非标准 OHLCV 顺序）
   - **dates 排序注释补充**：说明 YYYY-MM-DD 字符串排序正确（字典序与日期序一致）
   - **total_records 除零保护**：空数据时百分比返回 0.0（`calc_pct` 函数）
   - **版本历史移除硬编码行号**：改为描述性注释（避免行号不准确误导）
   - **argparse 版本描述修正**：v1.3 版本历史补充说明 argparse 为 CLI 入口特有导入，保留函数内导入
   - **修复原因**：代码 bug（注释不符、除零风险）+ 规范遗漏（日期排序说明、日志换行符规范）

24. **MODULE.md v2.45 (2026-05-25)** — 规范补充
   - **日志换行符规范**：新增章节说明换行符使用场景（错误日志多行格式化允许、__main__ 测试块视觉分隔允许、一般 info 日志不建议）
   - **规范补充原因**：用户发现 logger.info 中 `\n` 换行符可能产生 handler 解析问题，需明确允许/禁止场景

25. **factor_generator.py v1.13 (2026-05-25)** — Bug修复
   - **缩进错误修正**：Step 8 注释缩进从 0 修正为 4（脱离函数体风险）
   - **numpy.int64 类型转换**：bollinger_valid/kdj_valid/surge_valid 显式转换为 int（JSON 序列化兼容）
   - **__main__ 块重构**：改为 CLI 入口调用 main()，测试代码移至 test_cases/test_factor_generator.py（测试与 CLI 分离）
   - **修复原因**：代码 bug（缩进格式错误、类型不匹配、__main__ 结构不合理）

26. **test_cases/test_factor_generator.py (2026-05-25)** — 新增测试脚本
   - **测试与 CLI 分离**：独立测试脚本，与 __main__ CLI 入口分离
   - **测试内容**：函数定义验证、get_module_logger 验证、generate_all_factors 验证、返回字段验证、因子列验证、有效记录数验证

27. **factor_generator.py v1.14 (2026-05-25)** — Bug修复 + 代码结构优化
   - **除零保护统一**：使用模块级私有函数 `_calc_pct`，替代函数内嵌套定义
   - **硬编码常量**：新增 `_EXTENDED_FACTOR_COLS` 常量替代 `output_cols[8:]` 切片
   - **docstring 补充**：Raises 补充空数据异常声明，Note 补充除零保护说明
   - **turnover_missing 类型**：显式 `int()` 转换
   - **修复原因**：代码 bug（除零风险未统一保护、硬编码切片脆弱、函数结构混乱）

28. **MODULE.md v2.47 (2026-05-25)** — 规范补充
   - **除零保护规范**：模块级私有函数 `_calc_pct` 模式，避免函数内嵌套定义
   - **硬编码常量规范**：扩展因子列应使用常量定义，避免切片索引脆弱性

29. **factor_generator.py v1.15 (2026-05-25)** — Bug修复 + 文档修正
   - **docstring 修正**：移除 `json.JSONDecodeError` 声明（已内部捕获转换为 ValueError），补充说明调用方不会收到 JSONDecodeError
   - **TOCTOU 竞争窗口修复**：`temp_path.unlink(missing_ok=True)` 替代 `exists() + unlink()`，消除 Time-of-check-to-time-of-use 竞争
   - **修复原因**：代码 bug（文档不准确、并发安全风险）

30. **MODULE.md v2.48 (2026-05-25)** — 规范补充
   - **临时文件清理规范**：`unlink(missing_ok=True)` 原子操作，避免 TOCTOU 竞争窗口
   - **docstring Raises 规范**：声明异常应与实际抛出一致，已捕获转换的异常不应声明

31. **factor_generator.py v1.16 (2026-05-25)** — 代码结构优化
   - **常量统一**：新增 `_BASE_COLS` 和 `_OUTPUT_COLS` 常量，output_cols 使用 `_OUTPUT_COLS` 引用（消除维护隐患）
   - **sys 重复导入**：移除 __main__ 块中 sys 重复导入（顶部条件块已导入）
   - **_calc_pct 语义**：修正为通用百分比计算函数（参数名 count/total，docstring 补充通用语义说明）
   - **修复原因**：代码结构问题（常量关系不清晰、重复导入、函数语义不准确）

32. **MODULE.md v2.49 (2026-05-25)** — 规范补充
   - **常量引用关系规范**：相关常量应建立引用关系，避免各自硬编码导致维护遗漏
   - **条件块导入规范**：顶部条件块已导入的模块，__main__ 块无需重复导入

33. **factor_generator.py v1.17 (2026-05-25)** — Bug修复 + 文档优化
   - **父目录创建**：`output_path.parent.mkdir(parents=True, exist_ok=True)`（避免 FileNotFoundError）
   - **dates 字段来源**：从 `output_df['date']` 取（数据来源更清晰）
   - **docstring 示例值**：改为范围说明（`# 实际耗时，单位秒（范围：0.0 ~ 数百秒，取决于数据量）`）
   - **修复原因**：代码 bug（目录不存在风险）+ 文档问题（示例值过于具体）

34. **MODULE.md v2.50 (2026-05-25)** — 规范补充
   - **输出目录创建规范**：写入前确保父目录存在，`mkdir(parents=True, exist_ok=True)`
   - **docstring 示例规范**：避免过于具体的示例值，改为范围说明或注释

35. **factor_generator.py v1.18 (2026-05-25)** — Bug修复
   - **版本历史描述修正**：v1.12 "logger换行符修复" 改为 "MODULE.md日志换行符规范补充"（错误日志允许多行格式化，符合规范）
   - **可变对象返回副本**：`list(_EXTENDED_FACTOR_COLS)` 防止外部修改模块内部状态
   - **修复原因**：版本历史描述不准确 + 可变对象引用风险

36. **factor_generator.py v1.19 (2026-05-25)** — 代码结构优化
   - **常量改为元组**：`_EXTENDED_FACTOR_COLS: tuple`、`_BASE_COLS: tuple`、`_OUTPUT_COLS: tuple`（防止意外修改）
   - **docstring 示例补充注释**：`# 返回列表副本`（说明实际返回类型）
   - **内存释放**：`del factor_df`（显式释放中间列内存）
   - **优化原因**：代码结构优化（元组防止修改 + 内存管理）

37. **MODULE.md v2.52 (2026-05-25)** — 规范补充
   - **常量类型规范**：模块级常量列表应使用元组防止意外修改
   - **内存释放规范**：大 DataFrame 使用完毕后显式释放（`del df`）

38. **factor_generator.py v1.20 (2026-05-25)** — 代码结构优化
   - **mkdir 位置调整**：移入 try 块统一异常处理（与原子写入语义一致）
   - **注释位置优化**：_OUTPUT_COLS 索引切片说明移到常量定义处（注释与定义不分离）
   - **docstring 补充示例**：_calc_pct 补充参数含义示例（count/total 语义清晰）
   - **异常日志改进**：main() 增加 `type(e).__name__`（异常类型可追溯）
   - **优化原因**：代码结构问题（异常处理不一致 + 注释分离 + 参数语义模糊 + 日志信息不足）

39. **MODULE.md v2.53 (2026-05-25)** — 规范补充
   - **mkdir 位置规范**：应在 try 块内创建目录，异常时可统一处理
   - **常量注释规范**：常量结构说明应放在定义处，而非使用处
   - **异常日志规范**：应包含异常类型名（`type(e).__name__`）便于追溯

40. **factor_generator.py v1.21 (2026-05-25)** — Bug修复
   - **docstring Example 格式修正**：注释放在 `>>>` 行而非返回值行、增加 `isinstance` 示例
   - **修复原因**：docstring 格式不规范（注释位置错误 + 缺少类型验证示例）

41. **MODULE.md v2.54 (2026-05-25)** — 规范补充
   - **docstring Example 格式规范**：注释放在 `>>>` 行，返回值行无注释

42. **factor_generator.py v1.22 (2026-05-25)** — 代码结构优化
   - **冗余别名清理**：`output_cols = _OUTPUT_COLS` 改为直接使用 `_OUTPUT_COLS`
   - **职责分离**：mkdir 单独 try 块处理（异常信息更精确）
   - **内存释放**：`del base_data`、`del turnover_data`（JSON 加载的大对象）
   - **错误信息改进**：missing_cols 增加 `_EXTENDED_FACTOR_COLS` 提示（排错路径更短）
   - **优化原因**：代码结构问题（冗余别名 + 职责混乱 + 内存泄漏 + 错误信息模糊）

43. **MODULE.md v2.55 (2026-05-25)** — 规范补充
   - **冗余别名规范**：直接使用常量，无需局部别名
   - **职责分离规范**：mkdir 单独处理，与文件写入异常分离
   - **错误信息规范**：增加上下文提示，缩短排错路径

44. **factor_generator.py v1.23 (2026-05-26)** — 代码结构优化
   - **类型注解改进**：`tuple` → `tuple[str, ...]`（更精确表达字符串元组）
   - **优化原因**：类型注解不够精确（Python 3.9+ 支持泛型元组）

45. **MODULE.md v2.56 (2026-05-26)** — 规范补充
   - **tuple 类型注解规范**：使用 `tuple[str, ...]` 表达字符串元组，而非 `tuple`

46. **factor_generator.py v1.24 (2026-05-26)** — Bug修复 + 代码结构优化
   - **内存释放**：`del turnover_df`（merge 完成后不再需要）
   - **docstring 语义修正**：Example 标记非运行示例（需要输入数据文件）
   - **pandas 兼容性**：`list(_OUTPUT_COLS)`（元组转列表，列选择需要列表）
   - **修复原因**：内存泄漏 + docstring 语义问题 + pandas 元组索引兼容性

47. **MODULE.md v2.57 (2026-05-26)** — 规范补充
   - **DataFrame 内存释放规范**：merge 完成后立即释放（不再需要的 DataFrame）
   - **docstring Example 规范**：标记非运行示例（需要外部依赖的函数）
   - **pandas 列选择规范**：元组常量需转列表（`list(tuple)`）

49. **factor_generator.py v1.25 (2026-05-26)** — Bug修复 + 文档修正
   - **类型注解兼容性**：_calc_pct 补充兼容类型说明（int、numpy.int64、float）
   - **docstring Raises修正**：删除"输入数据为空"场景（代码无对应检查）
   - **兜底块异常信息**：补充 `{type(e).__name__}: {e}`

50. **fetch_factor_cache.py v3.5 (2026-05-26)** — 代码结构优化（第一轮）
   - **版本历史规范化**：采用标准格式（版本号 + 日期 + 描述）
   - **sys.path.insert移除**：删除冗余路径配置
   - **公共模块导入**：添加 setup_logger、get_logs_dir 导入
   - **docstring补充**：get_memory_usage_mb、get_memory_info_str、save_batch_cache_sorted
   - **流程文档创建**：docs/fetch_factor_cache_flow.md
   - **测试用例创建**：test_cases/fetch_factor_cache_test_cases.md

52. **factor_generator.py v1.26 (2026-05-26)** — 规范合规修复
   - **输出路径修正**：从 cache/factor_data/ 改为 data_fetchers/result/
   - **输入输出分离**：输入使用 cache（数据源原始缓存），输出使用 result（遵循 MODULE.md 约束 #2）

54. **MODULE.md v2.61 (2026-05-26)** — 版本更新
   - **第二轮优化进度**：print → logger 迁移进行中

57. **fetch_factor_cache.py v3.7 (2026-05-26)** — 代码规范化
   - **导入顺序**：PEP 8 规范（标准库→第三方→本地→公共模块）
   - **BatchStream 类**：完整 docstring + 类型注解（6个方法）
   - **路径配置**：使用公共模块 get_cache_dir() 替代硬编码
   - **类型注解**：使用 Path 对象替代 os.path.join

59. **fetch_factor_cache.py v3.8 (2026-05-26)** — Path 对象规范化
   - **os.path.join**：9处 → Path / 运算符
   - **os.path.exists**：2处 → Path.exists()
   - **os.path.getsize**：4处 → Path.stat().st_size
   - **os.remove**：3处 → Path.unlink()

61. **fetch_factor_cache.py v3.9 (2026-05-26)** — 类型注解完善
   - **save_batch_cache_sorted**：factor_df: pd.DataFrame, return_df: pd.DataFrame
   - **n_way_merge_deduplicate**：返回类型 tuple[Path | None, int]
   - **fetch_batch_stocks**：loader: RealDataLoader, 返回类型 tuple[pd.DataFrame | None, pd.DataFrame | None]
   - **format_final_output**：参数 Path | str, 返回类型 tuple[int, int, int]

63. **fetch_factor_cache.py v3.10 (2026-05-26)** — 代码清理 + 类型修复
   - **移除未使用导入**：os 模块（所有 os 调用已替换为 Path）
   - **类型注解修复**：validate_final_data 返回类型 bool → tuple[bool, int, int, int]

65. **fetch_factor_cache.py v3.11 (2026-05-26)** — main 函数完善
   - **返回类型注解**：main 函数 -> None
   - **版本号同步**：main 函数日志中的版本号 3.6 → 3.10

66. **MODULE.md v2.67 (2026-05-26)** — 版本更新
   - **v3.11版本记录**：main 函数完善
   - **完成状态**：74处全量替换，无剩余
   - **logger参数化**：6个核心函数（save_batch_cache_sorted、n_way_merge_deduplicate、fetch_batch_stocks、format_final_output、validate_final_data、cleanup_batch_files）
   - **main函数日志初始化**：setup_logger + logs_dir 规范
   - **docstring补充**：所有核心函数完整 Args/Returns/Note
   - **约束 #2 修正**：从"输出到 cache 目录"改为"输出到 result 目录"
   - **语义明确**：cache 为数据源原始缓存，result 为处理后的输出结果
   - **修复原因**：docstring 描述与实际行为不符 + 错误信息不完整

67. **fetch_factor_cache.py v3.12 (2026-05-26)** — Bug修复
   - **format_final_output 返回值修复**：在 `del factor_records` 前保存记录数 `n_records = len(factor_records)`
   - **n_way_merge_deduplicate 去重逻辑修复**：heap 元素使用 `batch_idx`（原始批次号）而非 `stream_idx`（列表索引）
   - **BatchStream 类补充属性**：新增 `batch_idx` 和 `data_type` 属性，用于去重优先级判断
   - **修复原因**：代码 bug（del 后变量名不存在、去重优先级错误）

68. **MODULE.md v2.68 (2026-05-26)** — 规范补充
   - **新增约束 #9**：N-way merge 去重使用 batch_idx
   - **约束内容**：heap 元素为 `(key, batch_idx, stream)`，而非 `(key, stream_idx, stream)`
   - **规范补充原因**：原有实现使用 stream_idx 导致去重优先级错误（批次缺失时索引与批次号不对应）

69. **fetch_factor_cache.py v3.13 (2026-05-26)** — Bug修复（4项）
   - **冗余导入删除**：fetch_batch_stocks 内 `import pandas as pd` 删除（文件顶部已导入）
   - **未使用变量删除**：`merged_records = []` 定义后从未使用，删除
   - **hasattr 无效检查改为列存在验证**：itertuples 的 namedtuple 字段由 DataFrame 列名决定，hasattr 对所有行结果相同，改为写入前验证列存在
   - **format_final_output 内存峰值优化**：改为分阶段加载，先处理因子数据并 del，再加载收益数据

70. **MODULE.md v2.69 (2026-05-26)** — 规范补充
   - **新增约束 #10**：itertuples 前验证列存在（hasattr 对同一 DataFrame 无效）
   - **新增约束 #11**：大文件分阶段加载（避免内存峰值）
   - **规范补充原因**：代码审查发现无效防御性检查、内存峰值问题

71. **fetch_factor_cache.py v3.14 (2026-05-26)** — Bug修复（5项）
   - **validate_final_data 数据有效性验证**：增加 RSI 非空比例 >= 80% 检查，综合判断（天数 + 数据有效性）
   - **peek_key 检查 exhausted**：`if self.exhausted or self.idx >= len(self.records)`，语义一致性
   - **get_memory_usage_mb Windows 兜底**：`import resource` try-except 兜底返回 0.0
   - **main docstring 删除冗余 Returns**：None 返回类型不需要 Returns 节
   - **version 字段提取为常量**：`_OUTPUT_VERSION = '3.14'`，两处引用统一

72. **MODULE.md v2.70 (2026-05-26)** — 规范补充
   - **新增约束 #12-#16**：数据验证综合判断、peek_key 检查 exhausted、Windows 兜底、docstring 无 Returns、version 常量
   - **规范补充原因**：代码审查发现验证逻辑宽松、语义不一致、跨平台兼容性缺失、版本号维护困难

73. **fetch_factor_cache.py v3.15 (2026-05-26)** — Bug修复（2项）
   - **n_way_merge 去重逻辑修正**：使用正值 `batch_idx`（而非负值），让高 batch_idx 后弹出，最终保留高 batch_idx 记录
   - **变量名语义修正**：`stream_idx` → `batch_idx`，消除"流索引"vs"负批次号"的语义混乱

74. **MODULE.md v2.71 (2026-05-26)** — 规范修正
   - **约束 #9 修正**："N-way merge 去重使用正值 batch_idx"（而非"使用 batch_idx"）
   - **修正原因**：负值会导致高 batch_idx 先弹出，与去重替换逻辑矛盾

75. **fetch_factor_cache.py v3.16 (2026-05-26)** — Bug修复（4项）
   - **main 版本号改用 _OUTPUT_VERSION**：`logger.info(f"  版本: {_OUTPUT_VERSION}")`（而非硬编码 3.10）
   - **format_final_output 固定生成时间**：入口处 `generated_at = datetime.now().isoformat()`，避免两次调用不一致
   - **save_batch_cache_sorted 入口 copy()**：防止修改调用方 DataFrame 引用
   - **validate_final_data 均匀抽样**：`step = total_records // sample_size`，避免 `[:1000]` 取前1000条偏差

76. **MODULE.md v2.72 (2026-05-26)** — 规范补充
   - **新增约束 #17-#18**：datetime.now() 固定时间戳、抽样检查均匀抽样
   - **约束 #6 补充说明**：包括 save_batch_cache_sorted
   - **规范补充原因**：代码审查发现版本号维护困难、时间戳不一致、抽样偏差

77. **fetch_factor_cache.py v3.17 (2026-05-26)** — Bug修复（4项）
   - **_OUTPUT_VERSION 移到 import 之后**：遵循 PEP 8 模块级代码顺序规范
   - **pop_record 检查 exhausted**：与 peek_key 对称，避免 exhausted=True 时仍返回数据
   - **sys 导入移除**：未使用，v3.10 移除 os 但漏了 sys
   - **cleanup_batch_files 用 try/finally**：保证临时文件清理（无论成功或失败）

78. **MODULE.md v2.73 (2026-05-26)** — 规范补充
   - **约束 #13 修正**：peek_key/pop_record 检查 exhausted（两个方法对称）
   - **新增约束 #19-#20**：常量定义在 import 之后、cleanup_batch_files 用 try/finally
   - **规范补充原因**：代码审查发现 PEP 8 顺序违规、方法不对称、临时文件清理不保证

79. **fetch_factor_cache.py v3.18 (2026-05-26)** — Bug修复（3项）
   - **n_way_merge 显式收集后选最大**：收集相同 key 所有记录后按 batch_idx 降序选最大，不依赖弹出顺序
   - **datetime.now() 只调用一次**：`now = datetime.now()` 后生成 `generated_at` 和 `last_updated` 两个格式
   - **save_batch_cache_sorted 移除 copy**：改为文档说明就地修改 date 列，避免内存峰值翻倍

80. **MODULE.md v2.74 (2026-05-26)** — 规范修正
   - **约束 #6 修正**：函数修改 DataFrame 需文档说明（不强制 copy）
   - **约束 #17 修正**：datetime.now() 只调用一次（而非"固定时间戳"）
   - **新增约束 #21**：N-way merge 显式收集后选最大
   - **规范修正原因**：copy 导致内存峰值翻倍，文档说明更灵活；弹出顺序依赖不可靠

81. **fetch_factor_cache.py v3.19 (2026-05-26)** — Bug修复（5项）
   - **validate_final_data 流式读取**：避免 json.load 全量加载只为抽样，改为流式迭代
   - **format_final_output 只保留标量**：date_start/date_end/n_assets，而非完整 dates_list/assets_list
   - **模块级注释合并到常量**：注释紧贴 _MODULE_LOGGER 和 _OUTPUT_VERSION 定义
   - **cleanup_batch_files 增加兜底**：merged_*.json.gz 可能残留，增加兜底清理
   - **n_way_merge 移除冗余赋值**：`streams = []` 在函数返回前无实际效果

82. **MODULE.md v2.75 (2026-05-26)** — 规范修正
   - **约束 #10-#11 修正**：大文件流式读取验证、meta 信息只保留标量
   - **新增约束 #22-#23**：cleanup 增加兜底清理、模块级注释合并到常量
   - **规范修正原因**：全量加载只为抽样浪费内存；完整列表用于 meta 信息冗余

83. **fetch_factor_cache.py v3.20 (2026-05-26)** — Bug修复（4项）
   - **validate_final_data 初始化默认值**：n_days/n_assets/date_start/date_end 初始化为 0/""，防止 NameError
   - **validate_final_data 健壮 meta 解析**：收集 meta 行后用 json.loads 解析，而非手动字符串匹配
   - **validate_final_data step 保守估计**：若 n_days=0 则使用 sample_size*100 保守步长
   - **n_way_merge 增加 counter**：heap 元素增加唯一计数器，打破同批次相同 key 的平局

84. **MODULE.md v2.76 (2026-05-26)** — 规范修正
   - **约束 #9 修正**：heap 元素增加 counter 打破平局
   - **新增约束 #24-#25**：变量初始化默认值、meta 解析用 json.loads
   - **规范修正原因**：变量未初始化导致 NameError；手动字符串匹配脆弱

85. **fetch_factor_cache.py v3.21 (2026-05-26)** — Bug修复（4项）
   - **is_exhausted 逻辑修正**：`return self.exhausted or self.idx >= len(self.records)`（而非 and）
   - **_load_next_chunk 改名**：改为 `_load_all`，语义更清晰（一次性加载，而非暗示多次调用）
   - **main 返回值冗余**：删除 format_final_output 返回值使用，统计信息由 validate_final_data 提供
   - **save_batch_cache_sorted 接口契约**：补充 Note 说明输入/输出类型

86. **MODULE.md v2.77 (2026-05-26)** — 规范修正
   - **新增约束 #14**：is_exhausted 逻辑用 or
   - **新增约束 #26-#28**：方法名语义清晰、返回值避免冗余、函数接口契约说明
   - **规范修正原因**：逻辑错误导致提前返回 False；方法名误导；返回值冗余；接口契约不清晰

87. **fetch_factor_cache.py v3.22 (2026-05-26)** — Bug修复（3项）
   - **cleanup_batch_files 增加 try**：中途出错也继续清理，收集 errors 并 warning
   - **get_memory_info_str 用 is not None**：`if vmrss is not None` 而非 `if vmrss`（0 是 falsy）
   - **write_record 闭包捕获 f**：定义在 with 块内闭包捕获，而非定义在外部又传入参数

88. **MODULE.md v2.78 (2026-05-26)** — 规范修正
   - **约束 #20 修正**：用 try 保证继续清理（而非 try/finally）
   - **新增约束 #29-#30**：vmrss 判断用 is not None、内嵌函数闭包捕获一致
   - **规范修正原因**：中途出错导致部分文件残留；0 是 falsy 导致跳过；参数传入与闭包捕获不一致

89. **fetch_factor_cache.py v3.23 (2026-05-26)** — Bug修复（1项）
   - **validate_final_data 一次性加载**：直接 json.load(full) 后提取 meta/data，避免 meta 手动拼接脆弱
   - **简化代码**：删除两阶段流式读取，改为一次性加载（meta 小，可接受）

90. **MODULE.md v2.79 (2026-05-26)** — 规范修正
   - **约束 #10/#25 修正**：大文件验证一次性加载（而非流式读取 meta）
   - **规范修正原因**：meta 手动拼接字符串脆弱，直接 json.load 更健壮

91. **fetch_factor_cache.py v3.24 (2026-05-26)** — Bug修复（4项）
   - **valid_batch_indices 移除**：收集了但从未使用，删除冗余变量
   - **heap 注释缩进修正**：注释缩进从 0 改为 4，与代码对齐
   - **valid_df 增加 copy()**：避免 SettingWithCopyWarning，每次过滤后 .copy()
   - **forward_return 统一写法**：`x.shift(-1) / x - 1` 比 `x.pct_change().shift(-1)` 更直观

92. **MODULE.md v2.80 (2026-05-26)** — 规范补充
   - **新增约束 #31-#32**：DataFrame 链式操作用 copy()、forward_return 统一写法
   - **规范补充原因**：SettingWithCopyWarning 导致赋值失败风险；pct_change().shift(-1) 不直观

93. **fetch_factor_cache.py v3.25 (2026-05-26)** — 接口设计修正（2项）
   - **format_final_output 返回 None**：删除返回值，统计信息由 validate_final_data 提供（单一来源）
   - **save_batch_cache_sorted 接口契约**：说明"实际调用方总是传字符串"，而非理想化"可以是 datetime 或字符串"

94. **MODULE.md v2.81 (2026-05-26)** — 规范补充
   - **约束 #28 修正**：接口契约说明实际调用方行为
   - **新增约束 #33-#34**：函数签名与调用一致、统计信息单一来源
   - **规范补充原因**：接口契约理想化不匹配实际；返回值被丢弃但函数做了大量工作

95. **fetch_factor_cache.py v3.26 (2026-05-26)** — Bug修复（3项）
   - **format_final_output 缩进修正**：注释缩进从 0 改为 4，避免 IndentationError
   - **validate_final_data 分两次读**：第一次只读 meta，第二次流式扫描 data，避免一次性加载大文件
   - **records_count 初始化**：函数顶部初始化 records_count = 0，防止 NameError

96. **MODULE.md v2.82 (2026-05-26)** — 规范修正
   - **约束 #10/#25 修正**：分两次读文件（而非一次性加载）
   - **约束 #24 修正**：函数顶部初始化所有返回值变量（包括 records_count）
   - **新增约束 #35**：缩进一致性检查
   - **规范修正原因**：一次性加载大文件内存峰值；records_count 未初始化；缩进错误导致 SyntaxError

97. **fetch_factor_cache.py v3.27 (2026-05-26)** — 代码改进（7项）
   - **BatchStream.pop_record 更新 exhausted**：弹出后立即更新状态
   - **BatchStream.__lt__ 添加**：用于 heap 比较的防御性编程
   - **del 注释修正**：准确描述为"减少引用计数"而非"释放内存"
   - **combined 增加 copy()**：sort_values 后避免 CoW 风险
   - **del data 而非 del full**：释放内存顺序正确
   - **main 用 _ 接收**：未使用返回值明确表示不使用
   - **n_records 保留用于日志**：命名合理，格式化前的记录数

98. **MODULE.md v2.83 (2026-05-26)** — 规范补充
   - **新增约束 #36-#41**：BatchStream.__lt__、pop_record 更新 exhausted、del 注释准确、sort_values 后 copy()、del 释放顺序、未使用返回值用 _
   - **规范补充原因**：heap 对象不可比较风险；状态不一致；注释误导；CoW 风险；内存释放顺序错误；未使用变量混淆

99. **fetch_factor_cache.py v3.28 (2026-05-27)** — Bug修复（1项）
   - **validate_final_data 真正流式扫描**：第二次改为流式行扫描，只解析抽样的行，避免两次 json.load 内存峰值翻倍

100. **MODULE.md v2.84 (2026-05-27)** — 规范修正
   - **约束 #10 修正**：明确第二次是"流式行扫描只解析抽样行"，而非"流式扫描 data"
   - **规范修正原因**：两次 json.load 整个大文件导致内存峰值翻倍，"分两次读"目标未实现

101. **fetch_factor_cache.py v3.29 (2026-05-27)** — Bug修复（2项）
   - **format_final_output 一次遍历**：合并 min/max/set 四次遍历为一次，同时释放 set 内存
   - **main 双校验合并路径**：factor_merged_path 和 return_merged_path 都校验，避免 None 路径触发 TypeError

102. **MODULE.md v2.85 (2026-05-27)** — 规范补充
   - **新增约束 #42-#44**：一次遍历提取元信息、set 内存立即释放、合并路径双校验
   - **规范补充原因**：四次遍历内存峰值（两份 set 同时存在）；return_merged_path 为 None 触发 TypeError

103. **fetch_factor_cache.py v3.30 (2026-05-27)** — 代码改进（2项）
   - **format_final_output n_records 定义**：移到日志前，明确仅用于日志
   - **cleanup_batch_files docstring 修正**：描述为 try/except（而非 try/finally），与实际实现一致

105. **MODULE.md v2.86 (2026-05-27)** — 规范修正
   - **约束 #20 修正**：cleanup_batch_files 用 try/except（而非 try/finally）
   - **规范修正原因**：docstring 描述与实现不一致

106. **fetch_factor_cache.py v3.31 (2026-05-27)** — Bug修复
   - **n_way_merge_deduplicate 返回值简化**：只返回 merged_path（而非 `(merged_path, count)`）
   - **调用方适配**：不再用 `_` 接收第二个返回值
   - **修复原因**：count 未被使用，统计信息由 validate_final_data 提供（单一来源）

108. **fetch_factor_cache.py v3.32 (2026-05-27)** — Bug修复（2项）
   - **format_final_output**：删除 n_records 重复赋值（第693行和第699行）
   - **validate_final_data**：改为真正流式验证（第一次只读 meta，第二次流式扫描边计数边抽样）
   - **修复原因**：重复赋值误导注释；第一次 json.load 加载完整 data 列表触发内存峰值

109. **MODULE.md v2.88 (2026-05-27)** — 规范补充
   - **新增约束 #46-#47**：流式验证不加载 data、变量定义位置合理
   - **规范补充原因**：validate_final_data 加载完整 data 列表导致内存峰值；n_records 重复赋值误导注释

110. **fetch_industry.py v1.1 (2026-05-27)** — 优化（6项）
   - **版本号常量**：添加 `_OUTPUT_VERSION = '1.1'`（MODULE.md 约束 #16）
   - **Dict → dict**：Python 3.9+ 使用内置类型注解
   - **iterrows → to_dict**：性能优化，避免逐行迭代
   - **输出路径修正**：从 cache 改为 result 目录（MODULE.md 约束 #2）
   - **__main__ logger**：遵循 PROJECT.md 日志规范
   - **文档头规范**：添加日期、版本、改进历史、约束合规说明

111. **MODULE.md v2.89 (2026-05-27)** — 版本历史补充
   - **新增 fetch_industry.py v1.1 版本历史**

112. **fetch_industry.py v1.2 (2026-05-27)** — Bug修复（5项）
   - **docstring Returns Dict→dict**：5处类型描述修正
   - **mkdir 用 RESULT_DIR**：输出目录与规范一致（MODULE.md 约束 #2）
   - **meta 添加 version 字段**：缓存文件包含版本号
   - **修复原因**：v1.1 只修改函数签名，遗漏 docstring 内部类型描述

113. **MODULE.md v2.90 (2026-05-27)** — 版本历史补充
   - **新增 fetch_industry.py v1.2 版本历史**

114. **fetch_industry.py v1.3 (2026-05-27)** — Bug修复（7项）
   - **文档头版本号同步**：v1.1 → v1.3（与代码一致）
   - **第355行 Dict→dict**：get_industry_distribution docstring 遗漏修改
   - **异常日志加类型名**：3处异常处理补充 `[{type(e).__name__}]`
   - **Counter 顶部导入**：从函数内移到模块顶部（PEP 8）
   - **原子写入异常处理**：try-except 包裹 rename，失败时 unlink 清理 .tmp
   - **__all__ 导出列表**：公共模块明确导出接口

115. **MODULE.md v2.91 (2026-05-27)** — 规范补充
   - **新增约束 #50-#53**：异常日志类型名、顶部导入、原子写入异常处理、__all__导出

116. **fetch_industry.py v1.4 (2026-05-27)** — Bug修复（3项）
   - **SW_INDUSTRY_CODE_MAP 添加注释 + TODO**：说明为近似映射，补充 TODO 核对官方标准
   - **原子写入捕获所有异常**：except Exception（而非仅 OSError），日志移到 rename 成功后
   - **全局缓存线程安全（DCL）**：threading.Lock + 双重检查锁

117. **MODULE.md v2.92 (2026-05-27)** — 规范补充
   - **新增约束 #54-#57**：数据映射注释+TODO、原子写入异常范围、日志位置、线程安全缓存

118. **fetch_industry.py v1.5 (2026-05-27)** — Bug修复（3项）
   - **日期解析异常 warning 日志**：`except ValueError as e` + `{updated_at!r}: {e}`（而非静默 pass）
   - **关键词映射移除歧义**：移除 '新能'（改为 '新能源'），移除 '信达'/'华创'（银行关键词）
   - **__all__ 移除私有名称**：移除 `_OUTPUT_VERSION`（以 `_` 开头表示模块私有）

119. **MODULE.md v2.93 (2026-05-27)** — 规范补充
   - **新增约束 #58-#60**：异常捕获需打印详情、关键词映射避免歧义、__all__ 不含私有名称

120. **fetch_industry.py v1.6 (2026-05-27)** — Bug修复（2项）
   - **DataFrame 列名校验**：校验 `_EXPECTED_INDUSTRY_COLS` 和 `_EXPECTED_STOCK_NAME_COLS`
   - **备用数据路径参数注入**：`STOCK_LIST_BACKUP_PATH` 常量 + `load_local_industry_backup(stock_list_path)` 参数

121. **MODULE.md v2.94 (2026-05-27)** — 规范补充
   - **新增约束 #61-#62**：DataFrame 列名校验、路径提取常量 + 参数注入

122. **fetch_industry.py v1.7 (2026-05-27)** — Bug修复（4项）
   - **threading 重复导入删除**：顶部已导入，删除第358行重复导入
   - **关键词重叠消除**：光伏/风电 只在电力中，新能源使用锂电/电池/太阳能
   - **注释修正**：中信在证券分类（而非银行），修正误导性注释
   - **备用数据写入缓存**：添加 `_write_backup_cache()` + `write_cache=True` 参数

123. **MODULE.md v2.95 (2026-05-27)** — 规范补充
   - **新增约束 #63-#66**：导入语句不散落、关键词映射消除重复、注释与代码一致、备用数据写入缓存

124. **fetch_industry.py v1.8 (2026-05-27)** — Bug修复（3项）
   - **缓存过期刷新失败降级**：`try: return refresh_industry_cache() except: return industries`（旧缓存）
   - **SW_INDUSTRY_CODE_MAP 注释修正**：说明具体映射来源（如"化学原料+化学制品 → 基础化工"），移除 TODO
   - **load_local_industry_backup 注释修正**：docstring 说明"基于名称关键词推断"（而非"代码特征"）

125. **MODULE.md v2.96 (2026-05-27)** — 规范补充
   - **新增约束 #67-#69**：缓存刷新失败降级、数据映射注释说明具体、文档注释与实现一致

126. **fetch_industry.py v1.9 (2026-05-27)** — Bug修复（注释诚实化）
   - **SW_INDUSTRY_CODE_MAP 注释诚实化**：承认"未核对申万官方标准"，恢复 TODO
   - **注释改为"二级归属待核实"**：不编造来源（如"化学原料+化学制品"）
   - **说明映射来源**：基于 akshare 实际返回数据建立，而非官方标准

127. **MODULE.md v2.97 (2026-05-27)** — 规范补充
   - **新增约束 #70**：注释诚实化（未核对官方标准需诚实说明，不编造来源）

128. **fetch_industry.py v2.0 (2026-05-27)** — Bug修复（映射核对官方标准）
   - **SW_INDUSTRY_CODE_MAP 核对申万2021官方标准**：移除错误映射
   - **不存在的一级代码映射到 '其他'**：22, 28, 33, 37, 47, 51, 61 → '其他'
   - **官方一级分类（31个行业）**：一级代码连续：11, 21, 23, 24, 25, 26, 27, 31, 32, 34, 35, 36, 41, 42, 43, 44, 45, 46, 48, 49, 62, 63, 64, 65, 71, 72, 73, 74, 75, 76, 77

129. **MODULE.md v2.98 (2026-05-27)** — 规范补充
   - **新增约束 #71**：映射核对官方标准（核对官方标准后修正映射，不存在的一级代码映射到 '其他'）

130. **fetch_industry.py v2.1 (2026-05-27)** — Bug修复（2项）
   - **日志信息修正**："akshare 获取失败，尝试本地备用数据..."（而非"获取失败，返回空映射"）
   - **备用缓存写入策略 docstring 说明**：非致命错误（warning），与主缓存策略不同（主缓存失败抛异常）

131. **MODULE.md v2.99 (2026-05-27)** — 规范补充
   - **新增约束 #72-#73**：备用缓存写入策略（非致命）、日志信息准确反映流程

132. **fetch_industry.py v2.2 (2026-05-27)** — Bug修复（数据完整性验证）
   - **load_stock_industry 缓存数据完整性验证**：检查 industries 是否为 dict 类型
   - **防止后续 AttributeError**：若 industries 为 None/list，删除损坏缓存并重新获取

133. **MODULE.md v3.00 (2026-05-27)** — 规范补充
   - **新增约束 #74**：缓存数据完整性验证（检查 industries 是否为 dict 类型）

134. **fetch_industry.py v2.3 (2026-05-27)** — Bug修复（3项）
   - **datetime.now() 单次调用**：固定时间戳避免不一致
   - **infer_industry_from_name Note 说明**：模糊匹配优先级（如"中信银行"→证券）
   - **get_industry_distribution 类型注解**：`dict[str, int]`

135. **MODULE.md v3.01 (2026-05-27)** — 规范补充
   - **新增约束 #75-#76**：模糊匹配优先级说明、返回类型注解完整

136. **dataframe_utils.py v1.0-v1.7 (2026-05-27)** — 公共模块新增
   - **v1.0**: 首次创建，validate_dataframe_columns 函数
   - **v1.1**: logger 参数化，错误信息包含可用列
   - **v1.2**: 导入顺序PEP8规范化，删除未使用导入，添加边界处理
   - **v1.3**: docstring Example 完善，正常+异常场景分离
   - **v1.4**: MODULE.md 版本历史同步，测试边界完善（TC009/TC010）
   - **v1.5**: __all__ 放置位置PEP8规范化，df_name 参数支持 None，类型注解更新
   - **v1.6**: 模块级常量定义，df_name 边界校验顺序优化，日志级别调整，集合操作优化
   - **v1.7**: df 类型检查改用 isinstance，删除冗余 info 日志，优化 debug 输出格式，缺失列顺序保持原始顺序

137. **test_dataframe_utils.py v1.0-v1.5 (2026-05-27)** — 测试文件新增
   - **v1.0**: 首次创建，覆盖正常/异常/边界场景（TC001-TC008）
   - **v1.1**: 导入顺序PEP8规范化，测试日志命名合规化
   - **v1.2**: 新增 TC009/TC010 测试边界（df_name空字符串、列名大小写敏感）
   - **v1.3**: 删除 __main__ 块，新增 TC011（df_name 为 None）
   - **v1.4**: 新增 TC012/TC013 验证默认值在错误信息中的使用
   - **v1.5**: 更新 TC003/TC013 适配 isinstance 类型检查，新增 TC014/TC015/TC016 验证非DataFrame类型和顺序保持

49. **MODULE.md v2.58 (2026-05-26)** — 规范补充
   - **类型注解兼容性规范**：补充兼容类型说明（Python 运行时不强制类型检查）
   - **docstring Raises 规范**：描述应与实际抛出一致，不应描述未实现的场景
   - **兜底块异常信息规范**：应包含异常类型和详情（便于追溯）

---

data_fetchers 模块负责：
1. 从外部数据源拉取因子数据、收益数据等
2. 统一因子生成（新增）
3. 存储到 cache 目录

**模块定位：**
- 输入：外部数据源（API、数据库等）+ 基础因子数据
- 输出：cache/factor_data/ 缓存文件

---

## 数据流程

```
外部数据源 → data_fetchers/ → cache/factor_data/ → factor_ic/
                   ↑
                   │
           factor_generator.py（统一因子生成）
```

**关键原则：**
- factor_ic 不自行拉取数据，只使用 cache
- data_fetchers 负责数据质量和格式转换
- **factor_generator.py 作为单一因子数据源（2026-05-24 新增）**

---

## 脚本命名规则

### 数据拉取脚本

**命名格式：** `fetch_<数据源名>.py`

| 脚本名 | 数据源 | 说明 |
|--------|--------|------|
| fetch_turnover.py | 换手率 | 拉取换手率数据 |
| fetch_stock_list.py | 股票列表 | 拉取 A 股股票列表 |
| fetch_industry.py | 行业分类 | 拉取行业分类数据 |

### 因子生成脚本

**命名格式：** `factor_generator.py`（统一入口）

---

## 公共模块架构

**目录规范：data_fetchers 下的公共模块放在 `data_fetchers/common/` 目录。**

禁止在脚本中重复实现已有公共功能，应复用 common 模块。

### 模块清单

| 模块 | 功能 | 核心函数 |
|------|------|----------|
| `paths.py` | 路径管理 | `get_cache_dir()`, `get_factor_data_dir()`, `get_stock_list_file()` |
| `cache_manager.py` | 缓存读写 | `read_gzip_cache()`, `write_gzip_cache()` |
| `http_client.py` | HTTP 客户端 | `create_retry_session()`, `create_eastmoney_session()` |
| `stock_utils.py` | 股票筛选 | `is_main_board_stock()`, `load_main_board_stock_list()` |

详细规范见 `data_fetchers/common/README.md`。

### 使用方式

```python
from data_fetchers.common import (
    get_cache_dir,
    read_gzip_cache,
    create_eastmoney_session,
    load_main_board_stock_list,
)

# 获取路径
cache_dir = get_cache_dir()

# 读取缓存
data = read_gzip_cache(cache_dir / 'factor_data/data.json.gz')

# 创建 HTTP Session
session = create_eastmoney_session()

# 加载主板股票列表
stocks = load_main_board_stock_list()
```

---

## 公共模块使用规范

### cache_manager.py 日志参数规范（2026-05-24 新增）

**遵循 PROJECT.md 第783-857行规范，公共模块接收 logger 参数。**

**缓存文件格式限制（2026-05-25 补充）：**
- 缓存文件必须是 JSON 格式（gzip 压缩或非压缩）
- `.gz` 文件必须是 gzip 压缩的 JSON，不能是纯 gzip 二进制文件
- `read_cache`、`read_gzip_cache` 内部调用 `json.load()`，非 JSON 文件会抛 `ValueError`
- 违反此限制会导致 JSON 解析失败

**使用方式：**
```python
from data_fetchers.common import read_gzip_cache
import logging

# 调用方传入 logger（推荐）
logger = logging.getLogger('factor_ic.ic_rsi_1d')
data = read_gzip_cache(cache_file, logger=logger)

# 不传 logger 时使用默认 logger（fallback）
data = read_gzip_cache(cache_file)  # 自动创建模块级 logger
```

**参数类型：**
- `path`: 支持 `Path | str`，内部统一转换为 Path
- `logger`: 可选，传入调用方的 logger 以追溯调用方

**禁止：**
```python
# ❌ 公共模块独立创建 logger（旧方式，已废弃）
# logger = logging.getLogger(__name__)  # 无法追溯调用方
```

**为何必须传入 logger：**
1. 日志可追溯调用方，便于定位问题
2. 符合 PROJECT.md 公共模块日志规范
3. 模块级 fallback logger 作为兼容方案

### 日志换行符规范（2026-05-25 新增）

**原则：** logging 模块的格式化器通常不期望消息内含换行，某些 handler（如 RotatingFileHandler）处理含换行的日志可能产生解析问题。

**允许使用换行符的场景：**

1. **错误日志多行格式化**
   - 复杂错误（如 JSON 解析失败）允许多行格式化输出以提高可读性
   - 示例：
     ```python
     logger.error(
         "JSON 解析失败\n"
         "文件路径: %s\n"
         "错误位置: 行 %d, 列 %d\n"
         "错误信息: %s",
         file_path, e.lineno, e.colno, e.msg
     )
     ```

2. **__main__ 测试块视觉分隔**
   - 自测试输出允许多行分隔符以提高可读性
   - 示例：
     ```python
     test_logger.info("\n[测试 1] 函数定义验证...")
     test_logger.info("\n" + "=" * 40)
     ```

**不建议使用换行符的场景：**

1. **一般 info 级别日志**
   - 避免 info 日志中使用 `\n` 换行符
   - 某些 handler（如 RotatingFileHandler）解析含换行的日志可能产生问题
   - 示例（禁止）：
     ```python
     # ❌ info 日志中使用换行符
     logger.info("数据加载完成\n记录数: %d", count)
     
     # ✅ 改为单行格式
     logger.info("数据加载完成，记录数: %d", count)
     ```

**JSON 解析异常处理：**
- 抛出 `ValueError` 而非 `json.JSONDecodeError`
- 避免传递完整 JSON 文档导致内存翻倍
- 参考 `references/backtest-module-optimization-patterns.md Section 1.2`

### 临时文件命名规范（2026-05-25 新增）

**问题背景：**
- `Path.with_suffix('.tmp')` 会替换最后一个后缀
- 对于 `.json.gz` 文件，会变成 `.json.tmp`（丢失 `.gz` 后缀）
- 导致临时文件名与原文件名不一致

**正确用法：**
```python
# ✅ 正确：追加 .tmp 后缀，保留原文件名
temp_path = output_path.parent / (output_path.name + '.tmp')
# factor_data.json.gz → factor_data.json.gz.tmp

# ❌ 错误：替换最后一个后缀
temp_path = output_path.with_suffix('.tmp')
# factor_data.json.gz → factor_data.json.tmp（丢失 .gz）
```

**适用场景：**
- 原子写入（临时文件 + os.replace）
- gzip 压缩文件写入
- 多后缀文件（如 `.tar.gz`、`.json.gz`）

### 异常捕获规范（2026-05-25 新增）

**问题背景：**
- `PermissionError` 是 `OSError` 的子类
- `IOError` 在 Python 3 中已合并到 `OSError`
- 重复捕获会导致代码冗余

**正确用法：**
```python
# ✅ 正确：OSError 涵盖 PermissionError 和 IOError
except OSError as e:
    # 文件系统错误（磁盘/权限/IO）
    ...

# ❌ 错误：重复捕获子类
except (OSError, PermissionError, IOError) as e:
    # PermissionError 是 OSError 子类，冗余
    ...
```

**OSError 子类关系：**
- `PermissionError` ⊆ `OSError`
- `FileNotFoundError` ⊆ `OSError`
- `IOError` = `OSError`（Python 3 合并）

### __main__ 测试块规范（2026-05-25 新增）

**问题背景：**
- `if __name__ == '__main__'` 时，模块名是 `__main__`
- `from data_fetchers.xxx import ...` 会触发重新导入
- 导致模块被执行两次，产生循环/重复行为

**正确用法：**
```python
# ✅ 正确：直接使用已定义的函数
if __name__ == '__main__':
    # 函数已在模块中定义，直接使用
    metadata = generate_all_factors(logger=test_logger)

# ❌ 错误：重新导入自己（循环导入）
if __name__ == '__main__':
    from data_fetchers.factor_generator import generate_all_factors  # 触发重新导入
    metadata = generate_all_factors(logger=test_logger)
```

**适用场景：**
- 模块自测试（__main__ 测试块）
- CLI 入口测试

**__main__ 块结构规范（2026-05-25 补充）：**

原则：`__main__` 块应作为 CLI 入口调用 `main()` 函数，测试代码应移至独立测试脚本。

```python
# ✅ 正确：__main__ 块作为 CLI 入口
if __name__ == '__main__':
    import sys
    sys.exit(main())

# ❌ 错误：__main__ 块直接运行测试代码
if __name__ == '__main__':
    test_logger = setup_logger(...)
    metadata = generate_all_factors(logger=test_logger)
    # ... 60行测试代码 ...
```

**测试代码位置规范：**
- 测试脚本应放在 `test_cases/test_xxx.py`
- 示例：`data_fetchers/test_cases/test_factor_generator.py`
- 测试脚本独立运行，与 CLI 入口分离

**为何必须分离：**
1. `__main__` 块应保持简洁，便于 CLI 调用
2. 测试代码复杂时会影响 CLI 入口可读性
3. 测试脚本可独立执行，便于 CI/CD 集成

### 条件导入位置规范（2026-05-25 新增）

**问题背景：**
- PEP 8 规范：导入应在文件顶部
- 多个 `if __name__ == '__main__'` 块分散在文件中间违反规范

**正确用法：**
```python
# ✅ 正确：所有条件导入合并到顶部
if __name__ == '__main__':
    import sys
    from xxx import func_a
    from xxx import func_b
else:
    from .xxx import func_a
    from .xxx import func_b

# ❌ 错误：条件导入分散在文件中间
if __name__ == '__main__':
    import sys
    from xxx import func_a
else:
    from .xxx import func_a

# ... 几十行代码后 ...

if __name__ == '__main__':
    from xxx import func_b  # 违反 PEP 8 导入位置规范
else:
    from .xxx import func_b
```

### 除零保护规范（2026-05-25 新增）

**问题背景：**
- 百分比计算 `count / total * 100` 在空数据时抛 `ZeroDivisionError`
- 函数内嵌套定义辅助函数导致作用域混乱

**正确用法：**
```python
# ✅ 正确：模块级私有函数，作用域清晰
def _calc_pct(valid_count: int, total_count: int) -> float:
    if total_count <= 0:
        return 0.0
    return round(valid_count / total_count * 100, 2)

# 调用方式
logger.info("有效记录: %d (%.2f%%)", valid, _calc_pct(valid, total))

# ❌ 错误：函数内嵌套定义
def generate_all_factors(...):
    # ...几十行代码...
    def calc_pct(valid_count):  # 作用域混乱
        return round(valid_count / total * 100, 2) if total > 0 else 0.0
```

**适用场景：**
- 有效记录百分比计算
- 缺失记录百分比计算
- 任何需要除零保护的百分比计算

### 硬编码常量规范（2026-05-25 新增）

**问题背景：**
- `output_cols[8:]` 等切片索引依赖列表顺序，脆弱
- 列顺序变化会导致索引错误

**正确用法：**
```python
# ✅ 正确：常量定义，明确语义
_EXTENDED_FACTOR_COLS = ['bollinger_pb', 'kdj_j', 'turnover_surge']
metadata['factor_columns'] = _EXTENDED_FACTOR_COLS

# ❌ 错误：切片索引，脆弱
output_cols = ['date', 'asset', 'open', 'close', 'high', 'low', 'rsi_6', 'volume_ratio_5', ...]
metadata['factor_columns'] = output_cols[8:]  # 依赖顺序
```

**适用场景：**
- 扩展因子列名
- 固定字段列表
- 任何不应依赖顺序的常量列表

### 临时文件清理规范（2026-05-25 新增）

**问题背景：**
- `exists() + unlink()` 存在 TOCTOU（Time-of-check-to-time-of-use）竞争窗口
- 检查文件存在与删除文件之间存在时间差，并发场景可能产生 FileNotFoundError

**正确用法：**
```python
# ✅ 正确：原子操作，消除 TOCTOU 竞争窗口
temp_path.unlink(missing_ok=True)

# ❌ 错误：TOCTOU 竞争窗口
if temp_path.exists():
    temp_path.unlink()  # 竞争窗口：exists() 后文件可能被其他进程删除
```

**适用场景：**
- 异常处理中的临时文件清理
- 原子写入失败后的清理
- 任何需要安全删除可能不存在文件的场景

**Python 版本要求：**
- Python 3.8+ 支持 `missing_ok=True`

### docstring Raises 规范（2026-05-25 新增）

**问题背景：**
- Raises 声明的异常应与实际抛出一致
- 已内部捕获转换的异常不应声明（调用方永远不会收到）

**正确用法：**
```python
# ✅ 正确：只声明调用方可能收到的异常
def generate_all_factors(...):
    """
    Raises:
        FileNotFoundError: 输入数据文件不存在
        ValueError: JSON 解析失败（已内部捕获转换）
        RuntimeError: 文件系统错误
    """
    try:
        data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(...) from e  # 转换，调用方收到 ValueError

# ❌ 错误：声明已转换的异常
def generate_all_factors(...):
    """
    Raises:
        json.JSONDecodeError: JSON 解析失败  # 调用方永远不会收到
    """
```

**原则：**
- Raises 声明应与实际抛出一致
- 已捕获转换的异常不应声明
- 补充 Note 说明内部转换逻辑

### 常量引用关系规范（2026-05-25 新增）

**问题背景：**
- 多个常量各自硬编码相同内容，没有引用关系
- 新增内容时需同时修改多处，极易遗漏
- 维护隐患：一处修改遗漏会导致不一致

**正确用法：**
```python
# ✅ 正确：建立引用关系，一处定义多处使用
_EXTENDED_FACTOR_COLS = ['bollinger_pb', 'kdj_j', 'turnover_surge']
_BASE_COLS = ['date', 'asset', 'open', 'close', 'high', 'low', 'rsi_6', 'volume_ratio_5']
_OUTPUT_COLS = _BASE_COLS + _EXTENDED_FACTOR_COLS

output_cols = _OUTPUT_COLS  # 引用，非硬编码
metadata['factor_columns'] = _EXTENDED_FACTOR_COLS  # 同一常量引用

# ❌ 错误：各自硬编码，没有引用关系
_EXTENDED_FACTOR_COLS = ['bollinger_pb', 'kdj_j', 'turnover_surge']
output_cols = ['date', 'asset', ..., 'bollinger_pb', 'kdj_j', 'turnover_surge']  # 硬编码
metadata['factor_columns'] = ['bollinger_pb', 'kdj_j', 'turnover_surge']  # 硬编码
```

**原则：**
- 相关常量应建立引用关系
- 新增内容只需修改一处
- 消除维护隐患

### 条件块导入规范（2026-05-25 新增）

**问题背景：**
- 顶部条件块已导入模块
- __main__ 块重复导入同一模块
- 冗余代码，增加维护负担

**正确用法：**
```python
# ✅ 正确：顶部条件块导入，__main__ 块直接使用
if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(project_root))
    from xxx import func_a
else:
    from .xxx import func_a

# 底部 __main__ CLI 入口
if __name__ == '__main__':
    sys.exit(main())  # sys 已在顶部导入，直接使用

# ❌ 错误：__main__ 块重复导入
if __name__ == '__main__':
    import sys  # 顶部已导入，重复
    sys.exit(main())
```

**原则：**
- 条件块导入的模块在同一执行路径内可见
- 无需在 __main__ 块重复导入
- 减少冗余代码

### 输出目录创建规范（2026-05-25 新增）

**问题背景：**
- 输出文件父目录可能不存在
- 直接写入会导致 FileNotFoundError
- 需在写入前确保目录存在

**正确用法：**
```python
# ✅ 正确：写入前确保父目录存在
output_path.parent.mkdir(parents=True, exist_ok=True)
temp_path = output_path.parent / (output_path.name + '.tmp')

# ❌ 错误：未创建父目录，可能导致 FileNotFoundError
temp_path = output_path.parent / (output_path.name + '.tmp')
with open(temp_path, 'w') as f:  # 父目录不存在时报错
    json.dump(data, f)
```

**参数说明：**
- `parents=True`：创建所有必要的父目录
- `exist_ok=True`：目录已存在时不报错

**适用场景：**
- 文件写入前
- 临时文件创建前
- 任何需要确保目录存在的场景

### docstring 示例规范（2026-05-25 新增）

**问题背景：**
- 过于具体的示例值（如 `120.5`）可能误导用户
- 实际运行值可能与示例差距悬殊（单元测试耗时 < 1ms）
- docstring 应反映真实场景而非假设值

**正确用法：**
```python
# ✅ 正确：范围说明或注释
>>> metadata['elapsed_seconds']  # 实际耗时，单位秒（范围：0.0 ~ 数百秒，取决于数据量）

# ❌ 错误：过于具体的示例值
>>> metadata['elapsed_seconds']
120.5  # 单元测试可能耗时 < 1ms，差距悬殊
```

**原则：**
- 示例值应反映真实场景
- 避免过于具体的假设值
- 改为范围说明或注释
- 适用于不确定的值（耗时、数据量等）

### 可变对象返回副本规范（2026-05-25 新增）

**问题背景：**
- 模块级常量（列表、字典等）是可变对象
- 直接返回引用，调用方可修改
- 修改会影响模块内部状态（意外副作用）

**正确用法：**
```python
# ✅ 正确：返回副本，防止外部修改
_EXTENDED_FACTOR_COLS = ['bollinger_pb', 'kdj_j', 'turnover_surge']
metadata['factor_columns'] = list(_EXTENDED_FACTOR_COLS)  # 返回副本

# ❌ 错误：返回引用，外部可修改模块内部状态
_EXTENDED_FACTOR_COLS = ['bollinger_pb', 'kdj_j', 'turnover_surge']
metadata['factor_columns'] = _EXTENDED_FACTOR_COLS  # 返回引用
# 调用方: cols = metadata['factor_columns']; cols.append('new')  # 修改了模块常量
```

**适用场景：**
- 模块级列表常量返回
- 模块级字典常量返回
- 任何可变对象返回给外部

**原则：**
- 返回副本而非引用
- 防止外部修改模块内部状态
- 使用 `list()`、`dict()`、`.copy()` 等方法

### 常量类型规范（2026-05-25 新增）

**问题背景：**
- 模块级常量列表是可变对象
- 意外修改会导致模块状态变化
- 元组是不可变对象，防止意外修改

**正确用法：**
```python
# ✅ 正确：使用元组防止意外修改
_EXTENDED_FACTOR_COLS: tuple = ('bollinger_pb', 'kdj_j', 'turnover_surge')
_BASE_COLS: tuple = ('date', 'asset', 'open', 'close', 'high', 'low')
_OUTPUT_COLS: tuple = _BASE_COLS + _EXTENDED_FACTOR_COLS  # 元组相加仍是元组

# ❌ 错误：使用列表，可能被意外修改
_EXTENDED_FACTOR_COLS = ['bollinger_pb', 'kdj_j', 'turnover_surge']
_EXTENDED_FACTOR_COLS.append('new')  # 模块状态被修改
```

**原则：**
- 模块级常量列表应使用元组
- 元组不可变，防止意外修改
- 返回副本时使用 `list(tuple)` 转换

### 内存释放规范（2026-05-25 新增）

**问题背景：**
- 大 DataFrame 可能包含中间列（比输出更多）
- 使用完毕后仍占用内存
- 显式释放可减少内存占用

**正确用法：**
```python
# ✅ 正确：显式释放不再需要的 DataFrame
output_df = factor_df[output_cols].copy()
del factor_df  # 显式释放内存

# ❌ 错误：factor_df 仍占用内存（可能包含中间列）
output_df = factor_df[output_cols].copy()
# factor_df 未释放，内存持续占用
```

**适用场景：**
- factor_df 包含中间列（比 output_df 更多）
- 大数据处理完毕后
- 内存敏感场景

**原则：**
- 显式释放不再需要的变量
- 使用 `del var` 释放内存
- 在变量使用完毕后立即释放

### mkdir 位置规范（2026-05-25 新增）

**问题背景：**
- mkdir 在 try 块外调用，异常无法统一处理
- 与原子写入语义冲突（写入失败时无法捕获目录创建异常）

**正确用法：**
```python
# ✅ 正确：mkdir 在 try 块内，异常可统一处理
temp_path = output_path.parent / (output_path.name + '.tmp')
try:
    output_path.parent.mkdir(parents=True, exist_ok=True)  # 在 try 块内
    with open(temp_path, 'w') as f:
        json.dump(data, f)
    os.replace(temp_path, output_path)
except OSError as e:
    temp_path.unlink(missing_ok=True)
    raise RuntimeError(...)

# ❌ 错误：mkdir 在 try 块外，异常无法统一处理
output_path.parent.mkdir(parents=True, exist_ok=True)  # 在 try 块外
temp_path = output_path.parent / (output_path.name + '.tmp')
try:
    with open(temp_path, 'w') as f:
        json.dump(data, f)
except OSError as e:
    # mkdir 异常无法捕获
```

**原则：**
- mkdir 应在 try 块内调用
- 异常可统一处理
- 与原子写入语义一致

### 常量注释规范（2026-05-25 新增）

**问题背景：**
- 常量结构说明放在使用处（函数内）
- 定义处无注释，维护困难
- 注释与定义分离，修改时易遗漏

**正确用法：**
```python
# ✅ 正确：注释放在定义处
_OUTPUT_COLS: tuple = _BASE_COLS + _EXTENDED_FACTOR_COLS
# 结构说明：
# _OUTPUT_COLS[0:2]  = date, asset（索引字段）
# _OUTPUT_COLS[2:6]  = open, close, high, low（行情数据）
# ...

# 使用处只需简短说明
output_cols = _OUTPUT_COLS  # 使用模块级常量

# ❌ 错误：注释放在使用处
_OUTPUT_COLS: tuple = _BASE_COLS + _EXTENDED_FACTOR_COLS  # 定义处无注释

def func():
    # _OUTPUT_COLS[0:2]  = date, asset  # 注释分离
    # _OUTPUT_COLS[2:6]  = open, close, high, low
    output_cols = _OUTPUT_COLS
```

**原则：**
- 常量结构说明应放在定义处
- 使用处只需简短说明
- 注释与定义不分离

### 异常日志规范（2026-05-25 新增）

**问题背景：**
- 异常日志只包含错误消息
- 缺少异常类型，难以追溯问题

**正确用法：**
```python
# ✅ 正确：包含异常类型名
except Exception as e:
    logger.error("执行失败 [%s]: %s", type(e).__name__, str(e))

# ❌ 错误：缺少异常类型
except Exception as e:
    logger.error("执行失败: %s", str(e))
```

**原则：**
- 异常日志应包含异常类型名
- 使用 `type(e).__name__` 获取类型名
- 便于追溯问题根源

### docstring Example 格式规范（2026-05-25 新增）

**问题背景：**
- 注释放在返回值行而非 `>>>` 行
- 格式不规范，影响 doctest 可读性

**正确用法：**
```python
# ✅ 正确：注释放在 >>> 行，返回值行无注释
>>> metadata['factor_columns']  # 返回列表副本，防止外部修改
['bollinger_pb', 'kdj_j', 'turnover_surge']
>>> isinstance(metadata['elapsed_seconds'], float)
True

# ❌ 错误：注释放在返回值行
>>> metadata['factor_columns']
['bollinger_pb', 'kdj_j', 'turnover_surge']  # 返回列表副本
>>> metadata['elapsed_seconds']  # 实际耗时
# 缺少返回值行
```

**原则：**
- 注释放在 `>>>` 行末
- 返回值行无注释
- 保持格式简洁

### 冗余别名规范（2026-05-26 新增）

**问题背景：**
- 局部变量作为常量的别名（`output_cols = _OUTPUT_COLS`）
- 增加代码复杂度，无实际作用
- 维护时需修改多处（常量 + 别名）

**正确用法：**
```python
# ✅ 正确：直接使用常量
missing_cols = [col for col in _OUTPUT_COLS if col not in df.columns]
output_df = df[_OUTPUT_COLS].copy()

# ❌ 错误：冗余别名
output_cols = _OUTPUT_COLS  # 无意义的别名
missing_cols = [col for col in output_cols if col not in df.columns]
output_df = df[output_cols].copy()
```

**原则：**
- 直接使用模块级常量
- 避免无意义的局部别名
- 减少代码复杂度

### 职责分离规范（2026-05-26 新增）

**问题背景：**
- mkdir 和文件写入在同一个 try 块
- temp_path 定义在 try 块外，unlink 存在路径未初始化风险
- 异常信息不够精确（无法区分目录创建失败 vs 文件写入失败）

**正确用法：**
```python
# ✅ 正确：mkdir 单独处理，职责分离
try:
    output_path.parent.mkdir(parents=True, exist_ok=True)
except OSError as e:
    raise RuntimeError(f"创建输出目录失败: {output_path.parent}, ...") from e

temp_path = output_path.parent / (output_path.name + '.tmp')  # mkdir 成功后才定义
try:
    with gzip.open(temp_path, 'wt') as f:
        json.dump(data, f)
    os.replace(temp_path, output_path)
except OSError as e:
    temp_path.unlink(missing_ok=True)
    raise RuntimeError(f"文件系统错误: {output_path}, ...") from e

# ❌ 错误：mkdir 和写入混在一起
temp_path = output_path.parent / (output_path.name + '.tmp')  # mkdir 未执行就定义
try:
    output_path.parent.mkdir(parents=True, exist_ok=True)  # 混在一起
    with gzip.open(temp_path, 'wt') as f:
        json.dump(data, f)
except OSError as e:
    temp_path.unlink(missing_ok=True)  # temp_path 可能未初始化
```

**原则：**
- mkdir 单独 try 块处理
- 异常信息区分职责（目录创建 vs 文件写入）
- temp_path 在 mkdir 成功后定义

### 错误信息规范（2026-05-26 新增）

**问题背景：**
- 错误信息过于模糊（"输出列不存在"）
- 缺少上下文提示，排错路径长
- 无法快速定位问题根源

**正确用法：**
```python
# ✅ 正确：增加上下文提示
if missing_cols:
    raise KeyError(
        f"输出列不存在: {missing_cols}，"
        f"请检查因子计算函数的输出列名是否与 _EXTENDED_FACTOR_COLS 一致"
    )

# ❌ 错误：错误信息过于模糊
if missing_cols:
    raise KeyError(f"输出列不存在: {missing_cols}")  # 缺少上下文
```

**原则：**
- 错误信息应包含上下文提示
- 提供排错建议（指向可能的问题根源）
- 缩短排错路径

### tuple 类型注解规范（2026-05-26 新增）

**问题背景：**
- `tuple` 类型注解不够精确，无法表达元素类型
- Python 3.9+ 支持泛型元组 `tuple[str, ...]`
- 类型检查器无法推断元素类型

**正确用法：**
```python
# ✅ 正确：使用泛型元组（Python 3.9+）
_EXTENDED_FACTOR_COLS: tuple[str, ...] = ('bollinger_pb', 'kdj_j', 'turnover_surge')
_BASE_COLS: tuple[str, ...] = ('date', 'asset', 'open', 'close', 'high', 'low')

# ❌ 错误：类型注解不够精确
_EXTENDED_FACTOR_COLS: tuple = ('bollinger_pb', 'kdj_j', 'turnover_surge')  # 无法表达元素类型
```

**原则：**
- 使用 `tuple[str, ...]` 表达字符串元组
- Python 3.9+ 支持泛型元组
- 类型检查器可推断元素类型

### DataFrame 内存释放规范（2026-05-26 新增）

**问题背景：**
- merge 完成后，源 DataFrame 仍驻留内存
- 直到函数结束才释放，内存占用持续

**正确用法：**
```python
# ✅ 正确：merge 完成后立即释放
factor_df = factor_df.merge(turnover_df[['date', 'asset', 'turnover_rate']], ...)
del turnover_df  # merge 完成后立即释放

# ❌ 错误：turnover_df 驻留内存直到函数结束
factor_df = factor_df.merge(turnover_df[['date', 'asset', 'turnover_rate']], ...)
# turnover_df 未释放，内存持续占用
```

**适用场景：**
- merge 完成后源 DataFrame 不再需要
- 大数据量场景
- 内存敏感场景

### docstring Example 规范（2026-05-26 新增）

**问题背景：**
- Example 中的函数调用会实际执行完整流程
- 需要外部依赖（数据文件）才能运行
- doctest 会失败（缺少依赖）

**正确用法：**
```python
# ✅ 正确：标记非运行示例
Example:
    # 以下为示例用法，非实际运行（generate_all_factors 需要输入数据文件）
    >>> from data_fetchers.factor_generator import generate_all_factors
    >>> metadata = generate_all_factors()  # 需要 cache/factor_data/*.json.gz

# ❌ 错误：未标记非运行示例（doctest 会失败）
Example:
    >>> from data_fetchers.factor_generator import generate_all_factors
    >>> metadata = generate_all_factors()  # 缺少数据文件，doctest 失败
```

**原则：**
- 需要外部依赖的函数应标记非运行示例
- 补充依赖说明（需要哪些文件）
- 避免 doctest 失败

### pandas 列选择规范（2026-05-26 新增）

**问题背景：**
- pandas DataFrame 列选择使用元组有兼容性问题
- 元组可能被视为 MultiIndex 而非列名列表
- 需转换为列表才能正确选择列

**正确用法：**
```python
# ✅ 正确：元组转列表
_OUTPUT_COLS: tuple[str, ...] = ('date', 'asset', 'open', 'close')
output_df = df[list(_OUTPUT_COLS)].copy()  # 元组转列表

# ❌ 错误：直接使用元组（兼容性问题）
_OUTPUT_COLS: tuple[str, ...] = ('date', 'asset', 'open', 'close')
output_df = df[_OUTPUT_COLS].copy()  # 可能被视为 MultiIndex

# ✅ 正确：迭代不受影响（for col in tuple 正常工作）
for col in _OUTPUT_COLS:  # 元组迭代正常
    if col not in df.columns:
        ...
```

**原则：**
- DataFrame 列选择使用 `list(tuple)` 转换
- 元组迭代不受影响（for col in tuple 正常）
- 常量定义使用元组（防止修改），使用时转为列表

### 类型注解兼容性规范（2026-05-26 新增）

**问题背景：**
- 类型注解为 int，但实际可能传入 numpy.int64 或 float
- 静态类型检查器可能报警告
- Python 运行时不强制类型检查

**正确用法：**
```python
# ✅ 正确：在 Note 中补充兼容类型说明
def _calc_pct(count: int, total: int) -> float:
    """
    ...
    Note:
        - 类型注解为 int，但实际接受 int、numpy.int64、float 等兼容类型
        - Python 运行时不强制类型检查，注解仅为静态分析提供参考
    """

# ❌ 错误：未说明兼容类型（静态分析可能警告）
def _calc_pct(count: int, total: int) -> float:
    """..."""  # 未说明兼容类型
```

**原则：**
- 类型注解为 int，但可接受兼容类型
- 在 Note 中补充兼容类型说明
- Python 运行时不强制类型检查

### docstring Raises 规范（2026-05-26 新增）

**问题背景：**
- docstring Raises 描述未实现的场景
- 与实际行为不符，误导调用方

**正确用法：**
```python
# ✅ 正确：描述与实际一致
Raises:
    ValueError: 数据格式不正确（缺少 'data' 字段）、JSON 解析失败

# ❌ 错误：描述未实现的场景
Raises:
    ValueError: ...、或输入数据为空  # 代码无对应检查，不会抛出
```

**原则：**
- Raises 描述应与实际抛出一致
- 不应描述未实现的场景
- 删除不符合实际行为的描述

### 兜底块异常信息规范（2026-05-26 新增）

**问题背景：**
- 兜底块异常信息不完整
- 缺少异常类型和详情，难以追溯

**正确用法：**
```python
# ✅ 正确：包含异常类型和详情
except Exception as e:
    raise RuntimeError(f"未知错误: {path}, {type(e).__name__}: {e}") from e

# ❌ 错误：缺少异常类型和详情
except Exception as e:
    raise RuntimeError(f"未知错误: {path}") from e  # 缺少异常详情
```

**原则：**
- 兜底块应包含异常类型（`type(e).__name__`）
- 包含异常详情（`str(e)`）
- 便于追溯问题根源

### paths.py 使用规范

### 强制规则

```
❌ 目录下有 common/ 公共模块，脚本仍手写相同逻辑
❌ 公共模块已封装缓存读写，脚本自行实现 gzip 解压 + JSON 加载
❌ 公共模块已封装 API 调用，脚本自行实现 requests 请求
```

### 正确做法

```
✅ 开发前先检查 common/ 是否有可复用函数
✅ 公共模块已封装的逻辑，直接调用，不重复实现
✅ 仅实现数据源特有的逻辑（API 参数、数据转换）
```

---

## 输出目录规范

### 缓存输出

**所有数据拉取结果输出到 cache 目录，不输出到脚本同级目录。**

| 数据类型 | 输出目录 | 文件格式 |
|----------|---------|----------|
| 因子数据 | `cache/factor_data/` | `factor_data_extended.json.gz` |
| 换手率数据 | `cache/` | `turnover_rate_data.json.gz` |
| 主力资金流 | `cache/` | `main_inflow_data.json.gz` |

**禁止：**
```
❌ 输出到脚本同级目录（散乱，难管理）
❌ 输出到 data_fetchers/result/（临时元信息才用）
```

### result 目录用途

`data_fetchers/result/` 用于存储：
- 数据拉取元信息（拉取时间、数据范围、行数）
- 数据质量报告（缺失字段统计、异常值检测）

### logs 目录用途

`data_fetchers/logs/` 用于存储：
- 数据拉取日志（API 调用记录、错误日志）
- 因子生成日志（计算进度、耗时统计）

**禁止：**
```
❌ 日志输出到项目根目录的 logs/（应输出到模块级 logs/）
❌ 日志文件与脚本同级（散乱，难管理）
```

---

## 统一因子生成模块

### factor_generator.py

**职责：** 生成所有因子数据到缓存，提供单一数据源。

**位置：** `data_fetchers/factor_generator.py`

**输出：** `cache/factor_data/factor_data_extended.json.gz`

### 支持的因子

| 因子 | 列名 | 参数 | 数据依赖 |
|------|------|------|---------|
| RSI | rsi_6 | period=6 | close |
| Volume_Ratio | volume_ratio_5 | window=5 | volume |
| Bollinger_PB | bollinger_pb | n=20, k=2.0 | close |
| KDJ_J | kdj_j | n=9, m1=3, m2=3 | close, high, low |
| Turnover_Surge | turnover_surge | window=5 | turnover_rate, close |

### 输出结构

```json
{
  "dates": ["2024-04-19", "2024-04-20", ...],
  "data": [
    {
      "date": "2024-04-19",
      "asset": "000001",
      "open": 10.71,
      "close": 10.69,
      "high": 10.82,
      "low": 10.66,
      "rsi_6": 64.42,
      "volume_ratio_5": 0.74,
      "bollinger_pb": null,
      "kdj_j": null,
      "turnover_surge": null
    },
    ...
  ]
}
```

### 使用方式

**CLI：**
```bash
python data_fetchers/factor_generator.py
```

**Python：**
```python
import logging
from data_fetchers.factor_generator import generate_all_factors, get_module_logger

# 使用模块默认 logger
metadata = generate_all_factors()

# 使用自定义 logger
logger = logging.getLogger('my_app')
metadata = generate_all_factors(logger=logger)
```

### 数据一致性验证

factor_generator.py 的因子计算逻辑从 IC 脚本迁移：
- `calculate_bollinger_pb()` ← `ic_bollinger_pb_1d.py`
- `calculate_kdj_j()` ← `ic_kdj_j_1d.py`
- `calculate_turnover_surge()` ← `ic_turnover_surge_1d.py`

**验证结果（2026-05-24）：**
- 均值差异 < 0.000001
- 有效数据数一致
- 因子计算逻辑完全一致

---

## 缓存格式

### factor_data.json.gz（基础因子）

**结构：**
```json
{
  "dates": ["2024-04-19", ...],
  "data": [
    {
      "date": "2024-04-19",
      "asset": "000001",
      "open": 10.71,
      "close": 10.69,
      "high": 10.82,
      "low": 10.66,
      "rsi_6": 64.42,
      "volume_ratio_5": 0.74
    },
    ...
  ]
}
```

### factor_data_extended.json.gz（扩展因子）

包含所有 5 个因子（见上方输出结构）。

### turnover_rate_data.json.gz

**结构：**
```json
{
  "data": [
    {
      "date": "2024-03-19",
      "asset": "000001",
      "turnover_rate": 0.6664
    },
    ...
  ]
}
```

---

## 因子计算参数规范

### 参数默认值

| 因子 | 参数 | 默认值 | 说明 |
|------|------|--------|------|
| RSI | period | 6 | RSI 计算周期 |
| Volume_Ratio | window | 5 | 成交量均值窗口 |
| Bollinger_PB | n | 20 | 移动平均周期 |
| Bollinger_PB | k | 2.0 | 标差倍数 |
| KDJ_J | n | 9 | RSV 计算周期 |
| KDJ_J | m1 | 3 | K 值平滑周期 |
| KDJ_J | m2 | 3 | D 值平滑周期 |
| Turnover_Surge | window | 5 | 换手率均值窗口 |

### 计算规范

**遵循 PROJECT.md 规范：**
- 函数入口必须 `.copy()` 避免副作用
- 使用 `transform` 方法避免 pandas 3.0 索引问题
- 异常检测而非静默修正
- 使用 EPSILON 避免除零

---

## pandas 3.0 兼容性规范（2026-05-24 新增）

**问题：**
```python
# ❌ 错误：pandas 3.0 返回 MultiIndex Series
middle = factor_df.groupby('asset', group_keys=False)['close'].rolling(window=n).mean()
factor_df['middle'] = middle  # TypeError: incompatible index
```

**解决方案：**
```python
# ✓ 正确：使用 transform 返回 RangeIndex Series
middle = factor_df.groupby('asset', group_keys=False)['close'].transform(
    lambda x: x.rolling(window=n).mean()
)
factor_df['middle'] = middle  # 成功赋值
```

**原因：**
- pandas 3.0 中，`groupby(group_keys=False).rolling()` 返回 MultiIndex Series
- 即使 `group_keys=False`，索引仍是 MultiIndex
- `transform` 返回与原 DataFrame 一致的 RangeIndex

---

## 模块边界规范

**遵循 PROJECT.md 模块边界规范：**

```
✓ factor_generator.py 独立运行（不依赖 factor_ic、backtest）
✓ 输出到 cache/factor_data/
✓ 被 factor_ic 模块读取
```

**禁止：**
```
❌ factor_generator.py 导入 factor_ic.common.*
❌ factor_generator.py 导入 backtest.common.*
```

---

## 流程文档配套规范

**遵循 PROJECT.md"脚本配套文件规范"章节：**

| 文件类型 | 位置 | 命名规则 | 示例 |
|---------|------|---------|------|
| 流程文档 | `data_fetchers/docs/` | `<脚本名>_flow.md` | `factor_generator_flow.md` |
| 测试用例 | `data_fetchers/test_cases/` | `<脚本名>_test_cases.md` | `factor_generator_test_cases.md` |

**新建脚本时：**
```
□ 创建脚本文件（如 fetch_xxx.py）
□ 同步创建流程文档（docs/fetch_xxx_flow.md）
□ 同步创建测试用例（test_cases/fetch_xxx_test_cases.md）
```

---

## 待补充内容

```
□ 各脚本流程文档（docs/fetch_xxx_flow.md）
□ 各脚本测试用例（test_cases/fetch_xxx_test_cases.md）
□ 日期处理模块（common/date_utils.py，交易日判断、日期范围计算）
□ 数据验证模块（common/data_validator.py，字段完整性检查）
□ 增量更新策略规范
□ 数据质量检查自动化
□ 因子计算性能优化（大数据量测试）

✓ 公共模块实现（paths.py、cache_manager.py、http_client.py、stock_utils.py）- 已完成 2026-05-24
```

---

*最后更新: 2026-05-25 10:30 北京时间*
---

## factor_calculator.py 版本历史

| 版本 | 时间 | 更新内容 |
|-----|------|---------|
| v1.0 | 2026-05-27 17:00 | 初始创建：导入规范化、logger参数化（约束77）、类型注解精确化（约束76）、__all__修复（约束60）、docstring补全（Example章节） |
| v1.0 | 2026-05-27 17:00 | 配套文件：docs/factor_calculator_flow.md、test_cases/test_factor_calculator.py |
| v1.1 | 2026-05-27 19:30 | 第二轮深度优化：版本历史添加、常量命名私有化（DEFAULT_* → _DEFAULT_*）、__all__移到导入后位置 |
| v1.2 | 2026-05-27 20:00 | 第三轮深度优化：内部函数`_calculate_ewm_with_initial` docstring补全、新增私有常量（volume_ratio_window、forward_return_shift）、消除硬编码默认值 |

---

*最后更新: 2026-05-27 17:00 北京时间*
