# fetch_stock_list.py 第三轮优化计划 v3.0

> 创建时间: 2026-05-27 06:45 北京时间
> 基于 v2.1 版本深度审查

---

## 发现的问题清单

### 1. 导入顺序错误（PEP 8 / MODULE.md 约束 19）

**问题**: 第38行 `import requests` 在标准库 `time` 之前

**当前顺序**:
```python
import json       # 标准库
import logging    # 标准库
import requests   # 第三方库 ← 错误位置
import time       # 标准库 ← 应在 requests 之前
from datetime import datetime  # 标准库
from pathlib import Path       # 标准库
```

**正确顺序（PEP 8）**: 标准库 → 第三方库 → 本地模块
```python
import json
import logging
import time
from datetime import datetime
from pathlib import Path
import requests   # 第三方库（应在标准库之后）
```

**依据**: MODULE.md 约束 19："常量定义在 import 之后"，PEP 8 导入顺序

### 2. save_cache 内 ensure_cache_dir/ensure_result_dir 未传 logger

**问题**: 第514-515行调用未传 logger 参数

**当前代码**:
```python
def save_cache(
    new_stocks: List[Dict[str, Any]],
    api_pages: int,
    logger: Optional[logging.Logger] = None
) -> Dict[str, Any]:
    ...
    ensure_cache_dir()      # 未传 logger
    ensure_result_dir()     # 未传 logger
```

**修复**: 传递 logger 参数
```python
    ensure_cache_dir(logger)
    ensure_result_dir(logger)
```

**依据**: PROJECT.md 日志参数化规范，MODULE.md 约束 33（函数签名与调用一致）

---

## 执行检查清单

```
□ Round 1: 修复导入顺序（requests 移至标准库之后）
□ Round 2: save_cache 内传递 logger 参数
□ Round 3: 版本号更新 2.3 → 2.4
□ Round 4: 流程文档同步更新
□ Round 5: MODULE.md 版本历史新增条目
□ Git commit
```