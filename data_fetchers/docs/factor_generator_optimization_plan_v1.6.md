# factor_generator.py 第六轮优化计划

> 版本: v1.6
> 创建时间: 2026-05-25 10:55 北京时间
> 目标: 深度审查优化，解决 JSONDecodeError 内存问题和 CLI 入口规范

---

## 一、当前状态分析

### 文件版本历史

| 版本 | 日期 | 主要变更 |
|------|------|---------|
| v1.0 | 2026-05-24 | 初始版本 |
| v1.1 | 2026-05-25 | logger 参数化 + __all__ 导出 |
| v1.2 | 2026-05-25 | 清理冗余导入/常量 + CLI 参数补全 |
| v1.3 | 2026-05-25 | 常量命名私有化 + 导入顺序 PEP 8 合规化 |
| v1.4 | 2026-05-25 | 流程文档 + 测试用例 + 注释补全 |
| v1.5 | 2026-05-25 | 条件导入合并 + 异常精确化 + metadata 注释 |

### 公共模块规范合规检查

| 检查项 | v1.5 状态 | 说明 |
|-------|---------|------|
| logger 参数化 | ✓ 已有 get_module_logger | 符合规范 |
| __all__ 导出 | ✓ 已定义 | 符合规范 |
| 模块级导入 | ✓ 已在顶部 | 符合规范 |
| 类型注解 | ✓ Optional[...] | 符合规范 |
| docstring Raises | ✓ 已补全 | 符合规范 |
| __main__ 日志 | ✓ 使用 setup_logger | 符合规范 |
| 资源清理 | ✓ finally 清理 | 符合规范 |

---

## 二、深度审查发现的新问题

### 问题清单

| # | 类别 | 问题描述 | 位置 | 参考来源 |
|---|------|---------|------|---------|
| 1 | **内存优化** | JSONDecodeError 持有完整 JSON 文档副本（e.doc），未提取关键信息 | 第172-173行、193-194行 | patterns.md JSONDecodeError 模式 |
| 2 | **CLI 规范** | main() 函数应返回退出码（0/1），而非 metadata | 第359-393行 | 标准CLI规范 |
| 3 | **测试覆盖** | __main__ 测试缺少 valid_records_percent 字段验证 | 第433-435行 | v1.4 新增字段 |
| 4 | **条件导入冗余** | 第348-353行重复 sys.path.insert（第一处已在第38-43行处理） | 第348-353行 | patterns.md 条件导入合并模式 |
| 5 | **日志级别** | main() 使用 setup_logger 而非 get_module_logger 模式 | 第374行 | 可选优化 |

---

## 三、优化任务分解（Bite-sized Tasks）

### Task 1: JSONDecodeError 内存优化

**耗时估计**: 3 分钟

**问题**: 第172-173行和193-194行未提取关键错误信息

**修改策略**: 按 patterns.md JSONDecodeError 模式，提取 lineno、colno、msg

**修改内容**:
```python
# 当前代码（第172-173行）：
except json.JSONDecodeError as e:
    raise ValueError(f"基础因子数据 JSON 解析失败: {factor_data_path}") from e

# 改为：
except json.JSONDecodeError as e:
    logger.error(
        "JSON 解析失败\n"
        "文件路径: %s\n"
        "错误位置: 行 %d, 列 %d\n"
        "错误信息: %s",
        factor_data_path, e.lineno, e.colno, e.msg
    )
    raise ValueError(f"JSON解析失败: {factor_data_path}, 位置 {e.pos}") from e
```

---

### Task 2: CLI 入口返回退出码

**耗时估计**: 2 分钟

**问题**: main() 函数返回 metadata，而非退出码

**修改策略**: 添加 try/except 返回 0/1

**修改内容**:
```python
def main():
    """CLI 主入口"""
    ...
    try:
        metadata = generate_all_factors(...)
        # 成功返回 0
        return 0
    except Exception as e:
        logger.error("执行失败: %s", str(e))
        return 1
    finally:
        # 清理 logger 处理器
        ...
```

---

### Task 3: __main__ 测试补全 valid_records_percent

**耗时估计**: 1 分钟

**问题**: required_fields 缺少 valid_records_percent

**修改内容**:
```python
# 当前代码（第433-435行）：
required_fields = [
    'generated_at', 'elapsed_seconds', 'total_records',
    'valid_records', 'factor_columns', 'input_sources', 'output_path'
]

# 改为：
required_fields = [
    'generated_at', 'elapsed_seconds', 'total_records',
    'valid_records', 'valid_records_percent', 'factor_columns', 
    'input_sources', 'output_path'
]
```

---

### Task 4: 条件导入合并简化（CLI 入口块）

**耗时估计**: 2 分钟

**问题**: 第348-353行重复 sys.path.insert

**修改策略**: 移除 sys.path.insert，只保留 setup_logger 导入

**修改内容**:
```python
# 当前代码（第348-356行）：
if __name__ == '__main__':
    import sys
    from pathlib import Path
    project_root = Path(__file__).parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from data_fetchers.common.logger_config import setup_logger
else:
    from .common.logger_config import setup_logger

# 改为：
if __name__ == '__main__':
    # 注意：sys.path 已在第38-43行处理，直接导入 setup_logger
    from data_fetchers.common.logger_config import setup_logger
else:
    from .common.logger_config import setup_logger
```

---

### Task 5: 版本历史更新

**耗时估计**: 1 分钟

**修改内容**:
```python
- v1.6 (2026-05-25): JSONDecodeError 内存优化（提取错误位置信息）+ CLI 入口返回退出码 + __main__ 测试补全 valid_records_percent + 条件导入合并简化（CLI 入口块）
```

---

## 四、执行顺序

```
Task 1（JSONDecodeError优化）→ Task 2（CLI退出码）→ Task 3（测试补全）→ Task 4（条件导入简化）→ Task 5（版本历史）
```

---

## 五、验证步骤

1. 运行脚本验证 JSON 解析失败时日志输出错误位置
2. 验证 CLI 入口返回退出码
3. 验证 __main__ 测试覆盖 valid_records_percent
4. 检查代码行数变化

---

## 六、Git Commit 信息

```
factor_generator.py v1.6: JSONDecodeError内存优化+CLI退出码+测试补全

- JSONDecodeError 内存优化：提取 lineno/colno/msg 避免内存翻倍
- CLI 入口规范：main() 返回退出码（0成功/1失败）
- __main__ 测试补全：valid_records_percent 字段验证
- 条件导入合并简化：移除 CLI 入口块重复 sys.path.insert
- MODULE.md 版本历史同步更新至 v2.39
```

---

*创建时间: 2026-05-25 10:55 北京时间*