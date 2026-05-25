# fetch_stock_list.py 优化计划 v1.0

> 创建时间: 2026-05-27 06:00 北京时间
> 预计执行: 6轮迭代

---

## 问题清单

### Round 1: 输出目录迁移 + 流程文档创建

**问题**: 输出到 cache 目录（违反 MODULE.md 约束 2）

**修复**:
1. 将 `CACHE_FILE` 从 `cache/stock_list.json` 改为 `result/stock_list_meta.json`
2. 创建流程文档 `docs/fetch_stock_list_flow.md`

### Round 2: 日志规范化

**问题**: 日志文件命名和格式不规范

**修复**:
1. 日志文件命名改为 `fetch_stock_list_YYYY-MM-DD.log`
2. 日志格式改为 `%(asctime)s | %(levelname)-8s | %(name)s | %(message)s`
3. 复用 common/logger_config.py 的 `setup_logger`

### Round 3: CLI 日志规范化

**问题**: __main__ 使用 print（违反 PROJECT.md 第780-839行）

**修复**:
1. 替换所有 print 为 logger.info
2. 使用 try/finally 结构

### Round 4: 类型注解 + __all__

**问题**: 类型注解不完整、缺少 __all__

**修复**:
1. 补充所有公共函数类型注解
2. 添加 __all__ 导出列表

### Round 5: 版本号常量 + datetime 统一

**问题**: 版本号硬编码、datetime.now() 多次调用

**修复**:
1. 提取 `_OUTPUT_VERSION = '2.2'` 常量
2. datetime.now() 只调用一次，派生两个格式

### Round 6: Path 对象迁移 + 公共模块复用

**问题**: 使用 os.path、未复用公共模块

**修复**:
1. os.path → Path 对象
2. 复用 http_client.py 的 `create_sina_session`
3. 复用 cache_manager.py 的写入函数

---

## 执行检查清单

```
□ Round 1: 输出目录 + 流程文档
□ Round 2: 日志规范化
□ Round 3: CLI 日志规范化
□ Round 4: 类型注解 + __all__
□ Round 5: 版本号常量 + datetime 统一
□ Round 6: Path 对象 + 公共模块复用
□ 创建测试用例文档
□ Git commit
```