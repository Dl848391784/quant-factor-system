# cache_manager.py 第三轮优化计划

> 创建时间: 2026-05-24 21:20 北京时间
> 审查范围: cache_manager.py (322行)
> 审查依据: PROJECT.md、MODULE.md、DRY原则、代码重复检测

---

## 一、审查发现

### 1.1 代码重复问题（高优先级）

| 重复代码对 | 重复行数 | 重复率 | 根因 |
|-----------|---------|--------|------|
| read_gzip_cache vs read_json_cache | 35行 | 92% | 仅 gzip.open vs open 区别 |
| write_gzip_cache vs write_json_cache | 28行 | 93% | 仅 gzip.open vs open 区别 |

**具体表现：**
- read_gzip_cache（第41-83行）与 read_json_cache（第119-161行）几乎完全相同
- write_gzip_cache（第86-116行）与 write_json_cache（第164-194行）几乎完全相同
- 只有 gzip.open 和 open 的区别，其他逻辑完全一样

**违反原则：**
- DRY（Don't Repeat Yourself）原则
- PROJECT.md 第783-857行规范：公共模块需减少重复代码

---

### 1.2 append_to_cache 文件类型判断不精确

**当前实现（第223行）：**
```python
existing = read_gzip_cache(path, logger=logger) if path.suffix == '.gz' else read_json_cache(path, logger=logger)
```

**问题：**
- 文件名可能是 `data.json.gz`，`path.suffix` 返回 `.gz`
- 文件名可能是 `data.json`，`path.suffix` 返回 `.json`
- 判断逻辑正确，但第242行的判断逻辑与第223行不一致

**第242行判断：**
```python
if path.suffix == '.gz':
    write_gzip_cache(path, result, logger=logger)
else:
    write_json_cache(path, result, logger=logger)
```

**一致性检查：**
- 第223行和第242行逻辑一致，都使用 `path.suffix == '.gz'` 判断
- 但重复判断，可提取为函数

---

### 1.3 流程文档版本历史缺失更新记录

**当前状态：**
- cache_manager_flow.md 版本 v1.0，创建时间 2026-05-24 21:05
- 第二轮优化（commit 601bfc3）未记录到版本历史

---

## 二、优化方案

### 2.1 重构读写函数，消除重复代码

**设计原则：**
1. 抽取公共函数 `_read_cache_impl` 和 `_write_cache_impl`
2. 保留原有函数签名，保持向后兼容
3. 原有函数调用公共实现

**实现方案：**
```python
def _read_cache_impl(
    path: Path,
    use_gzip: bool,
    logger: logging.Logger
) -> Dict[str, Any]:
    """读取缓存的公共实现"""
    if not path.exists():
        raise FileNotFoundError(f"缓存文件不存在: {path}")
    
    try:
        if use_gzip:
            with gzip.open(path, 'rt', encoding='utf-8') as f:
                data = json.load(f)
        else:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        logger.debug("成功读取缓存: %s", path)
        return data
    except json.JSONDecodeError as e:
        logger.error(
            "JSON 解析失败\n"
            "文件路径: %s\n"
            "错误位置: 行 %d, 列 %d\n"
            "错误信息: %s",
            path, e.lineno, e.colno, e.msg
        )
        raise ValueError(f"JSON解析失败: {path}, 位置 {e.pos}") from e
    except Exception as e:
        logger.exception("读取缓存失败: %s", path)
        raise

def read_gzip_cache(
    path: Union[Path, str],
    logger: Optional[logging.Logger] = None
) -> Dict[str, Any]:
    """读取 gzip 压缩的 JSON 缓存"""
    return _read_cache_impl(Path(path), use_gzip=True, logger=get_module_logger(logger))
```

---

### 2.2 抽取文件类型判断函数

**实现方案：**
```python
def _is_gzip_file(path: Path) -> bool:
    """判断是否为 gzip 文件"""
    return path.suffix == '.gz'
```

**应用位置：**
- append_to_cache 第223行和第242行

---

### 2.3 更新流程文档版本历史

**添加版本记录：**
```markdown
## 版本历史

| 版本 | 日期 | 变更内容 |
|------|------|---------|
| v1.0 | 2026-05-24 21:05 | 初始版本，流程文档创建 |
| v1.1 | 2026-05-24 21:10 | 第二轮优化：函数命名修复 + logger 使用 |
| v1.2 | 2026-05-24 21:25 | 第三轮优化：消除代码重复 + 文件类型判断优化 |
```

---

## 三、执行步骤

### Step 1: 重构读写函数（消除重复）

**变更文件：**
- cache_manager.py

**具体操作：**
1. 添加 `_read_cache_impl` 函数（公共读取实现）
2. 添加 `_write_cache_impl` 函数（公共写入实现）
3. 添加 `_is_gzip_file` 函数（文件类型判断）
4. 重构 read_gzip_cache 调用公共实现
5. 重构 write_gzip_cache 调用公共实现
6. 重构 read_json_cache 调用公共实现
7. 重构 write_json_cache 调用公共实现
8. 重构 append_to_cache 使用 `_is_gzip_file` 函数

---

### Step 2: 更新流程文档

**变更文件：**
- docs/cache_manager_flow.md

**具体操作：**
1. 添加版本历史章节
2. 更新架构图（新增公共函数）
3. 添加公共函数说明

---

### Step 3: 更新 MODULE.md

**变更文件：**
- MODULE.md

**具体操作：**
1. 版本历史 v2.4：第三轮优化记录
2. 更新最后修改时间

---

### Step 4: 测试验证

**测试命令：**
```bash
# 导入测试
python -c "from data_fetchers.common.cache_manager import read_gzip_cache, write_gzip_cache, read_json_cache, write_json_cache"

# 功能测试
python data_fetchers/common/cache_manager.py
```

---

### Step 5: Git 提交

**提交信息：**
```
重构 cache_manager.py：消除代码重复 + 文件类型判断优化

- 新增 _read_cache_impl/_write_cache_impl 公共函数
- 重构 read_gzip_cache/read_json_cache 消除重复
- 重构 write_gzip_cache/write_json_cache 消除重复
- 新增 _is_gzip_file 函数统一文件类型判断
- 更新流程文档版本历史 v1.2
```

---

## 四、预期收益

| 收益项 | 量化指标 |
|--------|---------|
| 代码重复率降低 | 从 92% → 0% |
| 代码行数减少 | 从 322行 → ~240行（减少 82行） |
| 维护成本降低 | 单点修改替代双点修改 |
| 测试覆盖率提升 | 公共函数统一测试 |

---

## 五、风险评估

| 风险项 | 概率 | 影响 | 缓解措施 |
|--------|------|------|---------|
| 重构后功能变化 | 低 | 高 | 保持原有函数签名，单元测试验证 |
| 导入路径变化 | 无 | - | 公共函数使用 `_` 前缀，不导出 |
| 性能退化 | 无 | - | 函数调用开销可忽略 |

---

## 六、合规性检查

- [x] 符合 PROJECT.md 第783-857行规范（公共模块）
- [x] 符合 MODULE.md 第382行规范（禁止 `_logger` 前缀，使用 `_impl` 后缀）
- [x] 符合 DRY 原则
- [x] 符合 PROJECT.md "脚本配套文件规范"（流程文档 + 测试用例）