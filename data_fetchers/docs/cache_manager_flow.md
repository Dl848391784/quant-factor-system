# cache_manager.py 流程文档

> 版本: v1.11
> 创建时间: 2026-05-24 21:05 北京时间
> 最后更新: 2026-05-24 23:20 北京时间
> 脚本位置: data_fetchers/common/cache_manager.py

---

## 版本历史

| 版本 | 日期 | 变更内容 |
|------|------|---------|
| v1.0 | 2026-05-24 21:05 | 初始版本，流程文档创建 |
| v1.1 | 2026-05-24 21:10 | 第二轮优化：函数命名修复 + logger 使用 |
| v1.2 | 2026-05-24 21:40 | 第三轮优化：消除代码重复 + 文件类型判断优化 |
| v1.3 | 2026-05-24 21:45 | 第四轮优化：类型注解 + 防御性编程 + __all__ 导出 |
| v1.4 | 2026-05-24 21:50 | 第五轮优化：统一缓存 API + 大文件监控 + 辅助函数 |
| v1.5 | 2026-05-24 21:55 | 第六轮优化：gzip 压缩级别 + JSON 格式选项 + 数据类型验证 |
| v1.6 | 2026-05-24 22:20 | 第七轮优化：异常处理精确化 + 空文件处理 + __init__.py 导出修复 |
| v1.7 | 2026-05-24 22:40 | 第八轮优化：测试代码日志规范化（print → logger + setup_test_logger） |
| v1.8 | 2026-05-24 22:50 | 第九轮优化：创建 logger_config.py，复用 setup_logger（DRY 原则） |
| v1.9 | 2026-05-24 23:00 | 第十轮优化：测试用例版本同步 + 时间标注修复 + TC025 新增 |
| v1.10 | 2026-05-24 23:10 | 第十轮发现 bug：get_module_logger 缺少 global 声明，修复 UnboundLocalError |
| v1.11 | 2026-05-24 23:20 | 第十一轮优化：删除冗余 datetime 导入 + 测试用例版本同步 |

---

## 模块概述

cache_manager.py 是 data_fetchers 模块的公共缓存管理模块，提供统一的 gzip + JSON 缓存读写操作。

**核心功能：**
- 读取 gzip 压缩的 JSON 缓存
- 写入 gzip 压缩的 JSON 缓存
- 读取普通 JSON 缓存
- 写入普通 JSON 缓存
- 增量追加数据到缓存
- 获取缓存文件信息

**第三轮优化新增公共函数：**
- `_is_gzip_file`：判断是否为 gzip 文件
- `_read_cache_impl`：读取缓存的公共实现
- `_write_cache_impl`：写入缓存的公共实现

---

## 架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                      cache_manager.py                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐         │
│  │  gzip 操作  │    │  json 操作  │    │   辅助函数   │         │
│  ├─────────────┤    ├─────────────┤    ├─────────────┤         │
│  │read_gzip    │    │read_json    │    │get_module   │         │
│  │write_gzip   │    │write_json   │    │_logger      │         │
│  │             │    │             │    │             │         │
│  └─────────────┘    └─────────────┘    │_is_gzip_file│         │
│         │                  │           │             │         │
│         │                  │           │_read_cache  │         │
│         │                  │           │_impl        │         │
│         │                  │           │             │         │
│         │                  │           │_write_cache │         │
│         │                  │           │_impl        │         │
│         │                  │           └─────────────┘         │
│         │                  │                  │                │
│         ▼                  ▼                  ▼                │
│  ┌─────────────────────────────────────────────────┐           │
│  │              append_to_cache                     │           │
│  │  (读取现有 + 合并新数据 + 写入)                    │           │
│  └─────────────────────────────────────────────────┘           │
│                                                                 │
│  ┌─────────────────────────────────────────────────┐           │
│  │              get_cache_file_info                 │           │
│  │  (获取文件存在状态、大小、修改时间)                 │           │
│  └─────────────────────────────────────────────────┘           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 核心函数流程

### read_gzip_cache / read_json_cache

```
┌──────────────┐
│   入口调用    │
│  path, logger│
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ path=Path(p) │  统一类型转换
│ logger=get   │  获取 logger
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ 检查文件存在  │
│ path.exists()│
└──────┬───────┘
       │
       ├──── 不存在 ────▶ raise FileNotFoundError
       │
       ▼ 存在
┌──────────────┐
│ gzip/json    │  解压/读取
│   .open()    │
│   .load()    │
└──────┬───────┘
       │
       ├──── JSONDecodeError ──▶ ValueError 包装 (from e)
       │
       ▼ 成功
┌──────────────┐
│ logger.debug │  记录成功日志
│ return data  │  返回数据
└──────────────┘
```

### write_gzip_cache / write_json_cache

```
┌──────────────┐
│   入口调用    │
│path,data,log │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ path=Path(p) │  统一类型转换
│ logger=get   │  获取 logger
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ ensure_dir?  │  创建目录
│ mkdir(p,e)   │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ gzip/json    │  压缩/写入
│   .open()    │
│   .dump()    │
└──────┬───────┘
       │
       ▼ 成功
┌──────────────┐
│ logger.debug │  记录成功日志
│ return None  │
└──────────────┘
```

### append_to_cache

```
┌──────────────┐
│   入口调用    │
│path,new_data │
│key,logger    │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ path=Path(p) │  统一类型转换
│ logger=get   │  获取 logger
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ 检查文件存在  │
│ path.exists()│
└──────┬───────┘
       │
       ├──── 存在 ────▶ read_gzip/read_json (传入 logger)
       │                existing_data = existing.get(key, [])
       │
       ▼ 不存在
┌──────────────┐
│existing_data │  初始化空列表
│   = []       │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ merged_data  │  合并数据
│ = existing   │  + new_data
│ + new_data   │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ 构建结果结构  │
│ result = {   │
│   key: merged│
│ }            │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ 保留其他字段  │  dates 等
│ for k,v in   │  existing
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ write_gzip   │  写入缓存
│ /write_json  │  (传入 logger)
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ logger.info  │  记录追加日志
│ return count │  返回总数
└──────────────┘
```

---

## 函数详细说明

### get_module_logger(logger=None)

**职责：** 获取 logger，遵循 PROJECT.md 公共模块日志规范。

**参数：**
| 参数 | 类型 | 说明 |
|------|------|------|
| logger | Optional[Logger] | 调用方传入的 logger |

**返回：** Logger 对象

**规范依据：** PROJECT.md 第783-857行

---

### read_gzip_cache(path, logger=None)

**职责：** 读取 gzip 压缩的 JSON 缓存。

**参数：**
| 参数 | 类型 | 说明 |
|------|------|------|
| path | Union[Path, str] | 缓存文件路径 (.json.gz) |
| logger | Optional[Logger] | 调用方传入的 logger |

**返回：** Dict[str, Any] - JSON 数据

**异常：**
| 异常 | 说明 |
|------|------|
| FileNotFoundError | 文件不存在 |
| ValueError | JSON 解析失败（避免内存翻倍） |

---

### write_gzip_cache(path, data, ensure_dir=True, logger=None)

**职责：** 写入 gzip 压缩的 JSON 缓存。

**参数：**
| 参数 | 类型 | 说明 |
|------|------|------|
| path | Union[Path, str] | 缓存文件路径 |
| data | Dict[str, Any] | 要写入的数据 |
| ensure_dir | bool | 是否自动创建目录 |
| logger | Optional[Logger] | 调用方传入的 logger |

**异常：** OSError - 文件写入失败

---

### append_to_cache(path, new_data, key='data', logger=None)

**职责：** 增量追加数据到缓存。

**参数：**
| 参数 | 类型 | 说明 |
|------|------|------|
| path | Union[Path, str] | 缓存文件路径 |
| new_data | list | 要追加的数据列表 |
| key | str | 数据存储的 key |
| logger | Optional[Logger] | 调用方传入的 logger |

**返回：** int - 追加后的总数据量

---

### get_cache_file_info(path, logger=None)

**职责：** 获取缓存文件信息。

**参数：**
| 参数 | 类型 | 说明 |
|------|------|------|
| path | Union[Path, str] | 缓存文件路径 |
| logger | Optional[Logger] | 调用方传入的 logger |

**返回：** Dict - 文件信息
```json
{
  "path": "str",
  "exists": bool,
  "size_mb": float,
  "modified_time": float
}
```

---

## 使用示例

### 基本读写

```python
from data_fetchers.common import read_gzip_cache, write_gzip_cache
import logging

# 配置日志
logger = logging.getLogger('my_script')

# 写入缓存
data = {'dates': ['2024-01-01'], 'data': [1, 2, 3]}
write_gzip_cache('/path/to/cache.json.gz', data, logger=logger)

# 读取缓存
loaded = read_gzip_cache('/path/to/cache.json.gz', logger=logger)
```

### 增量追加

```python
from data_fetchers.common import append_to_cache

# 追加新数据
new_data = [{'date': '2024-01-02', 'value': 100}]
total = append_to_cache('/path/to/cache.json.gz', new_data, logger=logger)
print(f"追加后总计 {total} 条")
```

### 获取文件信息

```python
from data_fetchers.common import get_cache_file_info

info = get_cache_file_info('/path/to/cache.json.gz', logger=logger)
if info['exists']:
    print(f"文件大小: {info['size_mb']:.2f} MB")
else:
    print("文件不存在")
```

---

## 错误处理

### FileNotFoundError

```python
try:
    data = read_gzip_cache('/path/to/not_exist.json.gz')
except FileNotFoundError as e:
    logger.error("缓存文件不存在: %s", e)
    # 执行全量计算或创建默认数据
```

### ValueError（JSON 解析失败）

```python
try:
    data = read_gzip_cache('/path/to/corrupt.json.gz')
except ValueError as e:
    logger.error("JSON 解析失败: %s", e)
    # 重新生成缓存或使用备份
```

---

## 版本历史

| 版本 | 日期 | 更新内容 |
|------|------|---------|
| v1.0 | 2026-05-24 | 创建流程文档 |
| v1.1 | 2026-05-24 | 修复 `_get_logger` → `get_module_logger`，添加 get_cache_file_info 日志 |
| v1.8 | 2026-05-24 | 第九轮优化：创建 logger_config.py，复用 setup_logger（DRY 原则） |
| v1.9 | 2026-05-24 | 第十轮优化：测试用例版本同步 + 时间标注修复 + TC025 新增 |
| v1.10 | 2026-05-24 | 第十轮发现 bug：get_module_logger 缺少 global 声明，修复 UnboundLocalError |
| v1.11 | 2026-05-24 | 第十一轮优化：删除冗余 datetime 导入 + 测试用例版本同步 |

---

*最后更新: 2026-05-24 23:20 北京时间*