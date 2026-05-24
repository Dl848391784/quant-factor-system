# data_fetchers/common 公共模块

> 版本: v1.0
> 创建时间: 2026-05-24
> 作者: 云瑶

公共模块为 `data_fetchers/` 目录下的数据拉取脚本提供统一的基础功能。

---

## 模块清单

| 模块 | 功能 | 核心函数 |
|------|------|----------|
| `paths.py` | 路径管理 | `get_cache_dir()`, `get_factor_data_dir()`, `get_stock_list_file()` |
| `cache_manager.py` | 缓存读写 | `read_gzip_cache()`, `write_gzip_cache()`, `append_to_cache()` |
| `http_client.py` | HTTP 客户端 | `create_retry_session()`, `create_eastmoney_session()`, `request_with_retry()` |
| `stock_utils.py` | 股票筛选 | `is_main_board_stock()`, `load_main_board_stock_list()` |

---

## 使用方式

### 1. 导入模块

```python
from data_fetchers.common import paths, cache_manager, http_client, stock_utils
```

或导入具体函数：

```python
from data_fetchers.common import (
    get_cache_dir,
    read_gzip_cache,
    create_eastmoney_session,
    load_main_board_stock_list,
)
```

### 2. 路径管理

```python
from data_fetchers.common import paths

# 获取缓存目录
cache_dir = paths.get_cache_dir()

# 获取因子数据目录
factor_data_dir = paths.get_factor_data_dir()

# 获取股票列表文件
stock_list_file = paths.get_stock_list_file()
```

### 3. 缓存读写

```python
from data_fetchers.common import read_gzip_cache, write_gzip_cache

# 读取 gzip 缓存
data = read_gzip_cache(factor_data_dir / 'factor_data.json.gz')

# 写入 gzip 缓存
write_gzip_cache(factor_data_dir / 'output.json.gz', {'data': [...]})
```

### 4. HTTP 客户端

```python
from data_fetchers.common import create_eastmoney_session, request_with_retry

# 创建东财 API Session
session = create_eastmoney_session()

# 带重试的请求
data = request_with_retry(session, url='https://...', params={...})
```

### 5. 股票筛选

```python
from data_fetchers.common import load_main_board_stock_list, is_main_board_stock

# 加载主板股票列表
stocks = load_main_board_stock_list(verbose=True)

# 判断是否主板股票
if is_main_board_stock('600000', '浦发银行'):
    print("主板股票")
```

---

## 设计原则

### 强制复用

**目录下有公共模块就必须使用公共模块，绝对禁止脚本自行实现！**

```
✓ 使用 paths.get_cache_dir() 获取缓存目录
✓ 使用 read_gzip_cache() 读取缓存
✓ 使用 create_retry_session() 创建 HTTP Session
✓ 使用 load_main_board_stock_list() 加载股票列表

❌ 硬编码绝对路径 '/home/admin/projects/...'
❌ 手写 gzip.open + json.load
❌ 手写 Retry + HTTPAdapter 配置
❌ 手写股票筛选逻辑
```

### 模块边界

**公共模块仅在本目录内复用，禁止跨目录调用。**

```
✓ data_fetchers/fetch_turnover.py 调用 data_fetchers/common/stock_utils.py

❌ factor_ic/ic_rsi_1d.py 调用 data_fetchers/common/stock_utils.py（禁止）
```

---

## 常量定义

### 路径常量

```python
# 主板股票代码前缀
MAIN_BOARD_PREFIXES = ('60', '00')

# 剔除的代码前缀
EXCLUDED_PREFIXES = ('30', '688', '8', '4')

# 剔除的名称关键词
EXCLUDED_NAME_KEYWORDS = ('ST', '*ST', '退市')
```

### HTTP 常量

```python
# 东财 API 默认请求头
DEFAULT_EASTMONEY_HEADERS = {
    "User-Agent": "Mozilla/5.0 ...",
    "Referer": "https://quote.eastmoney.com/",
    ...
}

# 新浪 API 默认请求头
DEFAULT_SINA_HEADERS = {
    "User-Agent": "Mozilla/5.0 ...",
    "Referer": "http://vip.stock.finance.sina.com.cn/",
    ...
}
```

---

## 待扩展

```
□ 日期处理模块（交易日判断、日期范围计算）
□ 数据验证模块（字段完整性检查、异常值检测）
□ 进度显示模块（进度条、批量处理统计）
```

---

*最后更新: 2026-05-24*