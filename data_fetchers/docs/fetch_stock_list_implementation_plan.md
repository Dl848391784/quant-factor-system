# fetch_stock_list.py 优化实现计划

> 版本: v2.9
> 创建时间: 2026-05-27 16:10 北京时间
> 目标版本: v2.9

---

## 问题诊断

### 问题1：手写原子写入未复用公共模块
**位置**: `_write_json_file` 函数（694-736行）
**现状**: 手写tempfile.NamedTemporaryFile + replace实现
**规范**: MODULE.md 约束 #4（强制复用公共模块）
**修复**: 替换为 `write_json_cache()` 调用

### 问题2：缺失pytest测试文件
**位置**: test_cases/test_fetch_stock_list.py
**现状**: 文件不存在
**规范**: PROJECT.md 编码规范（测试用例必须是pytest可执行文件）
**修复**: 创建完整测试文件，覆盖核心功能

### 问题3：缺失流程文档
**位置**: docs/fetch_stock_list_flow.md
**现状**: 文件不存在
**规范**: MODULE.md 约束 #8（流程文档配套）
**修复**: 创建完整流程文档，包含架构图、数据流、版本历史

---

## 实现步骤

### Step 1: 替换手写原子写入
```python
# 修改位置: save_cache 函数（678行、686行）
# 原代码:
_write_json_file(CACHE_FILE, cache_data, _logger)
_write_json_file(RESULT_FILE, result_data, _logger)

# 新代码:
from data_fetchers.common import write_json_cache
write_json_cache(CACHE_FILE, cache_data, json_indent=2, logger=_logger)
write_json_cache(RESULT_FILE, result_data, json_indent=2, logger=_logger)
```

**删除函数**: `_write_json_file`（694-736行）- 冗余代码

### Step 2: 创建pytest测试文件
**测试用例设计**:
- TC001: 正常流程 - fetch_stocks_from_sina mock测试
- TC002: 增量更新 - save_cache mock测试
- TC003: 缓存验证 - validate_cache测试
- TC004: 股票筛选 - is_valid_main_board_stock测试
- TC005: 市场判断 - determine_market测试
- TC006: 约束合规 - 版本号常量、公共模块导入验证

### Step 3: 创建流程文档
**文档结构**:
- 整体架构（ASCII图）
- 数据流图（增量更新流程）
- 关键函数说明
- 版本历史（v2.0 → v2.9）
- 相关文档链接

---

## 验证标准

1. pytest测试全部通过（预计6-8个测试）
2. 语法检查通过
3. 流程文档与实现一致
4. MODULE.md约束合规

---

## 预期改进

- 减少代码行数：删除 `_write_json_file`（43行）
- 提升代码质量：复用公共模块原子写入实现
- 提升可维护性：测试文件 + 流程文档完整覆盖
- 版本号: v2.8 → v2.9