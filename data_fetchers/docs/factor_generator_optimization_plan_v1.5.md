# factor_generator.py 第五轮优化计划

> 版本: v1.5
> 创建时间: 2026-05-25 10:35 北京时间
> 目标: 深度审查优化，解决条件导入冗余和代码结构问题

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

### 公共模块规范合规检查

| 检查项 | v1.4 状态 | 说明 |
|-------|---------|------|
| logger 参数化 | ✓ 已有 get_module_logger | 符合规范 |
| __all__ 导出 | ✓ 已定义 | 符合规范 |
| 模块级导入 | ✓ 已在顶部 | 符合规范 |
| 类型注解 | ✓ Optional[...] | 符合规范 |
| docstring Raises | ✓ 已补全 | 符合规范 |
| __main__ 日志 | ✓ 使用 setup_logger | 符合规范 |
| 资源清理 | ✓ finally 清理 | 符合规范 |

---

## 二、深度审查发现的问题

### 问题清单

| # | 类别 | 问题描述 | 位置 | 参考来源 |
|---|------|---------|------|---------|
| 1 | **代码冗余** | 条件导入重复：第37-49行 + 第333-341行 + 第385-393行 共3处 sys.path.insert | 第37-49行、333-341行、385-393行 | PEP 8 |
| 2 | **代码结构** | __main__ 测试部分重复导入 logger_config（第395行 vs 第339行） | 第395行 | - |
| 3 | **代码结构** | CLI 入口（第344-378行）和 __main__ 测试（第385-457行）分离，可合并 | 第344-457行 | - |
| 4 | **异常处理** | 第279-283行 Exception 捕获过于宽泛，未区分具体错误类型 | 第279-283行 | patterns.md |
| 5 | **规范遗漏** | metadata 返回值缺少字段注释（valid_records_percent 含义） | 第294-314行 | MODULE.md |
| 6 | **命名一致性** | _DEFAULT_CACHE_DIR 私有化，但 logger_config 导入未私有化 | - | - |

---

## 三、优化任务分解（Bite-sized Tasks）

### Task 1: 条件导入合并简化

**耗时估计**: 3 分钟

**问题**: 三处 sys.path.insert 重复

**修改策略**:
- 保留第37-49行的因子计算函数导入（必要）
- 保留第333-341行的 CLI 入口导入（必要）
- **移除第385-393行的 __main__ 测试重复导入**（改为使用已导入的 setup_logger）

**修改内容**:
```python
# 第385-393行改为：
if __name__ == '__main__':
    # 使用已导入的 setup_logger（第339行已导入）
    test_logger = setup_logger('data_fetchers.factor_generator', level=logging.INFO)
```

---

### Task 2: __main__ 测试结构简化

**耗时估计**: 3 分钟

**问题**: 第395行重复导入 logger_config

**修改内容**:
```python
# 第395行删除（已在第339行导入）
# from data_fetchers.common.logger_config import setup_logger  # 删除此行
```

---

### Task 3: 异常处理精确化

**耗时估计**: 2 分钟

**问题**: 第279-283行 Exception 捕获过于宽泛

**修改内容**:
```python
# 当前代码：
except Exception as e:
    # 失败时清理临时文件
    if temp_path.exists():
        temp_path.unlink()
    raise RuntimeError(f"保存输出文件失败: {output_path}") from e

# 改为精确化：
except (OSError, PermissionError, IOError) as e:
    # 失败时清理临时文件
    if temp_path.exists():
        temp_path.unlink()
    raise RuntimeError(f"保存输出文件失败: {output_path}") from e
except Exception as e:
    # 未知错误
    if temp_path.exists():
        temp_path.unlink()
    raise RuntimeError(f"未知错误保存失败: {output_path}") from e
```

---

### Task 4: metadata 字段注释补全

**耗时估计**: 2 分钟

**问题**: valid_records_percent 缺少注释说明

**修改内容**:
```python
# 在第303-307行上方添加注释：
# valid_records_percent: 有效记录百分比（与日志输出一致，便于质量评估）
'valid_records_percent': {
    'bollinger_pb': round(bollinger_valid / total_records * 100, 2),
    ...
},
```

---

### Task 5: 版本历史更新

**耗时估计**: 1 分钟

**修改内容**:
```python
- v1.5 (2026-05-25): 条件导入合并简化 + 异常处理精确化 + metadata 字段注释补全
```

---

## 四、执行顺序

```
Task 1（条件导入合并）→ Task 2（__main__简化）→ Task 3（异常精确化）→ Task 4（注释补全）→ Task 5（版本历史）
```

---

## 五、验证步骤

1. 运行脚本验证输出结构
2. 验证导入正常工作
3. 检查代码行数变化（预期减少 ~10 行）

---

## 六、Git Commit 信息

```
factor_generator.py v1.5: 条件导入合并+异常精确化+注释补全

- 合并条件导入：移除 __main__ 测试重复 sys.path.insert
- 异常处理精确化：区分 OSError/PermissionError/IOError
- metadata 字段注释补全：valid_records_percent 含义说明
- MODULE.md 版本历史同步更新至 v2.38
```

---

*创建时间: 2026-05-25 10:35 北京时间*