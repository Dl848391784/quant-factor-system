# factor_generator.py 第八轮优化计划

> 版本: v1.8
> 创建时间: 2026-05-25 11:20 北京时间
> 目标: 深度审查优化，解决 gzip.BadGzipFile 异常处理缺失

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
| v1.7 | 2026-05-25 | 注释修正 + docstring RuntimeError + 类型注解 |

### 公共模块规范合规检查

| 检查项 | v1.7 状态 | 说明 |
|-------|---------|------|
| logger 参数化 | ✓ 已有 get_module_logger | 符合规范 |
| __all__ 导出 | ✓ 已定义 | 符合规范 |
| 模块级导入 | ✓ 已在顶部 | 符合规范 |
| 类型注解 | ✓ Optional[...] + main() -> int | 符合规范 |
| docstring Raises | ✓ 已补全 RuntimeError | 符合规范 |
| __main__ 日志 | ✓ 使用 setup_logger | 符合规范 |
| 资源清理 | ✓ finally 清理 | 符合规范 |

---

## 二、深度审查发现的新问题

### 问题清单

| # | 类别 | 问题描述 | 位置 | 优先级 |
|---|------|---------|------|--------|
| 1 | **异常处理不完整** | gzip.open 没有处理 gzip.BadGzipFile 异常（gzip 文件损坏） | 第170-184行、199-213行 | 高 |
| 2 | **注释行号不准确** | 第365行注释说"sys.path 已在第38-43行处理"，实际是第38-45行 | 第365行 | 中 |

---

## 三、优化任务分解（Bite-sized Tasks）

### Task 1: 添加 BadGzipFile 异常处理

**耗时估计**: 3 分钟

**问题**: gzip.open 读取时没有处理文件损坏情况

**修改策略**: 在模块顶部导入 BadGzipFile，然后在 try-except 块中添加处理

**修改内容**:
```python
# 模块顶部导入（第24行后）：
import gzip
BadGzipFile = gzip.BadGzipFile

# try-except 块修改（第170-184行）：
try:
    with gzip.open(factor_data_path, 'rt') as f:
        base_data = json.load(f)
except FileNotFoundError:
    raise FileNotFoundError(f"基础因子数据文件不存在: {factor_data_path}")
except BadGzipFile as e:
    raise ValueError(f"gzip 文件损坏: {factor_data_path}") from e
except json.JSONDecodeError as e:
    ...
```

---

### Task 2: 修正注释行号

**耗时估计**: 1 分钟

**问题**: 第365行注释行号不准确

**修改内容**:
```python
# 当前代码（第365行）：
# 注意：sys.path 已在第38-43行（因子计算函数导入块）处理

# 改为：
# 注意：sys.path 已在第38-45行（因子计算函数导入块）处理
```

---

### Task 3: 版本历史更新

**耗时估计**: 1 分钟

**修改内容**:
```python
- v1.8 (2026-05-25): gzip.BadGzipFile 异常处理补全（gzip 文件损坏）+ 注释行号修正（sys.path.insert 位置）
```

---

## 四、执行顺序

```
Task 1（BadGzipFile 处理）→ Task 2（注释修正）→ Task 3（版本历史）
```

---

## 五、验证步骤

1. grep 验证 BadGzipFile 导入
2. 验证 try-except 块包含 BadGzipFile 处理
3. 验证注释行号正确

---

## 六、Git Commit 信息

```
factor_generator.py v1.8: BadGzipFile异常处理+注释修正

- gzip.BadGzipFile 异常处理：gzip 文件损坏错误处理
- 注释行号修正：sys.path.insert 位置改为第38-45行
- MODULE.md 版本历史同步更新至 v2.41
```

---

*创建时间: 2026-05-25 11:20 北京时间*