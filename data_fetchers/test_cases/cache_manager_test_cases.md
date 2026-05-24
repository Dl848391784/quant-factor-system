# cache_manager.py 测试用例

> 版本: v1.4
> 创建时间: 2026-05-24 21:10 北京时间
> 最后更新: 2026-05-24 22:20 北京时间
> 脚本位置: data_fetchers/common/cache_manager.py

---

## 版本历史

| 版本 | 日期 | 变更内容 |
|------|------|---------|
| v1.0 | 2026-05-24 21:10 | 初始版本，覆盖第二轮优化功能 |
| v1.1 | 2026-05-24 21:45 | 第四轮优化：防御性编程测试用例 |
| v1.2 | 2026-05-24 21:50 | 第五轮优化：统一缓存 API + 辅助函数测试用例 |
| v1.3 | 2026-05-24 21:55 | 第六轮优化：gzip 压缩级别 + JSON 格式选项测试用例 |
| v1.4 | 2026-05-24 22:20 | 第七轮优化：异常处理精确化 + 空文件处理测试用例 |

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

## 第五轮优化测试用例（v1.2）

### TC013: 统一缓存 API - gzip 文件

**测试目标：** 验证 `read_cache`、`write_cache` 自动判断 gzip 文件。

**测试步骤：**
1. 使用 `write_cache` 写入 `.json.gz` 文件
2. 使用 `read_cache` 读取
3. 验证数据一致性

**预期结果：**
- 自动使用 gzip 格式
- 数据一致

**测试代码：**
```python
from data_fetchers.common import read_cache, write_cache
from pathlib import Path
import tempfile

with tempfile.TemporaryDirectory() as tmpdir:
    test_path = Path(tmpdir) / 'test.json.gz'
    data = {'gzip': True}
    
    # 统一 API（自动判断 gzip）
    write_cache(test_path, data)
    loaded = read_cache(test_path)
    
    assert loaded == data
```

---

### TC014: 统一缓存 API - json 文件

**测试目标：** 验证 `read_cache`、`write_cache` 自动判断 json 文件。

**测试步骤：**
1. 使用 `write_cache` 写入 `.json` 文件
2. 使用 `read_cache` 读取
3. 验证数据一致性

**预期结果：**
- 自动使用普通 JSON 格式
- 数据一致

---

### TC015: 缓存存在性检查

**测试目标：** 验证 `cache_exists` 函数。

**测试步骤：**
1. 创建缓存文件
2. 使用 `cache_exists` 检查
3. 删除文件后再检查

**预期结果：**
- 文件存在时返回 True
- 文件不存在时返回 False

**测试代码：**
```python
from data_fetchers.common import cache_exists, write_cache, delete_cache
from pathlib import Path
import tempfile

with tempfile.TemporaryDirectory() as tmpdir:
    test_path = Path(tmpdir) / 'test.json.gz'
    
    # 文件不存在
    assert cache_exists(test_path) == False
    
    # 创建文件
    write_cache(test_path, {'data': 'test'})
    assert cache_exists(test_path) == True
    
    # 删除文件
    delete_cache(test_path)
    assert cache_exists(test_path) == False
```

---

### TC016: 缓存删除函数

**测试目标：** 验证 `delete_cache` 函数返回值和日志。

**测试步骤：**
1. 创建缓存文件
2. 使用 `delete_cache` 删除
3. 删除不存在文件

**预期结果：**
- 文件存在时删除成功，返回 True
- 文件不存在时返回 False
- 输出 INFO 日志（删除成功）

---

### TC017: 大文件监控

**测试目标：** 验证大文件（>100MB）触发 WARNING 日志。

**测试步骤：**
1. 模拟大文件场景（检查阈值）
2. 触发 WARNING 日志

**预期结果：**
- 文件大小 >100MB 时输出 WARNING 日志
- 日志内容包含文件大小和路径

---

## 第六轮优化测试用例（v1.3）

### TC018: gzip 压缩级别控制

**测试目标：** 验证 `compresslevel` 参数控制 gzip 压缩级别。

**测试步骤：**
1. 使用不同压缩级别（1、6、9）写入
2. 比较文件大小和压缩时间

**预期结果：**
- 压缩级别 1：文件最大，压缩最快
- 压缩级别 6：平衡（默认）
- 压缩级别 9：文件最小，压缩最慢

**测试代码：**
```python
from data_fetchers.common import write_gzip_cache, read_gzip_cache
from pathlib import Path
import tempfile

with tempfile.TemporaryDirectory() as tmpdir:
    data = {'large_data': [i for i in range(10000)]}
    
    # 压缩级别 1（最快）
    path1 = Path(tmpdir) / 'level1.json.gz'
    write_gzip_cache(path1, data, compresslevel=1)
    size1 = path1.stat().st_size
    
    # 压缩级别 9（最高）
    path9 = Path(tmpdir) / 'level9.json.gz'
    write_gzip_cache(path9, data, compresslevel=9)
    size9 = path9.stat().st_size
    
    # 验证：级别 9 文件更小
    assert size9 < size1
    
    # 验证：都能正常读取
    assert read_gzip_cache(path1) == data
    assert read_gzip_cache(path9) == data
```

---

### TC019: JSON 可读格式（indent）

**测试目标：** 验证 `json_indent` 参数生成可读格式。

**测试步骤：**
1. 使用 `json_indent=None`（紧凑格式）
2. 使用 `json_indent=2`（可读格式）
3. 比较文件内容

**预期结果：**
- 紧凑格式：无缩进，文件最小
- 可读格式：缩进 2，可读性好

**测试代码：**
```python
from data_fetchers.common import write_json_cache, read_json_cache
from pathlib import Path
import tempfile

with tempfile.TemporaryDirectory() as tmpdir:
    data = {'key1': 'value1', 'key2': 'value2'}
    
    # 紧凑格式
    compact_path = Path(tmpdir) / 'compact.json'
    write_json_cache(compact_path, data, json_indent=None)
    with open(compact_path) as f:
        compact_content = f.read()
    assert '\n' not in compact_content  # 无换行
    
    # 可读格式
    readable_path = Path(tmpdir) / 'readable.json'
    write_json_cache(readable_path, data, json_indent=2)
    with open(readable_path) as f:
        readable_content = f.read()
    assert '\n' in readable_content  # 有换行
    assert '  ' in readable_content  # 有缩进
    
    # 数据一致
    assert read_json_cache(compact_path) == data
    assert read_json_cache(readable_path) == data
```

---

### TC020: JSON 键排序（sort_keys）

**测试目标：** 验证 `json_sort_keys` 参数排序 JSON 键。

**测试步骤：**
1. 使用 `json_sort_keys=False`（不排序）
2. 使用 `json_sort_keys=True`（排序）
3. 比较文件内容

**预期结果：**
- 不排序：键顺序不确定
- 排序：键按字母顺序排序

**测试代码：**
```python
from data_fetchers.common import write_json_cache
from pathlib import Path
import tempfile

with tempfile.TemporaryDirectory() as tmpdir:
    data = {'z_key': 1, 'a_key': 2, 'm_key': 3}
    
    # 排序键
    sorted_path = Path(tmpdir) / 'sorted.json'
    write_json_cache(sorted_path, data, json_sort_keys=True, json_indent=2)
    with open(sorted_path) as f:
        content = f.read()
    
    # 验证：键顺序为 a_key, m_key, z_key
    assert content.index('a_key') < content.index('m_key') < content.index('z_key')
```

---

### TC021: 缓存数据类型验证

**测试目标：** 验证 `_write_cache_impl` 数据类型验证和 WARNING 日志。

**测试步骤：**
1. 写入字典数据（正常）
2. 写入非字典数据（触发 WARNING）

**预期结果：**
- 字典数据：正常写入，无 WARNING
- 非字典数据（如 list）：触发 WARNING 日志，但仍写入

**测试代码：**
```python
from data_fetchers.common import write_json_cache
from pathlib import Path
import tempfile
import logging

# 配置日志捕获
logging.basicConfig(level=logging.WARNING)

with tempfile.TemporaryDirectory() as tmpdir:
    # 正常写入（字典）
    normal_path = Path(tmpdir) / 'normal.json'
    write_json_cache(normal_path, {'data': 'test'})
    
    # 异常写入（非字典）- 应触发 WARNING
    abnormal_path = Path(tmpdir) / 'abnormal.json'
    write_json_cache(abnormal_path, ['list', 'data'])  # list 类型
    
    # 验证：文件仍成功写入（JSON 支持 list）
    import json
    with open(abnormal_path) as f:
        loaded = json.load(f)
    assert loaded == ['list', 'data']
```

---

## 测试汇总

| 测试编号 | 测试类型 | 测试目标 | 版本 |
|---------|---------|---------|------|
| TC001 | 功能 | gzip 缓存读写一致性 | v1.0 |
| TC002 | 功能 | json 缓存读写一致性 | v1.0 |
| TC003 | 功能 | 增量追加数据 | v1.0 |
| TC004 | 功能 | 获取缓存文件信息 | v1.0 |
| TC005 | 边界 | 文件不存在异常 | v1.0 |
| TC006 | 边界 | JSON 格式错误异常 | v1.0 |
| TC007 | 边界 | 空数据写入 | v1.0 |
| TC008 | 参数 | path 类型支持 | v1.0 |
| TC009 | 参数 | logger 参数传递 | v1.0 |
| TC010 | 参数 | logger fallback | v1.0 |
| TC011 | 日志 | get_cache_file_info 日志 | v1.0 |
| TC012 | 异常 | JSONDecodeError 包装 | v1.0 |
| TC013 | 功能 | 统一缓存 API - gzip | v1.2 |
| TC014 | 功能 | 统一缓存 API - json | v1.2 |
| TC015 | 功能 | 缓存存在性检查 | v1.2 |
| TC016 | 功能 | 缓存删除函数 | v1.2 |
| TC017 | 性能 | 大文件监控 | v1.2 |
| TC018 | 参数 | gzip 压缩级别控制 | v1.3 |
| TC019 | 参数 | JSON 可读格式 | v1.3 |
| TC020 | 参数 | JSON 键排序 | v1.3 |
| TC021 | 验证 | 缓存数据类型验证 | v1.3 |

---

## 第七轮优化测试用例（v1.4）

### TC022: gzip 文件损坏处理

**测试目标：** 验证 gzip 文件损坏时捕获 ValueError。

**测试步骤：**
1. 创建无效 gzip 文件（写入非 gzip 内容）
2. 调用 `read_gzip_cache`
3. 验证捕获 ValueError

**预期结果：**
- 抛出 ValueError（而非 BadGzipFile）
- 错误信息包含 "gzip 文件损坏"

**测试代码：**
```python
from data_fetchers.common import read_gzip_cache
from pathlib import Path
import tempfile

with tempfile.TemporaryDirectory() as tmpdir:
    corrupt_gzip = Path(tmpdir) / 'corrupt.json.gz'
    
    # 写入无效 gzip 内容
    with open(corrupt_gzip, 'wb') as f:
        f.write(b'invalid gzip content')
    
    try:
        read_gzip_cache(corrupt_gzip)
    except ValueError as e:
        assert 'gzip 文件损坏' in str(e)
```

---

### TC023: 空文件处理

**测试目标：** 验证空文件（大小为 0）返回空字典 {}。

**测试步骤：**
1. 创建空文件（大小为 0）
2. 调用 `read_json_cache`
3. 验证返回 {}

**预期结果：**
- 返回空字典 {}
- 输出 WARNING 日志

**测试代码：**
```python
from data_fetchers.common import read_json_cache
from pathlib import Path
import tempfile

with tempfile.TemporaryDirectory() as tmpdir:
    empty_file = Path(tmpdir) / 'empty.json'
    empty_file.touch()  # 创建空文件
    
    result = read_json_cache(empty_file)
    assert result == {}
```

---

### TC024: 权限错误处理

**测试目标：** 验证文件权限错误时捕获 PermissionError。

**测试步骤：**
1. 创建文件并修改权限（只读）
2. 调用 `write_json_cache`
3. 验证捕获 PermissionError

**预期结果：**
- 抛出 PermissionError
- 错误信息包含 "无权限写入缓存文件"

**测试代码：**
```python
from data_fetchers.common import write_json_cache
from pathlib import Path
import tempfile
import os

with tempfile.TemporaryDirectory() as tmpdir:
    readonly_file = Path(tmpdir) / 'readonly.json'
    readonly_file.touch()
    os.chmod(readonly_file, 0o444)  # 只读权限
    
    try:
        write_json_cache(readonly_file, {'data': 'test'})
    except PermissionError as e:
        assert '无权限写入缓存文件' in str(e)
```

---

## 测试汇总（v1.4）

| 测试编号 | 测试类型 | 测试目标 | 版本 |
|---------|---------|---------|------|
| TC001 | 功能 | gzip 缓存读写一致性 | v1.0 |
| TC002 | 功能 | json 缓存读写一致性 | v1.0 |
| TC003 | 功能 | 增量追加数据 | v1.0 |
| TC004 | 功能 | 获取缓存文件信息 | v1.0 |
| TC005 | 边界 | 文件不存在异常 | v1.0 |
| TC006 | 边界 | JSON 格式错误异常 | v1.0 |
| TC007 | 边界 | 空数据写入 | v1.0 |
| TC008 | 参数 | path 类型支持 | v1.0 |
| TC009 | 参数 | logger 参数传递 | v1.0 |
| TC010 | 参数 | logger fallback | v1.0 |
| TC011 | 日志 | get_cache_file_info 日志 | v1.0 |
| TC012 | 异常 | JSONDecodeError 包装 | v1.0 |
| TC013 | 功能 | 统一缓存 API - gzip | v1.2 |
| TC014 | 功能 | 统一缓存 API - json | v1.2 |
| TC015 | 功能 | 缓存存在性检查 | v1.2 |
| TC016 | 功能 | 缓存删除函数 | v1.2 |
| TC017 | 性能 | 大文件监控 | v1.2 |
| TC018 | 参数 | gzip 压缩级别控制 | v1.3 |
| TC019 | 参数 | JSON 可读格式 | v1.3 |
| TC020 | 参数 | JSON 键排序 | v1.3 |
| TC021 | 验证 | 缓存数据类型验证 | v1.3 |
| TC022 | 异常 | gzip 文件损坏处理 | v1.4 |
| TC023 | 边界 | 空文件处理 | v1.4 |
| TC024 | 异常 | 权限错误处理 | v1.4 |

---

*最后更新: 2026-05-24 22:20 北京时间*