# cache_manager.py 第五轮优化计划

> 创建时间: 2026-05-24 21:50 北京时间
> 审查范围: cache_manager.py (393行)
> 审查依据: PROJECT.md、MODULE.md、用户体验优化、性能监控最佳实践

---

## 一、审查发现

### 1.1 缺少统一缓存 API（高优先级）

**当前调用方式：**
```python
# 调用方需要手动判断文件类型
if path.suffix == '.gz':
    data = read_gzip_cache(path)
else:
    data = read_json_cache(path)
```

**问题：**
- 调用方负担重，需手动判断文件类型
- 代码重复，每个调用方都需要相同逻辑
- 不符合用户体验最佳实践

**修复方案：**
```python
# 提供统一接口
def read_cache(path: Union[Path, str], logger: Optional[logging.Logger] = None) -> Dict[str, Any]:
    """读取缓存（自动判断 gzip/json）"""
    use_gzip = _is_gzip_file(Path(path))
    return _read_cache_impl(Path(path), use_gzip, get_module_logger(logger))

def write_cache(path: Union[Path, str], data: Dict[str, Any], logger: Optional[logging.Logger] = None) -> None:
    """写入缓存（自动判断 gzip/json）"""
    use_gzip = _is_gzip_file(Path(path))
    _write_cache_impl(Path(path), data, use_gzip, ensure_dir=True, logger=get_module_logger(logger))
```

---

### 1.2 缺少缓存大小监控（中优先级）

**当前实现问题：**
- 无文件大小检查
- 大文件（>100MB）可能导致内存问题
- 缺少性能警告

**修复方案：**
```python
# _read_cache_impl 添加文件大小检查
file_size_mb = path.stat().st_size / (1024 * 1024)
if file_size_mb > 100:
    logger.warning("大缓存文件读取: %.2f MB, 可能影响性能", file_size_mb)
```

---

### 1.3 缺少原子写入模式（中优先级）

**当前实现风险：**
- 直接写入目标文件
- 写入失败时，可能产生损坏文件
- 原数据丢失

**修复方案：**
```python
# 原子写入：先写入临时文件，成功后重命名
import tempfile
import shutil

temp_path = path.with_suffix(path.suffix + '.tmp')
try:
    # 写入临时文件
    _write_to_file(temp_path, data, use_gzip)
    # 重命名临时文件
    shutil.move(str(temp_path), str(path))
except Exception:
    # 清理临时文件
    if temp_path.exists():
        temp_path.unlink()
    raise
```

---

### 1.4 缺少辅助函数（低优先级）

**缺失函数：**
- `cache_exists(path)`：缓存存在性检查
- `delete_cache(path)`：缓存删除 + 日志记录

---

## 二、优化方案

### 2.1 新增统一缓存 API

**新增函数：**
```python
def read_cache(path: Union[Path, str], logger: Optional[logging.Logger] = None) -> Dict[str, Any]:
    """读取缓存（自动判断 gzip/json）"""
    
def write_cache(path: Union[Path, str], data: Dict[str, Any], ensure_dir: bool = True, logger: Optional[logging.Logger] = None) -> None:
    """写入缓存（自动判断 gzip/json）"""
```

**__all__ 更新：**
```python
__all__ = [
    'get_module_logger',
    'read_cache',          # 新增
    'write_cache',         # 新增
    'read_gzip_cache',
    'write_gzip_cache',
    'read_json_cache',
    'write_json_cache',
    'append_to_cache',
    'get_cache_file_info',
]
```

---

### 2.2 添加缓存大小监控

**实现位置：**
- `_read_cache_impl` 第86行（文件存在检查后）
- `_write_cache_impl` 第137行（写入前）

**阈值定义：**
```python
# 大文件阈值（MB）
_LARGE_FILE_THRESHOLD_MB = 100
```

---

### 2.3 添加原子写入模式（可选参数）

**新增参数：**
```python
def write_cache(..., atomic: bool = False) -> None:
    """原子写入模式（默认 False，兼容现有调用）"""
```

---

### 2.4 新增辅助函数

**新增函数：**
```python
def cache_exists(path: Union[Path, str]) -> bool:
    """检查缓存文件是否存在"""
    
def delete_cache(path: Union[Path, str], logger: Optional[logging.Logger] = None) -> bool:
    """删除缓存文件（返回是否成功）"""
```

---

## 三、执行步骤

### Step 1: 新增统一缓存 API

**变更文件：**
- cache_manager.py

**具体操作：**
1. 新增 `read_cache` 函数
2. 新增 `write_cache` 函数
3. 更新 `__all__` 导出列表

---

### Step 2: 添加缓存大小监控

**变更文件：**
- cache_manager.py

**具体操作：**
1. 定义 `_LARGE_FILE_THRESHOLD_MB = 100`
2. `_read_cache_impl` 添加文件大小检查 + WARNING 日志
3. `_write_cache_impl` 添加数据大小估算 + WARNING 日志

---

### Step 3: 新增辅助函数

**变更文件：**
- cache_manager.py

**具体操作：**
1. 新增 `cache_exists` 函数
2. 新增 `delete_cache` 函数
3. 更新 `__all__` 导出列表

---

### Step 4: 更新文档

**变更文件：**
- docs/cache_manager_flow.md
- MODULE.md

**具体操作：**
1. 流程文档版本历史 v1.4
2. MODULE.md 版本历史 v2.6
3. 架构图新增统一 API

---

### Step 5: 测试验证

**测试命令：**
```bash
# 导入测试
python -c "from data_fetchers.common.cache_manager import read_cache, write_cache, cache_exists, delete_cache"

# 功能测试
python data_fetchers/common/cache_manager.py
```

---

### Step 6: Git 提交

**提交信息：**
```
优化 cache_manager.py 第五轮：统一缓存 API + 大文件监控 + 辅助函数

- 新增 read_cache/write_cache 统一接口（自动判断 gzip/json）
- 新增 cache_exists/delete_cache 辅助函数
- 添加大文件监控（>100MB WARNING 日志）
- 更新 __all__ 导出列表（新增 4 个函数）
- 更新流程文档 v1.4
- 更新 MODULE.md v2.6
```

---

## 四、预期收益

| 收益项 | 量化指标 |
|--------|---------|
| 调用方代码简化 | 统一 API 减少判断代码 |
| 性能监控提升 | 大文件 WARNING 提醒 |
| 功能完整性提升 | 新增 4 个常用函数 |

---

## 五、风险评估

| 风险项 | 概率 | 影响 | 缓解措施 |
|--------|------|------|---------|
| 统一 API 兼容性 | 无 | - | 保留原有函数，向后兼容 |
| 大文件阈值合理性 | 低 | 中 | 100MB 为业界通用阈值 |

---

## 六、合规性检查

- [x] 符合 PROJECT.md 公共模块规范
- [x] 符合 MODULE.md 函数命名规范
- [x] 符合用户体验最佳实践（统一 API）
- [x] 符合性能监控最佳实践（大文件警告）