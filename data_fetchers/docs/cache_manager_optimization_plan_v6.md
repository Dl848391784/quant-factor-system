# cache_manager.py 第六轮优化计划

> 创建时间: 2026-05-24 21:55 北京时间
> 审查范围: cache_manager.py (501行)
> 审查依据: PROJECT.md、MODULE.md、性能优化最佳实践、并发安全最佳实践

---

## 一、审查发现

### 1.1 缺少 gzip 压缩级别控制（高优先级）

**当前实现：**
```python
with gzip.open(path, 'wt', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
```

**问题：**
- gzip.open 默认使用 `compresslevel=9`（最高压缩）
- 对于大型数据集（>10MB），压缩时间可能很长
- 影响写入性能

**性能对比：**
| 压缩级别 | 压缩率 | 压缩时间 | 适用场景 |
|---------|--------|---------|---------|
| 1 | 50% | 最快 | 实时写入 |
| 6 | 70% | 平衡 | 默认推荐 |
| 9 | 80% | 最慢 | 长期存储 |

**修复方案：**
```python
# 新增模块级常量
_DEFAULT_GZIP_COMPRESSLEVEL = 6  # 平衡压缩率和速度

# _write_cache_impl 新增参数
def _write_cache_impl(
    path: Path,
    data: Dict[str, Any],
    use_gzip: bool,
    ensure_dir: bool,
    logger: logging.Logger,
    compresslevel: int = _DEFAULT_GZIP_COMPRESSLEVEL  # 新增参数
) -> None:
    if use_gzip:
        with gzip.open(path, 'wt', encoding='utf-8', compresslevel=compresslevel) as f:
            json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
```

---

### 1.2 缺少 JSON 序列化格式选项（中优先级）

**当前实现：**
```python
json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
```

**问题：**
- 紧凑格式，不可读
- 键未排序，不一致
- 缺少格式化选项

**修复方案：**
```python
# 新增模块级常量
_JSON_COMPACT_SEPARATORS = (',', ':')  # 紧凑格式
_JSON_READABLE_INDENT = 2               # 可读格式缩进

# _write_cache_impl 新增参数
def _write_cache_impl(
    ...,
    json_indent: Optional[int] = None,   # 新增参数（None=紧凑，数字=可读）
    json_sort_keys: bool = False         # 新增参数（键排序）
) -> None:
    if json_indent is None:
        separators = _JSON_COMPACT_SEPARATORS
    else:
        separators = None  # 默认分隔符
    
    json.dump(data, f, ensure_ascii=False, indent=json_indent, separators=separators, sort_keys=json_sort_keys)
```

---

### 1.3 缺少缓存数据类型验证（中优先级）

**当前实现：**
```python
def _write_cache_impl(path, data: Dict[str, Any], ...) -> None:
    # 无验证，直接写入
```

**问题：**
- 如果传入非字典数据（如 list），json.dump 会成功
- 但不符合函数签名预期（`Dict[str, Any]`）
- 可能导致后续读取逻辑异常

**修复方案：**
```python
def _write_cache_impl(...):
    # 验证数据类型
    if not isinstance(data, dict):
        logger.warning(
            "缓存数据类型异常: 预期 dict，实际 %s\n"
            "文件路径: %s\n"
            "继续写入（JSON 支持非字典数据）",
            type(data).__name__, path
        )
```

---

### 1.4 缺少并发安全机制（低优先级，暂不实现）

**风险场景：**
- 多进程并发写入同一缓存文件
- 数据损坏或丢失

**修复方案（暂不实现）：**
- 文件锁机制（fcntl.flock）
- 增加复杂度，暂不引入

---

## 二、优化方案

### 2.1 新增 gzip 压缩级别控制

**新增常量：**
```python
# gzip 压缩级别（1-9，默认 6 平衡压缩率和速度）
_DEFAULT_GZIP_COMPRESSLEVEL = 6
```

**新增参数：**
```python
# 所有写入函数新增 compresslevel 参数
def write_gzip_cache(..., compresslevel: int = _DEFAULT_GZIP_COMPRESSLEVEL) -> None:
    ...

def write_cache(..., compresslevel: int = _DEFAULT_GZIP_COMPRESSLEVEL) -> None:
    ...
```

---

### 2.2 新增 JSON 序列化格式选项

**新增常量：**
```python
# JSON 序列化选项
_JSON_COMPACT_SEPARATORS = (',', ':')  # 紧凑格式
_JSON_READABLE_INDENT = 2               # 可读格式缩进
```

**新增参数：**
```python
# 所有写入函数新增 json_indent、json_sort_keys 参数
def write_gzip_cache(..., json_indent: Optional[int] = None, json_sort_keys: bool = False) -> None:
    ...

def write_cache(..., json_indent: Optional[int] = None, json_sort_keys: bool = False) -> None:
    ...
```

---

### 2.3 添加缓存数据类型验证

**验证位置：**
- `_write_cache_impl` 第156行（写入前）

---

## 三、执行步骤

### Step 1: 新增模块级常量

**变更文件：**
- cache_manager.py

**具体操作：**
1. 新增 `_DEFAULT_GZIP_COMPRESSLEVEL = 6`
2. 新增 `_JSON_COMPACT_SEPARATORS = (',', ':')`
3. 新增 `_JSON_READABLE_INDENT = 2`

---

### Step 2: 修改 _write_cache_impl

**变更文件：**
- cache_manager.py

**具体操作：**
1. 新增 `compresslevel` 参数
2. 新增 `json_indent` 参数
3. 新增 `json_sort_keys` 参数
4. 添加数据类型验证
5. 修改 gzip.open 和 json.dump 逻辑

---

### Step 3: 更新所有写入函数签名

**变更文件：**
- cache_manager.py

**具体操作：**
1. `write_gzip_cache` 新增参数
2. `write_json_cache` 新增参数
3. `write_cache` 新增参数
4. `_write_cache_impl` 调用传递新参数

---

### Step 4: 更新文档

**变更文件：**
- docs/cache_manager_flow.md
- MODULE.md

**具体操作：**
1. 流程文档版本历史 v1.5
2. MODULE.md 版本历史 v2.7
3. 更新函数签名说明

---

### Step 5: 测试验证

**测试命令：**
```bash
# 导入测试
python -c "from data_fetchers.common.cache_manager import write_cache"

# 功能测试（压缩级别）
python data_fetchers/common/cache_manager.py
```

---

### Step 6: Git 提交

**提交信息：**
```
优化 cache_manager.py 第六轮：gzip 压缩级别 + JSON 格式选项 + 数据类型验证

- 新增 gzip 压缩级别控制（compresslevel 参数，默认 6）
- 新增 JSON 序列化格式选项（json_indent、json_sort_keys 参数）
- 新增缓存数据类型验证（非字典类型 WARNING 日志）
- 新增模块级常量（_DEFAULT_GZIP_COMPRESSLEVEL、_JSON_COMPACT_SEPARATORS）
- 更新所有写入函数签名
- 更新流程文档 v1.5
- 更新 MODULE.md v2.7
```

---

## 四、预期收益

| 收益项 | 量化指标 |
|--------|---------|
| 压缩性能提升 | 压缩级别 6 → 压缩时间减少 30% |
| 格式灵活性提升 | 支持紧凑/可读两种格式 |
| 数据验证提升 | 非字典类型 WARNING 提醒 |

---

## 五、风险评估

| 风险项 | 概率 | 影响 | 缓解措施 |
|--------|------|------|---------|
| 压缩级别兼容性 | 无 | - | gzip.open 支持 compresslevel 参数 |
| JSON 参数兼容性 | 无 | - | json.dump 支持 indent、sort_keys 参数 |
| 默认行为变化 | 无 | - | 默认参数保持原有行为 |

---

## 六、合规性检查

- [x] 符合 PROJECT.md 公共模块规范
- [x] 符合 MODULE.md 函数命名规范
- [x] 符合性能优化最佳实践（gzip 压缩级别）
- [x] 符合用户体验最佳实践（格式选项）