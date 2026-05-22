# backtest 模块规范

> 本文档定义 backtest/ 目录下分层回测脚本的开发规范。
> 创建时间: 2026-05-19
> 版本: v0.3（补充分层规则、换手率计算、参数校验规范）
> 修订日期: 2026-05-22

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

**分层数量：**
- percentile 模式：由 n_layers 参数控制（默认 5 层）
- fixed_threshold 模式：由 thresholds 长度决定（n 层 = len(thresholds) - 1）

**分层方式：**
- 正向因子（factor_direction='positive'）：高值预期高收益，多头取高层
- 反向因子（factor_direction='negative'）：低值预期高收益，多头取低层

**多空层默认设置（依赖已修正的 n_layers）：**
- 正向因子：多头 Layer(n-1, n)，空头 Layer(1, 2)
- 反向因子：多头 Layer(1, 2)，空头 Layer(n-1, n)

**边界处理规则（fixed_threshold 模式）：**
- 最大边界（≥ thresholds[-1]）：归入 Layer n
- 最小边界（< thresholds[0]）：归入 Layer 1，并输出警告日志
  - 警告内容：股票数量、占比、建议检查 thresholds 或改用 percentile
- 边界内（[thresholds[i], thresholds[i+1])）：归入 Layer (i+1)
- **业务建议：thresholds 应覆盖数据范围，避免边界外数据**

**每层权重分配：**
- 等权平均（每只股票权重相等）

---

## 多空组合换手率计算规则

**计算逻辑：先按日期分组取均值，再整体平均**

正确做法（已实现）：
```
每日多头换手率 = mean(多头各层换手率)  # 若有2层，先取均值
avg_turnover_long = mean(每日多头换手率)  # 每日权重相等
```

错误做法（已修复）：
```
avg_turnover_long = mean(所有多头层所有日期换手率列表)  # 多头多层重复计次
```

**原因：** 若某天多头有 2 层（如 Layer4 + Layer5），直接取列表会导致该天换手率被计 2 次，权重不对。

---

## 参数校验规范

**必须校验：**
- factor_direction：'positive' / 'negative'
- layer_method：'percentile' / 'fixed_threshold'
- thresholds（fixed_threshold 模式）：至少 2 个阈值点，严格递增
- long_layers / short_layers：层编号不越界（在 [1, n_layers] 范围内）

---

## 阈值描述规范

**LAYER_THRESHOLD_DESC 格式：** 完整区间 `[lower, upper)`，必须包含下界。

**示例：**
```python
LAYER_THRESHOLD_DESC = {
    1: '0 ≤ RSI < 20 (超卖)',   # 完整区间，含下界
    2: '20 ≤ RSI < 40 (含边界20)',
    5: 'RSI ≥ 80 (含边界80)'    # 最大边界使用 ≥
}
```

**原因：**
- 引擎 fixed_threshold 模式执行 `[thresholds[i], thresholds[i+1])` 归入 Layer (i+1)
- 描述必须与引擎一致，避免误导
- RSI 理论范围 [0, 100]，实际数据可能因计算误差越界，需校验

---

## 路径构造规范

**必须使用 `pathlib.Path`，语义清晰、不依赖文件层级假设。**

**正确写法：**
```python
from pathlib import Path
project_root = Path(__file__).parent.parent  # 项目根目录
cache_dir = project_root / 'cache' / 'factor_data'
```

**错误写法：**
```python
os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 两次 dirname，语义不清晰
```

**原因：**
- 两次 `dirname` 意味着祖父目录，但语义不直观
- 若脚本被移动或从其他目录调用，路径会静默失效
- `Path` 的 `/` 操作符更清晰表达层级关系

---

## 参数显式传入规范

**fixed_threshold 模式必须显式传入 `n_layers`。**

**正确写法：**
```python
n_layers = len(config.LAYER_THRESHOLDS) - 1  # fixed_threshold 模式
result = engine.run(
    layer_method='fixed_threshold',
    thresholds=config.LAYER_THRESHOLDS,
    n_layers=n_layers,  # 显式传入
    ...
)
```

**错误写法：**
```python
result = engine.run(
    layer_method='fixed_threshold',
    thresholds=config.LAYER_THRESHOLDS,
    # n_layers 未传入，依赖引擎内部覆盖
)
```

**原因：**
- 引擎内部会覆盖 `n_layers = len(thresholds) - 1`
- 若将来 `run` 默认值改变或 thresholds 变长，隐式依赖会静默出错
- 显式传入避免歧义，代码意图清晰

---

## 因子数据校验规范

**回测脚本必须校验因子数据范围，避免越界值。**

**校验逻辑：**
```python
factor_min = factor_df[factor_col].min()
factor_max = factor_df[factor_col].max()
logger.info("因子范围: %.2f ~ %.2f", factor_min, factor_max)

# 越界警告（如 RSI 理论范围 [0, 100]）
if factor_min < thresholds[0] or factor_max > thresholds[-1]:
    logger.warning(
        "因子值超出 thresholds 范围，建议检查因子计算或调整 thresholds"
    )
```

---

## 输出格式

待定义：

- 分层收益统计
- 夏普比率
- 最大回撤
- IC 与回测收益的对应关系

---

*最后更新: 2026-05-23*