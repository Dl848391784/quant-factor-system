# factor_generator.py v1.3 优化计划

> 创建时间: 2026-05-25
> 执行者: 云瑶

---

## 优化目标

对 factor_generator.py 进行第三轮深度优化，对比 cache_manager.py v1.12 和 stock_utils.py v2.1 的公共模块规范，发现并修复遗漏问题。

---

## 当前状态

factor_generator.py v1.2 (2026-05-25) 已完成：
- logger 参数化 ✓
- __all__ 导出 ✓
- 类型注解精确化 ✓
- 异常处理补全 ✓
- 原子写入 ✓
- CLI 日志规范化 ✓
- docstring 补全 ✓
- __init__.py 导出 ✓

---

## Spec Compliance 检查清单

### 1. 常量命名规范

**问题**: `DEFAULT_CACHE_DIR` 应改为 `_DEFAULT_CACHE_DIR`（私有常量）

**对比**:
- cache_manager.py: `_DEFAULT_GZIP_COMPRESSLEVEL`、`_LARGE_FILE_THRESHOLD_MB`
- stock_utils.py: `_MIN_DATE`（私有）
- factor_generator.py: `DEFAULT_CACHE_DIR`（公开）

**修复**: 改为 `_DEFAULT_CACHE_DIR`

---

### 2. 导入顺序 PEP 8 合规化

**当前导入顺序**:
```python
import json
import gzip
import logging
import os
import pandas as pd
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Union, Any
```

**问题**: 
- 标准库导入应按字母顺序：gzip, json, logging, os
- datetime 导入实际使用（datetime.now()），保留

**修复**: 调整导入顺序为 PEP 8 标准

---

### 3. CLI 参数完整性检查

**当前 CLI 参数**:
- `--factor_data`: 基础因子数据路径 ✓
- `--turnover_data`: 换手率数据路径 ✓
- `--output`: 输出路径 ✓
- `--quiet`: 静默模式 ✓

**对比 MODULE.md 第603-608行**:
- 缺少因子参数覆盖（如 --rsi_period、--bollinger_n）

**决策**: 当前版本因子参数硬编码，暂不添加 CLI 参数（后续版本可扩展）

---

### 4. __init__.py 导出完整性

**当前导出**:
- `generate_all_factors` ✓
- `get_module_logger` ✓

**检查**: 对比 factor_generator.py __all__，两者一致 ✓

---

### 5. get_module_logger 类型验证

**对比 cache_manager.py 第69-84行**:
- cache_manager.py: 无类型验证（直接返回）
- stock_utils.py v1.7+: 有类型验证

**factor_generator.py 第77-83行**: 有类型验证 ✓

```python
if not isinstance(logger, logging.Logger):
    raise TypeError(...)
```

---

### 6. __main__ 测试规范化

**检查项**:
- 使用 logger 替代 print ✓
- try/finally 资源清理 ✓
- setup_logger 导入 ✓

---

### 7. 导入位置规范

**问题**: 第131-134行在函数内导入 factor_ic 模块

```python
from factor_ic.ic_kdj_j_1d import calculate_kdj_j
from factor_ic.ic_bollinger_pb_1d import calculate_bollinger_pb
from factor_ic.ic_turnover_surge_1d import calculate_turnover_surge
```

**对比 PROJECT.md 第401-418行规范**:
> 所有 import 语句必须在文件顶部，禁止在函数内部 import。

**但注意**: MODULE.md 第776-777行说：
> 禁止：factor_generator.py 导入 factor_ic.common.*

**这是模块边界规范**。factor_generator.py 导入的是 factor_ic 的计算函数，不是公共模块。

**决策**: 需要移动到文件顶部，但需注意模块边界。

---

## 修复清单

| # | 问题 | 修复方式 | 优先级 |
|---|------|---------|--------|
| 1 | 常量命名不规范 | `DEFAULT_CACHE_DIR` → `_DEFAULT_CACHE_DIR` | 高 |
| 2 | 导入顺序不规范 | 调整标准库导入顺序（gzip, json, logging, os） | 中 |
| 3 | 导入位置违反规范 | 函数内导入移到文件顶部 | 高 |

---

## 不修复项

| # | 问题 | 原因 |
|---|------|------|
| 1 | 缺少因子参数 CLI | 当前版本硬编码，后续版本扩展 |
| 2 | 模块边界导入 | 导入计算函数而非公共模块，符合 MODULE.md |

---

## 执行顺序

1. Step 1: 常量命名修复 → 验证
2. Step 2: 导入顺序调整 → 验证
3. Step 3: 导入位置修复 → 验证
4. Step 4: 更新 MODULE.md 版本历史
5. Step 5: 运行脚本验证
6. Step 6: Git commit

---

## 验证方法

```bash
# 导入验证
python -c "from data_fetchers.factor_generator import generate_all_factors, get_module_logger"

# 运行测试
python data_fetchers/factor_generator.py

# 检查常量私有化
grep -n "DEFAULT_CACHE_DIR" data_fetchers/factor_generator.py
```