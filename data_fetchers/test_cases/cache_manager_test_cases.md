# cache_manager.py 测试用例

> 版本: v1.0
> 创建时间: 2026-05-24 21:10 北京时间
> 脚本位置: data_fetchers/common/cache_manager.py

---

## 测试概述

本测试用例覆盖 cache_manager.py 的核心功能、边界条件和异常处理。

---

## 功能测试

### TC001: gzip 缓存读写

**测试目标：** 验证 gzip 压缩缓存的读写一致性。

**测试步骤：**
1. 创建测试数据
2. 使用 write_gzip_cache 写入
3. 使用 read_gzip_cache 读取
4. 比较写入和读取的数据

**预期结果：**
- 写入成功，返回 None
- 读取成功，返回原始数据
- 数据一致

**测试代码：**
```python
from data_fetchers.common import read_gzip_cache, write_gzip_cache
from pathlib import Path
import tempfile

with tempfile.TemporaryDirectory() as tmpdir:
    test_path = Path(tmpdir) / 'test.json.gz'
    test_data = {'test': [1, 2, 3], 'dates': ['2024-01-01']}
    
    # 写入
    write_gzip_cache(test_path, test_data)
    
    # 读取
    loaded = read_gzip_cache(test_path)
    
    # 验证
    assert loaded == test_data
    assert test_path.exists()
```

---

### TC002: json 缓存读写

**测试目标：** 验证普通 JSON 缓存的读写一致性。

**测试步骤：**
1. 创建测试数据
2. 使用 write_json_cache 写入
3. 使用 read_json_cache 读取
4. 比较写入和读取的数据

**预期结果：**
- 数据一致
- 文件格式为 .json（非压缩）

---

### TC003: 增量追加数据

**测试目标：** 验证 append_to_cache 增量追加功能。

**测试步骤：**
1. 创建初始缓存
2. 追加新数据
3. 读取验证

**预期结果：**
- 追加后总数据量正确
- 原有数据保留
- 新数据追加成功
- 其他字段（如 dates）保留

**测试代码：**
```python
from data_fetchers.common import append_to_cache, read_gzip_cache
from pathlib import Path
import tempfile

with tempfile.TemporaryDirectory() as tmpdir:
    test_path = Path(tmpdir) / 'test.json.gz'
    
    # 第一次追加（文件不存在）
    total1 = append_to_cache(test_path, [{'date': '2024-01-01', 'value': 100}])
    assert total1 == 1
    
    # 第二次追加（文件已存在）
    total2 = append_to_cache(test_path, [{'date': '2024-01-02', 'value': 200}])
    assert total2 == 2
    
    # 验证数据
    loaded = read_gzip_cache(test_path)
    assert len(loaded['data']) == 2
```

---

### TC004: 获取缓存文件信息

**测试目标：** 验证 get_cache_file_info 返回正确的文件信息。

**测试步骤：**
1. 创建缓存文件
2. 获取文件信息
3. 验证信息正确

**预期结果：**
- exists = True
- size_mb > 0
- modified_time 有效

---

## 边界测试

### TC005: 文件不存在

**测试目标：** 验证读取不存在文件时的异常处理。

**测试步骤：**
1. 射向不存在的文件路径
2. 调用 read_gzip_cache

**预期结果：**
- 抛出 FileNotFoundError
- 错误信息包含文件路径

**测试代码：**
```python
from data_fetchers.common import read_gzip_cache
from pathlib import Path

try:
    read_gzip_cache('/path/to/not_exist.json.gz')
except FileNotFoundError as e:
    assert '缓存文件不存在' in str(e)
```

---

### TC006: JSON 格式错误

**测试目标：** 验证 JSON 解析失败时的异常处理。

**测试步骤：**
1. 创建包含非法 JSON 的文件
2. 调用 read_gzip_cache

**预期结果：**
- 抛出 ValueError（而非 JSONDecodeError）
- 异常链保留（from e）

**测试代码：**
```python
from data_fetchers.common import read_gzip_cache
from pathlib import Path
import gzip
import tempfile

with tempfile.TemporaryDirectory() as tmpdir:
    test_path = Path(tmpdir) / 'corrupt.json.gz'
    
    # 写入非法 JSON
    with gzip.open(test_path, 'wt') as f:
        f.write('{"invalid": }')  # 非法 JSON
    
    try:
        read_gzip_cache(test_path)
    except ValueError as e:
        assert 'JSON解析失败' in str(e)
```

---

### TC007: 空数据写入

**测试目标：** 验证写入空数据的行为。

**测试步骤：**
1. 写入空字典 {}
2. 读取验证

**预期结果：**
- 写入成功
- 读取返回 {}

---

## 参数测试

### TC008: path 支持 Path 和 str 类型

**测试目标：** 验证 path 参数支持 Union[Path, str]。

**测试步骤：**
1. 使用 Path 类型调用
2. 使用 str 类型调用
3. 比较结果

**预期结果：**
- 两种类型都能正常工作
- 结果一致

**测试代码：**
```python
from data_fetchers.common import read_gzip_cache, write_gzip_cache
from pathlib import Path
import tempfile

with tempfile.TemporaryDirectory() as tmpdir:
    test_path_str = str(Path(tmpdir) / 'test.json.gz')
    test_path_obj = Path(tmpdir) / 'test.json.gz'
    
    data = {'test': [1, 2, 3]}
    
    # 使用 str 类型
    write_gzip_cache(test_path_str, data)
    loaded1 = read_gzip_cache(test_path_str)
    
    # 使用 Path 类型
    write_gzip_cache(test_path_obj, data)
    loaded2 = read_gzip_cache(test_path_obj)
    
    assert loaded1 == loaded2 == data
```

---

### TC009: logger 参数传递

**测试目标：** 验证 logger 参数传递和追溯调用方。

**测试步骤：**
1. 创建自定义 logger
2. 传入 logger 参数
3. 检查日志输出

**预期结果：**
- 日志使用传入的 logger
- 日志名称为调用方的 logger 名称

**测试代码：**
```python
from data_fetchers.common import read_gzip_cache, write_gzip_cache
import logging
from pathlib import Path
import tempfile

# 配置测试 logger
logging.basicConfig(level=logging.DEBUG)
test_logger = logging.getLogger('test_script')

with tempfile.TemporaryDirectory() as tmpdir:
    test_path = Path(tmpdir) / 'test.json.gz'
    data = {'test': [1, 2, 3]}
    
    # 传入 logger
    write_gzip_cache(test_path, data, logger=test_logger)
    loaded = read_gzip_cache(test_path, logger=test_logger)
    
    # 日志应使用 test_logger（名称为 'test_script'）
```

---

### TC010: logger 不传时使用 fallback

**测试目标：** 验证不传 logger 时使用模块级 fallback logger。

**测试步骤：**
1. 不传 logger 参数
2. 调用缓存读写
3. 检查日志输出

**预期结果：**
- 使用模块级 logger
- logger 名称为 'data_fetchers.common.cache_manager'

---

## 日志测试

### TC011: get_cache_file_info 日志输出

**测试目标：** 验证 get_cache_file_info 使用 logger 参数。

**测试步骤：**
1. 传入 logger 参数
2. 获取文件信息
3. 检查日志输出

**预期结果：**
- 文件存在时输出 DEBUG 日志
- 文件不存在时输出 WARNING 日志

---

## 异常测试

### TC012: JSONDecodeError 包装为 ValueError

**测试目标：** 验证 JSONDecodeError 被 ValueError 包装，避免内存翻倍。

**测试步骤：**
1. 创建大 JSON 文件（模拟内存场景）
2. 损坏 JSON 格式
3. 触发异常

**预期结果：**
- 抛出 ValueError（而非 JSONDecodeError）
- 异常链保留（__cause__ 为 JSONDecodeError）

---

## 测试汇总

| 测试编号 | 测试类型 | 测试目标 |
|---------|---------|---------|
| TC001 | 功能 | gzip 缓存读写一致性 |
| TC002 | 功能 | json 缓存读写一致性 |
| TC003 | 功能 | 增量追加数据 |
| TC004 | 功能 | 获取缓存文件信息 |
| TC005 | 边界 | 文件不存在异常 |
| TC006 | 边界 | JSON 格式错误异常 |
| TC007 | 边界 | 空数据写入 |
| TC008 | 参数 | path 类型支持 |
| TC009 | 参数 | logger 参数传递 |
| TC010 | 参数 | logger fallback |
| TC011 | 日志 | get_cache_file_info 日志 |
| TC012 | 异常 | JSONDecodeError 包装 |

---

*最后更新: 2026-05-24 21:10 北京时间*