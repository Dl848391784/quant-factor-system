# weight_selector.py v1.4 优化计划

## 问题清单（5轮审查发现）

| Round | 问题 | 类型 |
|-------|------|------|
| 1 | 流程文档不存在 | 文档缺失 |
| 3 | `select_best_method()` 缺少空字典检查 | 代码防御 |
| 4 | 流程文档不存在（重复） | 文档缺失 |
| 5 | 测试用例文档不存在 | 文档缺失 |
| 5 | pytest 缺少边界测试（空字典） | 测试缺失 |

## 修复方案

### 1. 代码修改（weight_selector.py）

**位置**: `select_best_method()` 函数第 287-289 行

**修改内容**: 添加空字典检查

```python
def select_best_method(final_scores: dict[str, float]) -> tuple[str, float, list[tuple[str, float]]]:
    """选择最优方法"""
    # 防御性检查（遵循 MODULE.md 约束 M31: 校验前置）
    if not final_scores:
        raise ValueError("final_scores 不能为空")
    
    ranked = sorted(final_scores.items(), key=lambda x: x[1], reverse=True)
    best_method, best_score = ranked[0]
    return best_method, best_score, ranked
```

### 2. 文档创建

**流程文档**: `comprehensive_factor/docs/weight_selector_flow.md`
- 包含完整流程图
- 包含各步骤说明
- 包含示例数据

**测试用例文档**: `comprehensive_factor/test_cases/weight_selector_test_cases.md`
- 包含测试场景清单
- 包含边界测试说明
- 包含 pytest 映射

### 3. 测试补充（test_weight_selector.py）

**新增测试类**: `TestBoundaryConditions`
- `test_select_best_method_empty_dict`: 空字典抛 ValueError
- `test_normalize_minmax_single_method`: 单方法归一化
- `test_calculate_weighted_score_zero_weight`: 权重为零

## 执行顺序

```
1. weight_selector.py: 添加空字典检查 + 版本历史 v1.4
2. weight_selector_flow.md: 新建流程文档
3. weight_selector_test_cases.md: 新建测试用例文档
4. test_weight_selector.py: 添加边界测试
5. MODULE.md: 更新版本历史
6. ruff check/format → pytest → git commit
```

## 预期影响

- 代码行数增量: ~10 行
- 新增文档: 2 个
- 新增测试: 3 个
- 版本: v1.3 → v1.4

---
*创建时间: 2026-06-03*