# factor_ic 模块规范

> 版本: v4.1
> 最后更新: 2026-06-12
>
> 本规范由 AI 智能体或人类开发者执行。每条规则采用统一框架:**What / Why / How / Don't / When / Verify**(简单规则可省略部分项)。
>
> **harness 中立**:不绑定特定智能体平台,描述均为通用语义。

---

## 目录

### 一、模块概况
- [快速参考](#快速参考)
- [模块概述](#模块概述)
- [输出结构模板](#输出结构模板)

### 二、规则索引 (M1-M65,按类别)

| 类别 | 编号 | 主题 |
|------|------|------|
| **A. 模块复用** | M1-M4 | 模块边界 / 公共模块复用 / logger 传递 / 跨目录禁止 |
| **B. IC 计算核心** | M5-M10 | IC 指标 / 因子方向 / 反向因子 / 五维度 / ICIR / NW 滞后 |
| **C. 数据处理** | M11-M18 | DataFrame 副本 / 中间变量 / numpy 混用 / EWM 初值 / 异常排除 |
| **D. 异常与错误** | M19-M23 | 异常分类 / 链 / 主入口 / CLI 堆栈 / 错误信息 |
| **E. 输出契约** | M24-M29 | 结构统一 / 字段去重 / 集中构建 / 必需 vs 可选 / 字段校验 / 口径 |
| **F. 增量更新** | M30-M41 | 三模式 / SKIP / 等价性 / None 保留 / rolling / period / 向量化 / 边界 |
| **G. 数据类型与精度** | M42-M47 | 日期格式 / index 类型 / NaN / np.nan / 浮点容差 / 模块常量 |
| **H. 技术指标参数** | M48-M52 | rolling 窗口语义 / min_periods / 布林带 / KDJ / 极端值裁剪 |
| **I. 数据校验** | M53-M55 | 计算前校验 / 列存在 / 长度检查 |
| **J. 代码风格** | M56-M62 | PEP8 import / 注释缩进 / 字典缩进 / 命名 / 参数 / 签名同步 / 类型 |
| **K. 路径对称与同步** | M63-M65 | 防御对称 / 等价性三重保障 / 死代码清理 |

### 三、附录
- [更新记录](#更新记录)
- [引用说明](#引用说明)

---

## 快速参考

### 关键函数签名

| 函数 | 文件 | 用途 |
|------|------|------|
| `load_factor_return_data(factor_cols)` | data_loader.py | 加载因子+收益数据 |
| `calculate_ic_with_direction_verification(factor_df, return_df, factor_col)` | ic_calculator.py | IC 计算+五维度判断 |
| `build_ic_result(ic_result, raw_metadata, factor_name)` | ic_result_builder.py | 构建输出结构 |
| `incremental_update_ic(output_path, factor_df_full, ...)` | incremental_engine.py | 增量更新 |
| `run_simple_factor_ic(factor_name, factor_col)` | factor_ic_runner.py | 简单因子主入口 |
| `run_complex_factor_ic(..., custom_factor_calculation)` | factor_ic_runner.py | 复杂因子主入口 |
| `should_use_incremental(output_file, factor_df, force_full)` | incremental_engine.py | 三模式判断 → `UpdateMode` |
| `calculate_single_day_ic(daily_data, factor_col, return_col, min_stocks)` | ic_calculator.py | 单日 IC(全量/增量共用) |
| `calculate_ic_statistics(ic_series)` | ic_calculator.py | IC 统计指标 |

### 跨模块通用原则 (来自 PROJECT.md "输出数据规范")
- 输出结构必须统一
- 字段值不可为 None
- 结果输出到 `<模块>/result/` 目录
- 因子方向不可预判

### 模块特定硬约束 (11 条速查)
| # | 约束 | 对应规则 |
|---|------|---------|
| 1 | 统计显著性只用 p<0.05 | M7, M9 |
| 2 | ICIR 用 abs(ic_mean) | M9 |
| 3 | 日期格式 YYYY-MM-DD | M42 |
| 4 | DataFrame 参数先 .copy() | M11 |
| 5 | IC 脚本禁止分层回测 | M1 |
| 6 | 增量复用 calculate_single_day_ic | M32 |
| 7 | 异常链保留 from e | M20 |
| 8 | NW 样本量 T=valid_days | M10 |
| 9 | rolling_ic_mean 前 9 个为 None | M35 |
| 10 | sample_stats.avg_stocks_period 含口径说明 | M29 |
| 11 | 字段不重复输出 | M25 |

---

## 模块概述

factor_ic 模块负责计算各类因子的 IC(Information Coefficient)值,用于评估因子对未来收益的预测能力。

**模块定位**:
- **输入**:`data_fetchers/result/factor_ic_data.json.gz`(统一数据源,含因子和收益)
- **输出**:`factor_ic/result/ic_<因子>_<周期>_analysis_result.json`
- **依赖方向**:`data_fetchers → cache → factor_ic → backtest`,单向无环
- **数据职责**:不自行拉取数据,只处理已缓存数据

**脚本命名**:`ic_<因子名>_<收益周期>.py` (如 `ic_rsi_1d.py`)

**IC 脚本注册表**（截至 v4.1 2026-06-12）：

| 因子名 | IC脚本 | 因子类型 | 数据列名 | factor_cols |
|--------|--------|---------|---------|-------------|
| rsi | ic_rsi_1d.py | 简单 | rsi_6 | ['rsi_6'] |
| volume_ratio | ic_volume_ratio_1d.py | 简单 | volume_ratio_5 | ['volume_ratio_5'] |
| bollinger_pb | ic_bollinger_pb_1d.py | 复杂 | bollinger_pb | ['close'] |
| kdj_j | ic_kdj_j_1d.py | 复杂 | kdj_j | ['close','high','low'] |
| turnover_surge | ic_turnover_surge_1d.py | 复杂 | turnover_surge | ['turnover_rate','close'] |
| amplitude | ic_amplitude_1d.py | 复杂 | amplitude | ['close','high','low'] |
| price_position | ic_price_position_1d.py | 复杂 | price_position | ['close','high','low'] |
| overnight_ret | ic_overnight_ret_1d.py | 简单 | overnight_ret | ['close'] |
| momentum_strength | ic_momentum_strength_1d.py | 复杂 | momentum_strength | ['close'] |
| tail_price_position | ic_tail_price_position_1d.py | 复杂 | tail_price_position | ['close','volume'] |
| tail_price_slope | ic_tail_price_slope_1d.py | 复杂 | tail_price_slope | ['close','volume'] |
| tail_price_volume_intensity | ic_tail_price_volume_intensity_1d.py | 复杂 | tail_price_volume_intensity | ['close','volume'] |
| **industry_momentum_5d** | **ic_industry_momentum_5d_1d.py** | **复杂** | **industry_momentum_5d** | **['close','asset']** |
| **industry_turnover_trend** | **ic_industry_turnover_trend_1d.py** | **复杂** | **industry_turnover_trend** | **['turnover_rate','asset']** |
| **industry_amplitude_trend** | **ic_industry_amplitude_trend_1d.py** | **复杂** | **industry_amplitude_trend** | **['amplitude','asset']** |

> 注：行业方向性因子为"复杂"类型（需 `run_complex_factor_ic`），因为因子值由 `factor_calculator.calculate_industry_*` 函数预计算，而非直接从缓存列读取。

**公共模块架构** (`factor_ic/common/`):

| 模块 | 功能 | 核心函数 |
|------|------|----------|
| `data_loader.py` | 数据加载 | `load_factor_return_data()` |
| `ic_calculator.py` | IC 计算 | `calculate_ic_with_direction_verification()` / `calculate_single_day_ic()` / `calculate_ic_statistics()` |
| `ic_result_builder.py` | 结果构建 | `build_ic_result()` |
| `incremental_engine.py` | 增量更新 | `incremental_update_ic()` / `should_use_incremental()` / `UpdateMode` 枚举 |
| `factor_ic_runner.py` | 主入口 | `run_simple_factor_ic()` / `run_complex_factor_ic()` |

**新增因子开发模板**:

```python
"""xxx 因子 IC 计算器 - 使用公共模块"""
from factor_ic.common.factor_ic_runner import run_simple_factor_ic, run_complex_factor_ic

# 简单因子(直接用缓存列)
result = run_simple_factor_ic('rsi', 'rsi_6')

# 复杂因子(需自定义计算)
def calculate_xxx(factor_df, logger=None):
    """因子特有计算逻辑(含数据校验,见 M53)"""
    ...
    return factor_df

result = run_complex_factor_ic(
    factor_name='xxx', factor_col='xxx',
    factor_cols=['close', 'high', 'low'],
    custom_factor_calculation=calculate_xxx,
)
```

**目标代码量**:新增因子脚本 ~50-200 行(仅因子计算逻辑),而非 300-1000 行。

---

## 输出结构模板

所有 IC 计算结果遵循以下统一结构 (全量/增量两条路径必须完全一致,见 M24):

```json
{
  "factor_name": "<str>",
  "calculation_date": "<ISO时间>",
  "period": {"start": "<str>", "end": "<str>", "description": "<str>"},
  "ic_metrics": {
    "ic_mean": <float>, "ic_std": <float>, "icir": <float>,
    "p_value": <float>, "p_value_display": "<str>"
  },
  "sample_stats": {
    "total_days": <int>, "valid_days": <int>,
    "avg_stocks_per_day": <float>,
    "avg_stocks_period": {"start": "<str>", "end": "<str>", "description": "<str>"}
  },
  "statistical_significance": {
    "t_stat": <float>, "p_value": <float>, "p_value_display": "<str>",
    "nw_lag": <int>, "nw_lag_method": "<str>",
    "is_significant": <bool>, "conclusion": "<str>"
  },
  "factor_direction": {
    "ic_mean": <float>, "ic_mean_sign": "<str>",
    "direction_usage": "<str>", "conclusion": "<str>"
  },
  "economic_significance": {
    "abs_ic_mean": <float>,
    "threshold_used": {"weak": 0.03, "strong": 0.05},
    "level": "<str>", "is_economically_significant": <bool>, "conclusion": "<str>"
  },
  "icir_stability": {
    "icir": <float>,
    "threshold_used": {"usable": 0.5, "good": 1.0, "excellent": 2.0},
    "level": "<str>", "is_stable": <bool>, "conclusion": "<str>"
  },
  "ic_distribution_consistency": {
    "positive_ratio": <float>, "ic_mean_sign": "<str>",
    "consistency_type": "<str>", "distribution_hint": "<str>",
    "is_consistent": <bool>, "conclusion": "<str>"
  },
  "dates": ["<日期列表>"],
  "ic_values": [<IC值列表>],
  "rolling_ic_mean": [<滚动均值列表>],
  "positive_ratio": <float>,
  "n_assets": <int>,
  "summary": {
    "ic_performance": "<str>", "statistical_significance": "<str>",
    "factor_direction": "<str>", "economic_significance": "<str>",
    "recommendation": "<str>"
  },
  "factor_stats": {
    "factor_name": "<str>", "return_period": "<str>", "data_source": "<str>",
    "total_days": <int>, "valid_days": <int>
  },
  "factor_col": "<str>",
  "update_mode": "<str>"
}
```

**五维度判断字段说明**:

| 字段 | 判断依据 | 子字段 |
|------|---------|--------|
| statistical_significance | Newey-West t 检验,p<0.05 | t_stat, p_value, p_value_display, nw_lag, nw_lag_method, is_significant, conclusion |
| factor_direction | ic_mean 符号 | ic_mean, ic_mean_sign, direction_usage, conclusion |
| economic_significance | \|ic_mean\| ≥ 0.03/0.05 | abs_ic_mean, threshold_used, level, is_economically_significant, conclusion |
| icir_stability | \|ICIR\| ≥ 0.5/1.0/2.0 | icir, threshold_used, level, is_stable, conclusion |
| ic_distribution_consistency | positive_ratio 与方向匹配 | positive_ratio, ic_mean_sign, consistency_type, distribution_hint, is_consistent, conclusion |

**辅助字段**:

| 字段 | 含义 | 来源 |
|------|------|------|
| n_assets | 平均股票数 | raw_metadata.avg_stocks_per_day |
| factor_stats | 因子元信息 | build_ic_result 构建 |
| factor_col | 因子列名(追踪用) | 调用方传入 |
| update_mode | 三模式标识(skip/incremental/full) | 主入口决定 |

---

# A. 模块复用规则

## M1. IC 模块职责边界

**What**:`factor_ic/` 只做 IC 计算和方向判断,禁止做分层回测、引入 backtest 模块。

**Why**:模块边界清晰才能让重构不牵连;data_fetchers → factor_ic → backtest 的单向依赖才能防止环。

**How / Don't**:

| 模块 | 职责 | 禁止 |
|------|------|------|
| `factor_ic/` | IC 计算、方向判断 | 分层回测、`from backtest import` |
| `backtest/` | 分层回测、净值曲线 | — |

**Verify**:import-linter 配置模块边界;`grep "from backtest" factor_ic/` 应无结果。

---

## M1.1. IC 模块数据来源单一化

**What**: `factor_ic/` 下的脚本**只负责 IC 计算**,所需数据必须由 `data_fetchers/factor_generator.py` 统一生成到 `factor_ic_data.json.gz` 中,禁止自行拉取或计算因子数据。

**Why**: 
1. **数据源统一**: `factor_ic_data.json.gz` 是跨模块共享的统一数据源,综合因子(comprehensive_factor)等下游模块也依赖此数据
2. **职责分离**: factor_generator 负责数据合并与因子计算,factor_ic 只负责 IC 分析
3. **避免重复计算**: 同一因子数据不应在多个模块重复计算

**How**:
- ✅ `factor_ic/` 脚本从 `data_fetchers/result/factor_ic_data.json.gz` 读取数据
- ❌ `factor_ic/` 脚本自行调用 `fetch_factor_cache.py` 或 `fetch_turnover.py`
- ❌ `factor_ic/` 脚本自行计算基础因子(rsi_6, volume_ratio_5 等)

**Don't**:
```python
# ❌ 在 factor_ic 脚本中自行拉取数据
from data_fetchers.fetch_factor_cache import fetch_factor_data
raw_data = fetch_factor_data()  # 禁止

# ✅ 正确做法:从统一数据源加载
from factor_ic.common.data_loader import load_factor_return_data
data = load_factor_return_data(factor_cols=['rsi_6', 'close'])
```

**When**: 开发任何新因子 IC 脚本前,确认所需字段已在 `factor_ic_data.json.gz` 中存在。

**Verify**: 
- [ ] `factor_ic/` 脚本不调用 `data_fetchers/fetch_*.py` 中的数据获取函数
- [ ] 新增因子字段时,先在 `factor_generator.py` 中添加,再在 `factor_ic/` 中使用
- [ ] 开发新因子 IC 脚本前,先检查 `factor_ic_data.json.gz` 中是否存在所需字段(避免反复调试)

---

## M2. 公共模块强制复用

**What**:`factor_ic/common/` 已封装的功能(主流程、数据加载、IC 计算、结果构建、保存、增量、模式判断)必须直接调用,禁止脚本自行实现。

**Why**:抽取公共模块的根本目的就是消除重复;违反此原则等于公共模块毫无意义,且修改时必须改多处易遗漏。

**How**:

```python
# ✅ 调用公共模块主入口,只实现因子特有逻辑
def calculate_bollinger_pb(factor_df, n=20, k=2.0):
    """布林带计算(因子特有)"""
    ...

result = run_complex_factor_ic(
    factor_name='bollinger_pb', factor_col='bollinger_pb',
    factor_cols=['close'],
    custom_factor_calculation=calculate_bollinger_pb,
)
```

**Don't**:

```python
# ❌ 手写三模式分支(公共模块已有 run_complex_factor_ic)
def generate_bollinger_pb_ic_data(...):
    mode = should_use_incremental(...)
    if mode == UpdateMode.SKIP:
        with open(output_file) as f:
            return json.load(f)
    elif mode == UpdateMode.INCREMENTAL:
        result = incremental_update_ic(...)
    elif mode == UpdateMode.FULL:
        ic_result = calculate_ic_with_direction_verification(...)
        result = build_ic_result(...)
        save_ic_result(result, output_file)
```

**公共模块封装范围(禁止脚本自行实现)**:

| 功能 | 公共函数 | 不可自行实现 |
|------|---------|------------|
| 主流程入口 | `run_simple_factor_ic()` / `run_complex_factor_ic()` | 三模式分支、模式判断 |
| 数据加载 | `load_factor_return_data()` | gzip 解压、JSON 加载（ijson 流式 + 列式累积，峰值 <1GB）、日期转换 |
| 日期清单 | `get_factor_data_dates()` | gzip 流式扫描 dates 字段（ijson，无需加载全量数据） |
| IC 计算 | `calculate_ic_with_direction_verification()` | Spearman IC、五维度判断 |
| 结果构建 | `build_ic_result()` | 输出字典拼接、rolling_ic_mean |
| 结果保存 | `save_ic_result()` | JSON 序列化、文件写入 |
| 增量更新 | `incremental_update_ic()` | 缓存读取、缺失日期、合并 |
| 模式判断 | `should_use_incremental()` | 日期对比、缓存完整性 |

**When**:开发任何新因子脚本前。

**Verify** checklist:
- [ ] 检查 `factor_ic/common/` 下是否已有对应函数
- [ ] 主流程、数据加载、结果构建必须复用公共模块
- [ ] 仅因子特有的计算逻辑允许自行实现

---

## M3. 公共模块 logger 由调用方传入

**What**:`factor_ic/common/*.py` 中的公共函数不独立创建 logger,接收调用方传入的 `logger` 参数(`logger=None` fallback)。

**Why**:公共模块被多个脚本调用,若独立创建 logger,日志固定在 `data_loader.log` 等,无法追溯是哪个脚本调用的。

**How**:

```python
# 公共模块函数签名
def public_function(..., logger=None):
    if logger is None:
        logger = get_logger(__name__)  # fallback,独立调用时用
    logger.info("操作完成")

# 调用方传入自己的 logger
logger = get_logger(__name__)  # ic_kdj_j_1d 的 logger
data = load_data_from_cache(cache_path, logger=logger)
# → 日志记录在 ic_kdj_j_1d_YYYY-MM-DD.log
```

**Don't**:

```python
# ❌ 公共模块独立创建,日志无法定位调用方
def load_data_from_cache(cache_path):
    logger = get_logger(__name__)  # 固定为 data_loader
```

**Verify**:`grep -n "get_logger(__name__)" factor_ic/common/*.py` 查到的位置必须都在 `if logger is None:` 分支中。

---

## M3.1 主职责日志输出公共函数:logger 强制必传

**What**:当公共函数的**主要职责本身就是输出日志**(如 `factor_summary_logger.log_factor_summary` 输出 IC 计算总结/告警),`logger` 参数**强制必传**,不允许 `logger=None` fallback。这是 M3 的特例细化,适用范围:`factor_ic/common/` 中函数名包含 `log_` 前缀或函数体 ≥80% 是 `logger.xxx(...)` 调用的模块。

**Why**:M3 的 fallback 机制服务于"数据/结果构建类"公共函数(如 `load_data_from_cache`、`build_ic_result`),这类函数被独立调用做单元测试或一次性查询时,fallback 提供便捷。但**日志输出函数**没有"独立调用"场景——它的存在意义就是被入口脚本调用并归集到入口脚本的日志文件。若允许 `logger=None`,fallback 会落到 `factor_summary_logger` 自己的日志文件,与"日志归集到入口脚本"的设计意图完全相反。

**触发条件**(满足其一即应抽公共函数并强制必传 logger):
- ≥3 个入口脚本含相同/近似的 `logger.warning` / `logger.info` 文案块
- 文案修改需同步多脚本(违反 DRY)
- 文案需运维巡检统一(差异化文案让运维抓不到关键字)

**How**:

```python
# factor_ic/common/factor_summary_logger.py
# logger 不带默认值,必传
def log_factor_summary(result, factor_display_name, logger, *, extra_summary_lines=None):
    logger.info("=" * 60)
    logger.info("%s IC 计算完成", factor_display_name)
    # ... 主体全部是 logger.xxx(...)
    none_fields = [k for k in ("ic_mean", "ic_std", "icir", "ic_positive_ratio") if result.get(k) is None]
    if none_fields:
        logger.warning(
            "%s IC 指标异常字段: %s(数据加载可能失败,请查看上方 ERROR 日志或检查 build_error_result 触发条件)",
            factor_display_name, ", ".join(none_fields),
        )

# 入口脚本调用:必须显式传 logger
logger = get_logger(__name__)
log_factor_summary(result, "振幅差分因子", logger)
```

**Don't**:

```python
# ❌ 给日志输出函数加 fallback,违背日志归集意图
def log_factor_summary(result, factor_display_name, logger=None):
    if logger is None:
        logger = get_logger(__name__)  # 落到 factor_summary_logger.log,完全不是入口脚本的日志!
    logger.info("...")

# ❌ 在入口脚本继续保留各自的 4 条 if X is None: warning 字面量,不抽公共函数
if result.get("ic_std") is None:
    logger.warning("ICIR 无法计算...")  # 17 个脚本各写一份,文案漂移
```

**When**:

| 场景 | 适用规范 | 说明 |
|------|----------|------|
| 数据加载/结果构建公共函数 | M3 (fallback) | 例:`load_data_from_cache`、`build_ic_result`,有独立调用场景 |
| 日志输出主职责公共函数 | M3.1 (强制必传) | 例:`log_factor_summary`,无独立调用场景,日志须归集入口 |
| 因子计算公共函数(无日志) | M3 (fallback,但实际不会触发) | 例:`compute_layered_ic`,logger 仅用于异常输出 |

**Examples**:

```python
# ✓ 正确(M3.1):日志输出函数强制必传 logger
log_factor_summary(result, "振幅差分因子", logger)

# ✓ 正确(M3.1):测试用例必须传 mock logger
def test_log_factor_summary_warns_on_none_fields():
    mock_logger = MagicMock()
    log_factor_summary({"ic_mean": None, ...}, "test", mock_logger)
    mock_logger.warning.assert_called_once()

# ✗ 错误(M3.1):省略 logger 触发 TypeError
log_factor_summary(result, "振幅差分因子")  # missing 1 required positional argument
```

**Verify**:
- `grep -c "logger=None" factor_ic/common/factor_summary_logger.py` 必须为 `0`
- `grep -rn "ICIR 无法计算" factor_ic/ic_*.py | wc -l` 必须为 `0`(本轮迁移 17 脚本的字面量已全部抽到公共函数;另有 7 脚本采用"手写 summary_lines + 单条 ic_mean warning"模式,不在本规范适用范围,后续轮次单独处理)
- `pytest factor_ic/test_cases/test_factor_summary_logger.py` 9/9 通过

---

## M3.2 入口启动日志收口至公共模块横幅

**What**:`factor_ic/ic_*.py` 入口脚本**不再自行打印启动日志**,统一由公共模块 `factor_ic_runner` 在 `run_simple_factor_ic` / `run_complex_factor_ic` 内部打印横幅(含因子名/周期/min_stocks/force_full)。入口脚本如需追加因子专属参数(布林 n/k、KDJ n/m1/m2、版本号等),通过 `extra_log_params={"k": v}` 关键字参数显式声明,横幅自动追加"扩展参数"行。

**Why**:34 个入口脚本原各自手写启动 `logger.info(...)`,文案漂移严重(「启动 XX 因子 IC 计算」/「XX 因子 IC 计算启动」/「[min_stocks=%s, force_full=%s]」),运维巡检抓不到统一关键字;且每个入口脚本要在解析参数后立即重复打印 "min_stocks/force_full"——这两个值本就是 runner 入参,完全可以由 runner 自身打印,入口只负责声明参数差异(`extra_log_params`)。本规范是 M2「公共模块强制复用」在启动节点的具体实施。

**How**:

```python
# factor_ic/common/factor_ic_runner.py(已实施,见 commit 0709fe6)
def run_complex_factor_ic(..., extra_log_params: dict[str, Any] | None = None, ...):
    _logger.info("=" * 60)
    _logger.info("因子 IC 分析: %s_%s", factor_name, return_period)
    _logger.info("入口参数: min_stocks=%s, force_full=%s", min_stocks, force_full)
    if extra_log_params:
        extra_str = ", ".join(f"{k}={v!s}" for k, v in extra_log_params.items())
        _logger.info("扩展参数: %s", extra_str)
    _logger.info("=" * 60)

# 入口脚本(无扩展参数,29 个)
def main():
    args = parser.parse_args()
    # 启动横幅由公共模块 factor_ic_runner 统一打印（含 min_stocks/force_full）
    result = run_simple_factor_ic(
        factor_name="rsi", factor_col="rsi_6",
        min_stocks=args.min_stocks, force_full=args.force_full,
        _logger=logger,
    )

# 入口脚本(含扩展参数,5 个:bollinger_pb / capital_flow_ratio_trend / kdj_j / turnover_surge / 任何后续因子)
def main():
    args = parser.parse_args()
    # 启动横幅由公共模块 factor_ic_runner 统一打印（含 min_stocks/force_full + extra_log_params）
    result = run_complex_factor_ic(
        factor_name="kdj_j", ...,
        min_stocks=args.min_stocks, force_full=args.force_full,
        extra_log_params={"n": args.n, "m1": args.m1, "m2": args.m2},
        _logger=logger,
    )
```

**Don't**:

```python
# ❌ 入口脚本自行打印启动日志,文案漂移 + 关键字不统一
def main():
    args = parser.parse_args()
    logger.info(
        "启动 KDJ_J 因子 IC 计算: n=%s, m1=%s, min_stocks=%s, force_full=%s",
        args.n, args.m1, args.min_stocks, args.force_full,
    )
    result = run_complex_factor_ic(...)  # runner 内部还会再打一次横幅,关键节点重复

# ❌ 把扩展参数硬编码进 factor_name / 因子专属字段,不走 extra_log_params
result = run_complex_factor_ic(
    factor_name=f"kdj_j_n{args.n}",  # 污染数据契约,扩展参数应进 extra_log_params
    ...,
)
```

**When**:

| 场景 | 适用规范 | 说明 |
|------|----------|------|
| 入口脚本无因子专属启动参数 | M3.2(直接调 runner) | 例:`ic_rsi_1d`(只有 min_stocks/force_full) |
| 入口脚本有因子专属启动参数 | M3.2(`extra_log_params=`) | 例:`ic_kdj_j_1d` 传 n/m1/m2 |
| 公共模块横幅之外的运行节点日志 | 不在本规范范围 | 例:summary 输出(M3.1)、build_error_result 异常路径 |

**Examples**:

```python
# ✓ 正确:无扩展参数,单行注释占位
args = parser.parse_args()
# 启动横幅由公共模块 factor_ic_runner 统一打印（含 min_stocks/force_full）
result = run_simple_factor_ic(...)

# ✓ 正确:含扩展参数,显式声明
result = run_complex_factor_ic(
    ...,
    extra_log_params={"version": __version__},
    _logger=logger,
)

# ✗ 错误:入口脚本保留 logger.info 启动块
logger.info("启动 XXX 因子IC计算: ...")  # 与 runner 横幅重复
```

**Verify**:
- `grep -rn '启动.*因子\|因子.*计算启动\|IC 计算启动\|IC计算启动' factor_ic/ic_*.py | wc -l` 必须为 `0`(34 脚本启动字面量已全部收口)
- `grep -l '启动横幅由公共模块 factor_ic_runner 统一打印' factor_ic/ic_*.py | wc -l` 必须为 `34`(全部入口脚本均含标准占位注释)
- `pytest factor_ic/test_cases/test_factor_ic_runner_startup_log.py` 8/8 通过(覆盖空 dict / 单参数 / 多参数 mixed / None / bool+float / force_full=True / min_stocks 自定义)

---

## M3.3 factor_cols 声明式注册 + 运行时列校验

**What**: 34 个 IC 入口脚本必须通过 `FactorSpec` 声明式注册因子元数据（名称、目标列、所需列、计算函数、参数提取函数），并通过 `run_factor_ic(spec=SPEC, ...)` 统一入口调用，禁止 `factor_cols=` 字符串字面量散落在调用处。

**Why**:
- **排序漂移**: 38 处 `factor_cols` 字面量中存在 `[open,close,asset,date]` vs `[date,asset,close]` 等顺序不一致，依赖内部拼接逻辑隐式去重
- **静默失败**: 上游字段名变更时，硬编码列名无法被编译器或运行时检测
- **两套入口**: `run_simple_factor_ic` / `run_complex_factor_ic` 参数不对称，增加维护负担

**How**:
1. 每个入口脚本在模块级声明 `SPEC = register_factor(FactorSpec(...))`：
   - `factor_name`: 因子英文名（小写下划线）
   - `factor_col`: IC 目标列名
   - `required_columns`: 使用标准常量组合（`JOIN_KEYS` / `OHLC` / `OHLCV` / `PRICE_VOLUME`）+ 因子特有列
   - `calculation`: 因子计算函数（无自定义计算时省略）
   - `calc_params_fn`: 从 `argparse.Namespace` 提取计算参数的 `Callable`（无参数时省略）
   - `extra_log_params_fn`: 从 `argparse.Namespace` 提取横幅扩展参数的 `Callable`（无扩展时省略）
2. `main()` 内调用 `run_factor_ic(spec=SPEC, args=args, min_stocks=..., force_full=..., _logger=...)`
3. `register_factor()` 执行 L2 注册期校验（非空 / 无重复 / 全小写字母数字下划线 / factor_col ∈ required_columns）
4. `validate_required_columns()` 执行 L3 运行时校验（列缺失时抛出 `DataSchemaError`）

**Don't**:
- ❌ 在 `run_factor_ic()` 调用处写 `factor_cols=["date","asset","xxx"]` 字面量
- ❌ 继续使用 `run_simple_factor_ic` / `run_complex_factor_ic`（已由 `run_factor_ic` 统一）
- ❌ 在 SPEC 声明中引用尚未定义的本地函数（SPEC 应放在 `def main()` 之前、所有 `def calculate_*` 之后）

**When**: 新增 IC 入口脚本时必须声明 SPEC；已有脚本迁移时按 R3.4 批次执行。

**Examples**:
```python
# ✓ 正确: simple 因子（无自定义计算）
from factor_ic.common.data_columns import JOIN_KEYS
from factor_ic.common.factor_spec import FactorSpec, register_factor

SPEC = register_factor(
    FactorSpec(
        factor_name="rsi",
        factor_col="rsi_6",
        required_columns=JOIN_KEYS + ("rsi_6",),
    )
)

# ✓ 正确: complex 因子（含计算函数 + 参数提取）
SPEC = register_factor(
    FactorSpec(
        factor_name="turnover_surge",
        factor_col="turnover_surge",
        required_columns=JOIN_KEYS + ("close", "turnover_rate", "turnover_surge"),
        calculation=calculate_turnover_surge,
        calc_params_fn=lambda a: {"surge_window": a.surge_window},
        extra_log_params_fn=lambda a: {"surge_window": a.surge_window},
    )
)

# ✗ 错误: 字面量列名
run_factor_ic(
    spec=SPEC,
    factor_cols=["date", "asset", "amplitude"],  # 禁止
)
```

**Verify**:
- `grep -rn 'factor_cols=\[' factor_ic/ic_*.py | grep -v '#'` 必须为 `0`（代码行无字面量）
- `grep -rl 'SPEC = register_factor' factor_ic/ic_*.py | wc -l` 必须为 `34`（全部入口脚本已注册）
- `grep -rn 'run_simple_factor_ic\|run_complex_factor_ic' factor_ic/ic_*.py | grep -v '^#' | grep -v 'docstring\|FactorCalcError'` 必须为 `0`（旧入口已替换）
- `pytest factor_ic/test_cases/test_factor_spec.py factor_ic/test_cases/test_data_columns.py` 全部通过

---

## M4. 跨目录公共模块禁止调用

**What**:公共模块仅在本目录内复用,禁止跨目录调用 (`factor_ic/` 脚本不可 `from backtest.common import`)。

**Why**:跨目录调用破坏模块边界、增加耦合;违反 data_fetchers → factor_ic → backtest 单向依赖原则。

**How / Don't**:

```
✅ factor_ic/ic_rsi_1d.py 调用 factor_ic/common/data_loader.py
✅ backtest/layered_backtest.py 调用 backtest/common/backtest_utils.py

❌ factor_ic/ic_rsi_1d.py 调用 backtest/common/backtest_utils.py
❌ backtest/layered_backtest.py 调用 factor_ic/common/ic_calculator.py
```

**Verify**:import-linter 配置;CI grep 检查。

---

# B. IC 计算核心规则

## M5. IC 统计指标

**What**:统一使用以下定义计算 IC 指标。

| 字段 | 含义 | 计算方式 |
|------|------|---------|
| ic_mean | IC 均值 | 有效日期 IC 算术平均 |
| ic_std | IC 标准差 | 有效日期 IC 标准差 |
| icir | 信息比率 | `abs(ic_mean) / ic_std` (见 M9) |
| t_stat | t 统计量 | `ic_mean * sqrt(valid_days) / ic_std` |
| p_value | 显著性 p 值 | 双尾 t 检验 p 值(Newey-West 调整) |

**统计显著性**:`p < 0.05` (与 `|t| > 1.96` 等价)。

---

## M6. 因子方向由实际 IC 决定

**What**:因子方向(正向/反向/无效)只能根据实际 IC 结果判断,禁止根据因子类型假设方向。

**Why**:假设方向会让回测结论与实际相反 —— 比如假定动量因子正向,实测 IC 是 -0.05,但代码按正向计算导致结论倒挂。

**How / Don't**:

| IC 特征 | 方向 | 说明 |
|---------|------|------|
| ic_mean > 0.03 且 p<0.05 | 正向 | 高因子→高收益 |
| ic_mean < -0.03 且 p<0.05 | 反向 | 高因子→低收益 |
| p > 0.05 | 无效 | 无预测能力 |

**Verify**:pytest 断言因子方向字段由 IC 结果推导,而非硬编码。

---

## M7. 反向因子用原始值算 Spearman IC

**What**:计算反向因子 IC 时使用原始因子值做 Spearman IC,不反转因子值。`ic_mean < 0` 表示反向因子有效。

**Why**:业界标准做法。反转因子值会导致字段语义混乱(`ic_mean` 永远为正但方向标记需另外维护)。

**How**:分层回测时通过 `factor_direction='negative'` 参数控制方向。

---

## M8. p 值显示格式

**What**:`p_value_display` 由 `_format_p_value()` 生成,回退值用 `round(x, 4)` (见 M27 必需 vs 可选字段)。

**How**:

```python
'p_value_display': result.get('p_value_display', str(round(result['p_value'], 6)))
```

---

## M9. ICIR 用 abs(ic_mean)

**What**:ICIR 计算 `abs(ic_mean) / ic_std`,无论正向反向因子。

**Why**:ICIR 表征"信号强度 / 波动",方向已由 ic_mean 符号承载,ICIR 应只反映强度。

---

## M10. Newey-West 滞后样本量

**What**:Newey-West 调整使用的样本量 T 是 `valid_days` (有效 IC 日期数),不是 `total_days` (含跳过日期)。

**Why**:跳过日期没有 IC 值,纳入 T 会让 t 统计量计算错误。

---

# C. 数据处理规则

## M11. DataFrame 入口先 `.copy()`

**What**:函数入口收到 DataFrame 参数后,**第一步**就 `.copy()`,再做任何修改。

**Why**:不 copy 直接修改会污染调用方的 DataFrame(副作用);列赋值后再 copy 已经晚了。

**How**:

```python
def calculate_factor(factor_df: pd.DataFrame):
    factor_df = factor_df.copy()  # 第一步
    factor_df['new_col'] = ...
    return factor_df
```

**Don't**:

```python
def calculate_factor(factor_df: pd.DataFrame):
    factor_df['factor_col'] = ...  # ❌ 已污染原数据
    factor_df = factor_df.copy()
    return factor_df
```

**例外**(无需 copy):函数只读、返回全新 DataFrame、内部已 copy。

---

## M12. 中间变量不污染输出

**What**:多步骤因子计算的中间结果(如 KDJ 的 rsv/k/d)用**局部变量**存,只把最终因子列写入输出 DataFrame。

**Why**:中间列会增加内存、干扰下游(IC 计算期望只有因子列)、输出结构不清晰。

**How**:

```python
def calculate_kdj_j(factor_df: pd.DataFrame):
    factor_df = factor_df.copy()
    rsv = ...                # 局部变量
    k = rsv.groupby(...).transform(...)
    d = k.groupby(...).transform(...)
    factor_df['kdj_j'] = 3 * k - 2 * d  # 只写最终因子列
    return factor_df  # 不含 rsv/k/d
```

**Don't**:

```python
factor_df['rsv'] = ...
factor_df['k'] = ...
factor_df['d'] = ...
factor_df['kdj_j'] = 3 * factor_df['k'] - 2 * factor_df['d']
return factor_df  # ❌ 含 rsv/k/d 中间列
```

---

## M13. numpy 与 pandas 不混用

**What**:对 pandas Series 操作时,使用 `Series.where()` / `Series.clip()`,不使用 `np.where()`。

**Why**:`np.where` 返回 ndarray,丢失 Series 的 index 和 metadata;赋值给 DataFrame 列时可能产生对齐问题。

**How**:

```python
safe_denom = denom.clip(lower=EPSILON)
result = (factor_df['close'] - lower) / safe_denom

narrow_mask = denom.abs() < EPSILON
result = result.where(~narrow_mask, 0.5)
```

**Don't**:

```python
# ❌ ndarray 丢失 index
result = np.where(np.abs(denom) < EPSILON, 0.5, (close - lower) / denom)
factor_df['result'] = result
```

---

## M14. EWM 初始值用虚拟值插入,不覆盖

**What**:EWM 需要初始值 (如 KDJ 的 K[t-1]=50) 时,在第一个有效输入**之前**插入一个虚拟值,而不是覆盖第一个有效输入。

**Why**:EWM 递推公式 `K[t] = α * RSV[t] + (1-α) * K[t-1]`,初始条件 `K[t-1] = initial_k` 是 t-1 期的虚拟值,不是 t 期的输入覆盖值。覆盖第一个有效输入会丢失真实数据。

**How**:

```python
rsv_with_initial = pd.concat([
    pd.Series([initial_k], index=[-1]),  # 虚拟初始值
    rsv_series
], ignore_index=True)

k_with_initial = rsv_with_initial.ewm(alpha=1/m, adjust=False, ignore_na=True).mean()
k_series = k_with_initial.iloc[1:]      # 移除虚拟初始
k_series.index = rsv_series.index
k_series = k_series.where(rsv_series.notna(), float('nan'))  # 恢复原 NaN
```

**Don't**:

```python
# ❌ 覆盖第一个有效值
rsv_copy[first_valid_idx] = initial_k
k_series = rsv_copy.ewm(...).mean()
```

**适用**:KDJ 的 K/D 计算 (initial=50);任何需要 EWM 从特定初始值开始递推的场景。

---

## M15. 异常检测优于静默修正

**What**:数据异常 (如 `band_width < 0`、`prev_close <= 0`) 应**检测并标记 NaN**,不要用 `.abs()` / `.clip()` 静默修正后参与计算。

**Why**:静默修正会产生符号和数值都错的结果,且无法追溯数据质量问题(比除零更难察觉)。

**How**:

```python
abnormal_mask = band_width < 0  # 理论上恒 ≥ 0,负值即异常
normal_band_width = band_width.clip(lower=EPSILON)
bollinger_pb = (close - lower) / normal_band_width
bollinger_pb = bollinger_pb.where(~abnormal_mask, np.nan)  # 异常 → NaN

if abnormal_mask.sum() > 0:
    logger.warning(f"检测到 {abnormal_mask.sum()} 个异常数据,已标记 NaN")
```

**Don't**:

```python
# ❌ .abs() 静默修正,符号和数值都错
safe_band_width = band_width.abs().clip(lower=EPSILON)
bollinger_pb = (close - lower) / safe_band_width
```

**适用**:布林带宽度 `< 0`、换手率 `< 0`、量比 `< 0`、股价 `≤ 0` 等。

---

## M16. 先排除异常再计算

**What**:用 `.mask(异常)` 把异常置 NaN 后再做 `.clip()` 和后续计算,而不是先 clip 再覆盖。

**Why**:先 clip 后覆盖是冗余计算(异常数据先算无意义值再覆盖)且掩盖意图。

**How**:

```python
# ✅ mask 先排除
safe_band_width = band_width.mask(abnormal_mask).clip(lower=EPSILON)
bollinger_pb = (close - lower) / safe_band_width
# 异常 → NaN,NaN / 任何 = NaN,无需后续覆盖
```

**Don't**:

```python
# ❌ 先 clip 计算,后用 .where 覆盖
safe_band_width = band_width.clip(lower=EPSILON)
bollinger_pb = (close - lower) / safe_band_width
bollinger_pb = bollinger_pb.where(~abnormal_mask, None)
```

---

## M17. 异常集合明确分离

**What**:多种异常的 mask 必须互斥,禁止包含关系。

**Why**:包含关系会导致异常被多次处理(冗余),且统计日志数量不准确。

**How**:

```python
# ✅ 明确互斥
abnormal_mask = band_width < 0
narrow_band_mask = (band_width >= 0) & (band_width < EPSILON)
# abnormal ∩ narrow = ∅
```

**Don't**:

```python
# ❌ narrow 包含 abnormal (负值 < EPSILON 同时被 narrow 命中)
abnormal_mask = band_width < 0
narrow_band_mask = band_width < EPSILON
```

---

## M18. 异常处理按优先级顺序

**What**:多种异常类型用 `.where()` 处理时,**先低后高**,让高优先级覆盖低优先级。

**Why**:意图清晰、不需要"排除"逻辑、新增异常类型只需追加一行。

**How**:

```python
# ✅ 优先级 1 (低):过窄 → 0.5
# 优先级 2 (高):异常负值 → NaN (覆盖上一步)
bollinger_pb = bollinger_pb.where(~narrow_band_mask, 0.5)
bollinger_pb = bollinger_pb.where(~abnormal_mask, np.nan)
```

**Don't**:

```python
# ❌ 高优先级先处理,低优先级需 | abnormal_mask 排除
bollinger_pb = bollinger_pb.where(~abnormal_mask, None)
bollinger_pb = bollinger_pb.where(~narrow_band_mask | abnormal_mask, 0.5)
```

---

# D. 异常与错误规则

## M19. 异常按类型分类处理

**What**:`except` 块按具体异常类型分开处理,保留原始异常类型信息,便于调用方差异化处理。

**Why**:统一 `except Exception` 会丢失异常类型,调用方无法判断错误类型;不同错误类型需要不同应对(数据采集/权限修复/重建缓存)。

**How**:

```python
try:
    factor_df, return_df, raw_metadata = load_factor_return_data(...)
except FileNotFoundError as e:
    raise RuntimeError(f"缓存文件不存在,请先运行数据采集: {e}") from e
except json.JSONDecodeError as e:
    raise RuntimeError(f"缓存文件损坏,请检查数据源: {e}") from e
except PermissionError as e:
    raise RuntimeError(f"缓存文件权限错误: {e}") from e
except KeyError as e:
    raise ValueError(f"缓存数据结构错误,缺少必需字段: {e}") from e
except Exception as e:
    raise RuntimeError(f"数据加载失败(未预期): {type(e).__name__}: {e}") from e
```

**Don't**:

```python
# ❌ 粒度过粗
except Exception as e:
    raise RuntimeError(f"数据加载失败: {e}") from e
```

**异常分类表**:

| 异常类型 | 语义 | 包装为 | 调用方应对 |
|---------|------|-------|-----------|
| FileNotFoundError | 缓存缺失 | RuntimeError | 先运行数据采集 |
| JSONDecodeError | 缓存损坏 | RuntimeError | 检查/重建缓存 |
| PermissionError | 权限错误 | RuntimeError | 检查权限 |
| KeyError | 数据结构错误 | ValueError | 检查数据采集 |
| ValueError | 参数/数据验证 | 直接 raise | 检查输入 |
| 其他 Exception | 未预期 | RuntimeError + 类型名 | 诊断堆栈 |

---

## M20. 异常链保留 `raise ... from e`

**What**:重新 raise 异常时必须用 `from e` 保留原始异常链。`ValueError` 不二次包装。

**Why**:丢失异常链会让调试时看不到根因。

**How**:

```python
try:
    load(path)
except FileNotFoundError as e:
    raise RuntimeError("加载失败") from e
```

**Verify**:ruff B904 自动检查。

---

## M21. 主入口异常友好提示

**What**:`if __name__ == '__main__'` 必须有 try-except,捕获后给用户友好提示,以 `sys.exit(1)` 退出。

**How**:

| 异常类型 | 用户提示 |
|---------|----------|
| FileNotFoundError | "缓存文件不存在,先运行数据缓存脚本" |
| ValueError | "数据验证失败,检查数据质量" |
| RuntimeError | "计算过程异常,查看日志" |

**Don't**:`except Exception: pass` 隐藏异常;`print(e)` 只打印异常对象;无 `sys.exit()` 继续执行。

---

## M22. CLI 异常按类别选择 `logger.error` 或 `logger.exception`

**What**:CLI 入口的 except 块按异常类别选择日志方法:
- **业务异常子类**(`FactorCalcError` 等可预期失败):`logger.error("...: %s", e)` 携带消息即可
- **未预期异常**(`except Exception`):`logger.exception()` 自动附加完整堆栈

**Why**:
- 业务异常是可预期的失败场景(数据缺失、参数非法、上游返回 None 等),错误消息已足够定位,堆栈是噪音
- 未预期异常(Bug、依赖故障)需要堆栈才能定位发生位置,必须用 `exception()`
- 区分捕获却做相同处理 = 分支划分失去意义,必须让两个分支的行为差异体现分类捕获的价值

**How**:

```python
if __name__ == '__main__':
    try:
        main()
    except FactorCalcError as e:
        # 业务异常:消息已足够定位,堆栈是噪音
        logger.error("计算失败: %s", e)
        sys.exit(1)
    except Exception:
        # 未预期异常:必须打印堆栈以便定位
        logger.exception("未预期的错误")
        sys.exit(1)
```

**Don't**:

```python
# ❌ 业务异常打堆栈(噪音):
except FactorCalcError:
    logger.exception("计算失败")

# ❌ 未预期异常不打堆栈(信息缺失):
except Exception as e:
    logger.error(f"未预期的错误: {e}")

# ❌ 两个分支行为完全相同(分类捕获失去意义):
except FactorCalcError:
    logger.exception("计算失败")
    sys.exit(1)
except Exception:
    logger.exception("未预期的错误")
    sys.exit(1)
```

**Verify**:
```bash
# 业务异常分支应用 logger.error
grep -A2 "except FactorCalcError" factor_ic/ic_*.py | grep -E "logger\.(error|exception)"
# 未预期异常分支应用 logger.exception
grep -A2 "except Exception" factor_ic/ic_*.py | grep -E "logger\.(error|exception)"
```

---

## M23. 错误信息含上下文 + 合法值 + 问题定位

**What**:`raise` 的错误信息必须包含:
1. 出错的具体值
2. 枚举类错误的合法值列表
3. 涉及函数返回值校验时,明确问题定位(模块路径)

**How**:

```python
# 枚举类
raise RuntimeError(
    f"未知模式: {mode}\n"
    f"合法值: ['skip', 'incremental', 'full']"
)

# 函数返回值校验
raise RuntimeError(
    f"calculate_ic_with_direction_verification 返回值缺少必需字段\n"
    f"缺失字段: {missing_fields}\n"
    f"问题定位: factor_ic/common/ic_calculator.py\n"
    f"期望字段: {required_fields}"
)

# 兜底块
except Exception as e:
    raise RuntimeError(
        f"未知错误: {path}, {type(e).__name__}: {e}"
    ) from e
```

---

# E. 输出契约规则

## M24. 输出结构两条路径完全一致

**What**:全量路径 (`build_ic_result`) 和增量路径 (`incremental_update_ic`) 必须返回**完全一致**的结构 —— 字段、嵌套、顺序、类型全部对齐。

**Why**:调用方按统一字段路径访问,接口不统一就需要 `.get()` 防御,代码冗余且易出 KeyError。

**How**:`ic_metrics` 五维度判断字段、`statistical_significance`(7 字段)、`factor_direction`、`economic_significance`、`icir_stability`、`ic_distribution_consistency` 在两条路径都必须出现。

**字段映射 (原始 → 输出)**:

| 字段组 | 原始字段 | 输出字段 | 说明 |
|-------|---------|---------|------|
| ic_metrics.* | 直接透传 | 同名 | 五项指标 |
| factor_direction.direction | `ic_mean_sign` | `direction` | 重映射 |
| economic_significance.ic_strength | `level` | `ic_strength` | 重映射 |
| economic_significance.ic_mean_abs | `abs_ic_mean` | `ic_mean_abs` | 重映射 |
| statistical_significance | 直接透传 | — | 字段名一致 |

**statistical_significance 必需字段 (7 个)**:`t_stat`, `p_value`, `p_value_display`, `nw_lag`, `nw_lag_method`, `is_significant`, `conclusion`。

**Verify**:pytest 断言两条路径返回 dict 的 keys 完全一致。

---

## M25. 字段去重(一字段一位置)

**What**:同一字段只在一处输出,不重复出现在多个嵌套字典。

**How**:

| 字段 | 唯一输出位置 |
|------|-------------|
| ic_mean, ic_std, icir | `ic_metrics` |
| p_value, t_stat, is_significant | `statistical_significance` |

---

## M26. 字典集中构建,不分散赋值

**What**:字段集中在字典字面量中定义,不要 `result = {}` 后逐字段赋值。

**How**:

```python
result = {
    'ic_mean': ic_mean,
    'ic_std': ic_std,
    'icir': icir,
    'update_mode': 'full',
}
```

**Don't**:

```python
result = {}
result['ic_mean'] = ic_mean
result['ic_std'] = ic_std
# ... 几十行后
result['update_mode'] = 'full'  # ❌ 容易重复赋值或遗漏
```

---

## M27. 必需 vs 可选字段区分

**What**:`required_fields` 校验列表**只包含必需字段**;可选字段(有 fallback 逻辑的)不进 required_fields,在使用处 `.get(default)`。

**Why**:把可选字段放进 required_fields 是矛盾设计:校验先报错,fallback 永远不触发。

**How**:

```python
# ✅ 必需字段 (p_value 必须有,p_value_display 可选)
required_fields = [
    'ic_series', 'ic_mean', 'ic_std', 'icir', 'p_value',  # p_value 必需
    'statistical_significance', 'factor_direction',
    'economic_significance', 'positive_ratio', 'summary',
]

# p_value_display 是可选,可从 p_value 计算
'p_value_display': result.get('p_value_display', str(round(result['p_value'], 6)))
```

**Don't**:

```python
required_fields = [..., 'p_value_display']  # ❌ 矛盾:校验会报错,fallback 永不触发
```

---

## M28. 函数返回值字段校验

**What**:任何代码直接 `result['field']` 访问之前,`field` 必须在 `required_fields` 中校验过。

**Why**:KeyError 错误信息无法判断问题模块;校验后的 RuntimeError 含模块路径,排查效率高。

**How**:

```python
required_fields = [
    'ic_series', 'ic_mean', 'ic_std', 'icir',
    'p_value', 'p_value_display',  # 必须包含所有后续直接访问的字段
    ...
]

missing_fields = [f for f in required_fields if f not in result]
if missing_fields:
    raise RuntimeError(
        f"返回值缺少必需字段\n"
        f"缺失字段: {missing_fields}\n"
        f"问题定位: factor_ic/common/ic_calculator.py"
    )

# 校验后安全访问
'p_value': round(result['p_value'], 6)
```

---

## M29. 输出字段口径明确

**What**:统计字段必须显式说明口径(基于哪个数据范围、是否 dropna 等)。

**Why**:同一字段(如 `total_days` vs `avg_stocks_per_day`)可能基于不同口径,数值差异需要在字段说明中清楚。

**How**:

```json
{
  "avg_stocks_per_day": 4235.2,
  "avg_stocks_period": {
    "start": "2024-01-01",
    "end": "2024-12-31",
    "description": "平均每日有效股票数统计范围"
  }
}
```

**口径区别**:
- `avg_stocks_per_day` 基于 dropna 后数据
- `total_days` 基于 dropna 前数据(原始缓存范围)

---

# F. 增量更新规则

## M30. 三模式 (skip/incremental/full)

**What**:所有因子脚本主函数必须处理 `UpdateMode.SKIP` / `INCREMENTAL` / `FULL` 三种模式,通过 `should_use_incremental()` 判断。

**判定流程**:

```
缓存不存在 → FULL
缓存存在 → 读取 existing_dates
  new_dates ⊆ existing → SKIP (返回缓存)
  new_dates 有缺失 → INCREMENTAL
--force-full → 强制 FULL
```

**How**:

```python
from factor_ic.common.incremental_engine import UpdateMode, should_use_incremental

mode = should_use_incremental(output_file, factor_df, force_full)

if mode == UpdateMode.SKIP:
    # 返回缓存数据,update_mode='skip'
elif mode == UpdateMode.INCREMENTAL:
    # 调用 incremental_update_ic, update_mode='incremental'
else:  # UpdateMode.FULL
    # 全量计算, update_mode='full'
```

**Don't**:
- ❌ 只处理 SKIP 模式,缺失 INCREMENTAL 分支
- ❌ 使用旧版 `should_use_incremental` 返回 bool

---

## M31. SKIP 模式不修改缓存对象

**What**:SKIP 模式读取缓存后**直接返回**,不修改 `cached_data` 任何字段。

**Why**:内存修改后未持久化 → 调用方拿到的数据与文件不一致,下次读取行为不可预测。SKIP 的语义就是"跳过任何修改"。

**How**:

```python
if mode == UpdateMode.SKIP:
    logger.info("[模式] 缓存已最新,跳过更新")
    with open(output_file, 'r', encoding='utf-8') as f:
        cached_data = json.load(f)
    return cached_data  # 直接返回,不修改
```

**Don't**:

```python
if mode == UpdateMode.SKIP:
    cached_data = json.load(f)
    cached_data['update_mode'] = 'skip'  # ❌ 内存修改但未持久化
    return cached_data
```

---

## M32. 增量 IC 计算用 `calculate_single_day_ic`

**What**:增量路径计算单日 IC 必须使用与全量路径相同的 `calculate_single_day_ic`,不可自行 `scipy.stats.spearmanr`。

**Why**:确保算法一致性,避免全量/增量结果偏差。

**等价性三重保障**:

| 层 | 机制 |
|---|------|
| 代码架构 | 共用同一函数,无法独立演化 |
| 单元测试 | `TestAlgorithmEquivalence` 验证等价性 |
| 文档规范 | 修改核心函数时检查等价性 |

---

## M33. 增量合并保留 None 值

**What**:增量路径合并 `existing` 和 `new` 数据时**不过滤 None**,所有日期都进 `date_ic_map`。

**Why**:过滤 None 会丢失"股票数不足跳过"日期,导致 `total_days = valid_days`,无法区分跳过日期的语义失真。

**How**:

```python
date_ic_map = {}
for date, ic in zip(existing_dates, existing_ic_values):
    date_ic_map[date] = ic  # 保留 None
for date, ic in zip(new_dates, new_ic_values):
    date_ic_map[date] = ic  # 保留 None

all_dates = sorted(date_ic_map.keys())
all_ic_values = [date_ic_map[d] for d in all_dates]  # 含 None

valid_ic_count = sum(1 for ic in all_ic_values if ic is not None)
none_ic_count = len(all_ic_values) - valid_ic_count

# total_days = len(all_dates)
# valid_days = valid_ic_count
# calculate_ic_statistics 自动过滤 None 计算 IC/ICIR
```

**Don't**:

```python
if ic is not None:  # ❌ 过滤 None → 丢失跳过日期
    date_ic_map[date] = ic
```

---

## M34. 旧缓存兼容

**What**:增量计算读取现有缓存时,对 `existing_ic_values` 中可能存在的 None 做兼容处理(因为 v1.32 之前可能未过滤)。

**How**:见 M33 实现;`existing` 和 `new` 都接受 None。

---

## M35. rolling_ic_mean 基于 all_dates

**What**:`rolling_ic_mean` 必须基于 `all_dates` (含所有日期,包括 None IC 日期) 计算,长度与 `dates`、`ic_values` 严格一致。

**Why**:基于 `valid_dates` 子集会导致长度错位,前端绘图按 index 对齐时位移。

**How**:

```python
ic_series = pd.Series(all_ic_values, index=all_dates)
rolling_ic_mean_series = ic_series.rolling(window=20, min_periods=10).mean()
rolling_ic_mean = [round(v, 6) if not pd.isna(v) else None for v in rolling_ic_mean_series.values]

merged_data = {
    'dates': all_dates,            # len = N
    'ic_values': all_ic_values,    # len = N
    'rolling_ic_mean': rolling_ic_mean,  # len = N
}
```

**Don't**:

```python
valid_dates = [all_dates[i] for i in valid_indices]
ic_series = pd.Series(valid_ic, index=valid_dates)  # ❌ 长度错位
```

---

## M36. period.start/end 用 raw_metadata

**What**:`period.start/end` 表示**原始缓存范围** (dropna 前),用 `raw_metadata['period_start/end']`,不用 `all_dates[0/-1]` 或 `factor_df['date'].min/max()`。

**Why**:`raw_metadata` 表示数据源范围(语义稳定),`all_dates` 是有效 IC 范围,语义不同。混用两者会让 period 语义模糊,且全量/增量路径不一致。

**How**:

```python
merged_data = {
    'period': {
        'start': raw_metadata['period_start'],  # 原始缓存
        'end': raw_metadata['period_end'],
    },
    'sample_stats': {
        'total_days': raw_metadata.get('total_days', 0),
        'valid_days': len(all_dates),
    },
}
```

**Don't**:

```python
# ❌ 用过滤后范围
'period': {'start': all_dates[0], 'end': all_dates[-1]}

# ❌ 混合语义
'period': {
    'start': min(all_dates[0], raw_metadata['period_start']),
    'end': max(all_dates[-1], raw_metadata['period_end']),
}

# ❌ 冗余 max 比较
'total_days': max(raw_metadata.get('total_days', 0), factor_df['date'].nunique())
```

---

## M37. 增量返回结构含全部字段

**What**:增量路径 (`incremental_update_ic`) 返回结构必须包含 `factor_stats`、`ic_metrics`、五维度判断字段等全部字段 + `update_mode='incremental'` + `incremental_days`。

**How**:见 M24 + 输出结构模板。增量额外字段:

```python
merged_data = {
    # ... 全量结构所有字段 ...
    'factor_stats': factor_stats,
    'update_mode': 'incremental',
    'incremental_days': len(new_dates),
}
```

---

## M38. 增量加载全量数据 + 边界检查

**What**:增量路径计算技术指标 (布林带/RSI/KDJ 等) 必须**加载全量数据**计算,再筛选缺失日期。同时检查缺失日期是否在预热期内 (前 N-1 天)。

**Why**:rolling(window=N) 计算需要前 N-1 天历史数据;缺失日期在预热期内时,因子值会全为 NaN。提前预警避免无效计算。

**How**:

```python
factor_df_full, return_df_full, raw_metadata = load_data_from_cache()
factor_df_full, factor_stats = calculate_bollinger_pb_1d_factor(factor_df_full, n=n, k=k)

# 边界检查
cache_start_date = raw_metadata['period_start']
cache_start_dt = pd.to_datetime(cache_start_date)
warmup_boundary = (cache_start_dt + pd.Timedelta(days=n-1)).strftime('%Y-%m-%d')
missing_in_warmup = [d for d in missing_dates if d <= warmup_boundary]

if missing_in_warmup:
    logger.info(f"[边界检查] 预热期: {cache_start_date} ~ {warmup_boundary} (前 {n-1} 天)")
    logger.info(f"[边界检查] {len(missing_in_warmup)} 个缺失日期在预热期内,因子值可能全 NaN")
    if len(missing_in_warmup) == len(missing_dates):
        logger.warning("[边界检查] 所有缺失日期都在预热期内,建议延长缓存历史范围")

# 筛选缺失日期
missing_set = set(missing_dates)
factor_df_new = factor_df_full[factor_df_full['date'].isin(missing_set)]
```

---

## M39. 增量因子值有效性检查

**What**:筛选 `factor_df_new` 后必须检查 `notna().sum()` —— 若全为 NaN,提前返回缓存并提供诊断信息。

**How**:

```python
factor_df_new = factor_df_full[factor_df_full['date'].isin(missing_set)]

valid_factor_count = factor_df_new['bollinger_pb_1d'].notna().sum()
total_factor_count = len(factor_df_new)

if valid_factor_count == 0:
    logger.warning("[诊断] 缺失日期因子值全为 NaN (可能因布林带预热期)")
    logger.warning(f"[诊断] 缺失日期示例: {sorted(factor_df_new['date'].unique())[:5]}")
    return existing_data

logger.info(f"  - 筛选后: {len(factor_df_new)} 行,其中 {valid_factor_count} 行有效因子值")
```

---

## M40. 增量向量化计算 IC

**What**:计算多日 IC 时**先整体 merge,再按日期 groupby**,禁止逐行循环做 DataFrame 过滤 + merge。

**Why**:逐行循环 DataFrame 过滤每次扫描全表 O(n);向量化 + groupby 性能提升约 N 倍。

**How**:

```python
new_dates = sorted(factor_df_new['date'].unique())
merged_new = factor_df_new.merge(return_df_new, on=['date', 'asset'], how='inner')

if merged_new.empty:
    new_ic_values = [None] * len(new_dates)
else:
    ic_results = {}
    for date, group in merged_new.groupby('date'):
        ic_value = calculate_single_day_ic(
            group, factor_col='bollinger_pb_1d', return_col='forward_return',
            min_stocks=min_stocks,
        )
        ic_results[date] = round(ic_value, 6) if ic_value is not None else None
    new_ic_values = [ic_results.get(date) for date in new_dates]
```

**Don't**:

```python
# ❌ 逐行循环 DataFrame 过滤
for date in new_dates:
    day_factor = factor_df_new[factor_df_new['date'] == date]  # 每次扫全表
    day_return = return_df_new[return_df_new['date'] == date]
    merged = day_factor.merge(day_return, on=['date', 'asset'], how='inner')
    ic_value = calculate_single_day_ic(merged, ...)
```

**性能对比**:N=100, n=100k 行时,向量化提升约 100×。

---

## M41. 三模式步骤编号 + fallback 用内部函数

**What**:
- 全量和增量模式步骤编号统一为 `[N/4]` 格式
- SKIP fallback (缓存读取失败时降级) 必须调用内部函数 `do_full_calculation()`,不要靠 mode 重置 + elif 链

**Why**:统一编号便于诊断;内部函数语义清晰,避免依赖控制流。

**How**:

```python
# 步骤编号统一 [N/4]
# [1/4] 数据加载  [2/4] 计算因子  [3/4] 计算 IC  [4/4] 构建输出并保存

# fallback 用内部函数
def do_full_calculation() -> dict:
    """全量计算 (FULL 模式 + SKIP fallback 共用)"""
    ...
    return result

if mode == UpdateMode.SKIP:
    try:
        return json.load(f)
    except FileNotFoundError:
        logger.warning("[诊断] 缓存文件不存在,执行全量计算")
        return do_full_calculation()

elif mode == UpdateMode.FULL:
    return do_full_calculation()
```

**Don't**:

```python
# ❌ mode 重置 + elif 链
if mode == UpdateMode.SKIP:
    try:
        ...
    except FileNotFoundError:
        mode = UpdateMode.FULL  # 隐式跳转
elif mode == UpdateMode.FULL:
    ...  # SKIP fallback 进这里,但读者要追踪 elif 链才能理解
```

**返回值标记规范**:

| 场景 | update_mode | 附加字段 |
|------|------------|---------|
| 正常 skip | 'skip' | — |
| SKIP fallback → full | 'full' | `fallback_event` |
| 正常 incremental | 'incremental' | `incremental_events` |
| 正常 full | 'full' | — |

调用方判断:`update_mode == 'full' and 'fallback_event' in result` → 意外触发全量。

---

# G. 数据类型与精度规则

## M42. 日期格式 YYYY-MM-DD 强制

**What**:所有日期字符串必须为 `YYYY-MM-DD`,生成 `period.start/end` 前必须验证。

**How**:

```python
DATE_FORMAT_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}$')

def validate_date_format(date_str: str) -> None:
    if not DATE_FORMAT_PATTERN.match(date_str):
        raise ValueError(f"日期格式错误: '{date_str}',期望 YYYY-MM-DD")
```

**适用**:读取缓存/IC 结果时、生成 period 前、增量合并后。

**Don't**:不验证格式就用 `min/max` 比较日期(字符串比较对非标准格式行为异常)。

---

## M43. ic_series.index 字符串 + 排序

**What**:
- `ic_series.index` 必须是字符串 `'YYYY-MM-DD'`,不用 datetime
- 必须显式 `sort_index()`,不依赖 pandas 隐式 sort

**Why**:
- datetime index:rolling 计算可能报错、JSON 序列化失败
- 不显式排序:rolling 按位置顺序,index 乱序 → dates 与 rolling_ic_mean 错位;增量合并后可能乱序

**How**:

```python
# 全量路径 load_data_from_cache
factor_df['date'] = date_series.dt.strftime('%Y-%m-%d')

# calculate_daily_ic_series 返回
dates = [str(d) for d in ic_series.index]

# 显式排序 + 校验
ic_series = ic_series.sort_index()
if dates != sorted(dates):
    raise RuntimeError("dates 未按升序排列")
```

**两条路径 index 类型一致性**:

| 路径 | index 来源 | 类型 | 保障 |
|------|-----------|------|------|
| 全量 | `load_data_from_cache` 显式转字符串 | str | 显式转换 |
| 增量 | JSON 缓存 + strftime | str | JSON 格式 |

---

## M44. NaN → None 在生成阶段转换

**What**:NaN 转 None 必须在**数据生成阶段** (在 ic_calculator.py / build_ic_result) 完成,而非在 JSON 序列化时。

**Why**:JSON 不支持 nan;None 表示"无有效数据"语义清晰。

**How**:

```python
# rolling_ic_mean 需要 pd.isna 检查 (前 min_periods-1 个为 NaN)
rolling_ic_mean = [
    round(v, 6) if not pd.isna(v) else None
    for v in rolling_mean.values
]

# ic_values 不需要 (ic_calculator.py 只追加 ic_value is not None 的日期)
```

全量路径和增量路径必须一致处理。

---

## M45. 浮点 Series 用 np.nan,不用 pd.NA

**What**:浮点 Series 的缺失值统一用 `np.nan` 或 `float('nan')`,不用 `pd.NA`。

**Why**:
- 构造时用 pd.NA → dtype 变 `object`,丢失矢量化能力
- `.where()` 用 pd.NA → 虽然 dtype 保持 float64,但风格不一致

**How**:

```python
# ✅ 构造和 .where() 都用 np.nan
s = pd.Series([np.nan, 1.0, 2.0])  # dtype: float64
s = s.where(s > 1.5, np.nan)
```

**pd.NA 适用**:nullable Int64/String/boolean Series(非浮点)。

---

## M46. 浮点等值用 EPSILON 容差

**What**:浮点除零判断/等值比较用 `np.abs(x) < EPSILON` (`EPSILON = 1e-10`),不用 `== 0`。

**Why**:IEEE 754 运算累积误差可能产生 1e-15 等极小值,`== 0` 漏判后做分母会产生 1e15 极端值。

**How**:

```python
EPSILON = 1e-10  # 见 M47 模块级常量

diff = upper_band - lower_band
result = np.where(
    np.abs(diff) < EPSILON,
    0.5,
    (close - lower_band) / diff
)
```

**精度容差选择**:

| 场景 | 容差 |
|------|------|
| 价格数据除零 | 1e-10 |
| 数值通用 | 1e-9 |
| 高精度计算 | 1e-12 |

---

## M47. 常量提到模块级

**What**:`EPSILON` / `DEFAULT_MIN_STOCKS=10` / `DEFAULT_IC_THRESHOLD=0.03` / `DEFAULT_P_THRESHOLD=0.05` 等阈值/精度参数定义为**模块级常量**,不写在函数内。

**Why**:复用、维护、命名规范(`EPSILON` vs `epsilon`)、可独立测试。

**How**:

```python
# 模块顶部
EPSILON = 1e-10
DEFAULT_MIN_STOCKS = 10

def calculate_bollinger_pb(factor_df):
    safe_band_width = band_width.clip(lower=EPSILON)
    ...
```

参数通过函数签名传递,禁止用全局变量传参。

---

# H. 技术指标参数规则

## M48. rolling "过去几日"不含当日

**What**:计算"过去 N 日"均值/标准差等指标时,用 `series.shift(1).rolling(N)`,不用 `series.rolling(N)`。

**Why**:`rolling(N)` 包含当日 → 当日值同时出现在分子分母,因子值被稀释,无法正确反映"突增"语义。

**How**:

```python
# ✅ shift(1) 排除当日
avg_turnover = turnover_rate.shift(1).rolling(surge_window, min_periods=surge_window).mean()
turnover_surge = turnover_rate / avg_turnover
```

**Don't**:

```python
# ❌ 包含当日 → 稀释
avg_turnover = turnover_rate.rolling(surge_window, min_periods=surge_window).mean()
turnover_surge = turnover_rate / avg_turnover
```

**适用**:换手率突增、均值比较类因子、任何"当日 vs 历史"对比。

---

## M49. rolling min_periods 选择

**What**:`min_periods` 默认应等于 `window` (高质量要求);除非有明确业务理由,禁止 `min_periods=1`。

| min_periods | 适用场景 |
|-------------|---------|
| `= window` | 高质量,拒绝不完整数据(布林带、KDJ 等技术指标) |
| `= window // 2` | 平衡质量和覆盖度 |
| `= 1` | ❌ 早期数据质量极差,禁用 |

业务决策(如"新上市股票数据不足时如何处理")必须在注释中说明影响。

---

## M50. 布林带规范

**What**:
1. 标准差使用 `ddof=0` (总体标准差),不是默认的 ddof=1 (样本标准差)
2. 固定加载 `'close'` 列,不接受 `factor_col` 参数
3. `%B` 计算显式处理 NaN,不依赖隐式传播
4. `min_periods=window=N` (前 N-1 期为 NaN,等待足够数据)

**Why**:
- ddof=1 系统性高估带宽约 2.5% (N=20 时),%B 失真;业界 (TradingView/MetaTrader) 均用 ddof=0
- 布林带数学定义就是 close,接受 factor_col 参数会误导
- NaN 隐式传播 (`NaN < 1e-10 → False`) 极易出错

**How**:

```python
# 固定 close 列
def load_data_from_cache(return_col: str = 'forward_return_1d'):
    factor_cols = ['date', 'asset', 'close']
    factor_df = factor_df[factor_cols].copy()
    factor_df = factor_df.dropna(subset=['close']).reset_index(drop=True)
    return factor_df, return_df, raw_metadata

# ddof=0 + min_periods=n
factor_df['middle_band'] = factor_df.groupby('asset')['close'].transform(
    lambda x: x.rolling(window=n, min_periods=n).mean()
)
factor_df['std_dev'] = factor_df.groupby('asset')['close'].transform(
    lambda x: x.rolling(window=n, min_periods=n).std(ddof=0)
)

# %B 显式处理 NaN
diff = factor_df['upper_band'] - factor_df['lower_band']
factor_df['bollinger_pb_1d'] = np.where(
    pd.isna(diff),  # 预热期 NaN
    np.nan,
    np.where(
        np.abs(diff) < EPSILON,  # 带宽为零
        0.5,
        (factor_df['close'] - factor_df['lower_band']) / diff
    )
)
```

---

## M51. KDJ ewm 参数

**What**:KDJ 的 `alpha = 1/m` (不是 `(m-1)/m`),`ignore_na=False`,first_valid_index 用 `series[idx]` 不用 `iloc[0]`。

**Why**:`ewm` 公式 `y[t] = α·x[t] + (1-α)·y[t-1]`,KDJ 公式 `K[t] = (1/m)·RSV[t] + (m-1)/m·K[t-1]`,要匹配 α=1/m。

| 参数 | 错误 | 正确 | 原因 |
|------|------|------|------|
| alpha | `(m-1)/m` | `1/m` | 匹配 KDJ 公式 |
| ignore_na | True | False | False 使 NaN 传播,前 N-1 期 K 也为 NaN |
| first_valid | `iloc[0]` | `series[idx]` | iloc[0] 不一定是第一个有效值 |

**How**:

```python
first_valid_idx = rsv_series.first_valid_index()
initial_rsv = rsv_series[first_valid_idx]

k_series = rsv_copy.ewm(alpha=1/m, adjust=False, ignore_na=False).mean()
```

---

## M52. 极端值裁剪范围与筛选一致

**What**:极端值裁剪的范围必须与筛选条件一致:裁剪下界 ≥ 筛选下界;裁剪上界 ≤ 筛选上界。

**Why**:不一致会导致筛选条件失效或冗余。

**How**:

| 筛选条件 | 裁剪规则 |
|---------|---------|
| `factor > X` | 裁剪下界 ≥ X (如 `turnover_surge > 1` → `clip(1.0, 10)`) |
| `factor < Y` | 裁剪上界 ≤ Y |
| 无筛选 | 按业务逻辑 |

---

# I. 数据校验规则

## M53. 计算前数据校验 (新因子必校)

**What**:新因子计算 IC 前必须校验所需数据:必需列存在、数据日期范围、有效数据量 ≥ 100、收益数据存在。校验失败抛 ValueError 并附详细提示。

**Why**:防止数据缺失静默失败,提前给出可操作的错误信息。

**How**:

```python
def calculate_xxx(factor_df, logger=None):
    """因子计算(含数据校验)"""
    # 1. 必需列校验
    required_cols = ['close', 'turnover_rate']
    missing_cols = [col for col in required_cols if col not in factor_df.columns]
    if missing_cols:
        raise ValueError(
            f"数据校验失败:缺失必需列 {missing_cols}\n"
            f"实际列: {list(factor_df.columns)}\n"
            f"请检查 data_fetchers/result/factor_ic_data.json.gz 是否包含所需列"
        )

    # 2. 有效数据量校验
    valid_rows = factor_df[required_cols].dropna().shape[0]
    if valid_rows < 100:
        raise ValueError(
            f"数据校验失败:有效数据量不足\n"
            f"期望 ≥ 100 行,实际 {valid_rows} 行\n"
            f"请检查数据源质量"
        )

    # 3. 继续因子计算...
```

**校验内容表**:

| 校验项 | 校验方式 | 不满足时 |
|-------|---------|---------|
| 必需列存在 | `factor_df.columns` 含 `factor_cols` | 停 + 缺失列名 |
| 数据日期范围 | `dates` 覆盖计算周期 | 停 + 范围不足 |
| 有效数据量 | dropna 后 ≥ 100 | 停 + 量不足 |
| 收益数据存在 | `forward_return_1d` 列存在且非空 | 停 + 缺失提示 |

---

## M54. 输入列存在检查

**What**:在 IC 计算流程内,数据加载后立即校验必需列存在。

**How**:

```python
REQUIRED_COLUMNS = ['date', 'symbol', 'factor_value', 'future_return']

def validate_columns(df: pd.DataFrame) -> None:
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"数据缺少必需列: {missing}")
```

---

## M55. 列表索引访问前检查长度 + 数据对齐验证

**What**:
1. 访问 `list[0]` / `list[-1]` 前检查 `len(list) > 0`,防 IndexError
2. merge 后必须验证日期对齐,避免静默丢数据

**Why**:增量路径合并后 `all_dates` 可能为空(现有缓存为空 + 新日期无有效数据);merge 默认行为可能丢数据。

**How**:

```python
# 列表长度检查
if len(all_dates) == 0:
    logger.warning("[警告] 合并后无有效日期,跳过日期格式检查")
    dates_to_check = [raw_metadata['period_start'], raw_metadata['period_end']]
else:
    dates_to_check = [all_dates[0], all_dates[-1],
                      raw_metadata['period_start'], raw_metadata['period_end']]

# 数据对齐验证
factor_dates = set(factor_df['date'].unique())
return_dates = set(return_df['date'].unique())
missing_in_return = factor_dates - return_dates
if missing_in_return:
    raise ValueError(f"因子数据有 {len(missing_in_return)} 个日期在收益数据中不存在")
```

**适用**:load_data_from_cache、calculate_ic 前、merge 后、增量更新时。

---

# J. 代码风格规则

## M56. PEP8 import 顶部 + 未使用清理

**What**:
1. 所有 `import` 在文件顶部,禁函数内 import(除非避免循环依赖)
2. 未使用的导入必须删除

**Why**:
- 函数内 import 违反 PEP8,降低可读性,每次调用都走 import 查找
- 未使用导入误导读者以为有依赖,代码审计浪费时间

**How**:

```python
# 顶部统一导入同一模块的所有函数
from factor_ic.common.ic_calculator import (
    calculate_ic_with_direction_verification,
    calculate_single_day_ic,
    calculate_ic_statistics,
)

def _incremental_update(...):
    result = calculate_ic_statistics(ic_series)  # 已在顶部导入
```

**Don't**:

```python
def _incremental_update(...):
    from factor_ic.common.ic_calculator import calculate_ic_statistics  # ❌ 函数内
```

**典型清理场景**:

| 场景 | 旧导入 | 新导入 | 清理 |
|------|--------|--------|------|
| 函数替代 | `check_data_completeness` | `should_use_incremental` | 删旧 |
| 模块重构 | `from old_module import func` | `from new_module import func` | 删旧 |
| 功能移除 | `from module import deprecated_func` | 无 | 删整个 import |

---

## M57. 注释缩进与代码一致

**What**:函数内/类内/循环条件块内注释的缩进必须与代码块一致,避免顶格注释造成视觉歧义。

**How**:

```python
def _incremental_update(...):
    # 计算 IC
    for date in new_dates:
        ic_value = calculate_single_day_ic(...)

    # 合并数据  ← 4 空格缩进,与函数体一致
    print("合并数据并重新计算统计指标...")
```

**Don't**:

```python
def _incremental_update(...):
    # 计算 IC
    for date in new_dates:
        ...

# 合并数据  ← ❌ 顶格,视觉上像在函数外
    print("合并数据...")
```

---

## M58. 字典缩进一致

**What**:多层字典的缩进按层级(8/12/16 空格),闭合括号与同级字段对齐。

**How**:

```python
merged_data = {
    'factor_name': 'bollinger_pb_1d',  # 8 空格
    'ic_metrics': {                    # 8 空格
        'ic_mean': 0.05,               # 12 空格
        'ic_std': 0.15,                # 12 空格
    },                                 # 8 空格
    'sample_stats': {                  # 8 空格
        'total_days': 545,             # 12 空格
    },                                 # 8 空格
}
```

---

## M59. 变量名含数据源前缀

**What**:变量名必须包含数据源前缀(price/turnover/volume 等),避免模糊命名。

| 场景 | 模糊(禁止) | 正确 |
|------|----------|------|
| 收盘价涨跌幅 | `pct_change` | `price_pct_change` |
| 换手率变化率 | `pct_change` | `turnover_pct_change` |
| 均值 | `ma` | `turnover_ma_5` |

---

## M60. 函数参数无冗余

**What**:函数签名不应有冗余参数 —— 每个参数必须有实际用途(被实际传入或有明确默认值语义)。

**Why**:永远不被传入、永远使用默认值的参数是死参数,增加 API 复杂度且误导调用方。

**How**:

```python
# ✅ 删除冗余,直接用已有数据
def calculate_daily_ic_series(factor_df, return_df, raw_metadata, min_stocks=10):
    period_start = raw_metadata['period_start']  # 直接用
```

**Don't**:

```python
# ❌ period_start/end 永远不被传入,永远使用默认值
def calculate_daily_ic_series(
    factor_df, return_df, raw_metadata, min_stocks=10,
    period_start=None,  # 永远不传入
    period_end=None,    # 永远不传入
):
    if period_start is None:  # 永远为 True
        period_start = str(factor_df['date'].min())
```

**设计原则**:
1. 参数必要性:每个参数必须被实际传入或有明确默认值语义
2. 数据源优先:已有数据结构包含的信息,直接使用,不加额外参数
3. 语义一致性:参数语义应与数据源一致
4. 接口简洁:避免不必要的复杂度

---

## M61. 函数签名变更同步

**What**:修改函数返回值/参数时必须同步更新**类型注解**和 **docstring**。

**Why**:文档与实现不一致是调用方错误的常见来源。

**How**:

```python
def load_data_from_cache(...) -> Tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    Returns:
        factor_df: 过滤后因子数据
        return_df: 过滤后收益数据
        raw_metadata: 原始数据范围信息(新增)
    """
```

**Don't**:只改返回值不改类型注解 / 不改 docstring。

---

## M62. 参数类型统一 Path

**What**:`output_file` 等路径参数统一在入口处转为 `Path` 对象。

**Why**:Path 可安全使用 `.parent.mkdir()` 等方法;str 需额外处理;统一类型避免后续类型判断。

**How**:

```python
def generate_rsi_ic_data(output_file=None):
    if output_file is None:
        output_file = get_ic_output_path('rsi_1d')  # 返回 Path
    else:
        output_file = Path(output_file)  # str → Path
```

---

# K. 路径对称与同步规则

## M63. 全量与增量防御对称

**What**:防御性检查(日期格式断言、类型校验、边界检查)必须在全量和增量路径**都执行**,不能只在一条路径。

**Why**:不对称会让某条路径通过错误数据,产生下游问题且调试时难定位"为什么只有一条路径报错"。

**How**:

```python
# 全量路径 calculate_daily_ic_series
dates = [str(d) for d in ic_series.index]
dates_to_check = [
    dates[0] if len(dates) > 0 else None,
    dates[-1] if len(dates) > 0 else None,
    period_start, period_end,
]
for d in dates_to_check:
    if d is not None and not re.match(r'^\d{4}-\d{2}-\d{2}$', str(d)):
        raise ValueError(f"日期格式不符合 YYYY-MM-DD 约定: {d}")

# 增量路径 _incremental_update
dates_to_check = [
    all_dates[0], all_dates[-1],
    raw_metadata['period_start'], raw_metadata['period_end'],
]
for d in dates_to_check:
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', str(d)):
        raise ValueError(f"日期格式不符合 YYYY-MM-DD 约定: {d}")
```

**适用**:日期格式断言、数据类型校验、边界检查、任何防御性编程。

---

## M64. 全量/增量等价性三重保障

**What**:全量计算与增量计算的算法一致性,必须通过三层机制保障。

| 保障层 | 机制 | 说明 |
|-------|------|------|
| 1. 代码架构 | 共用 `calculate_single_day_ic` | 设计上无法独立演化 |
| 2. 单元测试 | `TestAlgorithmEquivalence` | 单日、多日、边界等价性 |
| 3. 文档规范 | 本规则 + M32 | 修改核心函数时检查等价性 |

**Verify**:`tests/test_algorithm_equivalence.py` 必须存在并通过。

---

## M65. 设计演进清理 + 代码维护同步

**What**:
1. 新实现替代旧实现后,**立即删除旧代码**,禁止保留死代码
2. 新增代码后,主动检查旧代码是否冗余 (重复赋值、可合并函数、冗余分支、可常量化的硬编码)

**Why**:死代码误导读者以为有两条路径可选;不同步检查会让旧代码与新实现产生偏差。

**How**:

```python
# ✅ 向量化版本替代循环版本后,删除旧函数
def calculate_all_stocks_vectorized(factor_df):
    return factor_df.groupby('asset').transform(...)

# 旧版本已删除:
# def calculate_single_stock(stock_df): ...
```

**Don't**:

```python
def calculate_single_stock(stock_df):  # ❌ 死代码,从未被调用
    """单股票版本(已被向量化版本替代)"""
    return stock_df.rolling(20).mean()

def calculate_all_stocks_vectorized(factor_df):  # 实际使用
    return factor_df.groupby('asset').transform(...)
```

**清理 checklist**:

```
□ 新增字段 → 检查是否有重复赋值
□ 新增函数 → 检查是否有类似功能函数可合并
□ 新增逻辑 → 检查是否有冗余分支
□ 新增参数 → 检查是否有硬编码值可替换
□ 重构后 → 删除被替代的旧函数,不留死代码
```

---

## 更新记录

| 版本 | 日期 | 主要变更 |
|------|------|---------|
| v4.4 | 2026-06-15 | 新增 M3.3 factor_cols 声明式注册 + 运行时列校验(FactorSpec + DataSchemaError + run_factor_ic 统一入口,34 脚本迁移完成) |
| v4.3 | 2026-06-15 | 新增 M3.2 入口启动日志收口至公共模块横幅(34 脚本统一,配套 `factor_ic_runner.extra_log_params` 参数) |
| v4.2 | 2026-06-15 | 新增 M3.1 主职责日志输出公共函数:logger 强制必传(M3 特例细化,配套 `factor_summary_logger.py`) |
| v4.1 | 2026-06-12 | 新增行业方向性因子IC脚本注册表(industry_momentum_5d / industry_turnover_trend / industry_amplitude_trend);脚本注册表章节 | [experimental] |
| v4.0 | 2026-06-03 | 大重构:58 章节去重合并到 65 条 M 编号规则,按 11 类别 (A-K) 组织,每条套用 What/Why/How/Don't/When/Verify 框架;加目录索引;精简更新记录 |
| v3.16 | 2026-06-02 | 新因子数据校验规范 (M53) |
| v3.10-v3.15 | 2026-05-22~28 | 累积补充:pandas 缺失值标记、股价异常检测、rolling 语义、布林带、向量化、边界检查、防御对称、可选字段回退等规范 |
| v3.0-v3.9 | 2026-05-22~23 | 大规模精简 + 多个技术陷阱规范 (EWM 初值、中间变量污染、CLI 堆栈、SKIP 缓存、主函数异常分类) |
| v2.0-v2.6 | 2026-05-22 | 按主题归类为 6 大章节;新增公共模块架构、ic_result_builder、incremental_engine、factor_ic_runner 规范;5 个因子脚本重构 (平均 -72% 代码量);新增"职责边界规范" |
| v1.0-v1.4 | 2026-05-21~22 | 首次创建;统一 statistical_significance 字段定义;合并重复章节 |

---

## 引用说明

本文档定义 `factor_ic/` 目录下所有 IC 计算脚本的开发规范。

**相关文档**:
- 项目级规范:`PROJECT.md` (目录结构、开发检查清单)
- 流程文档:`factor_ic/docs/ic_<因子名>_<周期>_flow.md`
- 公共函数:`factor_ic/common/` 模块
- 公共模块说明:`factor_ic/common/README.md`

---

*最后更新: 2026-06-15*

