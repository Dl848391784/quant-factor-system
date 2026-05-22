# backtest 模块规范

> 本文档定义 backtest/ 目录下分层回测脚本的开发规范。
> 创建时间: 2026-05-19
> 版本: v0.5（补充单层模式、NaN安全转换、percentile类型一致性、避免闭包捕获规范）
> 修订日期: 2026-05-23

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

**第5层（最大边界）特殊处理：** 使用 `≥` 并说明上界处理逻辑。

**示例：**
```python
layer_threshold_desc: TypingDict[str, str] = field(default_factory=lambda: {
    '1': '0 ≤ RSI < 20 (超卖)',   # 完整区间，含下界
    '2': '20 ≤ RSI < 40 (含边界20)',
    '5': 'RSI ≥ 80 (含边界80，含越界值)'  # 最大边界使用 ≥，说明越界值处理
})
```

**原因：**
- 引擎 fixed_threshold 模式执行 `[thresholds[i], thresholds[i+1])` 归入 Layer (i+1)
- 最大边界（`≥ thresholds[-1]`）归入 Layer n，包括越界值（如 RSI >= 100）
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

## Config 类规范

**必须使用 `@dataclass`，提供类型约束和不可变性保护。**

**正确写法：**
```python
from dataclasses import dataclass, field
from typing import List, Dict as TypingDict

@dataclass
class RSILayerConfig:
    """RSI分层配置"""
    layer_thresholds: List[float] = field(default_factory=lambda: [0, 20, 40, 60, 80, 100])
    layer_names: TypingDict[str, str] = field(default_factory=lambda: {'1': '超卖层', ...})
    factor_direction: str = 'negative'
    
    # 允许类属性访问（兼容旧代码）
    @property
    def LAYER_THRESHOLDS(self) -> List[float]:
        return self.layer_thresholds
```

**错误写法：**
```python
class RSILayerConfig:
    """RSI分层配置"""
    LAYER_THRESHOLDS = [0, 20, 40, 60, 80, 100]  # 类属性，可被实例覆盖
    LAYER_NAMES = {1: '超卖层', ...}  # int key，JSON 序列化后转为 str
```

**原因：**
- 类属性可被实例意外覆盖（`config.FACTOR_DIRECTION = 'positive'`）
- dataclass 提供类型约束，IDE 可检查类型错误
- property 提供不可变性保护，兼容旧代码的类属性访问风格

---

## 字典 key 类型规范

**layer_names / layer_threshold_desc 必须使用 `str key`，避免 JSON 序列化后 int→str 转换问题。**

**正确写法：**
```python
layer_names: TypingDict[str, str] = field(default_factory=lambda: {
    '1': '超卖层',  # str key
    '2': '弱势层',
    '5': '超买层'
})
```

**错误写法：**
```python
LAYER_NAMES = {
    1: '超卖层',  # int key，JSON dump 后变为 {'1': '超卖层'}
    2: '弱势层',
    5: '超买层'
}
# 下游使用 layer_names.get(1) 返回 None（key 已变为 '1'）
```

**原因：**
- JSON 序列化会将 int key 转为 str key
- 加载后 `layer_names.get(1)` 返回 None（因为 key 已变为 `'1'`）
- 使用 str key 保持一致性，下游访问 `layer_names.get('1')` 返回正确值

---

## 数据完整性校验规范

**load_data_from_cache 必须校验 JSON 结构完整性。**

**校验逻辑：**
```python
# 1. 校验文件存在
if not factor_path.exists():
    raise FileNotFoundError(f"缓存文件不存在: {factor_path}")

# 2. 校验 JSON 解析
try:
    with gzip.open(factor_path, 'rt', encoding='utf-8') as f:
        factor_data = json.load(f)
except json.JSONDecodeError as e:
    raise json.JSONDecodeError(f"JSON 解析失败: {factor_path}, 错误: {e.msg}", e.doc, e.pos)

# 3. 校验结构完整性
if 'data' not in factor_data:
    raise KeyError(
        f"JSON 结构缺失 'data' 字段: {factor_path}, "
        f"顶层字段: {list(factor_data.keys())}"
    )
```

**原因：**
- JSON 文件损坏或格式变更时，抛 KeyError 错误信息不友好
- 校验文件存在、JSON 解析、结构完整性，提供清晰的错误信息
- 错误信息包含文件路径、缺失字段、实际顶层字段

---

## 命令行入口规范

**main 函数必须捕获异常并返回正确退出码。**

**退出码定义：**
- 0：成功
- 1：回测无有效数据（n_days_total = 0）
- 2：数据文件不存在（FileNotFoundError）
- 3：数据结构错误（KeyError）
- 4：参数错误（ValueError）
- 5：其他异常

**正确写法：**
```python
def main():
    """命令行入口"""
    import argparse
    import sys
    
    parser = argparse.ArgumentParser(...)
    args = parser.parse_args()
    
    try:
        result = run_rsi_layered_backtest(...)
        
        if result['meta']['n_days_total'] == 0:
            logger.error("回测无有效数据，退出码 1")
            sys.exit(1)
        
        logger.info("回测完成，退出码 0")
        sys.exit(0)
        
    except FileNotFoundError as e:
        logger.error("数据文件不存在: %s", e)
        sys.exit(2)
    except KeyError as e:
        logger.error("数据结构错误: %s", e)
        sys.exit(3)
    except ValueError as e:
        logger.error("参数错误: %s", e)
        sys.exit(4)
    except Exception as e:
        logger.exception("回测执行异常: %s", e)
        sys.exit(5)
```

**原因：**
- 命令行入口应返回退出码，方便 CI/CD 判断执行结果
- 不同退出码对应不同错误类型，便于排查

---

## 单层模式处理规范

**引擎必须处理 n_layers=1 的特殊情况，避免默认多空层越界。**

**正确处理：**
```python
if long_layers is None:
    if n_layers == 1:
        # 单层模式：多头和空头都取唯一的层
        long_layers = [1]
    else:
        long_layers = [n_layers - 1, n_layers] if factor_direction == 'positive' else [1, 2]
```

**错误处理：**
```python
# n_layers=1 时，正向因子 long_layers = [0, 1]
# layer_id=0 触发 < 1 校验，抛出 ValueError（归咎于用户）
long_layers = [n_layers - 1, n_layers] if factor_direction == 'positive' else [1, 2]
```

**原因：**
- n_layers=1 时，`[n_layers - 1, n_layers] = [0, 1]`
- layer_id=0 越界（有效范围 [1, n_layers]），但错误信息归咎于用户
- 单层模式多空组合无意义，应显式处理避免误导

---

## NaN 安全转换规范

**JSON 序列化前必须将 NaN 替换为 None，避免 `json.dumps` 抛 ValueError。**

**正确写法：**
```python
def safe_float(val):
    """NaN → None，避免 json.dumps 抛 ValueError"""
    return None if pd.isna(val) else float(val)

long_short_stats = {
    'long_return_daily': safe_float(long_short_df['long_return'].mean()),
    ...
}
```

**错误写法：**
```python
long_short_stats = {
    'long_return_daily': float(long_short_df['long_return'].mean()),  # NaN 会抛 ValueError
    ...
}
```

**原因：**
- `float(np.nan)` 产生 `nan`，JSON 不支持 NaN
- `json.dumps({'val': nan})` 抛 `ValueError: Out of range float values are not JSON compliant`
- 使用 `pd.isna()` 检测 NaN，替换为 None（JSON 支持 `null`）

---

## percentile 类型一致性规范

**百分位分层前必须将 factor_values 转为 float64，避免 float32 类型不一致。**

**正确写法：**
```python
# 先转 float64，避免 float32 类型不一致（factor_values 可能被转为 float32）
factor_values_f64 = factor_values.astype('float64')
ranks = factor_values_f64.rank(pct=True)
layer_assignment = np.ceil(ranks * n_layers).astype(int)
```

**错误写法：**
```python
ranks = factor_values.rank(pct=True)  # float32 可能导致类型不一致
layer_assignment = np.ceil(ranks * n_layers).astype(int)
```

**原因：**
- 内存优化时 `factor_values` 可能被转为 `float32`
- `rank(pct=True)` 后与 `n_layers` 计算，类型不一致可能导致精度问题
- 显式转 `float64` 确保 rank 计算精度

---

## 避免闭包捕获规范

**groupby 内部函数必须使用静态方法或独立函数，显式传参避免闭包捕获外部变量。**

**正确写法：**
```python
@staticmethod
def _calc_daily_ls(group: pd.DataFrame, long_layers: List[int], short_layers: List[int]) -> pd.Series:
    """计算每日多空收益和换手率（静态方法，显式传参）"""
    long_rets = group[group['layer'].isin(long_layers)]['return'].dropna()
    ...

# 调用
long_short_df = daily_df.groupby('date').apply(
    lambda group: self._calc_daily_ls(group, long_layers, short_layers)
)
```

**错误写法：**
```python
# 闭包捕获 long_layers/short_layers
def calc_daily_ls(group):
    long_rets = group[group['layer'].isin(long_layers)]['return'].dropna()  # 捕获外部变量
    ...

long_short_df = daily_df.groupby('date').apply(calc_daily_ls)
```

**原因：**
- 闭包捕获外部变量（long_layers/short_layers），存在可维护性风险
- 若外部变量被修改，闭包行为不可预期
- 静态方法显式传参，代码意图清晰，便于测试和复用

---

## 输出格式

待定义：

- 分层收益统计
- 夏普比率
- 最大回撤
- IC 与回测收益的对应关系

---

*最后更新: 2026-05-23*