# cache_manager.py 第二轮优化计划

> 创建时间: 2026-05-24 21:00 北京时间
> 版本: v2.0

---

## 第一轮优化回顾

**已完成：**
1. logger 参数化
2. JSONDecodeError 内存优化
3. path 支持 Path | str
4. MODULE.md 同步更新

---

## 第二轮诊断结论

**问题类型：混合问题（规范遗漏 + 代码改进 + 代码 bug）**

| 问题 | 类型 | 说明 |
|------|------|------|
| `_get_logger` 函数名违反规范 | 代码改进 | MODULE.md 禁止 `_logger` 前缀（第382行），但 `_get_logger` 用了 `_` |
| `get_cache_file_info` logger 参数未使用 | 代码 bug | 获取了 logger 但未实际使用 |
| 缺少流程文档 | 规范遗漏 | PROJECT.md 要求 docs/cache_manager_flow.md |
| 缺少测试用例文档 | 规范遗漏 | PROJECT.md 要求 test_cases/cache_manager_test_cases.md |

---

## 分步执行计划（Bite-sized Tasks）

### Step 1: 修复 `_get_logger` 函数命名

**问题：** `_get_logger` 使用 `_` 前缀，但它是公共辅助函数，不应使用私有前缀。

**修改方案：**
```python
# 当前代码
_MODULE_LOGGER = None

def _get_logger(logger: Optional[logging.Logger] = None) -> logging.Logger:
    """获取 logger，遵循 PROJECT.md 公共模块日志规范"""
    ...

# 改为
_MODULE_LOGGER = None

def get_module_logger(logger: Optional[logging.Logger] = None) -> logging.Logger:
    """获取 logger，遵循 PROJECT.md 公共模块日志规范"""
    ...
```

**命名选择：** `get_module_logger` 清晰表达"获取模块级 logger"的语义。

---

### Step 2: 修复 `get_cache_file_info` logger 未使用问题

**问题：** 第272行获取了 logger 但未使用。

**修改方案：**
```python
# 当前代码
def get_cache_file_info(...):
    path = Path(path)
    logger = _get_logger(logger)  # 获取但未使用
    
    info = {...}
    return info

# 改为：添加 debug 日志
def get_cache_file_info(...):
    path = Path(path)
    logger = get_module_logger(logger)
    
    info = {...}
    
    if path.exists():
        logger.debug("获取缓存文件信息: %s, 大小 %.2f MB", path, info['size_mb'])
    
    return info
```

---

### Step 3: 创建流程文档 docs/cache_manager_flow.md

**遵循 PROJECT.md"脚本配套文件规范"章节。**

**内容结构：**
1. 模块概述
2. 核心函数流程图
3. 函数详细说明
4. 使用示例
5. 错误处理
6. 版本历史

---

### Step 4: 创建测试用例 test_cases/cache_manager_test_cases.md

**遵循 PROJECT.md"脚本配套文件规范"章节。**

**内容结构：**
1. 功能测试：读写缓存
2. 边界测试：文件不存在、JSON 格式错误
3. 参数测试：Path | str 类型
4. 日志测试：logger 参数传递
5. 异常测试：JSONDecodeError 包装

---

### Step 5: 同步更新 MODULE.md

**更新版本历史 v2.3**

---

## 执行顺序

```
Step 1 → 验证语法 → Step 2 → 验证语法 → Step 3 → Step 4 → Step 5 → Git commit
```

---

*最后更新: 2026-05-24 21:00 北京时间*