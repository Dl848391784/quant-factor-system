# backtest 模块规范

> 本文档定义 backtest/ 目录下分层回测脚本的开发规范。
> 创建时间: 2026-05-19
> 版本: v0.2（补充日志规范）

---

## 概述

backtest 模块负责对因子 IC 结果进行分层回测，评估因子的实际预测能力。

**模块定位：**
- 输入：factor_ic 的 IC 分析结果
- 输出：分层回测统计指标（收益、夏普、最大回撤等）

---

## 脚本命名

**格式：** `layered_backtest_<因子名>.py`

**示例：**
- `layered_backtest_rsi.py` — RSI 因子分层回测
- `layered_backtest_volume_ratio.py` — 量比因子分层回测

---

## 日志规范

**遵循 PROJECT.md 项目级日志规范（第783-857行）。**

核心要点：
- 使用 Python 标准库 `logging` 模块
- 导入方式：`from factor_ic.common.logger_config import get_logger`
- 日志路径：`backtest/logs/*.log`

---

## 公共模块复用

**遵循 PROJECT.md 强制复用规范（MODULE.md 第X-Y行）。**

必须复用的公共模块：
| 功能 | 公共模块路径 | 说明 |
|------|-------------|------|
| 类型转换 | `factor_ic.common.convert_types` | numpy/pandas → Python 原生类型 |
| 日志配置 | `factor_ic.common.logger_config` | get_logger 函数 |
| 分层回测引擎 | `backtest.common.layered_backtest` | LayeredBacktestEngine 类 |

---

## 分层规则

待定义：

- 分层数量（如 5 层、10 层）
- 分层方式（正向因子 vs 反向因子）
- 每层权重分配
- 边界处理规则

---

## 输出格式

待定义：

- 分层收益统计
- 夏普比率
- 最大回撤
- IC 与回测收益的对应关系

---

## 待补充内容

```
□ 分层规则定义
□ 输出字段规范
□ 统计指标计算公式
□ 因子方向处理规则
□ 测试用例规范
```

---

*最后更新: 2026-05-22*