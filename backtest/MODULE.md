# backtest 模块规范

> 本文档定义 backtest/ 目录下分层回测脚本的开发规范。
> 创建时间: 2026-05-19
> 版本: v1.3（新增因子列校验规范、JSONDecodeError 内存问题规范）
> 修订日期: 2026-05-23

---

## 概述

backtest 模块负责对因子 IC 结果进行分层回测，评估因子的实际预测能力。

**模块定位：**
- 输入：factor_ic 的 IC 分析结果
- 输出：分层回测统计指标（收益、夏普、最大回撤等）

---

## 脚本命名

**格式：** `layered_backtest_<因子名>_<收益周期>.py`（仿照 factor_ic 命名规则）

**示例：**
- `layered_backtest_rsi_1d.py` — RSI 因子 1日收益分层回测
- `layered_backtest_volume_ratio_1d.py` — 量比因子 1日收益分层回测

**命名规则来源：** 与 factor_ic 模块命名规则保持一致（`ic_<因子名>_<收益周期>.py`）

---

## 日志规范

**遵循 PROJECT.md 项目级日志规范。**

核心要点：
- 使用 Python 标准库 `logging` 模块
- 导入方式：`from backtest.common.logger_config import get_logger`
- 日志路径：`backtest/logs/*.log`

---

## 公共模块复用（强制）

**遵循 PROJECT.md 模块边界规范：只复用 backtest/common/ 下的模块。**

### 核心原则

**能用公共模块的一定复用，不要自己再实现。**

```
✓ 必须复用 backtest/common/ 下的模块
✗ 禁止手写数据加载、结果保存、CLI 入口逻辑
✗ 禁止跨模块复用 factor_ic/common/
```

### 必须复用的公共模块

| 功能 | 公共模块路径 | 说明 |
|------|-------------|------|
| 类型转换 | `backtest.common.convert_types` | numpy/pandas → Python 原生类型 |
| 日志配置 | `backtest.common.logger_config` | get_logger 函数 |
| 分层回测引擎 | `backtest.common.layered_backtest` | LayeredBacktestEngine 类 |
| 分层回测入口 | `backtest.common.layered_backtest_runner` | run_layered_backtest 公共入口 |
| 数据路径 | `backtest.common.data_loader` | DEFAULT_CACHE_DIR |

### 禁止手写的逻辑

| 逻辑 | 正确方式 | 错误方式 |
|------|---------|---------|
| 数据加载 | `run_layered_backtest()` 自动加载 | 手写 gzip.open + json.load |
| 结果保存 | `run_layered_backtest()` 自动保存 | 手写 json.dump |
| CLI 入口 | `create_cli_entrypoint()` | 手写 argparse + 异常处理 |
| Config 基类 | 继承 `LayerConfigBase` | 手写 property 方法 |
| 分层回测 | 调用 `LayeredBacktestEngine` | 手写分层逻辑 |

---

## 新因子开发规范（使用公共入口）

**强制要求：新因子分层回测脚本必须使用公共入口 `run_layered_backtest`。**

### 开发步骤

1. **定义 Config 类**（继承 `LayerConfigBase`）
```python
from backtest.common.layered_backtest_runner import LayerConfigBase

@dataclass
class MyFactorLayerConfig(LayerConfigBase):
    # 只需定义因子特有参数
    layer_thresholds: List[float] = field(default_factory=lambda: [0, 0.5, 1.0, 1.5, 2.0, 5.0])
    factor_direction: str = 'negative'
    long_layers: List[int] = field(default_factory=lambda: [1, 2])
    short_layers: List[int] = field(default_factory=lambda: [4, 5])
    # ... 其他因子特有参数
```

2. **调用公共入口**
```python
from backtest.common.layered_backtest_runner import run_layered_backtest

result = run_layered_backtest(
    factor_name='my_factor',
    factor_col='my_factor_value',
    config=MyFactorLayerConfig(),
    # 可选参数：
    factor_calculator=my_calculate_func,  # 若因子需实时计算
    additional_data_files={'turnover_rate': str(Path(args.cache_dir) / 'turnover_rate_data.json.gz')},  # 动态构建路径
    logger=logger
)
```

3. **CLI 入口**（使用工厂函数）
```python
from backtest.common.layered_backtest_runner import create_cli_entrypoint

main = create_cli_entrypoint(
    factor_name='my_factor',
    factor_col='my_factor_value',
    config_class=MyFactorLayerConfig
)

if __name__ == '__main__':
    main()
```

### 代码量对比

| 方式 | 行数 | 适用场景 |
|------|------|---------|
| 旧方式（手写全部逻辑） | ~350-500 | 不推荐 |
| 新方式（使用公共入口） | **~60-180** | 强制使用 |

### 示例脚本

| 因子类型 | 示例文件 | 特点 |
|---------|---------|------|
| 简单因子（数据已在缓存） | `layered_backtest_volume_ratio_1d.py` | 66 行，无需额外数据和计算 |
| 复杂因子（需额外数据） | `layered_backtest_turnover_surge_1d.py` | 136 行，需加载换手率数据 + 因子计算 |
| 复杂因子（需因子计算） | `layered_backtest_kdj_j_1d.py` | 163 行，需计算 KDJ_J |

**分层数说明：**
- `n_layers = len(layer_thresholds) - 1`
- 示例：`[0, 0.5, 1.0, 1.5, 2.0, 5.0]` → 5 层
- 示例：`[0, 30, 50, 70, 100]` → 4 层（RSI）

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

## 统计指标计算规范

**夏普比率（简化版）：**
- 公式：`sharpe = annual_return / annual_volatility`
- 说明：简化夏普（rf=0），未扣除无风险收益率
- 适用场景：内部因子对比（相对排序），不用于绝对收益评估
- 若需标准夏普，应改为 `(annual_return - risk_free_rate) / annual_volatility`

**最大回撤（除零保护）：**
- 公式：`drawdown = (cum_series - rolling_max) / rolling_max`
- 保护：若 `rolling_max == 0`（净值归零），drawdown 设为 0
- 原因：除零会产生 inf 或 NaN，破坏后续统计

**数据类型规范：**
- 因子列：`float32`（仅用于排序，精度要求低）
- 收益列：`float64`（用于累计收益 `(1+r).cumprod()`，长时间序列误差累积）
- 原因：float32 精度约7位有效数字，连乘累积收益误差会放大

**字典取值规范（防 None 运算）：**
- 错误写法：`val = dict.get('key', 0)` — 键存在但值为 None 时返回 None
- 错误写法：`val = dict.get('key') or 0` — 合法的 0.0 或负数会被替换为 0
- 正确写法：`val = _coalesce(dict.get('key'))` — 使用辅助函数，只替换 None/NaN
- 原因：`None * 100` 会抛 TypeError，但 `0.0` 和负数是合法值不应替换

**安全取值辅助函数（必须使用）：**
- 模块级辅助函数：`_coalesce(val, default=0.0)`
- 用法：`long_daily = _coalesce(ls_stats.get('long_return_daily'))`
- 原因：避免每个字段写两行代码，约 20 次重复

---

## 多空组合计算规范

**groupby.apply 多级索引风险：**
- pandas ≥ 2.2 下，`groupby.apply` 当 `group_keys=False` 时可能产生多级索引
- `reset_index()` 后 date 列不会出现，而是变成整数索引
- **正确做法：用显式循环 + concat 替代 groupby.apply**
- 原因：跨版本行为一致，避免多级索引陷阱

**正确写法：**
```python
daily_ls_list = []
for date_val in daily_df['date'].unique():
    group = daily_df[daily_df['date'] == date_val]
    ls_series = _calc_daily_ls(group, long_layers, short_layers)
    if pd.notna(ls_series.get('long_short_return')):
        ls_series['date'] = date_val
        daily_ls_list.append(ls_series)
long_short_df = pd.DataFrame(daily_ls_list)
```

**错误写法：**
```python
long_short_df = daily_df.groupby('date', group_keys=False).apply(
    lambda group: _calc_daily_ls(group, long_layers, short_layers)
)
long_short_df = long_short_df.reset_index()  # date 列可能消失
```

---

## fixed_threshold 分层规范

**统一循环写法（避免空循环）：**
- `range(len(thresholds) - 2)` 在双阈值时产生空循环（range(0)）
- **正确做法：统一循环处理所有层，最后一层用条件判断**
- 原因：语义清晰，避免空循环陷阱

**正确写法：**
```python
for i in range(len(thresholds) - 1):  # 统一循环
    lower = thresholds[i]
    upper = thresholds[i + 1]
    if i == n_layers - 1:  # 最后一层：右闭区间
        mask = (factor_values >= lower) & (factor_values <= upper)
    else:  # 前n-1层：右开区间
        mask = (factor_values >= lower) & (factor_values < upper)
    layer_assignment[mask] = i + 1
```

**断言验证（分层后必须校验）：**
- 归层后必须校验所有股票都已归层
- 未归层股票（layer_assignment == 0）应抛 ValueError
- 原因：边界逻辑遗漏时静默出错，断言强制暴露问题

**正确写法：**
```python
unassigned_mask = layer_assignment == 0
if unassigned_mask.any():
    raise ValueError("fixed_threshold 分层逻辑错误：存在未归层的股票")
```

**边界处理顺序依赖：**
- 边界处理必须在循环前执行
- 循环内只处理未归层股票（`mask & (layer_assignment == 0)`）
- 原因：若调整顺序，边界外数据会被循环覆盖

---

## 性能优化规范

**预先按日期分组：**
- 原布尔索引每次全表扫描，时间复杂度 O(n²)
- groupby 一次分组后遍历，时间复杂度 O(n)
- 原因：merged_df 有 n_dates × n_assets 行，全表扫描耗时

**正确写法：**
```python
grouped_by_date = merged_df.groupby(date_col)
for date in dates:
    day_data = grouped_by_date.get_group(date).copy()
```

**错误写法：**
```python
for date in dates:
    day_data = merged_df[merged_df[date_col] == date].copy()  # 全表扫描
```

---

## 静态方法调用规范

**静态方法应通过类名调用，而非 self.：**
- self. 调用破坏静态方法语义
- 类名调用明确是静态方法，便于维护

**正确写法：**
```python
ls_series = LayeredBacktestEngine._calc_daily_ls(group, long_layers, short_layers)
```

**错误写法：**
```python
ls_series = self._calc_daily_ls(group, long_layers, short_layers)
```

---

## 命名风格规范

**同一概念在不同字典中命名风格必须统一：**
- 换手率字段：统一使用 `turnover_xxx_avg`（与 `layer_stats.turnover_avg` 一致）
- 原因：`avg_turnover_long` 与 `turnover_avg` 风格不一致，增加维护成本

**正确写法：**
```python
long_short_stats = {
    'turnover_long_avg': ...,  # 统一风格
    'turnover_short_avg': ...,
}
```

**错误写法：**
```python
long_short_stats = {
    'avg_turnover_long': ...,  # 与 turnover_avg 风格不一致
    'avg_turnover_short': ...,
}

---

## Config 类设计规范（更新）

**禁止 Property 与字段重复定义：**
- Property 与字段同步风险：修改字段后 Property 返回旧值
- 统一使用字段名访问：`config.layer_thresholds` 而非 `config.LAYER_THRESHOLDS`
- 原因：dataclass 字段已提供类型约束，Property 是冗余设计

---

## 异常处理规范

**JSONDecodeError 必须用链式抛出，但不能重新构造 json.JSONDecodeError：**

**正确写法（使用 ValueError，避免传递 e.doc 导致内存翻倍）：**
```python
except json.JSONDecodeError as e:
    # 不传递 e.doc（完整文档字符串），避免内存翻倍
    raise ValueError(
        f"JSON 解析失败: {path}, 位置 {e.pos}: {e.msg}"
    ) from e
```

**错误写法（传递 e.doc 导致内存翻倍）：**
```python
except json.JSONDecodeError as e:
    # e.doc 是完整 JSON 文档字符串，传递给新异常会导致内存翻倍
    raise json.JSONDecodeError(
        f"JSON 解析失败: {path}, 错误: {e.msg}",
        e.doc,  # 完整文档字符串，内存翻倍
        e.pos
    ) from e
```

**原因：**
- `e.doc` 是完整 JSON 文档字符串（可能几十MB）
- `json.JSONDecodeError(msg, doc, pos)` 构造函数会存储 doc 参数
- 重新构造异常时传递 `e.doc`，异常对象持有完整文档副本，内存翻倍
- 使用 `ValueError` + `from e` 保留异常链，仅传递 `e.pos` 和 `e.msg`（字符串片段）

---

## 参数命名规范

**统一命名风格，禁止下划线前缀：**
- 参数名统一为 `logger`，而非 `_logger`
- 下划线前缀语义是"私有变量"，但参数是外部传入
- 原因：风格不一致增加维护成本

---

## 类型注解规范

**返回类型注解必须精确：**
- `tuple` → `Tuple[pd.DataFrame, pd.DataFrame]`
- `Callable` → `Callable[[], None]`
- 原因：宽泛类型注解无法提供有效类型检查

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

**thresholds 与 layer_names 数量对应关系（强制）：**
- `n_layers = len(thresholds) - 1`（fixed_threshold 模式）
- `len(layer_names) = n_layers`（必须相等）
- `len(layer_threshold_desc) = n_layers`（必须相等）

**示例：**
```python
# 5个阈值点形成4层
layer_thresholds = [-30, 0, 20, 80, 100]  # 5个阈值点 → 4层
layer_names = {'1': ..., '2': ..., '3': ..., '4': ...}  # 4层名称
layer_threshold_desc = {'1': ..., '2': ..., '3': ..., '4': ...}  # 4层描述
```

**原因：**
- thresholds 定义边界点，层数量 = 阈值点数量 - 1
- layer_names / layer_threshold_desc 与层数不一致会导致运行时错误或逻辑混淆

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

## 因子列校验规范

**run_layered_backtest 必须在因子计算后校验 factor_col 存在。**

**校验逻辑：**
```python
# 因子计算（如果需要）
if factor_calculator:
    logger.info("计算 %s 因子...", factor_name)
    factor_df = factor_calculator(factor_df)

# 校验因子列存在
if factor_col not in factor_df.columns:
    available_cols = [c for c in factor_df.columns if c not in ['date', 'asset']]
    raise ValueError(
        f"因子列 '{factor_col}' 不存在于 factor_df 中，"
        f"可用因子列: {available_cols}"
    )
```

**原因：**
- 直接访问 `factor_df[factor_col]` 在列不存在时抛 KeyError
- KeyError 消息不友好（仅显示列名），无法帮助用户定位问题
- 显式校验并提供可用因子列，帮助用户排查配置错误

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

# 2. 校验 JSON 解析（使用 ValueError，避免传递 e.doc）
try:
    with gzip.open(factor_path, 'rt', encoding='utf-8') as f:
        factor_data = json.load(f)
except json.JSONDecodeError as e:
    raise ValueError(
        f"JSON 解析失败: {factor_path}, 位置 {e.pos}: {e.msg}"
    ) from e

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
- 使用 ValueError 而非 json.JSONDecodeError，避免传递 e.doc 导致内存翻倍

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

## CLI 参数透传规范

**CLI 参数必须透传给 run_layered_backtest。**

**必须支持的 CLI 参数：**
| 参数 | 用途 | 默认值 |
|------|------|--------|
| `--cache_dir` | 缓存目录路径 | None（使用 DEFAULT_CACHE_DIR） |
| `--output_dir` | 输出目录路径 | None（使用默认路径） |
| `--quiet` | 静默模式 | False |

**正确写法：**
```python
def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='因子分层回测')
    parser.add_argument('--cache_dir', type=str, default=None,
                        help='缓存目录路径')
    parser.add_argument('--output_dir', type=str, default=None)
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args()
    
    try:
        result = run_layered_backtest(
            factor_name='my_factor',
            factor_col='my_factor_value',
            config=MyFactorLayerConfig(),
            cache_dir=args.cache_dir,      # 透传 cache_dir
            output_dir=args.output_dir,    # 透传 output_dir
            verbose=not args.quiet,        # 透传 quiet（反向为 verbose）
            logger=logger
        )
        ...
```

**原因：**
- cache_dir 支持自定义缓存路径，便于多环境部署
- output_dir 支持自定义输出路径，便于结果归档

### additional_data_files 动态构建规范

**additional_data_files 的路径必须使用 args.cache_dir 动态构建，而非硬编码 DEFAULT_CACHE_DIR。**

**原因：**
- DEFAULT_CACHE_DIR 在模块导入时即被求值，无法响应用户指定的 --cache_dir
- 附加数据文件应与主缓存目录保持一致

**正确写法：**
```python
result = run_layered_backtest(
    ...
    additional_data_files={
        'turnover_rate': str(Path(args.cache_dir) / 'turnover_rate_data.json.gz')
    },
    cache_dir=args.cache_dir,
    ...
)
```

**错误写法：**
```python
# 硬编码 DEFAULT_CACHE_DIR，--cache_dir 参数对附加数据无效
result = run_layered_backtest(
    ...
    additional_data_files={'turnover_rate': str(DEFAULT_CACHE_DIR / 'turnover_rate_data.json.gz')},
    cache_dir=args.cache_dir,
    ...
)
```
- 参数透传保证 CLI 参数生效

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

### pd.NA vs np.nan 规范

**对于 float64 Series，应使用 `np.nan` 或 `float('nan')`，而非 `pd.NA`。**

**原因：**
- `pd.NA` 是 pandas 1.0+ 引入的 nullable 类型标量，适用于 `Int64`、`StringDtype` 等 nullable 类型
- 对于 `float64` Series，`pd.NA` 可能触发类型提升或警告
- `np.nan` 与浮点运算完全兼容，不会改变 Series 的 dtype

**正确写法：**
```python
# float64 Series 使用 np.nan
safe_avg = avg_turnover.where(~zero_mask, np.nan)
```

**错误写法：**
```python
# pd.NA 不适合 float64 Series
safe_avg = avg_turnover.where(~zero_mask, pd.NA)  # 可能触发类型提升
```

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

## 空数据返回结构规范

**引擎空数据返回结构必须与正常返回结构一致，便于下游统一处理。**

**正确写法：**
```python
if len(daily_df) == 0:
    # 构造结构完整但值为 None 的 layer_stats
    layer_stats = {}
    for layer_id in range(1, n_layers + 1):
        layer_stats[f'layer_{layer_id}'] = {
            'n_days': 0,
            'n_stocks_avg': 0,
            'daily_return_mean': None,
            'daily_return_std': None,
            'cumulative_return': None,
            'annual_return': None,
            'annual_volatility': None,
            'sharpe_ratio': None,
            'max_drawdown': None,
            'turnover_avg': None
        }
    return {
        'meta': {...},
        'layer_stats': layer_stats,  # 结构完整
        'long_short': {},
        'monotonicity': {'correlation': None, 'quality': 'no_data', 'layer_returns': [None] * n_layers},
        ...
    }
```

**错误写法：**
```python
if len(daily_df) == 0:
    return {
        'meta': {...},
        'layer_stats': {},  # 结构缺失，下游处理不一致
        'long_short': {},
        'monotonicity': {'correlation': None, 'quality': 'no_data', 'layer_returns': []},
        ...
    }
```

**原因：**
- 空路径 `layer_stats: {}` 与正常路径结构不一致
- 下游访问 `result['layer_stats'].get('layer_1')` 可能返回 None 或空 dict
- 结构统一便于下游处理，避免 TypeError 或 KeyError

---

## 空数据报告提示规范

**generate_report 必须对空数据输出明确提示，避免用户困惑。**

**正确写法：**
```python
# 统计有效层数
valid_layer_count = 0
for layer_id in range(1, meta['n_layers'] + 1):
    stats = result['layer_stats'].get(f'layer_{layer_id}', {})
    if stats.get('n_stocks_avg', 0) == 0:
        continue
    valid_layer_count += 1
    ...

# 空数据提示
if valid_layer_count == 0:
    lines.append("⚠ 无有效分层数据：所有日期数据量均不足 min_stocks_per_layer")
    lines.append("  建议：检查数据范围或降低 min_stocks_per_layer 参数")
```

**错误写法：**
```python
for layer_id in range(1, meta['n_layers'] + 1):
    stats = result['layer_stats'].get(f'layer_{layer_id}', {})
    if stats.get('n_stocks_avg', 0) == 0:
        continue  # 空数据时所有层都跳过，报告完全空白
    ...
# 无任何提示，用户困惑
```

**原因：**
- 空数据时所有层都跳过，分层收益统计部分完全空白
- 用户无法理解为何空白，认为是代码错误
- 明确提示原因和建议，帮助用户排查

---

## 必须遵守的约束

**遵循 PROJECT.md"输出数据规范"章节（2026-05-23新增）的跨模块通用原则：**
- 输出结构必须统一
- 字段值不可为 None
- 结果输出到 result 目录
- 因子方向不可预判

**本模块特定约束：**

| # | 约束 | 说明 |
|---|------|------|
| 1 | 分层阈值必须覆盖数据范围 | 避免 fixed_threshold 边界警告 |
| 2 | 反向因子多头取低层 | Layer(1,2)，空头取高层 Layer(n-1,n) |
| 3 | 每层最小股票数校验 | min_stocks_per_layer 参数 |
| 4 | 因子列必须校验存在 | 避免 KeyError，提供可用列列表 |

---

## 测试用例规范

**遵循 PROJECT.md"脚本配套文件规范"章节。**

**测试用例目录：** `backtest/test_cases/`

**测试用例文件命名：** `<因子名>_layered_backtest_test_cases.md`

---

## 输出目录规范

**遵循 PROJECT.md"输出数据规范 > 输出目录规范"章节。**

**输出路径：** `backtest/result/<因子名>_layered_backtest.json`

---

## 输出结构模板

**本模块特定输出结构（遵循 PROJECT.md"输出结构一致性规范"）：**

```json
{
  "meta": {
    "factor_name": "<str>",
    "factor_direction": "<str>",
    "n_days_total": <int>,
    "n_assets_total": <int>,
    "n_layers": <int>,
    "date_range": {"start": "<str>", "end": "<str>"},
    "layer_names": {<dict>},
    "layer_thresholds": [<list>],
    "layer_thresholds_desc": {<dict>}
  },
  "layer_stats": {
    "layer_1": {
      "n_days": <int>,
      "n_stocks_avg": <float>,
      "daily_return_mean": <float>,
      "daily_return_std": <float>,
      "cumulative_return": <float>,
      "annual_return": <float>,
      "annual_volatility": <float>,
      "sharpe_ratio": <float>,
      "max_drawdown": <float>,
      "turnover_avg": <float>
    },
    ...
  },
  "long_short": {
    "long_return_daily": <float>,
    "long_return_annual": <float>,
    "short_return_daily": <float>,
    "short_return_annual": <float>,
    "ls_return_daily": <float>,
    "ls_return_annual": <float>,
    "sharpe_ratio": <float>
  },
  "monotonicity": {
    "correlation": <float>,
    "quality": "<str>",
    "layer_returns": [<list>]
  },
  "trading_cost_analysis": {
    "trade_cost_rate": <float>,
    "avg_turnover_long": <float>,
    "avg_turnover_short": <float>,
    "daily_cost_long": <float>,
    "daily_cost_short": <float>,
    "gross_return": <float>,
    "net_return": <float>
  },
  "config": {<dict>},
  "created_at": "<ISO时间>"
}
```

**字段说明（必须非空字段）：**

| 字段 | 含义 | 空数据处理 |
|------|------|-----------|
| meta.factor_name | 因子名称 | 必须有值 |
| meta.n_days_total | 回测天数 | 必须有值（空数据为 0） |
| meta.n_assets_total | 股票总数 | 必须有值 |
| layer_stats.layer_X.n_stocks_avg | 平均股票数 | 必须有值（空数据为 0） |
| long_short.sharpe_ratio | 夏普比率 | 空数据可为 None |

---

## 输出格式

待定义：

- 分层收益统计
- 夏普比率
- 最大回撤
- IC 与回测收益的对应关系

---

*最后更新: 2026-05-23*