# backtest 模块规范

> 版本: v1.17
> 创建时间: 2026-05-22
> 最后更新: 2026-06-01 (overnight_ret Round 8 元数据集中)
> 更新记录: 
>   v1.17 (2026-06-01): overnight_ret Round 8 元数据集中（ic_meta字段+factor_name类属性+docstring简化）
>   v1.16 (2026-06-01): overnight_ret Round 7 docstring描述修正（删除压缩至~30行误导性描述）
>   v1.15 (2026-06-01): overnight_ret Round 6 架构缺陷修复（6项：私有方法泄露、隐式耦合、sys.path依赖、版本历史膨胀、重复注释、日志覆盖验证）
>   v1.14 (2026-06-01): overnight_ret Round 5 测试覆盖完善（边界值测试+参数校验测试，19项测试全部通过）
>   v1.13 (2026-06-01): overnight_ret Round 4 pytest测试补充（修复测试覆盖缺失，17项测试全部通过）
>   v1.12 (2026-06-01): overnight_ret Round 3 文档精简（简化类 docstring，移除冗余 IC 信息）
>   v1.11 (2026-06-01): overnight_ret Round 2 深度优化（layer_names语义修正、实测范围补充、测试状态更新）
>   v1.10 (2026-06-01): overnight_ret 因子方向修正（negative→positive），补充流程文档和测试用例
>   v1.9 (2026-05-29): 新增 return_5d 分层回测脚本
> 修订日期: 2026-06-01

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
| 数据路径 | `backtest.common.data_loader` | DEFAULT_DATA_SOURCE（统一数据源） |

### 禁止手写的逻辑

| 逻辑 | 正确方式 | 错误方式 |
|------|---------|---------|
| 数据加载 | `run_layered_backtest()` 自动加载 | 手写 gzip.open + json.load |
| 结果保存 | `run_layered_backtest()` 自动保存 | 手写 json.dump |
| CLI 入口 | `create_cli_entrypoint()` | 手写 argparse + 异常处理 |

**历史脚本兼容说明：**
- 新因子脚本强制使用 `create_cli_entrypoint`
- 历史脚本（KDJ_J、BOLLINGER_PB、RSI、换手率突增）在 2026-05-23 前开发，手写 main() 函数
- 历史脚本待后续重构，新脚本必须遵循新规范

**create_cli_entrypoint 支持的参数：**
- `factor_name`：因子名称
- `factor_col`：因子列名
- `config_class`：Config 类（继承 LayerConfigBase）
- `required_factor_cols`：预计算因子列校验（可选，见第 845 行规范）
- `additional_data_files`：额外数据文件（可选）
- `factor_calculator`：因子计算函数（可选）
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

3. **CLI 入口**（使用 factor_cli_main 公共函数）
```python
from backtest.common.layered_backtest_runner import LayerConfigBase
from backtest.common.factor_cli import factor_cli_main
from data_fetchers.factor_calculator import calculate_my_factor

@dataclass
class MyFactorLayerConfig(LayerConfigBase):
    layer_names: Dict[str, str] = field(default_factory=lambda: {
        '1': '低值层', '2': '偏低层', '3': '中位层',
        '4': '偏高层', '5': '高值层'
    })
    factor_direction: str = 'negative'
    long_layers: List[int] = field(default_factory=lambda: [1, 2])
    short_layers: List[int] = field(default_factory=lambda: [4, 5])

if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).parent.parent))
    factor_cli_main(
        factor_name='my_factor',
        config_cls=MyFactorLayerConfig,
        factor_calculator=calculate_my_factor
    )
```

### 代码量对比（v2.0 更新）

| 方式 | 行数 | 适用场景 |
|------|------|---------|
| 旧方式（手写全部逻辑） | ~200-400 | 已废弃 |
| 新方式（factor_cli_main） | **~50-80** | 强制使用 |

### 示例脚本（v2.0 更新）

| 因子类型 | 示例文件 | 行数 | 特点 |
|---------|---------|------|------|
| 简单因子 | `layered_backtest_amplitude_1d.py` | 70 | 无自定义参数 |
| 预计算因子 | `layered_backtest_volume_ratio_1d.py` | 58 | factor_calculator=None |
| 自定义参数 | `layered_backtest_rsi_1d.py` | 83 | --rsi-n 参数 |
| 自定义参数 | `layered_backtest_turnover_surge_1d.py` | 81 | --surge-window 参数 |

**分层数说明：**
- `n_layers = len(layer_thresholds) - 1`
- 示例：`[0, 0.5, 1.0, 1.5, 2.0, 5.0]` → 5 层
- 示例：`[0, 30, 50, 70, 100]` → 4 层（RSI）

---

## 分层规则

**分层方法强制规范（v1.5 更新）：**

> **强制使用 percentile 分层，禁止使用 fixed_threshold**
> 
> 原因：fixed_threshold 在极端行情时分层不稳定（如2024-09-27政策行情，布林带Layer5涌入1235只股票），导致分层收益失真。percentile 分层保证每层固定比例股票，自适应数据分布变化。

**分层配置：**
```python
layer_method='percentile'  # 强制值，不得改为 fixed_threshold
n_layers=5                 # 默认5层（每层20%）
```

**禁止写法：**
```python
# ❌ 禁止：fixed_threshold 模式
layer_method='fixed_threshold'
thresholds=[0, 30, 50, 70, 100]  # 固定阈值
```

**正确写法：**
```python
# ✅ 正确：percentile 模式
layer_method='percentile'
n_layers=5
```

**分层数量：**
- percentile 模式：由 n_layers 参数控制（默认 5 层）
- fixed_threshold 模式：**已废弃**，禁止使用

**分层方式：**
- 正向因子（factor_direction='positive'）：高值预期高收益，多头取高层
- 反向因子（factor_direction='negative'）：低值预期高收益，多头取低层

**percentile 分层层编号语义（v1.6 补充）：**

> percentile 分层后，Layer 编号与因子值排序的关系必须明确：
> - Layer 1：因子值最低的 20% 股票（rank_pct ∈ [0, 0.2]）
> - Layer n_layers：因子值最高的 20% 股票（rank_pct ∈ [0.8, 1.0]）

| 因子方向 | Layer 1 语义 | Layer n_layers 语义 | 默认 long_layers | 默认 short_layers |
|---------|-------------|--------------------|-----------------|------------------|
| positive (正向) | 最差的层（低因子值） | **最好的层**（高因子值） | [n-1, n] | [1, 2] |
| negative (反向) | **最好的层**（低因子值） | 最差的层（高因子值） | [1, 2] | [n-1, n] |

映射关系说明：
- 正向因子：高因子值 → 高收益预期 → Layer n_layers 是"最好的层" → 多头取高层
- 反向因子：低因子值 → 高收益预期 → Layer 1 是"最好的层" → 多头取低层

这是 percentile 分层的核心语义，影响多空组合选择和单调性解读。

**多空层默认设置（依赖已修正的 n_layers）：**
- 正向因子：多头 Layer(n-1, n)，空头 Layer(1, 2)
- 反向因子：多头 Layer(1, 2)，空头 Layer(n-1, n)

**percentile 分层优势：**
- 分层稳定：每层固定比例（如20%），不受数据分布变化影响
- 自适应：极端行情时仍保持分层比例稳定
- 可比较：不同因子、不同时期的分层结果可直接对比

**percentile 分层精度要求（v1.6 更新）：**

> **因子数据必须以 float64 存储，禁止使用 float32**

原因：
- float32 精度约为7位有效数字，相邻因子值（如 1.0000001 vs 1.0000002）会被截断为相同值
- 精度损失后，method='first' 虽能给相同值分配不同秩，但无法恢复原始顺序信息
- 分层结果偏离预期：本应分层N的股票被错误归入分层M

数据源规范：
- Parquet 文件：使用 `dtype='float64'` 存储
- 数据库读取：使用 `pd.read_sql(..., dtype={'factor_col': 'float64'})`
- 内存计算：默认 float64，避免 `.astype('float32')`

验证方法：
```python
# 检查因子值唯一性
unique_ratio = factor_values.nunique() / len(factor_values)
if unique_ratio < 0.95:
    logger.warning(f'因子值重复率高 ({(1-unique_ratio)*100:.1f}%)，检查精度问题')
```

**分层均匀性说明：**

percentile 分层使用 `rank + ceil` 算法，分层结果取决于 N（股票数）与 n_layers 的整除关系：

- 当 N 可被 n_layers 整除时：每层恰好 N/n_layers 支股票（完全均匀）
- 当 N 不能被 n_layers 整除时：
  - 使用 `ceil(rank_pct * n_layers)` 计算层号
  - 余数个股票会均匀分布到后几层
  - 例如 N=3003, n_layers=5 → Layer1-3 各600支，Layer4-5 各601支

这是算法的数学特性，非bug。实际影响：每层股票数差异 ≤1，对回测结果无实质影响。

**每层权重分配：**
- 等权平均（每只股票权重相等）

---

## 统计指标计算规范

**累计收益（cumulative_return）计算假设（v1.6 补充）：**

> **NaN 日（停牌、数据缺失）不参与收益计算**

计算流程：
1. 从 layer_data['return'] 中 dropna() 过滤无效收益
2. dropna() 后索引可能不连续（部分交易日缺失）
3. `(1 + valid_returns).cumprod() - 1` 对非连续索引有效

语义假设：
- NaN 收益来源：停牌、涨跌停数据缺失、因子数据缺失
- 计算含义：忽略停牌日收益，只计算实际可交易日的累计表现
- 与实际交易一致：停牌股票无法交易，不应计入收益

示例：
- 假设某股票在第 10 日停牌，收益为 NaN
- cumulative_return = 第1-9日收益连乘 × 第11-N日收益连乘
- 第 10 日不参与计算（符合实际：停牌日无交易收益）

**年化收益计算规范（v1.6 修正）：**

> **年化收益必须考虑数据覆盖率**

修正说明：
- 旧版本：年化 = 有效均值 * 252（假设全年都有收益，忽略数据缺失）
- 新版本：年化 = 有效均值 * 252 * 覆盖率

覆盖率计算：
- 覆盖率 = 有效天数 / 总天数
- 总天数：回测区间内的所有交易日（含 NaN 日）
- 有效天数：有收益数据的交易日（忽略 NaN）

语义说明：
- 如果某因子只有 60% 的交易日有数据（覆盖率=0.6）
- 年化收益应乘以 0.6（反映实际可交易时段）
- 否则会高估收益（假设全年都有收益）

示例：
- 总天数 6天，有效天数 4天（2天停牌）
- 有效均值 2.5%
- 错误年化：2.5% * 252 = 6.3%
- 正确年化：2.5% * 252 * (4/6) = 4.2%

**交易成本计算规范（v1.6 修正）：**

> **换手率 NaN → 成本按 0 处理**

语义说明：
- 换手率 NaN 表示"未知"（数据缺失、计算异常）
- 无法计算交易成本 → 成本按 0 处理
- 不是"成本为 NaN"，而是"无成本"

修复方案：
```python
# 错误写法：NaN 传播
long_turnover = _coalesce(stats.get('turnover_long_avg'))  # NaN 透传
long_daily_cost = long_turnover * trade_cost_rate  # NaN * 0.003 = NaN

# 正确写法：显式处理 NaN
long_turnover_raw = stats.get('turnover_long_avg')
long_turnover = 0.0 if pd.isna(long_turnover_raw) else float(long_turnover_raw)
long_daily_cost = long_turnover * trade_cost_rate  # 0.0 * 0.003 = 0.0
```

**夏普比率（简化版）：**
- 公式：`sharpe = annual_return / annual_volatility`
- 说明：简化夏普（rf=0），未扣除无风险收益率
- 适用场景：内部因子对比（相对排序），不用于绝对收益评估
- 若需标准夏普，应改为 `(annual_return - risk_free_rate) / annual_volatility`

**最大回撤（除零保护）：**
- 公式：`drawdown = (cum_series - rolling_max) / rolling_max`
- 保护：若 `rolling_max == 0`（净值归零），drawdown 设为 0
- 原因：除零会产生 inf 或 NaN，破坏后续统计

**数据类型规范（v1.6 修正）：**
- 因子列：`float64`（rank 分层需要精确区分相邻因子值）
- 收益列：`float64`（累计收益 `(1+r).cumprod()` 防长时间序列误差累积）
- **禁用 float32**：精度约7位有效数字，会导致分层偏差

修正说明：
- 旧版本将因子列转为 float32 以节省内存，但 percentile 分层需要精确区分相邻因子值
- float32 精度损失后，1.0000001 vs 1.0000002 会被截断为相同值
- 分层结果偏离预期：本应分层N的股票被错误归入分层M
- 修正后：因子列强制 float64，代价是内存增加，但分层精确

**格式化辅助函数规范（v1.6 新增）：**

使用 `_format_pct(val, decimals, suffix)` 处理百分比格式化：
- NaN → "N/A"
- 数值 → "12.34%"

用法示例：
```python
from backtest.common.layered_backtest import _coalesce, _format_pct

daily_ret = _coalesce(stats.get('daily_return_mean'))
# 正确用法：使用 _format_pct 处理 NaN
lines.append(f"日均收益: {_format_pct(daily_ret, 4)}")

# 错误用法（已修正）：直接乘法格式化会传播 NaN
# lines.append(f"日均收益: {daily_ret*100:.4f}%")  # ❌ NaN 会导致格式化错误
```

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

**第n层（最大边界）特殊处理：** 使用 `≥` 并说明上界处理逻辑。

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

## RSI 计算规范（2026-05-23 新增）

**RSI 计算方法：必须使用 Wilder 平滑（EWM，alpha=1/n），而非简单移动平均（SMA）。**

**原因：**
- Wilder (1978) 定义 RSI 使用指数加权移动平均（EWM）
- EWM 公式：`avg_t = alpha * val_t + (1-alpha) * avg_{t-1}`，其中 `alpha=1/n`
- SMA 与 EWM 在短窗口（如 n=6）差异显著
- EWM 对近期数据更敏感，更符合 RSI 标准定义

**正确写法：**
```python
def _calc_ewm_mean(series: pd.Series, alpha: float) -> pd.Series:
    """Wilder 平滑均值（groupby transform 专用）"""
    return series.ewm(alpha=alpha, adjust=False).mean()

calc_avg = partial(_calc_ewm_mean, alpha=1/n)  # Wilder 平滑：alpha=1/n
df['avg_gain'] = df.groupby('asset')['gain'].transform(calc_avg)
df['avg_loss'] = df.groupby('asset')['loss'].transform(calc_avg)
```

**错误写法：**
```python
# 使用简单移动平均（SMA）—— 不符合 RSI 标准定义
df['avg_gain'] = df.groupby('asset')['gain'].transform(lambda x: x.rolling(n).mean())
df['avg_loss'] = df.groupby('asset')['loss'].transform(lambda x: x.rolling(n).mean())
```

---

## 边界处理规范（2026-05-23 新增）

**avg_loss 接近零时的 RSI 计算必须分场景处理，避免逻辑漏洞。**

**边界情况分类：**
1. `avg_loss > EPSILON` 且 `avg_gain > 0`: 正常计算 RS，RSI ∈ [0, 100]
2. `avg_loss > EPSILON` 且 `avg_gain = 0`: RS = 0，RSI = 0（超卖）
3. `avg_loss = 0` 且 `avg_gain > 0`: RS → ∞，RSI = 100（超买）
4. `avg_loss = 0` 且 `avg_gain = 0`: 无涨无跌，RSI = 50（中性）

**delta=0 归属说明：**
- `delta=0`（价格不变）时，`gain=0` 且 `loss=0`
- 这是正确的处理：既不是上涨也不是下跌
- 但连续多天 `delta=0` 会累积导致 `avg_gain=0` 且 `avg_loss=0`
- 此时 RSI 应为 50（无涨无跌），而非 100（超买）

**正确写法（分开处理）：**
```python
zero_loss_mask = (df['avg_loss'].notna()) & (df['avg_loss'].abs() < EPSILON)
zero_gain_mask = (df['avg_gain'].notna()) & (df['avg_gain'].abs() < EPSILON)

# 同时接近零：avg_gain=0 且 avg_loss=0 → RSI=50
both_zero_mask = zero_loss_mask & zero_gain_mask
df.loc[both_zero_mask, 'rsi'] = 50

# 只有 avg_loss 接近零（avg_gain > 0）: RSI=100
only_zero_loss_mask = zero_loss_mask & ~zero_gain_mask
df.loc[only_zero_loss_mask, 'rsi'] = 100

# RS 计算（避免 division by zero）
df['rs'] = df['avg_gain'] / df['avg_loss'].where(
    df['avg_loss'] > EPSILON,
    EPSILON  # 临时避免除零，会被后续 mask 覆盖
)
df['rsi'] = 100 - (100 / (1 + df['rs']))

# 边界处理覆盖（必须在 RS 计算后执行）
df.loc[only_zero_loss_mask, 'rsi'] = 100
df.loc[both_zero_mask, 'rsi'] = 50
```

**错误写法（合并处理）：**
```python
# 错误：avg_loss=0 且 avg_gain=0 时，RS → ∞，RSI → 100（应为 50）
df['rsi'] = df['avg_gain'] / df['avg_loss'].replace(0, EPSILON)  # 合并处理
df['rsi'] = 100 - (100 / (1 + df['rs']))  # 无后续覆盖，逻辑漏洞
```

**原因：**
- `avg_loss=0` 有两种场景：`avg_gain>0`（超买）和 `avg_gain=0`（中性）
- 合并处理会导致后者误判为超买
- 分开处理逻辑清晰，避免边界情况遗漏

---

## 预计算因子列校验规范（2026-05-23 新增）

**预计算因子列（数据已在缓存中）应指定 required_factor_cols 作为防御性校验。**

**使用场景：**
- 因子列已在 `factor_ic_data.json.gz` 统一数据源中预存（如 volume_ratio_5）
- 无需 factor_calculator 实时计算

**正确写法：**
```python
main = create_cli_entrypoint(
    factor_name='volume_ratio',
    factor_col='volume_ratio_5',
    config_class=VolumeRatioLayerConfig,
    required_factor_cols=['volume_ratio_5']  # 预计算列防御性校验
)
```

**原因：**
- 虽然 runner 内部会在因子计算后校验 factor_col 存在（第 342 行）
- 但 required_factor_cols 在数据加载阶段提前校验，更快暴露问题
- 防御性编程：显式声明依赖，避免数据源变更后静默失败

---

## layer_names 与 layer_threshold_desc 分离规范（2026-05-23 新增）

**layer_names 只包含业务描述，技术边界说明放在 layer_threshold_desc。**

**正确写法：**
```python
layer_names: TypingDict[str, str] = field(default_factory=lambda: {
    '1': '极缩量层',  # 只包含业务含义
    '2': '缩量层',
    '3': '正常层',
    '4': '放量层',
    '5': '极放量层'
})

layer_threshold_desc: TypingDict[str, str] = field(default_factory=lambda: {
    '1': 'ratio < 0.5 (含越界值<0，极缩量，做多)',  # 技术边界 + 业务含义
    '2': '0.5 ≤ ratio < 1.0 (缩量，做多)',
    '3': '1.0 ≤ ratio < 1.5 (正常，不参与)',
    '4': '1.5 ≤ ratio < 2.0 (放量，做空)',
    '5': 'ratio ≥ 2.0 (含边界2.0，含越界值>5，极放量，做空)'
})
```

**错误写法：**
```python
layer_names: TypingDict[str, str] = field(default_factory=lambda: {
    '1': '极缩量层(ratio<0.5，含越界值<0)',  # 混合技术边界和业务含义
    '2': '缩量层(0.5≤ratio<1)',
    ...
})
```

**原因：**
- `layer_names` 用于结果展示（日志、报告），应简洁易懂
- `layer_threshold_desc` 用于技术文档说明，包含完整边界信息
- 分离职责：业务语义与技术细节解耦，便于维护

---

## IC 值溯源规范（2026-05-23 新增）

**Config 类注释中必须说明 IC 值来源文件，不能硬编码无溯源。**

**正确写法：**
```python
@dataclass
class VolumeRatioLayerConfig(LayerConfigBase):
    """量比分层配置
    
    因子方向说明（基于IC测试结果）：
    - IC均值 = -0.029（负相关，显著）
    - IC来源：factor_ic/result/volume_ratio_5_ic_result.json（2026-05-22 测试）
    - 高量比 → 未来收益倾向于更低（放量可能预示见顶）
    ...
    """
```

**错误写法：**
```python
@dataclass
class VolumeRatioLayerConfig(LayerConfigBase):
    """量比分层配置
    
    因子方向说明（基于IC测试结果）：
    - IC均值 = -0.029（负相关，显著）  # 无来源说明
    ...
    """
```

**原因：**
- IC 值硬编码在注释中，维护风险：IC 测试更新后注释未同步
- 必须溯源到具体文件，便于后续验证和更新
- 方法论严谨性：结论可追溯

---

## 阈值设计建议（2026-05-23 新增）

**阈值应根据数据统计特征设计，避免各层数据占比极端不平衡。**

**设计流程：**
1. 先运行数据统计脚本，获取因子范围、均值、中位数、分位数分布
2. 根据业务逻辑（如均值回归、趋势跟随）确定分层边界
3. 检查各层数据占比，避免单层占比过低（< 1%）或过高（> 40%）

**示例（量比因子）：**
```python
# 数据统计结果：
# - 范围：[0.1, 4.97]
# - 均值：1.01
# - 中位数：0.94（大部分数据在缩量区间）

# 阈值设计：
layer_thresholds: List[float] = field(default_factory=lambda: [0, 0.5, 1.0, 1.5, 2.0, 5.0])

# 数据占比校验（建议在 Config 类注释中说明）：
# - Layer1（ratio<0.5）：1.39%（极缩量，占比低但符合预期）
# - Layer5（ratio≥2）：2.23%（极放量，占比低但符合预期）
```

**极端占比检查：**
- 若某层占比 < 1%，检查阈值是否过于严格
- 若某层占比 > 40%，检查阈值是否过于宽松
- 均值回归策略中，中间层（如 Layer3）占比高是合理的

**原因：**
- 阈值设计应基于实际数据分布，而非主观假设
- 各层占比不平衡可能导致多空组合收益不稳定

---

## 因子方向与策略适配规范（2026-05-23 新增）

**factor_direction 必须与业务策略逻辑一致，注释需明确策略类型。**

**策略类型说明：**
- **均值回归策略**：偏离中性后可能回归，反向操作
  - RSI < 30（超卖）→ 做多
  - RSI > 70（超买）→ 做空
  - RSI 50~70（偏强）→ 可能回落，做空（而非趋势跟随）
- **趋势跟随策略**：延续当前趋势，同向操作
  - RSI 50~70（上涨趋势）→ 做多
  - RSI 30~50（下跌趋势）→ 做空

**factor_direction 配置规则：**
- 均值回归策略：`factor_direction='negative'`（低值做多，高值做空）
- 趋势跟随策略：`factor_direction='positive'`（高值做多，低值做空）

**配置示例（均值回归）：**
```python
@dataclass
class RSILayerConfig(LayerConfigBase):
    factor_direction: str = 'negative'  # 均值回归：低RSI做多，高RSI做空
    long_layers: List[int] = field(default_factory=lambda: [1, 2])  # Layer1/2（超卖/偏弱）做多
    short_layers: List[int] = field(default_factory=lambda: [3, 4])  # Layer3/4（偏强/超买）做空
    
    # 策略说明注释（必须明确）
    # 注意：这是均值回归策略，而非趋势跟随策略。
    # Layer3（50≤RSI<70）做空是基于"偏离中性偏强后可能回落"的均值回归逻辑。
    # 若需趋势跟随策略，请调整 factor_direction='positive'。
```

**原因：**
- `factor_direction` 与策略类型直接相关
- Layer3 做空在均值回归策略中合理，在趋势跟随策略中错误
- 必须在注释中明确策略类型，避免读者猜测或误用

---

## EWM 累积计算规范（2026-05-23 新增）

**EWM 在 groupby transform 中的索引连续性要求。**

**问题场景：**
- groupby transform 使用 EWM 时，依赖索引连续性
- 若存在重复日期或缺失日期，EWM 递推可能产生错误结果
- EWM 累积计算假设时间序列连续，缺失日期会跳过递推步骤

**校验要求：**
1. 检查重复日期：每个 asset 的 date 必须唯一
2. 检查缺失日期：建议补全缺失日期（可选）
3. 排序：必须按 asset + date 排序后再计算

**正确写法：**
```python
# 数据加载后必须排序
df = df.sort_values(['asset', 'date'])

# 检查重复日期
duplicate_dates = df.groupby('asset')['date'].apply(lambda x: x.duplicated().sum())
if duplicate_dates.sum() > 0:
    logger.warning(
        f"发现重复日期: {duplicate_dates.sum()} 条，建议检查数据源"
    )

# 检查缺失日期（可选，取决于业务需求）
# 若需严格连续，可补全缺失日期并填充 NaN
```

**原因：**
- EWM 递推公式：`avg_t = alpha * val_t + (1-alpha) * avg_{t-1}`
- 若索引不连续（缺失日期），`avg_{t-1}` 可能指向错误的时间点
- 重复日期会导致同一日期计算多次

---

## 阈值边界依赖说明规范（2026-05-23 新增）

**layer_threshold_desc 与 runner 实现的依赖关系。**

**依赖说明：**
- `layer_threshold_desc` 描述依赖于 `LayeredBacktestEngine` 的 `fixed_threshold` 实现
- runner 实现逻辑（`backtest/common/layered_backtest.py` 第398-409行）：
  - 前n-1层：左闭右开区间 `[lower, upper)`
  - 第n层（最后一层）：左闭右闭区间 `[lower, upper]`
- 边界外数据：
  - 低于最小阈值：归入 Layer 1
  - 高于最大阈值：归入 Layer n

**注释要求：**
- 必须在 Config 类注释中明确引用 runner 实现逻辑
- 避免声称"已解决"而实际依赖其他模块实现

**正确写法：**
```python
@dataclass
class RSILayerConfig(LayerConfigBase):
    # layer_threshold_desc 与 thresholds 对应（4层）
    # 格式遵循 MODULE.md 第451行规范：完整区间 [lower, upper)，必须包含下界
    # 最大边界使用 ≥，说明越界值处理
    #
    # runner 分层逻辑说明（fixed_threshold 模式）：
    # - 低于最小阈值（RSI<0）→ 归入 Layer1（边界处理）
    # - 边界内循环归层：
    #   - Layer1: [0, 30) 区间（0 ≤ RSI < 30）
    #   - Layer2: [30, 50) 区间（30 ≤ RSI < 50）
    #   - Layer3: [50, 70) 区间（50 ≤ RSI < 70）
    #   - Layer4: [70, 100] 区间（最后一层右闭：70 ≤ RSI ≤ 100）
    # - 高于最大阈值（RSI>100）→ 归入 Layer4（边界处理）
    #
    # 注意：上述分层逻辑由 runner 实现（layered_backtest.py），Config 仅描述
```

**原因：**
- Config 配置与 runner 实现存在依赖关系
- 单独修改 Config 或 runner 可能导致不一致
- 必须明确依赖关系，避免维护时遗漏

---

## 模块级函数定义规范（2026-05-23 新增）

**关键算法函数应定义为模块级函数而非嵌套函数。**

**原因：**
1. **单元测试覆盖**：嵌套函数无法被外部单元测试直接调用
2. **代码复用**：模块级函数可被其他脚本导入复用
3. **维护性**：独立函数更易于调试和版本管理

**禁止模式：**
```python
def calculate_rsi(...):
    def _wilder_smoothing(series, n):  # 嵌套定义 ❌
        """Wilder 平滑（前 n 天 SMA 种子，之后 EWM 递推）"""
        sma_seed = series.iloc[:n].mean()  # 错误：单一值填充前n天
        ewm_part = series.iloc[n:].ewm(alpha=1/n, adjust=False).mean()  # 错误：未衔接SMA种子
        result = pd.Series(index=series.index, dtype=float)
        result.iloc[:n] = sma_seed
        result.iloc[n:] = ewm_part
        return result
    
    avg_gain = _wilder_smoothing(gain, period)  # 无法单元测试 ❌
```

**推荐模式：**
```python
# 模块级函数定义（可被单元测试覆盖）
def _wilder_smoothing(series: pd.Series, n: int) -> pd.Series:
    """Wilder 平滑（前 n 天 SMA 种子，之后 EWM 递推）
    
    Wilder (1978) 标准实现：
    1. 前 n 天使用 rolling SMA（rolling(n).mean()）
       - 前 n-1 天：NaN（数据不足）
       - 第 n-1 天（索引 n-1）：SMA 值作为 EWM 种子
    2. 第 n 天及之后：EWM 递推
       - 公式：avg_t = alpha * val_t + (1-alpha) * avg_{t-1}
       - alpha = 1/n
    
    与 pandas ewm(adjust=False) 的差异：
    - pandas ewm(adjust=False) 从第 1 个观测值就开始计算
    - Wilder 标准要求前 n-1 天为 NaN，第 n-1 天用 SMA
    """
    rolling_avg = series.rolling(window=n).mean()
    result = rolling_avg.copy()
    
    alpha = 1.0 / n
    for i in range(n, len(series)):
        if pd.notna(rolling_avg.iloc[i-1]):
            result.iloc[i] = alpha * series.iloc[i] + (1-alpha) * result.iloc[i-1]
    
    return result

def calculate_rsi(...):
    avg_gain = _wilder_smoothing(gain, period)  # ✓ 可单元测试
```

**单元测试示例：**
```python
# tests/test_wilder_smoothing.py
from backtest.layered_backtest_rsi_1d import _wilder_smoothing

def test_wilder_smoothing():
    series = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    result = _wilder_smoothing(series, n=3)
    
    # 验证前 n-1 天为 NaN
    assert pd.isna(result.iloc[0])
    assert pd.isna(result.iloc[1])
    
    # 验证第 n-1 天为 SMA 值
    assert result.iloc[2] == 2.0  # (1+2+3)/3
    
    # 验证第 n 天开始 EWM 递推
    assert result.iloc[3] == 1/3 * 4.0 + 2/3 * 2.0
```

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

## 导入分组规范

**导入语句应按分组注释组织：标准库、第三方库、本地模块。**

**正确写法：**
```python
# 标准库
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict

# 第三方库（如 pandas）
import pandas as pd

# 本地模块
sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.common.layered_backtest_runner import run_layered_backtest
```

**原因：**
- 分组注释提高可读性
- 符合 Python 编码规范（PEP 8）
- 便于识别依赖来源

----

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
| `--data_source` | 数据源文件路径 | None（使用 DEFAULT_DATA_SOURCE） |
| `--output_dir` | 输出目录路径 | None（使用默认路径） |
| `--quiet` | 静默模式 | False |

**正确写法：**
```python
def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='因子分层回测')
    parser.add_argument('--data_source', type=str, default=None,
                        help='数据源文件路径')
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

### 统一数据源架构（v2.7 更新）

**自 2026-05-27 起，所有模块统一从 `data_fetchers/result/factor_ic_data.json.gz` 读取数据。**

**数据结构：**
- 因子列：rsi_6, volume_ratio_5, turnover_rate, bollinger_pb, kdj_j, turnover_surge
- 行情数据：open, close, high, low
- 收益数据：forward_return_1d, forward_return_3d, forward_return_5d

**移除的参数：**
- `cache_dir` → 改为 `data_source`
- `additional_data_files` → 已废弃（所有数据在统一数据源中）

**正确写法：**
```python
result = run_layered_backtest(
    ...
    data_source=args.data_source,
    ...
)
```

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