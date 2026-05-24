# data_fetchers 模块规范

> 版本: v2.25
> 创建时间: 2026-05-19
> 更新时间: 2026-05-25
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
| `generate_all_factors(verbose)` | factor_generator.py | 生成所有因子数据 |
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

---

## 概述

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

**JSON 解析异常处理：**
- 抛出 `ValueError` 而非 `json.JSONDecodeError`
- 避免传递完整 JSON 文档导致内存翻倍
- 参考 `references/backtest-module-optimization-patterns.md Section 1.2`

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
from data_fetchers.factor_generator import generate_all_factors

metadata = generate_all_factors(
    verbose=True  # 打印进度
)
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

*最后更新: 2026-05-25 03:00*