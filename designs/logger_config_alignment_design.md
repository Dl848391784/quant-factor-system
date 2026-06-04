# Design: comprehensive_factor 日志规范修复

> 日期: 2026-06-04
> 状态: 待审核

---

## 问题诊断

**根因**: `comprehensive_factor/common/logger_config.py` 实现与 `factor_ic/common/logger_config.py` 不一致，导致日志只输出到控制台，不写文件。

| 模块 | logger_config.py | 日志行为 | logs/ 目录 |
|------|-----------------|---------|-----------|
| factor_ic | 自动创建目录 + 自动生成文件名 | 默认输出到文件 | 有日志文件 |
| backtest | 同上 | 默认输出到文件 | 有日志文件 |
| comprehensive_factor | 只有传入 log_file 才输出到文件 | 默认只输出到控制台 | **空目录** |

---

## 设计方案

### 修改文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `comprehensive_factor/common/logger_config.py` | 重写 | 对齐 factor_ic 实现，自动文件输出 |
| `comprehensive_factor/MODULE.md` | 补充 | 新增日志配置模块职责规范（M4 扩展） |

### 详细设计

#### 1. logger_config.py 重写

**目标**: 与 `factor_ic/common/logger_config.py` 保持一致

**修改点**:
- 参数签名：`log_file: str = None` → `log_dir: Path | None = None`
- 自动创建日志目录
- 自动生成日志文件名：`{module_name}_{date}.log`
- 默认添加文件 handler
- 添加 `set_log_level()` 函数
- 添加 `LOG_DIR` / `LOG_FORMAT` 常量

**参考实现**: `factor_ic/common/logger_config.py` 第 36-93 行

#### 2. MODULE.md 补充规范

**新增规范**: M4 扩展 — 日志配置模块职责

**规范内容**:
```
**What**: logger_config.py 必须自动创建日志目录并输出到文件，调用方无需传入 log_file 参数。

**Why**: 与 factor_ic/backtest 模块保持一致，确保所有脚本运行时日志持久化。

**How**:
- 调用方只需 `logger = get_logger(__name__)`
- 日志自动输出到 `comprehensive_factor/logs/{module_name}_YYYY-MM-DD.log`

**Don't**:
- 调用方传入 `log_file` 参数（已废弃）
- 使用 print 替代 logger
```

---

## 执行顺序

```
1. 重写 logger_config.py（对齐 factor_ic 实现）
2. 补充 MODULE.md 规范（M4 扩展）
3. 运行脚本验证日志输出
4. git commit
```

---

## 验证检查

```
□ logger_config.py get_logger() 不需要 log_file 参数
□ logger_config.py 自动创建 logs/ 目录
□ 运行 composite_icir_weight_1d.py 后 logs/ 目录有日志文件
□ 日志格式：%(asctime)s | %(levelname)-8s | %(name)s | %(message)s
□ MODULE.md 新增规范引用 factor_ic 对齐原则
```

---

## 预估改动量

- logger_config.py: ~130 行（参考 factor_ic 132 行）
- MODULE.md: ~30 行（新增规范章节）

**总计**: 2 文件，~160 行 ✓ 符合粒度约束（≤3 文件，≤200 行）