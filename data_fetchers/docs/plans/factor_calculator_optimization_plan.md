# factor_calculator.py 优化计划

> 创建时间: 2026-05-27 16:30 北京时间
> 版本: v1.0

---

## 诊断结论

| 类型 | 说明 |
|-----|------|
| **代码问题** | 导入分组注释缺失、logger 类型注解不精确、__all__ 导出私有函数 |
| **规范遗漏** | MODULE.md 约束 77（logger 参数命名）未被遵循 |
| **配套缺失** | 流程文档、测试用例缺失 |

---

## 优化任务清单（分轮执行）

### Round 1: 导入规范化 + 类型注解修复（2-5分钟）

| 任务 | 修改位置 | 规范依据 |
|-----|---------|---------|
| 1.1 添加导入分组注释 | 文件顶部 import 区域 | MODULE.md 约束 63 |
| 1.2 logger 类型注解精确化 | 所有函数签名 | MODULE.md 约束 76 |

**修改示例：**

```python
# 第三方库导入
import pandas as pd
import numpy as np
from typing import Optional, Any

# 本地模块导入（无）
```

```python
def calculate_bollinger_pb(
    factor_df: pd.DataFrame,
    n: int = DEFAULT_BOLLINGER_N,
    k: float = DEFAULT_BOLLINGER_K,
    logger: Optional[logging.Logger] = None  # 精确类型注解
) -> pd.DataFrame:
```

---

### Round 2: logger 参数命名规范化（2-5分钟）

| 任务 | 修改位置 | 规范依据 |
|-----|---------|---------|
| 2.1 参数名改为 `logger_arg` | 所有函数签名 | MODULE.md 约束 77 |
| 2.2 内部变量 `_logger = logger_arg or get_module_logger(__name__)` | 所有函数体 | MODULE.md 约束 77 |

**修改示例：**

```python
def calculate_bollinger_pb(
    factor_df: pd.DataFrame,
    ...
    logger_arg: Optional[logging.Logger] = None  # 约束 77
) -> pd.DataFrame:
    _logger = logger_arg or get_module_logger(__name__)  # fallback
```

---

### Round 3: __all__ 导出修复（2分钟）

| 任务 | 修改位置 | 规范依据 |
|-----|---------|---------|
| 3.1 移除私有函数导出 | `__all__` 列表 | MODULE.md 约束 60 |

**修改：**

```python
__all__ = [
    'EPSILON',
    'calculate_rsi',
    'calculate_volume_ratio',
    'calculate_forward_return',
    'calculate_bollinger_pb',
    'calculate_kdj_j',
    'calculate_turnover_surge',
    # 移除: '_wilder_smoothing_rsi', '_calculate_ewm_with_initial'
]
```

---

### Round 4: docstring 补全（5-10分钟）

| 任务 | 修改位置 | 规范依据 |
|-----|---------|---------|
| 4.1 添加 Example 章节 | 所有公共函数 docstring | PROJECT.md 公共模块规范 |
| 4.2 添加 Raises 章节 | 所有公共函数 docstring | PROJECT.md 公共模块规范 |

---

### Round 5: 配套文件创建（10-15分钟）

| 任务 | 文件位置 | 规范依据 |
|-----|---------|---------|
| 5.1 创建流程文档 | docs/factor_calculator_flow.md | PROJECT.md 脚本配套规范 |
| 5.2 创建测试用例 | test_cases/test_factor_calculator.py | PROJECT.md 测试代码规范 |

---

### Round 6: MODULE.md 版本历史更新（2分钟）

| 任务 | 修改位置 |
|-----|---------|
| 6.1 添加 factor_calculator.py 版本历史 | MODULE.md 更新记录章节 |

---

## 执行顺序

```
Round 1 → Round 2 → Round 3 → Round 4 → Round 5 → Round 6
  ↓         ↓         ↓         ↓         ↓         ↓
 导入规范  logger命名 __all__   docstring 配套文件 版本历史
```

**每轮完成后验证语法：**
```bash
python -c "from data_fetchers.factor_calculator import calculate_rsi"
```

---

## 预期效果

| 指标 | 优化前 | 优化后 |
|-----|-------|-------|
| 导入分组注释 | 无 | 有（符合 PEP 8） |
| logger 参数命名 | `_logger = logger` | `_logger = logger_arg or fallback` |
| logger 类型注解 | `Any` | `Optional[logging.Logger]` |
| __all__ 私有函数导出 | 2个 | 0个 |
| docstring 完整度 | 缺少 Example/Raises | 完整 |
| 流程文档 | 无 | docs/factor_calculator_flow.md |
| 测试用例 | 无 | test_cases/test_factor_calculator.py |

---

## 风险评估

| 风险 | 级别 | 缓解措施 |
|-----|------|---------|
| logger 参数名变更导致调用方不兼容 | 低 | 参数名向后兼容（支持旧名称） |
| __all__ 移除私有函数导出 | 低 | 私有函数本不应被外部调用 |

---

**计划文档完成，等待用户确认后执行。**