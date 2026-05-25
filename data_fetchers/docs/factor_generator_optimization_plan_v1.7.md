# factor_generator.py 第七轮优化计划

> 版本: v1.7
> 创建时间: 2026-05-25 11:10 北京时间
> 目标: 深度审查优化，解决注释不一致和类型注解缺失

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
| v1.6 | 2026-05-25 | JSONDecodeError 内存优化 + CLI 退出码 + 测试补全 |

### 公共模块规范合规检查

| 检查项 | v1.6 状态 | 说明 |
|-------|---------|------|
| logger 参数化 | ✓ 已有 get_module_logger | 符合规范 |
| __all__ 导出 | ✓ 已定义 | 符合规范 |
| 模块级导入 | ✓ 已在顶部 | 符合规范 |
| 类型注解 | ✓ Optional[...] | 符合规范 |
| docstring Raises | ⚠ 缺少 RuntimeError | 需补全 |
| __main__ 日志 | ✓ 使用 setup_logger | 符合规范 |
| 资源清理 | ✓ finally 清理 | 符合规范 |

---

## 二、深度审查发现的新问题

### 问题清单

| # | 类别 | 问题描述 | 位置 | 优先级 |
|---|------|---------|------|--------|
| 1 | **注释不一致** | 第417行注释说"setup_logger 已在第333-341行条件导入"，实际位置在第364-367行 | 第417行 | 高 |
| 2 | **docstring Raises 缺失** | generate_all_factors 的 Raises 缺少 RuntimeError（第297-306行会抛出） | 第133-137行 | 高 |
| 3 | **类型注解缺失** | main() 函数缺少返回类型注解 `-> int` | 第370行 | 中 |

---

## 三、优化任务分解（Bite-sized Tasks）

### Task 1: 修正注释行号

**耗时估计**: 1 分钟

**问题**: 第417行注释行号错误

**修改内容**:
```python
# 当前代码（第417行）：
# 注意：setup_logger 已在第333-341行条件导入，sys.path 已处理

# 改为：
# 注意：setup_logger 已在第364-367行条件导入，sys.path 已处理
```

---

### Task 2: 补全 docstring RuntimeError

**耗时估计**: 1 分钟

**问题**: generate_all_factors 的 Raises 缺少 RuntimeError

**修改内容**:
```python
# 当前代码（第133-137行）：
Raises:
    FileNotFoundError: 输入数据文件不存在
    json.JSONDecodeError: JSON 解析失败
    ValueError: 数据格式不正确（缺少 'data' 字段）
    KeyError: 必需字段不存在

# 改为：
Raises:
    FileNotFoundError: 输入数据文件不存在
    json.JSONDecodeError: JSON 解析失败
    ValueError: 数据格式不正确（缺少 'data' 字段）或 JSON 解析失败位置信息
    KeyError: 必需字段不存在
    RuntimeError: 文件系统错误（磁盘/权限/IO）或未知保存错误
```

---

### Task 3: 添加 main() 返回类型注解

**耗时估计**: 1 分钟

**问题**: main() 函数缺少返回类型注解

**修改内容**:
```python
# 当前代码（第370行）：
def main():
    """CLI 主入口"""

# 改为：
def main() -> int:
    """CLI 主入口"""
```

---

### Task 4: 版本历史更新

**耗时估计**: 1 分钟

**修改内容**:
```python
- v1.7 (2026-05-25): 注释行号修正（setup_logger 导入位置）+ docstring RuntimeError 补全 + main() 返回类型注解
```

---

## 四、执行顺序

```
Task 1（注释修正）→ Task 2（docstring补全）→ Task 3（类型注解）→ Task 4（版本历史）
```

---

## 五、验证步骤

1. grep 验证注释行号正确
2. 验证 docstring Raises 包含 RuntimeError
3. 验证 main() 有返回类型注解

---

## 六、Git Commit 信息

```
factor_generator.py v1.7: 注释修正+docstring补全+类型注解

- 注释行号修正：setup_logger 导入位置改为第364-367行
- docstring RuntimeError 补全：文件系统错误异常说明
- main() 返回类型注解：添加 -> int
- MODULE.md 版本历史同步更新至 v2.40
```

---

*创建时间: 2026-05-25 11:10 北京时间*