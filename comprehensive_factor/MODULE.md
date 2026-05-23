# comprehensive_factor 模块规范

> 本文档定义 comprehensive_factor/ 目录下综合因子计算脚本的开发规范。
> 创建时间: 2026-05-24
> 版本: v1.1（新增完整流程说明）

---

## 综合因子构建完整流程

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Step 1: 单一因子分析                              │
├─────────────────────────────────────────────────────────────────────┤
│  ├─ Percentile 分层回测 → 多空年化收益、夏普比率、单调性              │
│  └─ 计算 IC 序列 → IC均值、ICIR、每日IC值                            │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│                    Step 2: 因子筛选                                  │
├─────────────────────────────────────────────────────────────────────┤
│  ├─ 计算所有因子两两相关性矩阵                                        │
│  ├─ 无效因子（IC不显著、单调性差）→ 直接丢弃                          │
│  ├─ 高相关组（|corr|>0.7）→ 只保留最强的                             │
│  └─ 保留下来的因子 → 两两低相关                                       │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│                    Step 3: 标准化                                    │
├─────────────────────────────────────────────────────────────────────┤
│  每日截面标准化：factor_std = (factor - μ) / σ                       │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│                    Step 4: 加权计算综合因子                           │
├─────────────────────────────────────────────────────────────────────┤
│  ├─ 等权（equal_weight）                                             │
│  ├─ ICIR加权（icir_weight）                                          │
│  ├─ IC加权（ic_weight）                                              │
│  └─ 滚动ICIR加权（rolling_icir_weight）                              │
│  → 得到 4 个综合因子                                                 │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│                    Step 5: 综合因子分层回测                          │
├─────────────────────────────────────────────────────────────────────┤
│  对 4 个综合因子分别做分层回测 → 选择最优方案                         │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 概述

comprehensive_factor 模块负责将多个单因子按加权方式组合成综合因子，并调用 backtest 模块进行分层回测。

**模块定位：**
- 输入：factor_ic 的 IC 结果 + 单因子值（从 cache 或 backtest 结果）
- 处理：加权计算综合因子值
- 输出：综合因子分层回测结果

---

## 脚本命名

**格式：** `composite_<加权方式>_<收益周期>.py`

**加权方式标识：**

| 加权方式 | 标识 | 说明 |
|---------|------|------|
| 等权 | equal_weight | 所有因子权重相等 |
| ICIR加权 | icir_weight | 权重 = ICIR / sum(ICIR) |
| 滚动ICIR加权 | rolling_icir_weight | 滚动窗口（如60日）ICIR加权 |
| IC加权 | ic_weight | 权重 = IC均值 / sum(IC均值) |

**示例：**
- `composite_equal_weight_1d.py` — 等权综合因子
- `composite_icir_weight_1d.py` — ICIR加权综合因子
- `composite_rolling_icir_weight_1d.py` — 滚动ICIR加权
- `composite_ic_weight_1d.py` — IC加权综合因子

**命名规则来源：** 与 factor_ic、backtest 模块命名规则保持一致。

---

## 加权方式规范

### 1. 等权（Equal Weight）

```python
weight = 1 / n_factors  # 每个因子权重相等
composite_factor = sum(w_i * factor_i)  # 加权求和
```

**适用场景：** 因子数量较少，无先验IC信息时默认方案。

### 2. ICIR加权（静态）

```python
weight_i = ICIR_i / sum(ICIR_j)  # ICIR越高权重越大
composite_factor = sum(w_i * factor_i)
```

**数据来源：** `factor_ic/result/*.json` 的 `icir` 字段

**适用场景：** 已知历史ICIR，全样本静态加权。

**权重公式：**
$$w_i = \frac{ICIR_i}{\sum_j ICIR_j}$$

### 3. 滚动ICIR加权（动态）

```python
# 每日计算滚动窗口（如60日）内的ICIR
rolling_icir_t = calc_rolling_icir(ic_series, window=60)
weight_i_t = rolling_icir_i_t / sum(rolling_icir_j_t)
composite_factor_t = sum(w_i_t * factor_i_t)
```

**数据来源：** factor_ic 的每日IC序列（需从 `result/*_daily.json.gz` 加载）

**适用场景：** 因子有效性随时间变化，动态调整权重。

**滚动窗口参数：**
- 默认窗口：60日（可配置）
- 最小窗口：20日（数据不足时回退到静态ICIR）

### 4. IC加权（静态）

```python
weight_i = ic_mean_i / sum(ic_mean_j)  # IC均值越高权重越大
composite_factor = sum(w_i * factor_i)
```

**数据来源：** `factor_ic/result/*.json` 的 `ic_mean` 字段

**适用场景：** 简化版ICIR加权，忽略波动性。

---

## 因子标准化规范

**加权前必须标准化因子值：**

```python
# 每日对每个因子做截面标准化
factor_standardized = (factor - factor.mean()) / factor.std()
```

**原因：**
- 不同因子值范围不同（RSI: 0-100, Volume_Ratio: 0.1-5）
- 未标准化会导致高值因子主导组合

**标准化时机：** 加权计算前，在 `composite_runner` 中统一处理。

---

## 因子相关性过滤规范

**组合因子前必须检查相关性：**

| 组合 | 相关系数 | 建议 |
|------|---------|------|
| Volume_Ratio vs Turnover_Surge | 0.99 | 只选其一（等价） |
| RSI vs Bollinger_PB | 0.94 | 只选其一（等价） |
| Volume_Ratio vs RSI | 0.30 | ✓ 可组合（低相关） |
| Volume_Ratio vs Bollinger_PB | 0.27 | ✓ 可组合（低相关） |

**预设低相关组合：**
- 流动性因子（Volume_Ratio） + 技术指标因子（RSI 或 Bollinger_PB，选其一）

**高相关因子处理规则：**
```python
if corr > 0.7:
    # 选择ICIR更高的因子保留
    keep_factor = factor_with_max_icir([factor_a, factor_b])
```

---

## 公共模块复用（强制）

**遵循 PROJECT.md 模块边界规范：只复用 comprehensive_factor/common/ 下的模块。**

### 必须复用的公共模块

| 功能 | 公共模块路径 | 说明 |
|------|-------------|------|
| 因子数据加载 | `comprehensive_factor.common.factor_loader` | 从factor_ic/backtest结果加载因子值 |
| 加权计算 | `comprehensive_factor.common.weight_engine` | 等权/ICIR/滚动ICIR/IC加权引擎 |
| 公共入口 | `comprehensive_factor.common.composite_runner` | 调用backtest分层回测 |
| 日志配置 | `comprehensive_factor.common.logger_config` | get_logger函数 |
| 类型转换 | `comprehensive_factor.common.convert_types` | numpy/pandas → Python原生类型 |

### 禁止手写的逻辑

| 逻辑 | 正确方式 | 错误方式 |
|------|---------|---------|
| 因子加载 | `load_factor_values()` | 手写 gzip.open + json.load |
| IC结果加载 | `load_ic_results()` | 手写 json.load |
| 加权计算 | `WeightEngine.calculate()` | 手写权重循环 |
| 分层回测 | `run_composite_backtest()` | 手写分层逻辑 |

---

## 输出目录规范

**综合因子结果输出位置：** `comprehensive_factor/result/`

**输出文件命名：** `<脚本名>.json`

**输出结构：**

```json
{
  "meta": {
    "weight_method": "icir_weight",
    "return_period": "1d",
    "factor_list": ["rsi", "volume_ratio_5"],
    "weights": {
      "rsi": 0.35,
      "volume_ratio_5": 0.65
    },
    "ic_results": {
      "rsi": {"ic_mean": -0.032, "icir": -0.45},
      "volume_ratio_5": {"ic_mean": -0.058, "icir": -1.97}
    },
    "correlation_matrix": {
      "rsi_vs_volume_ratio_5": 0.30
    },
    "n_factors": 2,
    "composite_factor_range": [-2.5, 2.8]
  },
  "backtest_result": {
    // 复用 backtest 输出结构
    "meta": {...},
    "layer_stats": [...],
    "long_short": {...},
    "monotonicity": {...},
    "trading_cost_analysis": {...}
  },
  "config": {
    "n_layers": 5,
    "factor_direction": "negative",
    "long_layers": [1, 2],
    "short_layers": [4, 5],
    "trade_cost_rate": 0.003
  },
  "created_at": "2026-05-24T..."
}
```

---

## 日志规范

**遵循 PROJECT.md 项目级日志规范。**

核心要点：
- 使用 Python 标准库 `logging` 模块
- 导入方式：`from comprehensive_factor.common.logger_config import get_logger`
- 日志路径：`comprehensive_factor/logs/*.log`

---

## Config 配置规范

**综合因子分层回测 Config 类：**

```python
from dataclasses import dataclass, field
from typing import List, Dict

@dataclass
class CompositeLayerConfig:
    """综合因子分层配置
    
    综合因子默认为反向因子（低值预期高收益），
    因为低相关性组合中流动性因子（缩量）+ 技术指标（超卖）都指向反向逻辑。
    """
    n_layers: int = 5
    factor_direction: str = 'negative'  # 综合因子默认反向
    long_layers: List[int] = field(default_factory=lambda: [1, 2])
    short_layers: List[int] = field(default_factory=lambda: [4, 5])
    trade_cost_rate: float = 0.003
    min_stocks_per_layer: int = 10
    
    # 因子组合参数
    factor_list: List[str] = field(default_factory=lambda: ['rsi', 'volume_ratio_5'])
    rolling_window: int = 60  # 滚动ICIR窗口（仅rolling_icir使用）
    
    def validate(self) -> None:
        """校验配置完整性"""
        if self.n_layers < 2:
            raise ValueError(f"n_layers 至少需要 2 层，当前: {self.n_layers}")
        if not self.factor_list:
            raise ValueError("factor_list 不能为空")
```

---

## 新加权方式扩展规范

**添加新加权方式时：**

```
□ 在 weight_engine.py 新增加权方法类（继承 WeightMethodBase）
□ 在 MODULE.md 加权方式章节新增说明
□ 新建脚本 composite_<新方式>_1d.py
□ 新建测试用例 test_cases/<新方式>_test_cases.py
□ 运行脚本验证
□ 更新 MODULE.md 版本号
```

---

## 因子数据来源规范

**因子值加载路径：**

| 数据类型 | 来源路径 | 加载方式 |
|---------|---------|---------|
| 因子原始值 | `cache/factor_data/factor_data.json.gz` | `factor_loader.load_factor_values()` |
| IC统计结果 | `factor_ic/result/*.json` | `factor_loader.load_ic_results()` |
| IC每日序列 | `factor_ic/result/*_daily.json.gz` | `factor_loader.load_ic_daily()` |

---

## 调用 backtest 规范

**综合因子计算完成后，调用 backtest 分层回测：**

```python
from backtest.common.layered_backtest_runner import run_layered_backtest

# 将综合因子添加到 factor_df
factor_df['composite_factor'] = composite_factor_values

# 调用分层回测
result = run_layered_backtest(
    factor_name=f'{weight_method}_composite',
    factor_col='composite_factor',
    config=config,
    cache_dir=cache_dir,
    output_dir=output_dir,
    logger=logger
)
```

**注意：** 不重新加载 backtest 的公共模块，直接调用 `run_layered_backtest` 函数。

---

## 版本历史

| 版本 | 日期 | 变更内容 |
|------|------|---------|
| v1.0 | 2026-05-24 | 初始设计：目录结构、脚本命名、加权方式、公共模块、输出规范 |