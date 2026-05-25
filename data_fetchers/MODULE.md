# data_fetchers 模块规范

> 版本: v2.47
> 创建时间: 2026-05-19
> 更新时间: 2026-05-25 16:00 北京时间
> 重构时间: 2026-05-24（补充目录结构+命名规则+公共模块规范+公共模块实现）

---

## 快速参考

### 必须遵守的约束

**遵循 PROJECT.md"输出数据规范"章节的跨模块通用原则：**
- 输出结构必须统一
- 字段值不可为 None
- 结果输出到 result 目录

**本模块特定约束（8条）：**

| # | 约束 | 说明 |
|---|------|------|
| 1 | 脚本命名：`fetch_<数据源>.py` | 如 fetch_turnover.py、fetch_main_inflow.py |
| 2 | 输出到 cache 目录 | 不输出到脚本同级目录 |
| 3 | 因子生成使用 factor_generator.py | 单一数据源，不分散 |
| 4 | 公共模块必须复用 | 禁止脚本自行实现已有功能 |
| 5 | pandas 3.0 使用 transform | 避免 rolling 返回 MultiIndex |
| 6 | 函数入口 DataFrame 先 copy() | 防止副作用 |
| 7 | 日志输出到 logs 目录 | 不散落在项目根目录 |
| 8 | 流程文档配套 | docs/<脚本名>_flow.md |

### 关键函数签名

| 函数 | 文件 | 用途 |
|------|------|------|
|| `generate_all_factors(logger)` | factor_generator.py | 生成所有因子数据 |
| `fetch_ohlcv_data(start_date, end_date)` | fetch_ohlcv.py（待创建） | 拉取 OHLCV 数据 |
| `fetch_turnover_data()` | fetch_turnover.py | 拉取换手率数据 |
| `fetch_main_inflow_data()` | fetch_main_inflow.py | 拉取主力资金流数据 |

---

## 目录结构

```
data_fetchers/
├── MODULE.md           # 本文件（模块规范）
├── common/             # 公共函数
│   ├── __init__.py
│   └── data_source_base.py  # 数据源基类（待创建）
│
├── docs/               # 流程文档
│   ├── factor_generator_flow.md
│   └── fetch_<数据源>_flow.md
│
├── result/             # 数据拉取结果输出（元信息）
│   └── .gitkeep
│
├── logs/               # 日志目录
│   └── .gitkeep
│
├── test_cases/         # 测试用例
│   ├── __init__.py
│   └── <脚本名>_test_cases.md
│
├── factor_generator.py # 统一因子生成入口
├── fetch_turnover.py   # 换手率数据拉取
├── fetch_main_inflow.py # 主力资金流数据拉取
├── fetch_stock_list.py # 股票列表拉取
├── fetch_float_mv.py   # 流通市值拉取
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
| fetch_main_inflow.py | 主力资金流 | 拉取主力流入流出数据 |
| fetch_stock_list.py | 股票列表 | 拉取 A 股股票列表 |
| fetch_float_mv.py | 流通市值 | 拉取流通市值数据 |
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