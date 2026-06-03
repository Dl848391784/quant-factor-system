# backtest 模块规范

> 版本: v2.0 (大重构)
> 最后更新: 2026-06-03
>
> 本规范由 AI 智能体或人类开发者执行。每条规则采用统一框架:**What / Why / How / Don't / When / Verify**。
>
> **harness 中立**:不绑定特定智能体平台,描述均为通用语义。

---

## 目录

### 一、模块概况
- [快速参考](#快速参考)
- [模块概述](#模块概述)
- [输出结构模板](#输出结构模板)

### 二、规则索引 (M1-M52,按类别)

| 类别 | 编号 | 主题 |
|------|------|------|
| **A. 模块基础** | M1-M4 | 模块职责 / 公共模块复用 / 脚本命名 / 输出目录与日志 |
| **B. Config 与 CLI 入口** | M5-M9 | ClassVar 薄声明 / layer_names Sequence / ic_source 派生 / factor_cli_main / 启动日志 |
| **C. 分层规则** | M10-M14 | 强制 percentile / fixed_threshold 写法 / 阈值描述格式 / 阈值设计 / 阈值边界依赖 |
| **D. 因子方向与策略** | M15-M17 | factor_direction 由 IC 派生 / IC 值溯源 / 策略类型注释 |
| **E. 统计指标** | M18-M23 | 累计收益 NaN / 年化覆盖率 / 交易成本 / 夏普 / 最大回撤 / 多空换手率 |
| **F. 数据类型与 NaN** | M24-M27 | float64 强制 / dict key str / NaN→None JSON / pd.NA vs np.nan |
| **G. 因子计算** | M28-M30 | RSI Wilder EWM / RSI 边界 / EWM 索引连续 |
| **H. 数据校验** | M31-M34 | 因子范围 / 因子列存在 / required_factor_cols / 数据完整性 |
| **I. CLI 与异常** | M35-M40 | 退出码 / 参数透传 / 单层模式 / JSON 解析异常 / 多空 groupby 替代 / 闭包捕获 |
| **J. 输出契约** | M41-M42 | 空数据返回结构一致 / 空数据报告提示 |
| **K. 代码风格与函数设计** | M43-M52 | 命名 / 类型注解 / 导入分组 / pathlib / 静态方法调用 / 显式传参 / 模块级函数 / 性能 / Config 字段 / layer_names 分离 |

### 三、附录
- [更新记录](#更新记录)
- [引用说明](#引用说明)

---

## 快速参考

### 关键公共模块

| 模块 | 功能 | 核心 |
|------|------|------|
| `backtest.common.layered_backtest` | 分层回测引擎 | `LayeredBacktestEngine`、`_coalesce`、`_format_pct` |
| `backtest.common.layered_backtest_runner` | 主入口 | `run_layered_backtest()`、`LayerConfigBase` |
| `backtest.common.factor_cli` | CLI 入口 | `factor_cli_main()` |
| `backtest.common.convert_types` | 类型转换 | numpy/pandas → Python 原生 |
| `backtest.common.logger_config` | 日志配置 | `get_logger()` |
| `backtest.common.data_loader` | 数据加载 | `DEFAULT_DATA_SOURCE` (统一数据源) |

### 4 条硬约束 (速查)

| # | 约束 | 对应规则 |
|---|------|---------|
| 1 | 分层阈值必须覆盖数据范围 | M11, M14 |
| 2 | 反向因子多头取低层 Layer(1,2),空头取 Layer(n-1,n) | M15 |
| 3 | 每层最小股票数校验 (`min_stocks_per_layer`) | M31 |
| 4 | 因子列必须校验存在 | M32 |

### 跨模块通用原则 (来自 PROJECT.md)
- 输出结构必须统一
- 字段值不可为 None
- 结果输出到 result 目录
- 因子方向不可预判

---

## 模块概述

backtest 模块负责对因子 IC 结果进行**分层回测**,评估因子的实际预测能力。

**模块定位**:
- **输入**:`factor_ic/result/ic_<因子>_<周期>_analysis_result.json` (IC 分析结果)
- **数据源**:`data_fetchers/result/factor_ic_data.json.gz` (统一数据源,2026-05-27 后)
- **输出**:`backtest/result/<因子>_layered_backtest.json` (分层收益、夏普、回撤等)
- **依赖方向**:`data_fetchers → factor_ic → backtest`,单向无环

**脚本命名**:`layered_backtest_<因子>_<收益周期>.py` (与 `ic_<因子>_<周期>.py` 配对)

**新因子开发模板** (v1.22 理想形态):

```python
"""xxx 因子分层回测脚本 - 薄声明 + factor_cli_main"""
from typing import ClassVar, Sequence
from backtest.common.layered_backtest_runner import LayerConfigBase
from backtest.common.factor_cli import factor_cli_main
from data_fetchers.factor_calculator import calculate_xxx


class XxxLayerConfig(LayerConfigBase):
    """xxx 因子分层配置 (薄声明,逻辑下沉基类)"""

    factor_name: ClassVar[str] = 'xxx'
    # ic_source 可选(基类自动按 factor_name 派生)

    layer_names: ClassVar[Sequence[str]] = (
        '低值层', '偏低层', '中位层', '偏高层', '高值层',
    )


if __name__ == '__main__':
    factor_cli_main(
        config_cls=XxxLayerConfig,
        factor_calculator=calculate_xxx,  # 预计算因子可省略
    )
```

**目标代码量**:新因子脚本 ~50-80 行(只有薄声明),而非 200-400 行。

**基类自动派生 (无需子类显式写)**:

| 派生字段 | 派生逻辑 |
|---------|---------|
| `ic_source_resolved` | `f'factor_ic/result/ic_{factor_name}_1d_analysis_result.json'` |
| `n_layers` | `len(layer_names)` |
| `factor_direction` | 从 `ic_metrics.ic_mean` 符号派生 (禁止硬编码默认值,见 M15) |
| `long_layers / short_layers` | 按 `factor_direction` 自动派生(约 40% 层数) |
| `layer_names_dict` | `{层号: 名称}` 格式(运行时转换,供日志显示) |

---

## 输出结构模板

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
      "n_days": <int>, "n_stocks_avg": <float>,
      "daily_return_mean": <float>, "daily_return_std": <float>,
      "cumulative_return": <float>, "annual_return": <float>,
      "annual_volatility": <float>, "sharpe_ratio": <float>,
      "max_drawdown": <float>, "turnover_avg": <float>
    }
  },
  "long_short": {
    "long_return_daily": <float>, "long_return_annual": <float>,
    "short_return_daily": <float>, "short_return_annual": <float>,
    "ls_return_daily": <float>, "ls_return_annual": <float>,
    "sharpe_ratio": <float>
  },
  "monotonicity": {
    "correlation": <float>, "quality": "<str>",
    "layer_returns": [<list>]
  },
  "trading_cost_analysis": {
    "trade_cost_rate": <float>,
    "avg_turnover_long": <float>, "avg_turnover_short": <float>,
    "daily_cost_long": <float>, "daily_cost_short": <float>,
    "gross_return": <float>, "net_return": <float>
  },
  "config": {<dict>},
  "created_at": "<ISO时间>"
}
```

**必须非空字段**:`meta.factor_name`、`meta.n_days_total` (空数据为 0)、`meta.n_assets_total`、`layer_stats.layer_X.n_stocks_avg`。空数据返回结构必须与正常一致 (见 M41)。

---

# A. 模块基础

## M1. 模块职责边界

**What**:`backtest/` 只做分层回测,禁止反向操作 (跨模块复用 `factor_ic/common/`、自行拉取数据等)。

**Why**:模块边界清晰才能维护单向依赖 `data_fetchers → factor_ic → backtest`,防止环。

**How / Don't**:

```
✓ 必须复用 backtest/common/ 下的模块
✗ 禁止手写数据加载、结果保存、CLI 入口逻辑
✗ 禁止跨模块复用 factor_ic/common/
```

**Verify**:import-linter;`grep "from factor_ic.common" backtest/` 应无结果。

---

## M2. 公共模块强制复用

**What**:`backtest/common/` 已封装的功能(数据加载、结果保存、CLI 入口、Config 基类、分层回测引擎)必须直接调用,禁止脚本自行实现。

**Why**:抽取公共模块的根本目的就是消除重复;自行实现会导致逻辑漂移、维护成本翻倍。

**How**:

| 功能 | 正确 | 禁止 |
|------|------|------|
| 数据加载 | `run_layered_backtest()` 自动加载 | `gzip.open` + `json.load` 手写 |
| 结果保存 | `run_layered_backtest()` 自动保存 | `json.dump` 手写 |
| CLI 入口 | `factor_cli_main()` (新) / `create_cli_entrypoint()` (兼容) | `argparse` + 异常处理手写 |
| Config 基类 | 继承 `LayerConfigBase` | 手写 property 方法 |
| 分层回测 | 调用 `LayeredBacktestEngine` | 手写分层逻辑 |

**历史脚本兼容**:2026-05-23 前开发的 KDJ_J、BOLLINGER_PB、RSI、换手率突增脚本手写了 main(),待后续重构;新脚本必须遵循新规范。

**`factor_cli_main` 支持的参数**:`config_cls`、`factor_calculator`(可选)、`required_factor_cols`(可选,见 M33)、`additional_data_files`(可选)。

---

## M3. 脚本命名

**What**:分层回测脚本统一命名为 `layered_backtest_<因子名>_<收益周期>.py`。

**Why**:与 factor_ic 模块 `ic_<因子>_<周期>.py` 配对,便于自动化工具按命名规则查找。

**示例**:`layered_backtest_rsi_1d.py`、`layered_backtest_volume_ratio_1d.py`。

---

## M4. 输出目录与日志路径

**What**:
- 回测结果输出到 `backtest/result/<因子>_layered_backtest.json`
- 日志输出到 `backtest/logs/*.log`,通过 `from backtest.common.logger_config import get_logger`

**Why**:统一目录便于打包/清理脚本处理;日志按模块隔离避免混杂。

---

# B. Config 与 CLI 入口设计

## M5. Config 类 ClassVar 薄声明 (v1.22 理想形态)

**What**:Config 子类只声明 ClassVar 元数据 (`factor_name` 必须、`ic_source` 可选、`layer_names` 必须),其余字段由基类运行时派生。不用 `@dataclass`,不用 `field(default_factory=...)`。

**Why**:
- ClassVar 元数据是因子的"身份",纯声明无需运行时构造
- `@dataclass` + `field(default_factory)` 在纯 ClassVar 场景是冗余的
- 派生字段集中在基类,改一处全更新

**How** (v1.22 理想形态,12 行):

```python
from typing import ClassVar, Sequence
from backtest.common.layered_backtest_runner import LayerConfigBase

class MyFactorLayerConfig(LayerConfigBase):
    """my_factor 因子分层配置 (薄声明)"""

    factor_name: ClassVar[str] = 'my_factor'
    # ic_source 可选(基类自动派生)

    layer_names: ClassVar[Sequence[str]] = (
        '低值层', '偏低层', '中位层', '偏高层', '高值层',
    )
```

**Don't** (v1.21 及更早):

```python
@dataclass  # ❌ 删除
class MyFactorLayerConfig(LayerConfigBase):
    layer_names: Dict[str, str] = field(default_factory=lambda: {  # ❌ 改为 tuple
        '1': '低值层', '2': '偏低层', ...
    })
```

**v1.22 对比表**:

| 旧版 (v1.21) | 新版 (v1.22) |
|-------------|-------------|
| `@dataclass` 装饰器 | ❌ 删除 |
| `layer_names: Dict[str, str]` | `layer_names: ClassVar[Sequence[str]]` |
| `field(default_factory=lambda: {...})` | ❌ 改 tuple 直接赋值 |
| 键 `'1'..'5'` 冗余索引 | ❌ 按位置派生 1-based 层号 |
| 缺层漏写风险 | ✓ Sequence 强制连续 |
| 20+ 行 | **12 行** |

---

## M6. layer_names 用 Sequence 而非 Dict

**What**:`layer_names: ClassVar[Sequence[str]]` 用元组(按层序 1-based),不用 `Dict[str, str]`。

**Why**:
- 元组天然连续,消除"缺层漏写" (Dict 可能写 `{'1', '3', '5'}` 漏 `'2', '4'`)
- 消除冗余键 (键 `'1'..'5'` 本就可从位置派生)
- 运行时基类自动转换为 `layer_names_dict` 供日志显示

**How**:见 M5。

---

## M7. ic_source 由 factor_name 自动派生

**What**:`ic_source` 路径由基类按 `f'factor_ic/result/ic_{factor_name}_1d_analysis_result.json'` 自动派生,子类无需声明 (除非路径特殊)。

**Why**:90% 的因子路径符合默认规则;让子类只关心"非默认"部分。

**How**:

```python
# 默认 (推荐):省略 ic_source
class MyFactorLayerConfig(LayerConfigBase):
    factor_name: ClassVar[str] = 'my_factor'
    # ic_source 自动 = 'factor_ic/result/ic_my_factor_1d_analysis_result.json'

# 非默认:显式声明
class SpecialFactorLayerConfig(LayerConfigBase):
    factor_name: ClassVar[str] = 'special'
    ic_source: ClassVar[str] = 'factor_ic/result/ic_special_v2_5d.json'  # 自定义
```

`ic_source_resolved` 是基类实例属性,记录最终使用的路径。

---

## M8. factor_cli_main 是 CLI 入口标准

**What**:`__main__` 块只调用 `factor_cli_main(config_cls=..., factor_calculator=...)`,不写 `argparse`、`try-except`、退出码、日志初始化等。

**Why**:`factor_cli_main` 内部处理参数解析、异常分类、退出码、日志、启动日志等所有 CLI 关注点,脚本只关心"我是哪个因子"。

**How**:

```python
if __name__ == '__main__':
    factor_cli_main(
        config_cls=MyFactorLayerConfig,
        factor_calculator=calculate_my_factor,  # 预计算因子省略
    )
```

**factor_cli_main 简化历史**:
- v1.20 删除了 `factor_name` / `description` 参数 (从 `config_cls` 派生)
- v1.20 删除了硬编码 `n_layers` / `factor_direction` (从 `ic_source` 派生)
- v1.20 起自动打印启动日志(见 M9)

---

## M9. 基类启动日志

**What**:`LayerConfigBase.__post_init__` 自动打印因子关键上下文 (factor_name、direction、n_layers、IC 文件),不在脚本里手写。

**Why**:统一格式便于日志解析;避免每个脚本重复 `logger.info("因子:...")`。

**输出格式**:

```
========================================
因子: my_factor
方向: negative (ic_mean=-0.0337)
分层: 5 层 (percentile)
IC文件: factor_ic/result/ic_my_factor_1d_analysis_result.json
========================================
```

---

# C. 分层规则

## M10. 强制 percentile 分层 (fixed_threshold 废弃)

**What**:分层方法只用 `layer_method='percentile'`,禁止 `fixed_threshold`。

**Why**:
- fixed_threshold 在极端行情时分层不稳定 (如 2024-09-27 政策行情,布林带 Layer5 涌入 1235 只股票,收益失真)
- percentile 保证每层固定比例,自适应分布变化
- 不同因子/时期的分层结果可直接对比

**How**:

```python
layer_method='percentile'  # 强制
n_layers=5                 # 默认 5 层 (每层 20%)
```

**Don't**:

```python
# ❌ fixed_threshold 已废弃
layer_method='fixed_threshold'
thresholds=[0, 30, 50, 70, 100]
```

**Layer 编号语义**:

| 因子方向 | Layer 1 | Layer n_layers | 默认 long_layers | 默认 short_layers |
|---------|---------|----------------|------------------|-------------------|
| positive (正向) | 最差(低因子值) | **最好**(高因子值) | [n-1, n] | [1, 2] |
| negative (反向) | **最好**(低因子值) | 最差(高因子值) | [1, 2] | [n-1, n] |

**percentile 分层均匀性**:用 `rank + ceil` 算法,N 不能被 n_layers 整除时,余数股票分布到后几层(差异 ≤1)。

---

## M11. fixed_threshold 写法 (兼容历史)

**What**:历史脚本仍用 `fixed_threshold` 时,必须遵循以下三条:
1. 统一循环处理所有层 (`range(len(thresholds) - 1)`),最后一层用条件判断
2. 归层后断言所有股票都已归层 (`layer_assignment == 0` 视为错误)
3. 边界处理在循环前执行,循环内只处理未归层股票

**Why**:
- `range(len(thresholds) - 2)` 在双阈值时产生空循环,易遗漏
- 不断言会让归层逻辑遗漏静默出错
- 边界处理顺序错会被循环覆盖

**How**:

```python
for i in range(len(thresholds) - 1):  # 统一循环
    lower, upper = thresholds[i], thresholds[i + 1]
    if i == n_layers - 1:  # 最后一层:右闭
        mask = (factor_values >= lower) & (factor_values <= upper)
    else:                  # 前 n-1 层:右开
        mask = (factor_values >= lower) & (factor_values < upper)
    layer_assignment[mask] = i + 1

unassigned_mask = layer_assignment == 0
if unassigned_mask.any():
    raise ValueError("fixed_threshold 分层逻辑错误:存在未归层的股票")
```

`n_layers = len(thresholds) - 1` (5 阈值点 → 4 层)。

---

## M12. layer_threshold_desc 格式

**What**:`LAYER_THRESHOLD_DESC` 字典必须用完整区间 `[lower, upper)` 格式,最后一层用 `≥` 并说明上界处理。

**How**:

```python
layer_threshold_desc: ClassVar[dict[str, str]] = {
    '1': '0 ≤ RSI < 20 (超卖)',
    '2': '20 ≤ RSI < 40 (含边界 20)',
    '5': 'RSI ≥ 80 (含边界 80,含越界值)',  # 最后一层
}
```

**Why**:
- 引擎 `fixed_threshold` 执行 `[thresholds[i], thresholds[i+1])` 归 Layer (i+1)
- 最后一层包含越界值 (如 RSI ≥ 100),必须在描述中明确

---

## M13. 阈值设计

**What**:阈值必须基于数据统计特征设计,避免单层占比 < 1% 或 > 40%。

**Why**:阈值脱离实际分布会导致多空组合收益不稳定。

**How**:

```python
# Step 1: 数据统计
# - 范围: [0.1, 4.97]
# - 均值: 1.01
# - 中位数: 0.94 (大部分缩量)

# Step 2: 按业务逻辑设阈值
layer_thresholds = [0, 0.5, 1.0, 1.5, 2.0, 5.0]

# Step 3: 占比校验
# - Layer1 (ratio<0.5): 1.39% ✓
# - Layer3 (中位): 较高 ✓ (均值回归策略合理)
# - Layer5 (ratio≥2): 2.23% ✓
```

**极端占比**:< 1% 检查阈值是否太严;> 40% 检查是否太宽。均值回归策略中,中间层占比高是合理的。

---

## M14. 阈值边界依赖说明

**What**:`fixed_threshold` 模式下,Config 注释必须显式说明引擎实现的分层逻辑 (而非声称"已解决")。

**Why**:Config 与 runner 实现存在依赖关系;不写清楚边界规则,修改任一侧都会产生不一致。

**How**:

```python
class RSILayerConfig(LayerConfigBase):
    """
    runner 分层逻辑 (fixed_threshold 模式,见 backtest/common/layered_backtest.py 第 398-409 行):
    - 低于最小阈值 (RSI<0) → 归 Layer1 (边界处理)
    - 边界内循环归层:
      - Layer1: [0, 30)
      - Layer2: [30, 50)
      - Layer3: [50, 70)
      - Layer4: [70, 100] (最后一层右闭)
    - 高于最大阈值 (RSI>100) → 归 Layer4 (边界处理)
    """
```

---

# D. 因子方向与策略

## M15. factor_direction 由 IC 派生,禁止隐式默认值

**What**:`factor_direction` 必须从 IC 文件 `ic_metrics.ic_mean` 符号派生 (ic_mean < 0 → negative),禁止在 Config 中硬编码默认值。

**Why**:
- 硬编码方向会让回测结论与实际相反(假设动量正向,实测 -0.05,代码按正向算 → 多空倒挂)
- 基类自动从 IC 文件加载方向,确保与最新 IC 结果一致
- v1.21 删除了所有隐式默认值

**How**:基类 `_load_ic_meta` 从 IC 文件读取并派生 `factor_direction`,子类完全不写。

**Don't**:

```python
class MyConfig(LayerConfigBase):
    factor_direction: str = 'negative'  # ❌ 隐式默认值,硬编码
```

---

## M16. IC 值溯源

**What**:Config 类注释中说明 IC 值时必须标明**来源文件 + 测试日期**,禁止硬编码 IC 数值无溯源。

**Why**:IC 测试更新后,无来源的注释会过期且无法追溯。

**How**:

```python
class VolumeRatioLayerConfig(LayerConfigBase):
    """量比分层配置

    因子方向说明 (基于 IC 测试结果):
    - IC 均值 = -0.029 (负相关,显著)
    - IC 来源:factor_ic/result/volume_ratio_5_ic_result.json (2026-05-22 测试)
    - 高量比 → 未来收益倾向于更低 (放量可能预示见顶)
    """
```

**Don't**:

```python
"""
- IC 均值 = -0.029 (负相关,显著)  # ❌ 无来源,无法追溯
"""
```

---

## M17. 策略类型必须在注释中明确

**What**:Config 注释必须说明策略类型 (均值回归 / 趋势跟随),并解释 `long_layers/short_layers` 与策略的对应关系。

**Why**:`factor_direction` 配置与策略类型直接相关:Layer3 做空在均值回归中合理,在趋势跟随中错误。

**How**:

```python
class RSILayerConfig(LayerConfigBase):
    """RSI 分层配置 (均值回归策略)

    策略说明:
    - 这是均值回归策略,而非趋势跟随
    - Layer3 (50≤RSI<70) 做空 = "偏离中性偏强后可能回落"
    - 若需趋势跟随,改 factor_direction='positive',Layer3 改做多
    """
    # 均值回归
    long_layers = [1, 2]   # Layer1/2 (超卖/偏弱) 做多
    short_layers = [3, 4]  # Layer3/4 (偏强/超买) 做空
```

**策略类型对照**:

| 策略 | factor_direction | Layer 行为 |
|------|------------------|-----------|
| 均值回归 | `negative` | 低值做多,高值做空 (Layer1,2 做多) |
| 趋势跟随 | `positive` | 高值做多,低值做空 (Layer4,5 做多) |

---

# E. 统计指标

## M18. 累计收益:NaN 日不参与

**What**:`cumulative_return` 计算前 `dropna()` 过滤无效收益,只对实际可交易日做 `cumprod`。

**Why**:NaN 来源(停牌/涨跌停/数据缺失)是"无法交易",计入会让回测脱离实际。

**How**:

```python
valid_returns = layer_data['return'].dropna()  # 索引可能不连续
cumulative_return = (1 + valid_returns).cumprod() - 1
```

**语义**:第 10 日停牌 → cumulative = 第 1-9 日连乘 × 第 11-N 日连乘。

---

## M19. 年化收益必须乘覆盖率

**What**:年化 = `valid_mean * 252 * 覆盖率`,覆盖率 = 有效天数 / 总天数。

**Why**:某因子覆盖率 60% 时,年化按 100% 算会高估 67%。

**How**:

```python
valid_days = (~returns.isna()).sum()
total_days = len(returns)
coverage = valid_days / total_days if total_days > 0 else 0
annual_return = valid_mean * 252 * coverage
```

**示例**:总 6 天 / 有效 4 天 / 均值 2.5% → 错误年化 2.5% × 252 = 6.3%;正确 2.5% × 252 × (4/6) = 4.2%。

---

## M20. 交易成本:换手率 NaN → 0

**What**:换手率 NaN 表示"未知" → 成本按 0 处理,不让 NaN 透传到 `daily_cost` 计算。

**Why**:`NaN * 0.003 = NaN` 会污染下游所有累计指标。

**How**:

```python
long_turnover_raw = stats.get('turnover_long_avg')
long_turnover = 0.0 if pd.isna(long_turnover_raw) else float(long_turnover_raw)
long_daily_cost = long_turnover * trade_cost_rate  # 0.0 * 0.003 = 0.0
```

**Don't**:

```python
long_turnover = _coalesce(stats.get('turnover_long_avg'))  # ❌ NaN 透传
long_daily_cost = long_turnover * trade_cost_rate  # NaN
```

---

## M21. 夏普 / 最大回撤公式

**What**:
- 夏普 (简化版):`sharpe = annual_return / annual_volatility` (rf=0,适用因子对比,不用于绝对收益评估)
- 最大回撤:`drawdown = (cum_series - rolling_max) / rolling_max`,rolling_max=0 时 drawdown 设 0 (除零保护)

**Why**:
- 简化夏普适合内部相对排序;若要绝对评估改为 `(ar - rf) / vol`
- 除零会产生 inf/NaN,破坏后续统计

---

## M22. 多空换手率:先组内均值,再总均值

**What**:计算 `avg_turnover_long` 时,**每日先取多头各层均值,再对所有日均值求总均值**,不要直接对所有 (天×层) 列表求均值。

**Why**:某日多头有 2 层 (Layer4+Layer5) 时,直接列表均值会让该天权重×2,导致权重失真。

**How**:

```python
# 每日多头换手率 = mean(多头各层换手率)
daily_long_turnover = grouped.apply(
    lambda g: g[g['layer'].isin(long_layers)]['turnover'].mean()
)

# 平均日换手率 = mean(每日)
avg_turnover_long = daily_long_turnover.mean()
```

**Don't**:

```python
# ❌ 直接对 (天×层) 列表求均值,多层日被计多次
avg_turnover_long = merged[merged['layer'].isin(long_layers)]['turnover'].mean()
```

---

## M23. 字典取值用 `_coalesce`,不用 `.get(default) or default`

**What**:统计字段从字典取值时用 `_coalesce(dict.get('key'))`,只替换 None/NaN;不要 `dict.get('key', 0)` 或 `dict.get('key') or 0`。

**Why**:
- `dict.get('key', 0)`:键存在但值为 None 时返回 None,后续 `None * 100` 抛 TypeError
- `dict.get('key') or 0`:合法的 0.0 或负数会被替换为 0 (空值/0/负数无法区分)
- `_coalesce` 只替换 None/NaN,保留 0.0 / 负数

**How**:

```python
from backtest.common.layered_backtest import _coalesce, _format_pct

long_daily = _coalesce(ls_stats.get('long_return_daily'))
lines.append(f"日均收益: {_format_pct(long_daily, 4)}")
```

**`_format_pct(val, decimals, suffix)`**:NaN → "N/A",数值 → "12.34%"。

---

# F. 数据类型与 NaN

## M24. 因子列强制 float64

**What**:因子列必须以 `float64` 存储,禁止 `float32`。收益列同理。

**Why**:
- `float32` 精度约 7 位有效数字,相邻因子值 (1.0000001 vs 1.0000002) 被截断为相同值
- percentile 分层用 `rank + method='first'` 虽能分配不同秩,但无法恢复原始顺序信息 → 分层结果偏离

**How**:

```python
# Parquet
pd.read_parquet(path, dtype={'factor_col': 'float64'})

# 数据库
pd.read_sql(sql, conn, dtype={'factor_col': 'float64'})

# 内存计算:默认 float64,避免 .astype('float32')

# percentile 分层前显式转 float64 (防御)
factor_values_f64 = factor_values.astype('float64')
ranks = factor_values_f64.rank(pct=True)
layer_assignment = np.ceil(ranks * n_layers).astype(int)

# 验证因子唯一性
unique_ratio = factor_values.nunique() / len(factor_values)
if unique_ratio < 0.95:
    logger.warning(f"因子值重复率高 ({(1-unique_ratio)*100:.1f}%),检查精度问题")
```

---

## M25. 字典 key 用 str (避 JSON 序列化漂移)

**What**:`layer_names` / `layer_threshold_desc` 等字典的 key 必须用字符串,不用 int。

**Why**:JSON 序列化会把 int key 转 str key;`layer_names.get(1)` 在 JSON 往返后返回 None (因为 key 变成 `'1'`)。

**How**:

```python
layer_names = {
    '1': '超卖层',  # str key
    '2': '弱势层',
    '5': '超买层',
}
```

**Don't**:

```python
LAYER_NAMES = {
    1: '超卖层',  # ❌ int key,JSON 后变 '1',layer_names.get(1) → None
}
```

---

## M26. NaN 转 None (JSON 安全)

**What**:JSON 序列化前必须把 NaN 替换为 None,用 `safe_float()` 辅助函数,不要直接 `float(...)`。

**Why**:`float(np.nan) = nan`,JSON 不支持 NaN → `json.dumps({'val': nan})` 抛 `ValueError: Out of range float values are not JSON compliant`。

**How**:

```python
def safe_float(val):
    """NaN → None,避免 json.dumps 抛 ValueError"""
    return None if pd.isna(val) else float(val)

long_short_stats = {
    'long_return_daily': safe_float(long_short_df['long_return'].mean()),
}
```

---

## M27. 浮点 Series 用 np.nan,不用 pd.NA

**What**:`float64` Series 的缺失值用 `np.nan` 或 `float('nan')`,不用 `pd.NA`。

**Why**:
- `pd.NA` 是 pandas 1.0+ 的 nullable 标量,适用 `Int64` / `StringDtype` 等 nullable 类型
- 对 `float64` Series,`pd.NA` 可能触发类型提升或警告
- `np.nan` 与浮点运算完全兼容,不改 dtype

**How**:

```python
safe_avg = avg_turnover.where(~zero_mask, np.nan)  # ✓ float64 不变
```

**Don't**:

```python
safe_avg = avg_turnover.where(~zero_mask, pd.NA)  # ❌ 可能触发类型提升
```

---

# G. 因子计算

## M28. RSI 用 Wilder EWM (alpha=1/n)

**What**:RSI 计算必须用 Wilder 平滑 (EWM,`alpha=1/n`),不用简单移动平均 (SMA)。

**Why**:
- Wilder (1978) 原始定义就是 EWM
- EWM 公式 `avg_t = α * val_t + (1-α) * avg_{t-1}`,α=1/n
- SMA 与 EWM 在短窗口 (n=6) 差异显著;EWM 对近期数据更敏感

**How**:

```python
def _calc_ewm_mean(series: pd.Series, alpha: float) -> pd.Series:
    """Wilder 平滑 (groupby transform 专用)"""
    return series.ewm(alpha=alpha, adjust=False).mean()

calc_avg = partial(_calc_ewm_mean, alpha=1/n)
df['avg_gain'] = df.groupby('asset')['gain'].transform(calc_avg)
df['avg_loss'] = df.groupby('asset')['loss'].transform(calc_avg)
```

**Don't**:

```python
# ❌ 简单移动平均不符合 RSI 标准
df['avg_gain'] = df.groupby('asset')['gain'].transform(lambda x: x.rolling(n).mean())
```

---

## M29. RSI 边界情况分别处理

**What**:`avg_loss` 接近零时必须按 `avg_gain` 是否也接近零**分场景**处理,不能合并。

**边界分类**:

| `avg_loss` | `avg_gain` | RSI | 语义 |
|-----------|-----------|-----|------|
| > EPSILON | > 0 | 正常 RS 计算 | [0, 100] |
| > EPSILON | = 0 | RS=0,RSI=0 | 超卖 |
| = 0 | > 0 | RS→∞,RSI=100 | 超买 |
| = 0 | = 0 | **RSI=50** | 无涨无跌(中性) |

**Why**:
- `delta=0` (价格不变) → `gain=0` 且 `loss=0`,连续多天会累积 `avg_gain=0` 且 `avg_loss=0`
- 合并处理 (如统一 `avg_loss.replace(0, EPSILON)`) 会让"无涨无跌"误判为超买

**How**:

```python
zero_loss_mask = (df['avg_loss'].notna()) & (df['avg_loss'].abs() < EPSILON)
zero_gain_mask = (df['avg_gain'].notna()) & (df['avg_gain'].abs() < EPSILON)

# 都接近零 → RSI=50
both_zero_mask = zero_loss_mask & zero_gain_mask

# 只 avg_loss=0 (avg_gain>0) → RSI=100
only_zero_loss_mask = zero_loss_mask & ~zero_gain_mask

# RS 计算 (避除零)
df['rs'] = df['avg_gain'] / df['avg_loss'].where(df['avg_loss'] > EPSILON, EPSILON)
df['rsi'] = 100 - (100 / (1 + df['rs']))

# 边界覆盖 (必须在 RS 计算后)
df.loc[only_zero_loss_mask, 'rsi'] = 100
df.loc[both_zero_mask, 'rsi'] = 50
```

---

## M30. EWM 计算前必须排序 + 检查重复日期

**What**:在 groupby 内使用 EWM 之前:
1. `df.sort_values(['asset', 'date'])`
2. 检查每个 asset 内日期是否重复 (重复会导致同日计算多次)

**Why**:EWM 递推 `avg_t = α·val_t + (1-α)·avg_{t-1}` 依赖索引连续;缺失/重复日期会让 `avg_{t-1}` 指向错误的时间点。

**How**:

```python
df = df.sort_values(['asset', 'date'])

duplicate_dates = df.groupby('asset')['date'].apply(lambda x: x.duplicated().sum())
if duplicate_dates.sum() > 0:
    logger.warning(f"发现重复日期: {duplicate_dates.sum()} 条,检查数据源")
```

缺失日期通常不补全 (除非业务要求严格连续)。

---

# H. 数据校验

## M31. 因子数据范围校验

**What**:回测脚本必须输出因子的 min/max,并对越界值警告 (如 RSI 理论 `[0, 100]`)。

**How**:

```python
factor_min = factor_df[factor_col].min()
factor_max = factor_df[factor_col].max()
logger.info("因子范围: %.2f ~ %.2f", factor_min, factor_max)

if factor_min < thresholds[0] or factor_max > thresholds[-1]:
    logger.warning(
        "因子值超出 thresholds 范围,建议检查因子计算或调整 thresholds"
    )
```

---

## M32. 因子列存在校验

**What**:`run_layered_backtest` 在因子计算后必须校验 `factor_col` 列存在,缺失时抛 ValueError 并列出可用列。

**Why**:直接 `factor_df[factor_col]` 缺列时抛 KeyError,消息只含列名,不友好。

**How**:

```python
if factor_calculator:
    factor_df = factor_calculator(factor_df)

if factor_col not in factor_df.columns:
    available_cols = [c for c in factor_df.columns if c not in ['date', 'asset']]
    raise ValueError(
        f"因子列 '{factor_col}' 不存在于 factor_df 中,"
        f"可用因子列: {available_cols}"
    )
```

---

## M33. required_factor_cols 防御 (预计算因子)

**What**:预计算因子 (数据已在缓存中,无需 `factor_calculator`) 必须通过 `required_factor_cols` 在数据加载阶段提前校验。

**Why**:虽然 runner 内部在因子计算后会校验 `factor_col`,但 `required_factor_cols` 在更早阶段暴露问题。

**How**:

```python
main = create_cli_entrypoint(
    factor_name='volume_ratio',
    factor_col='volume_ratio_5',
    config_class=VolumeRatioLayerConfig,
    required_factor_cols=['volume_ratio_5'],  # 防御:数据加载阶段校验
)
```

---

## M34. JSON 数据完整性校验

**What**:`load_data_from_cache` 必须按"文件存在 → JSON 解析 → 结构完整性"三步校验,每步给出友好错误信息。

**How**:

```python
# 1. 文件存在
if not factor_path.exists():
    raise FileNotFoundError(f"缓存文件不存在: {factor_path}")

# 2. JSON 解析 (用 ValueError,见 M39)
try:
    with gzip.open(factor_path, 'rt', encoding='utf-8') as f:
        factor_data = json.load(f)
except json.JSONDecodeError as e:
    raise ValueError(
        f"JSON 解析失败: {factor_path}, 位置 {e.pos}: {e.msg}"
    ) from e

# 3. 结构完整性
if 'data' not in factor_data:
    raise KeyError(
        f"JSON 结构缺失 'data' 字段: {factor_path}, "
        f"顶层字段: {list(factor_data.keys())}"
    )
```

---

# I. CLI 与异常

## M35. 退出码标准

**What**:`main()` 必须按以下退出码退出:

| 码 | 含义 |
|---|------|
| 0 | 成功 |
| 1 | 回测无有效数据 (`n_days_total = 0`) |
| 2 | 数据文件不存在 (`FileNotFoundError`) |
| 3 | 数据结构错误 (`KeyError`) |
| 4 | 参数错误 (`ValueError`) |
| 5 | 其他异常 |

**Why**:统一退出码便于 CI/CD 判断;不同码对应不同错误类型,便于排查。

**How**:`factor_cli_main` 已内置此逻辑,新脚本无需手写。历史脚本用以下模板:

```python
try:
    result = run_xxx_layered_backtest(...)
    if result['meta']['n_days_total'] == 0:
        logger.error("回测无有效数据,退出码 1")
        sys.exit(1)
    sys.exit(0)
except FileNotFoundError as e:
    logger.error("数据文件不存在: %s", e); sys.exit(2)
except KeyError as e:
    logger.error("数据结构错误: %s", e); sys.exit(3)
except ValueError as e:
    logger.error("参数错误: %s", e); sys.exit(4)
except Exception as e:
    logger.exception("回测执行异常: %s", e); sys.exit(5)
```

---

## M36. CLI 参数透传

**What**:`main()` 必须支持以下 CLI 参数并透传给 `run_layered_backtest()`:

| 参数 | 用途 | 默认 |
|------|------|------|
| `--data_source` | 数据源文件路径 | None → `DEFAULT_DATA_SOURCE` |
| `--output_dir` | 输出目录 | None → 默认路径 |
| `--quiet` | 静默模式 | False |

**Why**:支持自定义数据源便于多环境部署;支持自定义输出便于结果归档。

**统一数据源** (v2.7 / 2026-05-27):所有模块从 `data_fetchers/result/factor_ic_data.json.gz` 读取。已废弃 `cache_dir` 和 `additional_data_files` 参数。

---

## M37. 单层模式 (n_layers=1) 特殊处理

**What**:`long_layers/short_layers` 默认派生时,必须处理 `n_layers=1` 的边界:`long_layers = [1]`,而非 `[n_layers-1, n_layers] = [0, 1]`。

**Why**:`layer_id=0` 越界 (合法范围 `[1, n_layers]`),会抛 ValueError 但错误信息归咎用户;单层模式多空组合本就无意义。

**How**:

```python
if long_layers is None:
    if n_layers == 1:
        long_layers = [1]  # 单层
    else:
        long_layers = [n_layers - 1, n_layers] if factor_direction == 'positive' else [1, 2]
```

---

## M38. JSON 解析异常用 ValueError (不传 e.doc)

**What**:捕获 `json.JSONDecodeError` 时重新抛**不用 `json.JSONDecodeError(...)` 重构造**,改用 `ValueError`,只传 `e.pos` 和 `e.msg`,**不传 `e.doc`**。

**Why**:`e.doc` 是完整 JSON 文档字符串 (可能几十 MB),`json.JSONDecodeError(msg, doc, pos)` 会存 doc → 异常对象持有完整文档副本,**内存翻倍**。

**How**:

```python
except json.JSONDecodeError as e:
    raise ValueError(
        f"JSON 解析失败: {path}, 位置 {e.pos}: {e.msg}"
    ) from e
```

**Don't**:

```python
except json.JSONDecodeError as e:
    raise json.JSONDecodeError(  # ❌ 内存翻倍
        f"JSON 解析失败: {path}, 错误: {e.msg}",
        e.doc,  # 完整文档字符串
        e.pos,
    ) from e
```

---

## M39. groupby.apply 替代为显式循环 + concat

**What**:多空组合计算等场景**禁止用 `groupby.apply`**,改为显式循环 `for date in dates: ...` + `pd.DataFrame(list)`。

**Why**:pandas ≥ 2.2 下,`groupby.apply` 在 `group_keys=False` 时可能产生多级索引;`reset_index()` 后 `date` 列消失,变成整数索引,行为难预测。

**How**:

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

**Don't**:

```python
# ❌ groupby.apply 多级索引陷阱
long_short_df = daily_df.groupby('date', group_keys=False).apply(
    lambda group: _calc_daily_ls(group, long_layers, short_layers)
)
long_short_df = long_short_df.reset_index()  # date 列可能消失
```

---

## M40. 避免闭包捕获 (静态方法 + 显式传参)

**What**:`groupby` 内部用的函数必须是静态方法或独立函数,通过参数显式传入 `long_layers/short_layers` 等,**不要闭包捕获**外部变量。

**Why**:闭包捕获让外部变量修改后行为不可预期;静态方法显式传参便于测试和复用。

**How**:

```python
@staticmethod
def _calc_daily_ls(
    group: pd.DataFrame,
    long_layers: List[int],
    short_layers: List[int],
) -> pd.Series:
    """计算每日多空收益和换手率 (静态方法,显式传参)"""
    long_rets = group[group['layer'].isin(long_layers)]['return'].dropna()
    ...

# 调用
long_short_df.groupby('date').apply(
    lambda g: LayeredBacktestEngine._calc_daily_ls(g, long_layers, short_layers)
)
```

---

# J. 输出契约

## M41. 空数据返回结构与正常一致

**What**:`daily_df` 为空时,返回的 `layer_stats` 必须**包含全部层 (`layer_1` 到 `layer_n`)**,各字段值为 None/0,而不是 `{}`。

**Why**:空 dict 让下游 `result['layer_stats'].get('layer_1')` 行为不一致 (None vs 空 dict),易触发 TypeError/KeyError。

**How**:

```python
if len(daily_df) == 0:
    layer_stats = {}
    for layer_id in range(1, n_layers + 1):
        layer_stats[f'layer_{layer_id}'] = {
            'n_days': 0, 'n_stocks_avg': 0,
            'daily_return_mean': None, 'daily_return_std': None,
            'cumulative_return': None, 'annual_return': None,
            'annual_volatility': None, 'sharpe_ratio': None,
            'max_drawdown': None, 'turnover_avg': None,
        }
    return {
        'meta': {...},
        'layer_stats': layer_stats,  # 结构完整
        'long_short': {},
        'monotonicity': {'correlation': None, 'quality': 'no_data',
                         'layer_returns': [None] * n_layers},
    }
```

---

## M42. 空数据报告必须明确提示

**What**:`generate_report` 在所有层都被跳过时,必须输出明确的"无有效分层数据"提示 + 排查建议。

**Why**:空数据时报告完全空白会让用户认为是代码 bug。

**How**:

```python
valid_layer_count = 0
for layer_id in range(1, meta['n_layers'] + 1):
    stats = result['layer_stats'].get(f'layer_{layer_id}', {})
    if stats.get('n_stocks_avg', 0) == 0:
        continue
    valid_layer_count += 1
    # ...

if valid_layer_count == 0:
    lines.append("⚠ 无有效分层数据:所有日期数据量均不足 min_stocks_per_layer")
    lines.append("  建议:检查数据范围或降低 min_stocks_per_layer 参数")
```

---

# K. 代码风格与函数设计

## M43. 命名风格统一 (含数据源前缀)

**What**:同一概念在不同字典中命名风格必须统一。换手率字段统一用 `turnover_xxx_avg` (与 `layer_stats.turnover_avg` 一致),不用 `avg_turnover_xxx`。

**How**:

```python
long_short_stats = {
    'turnover_long_avg': ...,   # ✓ 与 turnover_avg 风格一致
    'turnover_short_avg': ...,
}
```

**Don't**:

```python
long_short_stats = {
    'avg_turnover_long': ...,   # ❌ 风格不一致
}
```

---

## M44. 参数命名无下划线前缀

**What**:函数参数统一为 `logger`,不用 `_logger`。下划线前缀语义是"私有变量",参数是外部传入,不属此类。

---

## M45. 类型注解精确

**What**:返回类型必须精确,`tuple` 写成 `Tuple[pd.DataFrame, pd.DataFrame]`,`Callable` 写成 `Callable[[], None]`。

**Why**:宽泛类型注解无法提供有效类型检查。

---

## M46. 导入分组 (PEP 8)

**What**:导入按"标准库 → 第三方 → 本地"三组,组间空一行,组内带注释。

**How**:

```python
# 标准库
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, ClassVar

# 第三方
import pandas as pd
import numpy as np

# 本地
sys.path.insert(0, str(Path(__file__).parent.parent))
from backtest.common.layered_backtest_runner import run_layered_backtest
```

---

## M47. 路径用 pathlib.Path

**What**:路径构造用 `pathlib.Path`,不用 `os.path.dirname` 多层嵌套。

**Why**:多次 `dirname` 意味祖父目录但语义不直观;脚本被移动或从其他目录调用时静默失效;`Path` 的 `/` 操作符更清晰。

**How**:

```python
from pathlib import Path
project_root = Path(__file__).parent.parent
cache_dir = project_root / 'cache' / 'factor_data'
```

**Don't**:

```python
os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # ❌ 语义不清
```

---

## M48. 静态方法用类名调用,不用 self.

**What**:静态方法通过**类名**调用,不用 `self.`。

**How**:

```python
ls_series = LayeredBacktestEngine._calc_daily_ls(group, long_layers, short_layers)
```

**Don't**:`self._calc_daily_ls(...)` 破坏静态方法语义。

---

## M49. 显式传入派生参数 (如 n_layers)

**What**:`fixed_threshold` 模式调用 `engine.run()` 时必须显式传 `n_layers`,不依赖引擎内部覆盖。

**Why**:隐式依赖在引擎默认值改变或 thresholds 变长时静默出错。

**How**:

```python
n_layers = len(config.LAYER_THRESHOLDS) - 1
result = engine.run(
    layer_method='fixed_threshold',
    thresholds=config.LAYER_THRESHOLDS,
    n_layers=n_layers,  # 显式传入
)
```

---

## M50. 关键算法用模块级函数 (可单元测试)

**What**:关键算法函数(如 Wilder 平滑、IC 计算辅助)定义为**模块级函数**,不嵌套在主函数内部。

**Why**:
1. 嵌套函数无法被外部单元测试直接调用
2. 模块级函数可被其他脚本导入复用
3. 独立函数更易调试和版本管理

**How**:

```python
# 模块级
def _wilder_smoothing(series: pd.Series, n: int) -> pd.Series:
    """Wilder 平滑 (前 n 天 SMA 种子,之后 EWM 递推)

    Wilder (1978) 标准:
    1. 前 n 天: rolling SMA
       - 前 n-1 天: NaN (数据不足)
       - 第 n-1 天: SMA 值作 EWM 种子
    2. 第 n 天起: EWM 递推, alpha = 1/n

    与 pandas ewm(adjust=False) 差异:
    - pandas 从第 1 个观测就计算
    - Wilder 要求前 n-1 天 NaN, 第 n-1 天用 SMA
    """
    rolling_avg = series.rolling(window=n).mean()
    result = rolling_avg.copy()
    alpha = 1.0 / n
    for i in range(n, len(series)):
        if pd.notna(rolling_avg.iloc[i-1]):
            result.iloc[i] = alpha * series.iloc[i] + (1-alpha) * result.iloc[i-1]
    return result


def calculate_rsi(...):
    avg_gain = _wilder_smoothing(gain, period)  # ✓ 可测试
```

**Don't**:

```python
def calculate_rsi(...):
    def _wilder_smoothing(series, n):  # ❌ 嵌套,无法单测
        ...
    avg_gain = _wilder_smoothing(gain, period)
```

**单元测试示例**:

```python
def test_wilder_smoothing():
    series = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    result = _wilder_smoothing(series, n=3)
    assert pd.isna(result.iloc[0])
    assert pd.isna(result.iloc[1])
    assert result.iloc[2] == 2.0          # SMA: (1+2+3)/3
    assert result.iloc[3] == 1/3 * 4.0 + 2/3 * 2.0  # EWM 递推
```

---

## M51. groupby 替代布尔索引 (性能)

**What**:按日期遍历数据时用 `df.groupby(date_col).get_group(date)`,不用 `df[df[date_col] == date]` 布尔索引。

**Why**:布尔索引每次扫全表 O(n²);groupby 一次分组 O(n)。`merged_df` 有 `n_dates × n_assets` 行时差异显著。

**How**:

```python
grouped_by_date = merged_df.groupby(date_col)
for date in dates:
    day_data = grouped_by_date.get_group(date).copy()
```

**Don't**:

```python
for date in dates:
    day_data = merged_df[merged_df[date_col] == date].copy()  # ❌ 每次扫全表
```

---

## M52. layer_names vs layer_threshold_desc 职责分离

**What**:`layer_names` 只放业务描述,技术边界说明放 `layer_threshold_desc`。

**Why**:`layer_names` 用于结果展示 (日志/报告),应简洁;`layer_threshold_desc` 用于技术文档,含完整边界信息。

**How**:

```python
layer_names: ClassVar[Sequence[str]] = (
    '极缩量层',  # 只业务含义
    '缩量层',
    '正常层',
    '放量层',
    '极放量层',
)

layer_threshold_desc: ClassVar[dict[str, str]] = {
    '1': 'ratio < 0.5 (含越界值<0,极缩量,做多)',  # 技术边界 + 业务
    '2': '0.5 ≤ ratio < 1.0 (缩量,做多)',
    '3': '1.0 ≤ ratio < 1.5 (正常,不参与)',
    '4': '1.5 ≤ ratio < 2.0 (放量,做空)',
    '5': 'ratio ≥ 2.0 (含边界 2.0,含越界值>5,极放量,做空)',
}
```

**Don't**:

```python
layer_names = {
    '1': '极缩量层 (ratio<0.5,含越界值<0)',  # ❌ 技术 + 业务混合
}
```

---

## 更新记录

| 版本 | 日期 | 主要变更 |
|------|------|---------|
| v2.0 | 2026-06-03 | 大重构:50 章节去重合并为 52 条 M 编号规则,按 11 类别 (A-K) 组织;统一 W/W/H/D/W/V 框架;加目录索引;精简更新记录 |
| v1.22 | 2026-06-01 | ClassVar 统一 (`layer_names` 改 `Sequence[str]`,删 `@dataclass` 与 `field`,`factor_name`/`ic_source`/`layer_names` 统一 ClassVar 风格,基类新增 `ic_source_resolved` + `layer_names_dict`) |
| v1.21 | 2026-06-01 | 10 项架构重构:`_load_ic_meta` 上移基类、`PROJECT_ROOT` 可移植获取、禁 direction 隐式默认值、删旧格式兼容分支、统一 ic_metrics 来源、import 提顶部、基类启动日志、删冗余 docstring、ic_source 自动拼接、理想形态 (`factor_name`+`layer_names`+`factor_cli_main`) |
| v1.20 | 2026-06-01 | `factor_cli_main` 参数简化 (删 `factor_name`/`description`,从 config 派生);启动日志;Config 新增 `factor_name`/`ic_source` ClassVar;`__post_init__` 派生 `n_layers`/`factor_direction` |
| v1.10-v1.19 | 2026-06-01 | overnight_ret/return_5d 因子方向修正与多轮深度优化 (7 轮 architecture + 测试覆盖 + 文档精简 + 元数据集中) |
| v1.0-v1.9 | 2026-05-22~29 | 首次创建;持续补充约束规范 (公共模块复用、分层规则 percentile 强制、阈值描述、JSON 异常、CLI 入口、空数据返回等) |

---

## 引用说明

本文档定义 `backtest/` 目录下所有分层回测脚本的开发规范。

**相关文档**:
- 项目级规范:`PROJECT.md` (目录结构、开发检查清单)
- 因子计算规范:`factor_ic/MODULE.md` (上游 IC 计算)
- 流程文档:`backtest/docs/<因子>_layered_backtest_flow.md`
- 测试用例:`backtest/test_cases/<因子>_layered_backtest_test_cases.md`
- 公共模块:`backtest/common/` 各模块

---

*最后更新: 2026-06-03*

