# 设计文档：可扩展中性化框架（行业 + 市值 + 未来风格因子）

| 字段 | 值 |
|------|-----|
| 状态 | 起草中 |
| 起草日期 | 2026-06-18 |
| 范围 | factor_ic 模块中性化引擎重构 + 市值中性化接入 + 输出 schema 演进 |
| 实施分期 | P1 架构重构（不变功能） → P2 加 LogMarketCapProvider → P3 默认开启联合中性化 → P4 下游迁移 + 老字段下线 |
| 入口审核 | 待审核 |

## 目录

1. 背景与目标
2. 现状盘点（行业中性化实现 + 下游依赖）
3. 目标架构（三层分离）
4. ControlProvider 协议
5. 数据流与设计矩阵构建
6. 输出 schema 演进 + 向后兼容
7. 实施分期（P1/P2/P3/P4）
8. P1 详细任务拆分（重构不变功能）
9. P2 详细任务拆分（加市值 Provider）
10. P3 详细任务拆分（默认开启联合中性化）
11. P4 详细任务拆分（下游迁移 + 老字段下线）
12. 测试策略
13. 风险与回滚
14. 状态与验收

---

## 1. 背景与目标

### 1.1 业务背景

行业中性化已上线（`factor_ic` 模块 `neutralize=True` 默认开启），用截面回归 `factor ~ 行业哑变量` 求残差，剔除行业系统性影响。但单维度中性化覆盖不全：A 股市场公认的另一大风险源是**市值因子**——小盘股与大盘股的因子表现差异巨大（如反转因子在小盘股上更强、动量因子在大盘股上更弱），不剔除会让 IC 含\"市值溢价\"成分，污染 alpha 评估。

`fetch_market_cap` 已于 2026-06-18 完成（74 MB / 1,628,451 行 / 3026 stocks × 545 days，零失败），数据基础就绪。

### 1.2 设计目标

将\"中性化\"概念抽象为**控制变量驱动**的可扩展架构，而非为市值打补丁：

| 目标 | 说明 |
|------|------|
| **G1 可扩展性** | 新增任意中性化方式（市值/Beta/波动率/换手率/板块）只需新增一个 Provider 类，无需动引擎和调度层 |
| **G2 业界标准** | 联合中性化采用一次多元回归（Barra CNE 标准），而非串行残差或独立路径 |
| **G3 向后兼容** | P1 重构对外行为零变化（`ic_neutral_industry` 字段不变，IC 数值逐位一致），P3/P4 才迁移下游 |
| **G4 因子级排除** | 排除清单升级为二维 `{control_name: [factor_names]}`，避免\"自己中性化自己\" |
| **G5 可观测** | 输出含 `controls_used` + 各 control 的预处理元信息（哑变量数 / winsorize 区间 / 剔除行数） |

### 1.3 非目标

- 不改 `industry_neutral_residual()` 的对外契约（方便测试逐位对比）
- 不在本期实现 Beta / 波动率 / 换手率 Provider（仅在协议层预留扩展点）
- 不动 `fetch_industry` / `fetch_market_cap` 两个数据采集模块
- 不引入风险模型权重估计（这是 Barra 风险模型范畴，超出 IC 分析职责）

---

## 2. 现状盘点

### 2.1 行业中性化代码结构

| 位置 | 角色 | 行数 |
|------|------|------|
| `factor_ic/common/ic_calculator.py:794-880` | `industry_neutral_residual()` 截面回归求残差 | 87 |
| `factor_ic/common/factor_ic_runner.py:55-67` | `INDUSTRY_NEUTRALIZE_EXCLUDED` 排除清单（一维 set） | 13 |
| `factor_ic/common/factor_ic_runner.py:80-138` | `_resolve_neutralize_decision()` 三态决策（enabled/skip/excluded） | 59 |
| `factor_ic/common/factor_ic_runner.py:141-288` | `_compute_industry_neutral_ic()` 编排：merge → 剔'其他' → dropna → residual → recalc IC | 148 |
| `factor_ic/common/data_loader.py:373` | `merge_industry_column()` 注入 industry 列 | — |
| `factor_ic/common/ic_result_builder.py:57-126` | `RESULT_KEY_IC_NEUTRAL = "ic_neutral_industry"` + `_normalize_neutral_payload()` schema 校验 | 70 |

### 2.2 输出 schema 现状

```jsonc
{
  "ic_raw": { "ic_mean": ..., "icir": ..., "dates": [...], "ic_values": [...] },
  "ic_neutral_industry": {
    "enabled": true,
    "ic_mean": ..., "ic_std": ..., "icir": ..., "p_value": ...,
    "dates": [...], "ic_values": [...],
    "decay_rate": ..., "decay_level": "low|medium|high",
    "min_industry_stocks": 5,
    "skipped_reason": null  // 当 enabled=false 时填原因字符串
  }
}
```

### 2.3 下游依赖

| 文件 | 行号 | 读取字段 | 用途 |
|------|------|----------|------|
| `summary/generate_factor_summary_report.py` | 602 | `data["ic_neutral_industry"]` | 汇总报告输出中性化 IC 列 |
| `factor_ic/test_cases/test_ic_result_builder_neutral.py` | 全文 | schema 校验 | 单元测试 |
| `factor_ic/test_cases/test_factor_ic_runner_neutralize.py` | 全文 | end-to-end 测试 | 集成测试 |

`comprehensive_factor` / `backtest` 当前**不读取**中性化 IC，仅基于 raw IC 选因子，迁移面小。

### 2.4 重构关键约束

- **C1 IC 数值零变化**：P1 完成后，所有现有因子的 `ic_neutral_industry.ic_mean` / `icir` 必须与 P1 之前**逐位一致**（用快照测试锁住）
- **C2 排除清单语义不退化**：`INDUSTRY_NEUTRALIZE_EXCLUDED`（6 个行业聚合因子）在 P1 后必须仍能阻断中性化
- **C3 错误降级路径不变**：`raw IC = 0` / `industry merge 全 NaN` / `所有日期 < min_stocks` 三种降级仍输出 `enabled=false + skipped_reason`
- **C4 不动 `industry_neutral_residual()` 公开签名**：现行单元测试 + 调用方对此函数的契约不破坏，新引擎在其上层组合，不下沉

---

## 3. 目标架构

### 3.1 三层分离

```
┌────────────────────────────────────────────────────────────────────┐
│ Layer 3: 调度层  factor_ic_runner.run_factor_ic_analysis            │
│   - 接收参数 neutralize_specs: list[str] = ["industry"]            │
│   - 解析 spec → 实例化 Provider 列表                                 │
│   - 检查每个 (factor, control) 是否在排除清单 → 过滤                  │
│   - 调用 Layer 2 引擎，得到残差 + 元信息                              │
│   - 用残差重算 IC，组装 ic_neutralized payload                       │
└────────────────────────┬───────────────────────────────────────────┘
                         ↓ 传入 [IndustryProvider, LogMarketCapProvider]
┌────────────────────────────────────────────────────────────────────┐
│ Layer 2: 中性化引擎  factor_ic/common/neutralizer.py（新文件）        │
│   compute_neutral_residual(factor_df, factor_col, providers, ...)  │
│     1. 各 Provider load() → merge 到 factor_df                      │
│     2. 各 Provider preprocess() 链式调用                             │
│     3. dropna(subset=[factor_col, *all_control_cols])              │
│     4. 每日 cross-section:                                         │
│         X = pd.concat([p.to_design_columns(day) for p in providers])│
│         y = factor 列                                              │
│         residual = y - LinearRegression().fit(X,y).predict(X)      │
│     5. 返回 residual_df + meta（每 Provider 的统计信息）              │
└────────────────────────┬───────────────────────────────────────────┘
                         ↓ 协议调用
┌────────────────────────────────────────────────────────────────────┐
│ Layer 1: 控制变量提供器  factor_ic/common/control_providers/         │
│   ┌─ __init__.py    （PROVIDER_REGISTRY 注册表 + 工厂）             │
│   ├─ base.py        （ControlProvider Protocol）                    │
│   ├─ industry.py    （IndustryProvider，封装现 merge_industry_column）│
│   └─ log_market_cap.py  （P2 加，LogMarketCapProvider）             │
└────────────────────────────────────────────────────────────────────┘
```

### 3.2 关键调用关系（重构前 vs 重构后）

```
重构前:
run_factor_ic_analysis(neutralize=True)
  └─ _compute_industry_neutral_ic()
       └─ industry_neutral_residual()  [ic_calculator.py]

重构后（P1）:
run_factor_ic_analysis(neutralize_specs=["industry"])
  └─ _compute_neutralized_ic()
       └─ neutralizer.compute_neutral_residual(providers=[IndustryProvider()])
            └─ industry_neutral_residual()  [仍保留，作为 IndustryProvider 的内部实现委托]

重构后（P3）:
run_factor_ic_analysis(neutralize_specs=["industry", "log_market_cap"])
  └─ _compute_neutralized_ic()
       └─ neutralizer.compute_neutral_residual(providers=[IndustryProvider(), LogMarketCapProvider()])
            └─ 每日截面 LinearRegression(X=industry_dummies+log_cap_col, y=factor)
```

### 3.3 设计权衡

| 决策点 | 选择 | 理由 |
|--------|------|------|
| Provider 注入方式 | 注册表 + 字符串 spec | 支持 CLI / config 文件驱动；新 Provider 只需注册不需改调度层 |
| 引擎是否替代 `industry_neutral_residual()` | **不替代，包装** | C4 约束；旧函数继续作为 P1 行业 single-control 路径的实现，方便快照测试逐位对比 |
| `dropna` 在引擎做还是 Provider 做 | 引擎统一做 | 多 control 时 NaN 会跨 Provider 传染，统一 dropna 比 Provider 各自处理更可控 |
| 哑变量编码 | Provider 决定 | `IndustryProvider` 用 `pd.get_dummies(drop_first=False)` 保持与现行行为完全一致；多 Provider 时引擎检测多重共线性自动 drop_first |
| 数值列预处理顺序 | `ln → winsorize(1%,99%)` | 不做标准化（OLS 对量纲不敏感），保留残差原始尺度便于解读 |
| 多 Provider 时设计矩阵列拼接顺序 | 按 Provider 注册顺序 | 确定性 → 测试可复现 |

---

## 4. ControlProvider 协议

### 4.1 Protocol 定义（`factor_ic/common/control_providers/base.py`）

```python
from __future__ import annotations
from typing import Literal, Protocol, runtime_checkable
import pandas as pd


@runtime_checkable
class ControlProvider(Protocol):
    """中性化控制变量提供器协议。

    每个具体 Provider 提供一种风险因子的数据源 + 预处理 + 设计矩阵转换，
    供 neutralizer 引擎组合成多元回归的 X 矩阵。
    """

    name: str
    """控制变量名，作为 spec 字符串和注册表 key（如 'industry' / 'log_market_cap'）。"""

    column_type: Literal["categorical", "numerical"]
    """列类型，决定引擎如何转设计矩阵。
       categorical: 通过 to_design_columns 转哑变量
       numerical:   to_design_columns 直接返回单列 DataFrame
    """

    def load(self, dates: list, assets: list, *, logger=None) -> pd.DataFrame:
        """加载控制变量原始数据。

        参数:
            dates: 因子日期列表（用于按需加载切片）
            assets: 资产代码列表
            logger: 日志器

        返回:
            DataFrame，必须含列 [date, asset, <self.name 或派生列>]。
            缺失值用 NaN 表示，后续由引擎统一 dropna。
        """
        ...

    def preprocess(self, df: pd.DataFrame, *, logger=None) -> pd.DataFrame:
        """预处理（ln 变换 / 剔'其他' / winsorize / 标准化等）。

        输入: load() 返回的 DataFrame
        输出: 与输入同 schema，但值已变换；可能行数减少（剔除规则）
        """
        ...

    def to_design_columns(self, day_df: pd.DataFrame) -> pd.DataFrame:
        """将 day_df（单日 cross-section）转换为设计矩阵列。

        categorical 实现示例（IndustryProvider）:
            return pd.get_dummies(day_df['industry'], prefix='ind')

        numerical 实现示例（LogMarketCapProvider）:
            return day_df[['log_market_cap']]

        返回:
            DataFrame，行数 = day_df 行数，列数 = 该 Provider 贡献的设计矩阵列数
        """
        ...

    def filter_invalid_rows(
        self, day_df: pd.DataFrame, *, min_count: int, logger=None
    ) -> pd.DataFrame:
        """过滤当日 cross-section 中无效行。

        IndustryProvider: 剔除股票数 < min_industry_stocks 的行业
        LogMarketCapProvider: 剔除 log_market_cap 缺失或 ≤ 0 的行（理论不会，作护栏）

        参数:
            min_count: 数据需求的最小数量（categorical 通常用 5；numerical 通常用 20 个有效样本）
            logger: 日志器

        返回:
            过滤后的 day_df（行数 ≤ 输入）
        """
        ...

    def get_meta(self) -> dict:
        """返回该 Provider 的预处理统计信息（写入 ic_neutralized.control_meta）。

        IndustryProvider 示例:
            {'n_industries': 30, 'min_stocks': 5, 'other_dropped': 1234}
        LogMarketCapProvider 示例:
            {'winsorize': [0.01, 0.99], 'n_zero_dropped': 0, 'mean_log_cap': 23.45}
        """
        ...
```

### 4.2 注册表（`factor_ic/common/control_providers/__init__.py`）

```python
from .base import ControlProvider
from .industry import IndustryProvider

PROVIDER_REGISTRY: dict[str, type[ControlProvider]] = {
    "industry": IndustryProvider,
}

# P2 时追加:
# from .log_market_cap import LogMarketCapProvider
# PROVIDER_REGISTRY["log_market_cap"] = LogMarketCapProvider


def build_providers(specs: list[str]) -> list[ControlProvider]:
    """根据字符串 spec 列表构建 Provider 实例列表。

    参数:
        specs: 如 ["industry"] 或 ["industry", "log_market_cap"]

    异常:
        ValueError: spec 不在注册表里
    """
    providers = []
    for spec in specs:
        if spec not in PROVIDER_REGISTRY:
            raise ValueError(
                f"未知的中性化 spec '{spec}'，可选: {sorted(PROVIDER_REGISTRY.keys())}"
            )
        providers.append(PROVIDER_REGISTRY[spec]())
    return providers
```

### 4.3 因子级排除清单（升级为二维）

```python
# factor_ic/common/factor_ic_runner.py

NEUTRALIZE_EXCLUDED: dict[str, frozenset[str]] = {
    "industry": frozenset({
        "industry_momentum_5d",
        "industry_turnover_trend",
        "industry_amplitude_trend",
        "industry_roe_trend",
        "industry_earnings_growth",
        "industry_pe_trend",
    }),
    # P2 时追加:
    # "log_market_cap": frozenset({
    #     "log_market_cap",       # 自己不能中性化自己
    #     "size_factor",          # 若有市值因子衍生品
    # }),
}
```

### 4.4 决策协议（_resolve_neutralize_decision 升级）

每个 (factor, control_spec) 对独立判断：

| 输入 | 输出 |
|------|------|
| `factor in NEUTRALIZE_EXCLUDED["industry"]` | spec="industry" 被弹出，其他 specs 保留 |
| 用户传 `neutralize_specs=[]` | enabled=false, skipped_reason="user disabled" |
| 增量模式 | enabled=false, skipped_reason="incremental mode" |
| 所有 specs 都被排除 | enabled=false, skipped_reason="all controls excluded for this factor" |
| 部分 specs 被排除 | 用剩余 specs 跑，meta 记录 `excluded_specs: [...]` |

---

## 5. 数据流与设计矩阵构建

### 5.1 端到端数据流

```
factor_data.json.gz 加载
        ↓
factor_df: [date, asset, factor_col]
        ↓
[Provider.load() × N] 并行从各源加载（行业 dict / market_cap parquet）
        ↓
factor_df_with_controls: [date, asset, factor_col, industry, log_market_cap, ...]
        ↓
[Provider.preprocess() × N] 链式调用（剔'其他' / ln / winsorize）
        ↓
factor_df_clean: 同 schema，但行数减少
        ↓
dropna(subset=[factor_col, *control_cols])  ← 引擎统一处理
        ↓
groupby(date) cross-section loop:
    for date, day_df in factor_df_clean.groupby(date):
        # 1. 各 Provider 过滤无效行（行业 <5 / cap ≤0）
        for p in providers:
            day_df = p.filter_invalid_rows(day_df, min_count=...)
        if len(day_df) < min_stocks:
            continue
        
        # 2. 拼接设计矩阵
        X_parts = [p.to_design_columns(day_df) for p in providers]
        X = pd.concat(X_parts, axis=1)
        
        # 3. 多重共线性护栏
        X = _drop_collinear_columns(X)  # 见 §5.3
        
        # 4. 回归求残差
        y = day_df[factor_col]
        model = LinearRegression(fit_intercept=False)
        model.fit(X, y)
        residual = y - model.predict(X)
        
        # 5. 收集
        results.append(...)
        ↓
residual_df: [date, asset, neutral_factor]
        ↓
calculate_ic_with_direction_verification(residual_df, return_df, ...)
        ↓
ic_neutralized payload + control_meta
```

### 5.2 设计矩阵构建细节

**单 control = "industry" 时（P1 行为，与现行完全一致）**：

```
day_df:
  date         asset    factor   industry
  2024-03-18   600000   0.12     银行
  2024-03-18   600001   0.05     银行
  ...
  2024-03-18   002001   -0.08    电子

X = pd.get_dummies(day_df['industry'])   # drop_first=False（同现行 industry_neutral_residual）
  银行  非银  电子  ...  机械
   1    0    0   ...    0
   1    0    0   ...    0
   ...
   0    0    1   ...    0

y = day_df['factor']
LinearRegression(fit_intercept=False).fit(X, y)  # 不加截距，哑变量自身覆盖均值
residual = y - model.predict(X)
```

**双 control = ["industry", "log_market_cap"] 时（P3 行为）**：

```
X_industry = pd.get_dummies(day_df['industry'], drop_first=True)  # ← 多 control 时必须 drop_first 避免奇异矩阵
X_logcap   = day_df[['log_market_cap']]
X = pd.concat([X_industry, X_logcap], axis=1)
  非银  电子  ...  机械  log_market_cap
   0    0   ...    0      23.45
   0    0   ...    0      22.10
   ...

LinearRegression(fit_intercept=True).fit(X, y)  # ← 有 drop_first 后必须加截距
residual = y - model.predict(X)
```

### 5.3 多重共线性护栏

加入连续控制变量后，行业哑变量的全集（不 drop_first）会与截距列共线性，导致 `LinearRegression` 矩阵奇异。规则：

| 场景 | 截距 | 行业哑变量 |
|------|------|-----------|
| 仅 categorical Provider | `fit_intercept=False` | `drop_first=False`（保持现行为，结果与旧 `industry_neutral_residual` 逐位一致） |
| 含 numerical Provider | `fit_intercept=True` | `drop_first=True`（让 N-1 个哑变量与截距共同构成行业效应） |

引擎根据 providers 的 column_type 列表自动决策，不需调用方关心：

```python
has_numerical = any(p.column_type == "numerical" for p in providers)
fit_intercept = has_numerical
# Provider.to_design_columns 接受 drop_first 参数
```

### 5.4 NaN / 缺失数据处理

| 来源 | 策略 |
|------|------|
| factor_col 为 NaN | 引擎 dropna |
| industry 列 NaN（未匹配资产） | 引擎 dropna（pandas groupby 默认行为也会跳，但显式 dropna 更可控） |
| industry == "其他" | IndustryProvider.preprocess() 剔除 |
| log_market_cap NaN（个别股某日无数据） | 引擎 dropna |
| log_market_cap = ln(0) = -inf | LogMarketCapProvider.preprocess() 检测 cap ≤ 0 → drop（理论不会，护栏） |
| 当日有效行数 < min_stocks | continue 跳过该日 |

**关键不变量**: `dropna` 必须在所有 Provider 的 preprocess 之后、groupby 之前统一做一次，避免某个 Provider 引入新 NaN 但跳过 dropna。

---

## 6. 输出 schema 演进 + 向后兼容

### 6.1 新字段 `ic_neutralized`（P3 引入）

```jsonc
{
  "factor_name": "rsi",
  "factor_col": "rsi_6",
  
  "ic_raw": { /* 同现 */ },
  
  "ic_neutralized": {
    "enabled": true,
    "controls_used": ["industry", "log_market_cap"],   // ← 当前激活的 specs（按注册顺序）
    
    // 与 ic_neutral_industry 保持一致的核心字段（业务无感切换）
    "ic_mean": 0.0234,
    "ic_std": 0.0876,
    "icir": 0.267,
    "p_value": 0.0012,
    "p_value_display": "p<0.01",
    "positive_ratio": 0.567,
    "n_days": 545,
    "dates": ["2024-03-18", ...],
    "ic_values": [0.012, ...],
    
    // 衰减度量（与 ic_raw 比较）
    "decay_rate": 0.234,
    "decay_level": "low|medium|high",
    
    // 各 control 的预处理统计信息
    "control_meta": {
      "industry": {
        "n_industries": 30,
        "min_stocks": 5,
        "other_dropped": 1234,
        "nan_dropped": 0
      },
      "log_market_cap": {
        "winsorize_quantiles": [0.01, 0.99],
        "n_winsorized_low": 5430,
        "n_winsorized_high": 5430,
        "n_zero_dropped": 0,
        "mean_log_cap": 23.45,
        "std_log_cap": 1.23
      }
    },
    
    // 排除的 specs（factor 在排除清单里）
    "excluded_specs": [],
    
    "skipped_reason": null   // 当 enabled=false 时填降级原因
  },
  
  // [DEPRECATED 2026-09-18 by P4]
  // 当 controls_used == ["industry"] 时，P3 期间镜像写入此字段保持下游兼容
  "ic_neutral_industry": { /* 同 ic_neutralized 但不含 controls_used 和 excluded_specs */ }
}
```

### 6.2 兼容性时间线

| 阶段 | `ic_neutral_industry` | `ic_neutralized` | 下游读取 |
|------|----------------------|------------------|----------|
| **当前（P0）** | ✅ 唯一字段 | — | `summary` 读 `ic_neutral_industry` |
| **P1 完成后** | ✅ 不变（语义+数值都不变） | — | `summary` 读 `ic_neutral_industry` |
| **P2 完成后** | ✅ 不变 | — | 同 P1（`log_market_cap` Provider 已实现但未默认启用） |
| **P3 完成后** | ⚠️ 镜像写入（仅当 controls_used=["industry"]）；`controls_used != ["industry"]` 时**不写**该字段 | ✅ 主字段 | `summary` 读 `ic_neutralized`，老字段镜像兜底 |
| **P4 完成后** | ❌ 移除 | ✅ 唯一字段 | `summary` / 全部下游只读 `ic_neutralized` |

### 6.3 P3 镜像规则的精确语义

P3 默认 `neutralize_specs = ["industry", "log_market_cap"]`。新跑因子的输出**只有 `ic_neutralized`，没有 `ic_neutral_industry`**。

**为什么不强制镜像？**
- 镜像 `controls_used != ["industry"]` 的结果到 `ic_neutral_industry` = 字段语义撒谎（"行业中性化"≠"行业+市值中性化"）
- 下游应该立刻知道字段语义变了，强制升级
- 镜像仅用于 P3 期间临时兼容那些用户手动跑 `neutralize_specs=["industry"]` 的场景

P3 期间 summary 读取规则（兼容代码）：

```python
# summary/generate_factor_summary_report.py
neutral = data.get("ic_neutralized") or data.get("ic_neutral_industry") or {}
controls = neutral.get("controls_used", ["industry"])  # 老字段缺省视为行业中性化
```

P4 删除老字段读取分支。

### 6.4 schema 校验（`ic_result_builder._normalize_neutral_payload` 升级）

```python
RESULT_KEY_IC_NEUTRALIZED = "ic_neutralized"
RESULT_KEY_IC_NEUTRAL_LEGACY = "ic_neutral_industry"  # P3-P4 期间过渡

# 必填字段（enabled=true 时）
REQUIRED_FIELDS_ENABLED = {
    "ic_mean", "ic_std", "icir", "p_value",
    "positive_ratio", "n_days",
    "dates", "ic_values",
    "decay_rate", "decay_level",
    "controls_used",     # ← 新增
    "control_meta",      # ← 新增
}

# 必填字段（enabled=false 时）
REQUIRED_FIELDS_DISABLED = {
    "skipped_reason",
}
```

### 6.5 旧字段 `min_industry_stocks` 的迁移

P0 字段 `ic_neutral_industry.min_industry_stocks: 5` → P3 移到 `ic_neutralized.control_meta.industry.min_stocks: 5`，旧字段镜像期保留。

---

## 7. 实施分期

| 期 | 名称 | 文件改动 | 行数估计 | 对外行为 | commit 数 | 验收 |
|----|------|---------|----------|----------|----------|------|
| **P1** | 架构重构（不变功能） | 新增 `control_providers/` 3 文件 + `neutralizer.py`；改 `factor_ic_runner.py` / `ic_result_builder.py`；新增测试 | +600 / -120 | **零变化**：`ic_neutral_industry` schema/数值/降级行为完全一致 | 6-8 | 现有 34 测试全过 + 快照测试逐位一致 + 全因子 IC 对比无差异 |
| **P2** | 加 LogMarketCapProvider | 新增 `log_market_cap.py` + 测试；改 `__init__.py`（注册）+ `factor_ic_runner.py`（排除清单加 key） | +200 / -10 | **零变化**：默认 `neutralize_specs=["industry"]` 不变，市值 Provider 已实现但未启用 | 2-3 | 单元测试 cap-only / cap+industry 双 control 路径通过 |
| **P3** | 默认开启联合中性化 | 改 `factor_ic_runner.py` 默认 specs；改 `ic_result_builder.py` 加 `ic_neutralized` 字段；CLI 升级；镜像兜底逻辑；改 `summary` 读取 | +150 / -50 | **行为变化**：默认输出 `ic_neutralized`，镜像写 `ic_neutral_industry`；CLI `--neutralize-specs industry,log_market_cap` 可选 | 3-4 | 全因子跑批，对比 industry-only vs industry+cap 的 IC 衰减差异；下游 summary 报告字段正确 |
| **P4** | 下游迁移 + 老字段下线 | 改 `summary` 删兜底；移除 `RESULT_KEY_IC_NEUTRAL_LEGACY` 写入；删测试中老字段断言；改 PROJECT.md / MODULE.md / flow doc | +30 / -120 | **行为变化**：`ic_neutral_industry` 字段移除 | 2-3 | 全链路回归测试无 KeyError |

### 7.1 P1-P4 顺序约束

```
P1（重构）  →  P2（加市值）  →  P3（默认开启）  →  P4（删老字段）
   ↓            ↓                ↓                  ↓
 不变功能   不启用市值       启用市值+镜像        关镜像
```

每期独立可发布，回滚不影响下游：
- P1 出问题 → revert 单个 PR，回到现行行业中性化
- P2 出问题 → revert，市值 Provider 不影响默认路径
- P3 出问题 → revert，回到 P2 状态（仅行业中性化，市值 Provider 待命）
- P4 出问题 → revert，回到 P3 镜像状态

### 7.2 何时进入下一期

| 跨期门禁 | 验证项 |
|---------|--------|
| P1 → P2 | 全因子 IC 数值快照逐位一致；ruff/pytest 全过；下游 summary 报告无差异 |
| P2 → P3 | LogMarketCapProvider 单测通过；手动 `--neutralize-specs log_market_cap` 跑 1 个因子，结果合理 |
| P3 → P4 | 全因子跑批 N+1 周（用户决定具体周数）；summary 报告字段稳定无投诉；下游已全部迁移到新字段 |

---

## 8. P1 详细任务拆分（重构不变功能）

P1 是最关键的一期，输出**架构骨架 + 验证不变功能**。原则：每个 commit 独立可回滚，每步 ruff+pytest 通过。

### 8.1 P1 commit 链规划

| commit | 名称 | 文件 | 行数 | 验证 |
|--------|------|------|------|------|
| **P1.1** | 新增 `control_providers/` 协议层 + 注册表 | `factor_ic/common/control_providers/{__init__.py, base.py}` | +120 | ruff + 协议测试（is_protocol_compliant） |
| **P1.2** | `IndustryProvider` 实现（包装现 `merge_industry_column`） | `factor_ic/common/control_providers/industry.py` + 测试 | +200 | 单元测试：load/preprocess/to_design_columns/filter_invalid_rows/get_meta |
| **P1.3** | `neutralizer.py` 引擎实现 | `factor_ic/common/neutralizer.py` + 测试 | +250 | 单元测试：单 control 路径与 `industry_neutral_residual` 输出**逐位一致** |
| **P1.4** | `factor_ic_runner.py` 切换调用：`_compute_industry_neutral_ic` → `_compute_neutralized_ic` | `factor_ic_runner.py` | +60/-100 | 现 34 测试全过；`ic_neutral_industry` schema 不变 |
| **P1.5** | 排除清单升级：`INDUSTRY_NEUTRALIZE_EXCLUDED` → `NEUTRALIZE_EXCLUDED["industry"]` | `factor_ic_runner.py` | +15/-13 | 6 个行业聚合因子排除路径仍走 skipped_reason |
| **P1.6** | 全因子快照测试（锁住 IC 数值零变化） | `factor_ic/test_cases/test_p1_snapshot.py` | +150 | 在 P1 重构前 capture 一次基线，重构后比对逐位一致 |
| **P1.7** | 流程文档 + design.md 状态更新 | `factor_ic/docs/neutralization_flow.md` 新建 + `factor_ic/MODULE.md` 加段 | +200 | 人工审核 |

总计 7 个 commit，约 +795/-113 行（含测试）。

### 8.2 P1 各 commit 实施细节

#### P1.1 协议层 + 注册表

**文件**:
- `factor_ic/common/control_providers/__init__.py`（注册表 + `build_providers()` 工厂）
- `factor_ic/common/control_providers/base.py`（`ControlProvider` Protocol，仅协议无实现）

**测试要点**:
- `isinstance(IndustryProvider(), ControlProvider)` 为 True（runtime_checkable）
- `build_providers(["unknown"])` 抛 ValueError
- `build_providers(["industry"])` 返回 `[IndustryProvider 实例]`

**注意**:
- 仅协议，不引入实现，commit 单独，不破坏现有调用
- `IndustryProvider` import 在 P1.2 才生效，P1.1 的 `__init__.py` 用 try/except ImportError 占位（或直接挂空字典等 P1.2 填）

**推荐策略**: P1.1 + P1.2 合并为一个 commit（协议+第一个实现一起落地，不让 P1.1 短暂处于"协议无实现"状态）

#### P1.2 IndustryProvider 实现

**文件**: `factor_ic/common/control_providers/industry.py`

**实现要点**:
```python
class IndustryProvider:
    name = "industry"
    column_type = "categorical"
    
    def load(self, dates, assets, *, logger=None):
        # 委托给 data_loader.merge_industry_column 但只返回 [date, asset, industry] 列
        # 注意：merge_industry_column 当前接受整个 factor_df 注入列，
        #       这里需要构造一个最小 [date, asset] DataFrame 走同一路径，避免重复实现
        ...
    
    def preprocess(self, df, *, logger=None):
        # 剔除 industry == "其他"
        before = len(df)
        df = df[df["industry"] != "其他"].copy()
        self._meta["other_dropped"] = before - len(df)
        return df
    
    def to_design_columns(self, day_df, *, drop_first=False):
        return pd.get_dummies(day_df["industry"], prefix="ind", drop_first=drop_first)
    
    def filter_invalid_rows(self, day_df, *, min_count=5, logger=None):
        # 剔除股票数 < min_count 的行业（与现 industry_neutral_residual filter 一致）
        valid = day_df.groupby("industry").filter(lambda x: len(x) >= min_count)
        return valid
    
    def get_meta(self):
        return {
            "n_industries": self._n_industries,
            "min_stocks": self._min_stocks,
            "other_dropped": self._other_dropped,
            "nan_dropped": self._nan_dropped,
        }
```

**关键决策**: load() 不直接调用 `merge_industry_column`（会要求传入 factor_df），而是直接调 `fetch_industry.get_industry_map`，构造 [date, asset, industry] DataFrame。这让 Provider 真正自洽。

#### P1.3 neutralizer 引擎

**文件**: `factor_ic/common/neutralizer.py`

**核心 API**:
```python
def compute_neutral_residual(
    factor_df: pd.DataFrame,
    factor_col: str,
    providers: list[ControlProvider],
    *,
    date_col: str = "date",
    asset_col: str = "asset",
    min_stocks: int = 5,
    logger=None,
) -> tuple[pd.DataFrame, dict]:
    """通用中性化引擎。
    
    返回:
        residual_df: [date, asset, "neutral_factor"]
        meta: {"controls": {provider.name: provider.get_meta(), ...}, "n_days_processed": N, ...}
    """
```

**P1 阶段**: 单 control 路径要与现 `industry_neutral_residual` **逐位一致**。验证方法：

```python
def test_single_control_industry_matches_legacy():
    legacy = industry_neutral_residual(factor_df, "rsi_6", ...)
    new, _ = compute_neutral_residual(factor_df, "rsi_6", [IndustryProvider()])
    pd.testing.assert_frame_equal(legacy, new[["date", "asset", "neutral_factor"]], check_exact=True)
```

#### P1.4 factor_ic_runner 切换

替换 `_compute_industry_neutral_ic` 调用为 `_compute_neutralized_ic`，后者内部调 `compute_neutral_residual([IndustryProvider()])`。**此 commit 仅切实现，不动签名 / 输出 schema**。

#### P1.5 排除清单升级

```python
# 旧
INDUSTRY_NEUTRALIZE_EXCLUDED: frozenset[str] = frozenset({...})

# 新
NEUTRALIZE_EXCLUDED: dict[str, frozenset[str]] = {
    "industry": frozenset({...}),  # 6 个行业聚合因子
}
```

`_resolve_neutralize_decision` 改为根据 spec 索引：`NEUTRALIZE_EXCLUDED.get(spec, frozenset()) `

#### P1.6 全因子 IC 快照测试

- 在 P1 启动前先跑一次现有 `factor_ic_runner main` 全因子，存 `factor_ic/test_cases/snapshots/p0_baseline_ic.json`（仅核心字段：factor / ic_mean / ic_std / icir / decay_rate）
- 测试用例 `test_p1_snapshot.py`：跑当前代码，对比基线，所有 ic_mean 浮点 abs diff < 1e-9
- 这一步是 P1 → P2 的硬门禁

#### P1.7 文档同步

- 新建 `factor_ic/docs/neutralization_flow.md`（参考 `industry_neutralization_flow.md` 格式）
- `factor_ic/MODULE.md` 加 §X 中性化引擎一节
- design.md 本身的 §14 状态更新为"P1 完成"

---

## 9. P2 详细任务拆分（加 LogMarketCapProvider）

P2 不改默认行为（`neutralize_specs=["industry"]`），仅添加新 Provider 让用户能手动启用。

> **P2 实施状态 (2026-06-18)**：✅ 已完成。实际实现修正了设计伪代码中的一个细节：
> `market_cap_data.json.gz` 顶层结构是 gzip JSON `{meta, data}`，因此
> `LogMarketCapProvider.load()` 使用 `gzip.open + json.load(...)["data"]`，
> 不使用 `pd.read_json(..., compression="gzip")` 直接读取裸 records。

### 9.1 P2 commit 链

| commit | 名称 | 文件 | 行数 | 验证 |
|--------|------|------|------|------|
| ✅ `616a859` | `LogMarketCapProvider` 实现 | `factor_ic/common/control_providers/log_market_cap.py` + 测试 | +340 | 12 passed |
| ✅ `aa5f7cf` | 注册到 PROVIDER_REGISTRY + 排除清单 | `control_providers/__init__.py` + `factor_ic_runner.py` + 测试 | +31 | 42 passed |
| ✅ `1ce2b8d` | 联合中性化集成测试（手动指定 specs） | `factor_ic/test_cases/test_neutralizer_combined.py` | +120 | 6 passed；P1/P2 集合 89 passed |

总计 3 个代码 commit，约 +491 行；P2 未改变 runner 默认行为。

### 9.2 P2 各 commit 实施细节

#### P2.1 LogMarketCapProvider 实现

**文件**: `factor_ic/common/control_providers/log_market_cap.py`

**实现要点**:
```python
import gzip
import json
import numpy as np
import pandas as pd
from data_fetchers.common.paths import get_market_cap_data_file


class LogMarketCapProvider:
    name = "log_market_cap"
    column_type = "numerical"
    join_keys = ["date", "asset"]
    
    # 配置
    SOURCE_FIELD = "circ_market_cap"   # 用流通市值，不用总市值
    OUTPUT_COL = "log_market_cap"
    WINSORIZE_QUANTILES = (0.01, 0.99) # Barra 标准
    
    def __init__(self):
        self._meta = {
            "source_field": self.SOURCE_FIELD,
            "winsorize_quantiles": list(self.WINSORIZE_QUANTILES),
            "n_loaded": 0,
            "n_after_slice": 0,
            "n_missing_or_non_positive_dropped": 0,
            "n_winsorized_low": 0,
            "n_winsorized_high": 0,
        }
    
    def load(self, dates, assets, *, logger=None):
        # 从 gzip JSON {meta,data} 读 [date, asset, circ_market_cap]
        # 按 dates / assets 切片
        with gzip.open(get_market_cap_data_file(), "rt", encoding="utf-8") as fp:
            payload = json.load(fp)
        df = pd.DataFrame.from_records(payload["data"])
        df = df[df["date"].isin(dates) & df["asset"].isin(assets)]
        return df[["date", "asset", self.SOURCE_FIELD]]
    
    def preprocess(self, df, *, logger=None):
        # 1. 剔除 circ_market_cap 缺失或 <= 0（护栏）
        before = len(df)
        df = df[df[self.SOURCE_FIELD].notna() & (df[self.SOURCE_FIELD] > 0)].copy()
        self._meta["n_missing_or_non_positive_dropped"] = before - len(df)
        
        # 2. ln 变换
        df["log_market_cap"] = np.log(df[self.SOURCE_FIELD])
        
        # 3. 截面 winsorize（每日独立）
        def _winsorize_day(group):
            lo, hi = group["log_market_cap"].quantile(self.WINSORIZE_QUANTILES)
            n_low = (group["log_market_cap"] < lo).sum()
            n_high = (group["log_market_cap"] > hi).sum()
            self._meta["n_winsorized_low"] += int(n_low)
            self._meta["n_winsorized_high"] += int(n_high)
            group["log_market_cap"] = group["log_market_cap"].clip(lo, hi)
            return group
        
        df = df.groupby("date", group_keys=False).apply(_winsorize_day)
        return df.drop(columns=[self.SOURCE_FIELD])
    
    def to_design_columns(self, day_df, *, drop_first=False):
        # numerical 类型直接返回单列；drop_first 不影响
        return day_df[["log_market_cap"]]
    
    def filter_invalid_rows(self, day_df, *, min_count=20, logger=None):
        # numerical 通常不需要剔除（preprocess 已剔 cap≤0）
        # 这里仅做样本数下限护栏：当日有效 cap < 20 整批跳过（min_count=20 vs categorical 的 5）
        if len(day_df) < min_count:
            return day_df.iloc[0:0]  # 空
        return day_df
    
    def get_meta(self):
        return self._meta.copy()
```

**关键决策**:
- 用 `circ_market_cap`（流通市值）而非 `total_market_cap`（总市值）：流通盘反映可交易筹码，更贴近 alpha 信号去噪目标
- `WINSORIZE_QUANTILES = (0.01, 0.99)` 与 Barra 一致
- 不做标准化（OLS 对量纲不敏感，标准化反让残差解释复杂）
- 关键陷阱：`pd.read_json` 读 74 MB 文件慢（~10 秒）。考虑 P3 时切换为 `pd.read_parquet` 或缓存 DataFrame

#### P2.2 注册 + 排除清单

```python
# factor_ic/common/control_providers/__init__.py
from .log_market_cap import LogMarketCapProvider
PROVIDER_REGISTRY["log_market_cap"] = LogMarketCapProvider

# factor_ic/common/factor_ic_runner.py
NEUTRALIZE_EXCLUDED["log_market_cap"] = frozenset({
    "log_market_cap",       # 自己不能中性化自己（如果未来有 log_market_cap 因子）
    # 后续如果有 size_factor / total_assets_log 等市值相关因子继续追加
})
```

#### P2.3 联合中性化集成测试

**测试文件**: `factor_ic/test_cases/test_neutralizer_combined.py`

**关键用例**:

| 用例 | 输入 | 期望 |
|------|------|------|
| TC-N-1 | `providers=[IndustryProvider()]` 单 control | 与 P1.6 快照一致 |
| TC-N-2 | `providers=[LogMarketCapProvider()]` 单 numerical | 残差 mean ≈ 0；行数等于因子有效行数（不剔行业） |
| TC-N-3 | `providers=[IndustryProvider(), LogMarketCapProvider()]` 双 control | `fit_intercept=True` + `drop_first=True` 自动；残差 mean ≈ 0；列数 = (n_industries-1) + 1 |
| TC-N-4 | LogMarketCap 单 control，部分天数股票数 < 20 | 这些天数被跳过；其他天数正常 |
| TC-N-5 | 多 control，因子在排除清单 | 弹出对应 spec，剩余 specs 跑 |

#### P2.4 手动验证（不入 commit）

执行命令验证联合中性化路径：

```bash
python -m factor_ic.factors.factor_ic_rsi_1d --neutralize-specs industry,log_market_cap
```

验证输出 JSON 含 `ic_neutralized.controls_used == ["industry", "log_market_cap"]`，IC 数值与仅行业中性化对比有可解释的差异。

---

## 10. P3 详细任务拆分（默认开启联合中性化）

P3 是用户感知最强的一期：默认行为变化（`ic_neutral_industry` → `ic_neutralized`）。

### 10.1 P3 commit 链

| commit | 名称 | 文件 | 行数 | 验证 |
|--------|------|------|------|------|
| **P3.1** | `factor_ic_runner.py` 默认 specs 切换 + CLI 加 `--neutralize-specs` | `factor_ic_runner.py` | +40 | CLI 解析正确；默认 `["industry", "log_market_cap"]` |
| **P3.2** | `ic_result_builder.py` 加 `ic_neutralized` 字段 + 老字段镜像 | `ic_result_builder.py` + 测试 | +120 | schema 校验通过；镜像规则正确 |
| **P3.3** | `summary` 兼容读取（新字段优先，老字段兜底） | `summary/generate_factor_summary_report.py` | +20 / -5 | 新跑因子报告字段正确；旧 JSON 仍能读 |
| **P3.4** | 全因子跑批 + 衰减对比报告 | `temporary/p3_compare_neutralization.py`（脚本） | +100 | 输出三组对比表：raw vs ind-only vs ind+cap |

总计 4 个 commit，约 +280/-5 行。

### 10.2 P3 各 commit 实施细节

#### P3.1 默认 specs + CLI 升级

```python
# factor_ic_runner.run_factor_ic_analysis 签名变化
def run_factor_ic_analysis(
    factor_name: str,
    factor_col: str,
    ...
    *,
    neutralize: bool = True,                                    # 保留兼容参数
    neutralize_specs: list[str] | None = None,                   # 新增
    neutralize_min_industry_stocks: int = 5,
    ...
):
    if neutralize_specs is None:
        # 默认行为
        neutralize_specs = ["industry", "log_market_cap"] if neutralize else []
    ...
```

CLI:
```bash
python -m factor_ic.factors.factor_ic_rsi_1d \
    --neutralize-specs industry,log_market_cap   # 默认
    --neutralize-specs industry                  # 退回 P0 行为（兼容选项）
    --no-neutralize                              # 关闭中性化
```

#### P3.2 ic_result_builder 升级

```python
# factor_ic/common/ic_result_builder.py

RESULT_KEY_IC_NEUTRALIZED = "ic_neutralized"
RESULT_KEY_IC_NEUTRAL_LEGACY = "ic_neutral_industry"   # P3-P4 期间过渡

def build_ic_result(
    ...,
    ic_neutralized_payload: dict | None = None,    # 新参数
    ic_neutral_payload: dict | None = None,        # 老参数（builder 内部生成镜像，调用方不传）
    ...,
) -> dict:
    result = {...}
    
    if ic_neutralized_payload is not None:
        normalized = _normalize_neutralized_payload(ic_neutralized_payload)
        result[RESULT_KEY_IC_NEUTRALIZED] = normalized
        
        # 老字段镜像规则（P3 临时）
        if normalized.get("controls_used") == ["industry"]:
            legacy = _build_legacy_mirror(normalized)
            result[RESULT_KEY_IC_NEUTRAL_LEGACY] = legacy
    
    return result
```

`_build_legacy_mirror` 仅复制 `ic_mean / ic_std / icir / p_value / ... / decay_rate / decay_level`，不带 `controls_used` / `excluded_specs`，但带回 `min_industry_stocks` 字段（从 `control_meta.industry.min_stocks` 提取）。

#### P3.3 summary 兼容读取

```python
# summary/generate_factor_summary_report.py:602
# 旧
neutral = data.get("ic_neutral_industry") or {}

# 新（P3 期间）
neutral = data.get("ic_neutralized") or data.get("ic_neutral_industry") or {}
```

并在报告输出列加 "中性化方式" 一栏，显示 `controls_used` 或 "industry only (legacy)"。

#### P3.4 衰减对比报告（一次性脚本）

**目的**: 用真实数据回答"开启市值中性化是否真的需要"。

**脚本**: `temporary/p3_compare_neutralization.py`

**逻辑**:
1. 全因子跑三种 specs：`[]` (raw) / `["industry"]` / `["industry", "log_market_cap"]`
2. 输出对比表：

| factor | raw_ic_mean | ind_ic_mean | ind+cap_ic_mean | ind_decay | ind+cap_decay | 增量衰减 |
|--------|-------------|-------------|-----------------|-----------|---------------|----------|
| rsi_6 | 0.054 | 0.041 | 0.038 | 24% | 30% | +6% |
| volume_ratio_5 | 0.082 | 0.075 | 0.052 | 9% | 37% | +28% |
| ... |

3. 凡 "增量衰减 > 10%" 的因子标红：说明该因子原本含显著市值溢价，市值中性化必要

**期望发现**: 反转类 / 量价类 / 流动性类因子市值衰减大；价值类 / 质量类因子市值衰减小

**这一步是 P3 → P4 的硬门禁**：报告生成 + 用户审阅通过后才进入 P4

### 10.3 P3 风险

| 风险 | 缓解 |
|------|------|
| 全因子 IC 数值变化引起下游决策逻辑误判 | 镜像保留 + summary 报告显示"中性化方式"列让用户感知 |
| `pd.read_json(market_cap_data.json.gz, ...)` 慢 | 加内存缓存（`@functools.lru_cache` on file mtime + size）；后续考虑切 parquet |
| 部分股票市值数据缺失（新股 / 退市） | 引擎统一 dropna，不让缺失污染回归；meta 记录 dropped 行数 |

---

## 11. P4 详细任务拆分（下游迁移 + 老字段下线）

P4 是清理期，目的是去除 P3 引入的兼容包袱。**前置条件**：P3 全因子跑批稳定运行 ≥ 用户指定周数（默认 2 周），下游报告字段无投诉。

### 11.1 P4 commit 链

| commit | 名称 | 文件 | 行数 | 验证 |
|--------|------|------|------|------|
| **P4.1** | `summary` 删除老字段兜底读取 | `summary/generate_factor_summary_report.py` | +5 / -10 | 全因子 JSON 都有 `ic_neutralized` 才能合并；老 JSON 报错提示重跑 |
| **P4.2** | `ic_result_builder` 移除老字段镜像写入 | `ic_result_builder.py` + 测试 | +5 / -30 | 新跑 JSON 不含 `ic_neutral_industry` |
| **P4.3** | 测试 + 文档清理 | 测试中老字段断言移除；PROJECT.md / MODULE.md / flow doc 同步 | +20 / -80 | ruff + pytest 全过；文档行号引用更新 |

总计 3 个 commit，约 +30/-120 行。

### 11.2 P4 触发条件

```
P3 完成 → 全因子重跑 → summary 报告稳定 N 周 → P4 触发
                                              ↓
                                        用户书面确认进入 P4
```

P4 启动前**必做**：

1. 确认所有 `factor_ic/result/ic_*.json` 都已经过 P3 重跑（含 `ic_neutralized` 字段）
2. `comprehensive_factor` / `backtest` 等下游若开始读中性化 IC，必须读 `ic_neutralized`
3. 用户审阅 P3.4 对比报告，决策是否保留 `["industry", "log_market_cap"]` 默认或退回 `["industry"]`

---

## 12. 测试策略

### 12.1 测试金字塔

```
                    ┌──────────────────────┐
                    │ E2E 全因子快照对比     │  P1.6 / P3.4
                    │ (人工审核数值)        │
                    └──────────────────────┘
              ┌────────────────────────────────┐
              │ 集成测试 test_neutralizer_*    │  P2.3 / P3.2
              │ (引擎 + Provider 组合)         │
              └────────────────────────────────┘
        ┌────────────────────────────────────────────┐
        │ 单元测试 test_<provider_name>.py             │  P1.2 / P2.1
        │ (各 Provider 五方法独立验证)                  │
        └────────────────────────────────────────────┘
  ┌─────────────────────────────────────────────────────┐
  │ 协议测试 test_control_provider_protocol.py            │  P1.1
  │ (Protocol runtime_checkable / 注册表 / 工厂)          │
  └─────────────────────────────────────────────────────┘
```

### 12.2 关键测试用例清单

| 层级 | 文件 | 用例数 | 用途 |
|------|------|--------|------|
| 协议 | `test_control_provider_protocol.py` | 5 | Protocol 校验、注册表、build_providers 工厂 |
| 单元（IndustryProvider） | `test_industry_provider.py` | 8 | load/preprocess/to_design/filter/get_meta 各方法 + 边界 |
| 单元（LogMarketCapProvider） | `test_log_market_cap_provider.py` | 10 | 同上 + winsorize / ln 变换 / cap≤0 护栏 |
| 引擎 | `test_neutralizer.py` | 12 | 单 control（与 legacy 逐位对比） / 双 control / 多重共线性 / 空 day_df / 全 NaN / min_stocks 边界 |
| 集成 | `test_factor_ic_runner_neutralize.py`（已存在，扩） | +6 | 联合中性化 end-to-end / spec 排除 / 镜像写入 / CLI 解析 |
| schema | `test_ic_result_builder_neutral.py`（已存在，扩） | +4 | `ic_neutralized` 必填字段 / 镜像规则 / 老字段过渡 |
| E2E 快照 | `test_p1_snapshot.py` | 1 | 全因子 IC 数值与 P0 基线 abs diff < 1e-9 |

### 12.3 测试数据 fixture

新增 `factor_ic/test_cases/fixtures/`:
- `mock_industry_map.json`（10 个资产 × 3 个行业 + "其他"）
- `mock_market_cap.json.gz`（10 个资产 × 5 个日期，含 cap=0 边界 + 极端大小盘）
- `mock_factor_data.json.gz`（同 schema，最小可用）

复用现有 `test_factor_ic_runner_neutralize.py` 的 fixture 模式。

### 12.4 P3.4 对比报告作为门禁

P3 → P4 必跑 `temporary/p3_compare_neutralization.py`，输出可视化对比表。用户审阅通过 = P3 稳定 = P4 触发条件。

---

## 13. 风险与回滚

### 13.1 关键风险登记

| # | 风险 | 触发场景 | 缓解 | 回滚 |
|---|------|---------|------|------|
| R1 | P1 重构后 IC 数值漂移 | 浮点累积误差、列顺序变化、groupby 行为差异 | P1.6 全因子快照测试 abs diff < 1e-9 | revert P1.4 切换 commit |
| R2 | LogMarketCapProvider 数据加载慢（10s+） | `pd.read_json` on 74MB | `@functools.lru_cache` on file mtime；P3 后切 parquet | 短期：临时缓存；长期：换格式 |
| R3 | 多重共线性导致回归矩阵奇异 | `drop_first=False` + 截距列同时存在 | §5.3 自动 drop_first 规则；引擎加 try/except + 降级 | 单 spec 失败时回退到无该 spec 的子集 |
| R4 | 部分股票市值数据缺失 | 新股 / 退市 / 数据接口异常 | 引擎统一 dropna；meta 记录 dropped 行数 | 不回滚，正常降级 |
| R5 | P3 改字段后下游报告字段错位 | summary 读 `ic_neutralized` 但部分老 JSON 仅有 `ic_neutral_industry` | 镜像写入 + 兜底读取（`get("ic_neutralized") or get("ic_neutral_industry")`） | revert P3.3 |
| R6 | P3 加市值后某些因子 IC 衰减异常大 | 该因子本就高度市值相关（如 size_factor） | P3.4 对比报告自动识别 + 加排除清单 `NEUTRALIZE_EXCLUDED["log_market_cap"]` | 排除问题因子 |
| R7 | 因子排除清单升级后语义错位 | `INDUSTRY_NEUTRALIZE_EXCLUDED`（set）→ `NEUTRALIZE_EXCLUDED["industry"]`（dict["industry"] = set） | P1.5 commit 单独验证 6 个行业聚合因子仍能阻断 | revert P1.5 |
| R8 | Protocol runtime_checkable 在某些 Python 版本兼容问题 | Python 3.8+ 才稳定 | 项目已 Python 3.10+，无问题 | 改为 ABC 抽象基类 |

### 13.2 跨期回滚矩阵

```
P0 ─── P1 ─── P2 ─── P3 ─── P4
       │      │      │      │
   revert  revert revert revert
   P1.x   P2.x   P3.x   P4.x
       │      │      │      │
   回 P0  回 P1  回 P2  回 P3
```

每期内部 commit 链可单独 revert（依赖前期 commit 稳定）。跨期回滚需先回退当前期所有 commits，再回到上一期末状态。

### 13.3 回滚演练（必做）

P1.4（切换调用）commit 落地后，立即手动验证：

```bash
git revert P1.4_HASH        # 临时回滚
pytest factor_ic/test_cases/  # 全过
git revert HEAD             # 恢复（取消 revert）
pytest factor_ic/test_cases/  # 全过
```

确保 revert / 重应用都干净。

---

## 14. 状态与验收

### 14.1 当前状态

| 字段 | 值 |
|------|-----|
| design.md 起草 | ✅ 完成（2026-06-18） |
| 入口审核 | ✅ 通过（2026-06-18） |
| **P1 实施** | ✅ **完成（2026-06-18）— 6 commits + 73 tests 通过** |
| **P2 实施** | ✅ **完成（2026-06-18）— 3 commits + 89 tests 通过；默认行为不变** |
| **P3 实施** | ✅ **完成（2026-06-18）— 5 commits + 423 tests 通过；默认联合中性化生效** |
| P4 启动 | 待用户决策启动时机 |

#### P1 已完成的 6 个 commits

| commit | 主题 | 行数 | 测试 |
|--------|------|------|------|
| `3be1763` | P1.1+P1.2 协议 + IndustryProvider + 注册表 | +497/-0 | 16 passed |
| `d0c96ab` | P1.3 neutralizer 引擎 + legacy 逐位对比 | +341/-0 | 7 passed |
| `f9a0652` | P1.4 runner 切到 neutralizer 引擎 | +12/-7 | RSI 端到端 abs diff = 0 |
| `67ea446` | P1.5 排除清单升级 dict 结构 + 别名兼容 | +129/-17 | 9 + 7 旧 passed |
| `d33c9f5` | P1.6 全因子 hard gate baseline + 34 因子快照 | +1173/-0 | 34 passed |
| `faa5d91` | P1.7 文档同步（flow doc + design.md 状态） | +52/-6 | 人工审核 |

#### P2 已完成的 3 个 commits

| commit | 主题 | 行数 | 测试 |
|--------|------|------|------|
| `616a859` | P2.1 LogMarketCapProvider 实现 | +340/-0 | 12 passed |
| `aa5f7cf` | P2.2 注册 provider + 排除清单 | +31/-0 | 42 passed |
| `1ce2b8d` | P2.3 联合中性化集成测试 | +120/-0 | 6 passed；P1/P2 集合 89 passed |

#### P3 已完成的 5 个 commits

| commit | 主题 | 行数 | 测试 |
|--------|------|------|------|
| `e9b75cd` | P3.1 `_resolve_neutralize_specs` helper + `DEFAULT_NEUTRALIZE_SPECS` | +319/-120 | 6 passed |
| `00fca06` | P3.2 builder `ic_neutralized` schema + legacy mirror | +180/-21 | 25 passed |
| `2ef86d0` | P3.3 summary 新字段优先读取 + 「中性化方式」列 | +107/-25 | 17 passed；131 集合 |
| `f91e142` | P3.1b runner 默认 `industry+log_market_cap` 联合中性化 | +64/-41 | 423 passed, 66 skipped |
| `<本 commit>` | P3.4 真实数据衰减对比报告 + design.md 状态 | +约 200 | 34 因子报告生成 |

#### P3.4 衰减对比报告发现 (2026-06-18)

全因子跑 `["industry", "log_market_cap"]` vs P0/P1 `["industry"]`，对比 decay_rate：

- **3/34 因子增量衰减 > 10%**（市值中性化必要）：
  - `tail_volume_acceleration_1d`: delta_decay=23.9%（ind=-44.2% → ind+cap=-20.2%，inverse 减弱）
  - `tail_price_slope_1d`: delta_decay=12.4%（ind=30.5% → ind+cap=42.9%，市值溢价显著）
  - `tail_price_volume_intensity_1d`: delta_decay=11.8%（ind=32.2% → ind+cap=44.0%，市值溢价显著）
- **31/34 因子增量衰减 ≤ 10%**（市值中性化影响小）
- `return_3d_1d` 因使用 `custom_factor_calculation`（complex 因子），脚本用 `run_simple_factor_ic` 未覆盖，combined IC 缺失（1/34，不影响结论）
- 8 个行业聚合因子（`industry_*` / `capital_flow_*`）在排除清单中被 industry 弹出，仅跑 `log_market_cap`

报告文件: `temporary/p3_decay_comparison.txt` + `temporary/p3_decay_comparison.json`

#### P1 关键交付物

- 新模块: `factor_ic/common/control_providers/{base,industry,__init__}.py` + `factor_ic/common/neutralizer.py`
- 新测试: `test_control_providers.py` (16) + `test_neutralizer_parity.py` (7) + `test_neutralize_excluded_schema.py` (9) + `test_p1_baseline_snapshot.py` (34)
- 新 baseline: `factor_ic/test_cases/snapshots/p1_baseline_ic.json`（34 因子，13 KB）
- P1.7 文档同步: `factor_ic/docs/industry_neutralization_flow.md` 升级 v1.1（P1 重构变更摘要）

#### P1 验收硬证据

- 端到端 RSI 因子 P0 vs P1: 10 字段 + 509 个 ic_values + 509 个日期 abs diff = 0
- 全因子 P1.6 快照: 34/34 通过（含 26 enabled + 8 skipped）
- 排除清单别名兼容: 现有 `test_factor_ic_runner_neutralize.py` 7 测试 0 修改通过

### 14.2 设计审核 checklist（用户审阅项）

- [ ] **架构**: 三层分离（调度/引擎/Provider）是否清晰，是否预留足够扩展点（Beta / 波动率 / 换手率 Provider 能在不动引擎的前提下加入）
- [ ] **协议**: ControlProvider 五个方法（load/preprocess/to_design/filter/get_meta）是否完整，是否漏掉常见中性化场景
- [ ] **联合中性化**: 一次多元回归（Barra 标准）vs 串行残差 vs 独立路径——选 A 是否合理
- [ ] **多重共线性**: §5.3 的 `drop_first` + `fit_intercept` 自动决策是否覆盖全部组合
- [ ] **向后兼容**: P1 行为不变 + P3 镜像 + P4 删字段的演进路径是否可接受
- [ ] **市值字段**: 用 `circ_market_cap` (流通) 而非 `total_market_cap` (总值) 是否符合预期
- [ ] **Winsorize**: (0.01, 0.99) 截面 winsorize 是否合适（vs 不 winsorize / vs MAD 去极值）
- [ ] **测试粒度**: 协议→单元→集成→E2E 四层 + 全因子快照测试是否够
- [ ] **commit 节奏**: P1 7 个 commit / P2 3 个 / P3 4 个 / P4 3 个，共 17 个 commit 是否过细或过粗

### 14.3 P1 启动前必做（审核通过后）

1. 用户确认 design.md 通过
2. 跑当前代码，capture P0 基线快照（`factor_ic/test_cases/snapshots/p0_baseline_ic.json`）
3. 创建 P1 工作分支（或继续 master 小步提交）
4. 按 P1.1 → P1.7 顺序执行，每个 commit 独立 ruff + pytest

### 14.4 验收标准

每期 PR/commit 链交付时，用户验收下列 4 项：

| 项 | 检查方法 |
|----|----------|
| 1 | `ruff check . && ruff format --check .` 全过 |
| 2 | `pytest factor_ic/ -v` 全过（含新加用例） |
| 3 | 文档同步：design.md §14.1 状态更新；流程文档 + MODULE.md + PROJECT.md 行号引用对齐 |
| 4 | commit message 引用规范行号（如 "遵循 PROJECT.md 规则 #5（行 35-37）"） |

---

**通过即可进入 Execute（P1.1）。**
