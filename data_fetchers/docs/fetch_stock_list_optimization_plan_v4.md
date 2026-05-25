# fetch_stock_list.py 第四轮优化计划 v4.0

> 创建时间: 2026-05-27 07:00 北京时间
> 基于 v2.2 版本深度审查

---

## 发现的问题清单

### 1. load_cache 异常捕获范围过小

**问题**: 第652行只捕获 `json.JSONDecodeError`

**当前代码**:
```python
try:
    with open(CACHE_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)
except json.JSONDecodeError as e:
    logger.error(f"加载缓存失败: [{type(e).__name__}]: {e}")
    return None
```

**潜在风险**:
- 文件存在但读取失败（PermissionError、IsADirectoryError）会抛异常未捕获
- 文件损坏导致 OSError 也未捕获

**修复**: 捕获 `Exception`（遵循 MODULE.md 约束 55）

### 2. session 资源未关闭

**问题**: 第243行创建 session，但函数结束时未关闭

**当前代码**:
```python
session = create_sina_session(logger=logger)
# ... 使用 session
# 函数结束，session 未关闭
```

**潜在风险**:
- HTTP Session 资源泄漏
- 连接池未释放

**修复**: 使用 `try-finally` 确保 session 关闭

### 3. validate_cache 内部 logger_arg 未使用

**问题**: 参数已添加但函数内部未使用

**当前状态**: 纯验证函数，不产生日志

**修复**: 添加 docstring Note 说明设计意图

---

## 执行检查清单

```
□ Round 1: load_cache 异常捕获扩大
□ Round 2: fetch_stocks_from_sina session 关闭
□ Round 3: validate_cache docstring 补充 Note
□ Round 4: 版本号更新 2.4 → 2.5
□ Round 5: 流程文档同步更新
□ Round 6: MODULE.md 版本历史新增条目
□ Git commit
```