# fetch_stock_list.py 第二轮优化计划 v2.0

> 创建时间: 2026-05-27 06:30 北京时间
> 基于 v2.0 版本深度审查

---

## 发现的问题清单

### 1. MODULE.md 约束 51（导入在模块顶部）

**问题**: 第787-788行在 `__main__` 内导入 `requests`

**修复**: 移动 `requests` 导入到文件顶部

**依据**: PEP 8 规范，MODULE.md 约束 51

### 2. MODULE.md 约束 55（原子写入捕获所有异常）

**问题**: 第607行只捕获 `OSError`

**修复**: 改为捕获 `Exception`

**依据**: MODULE.md 约束 55："原子写入捕获所有异常 except Exception（而非仅 OSError）"

### 3. MODULE.md 约束 76（返回类型注解完整）

**问题**: `ensure_cache_dir` 和 `ensure_result_dir` 缺少返回类型注解

**修复**: 添加 `-> None` 类型注解

### 4. 类型注解不完整

**问题**: 第343行 `seen: set` 缺少元素类型

**修复**: 改为 `seen: set[str]`

### 5. validate_cache 缺少 logger 参数

**问题**: 第365行 `validate_cache` 只使用模块级 logger

**修复**: 添加 logger 参数，遵循公共模块日志参数化规范

### 6. _write_json_file Raises 不完整

**问题**: docstring 只写 OSError，但实际捕获 Exception

**修复**: 更新 Raises 说明

---

## 执行检查清单

```
□ Round 1: requests 导入移动到顶部
□ Round 2: 原子写入异常捕获扩大
□ Round 3: 公共函数类型注解补全
□ Round 4: validate_cache logger 参数化
□ Round 5: 流程文档同步更新
□ Git commit
```