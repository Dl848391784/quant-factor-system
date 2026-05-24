# cache_manager.py 优化计划

> 创建时间: 2026-05-24 20:30 北京时间
> 版本: v1.0

---

## 诊断结论

**问题类型：混合问题（规范遗漏 + 代码改进）**

| 问题 | 类型 | 规范依据 |
|------|------|---------|
| 公共模块独立创建 logger | 规范遗漏 | PROJECT.md 第783-857行：公共模块接收 logger 参数 |
| JSONDecodeError 内存翻倍 | 规范遗漏 | references/backtest-module-optimization-patterns.md Section 1.2 |
| path 参数不支持 str | 代码改进 | PROJECT.md 参数类型约定规范 |
| 测试入口引用不存在模块 | 代码改进 | __main__ 测试代码 |

---

## 优化目标

遵循 PROJECT.md 日志规范，将 cache_manager.py 从独立创建 logger 改为接收 logger 参数，同时优化异常处理和参数类型。

---

## 分步执行计划（Bite-sized Tasks）

### Step 1: 添加 logger 参数支持

**任务：** 为所有公共函数添加 logger 参数，遵循 PROJECT.md 第783-857行规范。

**修改内容：**
```python
# 当前代码（第17行）
logger = logging.getLogger(__name__)

# 改为模块级 fallback
_logger = None

def get_logger(logger=None):
    """获取 logger，遵循 PROJECT.md 公共模块日志规范"""
    if logger is not None:
        return logger
    if _logger is None:
        _logger = logging.getLogger('data_fetchers.common.cache_manager')
    return _logger
```

**函数签名修改：**
```python
# read_gzip_cache
def read_gzip_cache(path: Path | str, logger: logging.Logger = None) -> Dict[str, Any]:
    logger = get_logger(logger)
    ...

# write_gzip_cache
def write_gzip_cache(path: Path | str, data: Dict[str, Any], ensure_dir: bool = True, logger: logging.Logger = None) -> None:
    logger = get_logger(logger)
    ...

# read_json_cache
def read_json_cache(path: Path | str, logger: logging.Logger = None) -> Dict[str, Any]:
    logger = get_logger(logger)
    ...

# write_json_cache
def write_json_cache(path: Path | str, data: Dict[str, Any], ensure_dir: bool = True, logger: logging.Logger = None) -> None:
    logger = get_logger(logger)
    ...

# append_to_cache
def append_to_cache(path: Path | str, new_data: list, key: str = 'data', logger: logging.Logger = None) -> int:
    logger = get_logger(logger)
    ...

# get_cache_file_info
def get_cache_file_info(path: Path | str, logger: logging.Logger = None) -> Dict[str, Any]:
    logger = get_logger(logger)
    ...
```

**规范依据：** PROJECT.md 第783-857行 + references/session-2026-05-22-logger-migration-lessons.md

---

### Step 2: 修复 JSONDecodeError 内存翻倍问题

**任务：** 按照 references/backtest-module-optimization-patterns.md Section 1.2，避免传递完整 JSON 文档字符串。

**修改内容：**
```python
# 当前代码（第42-44行）
except json.JSONDecodeError as e:
    logger.error(f"JSON 解析失败: {path}, 错误: {e}")
    raise

# 改为
except json.JSONDecodeError as e:
    logger.error(
        "JSON 解析失败\n"
        "文件路径: %s\n"
        "错误位置: 行 %d, 列 %d\n"
        "错误信息: %s",
        path, e.lineno, e.colno, e.msg
    )
    raise ValueError(f"JSON解析失败: {path}, 位置 {e.pos}") from e
```

**为何修改：**
- `json.JSONDecodeError` 对象持有完整 JSON 文档副本（e.doc）
- 传递 e.doc 会导致内存翻倍
- 使用 `raise ValueError(...) from e` 保留异常链但避免内存问题

**规范依据：** references/backtest-module-optimization-patterns.md Section 1.2

---

### Step 3: 支持 Path | str 参数类型

**任务：** 为所有函数的 path 参数支持 Path | str 类型，内部统一转换为 Path。

**修改内容：**
```python
# 在每个函数开头添加转换
def read_gzip_cache(path: Path | str, logger: logging.Logger = None) -> Dict[str, Any]:
    """读取 gzip 压缩的 JSON 缓存"""
    path = Path(path)  # 统一转换为 Path
    logger = get_logger(logger)
    
    if not path.exists():
        raise FileNotFoundError(f"缓存文件不存在: {path}")
    ...
```

**适用函数：**
- read_gzip_cache
- write_gzip_cache
- read_json_cache
- write_json_cache
- append_to_cache
- get_cache_file_info

---

### Step 4: 修复测试入口代码

**任务：** 修复 __main__ 测试代码中引用不存在模块的问题。

**修改内容：**
```python
# 当前代码（第200-218行）
if __name__ == '__main__':
    from paths import get_factor_data_dir  # 不存在
    
    test_path = get_factor_data_dir() / 'test_cache.json.gz'
    ...

# 改为
if __name__ == '__main__':
    # 测试路径直接定义
    test_dir = Path(__file__).parent.parent.parent / 'cache' / 'test'
    test_dir.mkdir(parents=True, exist_ok=True)
    test_path = test_dir / 'test_cache.json.gz'
    
    # 配置测试日志
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s'
    )
    test_logger = logging.getLogger('test')
    
    test_data = {'test': [1, 2, 3], 'dates': ['2024-01-01']}
    
    print("写入测试缓存...")
    write_gzip_cache(test_path, test_data, logger=test_logger)
    
    print("读取测试缓存...")
    loaded = read_gzip_cache(test_path, logger=test_logger)
    print(f"读取结果: {loaded}")
    
    print("获取缓存信息...")
    info = get_cache_file_info(test_path, logger=test_logger)
    print(f"文件信息: {info}")
    
    # 清理测试文件
    test_path.unlink()
    print("测试完成，已清理测试文件")
```

---

### Step 5: 同步更新 MODULE.md 规范

**任务：** 在 MODULE.md 补充 cache_manager.py 的 logger 参数使用规范。

**修改内容：**
```markdown
## 公共模块使用规范（补充）

### cache_manager.py 日志参数规范

**遵循 PROJECT.md 第783-857行规范，公共模块接收 logger 参数。**

**使用方式：**
```python
from data_fetchers.common.cache_manager import read_gzip_cache
from factor_ic.common.logger_config import get_logger

# 调用方传入 logger（推荐）
logger = get_logger('factor_ic.ic_rsi_1d')
data = read_gzip_cache(cache_file, logger=logger)

# 不传 logger 时使用默认 logger（fallback）
data = read_gzip_cache(cache_file)  # 自动创建模块级 logger
```

**禁止：**
```python
# ❌ 公共模块独立创建 logger（旧方式，已废弃）
# logger = logging.getLogger(__name__)  # 无法追溯调用方
```

**参数类型：**
- `path`: 支持 `Path | str`，内部统一转换为 Path
- `logger`: 可选，传入调用方的 logger 以追溯调用方
```

---

## 执行顺序

```
Step 1 → 验证语法 → Step 2 → 验证语法 → Step 3 → 验证语法 → Step 4 → 运行测试 → Step 5 → Git commit
```

---

## 验证检查清单

```
□ Step 1 完成后：python -c "from data_fetchers.common.cache_manager import read_gzip_cache" 验证导入
□ Step 2 完成后：检查异常处理路径，确保 from e 保留异常链
□ Step 3 完成后：验证 Path | str 类型注解正确
□ Step 4 完成后：运行 __main__ 测试验证功能
□ Step 5 完成后：更新 MODULE.md 版本历史
□ Git commit：提交修改，不 push
```

---

*最后更新: 2026-05-24 20:30 北京时间*